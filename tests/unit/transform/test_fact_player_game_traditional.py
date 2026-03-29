"""Tests for fact_player_game_traditional transform."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.facts.fact_player_game_traditional import (
    FactPlayerGameTraditionalTransformer,
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
        assert FactPlayerGameTraditionalTransformer.output_table == "fact_player_game_traditional"

    def test_depends_on(self) -> None:
        assert set(FactPlayerGameTraditionalTransformer.depends_on) == {
            "stg_box_score_traditional",
            "dim_game",
        }


# ---------------------------------------------------------------------------
# SQL transform tests
# ---------------------------------------------------------------------------


class TestMinCast:
    """Verify that the string min column from staging is cast to float."""

    def test_min_cast_to_float(self) -> None:
        stg = pl.DataFrame(
            {
                "game_id": ["G1"],
                "player_id": [101],
                "team_id": [1],
                "start_position": ["G"],
                "comment": [None],
                "min": ["32.5"],
                "fgm": [5.0],
                "fga": [10.0],
                "fg_pct": [0.5],
                "fg3m": [2.0],
                "fg3a": [5.0],
                "fg3_pct": [0.4],
                "ftm": [3.0],
                "fta": [4.0],
                "ft_pct": [0.75],
                "oreb": [1.0],
                "dreb": [4.0],
                "reb": [5.0],
                "ast": [6.0],
                "stl": [2.0],
                "blk": [1.0],
                "tov": [3.0],
                "pf": [2.0],
                "pts": [15.0],
                "plus_minus": [5.0],
            }
        )
        dim_game = pl.DataFrame(
            {"game_id": ["G1"], "season_year": ["2024-25"]}
        )

        result = _run(
            FactPlayerGameTraditionalTransformer(),
            {"stg_box_score_traditional": stg, "dim_game": dim_game},
        )

        assert result.shape[0] == 1
        row = result.row(0, named=True)
        assert isinstance(row["min"], float)
        assert row["min"] == pytest.approx(32.5)

    def test_min_null_preserved(self) -> None:
        stg = pl.DataFrame(
            {
                "game_id": ["G1"],
                "player_id": [101],
                "team_id": [1],
                "start_position": [None],
                "comment": [None],
                "min": [None],
                "fgm": [None],
                "fga": [None],
                "fg_pct": [None],
                "fg3m": [None],
                "fg3a": [None],
                "fg3_pct": [None],
                "ftm": [None],
                "fta": [None],
                "ft_pct": [None],
                "oreb": [None],
                "dreb": [None],
                "reb": [None],
                "ast": [None],
                "stl": [None],
                "blk": [None],
                "tov": [None],
                "pf": [None],
                "pts": [None],
                "plus_minus": [None],
            }
        )
        dim_game = pl.DataFrame(
            {"game_id": ["G1"], "season_year": ["2024-25"]}
        )

        result = _run(
            FactPlayerGameTraditionalTransformer(),
            {"stg_box_score_traditional": stg, "dim_game": dim_game},
        )

        row = result.row(0, named=True)
        assert row["min"] is None

    def test_excludes_null_player_id(self) -> None:
        stg = pl.DataFrame(
            {
                "game_id": ["G1", "G2"],
                "player_id": [101, None],
                "team_id": [1, 2],
                "start_position": ["G", "F"],
                "comment": [None, None],
                "min": ["30.0", "25.0"],
                "fgm": [5.0, 3.0],
                "fga": [10.0, 8.0],
                "fg_pct": [0.5, 0.375],
                "fg3m": [2.0, 1.0],
                "fg3a": [5.0, 3.0],
                "fg3_pct": [0.4, 0.333],
                "ftm": [3.0, 2.0],
                "fta": [4.0, 2.0],
                "ft_pct": [0.75, 1.0],
                "oreb": [1.0, 0.0],
                "dreb": [4.0, 3.0],
                "reb": [5.0, 3.0],
                "ast": [6.0, 4.0],
                "stl": [2.0, 1.0],
                "blk": [1.0, 0.0],
                "tov": [3.0, 2.0],
                "pf": [2.0, 1.0],
                "pts": [15.0, 9.0],
                "plus_minus": [5.0, -3.0],
            }
        )
        dim_game = pl.DataFrame(
            {"game_id": ["G1", "G2"], "season_year": ["2024-25", "2024-25"]}
        )

        result = _run(
            FactPlayerGameTraditionalTransformer(),
            {"stg_box_score_traditional": stg, "dim_game": dim_game},
        )

        assert result.shape[0] == 1
        assert result["player_id"][0] == 101
