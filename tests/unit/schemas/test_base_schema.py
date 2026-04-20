from __future__ import annotations

import pandera.polars as pa
import polars as pl

from nbadb.schemas.base import BaseSchema


class _TestSchema(BaseSchema):
    name: str = pa.Field()
    value: int = pa.Field(gt=0)


class TestBaseSchema:
    def test_coerce_enabled(self) -> None:
        assert _TestSchema.Config.coerce is True

    def test_strict_disabled_for_two_tier(self) -> None:
        assert _TestSchema.Config.strict is False

    def test_valid_data_passes(self) -> None:
        df = pl.DataFrame({"name": ["a", "b"], "value": [1, 2]})
        result = _TestSchema.validate(df)
        assert result.shape == (2, 2)

    def test_extra_columns_stripped_with_warning(self) -> None:
        df = pl.DataFrame(
            {
                "name": ["a"],
                "value": [1],
                "extra": [True],
            }
        )
        result = _TestSchema.validate(df)
        assert "extra" not in result.columns
        assert result.shape == (1, 2)
