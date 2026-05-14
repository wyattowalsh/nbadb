from __future__ import annotations

import argparse
import json
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import duckdb

from nbadb.core.types import SeasonType
from nbadb.orchestrate.extraction_contract import FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT
from nbadb.orchestrate.seasons import season_range
from nbadb.orchestrate.workload_profile import (
    WorkloadPlanningSnapshot,
    build_workload_planning_snapshot,
    endpoint_cost,
    preferred_max_span,
)

DEFAULT_HISTORICAL_START = 1946
MAX_CONSECUTIVE_FAILURES = 3
SEASON_TYPE_PATTERNS = frozenset({"season", "player_season", "team_season"})
HISTORICAL_PATTERNS = frozenset({"season", "game", "date", "player_season", "team_season"})
REFERENCE_PATTERNS = frozenset({"static", "player", "team"})
REFERENCE_PATTERN_ORDER = ("static", "team", "player")
CROSS_PRODUCT_PATTERNS = frozenset({"player_team_season"})
SEASON_TYPE_GROUPABLE_PATTERNS = SEASON_TYPE_PATTERNS | CROSS_PRODUCT_PATTERNS
DEFAULT_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)
HISTORICAL_MAX_SPAN_BY_PATTERN: dict[str, int] = {
    "game": 12,
    "date": 12,
    "season": 18,
    "player_season": 16,
    "team_season": 16,
}
CROSS_PRODUCT_MAX_SPAN = 8
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
    "common_player_info": 4_200,
    "player_profile_v2": 5_400,
    "player_awards": 4_200,
    "player_career_stats": 4_800,
    "player_compare": 4_800,
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
        }


@dataclass(frozen=True, slots=True)
class FullExtractionChainState:
    vpn_quarantined_servers: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {"vpn_quarantined_servers": list(self.vpn_quarantined_servers)}


@dataclass(frozen=True, slots=True)
class FullExtractionManifest:
    lanes: tuple[FullExtractionLane, ...]
    chain_state: FullExtractionChainState = field(default_factory=FullExtractionChainState)


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


def _normalize_chain_state(raw_chain_state: Any) -> FullExtractionChainState:
    if raw_chain_state is None or raw_chain_state == "":
        return FullExtractionChainState()
    if not isinstance(raw_chain_state, dict):
        msg = "Expected chain_state to be an object"
        raise ValueError(msg)
    return FullExtractionChainState(
        vpn_quarantined_servers=_normalize_server_list(
            raw_chain_state.get("vpn_quarantined_servers", [])
        )
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
    if lane.lane_kind == "historical" and lane.patterns:
        return _max_span_for_pattern(lane.patterns[0])
    if lane.lane_kind in {"cross_product", "cross_product_blocked"}:
        return CROSS_PRODUCT_MAX_SPAN
    return None


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
        if not lane.resume_only and not lane.use_vpn:
            errors.append(f"{lane.lane_id}: active lanes must require VPN")
        max_span = _max_span_for_lane(lane)
        span = _season_span(lane.season_start, lane.season_end)
        if max_span is not None and span > max_span:
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

    return FullExtractionLane(
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
    )


def build_default_manifest(
    *,
    support_matrix_rows: list[dict[str, Any]],
    selected_patterns: list[str] | None = None,
    selected_endpoints: list[str] | None = None,
    planning_snapshot: WorkloadPlanningSnapshot | None = None,
) -> list[FullExtractionLane]:
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
                lanes.append(
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
                    )
                )
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
                endpoints = _endpoint_names(grouped_rows)
                adaptive_max_span = (
                    preferred_max_span(planning_snapshot.endpoint_profiles, endpoints)
                    if planning_snapshot is not None
                    else None
                )
                season_cost = endpoint_cost(
                    planning_snapshot.endpoint_profiles if planning_snapshot is not None else None,
                    endpoints,
                )
                target_cost = max(float(_max_span_for_pattern(pattern)), season_cost * 3.0)
                for start, end in _season_bands(grouped_rows, {pattern}):
                    season_costs = {year: season_cost for year in range(start, end + 1)}
                    for band_start, band_end in (
                        _adaptive_split_season_band(
                            start,
                            end,
                            max_span=min(
                                _max_span_for_pattern(pattern),
                                adaptive_max_span or _max_span_for_pattern(pattern),
                            ),
                            target_cost=target_cost,
                            season_costs=season_costs,
                        )
                        if planning_snapshot is not None
                        else _split_season_band(
                            start,
                            end,
                            max_span=_max_span_for_pattern(pattern),
                        )
                    ):
                        lane_id = (
                            f"historical-{pattern}-{_season_type_slug(season_types)}-"
                            f"{band_start}-{band_end}"
                        )
                        lane_name = f"Historical {pattern} {band_start}-{band_end}"
                        if season_types:
                            lane_name = f"{lane_name} ({', '.join(season_types)})"
                        lanes.append(
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
                            )
                        )
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
            for band_start, band_end in (
                _adaptive_split_season_band(
                    DEFAULT_HISTORICAL_START,
                    end_year,
                    max_span=CROSS_PRODUCT_MAX_SPAN,
                    target_cost=max(6.0, CROSS_PRODUCT_MAX_SPAN * 1.5),
                    season_costs=cross_product_costs,
                )
                if planning_snapshot is not None
                else _split_season_band(
                    DEFAULT_HISTORICAL_START,
                    end_year,
                    max_span=CROSS_PRODUCT_MAX_SPAN,
                )
            ):
                lanes.append(
                    FullExtractionLane(
                        lane_id=f"cross-product-{_season_type_slug(season_types)}-{band_start}-{band_end}",
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
                        timeout_seconds=_cross_product_timeout_seconds(band_start, band_end),
                    )
                )
                lane_index += 1

    if not lanes:
        msg = "Selected full-extraction filters produced no runnable lanes"
        raise ValueError(msg)

    return lanes


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
    return FullExtractionManifest(lanes=lanes, chain_state=chain_state)


