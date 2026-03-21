from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.core.config import get_settings


def generate_metadata(output_path: Path) -> None:
    """Generate dataset-metadata.json from table catalog."""
    settings = get_settings()
    metadata = {
        "id": settings.kaggle_dataset,
        "id_no": None,
        "title": "Basketball",
        "subtitle": (
            "Comprehensive NBA database: 131 endpoints, "
            "141-table star schema (1946\u2013present)"
        ),
        "description": (
            "The most comprehensive open NBA database available. "
            "131 stats.nba.com endpoints extracted via nba_api, normalized into a "
            "141-table star schema with 17 dimensions, 102 facts, 2 bridges, "
            "16 derived aggregations, and 4 analytics views. "
            "Covers every NBA season from 1946-47 to present.\n\n"
            "Includes box scores (traditional, advanced, misc, hustle, four factors, tracking), "
            "play-by-play, shot charts, rotations, win probability, lineups, synergy play types, "
            "draft data, player tracking (speed, distance, touches, passes), awards, standings, "
            "and franchise history.\n\n"
            "Available in DuckDB, SQLite, Parquet (zstd-compressed), and CSV formats. "
            "10 companion Kaggle notebooks demonstrate analytics use cases including "
            "MVP prediction, game outcome modeling, player clustering, and shot chart analysis."
        ),
        "isPrivate": False,
        "licenses": [{"name": "CC-BY-SA-4.0"}],
        "keywords": [
            "basketball",
            "nba",
            "sports",
            "statistics",
            "analytics",
            "sports-analytics",
            "star-schema",
            "duckdb",
            "play-by-play",
            "shot-charts",
            "player-tracking",
            "machine-learning",
            "data-science",
            "polars",
        ],
        "collaborators": [],
        "data": [],
        "resources": _build_resources(),
    }
    output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    logger.info(f"Generated metadata at {output_path}")


def _build_resources() -> list[dict]:
    """Build resource entries for each exported table."""
    resources: list[dict] = []
    table_categories = {
        "dimensions": [
            "dim_all_players",
            "dim_arena",
            "dim_coach",
            "dim_college",
            "dim_date",
            "dim_defunct_team",
            "dim_game",
            "dim_official",
            "dim_play_event_type",
            "dim_player",
            "dim_season",
            "dim_season_phase",
            "dim_season_week",
            "dim_shot_zone",
            "dim_team",
            "dim_team_extended",
            "dim_team_history",
        ],
        "facts": [
            "bridge_game_official",
            "bridge_play_player",
            "fact_box_score_advanced_team",
            "fact_box_score_defensive_team",
            "fact_box_score_four_factors",
            "fact_box_score_four_factors_team",
            "fact_box_score_hustle_player",
            "fact_box_score_misc_team",
            "fact_box_score_player_track_team",
            "fact_box_score_scoring_team",
            "fact_box_score_starter_bench",
            "fact_box_score_summary_v3",
            "fact_box_score_team",
            "fact_box_score_usage_team",
            "fact_college_rollup",
            "fact_cumulative_stats",
            "fact_defense_hub",
            "fact_draft",
            "fact_draft_board",
            "fact_draft_combine_detail",
            "fact_fantasy",
            "fact_franchise_detail",
            "fact_game_context",
            "fact_game_leaders",
            "fact_game_result",
            "fact_game_scoring",
            "fact_homepage",
            "fact_homepage_leaders",
            "fact_ist_standings",
            "fact_leaders_tiles",
            "fact_league_dash_player_stats",
            "fact_league_dash_team_stats",
            "fact_league_game_finder",
            "fact_league_hustle",
            "fact_league_leaders_detail",
            "fact_league_lineup_viz",
            "fact_league_pt_shots",
            "fact_league_shot_locations",
            "fact_league_team_clutch",
            "fact_lineup_stats",
            "fact_matchup",
            "fact_play_by_play",
            "fact_player_available_seasons",
            "fact_player_awards",
            "fact_player_career",
            "fact_player_dashboard_clutch_overall",
            "fact_player_dashboard_game_splits_overall",
            "fact_player_dashboard_general_splits_overall",
            "fact_player_dashboard_last_n_overall",
            "fact_player_dashboard_shooting_overall",
            "fact_player_dashboard_team_perf_overall",
            "fact_player_dashboard_yoy_overall",
            "fact_player_estimated_metrics",
            "fact_player_game_advanced",
            "fact_player_game_hustle",
            "fact_player_game_log",
            "fact_player_game_misc",
            "fact_player_game_tracking",
            "fact_player_game_traditional",
            "fact_player_headline_stats",
            "fact_player_matchups",
            "fact_player_next_games",
            "fact_player_profile",
            "fact_player_pt_reb_detail",
            "fact_player_pt_shots_detail",
            "fact_player_pt_tracking",
            "fact_player_season_ranks",
            "fact_player_splits",
            "fact_playoff_picture",
            "fact_playoff_series",
            "fact_rotation",
            "fact_scoreboard_detail",
            "fact_scoreboard_v3",
            "fact_season_matchups",
            "fact_shot_chart",
            "fact_shot_chart_league",
            "fact_shot_chart_lineup",
            "fact_standings",
            "fact_streak_finder",
            "fact_synergy",
            "fact_team_awards_conf",
            "fact_team_awards_div",
            "fact_team_background",
            "fact_team_dashboard_general_overall",
            "fact_team_dashboard_shooting_overall",
            "fact_team_game",
            "fact_team_game_hustle",
            "fact_team_game_log",
            "fact_team_historical",
            "fact_team_history_detail",
            "fact_team_hof",
            "fact_team_lineups_overall",
            "fact_team_matchups",
            "fact_team_player_dashboard",
            "fact_team_pt_reb_detail",
            "fact_team_pt_shots_detail",
            "fact_team_pt_tracking",
            "fact_team_retired",
            "fact_team_season_ranks",
            "fact_team_social_sites",
            "fact_team_splits",
            "fact_team_estimated_metrics",
            "fact_tracking_defense",
            "fact_win_probability",
        ],
        "derived": [
            "agg_all_time_leaders",
            "agg_clutch_stats",
            "agg_league_leaders",
            "agg_lineup_efficiency",
            "agg_on_off_splits",
            "agg_player_bio",
            "agg_player_career",
            "agg_player_rolling",
            "agg_player_season",
            "agg_player_season_per36",
            "agg_player_season_per48",
            "agg_shot_location_season",
            "agg_shot_zones",
            "agg_team_franchise",
            "agg_team_pace_and_efficiency",
            "agg_team_season",
        ],
        "analytics": [
            "analytics_head_to_head",
            "analytics_player_game_complete",
            "analytics_player_season_complete",
            "analytics_team_season_summary",
        ],
    }
    for category, tables in table_categories.items():
        for table in tables:
            resources.append(
                {
                    "path": f"csv/{table}.csv",
                    "description": f"{table} ({category})",
                }
            )
    return resources
