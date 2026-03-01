"""Tests for analytics view transformers.

Verify column-name fixes and join correctness for all four
analytics views: player_game, player_season, team_season, head_to_head.
"""

from __future__ import annotations

import polars as pl

from nbadb.transform.views.analytics_head_to_head import (
    AnalyticsHeadToHeadTransformer,
)
from nbadb.transform.views.analytics_player_game_complete import (
    AnalyticsPlayerGameCompleteTransformer,
)
from nbadb.transform.views.analytics_player_season_complete import (
    AnalyticsPlayerSeasonCompleteTransformer,
)
from nbadb.transform.views.analytics_team_season_summary import (
    AnalyticsTeamSeasonSummaryTransformer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dim_player_df(
    player_id: int = 101,
    full_name: str = "Test Player",
    team_id: int = 1,
    *,
    include_historical: bool = False,
) -> pl.DataFrame:
    """Build a minimal dim_player DataFrame.

    When *include_historical* is True, two rows are returned for the same
    player_id: one historical (is_current=False) and one current.
    """
    rows: list[dict] = []
    if include_historical:
        rows.append(
            {
                "player_sk": 1,
                "player_id": player_id,
                "full_name": full_name,
                "position": "PG",
                "team_id": 99,
                "jersey_number": "0",
                "height": "6-3",
                "weight": 200,
                "birth_date": "1990-01-01",
                "country": "USA",
                "draft_year": 2010,
                "draft_round": 1,
                "draft_number": 5,
                "college_id": 1,
                "valid_from": 2018,
                "valid_to": 2020,
                "is_current": False,
            }
        )
    rows.append(
        {
            "player_sk": 2 if include_historical else 1,
            "player_id": player_id,
            "full_name": full_name,
            "position": "SG",
            "team_id": team_id,
            "jersey_number": "23",
            "height": "6-6",
            "weight": 220,
            "birth_date": "1990-01-01",
            "country": "USA",
            "draft_year": 2010,
            "draft_round": 1,
            "draft_number": 5,
            "college_id": 1,
            "valid_from": 2020,
            "valid_to": None,
            "is_current": True,
        }
    )
    return pl.DataFrame(rows)


def _dim_team_df(
    team_id: int = 1,
    abbreviation: str = "TST",
    full_name: str = "Test Team",
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "team_id": [team_id],
            "abbreviation": [abbreviation],
            "full_name": [full_name],
            "city": ["Test City"],
            "state": ["TS"],
            "arena": ["Test Arena"],
            "year_founded": [1970],
            "conference": ["East"],
            "division": ["Atlantic"],
        }
    )


def _dim_game_df(
    game_id: int = 1001,
    home_team_id: int = 1,
    visitor_team_id: int = 2,
    game_date: str = "2024-01-15",
) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": [game_id],
            "game_date": [game_date],
            "season_year": [2024],
            "season_type": ["Regular Season"],
            "home_team_id": [home_team_id],
            "visitor_team_id": [visitor_team_id],
            "matchup": ["TST vs OPP"],
            "arena_name": ["Test Arena"],
            "arena_city": ["Test City"],
        }
    )


# ---------------------------------------------------------------------------
# Test 1: analytics_player_game_complete
# ---------------------------------------------------------------------------

