from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from nbadb.core.config import NbaDbSettings, get_settings
from nbadb.core.endpoint_coverage import (
    _ENDPOINT_ALIASES,
    _LIVE_SURFACE_ALIASES,
    _MODEL_EXCLUDED_STAGING_KEYS,
    _MODEL_EXCLUDED_STATS_ENDPOINTS,
    _STATIC_SURFACE_ALIASES,
    EndpointCoverageGenerator,
    _runtime_class_to_surface_name,
)
from nbadb.core.types import validate_sql_identifier
from nbadb.docs_gen.lineage import LineageGenerator
from nbadb.extract.registry import registry
from nbadb.orchestrate.discovery import EntityDiscovery
from nbadb.orchestrate.extractor_runner import _sync_extract, _sync_extract_all
from nbadb.orchestrate.seasons import current_season, season_string
from nbadb.orchestrate.staging_map import STAGING_MAP, StagingEntry
from nbadb.orchestrate.transformers import discover_all_transformers
from nbadb.schemas.registry import _star_schema_registry, get_input_schema, get_output_schema
from nbadb.transform.pipeline import TransformPipeline

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT_DIR = Path("artifacts/model-audit")
_PROBLEM_DECISIONS = {"runtime_gap", "source_gap", "schema_gap", "validation_gap"}


class AuditMode(StrEnum):
    INVENTORY = "inventory"
    PROBE = "probe"
    BUILD = "build"
    FULL = "full"


class AuditStrictness(StrEnum):
    CONSISTENCY = "consistency"
    NO_REGRESSIONS = "no-regressions"
    ZERO_GAPS = "zero-gaps"


class AuditDecision(StrEnum):
    MODELED = "modeled"
    EXCLUDED = "excluded"
    DEPRECATED = "deprecated"
    TEMPORALLY_UNAVAILABLE = "temporally_unavailable"
    RUNTIME_GAP = "runtime_gap"
    SOURCE_GAP = "source_gap"
    SCHEMA_GAP = "schema_gap"
    VALIDATION_GAP = "validation_gap"


class ColumnOrigin(StrEnum):
    SOURCE = "source"
    DERIVED = "derived"
    SURROGATE = "surrogate"
    LITERAL = "literal"
    FOREIGN_KEY = "foreign_key"
    AUDIT = "audit"


@dataclass(slots=True)
class AuditFailureError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class AuditRecord:
    layer: str
    key: str
    decision: str
    decision_reason: str
    issues: list[str] = field(default_factory=list)
    source_kind: str | None = None
    endpoint_name: str | None = None
    runtime_surface: str | None = None
    result_set_index: int | None = None
    staging_key: str | None = None
    param_pattern: str | None = None
    output_table: str | None = None
    column_name: str | None = None
    origin: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProbeRequest:
    key: str
    source_kind: str
    endpoint_name: str
    result_set_index: int | None
    staging_key: str | None
    params: dict[str, Any]
    probe_context: str
    use_multi: bool


@dataclass(slots=True)
class ProbeExecution:
    record: AuditRecord
    dataframe: pl.DataFrame | None = None


@dataclass(slots=True)
class _ExtractorCatalog:
    extractor_classes: list[Any]
    extractor_by_endpoint: dict[str, Any]
    extractor_by_canonical_endpoint: dict[str, Any]
    extractor_categories: Counter[str]

    def resolve(self, endpoint_name: str) -> Any | None:
        extractor_cls = self.extractor_by_endpoint.get(endpoint_name)
        if extractor_cls is not None:
            return extractor_cls
        canonical_endpoint = _ENDPOINT_ALIASES.get(endpoint_name, endpoint_name)
        return self.extractor_by_canonical_endpoint.get(canonical_endpoint)


@dataclass(slots=True)
class _TransformCatalog:
    transformers: list[Any]
    runtime_transform_outputs: list[str]
    runtime_outputs_set: set[str]
    transform_outputs_by_staging: dict[str, set[str]]
    transform_dependencies: dict[str, list[str]]
    unresolved_dependencies: dict[str, list[str]]
    legacy_outputs: set[str]
    legacy_runtime_only_outputs: list[str]


