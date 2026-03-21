from __future__ import annotations

from dataclasses import dataclass

from nbadb.orchestrate.staging_map import StagingEntry, get_by_pattern

type PlanParams = dict[str, int | str]


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
    game_dates: list[str],
    player_team_season_params: list[PlanParams] | None = None,
    include_static: bool = True,
    season_types: list[str] | None = None,
) -> list[ExtractionPlanItem]:
    """Build the pattern execution plan for a pipeline run.

    The returned plan preserves the current runtime behavior of
    ``Orchestrator._extract_all_patterns``. Eligibility checks such as
    ``min_season`` remain enforced at execution time by ``ExtractorRunner``.
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
    season_type_values = season_types or ["Regular Season"]
    if season_entries and seasons:
        plan.append(
            ExtractionPlanItem(
                label="season",
                pattern="season",
                entries=season_entries,
                params=[
                    {"season": season, "season_type": season_type}
                    for season in seasons
                    for season_type in season_type_values
                ],
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
        plan.append(
            ExtractionPlanItem(
                label="team",
                pattern="team",
                entries=team_entries,
                params=[{"team_id": team_id} for team_id in team_ids],
                priority=PATTERN_PRIORITY["team"],
            )
        )

    player_season_entries = get_by_pattern("player_season")
    if player_season_entries and player_ids and seasons:
        plan.append(
            ExtractionPlanItem(
                label="player x season",
                pattern="player_season",
                entries=player_season_entries,
                params=[
                    {"player_id": player_id, "season": season}
                    for player_id in player_ids
                    for season in seasons
                ],
                priority=PATTERN_PRIORITY["player_season"],
            )
        )

    team_season_entries = get_by_pattern("team_season")
    if team_season_entries and team_ids and seasons:
        plan.append(
            ExtractionPlanItem(
                label="team x season",
                pattern="team_season",
                entries=team_season_entries,
                params=[
                    {"team_id": team_id, "season": season}
                    for team_id in team_ids
                    for season in seasons
                ],
                priority=PATTERN_PRIORITY["team_season"],
            )
        )

    player_team_season_entries = get_by_pattern("player_team_season")
    if player_team_season_entries and player_team_season_params:
        plan.append(
            ExtractionPlanItem(
                label="player x team x season",
                pattern="player_team_season",
                entries=player_team_season_entries,
                params=player_team_season_params,
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
