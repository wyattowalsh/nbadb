"""Tests for derived transformers: agg_player_season, agg_team_season, agg_player_rolling.

Verify column fixes (team_id inclusion) and dependency declarations.
"""

from __future__ import annotations

import polars as pl
import pytest


# ---------------------------------------------------------------------------
# Dependency declaration tests
# ---------------------------------------------------------------------------


def test_agg_player_season_has_dim_game_dependency():
    from nbadb.transform.derived.agg_player_season import AggPlayerSeasonTransformer

    assert "dim_game" in AggPlayerSeasonTransformer.depends_on


def test_agg_player_rolling_has_dim_game_dependency():
    from nbadb.transform.derived.agg_player_rolling import AggPlayerRollingTransformer

    assert "dim_game" in AggPlayerRollingTransformer.depends_on


def test_agg_team_season_has_dim_game_dependency():
    from nbadb.transform.derived.agg_team_season import AggTeamSeasonTransformer

    assert "dim_game" in AggTeamSeasonTransformer.depends_on


def test_dim_player_no_phantom_dependency():
    from nbadb.transform.dimensions.dim_player import DimPlayerTransformer

    assert "stg_player_career" not in DimPlayerTransformer.depends_on


# ---------------------------------------------------------------------------
# Functional test: agg_player_season includes team_id
# ---------------------------------------------------------------------------


def test_agg_player_season_includes_team_id():
    """After fix, agg_player_season should include team_id in output."""
    from nbadb.transform.derived.agg_player_season import AggPlayerSeasonTransformer

    transformer = AggPlayerSeasonTransformer()

    fact_trad = pl.DataFrame(
        {
            "player_id": [101, 101],
            "game_id": [1001, 1002],
            "team_id": [1, 1],
            "min": [30.0, 28.0],
            "pts": [25, 20],
            "reb": [5, 6],
            "ast": [7, 5],
            "stl": [2, 1],
            "blk": [1, 0],
            "tov": [3, 2],
            "fgm": [9, 8],
            "fga": [18, 17],
            "fg_pct": [0.5, 0.47],
            "fg3m": [3, 2],
            "fg3a": [7, 6],
            "fg3_pct": [0.43, 0.33],
            "ftm": [4, 2],
            "fta": [5, 3],
            "ft_pct": [0.8, 0.67],
            "oreb": [1, 2],
            "dreb": [4, 4],
            "pf": [2, 3],
            "plus_minus": [10, -2],
        }
    )
    fact_adv = pl.DataFrame(
        {
            "player_id": [101, 101],
            "game_id": [1001, 1002],
            "off_rating": [115.0, 108.0],
            "def_rating": [105.0, 110.0],
            "net_rating": [10.0, -2.0],
            "ast_pct": [0.3, 0.25],
            "ast_ratio": [0.25, 0.2],
            "reb_pct": [0.1, 0.12],
            "oreb_pct": [0.05, 0.07],
            "dreb_pct": [0.15, 0.14],
            "efg_pct": [0.55, 0.5],
            "ts_pct": [0.6, 0.55],
            "pace": [100.0, 98.0],
            "pie": [0.15, 0.1],
            "usg_pct": [0.28, 0.25],
        }
    )
    dim_game = pl.DataFrame(
        {
            "game_id": [1001, 1002],
            "game_date": ["2024-01-15", "2024-01-17"],
            "season_year": [2024, 2024],
            "season_type": ["Regular Season", "Regular Season"],
            "home_team_id": [1, 2],
            "visitor_team_id": [2, 1],
            "matchup": ["TST vs OPP", "OPP vs TST"],
            "arena_name": ["Arena A", "Arena B"],
            "arena_city": ["City A", "City B"],
        }
    )

    staging = {
        "fact_player_game_traditional": fact_trad.lazy(),
        "fact_player_game_advanced": fact_adv.lazy(),
        "fact_player_game_misc": pl.DataFrame(
            {
                "player_id": [101, 101],
                "game_id": [1001, 1002],
                "pts_off_tov": [5, 3],
                "pts_2nd_chance": [4, 2],
                "pts_fb": [6, 4],
                "pts_paint": [10, 8],
                "usg_pct": [0.28, 0.25],
            }
        ).lazy(),
        "dim_game": dim_game.lazy(),
    }

    result = transformer.transform(staging)

    assert "team_id" in result.columns, f"team_id missing from output: {result.columns}"
    assert result.shape[0] == 1  # grouped by player, team, season, type
    assert result["team_id"][0] == 1
