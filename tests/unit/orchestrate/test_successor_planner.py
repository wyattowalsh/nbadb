from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from nbadb.orchestrate.successor_planner import (
    ConcreteSuccessorPlanningError,
    ConcreteSuccessorPlanningExecutor,
    PlanningCallExecution,
    deterministic_planning_generation_id,
)
from nbadb.orchestrate.successor_planning_driver import RequestDrivenSuccessorPlanningDriver
from nbadb.orchestrate.successor_planning_request_builder import (
    build_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_store import (
    PlanningArtifactSource,
    PlanningDatabaseSource,
    PlanningStoreBudget,
    PlanningWaveAdmission,
    SuccessorPlanningStore,
)
from nbadb.orchestrate.successor_update_contract import SuccessorUpdateMode

if TYPE_CHECKING:
    from pathlib import Path


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _request(
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
    *,
    as_of_utc: str = "2026-08-13T00:00:00Z",
):
    return build_successor_planning_request(
        baseline_identity_sha256=_digest("baseline"),
        mode=mode,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc=as_of_utc,
        workflow_run_id=731,
        workflow_run_attempt=4,
    )


def _budget() -> PlanningStoreBudget:
    return PlanningStoreBudget(
        generation_max_bytes=16 * 1024 * 1024,
        artifact_max_bytes=4 * 1024 * 1024,
        control_max_bytes=2 * 1024 * 1024,
        minimum_free_bytes=1,
        monotonic_deadline_seconds=1_000.0,
        minimum_deadline_headroom_seconds=100.0,
    )


class _NeverDriver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def derive_wave(self, *args: object) -> None:
        self.calls.append("derive_wave")
        raise AssertionError("request admission must precede driver derivation")

    async def execute_call(self, *args: object) -> None:
        self.calls.append("execute_call")
        raise AssertionError("request admission must precede driver execution")

    async def seal_wave(self, *args: object) -> None:
        self.calls.append("seal_wave")
        raise AssertionError("request admission must precede driver sealing")

    async def derive_manifest(self, *args: object) -> None:
        self.calls.append("derive_manifest")
        raise AssertionError("request admission must precede manifest derivation")


class _NeverResolver:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, **kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("request admission must precede resolver verification")


def _executor(
    tmp_path: Path,
) -> tuple[
    ConcreteSuccessorPlanningExecutor,
    SuccessorPlanningStore,
    _NeverDriver,
    _NeverResolver,
]:
    public = tmp_path / "public"
    public.mkdir()
    store = SuccessorPlanningStore(
        (tmp_path / "private-store").resolve(),
        public_roots=(public.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    work = tmp_path / "planning-work"
    work.mkdir(mode=0o700)
    work.chmod(0o700)
    work_stat = work.stat()
    driver = _NeverDriver()
    resolver = _NeverResolver()
    executor = ConcreteSuccessorPlanningExecutor(
        store,
        driver,
        resolver,
        _budget,
        planning_driver_database_max_bytes=4 * 1024 * 1024,
        planning_work_root=work.resolve(),
        expected_planning_work_root_identity=(work_stat.st_dev, work_stat.st_ino),
    )
    return executor, store, driver, resolver


def _narrowed_request():
    request = _request()
    return replace(
        request,
        requested_planning_scopes=request.requested_planning_scopes[:-1],
    )


def test_deterministic_generation_identity_uses_v2_domain_and_prefix() -> None:
    daily = _request()
    monthly = _request(SuccessorUpdateMode.MONTHLY)
    later = _request(as_of_utc="2026-08-14T00:00:00Z")

    first = deterministic_planning_generation_id(daily)

    assert first == deterministic_planning_generation_id(daily)
    assert first.startswith("successor-planning-v2-")
    assert first != deterministic_planning_generation_id(monthly)
    assert first != deterministic_planning_generation_id(later)
    assert "successor-planning-v1-" not in first


def test_deterministic_generation_identity_rejects_non_request() -> None:
    with pytest.raises(ConcreteSuccessorPlanningError, match="SuccessorPlanningRequest"):
        deterministic_planning_generation_id(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, 0, -1, 1 << 63])
def test_executor_requires_positive_signed63_driver_database_cap(
    tmp_path: Path,
    value: object,
) -> None:
    _executor_instance, store, driver, resolver = _executor(tmp_path)

    with pytest.raises(ConcreteSuccessorPlanningError, match="signed-63-bit"):
        work = tmp_path / "planning-work"
        work_stat = work.stat()
        ConcreteSuccessorPlanningExecutor(
            store,
            driver,
            resolver,
            _budget,
            planning_driver_database_max_bytes=value,  # type: ignore[arg-type]
            planning_work_root=work.resolve(),
            expected_planning_work_root_identity=(work_stat.st_dev, work_stat.st_ino),
        )


async def test_oversized_driver_output_fails_before_store_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _executor_instance, store, driver, resolver = _executor(tmp_path)
    executor = ConcreteSuccessorPlanningExecutor(
        store,
        driver,
        resolver,
        _budget,
        planning_driver_database_max_bytes=1,
        planning_work_root=(tmp_path / "planning-work").resolve(),
        expected_planning_work_root_identity=(
            (tmp_path / "planning-work").stat().st_dev,
            (tmp_path / "planning-work").stat().st_ino,
        ),
    )
    request = _request()
    scopes = tuple(
        sorted(request.requested_planning_scopes, key=lambda scope: scope.identity_sha256)
    )
    admission = PlanningWaveAdmission(
        wave_index=0,
        parent_wave_identity_sha256=None,
        requested_route_scopes=scopes,
        sealed_dispatches=RequestDrivenSuccessorPlanningDriver._build_wave_0_dispatches(  # noqa: SLF001
            scopes
        ),
    )
    source = tmp_path / "oversized.duckdb"
    source.write_bytes(b"xx")
    source.chmod(0o600)
    database = PlanningDatabaseSource(
        artifact=PlanningArtifactSource(
            path=source.resolve(),
            sha256=hashlib.sha256(b"xx").hexdigest(),
            byte_count=2,
        ),
        schema_sha256=_digest("schema"),
    )
    result = object.__new__(PlanningCallExecution)
    object.__setattr__(result, "members", ())
    object.__setattr__(result, "planning_database", database)
    executed = 0
    committed = 0

    async def derive_wave(*_args: object) -> PlanningWaveAdmission:
        return admission

    async def execute_call(*_args: object) -> PlanningCallExecution:
        nonlocal executed
        executed += 1
        return result

    @contextmanager
    def fake_context(*_args: object):
        yield object()

    def commit_call(*_args: object, **_kwargs: object) -> None:
        nonlocal committed
        committed += 1
        raise AssertionError("oversized driver output must not reach store commit")

    monkeypatch.setattr(driver, "derive_wave", derive_wave)
    monkeypatch.setattr(driver, "execute_call", execute_call)
    monkeypatch.setattr(executor, "_driver_context", fake_context)
    monkeypatch.setattr(store, "commit_call", commit_call)

    with pytest.raises(ConcreteSuccessorPlanningError, match="output database exceeds"):
        await executor(request)

    assert executed == 1
    assert committed == 0
    snapshot = store.load_and_verify(
        request,
        deterministic_planning_generation_id(request),
        budget=_budget(),
    )
    assert snapshot.active_wave == admission
    assert snapshot.committed_calls == ()


async def test_call_rejects_narrowed_request_before_store_driver_or_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, store, driver, resolver = _executor(tmp_path)
    begin_calls = 0

    def begin_generation(*args: object, **kwargs: object) -> Any:
        nonlocal begin_calls
        begin_calls += 1
        raise AssertionError("request admission must precede durable generation creation")

    monkeypatch.setattr(store, "begin_generation", begin_generation)

    with pytest.raises(
        ConcreteSuccessorPlanningError,
        match="current exact builder authority",
    ):
        await executor(_narrowed_request())

    assert begin_calls == 0
    assert driver.calls == []
    assert resolver.calls == 0
    assert not store.generations_root.exists()


async def test_planning_work_root_identity_is_rechecked_before_context_creation(
    tmp_path: Path,
) -> None:
    executor, _store, driver, resolver = _executor(tmp_path)
    work = tmp_path / "planning-work"
    displaced = tmp_path / "planning-work-original"
    work.rename(displaced)
    work.mkdir(mode=0o700)
    work.chmod(0o700)

    with pytest.raises(ConcreteSuccessorPlanningError, match="changed identity"):
        await executor(_request())

    assert driver.calls == []
    assert resolver.calls == 0
    assert tuple(work.iterdir()) == ()


def test_verify_rejects_narrowed_request_before_store_driver_or_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, store, driver, resolver = _executor(tmp_path)
    load_calls = 0

    def load_and_verify(*args: object, **kwargs: object) -> Any:
        nonlocal load_calls
        load_calls += 1
        raise AssertionError("request admission must precede sealed-store verification")

    monkeypatch.setattr(store, "load_and_verify", load_and_verify)

    with pytest.raises(
        ConcreteSuccessorPlanningError,
        match="current exact builder authority",
    ):
        executor.verify(_narrowed_request(), object())  # type: ignore[arg-type]

    assert load_calls == 0
    assert driver.calls == []
    assert resolver.calls == 0
    assert not store.generations_root.exists()
