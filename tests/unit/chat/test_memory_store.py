from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from typing import TYPE_CHECKING, Any, cast

import pytest

from nbadb.chat.mcp import memory as memory_mcp
from nbadb.chat.memory import MemoryStore
from nbadb.chat.memory import store as memory_store_module

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType


def _stored_preference(store: MemoryStore, key: str = "theme") -> tuple[dict[str, Any], str]:
    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT record_json, updated_at FROM preferences WHERE key = ?",
            [key],
        ).fetchone()
    assert row is not None
    return json.loads(row[0]), row[1]


def _insert_preference_with_timestamps(
    store: MemoryStore,
    *,
    json_timestamp: str | None,
    sql_timestamp: str | None,
) -> None:
    payload: dict[str, Any] = {
        "key": "theme",
        "value": "dark",
        "session_id": "sess-a",
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    if json_timestamp is not None:
        payload["updated_at"] = json_timestamp
    with sqlite3.connect(store.db_path) as conn:
        if sql_timestamp is None:
            conn.execute("DROP TABLE preferences")
            conn.execute(
                "CREATE TABLE preferences ("
                "key TEXT PRIMARY KEY, record_json TEXT NOT NULL, updated_at TEXT)"
            )
        conn.execute(
            "INSERT INTO preferences(key, record_json, updated_at) VALUES (?, ?, ?)",
            ["theme", json.dumps(payload), sql_timestamp],
        )


class _OrderedConnection:
    def __init__(
        self,
        db_path: Path,
        *,
        first: bool,
        first_acquired: Event,
        second_requested: Event,
    ) -> None:
        self._connection = sqlite3.connect(db_path, timeout=5)
        self._connection.row_factory = sqlite3.Row
        self._first = first
        self._first_acquired = first_acquired
        self._second_requested = second_requested

    def __enter__(self) -> _OrderedConnection:
        self._connection.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return cast("Any", self._connection).__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] | list[object] = (),
    ) -> sqlite3.Cursor:
        if sql == "BEGIN IMMEDIATE":
            if self._first:
                cursor = self._connection.execute(sql, parameters)
                self._first_acquired.set()
                assert self._second_requested.wait(timeout=5)
                return cursor
            assert self._first_acquired.wait(timeout=5)
            self._second_requested.set()
        return self._connection.execute(sql, parameters)


def _run_ordered_preference_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    first_operation: tuple[str, str, str],
    second_operation: tuple[str, str, str],
) -> tuple[list[str], MemoryStore]:
    root = tmp_path / "memory"
    seed = MemoryStore(root=root)
    fixed_clock = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(memory_store_module, "_preference_clock_now", lambda: fixed_clock)
    seed.remember_preference("theme", "seed", session_id="sess-a")

    first_store = MemoryStore(root=root)
    second_store = MemoryStore(root=root)
    first_acquired = Event()
    second_requested = Event()

    def first_connect() -> sqlite3.Connection:
        return cast(
            "sqlite3.Connection",
            _OrderedConnection(
                first_store.db_path,
                first=True,
                first_acquired=first_acquired,
                second_requested=second_requested,
            ),
        )

    def second_connect() -> sqlite3.Connection:
        return cast(
            "sqlite3.Connection",
            _OrderedConnection(
                second_store.db_path,
                first=False,
                first_acquired=first_acquired,
                second_requested=second_requested,
            ),
        )

    monkeypatch.setattr(first_store, "_connect", first_connect)
    monkeypatch.setattr(second_store, "_connect", second_connect)
    start = Barrier(2)

    def mutate(store: MemoryStore, operation: tuple[str, str, str]) -> str:
        kind, owner, value = operation
        start.wait()
        try:
            if kind == "update":
                store.remember_preference("theme", value, session_id=owner)
                return "updated"
            assert kind == "delete"
            store.forget_preference("theme", session_id=owner)
            return "deleted"
        except PermissionError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(mutate, first_store, first_operation)
        second_future = executor.submit(mutate, second_store, second_operation)
        results = [first_future.result(), second_future.result()]
    return results, seed


