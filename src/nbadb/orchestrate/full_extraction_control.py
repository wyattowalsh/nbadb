from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import duckdb

from nbadb.core.types import (
    PLAY_IN_FIRST_SEASON_START_YEAR,
    VIDEO_CONTEXT_MEASURES,
    SeasonType,
    classify_season_type_availability,
)
from nbadb.orchestrate.execution_policy import build_execution_policy
from nbadb.orchestrate.extraction_contract import (
    DISCOVERY_SEED_OWNED_ENDPOINTS,
    FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT,
    FinalLaneOutcome,
    contract_blocking_rules_for_lane,
)
from nbadb.orchestrate.planning import PATTERN_PRIORITY, executable_endpoint_routes
from nbadb.orchestrate.seasons import season_range
from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.orchestrate.workload_contract import (
    PlayerTeamSeasonWorkloadBaseUnit,
    PlayerTeamSeasonWorkloadStore,
    build_player_team_season_workload_scope,
    player_team_season_workload_base_unit,
    player_team_season_workload_scope_identity,
)
from nbadb.orchestrate.workload_profile import (
    WorkloadPlanningSnapshot,
    build_workload_planning_snapshot,
    endpoint_cost,
    preferred_max_span,
)

DEFAULT_HISTORICAL_START = 1946
MANIFEST_VERSION = 3
MAX_WORKFLOW_DISPATCH_JSON_CHARS = 60_000
MAX_GITHUB_MATRIX_LANES = 256
SCHEDULER_DIVERSITY_WINDOW = 6
MAX_CUMULATIVE_LANE_RETRIES = 12
SCHEDULER_QUEUE_SEQUENCE = (
    "fresh",
    "fresh",
    "fresh",
    "fresh",
    "fresh",
    "partial",
    "partial",
    "partial",
    "retry",
    "infrastructure",
)
FAILURE_RETRY_BUDGETS: dict[str, int] = {
    "transport_transient": 3,
    "response_contract": 2,
    "application": 1,
    "vpn_egress": 3,
    "runner_infrastructure": 3,
    "timeout_progress": 8,
    "timeout_stalled": 2,
}
CHUNK_PROFILES = frozenset({"standard", "balanced-small", "micro"})
DEFAULT_CHUNK_PROFILE = "standard"
SPLITTABLE_TIMEOUT_STATUSES = frozenset(
    {"needs_resume", "extract-timeout", "timeout_with_persisted_progress"}
)
RETRYABLE_PIPELINE_FAILURE_STATUSES = frozenset(
    {"cancelled", "vpn_auth_failure", "vpn_connect_timeout", "vpn_network_error"}
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
VIDEO_ENDPOINTS = frozenset({"video_details", "video_details_asset"})
VIDEO_CONTEXT_MEASURES_PER_LANE = 3
SEASON_TYPE_GROUPABLE_PATTERNS = SEASON_TYPE_PATTERNS | CROSS_PRODUCT_PATTERNS
DEFAULT_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)
HISTORICAL_MAX_SPAN_BY_PATTERN: dict[str, int] = {
    "game": 4,
    "date": 4,
    "season": 8,
    "player_season": 6,
    "team_season": 8,
}
HISTORICAL_ENDPOINT_ISOLATION_PATTERNS = frozenset(
    {"date", "game", "season", "player_season", "team_season"}
)
"""High-volume historical patterns that must be planned per endpoint.

The support matrix is endpoint/table-oriented, but high-volume historical
extraction can be much slower than broad season sweeps, and season-level
availability varies sharply by endpoint. Isolating these lanes keeps a slow,
rate-limited, or temporally unsupported endpoint from blocking unrelated
endpoint/time-period coverage.
"""
CROSS_PRODUCT_MAX_SPAN = 4
CROSS_PRODUCT_ENDPOINT_ISOLATION_PATTERNS = frozenset({"player_team_season"})
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
    context_measures: tuple[str, ...] = ()
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
    attempt_count: int = 0
    class_failure_streak: int = 0
    zero_progress_streak: int = 0
    last_failure_class: str = ""
    last_completed_calls: int = 0
    last_rows_persisted: int = 0
    next_eligible_iteration: int = 0
    state_artifact_run_id: str = ""
    state_artifact_name: str = ""
    state_artifact_digest: str = ""

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
            "context_measures": ",".join(self.context_measures),
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
            "attempt_count": self.attempt_count,
            "class_failure_streak": self.class_failure_streak,
            "zero_progress_streak": self.zero_progress_streak,
            "last_failure_class": self.last_failure_class,
            "last_completed_calls": self.last_completed_calls,
            "last_rows_persisted": self.last_rows_persisted,
            "next_eligible_iteration": self.next_eligible_iteration,
            "state_artifact_run_id": self.state_artifact_run_id,
            "state_artifact_name": self.state_artifact_name,
            "state_artifact_digest": self.state_artifact_digest,
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
    previous_checkpoint_run_id: str = ""
    previous_checkpoint_artifact_name: str = ""
    previous_checkpoint_generation: int = 0
    previous_checkpoint_coverage_hash: str = ""
    scheduler_rotation_cursor: int = 0
    iteration_budget: int = 0
    contract_blocked_evidence: tuple[dict[str, Any], ...] = ()
    contract_blocked_evidence_sha256: str = ""
    previous_contract_blocked_evidence: tuple[dict[str, Any], ...] = ()
    previous_contract_blocked_evidence_sha256: str = ""
    pending_contract_blocked_evidence: tuple[dict[str, Any], ...] = ()
    pending_contract_blocked_evidence_sha256: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "vpn_quarantined_servers": list(self.vpn_quarantined_servers),
            "artifact_run_ids": list(self.artifact_run_ids),
            "latest_checkpoint_run_id": self.latest_checkpoint_run_id,
            "latest_checkpoint_artifact_name": self.latest_checkpoint_artifact_name,
            "latest_checkpoint_generation": self.latest_checkpoint_generation,
            "latest_checkpoint_coverage_hash": self.latest_checkpoint_coverage_hash,
            "previous_checkpoint_run_id": self.previous_checkpoint_run_id,
            "previous_checkpoint_artifact_name": self.previous_checkpoint_artifact_name,
            "previous_checkpoint_generation": self.previous_checkpoint_generation,
            "previous_checkpoint_coverage_hash": self.previous_checkpoint_coverage_hash,
            "scheduler_rotation_cursor": self.scheduler_rotation_cursor,
            "iteration_budget": self.iteration_budget,
            "contract_blocked_evidence": [dict(row) for row in self.contract_blocked_evidence],
            "contract_blocked_evidence_sha256": self.contract_blocked_evidence_sha256,
            "previous_contract_blocked_evidence": [
                dict(row) for row in self.previous_contract_blocked_evidence
            ],
            "previous_contract_blocked_evidence_sha256": (
                self.previous_contract_blocked_evidence_sha256
            ),
        }
        if self.pending_contract_blocked_evidence or self.pending_contract_blocked_evidence_sha256:
            payload["pending_contract_blocked_evidence"] = [
                dict(row) for row in self.pending_contract_blocked_evidence
            ]
            payload["pending_contract_blocked_evidence_sha256"] = (
                self.pending_contract_blocked_evidence_sha256
            )
        return payload


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
    raw_blocked_evidence = raw_chain_state.get("contract_blocked_evidence", [])
    if not isinstance(raw_blocked_evidence, list) or any(
        not isinstance(row, dict) for row in raw_blocked_evidence
    ):
        raise ValueError("chain_state contract_blocked_evidence must be a list of objects")
    raw_previous_blocked_evidence = raw_chain_state.get("previous_contract_blocked_evidence", [])
    if not isinstance(raw_previous_blocked_evidence, list) or any(
        not isinstance(row, dict) for row in raw_previous_blocked_evidence
    ):
        raise ValueError("chain_state previous_contract_blocked_evidence must be a list of objects")
    raw_pending_blocked_evidence = raw_chain_state.get("pending_contract_blocked_evidence", [])
    if not isinstance(raw_pending_blocked_evidence, list) or any(
        not isinstance(row, dict) for row in raw_pending_blocked_evidence
    ):
        raise ValueError("chain_state pending_contract_blocked_evidence must be a list of objects")
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
        previous_checkpoint_run_id=_normalize_scalar_string(
            raw_chain_state.get("previous_checkpoint_run_id")
        ),
        previous_checkpoint_artifact_name=_normalize_scalar_string(
            raw_chain_state.get("previous_checkpoint_artifact_name")
        ),
        previous_checkpoint_generation=int(
            raw_chain_state.get("previous_checkpoint_generation") or 0
        ),
        previous_checkpoint_coverage_hash=_normalize_scalar_string(
            raw_chain_state.get("previous_checkpoint_coverage_hash")
        ),
        scheduler_rotation_cursor=(
            int(raw_chain_state.get("scheduler_rotation_cursor") or 0)
            % len(SCHEDULER_QUEUE_SEQUENCE)
        ),
        iteration_budget=int(raw_chain_state.get("iteration_budget") or 0),
        contract_blocked_evidence=tuple(dict(row) for row in raw_blocked_evidence),
        contract_blocked_evidence_sha256=_normalize_scalar_string(
            raw_chain_state.get("contract_blocked_evidence_sha256")
        ),
        previous_contract_blocked_evidence=tuple(
            dict(row) for row in raw_previous_blocked_evidence
        ),
        previous_contract_blocked_evidence_sha256=_normalize_scalar_string(
            raw_chain_state.get("previous_contract_blocked_evidence_sha256")
        ),
        pending_contract_blocked_evidence=tuple(dict(row) for row in raw_pending_blocked_evidence),
        pending_contract_blocked_evidence_sha256=_normalize_scalar_string(
            raw_chain_state.get("pending_contract_blocked_evidence_sha256")
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


def _runtime_support_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project canonical coverage rows onto concrete planner endpoint routes."""

    entries_by_staging_key = {entry.staging_key: entry for entry in STAGING_MAP}
    projected: list[dict[str, Any]] = []
    for row in rows:
        raw_windows = row.get("support_windows")
        if not isinstance(raw_windows, list) or not raw_windows:
            projected.append(row)
            continue

        grouped_windows: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for raw_window in raw_windows:
            if not isinstance(raw_window, dict):
                msg = "Support-matrix support_windows entries must be objects"
                raise ValueError(msg)
            window = dict(raw_window)
            staging_key = str(window.get("staging_key", "")).strip()
            entry = entries_by_staging_key.get(staging_key)
            if entry is None:
                msg = f"Support-matrix staging key has no runtime route: {staging_key or '<empty>'}"
                raise ValueError(msg)
            declared_pattern = str(window.get("param_pattern", "")).strip()
            if declared_pattern != entry.param_pattern:
                msg = (
                    f"Support-matrix route mismatch for {staging_key}: "
                    f"declared {declared_pattern or '<empty>'}, runtime {entry.param_pattern}"
                )
                raise ValueError(msg)
            grouped_windows.setdefault((entry.endpoint_name, entry.param_pattern), []).append(
                window
            )

        for (endpoint_name, pattern), windows in sorted(grouped_windows.items()):
            capabilities = {
                str(window.get("season_type_capability", "not_applicable")) for window in windows
            }
            supported_types = {
                tuple(str(value) for value in window.get("supported_season_types", []))
                for window in windows
            }
            min_seasons = {window.get("min_season") for window in windows}
            deprecated_after = {window.get("deprecated_after") for window in windows}
            if any(
                len(values) != 1
                for values in (capabilities, supported_types, min_seasons, deprecated_after)
            ):
                msg = (
                    f"Support-matrix windows disagree for concrete route {endpoint_name}/{pattern}"
                )
                raise ValueError(msg)

            runtime_row = dict(row)
            runtime_row.update(
                endpoint_name=endpoint_name,
                param_patterns=[pattern],
                staging_keys=sorted(str(window["staging_key"]) for window in windows),
                support_windows=windows,
                earliest_supported_season=next(iter(min_seasons)),
                season_type_contract_status=next(iter(capabilities)),
                declared_supported_season_types=list(next(iter(supported_types))),
            )
            projected.append(runtime_row)
    return projected


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
        and str(row.get("endpoint_name", "")) not in DISCOVERY_SEED_OWNED_ENDPOINTS
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
        else:
            try:
                thresholds.add(int(earliest))
            except (TypeError, ValueError):
                thresholds.add(DEFAULT_HISTORICAL_START)
        if SeasonType.PLAY_IN.value in _declared_supported_season_types(row):
            thresholds.add(PLAY_IN_FIRST_SEASON_START_YEAR)
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


def _context_measure_slug(context_measures: tuple[str, ...]) -> str:
    if not context_measures:
        return "all-contexts"
    return "-".join(value.lower().replace("_", "-") for value in context_measures)


def _available_season_types_for_band(
    season_types: tuple[str, ...],
    *,
    start: int,
    end: int,
) -> tuple[str, ...]:
    if SeasonType.PLAY_IN.value not in season_types:
        return season_types
    if start < PLAY_IN_FIRST_SEASON_START_YEAR <= end:
        msg = f"season band {start}-{end} crosses the PlayIn availability boundary"
        raise ValueError(msg)
    if end < PLAY_IN_FIRST_SEASON_START_YEAR:
        return tuple(
            season_type for season_type in season_types if season_type != SeasonType.PLAY_IN.value
        )
    return season_types


def _season_type_availability_bands(
    season_types: tuple[str, ...],
    *,
    start: int,
    end: int,
) -> list[tuple[int, int, tuple[str, ...]]]:
    boundaries = [(start, end)]
    if SeasonType.PLAY_IN.value in season_types and start < PLAY_IN_FIRST_SEASON_START_YEAR <= end:
        boundaries = [
            (start, PLAY_IN_FIRST_SEASON_START_YEAR - 1),
            (PLAY_IN_FIRST_SEASON_START_YEAR, end),
        ]
    return [
        (band_start, band_end, available_types)
        for band_start, band_end in boundaries
        if (
            available_types := _available_season_types_for_band(
                season_types,
                start=band_start,
                end=band_end,
            )
        )
        or not season_types
    ]


def _context_measure_groups(endpoints: tuple[str, ...]) -> list[tuple[str, ...]]:
    if not endpoints or not set(endpoints) <= VIDEO_ENDPOINTS:
        return [()]
    return [
        VIDEO_CONTEXT_MEASURES[index : index + VIDEO_CONTEXT_MEASURES_PER_LANE]
        for index in range(0, len(VIDEO_CONTEXT_MEASURES), VIDEO_CONTEXT_MEASURES_PER_LANE)
    ]


def _context_measures_for_endpoint(
    lane: FullExtractionLane,
    *,
    endpoint: str,
    pattern: str,
) -> tuple[str, ...]:
    if endpoint not in VIDEO_ENDPOINTS or pattern != "player_team_season":
        return ("",)
    return lane.context_measures or VIDEO_CONTEXT_MEASURES


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

    return _endpoint_row_groups(rows)


def _endpoint_row_groups(
    rows: list[dict[str, Any]],
) -> list[tuple[str | None, list[dict[str, Any]]]]:
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


def _cross_product_endpoint_row_groups(
    rows: list[dict[str, Any]],
    *,
    pattern: str,
) -> list[tuple[str | None, list[dict[str, Any]]]]:
    if pattern not in CROSS_PRODUCT_ENDPOINT_ISOLATION_PATTERNS:
        return [(None, rows)]
    return _endpoint_row_groups(rows)


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


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


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
    units: list[dict[str, Any]] = []
    for endpoint in endpoints:
        for pattern in patterns:
            for season_type in season_types:
                for season in seasons:
                    if (
                        season is not None
                        and season_type
                        and classify_season_type_availability(season, season_type)
                        == "upstream_unavailable"
                    ):
                        continue
                    for context_measure in _context_measures_for_endpoint(
                        lane,
                        endpoint=endpoint,
                        pattern=pattern,
                    ):
                        units.append(
                            {
                                "endpoint": endpoint,
                                "pattern": pattern,
                                "season_type": season_type,
                                "season": season,
                                "context_measure": context_measure,
                            }
                        )
    return units


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
    progress_bonus = 25_000.0 if lane.last_completed_calls or lane.last_rows_persisted else 0.0
    tier_bonus = THROUGHPUT_TIER_SEVERITY.get(lane.throughput_tier, 0) * 100_000.0
    family_bonus = FAMILY_PRIORITY.get(lane.endpoint_family, 0) * 1_000.0
    cost_bonus = lane.estimated_lane_cost * 100.0
    season_bonus = 0.0 if lane.season_start is None else max(0, 3_000 - lane.season_start)
    return progress_bonus + tier_bonus + family_bonus + cost_bonus + season_bonus


def _lane_scheduler_queue(lane: FullExtractionLane) -> str:
    if lane.attempt_count == 0 and not lane.last_failure_reason:
        return "fresh"
    if lane.last_failure_class in {"runner_infrastructure", "vpn_egress"}:
        return "infrastructure"
    if (
        lane.last_completed_calls > 0
        or lane.last_rows_persisted > 0
        or lane.last_failure_class == "timeout_progress"
    ):
        return "partial"
    return "retry"


def _lane_endpoint_identity(lane: FullExtractionLane) -> tuple[str, ...]:
    if lane.endpoints:
        return tuple(sorted(lane.endpoints))
    return (f"family:{lane.endpoint_family or 'default'}",)


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
    context_multiplier = max(
        (
            len(_context_measures_for_endpoint(lane, endpoint=endpoint, pattern=pattern or ""))
            for endpoint in lane.endpoints
        ),
        default=1,
    )
    estimated_lane_cost = endpoint_cost_value * span * context_multiplier
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
    rotation_cursor: int = 0,
) -> list[FullExtractionLane]:
    chunk_profile = _validate_chunk_profile(chunk_profile)
    annotated = [
        _annotate_lane(lane, chunk_profile=chunk_profile, planning_snapshot=planning_snapshot)
        for lane in lanes
    ]
    resume_only = [lane for lane in annotated if lane.resume_only]
    active = [lane for lane in annotated if not lane.resume_only]

    def sort_key(lane: FullExtractionLane) -> tuple[Any, ...]:
        return (
            -lane.schedule_priority,
            -lane.estimated_lane_cost,
            -THROUGHPUT_TIER_SEVERITY.get(lane.throughput_tier, 0),
            lane.endpoint_family,
            lane.season_start if lane.season_start is not None else 9999,
            lane.lane_id,
        )

    queues: dict[str, list[FullExtractionLane]] = {
        "fresh": [],
        "partial": [],
        "retry": [],
        "infrastructure": [],
    }
    for lane in active:
        queues[_lane_scheduler_queue(lane)].append(lane)
    for queue in queues.values():
        queue.sort(key=sort_key)

    scheduled: list[FullExtractionLane] = []
    sequence_index = rotation_cursor % len(SCHEDULER_QUEUE_SEQUENCE)
    while any(queues.values()):
        wave_size = min(max_matrix_lanes, sum(len(queue) for queue in queues.values()))
        family_cap = max(1, math.ceil(wave_size * 0.25))
        family_counts: dict[str, int] = {}
        wave: list[FullExtractionLane] = []
        while len(wave) < wave_size and any(queues.values()):
            preferred = SCHEDULER_QUEUE_SEQUENCE[sequence_index % len(SCHEDULER_QUEUE_SEQUENCE)]
            sequence_index += 1
            queue_order = [
                preferred,
                *(name for name in SCHEDULER_QUEUE_SEQUENCE if name != preferred),
            ]
            queue_order = list(dict.fromkeys(queue_order))
            uncapped_family_available = any(
                family_counts.get(candidate.endpoint_family or "default", 0) < family_cap
                for queue in queues.values()
                for candidate in queue
            )
            recent_lanes = [*scheduled, *wave][-(SCHEDULER_DIVERSITY_WINDOW - 1) :]
            homogeneous_endpoint = (
                _lane_endpoint_identity(recent_lanes[0])
                if len(recent_lanes) == SCHEDULER_DIVERSITY_WINDOW - 1
                and len({_lane_endpoint_identity(lane) for lane in recent_lanes}) == 1
                else None
            )
            diverse_candidate_available = homogeneous_endpoint is not None and any(
                (
                    family_counts.get(candidate.endpoint_family or "default", 0) < family_cap
                    or not uncapped_family_available
                )
                and _lane_endpoint_identity(candidate) != homogeneous_endpoint
                for queue in queues.values()
                for candidate in queue
            )
            selected_queue = ""
            selected_index = -1
            for queue_name in queue_order:
                queue = queues[queue_name]
                for candidate_index, candidate in enumerate(queue):
                    family = candidate.endpoint_family or "default"
                    if family_counts.get(family, 0) >= family_cap and uncapped_family_available:
                        continue
                    if (
                        diverse_candidate_available
                        and _lane_endpoint_identity(candidate) == homogeneous_endpoint
                    ):
                        continue
                    selected_queue = queue_name
                    selected_index = candidate_index
                    break
                if selected_queue:
                    break
            if not selected_queue:
                selected_queue = min(
                    (name for name, queue in queues.items() if queue),
                    key=lambda name: sort_key(queues[name][0]),
                )
                selected_index = 0
            lane = queues[selected_queue].pop(selected_index)
            family = lane.endpoint_family or "default"
            family_counts[family] = family_counts.get(family, 0) + 1
            wave.append(lane)
        scheduled.extend(wave)

    ordered = [*scheduled, *resume_only]
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


def _duplicate_lane_id_errors(lanes: list[FullExtractionLane]) -> list[str]:
    lane_id_counts: dict[str, int] = {}
    for lane in lanes:
        lane_id_counts[lane.lane_id] = lane_id_counts.get(lane.lane_id, 0) + 1
    duplicate_lane_ids = sorted(lane_id for lane_id, count in lane_id_counts.items() if count > 1)
    return (
        ["duplicate lane_id values: " + ", ".join(duplicate_lane_ids)] if duplicate_lane_ids else []
    )


def _lane_has_state_artifact_pointer(lane: FullExtractionLane) -> bool:
    # Restore revalidates the receipt and full provenance before the VPN step.
    run_id = lane.state_artifact_run_id
    artifact_name = lane.state_artifact_name
    if not _is_positive_run_id(run_id) or not _is_sha256(lane.state_artifact_digest):
        return False

    prefix = "extraction-lane-recovery-"
    recovery_marker = f"-{lane.lane_id}-run-{run_id}-attempt-"
    if not artifact_name.startswith(prefix):
        return False
    recovery_identity = artifact_name.removeprefix(prefix)
    marker_index = recovery_identity.rfind(recovery_marker)
    if marker_index <= 0:
        return False
    attempt = recovery_identity[marker_index + len(recovery_marker) :]
    return _is_positive_run_id(attempt)


def _raise_manifest_errors(errors: list[str]) -> None:
    if errors:
        msg = "Invalid full extraction manifest:\n- " + "\n- ".join(errors)
        raise ValueError(msg)


def _validate_unique_lane_ids(lanes: list[FullExtractionLane]) -> None:
    _raise_manifest_errors(_duplicate_lane_id_errors(lanes))


def validate_manifest(lanes: list[FullExtractionLane]) -> None:
    errors = _duplicate_lane_id_errors(lanes)
    executable_routes = executable_endpoint_routes()
    executable_patterns = frozenset(PATTERN_PRIORITY)
    for lane in lanes:
        unknown_context_measures = sorted(set(lane.context_measures) - set(VIDEO_CONTEXT_MEASURES))
        if unknown_context_measures:
            errors.append(
                f"{lane.lane_id}: unknown video context measures: "
                f"{', '.join(unknown_context_measures)}"
            )
        if lane.context_measures and not set(lane.endpoints) <= VIDEO_ENDPOINTS:
            errors.append(f"{lane.lane_id}: context measures require video-only endpoint lanes")
        unknown_patterns = sorted(set(lane.patterns) - executable_patterns)
        if unknown_patterns:
            errors.append(
                f"{lane.lane_id}: unknown extraction patterns: {', '.join(unknown_patterns)}"
            )
        excluded_endpoints = sorted(set(lane.endpoints) & FULL_EXTRACTION_EXCLUDED_ENDPOINTS.keys())
        if excluded_endpoints:
            errors.append(
                f"{lane.lane_id}: endpoints are excluded from full extraction: "
                f"{', '.join(excluded_endpoints)}"
            )
        discovery_owned_endpoints = sorted(set(lane.endpoints) & DISCOVERY_SEED_OWNED_ENDPOINTS)
        if discovery_owned_endpoints:
            errors.append(
                f"{lane.lane_id}: endpoints are owned by discovery_seed and must not "
                f"be scheduled as extraction lanes: {', '.join(discovery_owned_endpoints)}"
            )
        for endpoint_name in lane.endpoints:
            unsupported_patterns = sorted(
                pattern
                for pattern in lane.patterns
                if (endpoint_name, pattern) not in executable_routes
            )
            if unsupported_patterns:
                errors.append(
                    f"{lane.lane_id}: endpoint {endpoint_name} has no executable planner "
                    f"route for patterns {', '.join(unsupported_patterns)}"
                )
        if (lane.season_start is None) != (lane.season_end is None):
            errors.append(f"{lane.lane_id}: season_start/season_end must both be set or both empty")
        if lane.timeout_seconds <= 0:
            errors.append(f"{lane.lane_id}: timeout_seconds must be > 0")
        if lane.failure_streak < 0:
            errors.append(f"{lane.lane_id}: failure_streak must be >= 0")
        if lane.split_generation < 0:
            errors.append(f"{lane.lane_id}: split_generation must be >= 0")
        if lane.attempt_count < 0:
            errors.append(f"{lane.lane_id}: attempt_count must be >= 0")
        if lane.class_failure_streak < 0:
            errors.append(f"{lane.lane_id}: class_failure_streak must be >= 0")
        if lane.zero_progress_streak < 0:
            errors.append(f"{lane.lane_id}: zero_progress_streak must be >= 0")
        if lane.last_completed_calls < 0 or lane.last_rows_persisted < 0:
            errors.append(f"{lane.lane_id}: persisted progress counters must be >= 0")
        state_pointer_present = any(
            (
                lane.state_artifact_run_id,
                lane.state_artifact_name,
                lane.state_artifact_digest,
            )
        )
        if state_pointer_present and not _lane_has_state_artifact_pointer(lane):
            errors.append(
                f"{lane.lane_id}: state artifact pointer must identify a canonical "
                "uploaded recovery artifact"
            )
        progress_baseline_present = bool(lane.last_completed_calls or lane.last_rows_persisted)
        if progress_baseline_present and not _lane_has_state_artifact_pointer(lane):
            errors.append(
                f"{lane.lane_id}: persisted progress counters require a canonical "
                "recovery artifact pointer"
            )
        max_span = _max_span_for_lane(lane)
        span = _season_span(lane.season_start, lane.season_end)
        if (
            not lane.resume_only
            and max_span is not None
            and span > max_span
            and not _lane_has_state_artifact_pointer(lane)
        ):
            errors.append(f"{lane.lane_id}: span {span} exceeds lane policy max {max_span}")
    _raise_manifest_errors(errors)


def _legacy_failure_class(reason: str) -> str:
    normalized = reason.strip().lower().replace("_", "-")
    if not normalized:
        return ""
    if "missing-metadata" in normalized or normalized in {"cancelled", "cancellation-no-metadata"}:
        return "runner_infrastructure"
    if normalized in {"vpn-auth-failure", "vpn-connect-timeout"}:
        return "vpn_egress"
    if "timeout" in normalized:
        return "timeout_stalled"
    # Legacy v2 metadata flattened provider and parser errors into pipeline_failure.
    # Keep those lanes retryable once so v3 metadata can capture the real cause.
    if normalized == "pipeline-failure":
        return "transport_transient"
    return "application"


def _normalize_lane(raw: dict[str, Any], lane_index: int) -> FullExtractionLane:
    patterns = tuple(str(pattern) for pattern in raw.get("patterns", []) if str(pattern))
    season_types = tuple(str(value) for value in raw.get("season_types", []) if str(value))
    context_measures = tuple(str(value) for value in raw.get("context_measures", []) if str(value))
    endpoints = tuple(str(value) for value in raw.get("endpoints", []) if str(value))
    season_start = raw.get("season_start")
    season_end = raw.get("season_end")

    last_failure_reason = str(raw.get("last_failure_reason") or "")
    inferred_attempt_count = 1 if last_failure_reason else 0
    lane = FullExtractionLane(
        lane_id=str(raw["lane_id"]),
        lane_index=lane_index,
        lane_name=str(raw.get("lane_name") or raw["lane_id"]),
        lane_kind=str(raw.get("lane_kind") or "custom"),
        season_start=_optional_int(season_start),
        season_end=_optional_int(season_end),
        patterns=patterns,
        season_types=season_types,
        context_measures=context_measures,
        endpoints=endpoints,
        use_vpn=bool(raw.get("use_vpn", True)),
        resume_only=bool(raw.get("resume_only", False)),
        timeout_seconds=int(raw.get("timeout_seconds") or 7_200),
        failure_streak=int(raw.get("failure_streak") or 0),
        last_failure_reason=last_failure_reason,
        parent_lane_id=str(raw.get("parent_lane_id") or ""),
        split_generation=int(raw.get("split_generation") or 0),
        chunk_profile=str(raw.get("chunk_profile") or "standard"),
        endpoint_family=str(raw.get("endpoint_family") or ""),
        throughput_tier=str(raw.get("throughput_tier") or ""),
        estimated_lane_cost=float(raw.get("estimated_lane_cost") or 0.0),
        coverage_units_hash=str(raw.get("coverage_units_hash") or ""),
        schedule_priority=float(raw.get("schedule_priority") or 0.0),
        planned_wave=int(raw.get("planned_wave") or 0),
        attempt_count=int(raw.get("attempt_count") or inferred_attempt_count),
        class_failure_streak=int(raw.get("class_failure_streak") or raw.get("failure_streak") or 0),
        zero_progress_streak=int(raw.get("zero_progress_streak") or 0),
        last_failure_class=str(
            raw.get("last_failure_class") or _legacy_failure_class(last_failure_reason)
        ),
        last_completed_calls=int(raw.get("last_completed_calls") or 0),
        last_rows_persisted=int(raw.get("last_rows_persisted") or 0),
        next_eligible_iteration=int(raw.get("next_eligible_iteration") or 0),
        state_artifact_run_id=str(raw.get("state_artifact_run_id") or ""),
        state_artifact_name=str(raw.get("state_artifact_name") or ""),
        state_artifact_digest=str(raw.get("state_artifact_digest") or ""),
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
    max_matrix_lanes: int = MAX_GITHUB_MATRIX_LANES,
) -> list[FullExtractionLane]:
    chunk_profile = _validate_chunk_profile(chunk_profile)
    runtime_support_rows = _runtime_support_rows(support_matrix_rows)
    selected_discovery_endpoints = sorted(
        set(selected_endpoints or ()) & DISCOVERY_SEED_OWNED_ENDPOINTS
    )
    if selected_discovery_endpoints:
        msg = (
            "Selected full-extraction endpoints are discovery-seed-owned and cannot be "
            "scheduled as matrix lanes: " + ", ".join(selected_discovery_endpoints)
        )
        raise ValueError(msg)

    endpoint_patterns = _patterns_for_endpoints(runtime_support_rows, selected_endpoints)
    if selected_patterns is not None:
        requested_patterns = set(selected_patterns)
    elif endpoint_patterns is not None:
        requested_patterns = endpoint_patterns
    else:
        requested_patterns = {
            str(pattern)
            for row in runtime_support_rows
            for pattern in row.get("param_patterns", [])
        }

    filtered_rows = _selected_rows(
        runtime_support_rows,
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
                                lane_season_types = _available_season_types_for_band(
                                    season_types,
                                    start=band_start,
                                    end=band_end,
                                )
                                if season_types and not lane_season_types:
                                    continue
                                endpoint_component = f"-{endpoint_slug}" if endpoint_slug else ""
                                lane_id = (
                                    f"historical-{pattern}{endpoint_component}-"
                                    f"{_season_type_slug(lane_season_types)}-"
                                    f"{band_start}-{band_end}"
                                )
                                lane_name = f"Historical {pattern} {band_start}-{band_end}"
                                if endpoints and endpoint_slug:
                                    lane_name = f"{lane_name} ({', '.join(endpoints)})"
                                if lane_season_types:
                                    lane_name = f"{lane_name} ({', '.join(lane_season_types)})"
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
                                        season_types=lane_season_types,
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
            for endpoint_slug, endpoint_rows in _cross_product_endpoint_row_groups(
                grouped_rows,
                pattern="player_team_season",
            ):
                patterns = tuple(
                    sorted(
                        {
                            str(pattern)
                            for row in endpoint_rows
                            for pattern in row.get("param_patterns", [])
                            if str(pattern) in CROSS_PRODUCT_PATTERNS
                        }
                    )
                )
                endpoints = _endpoint_names(endpoint_rows)
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
                availability_bands = [
                    availability_band
                    for supported_start, supported_end in supported_bands
                    for availability_band in _season_type_availability_bands(
                        season_types,
                        start=supported_start,
                        end=supported_end,
                    )
                ]
                context_measure_groups = _context_measure_groups(endpoints)
                for supported_start, supported_end, lane_season_types in availability_bands:
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
                        for context_index, context_measures in enumerate(
                            context_measure_groups,
                            start=1,
                        ):
                            endpoint_component = f"-{endpoint_slug}" if endpoint_slug else ""
                            context_component = (
                                f"-ctx-{context_index:02d}" if context_measures else ""
                            )
                            lane_name = f"Cross Product Historical {band_start}-{band_end}"
                            if endpoints and endpoint_slug:
                                lane_name = f"{lane_name} ({', '.join(endpoints)})"
                            if context_measures:
                                lane_name = (
                                    f"{lane_name} (contexts "
                                    f"{context_index}/{len(context_measure_groups)}: "
                                    f"{', '.join(context_measures)})"
                                )
                            appended = _append_lane_if_supported(
                                lanes,
                                FullExtractionLane(
                                    lane_id=(
                                        f"cross-product{endpoint_component}{context_component}-"
                                        f"{_season_type_slug(lane_season_types)}-"
                                        f"{band_start}-{band_end}"
                                    ),
                                    lane_index=lane_index,
                                    lane_name=lane_name,
                                    lane_kind="cross_product",
                                    season_start=band_start,
                                    season_end=band_end,
                                    patterns=patterns,
                                    season_types=lane_season_types,
                                    context_measures=context_measures,
                                    endpoints=endpoints,
                                    use_vpn=True,
                                    resume_only=False,
                                    timeout_seconds=(
                                        19_800
                                        if context_measures
                                        else _cross_product_timeout_seconds(
                                            band_start,
                                            band_end,
                                        )
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
        max_matrix_lanes=max_matrix_lanes,
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


def _lane_summary_key(lane: FullExtractionLane, *, dimension: str) -> str:
    if dimension == "wave":
        return str(lane.planned_wave)
    if dimension == "pattern":
        return ",".join(lane.patterns) or "none"
    if dimension == "family":
        return lane.endpoint_family or "default"
    if dimension == "tier":
        return lane.throughput_tier or "unknown"
    msg = f"Unsupported lane summary dimension: {dimension}"
    raise ValueError(msg)


def _lane_cost_summary(
    lanes: list[FullExtractionLane],
    *,
    dimension: str,
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for lane in lanes:
        key = _lane_summary_key(lane, dimension=dimension)
        bucket = buckets.setdefault(
            key,
            {
                dimension: int(key) if dimension == "wave" else key,
                "lane_count": 0,
                "coverage_unit_count": 0,
                "estimated_lane_cost": 0.0,
                "schedule_priority": 0.0,
                "max_timeout_seconds": 0,
            },
        )
        bucket["lane_count"] += 1
        bucket["coverage_unit_count"] += len(_coverage_units_for_lane(lane))
        bucket["estimated_lane_cost"] += lane.estimated_lane_cost
        bucket["schedule_priority"] += lane.schedule_priority
        bucket["max_timeout_seconds"] = max(bucket["max_timeout_seconds"], lane.timeout_seconds)

    summary = [
        {
            **bucket,
            "estimated_lane_cost": round(float(bucket["estimated_lane_cost"]), 3),
            "schedule_priority": round(float(bucket["schedule_priority"]), 3),
        }
        for bucket in buckets.values()
    ]
    return sorted(
        summary,
        key=lambda row: (
            row[dimension] if dimension == "wave" else -float(row["estimated_lane_cost"]),
            str(row[dimension]),
        ),
    )


def _maximum_retry_leaf_count(lane: FullExtractionLane) -> int:
    """Return a conservative upper bound for descendants created by timeout splitting."""
    if not (_timeout_lane_can_split(lane) or _lane_exceeds_policy(lane)):
        return 1
    season_leaves = _season_span(lane.season_start, lane.season_end)
    season_type_leaves = max(1, len(lane.season_types))
    context_leaves = max(1, len(lane.context_measures))
    return season_leaves * season_type_leaves * context_leaves


def _remaining_dispatch_credits(lane: FullExtractionLane) -> int:
    """Bound remaining attempts without assuming which failure class a fresh lane will hit."""
    if lane.last_failure_class:
        budget = FAILURE_RETRY_BUDGETS.get(lane.last_failure_class, 1)
        return max(1, budget - lane.class_failure_streak)
    return max(1, max(FAILURE_RETRY_BUDGETS.values(), default=1))


def manifest_payload(
    lanes: list[FullExtractionLane],
    *,
    chain_state: FullExtractionChainState | None = None,
    max_matrix_lanes: int = MAX_GITHUB_MATRIX_LANES,
    current_iteration: int = 1,
) -> dict[str, Any]:
    if max_matrix_lanes < 1 or max_matrix_lanes > MAX_GITHUB_MATRIX_LANES:
        msg = (
            f"max_matrix_lanes must be between 1 and {MAX_GITHUB_MATRIX_LANES}, "
            f"got {max_matrix_lanes}"
        )
        raise ValueError(msg)
    lane_dicts = [_lane_payload(lane) for lane in lanes]
    active_lanes = [lane for lane in lanes if not lane.resume_only]
    matrix_lanes = active_lanes[:max_matrix_lanes]
    deferred_lane_count = max(0, len(active_lanes) - len(matrix_lanes))
    minimum_remaining_waves = math.ceil(len(active_lanes) / max_matrix_lanes)
    remaining_dispatch_credits = sum(
        _remaining_dispatch_credits(lane) * _maximum_retry_leaf_count(lane) for lane in active_lanes
    )
    maximum_retry_depth = max(
        (_remaining_dispatch_credits(lane) for lane in active_lanes),
        default=0,
    )
    suggested_remaining_waves = max(
        maximum_retry_depth,
        math.ceil(remaining_dispatch_credits / max_matrix_lanes),
    )
    resolved_chain_state = chain_state or FullExtractionChainState()
    if resolved_chain_state.iteration_budget < 1 and active_lanes:
        resolved_chain_state = replace(
            resolved_chain_state,
            iteration_budget=current_iteration - 1 + max(1, suggested_remaining_waves),
        )
    chunk_profiles = sorted({lane.chunk_profile for lane in lanes if lane.chunk_profile})
    coverage_fingerprint = _coverage_fingerprint(lanes)
    wave_summary = _lane_cost_summary(active_lanes, dimension="wave")
    pattern_summary = _lane_cost_summary(active_lanes, dimension="pattern")
    family_summary = _lane_cost_summary(active_lanes, dimension="family")
    tier_summary = _lane_cost_summary(active_lanes, dimension="tier")
    return {
        "manifest_version": MANIFEST_VERSION,
        "chunk_profile": chunk_profiles[0] if len(chunk_profiles) == 1 else "mixed",
        "coverage_fingerprint": coverage_fingerprint,
        "lane_count": len(lanes),
        "active_lane_count": len(active_lanes),
        "resume_only_lane_count": len(lanes) - len(active_lanes),
        "matrix_lane_count": len(matrix_lanes),
        "deferred_lane_count": deferred_lane_count,
        "planned_wave_count": max((lane.planned_wave for lane in lanes), default=0) + 1,
        "minimum_remaining_wave_count": minimum_remaining_waves,
        "suggested_remaining_wave_count": suggested_remaining_waves,
        "iteration_budget": resolved_chain_state.iteration_budget,
        "scheduler_diagnostics": {
            "max_matrix_lanes": max_matrix_lanes,
            "maximum_retry_depth": maximum_retry_depth,
            "remaining_dispatch_credits": remaining_dispatch_credits,
            "rotation_cursor": resolved_chain_state.scheduler_rotation_cursor,
            "queue_counts": {
                name: sum(1 for lane in active_lanes if _lane_scheduler_queue(lane) == name)
                for name in ("fresh", "partial", "retry", "infrastructure")
            },
            "active_wave_count": len(wave_summary),
            "wave_cost_summary": wave_summary,
            "pattern_cost_summary": pattern_summary,
            "family_cost_summary": family_summary,
            "throughput_tier_summary": tier_summary,
        },
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
        "chain_state": resolved_chain_state.to_payload(),
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
        if not lane.context_measures:
            payload.pop("context_measures", None)
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
        if not lane.attempt_count:
            payload.pop("attempt_count", None)
        if not lane.class_failure_streak:
            payload.pop("class_failure_streak", None)
        if not lane.zero_progress_streak:
            payload.pop("zero_progress_streak", None)
        if not lane.last_failure_class:
            payload.pop("last_failure_class", None)
        if not lane.last_completed_calls:
            payload.pop("last_completed_calls", None)
        if not lane.last_rows_persisted:
            payload.pop("last_rows_persisted", None)
        if not lane.next_eligible_iteration:
            payload.pop("next_eligible_iteration", None)
        if not lane.state_artifact_run_id:
            payload.pop("state_artifact_run_id", None)
        if not lane.state_artifact_name:
            payload.pop("state_artifact_name", None)
        if not lane.state_artifact_digest:
            payload.pop("state_artifact_digest", None)
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


def _metadata_records_by_lane(
    metadata_dir: Path,
) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    records: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    canonical_candidates = sorted(metadata_dir.rglob("lane-metadata.json"))
    candidates = canonical_candidates or sorted(metadata_dir.rglob("*.json"))
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Checkout/setup failures can leave zero-byte metadata artifacts; treat
            # those as missing metadata so resume policy can decide whether to retry.
            continue
        if not isinstance(payload, dict):
            continue
        lane_id = str(payload.get("lane_id", "")).strip()
        if lane_id:
            records.setdefault(lane_id, []).append((candidate, payload))
    return records


def _metadata_by_lane(metadata_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        lane_id: lane_records[-1][1]
        for lane_id, lane_records in _metadata_records_by_lane(metadata_dir).items()
    }


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
    if not lane.patterns:
        return False
    if not (set(lane.patterns) & TIMEOUT_SPLIT_PATTERNS):
        return False
    if _season_span(lane.season_start, lane.season_end) > 1:
        return True
    return len(lane.season_types) > 1 or len(lane.context_measures) > 1


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
    return _split_lane_by_segments(
        lane,
        bands=bands,
        season_type_groups=[lane.season_types],
        reason=reason,
    )


def _split_lane_by_segments(
    lane: FullExtractionLane,
    *,
    bands: list[tuple[int, int]],
    season_type_groups: list[tuple[str, ...]],
    reason: str,
) -> list[FullExtractionLane]:
    parent_lane_id = lane.parent_lane_id or lane.lane_id
    children: list[FullExtractionLane] = []
    for start, end in bands:
        for season_types in season_type_groups:
            season_type_suffix = (
                f"-{_season_type_slug(season_types)}"
                if season_types and season_types != lane.season_types
                else ""
            )
            child_lane_id = f"{_lane_slug(parent_lane_id)}-split-{start}-{end}{season_type_suffix}"
            lane_name = f"{lane.lane_name} {start}-{end}"
            if season_type_suffix:
                lane_name = f"{lane_name} ({', '.join(season_types)})"
            children.append(
                replace(
                    lane,
                    lane_id=child_lane_id,
                    lane_name=lane_name,
                    season_start=start,
                    season_end=end,
                    season_types=season_types,
                    resume_only=False,
                    last_failure_reason=f"split-from-{reason}",
                    parent_lane_id=parent_lane_id,
                    split_generation=lane.split_generation + 1,
                    state_artifact_run_id="",
                    state_artifact_name="",
                    state_artifact_digest="",
                    last_completed_calls=0,
                    last_rows_persisted=0,
                )
            )
    return children


def _split_timeout_lane(lane: FullExtractionLane, *, reason: str) -> list[FullExtractionLane]:
    if (
        lane.season_start is not None
        and lane.season_end is not None
        and _season_span(lane.season_start, lane.season_end) == 1
        and len(lane.season_types) > 1
    ):
        return _split_lane_by_segments(
            lane,
            bands=[(lane.season_start, lane.season_end)],
            season_type_groups=[(season_type,) for season_type in lane.season_types],
            reason=reason,
        )
    if (
        lane.season_start is not None
        and lane.season_end is not None
        and _season_span(lane.season_start, lane.season_end) == 1
        and len(lane.context_measures) > 1
    ):
        parent_lane_id = lane.parent_lane_id or lane.lane_id
        season_type_component = (
            f"-{_season_type_slug(lane.season_types)}" if lane.season_types else ""
        )
        return [
            replace(
                lane,
                lane_id=(
                    f"{_lane_slug(parent_lane_id)}-split-"
                    f"{lane.season_start}-{lane.season_end}{season_type_component}-"
                    f"{_context_measure_slug((context_measure,))}"
                ),
                lane_name=f"{lane.lane_name} ({context_measure})",
                context_measures=(context_measure,),
                resume_only=False,
                last_failure_reason=f"split-from-{reason}",
                parent_lane_id=parent_lane_id,
                split_generation=lane.split_generation + 1,
                state_artifact_run_id="",
                state_artifact_name="",
                state_artifact_digest="",
                last_completed_calls=0,
                last_rows_persisted=0,
            )
            for context_measure in lane.context_measures
        ]
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
    if not isinstance(vpn_payload, dict):
        return False

    completed_calls, rows_persisted = _metadata_progress(payload)
    if completed_calls < 1 and rows_persisted < 1:
        return True

    run_id, name, digest = _metadata_state_artifact(payload)
    artifact = payload.get("state_artifact")
    return (
        isinstance(artifact, dict)
        and artifact.get("required") is not False
        and bool(run_id)
        and bool(name)
        and _is_sha256(digest)
    )


def _metadata_progress(payload: dict[str, Any]) -> tuple[int, int]:
    progress = payload.get("progress")
    telemetry = payload.get("telemetry")
    progress_payload = progress if isinstance(progress, dict) else {}
    telemetry_payload = telemetry if isinstance(telemetry, dict) else {}
    db_telemetry = telemetry_payload.get("db_telemetry")
    db_payload = db_telemetry if isinstance(db_telemetry, dict) else {}
    completed_calls = _int_metadata_value(
        progress_payload.get("completed_calls")
        or telemetry_payload.get("completed_calls")
        or db_payload.get("completed_calls")
        or telemetry_payload.get("journal_skips")
    )
    rows_persisted = _int_metadata_value(
        progress_payload.get("rows_persisted") or telemetry_payload.get("rows_persisted")
    )
    return completed_calls, rows_persisted


def _metadata_progress_increased(
    lane: FullExtractionLane,
    payload: dict[str, Any],
) -> bool:
    completed_calls, rows_persisted = _metadata_progress(payload)
    return (
        completed_calls >= lane.last_completed_calls
        and rows_persisted >= lane.last_rows_persisted
        and (
            completed_calls > lane.last_completed_calls or rows_persisted > lane.last_rows_persisted
        )
    )


def _metadata_progress_regressed(
    lane: FullExtractionLane,
    payload: dict[str, Any],
) -> bool:
    completed_calls, rows_persisted = _metadata_progress(payload)
    return completed_calls < lane.last_completed_calls or rows_persisted < lane.last_rows_persisted


def _metadata_added_durable_progress(
    lane: FullExtractionLane,
    payload: dict[str, Any],
) -> bool:
    return _metadata_progress_increased(
        lane,
        payload,
    ) and _metadata_state_artifact_is_durable_for_lane(lane, payload)


def _support_rule_fingerprints(raw_rules: Any) -> tuple[str, ...] | None:
    if not isinstance(raw_rules, list):
        return None

    fingerprints: list[str] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            return None
        fingerprints.append(json.dumps(raw_rule, sort_keys=True, separators=(",", ":")))
    return tuple(sorted(fingerprints))


def _metadata_support_rules_match(
    payload: dict[str, Any],
    expected_rules: tuple[dict[str, Any], ...],
) -> bool:
    if not expected_rules:
        return False
    reported = _support_rule_fingerprints(payload.get("support_rules"))
    expected = _support_rule_fingerprints(list(expected_rules))
    return reported is not None and reported == expected


def _metadata_failure_class(payload: dict[str, Any], *, raw_status: str) -> str:
    if raw_status == "state-artifact-upload-failed" or (
        str(payload.get("status") or "").strip() == "complete"
        and not _metadata_state_artifact_is_durable(payload)
    ):
        return "runner_infrastructure"
    failure_class = str(payload.get("failure_class") or "").strip()
    if failure_class:
        return failure_class
    vpn_payload = payload.get("vpn")
    vpn_status = (
        str(vpn_payload.get("status") or "").strip() if isinstance(vpn_payload, dict) else ""
    )
    if raw_status in {"cancelled", "cancellation_no_metadata", "missing-metadata"}:
        return "runner_infrastructure"
    if raw_status in {
        "vpn_auth_failure",
        "vpn_connect_timeout",
        "vpn_network_error",
    } or vpn_status in {
        "vpn_auth_failure",
        "vpn_connect_timeout",
        "vpn_network_error",
    }:
        return "vpn_egress"
    if raw_status in SPLITTABLE_TIMEOUT_STATUSES:
        completed_calls, rows_persisted = _metadata_progress(payload)
        return "timeout_progress" if completed_calls or rows_persisted else "timeout_stalled"
    if raw_status == "extract-error":
        # Metadata v1 flattened root causes. Preserve one bounded retry so the
        # v2 producer can emit a diagnostic class on the next attempt.
        return "transport_transient"
    return "application"


def _metadata_state_artifact(payload: dict[str, Any]) -> tuple[str, str, str]:
    artifact = payload.get("state_artifact")
    artifact_payload = artifact if isinstance(artifact, dict) else {}
    return (
        _normalize_scalar_string(artifact_payload.get("run_id")),
        _normalize_scalar_string(artifact_payload.get("name")),
        _normalize_scalar_string(artifact_payload.get("sha256")),
    )


def _metadata_state_artifact_is_durable(payload: dict[str, Any]) -> bool:
    artifact = payload.get("state_artifact")
    if not isinstance(artifact, dict) or artifact.get("attested") is not True:
        return False
    run_id, name, digest = _metadata_state_artifact(payload)
    artifact_id = _normalize_scalar_string(artifact.get("artifact_id"))
    artifact_digest = _normalize_scalar_string(artifact.get("artifact_digest")).lower()
    return (
        bool(run_id)
        and bool(name)
        and _is_sha256(digest)
        and artifact.get("uploaded") is True
        and _is_positive_run_id(artifact_id)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest) is not None
    )


def _metadata_state_artifact_is_durable_for_lane(
    lane: FullExtractionLane,
    payload: dict[str, Any],
) -> bool:
    if not _metadata_state_artifact_is_durable(payload):
        return False
    run_id, name, digest = _metadata_state_artifact(payload)
    return _lane_has_state_artifact_pointer(
        replace(
            lane,
            state_artifact_run_id=run_id,
            state_artifact_name=name,
            state_artifact_digest=digest,
        )
    )


def _retry_budget_exhausted(failure_class: str, streak: int) -> bool:
    budget = FAILURE_RETRY_BUDGETS.get(failure_class, 1)
    return budget > 0 and streak >= budget


def _lane_retry_budget_exhausted(lane: FullExtractionLane) -> bool:
    return (
        _retry_budget_exhausted(
            lane.last_failure_class,
            lane.class_failure_streak,
        )
        or max(lane.attempt_count, lane.zero_progress_streak) >= MAX_CUMULATIVE_LANE_RETRIES
    )


def _retry_lane_from_metadata(
    lane: FullExtractionLane,
    payload: dict[str, Any],
    *,
    outcome: str,
    current_iteration: int,
) -> FullExtractionLane:
    completed_calls, rows_persisted = _metadata_progress(payload)
    state_artifact_durable = _metadata_state_artifact_is_durable_for_lane(lane, payload)
    if state_artifact_durable and _metadata_progress_regressed(lane, payload):
        raise ValueError(
            f"Durable lane state progress regressed for {lane.lane_id}: "
            f"calls {lane.last_completed_calls}->{completed_calls}, "
            f"rows {lane.last_rows_persisted}->{rows_persisted}"
        )
    durable_progress_increased = _metadata_added_durable_progress(lane, payload)
    raw_status = str(payload.get("raw_status") or payload.get("status") or outcome).strip()
    failure_class = _metadata_failure_class(payload, raw_status=raw_status)
    previous_failure_class = lane.last_failure_class or _legacy_failure_class(
        lane.last_failure_reason
    )
    previous_class_streak = lane.class_failure_streak or lane.failure_streak
    class_streak = previous_class_streak + 1 if previous_failure_class == failure_class else 1
    zero_progress_streak = 0 if durable_progress_increased else lane.zero_progress_streak + 1
    state_run_id, state_name, state_digest = _metadata_state_artifact(payload)
    if state_artifact_durable:
        next_completed_calls = max(lane.last_completed_calls, completed_calls)
        next_rows_persisted = max(lane.last_rows_persisted, rows_persisted)
    elif _lane_has_state_artifact_pointer(lane):
        state_run_id = lane.state_artifact_run_id
        state_name = lane.state_artifact_name
        state_digest = lane.state_artifact_digest
        next_completed_calls = lane.last_completed_calls
        next_rows_persisted = lane.last_rows_persisted
    else:
        state_run_id = state_name = state_digest = ""
        next_completed_calls = 0
        next_rows_persisted = 0
    cooldown = 1 if failure_class in {"transport_transient", "response_contract"} else 0
    return replace(
        lane,
        resume_only=False,
        attempt_count=lane.attempt_count + 1,
        class_failure_streak=class_streak,
        zero_progress_streak=zero_progress_streak,
        last_failure_class=failure_class,
        last_completed_calls=next_completed_calls,
        last_rows_persisted=next_rows_persisted,
        next_eligible_iteration=current_iteration + cooldown,
        state_artifact_run_id=state_run_id,
        state_artifact_name=state_name,
        state_artifact_digest=state_digest,
    )


def _timeout_retry_should_split(
    lane: FullExtractionLane,
    payload: dict[str, Any],
    *,
    outcome: str,
) -> bool:
    if outcome not in SPLITTABLE_TIMEOUT_STATUSES or not _timeout_lane_can_split(lane):
        return False

    raw_status = str(payload.get("raw_status") or payload.get("status") or outcome).strip()
    failure_class = _metadata_failure_class(payload, raw_status=raw_status)
    if failure_class not in {"timeout_progress", "timeout_stalled"}:
        return False

    return not _metadata_added_durable_progress(lane, payload)


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
        return "complete" if _metadata_state_artifact_is_durable(payload) else "pipeline_failure"
    if not _metadata_has_required_noncomplete_artifacts(payload):
        return "pipeline_failure"

    telemetry = payload.get("telemetry", {})
    if not isinstance(telemetry, dict):
        telemetry = {}
    rows_persisted = _int_metadata_value(telemetry.get("rows_persisted"))
    journal_skips = _int_metadata_value(telemetry.get("journal_skips"))
    completed_calls, _ = _metadata_progress(payload)
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
                season_start=_optional_int(season_start),
                season_end=_optional_int(season_end),
            )
        )
    )
    support_rules_attested = _metadata_support_rules_match(payload, lane_contract_rules)

    if metadata_status == "contract_blocked":
        return "contract_blocked" if support_rules_attested else "pipeline_failure"
    if (
        rows_persisted == 0
        and lane_contract_rules
        and (
            failed_calls > 0
            or running_calls > 0
            or raw_status in SPLITTABLE_TIMEOUT_STATUSES
            or metadata_status == "pipeline_failure"
        )
    ):
        if _int_metadata_value(payload.get("metadata_schema_version")) >= 3:
            return "contract_blocked" if support_rules_attested else "pipeline_failure"
        return "contract_blocked"
    if metadata_status == "needs_resume":
        return "needs_resume"

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

    if raw_status == "extract-error" and (
        completed_calls > 0 or rows_persisted > 0 or journal_skips > 0
    ):
        return "needs_resume"
    if raw_status in SPLITTABLE_TIMEOUT_STATUSES:
        return "needs_resume"
    if raw_status == "cancelled" and (rows_persisted > 0 or journal_skips > 0):
        return "needs_resume"
    return "pipeline_failure"


def _canonical_contract_blocked_row_for_lane(
    lane: FullExtractionLane,
) -> dict[str, Any]:
    return _canonical_contract_blocked_audit_row(
        lane.lane_id,
        {
            "lane_kind": lane.lane_kind,
            "endpoints": list(lane.endpoints),
            "patterns": list(lane.patterns),
            "season_start": lane.season_start,
            "season_end": lane.season_end,
            "season_types": list(lane.season_types),
            "context_measures": list(lane.context_measures),
            "coverage_units_hash": _coverage_hash_for_lane(lane),
            "support_rules": list(_lane_contract_blocking_rules(lane)),
        },
    )


def _validated_pending_contract_blocked_evidence(
    chain_state: FullExtractionChainState,
) -> list[dict[str, Any]]:
    raw_rows = list(chain_state.pending_contract_blocked_evidence)
    raw_digest = chain_state.pending_contract_blocked_evidence_sha256.strip().lower()
    if not raw_rows:
        if raw_digest:
            raise ValueError(
                "Pending contract-blocked evidence digest exists without evidence rows"
            )
        return []

    rows: list[dict[str, Any]] = []
    seen_lane_ids: set[str] = set()
    for raw_row in raw_rows:
        lane_id = str(raw_row.get("lane_id") or "").strip()
        if not lane_id or lane_id in seen_lane_ids:
            raise ValueError("Pending contract-blocked lane IDs must be non-empty and unique")
        canonical_input = dict(raw_row)
        canonical_input["lane_kind"] = raw_row.get("kind")
        canonical_row = _canonical_contract_blocked_audit_row(lane_id, canonical_input)
        if _hash_payload(canonical_row) != _hash_payload(raw_row):
            raise ValueError(f"Pending contract-blocked evidence is not canonical for {lane_id}")
        seen_lane_ids.add(lane_id)
        rows.append(canonical_row)

    rows.sort(key=lambda row: str(row["lane_id"]))
    evidence = {"schema_version": 1, "contract_blocked_lanes": rows}
    if raw_digest != _hash_payload(evidence):
        raise ValueError("Pending contract-blocked evidence digest does not match")
    return rows


def build_resume_manifest(
    lanes: list[FullExtractionLane],
    metadata_dir: Path,
    *,
    chain_state: FullExtractionChainState | None = None,
    attempted_lane_ids: frozenset[str] | None = None,
    allow_missing_attempted_metadata: bool = False,
    allow_pipeline_failures: bool = False,
    completed_artifact_run_id: str | None = None,
    chunk_profile: str | None = None,
    latest_checkpoint_run_id: str | None = None,
    latest_checkpoint_artifact_name: str | None = None,
    latest_checkpoint_generation: int | None = None,
    latest_checkpoint_coverage_hash: str | None = None,
    current_iteration: int = 1,
    max_matrix_lanes: int = MAX_GITHUB_MATRIX_LANES,
) -> tuple[list[FullExtractionLane], FullExtractionChainState, dict[str, Any]]:
    metadata = _metadata_by_lane(metadata_dir)
    previous_state = chain_state or FullExtractionChainState()
    pending_contract_blocked_rows = {
        str(row["lane_id"]): row
        for row in _validated_pending_contract_blocked_evidence(previous_state)
    }
    next_lanes: list[FullExtractionLane] = []
    resumed = 0
    active = 0
    deferred = 0
    outcome_counts: dict[str, int] = {}
    failure_reason_counts: dict[str, int] = {}
    failure_class_counts: dict[str, int] = {}
    split_lane_count = 0
    contract_blocked = 0
    blocked_lanes: list[FullExtractionLane] = []
    pipeline_failures: list[str] = []
    pipeline_failure_retries = 0
    profile_override = _validate_chunk_profile(chunk_profile) if chunk_profile else None

    def record_pending_contract_blocked_lane(lane: FullExtractionLane) -> None:
        row = _canonical_contract_blocked_row_for_lane(lane)
        existing = pending_contract_blocked_rows.get(lane.lane_id)
        if existing is not None and existing != row:
            raise ValueError(f"Pending contract-blocked evidence changed for {lane.lane_id}")
        pending_contract_blocked_rows[lane.lane_id] = row

    for source_lane in lanes:
        lane = (
            replace(source_lane, chunk_profile=profile_override)
            if profile_override is not None
            else source_lane
        )
        payload = metadata.get(lane.lane_id)
        raw_status = str(payload.get("status", "")) if payload else ""
        if not raw_status and _lane_is_contract_blocked(lane):
            record_pending_contract_blocked_lane(lane)
            contract_blocked += 1
            outcome_counts["contract_blocked"] = outcome_counts.get("contract_blocked", 0) + 1
            continue
        if not raw_status and lane.resume_only:
            next_lanes.append(lane)
            resumed += 1
            continue
        missing_attempted_metadata = (
            payload is None
            and allow_missing_attempted_metadata
            and (attempted_lane_ids is None or lane.lane_id in attempted_lane_ids)
        )
        if missing_attempted_metadata:
            infrastructure_streak = (
                lane.class_failure_streak + 1
                if lane.last_failure_class == "runner_infrastructure"
                else 1
            )
            retry_lane = replace(
                lane,
                resume_only=False,
                attempt_count=lane.attempt_count + 1,
                failure_streak=(
                    lane.failure_streak + 1 if lane.last_failure_reason == "missing-metadata" else 1
                ),
                class_failure_streak=infrastructure_streak,
                zero_progress_streak=lane.zero_progress_streak + 1,
                last_failure_reason="missing-metadata",
                last_failure_class="runner_infrastructure",
                next_eligible_iteration=current_iteration,
            )
            failure_class_counts["runner_infrastructure"] = (
                failure_class_counts.get("runner_infrastructure", 0) + 1
            )
            if _lane_retry_budget_exhausted(retry_lane):
                blocked_lanes.append(retry_lane)
                next_lanes.append(retry_lane)
                active += 1
                continue
            if _lane_exceeds_policy(lane) and not _lane_has_state_artifact_pointer(retry_lane):
                child_lanes = _split_legacy_oversized_lane(
                    retry_lane,
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
            next_lanes.append(retry_lane)
            active += 1
            failure_reason_counts["missing-metadata"] = (
                failure_reason_counts.get("missing-metadata", 0) + 1
            )
            outcome_counts["needs_resume"] = outcome_counts.get("needs_resume", 0) + 1
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
                if _lane_exceeds_policy(lane) and not _lane_has_state_artifact_pointer(lane):
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
                    class_failure_streak=0,
                    zero_progress_streak=0,
                    last_failure_reason="",
                    last_failure_class="",
                    next_eligible_iteration=0,
                    state_artifact_run_id="",
                    state_artifact_name="",
                    state_artifact_digest="",
                    last_completed_calls=0,
                    last_rows_persisted=0,
                )
            )
            resumed += 1
            continue
        if status == "contract_blocked":
            record_pending_contract_blocked_lane(lane)
            contract_blocked += 1
            continue
        failure_reason = str(payload.get("raw_status") or raw_status or status)
        failure_reason_counts[failure_reason] = failure_reason_counts.get(failure_reason, 0) + 1
        failure_class = _metadata_failure_class(payload, raw_status=failure_reason)
        failure_class_counts[failure_class] = failure_class_counts.get(failure_class, 0) + 1
        if status == "pipeline_failure":
            if not allow_pipeline_failures:
                pipeline_failures.append(f"{lane.lane_id} ({failure_reason})")
                continue
            failure_streak = lane.failure_streak + 1 if lane.last_failure_reason == status else 1
            retry_lane = replace(
                _retry_lane_from_metadata(
                    lane,
                    payload,
                    outcome=status,
                    current_iteration=current_iteration,
                ),
                failure_streak=failure_streak,
                last_failure_reason=status,
            )
            if _lane_retry_budget_exhausted(retry_lane):
                blocked_lanes.append(retry_lane)
                next_lanes.append(retry_lane)
                active += 1
                continue
            if _lane_exceeds_policy(lane) and not _metadata_added_durable_progress(lane, payload):
                child_lanes = _split_legacy_oversized_lane(
                    retry_lane,
                    reason=f"pipeline-failure-{failure_reason}",
                )
                next_lanes.extend(child_lanes)
                split_lane_count += len(child_lanes)
                active += len(child_lanes)
                pipeline_failure_retries += 1
                continue
            next_lanes.append(retry_lane)
            active += 1
            pipeline_failure_retries += 1
            continue
        failure_streak = lane.failure_streak + 1 if lane.last_failure_reason == status else 1
        retry_lane = replace(
            _retry_lane_from_metadata(
                lane,
                payload,
                outcome=status,
                current_iteration=current_iteration,
            ),
            failure_streak=failure_streak,
            last_failure_reason=status,
        )
        if _lane_retry_budget_exhausted(retry_lane):
            blocked_lanes.append(retry_lane)
            next_lanes.append(retry_lane)
            active += 1
            continue
        if (
            _status_allows_legacy_split(status)
            and _lane_exceeds_policy(lane)
            and not _metadata_added_durable_progress(lane, payload)
        ):
            child_lanes = _split_legacy_oversized_lane(
                retry_lane,
                reason=f"legacy-oversized-{status}",
            )
            next_lanes.extend(child_lanes)
            split_lane_count += len(child_lanes)
            active += len(child_lanes)
            continue
        if _timeout_retry_should_split(
            lane,
            payload,
            outcome=status,
        ):
            child_lanes = _split_timeout_lane(retry_lane, reason=status)
            next_lanes.extend(child_lanes)
            split_lane_count += len(child_lanes)
            active += len(child_lanes)
            continue
        next_lanes.append(retry_lane)
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
    dispatched_lane_count = sum(
        1
        for lane in lanes
        if not lane.resume_only
        and attempted_lane_ids is not None
        and lane.lane_id in attempted_lane_ids
    )
    next_scheduler_cursor = (
        previous_state.scheduler_rotation_cursor + dispatched_lane_count
    ) % len(SCHEDULER_QUEUE_SEQUENCE)
    replacing_checkpoint = bool(latest_checkpoint_run_id and latest_checkpoint_artifact_name)
    merged_artifact_run_ids = _normalize_server_list(
        [
            *(() if replacing_checkpoint else previous_state.artifact_run_ids),
            *([completed_artifact_run_id] if completed_artifact_run_id else []),
        ]
    )
    profile = profile_override or _manifest_chunk_profile(next_lanes or lanes)
    next_lanes = _schedule_lanes(
        next_lanes,
        chunk_profile=profile,
        max_matrix_lanes=max_matrix_lanes,
        rotation_cursor=next_scheduler_cursor,
    )
    checkpoint_generation = (
        int(latest_checkpoint_generation)
        if latest_checkpoint_generation is not None
        else previous_state.latest_checkpoint_generation
    )
    pending_contract_blocked_evidence = tuple(
        pending_contract_blocked_rows[lane_id] for lane_id in sorted(pending_contract_blocked_rows)
    )
    pending_contract_blocked_evidence_sha256 = (
        _hash_payload(
            {
                "schema_version": 1,
                "contract_blocked_lanes": list(pending_contract_blocked_evidence),
            }
        )
        if pending_contract_blocked_evidence
        else ""
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
        previous_checkpoint_run_id=(
            previous_state.latest_checkpoint_run_id
            if replacing_checkpoint
            else previous_state.previous_checkpoint_run_id
        ),
        previous_checkpoint_artifact_name=(
            previous_state.latest_checkpoint_artifact_name
            if replacing_checkpoint
            else previous_state.previous_checkpoint_artifact_name
        ),
        previous_checkpoint_generation=(
            previous_state.latest_checkpoint_generation
            if replacing_checkpoint
            else previous_state.previous_checkpoint_generation
        ),
        previous_checkpoint_coverage_hash=(
            previous_state.latest_checkpoint_coverage_hash
            if replacing_checkpoint
            else previous_state.previous_checkpoint_coverage_hash
        ),
        scheduler_rotation_cursor=next_scheduler_cursor,
        iteration_budget=previous_state.iteration_budget,
        contract_blocked_evidence=previous_state.contract_blocked_evidence,
        contract_blocked_evidence_sha256=previous_state.contract_blocked_evidence_sha256,
        previous_contract_blocked_evidence=(
            previous_state.contract_blocked_evidence
            if replacing_checkpoint
            else previous_state.previous_contract_blocked_evidence
        ),
        previous_contract_blocked_evidence_sha256=(
            previous_state.contract_blocked_evidence_sha256
            if replacing_checkpoint
            else previous_state.previous_contract_blocked_evidence_sha256
        ),
        pending_contract_blocked_evidence=pending_contract_blocked_evidence,
        pending_contract_blocked_evidence_sha256=(pending_contract_blocked_evidence_sha256),
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
            "pipeline_failure_retry_count": pipeline_failure_retries,
            "outcome_counts": outcome_counts,
            "failure_reason_counts": failure_reason_counts,
            "failure_class_counts": failure_class_counts,
            "durable_state_lane_count": sum(
                1 for lane in next_lanes if lane.state_artifact_run_id and not lane.resume_only
            ),
            "scheduler_dispatched_lane_count": dispatched_lane_count,
            "scheduler_rotation_cursor": next_scheduler_cursor,
        },
    )


def _audit_scope_sequence(
    payload: dict[str, Any],
    field_name: str,
    *,
    required: bool = False,
) -> tuple[str, ...]:
    raw_values = payload.get(field_name, [])
    if not isinstance(raw_values, list):
        raise ValueError(f"contract-blocked {field_name} must be a list")
    values: list[str] = []
    for raw_value in raw_values:
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError(f"contract-blocked {field_name} entries must be strings")
        value = raw_value.strip()
        if value in values:
            raise ValueError(f"contract-blocked {field_name} entries must be unique")
        values.append(value)
    if required and not values:
        raise ValueError(f"contract-blocked {field_name} must be non-empty")
    return tuple(values)


def _audit_scope_season(payload: dict[str, Any], field_name: str) -> int | None:
    raw_value = payload.get(field_name)
    if raw_value is None or raw_value == "":
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int | str):
        raise ValueError(f"contract-blocked {field_name} must be an integer or empty")
    raw_text = str(raw_value).strip()
    if not raw_text.isdigit():
        raise ValueError(f"contract-blocked {field_name} must be a non-negative integer")
    return int(raw_text)


def _canonical_contract_blocked_audit_row(
    lane_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    kind = payload.get("lane_kind")
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("contract-blocked lane_kind must be a non-empty string")
    endpoints = _audit_scope_sequence(payload, "endpoints", required=True)
    patterns = _audit_scope_sequence(payload, "patterns", required=True)
    season_types = _audit_scope_sequence(payload, "season_types")
    context_measures = _audit_scope_sequence(payload, "context_measures")
    season_start = _audit_scope_season(payload, "season_start")
    season_end = _audit_scope_season(payload, "season_end")
    if (season_start is None) != (season_end is None):
        raise ValueError("contract-blocked season bounds must both be set or both be empty")
    if season_start is not None and season_end is not None and season_start > season_end:
        raise ValueError("contract-blocked season_start must not exceed season_end")
    if set(context_measures) - set(VIDEO_CONTEXT_MEASURES):
        raise ValueError("contract-blocked context_measures contain unknown values")
    if context_measures and not set(endpoints) <= VIDEO_ENDPOINTS:
        raise ValueError("contract-blocked context_measures require video endpoints")

    lane = FullExtractionLane(
        lane_id=lane_id,
        lane_index=0,
        lane_name=lane_id,
        lane_kind=kind.strip(),
        season_start=season_start,
        season_end=season_end,
        patterns=patterns,
        season_types=season_types,
        context_measures=context_measures,
        endpoints=endpoints,
        resume_only=True,
        timeout_seconds=1,
    )
    support_rules = sorted(
        _lane_contract_blocking_rules(lane),
        key=lambda rule: json.dumps(rule, sort_keys=True, separators=(",", ":")),
    )
    if not support_rules:
        raise ValueError("contract-blocked scope has no recomputed support rules")
    reported_rules = payload.get("support_rules")
    if reported_rules is not None and _support_rule_fingerprints(reported_rules) != (
        _support_rule_fingerprints(support_rules)
    ):
        raise ValueError("contract-blocked support rules do not match recomputed rules")
    coverage_units_hash = _coverage_hash_for_lane(lane)
    reported_coverage_hash = payload.get("coverage_units_hash")
    if (
        not isinstance(reported_coverage_hash, str)
        or not _is_sha256(reported_coverage_hash)
        or reported_coverage_hash != coverage_units_hash
    ):
        raise ValueError("contract-blocked coverage hash does not match recomputed scope")

    return {
        "lane_id": lane_id,
        "status": "contract_blocked",
        "kind": lane.lane_kind,
        "endpoints": list(endpoints),
        "patterns": list(patterns),
        "season_start": season_start,
        "season_end": season_end,
        "season_types": list(season_types),
        "context_measures": list(context_measures),
        "coverage_units_hash": coverage_units_hash,
        "support_rules": support_rules,
    }


def _validated_checkpoint_contract_blocked_evidence(
    report: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Validate and canonicalize cumulative contract-blocked checkpoint evidence."""
    raw_count = report.get("contract_blocked_lane_count", 0)
    if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
        raise ValueError("Checkpoint contract-blocked lane count must be non-negative")
    raw_bundle = report.get("contract_blocked_evidence")
    raw_digest = str(report.get("contract_blocked_evidence_sha256") or "").strip().lower()
    if raw_bundle is None and raw_count == 0 and not raw_digest:
        return [], ""
    if not isinstance(raw_bundle, dict) or raw_bundle.get("schema_version") != 1:
        raise ValueError("Checkpoint contract-blocked evidence is invalid")
    raw_rows = raw_bundle.get("contract_blocked_lanes")
    if not isinstance(raw_rows, list):
        raise ValueError("Checkpoint contract-blocked evidence rows must be a list")

    rows: list[dict[str, Any]] = []
    seen_lane_ids: set[str] = set()
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise ValueError("Checkpoint contract-blocked evidence rows must be objects")
        lane_id = str(raw_row.get("lane_id") or "").strip()
        if not lane_id or lane_id in seen_lane_ids:
            raise ValueError("Checkpoint contract-blocked lane IDs must be non-empty and unique")
        canonical_input = dict(raw_row)
        canonical_input["lane_kind"] = raw_row.get("kind")
        canonical_row = _canonical_contract_blocked_audit_row(lane_id, canonical_input)
        if _hash_payload(canonical_row) != _hash_payload(raw_row):
            raise ValueError(f"Checkpoint contract-blocked evidence is not canonical for {lane_id}")
        seen_lane_ids.add(lane_id)
        rows.append(canonical_row)

    rows.sort(key=lambda row: str(row["lane_id"]))
    bundle = {"schema_version": 1, "contract_blocked_lanes": rows}
    actual_digest = _hash_payload(bundle)
    if raw_digest != actual_digest:
        raise ValueError("Checkpoint contract-blocked evidence digest does not match")
    if raw_count != len(rows):
        raise ValueError("Checkpoint contract-blocked evidence count does not match")
    return rows, actual_digest


def _validate_contract_blocked_evidence_commitment(
    report: dict[str, Any],
    chain_state: FullExtractionChainState,
    *,
    pointer_prefix: str,
) -> tuple[list[dict[str, Any]], str]:
    rows, digest = _validated_checkpoint_contract_blocked_evidence(report)
    if pointer_prefix == "latest":
        committed_rows = list(chain_state.contract_blocked_evidence)
        committed_digest = chain_state.contract_blocked_evidence_sha256
    elif pointer_prefix == "previous":
        committed_rows = list(chain_state.previous_contract_blocked_evidence)
        committed_digest = chain_state.previous_contract_blocked_evidence_sha256
    else:
        raise ValueError(f"Unknown checkpoint pointer prefix: {pointer_prefix}")
    if committed_rows != rows:
        raise ValueError(
            f"Checkpoint contract-blocked evidence does not match the {pointer_prefix} "
            "chain-state commitment"
        )
    if committed_digest != digest:
        raise ValueError(
            f"Checkpoint contract-blocked evidence digest does not match the {pointer_prefix} "
            "chain-state commitment"
        )
    return rows, digest


def _validated_chain_state_contract_blocked_evidence(
    chain_state: FullExtractionChainState,
) -> tuple[list[dict[str, Any]], str]:
    rows = list(chain_state.contract_blocked_evidence)
    digest = chain_state.contract_blocked_evidence_sha256.strip().lower()
    report: dict[str, Any] = {"contract_blocked_lane_count": len(rows)}
    if rows or digest:
        report.update(
            {
                "contract_blocked_evidence": {
                    "schema_version": 1,
                    "contract_blocked_lanes": rows,
                },
                "contract_blocked_evidence_sha256": digest,
            }
        )
    return _validated_checkpoint_contract_blocked_evidence(report)


def build_metadata_audit(metadata_dir: Path) -> dict[str, Any]:
    metadata = _metadata_by_lane(metadata_dir)
    status_counts: dict[str, int] = {}
    kind_counts: dict[str, dict[str, int]] = {}
    endpoint_counts: dict[str, dict[str, int]] = {}
    vpn_status_counts: dict[str, int] = {}
    failure_class_counts: dict[str, int] = {}
    root_error_type_counts: dict[str, int] = {}
    zero_row_lanes: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    contract_blocked_lanes: list[dict[str, Any]] = []
    pipeline_failure_lanes: list[dict[str, Any]] = []
    total_rows = 0
    total_failed_calls = 0
    total_journal_skips = 0
    total_completed_calls = 0
    durable_state_lane_count = 0

    for lane_id, payload in sorted(metadata.items()):
        status = str(lane_outcome_from_metadata(payload))
        contract_blocked_row: dict[str, Any] | None = None
        if status == "contract_blocked":
            try:
                contract_blocked_row = _canonical_contract_blocked_audit_row(
                    lane_id,
                    payload,
                )
            except ValueError:
                status = "pipeline_failure"
        kind = str(payload.get("lane_kind") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        kind_bucket = kind_counts.setdefault(kind, {})
        kind_bucket[status] = kind_bucket.get(status, 0) + 1
        vpn_status = str(payload.get("vpn_status") or "unknown")
        vpn_status_counts[vpn_status] = vpn_status_counts.get(vpn_status, 0) + 1
        failure_class = str(payload.get("failure_class") or "").strip()
        if failure_class:
            failure_class_counts[failure_class] = failure_class_counts.get(failure_class, 0) + 1
        raw_root_counts = payload.get("root_error_type_counts")
        if isinstance(raw_root_counts, dict):
            for error_type, count in raw_root_counts.items():
                root_error_type_counts[str(error_type)] = root_error_type_counts.get(
                    str(error_type), 0
                ) + _int_metadata_value(count)
        state_artifact = payload.get("state_artifact")
        if isinstance(state_artifact, dict) and state_artifact.get("run_id"):
            durable_state_lane_count += 1

        endpoints = payload.get("endpoints", [])
        if not isinstance(endpoints, list):
            endpoints = []
        telemetry = payload.get("telemetry", {})
        if not isinstance(telemetry, dict):
            telemetry = {}
        rows = int(telemetry.get("rows_persisted") or 0)
        failed_calls = int(telemetry.get("failed_calls") or 0)
        journal_skips = int(telemetry.get("journal_skips") or 0)
        completed_calls, _ = _metadata_progress(payload)
        total_rows += rows
        total_failed_calls += failed_calls
        total_journal_skips += journal_skips
        total_completed_calls += completed_calls

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
                    "failure_class": failure_class,
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
            "failure_class": failure_class,
            "root_error_type": str(payload.get("root_error_type") or ""),
        }
        if status == "contract_blocked":
            if contract_blocked_row is None:
                raise AssertionError("contract-blocked audit row was not validated")
            contract_blocked_lanes.append(contract_blocked_row)
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
        "failure_class_counts": failure_class_counts,
        "root_error_type_counts": root_error_type_counts,
        "rows_persisted": total_rows,
        "failed_calls": total_failed_calls,
        "journal_skips": total_journal_skips,
        "completed_calls": total_completed_calls,
        "durable_state_lane_count": durable_state_lane_count,
        "zero_row_lanes": zero_row_lanes,
        "contract_blocked_lanes": contract_blocked_lanes,
        "pipeline_failure_lanes": pipeline_failure_lanes,
        "blockers": blockers,
    }