def manifest_payload(
    lanes: list[FullExtractionLane],
    *,
    chain_state: FullExtractionChainState | None = None,
) -> dict[str, Any]:
    lane_dicts = [_lane_payload(lane) for lane in lanes]
    return {
        "manifest_version": 2,
        "lane_count": len(lanes),
        "lanes": lane_dicts,
        "chain_state": (chain_state or FullExtractionChainState()).to_payload(),
        "github_matrix": {"include": [lane.to_workflow_dict() for lane in lanes]},
    }


def _lane_payload(lane: FullExtractionLane, *, compact: bool = False) -> dict[str, Any]:
    payload = asdict(lane)
    if compact:
        # Redispatch payloads only need enough state to reconstruct lanes on the
        # next workflow iteration. Drop derived/default fields so chained
        # workflow_dispatch inputs stay under GitHub's size limits.
        payload.pop("lane_index", None)
        if lane.use_vpn is True:
            payload.pop("use_vpn", None)
        if not lane.failure_streak:
            payload.pop("failure_streak", None)
        if not lane.last_failure_reason:
            payload.pop("last_failure_reason", None)
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


def _load_manifest_argument(
    raw_json: str | None, path: Path | None
) -> FullExtractionManifest | None:
    if raw_json:
        return normalize_manifest(json.loads(raw_json))
    if path is not None:
        return normalize_manifest(json.loads(path.read_text(encoding="utf-8")))
    return None


def _metadata_by_lane(metadata_dir: Path) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for candidate in sorted(metadata_dir.rglob("*.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
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


def build_resume_manifest(
    lanes: list[FullExtractionLane],
    metadata_dir: Path,
    *,
    chain_state: FullExtractionChainState | None = None,
) -> tuple[list[FullExtractionLane], FullExtractionChainState, dict[str, Any]]:
    metadata = _metadata_by_lane(metadata_dir)
    next_lanes: list[FullExtractionLane] = []
    resumed = 0
    active = 0
    failure_reason_counts: dict[str, int] = {}
    blocked_lanes: list[FullExtractionLane] = []

    for lane in lanes:
        payload = metadata.get(lane.lane_id)
        status = str(payload.get("status", "")) if payload else ""
        if not status:
            status = "missing-metadata"
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
        failure_reason_counts[status] = failure_reason_counts.get(status, 0) + 1
        failure_streak = lane.failure_streak + 1 if lane.last_failure_reason == status else 1
        next_lane = replace(
            lane,
            resume_only=False,
            failure_streak=failure_streak,
            last_failure_reason=status,
        )
        if failure_streak >= MAX_CONSECUTIVE_FAILURES:
            blocked_lanes.append(next_lane)
        next_lanes.append(next_lane)
        active += 1

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
    next_chain_state = FullExtractionChainState(
        vpn_quarantined_servers=tuple(sorted(merged_quarantined_servers))
    )

    return (
        next_lanes,
        next_chain_state,
        {
            "vpn_quarantined_server_count": len(next_chain_state.vpn_quarantined_servers),
            "active_lane_count": active,
            "resume_only_lane_count": resumed,
            "blocked_lane_count": 0,
            "failure_reason_counts": failure_reason_counts,
        },
    )


def merge_lane_databases(
    *,
    artifacts_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    db_paths = sorted(path for path in artifacts_dir.rglob("nba.duckdb") if path.is_file())
    if not db_paths:
        msg = f"No lane databases found under {artifacts_dir}"
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


def _command_plan(args: argparse.Namespace) -> int:
    manifest = _load_manifest_argument(args.lane_manifest_json, args.lane_manifest_path)
    if manifest is None:
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
        )
        chain_state = FullExtractionChainState()
    else:
        lanes = list(manifest.lanes)
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
    )
    validate_manifest(next_lanes)
    payload = manifest_payload(next_lanes, chain_state=next_chain_state)
    payload["resume_summary"] = summary
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


def _command_merge(args: argparse.Namespace) -> int:
    summary = merge_lane_databases(artifacts_dir=args.artifacts_dir, output_dir=args.output_dir)
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
    plan.add_argument("--output-path", type=Path, required=True)
    plan.set_defaults(func=_command_plan)

    resume = subparsers.add_parser("resume", help="Build the next chained manifest.")
    resume.add_argument("--lane-manifest-json", type=str, default=None)
    resume.add_argument("--lane-manifest-path", type=Path, default=None)
    resume.add_argument("--metadata-dir", type=Path, required=True)
    resume.add_argument("--output-path", type=Path, required=True)
    resume.set_defaults(func=_command_resume)

    merge = subparsers.add_parser("merge", help="Merge lane DuckDB artifacts.")
    merge.add_argument("--artifacts-dir", type=Path, required=True)
    merge.add_argument("--output-dir", type=Path, required=True)
    merge.set_defaults(func=_command_merge)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
