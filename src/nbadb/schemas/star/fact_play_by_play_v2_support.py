from __future__ import annotations

from nbadb.schemas.staging.play_by_play import (
    StagingPlayByPlayV2Schema,
    StagingPlayByPlayV2VideoAvailableSchema,
)


class FactPlayByPlayV2Schema(StagingPlayByPlayV2Schema):
    pass


class FactPlayByPlayV2VideoSchema(StagingPlayByPlayV2VideoAvailableSchema):
    pass
