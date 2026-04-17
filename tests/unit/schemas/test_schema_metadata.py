from __future__ import annotations

import pandera.polars as pa

from nbadb.core.model_audit import _classify_column_origin
from nbadb.schemas.base import BaseSchema, derived_output_schema
from nbadb.schemas.star.fact_box_score_four_factors import FactBoxScoreFourFactorsSchema
from nbadb.schemas.star.fact_homepage_leaders import FactHomepageLeadersSchema
from nbadb.schemas.star.fact_shot_chart_league_averages import (
    FactShotChartLeagueAveragesSchema,
)


class _MetadataMixin(BaseSchema):
    player_id: int = pa.Field(gt=0, metadata={"description": "Player identifier"})
    metric: float | None = pa.Field(nullable=True, metadata={"description": "Derived metric"})


@derived_output_schema(
    source_overrides={"metric": "stg_example.metric"},
    literal_fields={"kind"},
)
class ExampleSchema(_MetadataMixin, BaseSchema):
    kind: str = pa.Field(metadata={"description": "Example discriminator"})


def test_derived_output_schema_applies_metadata_to_inherited_fields() -> None:
    schema = ExampleSchema.to_schema()

    assert schema.columns["player_id"].metadata == {
        "description": "Player identifier",
        "fk_ref": "dim_player.player_id",
    }
    assert schema.columns["metric"].metadata == {
        "description": "Derived metric",
        "source": "stg_example.metric",
    }
    assert schema.columns["kind"].metadata == {
        "description": "Example discriminator",
        "source": "literal.kind",
    }


def test_leaf_fact_schemas_emit_recognized_origin_metadata() -> None:
    schemas = (
        FactBoxScoreFourFactorsSchema,
        FactHomepageLeadersSchema,
        FactShotChartLeagueAveragesSchema,
    )

    for schema_cls in schemas:
        schema = schema_cls.to_schema()
        missing = [
            column_name
            for column_name, column in schema.columns.items()
            if _classify_column_origin(
                column_name=column_name,
                metadata=dict(column.metadata or {}),
            )
            is None
        ]
        assert missing == [], f"{schema_cls.__name__} is missing origin metadata for {missing}"

    homepage_schema = FactHomepageLeadersSchema.to_schema()
    assert homepage_schema.columns["leader_source"].metadata["source"] == "literal.leader_source"
    assert homepage_schema.columns["pts"].metadata["source"] == "derived.fact_homepage_leaders.pts"

    shot_chart_schema = FactShotChartLeagueAveragesSchema.to_schema()
    assert (
        shot_chart_schema.columns["average_source"].metadata["source"] == "literal.average_source"
    )
    assert (
        shot_chart_schema.columns["grid_type"].metadata["source"]
        == "derived.fact_shot_chart_league_averages.grid_type"
    )