def _merge_database_paths(
    *,
    db_paths: list[Path],
    output_dir: Path,
    base_database_path: Path | None = None,
) -> dict[str, Any]:
    db_paths = sorted(path for path in db_paths if path.is_file())
    if base_database_path is not None and not base_database_path.is_file():
        msg = f"Base database was not available to merge: {base_database_path}"
        raise FileNotFoundError(msg)
    if not db_paths and base_database_path is None:
        msg = "No lane databases were available to merge"
        raise FileNotFoundError(msg)

    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / "nba.duckdb"
    working_path = output_dir / ".nba.duckdb.tmp"
    working_wal_path = Path(f"{working_path}.wal")
    if base_database_path is not None and base_database_path.resolve() == target_path.resolve():
        msg = "Checkpoint roll-forward output must differ from the previous checkpoint"
        raise ValueError(msg)
    for stale_path in (working_path, working_wal_path):
        with suppress(FileNotFoundError):
            stale_path.unlink()

    if base_database_path is not None:
        shutil.copy2(base_database_path, working_path)

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

    merged_tables = 0
    table_reports: dict[str, dict[str, Any]] = {}
    journal_report: dict[str, Any] = {
        "source_rows": 0,
        "inserted_rows": 0,
        "duplicate_rows": 0,
        "replaced_base_rows": 0,
        "delete_batch_count": 0,
        "insert_batch_count": 0,
        "source_count": 0,
        "per_source": [],
    }

    summary = {
        "merged_database_count": len(db_paths) + int(base_database_path is not None),
        "merged_delta_database_count": len(db_paths),
        "base_database_copied": base_database_path is not None,
        "copy_fast_path": base_database_path is not None and not db_paths,
        "merged_table_operations": merged_tables,
        "output_path": str(target_path),
        "table_reports": table_reports,
        "journal_report": journal_report,
    }
    if not db_paths:
        working_path.replace(target_path)
        return summary

    target = duckdb.connect(str(working_path))
    target_database_row = target.execute("SELECT current_database()").fetchone()
    if target_database_row is None:
        target.close()
        msg = f"Could not resolve target database name for {working_path}"
        raise RuntimeError(msg)
    target_database = str(target_database_row[0])
    attached_aliases: list[str] = []
    journal_source_aliases: list[str] = []
    merge_failed = False

    try:
        for index, db_path in enumerate(db_paths):
            alias = f"src_{index}"
            target.execute(f"ATTACH '{db_path}' AS {alias} (READ_ONLY)")
            attached_aliases.append(alias)

        target.execute("BEGIN TRANSACTION")
        try:
            for alias, db_path in zip(attached_aliases, db_paths, strict=True):
                if not table_exists(target, alias, "_extraction_journal"):
                    continue
                source_schema = table_schema(target, alias, "_extraction_journal")
                if not table_exists(target, target_database, "_extraction_journal"):
                    target.execute(
                        "CREATE TABLE main._extraction_journal AS "
                        f"SELECT * FROM {alias}._extraction_journal WHERE FALSE"
                    )
                target_schema = table_schema(
                    target,
                    target_database,
                    "_extraction_journal",
                )
                if target_schema != source_schema:
                    msg = (
                        "Schema mismatch while merging _extraction_journal "
                        f"from {db_path}: expected {target_schema}, got {source_schema}"
                    )
                    raise ValueError(msg)
                if any(column_name == "__merge_source_order" for column_name, _ in source_schema):
                    msg = (
                        "Reserved merge column __merge_source_order exists in "
                        f"_extraction_journal from {db_path}"
                    )
                    raise ValueError(msg)
                journal_source_aliases.append(alias)

            if journal_source_aliases:
                source_order_by_alias = {
                    alias: index for index, alias in enumerate(attached_aliases)
                }
                journal_union = " UNION ALL ".join(
                    (
                        f"SELECT *, {source_order_by_alias[alias]}::INTEGER "
                        f"AS __merge_source_order FROM {alias}._extraction_journal"
                    )
                    for alias in journal_source_aliases
                )
                target.execute(
                    f"""
                    CREATE TEMP TABLE _delta_journal_winners AS
                    SELECT * EXCLUDE (__merge_rank)
                    FROM (
                        SELECT
                            *,
                            ROW_NUMBER() OVER (
                                PARTITION BY endpoint, params
                                ORDER BY __merge_source_order DESC
                            ) AS __merge_rank
                        FROM ({journal_union}) AS delta_rows
                    ) AS ranked_rows
                    WHERE __merge_rank = 1
                    """
                )

                for alias, db_path in zip(attached_aliases, db_paths, strict=True):
                    if alias not in journal_source_aliases:
                        continue
                    source_order = source_order_by_alias[alias]
                    source_rows = row_count(
                        target,
                        f"SELECT COUNT(*) FROM {alias}._extraction_journal",
                    )
                    winning_rows = row_count(
                        target,
                        "SELECT COUNT(*) FROM _delta_journal_winners "
                        "WHERE __merge_source_order = ?",
                        [source_order],
                    )
                    duplicate_rows = max(source_rows - winning_rows, 0)
                    journal_report["source_rows"] += source_rows
                    journal_report["duplicate_rows"] += duplicate_rows
                    journal_report["source_count"] += 1
                    journal_report["per_source"].append(
                        {
                            "database_path": str(db_path),
                            "source_rows": source_rows,
                            "inserted_rows": winning_rows,
                            "duplicate_rows": duplicate_rows,
                        }
                    )

                if base_database_path is not None:
                    before_rows = row_count(
                        target,
                        "SELECT COUNT(*) FROM main._extraction_journal",
                    )
                    target.execute(
                        """
                        DELETE FROM main._extraction_journal AS dst
                        WHERE EXISTS (
                            SELECT 1
                            FROM _delta_journal_winners AS src
                            WHERE dst.endpoint = src.endpoint
                              AND dst.params IS NOT DISTINCT FROM src.params
                        )
                        """
                    )
                    after_rows = row_count(
                        target,
                        "SELECT COUNT(*) FROM main._extraction_journal",
                    )
                    journal_report["replaced_base_rows"] = before_rows - after_rows
                    journal_report["delete_batch_count"] = 1

                journal_columns = [
                    column_name
                    for column_name, _data_type in table_schema(
                        target,
                        target_database,
                        "_extraction_journal",
                    )
                ]
                quoted_journal_columns = ", ".join(
                    quote_identifier(column_name) for column_name in journal_columns
                )
                target.execute(
                    f"""
                    INSERT INTO main._extraction_journal ({quoted_journal_columns})
                    SELECT {quoted_journal_columns}
                    FROM _delta_journal_winners
                    ORDER BY endpoint, params, __merge_source_order
                    """
                )
                journal_report["inserted_rows"] = row_count(
                    target,
                    "SELECT COUNT(*) FROM _delta_journal_winners",
                )
                journal_report["insert_batch_count"] = 1

            for alias, db_path in zip(attached_aliases, db_paths, strict=True):
                tables = [
                    row[0]
                    for row in target.execute(
                        "SELECT table_name FROM duckdb_tables() "
                        f"WHERE database_name = '{alias}' AND schema_name = 'main' "
                        "AND table_name LIKE 'stg_%' ORDER BY table_name"
                    ).fetchall()
                ]
                for table_name in tables:
                    quoted_table = quote_identifier(table_name)
                    source_schema = table_schema(target, alias, table_name)
                    if not table_exists(target, target_database, table_name):
                        target.execute(
                            f"CREATE TABLE main.{quoted_table} AS "
                            f"SELECT * FROM {alias}.{quoted_table} WHERE FALSE"
                        )
                    target_schema = table_schema(target, target_database, table_name)
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
                        f"EXCEPT ALL SELECT * FROM main.{quoted_table}"
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
            for failed_path in (working_path, working_wal_path):
                with suppress(FileNotFoundError):
                    failed_path.unlink()

    working_path.replace(target_path)
    summary["merged_table_operations"] = merged_tables
    return summary


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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _is_source_sha(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value.lower())


