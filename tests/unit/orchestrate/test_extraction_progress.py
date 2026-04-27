from __future__ import annotations

from types import SimpleNamespace

from nbadb.orchestrate.extraction_progress import ExtractionProgressStore


def test_extraction_progress_store_marks_completion(tmp_path) -> None:
    store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
    item = SimpleNamespace(
        label="player x season",
        pattern="player_season",
        entries=[SimpleNamespace(endpoint_name="player_game_log")],
        params=[{"player_id": 1, "season": "2024-25"}],
    )
    key = store.slice_key("init", item)

    store.mark_started(key, task_count=1)
    store.mark_complete(
        key,
        task_count=1,
        row_count=10,
        wall_time_seconds=2.5,
        staging_keys=["stg_player_game_log"],
        endpoint_families=["default"],
    )

    payload = store.load(key)
    assert payload["status"] == "complete"
    assert store.is_complete(key) is True


def test_extraction_progress_store_marks_failures(tmp_path) -> None:
    store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
    item = SimpleNamespace(
        label="game",
        pattern="game",
        entries=[SimpleNamespace(endpoint_name="box_score_traditional")],
        params=[{"game_id": "001"}],
    )
    key = store.slice_key("backfill", item)

    store.mark_failed(key, task_count=1, error="TimeoutError")

    payload = store.load(key)
    assert payload["status"] == "failed"
    assert payload["error"] == "TimeoutError"
