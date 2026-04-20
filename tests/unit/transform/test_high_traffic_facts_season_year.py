"""Tests verifying season_year enrichment via dim_game for high-traffic fact tables.

All six transformers should:
 1. Declare dim_game in depends_on.
 2. Include season_year in the output.
 3. Correctly LEFT JOIN so rows without a dim_game match get NULL season_year.
"""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.facts.fact_player_game_advanced import (
    FactPlayerGameAdvancedTransformer,
)
from nbadb.transform.facts.fact_player_game_hustle import (
    FactPlayerGameHustleTransformer,
)
from nbadb.transform.facts.fact_player_game_misc import (
    FactPlayerGameMiscTransformer,
)
from nbadb.transform.facts.fact_player_game_tracking import (
    FactPlayerGameTrackingTransformer,
)
from nbadb.transform.facts.fact_shot_chart import FactShotChartTransformer
from nbadb.transform.facts.fact_team_game import FactTeamGameTransformer

# ---------------------------------------------------------------------------
# Shared dim_game fixture
# ---------------------------------------------------------------------------

_DIM_GAME = pl.DataFrame(
    {
        "game_id": [1001],
        "game_date": ["2024-11-05"],
        "season_year": [2024],
        "season_type": ["Regular Season"],
        "home_team_id": [10],
        "visitor_team_id": [20],
        "matchup": ["HME vs AWY"],
        "arena_name": ["Test Arena"],
        "arena_city": ["Test City"],
    }
)


