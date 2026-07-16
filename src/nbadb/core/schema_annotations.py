from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.core.field_docs import resolved_field_description
from nbadb.core.nba_api_contract import (
    build_nba_api_bronze_contracts_from_bundle,
    build_nba_api_upstream_contract_bundle,
)
from nbadb.extract.live.endpoints import (
    LIVE_NON_ANALYTIC_JSON_ROOTS,
    LIVE_PACKET_CONTRACTS,
    LIVE_PARAMETER_FIELD_ROUTES,
    LIVE_RAW_ONLY_REFERENCE_JSON_PATHS,
)
from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.schemas.base import BaseSchema
from nbadb.schemas.consumer_metadata import infer_consumer_metadata
from nbadb.schemas.registry import (
    _raw_schema_registry,
    _staging_schema_registry,
    _star_schema_registry,
    get_input_schema,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

Tier = Literal["raw", "staging", "star"]
RawFate = Literal[
    "staged_same_name",
    "staged_renamed",
    "staged_normalized",
    "staged_json_payload",
    "raw_only_open_passthrough",
    "raw_only_reference",
    "gold_direct",
    "gold_derived",
    "gold_aggregate",
    "gold_dimension_attribute",
    "gold_bridge_key",
    "excluded_upstream_unavailable",
    "excluded_duplicate_alias",
    "excluded_non_analytic_payload",
    "excluded_deprecated_or_superseded",
    "blocked_needs_contract_work",
]

ARTIFACT_FILENAMES = {
    "raw_silver_gold_field_fate": "raw-silver-gold-field-fate.json",
    "silver_gold_feature_inventory": "silver-gold-feature-inventory.json",
    "staging_route_inventory": "staging-route-inventory.json",
    "schema_helper_reconciliation": "schema-helper-reconciliation.json",
    "schema_annotation_audit": "schema-annotation-audit.json",
    "silver_gold_column_category_summary": "silver-gold-column-category-summary.json",
}

_CAMEL_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")
_NON_WORD_RE = re.compile(r"[^a-zA-Z0-9]+")

_IDENTITY_TERMS = (
    "id",
    "sk",
    "key",
    "person",
    "player",
    "team",
    "game",
    "event",
    "action",
    "lineup",
    "official",
    "arena",
    "draft",
    "video",
)
_TIME_TERMS = (
    "season",
    "year",
    "date",
    "time",
    "period",
    "clock",
    "status",
    "location",
    "home",
    "away",
    "conference",
    "division",
    "playoff",
    "ist",
    "month",
    "day",
)
_DESCRIPTOR_TERMS = (
    "name",
    "abbr",
    "abbreviation",
    "tricode",
    "slug",
    "city",
    "state",
    "country",
    "position",
    "jersey",
    "school",
    "college",
    "organization",
    "arena",
    "broadcaster",
    "title",
)
_BOX_SCORE_TERMS = (
    "efg",
    "effective_field_goal",
    "field_goal",
    "point",
    "points",
    "pts",
    "fg",
    "fgm",
    "fga",
    "fg3",
    "fg3m",
    "fg3a",
    "free_throw",
    "ft",
    "ftm",
    "fta",
    "rebound",
    "reb",
    "rebounds",
    "assist",
    "assists",
    "oreb",
    "dreb",
    "ast",
    "steal",
    "steals",
    "stl",
    "block",
    "blocks",
    "blk",
    "turnover",
    "turnovers",
    "tov",
    "pf",
    "plus_minus",
    "rating",
    "pace",
    "usage",
    "usg",
    "hustle",
    "fantasy",
)
_SHOT_TERMS = (
    "shot",
    "zone",
    "loc",
    "loc_x",
    "loc_y",
    "distance",
    "made",
    "missed",
    "blocked",
    "assisted",
)
_PLAY_LIVE_TERMS = (
    "play",
    "pbp",
    "live",
    "score",
    "scoreboard",
    "leader",
    "odds",
    "ticket",
    "line_score",
    "video",
    "broadcast",
)
_SCHEDULE_TERMS = (
    "schedule",
    "standing",
    "record",
    "win",
    "wins",
    "loss",
    "losses",
    "streak",
    "rank",
    "seed",
    "clinch",
    "elimination",
    "series",
    "week",
)
_DRAFT_TERMS = (
    "draft",
    "combine",
    "pick",
    "round",
    "height",
    "weight",
    "wingspan",
    "standing_reach",
    "drill",
    "vertical",
    "lane_agility",
)
_MATCHUP_TERMS = (
    "matchup",
    "on_off",
    "onoff",
    "lineup",
    "group",
    "vs",
    "opponent",
    "pass",
    "rebound",
)
_OPERATIONAL_TERMS = (
    "load",
    "loaded",
    "updated",
    "created",
    "source",
    "audit",
    "checksum",
    "hash",
    "row",
    "ingested",
)
_BOX_SCORE_COMPOUND_TERMS = (
    "effective_field_goal",
    "field_goal",
    "free_throw",
    "turnover",
    "offensive_rebound",
    "defensive_rebound",
)
_USEFUL_STAT_TERMS = frozenset(
    {
        "point",
        "points",
        "pts",
        "assist",
        "assists",
        "ast",
        "rebound",
        "rebounds",
        "reb",
        "steal",
        "steals",
        "stl",
        "block",
        "blocks",
        "blk",
        "turnover",
        "turnovers",
        "tov",
        "win",
        "wins",
        "w",
        "loss",
        "losses",
        "l",
    }
)
_SOURCE_LINEAGE_IGNORED_PREFIXES = ("audit.", "derived.", "literal.", "schema_registry.")
_PLAYER_CAREER_REGULAR_MIRROR_COLUMNS = frozenset({"reb", "ast", "stl", "blk", "tov", "pts"})


def _camel_to_snake(name: str) -> str:
    interim = _CAMEL_RE_1.sub(r"\1_\2", name)
    return _CAMEL_RE_2.sub(r"\1_\2", interim).lower()


def _normalized_name(name: object) -> str:
    return _NON_WORD_RE.sub("_", str(name).strip().lower()).strip("_")


def _metadata_source_value(source: object) -> str:
    if isinstance(source, (list, tuple)):
        source = source[0] if source else ""
    return str(source or "").strip()


def _source_lineage_key(source: object) -> tuple[str, str, str] | None:
    source_value = _metadata_source_value(source)
    if not source_value or source_value.startswith(_SOURCE_LINEAGE_IGNORED_PREFIXES):
        return None
    parts = [part for part in source_value.split(".") if part]
    if len(parts) < 3:
        return None
    endpoint, result_set, source_column = parts[0], parts[1], parts[-1]
    return (
        _normalized_name(endpoint),
        _normalized_name(result_set),
        _normalized_name(source_column),
    )


def _contract_lineage_key(
    *,
    endpoint: object,
    result_set_name: object,
    column_name: object,
) -> tuple[str, str, str] | None:
    endpoint_name = _normalized_name(endpoint)
    result_set = _normalized_name(result_set_name)
    source_column = _normalized_name(column_name)
    if not endpoint_name or not result_set or not source_column:
        return None
    return endpoint_name, result_set, source_column


def _is_useful_source_field(column_name: object) -> bool:
    normalized = _normalized_name(column_name)
    if not normalized:
        return False
    tokens = set(normalized.split("_"))
    padded = f"_{normalized}_"
    return any(
        term == normalized or term in tokens or ("_" in term and f"_{term}_" in padded)
        for term in _USEFUL_STAT_TERMS
    )


def _schema_table_name_from_member(member_name: str) -> str:
    name = member_name.removesuffix("Schema").removesuffix("Model")
    return _camel_to_snake(name)


def _schema_doc(schema_cls: type[BaseSchema]) -> str:
    return " ".join((schema_cls.__doc__ or "").split())


def _schema_for_tier(tier: Tier) -> dict[str, type[BaseSchema]]:
    if tier == "raw":
        return _raw_schema_registry()
    if tier == "staging":
        return _staging_schema_registry()
    return _star_schema_registry()


def _schema_columns_for_tier(tier: Tier) -> dict[str, set[str]]:
    return {
        table_name: set(schema_cls.to_schema().columns)
        for table_name, schema_cls in _schema_for_tier(tier).items()
    }


def _valid_staging_alias_ref(
    *,
    fk_target_table: str,
    fk_target_column: str,
    staging_columns: dict[str, set[str]],
) -> bool:
    if not fk_target_table.startswith("staging_") or not fk_target_column:
        return False
    alias_token = fk_target_table.removeprefix("staging_")
    alias_variants = {alias_token, f"{alias_token}s"}
    return any(
        fk_target_column in columns
        and any(
            table_name == f"stg_{variant}"
            or table_name.endswith(f"_{variant}")
            or f"_{variant}_" in table_name
            for variant in alias_variants
        )
        for table_name, columns in staging_columns.items()
    )


def _column_type(column: Any) -> str:
    dtype = getattr(column, "dtype", None)
    return str(dtype) if dtype else "unknown"


def _semantic_category(
    *,
    tier: str,
    table_name: str,
    column_name: str,
    metadata: dict[str, Any],
) -> tuple[str, list[str]]:
    name = _normalized_name(column_name)
    table = _normalized_name(table_name)
    column_tokens = set(name.split("_")) if name else set()
    context_tokens = set(f"{table}_{name}".split("_")) if table or name else set()
    tags: list[str] = []

    def has_column_any(terms: Iterable[str]) -> bool:
        padded_name = f"_{name}_"
        return any(
            term == name or term in column_tokens or ("_" in term and f"_{term}_" in padded_name)
            for term in terms
        )

    def has_context_any(terms: Iterable[str]) -> bool:
        return any(term == name or term in context_tokens for term in terms)

    if has_column_any(_OPERATIONAL_TERMS):
        primary = "operational_fields"
    elif (
        name.endswith("_id")
        or name.endswith("_sk")
        or name in {"id", "key"}
        or {"id", "sk", "key"} & column_tokens
    ):
        primary = "identity_and_join_keys"
    elif has_column_any(_DRAFT_TERMS):
        primary = "draft_combine_features"
    elif has_column_any(_BOX_SCORE_COMPOUND_TERMS):
        primary = "box_score_measures"
    elif has_column_any(_MATCHUP_TERMS):
        primary = "matchup_on_off_lineup_features"
    elif has_column_any(_SHOT_TERMS):
        primary = "shot_and_spatial_features"
    elif has_column_any(_SCHEDULE_TERMS):
        primary = "schedule_standings_playoff_features"
    elif has_column_any(_BOX_SCORE_TERMS):
        primary = "box_score_measures"
    elif has_column_any(_PLAY_LIVE_TERMS):
        primary = "play_live_features"
    elif has_column_any(_TIME_TERMS):
        primary = "time_and_context"
    elif has_column_any(_DESCRIPTOR_TERMS):
        primary = "entity_descriptors"
    elif (tier == "star" and table_name.startswith(("agg_", "analytics_"))) or str(
        metadata.get("source") or ""
    ).startswith("derived."):
        primary = "derived_gold_features"
    else:
        primary = "entity_descriptors"

    for label, terms in (
        ("identity", _IDENTITY_TERMS),
        ("time", _TIME_TERMS),
        ("descriptor", _DESCRIPTOR_TERMS),
        ("box_score", _BOX_SCORE_TERMS),
        ("shot", _SHOT_TERMS),
        ("play_live", _PLAY_LIVE_TERMS),
        ("schedule", _SCHEDULE_TERMS),
        ("draft_combine", _DRAFT_TERMS),
        ("matchup", _MATCHUP_TERMS),
        ("operational", _OPERATIONAL_TERMS),
    ):
        if has_context_any(terms):
            tags.append(label)

    if metadata.get("fk_ref"):
        tags.append("foreign_key")
    if str(metadata.get("source") or "").startswith("derived."):
        tags.append("derived")
    return primary, sorted(set(tags))


def _source_kind(source: str, fk_ref: str) -> str:
    if source.startswith("derived."):
        return "derived_expression"
    if source.startswith("literal."):
        return "literal"
    if source.startswith("audit."):
        return "audit"
    if source:
        return "upstream_field"
    if fk_ref:
        return "foreign_key"
    return "schema_field"


def _lineage_source(tier: str, table_name: str, column_name: str, source: str, fk_ref: str) -> str:
    if source:
        return source
    if fk_ref:
        return fk_ref
    return f"schema_registry.{tier}.{table_name}.{column_name}"


def _table_family(table_name: str) -> str:
    for prefix in ("raw_", "stg_", "dim_", "fact_", "bridge_", "agg_", "analytics_"):
        if table_name.startswith(prefix):
            return prefix.rstrip("_")
    return "other"


def _grain_for_table(
    tier: str,
    table_name: str,
    staging_route_index: dict[str, list[dict[str, Any]]],
) -> str:
    if tier == "star":
        consumer = infer_consumer_metadata(table_name, schema_doc="")
        grain = consumer.get("grain")
        return str(grain) if grain else _table_family(table_name)
    if tier == "staging":
        patterns = sorted(
            {
                str(route["param_pattern"])
                for route in staging_route_index.get(table_name, [])
                if route.get("param_pattern")
            }
        )
        if patterns:
            return "staging-" + "-or-".join(patterns)
        return "staging-schema"
    return "raw-schema"


def _field_entries(
    *,
    tier: Tier,
    table_name: str,
    schema_cls: type[BaseSchema],
    staging_route_index: dict[str, list[dict[str, Any]]],
    star_tables: set[str],
) -> list[dict[str, Any]]:
    schema = schema_cls.to_schema()
    star_columns = _schema_columns_for_tier("star")
    staging_columns = _schema_columns_for_tier("staging")
    raw_columns = _schema_columns_for_tier("raw")
    entries: list[dict[str, Any]] = []
    for column_name, column in schema.columns.items():
        metadata = dict(getattr(column, "metadata", {}) or {})
        source = str(metadata.get("source") or "")
        fk_ref = str(metadata.get("fk_ref") or "")
        description, description_source = resolved_field_description(
            metadata.get("description"),
            column_name,
            table_name=table_name,
            tier=tier,
        )
        semantic_primary, semantic_tags = _semantic_category(
            tier=tier,
            table_name=table_name,
            column_name=column_name,
            metadata=metadata,
        )
        fk_target_table, _, fk_target_column = fk_ref.partition(".")
        normalized_fk_target_table = (
            f"stg_{fk_target_table.removeprefix('staging_')}"
            if fk_target_table.startswith("staging_")
            else fk_target_table
        )
        if not fk_ref:
            fk_ref_scope = ""
            valid_fk_ref = True
        elif fk_target_table in star_tables:
            fk_ref_scope = "star"
            valid_fk_ref = bool(
                fk_target_column and fk_target_column in star_columns.get(fk_target_table, set())
            )
        elif tier == "staging" and fk_target_table.startswith("staging_"):
            fk_ref_scope = "staging_alias_hint"
            valid_fk_ref = _valid_staging_alias_ref(
                fk_target_table=fk_target_table,
                fk_target_column=fk_target_column,
                staging_columns=staging_columns,
            )
        elif tier == "staging" and normalized_fk_target_table.startswith("stg_"):
            fk_ref_scope = "staging_hint"
            valid_fk_ref = bool(
                fk_target_column
                and fk_target_column in staging_columns.get(normalized_fk_target_table, set())
            )
        elif tier == "staging" and fk_target_table.startswith("raw_"):
            fk_ref_scope = "raw_hint"
            valid_fk_ref = bool(
                fk_target_column and fk_target_column in raw_columns.get(fk_target_table, set())
            )
        else:
            fk_ref_scope = "unresolved"
            valid_fk_ref = False
        source_kind = _source_kind(source, fk_ref)
        entries.append(
            {
                "tier": tier,
                "table_name": table_name,
                "table_family": _table_family(table_name),
                "schema_class": schema_cls.__name__,
                "column_name": column_name,
                "type": _column_type(column),
                "nullable": bool(getattr(column, "nullable", False)),
                "description": description,
                "description_source": description_source,
                "semantic_primary": semantic_primary,
                "semantic_tags": semantic_tags,
                "source": source,
                "source_kind": source_kind,
                "lineage_source": _lineage_source(tier, table_name, column_name, source, fk_ref),
                "lineage_status": "metadata" if source or fk_ref else "schema_inferred",
                "fk_ref": fk_ref,
                "fk_ref_scope": fk_ref_scope,
                "fk_target_table": fk_target_table,
                "fk_target_column": fk_target_column,
                "valid_fk_ref": valid_fk_ref,
                "grain": _grain_for_table(tier, table_name, staging_route_index),
                "relevance": f"public_{tier}_contract",
                "is_identifier": column_name.endswith(("_id", "_sk")) or column_name == "id",
                "is_join_key": bool(fk_ref) or column_name.endswith(("_id", "_sk")),
                "is_measure": semantic_primary
                in {
                    "box_score_measures",
                    "shot_and_spatial_features",
                    "derived_gold_features",
                    "schedule_standings_playoff_features",
                    "draft_combine_features",
                },
            }
        )
    return entries


def _schema_table_by_class_id() -> dict[int, tuple[str, str]]:
    mapping: dict[int, tuple[str, str]] = {}
    for tier in ("raw", "staging", "star"):
        for table_name, schema_cls in _schema_for_tier(tier).items():
            mapping[id(schema_cls)] = (tier, table_name)
    return mapping


def _resolved_input_schema_table(
    schema_cls: type[BaseSchema] | None,
) -> tuple[str | None, str | None]:
    if schema_cls is None:
        return None, None
    for table_name, candidate in _staging_schema_registry().items():
        if candidate is schema_cls:
            return "staging", table_name
    for table_name, candidate in _raw_schema_registry().items():
        if candidate is schema_cls:
            return "raw", table_name
    return None, None


def _staging_route_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal, entry in enumerate(STAGING_MAP):
        schema_cls = get_input_schema(entry.staging_key)
        resolved_tier, resolved_table = _resolved_input_schema_table(schema_cls)
        schema = schema_cls.to_schema() if schema_cls is not None else None
        route_status = "unresolved"
        if resolved_table == entry.staging_key:
            route_status = f"direct_{resolved_tier}"
        elif resolved_table is not None:
            route_status = f"alias_to_{resolved_tier}"
        rows.append(
            {
                "route_id": f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}",
                "ordinal": ordinal,
                "endpoint_name": entry.endpoint_name,
                "staging_key": entry.staging_key,
                "param_pattern": entry.param_pattern,
                "result_set_index": entry.result_set_index,
                "use_multi": entry.use_multi,
                "deprecated_after": entry.deprecated_after,
                "min_season": entry.min_season,
                "season_type_capability": entry.season_type_capability,
                "supported_season_types": list(entry.supported_season_types or ()),
                "allow_missing_result_set": entry.allow_missing_result_set,
                "resolved_schema_tier": resolved_tier,
                "resolved_schema_table": resolved_table,
                "resolved_schema_class": schema_cls.__name__ if schema_cls else None,
                "route_status": route_status,
                "column_count": len(schema.columns) if schema is not None else 0,
            }
        )
    return rows


