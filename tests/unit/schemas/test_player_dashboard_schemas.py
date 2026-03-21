from __future__ import annotations

import pandera.errors as pa_errors
import polars as pl
import pytest

from nbadb.schemas.registry import get_input_schema, get_output_schema
from nbadb.schemas.staging.player_dashboard import (
    StagingPlayerDashboardClutchSchema,
    StagingPlayerDashboardGameSplitsSchema,
    StagingPlayerDashboardGeneralSplitsSchema,
    StagingPlayerDashboardLastNGamesSchema,
    StagingPlayerDashboardShootingSplitsSchema,
    StagingPlayerDashboardTeamPerformanceSchema,
    StagingPlayerDashboardYearOverYearSchema,
    StagingPlayerPerfPtsScoredSchema,
    StagingPlayerShootAssistedBySchema,
    StagingPlayerShootTypeSummarySchema,
)
from nbadb.schemas.star.fact_player_dashboard import (
    FactPlayerDashboardClutchOverallSchema,
    FactPlayerDashboardGameSplitsOverallSchema,
    FactPlayerDashboardGeneralSplitsOverallSchema,
    FactPlayerDashboardLastNOverallSchema,
    FactPlayerDashboardShootingOverallSchema,
    FactPlayerDashboardTeamPerfOverallSchema,
    FactPlayerDashboardYoyOverallSchema,
    FactPlayerSplitsSchema,
)

_STANDARD_RANK_FIELDS = [
    "gp_rank",
    "w_rank",
    "l_rank",
    "w_pct_rank",
    "min_rank",
    "fgm_rank",
    "fga_rank",
    "fg_pct_rank",
    "fg3m_rank",
    "fg3a_rank",
    "fg3_pct_rank",
    "ftm_rank",
    "fta_rank",
    "ft_pct_rank",
    "oreb_rank",
    "dreb_rank",
    "reb_rank",
    "ast_rank",
    "tov_rank",
    "stl_rank",
    "blk_rank",
    "blka_rank",
    "pf_rank",
    "pfd_rank",
    "pts_rank",
    "plus_minus_rank",
    "nba_fantasy_pts_rank",
    "dd2_rank",
    "td3_rank",
]

_SHOOTING_RANK_FIELDS = [
    "fgm_rank",
    "fga_rank",
    "fg_pct_rank",
    "fg3m_rank",
    "fg3a_rank",
    "fg3_pct_rank",
    "efg_pct_rank",
    "blka_rank",
    "pct_ast_2pm_rank",
    "pct_uast_2pm_rank",
    "pct_ast_3pm_rank",
    "pct_uast_3pm_rank",
    "pct_ast_fgm_rank",
    "pct_uast_fgm_rank",
]


_STAGING_SCHEMA_GROUPS = [
    (
        [
            "stg_player_dashboard_clutch",
            "stg_player_clutch_last10sec_3pt2",
            "stg_player_clutch_last10sec_3pt",
            "stg_player_clutch_last1min_5pt",
            "stg_player_clutch_last1min_pm5",
            "stg_player_clutch_last30sec_3pt2",
            "stg_player_clutch_last30sec_3pt",
            "stg_player_clutch_last3min_5pt",
            "stg_player_clutch_last3min_pm5",
            "stg_player_clutch_last5min_5pt",
            "stg_player_clutch_last5min_pm5",
            "stg_player_clutch_overall",
        ],
        "StagingPlayerDashboardClutchSchema",
    ),
    (
        [
            "stg_player_dashboard_game_splits",
            "stg_player_dash_game_splits",
            "stg_player_split_actual_margin",
            "stg_player_split_by_half",
            "stg_player_split_by_period",
            "stg_player_split_score_margin",
            "stg_player_split_game_overall",
        ],
        "StagingPlayerDashboardGameSplitsSchema",
    ),
    (
        [
            "stg_player_dashboard_general_splits",
            "stg_player_dash_general_splits",
            "stg_player_split_days_rest",
            "stg_player_split_location",
            "stg_player_split_month",
            "stg_player_split_general_overall",
            "stg_player_split_pre_post_allstar",
            "stg_player_split_starting_pos",
            "stg_player_split_wins_losses",
        ],
        "StagingPlayerDashboardGeneralSplitsSchema",
    ),
    (
        [
            "stg_player_dashboard_last_n_games",
            "stg_player_dash_last_n_games",
            "stg_player_lastn_game_number",
            "stg_player_lastn_last10",
            "stg_player_lastn_last15",
            "stg_player_lastn_last20",
            "stg_player_lastn_last5",
            "stg_player_lastn_overall",
        ],
        "StagingPlayerDashboardLastNGamesSchema",
    ),
    (
        [
            "stg_player_dashboard_shooting_splits",
            "stg_player_dash_shooting_splits",
            "stg_player_shoot_assisted_shot",
            "stg_player_shoot_overall",
            "stg_player_shoot_5ft",
            "stg_player_shoot_8ft",
            "stg_player_shoot_area",
            "stg_player_shoot_type",
        ],
        "StagingPlayerDashboardShootingSplitsSchema",
    ),
    (["stg_player_shoot_assisted_by"], "StagingPlayerShootAssistedBySchema"),
    (["stg_player_shoot_type_summary"], "StagingPlayerShootTypeSummarySchema"),
    (
        [
            "stg_player_dashboard_team_performance",
            "stg_player_dash_team_perf",
            "stg_player_perf_overall",
        ],
        "StagingPlayerDashboardTeamPerformanceSchema",
    ),
    (
        [
            "stg_player_perf_pts_scored",
            "stg_player_perf_pts_against",
            "stg_player_perf_score_diff",
        ],
        "StagingPlayerPerfPtsScoredSchema",
    ),
    (
        [
            "stg_player_dashboard_year_over_year",
            "stg_player_dash_yoy",
            "stg_player_yoy_by_year",
            "stg_player_yoy_overall",
        ],
        "StagingPlayerDashboardYearOverYearSchema",
    ),
]


