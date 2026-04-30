from __future__ import annotations

from nbadb.schemas.base import derived_output_schema
from nbadb.schemas.staging.box_score import (
    StagingSummaryV3AvailableVideoSchema,
    StagingSummaryV3GameInfoSchema,
    StagingSummaryV3GameSummarySchema,
    StagingSummaryV3InactivePlayersSchema,
    StagingSummaryV3LastFiveMeetingsSchema,
    StagingSummaryV3LineScoreSchema,
    StagingSummaryV3OfficialsSchema,
    StagingSummaryV3OtherStatsSchema,
)


@derived_output_schema()
class FactBoxScoreSummaryV3GameSummarySchema(StagingSummaryV3GameSummarySchema):
    pass


@derived_output_schema()
class FactBoxScoreSummaryV3GameInfoSchema(StagingSummaryV3GameInfoSchema):
    pass


@derived_output_schema()
class FactBoxScoreSummaryV3OfficialsSchema(StagingSummaryV3OfficialsSchema):
    pass


@derived_output_schema()
class FactBoxScoreSummaryV3LineScoreSchema(StagingSummaryV3LineScoreSchema):
    pass


@derived_output_schema()
class FactBoxScoreSummaryV3InactivePlayersSchema(StagingSummaryV3InactivePlayersSchema):
    pass


@derived_output_schema()
class FactBoxScoreSummaryV3LastFiveMeetingsSchema(StagingSummaryV3LastFiveMeetingsSchema):
    pass


@derived_output_schema()
class FactBoxScoreSummaryV3OtherStatsSchema(StagingSummaryV3OtherStatsSchema):
    pass


@derived_output_schema()
class FactBoxScoreSummaryV3AvailableVideoSchema(StagingSummaryV3AvailableVideoSchema):
    pass
