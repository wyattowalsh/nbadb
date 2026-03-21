from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from functools import lru_cache

from nbadb.schemas.base import BaseSchema

_CAMEL_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")

_INPUT_SCHEMA_ALIASES: dict[str, str] = {
    # Staging schema aliases
    "stg_schedule": "stg_schedule_league_v2",
    "stg_standings": "stg_league_standings_v3",
    "stg_draft": "stg_draft_history",
    "stg_draft_combine": "stg_draft_combine_stats",
    "stg_synergy": "stg_synergy_play_types",
    "stg_box_score_traditional": "stg_box_score_traditional_player",
    "stg_box_score_advanced": "stg_box_score_advanced_player",
    "stg_box_score_hustle": "stg_box_score_hustle_player",
    "stg_box_score_defensive": "stg_box_score_defensive_player",
    "stg_play_by_play": "stg_play_by_play_v3",
    "stg_matchup": "stg_box_score_matchups",
    "stg_rotation_away": "stg_game_rotation",
    "stg_rotation_home": "stg_game_rotation",
    "stg_scoreboard": "stg_scoreboard_v2",
    "stg_shot_chart": "stg_shot_chart_detail",
    "stg_team_years": "stg_common_team_years",
    # Raw schema fallbacks for extracted inputs without dedicated staging models
    "stg_player_info": "raw_common_player_info",
    "stg_player_awards": "raw_player_awards",
    "stg_team_info": "raw_team_info_common",
    "stg_coaches": "raw_common_team_roster_coaches",
    "stg_franchise": "raw_franchise_history",
    "stg_box_score_misc": "raw_box_score_misc_player",
    "stg_box_score_scoring": "raw_box_score_scoring_player",
    "stg_box_score_usage": "raw_box_score_usage_player",
    "stg_shot_chart_league_wide": "raw_shot_chart_league_wide",
    "stg_playoff_picture_east": "raw_playoff_picture",
    "stg_playoff_picture_west": "raw_playoff_picture",
    "stg_draft_combine_drills": "raw_draft_combine_drill_results",
    "stg_draft_combine_nonstat_shooting": "raw_draft_combine_non_stationary_shooting",
    "stg_draft_combine_anthro": "raw_draft_combine_player_anthro",
    "stg_draft_combine_spot_shooting": "raw_draft_combine_spot_shooting",
}

_PLAYER_DASHBOARD_INPUT_SCHEMA_ALIASES: dict[str, str] = {
    # Player dashboard — clutch
    "stg_player_clutch_last10sec_3pt2": "stg_player_dashboard_clutch",
    "stg_player_clutch_last10sec_3pt": "stg_player_dashboard_clutch",
    "stg_player_clutch_last1min_5pt": "stg_player_dashboard_clutch",
    "stg_player_clutch_last1min_pm5": "stg_player_dashboard_clutch",
    "stg_player_clutch_last30sec_3pt2": "stg_player_dashboard_clutch",
    "stg_player_clutch_last30sec_3pt": "stg_player_dashboard_clutch",
    "stg_player_clutch_last3min_5pt": "stg_player_dashboard_clutch",
    "stg_player_clutch_last3min_pm5": "stg_player_dashboard_clutch",
    "stg_player_clutch_last5min_5pt": "stg_player_dashboard_clutch",
    "stg_player_clutch_last5min_pm5": "stg_player_dashboard_clutch",
    "stg_player_clutch_overall": "stg_player_dashboard_clutch",
    # Player dashboard — game splits
    "stg_player_dash_game_splits": "stg_player_dashboard_game_splits",
    "stg_player_split_actual_margin": "stg_player_dashboard_game_splits",
    "stg_player_split_by_half": "stg_player_dashboard_game_splits",
    "stg_player_split_by_period": "stg_player_dashboard_game_splits",
    "stg_player_split_score_margin": "stg_player_dashboard_game_splits",
    "stg_player_split_game_overall": "stg_player_dashboard_game_splits",
    # Player dashboard — general splits
    "stg_player_dash_general_splits": "stg_player_dashboard_general_splits",
    "stg_player_split_days_rest": "stg_player_dashboard_general_splits",
    "stg_player_split_location": "stg_player_dashboard_general_splits",
    "stg_player_split_month": "stg_player_dashboard_general_splits",
    "stg_player_split_general_overall": "stg_player_dashboard_general_splits",
    "stg_player_split_pre_post_allstar": "stg_player_dashboard_general_splits",
    "stg_player_split_starting_pos": "stg_player_dashboard_general_splits",
    "stg_player_split_wins_losses": "stg_player_dashboard_general_splits",
    # Player dashboard — last N
    "stg_player_dash_last_n_games": "stg_player_dashboard_last_n_games",
    "stg_player_lastn_game_number": "stg_player_dashboard_last_n_games",
    "stg_player_lastn_last10": "stg_player_dashboard_last_n_games",
    "stg_player_lastn_last15": "stg_player_dashboard_last_n_games",
    "stg_player_lastn_last20": "stg_player_dashboard_last_n_games",
    "stg_player_lastn_last5": "stg_player_dashboard_last_n_games",
    "stg_player_lastn_overall": "stg_player_dashboard_last_n_games",
    # Player dashboard — shooting
    "stg_player_dash_shooting_splits": "stg_player_dashboard_shooting_splits",
    "stg_player_shoot_assisted_shot": "stg_player_dashboard_shooting_splits",
    "stg_player_shoot_overall": "stg_player_dashboard_shooting_splits",
    "stg_player_shoot_5ft": "stg_player_dashboard_shooting_splits",
    "stg_player_shoot_8ft": "stg_player_dashboard_shooting_splits",
    "stg_player_shoot_area": "stg_player_dashboard_shooting_splits",
    "stg_player_shoot_type": "stg_player_dashboard_shooting_splits",
    # Player dashboard — team performance
    "stg_player_dash_team_perf": "stg_player_dashboard_team_performance",
    "stg_player_perf_overall": "stg_player_dashboard_team_performance",
    "stg_player_perf_pts_against": "stg_player_perf_pts_scored",
    "stg_player_perf_score_diff": "stg_player_perf_pts_scored",
    # Player dashboard — year over year
    "stg_player_dash_yoy": "stg_player_dashboard_year_over_year",
    "stg_player_yoy_by_year": "stg_player_dashboard_year_over_year",
    "stg_player_yoy_overall": "stg_player_dashboard_year_over_year",
}