def _staging_route_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        resolved_table = row.get("resolved_schema_table")
        if isinstance(resolved_table, str):
            index[resolved_table].append(row)
    return dict(index)


def _raw_schema_staging_route_index() -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for entry in STAGING_MAP:
        schema_cls = get_input_schema(entry.staging_key)
        resolved_tier, resolved_table = _resolved_input_schema_table(schema_cls)
        if resolved_tier == "raw" and resolved_table:
            index[resolved_table].add(entry.staging_key)

    try:
        from nbadb.orchestrate.live_snapshot import _LIVE_RAW_SCHEMA_BY_STAGING_KEY
    except ImportError:
        return dict(index)

    for staging_key, raw_table in _LIVE_RAW_SCHEMA_BY_STAGING_KEY.items():
        index[raw_table].add(staging_key)
    return dict(index)


def _gold_fate(table_name: str) -> RawFate:
    if table_name.startswith("agg_"):
        return "gold_aggregate"
    if table_name.startswith("dim_"):
        return "gold_dimension_attribute"
    if table_name.startswith("bridge_"):
        return "gold_bridge_key"
    return "gold_direct"


def _field_fate(
    column_name: str,
    *,
    staging_columns_by_name: dict[str, set[str]],
    star_columns_by_name: dict[str, set[str]],
    normalized_staging: dict[str, set[str]],
    normalized_star: dict[str, set[str]],
    staging_by_source: dict[tuple[str, str, str], set[str]],
    star_by_source: dict[tuple[str, str, str], set[str]],
    source_key: tuple[str, str, str] | None,
) -> dict[str, Any]:
    same_name_staging = sorted(staging_columns_by_name.get(column_name, set()))
    same_name_star = sorted(star_columns_by_name.get(column_name, set()))
    normalized = _normalized_name(column_name)
    normalized_staging_tables = sorted(normalized_staging.get(normalized, set()))
    normalized_star_tables = sorted(normalized_star.get(normalized, set()))
    candidate_staging_tables = same_name_staging or normalized_staging_tables
    candidate_star_tables = same_name_star or normalized_star_tables

    verified_staging_tables = sorted(staging_by_source.get(source_key, set())) if source_key else []
    verified_star_tables = sorted(star_by_source.get(source_key, set())) if source_key else []

    if verified_staging_tables:
        if _tables_with_column(verified_staging_tables, staging_columns_by_name, column_name):
            fate: RawFate = "staged_same_name"
        elif _tables_with_normalized_column(
            verified_staging_tables,
            normalized_staging,
            column_name,
        ):
            fate = "staged_normalized"
        else:
            fate = "staged_renamed"
        return {
            "fate": fate,
            "candidate_staging_tables": candidate_staging_tables,
            "candidate_star_tables": candidate_star_tables,
            "verified_staging_tables": verified_staging_tables,
            "verified_star_tables": verified_star_tables,
            "lineage_match_status": "verified",
            "lineage_match_basis": "source_metadata",
        }
    if verified_star_tables:
        return {
            "fate": _gold_fate(verified_star_tables[0]),
            "candidate_staging_tables": candidate_staging_tables,
            "candidate_star_tables": candidate_star_tables,
            "verified_staging_tables": verified_staging_tables,
            "verified_star_tables": verified_star_tables,
            "lineage_match_status": "verified",
            "lineage_match_basis": "source_metadata",
        }
    if same_name_staging:
        fate = "staged_same_name"
        match_basis = "global_same_name"
    elif normalized_staging_tables:
        fate = "staged_normalized"
        match_basis = "global_normalized_name"
    elif same_name_star:
        fate = _gold_fate(same_name_star[0])
        match_basis = "global_same_name"
    elif normalized_star_tables:
        fate = _gold_fate(normalized_star_tables[0])
        match_basis = "global_normalized_name"
    else:
        if "payload" in normalized or "json" in normalized:
            fate = "raw_only_open_passthrough"
            match_status = "classified"
            match_basis = "payload_or_json_name"
        else:
            fate = "raw_only_reference"
            match_status = "unresolved"
            match_basis = "no_lineage_match"
        return {
            "fate": fate,
            "candidate_staging_tables": candidate_staging_tables,
            "candidate_star_tables": candidate_star_tables,
            "verified_staging_tables": verified_staging_tables,
            "verified_star_tables": verified_star_tables,
            "lineage_match_status": match_status,
            "lineage_match_basis": match_basis,
        }

    return {
        "fate": fate,
        "candidate_staging_tables": candidate_staging_tables,
        "candidate_star_tables": candidate_star_tables,
        "verified_staging_tables": verified_staging_tables,
        "verified_star_tables": verified_star_tables,
        "lineage_match_status": "candidate_unverified",
        "lineage_match_basis": match_basis,
    }


