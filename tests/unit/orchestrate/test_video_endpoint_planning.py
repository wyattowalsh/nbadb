from __future__ import annotations

import pytest

from nbadb.core.types import VIDEO_CONTEXT_MEASURES, SeasonType
from nbadb.orchestrate.planning import build_extraction_plan
from nbadb.orchestrate.staging_map import get_by_staging_key


def _plan_for(params: list[dict[str, int | str]]):
    return build_extraction_plan(
        seasons=[],
        game_ids=[],
        player_ids=[],
        team_ids=[],
        game_dates=[],
        player_team_season_params=params,
        include_static=False,
        season_types=list(SeasonType),
    )


def test_video_planner_expands_every_measure_once_per_unique_affiliation() -> None:
    affiliation = {
        "player_id": 1,
        "team_id": 10,
        "season": "2024-25",
        "season_type": "Regular Season",
    }

    plan = _plan_for([affiliation, dict(affiliation)])

    assert len(plan) == 2
    items_by_endpoint = {item.entries[0].endpoint_name: item for item in plan}
    assert set(items_by_endpoint) == {
        "video_details",
        "video_details_asset",
    }
    for endpoint_name, item in items_by_endpoint.items():
        assert len(item.entries) == 1
        assert len(item.params) == 78
        assert item.task_count == 78
        assert endpoint_name in item.label
        assert [param["context_measure"] for param in item.params] == list(VIDEO_CONTEXT_MEASURES)
        assert all(
            {key: value for key, value in param.items() if key != "context_measure"} == affiliation
            for param in item.params
        )


def test_video_planner_classifies_pre_2019_play_in_as_unavailable() -> None:
    plan = _plan_for(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2018-19",
                "season_type": "PlayIn",
            }
        ]
    )

    assert plan == []


def test_video_planner_includes_first_play_in_season() -> None:
    plan = _plan_for(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2019-20",
                "season_type": "PlayIn",
            }
        ]
    )

    assert len(plan) == 2
    assert all(len(item.params) == len(VIDEO_CONTEXT_MEASURES) for item in plan)


@pytest.mark.parametrize("season", ["1949-50", "1998-99"])
def test_video_planner_excludes_historical_all_star_gaps(season: str) -> None:
    plan = _plan_for(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": season,
                "season_type": "All Star",
            }
        ]
    )

    assert plan == []


def test_video_staging_routes_declare_play_in_without_endpoint_floor() -> None:
    for staging_key in ("stg_video_details", "stg_video_details_asset"):
        entry = get_by_staging_key(staging_key)
        assert entry is not None
        assert entry.min_season is None
        assert entry.supported_season_types == tuple(SeasonType)