_FACT_SCHEMAS = {
    "fact_player_dashboard_clutch_overall": "FactPlayerDashboardClutchOverallSchema",
    "fact_player_dashboard_game_splits_overall": "FactPlayerDashboardGameSplitsOverallSchema",
    "fact_player_dashboard_general_splits_overall": "FactPlayerDashboardGeneralSplitsOverallSchema",
    "fact_player_dashboard_last_n_overall": "FactPlayerDashboardLastNOverallSchema",
    "fact_player_dashboard_shooting_overall": "FactPlayerDashboardShootingOverallSchema",
    "fact_player_dashboard_team_perf_overall": "FactPlayerDashboardTeamPerfOverallSchema",
    "fact_player_dashboard_yoy_overall": "FactPlayerDashboardYoyOverallSchema",
    "fact_player_splits": "FactPlayerSplitsSchema",
}


def _standard_dashboard_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "player_id": 2544,
        "season_year": "2024-25",
        "season_type": "Regular Season",
        "group_set": "Overall",
        "group_value": "Overall",
        "gp": 12,
        "w": 8,
        "l": 4,
        "w_pct": 0.667,
        "min": 35.2,
        "fgm": 10.0,
        "fga": 19.0,
        "fg_pct": 0.526,
        "fg3m": 2.5,
        "fg3a": 6.0,
        "fg3_pct": 0.417,
        "ftm": 5.0,
        "fta": 6.0,
        "ft_pct": 0.833,
        "oreb": 1.2,
        "dreb": 7.1,
        "reb": 8.3,
        "ast": 7.4,
        "tov": 3.1,
        "stl": 1.4,
        "blk": 0.8,
        "blka": 0.5,
        "pf": 1.9,
        "pfd": 5.3,
        "pts": 27.5,
        "plus_minus": 5.4,
        "nba_fantasy_pts": 49.8,
        "dd2": 3.0,
        "td3": 1.0,
        "cfid": 7,
        "cfparams": "PLAYER_ID=2544&SEASON=2024-25",
    }
    for index, field in enumerate(_STANDARD_RANK_FIELDS, start=1):
        base[field] = index
    base.update(overrides)
    return base


def _shooting_ranked_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "player_id": 2544,
        "season_year": "2024-25",
        "season_type": "Regular Season",
        "group_set": "Overall",
        "group_value": "Overall",
        "fgm": 10.0,
        "fga": 19.0,
        "fg_pct": 0.526,
        "fg3m": 2.5,
        "fg3a": 6.0,
        "fg3_pct": 0.417,
        "efg_pct": 0.592,
        "blka": 0.5,
        "pct_ast_2pm": 0.68,
        "pct_uast_2pm": 0.32,
        "pct_ast_3pm": 0.91,
        "pct_uast_3pm": 0.09,
        "pct_ast_fgm": 0.74,
        "pct_uast_fgm": 0.26,
        "cfid": 7,
        "cfparams": "PLAYER_ID=2544&SEASON=2024-25",
    }
    for index, field in enumerate(_SHOOTING_RANK_FIELDS, start=1):
        base[field] = index
    base.update(overrides)
    return base


def _shooting_summary_row(**overrides: object) -> dict[str, object]:
    base = _shooting_ranked_row()
    for field in _SHOOTING_RANK_FIELDS:
        base.pop(field)
    base.update(overrides)
    return base


