from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import duckdb

from nbadb.core.types import SeasonType
from nbadb.orchestrate.execution_policy import build_execution_policy
from nbadb.orchestrate.extraction_contract import (
    FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT,
    FinalLaneOutcome,
    contract_blocking_rules_for_lane,
)
from nbadb.orchestrate.seasons import season_range
from nbadb.orchestrate.workload_profile import (
    WorkloadPlanningSnapshot,
    build_workload_planning_snapshot,
    endpoint_cost,
    preferred_max_span,
)

DEFAULT_HISTORICAL_START = 1946
MAX_CONSECUTIVE_FAILURES = 3
MAX_WORKFLOW_DISPATCH_JSON_CHARS = 60_000
MAX_GITHUB_MATRIX_LANES = 220
CHUNK_PROFILES = frozenset({"standard", "balanced-small", "micro"})
DEFAULT_CHUNK_PROFILE = "balanced-small"
SPLITTABLE_TIMEOUT_STATUSES = frozenset(
    {"needs_resume", "extract-timeout", "timeout_with_persisted_progress"}
)
RETRYABLE_PIPELINE_FAILURE_STATUSES = frozenset(
    {"cancelled", "vpn_auth_failure", "vpn_connect_timeout"}
)
FINAL_LANE_OUTCOMES: frozenset[str] = frozenset(
    {"complete", "needs_resume", "contract_blocked", "pipeline_failure"}
)
MERGE_TERMINAL_OUTCOMES: frozenset[str] = frozenset({"complete", "contract_blocked"})
TIMEOUT_SPLIT_PATTERNS = frozenset(
    {
        "game",
        "date",
        "season",
        "player_season",
        "team_season",
        "player_team_season",
    }
)
SEASON_TYPE_PATTERNS = frozenset({"season", "player_season", "team_season"})
HISTORICAL_PATTERNS = frozenset({"season", "game", "date", "player_season", "team_season"})
REFERENCE_PATTERNS = frozenset({"static", "player", "team"})
REFERENCE_PATTERN_ORDER = ("static", "team", "player")
CROSS_PRODUCT_PATTERNS = frozenset({"player_team_season"})
SEASON_TYPE_GROUPABLE_PATTERNS = SEASON_TYPE_PATTERNS | CROSS_PRODUCT_PATTERNS
DEFAULT_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)
HISTORICAL_MAX_SPAN_BY_PATTERN: dict[str, int] = {
    "game": 4,
    "date": 4,
    "season": 8,
    "player_season": 6,
    "team_season": 8,
}
HISTORICAL_ENDPOINT_ISOLATION_PATTERNS = frozenset({"date", "game"})
"""High-volume historical patterns that must be planned per endpoint.

The support matrix is endpoint/table-oriented, but date/game extraction can be
much slower than the broad season sweeps. Isolating these lanes keeps a slow or
rate-limited endpoint from blocking unrelated endpoint/time-period coverage.
"""
CROSS_PRODUCT_MAX_SPAN = 4
CHUNK_PROFILE_MAX_SPAN_BY_PATTERN: dict[str, dict[str, dict[str, int]]] = {
    "standard": {
        "cheap_high_volume": {
            "game": HISTORICAL_MAX_SPAN_BY_PATTERN["game"],
            "date": HISTORICAL_MAX_SPAN_BY_PATTERN["date"],
            "season": HISTORICAL_MAX_SPAN_BY_PATTERN["season"],
            "player_season": HISTORICAL_MAX_SPAN_BY_PATTERN["player_season"],
            "team_season": HISTORICAL_MAX_SPAN_BY_PATTERN["team_season"],
            "player_team_season": CROSS_PRODUCT_MAX_SPAN,
        },
        "expensive_stable": {
            "game": HISTORICAL_MAX_SPAN_BY_PATTERN["game"],
            "date": HISTORICAL_MAX_SPAN_BY_PATTERN["date"],
            "season": HISTORICAL_MAX_SPAN_BY_PATTERN["season"],
            "player_season": HISTORICAL_MAX_SPAN_BY_PATTERN["player_season"],
            "team_season": HISTORICAL_MAX_SPAN_BY_PATTERN["team_season"],
            "player_team_season": CROSS_PRODUCT_MAX_SPAN,
        },
        "expensive_flaky": {
            "game": HISTORICAL_MAX_SPAN_BY_PATTERN["game"],
            "date": HISTORICAL_MAX_SPAN_BY_PATTERN["date"],
            "season": HISTORICAL_MAX_SPAN_BY_PATTERN["season"],
            "player_season": HISTORICAL_MAX_SPAN_BY_PATTERN["player_season"],
            "team_season": HISTORICAL_MAX_SPAN_BY_PATTERN["team_season"],
            "player_team_season": CROSS_PRODUCT_MAX_SPAN,
        },
        "discovery_bound_cross_product": {
            "player_team_season": CROSS_PRODUCT_MAX_SPAN,
        },
    },
    "balanced-small": {
        "cheap_high_volume": {
            "game": 2,
            "date": 2,
            "season": 4,
            "player_season": 3,
            "team_season": 4,
            "player_team_season": 2,
        },
        "expensive_stable": {
            "game": 1,
            "date": 1,
            "season": 3,
            "player_season": 2,
            "team_season": 3,
            "player_team_season": 1,
        },
        "expensive_flaky": {
            "game": 1,
            "date": 1,
            "season": 3,
            "player_season": 2,
            "team_season": 3,
            "player_team_season": 1,
        },
        "discovery_bound_cross_product": {
            "player_team_season": 1,
        },
    },
    "micro": {
        "cheap_high_volume": {
            "game": 1,
            "date": 1,
            "season": 1,
            "player_season": 1,
            "team_season": 1,
            "player_team_season": 1,
        },
        "expensive_stable": {
            "game": 1,
            "date": 1,
            "season": 1,
            "player_season": 1,
            "team_season": 1,
            "player_team_season": 1,
        },
        "expensive_flaky": {
            "game": 1,
            "date": 1,
            "season": 1,
            "player_season": 1,
            "team_season": 1,
            "player_team_season": 1,
        },
        "discovery_bound_cross_product": {
            "player_team_season": 1,
        },
    },
}
THROUGHPUT_TIER_SEVERITY: dict[str, int] = {
    "cheap_high_volume": 0,
    "expensive_stable": 1,
    "expensive_flaky": 2,
    "discovery_bound_cross_product": 3,
}
FAMILY_PRIORITY: dict[str, int] = {
    "box_score": 40,
    "play_by_play": 35,
    "player_history": 30,
    "team_history": 25,
    "default": 0,
}
REFERENCE_MAX_ENDPOINTS_BY_PATTERN: dict[str, int] = {
    "static": 64,
    "team": 12,
    "player": 4,
}
REFERENCE_SINGLETON_ENDPOINTS_BY_PATTERN: dict[str, frozenset[str]] = {
    "player": frozenset(
        {
            "common_player_info",
            "player_profile_v2",
            "player_awards",
            "player_career_stats",
            "player_compare",
        }
    ),
    "team": frozenset(
        {
            "franchise_leaders",
            "franchise_players",
            "team_historical_leaders",
            "team_year_by_year",
        }
    ),
}
REFERENCE_TIMEOUT_SECONDS_BY_PATTERN: dict[str, int] = {
    "static": 1_800,
    "team": 3_000,
    "player": 3_600,
}
REFERENCE_TIMEOUT_SECONDS_BY_ENDPOINT: dict[str, int] = {
    "common_player_info": 9_000,
    "player_profile_v2": 10_800,
    "player_awards": 9_000,
    "player_career_stats": 9_000,
    "player_compare": 9_000,
    "team_historical_leaders": 4_200,
}
FULL_EXTRACTION_EXCLUDED_ENDPOINTS: dict[str, str] = {
    endpoint_name: exclusion.reason
    for endpoint_name, exclusion in FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT.items()
}


@dataclass(frozen=True, slots=True)
class FullExtractionLane:
    lane_id: str
    lane_index: int
    lane_name: str
    lane_kind: str
    season_start: int | None
    season_end: int | None
    patterns: tuple[str, ...]
    season_types: tuple[str, ...] = ()
    endpoints: tuple[str, ...] = ()
    use_vpn: bool = True
    resume_only: bool = False
    timeout_seconds: int = 0
    failure_streak: int = 0
    last_failure_reason: str = ""
    parent_lane_id: str = ""
    split_generation: int = 0
    chunk_profile: str = "standard"
    endpoint_family: str = ""
    throughput_tier: str = ""
    estimated_lane_cost: float = 0.0
    coverage_units_hash: str = ""
    schedule_priority: float = 0.0
    planned_wave: int = 0

    def to_workflow_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "lane_index": self.lane_index,
            "lane_name": self.lane_name,
            "lane_kind": self.lane_kind,
            "season_start": "" if self.season_start is None else str(self.season_start),
            "season_end": "" if self.season_end is None else str(self.season_end),
            "patterns": ",".join(self.patterns),
            "season_types": ",".join(self.season_types),
            "endpoints": ",".join(self.endpoints),
            "use_vpn": self.use_vpn,
            "resume_only": self.resume_only,
            "timeout_seconds": self.timeout_seconds,
            "parent_lane_id": self.parent_lane_id,
            "split_generation": self.split_generation,
            "chunk_profile": self.chunk_profile,
            "endpoint_family": self.endpoint_family,
            "throughput_tier": self.throughput_tier,
            "estimated_lane_cost": f"{self.estimated_lane_cost:.3f}",
            "coverage_units_hash": self.coverage_units_hash,
            "schedule_priority": f"{self.schedule_priority:.3f}",
            "planned_wave": self.planned_wave,
        }


def _lane_contract_blocking_rules(lane: FullExtractionLane) -> tuple[dict[str, Any], ...]:
    return tuple(
        rule.to_dict()
        for rule in contract_blocking_rules_for_lane(
            endpoints=lane.endpoints,
            patterns=lane.patterns,
            season_start=lane.season_start,
            season_end=lane.season_end,
        )
    )


def _lane_is_contract_blocked(lane: FullExtractionLane) -> bool:
    return bool(_lane_contract_blocking_rules(lane))


def _append_lane_if_supported(lanes: list[FullExtractionLane], lane: FullExtractionLane) -> bool:
    if _lane_is_contract_blocked(lane):
        return False
    lanes.append(lane)
    return True


def _contract_supported_season_bands(
    *,
    endpoints: tuple[str, ...],
    patterns: tuple[str, ...],
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    """Return sub-bands that are not fully covered by support-contract blocks."""
    bands: list[tuple[int, int]] = []
    band_start: int | None = None
    for year in range(start, end + 1):
        is_blocked = bool(
            contract_blocking_rules_for_lane(
                endpoints=endpoints,
                patterns=patterns,
                season_start=year,
                season_end=year,
            )
        )
        if is_blocked:
            if band_start is not None:
                bands.append((band_start, year - 1))
                band_start = None
            continue
        if band_start is None:
            band_start = year
    if band_start is not None:
        bands.append((band_start, end))
    return bands


@dataclass(frozen=True, slots=True)
class FullExtractionChainState:
    vpn_quarantined_servers: tuple[str, ...] = ()
    artifact_run_ids: tuple[str, ...] = ()
    latest_checkpoint_run_id: str = ""
    latest_checkpoint_artifact_name: str = ""
    latest_checkpoint_generation: int = 0
    latest_checkpoint_coverage_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "vpn_quarantined_servers": list(self.vpn_quarantined_servers),
            "artifact_run_ids": list(self.artifact_run_ids),
            "latest_checkpoint_run_id": self.latest_checkpoint_run_id,
            "latest_checkpoint_artifact_name": self.latest_checkpoint_artifact_name,
            "latest_checkpoint_generation": self.latest_checkpoint_generation,
            "latest_checkpoint_coverage_hash": self.latest_checkpoint_coverage_hash,
        }


