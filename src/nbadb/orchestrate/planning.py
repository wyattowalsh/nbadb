from __future__ import annotations

from dataclasses import dataclass

from nbadb.core.types import (
    VIDEO_CONTEXT_MEASURES,
    classify_season_type_availability,
)
from nbadb.orchestrate.cume_workload_contract import (
    CumeEntityKind,
    CumeWorkloadDisposition,
    CumeWorkloadValue,
)
from nbadb.orchestrate.staging_map import StagingEntry, get_by_pattern

type PlanParams = dict[str, int | str]
_DEFAULT_HISTORICAL_START_SEASON = 1946


# Pattern priority tiers (lower = higher priority, runs first).
# Patterns in the same tier run concurrently; tiers run sequentially.
# This ensures small/fast patterns complete before the massive game-level
# extraction begins.
PATTERN_PRIORITY: dict[str, int] = {
    "static": 0,
    "season": 1,
    "team": 2,
    "date": 2,
    "player": 3,
    "team_season": 3,
    "player_season": 3,
    "player_team_season": 3,
    "game": 4,
}
PLAYER_TEAM_SEASON_WORKLOAD_ENDPOINTS = frozenset(
    {
        "video_details",
        "video_details_asset",
    }
)
_CURRENT_TEAM_ONLY_ENDPOINTS = frozenset(
    {
        "team_details",
        "team_historical_leaders",
        "team_info_common",
    }
)
CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT: dict[str, str] = {
    "cume_stats_player": "cume_stats_player_games",
    "cume_stats_team": "cume_stats_team_games",
}
_CUME_ENTITY_KIND_BY_DEPENDENT_ENDPOINT: dict[str, CumeEntityKind] = {
    "cume_stats_player": CumeEntityKind.PLAYER,
    "cume_stats_team": CumeEntityKind.TEAM,
}
_CUME_ENDPOINTS = frozenset(
    {
        *CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT,
        *CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT.values(),
    }
)


def _season_type_capability(entry: StagingEntry) -> str:
    capability = getattr(entry, "season_type_capability", "supported")
    return capability if isinstance(capability, str) else "supported"


def _supported_season_types(entry: StagingEntry) -> list[str]:
    values = getattr(entry, "supported_season_types", ())
    if not isinstance(values, list | tuple | set | frozenset):
        return []
    return [str(value) for value in values]


def _resolved_season_types(
    entry: StagingEntry,
    requested_season_types: list[str] | None,
) -> list[str]:
    if _season_type_capability(entry) != "supported":
        return []

    supported_season_types = _supported_season_types(entry)
    if not supported_season_types:
        return []

    requested = requested_season_types or supported_season_types
    return [season_type for season_type in supported_season_types if season_type in requested]


def _historical_start_year(entry: StagingEntry) -> int:
    return entry.min_season or _DEFAULT_HISTORICAL_START_SEASON


def _group_historical_entries(
    entries: list[StagingEntry],
    requested_season_types: list[str] | None,
) -> list[tuple[list[StagingEntry], int, list[str]]]:
    grouped: dict[tuple[int, tuple[str, ...]], list[StagingEntry]] = {}

    for entry in entries:
        season_types = _resolved_season_types(entry, requested_season_types)
        capability = _season_type_capability(entry)
        if capability == "supported" and not season_types:
            continue

        group_key = (_historical_start_year(entry), tuple(season_types))
        grouped.setdefault(group_key, []).append(entry)

    return [(grouped[group_key], group_key[0], list(group_key[1])) for group_key in sorted(grouped)]


def _build_historical_params(
    *,
    seasons: list[str],
    season_types: list[str] | None,
    base_params: list[dict[str, int | str]],
) -> list[PlanParams]:
    if not season_types:
        return [{**params, "season": season} for params in base_params for season in seasons]

    return [
        {**params, "season": season, "season_type": season_type}
        for params in base_params
        for season in seasons
        for season_type in season_types
        if _season_type_is_available(season, season_type)
    ]


