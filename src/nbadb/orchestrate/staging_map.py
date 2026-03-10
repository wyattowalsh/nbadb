from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class StagingEntry:
    endpoint_name: str
    staging_key: str
    param_pattern: Literal[
        "season",
        "game",
        "player",
        "team",
        "player_season",
        "team_season",
        "static",
        "date",
    ]
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
    StagingEntry("box_score_matchups", "stg_matchup", "game"),
    StagingEntry(
        "box_score_summary",
        "stg_game_summary_available_video",
        "game",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary",
        "stg_game_info",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary",
        "stg_game_summary",
        "game",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary",
        "stg_inactive_players",
        "game",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary",
        "stg_last_meeting",
        "game",
        result_set_index=4,
        use_multi=True,
    ),
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
        "box_score_summary",
        "stg_other_stats",
        "game",
        result_set_index=7,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary",
        "stg_season_series",
        "game",
        result_set_index=8,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_game_summary",
        "game",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_game_info",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_arena_info",
        "game",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_officials",
        "game",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_line_score",
        "game",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_inactive_players",
        "game",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_last_five_meetings",
        "game",
        result_set_index=6,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_other_stats",
        "game",
        result_set_index=7,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_available_video",
        "game",
        result_set_index=8,
        use_multi=True,
    ),
    StagingEntry(
        "game_rotation",
        "stg_rotation_away",
        "game",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "game_rotation",
        "stg_rotation_home",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    # ── Date-level (12) ───────────────────────────────────────────
    StagingEntry("scoreboard_v2", "stg_scoreboard", "date"),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_available",
        "date",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_east_conf",
        "date",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_v2_series_standings",
        "date",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_last_meeting",
        "date",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_line_score",
        "date",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_series_standings",
        "date",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_team_leaders",
        "date",
        result_set_index=6,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_ticket_links",
        "date",
        result_set_index=7,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_west_conf",
        "date",
        result_set_index=8,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v3",
        "stg_game_leaders",
        "date",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v3",
        "stg_scoreboard_v3_metadata",
        "date",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v3",
        "stg_scoreboard_v3_summary",
        "date",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v3",
        "stg_scoreboard_v3_line_score",
        "date",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v3",
        "stg_scoreboard_v3_team_stats",
        "date",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "scoreboard_v3",
        "stg_scoreboard_v3_broadcaster",
        "date",
        result_set_index=5,
        use_multi=True,
    ),
    # ── Player-level (6) ──────────────────────────────────────────
    StagingEntry("common_player_info", "stg_player_info", "player"),
    StagingEntry("player_awards", "stg_player_awards", "player"),
    StagingEntry("player_career_by_college", "stg_player_college", "player"),
    StagingEntry("shot_chart_detail", "stg_shot_chart", "player"),
    StagingEntry("player_estimated_metrics", "stg_player_tracking", "season"),
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
        "season",
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
    # ── Playoff / IST (9) ─────────────────────────────────────────
    StagingEntry(
        "playoff_picture",
        "stg_playoff_picture_east",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "playoff_picture",
        "stg_playoff_picture_east_remaining",
        "season",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "playoff_picture",
        "stg_playoff_picture_east_standings",
        "season",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "playoff_picture",
        "stg_playoff_picture_west",
        "season",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "playoff_picture",
        "stg_playoff_picture_west_remaining",
        "season",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "playoff_picture",
        "stg_playoff_picture_west_standings",
        "season",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry("ist_standings", "stg_ist_standings", "season"),
    StagingEntry("common_playoff_series", "stg_common_playoff_series", "season"),
    # --- merged from patch files ---
    # Season-level additions
    StagingEntry("league_hustle_player", "stg_league_hustle_player", "season"),
    StagingEntry("league_hustle_team", "stg_league_hustle_team", "season"),
    StagingEntry("league_dash_pt_stats", "stg_league_pt_stats", "season"),
    StagingEntry("league_dash_pt_team_defend", "stg_league_pt_team_defend", "season"),
    StagingEntry("league_dash_team_pt_shot", "stg_league_team_pt_shot", "season"),
    StagingEntry("league_dash_opp_pt_shot", "stg_league_opp_pt_shot", "season"),
    StagingEntry("league_dash_player_pt_shot", "stg_league_player_pt_shot", "season"),
    StagingEntry("league_dash_team_clutch", "stg_league_team_clutch", "season"),
    StagingEntry(
        "league_dash_team_shot_locations",
        "stg_league_team_shot_locations",
        "season",
    ),
    StagingEntry("league_dash_player_bio", "stg_league_player_bio", "season"),
    StagingEntry("league_leaders", "stg_league_leaders", "season"),
    StagingEntry("assist_leaders", "stg_assist_leaders", "season"),
    StagingEntry("assist_tracker", "stg_assist_tracker", "season"),
    StagingEntry("dunk_score_leaders", "stg_dunk_score_leaders", "season"),
    StagingEntry("gravity_leaders", "stg_gravity_leaders", "season"),
    StagingEntry("leaders_tiles", "stg_leaders_tiles", "season"),
    StagingEntry("homepage_leaders", "stg_homepage_leaders", "season"),
    StagingEntry("homepage_v2", "stg_homepage_v2", "season"),
    StagingEntry("league_player_on_details", "stg_player_on_details", "team_season"),
    StagingEntry("league_season_matchups", "stg_season_matchups", "season"),
    StagingEntry("matchups_rollup", "stg_matchups_rollup", "season"),
    StagingEntry("defense_hub", "stg_defense_hub", "season"),
    StagingEntry("shot_chart_league_wide", "stg_shot_chart_league_wide", "season"),
    StagingEntry("shot_chart_lineup", "stg_shot_chart_lineup", "season"),
    StagingEntry(
        "draft_combine_drill_results",
        "stg_draft_combine_drills",
        "season",
    ),
    StagingEntry(
        "draft_combine_non_stationary_shooting",
        "stg_draft_combine_nonstat_shooting",
        "season",
    ),
    StagingEntry(
        "draft_combine_player_anthro",
        "stg_draft_combine_anthro",
        "season",
    ),
    StagingEntry(
        "draft_combine_spot_shooting",
        "stg_draft_combine_spot_shooting",
        "season",
    ),
    # Extractor-only aliases (season)
    StagingEntry("common_all_players", "stg_common_all_players", "season"),
    StagingEntry("home_page_leaders", "stg_home_page_leaders", "season"),
    StagingEntry("home_page_v2", "stg_home_page_v2", "season"),
    StagingEntry(
        "league_dash_player_bio_stats",
        "stg_league_dash_player_bio_stats",
        "season",
    ),
    StagingEntry(
        "league_hustle_stats_player",
        "stg_league_hustle_stats_player",
        "season",
    ),
    StagingEntry("league_hustle_stats_team", "stg_league_hustle_stats_team", "season"),
    StagingEntry("player_game_logs", "stg_player_game_logs", "season"),
    StagingEntry("player_index", "stg_player_index", "season"),
    StagingEntry("shot_chart_lineup_detail", "stg_shot_chart_lineup_detail", "season"),
    # Game-level additions
    StagingEntry("hustle_stats_box_score", "stg_box_score_hustle_box", "game"),
    # gl_alum_box_score_similarity_score excluded: needs person IDs
    StagingEntry("play_by_play_v2", "stg_play_by_play_v2", "game"),
    # Player-level additions — PlayerCareerStats multi-result
    StagingEntry(
        "player_career_stats",
        "stg_player_career_total_allstar",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_career_total_college",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_career_total_postseason",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_career_total_regular",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_season_ranks_postseason",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_season_ranks_regular",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_career_allstar",
        "player",
        result_set_index=6,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_career_college",
        "player",
        result_set_index=7,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_career_postseason",
        "player",
        result_set_index=8,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_stats",
        "stg_player_career_regular",
        "player",
        result_set_index=9,
        use_multi=True,
    ),
    # Player-level additions — PlayerProfileV2 multi-result
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_career_highs",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_total_allstar",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_total_college",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_total_postseason",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_total_preseason",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_total_regular",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_next_game",
        "player",
        result_set_index=6,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_season_highs",
        "player",
        result_set_index=7,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_ranks_postseason",
        "player",
        result_set_index=8,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_ranks_regular",
        "player",
        result_set_index=9,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_allstar",
        "player",
        result_set_index=10,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_college",
        "player",
        result_set_index=11,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_postseason",
        "player",
        result_set_index=12,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_preseason",
        "player",
        result_set_index=13,
        use_multi=True,
    ),
    StagingEntry(
        "player_profile_v2",
        "stg_player_profile_regular",
        "player",
        result_set_index=14,
        use_multi=True,
    ),
    # Player-level additions — single-result endpoints
    StagingEntry("cume_stats_player", "stg_cume_player", "player"),
    StagingEntry("cume_stats_player_games", "stg_cume_player_games", "player"),
    StagingEntry(
        "player_dash_game_splits",
        "stg_player_dash_game_splits",
        "player",
    ),
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_dash_general_splits",
        "player",
    ),
    StagingEntry(
        "player_dash_last_n_games",
        "stg_player_dash_last_n_games",
        "player",
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_dash_shooting_splits",
        "player",
    ),
    StagingEntry("player_dash_team_perf", "stg_player_dash_team_perf", "player"),
    StagingEntry("player_dash_yoy", "stg_player_dash_yoy", "player"),
    StagingEntry("player_dash_pt_pass", "stg_player_pt_pass", "player"),
    StagingEntry("player_dash_pt_reb", "stg_player_pt_reb", "player"),
    StagingEntry(
        "player_dash_pt_shot_defend",
        "stg_player_pt_shot_defend",
        "player",
    ),
    StagingEntry("player_dash_pt_shots", "stg_player_pt_shots", "player"),
    StagingEntry("player_game_logs_v2", "stg_player_game_logs_v2", "player"),
    StagingEntry("player_streak_finder", "stg_player_streak_finder", "player"),
    StagingEntry("player_next_games", "stg_player_next_games", "player"),
    StagingEntry("player_vs_player", "stg_player_vs_player", "player"),
    # Extractor-only aliases (player)
    StagingEntry("player_compare", "stg_player_compare", "player"),
    StagingEntry("player_dash_pt_defend", "stg_player_dash_pt_defend", "player"),
    StagingEntry(
        "player_dashboard_game_splits",
        "stg_player_dashboard_game_splits",
        "player",
    ),
    StagingEntry(
        "player_dashboard_general_splits",
        "stg_player_dashboard_general_splits",
        "player",
    ),
    StagingEntry(
        "player_dashboard_last_n_games",
        "stg_player_dashboard_last_n_games",
        "player",
    ),
    StagingEntry(
        "player_dashboard_shooting_splits",
        "stg_player_dashboard_shooting_splits",
        "player",
    ),
    StagingEntry(
        "player_dashboard_team_performance",
        "stg_player_dashboard_team_performance",
        "player",
    ),
    StagingEntry(
        "player_dashboard_year_over_year",
        "stg_player_dashboard_year_over_year",
        "player",
    ),
    StagingEntry("player_game_log", "stg_player_game_log", "player_season"),
    StagingEntry("player_game_streak_finder", "stg_player_game_streak_finder", "player"),
    # Team-level additions
    StagingEntry(
        "team_dashboard_general_splits",
        "stg_team_dash_general_splits",
        "team",
    ),
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_dash_shooting_splits",
        "team",
    ),
    StagingEntry("team_dash_lineups", "stg_team_lineups", "team"),
    StagingEntry("team_dash_pt_pass", "stg_team_pt_pass", "team"),
    StagingEntry("team_dash_pt_reb", "stg_team_pt_reb", "team"),
    StagingEntry("team_dash_pt_shots", "stg_team_pt_shots", "team"),
    StagingEntry("team_details", "stg_team_details", "team"),
    StagingEntry("team_info_common", "stg_team_info_common", "team"),
    StagingEntry("team_historical_leaders", "stg_team_historical_leaders", "team"),
    StagingEntry("team_year_by_year", "stg_team_year_by_year", "team"),
    StagingEntry("common_team_years", "stg_team_years", "team"),
    StagingEntry("team_player_dashboard", "stg_team_player_dashboard", "team"),
    StagingEntry("cume_stats_team", "stg_cume_team", "team"),
    StagingEntry("cume_stats_team_games", "stg_cume_team_games", "team"),
    StagingEntry("franchise_leaders", "stg_franchise_leaders", "team"),
    StagingEntry("franchise_players", "stg_franchise_players", "team"),
    StagingEntry("team_game_logs", "stg_team_game_logs_v2", "team"),
    StagingEntry("team_game_streak_finder", "stg_team_streak_finder", "team"),
    StagingEntry("team_vs_player", "stg_team_vs_player", "team"),
    StagingEntry("team_and_players_vs", "stg_team_and_players_vs", "team"),
    # Extractor-only aliases (team)
    StagingEntry(
        "team_and_players_vs_players",
        "stg_team_and_players_vs_players",
        "team",
    ),
    StagingEntry("team_game_log", "stg_team_game_log", "team_season"),
    StagingEntry("team_year_by_year_stats", "stg_team_year_by_year_stats", "team"),
    # Static additions
    StagingEntry("league_game_finder", "stg_league_game_finder", "static"),
    StagingEntry("player_college_rollup", "stg_player_college_rollup", "static"),
    StagingEntry(
        "player_career_by_college_rollup",
        "stg_player_career_by_college_rollup",
        "static",
    ),
    StagingEntry("draft_board", "stg_draft_board", "season"),
    # Game-level — FanDuel infographic per player per game
    StagingEntry("infographic_fanduel_player", "stg_fanduel_player", "game"),
    # Player-level — Fantasy profile bar graph
    StagingEntry("player_fantasy_profile", "stg_player_fantasy_profile", "player"),
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
