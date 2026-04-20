"""Tests for agg_team_defense aggregate transformer."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.derived.agg_team_defense import AggTeamDefenseTransformer


def _run(transformer: AggTeamDefenseTransformer, staging: dict[str, pl.DataFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, df in staging.items():
            conn.register(key, df)
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


class TestAggTeamDefenseMetadata:
    def test_output_table(self) -> None:
        assert AggTeamDefenseTransformer.output_table == "agg_team_defense"

    def test_depends_on(self) -> None:
        deps = AggTeamDefenseTransformer.depends_on
        assert "fact_box_score_advanced_team" in deps
        assert "fact_team_game_hustle" in deps
        assert "fact_box_score_four_factors_team" in deps
        assert "dim_game" in deps


class TestAggTeamDefenseAggregation:
    @pytest.fixture()
    def staging(self) -> dict[str, pl.DataFrame]:
        """Two games for one team in a single season/season_type."""
        advanced = pl.DataFrame(
            {
                "game_id": ["001", "002"],
                "team_id": [1610612738, 1610612738],
                "off_rating": [112.0, 108.0],
                "def_rating": [105.0, 110.0],
                "net_rating": [7.0, -2.0],
                "pace": [98.0, 100.0],
                "ast_pct": [0.3, 0.28],
                "reb_pct": [0.5, 0.48],
                "oreb_pct": [0.25, 0.22],
                "dreb_pct": [0.75, 0.78],
                "efg_pct": [0.55, 0.52],
                "ts_pct": [0.60, 0.57],
                "pie": [0.55, 0.48],
            }
        )
        hustle = pl.DataFrame(
            {
                "game_id": ["001", "002"],
                "team_id": [1610612738, 1610612738],
                "contested_shots": [40.0, 50.0],
                "contested_shots_2pt": [25.0, 30.0],
                "contested_shots_3pt": [15.0, 20.0],
                "deflections": [10.0, 14.0],
                "loose_balls_recovered": [6.0, 8.0],
                "charges_drawn": [1.0, 3.0],
                "screen_assists": [8.0, 12.0],
                "screen_ast_pts": [16.0, 24.0],
                "box_outs": [5.0, 7.0],
            }
        )
        four_factors = pl.DataFrame(
            {
                "game_id": ["001", "002"],
                "team_id": [1610612738, 1610612738],
                "effective_field_goal_percentage": [0.55, 0.52],
                "free_throw_attempt_rate": [0.25, 0.28],
                "team_turnover_percentage": [0.12, 0.14],
                "offensive_rebound_percentage": [0.28, 0.30],
                "opp_effective_field_goal_percentage": [0.48, 0.52],
                "opp_free_throw_attempt_rate": [0.22, 0.26],
                "opp_team_turnover_percentage": [0.15, 0.13],
                "opp_offensive_rebound_percentage": [0.24, 0.28],
            }
        )
        dim_game = pl.DataFrame(
            {
                "game_id": ["001", "002"],
                "game_date": ["2025-01-10", "2025-01-12"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Regular Season"],
                "home_team_id": [1610612738, 1610612751],
                "visitor_team_id": [1610612751, 1610612738],
                "matchup": ["BOS vs BKN", "BKN vs BOS"],
                "arena_name": ["TD Garden", "Barclays Center"],
                "arena_city": ["Boston", "Brooklyn"],
            }
        )
        return {
            "fact_box_score_advanced_team": advanced,
            "fact_team_game_hustle": hustle,
            "fact_box_score_four_factors_team": four_factors,
            "dim_game": dim_game,
        }

    def test_basic_defense_aggregation(self, staging: dict[str, pl.DataFrame]) -> None:
        transformer = AggTeamDefenseTransformer()
        result = _run(transformer, staging)

        assert result.shape[0] == 1
        row = result.row(0, named=True)

        assert row["team_id"] == 1610612738
        assert row["season_year"] == "2024-25"
        assert row["season_type"] == "Regular Season"
        assert row["gp"] == 2

        # AVG(105.0, 110.0) = 107.5
        assert row["avg_def_rating"] == pytest.approx(107.5)
        # AVG(7.0, -2.0) = 2.5
        assert row["avg_net_rating"] == pytest.approx(2.5)
        # AVG(0.48, 0.52) = 0.50
        assert row["avg_opp_efg_pct"] == pytest.approx(0.50)
        # AVG(0.22, 0.26) = 0.24
        assert row["avg_opp_fta_rate"] == pytest.approx(0.24)
        # AVG(0.15, 0.13) = 0.14
        assert row["avg_opp_tov_pct"] == pytest.approx(0.14)
        # AVG(0.24, 0.28) = 0.26
        assert row["avg_opp_oreb_pct"] == pytest.approx(0.26)
        # AVG(40.0, 50.0) = 45.0
        assert row["avg_contested_shots"] == pytest.approx(45.0)
        # AVG(10.0, 14.0) = 12.0
        assert row["avg_deflections"] == pytest.approx(12.0)
        # AVG(6.0, 8.0) = 7.0
        assert row["avg_loose_balls_recovered"] == pytest.approx(7.0)
        # AVG(1.0, 3.0) = 2.0
        assert row["avg_charges_drawn"] == pytest.approx(2.0)
        # AVG(8.0, 12.0) = 10.0
        assert row["avg_screen_assists"] == pytest.approx(10.0)

    def test_groups_by_season_type(self, staging: dict[str, pl.DataFrame]) -> None:
        """When games span Regular Season and Playoffs, produce separate rows."""
        # Modify dim_game so second game is Playoffs
        staging["dim_game"] = staging["dim_game"].with_columns(
            pl.when(pl.col("game_id") == "002")
            .then(pl.lit("Playoffs"))
            .otherwise(pl.col("season_type"))
            .alias("season_type")
        )

        transformer = AggTeamDefenseTransformer()
        result = _run(transformer, staging)

        assert result.shape[0] == 2

        reg = result.filter(pl.col("season_type") == "Regular Season")
        po = result.filter(pl.col("season_type") == "Playoffs")

        assert reg.shape[0] == 1
        assert po.shape[0] == 1

        # Regular season: only game 001
        assert reg["gp"][0] == 1
        assert reg["avg_def_rating"][0] == pytest.approx(105.0)

        # Playoffs: only game 002
        assert po["gp"][0] == 1
        assert po["avg_def_rating"][0] == pytest.approx(110.0)


class TestAggTeamDefenseNullHustle:
    def test_null_hustle_columns_when_no_hustle_data(self) -> None:
        """When hustle data is missing, hustle columns should be NULL."""
        advanced = pl.DataFrame(
            {
                "game_id": ["001"],
                "team_id": [1610612738],
                "off_rating": [112.0],
                "def_rating": [105.0],
                "net_rating": [7.0],
                "pace": [98.0],
                "ast_pct": [0.3],
                "reb_pct": [0.5],
                "oreb_pct": [0.25],
                "dreb_pct": [0.75],
                "efg_pct": [0.55],
                "ts_pct": [0.60],
                "pie": [0.55],
            }
        )
        # Empty hustle and four_factors tables with correct schema
        hustle = pl.DataFrame(
            {
                "game_id": pl.Series([], dtype=pl.Utf8),
                "team_id": pl.Series([], dtype=pl.Int64),
                "contested_shots": pl.Series([], dtype=pl.Float64),
                "deflections": pl.Series([], dtype=pl.Float64),
                "loose_balls_recovered": pl.Series([], dtype=pl.Float64),
                "charges_drawn": pl.Series([], dtype=pl.Float64),
                "screen_assists": pl.Series([], dtype=pl.Float64),
            }
        )
        four_factors = pl.DataFrame(
            {
                "game_id": pl.Series([], dtype=pl.Utf8),
                "team_id": pl.Series([], dtype=pl.Int64),
                "opp_effective_field_goal_percentage": pl.Series([], dtype=pl.Float64),
                "opp_free_throw_attempt_rate": pl.Series([], dtype=pl.Float64),
                "opp_team_turnover_percentage": pl.Series([], dtype=pl.Float64),
                "opp_offensive_rebound_percentage": pl.Series([], dtype=pl.Float64),
            }
        )
        dim_game = pl.DataFrame(
            {
                "game_id": ["001"],
                "game_date": ["2025-01-10"],
                "season_year": ["2024-25"],
                "season_type": ["Regular Season"],
                "home_team_id": [1610612738],
                "visitor_team_id": [1610612751],
                "matchup": ["BOS vs BKN"],
                "arena_name": ["TD Garden"],
                "arena_city": ["Boston"],
            }
        )

        staging = {
            "fact_box_score_advanced_team": advanced,
            "fact_team_game_hustle": hustle,
            "fact_box_score_four_factors_team": four_factors,
            "dim_game": dim_game,
        }

        transformer = AggTeamDefenseTransformer()
        result = _run(transformer, staging)

        assert result.shape[0] == 1
        row = result.row(0, named=True)
        assert row["gp"] == 1
        assert row["avg_def_rating"] == pytest.approx(105.0)
        # Hustle and four_factors columns should be NULL (no matching rows)
        assert row["avg_contested_shots"] is None
        assert row["avg_deflections"] is None
        assert row["avg_opp_efg_pct"] is None
