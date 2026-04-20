"""Tests for analytics_league_benchmarks view transformer."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.views.analytics_league_benchmarks import (
    AnalyticsLeagueBenchmarksTransformer,
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


class TestAnalyticsLeagueBenchmarks:
    def test_output_table(self) -> None:
        t = AnalyticsLeagueBenchmarksTransformer()
        assert t.output_table == "analytics_league_benchmarks"

    def test_depends_on_count(self) -> None:
        t = AnalyticsLeagueBenchmarksTransformer()
        assert len(t.depends_on) == 2

    def test_depends_on_contents(self) -> None:
        t = AnalyticsLeagueBenchmarksTransformer()
        assert set(t.depends_on) == {
            "agg_player_season",
            "agg_team_season",
        }

    def test_sql_is_non_empty(self) -> None:
        assert AnalyticsLeagueBenchmarksTransformer._SQL.strip()

    def test_averages_computed_correctly(self) -> None:
        """Multiple players and teams produce correct league averages."""
        agg_player_season = pl.DataFrame(
            {
                "player_id": [101, 102, 103],
                "team_id": [1, 1, 2],
                "season_year": [2024, 2024, 2024],
                "season_type": [
                    "Regular Season",
                    "Regular Season",
                    "Regular Season",
                ],
                "gp": [82, 70, 60],
                "total_min": [2800.0, 2400.0, 2000.0],
                "avg_min": [34.1, 34.3, 33.3],
                "total_pts": [2050, 1400, 1200],
                "avg_pts": [25.0, 20.0, 20.0],
                "total_reb": [410, 700, 300],
                "avg_reb": [5.0, 10.0, 5.0],
                "total_ast": [574, 280, 360],
                "avg_ast": [7.0, 4.0, 6.0],
                "total_stl": [164, 70, 90],
                "avg_stl": [2.0, 1.0, 1.5],
                "total_blk": [82, 140, 60],
                "avg_blk": [1.0, 2.0, 1.0],
                "total_tov": [246, 210, 180],
                "avg_tov": [3.0, 3.0, 3.0],
                "total_fgm": [738, 500, 450],
                "total_fga": [1476, 1100, 1000],
                "fg_pct": [0.500, 0.455, 0.450],
                "total_fg3m": [246, 100, 150],
                "total_fg3a": [574, 300, 400],
                "fg3_pct": [0.429, 0.333, 0.375],
                "total_ftm": [328, 300, 150],
                "total_fta": [410, 380, 200],
                "ft_pct": [0.800, 0.789, 0.750],
                "avg_off_rating": [115.0, 112.0, 110.0],
                "avg_def_rating": [105.0, 108.0, 107.0],
                "avg_net_rating": [10.0, 4.0, 3.0],
                "avg_ts_pct": [0.600, 0.560, 0.550],
                "avg_usg_pct": [0.280, 0.220, 0.240],
                "avg_pie": [0.150, 0.120, 0.110],
            }
        ).lazy()

        agg_team_season = pl.DataFrame(
            {
                "team_id": [1, 2],
                "season_year": [2024, 2024],
                "season_type": ["Regular Season", "Regular Season"],
                "gp": [82, 82],
                "avg_pts": [112.0, 108.0],
                "avg_reb": [44.0, 42.0],
                "avg_ast": [25.0, 23.0],
                "avg_stl": [8.0, 7.0],
                "avg_blk": [5.0, 4.5],
                "avg_tov": [13.5, 14.0],
                "fg_pct": [0.480, 0.460],
                "fg3_pct": [0.370, 0.350],
                "ft_pct": [0.790, 0.770],
            }
        ).lazy()

        staging = {
            "agg_player_season": agg_player_season,
            "agg_team_season": agg_team_season,
        }
        result = _run(AnalyticsLeagueBenchmarksTransformer(), staging)

        assert result.shape[0] == 1  # one season_year + season_type combo
        row = result.row(0, named=True)

        # Player benchmarks: average of 3 players (all gp >= 10)
        assert row["total_players"] == 3
        assert row["league_avg_ppg"] == pytest.approx((25.0 + 20.0 + 20.0) / 3)
        assert row["league_avg_rpg"] == pytest.approx((5.0 + 10.0 + 5.0) / 3)
        assert row["league_avg_apg"] == pytest.approx((7.0 + 4.0 + 6.0) / 3)
        assert row["league_avg_spg"] == pytest.approx((2.0 + 1.0 + 1.5) / 3)
        assert row["league_avg_bpg"] == pytest.approx((1.0 + 2.0 + 1.0) / 3)
        assert row["league_avg_fg_pct"] == pytest.approx((0.500 + 0.455 + 0.450) / 3)
        assert row["league_avg_ts_pct"] == pytest.approx((0.600 + 0.560 + 0.550) / 3)
        assert row["league_avg_usg_pct"] == pytest.approx((0.280 + 0.220 + 0.240) / 3)

        # Team benchmarks: average of 2 teams
        assert row["total_teams"] == 2
        assert row["league_avg_team_ppg"] == pytest.approx((112.0 + 108.0) / 2)
        assert row["league_avg_team_rpg"] == pytest.approx((44.0 + 42.0) / 2)
        assert row["league_avg_team_apg"] == pytest.approx((25.0 + 23.0) / 2)
        assert row["league_avg_team_fg_pct"] == pytest.approx((0.480 + 0.460) / 2)

    def test_gp_filter_excludes_low_game_players(self) -> None:
        """Players with fewer than 10 games are excluded from benchmarks."""
        agg_player_season = pl.DataFrame(
            {
                "player_id": [101, 102],
                "team_id": [1, 1],
                "season_year": [2024, 2024],
                "season_type": ["Regular Season", "Regular Season"],
                "gp": [82, 5],  # player 102 below threshold
                "total_min": [2800.0, 100.0],
                "avg_min": [34.1, 20.0],
                "total_pts": [2050, 100],
                "avg_pts": [25.0, 20.0],
                "total_reb": [410, 30],
                "avg_reb": [5.0, 6.0],
                "total_ast": [574, 20],
                "avg_ast": [7.0, 4.0],
                "total_stl": [164, 5],
                "avg_stl": [2.0, 1.0],
                "total_blk": [82, 5],
                "avg_blk": [1.0, 1.0],
                "total_tov": [246, 15],
                "avg_tov": [3.0, 3.0],
                "total_fgm": [738, 40],
                "total_fga": [1476, 100],
                "fg_pct": [0.500, 0.400],
                "total_fg3m": [246, 10],
                "total_fg3a": [574, 30],
                "fg3_pct": [0.429, 0.333],
                "total_ftm": [328, 10],
                "total_fta": [410, 15],
                "ft_pct": [0.800, 0.667],
                "avg_off_rating": [115.0, 100.0],
                "avg_def_rating": [105.0, 115.0],
                "avg_net_rating": [10.0, -15.0],
                "avg_ts_pct": [0.600, 0.450],
                "avg_usg_pct": [0.280, 0.300],
                "avg_pie": [0.150, 0.050],
            }
        ).lazy()

        agg_team_season = pl.DataFrame(
            {
                "team_id": [1],
                "season_year": [2024],
                "season_type": ["Regular Season"],
                "gp": [82],
                "avg_pts": [110.0],
                "avg_reb": [44.0],
                "avg_ast": [25.0],
                "avg_stl": [8.0],
                "avg_blk": [5.0],
                "avg_tov": [13.5],
                "fg_pct": [0.480],
                "fg3_pct": [0.370],
                "ft_pct": [0.790],
            }
        ).lazy()

        staging = {
            "agg_player_season": agg_player_season,
            "agg_team_season": agg_team_season,
        }
        result = _run(AnalyticsLeagueBenchmarksTransformer(), staging)

        assert result.shape[0] == 1
        row = result.row(0, named=True)
        # Only player 101 counted (gp >= 10)
        assert row["total_players"] == 1
        assert row["league_avg_ppg"] == pytest.approx(25.0)

    def test_multiple_season_types(self) -> None:
        """Regular Season and Playoffs produce separate rows."""
        agg_player_season = pl.DataFrame(
            {
                "player_id": [101, 101],
                "team_id": [1, 1],
                "season_year": [2024, 2024],
                "season_type": ["Regular Season", "Playoffs"],
                "gp": [82, 20],
                "total_min": [2800.0, 700.0],
                "avg_min": [34.1, 35.0],
                "total_pts": [2050, 600],
                "avg_pts": [25.0, 30.0],
                "total_reb": [410, 120],
                "avg_reb": [5.0, 6.0],
                "total_ast": [574, 160],
                "avg_ast": [7.0, 8.0],
                "total_stl": [164, 40],
                "avg_stl": [2.0, 2.0],
                "total_blk": [82, 20],
                "avg_blk": [1.0, 1.0],
                "total_tov": [246, 60],
                "avg_tov": [3.0, 3.0],
                "total_fgm": [738, 220],
                "total_fga": [1476, 450],
                "fg_pct": [0.500, 0.489],
                "total_fg3m": [246, 60],
                "total_fg3a": [574, 140],
                "fg3_pct": [0.429, 0.429],
                "total_ftm": [328, 100],
                "total_fta": [410, 120],
                "ft_pct": [0.800, 0.833],
                "avg_off_rating": [115.0, 118.0],
                "avg_def_rating": [105.0, 103.0],
                "avg_net_rating": [10.0, 15.0],
                "avg_ts_pct": [0.600, 0.620],
                "avg_usg_pct": [0.280, 0.290],
                "avg_pie": [0.150, 0.170],
            }
        ).lazy()

        agg_team_season = pl.DataFrame(
            {
                "team_id": [1, 1],
                "season_year": [2024, 2024],
                "season_type": ["Regular Season", "Playoffs"],
                "gp": [82, 20],
                "avg_pts": [110.0, 105.0],
                "avg_reb": [44.0, 43.0],
                "avg_ast": [25.0, 24.0],
                "avg_stl": [8.0, 7.5],
                "avg_blk": [5.0, 5.5],
                "avg_tov": [13.5, 12.0],
                "fg_pct": [0.480, 0.470],
                "fg3_pct": [0.370, 0.360],
                "ft_pct": [0.790, 0.800],
            }
        ).lazy()

        staging = {
            "agg_player_season": agg_player_season,
            "agg_team_season": agg_team_season,
        }
        result = _run(AnalyticsLeagueBenchmarksTransformer(), staging)

        assert result.shape[0] == 2
        reg = result.filter(pl.col("season_type") == "Regular Season")
        playoffs = result.filter(pl.col("season_type") == "Playoffs")
        assert reg.shape[0] == 1
        assert playoffs.shape[0] == 1
        assert reg["league_avg_ppg"][0] == pytest.approx(25.0)
        assert playoffs["league_avg_ppg"][0] == pytest.approx(30.0)

    def test_no_connection_before_injection(self) -> None:
        t = AnalyticsLeagueBenchmarksTransformer()
        with pytest.raises(RuntimeError, match="No DuckDB connection"):
            t.conn  # noqa: B018
