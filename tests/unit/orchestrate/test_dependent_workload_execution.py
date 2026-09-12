"""Fail-closed public raw-request admission for dependent execution lanes."""

from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import ANY, AsyncMock, Mock

import pytest

from nbadb.contracts.field_fate_structure import (
    FieldFateStructureV1,
    compile_field_fate_structure,
)
from nbadb.orchestrate import dependent_workload_execution as subject
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.declared_bodyless_packet_store import (
    DeclaredBodylessPacketStore,
)
from nbadb.orchestrate.dependent_workload_contract import (
    DependentExecutableUnit,
    DependentWorkloadContractError,
    DependentWorkloadKind,
    canonical_sha256,
)
from nbadb.orchestrate.dependent_workload_planning import (
    DependentExecutionLane,
    DependentPhysicalCall,
)
from nbadb.orchestrate.orchestrator import ExtractionOutcome
from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
from nbadb.orchestrate.staging_map import get_by_endpoint
from nbadb.orchestrate.w2_source_call_preparation import (
    W2SourceCallPreparationRuntime,
)

from ._raw_request_test_support import raw_request_assurance_authority

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.orchestrate.raw_request_assurance import RawRequestAssuranceAuthorityV2

_SOURCE_SHA = "a" * 40
_LANE_ID = "dependent-player-vs-player-0123456789abcdef"


@lru_cache(maxsize=2)
def _assurance(*, source_sha: str = _SOURCE_SHA) -> RawRequestAssuranceAuthorityV2:
    return raw_request_assurance_authority(source_sha=source_sha)


def _plan_and_lane(
    *,
    calls: tuple[object, ...] = (object(),),
    provider_authority_sha256: str | None = None,
) -> tuple[Any, Any]:
    plan = SimpleNamespace(
        source_sha=_SOURCE_SHA,
        provider_authority_sha256=(
            provider_authority_sha256 or _assurance().provider_authority_sha256
        ),
        content_sha256="c" * 64,
        bundle_content_sha256="d" * 64,
    )
    lane = SimpleNamespace(
        lane_id=_LANE_ID,
        role="execute" if calls else "scope_accounting",
        endpoint_name="player_vs_player" if calls else "",
        calls=calls,
        content_sha256="e" * 64,
        semantic_unit_count=len(calls),
    )
    return plan, lane


def _execution(
    *,
    source_sha: str = _SOURCE_SHA,
    lane_id: str = _LANE_ID,
) -> RawRequestExecutionIdentityV1:
    return RawRequestExecutionIdentityV1(
        source_sha=source_sha,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id=lane_id,
    )


@lru_cache(maxsize=1)
def _field_fate() -> FieldFateStructureV1:
    return compile_field_fate_structure(upstream_root="")


def _runtime(
    tmp_path: Path,
    *,
    execution: RawRequestExecutionIdentityV1 | None = None,
) -> W2SourceCallPreparationRuntime:
    exact_execution = execution or _execution()
    body_root = tmp_path / "body"
    packet_root = tmp_path / "packet"
    body_root.mkdir(mode=0o700, parents=True)
    packet_root.mkdir(mode=0o700, parents=True)
    body_root.chmod(0o700)
    packet_root.chmod(0o700)
    return W2SourceCallPreparationRuntime(
        body_blob_store=BodyBlobStore(
            body_root,
            source_sha=exact_execution.source_sha,
            run_id=exact_execution.run_id,
            run_attempt=exact_execution.run_attempt,
            chain_id=exact_execution.chain_id,
            lane_id=exact_execution.lane_id,
        ),
        declared_bodyless_packet_store=DeclaredBodylessPacketStore(
            packet_root,
            source_sha=exact_execution.source_sha,
            run_id=exact_execution.run_id,
            run_attempt=exact_execution.run_attempt,
            chain_id=exact_execution.chain_id,
            lane_id=exact_execution.lane_id,
        ),
        field_fate=_field_fate(),
    )


def _execute_kwargs(tmp_path: Path) -> dict[str, Any]:
    return {
        "plan_path": tmp_path / "dependent-execution-plan.json",
        "lane_id": _LANE_ID,
        "expected_plan_sha256": "1" * 64,
        "expected_bundle_sha256": "2" * 64,
        "expected_lane_sha256": "3" * 64,
        "expected_foundation_transaction_sha256": "4" * 64,
        "expected_source_sha": _SOURCE_SHA,
        "expected_provider_authority_sha256": _assurance().provider_authority_sha256,
        "data_dir": tmp_path / "data",
        "timeout_seconds": 60,
    }