def test_memory_store_round_trip_preference_and_trajectory(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")

    preference = store.remember_preference("theme", "dark", notes="ui")
    assert preference.key == "theme"
    assert store.list_all_preferences()[0].value == "dark"

    trajectory = store.save_trajectory(
        "leaderboard",
        {
            "grain": "player-season",
            "sql_hash": "abc123",
            "chosen_surfaces": ["table"],
            "tags": ["scoring"],
        },
        session_id="sess-1",
    )
    assert trajectory.archetype == "leaderboard"

    hits = store.search_trajectories("scoring", session_id="sess-1", limit=5)
    assert hits
    assert hits[0].sql_hash == "abc123"

    assert store.forget_preference("theme") is True
    assert store.list_all_preferences() == []


def test_scoped_preference_reads_return_only_exact_owner(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    store.remember_preference("metric-a", "points", session_id="sess-a")
    store.remember_preference("metric-b", "assists", session_id="sess-b")
    store.remember_preference("admin-default", "rebounds")

    assert [record.key for record in store.list_preferences(session_id=" sess-a ")] == ["metric-a"]
    assert [record.key for record in store.list_preferences(session_id="sess-b")] == ["metric-b"]
    assert len(store.list_all_preferences()) == 3


def test_scoped_trajectory_search_returns_only_exact_owner(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    store.save_trajectory("leaderboard", {"tags": ["scoring"]}, session_id="sess-a")
    store.save_trajectory("leaderboard", {"tags": ["scoring"]}, session_id="sess-b")
    store.save_trajectory("leaderboard", {"tags": ["scoring"]})

    own = store.search_trajectories("scoring", session_id="sess-a")

    assert len(own) == 1
    assert own[0].session_id == "sess-a"
    assert len(store.search_all_trajectories("scoring")) == 3


@pytest.mark.parametrize("record_kind", ["preference-json", "preference-owner", "trajectory"])
def test_scoped_reads_skip_malformed_records(tmp_path, record_kind) -> None:
    """One corrupt row must not disable listing/search for valid rows (W8.5 R1-M1)."""
    store = MemoryStore(root=tmp_path / "memory")
    with sqlite3.connect(store.db_path) as conn:
        if record_kind == "preference-json":
            conn.execute(
                "INSERT INTO preferences(key, record_json, updated_at) VALUES (?, ?, ?)",
                ["broken", '{"not_a_profile": true}', "2026-01-01T00:00:00+00:00"],
            )
        elif record_kind == "preference-owner":
            conn.execute(
                "INSERT INTO preferences(key, record_json, updated_at) VALUES (?, ?, ?)",
                [
                    "broken",
                    json.dumps({"key": "broken", "session_id": "   ", "value": "secret"}),
                    "2026-01-01T00:00:00+00:00",
                ],
            )
        else:
            conn.execute(
                "INSERT INTO trajectories(session_id, archetype, record_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    "sess-a",
                    "leaderboard",
                    json.dumps(
                        {
                            "archetype": "leaderboard",
                            "session_id": "sess-b",
                            "tags": ["scoring"],
                        }
                    ),
                    "2026-01-01T00:00:00+00:00",
                ],
            )

    if record_kind.startswith("preference"):
        store.remember_preference("metric-a", "points", session_id="sess-a")
        assert [record.key for record in store.list_preferences(session_id="sess-a")] == [
            "metric-a"
        ]
        # The admin listing skips unparseable rows only. A structurally valid
        # record with an unnormalizable owner (whitespace session id) still
        # appears there; only scoped reads reject it.
        expected_admin = (
            ["broken", "metric-a"] if record_kind == "preference-owner" else ["metric-a"]
        )
        assert [record.key for record in store.list_all_preferences()] == expected_admin
    else:
        store.save_trajectory("leaderboard", {"tags": ["scoring"]}, session_id="sess-a")
        own = store.search_trajectories("scoring", session_id="sess-a")
        assert len(own) == 1
        assert own[0].session_id == "sess-a"
        assert len(store.search_all_trajectories("scoring")) == 1


@pytest.mark.parametrize("session_id", ["", "   ", "\t"])
def test_scoped_reads_reject_empty_session_ids(tmp_path, session_id) -> None:
    store = MemoryStore(root=tmp_path / "memory")

    with pytest.raises(ValueError, match="session_id must be non-empty"):
        store.list_preferences(session_id=session_id)
    with pytest.raises(ValueError, match="session_id must be non-empty"):
        store.search_trajectories("scoring", session_id=session_id)


def test_forget_preference_enforces_session_ownership(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    store.remember_preference("theme", "dark", session_id="sess-a")

    with pytest.raises(PermissionError, match="preference is not owned"):
        store.forget_preference("theme", session_id="sess-b")
    assert store.list_preferences(session_id="sess-a")
    assert store.forget_preference("theme", session_id="sess-a") is True
    assert store.list_all_preferences() == []


def test_forget_preference_refuses_when_stored_session_is_null(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    store.remember_preference("theme", "dark", session_id=None)

    with pytest.raises(PermissionError, match="preference is not owned"):
        store.forget_preference("theme", session_id="sess-a")
    assert store.list_all_preferences()
    # Admin / unscoped caller may still delete.
    assert store.forget_preference("theme") is True
    assert store.list_all_preferences() == []


def test_remember_preference_enforces_same_owner_and_preserves_fields(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    created = store.remember_preference(
        "theme",
        "dark",
        session_id="sess-a",
        notes="ui",
    )

    updated = store.remember_preference("theme", "light", session_id="sess-a")
    assert updated.value == "light"
    assert updated.session_id == "sess-a"
    assert updated.notes == "ui"
    assert updated.created_at == created.created_at

    with pytest.raises(PermissionError, match="preference is not owned"):
        store.remember_preference("theme", "blue", session_id="sess-b")
    assert store.list_preferences(session_id="sess-a")[0].value == "light"

    admin = store.remember_preference("theme", "system")
    assert admin.session_id == "sess-a"
    assert admin.notes == "ui"
    assert admin.created_at == created.created_at


def test_preference_mutations_reject_empty_session_ids(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")

    with pytest.raises(ValueError, match="session_id must be non-empty"):
        store.remember_preference("theme", "dark", session_id="   ")
    with pytest.raises(ValueError, match="session_id must be non-empty"):
        store.forget_preference("theme", session_id="\t")


def test_scoped_mutations_fail_closed_on_malformed_record(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "INSERT INTO preferences(key, record_json, updated_at) VALUES (?, ?, ?)",
            ["theme", '{"not_a_profile": true}', "2026-01-01T00:00:00+00:00"],
        )

    with pytest.raises(PermissionError, match="preference is not owned"):
        store.remember_preference("theme", "dark", session_id="sess-a")
    with pytest.raises(PermissionError, match="preference is not owned"):
        store.forget_preference("theme", session_id="sess-a")
    with pytest.raises(PermissionError, match="preference is not owned"):
        store.forget_preference("theme")

    with sqlite3.connect(store.db_path) as conn:
        stored = conn.execute("SELECT record_json FROM preferences WHERE key = 'theme'").fetchone()
    assert stored == ('{"not_a_profile": true}',)


def test_competing_scoped_creates_choose_exactly_one_owner(tmp_path) -> None:
    root = tmp_path / "memory"
    MemoryStore(root=root)
    barrier = Barrier(2)

    def create(owner: str) -> tuple[str, str]:
        store = MemoryStore(root=root)
        barrier.wait()
        try:
            store.remember_preference("theme", owner, session_id=owner)
        except PermissionError:
            return ("denied", owner)
        return ("created", owner)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, ("sess-a", "sess-b")))

    assert sorted(status for status, _ in results) == ["created", "denied"]
    winner = next(owner for status, owner in results if status == "created")
    stored = MemoryStore(root=root).list_all_preferences()
    assert len(stored) == 1
    assert stored[0].session_id == winner
    assert stored[0].value == winner


def test_preference_timestamps_advance_and_match_when_clock_stalls_or_rewinds(
    tmp_path,
    monkeypatch,
) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    fixed = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
    ticks = iter((fixed, fixed, fixed - timedelta(days=1)))
    monkeypatch.setattr(memory_store_module, "_preference_clock_now", lambda: next(ticks))

    created = store.remember_preference("theme", "dark", session_id="sess-a", notes="ui")
    updated = store.remember_preference("theme", "light", session_id="sess-a")
    admin = store.remember_preference("theme", "system")

    created_at = datetime.fromisoformat(created.updated_at or "")
    updated_at = datetime.fromisoformat(updated.updated_at or "")
    admin_at = datetime.fromisoformat(admin.updated_at or "")
    assert updated_at == created_at + timedelta(microseconds=1)
    assert admin_at == updated_at + timedelta(microseconds=1)
    assert admin.created_at == created.created_at
    assert admin.session_id == "sess-a"
    assert admin.notes == "ui"
    payload, sql_timestamp = _stored_preference(store)
    assert payload["updated_at"] == sql_timestamp == admin.updated_at


@pytest.mark.parametrize(
    ("json_timestamp", "sql_timestamp"),
    [
        (None, "2026-01-01T00:00:00+00:00"),
        ("2026-01-01T00:00:00+00:00", None),
    ],
)
def test_preference_update_accepts_one_missing_legacy_timestamp_copy(
    tmp_path,
    monkeypatch,
    json_timestamp,
    sql_timestamp,
) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    _insert_preference_with_timestamps(
        store,
        json_timestamp=json_timestamp,
        sql_timestamp=sql_timestamp,
    )
    fixed = datetime(2025, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(memory_store_module, "_preference_clock_now", lambda: fixed)

    updated = store.remember_preference("theme", "light", session_id="sess-a")

    assert updated.updated_at == "2026-01-01T00:00:00.000001+00:00"
    payload, stored_sql_timestamp = _stored_preference(store)
    assert payload["updated_at"] == stored_sql_timestamp == updated.updated_at


def test_preference_update_heals_timestamp_copy_mismatch_from_the_later_copy(
    tmp_path,
    monkeypatch,
) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    _insert_preference_with_timestamps(
        store,
        json_timestamp="2026-01-01T01:00:00+01:00",
        sql_timestamp="2026-01-01T00:00:01+00:00",
    )
    monkeypatch.setattr(
        memory_store_module,
        "_preference_clock_now",
        lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    updated = store.remember_preference("theme", "light", session_id="sess-a")

    assert updated.updated_at == "2026-01-01T00:00:01.000001+00:00"
    payload, sql_timestamp = _stored_preference(store)
    assert payload["updated_at"] == sql_timestamp == updated.updated_at


@pytest.mark.parametrize(
    ("json_timestamp", "sql_timestamp"),
    [
        ("not-a-timestamp", "2026-01-01T00:00:00+00:00"),
        ("2026-01-01T00:00:00", "2026-01-01T00:00:00+00:00"),
        (None, None),
        (
            "9999-12-31T23:59:59.999999+00:00",
            "9999-12-31T23:59:59.999999+00:00",
        ),
    ],
)
def test_invalid_preference_timestamps_use_scoped_and_admin_error_mapping(
    tmp_path,
    monkeypatch,
    json_timestamp,
    sql_timestamp,
) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    _insert_preference_with_timestamps(
        store,
        json_timestamp=json_timestamp,
        sql_timestamp=sql_timestamp,
    )
    monkeypatch.setattr(
        memory_store_module,
        "_preference_clock_now",
        lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(PermissionError, match="preference is not owned"):
        store.remember_preference("theme", "scoped", session_id="sess-a")
    with pytest.raises(ValueError, match="stored preference record is invalid"):
        store.remember_preference("theme", "admin")


def test_foreign_preference_update_is_denied_before_clock_sampling(tmp_path, monkeypatch) -> None:
    store = MemoryStore(root=tmp_path / "memory")
    store.remember_preference("theme", "dark", session_id="sess-a")
    clock_sampled = False

    def unexpected_clock_sample() -> datetime:
        nonlocal clock_sampled
        clock_sampled = True
        raise AssertionError("foreign update sampled the wall clock")

    monkeypatch.setattr(memory_store_module, "_preference_clock_now", unexpected_clock_sample)

    with pytest.raises(PermissionError, match="preference is not owned"):
        store.remember_preference("theme", "light", session_id="sess-b")
    assert clock_sampled is False


def test_preference_clock_failure_uses_fixed_existing_and_new_record_mapping(
    tmp_path,
    monkeypatch,
) -> None:
    existing = MemoryStore(root=tmp_path / "existing")
    existing.remember_preference("theme", "dark", session_id="sess-a")

    def overflowing_clock() -> datetime:
        raise OverflowError("clock overflow")

    monkeypatch.setattr(memory_store_module, "_preference_clock_now", overflowing_clock)

    with pytest.raises(PermissionError, match="preference is not owned"):
        existing.remember_preference("theme", "scoped", session_id="sess-a")
    with pytest.raises(ValueError, match="stored preference record is invalid"):
        existing.remember_preference("theme", "admin")

    new_store = MemoryStore(root=tmp_path / "new")
    with pytest.raises(ValueError, match="stored preference record is invalid"):
        new_store.remember_preference("theme", "new", session_id="sess-a")


@pytest.mark.parametrize(
    ("first_operation", "second_operation", "expected_results", "expected_value"),
    [
        (
            ("update", "sess-a", "owner-first"),
            ("update", "sess-b", "foreign-second"),
            ["updated", "denied"],
            "owner-first",
        ),
        (
            ("update", "sess-b", "foreign-first"),
            ("update", "sess-a", "owner-second"),
            ["denied", "updated"],
            "owner-second",
        ),
        (
            ("update", "sess-a", "owner-first"),
            ("delete", "sess-b", "unused"),
            ["updated", "denied"],
            "owner-first",
        ),
        (
            ("delete", "sess-b", "unused"),
            ("update", "sess-a", "owner-second"),
            ["denied", "updated"],
            "owner-second",
        ),
    ],
)
def test_ordered_separate_connection_mutations_preserve_exact_ownership(
    tmp_path,
    monkeypatch,
    first_operation,
    second_operation,
    expected_results,
    expected_value,
) -> None:
    results, store = _run_ordered_preference_mutations(
        tmp_path,
        monkeypatch,
        first_operation=first_operation,
        second_operation=second_operation,
    )

    assert results == expected_results
    stored = store.list_preferences(session_id="sess-a")
    assert len(stored) == 1
    assert stored[0].session_id == "sess-a"
    assert stored[0].value == expected_value
    payload, sql_timestamp = _stored_preference(store)
    assert payload["updated_at"] == sql_timestamp


def test_same_owner_frozen_clock_race_advances_twice_without_busy_error(
    tmp_path,
    monkeypatch,
) -> None:
    results, store = _run_ordered_preference_mutations(
        tmp_path,
        monkeypatch,
        first_operation=("update", "sess-a", "first"),
        second_operation=("update", "sess-a", "second"),
    )

    assert results == ["updated", "updated"]
    stored = store.list_preferences(session_id="sess-a")[0]
    assert stored.value == "second"
    assert stored.updated_at == "2026-01-01T00:00:00.000002+00:00"
    payload, sql_timestamp = _stored_preference(store)
    assert payload["updated_at"] == sql_timestamp == stored.updated_at


def test_mcp_memory_caps_and_payload_limit(tmp_path) -> None:
    store = MemoryStore(root=tmp_path / "memory")

    with pytest.raises(ValueError, match="preference notes"):
        memory_mcp.remember_preference(
            store,
            "k",
            "v",
            session_id="s1",
            notes="x" * (memory_mcp._MAX_NOTES_CHARS + 1),
        )

    with pytest.raises(ValueError, match="byte memory mutation limit"):
        memory_mcp.remember_preference(
            store,
            "k",
            {"blob": "y" * (memory_mcp._MAX_MEMORY_PAYLOAD_BYTES + 1)},
            session_id="s1",
        )

    memory_mcp.remember_preference(store, "theme", "dark", session_id="s1", notes="ok")
    with pytest.raises(PermissionError, match="preference is not owned"):
        memory_mcp.remember_preference(store, "theme", "light", session_id="s2")
    with pytest.raises(PermissionError, match="preference is not owned"):
        memory_mcp.forget_memory(store, "theme", session_id="s2", confirm=True)
    assert memory_mcp.forget_memory(store, "theme", session_id="s1", confirm=True) is True
