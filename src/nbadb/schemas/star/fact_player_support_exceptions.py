from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import derived_output_schema
from nbadb.schemas.staging.player import StagingPlayerIndexSchema
from nbadb.schemas.staging.player_support_matrix import _PvpPlayerInfoSchema


class FactPlayerIndexSchema(StagingPlayerIndexSchema):
    pass


class FactPlayerMatchupsPlayerInfoSchema(_PvpPlayerInfoSchema):
    player_role: str = pa.Field(nullable=False, isin=["player", "vs_player"])


derived_output_schema()(FactPlayerIndexSchema)
derived_output_schema(literal_fields={"player_role"})(FactPlayerMatchupsPlayerInfoSchema)
