from __future__ import annotations

import inspect

import nba_api
from nba_api.stats.library.parameters import ContextMeasureDetailed, SeasonTypeAllStar

from nbadb.core.types import (
    NBA_API_VIDEO_CONTEXT_MEASURE_DOCS_SOURCE,
    NBA_API_VIDEO_CONTEXT_MEASURE_RUNTIME_SOURCE,
    NBA_API_VIDEO_CONTEXT_MEASURE_VERSION,
    VIDEO_CONTEXT_MEASURE_DOCS_ONLY,
    VIDEO_CONTEXT_MEASURE_PROVENANCE,
    VIDEO_CONTEXT_MEASURES,
    SeasonType,
    VideoContextMeasure,
    classify_season_type_availability,
)


def _public_string_values(cls: type) -> set[str]:
    values: set[str] = set()
    for base in reversed(inspect.getmro(cls)):
        values.update(
            value
            for name, value in vars(base).items()
            if not name.startswith("_") and name != "default" and isinstance(value, str)
        )
    return values


def test_video_context_measure_contract_matches_pinned_docs_runtime_union() -> None:
    docs_only = {measure.value for measure in VIDEO_CONTEXT_MEASURE_DOCS_ONLY}
    runtime_values = _public_string_values(ContextMeasureDetailed)

    assert nba_api.__version__ == NBA_API_VIDEO_CONTEXT_MEASURE_VERSION == "1.11.4"
    assert len(VIDEO_CONTEXT_MEASURES) == len(set(VIDEO_CONTEXT_MEASURES)) == 78
    assert set(VIDEO_CONTEXT_MEASURES) - docs_only == runtime_values
    assert docs_only == {"PF", "PFD", "OPP_FGM", "OPP_FGA", "OPP_FG3M", "OPP_FG3A"}
    assert "1.11.4" in NBA_API_VIDEO_CONTEXT_MEASURE_DOCS_SOURCE
    assert "1.11.4" in NBA_API_VIDEO_CONTEXT_MEASURE_RUNTIME_SOURCE


def test_video_context_measure_provenance_is_explicit_for_every_literal() -> None:
    assert set(VIDEO_CONTEXT_MEASURE_PROVENANCE) == set(VideoContextMeasure)
    assert VIDEO_CONTEXT_MEASURE_PROVENANCE[VideoContextMeasure.PTS] == ("docs", "runtime")
    assert VIDEO_CONTEXT_MEASURE_PROVENANCE[VideoContextMeasure.PF] == ("docs",)


def test_play_in_is_runtime_supported_only_for_modern_seasons() -> None:
    assert SeasonTypeAllStar.playin == SeasonType.PLAY_IN.value == "PlayIn"
    assert classify_season_type_availability(2018, SeasonType.PLAY_IN.value) == (
        "upstream_unavailable"
    )
    assert classify_season_type_availability(2019, SeasonType.PLAY_IN.value) == "supported"
    assert classify_season_type_availability(1946, SeasonType.REGULAR.value) == "supported"
