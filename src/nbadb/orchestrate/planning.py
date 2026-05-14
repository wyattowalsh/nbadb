from __future__ import annotations

from dataclasses import dataclass

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
        if season_types and str(param_set.get("season_type", "")) not in season_types:
            continue
        filtered.append(param_set)
    return filtered


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

    @property
    def task_count(self) -> int:
        return len(self.entries) * len(self.params)


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
) -> list[ExtractionPlanItem]:
    """Build the pattern execution plan for a pipeline run.

    The returned plan preserves the current runtime behavior of
    ``Orchestrator._extract_all_patterns``. If a future staging entry carries
    a documented upstream support floor, that ``min_season`` still narrows the
    generated workload; production entries otherwise start at 1946.
    """

    plan: list[ExtractionPlanItem] = []

    static_entries = get_by_pattern("static")
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

    season_entries = [e for e in get_by_pattern("season") if e.endpoint_name != "league_game_log"]
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

    game_entries = get_by_pattern("game")
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

    player_entries = get_by_pattern("player")
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

    team_entries = get_by_pattern("team")
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

    player_season_entries = get_by_pattern("player_season")
    if player_season_entries and player_ids and seasons:
        for grouped_entries, start_year, grouped_season_types in _group_historical_entries(
            player_season_entries, season_types
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

    team_season_entries = get_by_pattern("team_season")
    if team_season_entries and team_ids and seasons:
        for grouped_entries, start_year, grouped_season_types in _group_historical_entries(
            team_season_entries, season_types
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

    player_team_season_entries = get_by_pattern("player_team_season")
    if player_team_season_entries and player_team_season_params:
        supported_cross_product_entries = [
            entry
            for entry in player_team_season_entries
            if entry.endpoint_name in PLAYER_TEAM_SEASON_WORKLOAD_ENDPOINTS
            and _season_type_capability(entry) == "supported"
            and _supported_season_types(entry)
        ]
        for grouped_entries, start_year, grouped_season_types in _group_historical_entries(
            supported_cross_product_entries,
            season_types,
        ):
            grouped_params = _filter_cross_product_params(
                player_team_season_params,
                start_year=start_year,
                season_types=grouped_season_types,
            )
            if not grouped_params:
                continue
            plan.append(
                ExtractionPlanItem(
                    label=_label_with_contract("player x team x season", grouped_season_types),
                    pattern="player_team_season",
                    entries=grouped_entries,
                    params=grouped_params,
                    priority=PATTERN_PRIORITY["player_team_season"],
                )
            )

    date_entries = get_by_pattern("date")
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
