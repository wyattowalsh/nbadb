from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class StagingEntry:
    endpoint_name: str
    staging_key: str
    param_pattern: Literal["season", "game", "player", "team", "static", "date"]
    result_set_index: int = 0
    use_multi: bool = False


STAGING_MAP: list[StagingEntry] = [
    # ── Season-level (13) ─────────────────────────────────────────
    StagingEntry("league_game_log", "stg_league_game_log", "season"),
    StagingEntry("schedule", "stg_schedule", "season"),
    StagingEntry("league_standings", "stg_standings", "season"),
    StagingEntry("draft_history", "stg_draft", "season"),
    StagingEntry("draft_combine_stats", "stg_draft_combine", "season"),
    StagingEntry(
        "league_dash_player_stats",
        "stg_league_dash_player_stats",
        "season",
    ),
    StagingEntry(
        "league_dash_team_stats",
        "stg_league_dash_team_stats",
        "season",
    ),
    StagingEntry("league_lineup_viz", "stg_league_lineup_viz", "season"),
    StagingEntry("synergy_play_types", "stg_synergy", "season"),
    StagingEntry("league_dash_pt_defend", "stg_tracking_defense", "season"),
    StagingEntry(
        "league_dash_player_shot_locations",
        "stg_shot_locations",
        "season",
    ),
    StagingEntry("league_dash_lineups", "stg_lineup", "season"),
    StagingEntry(
        "league_dash_player_clutch",
        "stg_league_player_clutch",
        "season",
    ),
    # ── Game-level (16) ───────────────────────────────────────────
    StagingEntry("box_score_traditional", "stg_box_score_traditional", "game"),
    StagingEntry("box_score_advanced", "stg_box_score_advanced", "game"),
    StagingEntry("box_score_misc", "stg_box_score_misc", "game"),
    StagingEntry("box_score_scoring", "stg_box_score_scoring", "game"),
    StagingEntry("box_score_usage", "stg_box_score_usage", "game"),
    StagingEntry(
        "box_score_four_factors",
        "stg_box_score_four_factors_player",
        "game",
    ),
    StagingEntry("box_score_hustle", "stg_box_score_hustle", "game"),
    StagingEntry("box_score_player_track", "stg_box_score_player_track", "game"),
    StagingEntry("box_score_defensive", "stg_box_score_defensive", "game"),
    StagingEntry("play_by_play", "stg_play_by_play", "game"),
    StagingEntry("win_probability", "stg_win_probability", "game"),
    StagingEntry("game_rotation", "stg_rotation", "game"),
    StagingEntry("box_score_matchups", "stg_matchup", "game"),
    StagingEntry(
        "box_score_summary",
        "stg_line_score",
        "game",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary",
        "stg_officials",
        "game",
        result_set_index=6,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_arena_info",
        "game",
        result_set_index=2,
        use_multi=True,
    ),
    # ── Date-level (2) ────────────────────────────────────────────
    StagingEntry("scoreboard_v2", "stg_scoreboard", "date"),
    StagingEntry(
        "scoreboard_v3",
        "stg_game_leaders",
        "date",
        result_set_index=3,
        use_multi=True,
    ),
    # ── Player-level (6) ──────────────────────────────────────────
    StagingEntry("common_player_info", "stg_player_info", "player"),
    StagingEntry("player_awards", "stg_player_awards", "player"),
    StagingEntry("player_career_by_college", "stg_player_college", "player"),
    StagingEntry("shot_chart_detail", "stg_shot_chart", "player"),
    StagingEntry("player_estimated_metrics", "stg_player_tracking", "player"),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_dashboard_clutch",
        "player",
    ),
    # ── Team-level (4) ────────────────────────────────────────────
    StagingEntry("common_team_roster", "stg_team_info", "team"),
    StagingEntry(
        "team_estimated_metrics",
        "stg_team_dashboard_estimated",
        "team",
    ),
    StagingEntry(
        "team_player_on_off_details",
        "stg_team_dashboard_on_off",
        "team",
    ),
    StagingEntry("team_player_on_off_summary", "stg_on_off", "team"),
    # ── Static (2) ────────────────────────────────────────────────
    StagingEntry("franchise_history", "stg_franchise", "static"),
    StagingEntry("all_time_leaders_grids", "stg_all_time", "static"),
]


def get_by_pattern(pattern: str) -> list[StagingEntry]:
    """Return all entries matching a given param_pattern."""
    return [e for e in STAGING_MAP if e.param_pattern == pattern]


def get_by_staging_key(key: str) -> StagingEntry | None:
    """Return the entry for a given staging_key, or None."""
    for e in STAGING_MAP:
        if e.staging_key == key:
            return e
    return None


def get_all_staging_keys() -> list[str]:
    """Return all staging key names."""
    return [e.staging_key for e in STAGING_MAP]


def get_multi_entries() -> dict[str, list[StagingEntry]]:
    """Group entries sharing the same endpoint where use_multi=True."""
    groups: dict[str, list[StagingEntry]] = {}
    for e in STAGING_MAP:
        if e.use_multi:
            groups.setdefault(e.endpoint_name, []).append(e)
    return groups