def _evidence_bound_lane(endpoint_name: str) -> DependentExecutionLane:
    if endpoint_name == "player_vs_player":
        kind = DependentWorkloadKind.PLAYER_MATCHUP
        parameters: tuple[tuple[str, int | str], ...] = (
            ("season", "2025-26"),
            ("season_type", "Regular Season"),
            ("player_id", 101),
            ("vs_player_id", 202),
        )
    elif endpoint_name == "team_vs_player":
        kind = DependentWorkloadKind.TEAM_PLAYER
        parameters = (
            ("season", "2025-26"),
            ("season_type", "Regular Season"),
            ("team_id", 1_610_612_737),
            ("vs_player_id", 202),
        )
    else:
        kind = DependentWorkloadKind.FIVE_V_FIVE
        parameters = (
            ("season", "2025-26"),
            ("season_type", "Regular Season"),
            ("team_id", 1_610_612_737),
            ("vs_team_id", 1_610_612_738),
            *((f"player_id{index}", 100 + index) for index in range(1, 6)),
            *((f"vs_player_id{index}", 200 + index) for index in range(1, 6)),
        )
    unit = DependentExecutableUnit(
        kind=kind,
        parameters=parameters,
        occurrence_sha256s=("f" * 64,),
    )
    routes = tuple(
        sorted(
            f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
            for entry in get_by_endpoint(endpoint_name)
        )
    )
    call = DependentPhysicalCall(
        endpoint_name=endpoint_name,
        kind=kind,
        unit_sha256=unit.identity_sha256,
        parameters=parameters,
        result_route_ids=routes,
    )
    scope_dispositions_sha256 = "e" * 64
    content = {
        "role": "execute",
        "endpoint_name": endpoint_name,
        "scope_dispositions_sha256": scope_dispositions_sha256,
        "calls": [call.to_payload()],
    }
    return DependentExecutionLane(
        lane_id=(f"dependent-{endpoint_name.replace('_', '-')}-{canonical_sha256(content)[:16]}"),
        role="execute",
        endpoint_name=endpoint_name,
        calls=(call,),
        scope_dispositions_sha256=scope_dispositions_sha256,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["execution", "assurance"])
async def test_call_bearing_lane_requires_both_authorities_before_runtime_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    plan, lane = _plan_and_lane()
    monkeypatch.setattr(
        subject,
        "load_authorized_dependent_lane",
        lambda **_kwargs: (plan, lane),
    )
    monkeypatch.setattr(
        subject,
        "raw_request_execution_identity_from_env",
        lambda: None if missing == "execution" else _execution(),
    )
    monkeypatch.setattr(
        subject,
        "raw_request_assurance_authority_from_env",
        lambda _execution_identity: None,
    )
    runtime_construction = Mock(side_effect=AssertionError("runtime constructed"))
    monkeypatch.setattr(subject, "_build_dependent_w2_runtime", runtime_construction)
    monkeypatch.setattr(subject, "get_settings", runtime_construction)

    expected = (
        "requires raw-request execution authority"
        if missing == "execution"
        else "requires independently validated raw-request assurance"
    )
    with pytest.raises(DependentWorkloadContractError, match=expected):
        await subject.execute_dependent_lane(**_execute_kwargs(tmp_path))

    runtime_construction.assert_not_called()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("execution_source", "execution source differs"),
        ("execution_lane", "execution lane differs"),
        ("assurance_source", "assurance source differs"),
        ("provider_authority", "assurance differs from the provider authority"),
    ],
)
def test_source_lane_and_provider_authority_mismatches_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected: str,
) -> None:
    execution = _execution(
        source_sha="f" * 40 if case == "execution_source" else _SOURCE_SHA,
        lane_id="dependent-foreign" if case == "execution_lane" else _LANE_ID,
    )
    assurance = _assurance(
        source_sha="f" * 40 if case == "assurance_source" else _SOURCE_SHA,
    )
    plan, lane = _plan_and_lane(
        provider_authority_sha256=(
            "f" * 64 if case == "provider_authority" else assurance.provider_authority_sha256
        )
    )
    monkeypatch.setattr(
        subject,
        "raw_request_execution_identity_from_env",
        lambda: execution,
    )
    monkeypatch.setattr(
        subject,
        "raw_request_assurance_authority_from_env",
        lambda _execution_identity: assurance,
    )

    with pytest.raises(DependentWorkloadContractError, match=expected):
        subject._load_dependent_raw_request_authorities(plan, lane)


