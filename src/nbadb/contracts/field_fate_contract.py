"""Exact, non-inferential provider-field fate contracts.

Provider fields are compiled in route/mapping order from the immutable
runtime-derived silver contract.  Local storage is linked only by its explicit
``RouteColumnMapping``.  Star-schema names, transform dependencies, wildcard
passthroughs, and schema ``source`` metadata are retained only as non-green
candidate evidence: none is promoted into reviewed gold or metric lineage.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from nbadb.contracts.staging_route_contract import (
    EXPECTED_STAGING_ROUTE_COUNT,
    StagingRouteContract,
    staging_route_contract_bundle,
    validate_staging_route_contract_bundle,
)
from nbadb.contracts.star_table_contract import (
    EXPECTED_STAR_TABLE_TOTAL,
    StarModelContractInventory,
    compile_star_table_contracts,
)
from nbadb.orchestrate.transformers import discover_all_transformers

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class FieldFateContractCompilationError(RuntimeError):
    """The exact provider-field fate inventory could not be proven."""


@dataclass(frozen=True, slots=True)
class FieldLayerDisposition:
    """One layer's exact evidence state for a provider-field occurrence."""

    status: str
    target_tier: str | None
    target_table: str | None
    target_column: str | None
    evidence_kind: str
    reviewed: bool
    green: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NonGreenLineageEvidence:
    """Candidate evidence that is explicitly inadmissible as proven lineage."""

    kind: str
    targets: tuple[str, ...]
    targets_sha256: str
    admitted: bool
    green: bool


@dataclass(frozen=True, slots=True)
class ProviderFieldFateContract:
    """One exact route-local provider-field occurrence and its dispositions."""

    occurrence_id: str
    occurrence_ordinal: int
    route_id: str
    route_ordinal: int
    route_field_ordinal: int
    provider_field_kind: str
    source_family: str
    endpoint_name: str
    provider_endpoint_id: str
    provider_runtime_class: str
    provider_runtime_module: str
    provider_result_set_name: str
    provider_result_set_ordinal: int
    provider_column: str
    provider_field_identity_sha256: str
    canonical_column: str
    mapping_transform: str
    staging_key: str
    resolved_schema_tier: str
    resolved_schema_table: str
    resolved_schema_class: str
    storage_column: str | None
    endpoint_contract_sha256: str
    physical_disposition: FieldLayerDisposition
    staging_disposition: FieldLayerDisposition
    star_disposition: FieldLayerDisposition
    model_disposition: FieldLayerDisposition
    metric_disposition: FieldLayerDisposition
    non_green_lineage_evidence: tuple[NonGreenLineageEvidence, ...]
    reason: str
    owner: str
    blockers: tuple[str, ...]
    revalidation_path: str
    model_green: bool


@dataclass(frozen=True, slots=True)
class StorageOnlySinkContract:
    """A route-local storage column that is not another provider source row."""

    occurrence_id: str
    occurrence_ordinal: int
    route_id: str
    route_ordinal: int
    storage_ordinal: int
    staging_key: str
    resolved_schema_tier: str
    resolved_schema_table: str
    resolved_schema_class: str
    storage_column: str
    disposition: str
    reason: str
    owner: str
    blockers: tuple[str, ...]
    revalidation_path: str


@dataclass(frozen=True, slots=True)
class ZeroFieldRouteContract:
    """A classified route for which the pinned contract declares no fields."""

    route_id: str
    route_ordinal: int
    endpoint_name: str
    staging_key: str
    classified_status: str
    disposition_reason: str
    owner: str
    blockers: tuple[str, ...]
    revalidation_path: str


@dataclass(frozen=True, slots=True)
class CandidateEvidenceSummary:
    """Exact counts for one rejected candidate-evidence class."""

    kind: str
    field_occurrence_count: int
    target_count: int


@dataclass(frozen=True, slots=True)
class FieldFateBlockerSummary:
    """Exact blocker occurrences, kept separate by inventory scope."""

    scope: str
    code: str
    occurrence_count: int


@dataclass(frozen=True, slots=True)
class FieldFateContractBundle:
    """Immutable exact field denominator plus non-source local inventories."""

    fields: tuple[ProviderFieldFateContract, ...]
    storage_only_sinks: tuple[StorageOnlySinkContract, ...]
    zero_field_routes: tuple[ZeroFieldRouteContract, ...]
    digest: str
    staging_route_contract_sha256: str
    star_table_contract_sha256: str
    provider_authority_sha256: str
    provider_field_occurrence_count: int
    top_level_provider_field_occurrence_count: int
    nested_projection_occurrence_count: int
    unique_provider_field_identity_count: int
    repeated_route_occurrence_count: int
    storage_mapped_occurrence_count: int
    storage_unmapped_occurrence_count: int
    unresolved_provider_field_occurrence_count: int
    source_family_counts: tuple[tuple[str, int], ...]
    mapping_transform_counts: tuple[tuple[str, int], ...]
    storage_tier_counts: tuple[tuple[str, int], ...]
    candidate_evidence_summary: tuple[CandidateEvidenceSummary, ...]
    blocker_summary: tuple[FieldFateBlockerSummary, ...]
    model_green: bool
    _by_occurrence_id: Mapping[str, ProviderFieldFateContract]

    @property
    def by_occurrence_id(self) -> Mapping[str, ProviderFieldFateContract]:
        return self._by_occurrence_id

    def field(self, occurrence_id: str) -> ProviderFieldFateContract:
        try:
            return self._by_occurrence_id[occurrence_id]
        except KeyError:
            raise KeyError(occurrence_id) from None


EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT: Final = 11_323
EXPECTED_TOP_LEVEL_PROVIDER_FIELD_OCCURRENCE_COUNT: Final = 11_321
EXPECTED_NESTED_PROJECTION_OCCURRENCE_COUNT: Final = 2
EXPECTED_UNIQUE_PROVIDER_FIELD_IDENTITY_COUNT: Final = 9_694
EXPECTED_REPEATED_ROUTE_OCCURRENCE_COUNT: Final = 1_629
EXPECTED_STORAGE_MAPPED_OCCURRENCE_COUNT: Final = 11_323
EXPECTED_STORAGE_UNMAPPED_OCCURRENCE_COUNT: Final = 0
EXPECTED_STORAGE_ONLY_SINK_OCCURRENCE_COUNT: Final = 1_445
EXPECTED_ZERO_FIELD_ROUTE_COUNT: Final = 6
FIELD_FATE_OWNER: Final = "nbadb_data_model"
FIELD_FATE_REVALIDATION_PATH: Final = (
    "regenerate_from_exact_route_contract_after_reviewed_field_dispositions"
)

_SELECT_STAR_FROM_RE: Final = re.compile(
    r"\bSELECT\s+\*\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)
_EVIDENCE_KIND_ORDER: Final = (
    "explicit_star_source_metadata_candidate",
    "dependency_same_name_candidate",
    "sql_passthrough_candidate",
    "global_same_name_candidate",
    "normalized_name_inference",
)


@dataclass(frozen=True, slots=True)
class _CandidateIndexes:
    star_by_name: dict[str, tuple[str, ...]]
    star_by_normalized_name: dict[str, tuple[str, ...]]
    star_by_source: dict[str, tuple[str, ...]]
    star_by_dependency_and_name: dict[tuple[str, str], tuple[str, ...]]
    star_by_passthrough_and_name: dict[tuple[str, str], tuple[str, ...]]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _freeze_index(
    values: Mapping[Any, Sequence[str]],
) -> dict[Any, tuple[str, ...]]:
    return {key: tuple(sorted(set(items))) for key, items in values.items()}


def _layer_payload(disposition: FieldLayerDisposition) -> dict[str, object]:
    return {
        "status": disposition.status,
        "target_tier": disposition.target_tier,
        "target_table": disposition.target_table,
        "target_column": disposition.target_column,
        "evidence_kind": disposition.evidence_kind,
        "reviewed": disposition.reviewed,
        "green": disposition.green,
        "blockers": list(disposition.blockers),
    }


def _candidate_payload(evidence: NonGreenLineageEvidence) -> dict[str, object]:
    return {
        "kind": evidence.kind,
        "target_count": len(evidence.targets),
        "targets_sha256": evidence.targets_sha256,
        "admitted": evidence.admitted,
        "green": evidence.green,
    }


def _field_payload(field: ProviderFieldFateContract) -> dict[str, object]:
    return {
        "occurrence_id": field.occurrence_id,
        "occurrence_ordinal": field.occurrence_ordinal,
        "route_id": field.route_id,
        "route_ordinal": field.route_ordinal,
        "route_field_ordinal": field.route_field_ordinal,
        "provider_field_kind": field.provider_field_kind,
        "source_family": field.source_family,
        "endpoint_name": field.endpoint_name,
        "provider_endpoint_id": field.provider_endpoint_id,
        "provider_runtime_class": field.provider_runtime_class,
        "provider_runtime_module": field.provider_runtime_module,
        "provider_result_set_name": field.provider_result_set_name,
        "provider_result_set_ordinal": field.provider_result_set_ordinal,
        "provider_column": field.provider_column,
        "provider_field_identity_sha256": field.provider_field_identity_sha256,
        "canonical_column": field.canonical_column,
        "mapping_transform": field.mapping_transform,
        "staging_key": field.staging_key,
        "resolved_schema_tier": field.resolved_schema_tier,
        "resolved_schema_table": field.resolved_schema_table,
        "resolved_schema_class": field.resolved_schema_class,
        "storage_column": field.storage_column,
        "endpoint_contract_sha256": field.endpoint_contract_sha256,
        "physical_disposition": _layer_payload(field.physical_disposition),
        "staging_disposition": _layer_payload(field.staging_disposition),
        "star_disposition": _layer_payload(field.star_disposition),
        "model_disposition": _layer_payload(field.model_disposition),
        "metric_disposition": _layer_payload(field.metric_disposition),
        "non_green_lineage_evidence": [
            _candidate_payload(evidence) for evidence in field.non_green_lineage_evidence
        ],
        "reason": field.reason,
        "owner": field.owner,
        "blockers": list(field.blockers),
        "revalidation_path": field.revalidation_path,
        "model_green": field.model_green,
    }


def _sink_payload(sink: StorageOnlySinkContract) -> dict[str, object]:
    return {
        "occurrence_id": sink.occurrence_id,
        "occurrence_ordinal": sink.occurrence_ordinal,
        "route_id": sink.route_id,
        "route_ordinal": sink.route_ordinal,
        "storage_ordinal": sink.storage_ordinal,
        "staging_key": sink.staging_key,
        "resolved_schema_tier": sink.resolved_schema_tier,
        "resolved_schema_table": sink.resolved_schema_table,
        "resolved_schema_class": sink.resolved_schema_class,
        "storage_column": sink.storage_column,
        "disposition": sink.disposition,
        "reason": sink.reason,
        "owner": sink.owner,
        "blockers": list(sink.blockers),
        "revalidation_path": sink.revalidation_path,
    }


def _zero_route_payload(route: ZeroFieldRouteContract) -> dict[str, object]:
    return {
        "route_id": route.route_id,
        "route_ordinal": route.route_ordinal,
        "endpoint_name": route.endpoint_name,
        "staging_key": route.staging_key,
        "classified_status": route.classified_status,
        "disposition_reason": route.disposition_reason,
        "owner": route.owner,
        "blockers": list(route.blockers),
        "revalidation_path": route.revalidation_path,
    }


def _build_candidate_indexes(
    star_inventory: StarModelContractInventory,
) -> _CandidateIndexes:
    if len(star_inventory.tables) != EXPECTED_STAR_TABLE_TOTAL:
        raise FieldFateContractCompilationError(
            f"star inventory has {len(star_inventory.tables)} tables; "
            f"expected {EXPECTED_STAR_TABLE_TOTAL}"
        )
    table_names = [table.output_name for table in star_inventory.tables]
    if len(table_names) != len(set(table_names)):
        raise FieldFateContractCompilationError("star inventory contains duplicate outputs")

    runtimes = discover_all_transformers(include_live=True)
    runtime_names = [runtime.output_table for runtime in runtimes]
    if len(runtime_names) != len(set(runtime_names)) or set(runtime_names) != set(table_names):
        raise FieldFateContractCompilationError(
            "star inventory and runtime transformer outputs are not identical"
        )
    runtime_by_name = dict(zip(runtime_names, runtimes, strict=True))

    by_name: dict[str, list[str]] = defaultdict(list)
    by_normalized_name: dict[str, list[str]] = defaultdict(list)
    by_source: dict[str, list[str]] = defaultdict(list)
    by_dependency_and_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_passthrough_and_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for table in star_inventory.tables:
        for column in table.columns:
            target = f"{table.output_name}.{column.name}"
            by_name[column.name].append(target)
            by_normalized_name[_normalized_name(column.name)].append(target)
            if column.source is not None:
                by_source[column.source].append(target)
            for dependency in table.transform.dependencies:
                by_dependency_and_name[(dependency, column.name)].append(target)

        runtime = runtime_by_name[table.output_name]
        sql = getattr(runtime, "_SQL", None)
        if isinstance(sql, str):
            passthrough_dependencies = {
                dependency
                for dependency in _SELECT_STAR_FROM_RE.findall(sql)
                if dependency in table.transform.dependencies
            }
            for dependency in passthrough_dependencies:
                for column in table.columns:
                    by_passthrough_and_name[(dependency, column.name)].append(
                        f"{table.output_name}.{column.name}"
                    )

    return _CandidateIndexes(
        star_by_name=_freeze_index(by_name),
        star_by_normalized_name=_freeze_index(by_normalized_name),
        star_by_source=_freeze_index(by_source),
        star_by_dependency_and_name=_freeze_index(by_dependency_and_name),
        star_by_passthrough_and_name=_freeze_index(by_passthrough_and_name),
    )


def _validate_route_mapping(route: StagingRouteContract) -> None:
    mappings = route.column_mappings
    provider_width = len(route.provider_columns)
    if len(mappings) < provider_width:
        raise FieldFateContractCompilationError(
            f"{route.route_id} has fewer mappings than provider columns"
        )
    if tuple(mapping.provider_column for mapping in mappings[:provider_width]) != (
        route.provider_columns
    ):
        raise FieldFateContractCompilationError(
            f"{route.route_id} provider columns are not the exact mapping prefix"
        )
    if tuple(mapping.canonical_column for mapping in mappings) != route.canonical_columns:
        raise FieldFateContractCompilationError(
            f"{route.route_id} canonical columns differ from exact mappings"
        )
    for mapping in mappings[provider_width:]:
        if mapping.transform != "nested_projection":
            raise FieldFateContractCompilationError(
                f"{route.route_id} has an undeclared provider-field extension"
            )
    mapped_storage = {
        mapping.storage_column for mapping in mappings if mapping.storage_column is not None
    }
    for mapping in mappings:
        if (
            mapping.storage_column is not None
            and mapping.storage_column not in route.storage_columns
        ):
            raise FieldFateContractCompilationError(
                f"{route.route_id}:{mapping.provider_column} targets an absent storage column"
            )
    expected_storage_only = tuple(
        column for column in route.storage_columns if column not in mapped_storage
    )
    if route.storage_columns_without_provider != expected_storage_only:
        raise FieldFateContractCompilationError(
            f"{route.route_id} storage-only column inventory differs from mappings"
        )
    if mappings and (
        route.provider_result_set_name is None or route.provider_result_set_ordinal is None
    ):
        raise FieldFateContractCompilationError(
            f"{route.route_id} has provider fields without result-set identity"
        )


def _provider_source_candidates(
    route: StagingRouteContract,
    provider_column: str,
) -> tuple[str, ...]:
    candidates: set[str] = set()
    if route.provider_result_set_name is not None:
        candidates.add(
            ".".join(
                (
                    route.provider_runtime_class,
                    route.provider_result_set_name,
                    provider_column,
                )
            )
        )
    if route.canonical_result_set_name is not None:
        candidates.add(
            ".".join(
                (
                    route.canonical_runtime_class,
                    route.canonical_result_set_name,
                    provider_column,
                )
            )
        )
    return tuple(sorted(candidates))


def _non_green_lineage_evidence(
    *,
    route: StagingRouteContract,
    provider_column: str,
    canonical_column: str,
    storage_column: str | None,
    indexes: _CandidateIndexes,
) -> tuple[NonGreenLineageEvidence, ...]:
    source_targets = tuple(
        sorted(
            {
                target
                for source in _provider_source_candidates(route, provider_column)
                for target in indexes.star_by_source.get(source, ())
            }
        )
    )
    same_name_targets = indexes.star_by_name.get(canonical_column, ())
    normalized_targets = tuple(
        target
        for target in indexes.star_by_normalized_name.get(
            _normalized_name(canonical_column),
            (),
        )
        if target not in set(same_name_targets)
    )
    dependency_targets = (
        indexes.star_by_dependency_and_name.get((route.staging_key, storage_column), ())
        if storage_column is not None
        else ()
    )
    passthrough_targets = (
        indexes.star_by_passthrough_and_name.get((route.staging_key, storage_column), ())
        if storage_column is not None
        else ()
    )
    targets_by_kind = {
        "explicit_star_source_metadata_candidate": source_targets,
        "dependency_same_name_candidate": dependency_targets,
        "sql_passthrough_candidate": passthrough_targets,
        "global_same_name_candidate": same_name_targets,
        "normalized_name_inference": normalized_targets,
    }
    return tuple(
        NonGreenLineageEvidence(
            kind=kind,
            targets=targets_by_kind[kind],
            targets_sha256=_sha256_json(list(targets_by_kind[kind])),
            admitted=False,
            green=False,
        )
        for kind in _EVIDENCE_KIND_ORDER
        if targets_by_kind[kind]
    )


def _provider_identity_sha256(
    route: StagingRouteContract,
    provider_column: str,
) -> str:
    return _sha256_json(
        {
            "source_family": route.source_family,
            "provider_endpoint_id": route.provider_endpoint_id,
            "provider_result_set_name": route.provider_result_set_name,
            "provider_result_set_ordinal": route.provider_result_set_ordinal,
            "provider_column": provider_column,
        }
    )


def _compile_field(
    *,
    occurrence_ordinal: int,
    route: StagingRouteContract,
    route_field_ordinal: int,
    indexes: _CandidateIndexes,
) -> ProviderFieldFateContract:
    mapping = route.column_mappings[route_field_ordinal]
    provider_field_kind = (
        "top_level_provider_column"
        if route_field_ordinal < len(route.provider_columns)
        else "nested_projection"
    )
    physical = FieldLayerDisposition(
        status="provider_declaration_not_physical_field_observation",
        target_tier=None,
        target_table=None,
        target_column=None,
        evidence_kind="exact_pinned_provider_and_route_contract",
        reviewed=False,
        green=False,
        blockers=("physical_field_capture_unobserved",),
    )
    if mapping.storage_column is None:
        staging = FieldLayerDisposition(
            status="declared_storage_target_absent",
            target_tier=route.resolved_schema_tier,
            target_table=route.staging_key,
            target_column=None,
            evidence_kind="exact_route_declared_storage_subset",
            reviewed=False,
            green=False,
            blockers=("storage_mapping_missing",),
        )
        reason = (
            "The exact route declares this provider field without a storage target; "
            "physical observation and reviewed star/model/metric dispositions are absent."
        )
    else:
        staging = FieldLayerDisposition(
            status="exact_declared_storage_mapping",
            target_tier=route.resolved_schema_tier,
            target_table=route.staging_key,
            target_column=mapping.storage_column,
            evidence_kind=f"route_column_mapping:{mapping.transform}",
            reviewed=False,
            green=True,
            blockers=(),
        )
        reason = (
            "The exact route mapping reaches a schema-owned storage column; physical "
            "observation and reviewed star/model/metric dispositions are absent."
        )
    star = FieldLayerDisposition(
        status="unreviewed_no_exact_provider_lineage",
        target_tier="star",
        target_table=None,
        target_column=None,
        evidence_kind="non_green_candidates_only",
        reviewed=False,
        green=False,
        blockers=("star_lineage_unreviewed",),
    )
    model = FieldLayerDisposition(
        status="unreviewed_no_model_disposition",
        target_tier="model",
        target_table=None,
        target_column=None,
        evidence_kind="missing_reviewed_model_contract",
        reviewed=False,
        green=False,
        blockers=("model_disposition_unreviewed",),
    )
    metric = FieldLayerDisposition(
        status="unreviewed_no_metric_disposition",
        target_tier="metric",
        target_table=None,
        target_column=None,
        evidence_kind="missing_reviewed_metric_contract",
        reviewed=False,
        green=False,
        blockers=("metric_disposition_unreviewed",),
    )
    candidates = _non_green_lineage_evidence(
        route=route,
        provider_column=mapping.provider_column,
        canonical_column=mapping.canonical_column,
        storage_column=mapping.storage_column,
        indexes=indexes,
    )
    blockers = tuple(
        dict.fromkeys(
            (
                *physical.blockers,
                *staging.blockers,
                *star.blockers,
                *model.blockers,
                *metric.blockers,
                *(f"non_green_{evidence.kind}" for evidence in candidates),
            )
        )
    )
    if route.provider_result_set_name is None or route.provider_result_set_ordinal is None:
        raise FieldFateContractCompilationError(
            f"{route.route_id} field occurrence lacks provider result-set identity"
        )
    field_model_green = (
        not blockers
        and not candidates
        and all(disposition.green for disposition in (physical, staging, star, model, metric))
    )
    return ProviderFieldFateContract(
        occurrence_id=f"{route.route_id}#field:{route_field_ordinal}",
        occurrence_ordinal=occurrence_ordinal,
        route_id=route.route_id,
        route_ordinal=route.ordinal,
        route_field_ordinal=route_field_ordinal,
        provider_field_kind=provider_field_kind,
        source_family=route.source_family,
        endpoint_name=route.endpoint_name,
        provider_endpoint_id=route.provider_endpoint_id,
        provider_runtime_class=route.provider_runtime_class,
        provider_runtime_module=route.provider_runtime_module,
        provider_result_set_name=route.provider_result_set_name,
        provider_result_set_ordinal=route.provider_result_set_ordinal,
        provider_column=mapping.provider_column,
        provider_field_identity_sha256=_provider_identity_sha256(
            route,
            mapping.provider_column,
        ),
        canonical_column=mapping.canonical_column,
        mapping_transform=mapping.transform,
        staging_key=route.staging_key,
        resolved_schema_tier=route.resolved_schema_tier,
        resolved_schema_table=route.resolved_schema_table,
        resolved_schema_class=route.resolved_schema_class,
        storage_column=mapping.storage_column,
        endpoint_contract_sha256=route.endpoint_contract_sha256,
        physical_disposition=physical,
        staging_disposition=staging,
        star_disposition=star,
        model_disposition=model,
        metric_disposition=metric,
        non_green_lineage_evidence=candidates,
        reason=reason,
        owner=FIELD_FATE_OWNER,
        blockers=blockers,
        revalidation_path=FIELD_FATE_REVALIDATION_PATH,
        model_green=field_model_green,
    )


def _compile_storage_only_sinks(
    routes: Sequence[StagingRouteContract],
) -> tuple[StorageOnlySinkContract, ...]:
    sinks: list[StorageOnlySinkContract] = []
    for route in routes:
        for storage_column in route.storage_columns_without_provider:
            storage_ordinal = route.storage_columns.index(storage_column)
            sinks.append(
                StorageOnlySinkContract(
                    occurrence_id=f"{route.route_id}#storage:{storage_ordinal}",
                    occurrence_ordinal=len(sinks),
                    route_id=route.route_id,
                    route_ordinal=route.ordinal,
                    storage_ordinal=storage_ordinal,
                    staging_key=route.staging_key,
                    resolved_schema_tier=route.resolved_schema_tier,
                    resolved_schema_table=route.resolved_schema_table,
                    resolved_schema_class=route.resolved_schema_class,
                    storage_column=storage_column,
                    disposition="local_storage_sink_not_provider_denominator",
                    reason=(
                        "The route storage schema declares this local column without an "
                        "exact provider-field mapping; it is sink evidence, not another "
                        "upstream source field."
                    ),
                    owner=FIELD_FATE_OWNER,
                    blockers=("storage_only_source_disposition_unreviewed",),
                    revalidation_path=FIELD_FATE_REVALIDATION_PATH,
                )
            )
    return tuple(sinks)


def _compile_zero_field_routes(
    routes: Sequence[StagingRouteContract],
) -> tuple[ZeroFieldRouteContract, ...]:
    records: list[ZeroFieldRouteContract] = []
    for route in routes:
        if route.column_mappings:
            continue
        if not route.disposition_reason:
            raise FieldFateContractCompilationError(
                f"{route.route_id} has no provider fields or disposition reason"
            )
        records.append(
            ZeroFieldRouteContract(
                route_id=route.route_id,
                route_ordinal=route.ordinal,
                endpoint_name=route.endpoint_name,
                staging_key=route.staging_key,
                classified_status=route.classified_status,
                disposition_reason=route.disposition_reason,
                owner=FIELD_FATE_OWNER,
                blockers=("provider_field_inventory_absent",),
                revalidation_path=FIELD_FATE_REVALIDATION_PATH,
            )
        )
    return tuple(records)


def _candidate_summary(
    fields: Sequence[ProviderFieldFateContract],
) -> tuple[CandidateEvidenceSummary, ...]:
    field_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    for field in fields:
        for evidence in field.non_green_lineage_evidence:
            field_counts[evidence.kind] += 1
            target_counts[evidence.kind] += len(evidence.targets)
    return tuple(
        CandidateEvidenceSummary(
            kind=kind,
            field_occurrence_count=field_counts[kind],
            target_count=target_counts[kind],
        )
        for kind in _EVIDENCE_KIND_ORDER
        if field_counts[kind]
    )


def _blocker_summary(
    fields: Sequence[ProviderFieldFateContract],
    storage_only_sinks: Sequence[StorageOnlySinkContract],
    zero_field_routes: Sequence[ZeroFieldRouteContract],
) -> tuple[FieldFateBlockerSummary, ...]:
    counts: Counter[tuple[str, str]] = Counter()
    for field in fields:
        counts.update(("provider_field", blocker) for blocker in field.blockers)
    for sink in storage_only_sinks:
        counts.update(("storage_only_sink", blocker) for blocker in sink.blockers)
    for route in zero_field_routes:
        counts.update(("zero_field_route", blocker) for blocker in route.blockers)
    return tuple(
        FieldFateBlockerSummary(
            scope=scope,
            code=code,
            occurrence_count=counts[(scope, code)],
        )
        for scope, code in sorted(counts)
    )


def _bundle_payload(
    *,
    fields: Sequence[ProviderFieldFateContract],
    storage_only_sinks: Sequence[StorageOnlySinkContract],
    zero_field_routes: Sequence[ZeroFieldRouteContract],
    staging_route_contract_sha256: str,
    star_table_contract_sha256: str,
    provider_authority_sha256: str,
    summary: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nbadb_provider_field_fate_contract_bundle",
        "staging_route_contract_sha256": staging_route_contract_sha256,
        "star_table_contract_sha256": star_table_contract_sha256,
        "provider_authority_sha256": provider_authority_sha256,
        "summary": dict(summary),
        "fields": [_field_payload(field) for field in fields],
        "storage_only_sinks": [_sink_payload(sink) for sink in storage_only_sinks],
        "zero_field_routes": [_zero_route_payload(route) for route in zero_field_routes],
    }


def _make_bundle(
    *,
    fields: Sequence[ProviderFieldFateContract],
    storage_only_sinks: Sequence[StorageOnlySinkContract],
    zero_field_routes: Sequence[ZeroFieldRouteContract],
    staging_route_contract_sha256: str,
    star_table_contract_sha256: str,
    provider_authority_sha256: str,
) -> FieldFateContractBundle:
    field_tuple = tuple(fields)
    sink_tuple = tuple(storage_only_sinks)
    zero_tuple = tuple(zero_field_routes)
    identity_count = len({field.provider_field_identity_sha256 for field in field_tuple})
    top_level_count = sum(
        field.provider_field_kind == "top_level_provider_column" for field in field_tuple
    )
    nested_count = sum(field.provider_field_kind == "nested_projection" for field in field_tuple)
    mapped_count = sum(field.storage_column is not None for field in field_tuple)
    candidate_summary = _candidate_summary(field_tuple)
    blocker_summary = _blocker_summary(field_tuple, sink_tuple, zero_tuple)
    model_green = not blocker_summary and all(field.model_green for field in field_tuple)
    summary: dict[str, object] = {
        "provider_field_occurrence_count": len(field_tuple),
        "top_level_provider_field_occurrence_count": top_level_count,
        "nested_projection_occurrence_count": nested_count,
        "unique_provider_field_identity_count": identity_count,
        "repeated_route_occurrence_count": len(field_tuple) - identity_count,
        "storage_mapped_occurrence_count": mapped_count,
        "storage_unmapped_occurrence_count": len(field_tuple) - mapped_count,
        "storage_only_sink_occurrence_count": len(sink_tuple),
        "zero_field_route_count": len(zero_tuple),
        "unresolved_provider_field_occurrence_count": sum(
            not field.model_green for field in field_tuple
        ),
        "source_family_counts": dict(
            sorted(Counter(field.source_family for field in field_tuple).items())
        ),
        "mapping_transform_counts": dict(
            sorted(Counter(field.mapping_transform for field in field_tuple).items())
        ),
        "storage_tier_counts": dict(
            sorted(Counter(field.resolved_schema_tier for field in field_tuple).items())
        ),
        "candidate_evidence_summary": [
            {
                "kind": item.kind,
                "field_occurrence_count": item.field_occurrence_count,
                "target_count": item.target_count,
            }
            for item in candidate_summary
        ],
        "blocker_summary": [
            {
                "scope": item.scope,
                "code": item.code,
                "occurrence_count": item.occurrence_count,
            }
            for item in blocker_summary
        ],
        "model_green": model_green,
    }
    digest = _sha256_json(
        _bundle_payload(
            fields=field_tuple,
            storage_only_sinks=sink_tuple,
            zero_field_routes=zero_tuple,
            staging_route_contract_sha256=staging_route_contract_sha256,
            star_table_contract_sha256=star_table_contract_sha256,
            provider_authority_sha256=provider_authority_sha256,
            summary=summary,
        )
    )
    return FieldFateContractBundle(
        fields=field_tuple,
        storage_only_sinks=sink_tuple,
        zero_field_routes=zero_tuple,
        digest=digest,
        staging_route_contract_sha256=staging_route_contract_sha256,
        star_table_contract_sha256=star_table_contract_sha256,
        provider_authority_sha256=provider_authority_sha256,
        provider_field_occurrence_count=len(field_tuple),
        top_level_provider_field_occurrence_count=top_level_count,
        nested_projection_occurrence_count=nested_count,
        unique_provider_field_identity_count=identity_count,
        repeated_route_occurrence_count=len(field_tuple) - identity_count,
        storage_mapped_occurrence_count=mapped_count,
        storage_unmapped_occurrence_count=len(field_tuple) - mapped_count,
        unresolved_provider_field_occurrence_count=sum(
            not field.model_green for field in field_tuple
        ),
        source_family_counts=tuple(
            sorted(Counter(field.source_family for field in field_tuple).items())
        ),
        mapping_transform_counts=tuple(
            sorted(Counter(field.mapping_transform for field in field_tuple).items())
        ),
        storage_tier_counts=tuple(
            sorted(Counter(field.resolved_schema_tier for field in field_tuple).items())
        ),
        candidate_evidence_summary=candidate_summary,
        blocker_summary=blocker_summary,
        model_green=model_green,
        _by_occurrence_id=MappingProxyType({field.occurrence_id: field for field in field_tuple}),
    )


def _validate_bundle_structure(bundle: FieldFateContractBundle) -> None:
    if bundle.provider_field_occurrence_count != len(bundle.fields):
        raise FieldFateContractCompilationError(
            "field-fate occurrence count differs from its field inventory"
        )
    if len(bundle.fields) != EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT:
        raise FieldFateContractCompilationError(
            f"provider-field denominator is {len(bundle.fields)}; "
            f"expected {EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT}"
        )
    if tuple(field.occurrence_ordinal for field in bundle.fields) != tuple(
        range(len(bundle.fields))
    ):
        raise FieldFateContractCompilationError(
            "provider-field occurrence ordinals are not exact and contiguous"
        )
    occurrence_ids = tuple(field.occurrence_id for field in bundle.fields)
    if len(set(occurrence_ids)) != len(bundle.fields):
        raise FieldFateContractCompilationError("provider-field occurrence IDs are not unique")
    if dict(bundle.by_occurrence_id) != {field.occurrence_id: field for field in bundle.fields}:
        raise FieldFateContractCompilationError(
            "immutable provider-field occurrence index differs from inventory"
        )
    expected_counts = {
        "top_level": EXPECTED_TOP_LEVEL_PROVIDER_FIELD_OCCURRENCE_COUNT,
        "nested": EXPECTED_NESTED_PROJECTION_OCCURRENCE_COUNT,
        "unique": EXPECTED_UNIQUE_PROVIDER_FIELD_IDENTITY_COUNT,
        "repeated": EXPECTED_REPEATED_ROUTE_OCCURRENCE_COUNT,
        "mapped": EXPECTED_STORAGE_MAPPED_OCCURRENCE_COUNT,
        "unmapped": EXPECTED_STORAGE_UNMAPPED_OCCURRENCE_COUNT,
        "sinks": EXPECTED_STORAGE_ONLY_SINK_OCCURRENCE_COUNT,
        "zero_routes": EXPECTED_ZERO_FIELD_ROUTE_COUNT,
    }
    observed_counts = {
        "top_level": bundle.top_level_provider_field_occurrence_count,
        "nested": bundle.nested_projection_occurrence_count,
        "unique": bundle.unique_provider_field_identity_count,
        "repeated": bundle.repeated_route_occurrence_count,
        "mapped": bundle.storage_mapped_occurrence_count,
        "unmapped": bundle.storage_unmapped_occurrence_count,
        "sinks": len(bundle.storage_only_sinks),
        "zero_routes": len(bundle.zero_field_routes),
    }
    if observed_counts != expected_counts:
        raise FieldFateContractCompilationError(
            f"field-fate census differs from exact expectations: {observed_counts!r}"
        )
    expected_unresolved_count = sum(not field.model_green for field in bundle.fields)
    if bundle.unresolved_provider_field_occurrence_count != expected_unresolved_count:
        raise FieldFateContractCompilationError(
            "unresolved provider-field count differs from field decisions"
        )
    for field in bundle.fields:
        expected_field_green = (
            not field.blockers
            and not field.non_green_lineage_evidence
            and all(
                disposition.green
                for disposition in (
                    field.physical_disposition,
                    field.staging_disposition,
                    field.star_disposition,
                    field.model_disposition,
                    field.metric_disposition,
                )
            )
        )
        if field.model_green is not expected_field_green:
            raise FieldFateContractCompilationError(
                f"{field.occurrence_id} MODEL-GREEN decision conflicts with field evidence"
            )
    expected_model_green = not bundle.blocker_summary and all(
        field.model_green for field in bundle.fields
    )
    if bundle.model_green is not expected_model_green:
        raise FieldFateContractCompilationError(
            "field-fate MODEL-GREEN decision conflicts with field evidence"
        )
    expected_candidates = _candidate_summary(bundle.fields)
    if bundle.candidate_evidence_summary != expected_candidates:
        raise FieldFateContractCompilationError(
            "candidate-evidence summary differs from provider-field inventory"
        )
    expected_blockers = _blocker_summary(
        bundle.fields,
        bundle.storage_only_sinks,
        bundle.zero_field_routes,
    )
    if bundle.blocker_summary != expected_blockers:
        raise FieldFateContractCompilationError("blocker summary differs from field-fate inventory")

    summary: dict[str, object] = {
        "provider_field_occurrence_count": bundle.provider_field_occurrence_count,
        "top_level_provider_field_occurrence_count": (
            bundle.top_level_provider_field_occurrence_count
        ),
        "nested_projection_occurrence_count": bundle.nested_projection_occurrence_count,
        "unique_provider_field_identity_count": bundle.unique_provider_field_identity_count,
        "repeated_route_occurrence_count": bundle.repeated_route_occurrence_count,
        "storage_mapped_occurrence_count": bundle.storage_mapped_occurrence_count,
        "storage_unmapped_occurrence_count": bundle.storage_unmapped_occurrence_count,
        "storage_only_sink_occurrence_count": len(bundle.storage_only_sinks),
        "zero_field_route_count": len(bundle.zero_field_routes),
        "unresolved_provider_field_occurrence_count": (
            bundle.unresolved_provider_field_occurrence_count
        ),
        "source_family_counts": dict(bundle.source_family_counts),
        "mapping_transform_counts": dict(bundle.mapping_transform_counts),
        "storage_tier_counts": dict(bundle.storage_tier_counts),
        "candidate_evidence_summary": [
            {
                "kind": item.kind,
                "field_occurrence_count": item.field_occurrence_count,
                "target_count": item.target_count,
            }
            for item in bundle.candidate_evidence_summary
        ],
        "blocker_summary": [
            {
                "scope": item.scope,
                "code": item.code,
                "occurrence_count": item.occurrence_count,
            }
            for item in bundle.blocker_summary
        ],
        "model_green": bundle.model_green,
    }
    expected_digest = _sha256_json(
        _bundle_payload(
            fields=bundle.fields,
            storage_only_sinks=bundle.storage_only_sinks,
            zero_field_routes=bundle.zero_field_routes,
            staging_route_contract_sha256=bundle.staging_route_contract_sha256,
            star_table_contract_sha256=bundle.star_table_contract_sha256,
            provider_authority_sha256=bundle.provider_authority_sha256,
            summary=summary,
        )
    )
    if bundle.digest != expected_digest:
        raise FieldFateContractCompilationError("field-fate bundle digest is invalid")


def compile_field_fate_contracts() -> FieldFateContractBundle:
    """Compile every exact route-local provider field without inference."""
    try:
        route_bundle = staging_route_contract_bundle()
        validate_staging_route_contract_bundle(route_bundle)
        star_inventory = compile_star_table_contracts()
    except Exception as exc:
        if isinstance(exc, FieldFateContractCompilationError):
            raise
        raise FieldFateContractCompilationError(
            f"cannot load exact field-fate inputs: {type(exc).__name__}: {exc}"
        ) from exc

    if len(route_bundle.routes) != EXPECTED_STAGING_ROUTE_COUNT:
        raise FieldFateContractCompilationError(
            f"route inventory has {len(route_bundle.routes)} routes; "
            f"expected {EXPECTED_STAGING_ROUTE_COUNT}"
        )
    for route in route_bundle.routes:
        _validate_route_mapping(route)
    indexes = _build_candidate_indexes(star_inventory)

    fields: list[ProviderFieldFateContract] = []
    for route in route_bundle.routes:
        for route_field_ordinal in range(len(route.column_mappings)):
            fields.append(
                _compile_field(
                    occurrence_ordinal=len(fields),
                    route=route,
                    route_field_ordinal=route_field_ordinal,
                    indexes=indexes,
                )
            )
    bundle = _make_bundle(
        fields=fields,
        storage_only_sinks=_compile_storage_only_sinks(route_bundle.routes),
        zero_field_routes=_compile_zero_field_routes(route_bundle.routes),
        staging_route_contract_sha256=route_bundle.digest,
        star_table_contract_sha256=star_inventory.contract_sha256,
        provider_authority_sha256=route_bundle.provider_authority_sha256,
    )
    _validate_bundle_structure(bundle)
    return bundle


def validate_field_fate_contract_bundle(bundle: FieldFateContractBundle) -> None:
    """Validate structure, digest, and exact equality to current inputs."""
    _validate_bundle_structure(bundle)
    expected = compile_field_fate_contracts()
    if bundle != expected:
        raise FieldFateContractCompilationError(
            "field-fate bundle differs from exact current inputs"
        )


__all__ = [
    "EXPECTED_NESTED_PROJECTION_OCCURRENCE_COUNT",
    "EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT",
    "EXPECTED_REPEATED_ROUTE_OCCURRENCE_COUNT",
    "EXPECTED_STORAGE_MAPPED_OCCURRENCE_COUNT",
    "EXPECTED_STORAGE_ONLY_SINK_OCCURRENCE_COUNT",
    "EXPECTED_STORAGE_UNMAPPED_OCCURRENCE_COUNT",
    "EXPECTED_TOP_LEVEL_PROVIDER_FIELD_OCCURRENCE_COUNT",
    "EXPECTED_UNIQUE_PROVIDER_FIELD_IDENTITY_COUNT",
    "EXPECTED_ZERO_FIELD_ROUTE_COUNT",
    "FIELD_FATE_OWNER",
    "FIELD_FATE_REVALIDATION_PATH",
    "CandidateEvidenceSummary",
    "FieldFateBlockerSummary",
    "FieldFateContractBundle",
    "FieldFateContractCompilationError",
    "FieldLayerDisposition",
    "NonGreenLineageEvidence",
    "ProviderFieldFateContract",
    "StorageOnlySinkContract",
    "ZeroFieldRouteContract",
    "compile_field_fate_contracts",
    "validate_field_fate_contract_bundle",
]
