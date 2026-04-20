from __future__ import annotations

from nbadb.schemas.base import derived_output_schema
from nbadb.schemas.staging.misc import (
    StagingVideoDetailsAssetSchema,
    StagingVideoDetailsSchema,
    StagingVideoEventsAssetSchema,
    StagingVideoEventsSchema,
    StagingVideoStatusSchema,
)


class FactVideoDetailsSchema(StagingVideoDetailsSchema):
    pass


class FactVideoDetailsAssetSchema(StagingVideoDetailsAssetSchema):
    pass


class FactVideoEventsSchema(StagingVideoEventsSchema):
    pass


class FactVideoEventsAssetSchema(StagingVideoEventsAssetSchema):
    pass


class FactVideoStatusSchema(StagingVideoStatusSchema):
    pass


derived_output_schema()(FactVideoDetailsSchema)
derived_output_schema()(FactVideoDetailsAssetSchema)
derived_output_schema()(FactVideoEventsSchema)
derived_output_schema()(FactVideoEventsAssetSchema)
derived_output_schema()(FactVideoStatusSchema)
