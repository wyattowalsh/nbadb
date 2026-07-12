from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.facts.fact_video_support import (
    FactVideoDetailsAssetTransformer,
    FactVideoDetailsTransformer,
)


@pytest.mark.parametrize(
    ("transformer_cls", "source_table", "output_table"),
    [
        (FactVideoDetailsTransformer, "stg_video_details", "fact_video_details"),
        (
            FactVideoDetailsAssetTransformer,
            "stg_video_details_asset",
            "fact_video_details_asset",
        ),
    ],
)
def test_video_passthrough_preserves_context_and_result_set_discriminators(
    transformer_cls: type,
    source_table: str,
    output_table: str,
) -> None:
    frame = pl.DataFrame(
        {
            "result_set_name": ["Playlist", "VideoUrls"],
            "result_set_index": [0, 1],
            "context_measure": ["PTS", "PTS"],
            "context_measure_provenance": ["docs,runtime", "docs,runtime"],
            "request_player_id": [2544, 2544],
            "dynamic_payload": ["event", "url"],
        }
    )
    conn = duckdb.connect()
    try:
        conn.register(source_table, frame)
        transformer = transformer_cls()
        transformer._conn = conn
        result = transformer.transform({source_table: frame.lazy()})
    finally:
        conn.close()

    assert transformer_cls.output_table == output_table
    assert transformer_cls.depends_on == [source_table]
    assert result.columns == frame.columns
    assert result.to_dicts() == frame.to_dicts()
