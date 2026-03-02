from __future__ import annotations

import pandera.polars as pa
import polars as pl
import pytest
from pandera.errors import SchemaError

from nbadb.schemas.base import BaseSchema


class _TestSchema(BaseSchema):
    name: str = pa.Field()
    value: int = pa.Field(gt=0)


class TestBaseSchema:
    def test_coerce_enabled(self) -> None:
        assert _TestSchema.Config.coerce is True

    def test_strict_enabled(self) -> None:
        assert _TestSchema.Config.strict is True

    def test_valid_data_passes(self) -> None:
        df = pl.DataFrame({"name": ["a", "b"], "value": [1, 2]})
        result = _TestSchema.validate(df)
        assert result.shape == (2, 2)

    def test_extra_columns_rejected(self) -> None:
        df = pl.DataFrame(
            {
                "name": ["a"],
                "value": [1],
                "extra": [True],
            }
        )
        with pytest.raises(SchemaError):
            _TestSchema.validate(df)