def _filter_seasons_for_start_year(
    seasons: list[str],
    start_year: int,
) -> list[str]:
    filtered: list[str] = []
    for season in seasons:
        try:
            season_year = int(season[:4])
        except (ValueError, IndexError):
            continue
        if season_year >= start_year:
            filtered.append(season)
    return filtered


def _label_with_contract(base_label: str, season_types: list[str]) -> str:
    if not season_types:
        return base_label
    season_type_label = "/".join(season_types)
    return f"{base_label} [{season_type_label}]"


def _param_season_year(params: PlanParams) -> int | None:
    season = params.get("season")
    if season is None:
        return None
    try:
        return int(str(season)[:4])
    except (ValueError, TypeError):
        return None


def _season_type_is_available(season: str, season_type: str) -> bool:
    try:
        season_start_year = int(season[:4])
    except (TypeError, ValueError):
        return True
    return classify_season_type_availability(season_start_year, season_type) == "supported"


def _deduplicate_params(params: list[PlanParams]) -> list[PlanParams]:
    deduplicated: list[PlanParams] = []
    seen: set[tuple[tuple[str, int | str], ...]] = set()
    for param_set in params:
        key = tuple(sorted(param_set.items()))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(param_set)
    return deduplicated


def resolve_video_context_measures(
    context_measures: list[str] | None,
) -> tuple[str, ...]:
    """Validate and resolve an optional video context-measure filter."""

    if context_measures is None:
        return VIDEO_CONTEXT_MEASURES
    if not context_measures:
        msg = "context_measures cannot be empty when explicitly provided"
        raise ValueError(msg)

    invalid = sorted(set(context_measures) - set(VIDEO_CONTEXT_MEASURES))
    if invalid:
        msg = f"Unknown video context measure(s): {', '.join(invalid)}"
        raise ValueError(msg)

    return tuple(dict.fromkeys(context_measures))


def _expand_video_context_measures(
    params: list[PlanParams],
    context_measures: tuple[str, ...],
) -> list[PlanParams]:
    return [
        {**param_set, "context_measure": context_measure}
        for param_set in _deduplicate_params(params)
        for context_measure in context_measures
    ]


def _filter_cross_product_params(
    params: list[PlanParams],
    *,
    start_year: int,
    season_types: list[str],
) -> list[PlanParams]:
    filtered: list[PlanParams] = []
    for param_set in params:
        season_year = _param_season_year(param_set)
        if season_year is not None and season_year < start_year:
            continue
        season_type = str(param_set.get("season_type", ""))
        if season_types and season_type not in season_types:
            continue
        if (
            season_year is not None
            and season_type
            and classify_season_type_availability(season_year, season_type)
            == "upstream_unavailable"
        ):
            continue
        filtered.append(param_set)
    return _deduplicate_params(filtered)


@dataclass(frozen=True, slots=True)
class CumeFoundationDependency:
    """Planner metadata for one fail-closed cumulative-stat dependency."""

    dependent_entries: tuple[StagingEntry, ...]
    entity_kind: CumeEntityKind

    def __post_init__(self) -> None:
        if not self.dependent_entries:
            raise ValueError("cumulative-stat dependency requires dependent routes")
        dependent_endpoint = self.dependent_entries[0].endpoint_name
        if any(entry.endpoint_name != dependent_endpoint for entry in self.dependent_entries):
            raise ValueError("cumulative-stat dependent routes must share one endpoint")
        expected_kind = _CUME_ENTITY_KIND_BY_DEPENDENT_ENDPOINT.get(dependent_endpoint)
        if expected_kind is None or expected_kind is not self.entity_kind:
            raise ValueError("invalid cumulative-stat dependent endpoint contract")


