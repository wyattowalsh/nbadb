"""Tests for analytics_draft_value view transformer."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.views.analytics_draft_value import (
    AnalyticsDraftValueTransformer,
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


class TestAnalyticsDraftValue:
    def test_output_table(self) -> None:
        t = AnalyticsDraftValueTransformer()
        assert t.output_table == "analytics_draft_value"

    def test_depends_on_count(self) -> None:
        t = AnalyticsDraftValueTransformer()
        assert len(t.depends_on) == 3

    def test_depends_on_contents(self) -> None:
        t = AnalyticsDraftValueTransformer()
        assert set(t.depends_on) == {
            "fact_draft",
            "agg_player_career",
            "dim_player",
        }

    def test_sql_is_non_empty(self) -> None:
        assert AnalyticsDraftValueTransformer._SQL.strip()

    def test_join_enriches_draft_with_career_stats(self) -> None:
        """Two draft picks joined to career stats and dim_player."""
        fact_draft = pl.DataFrame(
            {
                "person_id": [201566, 203507],
                "player_name": ["Russell Westbrook", "Giannis Antetokounmpo"],
                "season": [2008, 2013],
                "round_number": [1, 1],
                "round_pick": [4, 15],
                "overall_pick": [4, 15],
                "draft_type": ["Draft", "Draft"],
                "team_id": [1610612760, 1610612749],
                "organization": ["UCLA", "Filathlitikos"],
                "organization_type": ["College/University", "International"],
                "height_wo_shoes": [None, None],
                "height_w_shoes": [None, None],
                "weight": [None, None],
                "wingspan": [None, None],
                "standing_reach": [None, None],
                "body_fat_pct": [None, None],
                "hand_length": [None, None],
                "hand_width": [None, None],
                "standing_vertical_leap": [None, None],
                "max_vertical_leap": [None, None],
                "lane_agility_time": [None, None],
                "three_quarter_sprint": [None, None],
                "bench_press": [None, None],
            }
        ).lazy()

        agg_player_career = pl.DataFrame(
            {
                "player_id": [201566, 203507],
                "career_gp": [1000, 750],
                "career_min": [34000.0, 27000.0],
                "career_pts": [24000, 20000],
                "career_ppg": [24.0, 26.7],
                "career_rpg": [7.2, 11.0],
                "career_apg": [8.4, 5.8],
                "career_spg": [1.7, 1.2],
                "career_bpg": [0.3, 1.4],
                "career_fg_pct": [0.438, 0.553],
                "career_fg3_pct": [0.305, 0.289],
                "career_ft_pct": [0.800, 0.710],
                "first_season": [2008, 2013],
                "last_season": [2024, 2024],
                "seasons_played": [16, 11],
            }
        ).lazy()

        dim_player = pl.DataFrame(
            {
                "player_sk": [1, 2],
                "player_id": [201566, 203507],
                "full_name": ["Russell Westbrook", "Giannis Antetokounmpo"],
                "position": ["PG", "PF"],
                "team_id": [1610612746, 1610612749],
                "jersey_number": ["0", "34"],
                "height": ["6-3", "6-11"],
                "weight": [200, 243],
                "birth_date": ["1988-11-12", "1994-12-06"],
                "country": ["USA", "Greece"],
                "draft_year": [2008, 2013],
                "draft_round": [1, 1],
                "draft_number": [4, 15],
                "college_id": [1, None],
                "valid_from": [2020, 2020],
                "valid_to": [None, None],
                "is_current": [True, True],
            }
        ).lazy()

        staging = {
            "fact_draft": fact_draft,
            "agg_player_career": agg_player_career,
            "dim_player": dim_player,
        }
        result = _run(AnalyticsDraftValueTransformer(), staging)

        assert result.shape[0] == 2
        # Verify career stats are joined
        russ = result.filter(pl.col("person_id") == 201566)
        assert russ.shape[0] == 1
        assert russ["player_name"][0] == "Russell Westbrook"
        assert russ["career_gp"][0] == 1000
        assert russ["career_ppg"][0] == pytest.approx(24.0)
        assert russ["position"][0] == "PG"
        assert russ["country"][0] == "USA"
        assert russ["overall_pick"][0] == 4
        assert russ["seasons_played"][0] == 16

        giannis = result.filter(pl.col("person_id") == 203507)
        assert giannis.shape[0] == 1
        assert giannis["player_name"][0] == "Giannis Antetokounmpo"
        assert giannis["career_ppg"][0] == pytest.approx(26.7)
        assert giannis["country"][0] == "Greece"

    def test_no_dim_player_row_falls_back_to_fact_draft_name(self) -> None:
        """When dim_player has no match, COALESCE uses fact_draft.player_name."""
        fact_draft = pl.DataFrame(
            {
                "person_id": [888888],
                "player_name": ["Retired Legend"],
                "season": [1995],
                "round_number": [1],
                "round_pick": [1],
                "overall_pick": [1],
                "draft_type": ["Draft"],
                "team_id": [1610612738],
                "organization": ["Duke"],
                "organization_type": ["College/University"],
                "height_wo_shoes": [None],
                "height_w_shoes": [None],
                "weight": [None],
                "wingspan": [None],
                "standing_reach": [None],
                "body_fat_pct": [None],
                "hand_length": [None],
                "hand_width": [None],
                "standing_vertical_leap": [None],
                "max_vertical_leap": [None],
                "lane_agility_time": [None],
                "three_quarter_sprint": [None],
                "bench_press": [None],
            }
        ).lazy()

        agg_player_career = pl.DataFrame(
            {
                "player_id": pl.Series([], dtype=pl.Int64),
                "career_gp": pl.Series([], dtype=pl.Int64),
                "career_min": pl.Series([], dtype=pl.Float64),
                "career_pts": pl.Series([], dtype=pl.Int64),
                "career_ppg": pl.Series([], dtype=pl.Float64),
                "career_rpg": pl.Series([], dtype=pl.Float64),
                "career_apg": pl.Series([], dtype=pl.Float64),
                "career_spg": pl.Series([], dtype=pl.Float64),
                "career_bpg": pl.Series([], dtype=pl.Float64),
                "career_fg_pct": pl.Series([], dtype=pl.Float64),
                "career_fg3_pct": pl.Series([], dtype=pl.Float64),
                "career_ft_pct": pl.Series([], dtype=pl.Float64),
                "first_season": pl.Series([], dtype=pl.Int64),
                "last_season": pl.Series([], dtype=pl.Int64),
                "seasons_played": pl.Series([], dtype=pl.Int64),
            }
        ).lazy()

        # Empty dim_player — no matching row for person_id=888888
        dim_player = pl.DataFrame(
            {
                "player_id": pl.Series([], dtype=pl.Int64),
                "full_name": pl.Series([], dtype=pl.Utf8),
                "position": pl.Series([], dtype=pl.Utf8),
                "country": pl.Series([], dtype=pl.Utf8),
                "is_current": pl.Series([], dtype=pl.Boolean),
            }
        ).lazy()

        staging = {
            "fact_draft": fact_draft,
            "agg_player_career": agg_player_career,
            "dim_player": dim_player,
        }
        result = _run(AnalyticsDraftValueTransformer(), staging)

        assert result.shape[0] == 1
        # COALESCE falls back to fact_draft.player_name
        assert result["player_name"][0] == "Retired Legend"
        # Career stats are still NULL (no agg_player_career row)
        assert result["career_gp"][0] is None

    def test_undrafted_player_null_career(self) -> None:
        """Draft pick with no career stats yields NULLs for career columns."""
        fact_draft = pl.DataFrame(
            {
                "person_id": [999999],
                "player_name": ["Never Played"],
                "season": [2020],
                "round_number": [2],
                "round_pick": [30],
                "overall_pick": [60],
                "draft_type": ["Draft"],
                "team_id": [1610612738],
                "organization": ["Unknown U"],
                "organization_type": ["College/University"],
                "height_wo_shoes": [None],
                "height_w_shoes": [None],
                "weight": [None],
                "wingspan": [None],
                "standing_reach": [None],
                "body_fat_pct": [None],
                "hand_length": [None],
                "hand_width": [None],
                "standing_vertical_leap": [None],
                "max_vertical_leap": [None],
                "lane_agility_time": [None],
                "three_quarter_sprint": [None],
                "bench_press": [None],
            }
        ).lazy()

        agg_player_career = pl.DataFrame(
            {
                "player_id": pl.Series([], dtype=pl.Int64),
                "career_gp": pl.Series([], dtype=pl.Int64),
                "career_min": pl.Series([], dtype=pl.Float64),
                "career_pts": pl.Series([], dtype=pl.Int64),
                "career_ppg": pl.Series([], dtype=pl.Float64),
                "career_rpg": pl.Series([], dtype=pl.Float64),
                "career_apg": pl.Series([], dtype=pl.Float64),
                "career_spg": pl.Series([], dtype=pl.Float64),
                "career_bpg": pl.Series([], dtype=pl.Float64),
                "career_fg_pct": pl.Series([], dtype=pl.Float64),
                "career_fg3_pct": pl.Series([], dtype=pl.Float64),
                "career_ft_pct": pl.Series([], dtype=pl.Float64),
                "first_season": pl.Series([], dtype=pl.Int64),
                "last_season": pl.Series([], dtype=pl.Int64),
                "seasons_played": pl.Series([], dtype=pl.Int64),
            }
        ).lazy()

        dim_player = pl.DataFrame(
            {
                "player_id": pl.Series([], dtype=pl.Int64),
                "full_name": pl.Series([], dtype=pl.Utf8),
                "position": pl.Series([], dtype=pl.Utf8),
                "country": pl.Series([], dtype=pl.Utf8),
                "is_current": pl.Series([], dtype=pl.Boolean),
            }
        ).lazy()

        staging = {
            "fact_draft": fact_draft,
            "agg_player_career": agg_player_career,
            "dim_player": dim_player,
        }
        result = _run(AnalyticsDraftValueTransformer(), staging)

        assert result.shape[0] == 1
        assert result["career_gp"][0] is None
        assert result["career_ppg"][0] is None
        # With COALESCE, falls back to fact_draft.player_name
        assert result["player_name"][0] == "Never Played"

    def test_scd2_deduplication(self) -> None:
        """is_current=TRUE filter prevents SCD2 fan-out from dim_player."""
        fact_draft = pl.DataFrame(
            {
                "person_id": [201566],
                "player_name": ["Russell Westbrook"],
                "season": [2008],
                "round_number": [1],
                "round_pick": [4],
                "overall_pick": [4],
                "draft_type": ["Draft"],
                "team_id": [1610612760],
                "organization": ["UCLA"],
                "organization_type": ["College/University"],
                "height_wo_shoes": [None],
                "height_w_shoes": [None],
                "weight": [None],
                "wingspan": [None],
                "standing_reach": [None],
                "body_fat_pct": [None],
                "hand_length": [None],
                "hand_width": [None],
                "standing_vertical_leap": [None],
                "max_vertical_leap": [None],
                "lane_agility_time": [None],
                "three_quarter_sprint": [None],
                "bench_press": [None],
            }
        ).lazy()

        agg_player_career = pl.DataFrame(
            {
                "player_id": [201566],
                "career_gp": [1000],
                "career_min": [34000.0],
                "career_pts": [24000],
                "career_ppg": [24.0],
                "career_rpg": [7.2],
                "career_apg": [8.4],
                "career_spg": [1.7],
                "career_bpg": [0.3],
                "career_fg_pct": [0.438],
                "career_fg3_pct": [0.305],
                "career_ft_pct": [0.800],
                "first_season": [2008],
                "last_season": [2024],
                "seasons_played": [16],
            }
        ).lazy()

        # Two SCD2 rows for the same player
        dim_player = pl.DataFrame(
            {
                "player_sk": [1, 2],
                "player_id": [201566, 201566],
                "full_name": ["Russell Westbrook", "Russell Westbrook"],
                "position": ["PG", "PG"],
                "team_id": [1610612760, 1610612746],
                "jersey_number": ["0", "0"],
                "height": ["6-3", "6-3"],
                "weight": [200, 200],
                "birth_date": ["1988-11-12", "1988-11-12"],
                "country": ["USA", "USA"],
                "draft_year": [2008, 2008],
                "draft_round": [1, 1],
                "draft_number": [4, 4],
                "college_id": [1, 1],
                "valid_from": [2018, 2022],
                "valid_to": [2022, None],
                "is_current": [False, True],
            }
        ).lazy()

        staging = {
            "fact_draft": fact_draft,
            "agg_player_career": agg_player_career,
            "dim_player": dim_player,
        }
        result = _run(AnalyticsDraftValueTransformer(), staging)

        # is_current filter prevents fan-out: only 1 row
        assert result.shape[0] == 1
        assert result["player_name"][0] == "Russell Westbrook"

    def test_no_connection_before_injection(self) -> None:
        t = AnalyticsDraftValueTransformer()
        with pytest.raises(RuntimeError, match="No DuckDB connection"):
            t.conn  # noqa: B018
