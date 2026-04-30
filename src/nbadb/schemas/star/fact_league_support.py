from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema
from nbadb.schemas.raw.draft import (
    RawDraftCombineDrillResultsSchema,
    RawDraftCombineNonStationaryShootingSchema,
    RawDraftCombinePlayerAnthroSchema,
    RawDraftCombineSpotShootingSchema,
)
from nbadb.schemas.staging.league_stats import StagingLeagueDashPlayerStatsSchema
from nbadb.schemas.staging.league_support import (
    LeaguePtShotsBaseSchema,
    StagingBoxScoreUsageTeamSchema,
    StagingCommonPlayoffSeriesSchema,
    StagingIstStandingsSchema,
    StagingLeagueOppPtShotSchema,
    StagingLeaguePlayerPtShotSchema,
    StagingLeaguePtStatsSchema,
    StagingLeaguePtTeamDefendSchema,
    StagingLeagueTeamClutchSchema,
    StagingLeagueTeamPtShotSchema,
    StagingLeagueTeamShotLocationsSchema,
    StagingShotLocationsSchema,
)


class FactPlayoffSeriesSchema(StagingCommonPlayoffSeriesSchema):
    pass


class FactIstStandingsSchema(StagingIstStandingsSchema):
    pass


class FactLeagueDashPlayerStatsSchema(StagingLeagueDashPlayerStatsSchema):
    pass


class FactLeagueTeamClutchSchema(StagingLeagueTeamClutchSchema):
    pass


class FactLeagueShotLocationsSchema(StagingLeagueTeamShotLocationsSchema):
    pass


class FactLeagueTeamShotLocationsSchema(StagingLeagueTeamShotLocationsSchema):
    pass


class FactLeaguePlayerShotLocationsSchema(StagingShotLocationsSchema):
    pass


class FactLeaguePtStatsSchema(StagingLeaguePtStatsSchema):
    pass


class FactLeaguePtTeamDefendSchema(StagingLeaguePtTeamDefendSchema):
    pass


class FactLeagueTeamPtShotSchema(StagingLeagueTeamPtShotSchema):
    pass


class FactLeagueOppPtShotSchema(StagingLeagueOppPtShotSchema):
    pass


class FactLeaguePlayerPtShotSchema(StagingLeaguePlayerPtShotSchema):
    pass


class FactBoxScoreUsageTeamSchema(StagingBoxScoreUsageTeamSchema):
    pass


class FactDraftCombineDetailSchema(BaseSchema):
    player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Player identifier", "fk_ref": "dim_player.player_id"},
    )
    height: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Height metric"}
    )
    result: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Drill result"})
    pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"description": "Shooting percentage"},
    )
    detail_type: str = pa.Field(
        isin=["drills", "anthro", "nonstat_shooting", "spot_shooting"],
        metadata={"description": "Draft-combine detail packet discriminator"},
    )


class FactDraftCombineDrillResultsSchema(RawDraftCombineDrillResultsSchema):
    pass


class FactDraftCombineNonStationaryShootingSchema(RawDraftCombineNonStationaryShootingSchema):
    pass


class FactDraftCombinePlayerAnthroSchema(RawDraftCombinePlayerAnthroSchema):
    pass


class FactDraftCombineSpotShootingSchema(RawDraftCombineSpotShootingSchema):
    pass


class FactLeaguePtShotsSchema(LeaguePtShotsBaseSchema):
    shot_type: str = pa.Field(
        isin=["stats", "team_defend", "team", "opponent", "player"],
        metadata={"description": "League player-tracking shot packet discriminator"},
    )


class FactLeagueHustleSchema(BaseSchema):
    entity_type: str = pa.Field(
        isin=["player", "team", "bio_stats"],
        metadata={"description": "League hustle packet discriminator"},
    )
    player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Player identifier", "fk_ref": "dim_player.player_id"},
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={"description": "Team identifier", "fk_ref": "dim_team.team_id"},
    )
    player_name: str | None = pa.Field(nullable=True, metadata={"description": "Player name"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team name"})
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    min: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Minutes"})
    deflections: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={"description": "Deflections"},
    )


derived_output_schema()(FactPlayoffSeriesSchema)
derived_output_schema()(FactIstStandingsSchema)
derived_output_schema()(FactLeagueDashPlayerStatsSchema)
derived_output_schema()(FactLeagueTeamClutchSchema)
derived_output_schema()(FactLeagueShotLocationsSchema)
derived_output_schema()(FactLeagueTeamShotLocationsSchema)
derived_output_schema()(FactLeaguePlayerShotLocationsSchema)
derived_output_schema()(FactLeaguePtStatsSchema)
derived_output_schema()(FactLeaguePtTeamDefendSchema)
derived_output_schema()(FactLeagueTeamPtShotSchema)
derived_output_schema()(FactLeagueOppPtShotSchema)
derived_output_schema()(FactLeaguePlayerPtShotSchema)
derived_output_schema()(FactBoxScoreUsageTeamSchema)
derived_output_schema(literal_fields={"detail_type"})(FactDraftCombineDetailSchema)
derived_output_schema()(FactDraftCombineDrillResultsSchema)
derived_output_schema()(FactDraftCombineNonStationaryShootingSchema)
derived_output_schema()(FactDraftCombinePlayerAnthroSchema)
derived_output_schema()(FactDraftCombineSpotShootingSchema)
derived_output_schema(literal_fields={"shot_type"})(FactLeaguePtShotsSchema)
derived_output_schema(literal_fields={"entity_type"})(FactLeagueHustleSchema)
