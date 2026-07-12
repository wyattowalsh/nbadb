from __future__ import annotations

import tomllib
from pathlib import Path

import nba_api
import pytest
from nba_api.stats.library.parameters import (
    ContextMeasureDetailed,
)
from nba_api.stats.library.parameters import (
    SeasonType as NbaApiSeasonType,
)

from nbadb.core.types import (
    ALL_STAR_CANCELLED_UPSTREAM_UNAVAILABLE_REASON,
    ALL_STAR_PRE_HISTORY_UPSTREAM_UNAVAILABLE_REASON,
    NBA_API_VIDEO_CONTEXT_MEASURE_DOCS_SOURCE,
    NBA_API_VIDEO_CONTEXT_MEASURE_RUNTIME_SOURCE,
    NBA_API_VIDEO_CONTEXT_MEASURE_VERSION,
    PLAY_IN_FIRST_SEASON_START_YEAR,
    VIDEO_CONTEXT_MEASURE_DOCS_ONLY,
    VIDEO_CONTEXT_MEASURE_PROVENANCE,
    VIDEO_CONTEXT_MEASURES,
    VIDEO_SEASON_TYPE_PROVENANCE,
    SeasonType,
    VideoContextMeasure,
    classify_season_type_availability,
    season_type_upstream_unavailable_reason,
)


def _runtime_context_measures() -> set[str]:
    return {
        value
        for cls in ContextMeasureDetailed.__mro__
        for name, value in vars(cls).items()
        if not name.startswith("_") and name != "default" and isinstance(value, str)
    }


def test_video_context_measure_contract_matches_pinned_docs_runtime_union() -> None:
    runtime_values = _runtime_context_measures()
    runtime_provenance_values = {
        measure.value
        for measure, provenance in VIDEO_CONTEXT_MEASURE_PROVENANCE.items()
        if "runtime" in provenance
    }

    assert nba_api.__version__ == NBA_API_VIDEO_CONTEXT_MEASURE_VERSION == "1.11.4"
    assert len(VIDEO_CONTEXT_MEASURES) == 78
    assert len(set(VIDEO_CONTEXT_MEASURES)) == 78
    assert runtime_values == runtime_provenance_values
    assert {measure.value for measure in VIDEO_CONTEXT_MEASURE_DOCS_ONLY} == {
        "PF",
        "PFD",
        "OPP_FGM",
        "OPP_FGA",
        "OPP_FG3M",
        "OPP_FG3A",
    }
    assert set(VIDEO_CONTEXT_MEASURES) == runtime_values | {
        measure.value for measure in VIDEO_CONTEXT_MEASURE_DOCS_ONLY
    }
    assert "videodetails" in NBA_API_VIDEO_CONTEXT_MEASURE_DOCS_SOURCE
    assert "ContextMeasureDetailed" in NBA_API_VIDEO_CONTEXT_MEASURE_RUNTIME_SOURCE


def test_project_dependency_pins_the_provenance_runtime_exactly() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "nba-api==1.11.4" in pyproject["project"]["dependencies"]


def test_play_in_uses_runtime_spelling_provenance_and_historical_floor() -> None:
    assert SeasonType.PLAY_IN.value == NbaApiSeasonType.playin == "PlayIn"
    assert VIDEO_SEASON_TYPE_PROVENANCE[SeasonType.PLAY_IN] == ("runtime",)
    assert PLAY_IN_FIRST_SEASON_START_YEAR == 2019
    assert classify_season_type_availability(2018, SeasonType.PLAY_IN.value) == (
        "upstream_unavailable"
    )
    assert classify_season_type_availability(2019, SeasonType.PLAY_IN.value) == "supported"
    assert classify_season_type_availability(1946, SeasonType.REGULAR.value) == "supported"


@pytest.mark.parametrize(
    ("season_start_year", "expected_reason"),
    [
        (1949, ALL_STAR_PRE_HISTORY_UPSTREAM_UNAVAILABLE_REASON),
        (1998, ALL_STAR_CANCELLED_UPSTREAM_UNAVAILABLE_REASON),
    ],
)
def test_all_star_historical_gaps_have_deterministic_reason_codes(
    season_start_year: int,
    expected_reason: str,
) -> None:
    assert classify_season_type_availability(season_start_year, SeasonType.ALL_STAR) == (
        "upstream_unavailable"
    )
    assert (
        season_type_upstream_unavailable_reason(season_start_year, SeasonType.ALL_STAR)
        == expected_reason
    )


@pytest.mark.parametrize("season_start_year", [1950, 1999])
def test_all_star_supported_boundaries_remain_executable(season_start_year: int) -> None:
    assert classify_season_type_availability(season_start_year, SeasonType.ALL_STAR) == "supported"
    assert season_type_upstream_unavailable_reason(season_start_year, SeasonType.ALL_STAR) is None


def test_season_type_availability_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="not a valid SeasonType"):
        classify_season_type_availability(2024, "Play-In")


def test_video_context_measure_enum_rejects_undocumented_values() -> None:
    with pytest.raises(ValueError, match="not a valid VideoContextMeasure"):
        VideoContextMeasure("UNKNOWN")