def _column_indexes(
    tiers: Iterable[Tier],
) -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    staging_columns_by_name: dict[str, set[str]] = defaultdict(set)
    star_columns_by_name: dict[str, set[str]] = defaultdict(set)
    normalized_staging: dict[str, set[str]] = defaultdict(set)
    normalized_star: dict[str, set[str]] = defaultdict(set)

    if "staging" in tiers:
        for table_name, schema_cls in _staging_schema_registry().items():
            for column_name in schema_cls.to_schema().columns:
                staging_columns_by_name[column_name].add(table_name)
                normalized_staging[_normalized_name(column_name)].add(table_name)
    if "star" in tiers:
        for table_name, schema_cls in _star_schema_registry().items():
            for column_name in schema_cls.to_schema().columns:
                star_columns_by_name[column_name].add(table_name)
                normalized_star[_normalized_name(column_name)].add(table_name)
    return (
        dict(staging_columns_by_name),
        dict(star_columns_by_name),
        dict(normalized_staging),
        dict(normalized_star),
    )


def _source_lineage_indexes(
    tiers: Iterable[Tier],
) -> tuple[dict[tuple[str, str, str], set[str]], dict[tuple[str, str, str], set[str]]]:
    staging_by_source: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    star_by_source: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    if "staging" in tiers:
        for table_name, schema_cls in _staging_schema_registry().items():
            for column in schema_cls.to_schema().columns.values():
                metadata = dict(getattr(column, "metadata", {}) or {})
                source_key = _source_lineage_key(metadata.get("source"))
                if source_key is not None:
                    staging_by_source[source_key].add(table_name)
    if "star" in tiers:
        for table_name, schema_cls in _star_schema_registry().items():
            for column in schema_cls.to_schema().columns.values():
                metadata = dict(getattr(column, "metadata", {}) or {})
                source_key = _source_lineage_key(metadata.get("source"))
                if source_key is not None:
                    star_by_source[source_key].add(table_name)
    return dict(staging_by_source), dict(star_by_source)


