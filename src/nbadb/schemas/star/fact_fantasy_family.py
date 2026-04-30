from __future__ import annotations

from nbadb.schemas.base import derived_output_schema
from nbadb.schemas.staging.player_team_family_support import (
    StagingFanduelPlayerSchema,
    StagingFantasyWidgetSchema,
    StagingPlayerFantasyProfileLastFiveGamesAvgSchema,
    StagingPlayerFantasyProfileSeasonAvgSchema,
)


@derived_output_schema()
class FactFantasyWidgetSchema(StagingFantasyWidgetSchema):
    pass


@derived_output_schema()
class FactInfographicFanduelPlayerSchema(StagingFanduelPlayerSchema):
    pass


@derived_output_schema()
class FactPlayerFantasyProfileLastFiveGamesAvgSchema(
    StagingPlayerFantasyProfileLastFiveGamesAvgSchema
):
    pass


@derived_output_schema()
class FactPlayerFantasyProfileSeasonAvgSchema(StagingPlayerFantasyProfileSeasonAvgSchema):
    pass