def test_authority_loaders_require_exact_types_replay_and_sanitize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, lane = _plan_and_lane()

    class ExecutionSubclass(RawRequestExecutionIdentityV1):
        pass

    foreign_execution = ExecutionSubclass(**_execution().to_dict())
    monkeypatch.setattr(
        subject,
        "raw_request_execution_identity_from_env",
        lambda: foreign_execution,
    )
    assurance_loader = Mock(side_effect=AssertionError("assurance loader traversed"))
    monkeypatch.setattr(
        subject,
        "raw_request_assurance_authority_from_env",
        assurance_loader,
    )
    with pytest.raises(DependentWorkloadContractError) as foreign_failure:
        subject._load_dependent_raw_request_authorities(plan, lane)
    assert str(foreign_failure.value) == (
        "dependent provider lane raw-request execution authority is invalid"
    )
    assurance_loader.assert_not_called()

    monkeypatch.setattr(
        subject,
        "raw_request_execution_identity_from_env",
        Mock(side_effect=RuntimeError("hostile-secret-value")),
    )
    with pytest.raises(DependentWorkloadContractError) as hostile_failure:
        subject._load_dependent_raw_request_authorities(plan, lane)
    assert str(hostile_failure.value) == (
        "dependent provider lane raw-request execution authority is invalid"
    )
    assert "hostile-secret-value" not in str(hostile_failure.value)


def test_w2_runtime_factory_is_replayed_and_bound_to_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _execution()
    assurance = _assurance()
    runtime = _runtime(tmp_path, execution=execution)
    observed: list[tuple[object, object]] = []

    def _factory(exact_execution: object, exact_assurance: object) -> object:
        observed.append((exact_execution, exact_assurance))
        return runtime

    monkeypatch.setattr(
        subject,
        "w2_source_call_preparation_runtime_from_env",
        _factory,
    )

    replayed = subject._build_dependent_w2_runtime(execution, assurance)

    assert observed == [(execution, assurance)]
    assert type(replayed) is W2SourceCallPreparationRuntime
    assert replayed == runtime
    assert replayed is not runtime
    assert replayed.body_blob_store is runtime.body_blob_store
    assert replayed.declared_bodyless_packet_store is (runtime.declared_bodyless_packet_store)