def _tables_with_column(
    tables: Iterable[str],
    columns_by_name: dict[str, set[str]],
    column_name: str,
) -> set[str]:
    candidate_tables = columns_by_name.get(column_name, set())
    return set(tables) & candidate_tables


def _tables_with_normalized_column(
    tables: Iterable[str],
    normalized_columns: dict[str, set[str]],
    column_name: str,
) -> set[str]:
    candidate_tables = normalized_columns.get(_normalized_name(column_name), set())
    return set(tables) & candidate_tables


def _apply_raw_route_fate(
    fate_match: dict[str, Any],
    *,
    route_staging_tables: Iterable[str],
) -> dict[str, Any]:
    routed_tables = sorted(set(route_staging_tables))
    if not routed_tables:
        return fate_match

    updated = dict(fate_match)
    updated["fate"] = "staged_same_name"
    updated["candidate_staging_tables"] = sorted(
        {*fate_match.get("candidate_staging_tables", []), *routed_tables}
    )
    updated["verified_staging_tables"] = sorted(
        {*fate_match.get("verified_staging_tables", []), *routed_tables}
    )
    updated["lineage_match_status"] = "verified"
    updated["lineage_match_basis"] = "raw_input_schema_route"
    return updated


def _raw_fate_classification(source_table: str, source_column: str) -> dict[str, Any] | None:
    if source_table == "raw_box_score_advanced_player" and source_column == "tm_tov_pct":
        return {
            "fate": "staged_renamed",
            "lineage_match_status": "classified",
            "lineage_match_basis": "known_legacy_alias",
            "classification_reason": (
                "Legacy raw BoxScoreAdvancedV3 player TM_TOV_PCT is represented downstream "
                "as player turnover percentage tov_pct."
            ),
            "classified_staging_columns": [
                {"table_name": "stg_box_score_advanced_player", "column_name": "tov_pct"}
            ],
            "classified_star_columns": [
                {"table_name": "fact_player_game_advanced", "column_name": "tov_pct"}
            ],
        }
    if (
        source_table == "raw_player_career_stats"
        and source_column in _PLAYER_CAREER_REGULAR_MIRROR_COLUMNS
    ):
        return {
            "fate": "staged_same_name",
            "lineage_match_status": "classified",
            "lineage_match_basis": "known_player_career_regular_route",
            "classification_reason": (
                "Legacy raw PlayerCareerStats SeasonTotalsRegularSeason mirrors the "
                "registered stg_player_career_regular result-set route."
            ),
            "verified_staging_tables": ["stg_player_career_regular"],
            "classified_star_columns": [
                {"table_name": "fact_player_career", "column_name": source_column}
            ],
        }
    return None


def _apply_raw_fate_classification(
    fate_match: dict[str, Any],
    classification: dict[str, Any] | None,
) -> dict[str, Any]:
    if not classification or fate_match.get("lineage_match_status") == "verified":
        return fate_match

    updated = dict(fate_match)
    for key, value in classification.items():
        if key == "verified_staging_tables":
            updated[key] = sorted({*fate_match.get(key, []), *value})
        else:
            updated[key] = value
    return updated


def _fate_requires_followup(
    *,
    source_column: object,
    fate: RawFate,
    lineage_match_status: str,
) -> bool:
    if fate == "blocked_needs_contract_work":
        return True
    if lineage_match_status not in {"candidate_unverified", "unresolved"}:
        return False
    return _is_useful_source_field(source_column)