@dataclass(slots=True)
class _InventoryContext:
    extractors: _ExtractorCatalog
    runtime_classes: list[str]
    runtime_version: str
    runtime_static_surfaces: set[str]
    runtime_live_surfaces: set[str]
    extractor_map: dict[str, Any]
    static_extractors: set[str]
    live_extractors: set[str]
    staging_entries_by_endpoint: dict[str, list[StagingEntry]]
    runtime_stats_surfaces: set[str]
    runtime_stats_surface_rows: list[tuple[str, str, str]]
    transforms: _TransformCatalog
    star_schemas: dict[str, Any]
    star_schema_tables: set[str]
    lineage: dict[str, Any]
    discovery_issues: list[dict[str, Any]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dumps(payload), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _table_family(table_name: str) -> str:
    if table_name.startswith("dim_"):
        return "dimension"
    if table_name.startswith("fact_"):
        return "fact"
    if table_name.startswith("bridge_"):
        return "bridge"
    if table_name.startswith("agg_"):
        return "aggregate"
    if table_name.startswith("analytics_"):
        return "analytics"
    return "other"


def _hash_columns(df: pl.DataFrame) -> str:
    descriptors = [f"{name}:{dtype}" for name, dtype in df.schema.items()]
    return hashlib.sha256(",".join(sorted(descriptors)).encode("utf-8")).hexdigest()[:16]


def _problem_key(record: AuditRecord) -> str:
    return f"{record.layer}:{record.key}:{record.decision}"


def _is_problem(record: AuditRecord) -> bool:
    return record.decision in _PROBLEM_DECISIONS


def _summarize_records(
    records: list[AuditRecord],
    *,
    inventory_meta: dict[str, Any],
    discovery_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    by_layer: dict[str, Counter[str]] = defaultdict(Counter)
    by_decision = Counter[str]()
    issue_breakdown = Counter[str]()
    problem_keys: list[str] = []

    for record in records:
        by_layer[record.layer][record.decision] += 1
        by_decision[record.decision] += 1
        issue_breakdown.update(record.issues)
        if _is_problem(record):
            problem_keys.append(_problem_key(record))

    return {
        "generated_at": _now_iso(),
        "inventory": inventory_meta,
        "discovery_issue_count": len(discovery_issues),
        "discovery_issues": discovery_issues,
        "record_count": len(records),
        "decision_breakdown": dict(sorted(by_decision.items())),
        "layer_breakdown": {
            layer: dict(sorted(counter.items())) for layer, counter in sorted(by_layer.items())
        },
        "issue_breakdown": dict(sorted(issue_breakdown.items())),
        "problem_count": len(problem_keys),
        "problem_keys": sorted(problem_keys),
    }


def _classify_column_origin(
    *,
    column_name: str,
    metadata: dict[str, Any],
) -> str | None:
    source = str(metadata.get("source", "") or "")
    fk_ref = str(metadata.get("fk_ref", "") or "")

    if column_name.endswith("_sk"):
        return ColumnOrigin.SURROGATE.value
    if fk_ref:
        return ColumnOrigin.FOREIGN_KEY.value
    if source.startswith("audit."):
        return ColumnOrigin.AUDIT.value
    if source.startswith("literal."):
        return ColumnOrigin.LITERAL.value
    if source.startswith("derived."):
        if column_name.endswith("_sk") or source.endswith("ROW_NUMBER"):
            return ColumnOrigin.SURROGATE.value
        return ColumnOrigin.DERIVED.value
    if source:
        return ColumnOrigin.SOURCE.value
    return None


def _normalize_source_kind(category: str | None) -> str:
    if category in {"static", "live"}:
        return category
    return "stats"


def _load_baseline(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "summary" in payload:
        return payload["summary"]
    return payload


def compare_baseline(
    current_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
) -> dict[str, Any]:
    current_problem_keys = set(current_summary.get("problem_keys", []))
    baseline_problem_keys = set(baseline_summary.get("problem_keys", []))

    current_decisions = Counter(current_summary.get("decision_breakdown", {}))
    baseline_decisions = Counter(baseline_summary.get("decision_breakdown", {}))

    increased_problem_counts = {
        decision: current_decisions[decision] - baseline_decisions[decision]
        for decision in sorted(_PROBLEM_DECISIONS)
        if current_decisions[decision] > baseline_decisions[decision]
    }

    new_problem_keys = sorted(current_problem_keys - baseline_problem_keys)
    resolved_problem_keys = sorted(baseline_problem_keys - current_problem_keys)

    return {
        "baseline_generated_at": baseline_summary.get("generated_at"),
        "current_problem_count": len(current_problem_keys),
        "baseline_problem_count": len(baseline_problem_keys),
        "new_problem_keys": new_problem_keys,
        "resolved_problem_keys": resolved_problem_keys,
        "increased_problem_counts": increased_problem_counts,
        "regression_detected": bool(new_problem_keys or increased_problem_counts),
    }


class ModelAuditEngine:
    def __init__(
        self,
        *,
        project_root: Path | None = None,
        settings: NbaDbSettings | None = None,
    ) -> None:
        self.project_root = project_root.resolve() if project_root is not None else Path.cwd()
        self.settings = settings if settings is not None else get_settings()
        self._coverage = EndpointCoverageGenerator(project_root=self.project_root)

    def _discover_extractors(self) -> _ExtractorCatalog:
        registry.discover()
        extractor_classes = registry.get_all()
        extractor_by_endpoint = {cls.endpoint_name: cls for cls in extractor_classes}
        extractor_by_canonical_endpoint: dict[str, Any] = {}
        for cls in extractor_classes:
            canonical_endpoint = _ENDPOINT_ALIASES.get(cls.endpoint_name, cls.endpoint_name)
            extractor_by_canonical_endpoint.setdefault(canonical_endpoint, cls)
        return _ExtractorCatalog(
            extractor_classes=extractor_classes,
            extractor_by_endpoint=extractor_by_endpoint,
            extractor_by_canonical_endpoint=extractor_by_canonical_endpoint,
            extractor_categories=Counter(cls.category for cls in extractor_classes),
        )

    def _build_staging_entries_by_endpoint(self) -> dict[str, list[StagingEntry]]:
        staging_entries_by_endpoint: dict[str, list[StagingEntry]] = defaultdict(list)
        for entry in STAGING_MAP:
            canonical_endpoint = _ENDPOINT_ALIASES.get(entry.endpoint_name, entry.endpoint_name)
            staging_entries_by_endpoint[canonical_endpoint].append(entry)
        return staging_entries_by_endpoint

    def _discover_transform_catalog(self) -> _TransformCatalog:
        transformers = discover_all_transformers()
        runtime_transform_outputs = sorted(
            {transformer.output_table for transformer in transformers}
        )
        runtime_outputs_set = set(runtime_transform_outputs)

        transform_outputs_by_staging: dict[str, set[str]] = defaultdict(set)
        transform_dependencies: dict[str, list[str]] = {}
        unresolved_dependencies: dict[str, list[str]] = {}
        for transformer in transformers:
            transform_dependencies[transformer.output_table] = sorted(transformer.depends_on)
            unresolved_dependencies[transformer.output_table] = sorted(
                dep
                for dep in transformer.depends_on
                if dep not in runtime_outputs_set and not dep.startswith(("stg_", "raw_"))
            )
            for dependency in transformer.depends_on:
                if dependency.startswith("stg_"):
                    transform_outputs_by_staging[dependency].add(transformer.output_table)

        _, legacy_outputs = self._coverage._transform_catalog()
        return _TransformCatalog(
            transformers=transformers,
            runtime_transform_outputs=runtime_transform_outputs,
            runtime_outputs_set=runtime_outputs_set,
            transform_outputs_by_staging=transform_outputs_by_staging,
            transform_dependencies=transform_dependencies,
            unresolved_dependencies=unresolved_dependencies,
            legacy_outputs=set(legacy_outputs),
            legacy_runtime_only_outputs=sorted(runtime_outputs_set - legacy_outputs),
        )

    def _build_inventory_discovery_issues(
        self,
        transforms: _TransformCatalog,
    ) -> list[dict[str, Any]]:
        discovery_issues: list[dict[str, Any]] = []
        if transforms.legacy_runtime_only_outputs:
            discovery_issues.append(
                {
                    "key": "legacy_transform_catalog_mismatch",
                    "message": (
                        "runtime transformer discovery includes outputs missing from the "
                        "legacy static transform catalog"
                    ),
                    "details": {
                        "runtime_transform_output_count": len(transforms.runtime_outputs_set),
                        "legacy_transform_output_count": len(transforms.legacy_outputs),
                        "runtime_only_outputs": transforms.legacy_runtime_only_outputs,
                    },
                }
            )
        return discovery_issues

    def _discover_inventory_context(
        self,
        extractors: _ExtractorCatalog,
    ) -> _InventoryContext:
        runtime_classes, runtime_version = self._coverage._discover_runtime_endpoint_classes()
        runtime_static_surfaces = self._coverage._discover_runtime_static_surfaces()
        runtime_live_surfaces = self._coverage._discover_runtime_live_endpoint_classes()
        extractor_map = self._coverage._extractor_endpoint_map()
        static_extractors = self._coverage._static_extractor_surfaces()
        live_extractors = self._coverage._live_extractor_surfaces()
        staging_entries_by_endpoint = self._build_staging_entries_by_endpoint()

        known_stats_surfaces = set(staging_entries_by_endpoint) | set(extractor_map)
        runtime_stats_surfaces: set[str] = set()
        runtime_stats_surface_rows: list[tuple[str, str, str]] = []
        for class_name in runtime_classes:
            runtime_surface = _runtime_class_to_surface_name(class_name)
            canonical_surface = _runtime_class_to_surface_name(class_name, known_stats_surfaces)
            runtime_stats_surfaces.add(canonical_surface)
            runtime_stats_surface_rows.append((class_name, runtime_surface, canonical_surface))

        transforms = self._discover_transform_catalog()
        star_schemas = _star_schema_registry()
        lineage = LineageGenerator().generate_dict()
        discovery_issues = self._build_inventory_discovery_issues(transforms)

        return _InventoryContext(
            extractors=extractors,
            runtime_classes=sorted(runtime_classes),
            runtime_version=runtime_version,
            runtime_static_surfaces=runtime_static_surfaces,
            runtime_live_surfaces=runtime_live_surfaces,
            extractor_map=extractor_map,
            static_extractors=static_extractors,
            live_extractors=live_extractors,
            staging_entries_by_endpoint=staging_entries_by_endpoint,
            runtime_stats_surfaces=runtime_stats_surfaces,
            runtime_stats_surface_rows=runtime_stats_surface_rows,
            transforms=transforms,
            star_schemas=star_schemas,
            star_schema_tables=set(star_schemas),
            lineage=lineage,
            discovery_issues=discovery_issues,
        )

    def _stats_surface_decision(
        self,
        *,
        canonical_surface: str,
        runtime_present: bool,
        extractor_present: bool,
        entries: list[StagingEntry],
        inventory: _InventoryContext,
    ) -> tuple[str, str, list[str], list[str]]:
        transform_outputs = sorted(
            {
                output
                for entry in entries
                for output in inventory.transforms.transform_outputs_by_staging.get(
                    entry.staging_key, set()
                )
            }
        )
        exclusion_reason = _MODEL_EXCLUDED_STATS_ENDPOINTS.get(canonical_surface)
        issues: list[str] = []

        if not runtime_present and extractor_present:
            decision = AuditDecision.RUNTIME_GAP.value
            reason = "Extractor exists for a stats surface not present in installed nba_api."
            issues.append("runtime_surface_missing")
        elif runtime_present and not extractor_present and not entries:
            decision = AuditDecision.SOURCE_GAP.value
            reason = "Runtime stats surface is not represented by an extractor or staging map."
            issues.append("extractor_missing")
        elif entries and not extractor_present:
            decision = AuditDecision.SOURCE_GAP.value
            reason = "Staged stats surface is missing an extractor implementation."
            issues.append("extractor_missing")
        elif exclusion_reason is not None:
            decision = AuditDecision.EXCLUDED.value
            reason = exclusion_reason
        elif transform_outputs:
            decision = AuditDecision.MODELED.value
            reason = "Stats surface reaches at least one runtime-discovered model output."
        elif entries:
            decision = AuditDecision.VALIDATION_GAP.value
            reason = "Stats surface is staged but has no downstream model ownership decision."
            issues.append("unowned_surface")
        else:
            decision = AuditDecision.SOURCE_GAP.value
            reason = "Runtime stats surface is not mapped into staging."
            issues.append("staging_missing")

        return decision, reason, issues, transform_outputs

    def _audit_runtime_surfaces(self, inventory: _InventoryContext) -> list[AuditRecord]:
        runtime_surface_records: list[AuditRecord] = []

        for class_name, runtime_surface, canonical_surface in sorted(
            inventory.runtime_stats_surface_rows,
            key=lambda item: item[1],
        ):
            entries = inventory.staging_entries_by_endpoint.get(canonical_surface, [])
            extractor_present = canonical_surface in inventory.extractor_map
            decision, reason, issues, transform_outputs = self._stats_surface_decision(
                canonical_surface=canonical_surface,
                runtime_present=True,
                extractor_present=extractor_present,
                entries=entries,
                inventory=inventory,
            )
            runtime_surface_records.append(
                AuditRecord(
                    layer="RuntimeSurface",
                    key=f"stats:{runtime_surface}",
                    decision=decision,
                    decision_reason=reason,
                    issues=issues,
                    source_kind="stats",
                    endpoint_name=canonical_surface,
                    runtime_surface=runtime_surface,
                    details={
                        "runtime_class_name": class_name,
                        "canonical_surface": canonical_surface,
                        "is_runtime_alias": runtime_surface != canonical_surface,
                        "extractor_present": extractor_present,
                        "runtime_present": True,
                        "staging_entry_count": len(entries),
                        "transform_outputs": transform_outputs,
                    },
                )
            )

        non_runtime = (
            set(inventory.extractor_map) | set(inventory.staging_entries_by_endpoint)
        ) - inventory.runtime_stats_surfaces
        for surface_name in sorted(non_runtime):
            entries = inventory.staging_entries_by_endpoint.get(surface_name, [])
            extractor_present = surface_name in inventory.extractor_map
            decision, reason, issues, transform_outputs = self._stats_surface_decision(
                canonical_surface=surface_name,
                runtime_present=False,
                extractor_present=extractor_present,
                entries=entries,
                inventory=inventory,
            )
            runtime_surface_records.append(
                AuditRecord(
                    layer="RuntimeSurface",
                    key=f"stats:{surface_name}",
                    decision=decision,
                    decision_reason=reason,
                    issues=issues,
                    source_kind="stats",
                    endpoint_name=surface_name,
                    runtime_surface=surface_name,
                    details={
                        "canonical_surface": surface_name,
                        "is_runtime_alias": False,
                        "extractor_present": extractor_present,
                        "runtime_present": False,
                        "staging_entry_count": len(entries),
                        "transform_outputs": transform_outputs,
                    },
                )
            )

        for surface_name in sorted(inventory.runtime_static_surfaces | inventory.static_extractors):
            extractor_present = surface_name in inventory.static_extractors
            runtime_present = surface_name in inventory.runtime_static_surfaces
            endpoint_name = next(
                (key for key, value in _STATIC_SURFACE_ALIASES.items() if value == surface_name),
                surface_name,
            )
            decision = (
                AuditDecision.MODELED.value
                if extractor_present and runtime_present
                else AuditDecision.SOURCE_GAP.value
            )
            runtime_surface_records.append(
                AuditRecord(
                    layer="RuntimeSurface",
                    key=f"static:{surface_name}",
                    decision=decision,
                    decision_reason=(
                        "Static surface is represented by a runtime module and extractor."
                        if decision == AuditDecision.MODELED.value
                        else "Static surface is missing either runtime or extractor coverage."
                    ),
                    issues=(
                        [] if decision == AuditDecision.MODELED.value else ["static_surface_gap"]
                    ),
                    source_kind="static",
                    endpoint_name=endpoint_name,
                    runtime_surface=surface_name,
                    details={
                        "extractor_present": extractor_present,
                        "runtime_present": runtime_present,
                    },
                )
            )

        for surface_name in sorted(inventory.runtime_live_surfaces | inventory.live_extractors):
            extractor_present = surface_name in inventory.live_extractors
            runtime_present = surface_name in inventory.runtime_live_surfaces
            endpoint_name = next(
                (key for key, value in _LIVE_SURFACE_ALIASES.items() if value == surface_name),
                surface_name,
            )
            decision = (
                AuditDecision.MODELED.value
                if extractor_present and runtime_present
                else AuditDecision.SOURCE_GAP.value
            )
            runtime_surface_records.append(
                AuditRecord(
                    layer="RuntimeSurface",
                    key=f"live:{surface_name}",
                    decision=decision,
                    decision_reason=(
                        "Live surface is represented by a runtime module and extractor."
                        if decision == AuditDecision.MODELED.value
                        else "Live surface is missing either runtime or extractor coverage."
                    ),
                    issues=[] if decision == AuditDecision.MODELED.value else ["live_surface_gap"],
                    source_kind="live",
                    endpoint_name=endpoint_name,
                    runtime_surface=surface_name,
                    details={
                        "extractor_present": extractor_present,
                        "runtime_present": runtime_present,
                    },
                )
            )

        return runtime_surface_records

    def _audit_staging_surfaces(self, inventory: _InventoryContext) -> list[AuditRecord]:
        staging_surface_records: list[AuditRecord] = []

        def _sort_key(item: StagingEntry) -> tuple[str, int]:
            return (item.staging_key, item.result_set_index)

        for entry in sorted(STAGING_MAP, key=_sort_key):
            canonical_endpoint = _ENDPOINT_ALIASES.get(entry.endpoint_name, entry.endpoint_name)
            extractor_cls = inventory.extractors.resolve(entry.endpoint_name)
            extractor_present = extractor_cls is not None
            source_kind = _normalize_source_kind(
                extractor_cls.category if extractor_cls is not None else None
            )
            if source_kind == "static":
                runtime_present = (
                    _STATIC_SURFACE_ALIASES.get(entry.endpoint_name, entry.endpoint_name)
                    in inventory.runtime_static_surfaces
                )
            elif source_kind == "live":
                runtime_present = (
                    _LIVE_SURFACE_ALIASES.get(entry.endpoint_name, entry.endpoint_name)
                    in inventory.runtime_live_surfaces
                )
            else:
                runtime_present = canonical_endpoint in inventory.runtime_stats_surfaces

            transform_outputs = sorted(
                inventory.transforms.transform_outputs_by_staging.get(entry.staging_key, set())
            )
            input_schema = get_input_schema(entry.staging_key)
            exclusion_reason = _MODEL_EXCLUDED_STAGING_KEYS.get(entry.staging_key)
            if exclusion_reason is None:
                exclusion_reason = _MODEL_EXCLUDED_STATS_ENDPOINTS.get(canonical_endpoint)

            issues: list[str] = []
            is_deprecated = (
                entry.deprecated_after is not None
                and date.today() > date.fromisoformat(entry.deprecated_after)
            )
            if is_deprecated:
                decision = AuditDecision.DEPRECATED.value
                reason = (
                    f"Entry is deprecated after {entry.deprecated_after}"
                    " and is skipped by the extractor runner."
                )
            elif not extractor_present:
                decision = AuditDecision.SOURCE_GAP.value
                reason = "No extractor is registered for this staging entry."
                issues.append("extractor_missing")
            elif not runtime_present and source_kind == "stats":
                decision = AuditDecision.RUNTIME_GAP.value
                reason = (
                    "Stats staging entry references a runtime surface"
                    " absent from installed nba_api."
                )
                issues.append("runtime_surface_missing")
            elif exclusion_reason is not None:
                decision = AuditDecision.EXCLUDED.value
                reason = exclusion_reason
            elif transform_outputs and input_schema is not None:
                decision = AuditDecision.MODELED.value
                reason = (
                    "Staging entry is owned by at least one runtime"
                    " transform and has input schema coverage."
                )
            elif transform_outputs and input_schema is None:
                decision = AuditDecision.VALIDATION_GAP.value
                reason = "Staging entry is modeled but lacks input schema coverage."
                issues.append("input_schema_missing")
            else:
                decision = AuditDecision.VALIDATION_GAP.value
                reason = "Staging entry has no downstream model ownership decision."
                issues.append("unowned_staging")

            staging_surface_records.append(
                AuditRecord(
                    layer="StagingSurface",
                    key=entry.staging_key,
                    decision=decision,
                    decision_reason=reason,
                    issues=issues,
                    source_kind=source_kind,
                    endpoint_name=entry.endpoint_name,
                    runtime_surface=canonical_endpoint,
                    result_set_index=entry.result_set_index,
                    staging_key=entry.staging_key,
                    param_pattern=entry.param_pattern,
                    details={
                        "min_season": entry.min_season,
                        "deprecated_after": entry.deprecated_after,
                        "use_multi": entry.use_multi,
                        "transform_outputs": transform_outputs,
                        "input_schema_present": input_schema is not None,
                        "live_probe_status": "not_run",
                        "extractor_category": (
                            None if extractor_cls is None else extractor_cls.category
                        ),
                    },
                )
            )

        return staging_surface_records

    def _audit_model_surfaces(self, inventory: _InventoryContext) -> list[AuditRecord]:
        model_surface_records: list[AuditRecord] = []
        for output_table in inventory.transforms.runtime_transform_outputs:
            transformer = next(
                transformer
                for transformer in inventory.transforms.transformers
                if transformer.output_table == output_table
            )
            schema_cls = get_output_schema(output_table)
            staging_dependencies = sorted(
                dep for dep in transformer.depends_on if dep.startswith("stg_")
            )
            issue_list = list(inventory.transforms.unresolved_dependencies.get(output_table, []))
            issues = ["unresolved_dependency"] * len(issue_list) if issue_list else []

            if schema_cls is None:
                decision = AuditDecision.SCHEMA_GAP.value
                reason = "Runtime transform output is missing a registered star schema."
                issues.append("output_schema_missing")
            elif issue_list:
                decision = AuditDecision.VALIDATION_GAP.value
                reason = (
                    "Runtime transform has unresolved dependencies"
                    " outside staging/raw/model outputs."
                )
            else:
                decision = AuditDecision.MODELED.value
                reason = "Runtime transform output has a registered star schema."

            lineage_entry = inventory.lineage.get(output_table, {})
            model_surface_records.append(
                AuditRecord(
                    layer="ModelSurface",
                    key=output_table,
                    decision=decision,
                    decision_reason=reason,
                    issues=issues,
                    output_table=output_table,
                    details={
                        "table_family": _table_family(output_table),
                        "depends_on": inventory.transforms.transform_dependencies.get(
                            output_table, []
                        ),
                        "staging_dependencies": staging_dependencies,
                        "output_schema_present": schema_cls is not None,
                        "schema_lineage_present": "schema_lineage" in lineage_entry,
                        "sql_lineage_present": "sql_lineage" in lineage_entry,
                    },
                )
            )

        return model_surface_records

    def _audit_column_contracts(self, inventory: _InventoryContext) -> list[AuditRecord]:
        column_contract_records: list[AuditRecord] = []
        for output_table in inventory.transforms.runtime_transform_outputs:
            schema_cls = get_output_schema(output_table)
            if schema_cls is None:
                continue

            schema = schema_cls.to_schema()
            for column_name, column in sorted(schema.columns.items()):
                metadata = dict(column.metadata or {})
                origin = _classify_column_origin(column_name=column_name, metadata=metadata)
                column_issues: list[str] = []
                if origin is None:
                    decision = AuditDecision.VALIDATION_GAP.value
                    reason = "Modeled output column is missing explicit origin metadata."
                    column_issues.append("column_origin_missing")
                else:
                    decision = AuditDecision.MODELED.value
                    reason = f"Column origin is classified as {origin}."

                column_contract_records.append(
                    AuditRecord(
                        layer="ColumnContract",
                        key=f"{output_table}.{column_name}",
                        decision=decision,
                        decision_reason=reason,
                        issues=column_issues,
                        output_table=output_table,
                        column_name=column_name,
                        origin=origin,
                        details={
                            "nullable": column.nullable,
                            "source": metadata.get("source"),
                            "fk_ref": metadata.get("fk_ref"),
                            "description": metadata.get("description"),
                        },
                    )
                )
        return column_contract_records

    def _build_inventory_meta(self, inventory: _InventoryContext) -> dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "runtime_version": inventory.runtime_version,
            "runtime_stats_surface_count": len(inventory.runtime_classes),
            "runtime_stats_canonical_surface_count": len(inventory.runtime_stats_surfaces),
            "runtime_static_surface_count": len(inventory.runtime_static_surfaces),
            "runtime_live_surface_count": len(inventory.runtime_live_surfaces),
            "extractor_count": registry.count,
            "extractor_category_breakdown": dict(
                sorted(inventory.extractors.extractor_categories.items())
            ),
            "staging_entry_count": len(STAGING_MAP),
            "runtime_transform_output_count": len(inventory.transforms.runtime_outputs_set),
            "legacy_transform_output_count": len(inventory.transforms.legacy_outputs),
            "star_schema_count": len(inventory.star_schema_tables),
            "legacy_runtime_only_outputs": inventory.transforms.legacy_runtime_only_outputs,
        }

    def _build_inventory_sections(self) -> dict[str, Any]:
        extractors = self._discover_extractors()
        inventory = self._discover_inventory_context(extractors)
        runtime_surface_records = self._audit_runtime_surfaces(inventory)
        staging_surface_records = self._audit_staging_surfaces(inventory)
        model_surface_records = self._audit_model_surfaces(inventory)
        column_contract_records = self._audit_column_contracts(inventory)
        inventory_meta = self._build_inventory_meta(inventory)

        inventory_records = (
            runtime_surface_records
            + staging_surface_records
            + model_surface_records
            + column_contract_records
        )
        inventory_summary = _summarize_records(
            inventory_records,
            inventory_meta=inventory_meta,
            discovery_issues=inventory.discovery_issues,
        )

        return {
            "runtime_surfaces": runtime_surface_records,
            "staging_surfaces": staging_surface_records,
            "model_surfaces": model_surface_records,
            "column_contracts": column_contract_records,
            "records": inventory_records,
            "inventory_meta": inventory_meta,
            "discovery_issues": inventory.discovery_issues,
            "summary": inventory_summary,
        }

    async def _build_probe_requests(self) -> tuple[list[ProbeRequest], list[AuditRecord]]:
        extractors = self._discover_extractors()
        extractor_classes = extractors.extractor_classes

        discovery = EntityDiscovery(registry)

        current = current_season()
        current_regular_games, current_regular_log = await discovery.discover_game_ids(
            [current],
            season_types=["Regular Season"],
        )
        current_playoff_games, current_playoff_log = await discovery.discover_game_ids(
            [current],
            season_types=["Playoffs"],
        )
        current_regular_dates = await discovery.discover_game_dates(current_regular_log)
        current_playoff_dates = await discovery.discover_game_dates(current_playoff_log)
        current_players = await discovery.discover_player_ids(season=current)
        team_ids = await discovery.discover_team_ids()
        current_pts_params = await discovery.discover_player_team_season_params([current])

        season_game_cache: dict[tuple[str, str], tuple[list[str], list[str]]] = {
            (current, "Regular Season"): (current_regular_games, current_regular_dates),
            (current, "Playoffs"): (current_playoff_games, current_playoff_dates),
        }
        season_player_cache: dict[str, list[int]] = {current: current_players}
        pts_param_cache: dict[str, list[dict[str, int | str]]] = {current: current_pts_params}

        async def season_games(season: str, season_type: str) -> tuple[list[str], list[str]]:
            cache_key = (season, season_type)
            if cache_key not in season_game_cache:
                games, raw_df = await discovery.discover_game_ids(
                    [season], season_types=[season_type]
                )
                dates = await discovery.discover_game_dates(raw_df)
                season_game_cache[cache_key] = (games, dates)
            return season_game_cache[cache_key]

        async def season_players(season: str) -> list[int]:
            if season not in season_player_cache:
                season_player_cache[season] = await discovery.discover_all_player_ids(season=season)
            return season_player_cache[season]

        async def player_team_params(season: str) -> list[dict[str, int | str]]:
            if season not in pts_param_cache:
                pts_param_cache[season] = await discovery.discover_player_team_season_params(
                    [season]
                )
            return pts_param_cache[season]

        requests: list[ProbeRequest] = []
        synthetic_records: list[AuditRecord] = []
        staging_pattern_by_key = {entry.staging_key: entry.param_pattern for entry in STAGING_MAP}

        def _append_unavailable(
            *,
            key: str,
            source_kind: str,
            endpoint_name: str,
            staging_key: str | None,
            result_set_index: int | None,
            param_pattern: str | None,
            context: str,
            reason: str,
            params: dict[str, Any] | None = None,
        ) -> None:
            synthetic_records.append(
                AuditRecord(
                    layer="LiveProbe",
                    key=f"{key}:{context}",
                    decision=AuditDecision.TEMPORALLY_UNAVAILABLE.value,
                    decision_reason=reason,
                    issues=[],
                    source_kind=source_kind,
                    endpoint_name=endpoint_name,
                    staging_key=staging_key,
                    result_set_index=result_set_index,
                    param_pattern=param_pattern,
                    details={
                        "probe_context": context,
                        "params": params or {},
                    },
                )
            )

        for entry in sorted(
            STAGING_MAP,
            key=lambda item: (item.staging_key, item.result_set_index),
        ):
            extractor_cls = extractors.resolve(entry.endpoint_name)
            if extractor_cls is None:
                _append_unavailable(
                    key=entry.staging_key,
                    source_kind="stats",
                    endpoint_name=entry.endpoint_name,
                    staging_key=entry.staging_key,
                    result_set_index=entry.result_set_index,
                    param_pattern=entry.param_pattern,
                    context="no_extractor",
                    reason="No extractor is registered for this staging entry.",
                )
                continue

            source_kind = _normalize_source_kind(extractor_cls.category)
            contexts: list[tuple[str, dict[str, Any]]] = []
            earliest_year = entry.min_season or 1946
            earliest_season = season_string(earliest_year)

            if entry.param_pattern == "static":
                contexts.append(("static", {}))
            elif entry.param_pattern == "season":
                contexts.append(
                    (
                        "current_regular",
                        {"season": current, "season_type": "Regular Season"},
                    )
                )
                contexts.append(
                    (
                        "current_playoffs",
                        {"season": current, "season_type": "Playoffs"},
                    )
                )
                contexts.append(
                    (
                        "earliest_regular",
                        {"season": earliest_season, "season_type": "Regular Season"},
                    )
                )
                if entry.deprecated_after is not None:
                    cutoff_year = int(entry.deprecated_after[:4]) - 1
                    if cutoff_year >= earliest_year:
                        contexts.append(
                            (
                                "pre_cutoff_regular",
                                {
                                    "season": season_string(cutoff_year),
                                    "season_type": "Regular Season",
                                },
                            )
                        )
            elif entry.param_pattern == "game":
                current_game = current_regular_games[-1] if current_regular_games else None
                if current_game is not None:
                    contexts.append(("current_regular", {"game_id": current_game}))
                else:
                    _append_unavailable(
                        key=entry.staging_key,
                        source_kind=source_kind,
                        endpoint_name=entry.endpoint_name,
                        staging_key=entry.staging_key,
                        result_set_index=entry.result_set_index,
                        param_pattern=entry.param_pattern,
                        context="current_regular",
                        reason=(
                            "No current regular-season game_id was discoverable for live probing."
                        ),
                    )
                playoff_game = current_playoff_games[-1] if current_playoff_games else None
                if playoff_game is not None:
                    contexts.append(("current_playoffs", {"game_id": playoff_game}))
                earliest_games, _ = await season_games(earliest_season, "Regular Season")
                if earliest_games:
                    contexts.append(("earliest_regular", {"game_id": earliest_games[0]}))
            elif entry.param_pattern == "date":
                if current_regular_dates:
                    contexts.append(("current_regular", {"game_date": current_regular_dates[-1]}))
                else:
                    _append_unavailable(
                        key=entry.staging_key,
                        source_kind=source_kind,
                        endpoint_name=entry.endpoint_name,
                        staging_key=entry.staging_key,
                        result_set_index=entry.result_set_index,
                        param_pattern=entry.param_pattern,
                        context="current_regular",
                        reason=(
                            "No current regular-season game date was discoverable for live probing."
                        ),
                    )
                if current_playoff_dates:
                    contexts.append(("current_playoffs", {"game_date": current_playoff_dates[-1]}))
                _, earliest_dates = await season_games(earliest_season, "Regular Season")
                if earliest_dates:
                    contexts.append(("earliest_regular", {"game_date": earliest_dates[0]}))
            elif entry.param_pattern == "player":
                if current_players:
                    contexts.append(("current_regular", {"player_id": current_players[0]}))
                else:
                    _append_unavailable(
                        key=entry.staging_key,
                        source_kind=source_kind,
                        endpoint_name=entry.endpoint_name,
                        staging_key=entry.staging_key,
                        result_set_index=entry.result_set_index,
                        param_pattern=entry.param_pattern,
                        context="current_regular",
                        reason="No current player_id was discoverable for live probing.",
                    )
                earliest_players = await season_players(earliest_season)
                if earliest_players:
                    contexts.append(("earliest_regular", {"player_id": earliest_players[0]}))
            elif entry.param_pattern == "team":
                if team_ids:
                    contexts.append(("current_regular", {"team_id": team_ids[0]}))
                else:
                    _append_unavailable(
                        key=entry.staging_key,
                        source_kind=source_kind,
                        endpoint_name=entry.endpoint_name,
                        staging_key=entry.staging_key,
                        result_set_index=entry.result_set_index,
                        param_pattern=entry.param_pattern,
                        context="current_regular",
                        reason="No team_id was discoverable for live probing.",
                    )
            elif entry.param_pattern == "player_season":
                if current_players:
                    contexts.append(
                        (
                            "current_regular",
                            {"player_id": current_players[0], "season": current},
                        )
                    )
                earliest_players = await season_players(earliest_season)
                if earliest_players:
                    contexts.append(
                        (
                            "earliest_regular",
                            {"player_id": earliest_players[0], "season": earliest_season},
                        )
                    )
            elif entry.param_pattern == "team_season":
                if team_ids:
                    contexts.append(
                        (
                            "current_regular",
                            {"team_id": team_ids[0], "season": current},
                        )
                    )
                    contexts.append(
                        (
                            "earliest_regular",
                            {"team_id": team_ids[0], "season": earliest_season},
                        )
                    )
            elif entry.param_pattern == "player_team_season":
                if current_pts_params:
                    current_params = dict(current_pts_params[0])
                    contexts.append(("current_regular", current_params))
                earliest_pts_params = await player_team_params(earliest_season)
                if earliest_pts_params:
                    earliest_params = dict(earliest_pts_params[0])
                    contexts.append(("earliest_regular", earliest_params))

            seen: set[tuple[str, str]] = set()
            for context_name, params in contexts:
                params_json = json.dumps(params, sort_keys=True)
                dedupe_key = (context_name, params_json)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                requests.append(
                    ProbeRequest(
                        key=entry.staging_key,
                        source_kind=source_kind,
                        endpoint_name=entry.endpoint_name,
                        result_set_index=entry.result_set_index,
                        staging_key=entry.staging_key,
                        params=params,
                        probe_context=context_name,
                        use_multi=entry.use_multi,
                    )
                )

        staged_endpoint_names = {entry.endpoint_name for entry in STAGING_MAP}
        for extractor_cls in extractor_classes:
            source_kind = _normalize_source_kind(extractor_cls.category)
            if source_kind not in {"static", "live"}:
                continue
            if extractor_cls.endpoint_name in staged_endpoint_names:
                continue
            if source_kind == "static":
                requests.append(
                    ProbeRequest(
                        key=extractor_cls.endpoint_name,
                        source_kind="static",
                        endpoint_name=extractor_cls.endpoint_name,
                        result_set_index=None,
                        staging_key=None,
                        params={},
                        probe_context="static",
                        use_multi=False,
                    )
                )
                continue

            if extractor_cls.endpoint_name in {"live_box_score", "live_play_by_play"}:
                game_id = current_regular_games[-1] if current_regular_games else None
                if game_id is None:
                    _append_unavailable(
                        key=extractor_cls.endpoint_name,
                        source_kind="live",
                        endpoint_name=extractor_cls.endpoint_name,
                        staging_key=None,
                        result_set_index=None,
                        param_pattern="live",
                        context="current_regular",
                        reason=(
                            "No current regular-season game_id was discoverable for live probing."
                        ),
                    )
                    continue
                params = {"game_id": game_id}
            else:
                params = {}

            requests.append(
                ProbeRequest(
                    key=extractor_cls.endpoint_name,
                    source_kind=source_kind,
                    endpoint_name=extractor_cls.endpoint_name,
                    result_set_index=None,
                    staging_key=None,
                    params=params,
                    probe_context="current_regular",
                    use_multi=False,
                )
            )

        # CI canary runs sample one probe per source-kind/pattern group so PRs
        # exercise the live harness without paying the cost of the full matrix.
        if os.getenv("NBADB_MODEL_AUDIT_PROBE_PROFILE", "full").strip().lower() == "canary":
            canary_requests: list[ProbeRequest] = []
            seen_groups: set[tuple[str, str]] = set()
            for request in requests:
                pattern = (
                    "non_staged"
                    if request.staging_key is None
                    else staging_pattern_by_key.get(request.staging_key, "unknown")
                )
                group = (request.source_kind, pattern)
                if group in seen_groups:
                    continue
                seen_groups.add(group)
                canary_requests.append(request)
            requests = canary_requests

        return requests, synthetic_records

    async def _execute_probe(self, request: ProbeRequest) -> ProbeExecution:
        extractor_cls = registry.get(request.endpoint_name)
        extractor = extractor_cls()
        loop = asyncio.get_running_loop()

        try:
            if request.use_multi:
                frames = await loop.run_in_executor(
                    None, lambda: _sync_extract_all(extractor, **request.params)
                )
                if request.result_set_index is None:
                    df = frames[0] if frames else pl.DataFrame()
                elif request.result_set_index < len(frames):
                    df = frames[request.result_set_index]
                else:
                    return ProbeExecution(
                        record=AuditRecord(
                            layer="LiveProbe",
                            key=f"{request.key}:{request.probe_context}",
                            decision=AuditDecision.VALIDATION_GAP.value,
                            decision_reason=(
                                f"Extractor returned {len(frames)} result sets; "
                                f"index {request.result_set_index} was out of range."
                            ),
                            issues=["result_set_out_of_range"],
                            source_kind=request.source_kind,
                            endpoint_name=request.endpoint_name,
                            staging_key=request.staging_key,
                            result_set_index=request.result_set_index,
                            details={
                                "probe_context": request.probe_context,
                                "params": request.params,
                                "result_set_count": len(frames),
                            },
                        )
                    )
            else:
                df = await loop.run_in_executor(
                    None, lambda: _sync_extract(extractor, **request.params)
                )
        except Exception as exc:
            return ProbeExecution(
                record=AuditRecord(
                    layer="LiveProbe",
                    key=f"{request.key}:{request.probe_context}",
                    decision=AuditDecision.VALIDATION_GAP.value,
                    decision_reason=f"Live probe raised {type(exc).__name__}.",
                    issues=["probe_exception"],
                    source_kind=request.source_kind,
                    endpoint_name=request.endpoint_name,
                    staging_key=request.staging_key,
                    result_set_index=request.result_set_index,
                    details={
                        "probe_context": request.probe_context,
                        "params": request.params,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
            )

        if df.is_empty() and (
            request.source_kind == "live" or request.probe_context in {"current_playoffs"}
        ):
            decision = AuditDecision.TEMPORALLY_UNAVAILABLE.value
            reason = "Live probe returned no rows for a time-sensitive context."
        else:
            decision = AuditDecision.MODELED.value
            reason = "Live probe completed and returned a normalized dataframe."

        return ProbeExecution(
            record=AuditRecord(
                layer="LiveProbe",
                key=f"{request.key}:{request.probe_context}",
                decision=decision,
                decision_reason=reason,
                issues=[],
                source_kind=request.source_kind,
                endpoint_name=request.endpoint_name,
                staging_key=request.staging_key,
                result_set_index=request.result_set_index,
                details={
                    "probe_context": request.probe_context,
                    "params": request.params,
                    "row_count": df.shape[0],
                    "column_count": df.shape[1],
                    "columns": df.columns,
                    "column_hash": _hash_columns(df),
                    "is_empty": df.is_empty(),
                },
            ),
            dataframe=df,
        )

    async def _run_probes(
        self,
    ) -> tuple[list[AuditRecord], dict[str, pl.DataFrame], dict[str, Any]]:
        requests, synthetic_records = await self._build_probe_requests()

        semaphore = asyncio.Semaphore(max(1, min(self.settings.thread_pool_size, 8)))
        executions: list[ProbeExecution] = []

        async def _guarded(request: ProbeRequest) -> ProbeExecution:
            async with semaphore:
                return await self._execute_probe(request)

        if requests:
            executions = await asyncio.gather(*[_guarded(request) for request in requests])

        records = [*synthetic_records, *(execution.record for execution in executions)]

        selected_staging_frames: dict[str, pl.DataFrame] = {}
        for execution in executions:
            if execution.dataframe is None or execution.record.staging_key is None:
                continue
            existing = selected_staging_frames.get(execution.record.staging_key)
            if existing is None:
                selected_staging_frames[execution.record.staging_key] = execution.dataframe
                continue
            if execution.dataframe.shape[0] > existing.shape[0]:
                selected_staging_frames[execution.record.staging_key] = execution.dataframe

        summary = {
            "generated_at": _now_iso(),
            "request_count": len(requests),
            "record_count": len(records),
            "decision_breakdown": dict(
                sorted(Counter(record.decision for record in records).items())
            ),
            "selected_staging_key_count": len(selected_staging_frames),
        }
        payload = {
            "generated_at": _now_iso(),
            "requests": [asdict(request) for request in requests],
            "records": [record.to_dict() for record in records],
            "summary": summary,
        }
        return records, selected_staging_frames, payload

    def _annotate_probe_status(
        self,
        staging_records: list[AuditRecord],
        probe_records: list[AuditRecord],
    ) -> None:
        best_status: dict[str, str] = {}
        precedence = {
            AuditDecision.MODELED.value: 0,
            AuditDecision.TEMPORALLY_UNAVAILABLE.value: 1,
            AuditDecision.VALIDATION_GAP.value: 2,
            AuditDecision.RUNTIME_GAP.value: 3,
            AuditDecision.SOURCE_GAP.value: 4,
        }
        for record in probe_records:
            if record.staging_key is None:
                continue
            current = best_status.get(record.staging_key)
            if current is None or precedence.get(record.decision, 99) < precedence.get(current, 99):
                best_status[record.staging_key] = record.decision
        for record in staging_records:
            record.details["live_probe_status"] = best_status.get(
                record.staging_key or "", "not_run"
            )

    def _run_build_validation(
        self,
        staging_bundle: dict[str, pl.DataFrame],
        model_surface_records: list[AuditRecord],
    ) -> tuple[list[AuditRecord], dict[str, Any]]:
        conn = duckdb.connect(":memory:")
        try:
            pipeline = TransformPipeline(conn)
            transformers = discover_all_transformers()
            pipeline.register_all(transformers)
            outputs = pipeline.run(
                {key: df.lazy() for key, df in staging_bundle.items()},
                validate_input_schemas=True,
                validate_output_schemas=True,
            )
            result = pipeline.last_result

            records: list[AuditRecord] = []
            completed = set(result.completed if result is not None else [])
            failed_pairs = result.failed if result is not None else []
            failures = {table: error for table, error in failed_pairs}

            for surface in model_surface_records:
                output_table = surface.output_table
                if output_table is None:
                    continue
                df = outputs.get(output_table)
                if surface.decision == AuditDecision.SCHEMA_GAP.value:
                    records.append(
                        AuditRecord(
                            layer="BuildValidation",
                            key=output_table,
                            decision=AuditDecision.SCHEMA_GAP.value,
                            decision_reason=(
                                "Build validation mirrors the missing star schema contract."
                            ),
                            issues=["output_schema_missing"],
                            output_table=output_table,
                            details={},
                        )
                    )
                    continue
                if output_table in completed and df is not None:
                    records.append(
                        AuditRecord(
                            layer="BuildValidation",
                            key=output_table,
                            decision=AuditDecision.MODELED.value,
                            decision_reason=(
                                "Transform completed successfully during sampled build validation."
                            ),
                            issues=[],
                            output_table=output_table,
                            details={
                                "row_count": df.shape[0],
                                "column_count": df.shape[1],
                                "is_empty": df.is_empty(),
                            },
                        )
                    )
                else:
                    records.append(
                        AuditRecord(
                            layer="BuildValidation",
                            key=output_table,
                            decision=AuditDecision.VALIDATION_GAP.value,
                            decision_reason=failures.get(
                                output_table,
                                "Transform did not complete during sampled build validation.",
                            ),
                            issues=["transform_failed"],
                            output_table=output_table,
                            details={},
                        )
                    )

            fk_records = self._run_fk_contract_checks(conn, outputs)
            records.extend(fk_records)
            summary = {
                "generated_at": _now_iso(),
                "transform_output_count": len(model_surface_records),
                "completed_count": len(completed),
                "failed_count": len(failures),
                "fk_check_count": len([r for r in fk_records if r.key.startswith("fk:")]),
                "decision_breakdown": dict(
                    sorted(Counter(record.decision for record in records).items())
                ),
            }
            return records, summary
        finally:
            conn.close()

    def _run_fk_contract_checks(
        self,
        conn: duckdb.DuckDBPyConnection,
        outputs: dict[str, pl.DataFrame],
    ) -> list[AuditRecord]:
        records: list[AuditRecord] = []
        for table_name, schema_cls in sorted(_star_schema_registry().items()):
            if table_name not in outputs:
                continue
            schema = schema_cls.to_schema()
            for column_name, column in schema.columns.items():
                metadata = dict(column.metadata or {})
                fk_ref = str(metadata.get("fk_ref", "") or "")
                if not fk_ref or "." not in fk_ref:
                    continue
                ref_table, ref_column = fk_ref.split(".", 1)
                if ref_table not in outputs:
                    continue
                try:
                    validate_sql_identifier(table_name)
                    validate_sql_identifier(ref_table)
                    validate_sql_identifier(column_name)
                    validate_sql_identifier(ref_column)
                except ValueError:
                    logger.warning(
                        "Skipping FK check for %s.%s: invalid SQL identifier",
                        table_name,
                        column_name,
                    )
                    continue
                row = conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM "{table_name}" child
                    LEFT JOIN "{ref_table}" parent
                        ON child."{column_name}" = parent."{ref_column}"
                    WHERE child."{column_name}" IS NOT NULL
                      AND parent."{ref_column}" IS NULL
                    """
                ).fetchone()
                orphan_count = row[0] if row is not None else 0
                decision = (
                    AuditDecision.MODELED.value
                    if orphan_count == 0
                    else AuditDecision.VALIDATION_GAP.value
                )
                records.append(
                    AuditRecord(
                        layer="BuildValidation",
                        key=f"fk:{table_name}.{column_name}",
                        decision=decision,
                        decision_reason=(
                            "Foreign-key contract passed sampled build validation."
                            if orphan_count == 0
                            else f"Foreign-key contract found {orphan_count} orphan rows."
                        ),
                        issues=[] if orphan_count == 0 else ["fk_orphans"],
                        output_table=table_name,
                        column_name=column_name,
                        details={
                            "fk_ref": fk_ref,
                            "orphans": orphan_count,
                        },
                    )
                )
        return records

    def _build_report(
        self,
        *,
        summary: dict[str, Any],
        baseline_comparison: dict[str, Any] | None,
        inventory_sections: dict[str, Any],
    ) -> str:
        lines = [
            "# Model Audit Report",
            "",
            "## Summary",
            "",
            f"- Generated at: `{summary['generated_at']}`",
            f"- Problem count: `{summary['problem_count']}`",
            f"- Discovery issues: `{summary['discovery_issue_count']}`",
            "",
            "## Inventory",
            "",
        ]
        inventory_meta = inventory_sections["inventory_meta"]
        for key in (
            "runtime_version",
            "runtime_stats_surface_count",
            "runtime_static_surface_count",
            "runtime_live_surface_count",
            "extractor_count",
            "staging_entry_count",
            "runtime_transform_output_count",
            "legacy_transform_output_count",
            "star_schema_count",
        ):
            lines.append(f"- {key}: `{inventory_meta[key]}`")

        lines.extend(
            [
                "",
                "## Decisions",
                "",
                "| Decision | Count |",
                "|----------|------:|",
            ]
        )
        for decision, count in sorted(summary["decision_breakdown"].items()):
            lines.append(f"| `{decision}` | {count} |")

        if summary["discovery_issues"]:
            lines.extend(["", "## Discovery Issues", ""])
            for issue in summary["discovery_issues"]:
                lines.append(f"- `{issue['key']}`: {issue['message']}")

        if baseline_comparison is not None:
            lines.extend(["", "## Baseline Comparison", ""])
            lines.append(f"- Regression detected: `{baseline_comparison['regression_detected']}`")
            lines.append(f"- New problem keys: `{len(baseline_comparison['new_problem_keys'])}`")
            resolved_count = len(baseline_comparison["resolved_problem_keys"])
            lines.append(f"- Resolved problem keys: `{resolved_count}`")

        lines.extend(["", "## Top Problem Keys", ""])
        for key in summary["problem_keys"][:50]:
            lines.append(f"- `{key}`")
        if not summary["problem_keys"]:
            lines.append("- None")

        return "\n".join(lines)

    def write(
        self,
        *,
        mode: AuditMode = AuditMode.INVENTORY,
        strictness: AuditStrictness = AuditStrictness.CONSISTENCY,
        output_dir: Path | None = None,
        baseline_path: Path | None = None,
    ) -> dict[str, Path]:
        inventory_sections = self._build_inventory_sections()
        staging_surface_records = inventory_sections["staging_surfaces"]
        all_records: list[AuditRecord] = list(inventory_sections["records"])
        live_probe_payload: dict[str, Any] | None = None
        build_payload: dict[str, Any] | None = None

        if mode in {AuditMode.PROBE, AuditMode.BUILD, AuditMode.FULL}:
            probe_records, staging_bundle, live_probe_payload = asyncio.run(self._run_probes())
            self._annotate_probe_status(staging_surface_records, probe_records)
            all_records.extend(probe_records)
            if mode in {AuditMode.BUILD, AuditMode.FULL}:
                build_records, build_summary = self._run_build_validation(
                    staging_bundle,
                    inventory_sections["model_surfaces"],
                )
                all_records.extend(build_records)
                build_payload = {
                    "generated_at": _now_iso(),
                    "records": [record.to_dict() for record in build_records],
                    "summary": build_summary,
                }

        summary = _summarize_records(
            all_records,
            inventory_meta=inventory_sections["inventory_meta"],
            discovery_issues=inventory_sections["discovery_issues"],
        )

        baseline_comparison: dict[str, Any] | None = None
        if baseline_path is not None:
            baseline_summary = _load_baseline(baseline_path)
            baseline_comparison = compare_baseline(inventory_sections["summary"], baseline_summary)

        self._enforce(
            strictness=strictness,
            summary=summary,
            inventory_summary=inventory_sections["summary"],
            baseline_comparison=baseline_comparison,
            baseline_path=baseline_path,
        )

        payload = {
            "generated_at": _now_iso(),
            "mode": mode.value,
            "strictness": strictness.value,
            "runtime_surfaces": [
                record.to_dict() for record in inventory_sections["runtime_surfaces"]
            ],
            "staging_surfaces": [
                record.to_dict() for record in inventory_sections["staging_surfaces"]
            ],
            "model_surfaces": [record.to_dict() for record in inventory_sections["model_surfaces"]],
            "column_contracts": [
                record.to_dict() for record in inventory_sections["column_contracts"]
            ],
            "live_probes": [] if live_probe_payload is None else live_probe_payload["records"],
            "build_validations": [] if build_payload is None else build_payload["records"],
            "summary": summary,
            "baseline_comparison": baseline_comparison,
        }

        matrix_rows = [record.to_dict() for record in all_records]
        matrix_payload = {"generated_at": _now_iso(), "matrix": matrix_rows}
        report = self._build_report(
            summary=summary,
            baseline_comparison=baseline_comparison,
            inventory_sections=inventory_sections,
        )

        destination = (output_dir or _DEFAULT_OUTPUT_DIR).resolve()
        inventory_path = destination / "inventory.json"
        matrix_path = destination / "matrix.json"
        report_path = destination / "report.md"

        _write_json(inventory_path, payload)
        _write_json(matrix_path, matrix_payload)
        _write_text(report_path, report)

        written = {
            "inventory": inventory_path,
            "matrix": matrix_path,
            "report": report_path,
        }

        if live_probe_payload is not None:
            live_probe_path = destination / "live-probes.json"
            _write_json(live_probe_path, live_probe_payload)
            written["live_probes"] = live_probe_path
        if build_payload is not None:
            build_path = destination / "build-validation.json"
            _write_json(build_path, build_payload)
            written["build_validation"] = build_path
        if baseline_comparison is not None:
            baseline_compare_path = destination / "baseline-comparison.json"
            _write_json(
                baseline_compare_path,
                {"generated_at": _now_iso(), "comparison": baseline_comparison},
            )
            written["baseline_comparison"] = baseline_compare_path

        return written

    @staticmethod
    def _enforce(
        *,
        strictness: AuditStrictness,
        summary: dict[str, Any],
        inventory_summary: dict[str, Any],
        baseline_comparison: dict[str, Any] | None,
        baseline_path: Path | None,
    ) -> None:
        if (
            strictness == AuditStrictness.CONSISTENCY
            and inventory_summary.get("discovery_issue_count", 0) > 0
        ):
            raise AuditFailureError("consistency check failed: discovery issues remain")

        if strictness in {AuditStrictness.NO_REGRESSIONS, AuditStrictness.ZERO_GAPS}:
            if baseline_path is None:
                raise AuditFailureError(
                    "no-regressions and zero-gaps strictness require --baseline to be provided"
                )
            if baseline_comparison is None:
                raise AuditFailureError("baseline comparison could not be computed")
            if baseline_comparison.get("regression_detected"):
                raise AuditFailureError(
                    "no-regressions check failed: new audit regressions detected"
                )

        if strictness == AuditStrictness.ZERO_GAPS and summary.get("problem_count", 0) > 0:
            raise AuditFailureError("zero-gaps check failed: audit problems remain")


__all__ = [
    "AuditDecision",
    "AuditFailureError",
    "AuditMode",
    "AuditRecord",
    "AuditStrictness",
    "ColumnOrigin",
    "ModelAuditEngine",
    "compare_baseline",
]
