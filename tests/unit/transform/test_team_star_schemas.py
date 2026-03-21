from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.derived.agg_on_off_splits import AggOnOffSplitsTransformer
from nbadb.transform.facts.fact_team_dashboard_general_overall import (
    FactTeamDashboardGeneralOverallTransformer,
)
from nbadb.transform.facts.fact_team_dashboard_shooting_overall import (
    FactTeamDashboardShootingOverallTransformer,
)
from nbadb.transform.facts.fact_team_lineups_overall import FactTeamLineupsOverallTransformer
from nbadb.transform.facts.fact_team_player_dashboard import FactTeamPlayerDashboardTransformer
from nbadb.transform.facts.fact_team_pt_reb_detail import FactTeamPtRebDetailTransformer
from nbadb.transform.facts.fact_team_pt_shots_detail import FactTeamPtShotsDetailTransformer
from nbadb.transform.facts.fact_team_pt_tracking import FactTeamPtTrackingTransformer
from nbadb.transform.facts.fact_team_splits import FactTeamSplitsTransformer
from nbadb.transform.pipeline import _star_schema_map


def _frame(values: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame({key: [value] for key, value in values.items()})


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _assert_schema_valid(table: str, df: pl.DataFrame) -> None:
    schema_cls = _star_schema_map()[table]
    validated = schema_cls.validate(df)
    assert isinstance(validated, pl.DataFrame)


def _team_general_row() -> dict[str, object]:
    values = {
        "group_set": "Overall",
        "group_value": "2024-25",
        "season_year": "2024-25",
        "gp": 82,
        "w": 57,
        "l": 25,
        "w_pct": 0.695,
        "min": 48.0,
        "ftm": 18.2,
        "fta": 23.4,
        "ft_pct": 0.778,
        "oreb": 10.8,
        "dreb": 33.6,
        "reb": 44.4,
        "ast": 27.1,
        "tov": 12.8,
        "stl": 7.9,
        "blk": 5.3,
        "pf": 18.1,
        "pfd": 19.7,
        "pts": 118.7,
        "plus_minus": 7.8,
        "cfid": 7,
        "cfparams": "TEAM_ID=1610612738&SEASON=2024-25",
        "season_type": "Regular Season",
    }
    values.update(
        {
            key: value
            for key, value in {
                "fgm": 43.1,
                "fga": 88.9,
                "fg_pct": 0.485,
                "fg3m": 14.3,
                "fg3a": 38.2,
                "fg3_pct": 0.374,
                "blka": 4.1,
            }.items()
        }
    )
    values.update(
        {
            key: value
            for key, value in {
                "gp_rank": 3,
                "w_rank": 2,
                "l_rank": 29,
                "w_pct_rank": 2,
                "min_rank": 11,
                "fgm_rank": 5,
                "fga_rank": 8,
                "fg_pct_rank": 4,
                "fg3m_rank": 1,
                "fg3a_rank": 1,
                "fg3_pct_rank": 6,
                "ftm_rank": 9,
                "fta_rank": 12,
                "ft_pct_rank": 7,
                "oreb_rank": 10,
                "dreb_rank": 4,
                "reb_rank": 6,
                "ast_rank": 3,
                "tov_rank": 12,
                "stl_rank": 9,
                "blk_rank": 11,
                "blka_rank": 8,
                "pf_rank": 17,
                "pfd_rank": 13,
                "pts_rank": 2,
                "plus_minus_rank": 1,
            }.items()
        }
    )
    return values


def _team_shooting_row() -> dict[str, object]:
    values = {
        "group_set": "Overall",
        "group_value": "Overall",
        "cfid": 7,
        "cfparams": "TEAM_ID=1610612738&SEASON=2024-25",
        "season_type": "Regular Season",
        "efg_pct": 0.582,
        "pct_ast_2pm": 0.583,
        "pct_uast_2pm": 0.417,
        "pct_ast_3pm": 0.914,
        "pct_uast_3pm": 0.086,
        "pct_ast_fgm": 0.703,
        "pct_uast_fgm": 0.297,
    }
    values.update(
        {
            key: value
            for key, value in {
                "fgm": 43.1,
                "fga": 88.9,
                "fg_pct": 0.485,
                "fg3m": 14.3,
                "fg3a": 38.2,
                "fg3_pct": 0.374,
                "blka": 4.1,
            }.items()
        }
    )
    values.update(
        {
            key: value
            for key, value in {
                "fgm_rank": 5,
                "fga_rank": 8,
                "fg_pct_rank": 4,
                "fg3m_rank": 1,
                "fg3a_rank": 1,
                "fg3_pct_rank": 6,
                "blka_rank": 8,
                "efg_pct_rank": 3,
                "pct_ast_2pm_rank": 7,
                "pct_uast_2pm_rank": 19,
                "pct_ast_3pm_rank": 1,
                "pct_uast_3pm_rank": 30,
                "pct_ast_fgm_rank": 2,
                "pct_uast_fgm_rank": 28,
            }.items()
        }
    )
    return values


def _team_player_row() -> dict[str, object]:
    values = {
        "group_set": "PlayersSeasonTotals",
        "player_id": 1627759,
        "player_name": "Jaylen Brown",
        "gp": 70,
        "w": 49,
        "l": 21,
        "w_pct": 0.7,
        "min": 33.5,
        "ftm": 4.4,
        "fta": 5.8,
        "ft_pct": 0.758,
        "oreb": 1.2,
        "dreb": 4.4,
        "reb": 5.6,
        "ast": 3.7,
        "tov": 2.4,
        "stl": 1.0,
        "blk": 0.4,
        "pf": 2.2,
        "pfd": 4.8,
        "pts": 23.0,
        "plus_minus": 5.9,
        "season_type": "Regular Season",
        "nba_fantasy_pts": 38.7,
        "dd2": 6.0,
        "td3": 1.0,
    }
    values.update(
        {
            key: value
            for key, value in {
                "fgm": 8.6,
                "fga": 18.2,
                "fg_pct": 0.472,
                "fg3m": 2.4,
                "fg3a": 6.7,
                "fg3_pct": 0.358,
                "blka": 1.1,
            }.items()
        }
    )
    values.update(
        {
            key: value
            for key, value in {
                "gp_rank": 37,
                "w_rank": 19,
                "l_rank": 402,
                "w_pct_rank": 22,
                "min_rank": 31,
                "fgm_rank": 20,
                "fga_rank": 18,
                "fg_pct_rank": 74,
                "fg3m_rank": 34,
                "fg3a_rank": 55,
                "fg3_pct_rank": 117,
                "ftm_rank": 41,
                "fta_rank": 39,
                "ft_pct_rank": 151,
                "oreb_rank": 128,
                "dreb_rank": 94,
                "reb_rank": 97,
                "ast_rank": 110,
                "tov_rank": 89,
                "stl_rank": 128,
                "blk_rank": 217,
                "blka_rank": 63,
                "pf_rank": 143,
                "pfd_rank": 28,
                "pts_rank": 25,
                "plus_minus_rank": 34,
                "nba_fantasy_pts_rank": 33,
                "dd2_rank": 69,
                "td3_rank": 111,
            }.items()
        }
    )
    return values


def _team_lineup_row() -> dict[str, object]:
    values = {
        "group_set": "Lineups",
        "group_id": "1627759-1628369-1628400-1629057-203954",
        "group_name": "Lineup A",
        "gp": 34,
        "w": 22,
        "l": 12,
        "w_pct": 0.647,
        "min": 315.4,
        "fg_pct": 0.512,
        "fg3_pct": 0.392,
        "ft_pct": 0.781,
        "plus_minus": 42.0,
        "season_type": "Regular Season",
    }
    values.update(
        {
            key: value
            for key, value in {
                "fgm": 128,
                "fga": 250,
                "fg3m": 51,
                "fg3a": 130,
                "ftm": 44,
                "fta": 56,
                "oreb": 31,
                "dreb": 92,
                "reb": 123,
                "ast": 78,
                "tov": 29,
                "stl": 18,
                "blk": 11,
                "blka": 9,
                "pf": 52,
                "pfd": 47,
                "pts": 351,
            }.items()
        }
    )
    values.update(
        {
            key: value
            for key, value in {
                "gp_rank": 7,
                "w_rank": 5,
                "l_rank": 18,
                "w_pct_rank": 6,
                "min_rank": 4,
                "fgm_rank": 3,
                "fga_rank": 5,
                "fg_pct_rank": 2,
                "fg3m_rank": 2,
                "fg3a_rank": 4,
                "fg3_pct_rank": 3,
                "ftm_rank": 8,
                "fta_rank": 10,
                "ft_pct_rank": 12,
                "oreb_rank": 16,
                "dreb_rank": 5,
                "reb_rank": 7,
                "ast_rank": 4,
                "tov_rank": 20,
                "stl_rank": 14,
                "blk_rank": 12,
                "blka_rank": 11,
                "pf_rank": 19,
                "pfd_rank": 13,
                "pts_rank": 3,
                "plus_minus_rank": 2,
            }.items()
        }
    )
    return values


def _team_pt_pass_row() -> dict[str, object]:
    return {
        "team_id": 1610612738,
        "team_name": "Boston Celtics",
        "pass_type": "made",
        "g": 82,
        "pass_from": "Jayson Tatum",
        "pass_teammate_player_id": 1627759,
        "frequency": 0.148,
        "pass": 312,
        "ast": 28,
        "fgm": 41,
        "fga": 88,
        "fg_pct": 0.466,
        "fg2m": 23,
        "fg2a": 40,
        "fg2_pct": 0.575,
        "fg3m": 18,
        "fg3a": 48,
        "fg3_pct": 0.375,
        "season_type": "Regular Season",
    }


def _team_pt_pass_received_row() -> dict[str, object]:
    return {
        "team_id": 1610612738,
        "team_name": "Boston Celtics",
        "pass_type": "received",
        "g": 82,
        "pass_to": "Jaylen Brown",
        "pass_teammate_player_id": 1628369,
        "frequency": 0.141,
        "pass": 297,
        "ast": 24,
        "fgm": 39,
        "fga": 80,
        "fg_pct": 0.487,
        "fg2m": 24,
        "fg2a": 39,
        "fg2_pct": 0.615,
        "fg3m": 15,
        "fg3a": 41,
        "fg3_pct": 0.366,
        "season_type": "Regular Season",
    }


def _team_pt_reb_row() -> dict[str, object]:
    return {
        "team_id": 1610612738,
        "team_name": "Boston Celtics",
        "sort_order": 1,
        "g": 82,
        "reb_num_contesting_range": "0-2",
        "reb_frequency": 0.314,
        "oreb": 94,
        "dreb": 228,
        "reb": 322,
        "c_oreb": 28,
        "c_dreb": 90,
        "c_reb": 118,
        "c_reb_pct": 0.366,
        "uc_oreb": 66,
        "uc_dreb": 138,
        "uc_reb": 204,
        "uc_reb_pct": 0.634,
        "season_type": "Regular Season",
    }


def _team_pt_shots_row() -> dict[str, object]:
    return {
        "team_id": 1610612738,
        "team_name": "Boston Celtics",
        "sort_order": 1,
        "g": 82,
        "close_def_dist_range": "6+ Feet - Wide Open",
        "fga_frequency": 0.286,
        "fgm": 205,
        "fga": 420,
        "fg_pct": 0.488,
        "efg_pct": 0.612,
        "fg2a_frequency": 0.382,
        "fg2m": 88,
        "fg2a": 160,
        "fg2_pct": 0.55,
        "fg3a_frequency": 0.618,
        "fg3m": 117,
        "fg3a": 260,
        "fg3_pct": 0.45,
        "season_type": "Regular Season",
    }


class TestTeamDashboardStarSchemas:
    def test_team_dashboard_general_overall_schema_validates_transform_output(self) -> None:
        staging = {"stg_team_dash_general_splits": _frame(_team_general_row()).lazy()}

        result = _run(FactTeamDashboardGeneralOverallTransformer(), staging)

        assert result.shape == (1, len(_team_general_row()))
        _assert_schema_valid("fact_team_dashboard_general_overall", result)

    def test_team_dashboard_shooting_overall_schema_validates_transform_output(self) -> None:
        staging = {"stg_team_dash_shooting_splits": _frame(_team_shooting_row()).lazy()}

        result = _run(FactTeamDashboardShootingOverallTransformer(), staging)

        assert result.shape == (1, len(_team_shooting_row()))
        _assert_schema_valid("fact_team_dashboard_shooting_overall", result)

    def test_team_player_dashboard_schema_validates_transform_output(self) -> None:
        staging = {"stg_team_player_dashboard": _frame(_team_player_row()).lazy()}

        result = _run(FactTeamPlayerDashboardTransformer(), staging)

        assert result.shape == (1, len(_team_player_row()))
        _assert_schema_valid("fact_team_player_dashboard", result)

    def test_team_lineups_overall_schema_validates_transform_output(self) -> None:
        staging = {"stg_team_lineups": _frame(_team_lineup_row()).lazy()}

        result = _run(FactTeamLineupsOverallTransformer(), staging)

        assert result.shape == (1, len(_team_lineup_row()))
        _assert_schema_valid("fact_team_lineups_overall", result)

    def test_team_tracking_schemas_validate_transform_outputs(self) -> None:
        staging = {
            "stg_team_pt_pass": _frame(_team_pt_pass_row()).lazy(),
            "stg_team_pt_pass_received": _frame(_team_pt_pass_received_row()).lazy(),
            "stg_team_pt_reb": _frame(_team_pt_reb_row()).lazy(),
            "stg_team_pt_shots": _frame(_team_pt_shots_row()).lazy(),
        }

        tracking = _run(FactTeamPtTrackingTransformer(), staging)
        reb_detail = _run(FactTeamPtRebDetailTransformer(), staging)
        shots_detail = _run(FactTeamPtShotsDetailTransformer(), staging)

        assert set(tracking["tracking_type"].to_list()) == {
            "pass",
            "pass_received",
            "rebound",
            "shots",
        }
        _assert_schema_valid("fact_team_pt_tracking", tracking)
        _assert_schema_valid("fact_team_pt_reb_detail", reb_detail)
        _assert_schema_valid("fact_team_pt_shots_detail", shots_detail)

    def test_team_splits_and_on_off_schemas_validate_transform_outputs(self) -> None:
        split_staging = {
            "stg_team_dash_general_splits": _frame(_team_general_row()).lazy(),
            "stg_team_dash_shooting_splits": _frame(_team_shooting_row()).lazy(),
        }
        on_off_staging = {
            "stg_team_dashboard_on_off": _frame(
                {
                    "team_id": 1610612738,
                    "season_year": "2024-25",
                    "on_off": "overall",
                    "gp": 82,
                    "min": 48.0,
                    "pts": 118.7,
                    "reb": 44.4,
                    "ast": 27.1,
                    "off_rating": 121.8,
                    "def_rating": 110.5,
                    "net_rating": 11.3,
                }
            ).lazy(),
            "stg_on_off": _frame(
                {
                    "player_id": 1628369,
                    "team_id": 1610612738,
                    "season_year": "2024-25",
                    "on_off": "on",
                    "gp": 65,
                    "min": 35.1,
                    "pts": 117.2,
                    "reb": 43.0,
                    "ast": 26.0,
                    "off_rating": 120.3,
                    "def_rating": 111.4,
                    "net_rating": 8.9,
                }
            ).lazy(),
            "stg_player_on_details": _frame(
                {
                    "player_id": 1627759,
                    "team_id": 1610612738,
                    "season_year": "2024-25",
                    "on_off": "off",
                    "gp": 60,
                    "min": 31.8,
                    "pts": 111.4,
                    "reb": 41.7,
                    "ast": 24.2,
                    "off_rating": 114.2,
                    "def_rating": 112.1,
                    "net_rating": 2.1,
                }
            ).lazy(),
        }

        splits = _run(FactTeamSplitsTransformer(), split_staging)
        on_off = _run(AggOnOffSplitsTransformer(), on_off_staging)

        assert set(splits["split_type"].to_list()) == {"general", "shooting"}
        assert set(on_off["entity_type"].to_list()) == {"player", "player_detail", "team"}
        _assert_schema_valid("fact_team_splits", splits)
        _assert_schema_valid("agg_on_off_splits", on_off)


def test_team_family_schemas_are_discovered_without_init_exports() -> None:
    assert {
        "agg_on_off_splits",
        "fact_team_dashboard_general_overall",
        "fact_team_dashboard_shooting_overall",
        "fact_team_lineups_overall",
        "fact_team_player_dashboard",
        "fact_team_pt_reb_detail",
        "fact_team_pt_shots_detail",
        "fact_team_pt_tracking",
        "fact_team_splits",
    }.issubset(_star_schema_map())
