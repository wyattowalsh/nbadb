from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.views.analytics_player_general_splits import (
    AnalyticsPlayerGeneralSplitsTransformer,
)
from nbadb.transform.views.analytics_team_general_splits import (
    AnalyticsTeamGeneralSplitsTransformer,
)


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def test_analytics_player_general_splits() -> None:
    fact_player_general_splits_detail = pl.DataFrame(
        {
            "player_id": [101, 101, 101],
            "season_year": ["2024-25", "2024-25", "2024-25"],
            "season_type": ["Regular Season", "Regular Season", "Regular Season"],
            "split_type": ["general_overall", "location", "days_rest"],
            "group_set": [None, "Location", "DaysRest"],
            "group_value": [None, "Home", "0 Days"],
            "gp": [82, 41, 12],
            "w": [50, 28, 6],
            "l": [32, 13, 6],
            "w_pct": [0.610, 0.683, 0.500],
            "min": [34.5, 35.2, 33.1],
            "pts": [25.0, 27.5, 22.0],
            "reb": [7.0, 7.8, 6.5],
            "ast": [6.0, 6.8, 5.2],
            "fg_pct": [0.490, 0.520, 0.450],
            "fg3_pct": [0.380, 0.410, 0.330],
            "ft_pct": [0.850, 0.880, 0.810],
            "plus_minus": [5.0, 7.0, -1.0],
        }
    ).lazy()
    dim_player = pl.DataFrame(
        {
            "player_sk": [1, 2],
            "player_id": [101, 101],
            "full_name": ["Old Name", "Test Player"],
            "position": ["PG", "SG"],
            "team_id": [99, 1],
            "jersey_number": ["0", "23"],
            "height": ["6-3", "6-6"],
            "weight": [200, 215],
            "birth_date": ["1990-01-01", "1990-01-01"],
            "country": ["USA", "USA"],
            "draft_year": [2010, 2010],
            "draft_round": [1, 1],
            "draft_number": [5, 5],
            "college_id": [1, 1],
            "valid_from": [2018, 2020],
            "valid_to": [2020, None],
            "is_current": [False, True],
        }
    ).lazy()

    result = _run(
        AnalyticsPlayerGeneralSplitsTransformer(),
        {
            "fact_player_general_splits_detail": fact_player_general_splits_detail,
            "dim_player": dim_player,
        },
    )

    assert result.shape[0] == 3
    assert set(result["split_type"].to_list()) == {"general_overall", "location", "days_rest"}
    assert set(result["player_name"].to_list()) == {"Test Player"}

    home = result.filter(pl.col("group_value") == "Home").row(0, named=True)
    assert home["overall_pts"] == 25.0
    assert home["pts_delta"] == 2.5
    assert home["fg_pct_delta"] == pytest.approx(0.03)
    assert home["gp_share"] == 0.5

    overall = result.filter(pl.col("split_type") == "general_overall").row(0, named=True)
    assert overall["pts_delta"] == 0.0
    assert overall["plus_minus_delta"] == 0.0


def test_analytics_team_general_splits() -> None:
    fact_team_general_splits_detail = pl.DataFrame(
        {
            "team_id": [1, 1, 1],
            "season_year": ["2024-25", "2024-25", "2024-25"],
            "season_type": ["Regular Season", "Regular Season", "Regular Season"],
            "split_type": ["general_overall", "location", "days_rest"],
            "group_set": [None, "Location", "DaysRest"],
            "group_value": [None, "Home", "0 Days"],
            "gp": [82, 41, 11],
            "w": [55, 31, 5],
            "l": [27, 10, 6],
            "w_pct": [0.671, 0.756, 0.455],
            "min": [240.0, 240.0, 240.0],
            "pts": [118.0, 121.0, 111.0],
            "reb": [45.0, 46.0, 43.0],
            "ast": [28.0, 29.5, 25.0],
            "fg_pct": [0.495, 0.512, 0.470],
            "fg3_pct": [0.385, 0.401, 0.342],
            "ft_pct": [0.812, 0.825, 0.790],
            "plus_minus": [7.5, 10.2, -0.8],
        }
    ).lazy()
    dim_team = pl.DataFrame(
        {
            "team_id": [1],
            "abbreviation": ["TST"],
            "full_name": ["Test Team"],
            "city": ["Test City"],
            "state": ["TS"],
            "arena": ["Test Arena"],
            "year_founded": [1970],
            "conference": ["East"],
            "division": ["Atlantic"],
        }
    ).lazy()

    result = _run(
        AnalyticsTeamGeneralSplitsTransformer(),
        {
            "fact_team_general_splits_detail": fact_team_general_splits_detail,
            "dim_team": dim_team,
        },
    )

    assert result.shape[0] == 3
    assert set(result["team_name"].to_list()) == {"Test Team"}
    assert set(result["team_abbreviation"].to_list()) == {"TST"}

    rest = result.filter(pl.col("group_value") == "0 Days").row(0, named=True)
    assert rest["overall_pts"] == 118.0
    assert rest["pts_delta"] == -7.0
    assert rest["w_pct_delta"] == pytest.approx(-0.216)
    assert rest["gp_share"] == pytest.approx(11 / 82)

    overall = result.filter(pl.col("split_type") == "general_overall").row(0, named=True)
    assert overall["fg3_pct_delta"] == 0.0
