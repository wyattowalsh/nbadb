from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_defense_hub import FactDefenseHubTransformer
from nbadb.transform.facts.fact_homepage import FactHomepageTransformer
from nbadb.transform.facts.fact_homepage_leaders import FactHomepageLeadersTransformer
from nbadb.transform.facts.fact_leaders_tiles import FactLeadersTilesTransformer
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


class TestFactHomepage:
    def test_union_with_homepage_source(self) -> None:
        staging = {
            "stg_home_page_v2": pl.DataFrame(
                {
                    "rank": [1],
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "pts": [119.5],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
            "stg_homepage_v2": pl.DataFrame(
                {
                    "rank": [2],
                    "team_id": [1610612739],
                    "team_abbreviation": ["CLE"],
                    "team_name": ["Cavaliers"],
                    "pts": [118.2],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
        }

        result = _run(FactHomepageTransformer(), staging)

        assert result.shape == (2, 7)
        assert set(result["homepage_source"].to_list()) == {"home_page", "homepage"}
        _assert_schema_valid("fact_homepage", result)


class TestFactHomepageLeaders:
    def test_union_with_leader_source(self) -> None:
        staging = {
            "stg_home_page_leaders": pl.DataFrame(
                {
                    "rank": [1],
                    "team_id": [1610612738],
                    "team_name": ["Celtics"],
                    "team_abbreviation": ["BOS"],
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
            "stg_homepage_leaders": pl.DataFrame(
                {
                    "rank": [2],
                    "team_id": [1610612739],
                    "team_name": ["Cavaliers"],
                    "team_abbreviation": ["CLE"],
                    "pts": [118.2],
                    "fg_pct": [0.507],
                    "fg3_pct": [0.381],
                    "ft_pct": [0.792],
                    "efg_pct": [0.571],
                    "ts_pct": [0.601],
                    "pts_per48": [117.4],
                    "season_type": ["Regular Season"],
                }
            ).lazy(),
        }

        result = _run(FactHomepageLeadersTransformer(), staging)

        assert result.shape == (2, 13)
        assert set(result["leader_source"].to_list()) == {"home_page", "homepage"}
        _assert_schema_valid("fact_homepage_leaders", result)


class TestFactLeadersTiles:
    def test_validates_base_leaders_tiles_packet(self) -> None:
        staging = {
            "stg_leaders_tiles": pl.DataFrame(
                {
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "season_year": ["1985-86"],
                    "pts": [122.7],
                    "season_type": ["Regular Season"],
                }
            ).lazy()
        }

        result = _run(FactLeadersTilesTransformer(), staging)

        assert result.shape == (1, 6)
        _assert_schema_valid("fact_leaders_tiles", result)


class TestFactDefenseHub:
    def test_validates_base_defense_hub_packet(self) -> None:
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
            ).lazy()
        }

        result = _run(FactDefenseHubTransformer(), staging)

        assert result.shape == (1, 6)
        _assert_schema_valid("fact_defense_hub", result)


def test_new_base_hub_schemas_are_discovered_without_init_exports() -> None:
    assert {
        "fact_defense_hub",
        "fact_homepage",
        "fact_homepage_leaders",
        "fact_leaders_tiles",
    }.issubset(_star_schema_map())
