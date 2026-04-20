from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_shot_chart_league_averages import (
    FactShotChartLeagueAveragesTransformer,
)
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


class TestFactShotChartLeagueAverages:
    def test_class_attrs(self) -> None:
        assert (
            FactShotChartLeagueAveragesTransformer.output_table == "fact_shot_chart_league_averages"
        )
        assert len(FactShotChartLeagueAveragesTransformer.depends_on) == 2

    def test_unions_shot_chart_league_average_packets(self) -> None:
        staging = {
            "stg_shot_chart_league_averages": pl.DataFrame(
                {
                    "grid_type": ["Shot Chart Detail"],
                    "shot_zone_basic": ["Restricted Area"],
                    "shot_zone_area": ["Center(C)"],
                    "shot_zone_range": ["Less Than 8 ft."],
                    "fga": [120.0],
                    "fgm": [78.0],
                    "fg_pct": [0.65],
                }
            ).lazy(),
            "stg_shot_chart_lineup_league_avg": pl.DataFrame(
                {
                    "grid_type": ["Shot Chart Lineup Detail"],
                    "shot_zone_basic": ["Above the Break 3"],
                    "shot_zone_area": ["Center(C)"],
                    "shot_zone_range": ["24+ ft."],
                    "fga": [210.0],
                    "fgm": [76.0],
                    "fg_pct": [0.362],
                }
            ).lazy(),
        }

        result = _run(FactShotChartLeagueAveragesTransformer(), staging)

        assert result.shape[0] == 2
        assert set(result["average_source"].to_list()) == {
            "shot_chart_detail",
            "shot_chart_lineup_detail",
        }
        _assert_schema_valid("fact_shot_chart_league_averages", result)


def test_auxiliary_schema_is_discovered_without_init_exports() -> None:
    assert "fact_shot_chart_league_averages" in _star_schema_map()
