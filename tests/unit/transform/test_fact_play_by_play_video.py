from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_play_by_play_video import (
    FactPlayByPlayVideoTransformer,
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


class TestFactPlayByPlayVideo:
    def test_output_table(self) -> None:
        assert FactPlayByPlayVideoTransformer.output_table == "fact_play_by_play_video"

    def test_depends_on(self) -> None:
        assert FactPlayByPlayVideoTransformer.depends_on == ["stg_play_by_play_video_available"]

    def test_pass_through(self) -> None:
        staging = {
            "stg_play_by_play_video_available": pl.DataFrame({"video_available": [1, 0, 1]}).lazy(),
        }
        result = _run(FactPlayByPlayVideoTransformer(), staging)

        assert result.shape == (3, 1)
        assert result.columns == ["video_available"]
        assert result["video_available"].to_list() == [1, 0, 1]

    def test_empty_staging(self) -> None:
        staging = {
            "stg_play_by_play_video_available": pl.DataFrame(
                {"video_available": pl.Series([], dtype=pl.Int64)}
            ).lazy(),
        }
        result = _run(FactPlayByPlayVideoTransformer(), staging)

        assert result.shape[0] == 0
        assert "video_available" in result.columns
