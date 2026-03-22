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
        "player_team_season",
        "team_season",
        "static",
        "date",
    ]
    result_set_index: int = 0
    use_multi: bool = False
    deprecated_after: str | None = None
    """ISO date (YYYY-MM-DD) after which this entry should be skipped.

    Used for V2 endpoints superseded by V3 — historical data is still valid
    but current data is unreliable after the cutoff date.
    """
    min_season: int | None = None
    """Earliest season year (e.g. 2013) for which this endpoint returns data.

    The orchestrator skips API calls for seasons before this threshold.
    ``None`` means the endpoint is available for all historical seasons.

    Common thresholds:
    - 2013: Player tracking, hustle stats, matchups
    - 2016: Hustle box scores
    - 2020: IST / In-Season Tournament standings
    - 2023: BoxScoreSummaryV3, DunkScoreLeaders
    """


STAGING_MAP: list[StagingEntry] = [
    # ── Season-level (13) ─────────────────────────────────────────
    StagingEntry("league_game_log", "stg_league_game_log", "season"),
    StagingEntry(
        "schedule",
        "stg_schedule",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "schedule",
        "stg_schedule_weeks",
        "season",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "schedule_int",
        "stg_schedule_int",
        "season",
        result_set_index=0,
        use_multi=True,
        min_season=2016,
    ),
    StagingEntry(
        "schedule_int",
        "stg_schedule_int_weeks",
        "season",
        result_set_index=1,
        use_multi=True,
        min_season=2016,
    ),
    # BroadcasterList (result_set_index=2) deferred — no consuming transform
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
    StagingEntry("synergy_play_types", "stg_synergy", "season", min_season=2015),
    StagingEntry("league_dash_pt_defend", "stg_tracking_defense", "season", min_season=2013),
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
    StagingEntry(
        "box_score_traditional",
        "stg_box_score_traditional",
        "game",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_traditional",
        "stg_box_score_traditional_starter_bench",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_traditional",
        "stg_box_score_traditional_team",
        "game",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_advanced", "stg_box_score_advanced", "game", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "box_score_misc", "stg_box_score_misc", "game", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "box_score_scoring", "stg_box_score_scoring", "game", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "box_score_usage", "stg_box_score_usage", "game", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "box_score_four_factors",
        "stg_box_score_four_factors_player",
        "game",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_hustle",
        "stg_box_score_hustle",
        "game",
        result_set_index=1,
        use_multi=True,
        min_season=2016,
    ),
    StagingEntry(
        "box_score_player_track",
        "stg_box_score_player_track",
        "game",
        result_set_index=0,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "box_score_defensive",
        "stg_box_score_defensive",
        "game",
        result_set_index=0,
        use_multi=True,
        min_season=2016,
    ),
    StagingEntry("play_by_play", "stg_play_by_play", "game", result_set_index=0, use_multi=True),
    StagingEntry(
        "win_probability",
        "stg_win_probability",
        "game",
        result_set_index=0,
        use_multi=True,
        min_season=2015,
    ),
    StagingEntry("video_events", "stg_video_events", "game"),
    StagingEntry("box_score_matchups", "stg_matchup", "game", min_season=2016),
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
        min_season=2023,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_game_info",
        "game",
        result_set_index=1,
        use_multi=True,
        min_season=2023,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_arena_info",
        "game",
        result_set_index=2,
        use_multi=True,
        min_season=2023,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_officials",
        "game",
        result_set_index=3,
        use_multi=True,
        min_season=2023,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_line_score",
        "game",
        result_set_index=4,
        use_multi=True,
        min_season=2023,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_inactive_players",
        "game",
        result_set_index=5,
        use_multi=True,
        min_season=2023,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_last_five_meetings",
        "game",
        result_set_index=6,
        use_multi=True,
        min_season=2023,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_other_stats",
        "game",
        result_set_index=7,
        use_multi=True,
        min_season=2023,
    ),
    StagingEntry(
        "box_score_summary_v3",
        "stg_summary_v3_available_video",
        "game",
        result_set_index=8,
        use_multi=True,
        min_season=2023,
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
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard",
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
    StagingEntry("video_status", "stg_video_status", "date"),
    # ── Player-level (6) ──────────────────────────────────────────
    StagingEntry(
        "common_player_info",
        "stg_player_available_seasons",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "common_player_info",
        "stg_player_info",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "common_player_info",
        "stg_player_headline_stats",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry("player_awards", "stg_player_awards", "player"),
    StagingEntry("player_career_by_college", "stg_player_college", "player"),
    StagingEntry(
        "shot_chart_detail",
        "stg_shot_chart",
        "player",
        result_set_index=0,
        use_multi=True,
        min_season=1996,
    ),
    StagingEntry("player_estimated_metrics", "stg_player_tracking", "season", min_season=2013),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_dashboard_clutch",
        "player",
        result_set_index=10,
        use_multi=True,
    ),
    # ── Team-level (4) ────────────────────────────────────────────
    StagingEntry(
        "common_team_roster",
        "stg_coaches",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "common_team_roster",
        "stg_team_info",
        "team",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "team_estimated_metrics",
        "stg_team_dashboard_estimated",
        "season",
        min_season=2013,
    ),
    StagingEntry(
        "team_player_on_off_details",
        "stg_team_dashboard_on_off",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_player_on_off_summary", "stg_on_off", "team", result_set_index=0, use_multi=True
    ),
    # ── Static (2) ────────────────────────────────────────────────
    StagingEntry(
        "franchise_history",
        "stg_franchise",
        "static",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "franchise_history",
        "stg_defunct_teams",
        "static",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "all_time_leaders_grids",
        "stg_all_time",
        "static",
        result_set_index=0,
        use_multi=True,
    ),
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
    StagingEntry("ist_standings", "stg_ist_standings", "season", min_season=2020),
    StagingEntry("common_playoff_series", "stg_common_playoff_series", "season"),
    # --- merged from patch files ---
    # Season-level additions
    StagingEntry("league_hustle_player", "stg_league_hustle_player", "season", min_season=2016),
    StagingEntry("league_hustle_team", "stg_league_hustle_team", "season", min_season=2016),
    StagingEntry("league_dash_pt_stats", "stg_league_pt_stats", "season", min_season=2013),
    StagingEntry(
        "league_dash_pt_team_defend", "stg_league_pt_team_defend", "season", min_season=2013
    ),
    StagingEntry("league_dash_team_pt_shot", "stg_league_team_pt_shot", "season", min_season=2013),
    StagingEntry("league_dash_opp_pt_shot", "stg_league_opp_pt_shot", "season", min_season=2013),
    StagingEntry(
        "league_dash_player_pt_shot", "stg_league_player_pt_shot", "season", min_season=2013
    ),
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
    StagingEntry("dunk_score_leaders", "stg_dunk_score_leaders", "season", min_season=2023),
    StagingEntry("gravity_leaders", "stg_gravity_leaders", "season", min_season=2023),
    StagingEntry(
        "leaders_tiles",
        "stg_leaders_tiles",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "homepage_leaders",
        "stg_homepage_leaders",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "homepage_v2",
        "stg_homepage_v2",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "league_player_on_details", "stg_player_on_details", "team_season", min_season=2013
    ),
    StagingEntry("league_season_matchups", "stg_season_matchups", "season", min_season=2016),
    StagingEntry("matchups_rollup", "stg_matchups_rollup", "season", min_season=2016),
    # defense_hub index 0 covered by stg_defense_hub_stat1 in Phase 4 multi-result section
    StagingEntry("shot_chart_league_wide", "stg_shot_chart_league_wide", "season", min_season=1996),
    # Requires group_id (lineup ID) — not available in season-pattern sweep
    StagingEntry(
        "shot_chart_lineup",
        "stg_shot_chart_lineup",
        "season",
        result_set_index=0,
        use_multi=True,
        min_season=1996,
        deprecated_after="2000-01-01",
    ),
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
    StagingEntry(
        "home_page_leaders",
        "stg_home_page_leaders",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "home_page_v2",
        "stg_home_page_v2",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "league_dash_player_bio_stats",
        "stg_league_dash_player_bio_stats",
        "season",
    ),
    StagingEntry(
        "league_hustle_stats_player",
        "stg_league_hustle_stats_player",
        "season",
        min_season=2016,
    ),
    StagingEntry(
        "league_hustle_stats_team", "stg_league_hustle_stats_team", "season", min_season=2016
    ),
    StagingEntry("player_game_logs", "stg_player_game_logs", "season"),
    StagingEntry("player_index", "stg_player_index", "season"),
    # Requires group_id (lineup ID) — not available in season-pattern sweep
    StagingEntry(
        "shot_chart_lineup_detail",
        "stg_shot_chart_lineup_detail",
        "season",
        result_set_index=0,
        use_multi=True,
        min_season=1996,
        deprecated_after="2000-01-01",
    ),
    # Game-level additions
    StagingEntry(
        "hustle_stats_box_score",
        "stg_box_score_hustle_box",
        "game",
        result_set_index=1,
        use_multi=True,
        min_season=2016,
    ),
    StagingEntry(
        "hustle_stats_box_score",
        "stg_box_score_hustle_team",
        "game",
        result_set_index=2,
        use_multi=True,
        min_season=2016,
    ),
    StagingEntry(
        "play_by_play_v2", "stg_play_by_play_v2", "game", result_set_index=0, use_multi=True
    ),
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
    StagingEntry(
        "cume_stats_player",
        "stg_cume_player",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry("cume_stats_player_games", "stg_cume_player_games", "player"),
    StagingEntry(
        "player_dash_game_splits",
        "stg_player_dash_game_splits",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_dash_general_splits",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_last_n_games",
        "stg_player_dash_last_n_games",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_dash_shooting_splits",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_team_perf",
        "stg_player_dash_team_perf",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_yoy",
        "stg_player_dash_yoy",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_pt_pass",
        "stg_player_pt_pass",
        "player",
        result_set_index=0,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_pass",
        "stg_player_pt_pass_received",
        "player",
        result_set_index=1,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_reb",
        "stg_player_pt_reb",
        "player",
        result_set_index=0,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_shot_defend",
        "stg_player_pt_shot_defend",
        "player",
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_shots",
        "stg_player_pt_shots",
        "player",
        result_set_index=0,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry("player_game_logs_v2", "stg_player_game_logs_v2", "player"),
    StagingEntry("player_streak_finder", "stg_player_streak_finder", "player"),
    StagingEntry("player_next_games", "stg_player_next_games", "player"),
    StagingEntry(
        "player_vs_player",
        "stg_player_vs_player",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    # Extractor-only aliases (player)
    StagingEntry(
        "player_compare",
        "stg_player_compare",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry("player_dash_pt_defend", "stg_player_dash_pt_defend", "player", min_season=2013),
    StagingEntry(
        "player_dashboard_game_splits",
        "stg_player_dashboard_game_splits",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_general_splits",
        "stg_player_dashboard_general_splits",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_last_n_games",
        "stg_player_dashboard_last_n_games",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_shooting_splits",
        "stg_player_dashboard_shooting_splits",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_team_performance",
        "stg_player_dashboard_team_performance",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_year_over_year",
        "stg_player_dashboard_year_over_year",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry("player_game_log", "stg_player_game_log", "player_season"),
    # PlayerFantasyProfile exposes LastFiveGamesAvg + SeasonAvg for player seasons.
    StagingEntry(
        "player_fantasy_profile",
        "stg_player_fantasy_profile_last_five_games_avg",
        "player_season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_fantasy_profile",
        "stg_player_fantasy_profile_season_avg",
        "player_season",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "gl_alum_box_score_similarity_score",
        "stg_gl_alum_box_score_similarity_score",
        "player_season",
    ),
    StagingEntry("video_details", "stg_video_details", "player_team_season"),
    StagingEntry("video_details_asset", "stg_video_details_asset", "player_team_season"),
    StagingEntry("player_game_streak_finder", "stg_player_game_streak_finder", "player"),
    # Team-level additions
    StagingEntry(
        "team_dashboard_general_splits",
        "stg_team_dash_general_splits",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_dash_shooting_splits",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_dash_lineups", "stg_team_lineups", "team", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "team_dash_pt_pass",
        "stg_team_pt_pass",
        "team",
        result_set_index=0,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_pass",
        "stg_team_pt_pass_received",
        "team",
        result_set_index=1,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_reb",
        "stg_team_pt_reb",
        "team",
        result_set_index=0,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_shots",
        "stg_team_pt_shots",
        "team",
        result_set_index=0,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry("team_details", "stg_team_details", "team", result_set_index=0, use_multi=True),
    StagingEntry(
        "team_info_common",
        "stg_team_info_common",
        "team",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "team_info_common",
        "stg_team_season_ranks",
        "team",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry("team_historical_leaders", "stg_team_historical_leaders", "team"),
    StagingEntry("team_year_by_year", "stg_team_year_by_year", "team"),
    StagingEntry("common_team_years", "stg_team_years", "team"),
    StagingEntry(
        "team_player_dashboard",
        "stg_team_player_dashboard",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "cume_stats_team",
        "stg_cume_team",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry("cume_stats_team_games", "stg_cume_team_games", "team"),
    StagingEntry("franchise_leaders", "stg_franchise_leaders", "team"),
    StagingEntry("franchise_players", "stg_franchise_players", "team"),
    StagingEntry("team_game_logs", "stg_team_game_logs_v2", "team"),
    StagingEntry("team_game_streak_finder", "stg_team_streak_finder", "team"),
    StagingEntry(
        "team_vs_player",
        "stg_team_vs_player",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_and_players_vs",
        "stg_team_and_players_vs",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    # Extractor-only aliases (team)
    StagingEntry(
        "team_and_players_vs_players",
        "stg_team_and_players_vs_players",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry("team_game_log", "stg_team_game_log", "team_season"),
    StagingEntry("team_year_by_year_stats", "stg_team_year_by_year_stats", "team"),
    # Static additions
    StagingEntry("league_game_finder", "stg_league_game_finder", "static"),
    StagingEntry(
        "player_college_rollup",
        "stg_player_college_rollup",
        "static",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_career_by_college_rollup",
        "stg_player_career_by_college_rollup",
        "static",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry("draft_board", "stg_draft_board", "season"),
    StagingEntry("fantasy_widget", "stg_fantasy_widget", "season"),
    # Game-level — FanDuel infographic per player per game
    StagingEntry("infographic_fanduel_player", "stg_fanduel_player", "game"),
    # ── Phase 1: Box Score Team Stats ────────────────────────────────
    StagingEntry(
        "box_score_advanced",
        "stg_box_score_advanced_team",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_misc",
        "stg_box_score_misc_team",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_scoring",
        "stg_box_score_scoring_team",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_usage",
        "stg_box_score_usage_team",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_four_factors",
        "stg_box_score_four_factors_team",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "box_score_player_track",
        "stg_box_score_player_track_team",
        "game",
        result_set_index=1,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "box_score_defensive",
        "stg_box_score_defensive_team",
        "game",
        result_set_index=1,
        use_multi=True,
        min_season=2016,
    ),
    StagingEntry(
        "box_score_hustle",
        "stg_box_score_hustle_player",
        "game",
        result_set_index=0,
        use_multi=True,
        min_season=2016,
    ),
    # ── Phase 2: Player Dashboard Multi-Result ───────────────────────
    # PlayerDashboardByClutch (11 sets)
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last10sec_3pt2",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last10sec_3pt",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last1min_5pt",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last1min_pm5",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last30sec_3pt2",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last30sec_3pt",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last3min_5pt",
        "player",
        result_set_index=6,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last3min_pm5",
        "player",
        result_set_index=7,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last5min_5pt",
        "player",
        result_set_index=8,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_last5min_pm5",
        "player",
        result_set_index=9,
        use_multi=True,
    ),
    StagingEntry(
        "player_dashboard_clutch",
        "stg_player_clutch_overall",
        "player",
        result_set_index=10,
        use_multi=True,
    ),
    # PlayerDashboardByGameSplits (5 sets)
    StagingEntry(
        "player_dash_game_splits",
        "stg_player_split_actual_margin",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_game_splits",
        "stg_player_split_by_half",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_game_splits",
        "stg_player_split_by_period",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_game_splits",
        "stg_player_split_score_margin",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_game_splits",
        "stg_player_split_game_overall",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    # PlayerDashboardByGeneralSplits (7 sets)
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_split_days_rest",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_split_location",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_split_month",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_split_general_overall",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_split_pre_post_allstar",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_split_starting_pos",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_general_splits",
        "stg_player_split_wins_losses",
        "player",
        result_set_index=6,
        use_multi=True,
    ),
    # PlayerDashboardByLastNGames (6 sets)
    StagingEntry(
        "player_dash_last_n_games",
        "stg_player_lastn_game_number",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_last_n_games",
        "stg_player_lastn_last10",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_last_n_games",
        "stg_player_lastn_last15",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_last_n_games",
        "stg_player_lastn_last20",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_last_n_games",
        "stg_player_lastn_last5",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_last_n_games",
        "stg_player_lastn_overall",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    # PlayerDashboardByShootingSplits (8 sets)
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_shoot_assisted_by",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_shoot_assisted_shot",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_shoot_overall",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_shoot_5ft",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_shoot_8ft",
        "player",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_shoot_area",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_shoot_type",
        "player",
        result_set_index=6,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_shooting_splits",
        "stg_player_shoot_type_summary",
        "player",
        result_set_index=7,
        use_multi=True,
    ),
    # PlayerDashboardByTeamPerformance (4 sets)
    StagingEntry(
        "player_dash_team_perf",
        "stg_player_perf_overall",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_team_perf",
        "stg_player_perf_pts_scored",
        "player",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_team_perf",
        "stg_player_perf_pts_against",
        "player",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_dash_team_perf",
        "stg_player_perf_score_diff",
        "player",
        result_set_index=3,
        use_multi=True,
    ),
    # PlayerDashboardByYearOverYear (2 sets)
    StagingEntry(
        "player_dash_yoy", "stg_player_yoy_by_year", "player", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "player_dash_yoy", "stg_player_yoy_overall", "player", result_set_index=1, use_multi=True
    ),
    # ── Phase 2: Team Dashboard Multi-Result ─────────────────────────
    # TeamDashboardByGeneralSplits (6 sets)
    StagingEntry(
        "team_dashboard_general_splits",
        "stg_team_split_days_rest",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_general_splits",
        "stg_team_split_location",
        "team",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_general_splits",
        "stg_team_split_month",
        "team",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_general_splits",
        "stg_team_split_general_overall",
        "team",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_general_splits",
        "stg_team_split_pre_post_allstar",
        "team",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_general_splits",
        "stg_team_split_wins_losses",
        "team",
        result_set_index=5,
        use_multi=True,
    ),
    # TeamDashboardByShootingSplits (7 sets)
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_shoot_assisted_by",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_shoot_assisted_shot",
        "team",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_shoot_overall",
        "team",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_shoot_5ft",
        "team",
        result_set_index=3,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_shoot_8ft",
        "team",
        result_set_index=4,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_shoot_area",
        "team",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "team_dashboard_shooting_splits",
        "stg_team_shoot_type",
        "team",
        result_set_index=6,
        use_multi=True,
    ),
    # ── Phase 3: Tracking Detail Sets ────────────────────────────────
    # PlayerDashPtShots (7 sets — index 0 already captured as stg_player_pt_shots)
    StagingEntry(
        "player_dash_pt_shots",
        "stg_player_pt_shots_closest_def",
        "player",
        result_set_index=1,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_shots",
        "stg_player_pt_shots_dribble",
        "player",
        result_set_index=2,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_shots",
        "stg_player_pt_shots_general",
        "player",
        result_set_index=3,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_shots",
        "stg_player_pt_shots_overall",
        "player",
        result_set_index=4,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_shots",
        "stg_player_pt_shots_shot_clock",
        "player",
        result_set_index=5,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_shots",
        "stg_player_pt_shots_touch_time",
        "player",
        result_set_index=6,
        use_multi=True,
        min_season=2013,
    ),
    # PlayerDashPtReb (5 sets — index 0 already captured as stg_player_pt_reb)
    StagingEntry(
        "player_dash_pt_reb",
        "stg_player_pt_reb_overall",
        "player",
        result_set_index=1,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_reb",
        "stg_player_pt_reb_distance",
        "player",
        result_set_index=2,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_reb",
        "stg_player_pt_reb_shot_dist",
        "player",
        result_set_index=3,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "player_dash_pt_reb",
        "stg_player_pt_reb_shot_type",
        "player",
        result_set_index=4,
        use_multi=True,
        min_season=2013,
    ),
    # TeamDashPtShots (6 sets — index 0 already captured as stg_team_pt_shots)
    StagingEntry(
        "team_dash_pt_shots",
        "stg_team_pt_shots_closest_def",
        "team",
        result_set_index=1,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_shots",
        "stg_team_pt_shots_dribble",
        "team",
        result_set_index=2,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_shots",
        "stg_team_pt_shots_general",
        "team",
        result_set_index=3,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_shots",
        "stg_team_pt_shots_shot_clock",
        "team",
        result_set_index=4,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_shots",
        "stg_team_pt_shots_touch_time",
        "team",
        result_set_index=5,
        use_multi=True,
        min_season=2013,
    ),
    # TeamDashPtReb (5 sets — index 0 already captured as stg_team_pt_reb)
    StagingEntry(
        "team_dash_pt_reb",
        "stg_team_pt_reb_overall",
        "team",
        result_set_index=1,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_reb",
        "stg_team_pt_reb_distance",
        "team",
        result_set_index=2,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_reb",
        "stg_team_pt_reb_shot_dist",
        "team",
        result_set_index=3,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "team_dash_pt_reb",
        "stg_team_pt_reb_shot_type",
        "team",
        result_set_index=4,
        use_multi=True,
        min_season=2013,
    ),
    # TeamDashLineups (2 sets)
    StagingEntry(
        "team_dash_lineups", "stg_team_lineups_overall", "team", result_set_index=1, use_multi=True
    ),
    # ── Phase 4: Team Details (8 sets — index 0 already captured as stg_team_details)
    StagingEntry(
        "team_details", "stg_team_awards_conf", "team", result_set_index=1, use_multi=True
    ),
    StagingEntry("team_details", "stg_team_awards_div", "team", result_set_index=2, use_multi=True),
    StagingEntry("team_details", "stg_team_background", "team", result_set_index=3, use_multi=True),
    StagingEntry("team_details", "stg_team_history", "team", result_set_index=4, use_multi=True),
    StagingEntry("team_details", "stg_team_hof", "team", result_set_index=5, use_multi=True),
    StagingEntry("team_details", "stg_team_retired", "team", result_set_index=6, use_multi=True),
    StagingEntry(
        "team_details", "stg_team_social_sites", "team", result_set_index=7, use_multi=True
    ),
    # ── Phase 5: Leaders Multi-Result ────────────────────────────────
    # AllTimeLeadersGrids (19 sets — all stat categories)
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_ast", "static", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_blk", "static", result_set_index=1, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_dreb", "static", result_set_index=2, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_fg3a", "static", result_set_index=3, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_fg3m", "static", result_set_index=4, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids",
        "stg_all_time_fg3_pct",
        "static",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_fga", "static", result_set_index=6, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_fgm", "static", result_set_index=7, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids",
        "stg_all_time_fg_pct",
        "static",
        result_set_index=8,
        use_multi=True,
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_fta", "static", result_set_index=9, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_ftm", "static", result_set_index=10, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids",
        "stg_all_time_ft_pct",
        "static",
        result_set_index=11,
        use_multi=True,
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_gp", "static", result_set_index=12, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_oreb", "static", result_set_index=13, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_pf", "static", result_set_index=14, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_pts", "static", result_set_index=15, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_reb", "static", result_set_index=16, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_stl", "static", result_set_index=17, use_multi=True
    ),
    StagingEntry(
        "all_time_leaders_grids", "stg_all_time_tov", "static", result_set_index=18, use_multi=True
    ),
    # DefenseHub (10 sets)
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat1",
        "season",
        result_set_index=0,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat10",
        "season",
        result_set_index=1,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat2",
        "season",
        result_set_index=2,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat3",
        "season",
        result_set_index=3,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat4",
        "season",
        result_set_index=4,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat5",
        "season",
        result_set_index=5,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat6",
        "season",
        result_set_index=6,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat7",
        "season",
        result_set_index=7,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat8",
        "season",
        result_set_index=8,
        use_multi=True,
        min_season=2013,
    ),
    StagingEntry(
        "defense_hub",
        "stg_defense_hub_stat9",
        "season",
        result_set_index=9,
        use_multi=True,
        min_season=2013,
    ),
    # HomePageV2 (8 sets)
    StagingEntry(
        "homepage_v2", "stg_homepage_v2_stat1", "season", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "homepage_v2", "stg_homepage_v2_stat2", "season", result_set_index=1, use_multi=True
    ),
    StagingEntry(
        "homepage_v2", "stg_homepage_v2_stat3", "season", result_set_index=2, use_multi=True
    ),
    StagingEntry(
        "homepage_v2", "stg_homepage_v2_stat4", "season", result_set_index=3, use_multi=True
    ),
    StagingEntry(
        "homepage_v2", "stg_homepage_v2_stat5", "season", result_set_index=4, use_multi=True
    ),
    StagingEntry(
        "homepage_v2", "stg_homepage_v2_stat6", "season", result_set_index=5, use_multi=True
    ),
    StagingEntry(
        "homepage_v2", "stg_homepage_v2_stat7", "season", result_set_index=6, use_multi=True
    ),
    StagingEntry(
        "homepage_v2", "stg_homepage_v2_stat8", "season", result_set_index=7, use_multi=True
    ),
    # HomePageLeaders (3 sets)
    StagingEntry(
        "homepage_leaders",
        "stg_homepage_leaders_main",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "homepage_leaders",
        "stg_homepage_leaders_league_avg",
        "season",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "homepage_leaders",
        "stg_homepage_leaders_league_max",
        "season",
        result_set_index=2,
        use_multi=True,
    ),
    # LeadersTiles (4 sets)
    StagingEntry(
        "leaders_tiles",
        "stg_leaders_tiles_alltime_high",
        "season",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "leaders_tiles",
        "stg_leaders_tiles_last_season",
        "season",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "leaders_tiles", "stg_leaders_tiles_main", "season", result_set_index=2, use_multi=True
    ),
    StagingEntry(
        "leaders_tiles",
        "stg_leaders_tiles_low_season",
        "season",
        result_set_index=3,
        use_multi=True,
    ),
    # ── Phase 5: Comparison Multi-Result ─────────────────────────────
    # PlayerVsPlayer (10 sets)
    StagingEntry(
        "player_vs_player", "stg_pvp_on_off_court", "player", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "player_vs_player", "stg_pvp_overall", "player", result_set_index=1, use_multi=True
    ),
    StagingEntry(
        "player_vs_player", "stg_pvp_player_info", "player", result_set_index=2, use_multi=True
    ),
    StagingEntry(
        "player_vs_player", "stg_pvp_shot_area_off", "player", result_set_index=3, use_multi=True
    ),
    StagingEntry(
        "player_vs_player", "stg_pvp_shot_area_on", "player", result_set_index=4, use_multi=True
    ),
    StagingEntry(
        "player_vs_player",
        "stg_pvp_shot_area_overall",
        "player",
        result_set_index=5,
        use_multi=True,
    ),
    StagingEntry(
        "player_vs_player", "stg_pvp_shot_dist_off", "player", result_set_index=6, use_multi=True
    ),
    StagingEntry(
        "player_vs_player", "stg_pvp_shot_dist_on", "player", result_set_index=7, use_multi=True
    ),
    StagingEntry(
        "player_vs_player",
        "stg_pvp_shot_dist_overall",
        "player",
        result_set_index=8,
        use_multi=True,
    ),
    StagingEntry(
        "player_vs_player", "stg_pvp_vs_player_info", "player", result_set_index=9, use_multi=True
    ),
    # TeamVsPlayer (9 sets)
    StagingEntry(
        "team_vs_player", "stg_tvp_on_off_court", "team", result_set_index=0, use_multi=True
    ),
    StagingEntry("team_vs_player", "stg_tvp_overall", "team", result_set_index=1, use_multi=True),
    StagingEntry(
        "team_vs_player", "stg_tvp_shot_area_off", "team", result_set_index=2, use_multi=True
    ),
    StagingEntry(
        "team_vs_player", "stg_tvp_shot_area_on", "team", result_set_index=3, use_multi=True
    ),
    StagingEntry(
        "team_vs_player", "stg_tvp_shot_area_overall", "team", result_set_index=4, use_multi=True
    ),
    StagingEntry(
        "team_vs_player", "stg_tvp_shot_dist_off", "team", result_set_index=5, use_multi=True
    ),
    StagingEntry(
        "team_vs_player", "stg_tvp_shot_dist_on", "team", result_set_index=6, use_multi=True
    ),
    StagingEntry(
        "team_vs_player", "stg_tvp_shot_dist_overall", "team", result_set_index=7, use_multi=True
    ),
    StagingEntry(
        "team_vs_player", "stg_tvp_vs_player_overall", "team", result_set_index=8, use_multi=True
    ),
    # TeamAndPlayersVsPlayers (5 sets)
    StagingEntry(
        "team_and_players_vs", "stg_tapvp_players_vs", "team", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "team_and_players_vs", "stg_tapvp_team_off", "team", result_set_index=1, use_multi=True
    ),
    StagingEntry(
        "team_and_players_vs", "stg_tapvp_team_on", "team", result_set_index=2, use_multi=True
    ),
    StagingEntry(
        "team_and_players_vs", "stg_tapvp_team_vs", "team", result_set_index=3, use_multi=True
    ),
    StagingEntry(
        "team_and_players_vs", "stg_tapvp_team_vs_off", "team", result_set_index=4, use_multi=True
    ),
    # TeamPlayerOnOffDetails (3 sets)
    StagingEntry(
        "team_player_on_off_details",
        "stg_on_off_details_overall",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_player_on_off_details",
        "stg_on_off_details_off_court",
        "team",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "team_player_on_off_details",
        "stg_on_off_details_on_court",
        "team",
        result_set_index=2,
        use_multi=True,
    ),
    # TeamPlayerOnOffSummary (3 sets)
    StagingEntry(
        "team_player_on_off_summary",
        "stg_on_off_summary_overall",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_player_on_off_summary",
        "stg_on_off_summary_off_court",
        "team",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "team_player_on_off_summary",
        "stg_on_off_summary_on_court",
        "team",
        result_set_index=2,
        use_multi=True,
    ),
    # TeamPlayerDashboard (2 sets)
    StagingEntry(
        "team_player_dashboard",
        "stg_team_player_dash_players",
        "team",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "team_player_dashboard",
        "stg_team_player_dash_overall",
        "team",
        result_set_index=1,
        use_multi=True,
    ),
    # ── Phase 5: Misc Multi-Result ───────────────────────────────────
    # CumeStatsPlayer (2 sets)
    StagingEntry(
        "cume_stats_player",
        "stg_cume_player_game_by_game",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "cume_stats_player", "stg_cume_player_totals", "player", result_set_index=1, use_multi=True
    ),
    # CumeStatsTeam (2 sets)
    StagingEntry(
        "cume_stats_team", "stg_cume_team_game_by_game", "team", result_set_index=0, use_multi=True
    ),
    StagingEntry(
        "cume_stats_team", "stg_cume_team_totals", "team", result_set_index=1, use_multi=True
    ),
    # PlayerCompare (2 sets)
    StagingEntry(
        "player_compare",
        "stg_player_compare_individual",
        "player",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_compare", "stg_player_compare_overall", "player", result_set_index=1, use_multi=True
    ),
    # PlayerCareerByCollegeRollup (4 sets — regional breakdowns)
    StagingEntry(
        "player_college_rollup",
        "stg_college_rollup_east",
        "static",
        result_set_index=0,
        use_multi=True,
    ),
    StagingEntry(
        "player_college_rollup",
        "stg_college_rollup_midwest",
        "static",
        result_set_index=1,
        use_multi=True,
    ),
    StagingEntry(
        "player_college_rollup",
        "stg_college_rollup_south",
        "static",
        result_set_index=2,
        use_multi=True,
    ),
    StagingEntry(
        "player_college_rollup",
        "stg_college_rollup_west",
        "static",
        result_set_index=3,
        use_multi=True,
    ),
    # ShotChartDetail (2 sets)
    StagingEntry(
        "shot_chart_detail",
        "stg_shot_chart_league_averages",
        "player",
        result_set_index=1,
        use_multi=True,
        min_season=1996,
    ),
    # ShotChartLineupDetail (2 sets)
    # Requires group_id (lineup ID) — not available in season-pattern sweep
    StagingEntry(
        "shot_chart_lineup_detail",
        "stg_shot_chart_lineup_league_avg",
        "season",
        result_set_index=1,
        use_multi=True,
        min_season=1996,
        deprecated_after="2000-01-01",
    ),
    # HustleStatsBoxScore — missing index 0 (HustleStatsAvailable)
    StagingEntry(
        "hustle_stats_box_score",
        "stg_hustle_stats_available",
        "game",
        result_set_index=0,
        use_multi=True,
        min_season=2016,
    ),
    # TeamInfoCommon — missing index 0 (AvailableSeasons)
    StagingEntry(
        "team_info_common", "stg_team_available_seasons", "team", result_set_index=0, use_multi=True
    ),
    # WinProbabilityPBP (2 sets) — capture the PBP detail at index 1
    StagingEntry(
        "win_probability",
        "stg_win_prob_pbp",
        "game",
        result_set_index=1,
        use_multi=True,
        min_season=2015,
    ),
    # PlayByPlayV3 — capture AvailableVideo at index 1
    StagingEntry(
        "play_by_play",
        "stg_play_by_play_video_available",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    # PlayByPlayV2 — index 0 already captured as stg_play_by_play_v2
    StagingEntry(
        "play_by_play_v2",
        "stg_play_by_play_v2_video_available",
        "game",
        result_set_index=1,
        use_multi=True,
    ),
    # ScoreboardV2 — missing index 9 (WinProbability)
    StagingEntry(
        "scoreboard_v2",
        "stg_scoreboard_win_probability",
        "date",
        result_set_index=9,
        use_multi=True,
    ),
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


def get_by_endpoint(endpoint_name: str) -> list[StagingEntry]:
    """Return all staging entries for the given endpoint_name."""
    return [e for e in STAGING_MAP if e.endpoint_name == endpoint_name]


def get_unique_endpoints() -> list[str]:
    """Return sorted list of unique endpoint names in STAGING_MAP."""
    return sorted({e.endpoint_name for e in STAGING_MAP})


def get_unique_patterns() -> list[str]:
    """Return sorted list of unique param_patterns in STAGING_MAP."""
    return sorted({e.param_pattern for e in STAGING_MAP})
