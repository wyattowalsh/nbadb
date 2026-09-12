import pandera.polars as pa

from nbadb.schemas.staging.play_by_play import StagingPlayByPlayV3Schema


class FactPlayByPlaySchema(StagingPlayByPlayV3Schema):
    """Canonical V3 play-by-play packet plus its stable event label."""

    event_type_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("derived.event_type_name"),
            "description": "Stable label derived from the V3 action type",
        },
    )
