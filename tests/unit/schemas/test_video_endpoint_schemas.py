from __future__ import annotations

import polars as pl
import pytest
from pandera.errors import SchemaError

from nbadb.extract.raw_schema_registry import get_raw_schema
from nbadb.schemas.registry import get_input_schema, get_output_schema


def _video_frame(**overrides: object) -> pl.DataFrame:
    row = {
        "result_set_name": "playlist",
        "result_set_index": 1,
        "context_measure": "PTS",
        "context_measure_provenance": "docs,runtime",
        "season_type_provenance": "runtime",
        "nba_api_contract_version": "1.11.4",
        "request_player_id": 1,
        "request_team_id": 10,
        "request_season": "2020-21",
        "request_season_type": "PlayIn",
        "payload_value": "retained",
    }
    row.update(overrides)
    return pl.DataFrame([row])


@pytest.mark.parametrize(
    "schema",
    [
        get_raw_schema("video_details"),
        get_raw_schema("video_details_asset"),
        get_input_schema("stg_video_details"),
        get_input_schema("stg_video_details_asset"),
        get_output_schema("fact_video_details"),
        get_output_schema("fact_video_details_asset"),
    ],
)
def test_video_schemas_require_provenance_and_retain_dynamic_columns(schema: type) -> None:
    assert schema is not None

    validated = schema.validate(_video_frame())

    assert validated.get_column("payload_value").to_list() == ["retained"]


def test_video_schema_rejects_context_measure_outside_contract() -> None:
    schema = get_input_schema("stg_video_details")
    assert schema is not None

    with pytest.raises(SchemaError):
        schema.validate(_video_frame(context_measure="NOT_A_MEASURE"))


@pytest.mark.parametrize(
    "schema",
    [
        get_input_schema("stg_video_details_asset"),
        get_output_schema("fact_video_details_asset"),
    ],
)
def test_video_details_asset_effective_request_metadata_uses_asset_endpoint(
    schema: type,
) -> None:
    assert schema is not None
    columns = schema.to_schema().columns
    expected_sources = {
        "context_measure": "VideoDetailsAsset.ContextMeasure request",
        "request_player_id": "VideoDetailsAsset.PlayerID request",
        "request_team_id": "VideoDetailsAsset.TeamID request",
        "request_season": "VideoDetailsAsset.Season request",
        "request_season_type": "VideoDetailsAsset.SeasonType request",
    }

    assert {
        column_name: columns[column_name].metadata["source"] for column_name in expected_sources
    } == expected_sources
