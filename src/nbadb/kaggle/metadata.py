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
        "subtitle": ("Comprehensive NBA database: 131 endpoints, star schema, 58 tables"),
        "description": (
            "Complete NBA statistical database covering all "
            "available stats.nba.com endpoints. Normalized "
            "star schema with dimensions, facts, derived "
            "aggregations, and analytics views. Available in "
            "SQLite, DuckDB, Parquet, and CSV formats."
        ),
        "isPrivate": False,
        "licenses": [{"name": "CC-BY-SA-4.0"}],
        "keywords": [
            "basketball",
            "nba",
            "sports",
            "statistics",
            "analytics",
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
            "dim_player",
            "dim_team",
            "dim_team_history",
            "dim_game",
            "dim_season",
            "dim_date",
            "dim_official",
            "dim_coach",
            "dim_arena",
            "dim_season_phase",
            "dim_shot_zone",
            "dim_play_event_type",
            "dim_college",
        ],
        "facts": [
            "fact_player_game_traditional",
            "fact_player_game_advanced",
            "fact_player_game_misc",
            "fact_player_game_hustle",
            "fact_player_game_tracking",
            "fact_game_result",
            "fact_game_scoring",
            "fact_team_game_stats",
            "fact_play_by_play",
            "fact_win_probability",
            "fact_shot_chart",
            "fact_matchup",
            "fact_rotation",
            "fact_lineup_stats",
            "fact_standings",
            "fact_draft",
            "fact_synergy_play_type",
            "fact_tracking_defense",
            "fact_player_awards",
            "fact_player_estimated_metrics",
            "fact_team_estimated_metrics",
            "bridge_game_official",
            "bridge_play_player",
        ],
        "derived": [
            "agg_player_season",
            "agg_player_season_per36",
            "agg_player_season_per48",
            "agg_player_rolling",
            "agg_team_season",
            "agg_team_pace_and_efficiency",
            "agg_player_career",
            "agg_team_franchise",
            "agg_league_leaders",
            "agg_all_time_leaders",
            "agg_shot_zones",
            "agg_lineup_efficiency",
            "agg_on_off_splits",
            "agg_clutch_stats",
            "agg_shot_location_season",
        ],
        "analytics": [
            "analytics_player_game_complete",
            "analytics_player_season_complete",
            "analytics_team_season_summary",
            "analytics_head_to_head",
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