def _raw_schema_fate_rows(tiers: Iterable[Tier]) -> list[dict[str, Any]]:
    (
        staging_columns_by_name,
        star_columns_by_name,
        normalized_staging,
        normalized_star,
    ) = _column_indexes(tiers)
    staging_by_source, star_by_source = _source_lineage_indexes(tiers)
    raw_route_index = _raw_schema_staging_route_index() if "staging" in tiers else {}
    rows: list[dict[str, Any]] = []
    for table_name, schema_cls in sorted(_raw_schema_registry().items()):
        schema = schema_cls.to_schema()
        for ordinal, (column_name, column) in enumerate(schema.columns.items()):
            metadata = dict(getattr(column, "metadata", {}) or {})
            source = _metadata_source_value(metadata.get("source"))
            source_key = _source_lineage_key(source)
            fate_match = _field_fate(
                column_name,
                staging_columns_by_name=staging_columns_by_name,
                star_columns_by_name=star_columns_by_name,
                normalized_staging=normalized_staging,
                normalized_star=normalized_star,
                staging_by_source=staging_by_source,
                star_by_source=star_by_source,
                source_key=source_key,
            )
            fate_match = _apply_raw_route_fate(
                fate_match,
                route_staging_tables=raw_route_index.get(table_name, set()),
            )
            fate_match = _apply_raw_fate_classification(
                fate_match,
                classification=_raw_fate_classification(table_name, column_name),
            )
            fate = fate_match["fate"]
            rows.append(
                {
                    "source_layer": "raw_schema",
                    "source_table": table_name,
                    "source_column": column_name,
                    "ordinal": ordinal,
                    "source": source,
                    "source_lineage_key": ".".join(source_key) if source_key else "",
                    **fate_match,
                    "requires_followup": _fate_requires_followup(
                        source_column=column_name,
                        fate=fate,
                        lineage_match_status=str(fate_match["lineage_match_status"]),
                    ),
                }
            )
    return rows


