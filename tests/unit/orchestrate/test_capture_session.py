from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest
from nba_api.stats.endpoints import LeagueGameLog

from nbadb.core.errors import ExtractionError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_endpoint_contract,
)
from nbadb.extract.base import BaseExtractor
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    BronzeCaptureStore,
    BronzeLimits,
    LogicalCallReceiptBinding,
    ParserInputCapacityError,
    ParserInputContext,
    ResultSetReceipt,
    canonical_parameters_sha256,
    parent_occurrence_states_digest,
)
from nbadb.orchestrate.capture_session import (
    CAPTURE_SESSION_PLACEHOLDER_ENDPOINT_CONTRACT_SHA256,
    CaptureRunScope,
    CaptureSessionContractError,
    CaptureSessionState,
    CaptureSessionTransitionError,
    IncompleteCaptureIdentity,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
    planning_wave_lane_id,
    require_planning_wave_ownership,
)

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.extract.nba_api_adapter import NbaApiCaptureContract

_SOURCE_SHA = "a" * 40


def _limits() -> BronzeLimits:
    return BronzeLimits(
        max_response_bytes=100_000,
        max_generation_stored_bytes=2_000_000,
        minimum_free_bytes=1,
        max_receipt_bytes=100_000,
        max_receipt_count=1_000,
        max_checkpoint_bytes=1_000_000,
        minimum_deadline_headroom_seconds=10.0,
    )


def _scope(
    *,
    lane_id: str = "lane-001",
    workflow_run_id: int = 123,
    workflow_run_attempt: int = 1,
) -> CaptureRunScope:
    return CaptureRunScope(
        semantic_source_sha=_SOURCE_SHA,
        chain_id="full-chain-001",
        lane_id=lane_id,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
    )


def _session(
    tmp_path: Path,
    *,
    name: str = "generation",
    scope: CaptureRunScope | None = None,
    limits: BronzeLimits | None = None,
) -> PrivateCaptureSession:
    return PrivateCaptureSession(
        tmp_path / "private" / name,
        limits=limits or _limits(),
        public_roots=(tmp_path / "data" / "nbadb",),
        scope=scope or _scope(),
    )


def _admit(session: PrivateCaptureSession) -> None:
    session.admit(
        estimated_checkpoint_bytes=50_000,
        monotonic_now_seconds=100.0,
        monotonic_deadline_seconds=200.0,
    )


def _tree_snapshot(root: Path) -> dict[str, tuple[bytes, int, int]]:
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(),
            path.stat().st_mode & 0o777,
            path.stat().st_mtime_ns,
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _complete_logical_call(
    session: PrivateCaptureSession,
    *,
    endpoint_name: str = "league_game_log",
    params: dict[str, object] | None = None,
    context_override: ParserInputContext | None = None,
) -> tuple[LogicalCallReceiptBinding, NbaApiCaptureContract]:
    logical_params = params or {"season": "2025-26", "season_type": "Regular Season"}
    contract = session.contract_for(endpoint_name, logical_params)
    contract = contract.for_endpoint_contract("b" * 64)
    if context_override is not None:
        contract = replace(contract, context=context_override)

    request_context = contract.begin_request()
    captured = contract.sink.store_parser_input(
        '{"resultSets":[{"name":"LeagueGameLog","headers":[],"rowSet":[]}]}',
        representation=PARSER_INPUT_REPRESENTATION,
    )
    attempt_receipt = contract.sink.record_response_attempt(
        context=request_context,
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="LeagueGameLog",
        endpoint_slug="leaguegamelog",
        parameters=logical_params,
        provider_authority_sha256=contract.provider_authority_sha256,
        contract_sha256=contract.endpoint_contract_sha256,
        status_code=200,
        captured=captured,
        outcome="success_empty",
        failure_class=None,
        root_exception_class=None,
        result_sets=(
            ResultSetReceipt(
                name="LeagueGameLog",
                provider_index=0,
                canonical_index=0,
                headers_sha256="c" * 64,
                row_count=0,
                json_path=None,
                container_kind="nba_api_result_set",
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
                observed_field_orders_sha256="d" * 64,
                normalized_output_sha256="e" * 64,
            ),
        ),
    )
    contract.record_receipt(request_context, attempt_receipt, successful=True)
    snapshot = contract.receipt_snapshot()
    route = f"{endpoint_name}:stg_{endpoint_name}:0"
    logical_root = contract.sink.record_logical_call(
        context=contract.context,
        logical_endpoint_id=endpoint_name,
        logical_parameters=logical_params,
        provider_authority_sha256=contract.provider_authority_sha256,
        response_receipt_sha256s=snapshot.receipt_sha256s,
        successful_response_ordinals=snapshot.successful_response_ordinals,
        result_route_ids=(route,),
    )
    return (
        LogicalCallReceiptBinding(
            logical_call_receipt_sha256=logical_root,
            endpoint_name=endpoint_name,
            logical_parameters_sha256=canonical_parameters_sha256(logical_params),
            provider_authority_sha256=contract.provider_authority_sha256,
            result_route_ids=(route,),
        ),
        contract,
    )


