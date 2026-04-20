"""Tests for agg_player_season aggregate transform."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.derived.agg_player_season import (
    AggPlayerSeasonTransformer,
)


def _run(transformer, tables: dict[str, pl.DataFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    for key, val in tables.items():
        conn.register(key, val)
    transformer._conn = conn
    result = transformer.transform({})
    conn.close()
    return result


def _make_fact_traditional(**overrides):
    base = {
        "game_id": ["G1", "G2"],
        "player_id": [101, 101],
        "team_id": [1, 1],
        "season_year": ["2024-25", "2024-25"],
        "start_position": ["G", "G"],
        "comment": [None, None],
        "min": [30.0, 34.0],
        "fgm": [5, 7],
        "fga": [10, 14],
        "fg_pct": [0.5, 0.5],
        "fg3m": [2, 3],
        "fg3a": [5, 6],
        "fg3_pct": [0.4, 0.5],
        "ftm": [3, 4],
        "fta": [4, 5],
        "ft_pct": [0.75, 0.8],
        "oreb": [1, 2],
        "dreb": [4, 5],
        "reb": [5, 7],
        "ast": [6, 8],
        "stl": [2, 3],
        "blk": [1, 2],
        "tov": [3, 2],
        "pf": [2, 3],
        "pts": [15, 21],
        "plus_minus": [5.0, 10.0],
    }
    base.update(overrides)
    return pl.DataFrame(base)


def _make_dim_game(**overrides):
    base = {
        "game_id": ["G1", "G2"],
        "season_year": ["2024-25", "2024-25"],
        "season_type": ["Regular Season", "Regular Season"],
    }
    base.update(overrides)
    return pl.DataFrame(base)


def _make_dim_team(**overrides):
    base = {
        "team_id": [1],
        "abbreviation": ["LAL"],
    }
    base.update(overrides)
    return pl.DataFrame(base)


def _make_fact_advanced(**overrides):
    base = {
        "game_id": ["G1", "G2"],
        "player_id": [101, 101],
        "team_id": [1, 1],
        "min": [30.0, 34.0],
        "off_rating": [110.0, 120.0],
        "def_rating": [105.0, 109.0],
        "net_rating": [5.0, 11.0],
        "ts_pct": [0.58, 0.68],
        "usg_pct": [0.25, 0.35],
        "pie": [0.10, 0.20],
    }
    base.update(overrides)
    return pl.DataFrame(base)


# ---------------------------------------------------------------------------
# Class attribute tests
# ---------------------------------------------------------------------------


class TestClassAttributes:
    def test_output_table(self) -> None:
        assert AggPlayerSeasonTransformer.output_table == "agg_player_season"

    def test_depends_on(self) -> None:
        assert set(AggPlayerSeasonTransformer.depends_on) == {
            "fact_player_game_traditional",
            "fact_player_game_advanced",
            "dim_game",
            "dim_team",
        }


# ---------------------------------------------------------------------------
# team_abbreviation tests
# ---------------------------------------------------------------------------


class TestTeamAbbreviation:
    def test_team_abbreviation_present(self) -> None:
        """team_abbreviation should appear in the output from dim_team join."""
        result = _run(
            AggPlayerSeasonTransformer(),
            {
                "fact_player_game_traditional": _make_fact_traditional(),
                "dim_game": _make_dim_game(),
                "dim_team": _make_dim_team(),
                "fact_player_game_advanced": _make_fact_advanced(),
            },
        )

        assert "team_abbreviation" in result.columns
        row = result.row(0, named=True)
        assert row["team_abbreviation"] == "LAL"

    def test_team_abbreviation_null_when_no_match(self) -> None:
        """LEFT JOIN means missing teams yield null abbreviation."""
        dim_team = pl.DataFrame({"team_id": [999], "abbreviation": ["XXX"]})

        result = _run(
            AggPlayerSeasonTransformer(),
            {
                "fact_player_game_traditional": _make_fact_traditional(),
                "dim_game": _make_dim_game(),
                "dim_team": dim_team,
                "fact_player_game_advanced": _make_fact_advanced(),
            },
        )

        assert result.shape[0] == 1
        row = result.row(0, named=True)
        assert row["team_abbreviation"] is None

    def test_different_teams_produce_separate_rows(self) -> None:
        """A player traded mid-season should get separate rows per team."""
        fact = _make_fact_traditional(
            team_id=[1, 2],
        )
        dim_team = pl.DataFrame({"team_id": [1, 2], "abbreviation": ["LAL", "BOS"]})

        result = _run(
            AggPlayerSeasonTransformer(),
            {
                "fact_player_game_traditional": fact,
                "dim_game": _make_dim_game(),
                "dim_team": dim_team,
                "fact_player_game_advanced": _make_fact_advanced(team_id=[1, 2]),
            },
        )

        assert result.shape[0] == 2
        abbrevs = set(result["team_abbreviation"].to_list())
        assert abbrevs == {"LAL", "BOS"}


# ---------------------------------------------------------------------------
# Aggregation tests
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_basic_aggregation(self) -> None:
        """Two games should produce correct sums and averages."""
        result = _run(
            AggPlayerSeasonTransformer(),
            {
                "fact_player_game_traditional": _make_fact_traditional(),
                "dim_game": _make_dim_game(),
                "dim_team": _make_dim_team(),
                "fact_player_game_advanced": _make_fact_advanced(),
            },
        )

        assert result.shape[0] == 1
        row = result.row(0, named=True)
        assert row["gp"] == 2
        assert row["total_pts"] == pytest.approx(36.0)
        assert row["avg_pts"] == pytest.approx(18.0)
        assert row["total_min"] == pytest.approx(64.0)
        assert row["avg_min"] == pytest.approx(32.0)
        assert row["avg_off_rating"] == pytest.approx(115.0)
        assert row["avg_ts_pct"] == pytest.approx(0.63)

    def test_groups_by_season_type(self) -> None:
        """Regular Season and Playoffs produce separate rows."""
        dim_game = _make_dim_game(
            season_type=["Regular Season", "Playoffs"],
        )

        result = _run(
            AggPlayerSeasonTransformer(),
            {
                "fact_player_game_traditional": _make_fact_traditional(),
                "dim_game": dim_game,
                "dim_team": _make_dim_team(),
                "fact_player_game_advanced": _make_fact_advanced(),
            },
        )

        assert result.shape[0] == 2
        season_types = set(result["season_type"].to_list())
        assert season_types == {"Regular Season", "Playoffs"}