def test_analytics_player_game_complete():
    """View runs without column errors and is_current filter deduplicates SCD2 rows."""
    transformer = AnalyticsPlayerGameCompleteTransformer()

    # dim_player with 2 rows for same player (historical + current)
    dim_player = _dim_player_df(player_id=101, team_id=1, include_historical=True)
    dim_team = _dim_team_df(team_id=1)
    dim_game = _dim_game_df(game_id=1001)

    fact_trad = pl.DataFrame(
        {
            "player_id": [101],
            "game_id": [1001],
            "team_id": [1],
            "min": [30.0],
            "pts": [25],
            "reb": [5],
            "ast": [7],
            "stl": [2],
            "blk": [1],
            "tov": [3],
            "fgm": [9],
            "fga": [18],
            "fg_pct": [0.5],
            "fg3m": [3],
            "fg3a": [7],
            "fg3_pct": [0.429],
            "ftm": [4],
            "fta": [5],
            "ft_pct": [0.8],
            "oreb": [1],
            "dreb": [4],
            "pf": [2],
            "plus_minus": [10],
        }
    )
    fact_adv = pl.DataFrame(
        {
            "player_id": [101],
            "game_id": [1001],
            "off_rating": [115.0],
            "def_rating": [105.0],
            "net_rating": [10.0],
            "ast_pct": [0.3],
            "ast_ratio": [0.25],
            "reb_pct": [0.1],
            "oreb_pct": [0.05],
            "dreb_pct": [0.15],
            "efg_pct": [0.55],
            "ts_pct": [0.6],
            "pace": [100.0],
            "pie": [0.15],
        }
    )
    fact_misc = pl.DataFrame(
        {
            "player_id": [101],
            "game_id": [1001],
            "pts_off_tov": [5],
            "pts_2nd_chance": [4],
            "pts_fb": [6],
            "pts_paint": [10],
            "usg_pct": [0.28],
        }
    )
    fact_hustle = pl.DataFrame(
        {
            "player_id": [101],
            "game_id": [1001],
            "contested_shots": [8],
            "deflections": [3],
            "loose_balls_recovered": [2],
            "charges_drawn": [1],
            "screen_assists": [4],
        }
    )
    fact_tracking = pl.DataFrame(
        {
            "player_id": [101],
            "game_id": [1001],
            "dist_miles": [2.5],
            "speed": [4.3],
            "touches": [60],
            "passes": [40],
            "contested_shots_defended": [5],
            "dfg_pct": [0.42],
        }
    )

    staging = {
        "fact_player_game_traditional": fact_trad.lazy(),
        "fact_player_game_advanced": fact_adv.lazy(),
        "fact_player_game_misc": fact_misc.lazy(),
        "fact_player_game_hustle": fact_hustle.lazy(),
        "fact_player_game_tracking": fact_tracking.lazy(),
        "dim_player": dim_player.lazy(),
        "dim_game": dim_game.lazy(),
        "dim_team": dim_team.lazy(),
    }

    result = transformer.transform(staging)

    # is_current filter should prevent SCD2 row multiplication
    assert result.shape[0] == 1, f"Expected 1 row, got {result.shape[0]}"
    assert "player_name" in result.columns
    assert "team_abbreviation" in result.columns
    assert result["player_name"][0] == "Test Player"
    assert result["team_abbreviation"][0] == "TST"


# ---------------------------------------------------------------------------
# Test 2: analytics_player_season_complete
# ---------------------------------------------------------------------------

def test_analytics_player_season_complete():
    """View runs with correct column names and no SCD2 row multiplication."""
    transformer = AnalyticsPlayerSeasonCompleteTransformer()

    dim_player = _dim_player_df(player_id=101, team_id=1, include_historical=True)
    dim_team = _dim_team_df(team_id=1)

    agg_season = pl.DataFrame(
        {
            "player_id": [101],
            "team_id": [1],
            "season_year": [2024],
            "season_type": ["Regular Season"],
            "gp": [82],
            "total_min": [2800.0],
            "avg_min": [34.1],
            "total_pts": [2050],
            "avg_pts": [25.0],
            "total_reb": [410],
            "avg_reb": [5.0],
            "total_ast": [574],
            "avg_ast": [7.0],
            "total_stl": [164],
            "avg_stl": [2.0],
            "total_blk": [82],
            "avg_blk": [1.0],
            "total_tov": [246],
            "avg_tov": [3.0],
            "total_fgm": [738],
            "total_fga": [1476],
            "fg_pct": [0.5],
            "total_fg3m": [246],
            "total_fg3a": [574],
            "fg3_pct": [0.429],
            "total_ftm": [328],
            "total_fta": [410],
            "ft_pct": [0.8],
            "avg_off_rating": [115.0],
            "avg_def_rating": [105.0],
            "avg_net_rating": [10.0],
            "avg_ts_pct": [0.6],
            "avg_usg_pct": [0.28],
            "avg_pie": [0.15],
        }
    )
    per36 = pl.DataFrame(
        {
            "player_id": [101],
            "season_year": [2024],
            "season_type": ["Regular Season"],
            "gp": [82],
            "avg_min": [34.1],
            "pts_per36": [26.4],
            "reb_per36": [5.3],
            "ast_per36": [7.4],
            "stl_per36": [2.1],
            "blk_per36": [1.1],
            "tov_per36": [3.2],
        }
    )
    per100 = pl.DataFrame(
        {
            "player_id": [101],
            "season_year": [2024],
            "season_type": ["Regular Season"],
            "gp": [82],
            "avg_min": [34.1],
            "pts_per100": [35.1],
            "reb_per100": [7.0],
            "ast_per100": [9.8],
            "stl_per100": [2.8],
            "blk_per100": [1.4],
            "tov_per100": [4.2],
        }
    )

    staging = {
        "agg_player_season": agg_season.lazy(),
        "agg_player_season_per36": per36.lazy(),
        "agg_player_season_per100": per100.lazy(),
        "dim_player": dim_player.lazy(),
        "dim_team": dim_team.lazy(),
    }

    result = transformer.transform(staging)

    assert result.shape[0] == 1, f"Expected 1 row, got {result.shape[0]}"
    assert "player_name" in result.columns
    assert "team_abbreviation" in result.columns
    assert "fg_pct" in result.columns
    assert result["player_name"][0] == "Test Player"