def test_planning_wave_ownership_is_disjoint_from_update_execution_lane() -> None:
    assert planning_wave_lane_id(0) == "planning-wave-0"
    assert planning_wave_lane_id(1) == "planning-wave-1"
    with pytest.raises(CaptureSessionContractError, match="exactly 0 or 1"):
        planning_wave_lane_id(2)

    require_planning_wave_ownership(
        planning_generation_id="successor-planning-v2-test",
        wave_index=0,
        chain_id="successor-planning-v2-test",
        lane_id="planning-wave-0",
    )
    with pytest.raises(CaptureSessionContractError, match="not exclusively owned"):
        require_planning_wave_ownership(
            planning_generation_id="successor-planning-v2-test",
            wave_index=0,
            chain_id="full-chain-001",
            lane_id="planning-wave-0",
        )
    with pytest.raises(CaptureSessionContractError, match="not exclusively owned"):
        require_planning_wave_ownership(
            planning_generation_id="successor-planning-v2-test",
            wave_index=0,
            chain_id="successor-planning-v2-test",
            lane_id="b" * 64,
        )


def test_successful_call_without_receipt_binding_remains_unbound_orphan(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, name="unbound-success")
    _admit(session)
    binding, _contract = _complete_logical_call(session)

    identity = session.seal()

    assert identity.done_call_count == 0
    assert identity.done_call_receipt_sha256s == ()
    assert identity.orphan_call_count == 1
    assert binding.logical_call_receipt_sha256 not in identity.done_call_receipt_sha256s
    session.close()


def test_run_scope_is_path_free_and_requires_positive_workflow_identity() -> None:
    scope = _scope()
    assert scope.to_dict() == {
        "semantic_source_sha": _SOURCE_SHA,
        "chain_id": "full-chain-001",
        "lane_id": "lane-001",
        "workflow_run_id": 123,
        "workflow_run_attempt": 1,
    }
    assert len(scope.identity_sha256) == 64

    with pytest.raises(CaptureSessionContractError, match="positive integer"):
        _scope(workflow_run_attempt=0)
    with pytest.raises(CaptureSessionContractError, match="safe token"):
        _scope(lane_id="../../foreign")


def test_session_requires_explicit_evidence_backed_admission_limits(tmp_path: Path) -> None:
    root = tmp_path / "private" / "unconfigured"
    limits = BronzeLimits(
        max_response_bytes=100,
        max_generation_stored_bytes=10_000,
        minimum_free_bytes=1,
    )
    with pytest.raises(CaptureSessionContractError, match="limits are not configured"):
        PrivateCaptureSession(
            root,
            limits=limits,
            public_roots=(tmp_path / "data",),
            scope=_scope(),
        )
    assert not root.exists()


def test_authorized_base_session_rejects_foreign_identity_before_child_creation(
    tmp_path: Path,
) -> None:
    base = (tmp_path / "authorized-capture").resolve()
    base.mkdir(mode=0o700, parents=True)
    observed = base.stat()

    with pytest.raises(ExtractionError, match="parent root authority"):
        PrivateCaptureSession.create_under_authorized_base(
            base,
            "generation",
            expected_base_identity=(observed.st_dev, observed.st_ino + 1),
            limits=_limits(),
            public_roots=((tmp_path / "data" / "nbadb").resolve(),),
            scope=_scope(),
        )

    assert list(base.iterdir()) == []


def test_authorized_base_session_keeps_all_writes_on_pinned_generation(
    tmp_path: Path,
) -> None:
    base = (tmp_path / "authorized-capture").resolve()
    base.mkdir(mode=0o700, parents=True)
    observed = base.stat()
    generation = base / "generation"
    session = PrivateCaptureSession.create_under_authorized_base(
        base,
        generation.name,
        expected_base_identity=(observed.st_dev, observed.st_ino),
        limits=_limits(),
        public_roots=((tmp_path / "data" / "nbadb").resolve(),),
        scope=_scope(),
    )
    retained = generation.with_name("generation-retained")
    generation.rename(retained)
    generation.mkdir(mode=0o700)

    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)
    identity = session.seal()
    session.close()

    assert identity.done_call_count == 1
    assert list(generation.iterdir()) == []
    assert (retained / "manifest.json").is_file()


def test_admission_uses_exact_caller_measurements_before_contract_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: list[dict[str, int | float]] = []
    original = BronzeCaptureStore.admit_capture

    def spy(self: BronzeCaptureStore, **kwargs: int | float) -> None:
        observed.append(dict(kwargs))
        original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(BronzeCaptureStore, "admit_capture", spy)
    session = _session(tmp_path)
    with pytest.raises(CaptureSessionTransitionError, match="expected admitted"):
        session.contract_for("league_game_log", {"season": "2025-26"})

    session.admit(
        estimated_checkpoint_bytes=50_000,
        monotonic_now_seconds=100.0,
        monotonic_deadline_seconds=200.0,
    )
    assert observed == [
        {
            "estimated_checkpoint_bytes": 50_000,
            "monotonic_now_seconds": 100.0,
            "monotonic_deadline_seconds": 200.0,
        }
    ]
    assert session.state is CaptureSessionState.ADMITTED
    session.close()


def test_failed_admission_does_not_authorize_capture(tmp_path: Path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ParserInputCapacityError, match="checkpoint byte limit"):
        session.admit(
            estimated_checkpoint_bytes=1_000_001,
            monotonic_now_seconds=100.0,
            monotonic_deadline_seconds=200.0,
        )
    assert session.state is CaptureSessionState.CREATED
    with pytest.raises(CaptureSessionTransitionError, match="expected admitted"):
        session.contract_for("league_game_log", {})
    session.close()