def _is_positive_run_id(value: str) -> bool:
    return value.isdigit() and not value.startswith("0")


def _checkpoint_artifact_name(chain_id: str, generation: int) -> str:
    return f"full-extraction-checkpoint-{chain_id}-iter-{generation}"


def _lane_artifact_name(chain_id: str, lane_id: str) -> str:
    return f"extraction-lane-{chain_id}-{lane_id}"


def _lane_metadata_artifact_name(chain_id: str, lane_id: str) -> str:
    return f"extraction-lane-metadata-{chain_id}-{lane_id}"


@dataclass(frozen=True, slots=True)
class _CheckpointPointer:
    run_id: str
    artifact_name: str
    generation: int
    coverage_hash: str


def _checkpoint_pointer(
    chain_state: FullExtractionChainState,
    *,
    prefix: str,
    chain_id: str,
) -> _CheckpointPointer | None:
    if prefix not in {"latest", "previous"}:
        raise ValueError(f"Unsupported checkpoint pointer prefix: {prefix}")
    run_id = getattr(chain_state, f"{prefix}_checkpoint_run_id")
    artifact_name = getattr(chain_state, f"{prefix}_checkpoint_artifact_name")
    generation = getattr(chain_state, f"{prefix}_checkpoint_generation")
    coverage_hash = getattr(chain_state, f"{prefix}_checkpoint_coverage_hash").lower()
    present = (bool(run_id), bool(artifact_name), generation != 0, bool(coverage_hash))
    if any(present) and not all(present):
        raise ValueError(
            f"The {prefix} checkpoint pointer must set run ID, artifact name, "
            "generation, and coverage hash together"
        )
    if not any(present):
        return None
    if not _is_positive_run_id(run_id):
        raise ValueError(f"The {prefix} checkpoint run ID must be a positive integer")
    if generation < 1:
        raise ValueError(f"The {prefix} checkpoint generation must be positive")
    expected_name = _checkpoint_artifact_name(chain_id, generation)
    if artifact_name != expected_name:
        raise ValueError(
            f"The {prefix} checkpoint artifact name must be {expected_name}, got {artifact_name}"
        )
    if not _is_sha256(coverage_hash):
        raise ValueError(f"The {prefix} checkpoint coverage hash must be a SHA-256")
    return _CheckpointPointer(
        run_id=run_id,
        artifact_name=artifact_name,
        generation=generation,
        coverage_hash=coverage_hash,
    )


