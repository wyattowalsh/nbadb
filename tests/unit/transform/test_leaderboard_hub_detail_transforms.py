from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_defense_hub_detail import FactDefenseHubDetailTransformer
from nbadb.transform.facts.fact_homepage_detail import FactHomepageDetailTransformer
from nbadb.transform.facts.fact_homepage_leaders_detail import (
    FactHomepageLeadersDetailTransformer,
)
from nbadb.transform.facts.fact_leaders_tiles_detail import FactLeadersTilesDetailTransformer
from nbadb.transform.pipeline import _star_schema_map


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _assert_schema_valid(table: str, df: pl.DataFrame) -> None:
    schema_cls = _star_schema_map()[table]
    validated = schema_cls.validate(df)
    assert isinstance(validated, pl.DataFrame)


class TestFactHomepageDetail:
    def test_class_attrs(self) -> None:
        assert FactHomepageDetailTransformer.output_table == "fact_homepage_detail"
        assert len(FactHomepageDetailTransformer.depends_on) == 8

    def test_union_with_homepage_metric(self) -> None:
        staging = {
            "stg_homepage_v2_stat1": pl.DataFrame(
                {
                    "rank": [1],
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "pts": [119.5],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
            "stg_homepage_v2_stat5": pl.DataFrame(
                {
                    "rank": [2],
                    "team_id": [1610612739],
                    "team_abbreviation": ["CLE"],
                    "team_name": ["Cavaliers"],
                    "fg_pct": [0.512],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
        }

        result = _run(FactHomepageDetailTransformer(), staging)

        assert result.shape == (2, 7)
        assert set(result.columns) == {
            "homepage_metric",
            "rank",
            "team_id",
            "team_abbreviation",
            "team_name",
            "season_type",
            "stat_value",
        }
        assert set(result["homepage_metric"].to_list()) == {"pts", "fg_pct"}
        assert result["stat_value"].to_list() == [0.512, 119.5]
        _assert_schema_valid("fact_homepage_detail", result)


class TestFactHomepageLeadersDetail:
    def test_class_attrs(self) -> None:
        assert FactHomepageLeadersDetailTransformer.output_table == "fact_homepage_leaders_detail"
        assert len(FactHomepageLeadersDetailTransformer.depends_on) == 3

    def test_union_with_leader_variant(self) -> None:
        staging = {
            "stg_homepage_leaders_main": pl.DataFrame(
                {
                    "rank": [1],
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "pts": [119.5],
                    "fg_pct": [0.512],
                    "fg3_pct": [0.389],
                    "ft_pct": [0.811],
                    "efg_pct": [0.578],
                    "ts_pct": [0.607],
                    "pts_per48": [118.9],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
            "stg_homepage_leaders_league_avg": pl.DataFrame(
                {
                    "pts": [112.4],
                    "fg_pct": [0.477],
                    "fg3_pct": [0.364],
                    "ft_pct": [0.782],
                    "efg_pct": [0.541],
                    "ts_pct": [0.577],
                    "pts_per48": [112.4],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
            "stg_homepage_leaders_league_max": pl.DataFrame(
                {
                    "pts": [121.0],
                    "fg_pct": [0.512],
                    "fg3_pct": [0.389],
                    "ft_pct": [0.811],
                    "efg_pct": [0.578],
                    "ts_pct": [0.607],
                    "pts_per48": [118.9],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
        }

        result = _run(FactHomepageLeadersDetailTransformer(), staging)

        assert result.shape == (3, 13)
        assert set(result["leader_variant"].to_list()) == {"main", "league_avg", "league_max"}
        assert result.filter(pl.col("leader_variant") != "main")["team_id"].to_list() == [
            None,
            None,
        ]
        _assert_schema_valid("fact_homepage_leaders_detail", result)


class TestFactLeadersTilesDetail:
    def test_class_attrs(self) -> None:
        assert FactLeadersTilesDetailTransformer.output_table == "fact_leaders_tiles_detail"
        assert len(FactLeadersTilesDetailTransformer.depends_on) == 4

    def test_union_with_tile_variant(self) -> None:
        staging = {
            "stg_leaders_tiles_alltime_high": pl.DataFrame(
                {
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "season_year": ["1985-86"],
                    "pts": [122.7],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
            "stg_leaders_tiles_main": pl.DataFrame(
                {
                    "rank": [1],
                    "team_id": [1610612741],
                    "team_abbreviation": ["CHI"],
                    "team_name": ["Bulls"],
                    "pts": [118.2],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
            "stg_leaders_tiles_low_season": pl.DataFrame(
                {
                    "team_id": [1610612745],
                    "team_abbreviation": ["HOU"],
                    "team_name": ["Rockets"],
                    "season_year": ["1978-79"],
                    "pts": [95.1],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
        }

        result = _run(FactLeadersTilesDetailTransformer(), staging)

        assert result.shape == (3, 8)
        assert set(result["tile_variant"].to_list()) == {
            "all_time_high",
            "main",
            "low_season_high",
        }
        assert result.filter(pl.col("tile_variant") == "main")["season_year"].to_list() == [None]
        _assert_schema_valid("fact_leaders_tiles_detail", result)


class TestFactDefenseHubDetail:
    def test_class_attrs(self) -> None:
        assert FactDefenseHubDetailTransformer.output_table == "fact_defense_hub_detail"
        assert len(FactDefenseHubDetailTransformer.depends_on) == 10

    def test_union_with_metric_fallback_and_missing_packets(self) -> None:
        staging = {
            "stg_defense_hub_stat1": pl.DataFrame(
                {
                    "rank": [1],
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "dreb": [35.4],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
            "stg_defense_hub_stat4": pl.DataFrame(
                {
                    "rank": [2],
                    "team_id": [1610612740],
                    "team_abbreviation": ["NOP"],
                    "team_name": ["Pelicans"],
                    "tm_def_rating": [109.7],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
            "stg_defense_hub_stat10": pl.DataFrame(
                {
                    "rank": [3],
                    "team_id": [1610612752],
                    "team_abbreviation": ["NYK"],
                    "team_name": ["Knicks"],
                    "contested_shots": [15.0],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
        }

        result = _run(FactDefenseHubDetailTransformer(), staging)

        assert result.shape == (3, 7)
        assert set(result["defense_metric"].to_list()) == {
            "dreb",
            "tm_def_rating",
            "contested_shots",
        }
        _assert_schema_valid("fact_defense_hub_detail", result)

    def test_ambiguous_metric_packet_raises(self) -> None:
        staging = {
            "stg_defense_hub_stat10": pl.DataFrame(
                {
                    "rank": [3],
                    "team_id": [1610612752],
                    "team_abbreviation": ["NYK"],
                    "team_name": ["Knicks"],
                    "contested_shots": [15.0],
                    "closeouts": [22.0],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
        }

        try:
            _run(FactDefenseHubDetailTransformer(), staging)
        except ValueError as exc:
            assert "stg_defense_hub_stat10" in str(exc)
            assert "metric column" in str(exc)
        else:
            raise AssertionError("Expected ambiguous stat10 packet to raise ValueError")


def test_new_detail_schemas_are_discovered_without_init_exports() -> None:
    schema_map = _star_schema_map()

    assert {
        "fact_homepage_detail",
        "fact_homepage_leaders_detail",
        "fact_leaders_tiles_detail",
        "fact_defense_hub_detail",
    }.issubset(schema_map)