# ---------------------------------------------------------------------------
# Test 3: analytics_team_season_summary
# ---------------------------------------------------------------------------

def test_analytics_team_season_summary():
    """View uses standings for wins/losses and correct dim_team columns."""
    transformer = AnalyticsTeamSeasonSummaryTransformer()

    dim_team = _dim_team_df(team_id=1, full_name="Test Team", abbreviation="TST")

    agg_team = pl.DataFrame(
        {
            "team_id": [1],
            "season_year": [2024],
            "season_type": ["Regular Season"],
            "gp": [82],
            "avg_pts": [110.5],
            "avg_reb": [44.0],
            "avg_ast": [25.0],
            "avg_stl": [8.0],
            "avg_blk": [5.0],
            "avg_tov": [13.5],
            "fg_pct": [0.48],
            "fg3_pct": [0.37],
            "ft_pct": [0.79],
        }
    )
    standings = pl.DataFrame(
        {
            "team_id": [1],
            "season_year": [2024],
            "conference": ["East"],
            "division": ["Atlantic"],
            "wins": [52],
            "losses": [30],
            "win_pct": [0.634],
            "conference_rank": [3],
            "division_rank": [2],
            "home_record": ["30-11"],
            "road_record": ["22-19"],
            "last_ten": ["7-3"],
            "streak": ["W3"],
            "standings_date": ["2024-04-14"],
        }
    )

    staging = {
        "agg_team_season": agg_team.lazy(),
        "fact_standings": standings.lazy(),
        "dim_team": dim_team.lazy(),
    }

    result = transformer.transform(staging)

    assert result.shape[0] == 1
    assert "team_name" in result.columns
    assert "team_abbreviation" in result.columns
    assert "wins" in result.columns
    assert "losses" in result.columns
    assert result["team_name"][0] == "Test Team"
    assert result["wins"][0] == 52
    assert result["losses"][0] == 30
    # These columns should NOT exist in the fixed view
    assert "playoff_seed" not in result.columns
    assert "avg_pts_allowed" not in result.columns


# ---------------------------------------------------------------------------
# Test 4: analytics_head_to_head
# ---------------------------------------------------------------------------

def test_analytics_head_to_head():
    """Head-to-head derives opponent and W/L from dim_game correctly."""
    transformer = AnalyticsHeadToHeadTransformer()

    dim_team = pl.concat(
        [
            _dim_team_df(team_id=1, abbreviation="AAA", full_name="Alpha"),
            _dim_team_df(team_id=2, abbreviation="BBB", full_name="Beta"),
        ]
    )
    dim_game = _dim_game_df(game_id=1001, home_team_id=1, visitor_team_id=2)

    fact_team_game = pl.DataFrame(
        {
            "game_id": [1001, 1001],
            "team_id": [1, 2],
            "fgm": [40, 35],
            "fga": [85, 82],
            "fg_pct": [0.47, 0.43],
            "fg3m": [12, 10],
            "fg3a": [30, 28],
            "fg3_pct": [0.40, 0.36],
            "ftm": [18, 15],
            "fta": [22, 20],
            "ft_pct": [0.82, 0.75],
            "oreb": [10, 8],
            "dreb": [32, 30],
            "reb": [42, 38],
            "ast": [25, 20],
            "stl": [8, 6],
            "blk": [5, 4],
            "tov": [12, 14],
            "pf": [18, 20],
            "pts": [110, 95],
            "pts_qtr1": [28, 22],
            "pts_qtr2": [30, 25],
            "pts_qtr3": [27, 24],
            "pts_qtr4": [25, 24],
        }
    )

    staging = {
        "fact_team_game": fact_team_game.lazy(),
        "dim_team": dim_team.lazy(),
        "dim_game": dim_game.lazy(),
    }

    result = transformer.transform(staging)

    # 2 rows: one per team perspective for this single game
    assert result.shape[0] == 2, f"Expected 2 rows, got {result.shape[0]}"

    # Team 1 (home, higher pts) should have wins=1
    team1_row = result.filter(pl.col("team_id") == 1)
    assert team1_row["wins"][0] == 1
    assert team1_row["losses"][0] == 0

    # Team 2 (visitor, lower pts) should have losses=1
    team2_row = result.filter(pl.col("team_id") == 2)
    assert team2_row["wins"][0] == 0
    assert team2_row["losses"][0] == 1
