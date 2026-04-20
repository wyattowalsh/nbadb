from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class BridgeGameOfficialSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": ("BoxScoreSummaryV2.Officials.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": "dim_game.game_id",
        },
    )
    official_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("BoxScoreSummaryV2.Officials.OFFICIAL_ID"),
            "description": ("Official identifier"),
            "fk_ref": ("dim_official.official_id"),
        },
    )
    jersey_num: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreSummaryV2.Officials.JERSEY_NUM"),
            "description": ("Official jersey number"),
        },
    )