def _stats_route_index(
    provenance: dict[str, Any] | None,
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for route in (provenance or {}).get("routes", []):
        route_key = _contract_lineage_key(
            endpoint=route.get("runtime_class_name"),
            result_set_name=route.get("source_result_set_name"),
            column_name=route.get("source_column"),
        )
        if route_key is not None:
            index[route_key].append(route)
    return dict(index)


def _routed_column_fate(source_column: str, routed_column: str) -> RawFate:
    if source_column == routed_column:
        return "staged_same_name"
    if _camel_to_snake(source_column) == routed_column:
        return "staged_normalized"
    return "staged_renamed"


def _apply_stats_contract_route_fate(
    fate_match: dict[str, Any],
    *,
    source_column: str,
    route_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not route_rows:
        return fate_match

    updated = dict(fate_match)
    route_statuses = sorted({str(route.get("route_status") or "missing") for route in route_rows})
    staging_tables = sorted(
        {str(route["staging_key"]) for route in route_rows if route.get("staging_key")}
    )
    updated["candidate_staging_tables"] = sorted(
        {*fate_match.get("candidate_staging_tables", []), *staging_tables}
    )
    updated["contract_route_statuses"] = route_statuses
    updated["contract_route_endpoint_names"] = sorted(
        {str(route["endpoint_name"]) for route in route_rows if route.get("endpoint_name")}
    )
    updated["contract_route_result_set_names"] = sorted(
        {
            str(route["source_result_set_name"])
            for route in route_rows
            if route.get("source_result_set_name")
        }
    )
    updated["contract_route_result_set_indices"] = sorted(
        {
            int(route["source_result_set_index"])
            for route in route_rows
            if route.get("source_result_set_index") is not None
        }
    )
    updated["contract_route_declared_result_set_indices"] = sorted(
        {
            int(route["declared_result_set_index"])
            for route in route_rows
            if route.get("declared_result_set_index") is not None
        }
    )

    blocking_statuses = {"missing_input_schema", "missing_sink"}
    if blocking_statuses.intersection(route_statuses):
        updated.update(
            {
                "fate": "blocked_needs_contract_work",
                "lineage_match_status": "unresolved",
                "lineage_match_basis": "runtime_contract_route_gap",
                "classification_reason": (
                    "The authoritative runtime field route has no declared or open staging sink."
                ),
            }
        )
        return updated

    routed_columns = {
        str(route["normalized_column"]) for route in route_rows if route.get("normalized_column")
    }
    if len(routed_columns) != 1:
        updated.update(
            {
                "fate": "blocked_needs_contract_work",
                "lineage_match_status": "unresolved",
                "lineage_match_basis": "runtime_contract_route_ambiguous",
                "classification_reason": (
                    "The authoritative runtime field routes disagree on the normalized column."
                ),
            }
        )
        return updated

    routed_column = routed_columns.pop()
    schema_behaviors = sorted(
        {str(route.get("schema_behavior") or "missing") for route in route_rows}
    )
    updated.update(
        {
            "fate": _routed_column_fate(source_column, routed_column),
            "verified_staging_tables": staging_tables,
            "lineage_match_status": "verified",
            "lineage_match_basis": (
                "runtime_contract_open_schema_route"
                if "open_passthrough" in route_statuses
                else "runtime_contract_declared_route"
            ),
            "schema_behaviors": schema_behaviors,
            "classified_staging_columns": [
                {"table_name": table_name, "column_name": routed_column}
                for table_name in staging_tables
            ],
        }
    )
    return updated


def _apply_superseded_stats_fate(
    fate_match: dict[str, Any],
    *,
    endpoint: object,
    superseded_runtime_classes: dict[str, str],
) -> dict[str, Any]:
    endpoint_name = str(endpoint or "")
    superseded_by = superseded_runtime_classes.get(endpoint_name)
    if superseded_by is None or fate_match.get("lineage_match_status") == "verified":
        return fate_match

    updated = dict(fate_match)
    updated.update(
        {
            "fate": "excluded_deprecated_or_superseded",
            "verified_staging_tables": [],
            "verified_star_tables": [],
            "lineage_match_status": "classified",
            "lineage_match_basis": "runtime_class_superseded",
            "superseded_by_runtime_class": superseded_by,
            "classification_reason": (
                f"{endpoint_name} is superseded by the authoritative runtime alias {superseded_by}."
            ),
        }
    )
    return updated


def _path_is_within(json_path: str, json_root: str) -> bool:
    return json_path == json_root or json_path.startswith(f"{json_root}.")


def _live_packet_for_path(endpoint: str, json_path: str) -> Any | None:
    matching_packets = [
        packet
        for packet in LIVE_PACKET_CONTRACTS
        if packet.upstream_endpoint == endpoint and _path_is_within(json_path, packet.json_root)
    ]
    if not matching_packets:
        return None
    return max(matching_packets, key=lambda packet: len(packet.json_root))


def _live_typed_fate(
    fate_match: dict[str, Any],
    *,
    source_column: str,
    target_column: str,
    staging_key: str,
    star_tables: Iterable[str],
    staging_columns: dict[str, set[str]],
    star_columns: dict[str, set[str]],
    lineage_match_basis: str,
    json_root: str | None = None,
) -> dict[str, Any]:
    updated = dict(fate_match)
    if target_column not in staging_columns.get(staging_key, set()):
        updated.update(
            {
                "fate": "blocked_needs_contract_work",
                "lineage_match_status": "unresolved",
                "lineage_match_basis": "live_typed_projection_missing_staging_column",
                "classification_reason": (
                    f"The live route projects {source_column} to missing column "
                    f"{staging_key}.{target_column}."
                ),
            }
        )
        return updated

    verified_star_tables = sorted(
        table_name
        for table_name in star_tables
        if target_column in star_columns.get(table_name, set())
    )
    updated.update(
        {
            "fate": _routed_column_fate(source_column, target_column),
            "candidate_staging_tables": sorted(
                {*fate_match.get("candidate_staging_tables", []), staging_key}
            ),
            "candidate_star_tables": sorted(
                {*fate_match.get("candidate_star_tables", []), *verified_star_tables}
            ),
            "verified_staging_tables": [staging_key],
            "verified_star_tables": verified_star_tables,
            "lineage_match_status": "verified",
            "lineage_match_basis": lineage_match_basis,
            "representation_column": target_column,
            "classified_staging_columns": [
                {"table_name": staging_key, "column_name": target_column}
            ],
            "classified_star_columns": [
                {"table_name": table_name, "column_name": target_column}
                for table_name in verified_star_tables
            ],
        }
    )
    if json_root is not None:
        updated["packet_json_root"] = json_root
    return updated


def _apply_live_contract_fate(
    fate_match: dict[str, Any],
    *,
    endpoint: object,
    source_column: str,
    json_path: object,
    staging_columns: dict[str, set[str]],
    star_columns: dict[str, set[str]],
) -> dict[str, Any]:
    endpoint_name = str(endpoint or "")
    path = str(json_path or "")
    if not path:
        updated = dict(fate_match)
        updated.update(
            {
                "fate": "blocked_needs_contract_work",
                "lineage_match_status": "unresolved",
                "lineage_match_basis": "live_json_path_missing",
                "classification_reason": "The live upstream field has no JSON path provenance.",
            }
        )
        return updated

    parameter_route = LIVE_PARAMETER_FIELD_ROUTES.get((endpoint_name, path))
    if parameter_route is not None:
        return _live_typed_fate(
            fate_match,
            source_column=source_column,
            target_column=str(parameter_route["target_column"]),
            staging_key=str(parameter_route["staging_key"]),
            star_tables=parameter_route["star_tables"],
            staging_columns=staging_columns,
            star_columns=star_columns,
            lineage_match_basis="live_request_parameter_route",
        )

    for excluded_root in LIVE_NON_ANALYTIC_JSON_ROOTS.get(endpoint_name, ()):
        if _path_is_within(path, excluded_root):
            updated = dict(fate_match)
            updated.update(
                {
                    "fate": "excluded_non_analytic_payload",
                    "verified_staging_tables": [],
                    "verified_star_tables": [],
                    "lineage_match_status": "classified",
                    "lineage_match_basis": "live_non_analytic_json_root",
                    "classification_reason": (
                        f"{path} is inside the exact non-analytic envelope root {excluded_root}."
                    ),
                }
            )
            return updated

    if path in LIVE_RAW_ONLY_REFERENCE_JSON_PATHS.get(endpoint_name, frozenset()):
        updated = dict(fate_match)
        updated.update(
            {
                "fate": "raw_only_reference",
                "verified_staging_tables": [],
                "verified_star_tables": [],
                "lineage_match_status": "classified",
                "lineage_match_basis": "live_raw_only_reference_path",
                "classification_reason": (
                    f"{path} is an exact live response-envelope reference field, not a packet row."
                ),
            }
        )
        return updated

    packet = _live_packet_for_path(endpoint_name, path)
    if packet is None:
        updated = dict(fate_match)
        updated.update(
            {
                "fate": "blocked_needs_contract_work",
                "lineage_match_status": "unresolved",
                "lineage_match_basis": "live_json_path_outside_packet_contract",
                "classification_reason": (
                    f"{path} is not inside an exact extracted packet root for {endpoint_name}."
                ),
            }
        )
        return updated

    relative_path = path.removeprefix(packet.json_root).removeprefix(".")
    configured_projection = dict(packet.typed_projections).get(relative_path)
    if configured_projection is not None:
        return _live_typed_fate(
            fate_match,
            source_column=source_column,
            target_column=configured_projection,
            staging_key=packet.staging_key,
            star_tables=packet.star_tables,
            staging_columns=staging_columns,
            star_columns=star_columns,
            lineage_match_basis="live_packet_typed_projection",
            json_root=packet.json_root,
        )

    direct_column = _camel_to_snake(source_column)
    if "." not in relative_path and direct_column in staging_columns.get(packet.staging_key, set()):
        return _live_typed_fate(
            fate_match,
            source_column=source_column,
            target_column=direct_column,
            staging_key=packet.staging_key,
            star_tables=packet.star_tables,
            staging_columns=staging_columns,
            star_columns=star_columns,
            lineage_match_basis="live_packet_direct_column",
            json_root=packet.json_root,
        )

    if "payload_json" not in staging_columns.get(packet.staging_key, set()):
        updated = dict(fate_match)
        updated.update(
            {
                "fate": "blocked_needs_contract_work",
                "lineage_match_status": "unresolved",
                "lineage_match_basis": "live_packet_missing_payload_json",
                "classification_reason": (
                    f"{packet.staging_key} does not declare payload_json for packet root "
                    f"{packet.json_root}."
                ),
            }
        )
        return updated

    verified_star_tables = sorted(
        table_name
        for table_name in packet.star_tables
        if "payload_json" in star_columns.get(table_name, set())
    )
    updated = dict(fate_match)
    updated.update(
        {
            "fate": "staged_json_payload",
            "candidate_staging_tables": sorted(
                {*fate_match.get("candidate_staging_tables", []), packet.staging_key}
            ),
            "candidate_star_tables": sorted(
                {*fate_match.get("candidate_star_tables", []), *verified_star_tables}
            ),
            "verified_staging_tables": [packet.staging_key],
            "verified_star_tables": verified_star_tables,
            "lineage_match_status": "verified",
            "lineage_match_basis": "live_packet_json_path",
            "packet_json_root": packet.json_root,
            "representation_column": "payload_json",
            "classified_staging_columns": [
                {"table_name": packet.staging_key, "column_name": "payload_json"}
            ],
            "classified_star_columns": [
                {"table_name": table_name, "column_name": "payload_json"}
                for table_name in verified_star_tables
            ],
        }
    )
    return updated


def _bronze_fate_rows(
    tiers: Iterable[Tier],
    endpoint_analysis_docs_root: Path | str | None,
    bronze_contracts_path: Path | str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if bronze_contracts_path is not None:
        bronze_contracts = json.loads(Path(bronze_contracts_path).read_text(encoding="utf-8"))
    elif endpoint_analysis_docs_root is not None:
        bundle = build_nba_api_upstream_contract_bundle(endpoint_analysis_docs_root)
        bronze_contracts = build_nba_api_bronze_contracts_from_bundle(bundle)
    else:
        return [], None

    bronze_tables = bronze_contracts.get("tables", [])
    if not bronze_tables:
        summary = dict(bronze_contracts.get("summary", {}))
        summary["enabled"] = bool(bronze_contracts.get("enabled"))
        return [], summary

    (
        staging_columns_by_name,
        star_columns_by_name,
        normalized_staging,
        normalized_star,
    ) = _column_indexes(tiers)
    staging_by_source, star_by_source = _source_lineage_indexes(tiers)
    staging_columns = {
        table_name: set(schema_cls.to_schema().columns)
        for table_name, schema_cls in _staging_schema_registry().items()
    }
    star_columns = {
        table_name: set(schema_cls.to_schema().columns)
        for table_name, schema_cls in _star_schema_registry().items()
    }
    stats_provenance = (
        EndpointCoverageGenerator(
            endpoint_analysis_docs_root=Path(endpoint_analysis_docs_root)
        ).build_schema_annotation_route_provenance()
        if endpoint_analysis_docs_root is not None
        else None
    )
    stats_routes = _stats_route_index(stats_provenance)
    superseded_runtime_classes = dict(
        (stats_provenance or {}).get("superseded_runtime_classes", {})
    )
    rows: list[dict[str, Any]] = []
    for table in bronze_tables:
        table_name = str(table.get("bronze_table") or "")
        for ordinal, column in enumerate(table.get("columns", [])):
            column_name = str(column.get("name") or column.get("key") or "")
            if not column_name:
                continue
            source_key = _contract_lineage_key(
                endpoint=table.get("endpoint"),
                result_set_name=table.get("result_set_name"),
                column_name=column_name,
            )
            fate_match = _field_fate(
                column_name,
                staging_columns_by_name=staging_columns_by_name,
                star_columns_by_name=star_columns_by_name,
                normalized_staging=normalized_staging,
                normalized_star=normalized_star,
                staging_by_source=staging_by_source,
                star_by_source=star_by_source,
                source_key=source_key,
            )
            source_family = str(table.get("source_family") or "")
            if source_family == "stats":
                fate_match = _apply_stats_contract_route_fate(
                    fate_match,
                    source_column=column_name,
                    route_rows=stats_routes.get(source_key, []) if source_key else [],
                )
                if not (source_key and stats_routes.get(source_key)):
                    fate_match = _apply_superseded_stats_fate(
                        fate_match,
                        endpoint=table.get("endpoint"),
                        superseded_runtime_classes=superseded_runtime_classes,
                    )
            elif source_family == "live":
                fate_match = _apply_live_contract_fate(
                    fate_match,
                    endpoint=table.get("endpoint"),
                    source_column=column_name,
                    json_path=column.get("json_path"),
                    staging_columns=staging_columns,
                    star_columns=star_columns,
                )
            fate = fate_match["fate"]
            rows.append(
                {
                    "source_layer": "bronze_contract",
                    "source_table": table_name,
                    "source_column": column_name,
                    "ordinal": ordinal,
                    "endpoint": table.get("endpoint"),
                    "source_family": source_family,
                    "result_set_name": table.get("result_set_name"),
                    "json_path": column.get("json_path"),
                    "source_lineage_key": ".".join(source_key) if source_key else "",
                    **fate_match,
                    "description": column.get("description"),
                    "description_source": column.get("description_source"),
                    "requires_followup": _fate_requires_followup(
                        source_column=column_name,
                        fate=fate,
                        lineage_match_status=str(fate_match["lineage_match_status"]),
                    ),
                }
            )
    summary = dict(bronze_contracts.get("summary", {}))
    summary["enabled"] = bool(bronze_contracts.get("enabled"))
    return rows, summary


def _schema_helper_reconciliation() -> dict[str, Any]:
    public_by_class_id = _schema_table_by_class_id()
    public_tables = {tier: set(_schema_for_tier(tier)) for tier in ("raw", "staging", "star")}
    rows: list[dict[str, Any]] = []
    for tier, package_name in (
        ("raw", "nbadb.schemas.raw"),
        ("staging", "nbadb.schemas.staging"),
        ("star", "nbadb.schemas.star"),
    ):
        package = importlib.import_module(package_name)
        for module_info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            module = importlib.import_module(module_info.name)
            for member_name, obj in inspect.getmembers(module, inspect.isclass):
                if obj is BaseSchema or not issubclass(obj, BaseSchema):
                    continue
                if obj.__module__ != module_info.name:
                    continue
                public_match = public_by_class_id.get(id(obj))
                conventional_table = _schema_table_name_from_member(member_name)
                if member_name != obj.__name__:
                    classification = "excluded_alias"
                elif public_match is not None:
                    classification = "public_registry"
                elif member_name.startswith("_") or conventional_table.startswith("_"):
                    classification = "excluded_private"
                elif conventional_table.endswith("_base") or "base" in conventional_table:
                    classification = "excluded_helper_or_base"
                else:
                    classification = "excluded_non_registry"
                rows.append(
                    {
                        "tier": tier,
                        "module": module_info.name,
                        "member_name": member_name,
                        "class_name": obj.__name__,
                        "conventional_table_name": conventional_table,
                        "registry_tier": public_match[0] if public_match else None,
                        "registry_table_name": public_match[1] if public_match else None,
                        "classification": classification,
                    }
                )

    public_leaks = [
        {"tier": tier, "table_name": table_name}
        for tier, tables in public_tables.items()
        for table_name in sorted(tables)
        if table_name.startswith("_") or table_name.endswith("_base")
    ]
    counts = Counter(row["classification"] for row in rows)
    return {
        "summary": {
            "inspected_schema_class_count": len(rows),
            "classification_counts": dict(sorted(counts.items())),
            "public_helper_leak_count": len(public_leaks),
            "public_table_counts": {tier: len(tables) for tier, tables in public_tables.items()},
        },
        "public_helper_leaks": public_leaks,
        "classes": rows,
    }


def _feature_inventory(
    tiers: Iterable[Tier],
    staging_route_index: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    star_tables = set(_star_schema_registry())
    rows: list[dict[str, Any]] = []
    for tier in tiers:
        if tier == "raw":
            continue
        for table_name, schema_cls in sorted(_schema_for_tier(tier).items()):
            rows.extend(
                _field_entries(
                    tier=tier,
                    table_name=table_name,
                    schema_cls=schema_cls,
                    staging_route_index=staging_route_index,
                    star_tables=star_tables,
                )
            )
    return rows


def _category_summary(feature_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier = Counter(str(row["tier"]) for row in feature_rows)
    by_category = Counter(str(row["semantic_primary"]) for row in feature_rows)
    by_tier_category = Counter(f"{row['tier']}::{row['semantic_primary']}" for row in feature_rows)
    by_family_category = Counter(
        f"{row['table_family']}::{row['semantic_primary']}" for row in feature_rows
    )
    return {
        "summary": {
            "column_count": len(feature_rows),
            "tier_counts": dict(sorted(by_tier.items())),
            "semantic_primary_counts": dict(sorted(by_category.items())),
        },
        "tier_category_counts": dict(sorted(by_tier_category.items())),
        "family_category_counts": dict(sorted(by_family_category.items())),
    }


def _transform_schema_parity() -> dict[str, Any]:
    from nbadb.orchestrate.transformers import discover_all_transformers

    schema_tables = set(_star_schema_registry())
    transform_outputs = {transformer.output_table for transformer in discover_all_transformers()}
    schema_without_transform = sorted(schema_tables - transform_outputs)
    transform_without_schema = sorted(transform_outputs - schema_tables)
    return {
        "schema_table_count": len(schema_tables),
        "transform_output_count": len(transform_outputs),
        "schema_without_transform": schema_without_transform,
        "transform_without_schema": transform_without_schema,
        "schema_without_transform_count": len(schema_without_transform),
        "transform_without_schema_count": len(transform_without_schema),
    }


def _audit_summary(
    *,
    tiers: Iterable[Tier],
    route_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    fate_rows: list[dict[str, Any]],
    helper_reconciliation: dict[str, Any],
    bronze_summary: dict[str, Any] | None,
    require_bronze_contracts: bool,
) -> dict[str, Any]:
    public_table_counts = {tier: len(_schema_for_tier(tier)) for tier in tiers}
    description_missing_count = sum(1 for row in feature_rows if not row.get("description"))
    unclassified_count = sum(1 for row in feature_rows if not row.get("semantic_primary"))
    invalid_fk_rows = [
        row for row in feature_rows if row.get("fk_ref") and not row.get("valid_fk_ref")
    ]
    unresolved_routes = [row for row in route_rows if row["route_status"] == "unresolved"]
    raw_missing_fate = [row for row in fate_rows if not row.get("fate")]
    unresolved_useful_fate_rows = [row for row in fate_rows if row.get("requires_followup")]
    unresolved_lineage_critical = [row for row in feature_rows if not row.get("lineage_source")]
    parity = _transform_schema_parity() if "star" in tiers else {}
    bronze_contract_missing_count = 1 if require_bronze_contracts and bronze_summary is None else 0
    bronze_contract_disabled_count = (
        1
        if require_bronze_contracts
        and bronze_summary is not None
        and not bool(bronze_summary.get("enabled"))
        else 0
    )
    bronze_contract_zero_table_count = (
        1
        if require_bronze_contracts
        and bronze_summary is not None
        and int(bronze_summary.get("table_count", 0)) == 0
        else 0
    )
    bronze_contract_zero_column_table_count = (
        int(bronze_summary.get("zero_column_table_count", 0)) if bronze_summary is not None else 0
    )
    bronze_contract_classified_zero_column_table_count = (
        int(bronze_summary.get("classified_zero_column_table_count", 0))
        if bronze_summary is not None
        else 0
    )
    reported_blocking_zero_column_table_count = (
        int(bronze_summary.get("blocking_zero_column_table_count", 0))
        if bronze_summary is not None
        else 0
    )
    bronze_contract_blocking_zero_column_table_count = max(
        reported_blocking_zero_column_table_count,
        bronze_contract_zero_column_table_count
        - bronze_contract_classified_zero_column_table_count,
    )
    blocking_issue_counts = {
        "missing_description_count": description_missing_count,
        "unclassified_semantic_primary_count": unclassified_count,
        "invalid_fk_count": len(invalid_fk_rows),
        "staging_route_unresolved_count": len(unresolved_routes),
        "raw_field_missing_fate_count": len(raw_missing_fate),
        "raw_bronze_unresolved_useful_field_count": len(unresolved_useful_fate_rows),
        "helper_public_leak_count": int(
            helper_reconciliation["summary"]["public_helper_leak_count"]
        ),
        "unresolved_lineage_critical_count": len(unresolved_lineage_critical),
        "transform_without_schema_count": int(parity.get("transform_without_schema_count", 0)),
        "schema_without_transform_count": int(parity.get("schema_without_transform_count", 0)),
        "bronze_contract_missing_count": bronze_contract_missing_count,
        "bronze_contract_disabled_count": bronze_contract_disabled_count,
        "bronze_contract_zero_table_count": bronze_contract_zero_table_count,
        "bronze_contract_blocking_zero_column_table_count": (
            bronze_contract_blocking_zero_column_table_count
        ),
    }
    return {
        "tiers": list(tiers),
        "public_table_counts": public_table_counts,
        "public_feature_column_count": len(feature_rows),
        "raw_and_bronze_fate_count": len(fate_rows),
        "bronze_contracts": bronze_summary,
        "bronze_contract_zero_column_table_count": bronze_contract_zero_column_table_count,
        "bronze_contract_classified_zero_column_table_count": (
            bronze_contract_classified_zero_column_table_count
        ),
        "bronze_contract_blocking_zero_column_table_count": (
            bronze_contract_blocking_zero_column_table_count
        ),
        "blocking_issue_counts": blocking_issue_counts,
        "strict_pass": all(value == 0 for value in blocking_issue_counts.values()),
        "transform_schema_parity": parity,
        "sample_invalid_fk_rows": invalid_fk_rows[:25],
        "sample_unresolved_routes": unresolved_routes[:25],
        "sample_raw_bronze_unresolved_useful_fields": unresolved_useful_fate_rows[:25],
        "sample_unresolved_lineage_critical": unresolved_lineage_critical[:25],
    }


def build_schema_annotation_artifacts(
    *,
    tiers: Iterable[Tier] = ("raw", "staging", "star"),
    endpoint_analysis_docs_root: Path | str | None = None,
    bronze_contracts_path: Path | str | None = None,
    require_bronze_contracts: bool = False,
) -> dict[str, Any]:
    selected_tiers = tuple(dict.fromkeys(tiers))
    invalid_tiers = [tier for tier in selected_tiers if tier not in {"raw", "staging", "star"}]
    if invalid_tiers:
        msg = f"Unsupported schema annotation tiers: {invalid_tiers}"
        raise ValueError(msg)

    route_rows = _staging_route_rows()
    route_index = _staging_route_index(route_rows)
    feature_rows = _feature_inventory(selected_tiers, route_index)
    raw_fate_rows = _raw_schema_fate_rows(selected_tiers) if "raw" in selected_tiers else []
    bronze_fate_rows, bronze_summary = _bronze_fate_rows(
        selected_tiers,
        endpoint_analysis_docs_root,
        bronze_contracts_path,
    )
    fate_rows = [*raw_fate_rows, *bronze_fate_rows]
    helper_reconciliation = _schema_helper_reconciliation()
    category_summary = _category_summary(feature_rows)
    audit_summary = _audit_summary(
        tiers=selected_tiers,
        route_rows=route_rows,
        feature_rows=feature_rows,
        fate_rows=fate_rows,
        helper_reconciliation=helper_reconciliation,
        bronze_summary=bronze_summary,
        require_bronze_contracts=require_bronze_contracts,
    )
    route_status_counts = Counter(str(row["route_status"]) for row in route_rows)
    fate_counts = Counter(str(row["fate"]) for row in fate_rows)

    return {
        "raw_silver_gold_field_fate": {
            "summary": {
                "field_count": len(fate_rows),
                "fate_counts": dict(sorted(fate_counts.items())),
                "bronze_enabled": bronze_summary is not None,
                "bronze_required": require_bronze_contracts,
            },
            "fields": fate_rows,
        },
        "silver_gold_feature_inventory": {
            "summary": {
                "column_count": len(feature_rows),
                "tier_counts": dict(Counter(str(row["tier"]) for row in feature_rows)),
            },
            "columns": feature_rows,
        },
        "staging_route_inventory": {
            "summary": {
                "route_count": len(route_rows),
                "route_status_counts": dict(sorted(route_status_counts.items())),
                "unresolved_route_count": route_status_counts.get("unresolved", 0),
            },
            "routes": route_rows,
        },
        "schema_helper_reconciliation": helper_reconciliation,
        "schema_annotation_audit": {
            "summary": audit_summary,
            "artifact_files": ARTIFACT_FILENAMES,
        },
        "silver_gold_column_category_summary": category_summary,
    }


def schema_annotation_strict_issues(audit_payload: dict[str, Any]) -> list[str]:
    summary = audit_payload["schema_annotation_audit"]["summary"]
    counts = summary.get("blocking_issue_counts", {})
    issues: list[str] = []
    for key, value in sorted(counts.items()):
        if int(value):
            issues.append(f"{key}={value}")
    return issues


def write_schema_annotation_artifacts(
    *,
    output_dir: Path,
    tiers: Iterable[Tier] = ("raw", "staging", "star"),
    endpoint_analysis_docs_root: Path | str | None = None,
    bronze_contracts_path: Path | str | None = None,
    require_bronze_contracts: bool = False,
) -> dict[str, Path]:
    payload = build_schema_annotation_artifacts(
        tiers=tiers,
        endpoint_analysis_docs_root=endpoint_analysis_docs_root,
        bronze_contracts_path=bronze_contracts_path,
        require_bronze_contracts=require_bronze_contracts,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for artifact_key, filename in ARTIFACT_FILENAMES.items():
        path = output_dir / filename
        path.write_text(
            json.dumps(payload[artifact_key], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[artifact_key] = path
    return written