@dataclass(frozen=True, slots=True)
class ExtractionPlanItem:
    """One pattern-specific extraction workload.

    This is intentionally small and behavior-preserving: it mirrors the
    current orchestrator plan shape so planning logic can evolve independently
    from execution logic in later phases.
    """

    label: str
    pattern: str
    entries: list[StagingEntry]
    params: list[PlanParams]
    priority: int
    cume_dependency: CumeFoundationDependency | None = None

    def __post_init__(self) -> None:
        dependency = self.cume_dependency
        if dependency is None:
            return
        expected_foundation = CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT[
            dependency.dependent_entries[0].endpoint_name
        ]
        if len(self.entries) != 1 or self.entries[0].endpoint_name != expected_foundation:
            raise ValueError(
                "cumulative-stat dependency must contain exactly its paired foundation entry"
            )

    @property
    def coverage_entries(self) -> tuple[StagingEntry, ...]:
        """Return concrete routes represented by this semantic plan slice."""

        dependency = self.cume_dependency
        if dependency is None:
            return tuple(self.entries)
        return (*self.entries, *dependency.dependent_entries)

    @property
    def task_count(self) -> int:
        return len(self.coverage_entries) * len(self.params)


def cume_workload_execution_params(workload: CumeWorkloadValue) -> PlanParams:
    """Serialize a complete workload into runner-safe, journal-bound parameters."""

    if workload.disposition is not CumeWorkloadDisposition.COMPLETE:
        raise ValueError("typed-zero cumulative-stat workloads are not executable")
    entity_key = f"{workload.entity_kind.value}_id"
    params: PlanParams = {
        entity_key: workload.entity_id,
        "season": workload.season,
        "season_type": workload.season_type,
        "game_ids": workload.encoded_game_ids,
        "cume_workload_sha256": workload.content_sha256,
    }
    if workload.foundation_receipt_sha256 is not None:
        params["foundation_receipt_sha256"] = workload.foundation_receipt_sha256
    if workload.provider_authority_sha256 is not None:
        params["provider_authority_sha256"] = workload.provider_authority_sha256
    return params


def _build_cume_foundation_plan_items(
    *,
    entries: list[StagingEntry],
    entity_kind: CumeEntityKind,
    entity_ids: list[int],
    seasons: list[str],
    requested_season_types: list[str] | None,
    base_label: str,
    pattern: str,
) -> list[ExtractionPlanItem]:
    """Build isolated foundation slices; dependent params are derived at runtime."""

    by_endpoint: dict[str, list[StagingEntry]] = {}
    for entry in entries:
        if entry.endpoint_name in _CUME_ENDPOINTS:
            by_endpoint.setdefault(entry.endpoint_name, []).append(entry)

    dependent_endpoint = f"cume_stats_{entity_kind.value}"
    foundation_endpoint = CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT[dependent_endpoint]
    dependent_entries = by_endpoint.get(dependent_endpoint, [])
    foundation_entries = by_endpoint.get(foundation_endpoint, [])
    if not dependent_entries and not foundation_entries:
        return []
    if not dependent_entries or len(foundation_entries) != 1:
        raise ValueError(f"{dependent_endpoint} requires exactly one {foundation_endpoint} route")

    foundation_entry = foundation_entries[0]
    foundation_types = _resolved_season_types(foundation_entry, requested_season_types)
    dependent_types = _resolved_season_types(dependent_entries[0], requested_season_types)
    season_types = (
        [value for value in foundation_types if value in dependent_types]
        if _season_type_capability(dependent_entries[0]) == "supported"
        else foundation_types
    )
    if not season_types:
        return []
    start_year = max(
        *(_historical_start_year(entry) for entry in dependent_entries),
        _historical_start_year(foundation_entry),
    )
    grouped_seasons = _filter_seasons_for_start_year(seasons, start_year)
    if not grouped_seasons:
        return []
    entity_key = f"{entity_kind.value}_id"
    params = _build_historical_params(
        seasons=grouped_seasons,
        season_types=season_types,
        base_params=[{entity_key: entity_id} for entity_id in entity_ids],
    )
    if not params:
        return []
    return [
        ExtractionPlanItem(
            label=_label_with_contract(
                f"{base_label} ({dependent_endpoint})",
                season_types,
            ),
            pattern=pattern,
            entries=[foundation_entry],
            params=params,
            priority=PATTERN_PRIORITY[pattern],
            cume_dependency=CumeFoundationDependency(
                dependent_entries=tuple(dependent_entries),
                entity_kind=entity_kind,
            ),
        )
    ]


