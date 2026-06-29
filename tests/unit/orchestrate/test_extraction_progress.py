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
    assert payload["schema_version"] == ExtractionProgressStore.SCHEMA_VERSION
    assert store.is_complete(key) is True


def test_extraction_progress_store_rejects_v1_complete_payload(tmp_path) -> None:
    store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
    item = SimpleNamespace(
        label="player x season",
        pattern="player_season",
        entries=[SimpleNamespace(endpoint_name="player_game_log")],
        params=[{"player_id": 1, "season": "2024-25"}],
    )
    key = store.slice_key("init", item)
    path = store._path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"status":"complete","task_count":1}\n', encoding="utf-8")

    assert store.is_complete(key) is False


def test_extraction_progress_store_requires_all_eligible_calls(tmp_path) -> None:
    store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
    item = SimpleNamespace(
        label="game",
        pattern="game",
        entries=[SimpleNamespace(endpoint_name="box_score_traditional")],
        params=[{"game_id": "001"}],
    )
    key = store.slice_key("init", item)

    store.mark_complete(
        key,
        task_count=2,
        eligible_calls=2,
        success_count=1,
        journal_skip_count=0,
        row_count=10,
        wall_time_seconds=2.5,
        staging_keys=["stg_box_score_traditional"],
        endpoint_families=["box_score"],
    )

    assert store.is_complete(key) is False


def test_extraction_progress_store_counts_retry_skips_as_complete(tmp_path) -> None:
    store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
    item = SimpleNamespace(
        label="game",
        pattern="game",
        entries=[SimpleNamespace(endpoint_name="box_score_traditional")],
        params=[{"game_id": "001"}],
    )
    key = store.slice_key("retry", item)

    store.mark_complete(
        key,
        task_count=1,
        eligible_calls=1,
        success_count=0,
        retry_skip_count=1,
        row_count=0,
        wall_time_seconds=0.5,
        staging_keys=["stg_box_score_traditional"],
        endpoint_families=["box_score"],
    )

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
    assert store.is_complete(key) is False


def test_extraction_progress_store_running_status_is_not_complete(tmp_path) -> None:
    store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
    item = SimpleNamespace(
        label="game",
        pattern="game",
        entries=[SimpleNamespace(endpoint_name="box_score_traditional")],
        params=[{"game_id": "001"}],
    )
    key = store.slice_key("backfill", item)

    store.mark_started(key, task_count=1)

    assert store.is_complete(key) is False


def test_extraction_progress_store_ignores_corrupted_json(tmp_path) -> None:
    store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
    item = SimpleNamespace(
        label="game",
        pattern="game",
        entries=[SimpleNamespace(endpoint_name="box_score_traditional")],
        params=[{"game_id": "001"}],
    )
    key = store.slice_key("backfill", item)
    path = store._path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")

    assert store.load(key) == {}
    assert store.is_complete(key) is False
    assert path.exists() is False
    assert list(path.parent.glob(f"{path.name}.corrupt.*"))
