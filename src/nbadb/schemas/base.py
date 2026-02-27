from __future__ import annotations

import pandera.polars as pa


class BaseSchema(pa.DataFrameModel):
    class Config:
        coerce = True
        strict = False