def executable_entries_by_pattern() -> dict[str, list[StagingEntry]]:
    """Return planner-owned endpoint routes independent of workload cardinality."""

    entries = {pattern: get_by_pattern(pattern) for pattern in PATTERN_PRIORITY}
    entries["season"] = [
        entry for entry in entries["season"] if entry.endpoint_name != "league_game_log"
    ]
    entries["player_team_season"] = [
        entry
        for entry in entries["player_team_season"]
        if entry.endpoint_name in PLAYER_TEAM_SEASON_WORKLOAD_ENDPOINTS
        and _season_type_capability(entry) == "supported"
        and _supported_season_types(entry)
    ]
    return entries


def executable_endpoint_routes() -> frozenset[tuple[str, str]]:
    """Return every concrete endpoint/pattern pair the planner can emit."""

    return frozenset(
        (entry.endpoint_name, pattern)
        for pattern, entries in executable_entries_by_pattern().items()
        for entry in entries
    )


def build_extraction_plan(
    *,
    seasons: list[str],
    game_ids: list[str],
    player_ids: list[int],
    team_ids: list[int],
    current_team_ids: list[int] | None = None,
    game_dates: list[str],
    player_team_season_params: list[PlanParams] | None = None,
    include_static: bool = True,
    season_types: list[str] | None = None,
    context_measures: list[str] | None = None,
) -> list[ExtractionPlanItem]:
    """Build the pattern execution plan for a pipeline run.

    The returned plan preserves the current runtime behavior of
    ``Orchestrator._extract_all_patterns``. If a future staging entry carries
    a documented upstream support floor, that ``min_season`` still narrows the
    generated workload; production entries otherwise start at 1946.
    """

    resolved_context_measures = resolve_video_context_measures(context_measures)
    plan: list[ExtractionPlanItem] = []
    entries_by_pattern = executable_entries_by_pattern()

    static_entries = entries_by_pattern["static"]
    if include_static and static_entries:
        plan.append(
            ExtractionPlanItem(
                label="static",
                pattern="static",
                entries=static_entries,
                params=[{}],
                priority=PATTERN_PRIORITY["static"],
            )
        )

    season_entries = entries_by_pattern["season"]
    if season_entries and seasons:
        for grouped_entries, start_year, grouped_season_types in _group_historical_entries(
            season_entries, season_types
        ):
            grouped_seasons = _filter_seasons_for_start_year(seasons, start_year)
            if not grouped_seasons:
                continue
            plan.append(
                ExtractionPlanItem(
                    label=_label_with_contract("season", grouped_season_types),
                    pattern="season",
                    entries=grouped_entries,
                    params=_build_historical_params(
                        seasons=grouped_seasons,
                        season_types=grouped_season_types,
                        base_params=[{}],
                    ),
                    priority=PATTERN_PRIORITY["season"],
                )
            )

    game_entries = entries_by_pattern["game"]
    if game_entries and game_ids:
        plan.append(
            ExtractionPlanItem(
                label="game",
                pattern="game",
                entries=game_entries,
                params=[{"game_id": game_id} for game_id in game_ids],
                priority=PATTERN_PRIORITY["game"],
            )
        )

    player_entries = entries_by_pattern["player"]
    if player_entries and player_ids:
        plan.append(
            ExtractionPlanItem(
                label="player",
                pattern="player",
                entries=player_entries,
                params=[{"player_id": player_id} for player_id in player_ids],
                priority=PATTERN_PRIORITY["player"],
            )
        )

    team_entries = entries_by_pattern["team"]
    if team_entries and team_ids:
        general_team_entries = [
            entry
            for entry in team_entries
            if entry.endpoint_name not in _CURRENT_TEAM_ONLY_ENDPOINTS
        ]
        if general_team_entries:
            plan.append(
                ExtractionPlanItem(
                    label="team",
                    pattern="team",
                    entries=general_team_entries,
                    params=[{"team_id": team_id} for team_id in team_ids],
                    priority=PATTERN_PRIORITY["team"],
                )
            )
        current_only_entries = [
            entry for entry in team_entries if entry.endpoint_name in _CURRENT_TEAM_ONLY_ENDPOINTS
        ]
        resolved_current_team_ids = current_team_ids or team_ids
        if current_only_entries and resolved_current_team_ids:
            plan.append(
                ExtractionPlanItem(
                    label="team (current)",
                    pattern="team",
                    entries=current_only_entries,
                    params=[{"team_id": team_id} for team_id in resolved_current_team_ids],
                    priority=PATTERN_PRIORITY["team"],
                )
            )

    player_season_entries = entries_by_pattern["player_season"]
    if player_season_entries and player_ids and seasons:
        ordinary_player_season_entries = [
            entry for entry in player_season_entries if entry.endpoint_name not in _CUME_ENDPOINTS
        ]
        for grouped_entries, start_year, grouped_season_types in _group_historical_entries(
            ordinary_player_season_entries, season_types
        ):
            grouped_seasons = _filter_seasons_for_start_year(seasons, start_year)
            if not grouped_seasons:
                continue
            plan.append(
                ExtractionPlanItem(
                    label=_label_with_contract("player x season", grouped_season_types),
                    pattern="player_season",
                    entries=grouped_entries,
                    params=_build_historical_params(
                        seasons=grouped_seasons,
                        season_types=grouped_season_types,
                        base_params=[{"player_id": player_id} for player_id in player_ids],
                    ),
                    priority=PATTERN_PRIORITY["player_season"],
                )
            )
        plan.extend(
            _build_cume_foundation_plan_items(
                entries=player_season_entries,
                entity_kind=CumeEntityKind.PLAYER,
                entity_ids=player_ids,
                seasons=seasons,
                requested_season_types=season_types,
                base_label="player x season",
                pattern="player_season",
            )
        )

    team_season_entries = entries_by_pattern["team_season"]
    if team_season_entries and team_ids and seasons:
        ordinary_team_season_entries = [
            entry for entry in team_season_entries if entry.endpoint_name not in _CUME_ENDPOINTS
        ]
        for grouped_entries, start_year, grouped_season_types in _group_historical_entries(
            ordinary_team_season_entries, season_types
        ):
            grouped_seasons = _filter_seasons_for_start_year(seasons, start_year)
            if not grouped_seasons:
                continue
            plan.append(
                ExtractionPlanItem(
                    label=_label_with_contract("team x season", grouped_season_types),
                    pattern="team_season",
                    entries=grouped_entries,
                    params=_build_historical_params(
                        seasons=grouped_seasons,
                        season_types=grouped_season_types,
                        base_params=[{"team_id": team_id} for team_id in team_ids],
                    ),
                    priority=PATTERN_PRIORITY["team_season"],
                )
            )
        plan.extend(
            _build_cume_foundation_plan_items(
                entries=team_season_entries,
                entity_kind=CumeEntityKind.TEAM,
                entity_ids=team_ids,
                seasons=seasons,
                requested_season_types=season_types,
                base_label="team x season",
                pattern="team_season",
            )
        )

    player_team_season_entries = entries_by_pattern["player_team_season"]
    if player_team_season_entries and player_team_season_params:
        for grouped_entries, start_year, grouped_season_types in _group_historical_entries(
            player_team_season_entries,
            season_types,
        ):
            grouped_params = _filter_cross_product_params(
                player_team_season_params,
                start_year=start_year,
                season_types=grouped_season_types,
            )
            if not grouped_params:
                continue
            expanded_params = _expand_video_context_measures(
                grouped_params,
                resolved_context_measures,
            )
            for entry in grouped_entries:
                plan.append(
                    ExtractionPlanItem(
                        label=_label_with_contract(
                            f"player x team x season ({entry.endpoint_name})",
                            grouped_season_types,
                        ),
                        pattern="player_team_season",
                        entries=[entry],
                        params=expanded_params,
                        priority=PATTERN_PRIORITY["player_team_season"],
                    )
                )

    date_entries = entries_by_pattern["date"]
    if date_entries and game_dates:
        plan.append(
            ExtractionPlanItem(
                label="date",
                pattern="date",
                entries=date_entries,
                params=[{"game_date": game_date} for game_date in game_dates],
                priority=PATTERN_PRIORITY["date"],
            )
        )

    return plan
