from __future__ import annotations

import pandera.errors as pa_errors
import polars as pl
import pytest

from nbadb.schemas.staging.misc import (
    StagingVideoDetailsAssetSchema,
    StagingVideoDetailsSchema,
)
from nbadb.schemas.star.fact_video_support import (
    FactVideoDetailsAssetSchema,
    FactVideoDetailsSchema,
)


def _video_frame(**overrides: object) -> pl.DataFrame:
    row = {
        "result_set_name": "Playlist",
        "result_set_index": 0,
        "context_measure": "PTS",
        "context_measure_provenance": "docs,runtime",
        "season_type_provenance": "docs,runtime",
        "nba_api_contract_version": "1.11.4",
        "request_player_id": 2544,
        "request_team_id": 1610612739,
        "request_season": "2019-20",
        "request_season_type": "Regular Season",
        "game_id": "0021900001",
    }
    row.update(overrides)
    return pl.DataFrame([row])


@pytest.mark.parametrize(
    "schema_cls",
    [
        StagingVideoDetailsSchema,
        StagingVideoDetailsAssetSchema,
        FactVideoDetailsSchema,
        FactVideoDetailsAssetSchema,
    ],
)
def test_video_schema_requires_provenance_and_preserves_dynamic_columns(schema_cls: type) -> None:
    result = schema_cls.validate(_video_frame())

    assert result.get_column("result_set_name").to_list() == ["Playlist"]
    assert result.get_column("game_id").to_list() == ["0021900001"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"context_measure": "UNKNOWN"},
        {"context_measure_provenance": "runtime-only-unknown"},
        {"request_season_type": "Play-In"},
        {"result_set_index": -1},
        {"nba_api_contract_version": "1.11.3"},
    ],
)
def test_video_schema_rejects_values_outside_pinned_contract(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(pa_errors.SchemaError):
        StagingVideoDetailsSchema.validate(_video_frame(**overrides))


def test_video_schema_requires_result_set_discriminator() -> None:
    with pytest.raises(pa_errors.SchemaError):
        StagingVideoDetailsAssetSchema.validate(_video_frame().drop("result_set_name"))
