from __future__ import annotations

import pandera.polars as pa
import polars as pl

from nbadb.schemas.base import BaseSchema


class _TestSchema(BaseSchema):
    name: str = pa.Field()
    value: int = pa.Field(gt=0)


class _TestStarSchema(BaseSchema):
    __module__ = "nbadb.schemas.star._test"

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

    def test_extra_columns_are_preserved(self) -> None:
        df = pl.DataFrame(
            {
                "name": ["a"],
                "value": [1],
                "extra": [True],
            }
        )
        result = _TestSchema.validate(df)
        assert result.columns == ["name", "value", "extra"]
        assert result["extra"].to_list() == [True]
        assert result.shape == (1, 3)

    def test_lazy_frame_extra_columns_are_preserved(self) -> None:
        lazy = pl.DataFrame(
            {
                "name": ["a"],
                "value": [1],
                "provider_addition": ["kept"],
            }
        ).lazy()

        result = _TestSchema.validate(lazy).collect()

        assert result.columns == ["name", "value", "provider_addition"]
        assert result["provider_addition"].to_list() == ["kept"]

    def test_curated_star_schema_excludes_unreviewed_columns(self) -> None:
        df = pl.DataFrame(
            {
                "name": ["a"],
                "value": [1],
                "unreviewed_provider_field": ["landing-only"],
            }
        )

        result = _TestStarSchema.validate(df)

        assert result.columns == ["name", "value"]
