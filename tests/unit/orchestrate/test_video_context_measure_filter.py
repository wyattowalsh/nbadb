from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

from nbadb.core.types import VIDEO_CONTEXT_MEASURES
from nbadb.orchestrate.orchestrator import ExtractionOutcome, Orchestrator
from nbadb.orchestrate.planning import ExtractionPlanItem, build_extraction_plan

_BUILD_EXTRACTION_PLAN = "nbadb.orchestrate.orchestrator.build_extraction_plan"


def _video_plan(context_measures: list[str] | None = None) -> list[ExtractionPlanItem]:
    return build_extraction_plan(
        seasons=["2024-25"],
        game_ids=[],
        player_ids=[],
        team_ids=[],
        game_dates=[],
        player_team_season_params=[
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ],
        include_static=False,
        season_types=["Regular Season"],
        context_measures=context_measures,
    )


def _video_item(plan: list[ExtractionPlanItem]) -> ExtractionPlanItem:
    return next(item for item in plan if item.pattern == "player_team_season")


def _plan_snapshot(plan: list[ExtractionPlanItem]) -> list[tuple[object, ...]]:
    return [
        (
            item.label,
            item.pattern,
            tuple(entry.staging_key for entry in item.entries),
            item.params,
            item.priority,
        )
        for item in plan
    ]


def test_video_context_measure_filter_defaults_to_all_measures() -> None:
    item = _video_item(_video_plan())

    assert [param["context_measure"] for param in item.params] == list(VIDEO_CONTEXT_MEASURES)


def test_video_context_measure_filter_uses_explicit_unique_order() -> None:
    item = _video_item(_video_plan(["AST", "PTS", "AST"]))

    assert [param["context_measure"] for param in item.params] == ["AST", "PTS"]


@pytest.mark.parametrize(
    ("context_measures", "error"),
    [
        ([], "cannot be empty"),
        (["NOT_A_MEASURE"], "Unknown video context measure\\(s\\): NOT_A_MEASURE"),
    ],
)
def test_video_context_measure_filter_rejects_invalid_explicit_values(
    context_measures: list[str],
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        _video_plan(context_measures)


def test_context_measure_filter_does_not_change_non_video_plan() -> None:
    default_plan = build_extraction_plan(
        seasons=[],
        game_ids=["0022400001"],
        player_ids=[],
        team_ids=[],
        game_dates=[],
        include_static=False,
    )
    filtered_plan = build_extraction_plan(
        seasons=[],
        game_ids=["0022400001"],
        player_ids=[],
        team_ids=[],
        game_dates=[],
        include_static=False,
        context_measures=["PTS"],
    )

    assert _plan_snapshot(filtered_plan) == _plan_snapshot(default_plan)


def test_extract_all_patterns_threads_context_measures_to_planner() -> None:
    orchestrator = Orchestrator(settings=MagicMock())
    runner = MagicMock()

    with patch(_BUILD_EXTRACTION_PLAN, return_value=[]) as mock_build_plan:
        outcome = asyncio.run(
            orchestrator._extract_all_patterns(
                runner,
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                game_dates=[],
                game_log_df=pl.DataFrame(),
                include_static=False,
                context_measures=["AST", "PTS"],
            )
        )

    assert outcome == ExtractionOutcome(raw={})
    assert mock_build_plan.call_args.kwargs["context_measures"] == ["AST", "PTS"]


def test_run_backfill_validates_context_measures_before_initializing_db() -> None:
    orchestrator = Orchestrator(settings=MagicMock())

    with (
        patch.object(orchestrator, "_init_db") as mock_init_db,
        pytest.raises(ValueError, match="cannot be empty"),
    ):
        asyncio.run(orchestrator.run_backfill(context_measures=[]))

    mock_init_db.assert_not_called()


def test_run_backfill_threads_context_measures_to_plan_and_extraction() -> None:
    orchestrator = Orchestrator(settings=MagicMock())
    db = MagicMock()
    journal = MagicMock()
    journal.get_failed.return_value = []
    runner = MagicMock(skipped=0)
    runner.__aenter__ = AsyncMock(return_value=runner)
    runner.__aexit__ = AsyncMock(return_value=None)
    runner._thread_pool = None
    mock_extract = AsyncMock(return_value=ExtractionOutcome(raw={}))

    with (
        patch.object(orchestrator, "_init_db", return_value=(db, journal)),
        patch.object(orchestrator, "_build_runner", return_value=runner),
        patch.object(orchestrator, "_build_discovery", return_value=MagicMock()),
        patch.object(
            orchestrator,
            "_discover_entities",
            AsyncMock(return_value=([], [], [], [], pl.DataFrame())),
        ),
        patch.object(orchestrator, "_extract_all_patterns", mock_extract),
        patch.object(orchestrator, "_extraction_progress", return_value=None),
        patch(_BUILD_EXTRACTION_PLAN, return_value=[]) as mock_build_plan,
    ):
        asyncio.run(
            orchestrator.run_backfill(
                patterns=["static"],
                extract_only=True,
                context_measures=["AST", "PTS"],
            )
        )

    assert mock_build_plan.call_args.kwargs["context_measures"] == ["AST", "PTS"]
    assert mock_extract.await_args is not None
    assert mock_extract.await_args.kwargs["context_measures"] == ["AST", "PTS"]