def _shooting_assisted_by_row(**overrides: object) -> dict[str, object]:
    base = _shooting_ranked_row()
    base.pop("group_value")
    base["group_set"] = "AssistedBy"
    base["player_name"] = "Stephen Curry"
    base.update(overrides)
    return base


def _team_perf_detail_row(**overrides: object) -> dict[str, object]:
    base = _standard_dashboard_row(
        group_set="PointsScored",
        group_value="100-109",
        group_value_order=1,
        group_value_2="Home",
    )
    base.update(overrides)
    return base


def _yoy_row(**overrides: object) -> dict[str, object]:
    base = _standard_dashboard_row(
        team_id=1610612747,
        team_abbreviation="LAL",
        max_game_date="2025-04-10",
    )
    base.update(overrides)
    return base


def _player_splits_row(**overrides: object) -> dict[str, object]:
    base = _standard_dashboard_row(split_type="game_splits")
    base.update(
        {
            "team_id": None,
            "team_abbreviation": None,
            "max_game_date": None,
            "efg_pct": None,
            "pct_ast_2pm": None,
            "pct_uast_2pm": None,
            "pct_ast_3pm": None,
            "pct_uast_3pm": None,
            "pct_ast_fgm": None,
            "pct_uast_fgm": None,
        }
    )
    for field in _SHOOTING_RANK_FIELDS[6:]:
        base[field] = None
    base["efg_pct_rank"] = None
    base.update(overrides)
    return base


@pytest.mark.parametrize(("staging_keys", "expected_schema_name"), _STAGING_SCHEMA_GROUPS)
def test_input_schema_resolves_player_dashboard_families(
    staging_keys: list[str],
    expected_schema_name: str,
) -> None:
    for staging_key in staging_keys:
        schema = get_input_schema(staging_key)
        assert schema is not None
        assert schema.__name__ == expected_schema_name


@pytest.mark.parametrize(
    ("schema_cls", "row_builder"),
    [
        (StagingPlayerDashboardClutchSchema, _standard_dashboard_row),
        (StagingPlayerDashboardGameSplitsSchema, _standard_dashboard_row),
        (StagingPlayerDashboardGeneralSplitsSchema, _standard_dashboard_row),
        (StagingPlayerDashboardLastNGamesSchema, _standard_dashboard_row),
        (StagingPlayerDashboardShootingSplitsSchema, _shooting_ranked_row),
        (StagingPlayerDashboardTeamPerformanceSchema, _standard_dashboard_row),
        (StagingPlayerDashboardYearOverYearSchema, _yoy_row),
        (StagingPlayerShootAssistedBySchema, _shooting_assisted_by_row),
        (StagingPlayerShootTypeSummarySchema, _shooting_summary_row),
        (StagingPlayerPerfPtsScoredSchema, _team_perf_detail_row),
    ],
)
def test_player_dashboard_staging_schemas_validate(
    schema_cls: type,
    row_builder,
) -> None:
    df = pl.DataFrame(row_builder())
    result = schema_cls.validate(df)
    assert result.shape[0] == 1


def test_player_dashboard_staging_schema_requires_query_context() -> None:
    df = pl.DataFrame(_standard_dashboard_row(player_id=None))
    with pytest.raises(pa_errors.SchemaError):
        StagingPlayerDashboardClutchSchema.validate(df)


@pytest.mark.parametrize("table_name, expected_schema_name", _FACT_SCHEMAS.items())
def test_output_schema_resolves_player_dashboard_facts(
    table_name: str,
    expected_schema_name: str,
) -> None:
    schema = get_output_schema(table_name)
    assert schema is not None
    assert schema.__name__ == expected_schema_name


@pytest.mark.parametrize(
    ("schema_cls", "row_builder"),
    [
        (FactPlayerDashboardClutchOverallSchema, _standard_dashboard_row),
        (FactPlayerDashboardGameSplitsOverallSchema, _standard_dashboard_row),
        (FactPlayerDashboardGeneralSplitsOverallSchema, _standard_dashboard_row),
        (FactPlayerDashboardLastNOverallSchema, _standard_dashboard_row),
        (FactPlayerDashboardShootingOverallSchema, _shooting_ranked_row),
        (FactPlayerDashboardTeamPerfOverallSchema, _standard_dashboard_row),
        (FactPlayerDashboardYoyOverallSchema, _yoy_row),
        (FactPlayerSplitsSchema, _player_splits_row),
    ],
)
def test_player_dashboard_star_schemas_validate(schema_cls: type, row_builder) -> None:
    df = pl.DataFrame(row_builder())
    result = schema_cls.validate(df)
    assert result.shape[0] == 1
