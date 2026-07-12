from __future__ import annotations

import pandera.polars as pa
import polars as pl
from pandera.errors import SchemaError

from nbadb.core.types import VIDEO_CONTEXT_MEASURES, SeasonType
from nbadb.schemas.base import BaseSchema


class RawDunkScoreLeadersSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": "DunkScoreLeaders.dunks.playerId",
            "description": "NBA player identifier from the dunk score leaderboard payload.",
            "fk_ref": "dim_player.player_id",
        },
    )
    dunk_score: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "DunkScoreLeaders.dunks.dunkScore",
            "description": "Endpoint-provided dunk score leaderboard value.",
        },
    )


class RawGravityLeadersSchema(BaseSchema):
    playerid: int = pa.Field(
        gt=0,
        metadata={
            "source": "GravityLeaders.leaders.PLAYERID",
            "description": "NBA player identifier from the gravity leaderboard payload.",
            "fk_ref": "dim_player.player_id",
        },
    )
    gravityscore: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "GravityLeaders.leaders.GRAVITYSCORE",
            "description": "Endpoint-provided player gravity score leaderboard value.",
        },
    )


class _OpenVideoDetailsSchema(BaseSchema):
    result_set_name: str = pa.Field(nullable=False)
    result_set_index: int = pa.Field(nullable=False, ge=0)
    context_measure: str = pa.Field(nullable=False, isin=VIDEO_CONTEXT_MEASURES)
    context_measure_provenance: str = pa.Field(
        nullable=False,
        isin=["docs", "docs,runtime"],
    )
    season_type_provenance: str = pa.Field(
        nullable=False,
        isin=["docs,runtime", "runtime"],
    )
    nba_api_contract_version: str = pa.Field(nullable=False, isin=["1.11.4"])
    request_player_id: int = pa.Field(nullable=False, gt=0)
    request_team_id: int = pa.Field(nullable=False, gt=0)
    request_season: str = pa.Field(nullable=False)
    request_season_type: str = pa.Field(
        nullable=False,
        isin=tuple(season_type.value for season_type in SeasonType),
    )

    @classmethod
    def validate(cls, data, *args, **kwargs):
        schema = cls.to_schema()
        if isinstance(data, (pl.DataFrame, pl.LazyFrame)):
            columns = (
                data.collect_schema().names() if isinstance(data, pl.LazyFrame) else data.columns
            )
            missing = sorted(set(schema.columns) - set(columns))
            if missing:
                raise SchemaError(
                    schema,
                    data,
                    f"missing required video contract columns: {missing}",
                )
        return pa.DataFrameModel.validate.__func__(cls, data, *args, **kwargs)


class RawVideoDetailsSchema(_OpenVideoDetailsSchema):
    pass


class RawVideoDetailsAssetSchema(_OpenVideoDetailsSchema):
    pass
