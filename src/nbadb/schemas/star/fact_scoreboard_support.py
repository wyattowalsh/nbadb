from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import derived_output_schema
from nbadb.schemas.staging.schedule import (
    StagingScoreboardEastConfSchema,
    StagingScoreboardLastMeetingSchema,
    StagingScoreboardLineScoreSchema,
    StagingScoreboardSeriesStandingsSchema,
    StagingScoreboardTeamLeadersSchema,
    StagingScoreboardTicketLinksSchema,
    StagingScoreboardV2Schema,
    StagingScoreboardV3BroadcasterSchema,
    StagingScoreboardV3LineScoreSchema,
    StagingScoreboardV3MetadataSchema,
    StagingScoreboardV3SummarySchema,
    StagingScoreboardV3TeamStatsSchema,
)


@derived_output_schema()
class FactScoreboardGameHeaderSchema(StagingScoreboardV2Schema):
    pass


@derived_output_schema(literal_fields={"conference_scope"})
class FactScoreboardConferenceStandingsSchema(StagingScoreboardEastConfSchema):
    conference_scope: str = pa.Field(nullable=False, isin=["east", "west"])


@derived_output_schema()
class FactScoreboardLastMeetingSchema(StagingScoreboardLastMeetingSchema):
    pass


@derived_output_schema()
class FactScoreboardLineScoreSchema(StagingScoreboardLineScoreSchema):
    pass


@derived_output_schema(literal_fields={"series_scope"})
class FactScoreboardSeriesStandingsSchema(StagingScoreboardSeriesStandingsSchema):
    series_scope: str = pa.Field(
        nullable=False,
        isin=["scoreboard_v2", "scoreboard_v2_alternate"],
    )


@derived_output_schema()
class FactScoreboardTeamLeadersSchema(StagingScoreboardTeamLeadersSchema):
    pass


@derived_output_schema()
class FactScoreboardTicketLinksSchema(StagingScoreboardTicketLinksSchema):
    pass


@derived_output_schema()
class FactScoreboardV3MetadataSchema(StagingScoreboardV3MetadataSchema):
    pass


@derived_output_schema()
class FactScoreboardV3GameSummarySchema(StagingScoreboardV3SummarySchema):
    pass


@derived_output_schema()
class FactScoreboardV3LineScoreSchema(StagingScoreboardV3LineScoreSchema):
    pass


@derived_output_schema()
class FactScoreboardV3TeamLeadersSchema(StagingScoreboardV3TeamStatsSchema):
    pass


@derived_output_schema()
class FactScoreboardV3BroadcasterSchema(StagingScoreboardV3BroadcasterSchema):
    pass
