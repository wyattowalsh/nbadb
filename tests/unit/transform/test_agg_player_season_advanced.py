"""Tests for agg_player_season_advanced aggregate transform."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.derived.agg_player_season_advanced import (
    AggPlayerSeasonAdvancedTransformer,
)


def _run(transformer, tables: dict[str, pl.DataFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    for key, val in tables.items():
        conn.register(key, val)
    transformer._conn = conn
    result = transformer.transform({})
    conn.close()
    return result


# ---------------------------------------------------------------------------
# Class attribute tests
# ---------------------------------------------------------------------------


class TestClassAttributes:
    def test_output_table(self) -> None:
        assert AggPlayerSeasonAdvancedTransformer.output_table == "agg_player_season_advanced"

    def test_depends_on(self) -> None:
        assert set(AggPlayerSeasonAdvancedTransformer.depends_on) == {
            "fact_player_game_advanced",
            "dim_game",
        }


# ---------------------------------------------------------------------------
# SQL aggregation tests
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_basic_aggregation(self) -> None:
        """Two games for the same player/team/season should produce averaged stats."""
        fact = pl.DataFrame(
            {
                "game_id": ["G1", "G2"],
                "player_id": [101, 101],
                "team_id": [1, 1],
                "min": [30.0, 34.0],
                "off_rating": [110.0, 120.0],
                "def_rating": [105.0, 109.0],
                "net_rating": [5.0, 11.0],
                "ast_pct": [0.20, 0.30],
                "ast_tov": [2.0, 3.0],
                "ast_ratio": [15.0, 25.0],
                "oreb_pct": [0.04, 0.06],
                "dreb_pct": [0.18, 0.22],
                "reb_pct": [0.10, 0.14],
                "tov_pct": [0.12, 0.08],
                "efg_pct": [0.55, 0.65],
                "ts_pct": [0.58, 0.68],
                "usg_pct": [0.25, 0.35],
                "pace": [98.0, 102.0],
                "poss": [50.0, 55.0],
                "pie": [0.10, 0.20],
                "e_off_rating": [111.0, 121.0],
                "e_def_rating": [106.0, 110.0],
                "e_net_rating": [5.0, 11.0],
                "e_usg_pct": [0.26, 0.36],
                "e_pace": [99.0, 103.0],
            }
        )
        dim_game = pl.DataFrame(
            {
                "game_id": ["G1", "G2"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Regular Season"],
            }
        )

        result = _run(
            AggPlayerSeasonAdvancedTransformer(),
            {"fact_player_game_advanced": fact, "dim_game": dim_game},
        )

        assert result.shape[0] == 1
        row = result.row(0, named=True)
        assert row["player_id"] == 101
        assert row["team_id"] == 1
        assert row["season_year"] == "2024-25"
        assert row["season_type"] == "Regular Season"
        assert row["gp"] == 2
        # Averages
        assert row["avg_off_rating"] == pytest.approx(115.0)
        assert row["avg_def_rating"] == pytest.approx(107.0)
        assert row["avg_net_rating"] == pytest.approx(8.0)
        assert row["avg_ts_pct"] == pytest.approx(0.63)
        assert row["avg_usg_pct"] == pytest.approx(0.30)
        assert row["avg_efg_pct"] == pytest.approx(0.60)
        assert row["avg_ast_pct"] == pytest.approx(0.25)
        assert row["avg_ast_ratio"] == pytest.approx(20.0)
        assert row["avg_oreb_pct"] == pytest.approx(0.05)
        assert row["avg_dreb_pct"] == pytest.approx(0.20)
        assert row["avg_reb_pct"] == pytest.approx(0.12)
        assert row["avg_tov_pct"] == pytest.approx(0.10)
        assert row["avg_pace"] == pytest.approx(100.0)
        assert row["avg_pie"] == pytest.approx(0.15)

    def test_groups_by_season_type(self) -> None:
        """Regular Season and Playoffs games produce separate rows."""
        fact = pl.DataFrame(
            {
                "game_id": ["G1", "G2"],
                "player_id": [101, 101],
                "team_id": [1, 1],
                "min": [32.0, 36.0],
                "off_rating": [115.0, 120.0],
                "def_rating": [108.0, 105.0],
                "net_rating": [7.0, 15.0],
                "ast_pct": [0.25, 0.28],
                "ast_tov": [2.5, 3.0],
                "ast_ratio": [18.0, 22.0],
                "oreb_pct": [0.05, 0.04],
                "dreb_pct": [0.20, 0.19],
                "reb_pct": [0.12, 0.11],
                "tov_pct": [0.10, 0.09],
                "efg_pct": [0.58, 0.62],
                "ts_pct": [0.60, 0.65],
                "usg_pct": [0.28, 0.32],
                "pace": [100.0, 96.0],
                "poss": [52.0, 48.0],
                "pie": [0.14, 0.18],
                "e_off_rating": [116.0, 121.0],
                "e_def_rating": [109.0, 106.0],
                "e_net_rating": [7.0, 15.0],
                "e_usg_pct": [0.29, 0.33],
                "e_pace": [101.0, 97.0],
            }
        )
        dim_game = pl.DataFrame(
            {
                "game_id": ["G1", "G2"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Playoffs"],
            }
        )

        result = _run(
            AggPlayerSeasonAdvancedTransformer(),
            {"fact_player_game_advanced": fact, "dim_game": dim_game},
        )

        assert result.shape[0] == 2
        season_types = set(result["season_type"].to_list())
        assert season_types == {"Regular Season", "Playoffs"}
        # Each group has exactly 1 game
        assert all(gp == 1 for gp in result["gp"].to_list())