def _validate_checkpoint_trust_root(
    raw_manifest: Any,
    *,
    chain_id: str,
    source_sha: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not chain_id:
        raise ValueError("Checkpoint chain_id must be non-empty")
    normalized_source_sha = source_sha.strip().lower()
    if not _is_source_sha(normalized_source_sha):
        raise ValueError("Checkpoint source_sha must be a 40-character commit SHA")
    if run_id is not None and not _is_positive_run_id(run_id):
        raise ValueError("Checkpoint run_id must be a positive integer")
    if not isinstance(raw_manifest, dict):
        raise ValueError("Checkpoint manifest must be an object")
    raw_chain_state = raw_manifest.get("chain_state", {})
    if not isinstance(raw_chain_state, dict):
        raise ValueError("Checkpoint manifest chain_state must be an object")
    for prefix in ("latest", "previous"):
        raw_generation = raw_chain_state.get(f"{prefix}_checkpoint_generation", 0)
        if isinstance(raw_generation, bool) or not isinstance(raw_generation, int):
            raise ValueError(
                f"The {prefix} checkpoint generation must be represented as an integer"
            )
    if str(raw_manifest.get("chain_id") or "") != chain_id:
        raise ValueError("Checkpoint manifest chain_id does not match the trusted chain")
    if str(raw_manifest.get("workflow_source_sha") or "").strip().lower() != normalized_source_sha:
        raise ValueError("Checkpoint manifest source SHA does not match the trusted source")
    return raw_manifest


def _artifact_root_for_provenance(
    *,
    path: Path,
    root: Path,
    run_id: str,
    artifact_name: str,
) -> Path | None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    matches = [index for index, part in enumerate(relative.parts) if part == artifact_name]
    if len(matches) != 1:
        return None
    artifact_index = matches[0]
    if artifact_index == 0 or relative.parts[artifact_index - 1] != f"run-{run_id}":
        return None
    return root.joinpath(*relative.parts[: artifact_index + 1])


def _read_lane_state_attestation(artifact_root: Path) -> tuple[dict[str, Any], str]:
    candidates = sorted(artifact_root.rglob("lane-state-attestation.json"))
    if len(candidates) != 1:
        return {}, f"lane_state_attestation_count:{len(candidates)}"
    attestation_path = candidates[0]
    if attestation_path.is_symlink() or not attestation_path.is_file():
        return {}, "lane_state_attestation_not_regular"
    try:
        payload = json.loads(attestation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, "lane_state_attestation_invalid_json"
    if not isinstance(payload, dict):
        return {}, "lane_state_attestation_not_object"
    return payload, ""


def _checkpoint_lane_coverage_hashes(
    lanes_by_id: dict[str, FullExtractionLane],
    lane_ids: set[str],
) -> dict[str, str]:
    return {
        lane_id: _coverage_hash_for_lane(lanes_by_id[lane_id])
        for lane_id in sorted(lane_ids & set(lanes_by_id))
    }


def _checkpoint_lane_workload_contracts(
    lanes_by_id: dict[str, FullExtractionLane],
    lane_ids: set[str],
    workload_store: PlayerTeamSeasonWorkloadStore | None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    contracts: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for lane_id in sorted(lane_ids & set(lanes_by_id)):
        lane = lanes_by_id[lane_id]
        if "player_team_season" not in lane.patterns:
            continue
        _base_units, contract, lane_errors = _workload_scope_contract(lane, workload_store)
        if lane_errors:
            errors.extend(f"{lane_id}:{error}" for error in lane_errors)
            continue
        contracts[lane_id] = contract
    return contracts, errors


def _validate_previous_checkpoint_report(
    *,
    previous_db_path: Path,
    previous_report_path: Path | None,
    previous_report: dict[str, Any],
    lanes_by_id: dict[str, FullExtractionLane],
    pointer: _CheckpointPointer,
    chain_id: str,
    source_sha: str,
    expected_workload_store: PlayerTeamSeasonWorkloadStore | None = None,
) -> tuple[set[str], list[str], dict[str, str]]:
    if previous_report_path is None or not previous_report_path.is_file() or not previous_report:
        msg = "Previous checkpoint database has no readable checkpoint report"
        raise ValueError(msg)
    if previous_report_path.is_symlink():
        raise ValueError("Previous checkpoint report must be a regular file")

    provenance_fields = (
        ("chain_id", chain_id),
        ("run_id", pointer.run_id),
        ("artifact_name", pointer.artifact_name),
        ("source_sha", source_sha),
        ("coverage_fingerprint", pointer.coverage_hash),
    )
    for field_name, expected in provenance_fields:
        actual = str(previous_report.get(field_name) or "").strip()
        if field_name in {"source_sha", "coverage_fingerprint"}:
            actual = actual.lower()
        if actual != expected:
            raise ValueError(f"Previous checkpoint report {field_name} does not match its pointer")
    reported_generation = previous_report.get("checkpoint_generation")
    if (
        isinstance(reported_generation, bool)
        or not isinstance(reported_generation, int)
        or reported_generation != pointer.generation
    ):
        raise ValueError(
            "Previous checkpoint report checkpoint_generation does not match its pointer"
        )

    reported_database_sha256 = str(previous_report.get("database_sha256") or "").strip()
    if not _is_sha256(reported_database_sha256):
        msg = "Previous checkpoint report is missing a valid database_sha256"
        raise ValueError(msg)
    actual_database_sha256 = _file_sha256(previous_db_path)
    if actual_database_sha256 != reported_database_sha256.lower():
        msg = "Previous checkpoint database digest does not match its report"
        raise ValueError(msg)

    raw_lane_ids = previous_report.get("included_lane_ids")
    if not isinstance(raw_lane_ids, list):
        msg = "Previous checkpoint report included_lane_ids must be a list"
        raise ValueError(msg)
    normalized_lane_ids = [str(value).strip() for value in raw_lane_ids]
    if any(not lane_id for lane_id in normalized_lane_ids):
        raise ValueError("Previous checkpoint report included_lane_ids must be non-empty")
    if len(set(normalized_lane_ids)) != len(normalized_lane_ids):
        raise ValueError("Previous checkpoint report included_lane_ids must be unique")
    included_lane_ids = set(normalized_lane_ids)
    out_of_scope_lane_ids = included_lane_ids - set(lanes_by_id)
    if out_of_scope_lane_ids:
        raise ValueError(
            "Previous checkpoint report contains lanes outside the current manifest: "
            + ", ".join(sorted(out_of_scope_lane_ids))
        )

    raw_coverage_hashes = previous_report.get("included_lane_coverage_hashes")
    if not isinstance(raw_coverage_hashes, dict):
        msg = "Previous checkpoint report is missing included_lane_coverage_hashes"
        raise ValueError(msg)
    coverage_hashes = {
        str(lane_id).strip(): str(coverage_hash).strip().lower()
        for lane_id, coverage_hash in raw_coverage_hashes.items()
        if str(lane_id).strip()
    }
    if len(coverage_hashes) != len(raw_coverage_hashes):
        raise ValueError("Previous checkpoint report has invalid lane coverage hash keys")
    if set(coverage_hashes) != included_lane_ids:
        missing_hash_ids = included_lane_ids - set(coverage_hashes)
        unexpected_hash_ids = set(coverage_hashes) - included_lane_ids
        details = []
        if missing_hash_ids:
            details.append("missing=" + ",".join(sorted(missing_hash_ids)))
        if unexpected_hash_ids:
            details.append("unexpected=" + ",".join(sorted(unexpected_hash_ids)))
        raise ValueError(
            "Previous checkpoint report lane coverage hash inventory does not match "
            "included_lane_ids: " + "; ".join(details)
        )
    invalid_hash_ids = sorted(
        lane_id
        for lane_id, coverage_hash in coverage_hashes.items()
        if not _is_sha256(coverage_hash)
    )
    if invalid_hash_ids:
        raise ValueError(
            "Previous checkpoint report has invalid lane coverage hashes: "
            + ", ".join(invalid_hash_ids)
        )

    for lane_id in sorted(included_lane_ids & set(lanes_by_id)):
        expected_hash = _coverage_hash_for_lane(lanes_by_id[lane_id])
        reported_hash = coverage_hashes.get(lane_id, "")
        if reported_hash != expected_hash:
            msg = (
                "Previous checkpoint lane coverage identity mismatch for "
                f"{lane_id}: expected {expected_hash}, got {reported_hash or 'missing'}"
            )
            raise ValueError(msg)

    if expected_workload_store is not None:
        expected_workload_integrity = expected_workload_store.integrity_attestation()
        if expected_workload_integrity is None:
            raise ValueError("Active discovery workload integrity is unavailable")

        raw_workload_contracts = previous_report.get("included_lane_workload_contracts")
        workload_lane_ids = {
            lane_id
            for lane_id in included_lane_ids & set(lanes_by_id)
            if "player_team_season" in lanes_by_id[lane_id].patterns
        }
        if not workload_lane_ids:
            if raw_workload_contracts not in (None, {}):
                raise ValueError(
                    "Previous checkpoint has workload contracts without an included "
                    "player/team/season lane"
                )
        else:
            previous_workload_integrity = previous_report.get("workload_integrity")
            if not isinstance(previous_workload_integrity, dict):
                raise ValueError("Previous checkpoint workload integrity is missing or invalid")
            if not isinstance(raw_workload_contracts, dict):
                raise ValueError("Previous checkpoint is missing included_lane_workload_contracts")
            unexpected_contract_ids = set(raw_workload_contracts) - included_lane_ids
            if unexpected_contract_ids:
                raise ValueError(
                    "Previous checkpoint has workload contracts for non-included lanes: "
                    + ", ".join(sorted(unexpected_contract_ids))
                )
            for lane_id in sorted(workload_lane_ids):
                previous_contract = raw_workload_contracts.get(lane_id)
                if not isinstance(previous_contract, dict):
                    raise ValueError(
                        f"Previous checkpoint is missing workload contract for {lane_id}"
                    )
                if previous_contract.get("integrity") != previous_workload_integrity:
                    raise ValueError(
                        f"Previous checkpoint workload integrity is unbound for {lane_id}"
                    )
                _base_units, expected_contract, errors = _workload_scope_contract(
                    lanes_by_id[lane_id],
                    expected_workload_store,
                )
                if errors:
                    raise ValueError(
                        f"Active discovery workload contract is invalid for {lane_id}: "
                        + ", ".join(errors)
                    )
                try:
                    previous_identity = player_team_season_workload_scope_identity(
                        previous_contract
                    )
                    expected_identity = player_team_season_workload_scope_identity(
                        expected_contract
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"Previous checkpoint workload contract is invalid for {lane_id}: {exc}"
                    ) from exc
                if previous_identity != expected_identity:
                    raise ValueError(
                        f"Previous checkpoint lane workload identity mismatch for {lane_id}"
                    )

    raw_run_ids = previous_report.get("included_run_ids")
    if not isinstance(raw_run_ids, list):
        msg = "Previous checkpoint report included_run_ids must be a list"
        raise ValueError(msg)
    included_run_ids = [str(value).strip() for value in raw_run_ids]
    if (
        any(not _is_positive_run_id(value) for value in included_run_ids)
        or len(set(included_run_ids)) != len(included_run_ids)
        or pointer.run_id not in included_run_ids
    ):
        raise ValueError(
            "Previous checkpoint report included_run_ids must be unique positive integers "
            "and include the checkpoint run"
        )
    return included_lane_ids, included_run_ids, coverage_hashes


def _first_database_path(root: Path | None) -> Path | None:
    if root is None or not root.exists():
        return None
    for path in sorted(root.rglob("nba.duckdb")):
        if path.is_file():
            return path
    return None


def _single_database_path(root: Path | None, *, label: str) -> Path:
    candidates = (
        []
        if root is None or not root.exists()
        else sorted(path for path in root.rglob("nba.duckdb") if path.is_file())
    )
    if len(candidates) != 1:
        raise ValueError(f"{label} must contain exactly one nba.duckdb, found {len(candidates)}")
    database_path = candidates[0]
    if database_path.is_symlink():
        raise ValueError(f"{label} database must be a regular file")
    return database_path


def validate_checkpoint_artifact(
    *,
    manifest_path: Path,
    checkpoint_dir: Path,
    checkpoint_report_path: Path,
    chain_id: str,
    source_sha: str,
    pointer_prefix: str = "latest",
) -> dict[str, Any]:
    """Validate a checkpoint before its report is used to select lane inventory."""
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    trusted_manifest = _validate_checkpoint_trust_root(
        raw_manifest,
        chain_id=chain_id,
        source_sha=source_sha,
    )
    manifest = normalize_manifest(trusted_manifest)
    pointer = _checkpoint_pointer(
        manifest.chain_state,
        prefix=pointer_prefix,
        chain_id=chain_id,
    )
    if pointer is None:
        raise ValueError(f"The manifest has no {pointer_prefix} checkpoint pointer")
    checkpoint_db_path = _single_database_path(
        checkpoint_dir,
        label=f"{pointer_prefix.capitalize()} checkpoint artifact",
    )
    report = _read_json_file(checkpoint_report_path)
    lane_ids, run_ids, coverage_hashes = _validate_previous_checkpoint_report(
        previous_db_path=checkpoint_db_path,
        previous_report_path=checkpoint_report_path,
        previous_report=report,
        lanes_by_id={lane.lane_id: lane for lane in manifest.lanes},
        pointer=pointer,
        chain_id=chain_id,
        source_sha=source_sha.strip().lower(),
    )
    contract_blocked_rows, contract_blocked_evidence_sha256 = (
        _validate_contract_blocked_evidence_commitment(
            report,
            manifest.chain_state,
            pointer_prefix=pointer_prefix,
        )
    )
    return {
        "run_id": pointer.run_id,
        "artifact_name": pointer.artifact_name,
        "checkpoint_generation": pointer.generation,
        "coverage_fingerprint": pointer.coverage_hash,
        "database_sha256": str(report["database_sha256"]).lower(),
        "included_lane_ids": sorted(lane_ids),
        "included_run_ids": run_ids,
        "included_lane_coverage_hashes": coverage_hashes,
        "contract_blocked_lane_count": len(contract_blocked_rows),
        "contract_blocked_evidence_sha256": contract_blocked_evidence_sha256,
    }


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


def _metadata_sequence(payload: dict[str, Any], field: str) -> tuple[str, ...]:
    raw_value = payload.get(field)
    if isinstance(raw_value, list):
        return tuple(str(value) for value in raw_value if str(value))
    if isinstance(raw_value, str):
        return tuple(value for value in raw_value.split(",") if value)
    return ()


def _metadata_lane_contract_errors(
    payload: dict[str, Any],
    lane: FullExtractionLane,
    *,
    strict: bool,
) -> list[str]:
    errors: list[str] = []
    scalar_fields: tuple[tuple[str, str], ...] = (
        ("lane_id", lane.lane_id),
        ("lane_name", lane.lane_name),
        ("lane_kind", lane.lane_kind),
    )
    for metadata_field, expected in scalar_fields:
        if metadata_field not in payload:
            if strict:
                errors.append(f"metadata_{metadata_field}_missing")
            continue
        actual = str(payload.get(metadata_field) or "")
        if actual != expected:
            errors.append(f"metadata_{metadata_field}_mismatch")

    if "lane_index" in payload:
        if _int_metadata_value(payload.get("lane_index")) != lane.lane_index:
            errors.append("metadata_lane_index_mismatch")
    elif strict:
        errors.append("metadata_lane_index_missing")

    sequence_fields: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("patterns", lane.patterns),
        ("season_types", lane.season_types),
        ("context_measures", lane.context_measures),
        ("endpoints", lane.endpoints),
    )
    for metadata_field, expected in sequence_fields:
        if metadata_field not in payload:
            if strict and (metadata_field != "context_measures" or expected):
                errors.append(f"metadata_{metadata_field}_missing")
            continue
        if _metadata_sequence(payload, metadata_field) != expected:
            errors.append(f"metadata_{metadata_field}_mismatch")

    season_fields: tuple[tuple[str, int | None], ...] = (
        ("season_start", lane.season_start),
        ("season_end", lane.season_end),
    )
    for metadata_field, expected in season_fields:
        if metadata_field not in payload:
            if strict:
                errors.append(f"metadata_{metadata_field}_missing")
            continue
        if _optional_int(payload.get(metadata_field)) != expected:
            errors.append(f"metadata_{metadata_field}_mismatch")
    return errors


def _journal_values(params_json: str) -> set[str]:
    try:
        payload = json.loads(params_json)
    except json.JSONDecodeError:
        return {params_json}

    values: set[str] = set()
    stack: list[Any] = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        else:
            values.add(str(value))
    return values


_JOURNAL_PARAMETER_KEYS_BY_PATTERN: dict[str, tuple[str, ...]] = {
    "game": ("game_id",),
    "date": ("game_date",),
    "player": ("player_id",),
    "team": ("team_id",),
    "player_season": ("player_id", "season"),
    "team_season": ("team_id", "season"),
    "player_team_season": ("player_id", "team_id", "season"),
    "season": ("season",),
}
_JOURNAL_PARAMETER_COVERAGE_PATTERNS = frozenset(
    {
        "game",
        "date",
        "player",
        "player_season",
        "team_season",
        "player_team_season",
    }
)
# Reference team endpoints intentionally mix all-team and current-team workloads.
# Their manifest unit is still attested, but their team-id sets are not interchangeable.
_JOURNAL_COVERAGE_ERROR_SAMPLE_LIMIT = 5
_GAME_ID_SEASON_TYPES: dict[str, str] = {
    "001": SeasonType.PRE_SEASON.value,
    "002": SeasonType.REGULAR.value,
    "003": SeasonType.ALL_STAR.value,
    "004": SeasonType.PLAYOFFS.value,
    "005": SeasonType.PLAY_IN.value,
}


def _journal_required_keys(pattern: str, *, endpoint: str) -> tuple[str, ...]:
    keys = _JOURNAL_PARAMETER_KEYS_BY_PATTERN.get(pattern, ())
    if endpoint in VIDEO_ENDPOINTS and pattern == "player_team_season":
        return (*keys, "context_measure")
    return keys


def _journal_params_payload(params_json: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(params_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _journal_param_value(params: dict[str, Any], key: str) -> str | None:
    value = params.get(key)
    if value is None or value == "":
        return None
    return str(value)


def _journal_param_int(params: dict[str, Any], key: str) -> int | None:
    value = _journal_param_value(params, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _journal_game_date_season_year(raw_value: str) -> int | None:
    date_value = raw_value.split("T", 1)[0].split(" ", 1)[0]
    pieces = date_value.split("-")
    if len(pieces) == 3 and len(pieces[0]) == 4:
        year_raw, month_raw = pieces[0], pieces[1]
    else:
        pieces = date_value.split("/")
        if len(pieces) != 3 or len(pieces[2]) != 4:
            return None
        month_raw, year_raw = pieces[0], pieces[2]
    try:
        year = int(year_raw)
        month = int(month_raw)
    except ValueError:
        return None
    if not 1 <= month <= 12:
        return None
    return year if month >= 7 else year - 1


def _journal_param_season_year(params: dict[str, Any]) -> int | None:
    season = _journal_param_value(params, "season")
    if season is not None:
        try:
            return int(season[:4])
        except ValueError:
            return None

    game_id = _journal_param_value(params, "game_id")
    if game_id is not None and len(game_id) >= 5 and game_id[3:5].isdigit():
        season_suffix = int(game_id[3:5])
        return 2000 + season_suffix if season_suffix <= 30 else 1900 + season_suffix

    game_date = _journal_param_value(params, "game_date")
    if game_date is not None:
        return _journal_game_date_season_year(game_date)
    return None


def _journal_param_season_type(params: dict[str, Any]) -> str | None:
    season_type = _journal_param_value(params, "season_type")
    if season_type is not None:
        return season_type
    game_id = _journal_param_value(params, "game_id")
    if game_id is None:
        return None
    return _GAME_ID_SEASON_TYPES.get(game_id[:3])


def _journal_params_cover_manifest_unit(
    params: dict[str, Any],
    *,
    endpoint: str,
    pattern: str,
    season_year: int | None,
    season_type: str | None,
    context_measure: str | None,
) -> bool:
    required_keys = _journal_required_keys(pattern, endpoint=endpoint)
    if any(_journal_param_value(params, key) is None for key in required_keys):
        return False
    if season_year is not None and _journal_param_season_year(params) != season_year:
        return False
    actual_season_type = _journal_param_season_type(params)
    if season_type is not None:
        if actual_season_type != season_type:
            return False
    elif (
        pattern in SEASON_TYPE_GROUPABLE_PATTERNS
        and _journal_param_value(params, "season_type") is not None
    ):
        return False
    if context_measure is not None:
        return _journal_param_value(params, "context_measure") == context_measure
    return (
        endpoint not in VIDEO_ENDPOINTS or _journal_param_value(params, "context_measure") is None
    )


def _journal_params_in_lane_scope(
    params: dict[str, Any],
    *,
    endpoint: str,
    lane: FullExtractionLane,
    pattern: str,
) -> bool:
    required_keys = _journal_required_keys(pattern, endpoint=endpoint)
    if any(_journal_param_value(params, key) is None for key in required_keys):
        return False

    if lane.season_start is not None and lane.season_end is not None:
        season_year = _journal_param_season_year(params)
        if season_year is None or not lane.season_start <= season_year <= lane.season_end:
            return False

    actual_season_type = _journal_param_season_type(params)
    if lane.season_types:
        if actual_season_type not in lane.season_types:
            return False
    elif (
        pattern in SEASON_TYPE_GROUPABLE_PATTERNS
        and _journal_param_value(params, "season_type") is not None
    ):
        return False
    if endpoint in VIDEO_ENDPOINTS and pattern == "player_team_season":
        return _journal_param_value(params, "context_measure") in _context_measures_for_endpoint(
            lane,
            endpoint=endpoint,
            pattern=pattern,
        )
    return True


def _journal_parameter_identity(
    params: dict[str, Any],
    *,
    endpoint: str,
    lane: FullExtractionLane,
    pattern: str,
) -> tuple[Any, ...] | None:
    if not _journal_params_in_lane_scope(
        params,
        endpoint=endpoint,
        lane=lane,
        pattern=pattern,
    ):
        return None

    season_type = _journal_param_season_type(params) if lane.season_types else ""
    if pattern == "game":
        return (
            _journal_param_season_year(params),
            season_type,
            _journal_param_value(params, "game_id"),
        )
    if pattern == "date":
        return (
            _journal_param_season_year(params),
            season_type,
            _journal_param_value(params, "game_date"),
        )
    if pattern == "player":
        return (_journal_param_value(params, "player_id"),)
    if pattern == "player_season":
        return (
            _journal_param_season_year(params),
            season_type,
            _journal_param_value(params, "player_id"),
        )
    if pattern == "team_season":
        return (
            _journal_param_season_year(params),
            season_type,
            _journal_param_value(params, "team_id"),
        )
    if pattern == "player_team_season":
        identity = (
            _journal_param_season_year(params),
            season_type,
            _journal_param_int(params, "player_id"),
            _journal_param_int(params, "team_id"),
        )
        if endpoint in VIDEO_ENDPOINTS:
            return (*identity, _journal_param_value(params, "context_measure"))
        return identity
    return None


def _journal_coverage_label(
    *,
    endpoint: str,
    pattern: str,
    season: int | None = None,
    season_type: str = "",
    context_measure: str = "",
    parameter_unit: tuple[Any, ...] | None = None,
) -> str:
    return json.dumps(
        {
            "endpoint": endpoint,
            "context_measure": context_measure,
            "parameter_unit": parameter_unit,
            "pattern": pattern,
            "season": season,
            "season_type": season_type,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _journal_missing_coverage_error(
    prefix: str,
    *,
    missing_count: int,
    samples: list[str],
) -> str:
    sample_payload = "|".join(samples)
    return f"{prefix}:{missing_count}:{sample_payload}"


def _workload_scope_contract(
    lane: FullExtractionLane,
    workload_store: PlayerTeamSeasonWorkloadStore | None,
) -> tuple[set[PlayerTeamSeasonWorkloadBaseUnit] | None, dict[str, Any], list[str]]:
    if "player_team_season" not in lane.patterns:
        return None, {}, []
    if set(lane.patterns) != {"player_team_season"}:
        return None, {}, ["workload_contract_mixed_patterns"]
    if lane.season_start is None or lane.season_end is None or not lane.season_types:
        return None, {}, ["workload_contract_scope_missing"]
    if workload_store is None:
        return None, {}, ["workload_contract_unavailable"]

    seasons = season_range(lane.season_start, lane.season_end)
    season_types = list(lane.season_types)
    try:
        scope = build_player_team_season_workload_scope(
            workload_store,
            seasons=seasons,
            season_types=season_types,
        )
    except ValueError as exc:
        return None, {}, [f"workload_contract_invalid:{exc}"]
    return set(scope.base_units), dict(scope.contract), []


def _current_journal_workload_identity_errors(
    lane: FullExtractionLane,
    parsed_rows: list[tuple[str, str, dict[str, Any]]],
    *,
    expected_workload_base_units: set[PlayerTeamSeasonWorkloadBaseUnit] | None,
) -> list[str]:
    if expected_workload_base_units is None or set(lane.patterns) != {"player_team_season"}:
        return []

    invalid_count = 0
    unexpected: set[PlayerTeamSeasonWorkloadBaseUnit] = set()
    for endpoint, _status, params in parsed_rows:
        if endpoint not in lane.endpoints:
            continue
        identity = player_team_season_workload_base_unit(params)
        if identity is None:
            invalid_count += 1
        elif identity not in expected_workload_base_units:
            unexpected.add(identity)

    errors: list[str] = []
    if invalid_count:
        errors.append(f"journal_invalid_workload_identities:{invalid_count}")
    if unexpected:
        samples = "|".join(json.dumps(identity) for identity in sorted(unexpected)[:10])
        errors.append(f"journal_unexpected_workload_identities:{len(unexpected)}:{samples}")
    return errors


def _current_journal_manifest_coverage_errors(
    lane: FullExtractionLane,
    parsed_rows: list[tuple[str, str, dict[str, Any]]],
    *,
    expected_workload_base_units: set[tuple[int, str, int, int]] | None = None,
    zero_workload_pairs: set[tuple[int, str]] | None = None,
) -> list[str]:
    """Require successful journal evidence for every manifest coverage unit."""
    done_params_by_endpoint: dict[str, list[dict[str, Any]]] = {}
    for endpoint, status, params in parsed_rows:
        if status == "done":
            done_params_by_endpoint.setdefault(endpoint, []).append(params)

    missing_count = 0
    samples: list[str] = []
    for coverage_unit in _coverage_units_for_lane(lane):
        endpoint = str(coverage_unit["endpoint"])
        pattern = str(coverage_unit["pattern"])
        season = coverage_unit["season"]
        season_type = str(coverage_unit["season_type"] or "")
        if (
            pattern == "player_team_season"
            and season is not None
            and (int(season), season_type) in (zero_workload_pairs or set())
        ):
            continue
        context_measure = str(coverage_unit["context_measure"] or "")
        if any(
            _journal_params_cover_manifest_unit(
                params,
                endpoint=endpoint,
                pattern=pattern,
                season_year=season,
                season_type=season_type or None,
                context_measure=context_measure or None,
            )
            for params in done_params_by_endpoint.get(endpoint, [])
        ):
            continue
        missing_count += 1
        if len(samples) < _JOURNAL_COVERAGE_ERROR_SAMPLE_LIMIT:
            samples.append(
                _journal_coverage_label(
                    endpoint=endpoint,
                    pattern=pattern,
                    season=season,
                    season_type=season_type,
                    context_measure=context_measure,
                )
            )

    if not missing_count:
        return []
    return [
        _journal_missing_coverage_error(
            "journal_missing_manifest_coverage",
            missing_count=missing_count,
            samples=samples,
        )
    ]


def _current_journal_parameter_coverage_errors(
    lane: FullExtractionLane,
    parsed_rows: list[tuple[str, str, dict[str, Any]]],
    *,
    expected_workload_base_units: set[tuple[int, str, int, int]] | None = None,
) -> list[str]:
    """Require every concrete discovery unit in the journal to be successful."""
    missing_count = 0
    samples: list[str] = []
    lane_rows = [row for row in parsed_rows if row[0] in lane.endpoints]

    for pattern in lane.patterns:
        if pattern not in _JOURNAL_PARAMETER_COVERAGE_PATTERNS:
            continue

        done_units_by_endpoint: dict[str, set[tuple[Any, ...]]] = {
            endpoint: set() for endpoint in lane.endpoints
        }
        for endpoint, status, params in lane_rows:
            if status != "done" or endpoint not in done_units_by_endpoint:
                continue
            identity = _journal_parameter_identity(
                params,
                endpoint=endpoint,
                lane=lane,
                pattern=pattern,
            )
            if identity is not None:
                done_units_by_endpoint[endpoint].add(identity)

        required_units: set[tuple[Any, ...]] = set()
        if pattern in {"player", "player_season", "team_season"}:
            id_key = "team_id" if pattern == "team_season" else "player_id"
            entity_ids = {
                value
                for _endpoint, _status, params in lane_rows
                if (value := _journal_param_value(params, id_key)) is not None
            }
            if pattern == "player":
                required_units = {(entity_id,) for entity_id in entity_ids}
            else:
                season_types = lane.season_types or ("",)
                if lane.season_start is not None and lane.season_end is not None:
                    required_units = {
                        (season, season_type, entity_id)
                        for season in range(lane.season_start, lane.season_end + 1)
                        for season_type in season_types
                        for entity_id in entity_ids
                    }
        elif pattern != "player_team_season":
            for endpoint, _status, params in lane_rows:
                identity = _journal_parameter_identity(
                    params,
                    endpoint=endpoint,
                    lane=lane,
                    pattern=pattern,
                )
                if identity is not None:
                    required_units.add(identity)

        for endpoint in lane.endpoints:
            endpoint_required_units = required_units
            if pattern == "player_team_season":
                base_units: set[tuple[Any, ...]] = (
                    set(expected_workload_base_units)
                    if expected_workload_base_units is not None
                    else {
                        (
                            _journal_param_season_year(params),
                            _journal_param_season_type(params) if lane.season_types else "",
                            _journal_param_int(params, "player_id"),
                            _journal_param_int(params, "team_id"),
                        )
                        for row_endpoint, _status, params in lane_rows
                        if _journal_params_in_lane_scope(
                            params,
                            endpoint=row_endpoint,
                            lane=lane,
                            pattern=pattern,
                        )
                    }
                )
                if endpoint in VIDEO_ENDPOINTS:
                    endpoint_required_units = {
                        (*base_unit, context_measure)
                        for base_unit in base_units
                        for context_measure in _context_measures_for_endpoint(
                            lane,
                            endpoint=endpoint,
                            pattern=pattern,
                        )
                    }
                else:
                    endpoint_required_units = base_units
            missing_units = endpoint_required_units - done_units_by_endpoint.get(endpoint, set())
            missing_count += len(missing_units)
            for parameter_unit in sorted(missing_units, key=str):
                if len(samples) >= _JOURNAL_COVERAGE_ERROR_SAMPLE_LIMIT:
                    break
                samples.append(
                    _journal_coverage_label(
                        endpoint=endpoint,
                        pattern=pattern,
                        parameter_unit=parameter_unit,
                    )
                )

    if not missing_count:
        return []
    return [
        _journal_missing_coverage_error(
            "journal_missing_parameter_coverage",
            missing_count=missing_count,
            samples=samples,
        )
    ]


def _legacy_journal_contract_errors(
    lane: FullExtractionLane,
    done_params_by_endpoint: dict[str, list[str]],
) -> list[str]:
    if lane.season_start is None or lane.season_end is None:
        return []

    errors: list[str] = []
    season_types: tuple[str | None, ...] = lane.season_types or (None,)
    for endpoint in lane.endpoints:
        params_values = [
            _journal_values(params_json)
            for params_json in done_params_by_endpoint.get(endpoint, [])
        ]
        for season_year in range(lane.season_start, lane.season_end + 1):
            season_tokens = _season_year_tokens(season_year)
            for season_type in season_types:
                if any(
                    bool(values & season_tokens) and (season_type is None or season_type in values)
                    for values in params_values
                ):
                    continue
                season_label = f"{season_year}-{str(season_year + 1)[-2:]}"
                suffix = f":{season_type}" if season_type is not None else ""
                errors.append(f"legacy_journal_contract_missing:{endpoint}:{season_label}{suffix}")
    return errors


def _lane_database_journal_errors(
    db_path: Path,
    lane: FullExtractionLane,
    *,
    require_complete_contract_evidence: bool,
    workload_store: PlayerTeamSeasonWorkloadStore | None = None,
) -> list[str]:
    expected_workload_base_units, workload_contract, workload_errors = (
        _workload_scope_contract(lane, workload_store)
        if require_complete_contract_evidence
        else (None, {}, [])
    )
    empty_workload_only = (
        not workload_errors
        and expected_workload_base_units == set()
        and set(lane.patterns) == {"player_team_season"}
    )
    zero_workload_pairs = {
        (int(str(pair["season"]).split("-", 1)[0]), str(pair["season_type"]))
        for pair in workload_contract.get("requested_pairs", [])
        if isinstance(pair, dict) and int(pair.get("row_count") or 0) == 0
    }
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        return [f"database_unreadable:{type(exc).__name__}"]

    try:
        columns = {
            str(row[0])
            for row in conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'main'
                  AND table_name = '_extraction_journal'
                """
            ).fetchall()
        }
        required_columns = {"endpoint", "params", "status"}
        if not required_columns <= columns:
            missing = ",".join(sorted(required_columns - columns))
            return [f"journal_missing_columns:{missing}"]
        rows = conn.execute("SELECT endpoint, params, status FROM _extraction_journal").fetchall()
    except Exception as exc:
        return [f"journal_unreadable:{type(exc).__name__}"]
    finally:
        conn.close()

    errors: list[str] = list(workload_errors)
    status_counts: dict[str, int] = {}
    done_params_by_endpoint: dict[str, list[str]] = {}
    parsed_rows: list[tuple[str, str, dict[str, Any]]] = []
    invalid_params_by_endpoint: dict[str, int] = {}
    for endpoint, params, status in rows:
        endpoint_name = str(endpoint)
        params_json = str(params or "")
        normalized_status = str(status or "")
        status_counts[normalized_status] = status_counts.get(normalized_status, 0) + 1
        if normalized_status == "done":
            done_params_by_endpoint.setdefault(endpoint_name, []).append(params_json)
        params_payload = _journal_params_payload(params_json)
        if params_payload is not None:
            parsed_rows.append((endpoint_name, normalized_status, params_payload))
        elif require_complete_contract_evidence and endpoint_name in lane.endpoints:
            invalid_params_by_endpoint[endpoint_name] = (
                invalid_params_by_endpoint.get(endpoint_name, 0) + 1
            )

    if not done_params_by_endpoint and not empty_workload_only:
        errors.append("journal_has_no_done_calls")
    for status, count in sorted(status_counts.items()):
        if status != "done" and count:
            errors.append(f"journal_nonterminal_status:{status or 'empty'}:{count}")
    missing_endpoints = (
        [] if empty_workload_only else sorted(set(lane.endpoints) - set(done_params_by_endpoint))
    )
    if missing_endpoints:
        errors.append("journal_missing_endpoints:" + ",".join(missing_endpoints))
    for endpoint, count in sorted(invalid_params_by_endpoint.items()):
        errors.append(f"journal_invalid_params_json:{endpoint}:{count}")
    if require_complete_contract_evidence:
        errors.extend(
            _current_journal_workload_identity_errors(
                lane,
                parsed_rows,
                expected_workload_base_units=expected_workload_base_units,
            )
        )
        errors.extend(
            _current_journal_manifest_coverage_errors(
                lane,
                parsed_rows,
                expected_workload_base_units=expected_workload_base_units,
                zero_workload_pairs=zero_workload_pairs,
            )
        )
        errors.extend(
            _current_journal_parameter_coverage_errors(
                lane,
                parsed_rows,
                expected_workload_base_units=expected_workload_base_units,
            )
        )
    else:
        errors.extend(_legacy_journal_contract_errors(lane, done_params_by_endpoint))
    return errors


def _validate_current_lane_artifact(
    *,
    lane: FullExtractionLane,
    metadata: dict[str, Any],
    metadata_path: Path,
    metadata_dir: Path,
    db_path: Path,
    artifacts_dir: Path,
    chain_id: str,
    source_sha: str,
    authorized_run_ids: set[str],
    workload_store: PlayerTeamSeasonWorkloadStore | None = None,
) -> list[str]:
    schema_version = _int_metadata_value(metadata.get("metadata_schema_version"))
    errors = _metadata_lane_contract_errors(metadata, lane, strict=True)
    if schema_version < 3:
        errors.append("metadata_schema_version_unsupported")
    if metadata_path.is_symlink() or not metadata_path.is_file():
        errors.append("lane_metadata_not_regular")
    if metadata_path.name != "lane-metadata.json":
        errors.append("lane_metadata_filename_mismatch")
    if db_path.is_symlink() or not db_path.is_file():
        errors.append("lane_database_not_regular")
    actual_database_sha256 = _file_sha256(db_path)
    expected_coverage_hash = _coverage_hash_for_lane(lane)
    expected_artifact_name = _lane_artifact_name(chain_id, lane.lane_id)
    expected_metadata_artifact_name = _lane_metadata_artifact_name(chain_id, lane.lane_id)
    normalized_source_sha = source_sha.strip().lower()

    if str(metadata.get("chain_id") or "") != chain_id:
        errors.append("metadata_chain_id_mismatch")
    if str(metadata.get("source_sha") or "").strip().lower() != normalized_source_sha:
        errors.append("metadata_source_sha_mismatch")
    metadata_coverage_hash = str(metadata.get("coverage_units_hash") or "").strip().lower()
    if metadata_coverage_hash != expected_coverage_hash:
        errors.append("metadata_coverage_units_hash_mismatch")

    metadata_database_sha256 = str(metadata.get("database_sha256") or "").strip().lower()
    if not _is_sha256(metadata_database_sha256):
        errors.append("metadata_database_sha256_missing_or_invalid")
    elif metadata_database_sha256 != actual_database_sha256:
        errors.append("metadata_database_sha256_mismatch")

    state_artifact = metadata.get("state_artifact")
    state_payload = state_artifact if isinstance(state_artifact, dict) else {}
    if not isinstance(state_artifact, dict):
        errors.append("metadata_state_artifact_missing")
    state_run_id = str(state_payload.get("run_id") or "").strip()
    state_name = str(state_payload.get("name") or "").strip()
    state_digest = str(state_payload.get("sha256") or "").strip().lower()
    state_artifact_id = str(state_payload.get("artifact_id") or "").strip()
    state_artifact_digest = str(state_payload.get("artifact_digest") or "").strip().lower()
    if state_payload.get("attested") is not True:
        errors.append("metadata_state_artifact_not_attested")
    if state_payload.get("uploaded") is not True:
        errors.append("metadata_state_artifact_not_uploaded")
    if not _is_positive_run_id(state_artifact_id):
        errors.append("metadata_state_artifact_id_invalid")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", state_artifact_digest) is None:
        errors.append("metadata_state_artifact_digest_invalid")
    if not _is_positive_run_id(state_run_id):
        errors.append("metadata_state_artifact_run_id_invalid")
    elif state_run_id not in authorized_run_ids:
        errors.append("metadata_state_artifact_run_id_unauthorized")
    if state_name != expected_artifact_name:
        errors.append("metadata_state_artifact_name_mismatch")
    if state_digest != actual_database_sha256:
        errors.append("metadata_state_artifact_sha256_mismatch")

    metadata_artifact_root = _artifact_root_for_provenance(
        path=metadata_path,
        root=metadata_dir,
        run_id=state_run_id,
        artifact_name=expected_metadata_artifact_name,
    )
    if metadata_artifact_root is None:
        errors.append("metadata_artifact_path_provenance_mismatch")
    database_artifact_root = _artifact_root_for_provenance(
        path=db_path,
        root=artifacts_dir,
        run_id=state_run_id,
        artifact_name=expected_artifact_name,
    )
    if database_artifact_root is None:
        errors.append("lane_database_path_provenance_mismatch")
    else:
        attestation, attestation_error = _read_lane_state_attestation(database_artifact_root)
        if attestation_error:
            errors.append(attestation_error)
        else:
            if attestation.get("schema_version") != 3:
                errors.append("lane_state_attestation_schema_version_mismatch")
            attested_fields = (
                ("chain_id", chain_id),
                ("source_sha", normalized_source_sha),
                ("lane_id", lane.lane_id),
                ("run_id", state_run_id),
                ("artifact_name", expected_artifact_name),
                ("coverage_units_hash", expected_coverage_hash),
                ("database_sha256", actual_database_sha256),
            )
            for field_name, expected in attested_fields:
                actual = str(attestation.get(field_name) or "").strip()
                if field_name in {
                    "source_sha",
                    "coverage_units_hash",
                    "database_sha256",
                }:
                    actual = actual.lower()
                if actual != expected:
                    errors.append(f"lane_state_attestation_{field_name}_mismatch")
            if attestation.get("attested") is not True:
                errors.append("lane_state_attestation_not_attested")

    _expected_units, expected_workload_contract, workload_errors = _workload_scope_contract(
        lane, workload_store
    )
    if not workload_errors and expected_workload_contract:
        metadata_workload_contract = metadata.get("workload_contract")
        if metadata_workload_contract != expected_workload_contract:
            errors.append("metadata_workload_contract_mismatch")

    errors.extend(
        _lane_database_journal_errors(
            db_path,
            lane,
            require_complete_contract_evidence=True,
            workload_store=workload_store,
        )
    )
    return errors


def _metadata_contract_blocked_lane_ids(
    metadata: dict[str, dict[str, Any]],
    lanes_by_id: dict[str, FullExtractionLane],
) -> set[str]:
    return {
        lane_id
        for lane_id, payload in metadata.items()
        if str(lane_outcome_from_metadata(payload, lanes_by_id.get(lane_id))) == "contract_blocked"
    }


def _artifact_ancestor_components(
    *,
    db_path: Path,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    try:
        relative_parent = db_path.parent.relative_to(artifacts_dir)
    except ValueError:
        return ()
    return (artifacts_dir.name, *relative_parent.parts)


def _artifact_lane_id_for_database(
    *,
    db_path: Path,
    artifacts_dir: Path,
    ordered_lane_ids: list[str],
) -> str | None:
    matches: set[str] = set()
    for component in reversed(
        _artifact_ancestor_components(db_path=db_path, artifacts_dir=artifacts_dir)
    ):
        for lane_id in ordered_lane_ids:
            if component == lane_id or (
                component.startswith("extraction-lane-") and component.endswith(f"-{lane_id}")
            ):
                matches.add(lane_id)
    return next(iter(matches)) if len(matches) == 1 else None


def _lane_artifact_database_paths(
    *,
    artifacts_dir: Path,
    lane_ids: set[str],
) -> tuple[list[Path], set[str]]:
    if not lane_ids or not artifacts_dir.exists():
        return [], set()
    matched_paths: list[Path] = []
    matched_lane_ids: set[str] = set()
    ordered_lane_ids = sorted(lane_ids, key=lambda lane_id: len(lane_id), reverse=True)
    for db_path in sorted(artifacts_dir.rglob("nba.duckdb")):
        lane_id = _artifact_lane_id_for_database(
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            ordered_lane_ids=ordered_lane_ids,
        )
        if lane_id is not None and lane_id not in matched_lane_ids:
            matched_paths.append(db_path)
            matched_lane_ids.add(lane_id)
    return matched_paths, matched_lane_ids


def _attested_current_lane_artifacts(
    *,
    artifacts_dir: Path,
    metadata_dir: Path,
    complete_lane_ids: set[str],
    metadata: dict[str, dict[str, Any]],
    metadata_records: dict[str, list[tuple[Path, dict[str, Any]]]],
    lanes_by_id: dict[str, FullExtractionLane],
    chain_id: str,
    source_sha: str,
    authorized_run_ids: set[str],
    workload_store: PlayerTeamSeasonWorkloadStore | None = None,
) -> tuple[list[Path], set[str], dict[str, list[str]], set[str]]:
    failures: dict[str, list[str]] = {}
    if not complete_lane_ids:
        return [], set(), failures, set()

    candidates: dict[str, list[Path]] = {lane_id: [] for lane_id in complete_lane_ids}
    if artifacts_dir.exists():
        for db_path in sorted(artifacts_dir.rglob("nba.duckdb")):
            ancestor_components = set(
                _artifact_ancestor_components(
                    db_path=db_path,
                    artifacts_dir=artifacts_dir,
                )
            )
            for lane_id in complete_lane_ids:
                if _lane_artifact_name(chain_id, lane_id) in ancestor_components:
                    candidates[lane_id].append(db_path)

    attested_paths: list[Path] = []
    attested_lane_ids: set[str] = set()
    attested_run_ids: set[str] = set()
    for lane_id in sorted(complete_lane_ids):
        lane = lanes_by_id.get(lane_id)
        if lane is None:
            failures[lane_id] = ["lane_not_in_manifest"]
            continue
        lane_metadata_records = metadata_records.get(lane_id, [])
        if len(lane_metadata_records) != 1:
            failures[lane_id] = [f"lane_metadata_ambiguous:{len(lane_metadata_records)}"]
            continue
        metadata_path, lane_metadata = lane_metadata_records[0]
        if lane_metadata is not metadata[lane_id]:
            failures[lane_id] = ["lane_metadata_selection_mismatch"]
            continue
        lane_candidates = candidates.get(lane_id, [])
        if not lane_candidates:
            failures[lane_id] = ["lane_database_missing"]
            continue
        if len(lane_candidates) != 1:
            failures[lane_id] = [f"lane_database_ambiguous:{len(lane_candidates)}"]
            continue
        db_path = lane_candidates[0]
        errors = _validate_current_lane_artifact(
            lane=lane,
            metadata=lane_metadata,
            metadata_path=metadata_path,
            metadata_dir=metadata_dir,
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            chain_id=chain_id,
            source_sha=source_sha,
            authorized_run_ids=authorized_run_ids,
            workload_store=workload_store,
        )
        if errors:
            failures[lane_id] = errors
            continue
        attested_paths.append(db_path)
        attested_lane_ids.add(lane_id)
        state_artifact = lane_metadata["state_artifact"]
        attested_run_ids.add(str(state_artifact["run_id"]))
    return attested_paths, attested_lane_ids, failures, attested_run_ids


def _legacy_cross_product_spans(lane_ids: set[str]) -> set[tuple[str, int, int]]:
    spans: set[tuple[str, int, int]] = set()
    prefix = "cross-product-"
    for lane_id in lane_ids:
        if not lane_id.startswith(prefix):
            continue
        pieces = lane_id[len(prefix) :].rsplit("-", 2)
        if len(pieces) != 3:
            continue
        season_slug, raw_start, raw_end = pieces
        if not raw_start.isdigit() or not raw_end.isdigit():
            continue
        spans.add((season_slug, int(raw_start), int(raw_end)))
    return spans


def _legacy_historical_spans(lane_ids: set[str]) -> set[tuple[str, str, int, int]]:
    spans: set[tuple[str, str, int, int]] = set()
    prefix = "historical-"
    pattern_aliases = {
        pattern: {pattern, _lane_slug(pattern)}
        for pattern in HISTORICAL_ENDPOINT_ISOLATION_PATTERNS
    }
    for lane_id in lane_ids:
        if not lane_id.startswith(prefix):
            continue
        pieces = lane_id[len(prefix) :].rsplit("-", 2)
        if len(pieces) != 3:
            continue
        body, raw_start, raw_end = pieces
        if not raw_start.isdigit() or not raw_end.isdigit():
            continue
        for pattern, aliases in pattern_aliases.items():
            for alias in aliases:
                marker = f"{alias}-"
                if not body.startswith(marker):
                    continue
                season_slug = body[len(marker) :]
                if season_slug:
                    spans.add((pattern, season_slug, int(raw_start), int(raw_end)))
    return spans


def _season_year_tokens(season_year: int) -> set[str]:
    return {str(season_year), f"{season_year}-{str(season_year + 1)[-2:]}"}


def _journal_params_match_season(params_json: str, season_year: int) -> bool:
    payload = _journal_params_payload(params_json)
    if payload is None:
        return any(token in params_json for token in _season_year_tokens(season_year))

    if _journal_param_season_year(payload) == season_year:
        return True

    tokens = _season_year_tokens(season_year)
    stack: list[Any] = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif str(value) in tokens:
            return True
    return False


def _previous_checkpoint_has_lane_evidence(
    previous_db_path: Path | None,
    lane: FullExtractionLane,
) -> bool:
    if (
        previous_db_path is None
        or lane.season_start is None
        or lane.season_end is None
        or not lane.endpoints
    ):
        return False

    conn = duckdb.connect(str(previous_db_path), read_only=True)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        if "_extraction_journal" not in tables:
            return False
        rows = conn.execute(
            """
            SELECT endpoint, params
            FROM _extraction_journal
            WHERE status = 'done'
            """
        ).fetchall()
    finally:
        conn.close()

    params_by_endpoint: dict[str, list[str]] = {}
    for endpoint, params in rows:
        params_by_endpoint.setdefault(str(endpoint), []).append(str(params))

    for endpoint in lane.endpoints:
        endpoint_params = params_by_endpoint.get(endpoint, [])
        if not endpoint_params:
            return False
        for season_year in range(lane.season_start, lane.season_end + 1):
            if not any(
                _journal_params_match_season(params_json, season_year)
                for params_json in endpoint_params
            ):
                return False
    return True


def _compatible_previous_checkpoint_lane_ids(
    lanes: list[FullExtractionLane],
    *,
    previous_included_lane_ids: set[str],
    previous_db_path: Path | None,
) -> set[str]:
    """Map pre-endpoint-isolation checkpoint lanes to current isolated lanes."""
    legacy_spans = _legacy_cross_product_spans(previous_included_lane_ids)
    legacy_historical_spans = _legacy_historical_spans(previous_included_lane_ids)
    if previous_db_path is None or (not legacy_spans and not legacy_historical_spans):
        return set()

    compatible: set[str] = set()
    for lane in lanes:
        if lane.season_start is None or lane.season_end is None:
            continue
        if (
            lane.lane_kind == "historical"
            and len(lane.patterns) == 1
            and lane.patterns[0] in HISTORICAL_ENDPOINT_ISOLATION_PATTERNS
        ):
            season_slug = _season_type_slug(lane.season_types)
            for (
                legacy_pattern,
                legacy_season_slug,
                legacy_start,
                legacy_end,
            ) in legacy_historical_spans:
                if legacy_pattern != lane.patterns[0] or legacy_season_slug != season_slug:
                    continue
                if legacy_start <= lane.season_start and lane.season_end <= legacy_end:
                    if _previous_checkpoint_has_lane_evidence(previous_db_path, lane):
                        compatible.add(lane.lane_id)
                    break
            continue
        if lane.lane_kind == "cross_product":
            season_slug = _season_type_slug(lane.season_types)
            for legacy_season_slug, legacy_start, legacy_end in legacy_spans:
                if legacy_season_slug != season_slug:
                    continue
                if legacy_start <= lane.season_start and lane.season_end <= legacy_end:
                    if _previous_checkpoint_has_lane_evidence(previous_db_path, lane):
                        compatible.add(lane.lane_id)
                    break
    return compatible


def build_checkpoint_database(
    *,
    manifest_path: Path,
    metadata_dir: Path,
    lane_artifacts_dir: Path,
    output_dir: Path,
    report_path: Path,
    previous_checkpoint_dir: Path | None = None,
    previous_checkpoint_report_path: Path | None = None,
    workload_duckdb_path: Path | None = None,
    chain_id: str = "",
    run_id: str = "",
    source_sha: str = "",
) -> dict[str, Any]:
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    trusted_manifest = _validate_checkpoint_trust_root(
        raw_manifest,
        chain_id=chain_id,
        source_sha=source_sha,
        run_id=run_id,
    )
    normalized_source_sha = source_sha.strip().lower()
    manifest = normalize_manifest(trusted_manifest)
    lanes = list(manifest.lanes)
    _validate_unique_lane_ids(lanes)
    lanes_by_id = {lane.lane_id: lane for lane in lanes}
    committed_contract_blocked_rows, _committed_contract_blocked_digest = (
        _validated_chain_state_contract_blocked_evidence(manifest.chain_state)
    )
    committed_contract_blocked_lane_ids = {
        str(row["lane_id"]) for row in committed_contract_blocked_rows
    }
    duplicate_accounted_lane_ids = sorted(set(lanes_by_id) & committed_contract_blocked_lane_ids)
    if duplicate_accounted_lane_ids:
        raise ValueError(
            "Checkpoint manifest lanes overlap committed contract-blocked evidence: "
            + ", ".join(duplicate_accounted_lane_ids)
        )
    latest_pointer = _checkpoint_pointer(
        manifest.chain_state,
        prefix="latest",
        chain_id=chain_id,
    )
    if latest_pointer is None:
        raise ValueError("Checkpoint manifest is missing its latest checkpoint pointer")
    if latest_pointer.run_id != run_id:
        raise ValueError("Latest checkpoint pointer run ID does not match checkpoint run_id")
    previous_pointer = _checkpoint_pointer(
        manifest.chain_state,
        prefix="previous",
        chain_id=chain_id,
    )
    expected_previous_generation = previous_pointer.generation if previous_pointer else 0
    if latest_pointer.generation != expected_previous_generation + 1:
        raise ValueError("Checkpoint pointer generations are not contiguous")
    previous_inputs = (
        previous_checkpoint_dir is not None,
        previous_checkpoint_report_path is not None,
    )
    if any(previous_inputs) and not all(previous_inputs):
        raise ValueError("Previous checkpoint directory and report path must be provided together")
    if bool(previous_pointer) != all(previous_inputs):
        raise ValueError(
            "Previous checkpoint inputs must exactly match the manifest previous pointer"
        )
    authorized_run_ids = {*manifest.chain_state.artifact_run_ids, run_id}
    invalid_authorized_run_ids = sorted(
        value for value in authorized_run_ids if not _is_positive_run_id(value)
    )
    if invalid_authorized_run_ids:
        raise ValueError(
            "Checkpoint manifest has invalid artifact run IDs: "
            + ", ".join(invalid_authorized_run_ids)
        )
    requires_workload_contract = any("player_team_season" in lane.patterns for lane in lanes)
    workload_store = (
        PlayerTeamSeasonWorkloadStore.from_duckdb_path(workload_duckdb_path)
        if workload_duckdb_path is not None
        else None
    )
    workload_integrity = (
        workload_store.integrity_attestation() if workload_store is not None else None
    )
    workload_contract_errors = (
        ["workload_contract_integrity_unavailable"]
        if requires_workload_contract and workload_integrity is None
        else []
    )
    previous_report: dict[str, Any] = {}
    previous_db_path: Path | None = None
    previous_included_lane_ids: set[str] = set()
    previous_run_ids: list[str] = []
    previous_coverage_hashes: dict[str, str] = {}
    if previous_pointer is not None:
        previous_db_path = _single_database_path(
            previous_checkpoint_dir,
            label="Previous checkpoint artifact",
        )
        previous_report = _read_json_file(previous_checkpoint_report_path)
        _validate_contract_blocked_evidence_commitment(
            previous_report,
            manifest.chain_state,
            pointer_prefix="previous",
        )
        (
            previous_included_lane_ids,
            previous_run_ids,
            previous_coverage_hashes,
        ) = _validate_previous_checkpoint_report(
            previous_db_path=previous_db_path,
            previous_report_path=previous_checkpoint_report_path,
            previous_report=previous_report,
            lanes_by_id=lanes_by_id,
            pointer=previous_pointer,
            chain_id=chain_id,
            source_sha=normalized_source_sha,
            expected_workload_store=(workload_store if requires_workload_contract else None),
        )
    metadata_records = _metadata_records_by_lane(metadata_dir)
    metadata = {lane_id: lane_records[-1][1] for lane_id, lane_records in metadata_records.items()}
    complete_current_lane_ids = _metadata_complete_lane_ids(metadata)
    contract_blocked_lane_ids = _metadata_contract_blocked_lane_ids(metadata, lanes_by_id)
    accounted_contract_blocked_lane_ids = (
        committed_contract_blocked_lane_ids | contract_blocked_lane_ids
    )
    (
        current_db_paths,
        current_included_lane_ids,
        current_lane_attestation_failures,
        current_artifact_run_ids,
    ) = _attested_current_lane_artifacts(
        artifacts_dir=lane_artifacts_dir,
        metadata_dir=metadata_dir,
        complete_lane_ids=complete_current_lane_ids,
        metadata=metadata,
        metadata_records=metadata_records,
        lanes_by_id=lanes_by_id,
        chain_id=chain_id,
        source_sha=normalized_source_sha,
        authorized_run_ids=authorized_run_ids,
        workload_store=workload_store,
    )
    skipped_complete_lane_ids = sorted(complete_current_lane_ids - current_included_lane_ids)
    compatible_previous_lane_ids = _compatible_previous_checkpoint_lane_ids(
        lanes,
        previous_included_lane_ids=previous_included_lane_ids,
        previous_db_path=previous_db_path,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    if current_db_paths or previous_db_path is not None:
        merge_summary = _merge_database_paths(
            db_paths=current_db_paths,
            output_dir=output_dir,
            base_database_path=previous_db_path,
        )
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

    included_lane_ids = (
        previous_included_lane_ids | compatible_previous_lane_ids | current_included_lane_ids
    )
    effective_included_lane_ids = set(lanes_by_id) & included_lane_ids
    non_contract_lane_ids = set(lanes_by_id) - contract_blocked_lane_ids
    missing_lane_ids = sorted(non_contract_lane_ids - effective_included_lane_ids)
    included_lanes = [lane for lane in lanes if lane.lane_id in effective_included_lane_ids]
    coverage_fingerprint = _coverage_fingerprint(included_lanes)
    included_lane_coverage_hashes = {
        **previous_coverage_hashes,
        **_checkpoint_lane_coverage_hashes(lanes_by_id, effective_included_lane_ids),
    }
    included_lane_workload_contracts, included_workload_contract_errors = (
        _checkpoint_lane_workload_contracts(
            lanes_by_id,
            effective_included_lane_ids,
            workload_store,
        )
    )
    workload_contract_errors.extend(included_workload_contract_errors)
    checkpoint_generation = latest_pointer.generation
    included_run_ids = list(
        dict.fromkeys([*previous_run_ids, *sorted(current_artifact_run_ids), run_id])
    )
    database_sha256 = _file_sha256(Path(output_path)) if output_path else ""
    manifest_lane_count = len(lanes) + len(committed_contract_blocked_lane_ids)
    complete_lane_count = len(effective_included_lane_ids)
    contract_blocked_lane_count = len(accounted_contract_blocked_lane_ids)
    if coverage_fingerprint != latest_pointer.coverage_hash:
        raise ValueError(
            "Latest checkpoint pointer coverage hash does not match the built checkpoint"
        )
    report = {
        "chain_id": chain_id,
        "run_id": run_id,
        "artifact_name": latest_pointer.artifact_name,
        "source_sha": normalized_source_sha,
        "chunk_profile": _manifest_chunk_profile(lanes),
        "checkpoint_generation": checkpoint_generation,
        "previous_checkpoint_generation": expected_previous_generation,
        "included_lane_ids": sorted(included_lane_ids),
        "included_lane_coverage_hashes": included_lane_coverage_hashes,
        "included_lane_workload_contracts": included_lane_workload_contracts,
        "compatible_previous_lane_ids": sorted(compatible_previous_lane_ids),
        "included_run_ids": included_run_ids,
        "manifest_lane_count": manifest_lane_count,
        "complete_lane_count": complete_lane_count,
        "contract_blocked_lane_count": contract_blocked_lane_count,
        "active_lane_count": len(missing_lane_ids),
        "skipped_lane_count": len(skipped_complete_lane_ids),
        "missing_lane_ids": missing_lane_ids,
        "skipped_complete_lane_ids": skipped_complete_lane_ids,
        "attested_current_lane_ids": sorted(current_included_lane_ids),
        "current_lane_attestation_failures": current_lane_attestation_failures,
        "coverage_fingerprint": coverage_fingerprint,
        "table_row_counts": table_row_counts,
        "journal_row_count": journal_row_count,
        "merge_mode": merge_mode,
        "merge_summary": merge_summary,
        "output_path": output_path,
        "database_sha256": database_sha256,
        "workload_integrity": workload_integrity,
        "workload_contract_errors": workload_contract_errors,
        "terminal_ready": (
            not missing_lane_ids
            and bool(effective_included_lane_ids)
            and bool(database_sha256)
            and set(effective_included_lane_ids) <= set(included_lane_coverage_hashes)
            and not workload_contract_errors
            and manifest_lane_count == complete_lane_count + contract_blocked_lane_count
        ),
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
    allow_artifact_fallback: bool = False,
) -> dict[str, Any]:
    fallback_reason = ""
    checkpoint_report = _read_json_file(checkpoint_report_path)
    checkpoint_db_path = _first_database_path(checkpoint_dir)
    if checkpoint_report and checkpoint_db_path is not None:
        if checkpoint_report.get("terminal_ready") is True:
            reported_database_sha256 = str(checkpoint_report.get("database_sha256") or "").strip()
            actual_database_sha256 = _file_sha256(checkpoint_db_path)
            if reported_database_sha256 != actual_database_sha256:
                fallback_reason = (
                    "checkpoint database digest mismatch: "
                    f"expected {reported_database_sha256 or 'missing'}, "
                    f"got {actual_database_sha256}"
                )
            elif manifest_path is not None and manifest_path.exists():
                manifest = normalize_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
                _validate_unique_lane_ids(list(manifest.lanes))
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

    checkpoint_requested = checkpoint_report_path is not None or checkpoint_dir is not None
    if not allow_artifact_fallback and checkpoint_requested:
        msg = f"Terminal checkpoint validation failed: {fallback_reason}"
        raise RuntimeError(msg)
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
            max_matrix_lanes=args.max_matrix_lanes,
        )
        chain_state = FullExtractionChainState()
    else:
        lanes = _schedule_lanes(
            list(manifest.lanes),
            chunk_profile=args.chunk_profile or _manifest_chunk_profile(manifest.lanes),
            max_matrix_lanes=args.max_matrix_lanes,
            rotation_cursor=manifest.chain_state.scheduler_rotation_cursor,
        )
        chain_state = manifest.chain_state

    validate_manifest(lanes)
    payload = manifest_payload(
        lanes,
        chain_state=chain_state,
        max_matrix_lanes=args.max_matrix_lanes,
        current_iteration=args.iteration,
    )
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
        allow_pipeline_failures=args.allow_pipeline_failures,
        completed_artifact_run_id=args.completed_artifact_run_id,
        chunk_profile=args.chunk_profile,
        latest_checkpoint_run_id=args.latest_checkpoint_run_id,
        latest_checkpoint_artifact_name=args.latest_checkpoint_artifact_name,
        latest_checkpoint_generation=args.latest_checkpoint_generation,
        latest_checkpoint_coverage_hash=args.latest_checkpoint_coverage_hash,
        current_iteration=args.iteration,
        max_matrix_lanes=args.max_matrix_lanes,
    )
    validate_manifest(next_lanes)
    payload = manifest_payload(
        next_lanes,
        chain_state=next_chain_state,
        max_matrix_lanes=args.max_matrix_lanes,
        current_iteration=args.iteration,
    )
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
        allow_artifact_fallback=args.allow_artifact_fallback,
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
        workload_duckdb_path=args.workload_duckdb_path,
        chain_id=args.chain_id,
        run_id=args.run_id,
        source_sha=args.source_sha,
    )
    print(json.dumps(summary))
    return 0


def _command_verify_checkpoint(args: argparse.Namespace) -> int:
    summary = validate_checkpoint_artifact(
        manifest_path=args.lane_manifest_path,
        checkpoint_dir=args.checkpoint_dir,
        checkpoint_report_path=args.checkpoint_report_path,
        chain_id=args.chain_id,
        source_sha=args.source_sha,
        pointer_prefix=args.pointer_prefix,
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
    plan.add_argument("--max-matrix-lanes", type=int, default=MAX_GITHUB_MATRIX_LANES)
    plan.add_argument("--iteration", type=int, default=1)
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
    resume.add_argument("--allow-pipeline-failures", action="store_true")
    resume.add_argument("--max-matrix-lanes", type=int, default=MAX_GITHUB_MATRIX_LANES)
    resume.add_argument("--iteration", type=int, default=1)
    resume.add_argument("--output-path", type=Path, required=True)
    resume.set_defaults(func=_command_resume)

    checkpoint = subparsers.add_parser("checkpoint", help="Build a cumulative checkpoint DB.")
    checkpoint.add_argument("--lane-manifest-path", type=Path, required=True)
    checkpoint.add_argument("--metadata-dir", type=Path, required=True)
    checkpoint.add_argument("--artifacts-dir", type=Path, required=True)
    checkpoint.add_argument("--previous-checkpoint-dir", type=Path, default=None)
    checkpoint.add_argument("--previous-checkpoint-report-path", type=Path, default=None)
    checkpoint.add_argument("--workload-duckdb-path", type=Path, default=None)
    checkpoint.add_argument("--output-dir", type=Path, required=True)
    checkpoint.add_argument("--report-path", type=Path, required=True)
    checkpoint.add_argument("--chain-id", type=str, required=True)
    checkpoint.add_argument("--run-id", type=str, required=True)
    checkpoint.add_argument("--source-sha", type=str, required=True)
    checkpoint.set_defaults(func=_command_checkpoint)

    verify_checkpoint = subparsers.add_parser(
        "verify-checkpoint",
        help="Validate checkpoint provenance before trusting its lane inventory.",
    )
    verify_checkpoint.add_argument("--lane-manifest-path", type=Path, required=True)
    verify_checkpoint.add_argument("--checkpoint-dir", type=Path, required=True)
    verify_checkpoint.add_argument("--checkpoint-report-path", type=Path, required=True)
    verify_checkpoint.add_argument("--chain-id", type=str, required=True)
    verify_checkpoint.add_argument("--source-sha", type=str, required=True)
    verify_checkpoint.add_argument(
        "--pointer-prefix",
        choices=("latest", "previous"),
        default="latest",
    )
    verify_checkpoint.set_defaults(func=_command_verify_checkpoint)

    merge = subparsers.add_parser("merge", help="Merge lane DuckDB artifacts.")
    merge.add_argument("--artifacts-dir", type=Path, required=True)
    merge.add_argument("--output-dir", type=Path, required=True)
    merge.add_argument("--manifest-path", type=Path, default=None)
    merge.add_argument("--checkpoint-dir", type=Path, default=None)
    merge.add_argument("--checkpoint-report-path", type=Path, default=None)
    merge.add_argument("--allow-artifact-fallback", action="store_true")
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
