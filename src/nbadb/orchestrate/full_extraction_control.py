from __future__ import annotations

import argparse
import json
import shutil
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import duckdb

from nbadb.core.types import SeasonType
from nbadb.orchestrate.seasons import season_range

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
            "player_dashboard_clutch",
            "player_awards",
            "player_career_stats",
            "player_compare",
            "player_dash_game_splits",
            "player_dash_general_splits",
            "player_dash_last_n_games",
            "player_dash_shooting_splits",
            "player_dash_team_perf",
            "player_dash_yoy",
            "player_next_games",
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
    "player_dashboard_clutch": 4_800,
    "player_awards": 4_200,
    "player_career_stats": 4_800,
    "player_compare": 4_800,
    "player_dash_game_splits": 4_200,
    "player_dash_general_splits": 4_200,
    "player_dash_last_n_games": 4_200,
    "player_dash_shooting_splits": 4_200,
    "player_dash_team_perf": 4_200,
    "player_dash_yoy": 4_200,
    "player_next_games": 4_200,
    "team_historical_leaders": 4_200,
}
FULL_EXTRACTION_EXCLUDED_ENDPOINTS: dict[str, str] = {
    "player_dash_pt_pass": (
        "The live PlayerDashPtPass endpoint requires player/team context that the current "
        "reference-player full-extraction lanes do not provide, so it is excluded until "
        "that contract is modeled explicitly."
    ),
    "player_dash_pt_reb": (
        "The live PlayerDashPtReb endpoint requires player/team context that the current "
        "reference-player full-extraction lanes do not provide, so it is excluded until "
        "that contract is modeled explicitly."
    ),
    "player_dash_pt_shot_defend": (
        "The live PlayerDashPtShotDefend endpoint requires player/team context that the "
        "current reference-player full-extraction lanes do not provide, so it is excluded "
        "until that contract is modeled explicitly."
    ),
    "player_dash_pt_shots": (
        "The live PlayerDashPtShots endpoint requires player/team context that the current "
        "reference-player full-extraction lanes do not provide, so it is excluded until "
        "that contract is modeled explicitly."
    ),
    "team_historical_leaders": (
        "The live TeamHistoricalLeaders endpoint currently returns invalid JSON for valid "
        "current NBA franchise IDs, so it is excluded from end-to-end full extraction."
    ),
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
    grouped_singletons = [(endpoint,) for endpoint in endpoints if endpoint in singleton_endpoints]
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


def validate_manifest(lanes: list[FullExtractionLane]) -> None:
    errors: list[str] = []
    for lane in lanes:
        if (lane.season_start is None) != (lane.season_end is None):
            errors.append(f"{lane.lane_id}: season_start/season_end must both be set or both empty")
        if lane.timeout_seconds <= 0:
            errors.append(f"{lane.lane_id}: timeout_seconds must be > 0")
        if lane.failure_streak < 0:
            errors.append(f"{lane.lane_id}: failure_streak must be >= 0")
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
            endpoint_groups = _reference_endpoint_groups(pattern, endpoints)
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
                        use_vpn=pattern != "player",
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
                for start, end in _season_bands(grouped_rows, {pattern}):
                    for band_start, band_end in _split_season_band(
                        start,
                        end,
                        max_span=_max_span_for_pattern(pattern),
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
            for band_start, band_end in _split_season_band(
                DEFAULT_HISTORICAL_START,
                end_year,
                max_span=CROSS_PRODUCT_MAX_SPAN,
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
) -> list[FullExtractionLane]:
    raw_lanes = raw_manifest.get("lanes", []) if isinstance(raw_manifest, dict) else raw_manifest
    return [
        _normalize_lane(dict(raw_lane), lane_index) for lane_index, raw_lane in enumerate(raw_lanes)
    ]


def manifest_payload(lanes: list[FullExtractionLane]) -> dict[str, Any]:
    lane_dicts = [asdict(lane) for lane in lanes]
    return {
        "manifest_version": 2,
        "lane_count": len(lanes),
        "lanes": lane_dicts,
        "github_matrix": {"include": [lane.to_workflow_dict() for lane in lanes]},
    }


def _load_manifest_argument(
    raw_json: str | None, path: Path | None
) -> list[FullExtractionLane] | None:
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


def build_resume_manifest(
    lanes: list[FullExtractionLane],
    metadata_dir: Path,
) -> tuple[list[FullExtractionLane], dict[str, Any]]:
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

    return next_lanes, {
        "active_lane_count": active,
        "resume_only_lane_count": resumed,
        "blocked_lane_count": 0,
        "failure_reason_counts": failure_reason_counts,
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

    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / "nba.duckdb"

    base_path = max(db_paths, key=lambda path: path.stat().st_size)
    shutil.copy2(base_path, target_path)

    target = duckdb.connect(str(target_path))
    merged_databases = 1
    merged_tables = 0

    try:
        for index, db_path in enumerate(db_paths):
            if db_path == base_path:
                continue
            alias = f"src_{index}"
            target.execute(f"ATTACH '{db_path}' AS {alias} (READ_ONLY)")
            try:
                tables = [
                    row[0]
                    for row in target.execute(
                        "SELECT table_name FROM duckdb_tables() "
                        f"WHERE database_name = '{alias}' AND schema_name = 'main' "
                        "AND table_name LIKE 'stg_%'"
                    ).fetchall()
                ]
                for table_name in tables:
                    try:
                        target.execute(
                            f'INSERT INTO main."{table_name}" '
                            f'SELECT * FROM {alias}."{table_name}" '
                            f'EXCEPT SELECT * FROM main."{table_name}"'
                        )
                    except duckdb.CatalogException:
                        target.execute(
                            f'CREATE TABLE main."{table_name}" AS '
                            f'SELECT * FROM {alias}."{table_name}"'
                        )
                    merged_tables += 1

                with suppress(duckdb.CatalogException):
                    target.execute(
                        "INSERT INTO main._extraction_journal "
                        "SELECT src.endpoint, src.params, src.status, "
                        "src.started_at, src.completed_at, "
                        f"src.rows_extracted, src.error_message, src.retry_count "
                        f"FROM {alias}._extraction_journal AS src "
                        "WHERE NOT EXISTS ("
                        "  SELECT 1 FROM main._extraction_journal AS dst "
                        "  WHERE dst.endpoint = src.endpoint "
                        "    AND dst.params IS NOT DISTINCT FROM src.params"
                        ")"
                    )

                merged_databases += 1
            finally:
                target.execute(f"DETACH {alias}")
    finally:
        target.close()

    return {
        "base_path": str(base_path),
        "merged_database_count": merged_databases,
        "merged_table_operations": merged_tables,
        "output_path": str(target_path),
    }


def _command_plan(args: argparse.Namespace) -> int:
    lanes = _load_manifest_argument(args.lane_manifest_json, args.lane_manifest_path)
    if lanes is None:
        if args.support_matrix_path is None:
            msg = "support-matrix-path is required when no explicit lane manifest is provided"
            raise ValueError(msg)
        support_matrix_rows = _load_matrix_payload(args.support_matrix_path)
        lanes = build_default_manifest(
            support_matrix_rows=support_matrix_rows,
            selected_patterns=_parse_csv(args.backfill_patterns),
            selected_endpoints=_parse_csv(args.backfill_endpoints),
        )

    validate_manifest(lanes)
    payload = manifest_payload(lanes)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


def _command_resume(args: argparse.Namespace) -> int:
    lanes = _load_manifest_argument(args.lane_manifest_json, args.lane_manifest_path)
    if lanes is None:
        msg = "lane-manifest-json or lane-manifest-path is required"
        raise ValueError(msg)

    next_lanes, summary = build_resume_manifest(lanes, args.metadata_dir)
    validate_manifest(next_lanes)
    payload = manifest_payload(next_lanes)
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
