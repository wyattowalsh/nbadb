from __future__ import annotations

from nbadb.transform.facts.fact_video_support import (
    FactVideoDetailsAssetTransformer,
    FactVideoDetailsTransformer,
)


def test_video_transforms_preserve_all_discriminator_columns() -> None:
    assert FactVideoDetailsTransformer._SQL == "SELECT * FROM stg_video_details"
    assert FactVideoDetailsAssetTransformer._SQL == "SELECT * FROM stg_video_details_asset"