def test_unsealed_restore_probe_returns_none_then_allows_normal_admission(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    root = tmp_path / "private" / "generation"
    before = _tree_snapshot(root)

    assert session.restore_sealed_identity_if_present() is None
    assert session.restore_sealed_identity_if_present() is None
    assert session.state is CaptureSessionState.CREATED
    assert session.generation_identity is None
    assert session._completed_bindings == {}
    assert _tree_snapshot(root) == before

    _admit(session)
    assert session.state is CaptureSessionState.ADMITTED
    with pytest.raises(CaptureSessionTransitionError, match="expected created"):
        session.restore_sealed_identity_if_present()
    session.close()


def test_inventory_unsealed_contexts_does_not_change_created_state(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, name="inventory-created")
    assert session.inventory_unsealed_contexts() == ()
    assert session.state is CaptureSessionState.CREATED
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    contexts = session.inventory_unsealed_contexts()
    assert contexts
    assert all(isinstance(item, ParserInputContext) for item in contexts)
    assert session.state is CaptureSessionState.ADMITTED
    session.record_completed(binding)
    session.close()


def test_adopt_unsealed_same_generation_writer_marks_admitted_without_capacity_admit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    calls: list[str] = []

    def forbidden(*_args: object, **_kwargs: object) -> None:
        calls.append("admit_capture")
        raise AssertionError("adopt must not call admit_capture")

    monkeypatch.setattr(session._store, "admit_capture", forbidden)
    session.adopt_unsealed_same_generation_writer()
    assert session.state is CaptureSessionState.ADMITTED
    assert calls == []
    with pytest.raises(CaptureSessionTransitionError, match="expected created"):
        session.adopt_unsealed_same_generation_writer()
    session.close()


def test_adopt_unsealed_same_generation_writer_rejects_sealed_manifest(
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="sealed-adopt")
    _admit(first)
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    first.seal()
    first.close()

    resumed = _session(tmp_path, name="sealed-adopt")
    assert resumed.state is CaptureSessionState.CREATED
    with pytest.raises(CaptureSessionContractError, match="sealed manifest"):
        resumed.adopt_unsealed_same_generation_writer()
    resumed.close()


def test_contract_ids_are_deterministic_unique_safe_and_do_not_retain_raw_params(
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="first")
    second = _session(tmp_path, name="second")
    _admit(first)
    _admit(second)
    params = {"season": "RAW-VALUE-MUST-NOT-PERSIST", "league_id": "00"}

    first_contract = first.contract_for("league_game_log", params)
    second_contract = first.contract_for("league_game_log", params)
    replayed_contract = second.contract_for("league_game_log", params)

    assert first_contract.context.attempt_id == replayed_contract.context.attempt_id
    assert first_contract.context.attempt_id != second_contract.context.attempt_id
    assert "RAW-VALUE-MUST-NOT-PERSIST" not in first_contract.context.attempt_id
    assert first_contract.context.retry_ordinal == 0
    assert first_contract.context.request_ordinal == 0
    assert (
        first_contract.provider_authority_sha256
        == (expected_nba_api_provider_authority()["authority_sha256"])
    )
    assert first_contract.endpoint_contract_sha256 == (
        CAPTURE_SESSION_PLACEHOLDER_ENDPOINT_CONTRACT_SHA256
    )
    assert len(first_contract.context.attempt_id) <= 200
    assert all(
        "RAW-VALUE-MUST-NOT-PERSIST" not in path.read_text(encoding="utf-8")
        for path in (tmp_path / "private").rglob("*.json")
    )
    assert "RAW-VALUE-MUST-NOT-PERSIST" not in repr(first._issued_parameter_counts)
    first.close()
    second.close()


def test_base_extractor_rebinds_placeholder_before_stats_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FixtureExtractor(BaseExtractor):
        endpoint_name = "fixture"
        category = "test"

        async def extract(self, **_params: Any) -> pl.DataFrame:
            return pl.DataFrame()

    session = _session(tmp_path)
    _admit(session)
    placeholder = session.contract_for("fixture", {"season": "2025-26"})
    assert placeholder.endpoint_contract_sha256 == (
        CAPTURE_SESSION_PLACEHOLDER_ENDPOINT_CONTRACT_SHA256
    )
    observed: list[NbaApiCaptureContract | None] = []

    def fake_transport(
        _endpoint_cls: type,
        *,
        capture: NbaApiCaptureContract | None = None,
        **_kwargs: Any,
    ) -> tuple[()]:
        observed.append(capture)
        return ()

    monkeypatch.setattr("nbadb.extract.base.fetch_stats_packets", fake_transport)
    extractor = FixtureExtractor()
    extractor.set_capture_contract(placeholder)
    assert extractor._from_nba_api(LeagueGameLog, season="2025-26").is_empty()

    assert len(observed) == 1
    rebound = observed[0]
    assert rebound is not None
    assert rebound.receipt_ledger is placeholder.receipt_ledger
    assert rebound.endpoint_contract_sha256 == endpoint_contract_sha256(
        pinned_endpoint_contract(LeagueGameLog)
    )
    assert rebound.endpoint_contract_sha256 != (
        CAPTURE_SESSION_PLACEHOLDER_ENDPOINT_CONTRACT_SHA256
    )
    session.close()


def test_completed_root_seals_to_exact_path_free_generation_identity(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)

    identity = session.seal()
    assert session.state is CaptureSessionState.SEALED
    assert isinstance(identity, PrivateGenerationIdentity)
    assert identity.done_call_count == 1
    assert identity.done_call_receipt_sha256s == (binding.logical_call_receipt_sha256,)
    assert (
        identity.done_call_receipts_sha256
        == hashlib.sha256(
            json.dumps(
                [binding.logical_call_receipt_sha256],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    expected_binding_payload = [
        {
            "logical_call_receipt_sha256": binding.logical_call_receipt_sha256,
            "endpoint_name": binding.endpoint_name,
            "logical_parameters_sha256": binding.logical_parameters_sha256,
            "provider_authority_sha256": binding.provider_authority_sha256,
            "result_route_ids": list(binding.result_route_ids),
        }
    ]
    assert (
        identity.done_call_bindings_sha256
        == hashlib.sha256(
            json.dumps(
                expected_binding_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    assert identity.done_attempt_count == 1
    assert identity.done_blob_count == 1
    assert identity.orphan_call_count == 0
    assert identity.orphan_attempt_count == 0
    assert identity.orphan_blob_count == 0
    assert identity.artifact_count == 3
    assert identity.stored_bytes > 0
    assert len(identity.manifest_sha256) == 64
    assert identity.workflow_run_id == 123
    assert identity.workflow_run_attempt == 1
    assert (
        identity.provider_authority_sha256
        == (expected_nba_api_provider_authority()["authority_sha256"])
    )
    assert set(identity.to_dict()) == {
        "schema_version",
        "kind",
        "manifest_sha256",
        "provider_authority_sha256",
        "semantic_source_sha",
        "chain_id",
        "lane_id",
        "workflow_run_id",
        "workflow_run_attempt",
        "artifact_count",
        "done_call_count",
        "done_call_receipt_sha256s",
        "done_call_receipts_sha256",
        "done_call_bindings_sha256",
        "done_attempt_count",
        "done_blob_count",
        "orphan_call_count",
        "orphan_attempt_count",
        "orphan_blob_count",
        "stored_bytes",
    }
    assert all("path" not in key for key in identity.to_dict())
    assert session.seal() is identity
    assert session.close() is identity
    assert session.close() is identity


def test_private_generation_identity_strict_canonical_codec_round_trips(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, name="identity-codec")
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)
    identity = session.seal()
    session.close()

    expected = json.dumps(
        identity.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    assert identity.canonical_bytes == expected
    assert identity.identity_sha256 == hashlib.sha256(expected).hexdigest()
    assert PrivateGenerationIdentity.from_dict(identity.to_dict()) == identity
    assert PrivateGenerationIdentity.from_canonical_bytes(expected) == identity


def test_private_generation_identity_codec_rejects_field_and_type_drift(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, name="identity-field-drift")
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)
    identity = session.seal()
    session.close()
    canonical = identity.to_dict()

    for field_name in ("schema_version", "kind"):
        payload = dict(canonical)
        payload.pop(field_name)
        with pytest.raises(CaptureSessionContractError, match="fields are invalid"):
            PrivateGenerationIdentity.from_dict(payload)
    payload = dict(canonical)
    payload["unexpected"] = "field"
    with pytest.raises(CaptureSessionContractError, match="fields are invalid"):
        PrivateGenerationIdentity.from_dict(payload)

    for schema_version in (True, float(identity.schema_version)):
        payload = dict(canonical)
        payload["schema_version"] = schema_version
        with pytest.raises(CaptureSessionContractError, match="schema is invalid"):
            PrivateGenerationIdentity.from_dict(payload)
    payload = dict(canonical)
    payload["kind"] = "private_parser_input_generation_v0"
    with pytest.raises(CaptureSessionContractError, match="schema is invalid"):
        PrivateGenerationIdentity.from_dict(payload)

    for field_name in ("workflow_run_id", "workflow_run_attempt"):
        payload = dict(canonical)
        payload[field_name] = True
        with pytest.raises(CaptureSessionContractError, match="positive integer"):
            PrivateGenerationIdentity.from_dict(payload)
    for field_name in (
        "artifact_count",
        "done_call_count",
        "done_attempt_count",
        "done_blob_count",
        "orphan_call_count",
        "orphan_attempt_count",
        "orphan_blob_count",
        "stored_bytes",
    ):
        payload = dict(canonical)
        payload[field_name] = 1.0
        with pytest.raises(CaptureSessionContractError, match="nonnegative integer"):
            PrivateGenerationIdentity.from_dict(payload)

    for field_name in (
        "manifest_sha256",
        "provider_authority_sha256",
        "done_call_receipts_sha256",
        "done_call_bindings_sha256",
    ):
        payload = dict(canonical)
        payload[field_name] = "A" * 64
        with pytest.raises(CaptureSessionContractError, match="lowercase SHA-256"):
            PrivateGenerationIdentity.from_dict(payload)
    payload = dict(canonical)
    payload["semantic_source_sha"] = _SOURCE_SHA.upper()
    with pytest.raises(CaptureSessionContractError, match="lowercase commit SHA"):
        PrivateGenerationIdentity.from_dict(payload)
    for field_name in ("chain_id", "lane_id"):
        payload = dict(canonical)
        payload[field_name] = "../foreign"
        with pytest.raises(CaptureSessionContractError, match="safe token"):
            PrivateGenerationIdentity.from_dict(payload)


def test_private_generation_identity_codec_rejects_noncanonical_root_authority(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, name="identity-root-drift")
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)
    identity = session.seal()
    session.close()
    canonical = identity.to_dict()

    payload = dict(canonical)
    payload["done_call_receipt_sha256s"] = tuple(identity.done_call_receipt_sha256s)
    with pytest.raises(CaptureSessionContractError, match="must be a list"):
        PrivateGenerationIdentity.from_dict(payload)

    payload = dict(canonical)
    payload["done_call_receipt_sha256s"] = ["f" * 64, "0" * 64]
    payload["done_call_count"] = 2
    payload["done_call_receipts_sha256"] = hashlib.sha256(
        json.dumps(
            ["0" * 64, "f" * 64],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(CaptureSessionContractError, match="canonical sorted unique"):
        PrivateGenerationIdentity.from_dict(payload)

    payload = dict(canonical)
    payload["done_call_receipt_sha256s"] = ["0" * 64, "0" * 64]
    payload["done_call_count"] = 2
    with pytest.raises(CaptureSessionContractError, match="canonical sorted unique"):
        PrivateGenerationIdentity.from_dict(payload)

    payload = dict(canonical)
    payload["done_call_receipts_sha256"] = "0" * 64
    if identity.done_call_receipts_sha256 == payload["done_call_receipts_sha256"]:
        payload["done_call_receipts_sha256"] = "f" * 64
    with pytest.raises(CaptureSessionContractError, match="canonical root inventory"):
        PrivateGenerationIdentity.from_dict(payload)


def test_private_generation_identity_codec_rejects_noncanonical_json_bytes(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, name="identity-byte-drift")
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)
    identity = session.seal()
    session.close()
    canonical = identity.canonical_bytes

    noncanonical = (
        canonical + b"\n",
        json.dumps(identity.to_dict(), sort_keys=True).encode("utf-8"),
        b"[]",
        b'{"kind":"private_parser_input_generation","kind":"duplicate"}',
        b'{"schema_version":NaN}',
        b'{"schema_version":1e999}',
        b"\xff",
    )
    for encoded in noncanonical:
        with pytest.raises(CaptureSessionContractError):
            PrivateGenerationIdentity.from_canonical_bytes(encoded)
    non_bytes_encoding: Any = "{}"
    with pytest.raises(CaptureSessionContractError, match="must be bytes"):
        PrivateGenerationIdentity.from_canonical_bytes(non_bytes_encoding)


def test_sealed_crash_reopen_restores_exact_identity_and_roots_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="reentry")
    _admit(first)
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    expected_identity = first.seal()
    root = tmp_path / "private" / "reentry"
    first.close()
    before = _tree_snapshot(root)

    resumed = _session(tmp_path, name="reentry")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("sealed identity restoration must remain read-only")

    monkeypatch.setattr(BronzeCaptureStore, "admit_capture", forbidden)
    monkeypatch.setattr(BronzeCaptureStore, "write_manifest", forbidden)
    monkeypatch.setattr(
        "nbadb.orchestrate.capture_session.expected_nba_api_provider_authority",
        forbidden,
    )

    restored = resumed.restore_sealed_identity_if_present()

    assert restored == expected_identity
    assert resumed.generation_identity == expected_identity
    assert resumed.state is CaptureSessionState.SEALED
    assert resumed._completed_bindings == {
        binding.logical_call_receipt_sha256: binding,
    }
    assert _tree_snapshot(root) == before
    with pytest.raises(CaptureSessionTransitionError, match="expected created"):
        _admit(resumed)
    with pytest.raises(CaptureSessionTransitionError, match="expected admitted"):
        resumed.contract_for("league_game_log", {})
    with pytest.raises(CaptureSessionTransitionError, match="expected admitted"):
        resumed.record_completed(binding)
    with pytest.raises(CaptureSessionTransitionError, match="expected admitted"):
        resumed.restore_completed_bindings((binding,))
    with pytest.raises(CaptureSessionTransitionError, match="expected created"):
        resumed.restore_sealed_identity_if_present()
    assert resumed.seal() is restored
    assert resumed.close() is restored
    assert resumed.close() is restored
    assert _tree_snapshot(root) == before


def test_open_existing_sealed_restore_remains_bound_to_authorized_inode_after_swap(
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="descriptor-reentry")
    _admit(first)
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    expected_identity = first.seal()
    root = tmp_path / "private" / "descriptor-reentry"
    first.close()
    expected_root_identity = (root.stat().st_dev, root.stat().st_ino)
    sibling = tmp_path / "invalid-descriptor-sibling"
    shutil.copytree(root, sibling)
    (sibling / "manifest.json").write_bytes((sibling / "manifest.json").read_bytes() + b"\n")

    resumed = PrivateCaptureSession.open_existing(
        root,
        limits=_limits(),
        public_roots=(tmp_path / "data" / "nbadb",),
        scope=_scope(),
        expected_root_identity=expected_root_identity,
    )
    retained = tmp_path / "retained-descriptor-reentry"
    root.rename(retained)
    sibling.rename(root)
    try:
        assert resumed.restore_sealed_identity_if_present() == expected_identity
        assert resumed.generation_identity == expected_identity
        assert resumed.state is CaptureSessionState.SEALED
    finally:
        resumed.close()
        root.rename(sibling)
        retained.rename(root)


def test_open_existing_rejects_valid_sibling_substituted_before_descriptor_open(
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="descriptor-preopen")
    _admit(first)
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    first.seal()
    root = tmp_path / "private" / "descriptor-preopen"
    first.close()
    expected_root_identity = (root.stat().st_dev, root.stat().st_ino)
    sibling = tmp_path / "valid-descriptor-sibling"
    shutil.copytree(root, sibling)
    retained = tmp_path / "retained-descriptor-preopen"
    root.rename(retained)
    sibling.rename(root)
    try:
        with pytest.raises(ExtractionError, match="changed identity before open"):
            PrivateCaptureSession.open_existing(
                root,
                limits=_limits(),
                public_roots=(tmp_path / "data" / "nbadb",),
                scope=_scope(),
                expected_root_identity=expected_root_identity,
            )
    finally:
        root.rename(sibling)
        retained.rename(root)


@pytest.mark.parametrize(
    "foreign_scope",
    [
        replace(_scope(), semantic_source_sha="b" * 40),
        replace(_scope(), chain_id="foreign-chain"),
        _scope(lane_id="foreign-lane"),
        _scope(workflow_run_id=124),
        _scope(workflow_run_attempt=2),
    ],
)
def test_sealed_restore_rejects_foreign_scope(
    tmp_path: Path,
    foreign_scope: CaptureRunScope,
) -> None:
    first = _session(tmp_path, name="foreign-scope")
    _admit(first)
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    first.seal()
    first.close()

    resumed = _session(tmp_path, name="foreign-scope", scope=foreign_scope)
    with pytest.raises(CaptureSessionContractError, match="scope does not match"):
        resumed.restore_sealed_identity_if_present()
    assert resumed.state is CaptureSessionState.INCOMPLETE
    assert resumed.closed is True
    assert resumed.generation_identity is None
    assert resumed._completed_bindings == {}
    competing = _session(tmp_path, name="foreign-scope")
    assert competing.restore_sealed_identity_if_present() is not None
    competing.close()


def test_sealed_restore_rejects_foreign_provider_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="foreign-provider")
    _admit(first)
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    first.seal()
    first.close()
    monkeypatch.setattr(
        "nbadb.orchestrate.capture_session.expected_nba_api_provider_authority",
        lambda: {"authority_sha256": "f" * 64},
    )

    resumed = _session(tmp_path, name="foreign-provider")
    with pytest.raises(
        CaptureSessionContractError,
        match="scope does not match: provider_authority_sha256",
    ):
        resumed.restore_sealed_identity_if_present()
    assert resumed.state is CaptureSessionState.INCOMPLETE
    assert resumed.closed is True
    assert resumed.generation_identity is None
    monkeypatch.setattr(
        "nbadb.orchestrate.capture_session.expected_nba_api_provider_authority",
        expected_nba_api_provider_authority,
    )
    competing = _session(tmp_path, name="foreign-provider")
    assert competing.restore_sealed_identity_if_present() is not None
    competing.close()


def test_sealed_restore_rejects_foreign_orphan_context_and_releases_lock(
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="foreign-orphan")
    _admit(first)
    contract = first.contract_for("league_game_log", {"season": "2025-26"})
    contract.sink.record_no_response_attempt(
        context=replace(contract.context, lane_id="foreign-lane"),
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="LeagueGameLog",
        endpoint_slug="leaguegamelog",
        parameters={"season": "2025-26"},
        provider_authority_sha256=contract.provider_authority_sha256,
        contract_sha256=contract.endpoint_contract_sha256,
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="Timeout",
    )
    first.seal()
    first.close()

    resumed = _session(tmp_path, name="foreign-orphan")
    with pytest.raises(
        CaptureSessionContractError,
        match="resume context differs from run scope: lane_id",
    ):
        resumed.restore_sealed_identity_if_present()
    assert resumed.closed is True
    assert resumed.state is CaptureSessionState.INCOMPLETE

    competing = BronzeCaptureStore(
        tmp_path / "private" / "foreign-orphan",
        limits=_limits(),
        public_roots=(tmp_path / "data" / "nbadb",),
    )
    competing.close()


@pytest.mark.parametrize("target", ["manifest", "receipt"])
def test_sealed_restore_fails_closed_on_fresh_tampering_without_mutation(
    tmp_path: Path,
    target: str,
) -> None:
    first = _session(tmp_path, name=f"tampered-{target}")
    _admit(first)
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    first.seal()
    root = tmp_path / "private" / f"tampered-{target}"
    first.close()

    resumed = _session(tmp_path, name=f"tampered-{target}")
    path = (
        root / "manifest.json"
        if target == "manifest"
        else next((root / "receipts" / "calls").rglob("*.json"))
    )
    path.write_bytes(path.read_bytes() + b"\n")
    before = _tree_snapshot(root)

    with pytest.raises(CaptureSessionContractError, match="generation is invalid") as raised:
        resumed.restore_sealed_identity_if_present()
    assert isinstance(raised.value.__cause__, ExtractionError)
    assert resumed.state is CaptureSessionState.INCOMPLETE
    assert resumed.closed is True
    assert resumed.generation_identity is None
    assert resumed._completed_bindings == {}
    assert _tree_snapshot(root) == before
    with pytest.raises(ExtractionError) as reopened:
        BronzeCaptureStore(
            root,
            limits=_limits(),
            public_roots=(tmp_path / "data" / "nbadb",),
        )
    assert "already has a writer" not in str(reopened.value)


def test_generation_identity_rejects_manifest_digest_and_count_tampering(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private" / "generation"
    session = _session(tmp_path)
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)
    session.seal()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    digest_tampered = dict(manifest)
    digest_tampered["done_call_count"] = 2
    with pytest.raises(CaptureSessionContractError, match="digest does not match"):
        PrivateGenerationIdentity.from_manifest(
            digest_tampered,
            scope=session.scope,
            provider_authority_sha256=(expected_nba_api_provider_authority()["authority_sha256"]),
        )

    count_tampered = dict(digest_tampered)
    body = dict(count_tampered)
    body.pop("manifest_sha256")
    count_tampered["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(CaptureSessionContractError, match="does not reconcile"):
        PrivateGenerationIdentity.from_manifest(
            count_tampered,
            scope=session.scope,
            provider_authority_sha256=(expected_nba_api_provider_authority()["authority_sha256"]),
        )

    execution_tampered = dict(manifest)
    execution_tampered["workflow_run_attempt"] = 2
    body = dict(execution_tampered)
    body.pop("manifest_sha256")
    execution_tampered["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        CaptureSessionContractError,
        match="scope does not match: workflow_run_attempt",
    ):
        PrivateGenerationIdentity.from_manifest(
            execution_tampered,
            scope=session.scope,
            provider_authority_sha256=(expected_nba_api_provider_authority()["authority_sha256"]),
        )
    session.close()


def test_completed_roots_allow_exact_replay_and_reject_foreign_or_changed_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _session(tmp_path, name="first")
    second = _session(tmp_path, name="second")
    _admit(first)
    _admit(second)
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    original_load = first._store.load_completed_logical_call_binding
    replay_loads = 0

    def load_replay(*args: object, **kwargs: object) -> LogicalCallReceiptBinding:
        nonlocal replay_loads
        replay_loads += 1
        return original_load(*args, **kwargs)

    monkeypatch.setattr(first._store, "load_completed_logical_call_binding", load_replay)
    first.record_completed(binding)
    assert replay_loads == 1
    assert first._completed_bindings == {binding.logical_call_receipt_sha256: binding}

    with pytest.raises(
        CaptureSessionContractError,
        match="does not match canonical stored authority",
    ):
        first.record_completed(replace(binding, result_route_ids=("league_game_log:stg_forged:0",)))

    second.contract_for(
        "league_game_log",
        {"season": "2025-26", "season_type": "Regular Season"},
    )
    with pytest.raises(
        CaptureSessionContractError,
        match="does not match canonical stored authority",
    ):
        second.record_completed(binding)

    with pytest.raises(CaptureSessionContractError, match="provider-authority drift"):
        second.record_completed(replace(binding, provider_authority_sha256="f" * 64))
    first.close()
    second.close()


def test_completed_root_rejects_forged_caller_binding_against_stored_bytes(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    forged_params = {"season": "2024-25", "season_type": "Regular Season"}
    session.contract_for("league_game_log", forged_params)
    session.contract_for(
        "team_game_log",
        binding_parameters := {
            "season": "2025-26",
            "season_type": "Regular Season",
        },
    )
    assert canonical_parameters_sha256(binding_parameters) == binding.logical_parameters_sha256

    with pytest.raises(
        CaptureSessionContractError,
        match="does not match canonical stored authority",
    ):
        session.record_completed(
            replace(
                binding,
                logical_parameters_sha256=canonical_parameters_sha256(forged_params),
            )
        )
    with pytest.raises(
        CaptureSessionContractError,
        match="does not match canonical stored authority",
    ):
        session.record_completed(replace(binding, endpoint_name="team_game_log"))
    with pytest.raises(
        CaptureSessionContractError,
        match="does not match canonical stored authority",
    ):
        session.record_completed(
            replace(binding, result_route_ids=("league_game_log:stg_forged:0",))
        )

    session.record_completed(binding)
    assert session.seal().done_call_count == 1
    session.close()


def test_completed_root_rejects_foreign_scope_and_unissued_parameter_authority(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path)
    _admit(session)
    issued = session.contract_for(
        "league_game_log",
        {"season": "2025-26", "season_type": "Regular Season"},
    )
    foreign_context = replace(issued.context, lane_id="foreign-lane")
    foreign_binding, _contract = _complete_logical_call(
        session,
        context_override=foreign_context,
    )
    with pytest.raises(CaptureSessionContractError, match="no issued parameter authority"):
        session.record_completed(replace(foreign_binding, logical_parameters_sha256="f" * 64))
    session.record_completed(foreign_binding)
    with pytest.raises(CaptureSessionContractError, match="foreign, scope-mismatched"):
        session.seal()
    session.close()


@pytest.mark.parametrize(
    ("workflow_run_id", "workflow_run_attempt"),
    [(124, 1), (123, 2)],
)
def test_completed_root_rejects_workflow_execution_mismatch_at_seal(
    tmp_path: Path,
    workflow_run_id: int,
    workflow_run_attempt: int,
) -> None:
    session = _session(tmp_path)
    _admit(session)
    issued = session.contract_for(
        "league_game_log",
        {"season": "2025-26", "season_type": "Regular Season"},
    )
    foreign_context = replace(
        issued.context,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
    )
    binding, _contract = _complete_logical_call(
        session,
        context_override=foreign_context,
    )
    session.record_completed(binding)

    with pytest.raises(CaptureSessionContractError) as raised:
        session.seal()
    assert raised.value.__cause__ is not None
    assert "generation-execution drift" in str(raised.value.__cause__)
    session.close()


def test_post_seal_session_and_preexisting_contract_writes_fail_closed(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _admit(session)
    binding, contract = _complete_logical_call(session)
    session.record_completed(binding)
    session.seal()

    with pytest.raises(CaptureSessionTransitionError, match="expected admitted"):
        session.contract_for("league_game_log", {})
    with pytest.raises(CaptureSessionTransitionError, match="expected admitted"):
        session.record_completed(binding)
    with pytest.raises(ExtractionError, match="generation is sealed"):
        contract.sink.store_parser_input(
            "{}",
            representation=PARSER_INPUT_REPRESENTATION,
        )
    session.close()


def test_incomplete_close_preserves_completed_roots_and_releases_lock(tmp_path: Path) -> None:
    root = tmp_path / "private" / "generation"
    public_root = tmp_path / "data" / "nbadb"
    session = PrivateCaptureSession(
        root,
        limits=_limits(),
        public_roots=(public_root,),
        scope=_scope(),
    )
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)

    identity = session.close()
    assert isinstance(identity, IncompleteCaptureIdentity)
    assert session.state is CaptureSessionState.INCOMPLETE
    assert identity.closed_from_state == "admitted"
    assert identity.workflow_run_id == 123
    assert identity.workflow_run_attempt == 1
    assert identity.done_call_receipt_sha256s == (binding.logical_call_receipt_sha256,)
    assert identity.inventory_validated is True
    assert identity.artifact_count == 3
    assert identity.stored_bytes is not None and identity.stored_bytes > 0
    assert not (root / "manifest.json").exists()
    assert session.close() is identity

    reopened = BronzeCaptureStore(root, limits=_limits(), public_roots=(public_root,))
    reopened.close()


def test_incomplete_close_keeps_roots_even_when_inventory_cannot_be_validated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private" / "generation"
    session = _session(tmp_path)
    _admit(session)
    binding, _contract = _complete_logical_call(session)
    session.record_completed(binding)
    (root / "unexpected.private").write_text("invalid inventory", encoding="utf-8")

    identity = session.close()
    assert isinstance(identity, IncompleteCaptureIdentity)
    assert identity.done_call_receipt_sha256s == (binding.logical_call_receipt_sha256,)
    assert identity.inventory_validated is False
    assert identity.artifact_set_sha256 is None
    assert identity.artifact_count is None
    assert identity.stored_bytes is None


def test_unsealed_session_restores_durable_roots_and_advances_call_ordinal(
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="resumable")
    _admit(first)
    first.contract_for("league_game_log", {"season": "unpersisted"})
    binding, _contract = _complete_logical_call(first)
    first.record_completed(binding)
    incomplete = first.close()
    assert isinstance(incomplete, IncompleteCaptureIdentity)

    resumed = _session(tmp_path, name="resumable")
    _admit(resumed)
    next_contract = resumed.contract_for(
        "team_game_log",
        {"season": "2025-26", "season_type": "Regular Season"},
    )
    assert "-00000002-" in next_contract.context.attempt_id

    resumed.restore_completed_bindings((binding,))
    resumed.restore_completed_bindings((binding,))
    identity = resumed.seal()

    assert identity.done_call_receipt_sha256s == (binding.logical_call_receipt_sha256,)
    assert identity.done_call_count == 1
    assert resumed.close() == identity


def test_unsealed_session_rejects_foreign_restored_binding(
    tmp_path: Path,
) -> None:
    first = _session(tmp_path, name="restore-drift")
    _admit(first)
    binding, _contract = _complete_logical_call(first)
    first.close()

    resumed = _session(tmp_path, name="restore-drift")
    _admit(resumed)
    with pytest.raises(CaptureSessionContractError, match="unsealed generation"):
        resumed.restore_completed_bindings((replace(binding, endpoint_name="team_game_log"),))
    resumed.close()


def test_close_before_admission_is_explicit_idempotent_and_unlocks(tmp_path: Path) -> None:
    root = tmp_path / "private" / "generation"
    public_root = tmp_path / "data" / "nbadb"
    session = PrivateCaptureSession(
        root,
        limits=_limits(),
        public_roots=(public_root,),
        scope=_scope(),
    )
    identity = session.close()
    assert isinstance(identity, IncompleteCaptureIdentity)
    assert identity.closed_from_state == "created"
    assert identity.workflow_run_id == 123
    assert identity.workflow_run_attempt == 1
    assert identity.issued_call_count == 0
    assert identity.done_call_receipt_sha256s == ()
    assert identity.inventory_validated is True
    assert identity.artifact_count == 0
    assert identity.stored_bytes == 0
    assert session.close() is identity

    reopened = BronzeCaptureStore(root, limits=_limits(), public_roots=(public_root,))
    reopened.close()


def test_incomplete_identity_is_path_free_and_digest_bound(tmp_path: Path) -> None:
    session = _session(tmp_path)
    identity = session.close()
    assert isinstance(identity, IncompleteCaptureIdentity)
    payload = identity.to_dict()
    assert payload["workflow_run_id"] == 123
    assert payload["workflow_run_attempt"] == 1
    assert all("path" not in key for key in payload)
    assert all("message" not in key for key in payload)
    assert len(identity.done_call_receipts_sha256) == 64
    expected = hashlib.sha256(b"[]").hexdigest()
    assert identity.done_call_receipts_sha256 == expected
    assert len(identity.identity_sha256) == 64