_INPUT_SCHEMA_ALIASES.update(_PLAYER_DASHBOARD_INPUT_SCHEMA_ALIASES)


def _camel_to_snake(name: str) -> str:
    interim = _CAMEL_RE_1.sub(r"\1_\2", name)
    return _CAMEL_RE_2.sub(r"\1_\2", interim).lower()


def _discover_schemas(
    package_name: str,
    *,
    class_prefix: str,
    table_prefix: str,
) -> dict[str, type[BaseSchema]]:
    package = importlib.import_module(package_name)
    schemas: dict[str, type[BaseSchema]] = {}

    for _, module_name, _ in pkgutil.walk_packages(
        package.__path__,
        prefix=f"{package_name}.",
    ):
        module = importlib.import_module(module_name)
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj.__module__ != module_name
                or obj is BaseSchema
                or not issubclass(obj, BaseSchema)
                or not name.endswith("Schema")
                or (class_prefix and not name.startswith(class_prefix))
            ):
                continue

            stem = name.removesuffix("Schema")
            if class_prefix:
                stem = stem.removeprefix(class_prefix)
            table_name = f"{table_prefix}{_camel_to_snake(stem)}"
            schemas[table_name] = obj

    return schemas


@lru_cache(maxsize=1)
def _staging_schema_registry() -> dict[str, type[BaseSchema]]:
    return _discover_schemas(
        "nbadb.schemas.staging",
        class_prefix="Staging",
        table_prefix="stg_",
    )


@lru_cache(maxsize=1)
def _raw_schema_registry() -> dict[str, type[BaseSchema]]:
    return _discover_schemas(
        "nbadb.schemas.raw",
        class_prefix="Raw",
        table_prefix="raw_",
    )


@lru_cache(maxsize=1)
def _star_schema_registry() -> dict[str, type[BaseSchema]]:
    return _discover_schemas(
        "nbadb.schemas.star",
        class_prefix="",
        table_prefix="",
    )


def get_input_schema(table_name: str) -> type[BaseSchema] | None:
    if schema := _staging_schema_registry().get(table_name):
        return schema

    alias = _INPUT_SCHEMA_ALIASES.get(table_name)
    if alias is None:
        return None

    if schema := _staging_schema_registry().get(alias):
        return schema
    return _raw_schema_registry().get(alias)


def get_output_schema(table_name: str) -> type[BaseSchema] | None:
    return _star_schema_registry().get(table_name)


__all__ = ["get_input_schema", "get_output_schema"]