def _run_sql(transformer, tables: dict[str, pl.DataFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for name, df in tables.items():
            conn.register(name, df)
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Metadata: dim_game in depends_on
# ---------------------------------------------------------------------------

ALL_TRANSFORMERS = [
    FactTeamGameTransformer,
    FactPlayerGameAdvancedTransformer,
    FactPlayerGameHustleTransformer,
    FactPlayerGameMiscTransformer,
    FactPlayerGameTrackingTransformer,
    FactShotChartTransformer,
]


@pytest.mark.parametrize(
    "cls",
    ALL_TRANSFORMERS,
    ids=[c.output_table for c in ALL_TRANSFORMERS],
)
def test_dim_game_in_depends_on(cls):
    assert "dim_game" in cls.depends_on


# ---------------------------------------------------------------------------
# fact_team_game
# ---------------------------------------------------------------------------


class TestFactTeamGameSeasonYear:
    @staticmethod
    def _tables():
        stg_box = pl.DataFrame(
            {
                "game_id": [1001, 1001],
                "player_id": [100, 200],
                "team_id": [10, 20],
                "fgm": [5, 4],
                "fga": [10, 9],
                "fg3m": [2, 1],
                "fg3a": [5, 4],
                "ftm": [3, 2],
                "fta": [4, 3],
                "oreb": [1, 2],
                "dreb": [3, 4],
                "reb": [4, 6],
                "ast": [3, 2],
                "stl": [1, 1],
                "blk": [0, 1],
                "tov": [2, 1],
                "pf": [3, 2],
                "pts": [15, 11],
            }
        )
        stg_line = pl.DataFrame(
            {
                "game_id": [1001, 1001],
                "team_id": [10, 20],
                "pts_qtr1": [5, 3],
                "pts_qtr2": [4, 3],
                "pts_qtr3": [3, 3],
                "pts_qtr4": [3, 2],
            }
        )
        return {
            "stg_box_score_traditional": stg_box,
            "stg_line_score": stg_line,
            "dim_game": _DIM_GAME,
        }

    def test_season_year_present(self):
        result = _run_sql(FactTeamGameTransformer(), self._tables())
        assert "season_year" in result.columns

    def test_season_year_value(self):
        result = _run_sql(FactTeamGameTransformer(), self._tables())
        assert result["season_year"].to_list() == [2024, 2024]

    def test_season_year_null_when_no_dim_game(self):
        tables = self._tables()
        tables["dim_game"] = _DIM_GAME.filter(pl.col("game_id") == -1)
        result = _run_sql(FactTeamGameTransformer(), tables)
        assert result["season_year"].null_count() == result.shape[0]


# ---------------------------------------------------------------------------
# fact_player_game_advanced
# ---------------------------------------------------------------------------


class TestFactPlayerGameAdvancedSeasonYear:
    @staticmethod
    def _tables():
        stg = pl.DataFrame(
            {
                "game_id": [1001],
                "player_id": [100],
                "team_id": [10],
                "min": ["30:00"],
                "off_rating": [110.0],
                "def_rating": [105.0],
                "net_rating": [5.0],
                "ast_pct": [0.2],
                "ast_tov": [1.5],
                "ast_ratio": [0.15],
                "oreb_pct": [0.05],
                "dreb_pct": [0.15],
                "reb_pct": [0.10],
                "tov_pct": [0.12],
                "efg_pct": [0.55],
                "ts_pct": [0.58],
                "usg_pct": [0.25],
                "pace": [100.0],
                "poss": [50],
                "pie": [0.12],
                "e_off_rating": [112.0],
                "e_def_rating": [104.0],
                "e_net_rating": [8.0],
                "e_usg_pct": [0.24],
                "e_pace": [101.0],
            }
        )
        return {"stg_box_score_advanced": stg, "dim_game": _DIM_GAME}

    def test_season_year_present(self):
        result = _run_sql(FactPlayerGameAdvancedTransformer(), self._tables())
        assert "season_year" in result.columns

    def test_season_year_value(self):
        result = _run_sql(FactPlayerGameAdvancedTransformer(), self._tables())
        assert result["season_year"][0] == 2024

    def test_season_year_null_when_no_dim_game(self):
        tables = self._tables()
        tables["dim_game"] = _DIM_GAME.filter(pl.col("game_id") == -1)
        result = _run_sql(FactPlayerGameAdvancedTransformer(), tables)
        assert result["season_year"].null_count() == 1


# ---------------------------------------------------------------------------
# fact_player_game_hustle
# ---------------------------------------------------------------------------


class TestFactPlayerGameHustleSeasonYear:
    @staticmethod
    def _tables():
        stg = pl.DataFrame(
            {
                "game_id": [1001],
                "player_id": [100],
                "team_id": [10],
                "min": ["28:00"],
                "contested_shots": [8],
                "contested_shots_2pt": [5],
                "contested_shots_3pt": [3],
                "deflections": [4],
                "charges_drawn": [1],
                "screen_assists": [2],
                "screen_ast_pts": [6],
                "loose_balls_recovered": [3],
                "box_outs": [5],
            }
        )
        return {"stg_box_score_hustle": stg, "dim_game": _DIM_GAME}

    def test_season_year_present(self):
        result = _run_sql(FactPlayerGameHustleTransformer(), self._tables())
        assert "season_year" in result.columns

    def test_season_year_value(self):
        result = _run_sql(FactPlayerGameHustleTransformer(), self._tables())
        assert result["season_year"][0] == 2024

    def test_season_year_null_when_no_dim_game(self):
        tables = self._tables()
        tables["dim_game"] = _DIM_GAME.filter(pl.col("game_id") == -1)
        result = _run_sql(FactPlayerGameHustleTransformer(), tables)
        assert result["season_year"].null_count() == 1


# ---------------------------------------------------------------------------
# fact_player_game_misc
# ---------------------------------------------------------------------------


class TestFactPlayerGameMiscSeasonYear:
    @staticmethod
    def _tables():
        misc = pl.DataFrame(
            {
                "game_id": [1001],
                "player_id": [100],
                "team_id": [10],
                "pts_off_tov": [5],
                "pts_2nd_chance": [4],
                "pts_fb": [6],
                "pts_paint": [8],
                "opp_pts_off_tov": [3],
                "opp_pts_2nd_chance": [2],
                "opp_pts_fb": [4],
                "opp_pts_paint": [6],
            }
        )
        scoring = pl.DataFrame(
            {
                "game_id": [1001],
                "player_id": [100],
                "pct_fga_2pt": [0.6],
                "pct_fga_3pt": [0.4],
                "pct_pts_2pt": [0.5],
                "pct_pts_2pt_mr": [0.15],
                "pct_pts_3pt": [0.3],
                "pct_pts_fb": [0.1],
                "pct_pts_ft": [0.1],
                "pct_pts_off_tov": [0.05],
                "pct_pts_paint": [0.35],
                "pct_ast_2pm": [0.4],
                "pct_uast_2pm": [0.6],
                "pct_ast_3pm": [0.3],
                "pct_uast_3pm": [0.7],
                "pct_ast_fgm": [0.35],
                "pct_uast_fgm": [0.65],
            }
        )
        usage = pl.DataFrame(
            {
                "game_id": [1001],
                "player_id": [100],
                "usg_pct": [0.25],
                "pct_fgm": [0.1],
                "pct_fga": [0.12],
                "pct_fg3m": [0.08],
                "pct_fg3a": [0.1],
                "pct_ftm": [0.09],
                "pct_fta": [0.11],
                "pct_oreb": [0.05],
                "pct_dreb": [0.15],
                "pct_reb": [0.10],
                "pct_ast": [0.12],
                "pct_tov": [0.08],
                "pct_stl": [0.06],
                "pct_blk": [0.04],
                "pct_pts": [0.14],
            }
        )
        return {
            "stg_box_score_misc": misc,
            "stg_box_score_scoring": scoring,
            "stg_box_score_usage": usage,
            "dim_game": _DIM_GAME,
        }

    def test_season_year_present(self):
        result = _run_sql(FactPlayerGameMiscTransformer(), self._tables())
        assert "season_year" in result.columns

    def test_season_year_value(self):
        result = _run_sql(FactPlayerGameMiscTransformer(), self._tables())
        assert result["season_year"][0] == 2024

    def test_season_year_null_when_no_dim_game(self):
        tables = self._tables()
        tables["dim_game"] = _DIM_GAME.filter(pl.col("game_id") == -1)
        result = _run_sql(FactPlayerGameMiscTransformer(), tables)
        assert result["season_year"].null_count() == 1


# ---------------------------------------------------------------------------
# fact_player_game_tracking
# ---------------------------------------------------------------------------


class TestFactPlayerGameTrackingSeasonYear:
    @staticmethod
    def _tables():
        track = pl.DataFrame(
            {
                "game_id": [1001],
                "player_id": [100],
                "team_id": [10],
                "min": ["32:00"],
                "spd": [4.5],
                "dist": [2.3],
                "orbc": [1],
                "drbc": [3],
                "rbc": [4],
                "tchs": [50],
                "sast": [5],
                "ftast": [2],
                "pass": [40],
                "cfgm": [3],
                "cfga": [6],
                "cfg_pct": [0.5],
                "ufgm": [2],
                "ufga": [5],
                "ufg_pct": [0.4],
                "dfgm": [1],
                "dfga": [4],
                "dfg_pct": [0.25],
            }
        )
        defense = pl.DataFrame(
            {
                "game_id": [1001],
                "player_id": [100],
                "matchup_min": ["25:00"],
                "partial_poss": [30.0],
                "switches_on": [5],
                "player_pts": [12],
                "def_fgm": [4],
                "def_fga": [10],
                "def_fg_pct": [0.4],
            }
        )
        return {
            "stg_box_score_player_track": track,
            "stg_box_score_defensive": defense,
            "dim_game": _DIM_GAME,
        }

    def test_season_year_present(self):
        result = _run_sql(FactPlayerGameTrackingTransformer(), self._tables())
        assert "season_year" in result.columns

    def test_season_year_value(self):
        result = _run_sql(FactPlayerGameTrackingTransformer(), self._tables())
        assert result["season_year"][0] == 2024

    def test_season_year_null_when_no_dim_game(self):
        tables = self._tables()
        tables["dim_game"] = _DIM_GAME.filter(pl.col("game_id") == -1)
        result = _run_sql(FactPlayerGameTrackingTransformer(), tables)
        assert result["season_year"].null_count() == 1


# ---------------------------------------------------------------------------
# fact_shot_chart
# ---------------------------------------------------------------------------


class TestFactShotChartSeasonYear:
    @staticmethod
    def _tables():
        stg = pl.DataFrame(
            {
                "game_id": [1001],
                "player_id": [100],
                "team_id": [10],
                "period": [1],
                "minutes_remaining": [8],
                "seconds_remaining": [30],
                "action_type": ["Jump Shot"],
                "shot_type": ["2PT Field Goal"],
                "shot_zone_basic": ["Mid-Range"],
                "shot_zone_area": ["Center(C)"],
                "shot_zone_range": ["8-16 ft."],
                "shot_distance": [12],
                "loc_x": [5],
                "loc_y": [80],
                "shot_made_flag": [1],
            }
        )
        return {"stg_shot_chart": stg, "dim_game": _DIM_GAME}

    def test_season_year_present(self):
        result = _run_sql(FactShotChartTransformer(), self._tables())
        assert "season_year" in result.columns

    def test_season_year_value(self):
        result = _run_sql(FactShotChartTransformer(), self._tables())
        assert result["season_year"][0] == 2024

    def test_season_year_null_when_no_dim_game(self):
        tables = self._tables()
        tables["dim_game"] = _DIM_GAME.filter(pl.col("game_id") == -1)
        result = _run_sql(FactShotChartTransformer(), tables)
        assert result["season_year"].null_count() == 1