def test_w2_runtime_factory_failure_and_foreign_binding_are_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _execution()
    assurance = _assurance()
    monkeypatch.setattr(
        subject,
        "w2_source_call_preparation_runtime_from_env",
        Mock(side_effect=RuntimeError("hostile-secret-value")),
    )
    with pytest.raises(DependentWorkloadContractError) as hostile_failure:
        subject._build_dependent_w2_runtime(execution, assurance)
    assert str(hostile_failure.value) == (
        "dependent provider lane W2 preparation runtime is invalid"
    )
    assert "hostile-secret-value" not in str(hostile_failure.value)

    foreign_execution = _execution(lane_id="dependent-foreign")
    foreign_runtime = _runtime(tmp_path / "foreign", execution=foreign_execution)
    monkeypatch.setattr(
        subject,
        "w2_source_call_preparation_runtime_from_env",
        lambda *_args: foreign_runtime,
    )
    with pytest.raises(
        DependentWorkloadContractError,
        match="W2 preparation runtime is invalid",
    ):
        subject._build_dependent_w2_runtime(execution, assurance)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint_name",
    [
        "player_vs_player",
        "team_vs_player",
        "team_and_players_vs",
        "team_and_players_vs_players",
    ],
)
async def test_evidence_bound_lane_preserves_one_exact_physical_call_without_fanout(
    endpoint_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _evidence_bound_lane(endpoint_name)
    call = lane.calls[0]
    parameters_sha256 = call.parameters_sha256
    route_ids = call.result_route_ids
    extraction_plan = lane.to_extraction_plan_items()
    closure = SimpleNamespace(
        authority=SimpleNamespace(
            logical_calls=(
                SimpleNamespace(
                    endpoint_name=endpoint_name,
                    logical_parameters_sha256=parameters_sha256,
                ),
            ),
            staging_route_aliases=tuple(
                SimpleNamespace(staging_route_id=route_id) for route_id in route_ids
            ),
        ),
        static_authorities=(),
        scope_gaps=(),
    )
    order: list[str] = []
    observed: dict[str, Any] = {}

    def _build_closure(_runner: object, plan: list[Any], **kwargs: Any) -> Any:
        order.append("closure")
        observed["closure_plan"] = plan
        observed["closure_kwargs"] = kwargs
        return closure

    admission_result = (object(),)
    parameter_binding = object()
    parameter_binding_sha256 = "9" * 64
    parameter_bindings = {
        (endpoint_name, parameters_sha256): (
            parameter_binding,
            parameter_binding_sha256,
        )
    }
    source_result: dict[str, object] = {
        "source_endpoint_name": endpoint_name,
        "source_params_json": subject.json.dumps(dict(call.parameters), sort_keys=True),
    }

    def _compile_bindings(**kwargs: object) -> object:
        order.append("compile-bindings")
        observed["compile_binding_kwargs"] = kwargs
        return parameter_bindings

    def _persist(_db: object, _frames: dict[str, object], **metadata: object) -> object:
        order.append("persist")
        observed["persist_metadata"] = metadata
        return admission_result

    async def _extract(_runner: object, **kwargs: Any) -> ExtractionOutcome:
        order.append("extract")
        observed["extract_kwargs"] = kwargs
        exact_plan = kwargs["plan"]
        assert len(exact_plan) == 1
        assert exact_plan[0].params == [dict(call.parameters)]
        assert {entry.endpoint_name for entry in exact_plan[0].entries} == {endpoint_name}
        callback = kwargs["persist_results"]
        assert (
            callback(
                {},
                pattern="player_team_season",
                chunk_index=0,
                source_results=[source_result],
            )
            is admission_result
        )
        return ExtractionOutcome(raw={})

    def _assure(**kwargs: object) -> None:
        order.append("assure")
        observed["assure_kwargs"] = kwargs

    orchestrator: Any = SimpleNamespace(
        _build_ordinary_request_closure=_build_closure,
        _extract_all_patterns=_extract,
        _persist_staging_to_duckdb=_persist,
        _materialize_staging_batches=Mock(),
    )
    db = SimpleNamespace(duckdb=SimpleNamespace(execute=Mock()))
    monkeypatch.setattr(subject, "_assure_dependent_w2_completion", _assure)
    monkeypatch.setattr(
        subject,
        "_compile_dependent_parameter_bindings",
        _compile_bindings,
    )

    outcome = await subject._execute_lane_with_runner(
        orchestrator=orchestrator,
        db=db,
        journal=object(),
        runner=object(),
        lane=lane,
    )

    assert outcome == ExtractionOutcome(raw={})
    assert order == ["closure", "compile-bindings", "extract", "persist", "assure"]
    assert observed["closure_plan"] == extraction_plan
    assert observed["closure_kwargs"]["run_mode"] == "backfill"
    assert observed["closure_kwargs"]["discovery_seed_requested"] is False
    assert observed["closure_kwargs"]["recurring_live_requested"] is False
    extract_kwargs = observed["extract_kwargs"]
    assert extract_kwargs["plan"] == extraction_plan
    assert extract_kwargs["request_closure_build"] is closure
    assert extract_kwargs["run_mode"] == subject.DEPENDENT_LANE_KIND
    assert observed["compile_binding_kwargs"] == {
        "orchestrator": orchestrator,
        "lane": lane,
        "request_closure": closure,
    }
    assert observed["persist_metadata"] == {
        "pattern": "player_team_season",
        "chunk_index": 0,
        "source_results": [source_result],
    }
    assert source_result["logical_provider_parameter_binding"] is parameter_binding
    assert (
        source_result["expected_logical_provider_parameter_binding_sha256"]
        == parameter_binding_sha256
    )
    assert observed["assure_kwargs"] == {
        "orchestrator": orchestrator,
        "db": db,
        "journal": ANY,
        "lane": lane,
        "outcome": outcome,
    }
    orchestrator._materialize_staging_batches.assert_called_once_with(
        db,
        endpoints=[endpoint_name],
    )
    db.duckdb.execute.assert_called_once_with("CHECKPOINT")


def test_post_foundation_alias_calls_remain_bound_to_exact_observed_intervals(
    tmp_path: Path,
) -> None:
    """A five-v-five lane may consume evidence, never invent opponent pairs."""

    from nbadb.orchestrate.dependent_workload_planning import (
        build_dependent_execution_plan,
    )

    from .test_dependent_workload_planning import _compile, _fixture

    bundle = _compile(_fixture(tmp_path))
    plan = build_dependent_execution_plan(bundle)
    occurrences = {
        occurrence.identity_sha256: occurrence for occurrence in bundle.five_v_five_occurrences
    }
    units = {
        unit.identity_sha256: unit
        for unit in bundle.executable_units
        if unit.kind is DependentWorkloadKind.FIVE_V_FIVE
    }
    calls = [call for call in plan.calls if call.kind is DependentWorkloadKind.FIVE_V_FIVE]

    assert len(occurrences) == 2
    assert len(units) == 2
    assert len(calls) == 4
    assert {call.unit_sha256 for call in calls} == set(units)
    assert {
        (dict(call.parameters)["team_id"], dict(call.parameters)["vs_team_id"]) for call in calls
    } == {(101, 202), (202, 101)}

    for unit_sha256, unit in units.items():
        assert len(unit.occurrence_sha256s) == 1
        occurrence = occurrences[unit.occurrence_sha256s[0]]
        assert (occurrence.interval_start, occurrence.interval_end) == ("0", "10")
        exact_parameters = (
            ("season", occurrence.scope.season),
            ("season_type", occurrence.scope.season_type),
            ("team_id", occurrence.team_id),
            ("vs_team_id", occurrence.vs_team_id),
            *(
                (f"player_id{index}", player_id)
                for index, player_id in enumerate(
                    occurrence.team_player_ids,
                    start=1,
                )
            ),
            *(
                (f"vs_player_id{index}", player_id)
                for index, player_id in enumerate(
                    occurrence.vs_player_ids,
                    start=1,
                )
            ),
        )
        assert unit.parameters == exact_parameters
        alias_calls = [call for call in calls if call.unit_sha256 == unit_sha256]
        assert {call.endpoint_name for call in alias_calls} == {
            "team_and_players_vs",
            "team_and_players_vs_players",
        }
        assert {call.parameters for call in alias_calls} == {exact_parameters}

        widened = tuple(
            (name, 303 if name == "vs_team_id" else value) for name, value in exact_parameters
        )
        with pytest.raises(
            DependentWorkloadContractError,
            match="parameters differ from its unit identity",
        ):
            DependentPhysicalCall(
                endpoint_name="team_and_players_vs",
                kind=DependentWorkloadKind.FIVE_V_FIVE,
                unit_sha256=unit_sha256,
                parameters=widened,
                result_route_ids=next(
                    call.result_route_ids
                    for call in alias_calls
                    if call.endpoint_name == "team_and_players_vs"
                ),
            )


@pytest.mark.parametrize(
    ("endpoint_name", "provider_endpoint_id"),
    [
        ("player_vs_player", "PlayerVsPlayer"),
        ("team_vs_player", "TeamVsPlayer"),
        ("team_and_players_vs", "TeamAndPlayersVsPlayers"),
        ("team_and_players_vs_players", "TeamAndPlayersVsPlayers"),
    ],
)
def test_dependent_parameter_binding_is_compiled_and_pinned_before_transport(
    endpoint_name: str,
    provider_endpoint_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from nba_api.stats.library.http import NBAStatsHTTP

    from nbadb.extract.registry import EndpointRegistry
    from nbadb.extract.stats.player_compare import (
        PlayerVsPlayerExtractor,
        TeamAndPlayersVsPlayersExtractor,
        TeamVsPlayerExtractor,
    )
    from nbadb.extract.stats.team_info import TeamAndPlayersVsExtractor
    from nbadb.orchestrate.request_closure_production import (
        build_ordinary_request_closure_authority,
    )

    monkeypatch.setattr(
        NBAStatsHTTP,
        "send_api_request",
        Mock(side_effect=AssertionError("parameter binding attempted network I/O")),
    )
    extractor_by_endpoint = {
        "player_vs_player": PlayerVsPlayerExtractor,
        "team_vs_player": TeamVsPlayerExtractor,
        "team_and_players_vs": TeamAndPlayersVsExtractor,
        "team_and_players_vs_players": TeamAndPlayersVsPlayersExtractor,
    }
    lane = _evidence_bound_lane(endpoint_name)
    registry = EndpointRegistry()
    registry.register(extractor_by_endpoint[endpoint_name])
    closure = build_ordinary_request_closure_authority(
        lane.to_extraction_plan_items(),
        registry=registry,
        run_mode="backfill",
        support_date=date(2026, 8, 31),
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )
    assert closure.scope_gaps == ()
    assert closure.authority is not None
    execution = _execution(lane_id=lane.lane_id)

    bindings = subject._compile_dependent_parameter_bindings(
        orchestrator=SimpleNamespace(_raw_request_execution_identity=execution),
        lane=lane,
        request_closure=closure,
    )

    call = lane.calls[0]
    binding, external_pin = bindings[(endpoint_name, call.parameters_sha256)]
    assert binding.binding_sha256 == external_pin
    assert binding.logical_endpoint_name == endpoint_name
    assert binding.logical_parameters_sha256 == call.parameters_sha256
    assert binding.result_route_ids == call.result_route_ids
    assert len(binding.provider_entries) == 1
    assert binding.provider_entries[0].endpoint_id == provider_endpoint_id
    assert binding.provider_entries[0].safe_parameters_sha256 != call.parameters_sha256


def test_dependent_parameter_binding_attachment_is_exact_and_has_no_fallback() -> None:
    lane = _evidence_bound_lane("team_and_players_vs_players")
    call = lane.calls[0]
    binding = object()
    external_pin = "8" * 64
    source_result: dict[str, object] = {
        "source_endpoint_name": call.endpoint_name,
        "source_params_json": subject.json.dumps(dict(call.parameters), sort_keys=True),
    }

    subject._attach_dependent_parameter_bindings(
        source_results=[source_result],
        bindings={(call.endpoint_name, call.parameters_sha256): (binding, external_pin)},  # type: ignore[dict-item]
    )

    assert source_result["logical_provider_parameter_binding"] is binding
    assert source_result["expected_logical_provider_parameter_binding_sha256"] == external_pin

    with pytest.raises(
        DependentWorkloadContractError,
        match="pre-populated parameter binding",
    ):
        subject._attach_dependent_parameter_bindings(
            source_results=[source_result],
            bindings={},
        )

    missing: dict[str, object] = {
        "source_endpoint_name": call.endpoint_name,
        "source_params_json": subject.json.dumps(dict(call.parameters), sort_keys=True),
    }
    with pytest.raises(
        DependentWorkloadContractError,
        match="lacks its precompiled parameter binding",
    ):
        subject._attach_dependent_parameter_bindings(
            source_results=[missing],
            bindings={},
        )


@pytest.mark.asyncio
async def test_call_lane_constructs_capture_enabled_orchestrator_with_exact_authorities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, lane = _plan_and_lane()
    execution = _execution()
    assurance = _assurance()
    w2_runtime = object()
    order: list[str] = []
    constructor_kwargs: dict[str, Any] = {}
    w2_arguments: list[tuple[object, object]] = []

    class _RunnerContext:
        async def __aenter__(self) -> object:
            order.append("runner")
            return object()

        async def __aexit__(self, *_args: object) -> None:
            order.append("runner-exit")

    class _FakeSettings:
        @classmethod
        def model_validate(cls, payload: dict[str, Any]) -> dict[str, Any]:
            return payload

    class _FakeOrchestrator:
        def __init__(self, **kwargs: Any) -> None:
            order.append("orchestrator")
            constructor_kwargs.update(kwargs)

        def _enable_ordinary_request_closure_capture(self) -> None:
            order.append("enable")

        def _init_db(self) -> tuple[object, object]:
            return object(), object()

        def _build_runner(self, _journal: object) -> _RunnerContext:
            return _RunnerContext()

        def close(self) -> None:
            order.append("close")

    async def _execute(**_kwargs: Any) -> ExtractionOutcome:
        order.append("execute")
        return ExtractionOutcome(raw={})

    def _build_w2(exact_execution: object, exact_assurance: object) -> object:
        order.append("w2")
        w2_arguments.append((exact_execution, exact_assurance))
        return w2_runtime

    def _settings() -> SimpleNamespace:
        order.append("settings")
        return SimpleNamespace(model_dump=lambda: {})

    monkeypatch.setattr(
        subject,
        "load_authorized_dependent_lane",
        lambda **_kwargs: (plan, lane),
    )
    monkeypatch.setattr(
        subject,
        "raw_request_execution_identity_from_env",
        lambda: execution,
    )
    monkeypatch.setattr(
        subject,
        "raw_request_assurance_authority_from_env",
        lambda _execution_identity: assurance,
    )
    monkeypatch.setattr(
        subject,
        "get_settings",
        _settings,
    )
    monkeypatch.setattr(subject, "_build_dependent_w2_runtime", _build_w2)
    monkeypatch.setattr(subject, "NbaDbSettings", _FakeSettings)
    monkeypatch.setattr(subject, "Orchestrator", _FakeOrchestrator)
    monkeypatch.setattr(subject, "_execute_lane_with_runner", _execute)

    summary = await subject.execute_dependent_lane(**_execute_kwargs(tmp_path))

    assert summary["status"] == "complete"
    replayed_execution, replayed_assurance = w2_arguments[0]
    assert replayed_execution == execution
    assert replayed_execution is not execution
    assert replayed_assurance == assurance
    assert replayed_assurance is not assurance
    assert constructor_kwargs["raw_request_execution_identity"] is replayed_execution
    assert constructor_kwargs["raw_request_assurance_authority"] is replayed_assurance
    assert constructor_kwargs["w2_preparation_runtime"] is w2_runtime
    assert order == [
        "w2",
        "settings",
        "orchestrator",
        "enable",
        "runner",
        "execute",
        "runner-exit",
        "close",
    ]


@pytest.mark.asyncio
async def test_scope_accounting_lane_is_deterministically_provider_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, lane = _plan_and_lane(calls=())
    db = SimpleNamespace(duckdb=SimpleNamespace(execute=Mock()))
    execution_loader = Mock(side_effect=AssertionError("execution authority loaded"))
    assurance_loader = Mock(side_effect=AssertionError("assurance authority loaded"))
    w2_builder = Mock(side_effect=AssertionError("W2 runtime constructed"))
    constructor_kwargs: dict[str, Any] = {}

    class _RunnerContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _FakeSettings:
        @classmethod
        def model_validate(cls, payload: dict[str, Any]) -> dict[str, Any]:
            return payload

    class _FakeOrchestrator:
        def __init__(self, **kwargs: Any) -> None:
            constructor_kwargs.update(kwargs)

        def _enable_ordinary_request_closure_capture(self) -> None:
            raise AssertionError("provider-free lane enabled capture")

        def _init_db(self) -> tuple[object, object]:
            return db, object()

        def _build_runner(self, _journal: object) -> _RunnerContext:
            return _RunnerContext()

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        subject,
        "load_authorized_dependent_lane",
        lambda **_kwargs: (plan, lane),
    )
    monkeypatch.setattr(
        subject,
        "raw_request_execution_identity_from_env",
        execution_loader,
    )
    monkeypatch.setattr(
        subject,
        "raw_request_assurance_authority_from_env",
        assurance_loader,
    )
    monkeypatch.setattr(subject, "_build_dependent_w2_runtime", w2_builder)
    monkeypatch.setattr(
        subject,
        "get_settings",
        lambda: SimpleNamespace(model_dump=lambda: {}),
    )
    monkeypatch.setattr(subject, "NbaDbSettings", _FakeSettings)
    monkeypatch.setattr(subject, "Orchestrator", _FakeOrchestrator)

    summary = await subject.execute_dependent_lane(**_execute_kwargs(tmp_path))

    assert summary["status"] == "complete"
    assert summary["progress"] == {
        "planned_physical_calls": 0,
        "planned_semantic_units": 0,
    }
    assert constructor_kwargs["raw_request_execution_identity"] is None
    assert constructor_kwargs["raw_request_assurance_authority"] is None
    assert constructor_kwargs["w2_preparation_runtime"] is None
    execution_loader.assert_not_called()
    assurance_loader.assert_not_called()
    w2_builder.assert_not_called()
    db.duckdb.execute.assert_called_once_with("CHECKPOINT")


@pytest.mark.asyncio
async def test_incomplete_lane_closure_cannot_silently_opt_out() -> None:
    call = SimpleNamespace(
        endpoint_name="player_vs_player",
        parameters_sha256="1" * 64,
        result_route_ids=("player_vs_player:stg_player_vs_player:0",),
    )
    lane = SimpleNamespace(
        calls=(call,),
        endpoint_name="player_vs_player",
        to_extraction_plan_items=lambda: [SimpleNamespace(label="exact-dependent-plan")],
    )
    extract = AsyncMock(return_value=ExtractionOutcome(raw={}))
    orchestrator: Any = SimpleNamespace(
        _build_ordinary_request_closure=lambda *_args, **_kwargs: SimpleNamespace(
            authority=None,
            static_authorities=(),
            scope_gaps=(SimpleNamespace(reason_code="unbound"),),
        ),
        _extract_all_patterns=extract,
        _persist_staging_to_duckdb=Mock(),
        _materialize_staging_batches=Mock(),
    )

    with pytest.raises(
        DependentWorkloadContractError,
        match="request closure is incomplete",
    ):
        await subject._execute_lane_with_runner(
            orchestrator=orchestrator,
            db=SimpleNamespace(duckdb=SimpleNamespace(execute=Mock())),
            journal=object(),
            runner=object(),
            lane=lane,
        )

    extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_incomplete_provider_outcome_cannot_materialize_or_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _evidence_bound_lane("player_vs_player")
    closure = SimpleNamespace(
        authority=SimpleNamespace(
            logical_calls=tuple(
                SimpleNamespace(
                    endpoint_name=call.endpoint_name,
                    logical_parameters_sha256=call.parameters_sha256,
                )
                for call in lane.calls
            ),
            staging_route_aliases=tuple(
                SimpleNamespace(staging_route_id=route_id)
                for call in lane.calls
                for route_id in call.result_route_ids
            ),
        ),
        static_authorities=(),
        scope_gaps=(),
    )
    materialize = Mock(side_effect=AssertionError("incomplete lane materialized"))
    checkpoint = Mock(side_effect=AssertionError("incomplete lane checkpointed"))
    orchestrator: Any = SimpleNamespace(
        _build_ordinary_request_closure=lambda *_args, **_kwargs: closure,
        _extract_all_patterns=AsyncMock(
            return_value=ExtractionOutcome(
                raw={},
                pattern_failures=1,
                failed_calls=1,
                errors=["test-only incomplete"],
            )
        ),
        _persist_staging_to_duckdb=Mock(),
        _materialize_staging_batches=materialize,
    )
    monkeypatch.setattr(
        subject,
        "_compile_dependent_parameter_bindings",
        lambda **_kwargs: {},
    )

    with pytest.raises(
        DependentWorkloadContractError,
        match="extraction closure is incomplete",
    ):
        await subject._execute_lane_with_runner(
            orchestrator=orchestrator,
            db=SimpleNamespace(duckdb=SimpleNamespace(execute=checkpoint)),
            journal=object(),
            runner=object(),
            lane=lane,
        )

    materialize.assert_not_called()
    checkpoint.assert_not_called()


def _closed_dependent_authorities(
    lane: DependentExecutionLane,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    call_count = len(lane.calls)
    inventory = SimpleNamespace(
        authority=object(),
        observations=tuple(object() for _ in lane.calls),
        incomplete=(),
        scope_gaps=(),
        green=True,
    )
    manifest = SimpleNamespace(
        is_complete=True,
        coverage_complete=True,
        terminal_sealed=True,
        expected_request_count=call_count,
        completed_request_count=call_count,
        unresolved_request_count=0,
        receipt_count=call_count,
    )
    return inventory, manifest


def test_terminal_dependent_lane_replays_journal_and_database_w2_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = _evidence_bound_lane("team_and_players_vs_players")
    inventory, manifest = _closed_dependent_authorities(lane)
    expected_keys = [
        (
            call.endpoint_name,
            subject.json.dumps(dict(call.parameters), sort_keys=True),
        )
        for call in lane.calls
    ]
    journal = SimpleNamespace(
        was_extracted_batch=Mock(return_value=set(expected_keys)),
    )
    orchestrator = SimpleNamespace(
        request_closure_inventory=inventory,
        raw_request_authority_manifest=manifest,
    )
    database_receipt = SimpleNamespace(
        w2_required_logical_call_count=len(lane.calls),
        raw_authority_v2_bundle_count=len(lane.calls),
        w2_publication_receipt_count=len(lane.calls),
    )
    database_verifier = Mock(return_value=database_receipt)
    monkeypatch.setattr(subject, "_verify_dependent_w2_database", database_verifier)
    db = SimpleNamespace(duckdb=object())

    subject._assure_dependent_w2_completion(
        orchestrator=orchestrator,
        db=db,
        journal=journal,
        lane=lane,
        outcome=ExtractionOutcome(raw={}),
    )

    journal.was_extracted_batch.assert_called_once_with(
        expected_keys,
        require_receipt=True,
        require_w2_operation=True,
    )
    database_verifier.assert_called_once_with(db)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("inventory", "request closure did not reach terminal green"),
        ("manifest", "Raw Authority V2 closure is incomplete"),
        ("journal", "lacks one durable W2 journal admission"),
        ("database", "database call inventory differs"),
    ],
)
def test_dependent_w2_postcondition_rejects_each_incomplete_authority_layer(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected: str,
) -> None:
    lane = _evidence_bound_lane("team_and_players_vs")
    inventory, manifest = _closed_dependent_authorities(lane)
    if mutation == "inventory":
        inventory.green = False
    if mutation == "manifest":
        manifest.terminal_sealed = False
    expected_keys = {
        (
            call.endpoint_name,
            subject.json.dumps(dict(call.parameters), sort_keys=True),
        )
        for call in lane.calls
    }
    journal_rows = set() if mutation == "journal" else expected_keys
    receipt_count = 0 if mutation == "database" else len(lane.calls)
    monkeypatch.setattr(
        subject,
        "_verify_dependent_w2_database",
        lambda _db: SimpleNamespace(
            w2_required_logical_call_count=receipt_count,
            raw_authority_v2_bundle_count=receipt_count,
            w2_publication_receipt_count=receipt_count,
        ),
    )

    with pytest.raises(DependentWorkloadContractError, match=expected):
        subject._assure_dependent_w2_completion(
            orchestrator=SimpleNamespace(
                request_closure_inventory=inventory,
                raw_request_authority_manifest=manifest,
            ),
            db=SimpleNamespace(duckdb=object()),
            journal=SimpleNamespace(
                was_extracted_batch=Mock(return_value=journal_rows),
            ),
            lane=lane,
            outcome=ExtractionOutcome(raw={}),
        )