@dataclass(frozen=True, slots=True)
class FullExtractionManifest:
    lanes: tuple[FullExtractionLane, ...]
    chain_state: FullExtractionChainState = field(default_factory=FullExtractionChainState)
    matrix_lane_ids: frozenset[str] = field(default_factory=frozenset)


def _normalize_server_list(raw: Any) -> tuple[str, ...]:
    if raw is None or raw == "":
        return ()
    if not isinstance(raw, list | tuple):
        msg = "Expected a list of VPN server hostnames"
        raise ValueError(msg)

    seen: set[str] = set()
    values: list[str] = []
    for value in raw:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        values.append(normalized)
    return tuple(values)


def _normalize_scalar_string(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def _normalize_chain_state(raw_chain_state: Any) -> FullExtractionChainState:
    if raw_chain_state is None or raw_chain_state == "":
        return FullExtractionChainState()
    if not isinstance(raw_chain_state, dict):
        msg = "Expected chain_state to be an object"
        raise ValueError(msg)
    return FullExtractionChainState(
        vpn_quarantined_servers=_normalize_server_list(
            raw_chain_state.get("vpn_quarantined_servers", [])
        ),
        artifact_run_ids=_normalize_server_list(raw_chain_state.get("artifact_run_ids", [])),
        latest_checkpoint_run_id=_normalize_scalar_string(
            raw_chain_state.get("latest_checkpoint_run_id")
        ),
        latest_checkpoint_artifact_name=_normalize_scalar_string(
            raw_chain_state.get("latest_checkpoint_artifact_name")
        ),
        latest_checkpoint_generation=int(raw_chain_state.get("latest_checkpoint_generation") or 0),
        latest_checkpoint_coverage_hash=_normalize_scalar_string(
            raw_chain_state.get("latest_checkpoint_coverage_hash")
        ),
    )


def _parse_csv(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    values = [value.strip() for value in raw.split(",") if value.strip()]
    return values or None


def _load_matrix_payload(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        matrix = payload.get("matrix", payload)
        if isinstance(matrix, list):
            return [dict(row) for row in matrix]
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    msg = f"Unsupported support matrix payload in {path}"
    raise ValueError(msg)


def _current_end_year() -> int:
    return int(season_range()[-1][:4])


def _patterns_for_endpoints(
    rows: list[dict[str, Any]],
    endpoints: list[str] | None,
) -> set[str] | None:
    if not endpoints:
        return None
    endpoint_set = set(endpoints)
    patterns: set[str] = set()
    for row in rows:
        if str(row.get("endpoint_name", "")) not in endpoint_set:
            continue
        patterns.update(str(pattern) for pattern in row.get("param_patterns", []))
    return patterns


def _selected_rows(
    rows: list[dict[str, Any]],
    *,
    selected_patterns: set[str] | None,
    selected_endpoints: list[str] | None,
) -> list[dict[str, Any]]:
    endpoint_set = set(selected_endpoints or ())
    filtered: list[dict[str, Any]] = []
    for row in rows:
        endpoint_name = str(row.get("endpoint_name", ""))
        row_patterns = {str(pattern) for pattern in row.get("param_patterns", [])}
        if endpoint_set and endpoint_name not in endpoint_set:
            continue
        if selected_patterns is not None and not row_patterns & selected_patterns:
            continue
        filtered.append(row)
    return filtered


def _runnable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("endpoint_name", "")) not in FULL_EXTRACTION_EXCLUDED_ENDPOINTS
    ]


def _historical_thresholds(rows: list[dict[str, Any]], requested_patterns: set[str]) -> list[int]:
    thresholds: set[int] = set()
    for row in rows:
        if str(row.get("execution_semantics")) != "historical_backfill":
            continue
        row_patterns = {str(pattern) for pattern in row.get("param_patterns", [])}
        if not row_patterns & requested_patterns:
            continue
        earliest = row.get("earliest_supported_season")
        if earliest is None:
            thresholds.add(DEFAULT_HISTORICAL_START)
            continue
        try:
            thresholds.add(int(earliest))
        except (TypeError, ValueError):
            thresholds.add(DEFAULT_HISTORICAL_START)
    if not thresholds:
        thresholds.add(DEFAULT_HISTORICAL_START)
    return sorted(thresholds)


def _declared_supported_season_types(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(value) for value in row.get("declared_supported_season_types", []) if str(value)
    )


def _season_type_slug(season_types: tuple[str, ...]) -> str:
    if not season_types:
        return "no-season-type"
    return "-".join(value.lower().replace(" ", "-") for value in season_types)


def _lane_slug(value: str) -> str:
    slug = value.strip().lower().replace("_", "-").replace(" ", "-")
    return "".join(char for char in slug if char.isalnum() or char == "-").strip("-")


def _historical_rows_for_pattern(
    rows: list[dict[str, Any]],
    pattern: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if str(row.get("execution_semantics")) == "historical_backfill"
        and pattern in {str(candidate) for candidate in row.get("param_patterns", [])}
    ]


def _group_historical_rows_by_season_types(
    rows: list[dict[str, Any]],
    *,
    pattern: str,
) -> list[tuple[tuple[str, ...], list[dict[str, Any]]]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        if (
            pattern in SEASON_TYPE_GROUPABLE_PATTERNS
            and str(row.get("season_type_contract_status", "not_applicable")) == "supported"
        ):
            season_types = _declared_supported_season_types(row)
        else:
            season_types = ()
        grouped.setdefault(season_types, []).append(row)

    return [
        (season_types, grouped[season_types])
        for season_types in sorted(grouped, key=lambda value: (len(value), value))
    ]


def _endpoint_names(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted({str(row.get("endpoint_name", "")) for row in rows if row.get("endpoint_name")})
    )


def _historical_endpoint_row_groups(
    rows: list[dict[str, Any]],
    *,
    pattern: str,
) -> list[tuple[str | None, list[dict[str, Any]]]]:
    if pattern not in HISTORICAL_ENDPOINT_ISOLATION_PATTERNS:
        return [(None, rows)]

    rows_by_endpoint: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        endpoint_name = str(row.get("endpoint_name", "")).strip()
        if not endpoint_name:
            continue
        rows_by_endpoint.setdefault(endpoint_name, []).append(row)
    return [
        (_lane_slug(endpoint_name), rows_by_endpoint[endpoint_name])
        for endpoint_name in sorted(rows_by_endpoint)
    ]


def _chunked_endpoint_names(
    endpoints: tuple[str, ...], *, chunk_size: int
) -> list[tuple[str, ...]]:
    if chunk_size < 1:
        msg = f"chunk_size must be >= 1, got {chunk_size}"
        raise ValueError(msg)
    return [
        endpoints[index : index + chunk_size]
        for index in range(0, len(endpoints), chunk_size)
        if endpoints[index : index + chunk_size]
    ]


def _reference_patterns_in_order(patterns: set[str]) -> list[str]:
    ordered = [pattern for pattern in REFERENCE_PATTERN_ORDER if pattern in patterns]
    remaining = sorted(pattern for pattern in patterns if pattern not in REFERENCE_PATTERN_ORDER)
    return ordered + remaining


def _reference_timeout_seconds(pattern: str) -> int:
    return REFERENCE_TIMEOUT_SECONDS_BY_PATTERN.get(pattern, 3_000)


def _reference_endpoint_groups(pattern: str, endpoints: tuple[str, ...]) -> list[tuple[str, ...]]:
    singleton_endpoints = REFERENCE_SINGLETON_ENDPOINTS_BY_PATTERN.get(pattern, frozenset())
    grouped_singletons: list[tuple[str, ...]] = [
        (endpoint,) for endpoint in endpoints if endpoint in singleton_endpoints
    ]
    remaining_endpoints = tuple(
        endpoint for endpoint in endpoints if endpoint not in singleton_endpoints
    )
    if not remaining_endpoints:
        return grouped_singletons
    chunk_size = REFERENCE_MAX_ENDPOINTS_BY_PATTERN.get(pattern, len(remaining_endpoints))
    return [
        *_chunked_endpoint_names(remaining_endpoints, chunk_size=chunk_size),
        *grouped_singletons,
    ]


def _adaptive_reference_endpoint_groups(
    pattern: str,
    endpoints: tuple[str, ...],
    *,
    planning_snapshot: WorkloadPlanningSnapshot,
) -> list[tuple[str, ...]]:
    singleton_endpoints = REFERENCE_SINGLETON_ENDPOINTS_BY_PATTERN.get(pattern, frozenset())
    grouped_singletons: list[tuple[str, ...]] = [
        (endpoint,) for endpoint in endpoints if endpoint in singleton_endpoints
    ]
    remaining_endpoints = tuple(
        endpoint for endpoint in endpoints if endpoint not in singleton_endpoints
    )
    if not remaining_endpoints:
        return grouped_singletons

    target_batch_cost = float(
        REFERENCE_MAX_ENDPOINTS_BY_PATTERN.get(pattern, len(remaining_endpoints))
    )
    batches: list[tuple[str, ...]] = []
    current: list[str] = []
    current_cost = 0.0
    for endpoint_name in remaining_endpoints:
        next_cost = endpoint_cost(planning_snapshot.endpoint_profiles, [endpoint_name])
        if current and current_cost + next_cost > target_batch_cost:
            batches.append(tuple(current))
            current = []
            current_cost = 0.0
        current.append(endpoint_name)
        current_cost += next_cost
    if current:
        batches.append(tuple(current))
    return [*batches, *grouped_singletons]


def _reference_lane_timeout_seconds(pattern: str, endpoints: tuple[str, ...]) -> int:
    timeout = _reference_timeout_seconds(pattern)
    for endpoint in endpoints:
        timeout = max(timeout, REFERENCE_TIMEOUT_SECONDS_BY_ENDPOINT.get(endpoint, 0))
    return timeout


def _season_bands(
    rows: list[dict[str, Any]], requested_patterns: set[str]
) -> list[tuple[int, int]]:
    thresholds = _historical_thresholds(rows, requested_patterns)
    end_year = _current_end_year()
    if not thresholds:
        return []

    bands: list[tuple[int, int]] = []
    for index, start in enumerate(thresholds):
        if start > end_year:
            continue
        next_start = thresholds[index + 1] if index + 1 < len(thresholds) else end_year + 1
        end = min(end_year, next_start - 1)
        if start <= end:
            bands.append((start, end))
    return bands


def _band_timeout_seconds(start: int, end: int) -> int:
    span_years = max(1, end - start + 1)
    return min(19_800, max(7_200, span_years * 600))


def _season_span(start: int | None, end: int | None) -> int:
    if start is None or end is None:
        return 0
    return max(1, end - start + 1)


def _max_span_for_pattern(pattern: str) -> int:
    return HISTORICAL_MAX_SPAN_BY_PATTERN.get(pattern, 12)


def _max_span_for_lane(lane: FullExtractionLane) -> int | None:
    if lane.season_start is None or lane.season_end is None:
        return None
    if lane.chunk_profile in CHUNK_PROFILES and lane.patterns:
        return _profile_max_span_for_lane(lane)
    if lane.lane_kind == "historical" and lane.patterns:
        return _max_span_for_pattern(lane.patterns[0])
    if lane.lane_kind in {"cross_product", "cross_product_blocked"}:
        return CROSS_PRODUCT_MAX_SPAN
    return None


def _validate_chunk_profile(chunk_profile: str) -> str:
    if chunk_profile not in CHUNK_PROFILES:
        msg = (
            f"Unsupported chunk_profile {chunk_profile!r}; expected one of {sorted(CHUNK_PROFILES)}"
        )
        raise ValueError(msg)
    return chunk_profile


def _endpoint_profile_values(
    *,
    endpoints: tuple[str, ...],
    pattern: str | None,
    planning_snapshot: WorkloadPlanningSnapshot | None,
) -> tuple[str, str, float]:
    families: list[str] = []
    tiers: list[str] = []
    cost = 0.0
    for endpoint in endpoints:
        profile = (
            planning_snapshot.endpoint_profiles.get(endpoint)
            if planning_snapshot is not None
            else None
        )
        if profile is not None:
            families.append(profile.endpoint_family)
            tiers.append(profile.throughput_tier)
            cost += profile.lane_cost
            continue
        policy = build_execution_policy(endpoint, pattern=pattern)
        families.append(policy.family)
        tiers.append(policy.throughput_tier)
        cost += 1.0
    if not endpoints:
        families.append(pattern or "default")
        tiers.append("cheap_high_volume")
        cost += 1.0
    family_values = sorted(set(families))
    tier = max(tiers, key=lambda value: THROUGHPUT_TIER_SEVERITY.get(value, 0))
    family = family_values[0] if len(family_values) == 1 else "mixed"
    return family, tier, max(cost, 1.0)


def _profile_max_span(
    *,
    chunk_profile: str,
    pattern: str,
    throughput_tier: str,
    endpoint_family: str = "",
) -> int:
    _validate_chunk_profile(chunk_profile)
    if chunk_profile == "standard":
        if pattern == "player_team_season":
            return CROSS_PRODUCT_MAX_SPAN
        return _max_span_for_pattern(pattern)
    if (
        chunk_profile == "balanced-small"
        and pattern in {"date", "game"}
        and endpoint_family in {"box_score", "play_by_play"}
    ):
        return 1
    profile_map = CHUNK_PROFILE_MAX_SPAN_BY_PATTERN[chunk_profile]
    tier_map = profile_map.get(throughput_tier) or profile_map["cheap_high_volume"]
    return max(1, int(tier_map.get(pattern, _max_span_for_pattern(pattern))))


def _profile_max_span_for_lane(lane: FullExtractionLane) -> int | None:
    if lane.season_start is None or lane.season_end is None or not lane.patterns:
        return None
    return _profile_max_span(
        chunk_profile=lane.chunk_profile,
        pattern=lane.patterns[0],
        throughput_tier=lane.throughput_tier or "cheap_high_volume",
        endpoint_family=lane.endpoint_family,
    )


def _coverage_units_for_lane(lane: FullExtractionLane) -> list[dict[str, Any]]:
    patterns = lane.patterns or ("",)
    endpoints = lane.endpoints or ("",)
    season_types = lane.season_types or ("",)
    seasons: tuple[int | None, ...]
    if lane.season_start is None or lane.season_end is None:
        seasons = (None,)
    else:
        seasons = tuple(range(lane.season_start, lane.season_end + 1))
    return [
        {
            "endpoint": endpoint,
            "pattern": pattern,
            "season_type": season_type,
            "season": season,
        }
        for endpoint in endpoints
        for pattern in patterns
        for season_type in season_types
        for season in seasons
    ]


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _coverage_hash_for_lane(lane: FullExtractionLane) -> str:
    return _hash_payload(_coverage_units_for_lane(lane))


def _coverage_fingerprint(lanes: list[FullExtractionLane] | tuple[FullExtractionLane, ...]) -> str:
    units: list[dict[str, Any]] = []
    for lane in lanes:
        units.extend(_coverage_units_for_lane(lane))
    units.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    return _hash_payload(units)


def _lane_schedule_priority(lane: FullExtractionLane) -> float:
    failure_bonus = 1_000_000.0 if lane.last_failure_reason or lane.split_generation else 0.0
    tier_bonus = THROUGHPUT_TIER_SEVERITY.get(lane.throughput_tier, 0) * 100_000.0
    family_bonus = FAMILY_PRIORITY.get(lane.endpoint_family, 0) * 1_000.0
    cost_bonus = lane.estimated_lane_cost * 100.0
    season_bonus = 0.0 if lane.season_start is None else max(0, 3_000 - lane.season_start)
    return failure_bonus + tier_bonus + family_bonus + cost_bonus + season_bonus


def _annotate_lane(
    lane: FullExtractionLane,
    *,
    chunk_profile: str,
    planning_snapshot: WorkloadPlanningSnapshot | None,
) -> FullExtractionLane:
    pattern = lane.patterns[0] if lane.patterns else None
    family, tier, endpoint_cost_value = _endpoint_profile_values(
        endpoints=lane.endpoints,
        pattern=pattern,
        planning_snapshot=planning_snapshot,
    )
    span = max(1, _season_span(lane.season_start, lane.season_end))
    estimated_lane_cost = endpoint_cost_value * span
    annotated = replace(
        lane,
        chunk_profile=chunk_profile,
        endpoint_family=family,
        throughput_tier=tier,
        estimated_lane_cost=round(estimated_lane_cost, 3),
        coverage_units_hash=_coverage_hash_for_lane(lane),
    )
    return replace(annotated, schedule_priority=round(_lane_schedule_priority(annotated), 3))


def _schedule_lanes(
    lanes: list[FullExtractionLane],
    *,
    chunk_profile: str,
    planning_snapshot: WorkloadPlanningSnapshot | None = None,
    max_matrix_lanes: int = MAX_GITHUB_MATRIX_LANES,
) -> list[FullExtractionLane]:
    chunk_profile = _validate_chunk_profile(chunk_profile)
    annotated = [
        _annotate_lane(lane, chunk_profile=chunk_profile, planning_snapshot=planning_snapshot)
        for lane in lanes
    ]
    if chunk_profile == "standard":
        return [
            replace(lane, lane_index=index, planned_wave=index // max_matrix_lanes)
            for index, lane in enumerate(annotated)
        ]

    resume_only = [lane for lane in annotated if lane.resume_only]
    active = [lane for lane in annotated if not lane.resume_only]
    active.sort(
        key=lambda lane: (
            -lane.schedule_priority,
            lane.endpoint_family,
            lane.season_start if lane.season_start is not None else 9999,
            lane.lane_id,
        )
    )
    buckets: dict[str, list[FullExtractionLane]] = {}
    for lane in active:
        buckets.setdefault(lane.endpoint_family or "default", []).append(lane)
    family_order = sorted(
        buckets,
        key=lambda family: (
            -buckets[family][0].schedule_priority,
            family,
        ),
    )
    interleaved: list[FullExtractionLane] = []
    while any(buckets.values()):
        for family in family_order:
            if buckets[family]:
                interleaved.append(buckets[family].pop(0))
    ordered = [*interleaved, *resume_only]
    return [
        replace(lane, lane_index=index, planned_wave=index // max_matrix_lanes)
        for index, lane in enumerate(ordered)
    ]


def _historical_timeout_seconds(pattern: str, start: int, end: int) -> int:
    span_years = _season_span(start, end)
    if pattern in {"game", "date"}:
        return min(10_800, max(5_400, span_years * 600))
    return min(10_800, max(4_800, span_years * 450))


def _cross_product_timeout_seconds(start: int, end: int) -> int:
    span_years = _season_span(start, end)
    return min(10_800, max(6_300, span_years * 900))


def _split_season_band(start: int, end: int, *, max_span: int) -> list[tuple[int, int]]:
    if max_span < 1:
        msg = f"max_span must be >= 1, got {max_span}"
        raise ValueError(msg)
    bands: list[tuple[int, int]] = []
    cursor = start
    while cursor <= end:
        band_end = min(end, cursor + max_span - 1)
        bands.append((cursor, band_end))
        cursor = band_end + 1
    return bands


def _adaptive_split_season_band(
    start: int,
    end: int,
    *,
    max_span: int,
    target_cost: float,
    season_costs: dict[int, float],
) -> list[tuple[int, int]]:
    if not season_costs:
        return _split_season_band(start, end, max_span=max_span)
    bands: list[tuple[int, int]] = []
    cursor = start
    band_start = start
    band_cost = 0.0
    band_span = 0
    while cursor <= end:
        season_cost = max(1.0, float(season_costs.get(cursor, 1.0)))
        should_split = band_span > 0 and (
            band_span >= max_span or band_cost + season_cost > max(target_cost, 1.0)
        )
        if should_split:
            bands.append((band_start, cursor - 1))
            band_start = cursor
            band_cost = 0.0
            band_span = 0
        band_cost += season_cost
        band_span += 1
        cursor += 1
    bands.append((band_start, end))
    return bands


def validate_manifest(lanes: list[FullExtractionLane]) -> None:
    errors: list[str] = []
    for lane in lanes:
        if (lane.season_start is None) != (lane.season_end is None):
            errors.append(f"{lane.lane_id}: season_start/season_end must both be set or both empty")
        if lane.timeout_seconds <= 0:
            errors.append(f"{lane.lane_id}: timeout_seconds must be > 0")
        if lane.failure_streak < 0:
            errors.append(f"{lane.lane_id}: failure_streak must be >= 0")
        if lane.split_generation < 0:
            errors.append(f"{lane.lane_id}: split_generation must be >= 0")
        max_span = _max_span_for_lane(lane)
        span = _season_span(lane.season_start, lane.season_end)
        if not lane.resume_only and max_span is not None and span > max_span:
            errors.append(f"{lane.lane_id}: span {span} exceeds lane policy max {max_span}")
    if errors:
        msg = "Invalid full extraction manifest:\n- " + "\n- ".join(errors)
        raise ValueError(msg)


def _normalize_lane(raw: dict[str, Any], lane_index: int) -> FullExtractionLane:
    patterns = tuple(str(pattern) for pattern in raw.get("patterns", []) if str(pattern))
    season_types = tuple(str(value) for value in raw.get("season_types", []) if str(value))
    endpoints = tuple(str(value) for value in raw.get("endpoints", []) if str(value))
    season_start = raw.get("season_start")
    season_end = raw.get("season_end")

    lane = FullExtractionLane(
        lane_id=str(raw["lane_id"]),
        lane_index=lane_index,
        lane_name=str(raw.get("lane_name") or raw["lane_id"]),
        lane_kind=str(raw.get("lane_kind") or "custom"),
        season_start=None if season_start in {None, ""} else int(season_start),
        season_end=None if season_end in {None, ""} else int(season_end),
        patterns=patterns,
        season_types=season_types,
        endpoints=endpoints,
        use_vpn=bool(raw.get("use_vpn", True)),
        resume_only=bool(raw.get("resume_only", False)),
        timeout_seconds=int(raw.get("timeout_seconds") or 7_200),
        failure_streak=int(raw.get("failure_streak") or 0),
        last_failure_reason=str(raw.get("last_failure_reason") or ""),
        parent_lane_id=str(raw.get("parent_lane_id") or ""),
        split_generation=int(raw.get("split_generation") or 0),
        chunk_profile=str(raw.get("chunk_profile") or "standard"),
        endpoint_family=str(raw.get("endpoint_family") or ""),
        throughput_tier=str(raw.get("throughput_tier") or ""),
        estimated_lane_cost=float(raw.get("estimated_lane_cost") or 0.0),
        coverage_units_hash=str(raw.get("coverage_units_hash") or ""),
        schedule_priority=float(raw.get("schedule_priority") or 0.0),
        planned_wave=int(raw.get("planned_wave") or 0),
    )
    if not lane.coverage_units_hash:
        lane = replace(lane, coverage_units_hash=_coverage_hash_for_lane(lane))
    return lane


def build_default_manifest(
    *,
    support_matrix_rows: list[dict[str, Any]],
    selected_patterns: list[str] | None = None,
    selected_endpoints: list[str] | None = None,
    planning_snapshot: WorkloadPlanningSnapshot | None = None,
    chunk_profile: str = "standard",
) -> list[FullExtractionLane]:
    chunk_profile = _validate_chunk_profile(chunk_profile)
    endpoint_patterns = _patterns_for_endpoints(support_matrix_rows, selected_endpoints)
    if selected_patterns is not None:
        requested_patterns = set(selected_patterns)
    elif endpoint_patterns is not None:
        requested_patterns = endpoint_patterns
    else:
        requested_patterns = {
            str(pattern) for row in support_matrix_rows for pattern in row.get("param_patterns", [])
        }

    filtered_rows = _selected_rows(
        support_matrix_rows,
        selected_patterns=requested_patterns,
        selected_endpoints=selected_endpoints,
    )
    if not filtered_rows:
        msg = "Selected full-extraction filters matched no support-matrix rows"
        raise ValueError(msg)
    runnable_rows = _runnable_rows(filtered_rows)
    if not runnable_rows:
        msg = "Selected full-extraction filters produced no runnable lanes"
        raise ValueError(msg)

    lanes: list[FullExtractionLane] = []
    lane_index = 0

    reference_patterns = requested_patterns & REFERENCE_PATTERNS
    if reference_patterns:
        for pattern in _reference_patterns_in_order(reference_patterns):
            pattern_rows = [
                row
                for row in runnable_rows
                if pattern in {str(candidate) for candidate in row.get("param_patterns", [])}
            ]
            endpoints = _endpoint_names(pattern_rows)
            if not endpoints:
                continue
            endpoint_groups = (
                _adaptive_reference_endpoint_groups(
                    pattern,
                    endpoints,
                    planning_snapshot=planning_snapshot,
                )
                if planning_snapshot is not None
                else _reference_endpoint_groups(pattern, endpoints)
            )
            for group_index, endpoint_group in enumerate(endpoint_groups, start=1):
                chunk_suffix = f"-{group_index:02d}" if len(endpoint_groups) > 1 else ""
                lane_name = f"Reference {pattern.replace('_', ' ').title()}"
                if len(endpoint_groups) > 1:
                    lane_name = f"{lane_name} {group_index}/{len(endpoint_groups)}"
                appended = _append_lane_if_supported(
                    lanes,
                    FullExtractionLane(
                        lane_id=f"reference-{pattern}{chunk_suffix}",
                        lane_index=lane_index,
                        lane_name=lane_name,
                        lane_kind="reference",
                        season_start=None,
                        season_end=None,
                        patterns=(pattern,),
                        endpoints=endpoint_group,
                        use_vpn=True,
                        resume_only=False,
                        timeout_seconds=_reference_lane_timeout_seconds(pattern, endpoint_group),
                    ),
                )
                if appended:
                    lane_index += 1

    historical_patterns = requested_patterns & HISTORICAL_PATTERNS
    if historical_patterns:
        for pattern in sorted(historical_patterns):
            pattern_rows = _historical_rows_for_pattern(runnable_rows, pattern)
            if not pattern_rows:
                continue
            for season_types, grouped_rows in _group_historical_rows_by_season_types(
                pattern_rows,
                pattern=pattern,
            ):
                for endpoint_slug, endpoint_rows in _historical_endpoint_row_groups(
                    grouped_rows,
                    pattern=pattern,
                ):
                    endpoints = _endpoint_names(endpoint_rows)
                    endpoint_family_value, throughput_tier_value, season_cost = (
                        _endpoint_profile_values(
                            endpoints=endpoints,
                            pattern=pattern,
                            planning_snapshot=planning_snapshot,
                        )
                    )
                    adaptive_max_span = (
                        preferred_max_span(planning_snapshot.endpoint_profiles, endpoints)
                        if planning_snapshot is not None
                        else None
                    )
                    season_cost = (
                        endpoint_cost(planning_snapshot.endpoint_profiles, endpoints)
                        if planning_snapshot is not None
                        else season_cost
                    )
                    profile_max_span = _profile_max_span(
                        chunk_profile=chunk_profile,
                        pattern=pattern,
                        throughput_tier=throughput_tier_value,
                        endpoint_family=endpoint_family_value,
                    )
                    target_cost = max(float(_max_span_for_pattern(pattern)), season_cost * 3.0)
                    for start, end in _season_bands(endpoint_rows, {pattern}):
                        supported_bands = _contract_supported_season_bands(
                            endpoints=endpoints,
                            patterns=(pattern,),
                            start=start,
                            end=end,
                        )
                        for supported_start, supported_end in supported_bands:
                            season_costs = {
                                year: season_cost
                                for year in range(supported_start, supported_end + 1)
                            }
                            for band_start, band_end in (
                                _adaptive_split_season_band(
                                    supported_start,
                                    supported_end,
                                    max_span=min(
                                        profile_max_span,
                                        adaptive_max_span or profile_max_span,
                                    ),
                                    target_cost=target_cost,
                                    season_costs=season_costs,
                                )
                                if planning_snapshot is not None
                                else _split_season_band(
                                    supported_start,
                                    supported_end,
                                    max_span=profile_max_span,
                                )
                            ):
                                endpoint_component = f"-{endpoint_slug}" if endpoint_slug else ""
                                lane_id = (
                                    f"historical-{pattern}{endpoint_component}-"
                                    f"{_season_type_slug(season_types)}-{band_start}-{band_end}"
                                )
                                lane_name = f"Historical {pattern} {band_start}-{band_end}"
                                if endpoints and endpoint_slug:
                                    lane_name = f"{lane_name} ({', '.join(endpoints)})"
                                if season_types:
                                    lane_name = f"{lane_name} ({', '.join(season_types)})"
                                appended = _append_lane_if_supported(
                                    lanes,
                                    FullExtractionLane(
                                        lane_id=lane_id,
                                        lane_index=lane_index,
                                        lane_name=lane_name,
                                        lane_kind="historical",
                                        season_start=band_start,
                                        season_end=band_end,
                                        patterns=(pattern,),
                                        season_types=season_types,
                                        endpoints=endpoints,
                                        use_vpn=True,
                                        resume_only=False,
                                        timeout_seconds=_historical_timeout_seconds(
                                            pattern,
                                            band_start,
                                            band_end,
                                        ),
                                    ),
                                )
                                if appended:
                                    lane_index += 1

    cross_product_rows = [
        row
        for row in runnable_rows
        if str(row.get("execution_semantics")) == "historical_backfill"
        and {str(pattern) for pattern in row.get("param_patterns", [])} & CROSS_PRODUCT_PATTERNS
    ]
    supported_cross_product_rows = [
        row
        for row in cross_product_rows
        if str(row.get("season_type_contract_status")) == "supported"
    ]
    if supported_cross_product_rows:
        for season_types, grouped_rows in _group_historical_rows_by_season_types(
            supported_cross_product_rows,
            pattern="player_team_season",
        ):
            patterns = tuple(
                sorted(
                    {
                        str(pattern)
                        for row in grouped_rows
                        for pattern in row.get("param_patterns", [])
                        if str(pattern) in CROSS_PRODUCT_PATTERNS
                    }
                )
            )
            endpoints = _endpoint_names(grouped_rows)
            endpoint_family_value, throughput_tier_value, _endpoint_cost_value = (
                _endpoint_profile_values(
                    endpoints=endpoints,
                    pattern="player_team_season",
                    planning_snapshot=planning_snapshot,
                )
            )
            end_year = _current_end_year()
            cross_product_costs = {
                year: max(
                    1.0,
                    sum(
                        count / 500.0
                        for (season, _season_type), count in (
                            planning_snapshot.cross_product_pair_counts.items()
                            if planning_snapshot is not None
                            else {}
                        )
                        if str(season).startswith(str(year))
                    ),
                )
                for year in range(DEFAULT_HISTORICAL_START, end_year + 1)
            }
            supported_bands = _contract_supported_season_bands(
                endpoints=endpoints,
                patterns=patterns,
                start=DEFAULT_HISTORICAL_START,
                end=end_year,
            )
            for supported_start, supported_end in supported_bands:
                supported_costs = {
                    year: cross_product_costs[year]
                    for year in range(supported_start, supported_end + 1)
                }
                for band_start, band_end in (
                    _adaptive_split_season_band(
                        supported_start,
                        supported_end,
                        max_span=_profile_max_span(
                            chunk_profile=chunk_profile,
                            pattern="player_team_season",
                            throughput_tier=throughput_tier_value,
                            endpoint_family=endpoint_family_value,
                        ),
                        target_cost=max(6.0, CROSS_PRODUCT_MAX_SPAN * 1.5),
                        season_costs=supported_costs,
                    )
                    if planning_snapshot is not None
                    else _split_season_band(
                        supported_start,
                        supported_end,
                        max_span=_profile_max_span(
                            chunk_profile=chunk_profile,
                            pattern="player_team_season",
                            throughput_tier=throughput_tier_value,
                            endpoint_family=endpoint_family_value,
                        ),
                    )
                ):
                    appended = _append_lane_if_supported(
                        lanes,
                        FullExtractionLane(
                            lane_id=(
                                f"cross-product-{_season_type_slug(season_types)}-"
                                f"{band_start}-{band_end}"
                            ),
                            lane_index=lane_index,
                            lane_name=f"Cross Product Historical {band_start}-{band_end}",
                            lane_kind="cross_product",
                            season_start=band_start,
                            season_end=band_end,
                            patterns=patterns,
                            season_types=season_types,
                            endpoints=endpoints,
                            use_vpn=True,
                            resume_only=False,
                            timeout_seconds=_cross_product_timeout_seconds(
                                band_start,
                                band_end,
                            ),
                        ),
                    )
                    if appended:
                        lane_index += 1

    if not lanes:
        msg = "Selected full-extraction filters produced no runnable lanes"
        raise ValueError(msg)

    return _schedule_lanes(
        lanes,
        chunk_profile=chunk_profile,
        planning_snapshot=planning_snapshot,
    )


def normalize_manifest(
    raw_manifest: dict[str, Any] | list[dict[str, Any]],
) -> FullExtractionManifest:
    raw_lanes = raw_manifest.get("lanes", []) if isinstance(raw_manifest, dict) else raw_manifest
    chain_state = (
        _normalize_chain_state(raw_manifest.get("chain_state", {}))
        if isinstance(raw_manifest, dict)
        else FullExtractionChainState()
    )
    lanes = tuple(
        _normalize_lane(dict(raw_lane), lane_index) for lane_index, raw_lane in enumerate(raw_lanes)
    )
    raw_matrix = raw_manifest.get("github_matrix", {}) if isinstance(raw_manifest, dict) else {}
    raw_matrix_include = raw_matrix.get("include", []) if isinstance(raw_matrix, dict) else []
    matrix_lane_ids = frozenset(
        str(row.get("lane_id", "")).strip()
        for row in raw_matrix_include
        if isinstance(row, dict) and str(row.get("lane_id", "")).strip()
    )
    return FullExtractionManifest(
        lanes=lanes,
        chain_state=chain_state,
        matrix_lane_ids=matrix_lane_ids,
    )


def manifest_payload(
    lanes: list[FullExtractionLane],
    *,
    chain_state: FullExtractionChainState | None = None,
    max_matrix_lanes: int = MAX_GITHUB_MATRIX_LANES,
) -> dict[str, Any]:
    lane_dicts = [_lane_payload(lane) for lane in lanes]
    active_lanes = [lane for lane in lanes if not lane.resume_only]
    matrix_lanes = active_lanes[:max_matrix_lanes]
    deferred_lane_count = max(0, len(active_lanes) - len(matrix_lanes))
    chunk_profiles = sorted({lane.chunk_profile for lane in lanes if lane.chunk_profile})
    coverage_fingerprint = _coverage_fingerprint(lanes)
    return {
        "manifest_version": 2,
        "chunk_profile": chunk_profiles[0] if len(chunk_profiles) == 1 else "mixed",
        "coverage_fingerprint": coverage_fingerprint,
        "lane_count": len(lanes),
        "active_lane_count": len(active_lanes),
        "resume_only_lane_count": len(lanes) - len(active_lanes),
        "matrix_lane_count": len(matrix_lanes),
        "deferred_lane_count": deferred_lane_count,
        "planned_wave_count": max((lane.planned_wave for lane in lanes), default=0) + 1,
        "top_cost_lanes": [
            {
                "lane_id": lane.lane_id,
                "estimated_lane_cost": lane.estimated_lane_cost,
                "schedule_priority": lane.schedule_priority,
                "planned_wave": lane.planned_wave,
            }
            for lane in sorted(
                active_lanes,
                key=lambda lane: (-lane.schedule_priority, lane.lane_id),
            )[:10]
        ],
        "lanes": lane_dicts,
        "chain_state": (chain_state or FullExtractionChainState()).to_payload(),
        "github_matrix": {"include": [lane.to_workflow_dict() for lane in matrix_lanes]},
    }


def _lane_payload(lane: FullExtractionLane, *, compact: bool = False) -> dict[str, Any]:
    payload = asdict(lane)
    if compact:
        # Redispatch payloads only need enough state to reconstruct lanes on the
        # next workflow iteration. Drop derived/default fields so chained
        # workflow_dispatch inputs stay under GitHub's size limits.
        payload.pop("lane_name", None)
        payload.pop("lane_index", None)
        if not lane.season_types:
            payload.pop("season_types", None)
        if not lane.endpoints:
            payload.pop("endpoints", None)
        if lane.use_vpn is True:
            payload.pop("use_vpn", None)
        if lane.resume_only is False:
            payload.pop("resume_only", None)
        if not lane.failure_streak:
            payload.pop("failure_streak", None)
        if not lane.last_failure_reason:
            payload.pop("last_failure_reason", None)
        if not lane.parent_lane_id:
            payload.pop("parent_lane_id", None)
        if not lane.split_generation:
            payload.pop("split_generation", None)
        if lane.chunk_profile == "standard":
            payload.pop("chunk_profile", None)
        if not lane.endpoint_family:
            payload.pop("endpoint_family", None)
        if not lane.throughput_tier:
            payload.pop("throughput_tier", None)
        if not lane.estimated_lane_cost:
            payload.pop("estimated_lane_cost", None)
        if not lane.coverage_units_hash:
            payload.pop("coverage_units_hash", None)
        if not lane.schedule_priority:
            payload.pop("schedule_priority", None)
        if not lane.planned_wave:
            payload.pop("planned_wave", None)
    return payload


def redispatch_manifest_payload(
    lanes: list[FullExtractionLane],
    *,
    chain_state: FullExtractionChainState | None = None,
) -> dict[str, Any]:
    return {
        "lanes": [_lane_payload(lane, compact=True) for lane in lanes],
        "chain_state": (chain_state or FullExtractionChainState()).to_payload(),
    }


def validate_workflow_dispatch_manifest_json(
    raw_json: str,
    *,
    max_chars: int = MAX_WORKFLOW_DISPATCH_JSON_CHARS,
) -> None:
    """Reject manual JSON manifests that are too large for workflow_dispatch.

    GitHub currently caps the combined workflow_dispatch input payload at
    65,535 characters.  Keep a conservative buffer because scalar inputs share
    the same budget.
    """
    if len(raw_json) > max_chars:
        msg = (
            "lane_manifest_json is too large for workflow_dispatch "
            f"({len(raw_json)} chars > {max_chars}); upload the manifest as an "
            "artifact and pass lane_manifest_run_id/lane_manifest_artifact_name instead"
        )
        raise ValueError(msg)


def _load_manifest_argument(
    raw_json: str | None, path: Path | None
) -> FullExtractionManifest | None:
    if raw_json:
        validate_workflow_dispatch_manifest_json(raw_json)
        return normalize_manifest(json.loads(raw_json))
    if path is not None:
        return normalize_manifest(json.loads(path.read_text(encoding="utf-8")))
    return None


def _metadata_by_lane(metadata_dir: Path) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for candidate in sorted(metadata_dir.rglob("*.json")):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Checkout/setup failures can leave zero-byte metadata artifacts; treat
            # those as missing metadata so resume policy can decide whether to retry.
            continue
        lane_id = str(payload.get("lane_id", "")).strip()
        if lane_id:
            payloads[lane_id] = payload
    return payloads


def _metadata_quarantined_servers(metadata: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    quarantined: list[str] = []
    seen: set[str] = set()
    for payload in metadata.values():
        vpn_payload = payload.get("vpn", {})
        if not isinstance(vpn_payload, dict):
            continue
        for server in _normalize_server_list(vpn_payload.get("failed_servers", [])):
            if server in seen:
                continue
            seen.add(server)
            quarantined.append(server)
    return tuple(quarantined)


def _timeout_lane_can_split(lane: FullExtractionLane) -> bool:
    if lane.season_start is None or lane.season_end is None:
        return False
    if _season_span(lane.season_start, lane.season_end) <= 1:
        return False
    if not lane.patterns:
        return False
    return bool(set(lane.patterns) & TIMEOUT_SPLIT_PATTERNS)


def _timeout_split_bands(lane: FullExtractionLane) -> list[tuple[int, int]]:
    if lane.season_start is None or lane.season_end is None:
        return []
    span = _season_span(lane.season_start, lane.season_end)
    if set(lane.patterns) & {"game", "date"} and span <= 4:
        return _split_season_band(lane.season_start, lane.season_end, max_span=1)
    policy_max_span = _max_span_for_lane(lane) or span
    child_span = max(1, min(policy_max_span, span // 2))
    if child_span >= span:
        child_span = span - 1
    return _split_season_band(lane.season_start, lane.season_end, max_span=child_span)


def _lane_exceeds_policy(lane: FullExtractionLane) -> bool:
    if lane.season_start is None or lane.season_end is None:
        return False
    max_span = _max_span_for_lane(lane)
    return max_span is not None and _season_span(lane.season_start, lane.season_end) > max_span


def _policy_split_bands(lane: FullExtractionLane) -> list[tuple[int, int]]:
    if lane.season_start is None or lane.season_end is None:
        return []
    max_span = _max_span_for_lane(lane)
    if max_span is None:
        return []
    return _split_season_band(lane.season_start, lane.season_end, max_span=max_span)


def _split_lane_by_bands(
    lane: FullExtractionLane,
    *,
    bands: list[tuple[int, int]],
    reason: str,
) -> list[FullExtractionLane]:
    parent_lane_id = lane.parent_lane_id or lane.lane_id
    children: list[FullExtractionLane] = []
    for start, end in bands:
        child_lane_id = f"{_lane_slug(parent_lane_id)}-split-{start}-{end}"
        children.append(
            replace(
                lane,
                lane_id=child_lane_id,
                lane_name=f"{lane.lane_name} {start}-{end}",
                season_start=start,
                season_end=end,
                resume_only=False,
                failure_streak=0,
                last_failure_reason=f"split-from-{reason}",
                parent_lane_id=parent_lane_id,
                split_generation=lane.split_generation + 1,
            )
        )
    return children


def _split_timeout_lane(lane: FullExtractionLane, *, reason: str) -> list[FullExtractionLane]:
    return _split_lane_by_bands(lane, bands=_timeout_split_bands(lane), reason=reason)


def _split_legacy_oversized_lane(
    lane: FullExtractionLane, *, reason: str
) -> list[FullExtractionLane]:
    return _split_lane_by_bands(lane, bands=_policy_split_bands(lane), reason=reason)


def _status_allows_legacy_split(status: str) -> bool:
    return status not in {"cancelled", "cancellation_no_metadata"}


def _reindex_lanes(lanes: list[FullExtractionLane]) -> list[FullExtractionLane]:
    return [replace(lane, lane_index=index) for index, lane in enumerate(lanes)]


def _manifest_chunk_profile(
    lanes: list[FullExtractionLane] | tuple[FullExtractionLane, ...],
) -> str:
    profiles = [lane.chunk_profile for lane in lanes if lane.chunk_profile]
    if not profiles:
        return "standard"
    unique_profiles = set(profiles)
    if len(unique_profiles) == 1:
        return _validate_chunk_profile(profiles[0])
    # Mixed manifests can arise during manual recovery. Keep the narrowest policy.
    if "micro" in unique_profiles:
        return "micro"
    if "balanced-small" in unique_profiles:
        return "balanced-small"
    return "standard"


def _int_metadata_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _metadata_has_required_noncomplete_artifacts(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    vpn_payload = payload.get("vpn")
    return isinstance(vpn_payload, dict)


def lane_outcome_from_metadata(
    payload: dict[str, Any] | None,
    lane: FullExtractionLane | None = None,
) -> FinalLaneOutcome | str:
    if not payload:
        return "pipeline_failure"

    metadata_status = str(payload.get("status") or "").strip()
    raw_status = str(
        payload.get("raw_status") or payload.get("extract_status") or metadata_status
    ).strip()
    if metadata_status == "complete":
        return "complete"
    if metadata_status in {"needs_resume", "contract_blocked"}:
        if not _metadata_has_required_noncomplete_artifacts(payload):
            return "pipeline_failure"
        return metadata_status
    if metadata_status == "pipeline_failure" and raw_status == "pipeline_failure":
        if not _metadata_has_required_noncomplete_artifacts(payload):
            return "pipeline_failure"
        return "pipeline_failure"
    if not _metadata_has_required_noncomplete_artifacts(payload):
        return "pipeline_failure"

    vpn_payload = payload.get("vpn")
    vpn_status = (
        str(vpn_payload.get("status") or "").strip() if isinstance(vpn_payload, dict) else ""
    )
    if metadata_status == "pipeline_failure" and (
        raw_status in RETRYABLE_PIPELINE_FAILURE_STATUSES
        or str(payload.get("vpn_status") or "").strip() in RETRYABLE_PIPELINE_FAILURE_STATUSES
        or vpn_status in RETRYABLE_PIPELINE_FAILURE_STATUSES
    ):
        return "needs_resume"

    telemetry = payload.get("telemetry", {})
    if not isinstance(telemetry, dict):
        telemetry = {}
    rows_persisted = _int_metadata_value(telemetry.get("rows_persisted"))
    journal_skips = _int_metadata_value(telemetry.get("journal_skips"))
    running_calls = _int_metadata_value(
        (telemetry.get("db_telemetry") or {}).get("running_calls")
        if isinstance(telemetry.get("db_telemetry"), dict)
        else 0
    )
    failed_calls = _int_metadata_value(telemetry.get("failed_calls"))
    endpoints = tuple(str(value) for value in payload.get("endpoints", []) if str(value))
    patterns = tuple(str(value) for value in payload.get("patterns", []) if str(value))
    season_start = payload.get("season_start")
    season_end = payload.get("season_end")
    lane_contract_rules = (
        _lane_contract_blocking_rules(lane)
        if lane is not None
        else tuple(
            rule.to_dict()
            for rule in contract_blocking_rules_for_lane(
                endpoints=endpoints,
                patterns=patterns,
                season_start=None if season_start in {None, ""} else int(season_start),
                season_end=None if season_end in {None, ""} else int(season_end),
            )
        )
    )

    if rows_persisted == 0 and failed_calls > 0 and lane_contract_rules:
        return "contract_blocked"
    if raw_status == "extract-error" and (
        rows_persisted > 0 or journal_skips > 0 or running_calls > 0
    ):
        return "needs_resume"
    if raw_status in SPLITTABLE_TIMEOUT_STATUSES:
        return "needs_resume"
    if raw_status == "cancelled" and (rows_persisted > 0 or journal_skips > 0 or running_calls > 0):
        return "needs_resume"
    return "pipeline_failure"


def build_resume_manifest(
    lanes: list[FullExtractionLane],
    metadata_dir: Path,
    *,
    chain_state: FullExtractionChainState | None = None,
    attempted_lane_ids: frozenset[str] | None = None,
    allow_missing_attempted_metadata: bool = False,
    completed_artifact_run_id: str | None = None,
    chunk_profile: str | None = None,
    latest_checkpoint_run_id: str | None = None,
    latest_checkpoint_artifact_name: str | None = None,
    latest_checkpoint_generation: int | None = None,
    latest_checkpoint_coverage_hash: str | None = None,
) -> tuple[list[FullExtractionLane], FullExtractionChainState, dict[str, Any]]:
    metadata = _metadata_by_lane(metadata_dir)
    next_lanes: list[FullExtractionLane] = []
    resumed = 0
    active = 0
    deferred = 0
    outcome_counts: dict[str, int] = {}
    failure_reason_counts: dict[str, int] = {}
    split_lane_count = 0
    contract_blocked = 0
    blocked_lanes: list[FullExtractionLane] = []
    pipeline_failures: list[str] = []
    profile_override = _validate_chunk_profile(chunk_profile) if chunk_profile else None

    for source_lane in lanes:
        lane = (
            replace(source_lane, chunk_profile=profile_override)
            if profile_override is not None
            else source_lane
        )
        payload = metadata.get(lane.lane_id)
        raw_status = str(payload.get("status", "")) if payload else ""
        if not raw_status and lane.resume_only:
            next_lanes.append(lane)
            resumed += 1
            continue
        if (
            not raw_status
            and attempted_lane_ids is not None
            and lane.lane_id not in attempted_lane_ids
        ):
            next_lanes.append(lane)
            if lane.resume_only:
                resumed += 1
            else:
                active += 1
                deferred += 1
                if _lane_exceeds_policy(lane):
                    next_lanes.pop()
                    child_lanes = _split_legacy_oversized_lane(
                        lane,
                        reason="resume-profile-oversized",
                    )
                    next_lanes.extend(child_lanes)
                    split_lane_count += len(child_lanes)
                    active += len(child_lanes) - 1
                    deferred += len(child_lanes) - 1
            continue
        if payload is None and allow_missing_attempted_metadata:
            if _lane_exceeds_policy(lane):
                child_lanes = _split_legacy_oversized_lane(
                    lane,
                    reason="missing-metadata-profile-oversized",
                )
                next_lanes.extend(child_lanes)
                split_lane_count += len(child_lanes)
                active += len(child_lanes)
                failure_reason_counts["missing-metadata"] = (
                    failure_reason_counts.get("missing-metadata", 0) + 1
                )
                outcome_counts["needs_resume"] = outcome_counts.get("needs_resume", 0) + 1
                continue
            next_lanes.append(
                replace(
                    lane,
                    resume_only=False,
                    last_failure_reason="missing-metadata",
                )
            )
            active += 1
            failure_reason_counts["missing-metadata"] = (
                failure_reason_counts.get("missing-metadata", 0) + 1
            )
            outcome_counts["needs_resume"] = outcome_counts.get("needs_resume", 0) + 1
            continue
        if payload is None:
            payload = {"lane_id": lane.lane_id, "status": "missing-metadata", "vpn": {}}
        status = str(lane_outcome_from_metadata(payload, lane))
        outcome_counts[status] = outcome_counts.get(status, 0) + 1
        if status == "complete":
            next_lanes.append(
                replace(
                    lane,
                    resume_only=True,
                    failure_streak=0,
                    last_failure_reason="",
                )
            )
            resumed += 1
            continue
        if status == "contract_blocked":
            contract_blocked += 1
            continue
        failure_reason = str(payload.get("raw_status") or raw_status or status)
        failure_reason_counts[failure_reason] = failure_reason_counts.get(failure_reason, 0) + 1
        if status == "pipeline_failure":
            pipeline_failures.append(f"{lane.lane_id} ({failure_reason})")
            continue
        if _status_allows_legacy_split(status) and _lane_exceeds_policy(lane):
            child_lanes = _split_legacy_oversized_lane(lane, reason=f"legacy-oversized-{status}")
            next_lanes.extend(child_lanes)
            split_lane_count += len(child_lanes)
            active += len(child_lanes)
            continue
        if status in SPLITTABLE_TIMEOUT_STATUSES and _timeout_lane_can_split(lane):
            child_lanes = _split_timeout_lane(lane, reason=status)
            next_lanes.extend(child_lanes)
            split_lane_count += len(child_lanes)
            active += len(child_lanes)
            continue
        failure_streak = lane.failure_streak + 1 if lane.last_failure_reason == status else 1
        next_lane = replace(
            lane,
            resume_only=False,
            failure_streak=failure_streak,
            last_failure_reason=status,
        )
        if status != "needs_resume" and failure_streak >= MAX_CONSECUTIVE_FAILURES:
            blocked_lanes.append(next_lane)
        next_lanes.append(next_lane)
        active += 1

    if pipeline_failures:
        msg = "Pipeline-failure lane outcomes prevent safe redispatch: " + ", ".join(
            pipeline_failures
        )
        raise ValueError(msg)

    if blocked_lanes:
        blocked = ", ".join(
            f"{lane.lane_id} ({lane.last_failure_reason} x{lane.failure_streak})"
            for lane in blocked_lanes
        )
        msg = (
            "Repeated lane failures reached the chain safety cap; refusing to redispatch: "
            f"{blocked}"
        )
        raise ValueError(msg)

    merged_quarantined_servers = _normalize_server_list(
        [
            *(chain_state.vpn_quarantined_servers if chain_state is not None else ()),
            *_metadata_quarantined_servers(metadata),
        ]
    )
    merged_artifact_run_ids = _normalize_server_list(
        [
            *(chain_state.artifact_run_ids if chain_state is not None else ()),
            *([completed_artifact_run_id] if completed_artifact_run_id else []),
        ]
    )
    profile = profile_override or _manifest_chunk_profile(next_lanes or lanes)
    next_lanes = _schedule_lanes(next_lanes, chunk_profile=profile)
    previous_state = chain_state or FullExtractionChainState()
    checkpoint_generation = (
        int(latest_checkpoint_generation)
        if latest_checkpoint_generation is not None
        else previous_state.latest_checkpoint_generation
    )
    next_chain_state = FullExtractionChainState(
        vpn_quarantined_servers=tuple(sorted(merged_quarantined_servers)),
        artifact_run_ids=tuple(merged_artifact_run_ids),
        latest_checkpoint_run_id=(
            _normalize_scalar_string(latest_checkpoint_run_id)
            or previous_state.latest_checkpoint_run_id
        ),
        latest_checkpoint_artifact_name=(
            _normalize_scalar_string(latest_checkpoint_artifact_name)
            or previous_state.latest_checkpoint_artifact_name
        ),
        latest_checkpoint_generation=checkpoint_generation,
        latest_checkpoint_coverage_hash=(
            _normalize_scalar_string(latest_checkpoint_coverage_hash)
            or previous_state.latest_checkpoint_coverage_hash
        ),
    )

    return (
        next_lanes,
        next_chain_state,
        {
            "vpn_quarantined_server_count": len(next_chain_state.vpn_quarantined_servers),
            "active_lane_count": active,
            "resume_only_lane_count": resumed,
            "deferred_lane_count": deferred,
            "contract_blocked_lane_count": contract_blocked,
            "blocked_lane_count": 0,
            "split_lane_count": split_lane_count,
            "outcome_counts": outcome_counts,
            "failure_reason_counts": failure_reason_counts,
        },
    )


def build_metadata_audit(metadata_dir: Path) -> dict[str, Any]:
    metadata = _metadata_by_lane(metadata_dir)
    status_counts: dict[str, int] = {}
    kind_counts: dict[str, dict[str, int]] = {}
    endpoint_counts: dict[str, dict[str, int]] = {}
    vpn_status_counts: dict[str, int] = {}
    zero_row_lanes: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    contract_blocked_lanes: list[dict[str, Any]] = []
    pipeline_failure_lanes: list[dict[str, Any]] = []
    total_rows = 0
    total_failed_calls = 0
    total_journal_skips = 0

    for lane_id, payload in sorted(metadata.items()):
        status = str(lane_outcome_from_metadata(payload))
        kind = str(payload.get("lane_kind") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        kind_bucket = kind_counts.setdefault(kind, {})
        kind_bucket[status] = kind_bucket.get(status, 0) + 1
        vpn_status = str(payload.get("vpn_status") or "unknown")
        vpn_status_counts[vpn_status] = vpn_status_counts.get(vpn_status, 0) + 1

        endpoints = payload.get("endpoints", [])
        if not isinstance(endpoints, list):
            endpoints = []
        telemetry = payload.get("telemetry", {})
        if not isinstance(telemetry, dict):
            telemetry = {}
        rows = int(telemetry.get("rows_persisted") or 0)
        failed_calls = int(telemetry.get("failed_calls") or 0)
        journal_skips = int(telemetry.get("journal_skips") or 0)
        total_rows += rows
        total_failed_calls += failed_calls
        total_journal_skips += journal_skips

        for endpoint in endpoints:
            endpoint_name = str(endpoint)
            endpoint_bucket = endpoint_counts.setdefault(endpoint_name, {})
            endpoint_bucket[status] = endpoint_bucket.get(status, 0) + 1

        if rows == 0 and status != "complete":
            zero_row_lanes.append(
                {
                    "lane_id": lane_id,
                    "status": status,
                    "raw_status": str(payload.get("raw_status") or ""),
                    "reason": str(telemetry.get("zero_row_reason") or "unknown"),
                    "endpoints": endpoints,
                }
            )
        blocker = {
            "lane_id": lane_id,
            "status": status,
            "raw_status": str(payload.get("raw_status") or ""),
            "kind": kind,
            "rows_persisted": rows,
            "failed_calls": failed_calls,
        }
        if status == "contract_blocked":
            blocker["support_rules"] = payload.get("support_rules", [])
            contract_blocked_lanes.append(blocker)
        elif status == "pipeline_failure":
            pipeline_failure_lanes.append(blocker)
            blockers.append(blocker)
        elif status not in MERGE_TERMINAL_OUTCOMES:
            blockers.append(blocker)

    return {
        "lane_count": len(metadata),
        "status_counts": status_counts,
        "outcome_counts": status_counts,
        "kind_status_counts": kind_counts,
        "endpoint_status_counts": endpoint_counts,
        "vpn_status_counts": vpn_status_counts,
        "rows_persisted": total_rows,
        "failed_calls": total_failed_calls,
        "journal_skips": total_journal_skips,
        "zero_row_lanes": zero_row_lanes,
        "contract_blocked_lanes": contract_blocked_lanes,
        "pipeline_failure_lanes": pipeline_failure_lanes,
        "blockers": blockers,
    }


def _merge_database_paths(
    *,
    db_paths: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    db_paths = sorted(path for path in db_paths if path.is_file())
    if not db_paths:
        msg = "No lane databases were available to merge"
        raise FileNotFoundError(msg)

    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / "nba.duckdb"
    if target_path.exists():
        target_path.unlink()

    def quote_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def table_exists(conn: duckdb.DuckDBPyConnection, database: str, table_name: str) -> bool:
        return bool(
            row_count(
                conn,
                """
                SELECT COUNT(*)
                FROM duckdb_tables()
                WHERE database_name = ?
                  AND schema_name = 'main'
                  AND table_name = ?
                """,
                [database, table_name],
            )
        )

    def table_schema(
        conn: duckdb.DuckDBPyConnection,
        database: str,
        table_name: str,
    ) -> list[tuple[str, str]]:
        return conn.execute(
            """
            SELECT column_name, data_type
            FROM duckdb_columns()
            WHERE database_name = ?
              AND schema_name = 'main'
              AND table_name = ?
            ORDER BY column_index
            """,
            [database, table_name],
        ).fetchall()

    def row_count(
        conn: duckdb.DuckDBPyConnection,
        sql: str,
        parameters: list[Any] | None = None,
    ) -> int:
        row = conn.execute(sql, parameters).fetchone()
        if row is None:
            msg = f"Expected COUNT(*) query to return a row: {sql}"
            raise RuntimeError(msg)
        return int(row[0])

    target = duckdb.connect(str(target_path))
    attached_aliases: list[str] = []
    merge_failed = False
    merged_tables = 0
    table_reports: dict[str, dict[str, Any]] = {}
    journal_report: dict[str, Any] = {
        "source_rows": 0,
        "inserted_rows": 0,
        "duplicate_rows": 0,
        "source_count": 0,
        "per_source": [],
    }

    try:
        for index, db_path in enumerate(db_paths):
            alias = f"src_{index}"
            target.execute(f"ATTACH '{db_path}' AS {alias} (READ_ONLY)")
            attached_aliases.append(alias)

        target.execute("BEGIN TRANSACTION")
        try:
            for alias, db_path in zip(attached_aliases, db_paths, strict=True):
                tables = [
                    row[0]
                    for row in target.execute(
                        "SELECT table_name FROM duckdb_tables() "
                        f"WHERE database_name = '{alias}' AND schema_name = 'main' "
                        "AND table_name LIKE 'stg_%'"
                    ).fetchall()
                ]
                for table_name in tables:
                    quoted_table = quote_identifier(table_name)
                    source_schema = table_schema(target, alias, table_name)
                    if not table_exists(target, "nba", table_name):
                        target.execute(
                            f"CREATE TABLE main.{quoted_table} AS "
                            f"SELECT * FROM {alias}.{quoted_table} WHERE FALSE"
                        )
                    target_schema = table_schema(target, "nba", table_name)
                    if target_schema != source_schema:
                        msg = (
                            f"Schema mismatch while merging {table_name} from {db_path}: "
                            f"expected {target_schema}, got {source_schema}"
                        )
                        raise ValueError(msg)

                    source_rows = row_count(target, f"SELECT COUNT(*) FROM {alias}.{quoted_table}")
                    before_rows = row_count(target, f"SELECT COUNT(*) FROM main.{quoted_table}")
                    target.execute(
                        f"INSERT INTO main.{quoted_table} "
                        f"SELECT * FROM {alias}.{quoted_table} "
                        f"EXCEPT SELECT * FROM main.{quoted_table}"
                    )
                    after_rows = row_count(target, f"SELECT COUNT(*) FROM main.{quoted_table}")
                    inserted_rows = after_rows - before_rows
                    duplicate_rows = max(source_rows - inserted_rows, 0)
                    report = table_reports.setdefault(
                        table_name,
                        {
                            "source_rows": 0,
                            "inserted_rows": 0,
                            "duplicate_rows": 0,
                            "source_count": 0,
                            "per_source": [],
                        },
                    )
                    report["source_rows"] += source_rows
                    report["inserted_rows"] += inserted_rows
                    report["duplicate_rows"] += duplicate_rows
                    report["source_count"] += 1
                    report["per_source"].append(
                        {
                            "database_path": str(db_path),
                            "source_rows": source_rows,
                            "inserted_rows": inserted_rows,
                            "duplicate_rows": duplicate_rows,
                        }
                    )
                    merged_tables += 1

                if table_exists(target, alias, "_extraction_journal"):
                    source_schema = table_schema(target, alias, "_extraction_journal")
                    if not table_exists(target, "nba", "_extraction_journal"):
                        target.execute(
                            "CREATE TABLE main._extraction_journal AS "
                            f"SELECT * FROM {alias}._extraction_journal WHERE FALSE"
                        )
                    target_schema = table_schema(target, "nba", "_extraction_journal")
                    if target_schema != source_schema:
                        msg = (
                            "Schema mismatch while merging _extraction_journal "
                            f"from {db_path}: expected {target_schema}, got {source_schema}"
                        )
                        raise ValueError(msg)
                    source_rows = row_count(
                        target,
                        f"SELECT COUNT(*) FROM {alias}._extraction_journal",
                    )
                    before_rows = row_count(target, "SELECT COUNT(*) FROM main._extraction_journal")
                    target.execute(
                        f"""
                        INSERT INTO main._extraction_journal
                        SELECT src.*
                        FROM {alias}._extraction_journal AS src
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM main._extraction_journal AS dst
                            WHERE dst.endpoint = src.endpoint
                              AND dst.params IS NOT DISTINCT FROM src.params
                        )
                        """
                    )
                    after_rows = row_count(target, "SELECT COUNT(*) FROM main._extraction_journal")
                    inserted_rows = after_rows - before_rows
                    duplicate_rows = max(source_rows - inserted_rows, 0)
                    journal_report["source_rows"] += source_rows
                    journal_report["inserted_rows"] += inserted_rows
                    journal_report["duplicate_rows"] += duplicate_rows
                    journal_report["source_count"] += 1
                    journal_report["per_source"].append(
                        {
                            "database_path": str(db_path),
                            "source_rows": source_rows,
                            "inserted_rows": inserted_rows,
                            "duplicate_rows": duplicate_rows,
                        }
                    )
            target.execute("COMMIT")
        except Exception:
            with suppress(Exception):
                target.execute("ROLLBACK")
            raise
    except Exception:
        merge_failed = True
        raise
    finally:
        for alias in reversed(attached_aliases):
            with suppress(Exception):
                target.execute(f"DETACH {alias}")
        with suppress(Exception):
            target.close()
        if merge_failed:
            with suppress(FileNotFoundError):
                target_path.unlink()

    return {
        "merged_database_count": len(db_paths),
        "merged_table_operations": merged_tables,
        "output_path": str(target_path),
        "table_reports": table_reports,
        "journal_report": journal_report,
    }


def merge_lane_databases(
    *,
    artifacts_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    db_paths = sorted(path for path in artifacts_dir.rglob("nba.duckdb") if path.is_file())
    if not db_paths:
        msg = f"No lane databases found under {artifacts_dir}"
        raise FileNotFoundError(msg)
    return _merge_database_paths(db_paths=db_paths, output_dir=output_dir)


def _read_json_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _first_database_path(root: Path | None) -> Path | None:
    if root is None or not root.exists():
        return None
    for path in sorted(root.rglob("nba.duckdb")):
        if path.is_file():
            return path
    return None


def _database_row_counts(db_path: Path) -> tuple[dict[str, int], int]:
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                """
                SELECT table_name
                FROM duckdb_tables()
                WHERE database_name = 'nba'
                  AND schema_name = 'main'
                ORDER BY table_name
                """
            ).fetchall()
        ]
        table_counts: dict[str, int] = {}
        journal_rows = 0
        for table_name in tables:
            quoted = '"' + table_name.replace('"', '""') + '"'
            row = conn.execute(f"SELECT COUNT(*) FROM main.{quoted}").fetchone()
            count = int(row[0] if row is not None else 0)
            if table_name == "_extraction_journal":
                journal_rows = count
            elif table_name.startswith("stg_"):
                table_counts[table_name] = count
        return table_counts, journal_rows
    finally:
        conn.close()


def _metadata_complete_lane_ids(metadata: dict[str, dict[str, Any]]) -> set[str]:
    return {
        lane_id
        for lane_id, payload in metadata.items()
        if str(lane_outcome_from_metadata(payload)) == "complete"
    }


def _metadata_contract_blocked_lane_ids(
    metadata: dict[str, dict[str, Any]],
    lanes_by_id: dict[str, FullExtractionLane],
) -> set[str]:
    return {
        lane_id
        for lane_id, payload in metadata.items()
        if str(lane_outcome_from_metadata(payload, lanes_by_id.get(lane_id))) == "contract_blocked"
    }


def _lane_artifact_database_paths(
    *,
    artifacts_dir: Path,
    lane_ids: set[str],
) -> tuple[list[Path], set[str]]:
    if not lane_ids or not artifacts_dir.exists():
        return [], set()
    matched_paths: list[Path] = []
    matched_lane_ids: set[str] = set()
    ordered_lane_ids = sorted(lane_ids, key=len, reverse=True)
    for db_path in sorted(artifacts_dir.rglob("nba.duckdb")):
        parent_name = db_path.parent.name
        for lane_id in ordered_lane_ids:
            if parent_name.endswith(lane_id) or f"-{lane_id}" in parent_name:
                if lane_id not in matched_lane_ids:
                    matched_paths.append(db_path)
                    matched_lane_ids.add(lane_id)
                break
    return matched_paths, matched_lane_ids


def build_checkpoint_database(
    *,
    manifest_path: Path,
    metadata_dir: Path,
    lane_artifacts_dir: Path,
    output_dir: Path,
    report_path: Path,
    previous_checkpoint_dir: Path | None = None,
    previous_checkpoint_report_path: Path | None = None,
    chain_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    lanes = list(manifest.lanes)
    lanes_by_id = {lane.lane_id: lane for lane in lanes}
    metadata = _metadata_by_lane(metadata_dir)
    previous_report = _read_json_file(previous_checkpoint_report_path)
    previous_included_lane_ids = {
        str(value) for value in previous_report.get("included_lane_ids", []) if str(value).strip()
    }
    previous_run_ids = [
        str(value) for value in previous_report.get("included_run_ids", []) if str(value).strip()
    ]
    complete_current_lane_ids = _metadata_complete_lane_ids(metadata)
    contract_blocked_lane_ids = _metadata_contract_blocked_lane_ids(metadata, lanes_by_id)
    current_db_paths, current_included_lane_ids = _lane_artifact_database_paths(
        artifacts_dir=lane_artifacts_dir,
        lane_ids=complete_current_lane_ids,
    )
    skipped_complete_lane_ids = sorted(complete_current_lane_ids - current_included_lane_ids)
    db_paths: list[Path] = []
    db_paths.extend(current_db_paths)
    previous_db_path = _first_database_path(previous_checkpoint_dir)
    if previous_db_path is not None:
        # Merge current lanes first so newer journal rows win when endpoint/params collide.
        db_paths.append(previous_db_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    if db_paths:
        merge_summary = _merge_database_paths(db_paths=db_paths, output_dir=output_dir)
        checkpoint_db_path = Path(str(merge_summary["output_path"]))
        table_row_counts, journal_row_count = _database_row_counts(checkpoint_db_path)
        merge_mode = "checkpoint"
        output_path = str(checkpoint_db_path)
    else:
        merge_summary = {
            "merged_database_count": 0,
            "merged_table_operations": 0,
            "output_path": "",
            "table_reports": {},
            "journal_report": {},
        }
        table_row_counts = {}
        journal_row_count = 0
        merge_mode = "empty"
        output_path = ""

    included_lane_ids = previous_included_lane_ids | current_included_lane_ids
    non_contract_lane_ids = set(lanes_by_id) - contract_blocked_lane_ids
    missing_lane_ids = sorted(non_contract_lane_ids - included_lane_ids)
    included_lanes = [lane for lane in lanes if lane.lane_id in included_lane_ids]
    coverage_fingerprint = _coverage_fingerprint(included_lanes)
    checkpoint_generation = int(previous_report.get("checkpoint_generation") or 0) + 1
    included_run_ids = list(dict.fromkeys([*previous_run_ids, *([run_id] if run_id else [])]))
    report = {
        "chain_id": chain_id,
        "run_id": run_id,
        "chunk_profile": _manifest_chunk_profile(lanes),
        "checkpoint_generation": checkpoint_generation,
        "previous_checkpoint_generation": int(previous_report.get("checkpoint_generation") or 0),
        "included_lane_ids": sorted(included_lane_ids),
        "included_run_ids": included_run_ids,
        "complete_lane_count": len(included_lane_ids),
        "contract_blocked_lane_count": len(contract_blocked_lane_ids),
        "active_lane_count": len(missing_lane_ids),
        "skipped_lane_count": len(skipped_complete_lane_ids),
        "missing_lane_ids": missing_lane_ids,
        "skipped_complete_lane_ids": skipped_complete_lane_ids,
        "coverage_fingerprint": coverage_fingerprint,
        "table_row_counts": table_row_counts,
        "journal_row_count": journal_row_count,
        "merge_mode": merge_mode,
        "merge_summary": merge_summary,
        "output_path": output_path,
        "terminal_ready": not missing_lane_ids and bool(included_lane_ids),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def merge_final_database(
    *,
    artifacts_dir: Path,
    output_dir: Path,
    manifest_path: Path | None = None,
    checkpoint_dir: Path | None = None,
    checkpoint_report_path: Path | None = None,
) -> dict[str, Any]:
    fallback_reason = ""
    checkpoint_report = _read_json_file(checkpoint_report_path)
    checkpoint_db_path = _first_database_path(checkpoint_dir)
    if checkpoint_report and checkpoint_db_path is not None:
        if checkpoint_report.get("terminal_ready") is True:
            if manifest_path is not None and manifest_path.exists():
                manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
                expected_hash = _coverage_fingerprint(list(manifest.lanes))
                actual_hash = str(checkpoint_report.get("coverage_fingerprint") or "")
                if actual_hash != expected_hash:
                    fallback_reason = (
                        "checkpoint coverage fingerprint mismatch: "
                        f"expected {expected_hash}, got {actual_hash}"
                    )
                else:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    target_path = output_dir / "nba.duckdb"
                    shutil.copy2(checkpoint_db_path, target_path)
                    table_row_counts, journal_row_count = _database_row_counts(target_path)
                    return {
                        "merge_mode": "checkpoint",
                        "output_path": str(target_path),
                        "checkpoint_generation": checkpoint_report.get("checkpoint_generation"),
                        "coverage_fingerprint": actual_hash,
                        "table_row_counts": table_row_counts,
                        "journal_row_count": journal_row_count,
                    }
            else:
                output_dir.mkdir(parents=True, exist_ok=True)
                target_path = output_dir / "nba.duckdb"
                shutil.copy2(checkpoint_db_path, target_path)
                table_row_counts, journal_row_count = _database_row_counts(target_path)
                return {
                    "merge_mode": "checkpoint",
                    "output_path": str(target_path),
                    "checkpoint_generation": checkpoint_report.get("checkpoint_generation"),
                    "coverage_fingerprint": checkpoint_report.get("coverage_fingerprint"),
                    "table_row_counts": table_row_counts,
                    "journal_row_count": journal_row_count,
                }
        else:
            fallback_reason = "checkpoint report is not terminal-ready"
    elif checkpoint_report_path is not None or checkpoint_dir is not None:
        fallback_reason = "checkpoint database or report missing"

    lane_summary = merge_lane_databases(artifacts_dir=artifacts_dir, output_dir=output_dir)
    lane_summary["merge_mode"] = "lane_artifacts"
    lane_summary["fallback_reason"] = fallback_reason
    return lane_summary


def _command_plan(args: argparse.Namespace) -> int:
    manifest = _load_manifest_argument(args.lane_manifest_json, args.lane_manifest_path)
    if manifest is None:
        chunk_profile = args.chunk_profile or DEFAULT_CHUNK_PROFILE
        if args.support_matrix_path is None:
            msg = "support-matrix-path is required when no explicit lane manifest is provided"
            raise ValueError(msg)
        support_matrix_rows = _load_matrix_payload(args.support_matrix_path)
        planning_snapshot = (
            build_workload_planning_snapshot(
                support_matrix_rows,
                duckdb_path=args.duckdb_path,
            )
            if args.duckdb_path is not None
            else None
        )
        lanes = build_default_manifest(
            support_matrix_rows=support_matrix_rows,
            selected_patterns=_parse_csv(args.backfill_patterns),
            selected_endpoints=_parse_csv(args.backfill_endpoints),
            planning_snapshot=planning_snapshot,
            chunk_profile=chunk_profile,
        )
        chain_state = FullExtractionChainState()
    else:
        lanes = _schedule_lanes(
            list(manifest.lanes),
            chunk_profile=args.chunk_profile or _manifest_chunk_profile(manifest.lanes),
        )
        chain_state = manifest.chain_state

    validate_manifest(lanes)
    payload = manifest_payload(lanes, chain_state=chain_state)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


def _command_resume(args: argparse.Namespace) -> int:
    manifest = _load_manifest_argument(args.lane_manifest_json, args.lane_manifest_path)
    if manifest is None:
        msg = "lane-manifest-json or lane-manifest-path is required"
        raise ValueError(msg)

    next_lanes, next_chain_state, summary = build_resume_manifest(
        list(manifest.lanes),
        args.metadata_dir,
        chain_state=manifest.chain_state,
        attempted_lane_ids=manifest.matrix_lane_ids or None,
        allow_missing_attempted_metadata=args.allow_missing_attempted_metadata,
        completed_artifact_run_id=args.completed_artifact_run_id,
        chunk_profile=args.chunk_profile,
        latest_checkpoint_run_id=args.latest_checkpoint_run_id,
        latest_checkpoint_artifact_name=args.latest_checkpoint_artifact_name,
        latest_checkpoint_generation=args.latest_checkpoint_generation,
        latest_checkpoint_coverage_hash=args.latest_checkpoint_coverage_hash,
    )
    validate_manifest(next_lanes)
    payload = manifest_payload(next_lanes, chain_state=next_chain_state)
    payload["resume_summary"] = summary
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


def _command_merge(args: argparse.Namespace) -> int:
    summary = merge_final_database(
        artifacts_dir=args.artifacts_dir,
        output_dir=args.output_dir,
        manifest_path=args.manifest_path,
        checkpoint_dir=args.checkpoint_dir,
        checkpoint_report_path=args.checkpoint_report_path,
    )
    print(json.dumps(summary))
    return 0


def _command_checkpoint(args: argparse.Namespace) -> int:
    summary = build_checkpoint_database(
        manifest_path=args.lane_manifest_path,
        metadata_dir=args.metadata_dir,
        lane_artifacts_dir=args.artifacts_dir,
        output_dir=args.output_dir,
        report_path=args.report_path,
        previous_checkpoint_dir=args.previous_checkpoint_dir,
        previous_checkpoint_report_path=args.previous_checkpoint_report_path,
        chain_id=args.chain_id,
        run_id=args.run_id,
    )
    print(json.dumps(summary))
    return 0


def _command_audit(args: argparse.Namespace) -> int:
    summary = build_metadata_audit(args.metadata_dir)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Full extraction control-plane helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Build a workflow lane manifest.")
    plan.add_argument("--support-matrix-path", type=Path, default=None)
    plan.add_argument("--lane-manifest-json", type=str, default=None)
    plan.add_argument("--lane-manifest-path", type=Path, default=None)
    plan.add_argument("--backfill-patterns", type=str, default=None)
    plan.add_argument("--backfill-endpoints", type=str, default=None)
    plan.add_argument("--duckdb-path", type=Path, default=None)
    plan.add_argument("--chunk-profile", choices=sorted(CHUNK_PROFILES), default=None)
    plan.add_argument("--output-path", type=Path, required=True)
    plan.set_defaults(func=_command_plan)

    resume = subparsers.add_parser("resume", help="Build the next chained manifest.")
    resume.add_argument("--lane-manifest-json", type=str, default=None)
    resume.add_argument("--lane-manifest-path", type=Path, default=None)
    resume.add_argument("--metadata-dir", type=Path, required=True)
    resume.add_argument("--completed-artifact-run-id", type=str, default=None)
    resume.add_argument("--latest-checkpoint-run-id", type=str, default=None)
    resume.add_argument("--latest-checkpoint-artifact-name", type=str, default=None)
    resume.add_argument("--latest-checkpoint-generation", type=int, default=None)
    resume.add_argument("--latest-checkpoint-coverage-hash", type=str, default=None)
    resume.add_argument("--chunk-profile", choices=sorted(CHUNK_PROFILES), default=None)
    resume.add_argument("--allow-missing-attempted-metadata", action="store_true")
    resume.add_argument("--output-path", type=Path, required=True)
    resume.set_defaults(func=_command_resume)

    checkpoint = subparsers.add_parser("checkpoint", help="Build a cumulative checkpoint DB.")
    checkpoint.add_argument("--lane-manifest-path", type=Path, required=True)
    checkpoint.add_argument("--metadata-dir", type=Path, required=True)
    checkpoint.add_argument("--artifacts-dir", type=Path, required=True)
    checkpoint.add_argument("--previous-checkpoint-dir", type=Path, default=None)
    checkpoint.add_argument("--previous-checkpoint-report-path", type=Path, default=None)
    checkpoint.add_argument("--output-dir", type=Path, required=True)
    checkpoint.add_argument("--report-path", type=Path, required=True)
    checkpoint.add_argument("--chain-id", type=str, default="")
    checkpoint.add_argument("--run-id", type=str, default="")
    checkpoint.set_defaults(func=_command_checkpoint)

    merge = subparsers.add_parser("merge", help="Merge lane DuckDB artifacts.")
    merge.add_argument("--artifacts-dir", type=Path, required=True)
    merge.add_argument("--output-dir", type=Path, required=True)
    merge.add_argument("--manifest-path", type=Path, default=None)
    merge.add_argument("--checkpoint-dir", type=Path, default=None)
    merge.add_argument("--checkpoint-report-path", type=Path, default=None)
    merge.set_defaults(func=_command_merge)

    audit = subparsers.add_parser("audit", help="Summarize lane metadata for extraction audit.")
    audit.add_argument("--metadata-dir", type=Path, required=True)
    audit.add_argument("--output-path", type=Path, required=True)
    audit.set_defaults(func=_command_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
