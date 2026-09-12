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

        # Provider metrics are exposure weighted, never raw per-game averages.
        def weighted(first: float, second: float) -> float:
            return (first * 50.0 + second * 55.0) / 105.0

        assert row["avg_off_rating"] == pytest.approx(weighted(110.0, 120.0))
        assert row["avg_def_rating"] == pytest.approx(weighted(105.0, 109.0))
        assert row["avg_net_rating"] == pytest.approx(weighted(5.0, 11.0))
        assert row["avg_ts_pct"] == pytest.approx(weighted(0.58, 0.68))
        assert row["avg_usg_pct"] == pytest.approx(weighted(0.25, 0.35))
        assert row["avg_efg_pct"] == pytest.approx(weighted(0.55, 0.65))
        assert row["avg_ast_pct"] == pytest.approx(weighted(0.20, 0.30))
        assert row["avg_ast_ratio"] == pytest.approx(weighted(15.0, 25.0))
        assert row["avg_oreb_pct"] == pytest.approx(weighted(0.04, 0.06))
        assert row["avg_dreb_pct"] == pytest.approx(weighted(0.18, 0.22))
        assert row["avg_reb_pct"] == pytest.approx(weighted(0.10, 0.14))
        assert row["avg_tov_pct"] == pytest.approx(weighted(0.12, 0.08))
        assert row["avg_pace"] == pytest.approx((98.0 * 30.0 + 102.0 * 34.0) / 64.0)
        assert row["avg_pie"] == pytest.approx(weighted(0.10, 0.20))
        assert row["off_rating_covered_games"] == 2
        assert row["off_rating_covered_possessions"] == pytest.approx(105.0)
        assert row["advanced_metric_source"] == "provider_possession_weighted"
        assert row["pace_source"] == "provider_minute_weighted"

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


class TestAuthorityAndExposure:
    @staticmethod
    def _fact() -> pl.DataFrame:
        return pl.DataFrame(
            {
                "game_id": ["G1", "G2"],
                "player_id": [101, 101],
                "team_id": [1, 1],
                "min": [10.0, 40.0],
                "off_rating": [80.0, 120.0],
                "def_rating": [115.0, 100.0],
                "net_rating": [-35.0, 20.0],
                "ast_pct": [0.10, 0.40],
                "ast_ratio": [10.0, 30.0],
                "oreb_pct": [0.02, 0.08],
                "dreb_pct": [0.10, 0.25],
                "reb_pct": [0.06, 0.16],
                "tov_pct": [0.20, 0.05],
                "efg_pct": [0.20, 0.70],
                "ts_pct": [0.25, 0.75],
                "usg_pct": [0.10, 0.40],
                "pace": [90.0, 110.0],
                "poss": [10.0, 90.0],
                "pie": [0.01, 0.20],
            }
        )

    @staticmethod
    def _games() -> pl.DataFrame:
        return pl.DataFrame(
            {
                "game_id": ["G1", "G2"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Regular Season"],
            }
        )

    def test_weighted_metrics_differ_from_simple_game_averages(self) -> None:
        fact = self._fact()
        result = _run(
            AggPlayerSeasonAdvancedTransformer(),
            {"fact_player_game_advanced": fact, "dim_game": self._games()},
        )

        row = result.row(0, named=True)
        assert row["avg_off_rating"] == pytest.approx(116.0)
        assert row["avg_off_rating"] != pytest.approx(fact["off_rating"].mean())
        assert row["avg_ts_pct"] == pytest.approx(0.70)
        assert row["avg_ts_pct"] != pytest.approx(fact["ts_pct"].mean())
        assert row["avg_pace"] == pytest.approx(106.0)
        assert row["avg_pace"] != pytest.approx(fact["pace"].mean())
        assert row["off_rating_covered_games"] == 2
        assert row["off_rating_covered_possessions"] == pytest.approx(100.0)
        assert row["pace_covered_minutes"] == pytest.approx(50.0)

    def test_groups_by_team_within_season_and_type(self) -> None:
        fact = self._fact().with_columns(pl.Series("team_id", [1, 2]))
        result = _run(
            AggPlayerSeasonAdvancedTransformer(),
            {"fact_player_game_advanced": fact, "dim_game": self._games()},
        )

        assert result.shape[0] == 2
        assert set(result["team_id"].to_list()) == {1, 2}
        assert result["gp"].to_list() == [1, 1]

    def test_exact_duplicates_are_idempotent(self) -> None:
        fact = self._fact()
        games = self._games()
        result = _run(
            AggPlayerSeasonAdvancedTransformer(),
            {
                "fact_player_game_advanced": pl.concat([fact, fact], how="vertical"),
                "dim_game": pl.concat([games, games], how="vertical"),
            },
        )

        row = result.row(0, named=True)
        assert row["gp"] == 2
        assert row["total_possessions"] == pytest.approx(100.0)

    def test_conflicting_same_key_rows_fail_closed(self) -> None:
        fact = self._fact()
        conflict = fact.head(1).with_columns(pl.lit(999.0).alias("off_rating"))

        with pytest.raises(duckdb.Error, match="conflicting player-game rows"):
            _run(
                AggPlayerSeasonAdvancedTransformer(),
                {
                    "fact_player_game_advanced": pl.concat([fact, conflict], how="vertical"),
                    "dim_game": self._games(),
                },
            )

    def test_conflicting_game_dimension_rows_fail_closed(self) -> None:
        games = pl.concat(
            [
                self._games(),
                self._games().head(1).with_columns(pl.lit("Playoffs").alias("season_type")),
            ],
            how="vertical",
        )

        with pytest.raises(duckdb.Error, match="conflicting game-dimension rows"):
            _run(
                AggPlayerSeasonAdvancedTransformer(),
                {"fact_player_game_advanced": self._fact(), "dim_game": games},
            )
