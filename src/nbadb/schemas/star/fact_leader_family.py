from __future__ import annotations

from nbadb.schemas.base import derived_output_schema
from nbadb.schemas.staging.leaders import (
    StagingAssistLeadersSchema,
    StagingAssistTrackerSchema,
    StagingDunkScoreLeadersSchema,
    StagingGravityLeadersSchema,
    StagingLeagueLeadersSchema,
)


@derived_output_schema()
class FactLeagueLeadersSchema(StagingLeagueLeadersSchema):
    pass


@derived_output_schema()
class FactAssistLeadersSchema(StagingAssistLeadersSchema):
    pass


@derived_output_schema()
class FactAssistTrackerSchema(StagingAssistTrackerSchema):
    pass


@derived_output_schema()
class FactDunkScoreLeadersSchema(StagingDunkScoreLeadersSchema):
    pass


@derived_output_schema()
class FactGravityLeadersSchema(StagingGravityLeadersSchema):
    pass
