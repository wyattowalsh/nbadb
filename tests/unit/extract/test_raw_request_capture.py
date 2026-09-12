from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import polars as pl
import pytest
from nba_api.live.nba.endpoints import ScoreBoard
from nba_api.stats.endpoints import LeagueGameLog
from pydantic import ValidationError

import nbadb.extract.raw_request_capture as raw_request_capture
from nbadb.contracts.raw_request_authority import (
    RequestObservationV2,
    canonical_semantic_parameters,
    decode_parser_input_object,
)
from nbadb.core.errors import ResponseContractError
from nbadb.core.errors import ValidationError as NbaDbValidationError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    owned_contract_sha256,
    pinned_live_contracts,
    pinned_static_dataset_contract,
)
from nbadb.extract.base import BaseExtractor
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    BronzeCaptureStore,
    BronzeLimits,
    CapturedParserInput,
    ParserInputContext,
    ResultSetReceipt,
    parent_occurrence_states_digest,
)
from nbadb.extract.nba_api_adapter import (
    NbaApiCaptureContract,
    NbaApiPayload,
    NbaApiResultPacket,
    NbaApiResultPackets,
)
from nbadb.extract.raw_request_capture import (
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
    RawRequestCaptureContract,
    wrap_raw_request_capture_contract,
)

if TYPE_CHECKING:
    from pathlib import Path


_SOURCE_SHA = "a" * 40
_SEMANTIC_REQUEST_SHA256 = "1" * 64
_LOGICAL_INVOCATION_SHA256 = "2" * 64
_SCOPE_SHA256 = "3" * 64
_ENDPOINT_ID = "ScoreBoard"
_ENDPOINT_CONTRACT_SHA256 = owned_contract_sha256(pinned_live_contracts()[_ENDPOINT_ID])
_STATIC_ENDPOINT_ID = "static_players"
_STATIC_CONTRACT = pinned_static_dataset_contract(_STATIC_ENDPOINT_ID)
_STATIC_ENDPOINT_CONTRACT_SHA256 = owned_contract_sha256(_STATIC_CONTRACT)
_PROVIDER_AUTHORITY_SHA256 = cast(
    "str",
    expected_nba_api_provider_authority()["authority_sha256"],
)
_BODY = '{"meta":{"version":1,"request":"fixture","time":"now","code":200}}'


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _public_context(*, call_count: int = 1) -> RawRequestCaptureContextV2:
    _, _, provider_request_sha256 = canonical_semantic_parameters("live", _ENDPOINT_ID, {})
    return RawRequestCaptureContextV2(
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        source_sha=_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain-1",
        lane_id="lane-1",
        provider_calls=tuple(
            RawProviderCallContextV2(
                request_ordinal=request_ordinal,
                semantic_request_sha256=_SEMANTIC_REQUEST_SHA256,
                logical_invocation_sha256=_LOGICAL_INVOCATION_SHA256,
                provider_call_role="primary",
                provider_call_ordinal=request_ordinal,
                source_family="live",
                endpoint_id=_ENDPOINT_ID,
                provider_request_sha256=provider_request_sha256,
                endpoint_contract_sha256=_ENDPOINT_CONTRACT_SHA256,
                scope_sha256=_SCOPE_SHA256,
            )
            for request_ordinal in range(call_count)
        ),
    )


def _static_public_context() -> RawRequestCaptureContextV2:
    _, _, provider_request_sha256 = canonical_semantic_parameters("static", _STATIC_ENDPOINT_ID, {})
    return RawRequestCaptureContextV2(
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        source_sha=_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain-1",
        lane_id="lane-1",
        provider_calls=(
            RawProviderCallContextV2(
                request_ordinal=0,
                semantic_request_sha256=_SEMANTIC_REQUEST_SHA256,
                logical_invocation_sha256=_LOGICAL_INVOCATION_SHA256,
                provider_call_role="primary",
                provider_call_ordinal=0,
                source_family="static",
                endpoint_id=_STATIC_ENDPOINT_ID,
                provider_request_sha256=provider_request_sha256,
                endpoint_contract_sha256=_STATIC_ENDPOINT_CONTRACT_SHA256,
                scope_sha256=_SCOPE_SHA256,
            ),
        ),
    )


def _private_contract(
    tmp_path: Path,
    *,
    endpoint_contract_sha256: str = _ENDPOINT_CONTRACT_SHA256,
) -> tuple[NbaApiCaptureContract, BronzeCaptureStore]:
    store = BronzeCaptureStore(
        tmp_path / "private" / "bronze",
        public_roots=(tmp_path / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=1_000_000,
            max_generation_stored_bytes=2_000_000,
            minimum_free_bytes=1,
        ),
    )
    return (
        NbaApiCaptureContract(
            sink=store,
            context=ParserInputContext(
                attempt_id="raw-capture-attempt-1",
                workflow_run_id=101,
                workflow_run_attempt=1,
                chain_id="chain-1",
                lane_id="lane-1",
                semantic_source_sha=_SOURCE_SHA,
            ),
            provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
            endpoint_contract_sha256=endpoint_contract_sha256,
        ),
        store,
    )


def _wrapped_contract(
    tmp_path: Path,
    *,
    public_context: RawRequestCaptureContextV2 | None = None,
) -> tuple[RawRequestCaptureContract, BronzeCaptureStore]:
    private, store = _private_contract(tmp_path)
    return wrap_raw_request_capture_contract(private, public_context), store


def _meta_result_receipt() -> ResultSetReceipt:
    headers = ("version", "request", "time", "code")
    return ResultSetReceipt(
        name="meta",
        provider_index=None,
        canonical_index=0,
        headers_sha256=_sha256(json.dumps(list(headers), separators=(",", ":")).encode()),
        row_count=1,
        json_path="$.meta",
        container_kind="nba_api_live_json_object",
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_observation_count=1,
        parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
        observed_field_orders_sha256=_sha256(b"observed-meta-fields"),
        normalized_output_sha256=_sha256(b"normalized-meta-output"),
    )


def _static_result_receipt() -> ResultSetReceipt:
    headers = tuple(field.name for field in _STATIC_CONTRACT.raw_fields)
    return ResultSetReceipt(
        name="players_shape_1",
        provider_index=0,
        canonical_index=0,
        headers_sha256=_sha256(json.dumps(list(headers), separators=(",", ":")).encode()),
        row_count=1,
        json_path=None,
        container_kind="nba_api_static_records",
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_observation_count=1,
        parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
        observed_field_orders_sha256=_sha256(b"observed-static-fields"),
        normalized_output_sha256=_sha256(b"normalized-static-output"),
    )


def _record_success(
    capture: RawRequestCaptureContract,
    *,
    body: str = _BODY,
) -> tuple[ParserInputContext, str]:
    request = capture.begin_request()
    captured = capture.sink.store_parser_input(
        body,
        representation=PARSER_INPUT_REPRESENTATION,
    )
    receipt = _record_captured_success(capture, request, captured)
    return request, receipt


def _record_captured_success(
    capture: RawRequestCaptureContract,
    request: ParserInputContext,
    captured: CapturedParserInput,
    *,
    result_set: ResultSetReceipt | None = None,
) -> str:
    receipt = capture.sink.record_response_attempt(
        context=request,
        transport_kind="http_response",
        source_family="live",
        endpoint_id=_ENDPOINT_ID,
        endpoint_slug="scoreboard",
        parameters={},
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        contract_sha256=_ENDPOINT_CONTRACT_SHA256,
        status_code=200,
        captured=captured,
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        result_sets=((_meta_result_receipt() if result_set is None else result_set),),
    )
    capture.record_receipt(request, receipt, successful=True)
    return receipt


def test_public_capture_context_is_strict_frozen_and_complete() -> None:
    context = _public_context()

    with pytest.raises(ValidationError, match="frozen"):
        context.run_id = 102  # type: ignore[misc]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RawRequestCaptureContextV2.model_validate(
            context.model_dump(mode="python") | {"proxy": "forbidden"}
        )
    with pytest.raises(ValidationError, match="competition identity"):
        RawProviderCallContextV2(
            **(context.provider_calls[0].model_dump(mode="python") | {"competition_id": "nba"})
        )
    with pytest.raises(ValidationError, match="request_ordinal"):
        RawProviderCallContextV2(
            **(context.provider_calls[0].model_dump(mode="python") | {"request_ordinal": True})
        )
    with pytest.raises(ValidationError, match="prohibited public identifier"):
        RawProviderCallContextV2(
            **(
                context.provider_calls[0].model_dump(mode="python")
                | {"provider_call_role": "proxy-route"}
            )
        )


def test_public_capture_surface_has_no_removed_v1_authority_names() -> None:
    removed_names = {
        "PendingRawRequestSuccessV1",
        "PendingResultOccurrenceV1",
        "RawProviderCallContextV1",
        "RawRequestCaptureContextV1",
        "RawRequestCaptureIssueV1",
        "RawRequestCaptureSnapshotV1",
    }
    assert removed_names.isdisjoint(raw_request_capture.__all__)
    assert all(not hasattr(raw_request_capture, name) for name in removed_names)


def test_success_keeps_exact_public_body_pending_for_transactional_routes(
    tmp_path: Path,
) -> None:
    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    try:
        _, receipt = _record_success(capture)

        snapshot = capture.sink.snapshot()
        assert snapshot.requires_transactional_finalization is True
        assert snapshot.observations == ()
        assert snapshot.issues == ()
        assert len(snapshot.pending_successes) == len(snapshot.objects) == 1
        pending = snapshot.pending_successes[0]
        assert pending.private_receipt_sha256 == receipt
        assert pending.body_disposition == "public_parser_input"
        assert pending.logical_receipt_sha256 is None
        assert pending.aggregate_route_ids == ()
        assert pending.results[0].ordered_headers == (
            "version",
            "request",
            "time",
            "code",
        )
        assert pending.body_object is not None
        assert decode_parser_input_object(snapshot.objects[0]) == _BODY.encode()
        assert capture.sink.replay_parser_input(receipt) == _BODY.encode()

        with pytest.raises(ValidationError, match="response-level route landing"):
            RequestObservationV2.build(
                attempt=pending.attempt,
                transport=pending.transport,
                started_at=pending.started_at,
                finished_at=pending.finished_at,
                elapsed_ns=pending.elapsed_ns,
                lifecycle="selected_terminal",
                outcome=pending.outcome,
                failure_class=None,
                root_exception_class=None,
                body_disposition=pending.body_disposition,
                body_object_sha256=pending.body_object.object_sha256,
                bodyless_evidence_sha256=None,
                result_occurrence_sha256s=(),
                route_landing_sha256s=(),
                capture_response_receipt_sha256=pending.private_receipt_sha256,
                logical_receipt_sha256="f" * 64,
            )
    finally:
        store.close()


def test_secret_shaped_success_body_remains_private_and_cannot_claim_authority(
    tmp_path: Path,
) -> None:
    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    secret_body = '{"meta":{"version":1,"apiKey":"sentinel"}}'
    try:
        _, receipt = _record_success(capture, body=secret_body)

        snapshot = capture.sink.snapshot()
        assert snapshot.objects == snapshot.observations == snapshot.pending_successes == ()
        assert [issue.code for issue in snapshot.issues] == ["response_observation_unavailable"]
        assert snapshot.issues[0].root_exception_class == "UnclassifiedError"
        assert capture.sink.replay_parser_input(receipt) == secret_body.encode()
        assert "sentinel" not in repr(snapshot)
    finally:
        store.close()


def test_missing_public_context_preserves_private_receipt_but_cannot_claim_authority(
    tmp_path: Path,
) -> None:
    capture, store = _wrapped_contract(tmp_path)
    try:
        _, receipt = _record_success(capture)

        snapshot = capture.sink.snapshot()
        assert capture.sink.replay_parser_input(receipt) == _BODY.encode()
        assert snapshot.objects == ()
        assert snapshot.observations == ()
        assert snapshot.pending_successes == ()
        assert [issue.code for issue in snapshot.issues] == ["response_observation_unavailable"]
        assert capture.sink._parser_inputs == {}  # type: ignore[attr-defined]
        assert capture.sink._starts == {}  # type: ignore[attr-defined]
    finally:
        store.close()


def test_identical_inflight_bodies_each_retain_their_attempt_authority(tmp_path: Path) -> None:
    capture, store = _wrapped_contract(
        tmp_path,
        public_context=_public_context(call_count=2),
    )
    try:
        first_request = capture.begin_request()
        first_captured = capture.sink.store_parser_input(
            _BODY,
            representation=PARSER_INPUT_REPRESENTATION,
        )
        second_request = capture.begin_request()
        second_captured = capture.sink.store_parser_input(
            _BODY,
            representation=PARSER_INPUT_REPRESENTATION,
        )

        first_receipt = _record_captured_success(capture, first_request, first_captured)
        second_receipt = _record_captured_success(capture, second_request, second_captured)

        snapshot = capture.sink.snapshot()
        assert snapshot.issues == ()
        assert len(snapshot.objects) == 1
        assert [item.private_receipt_sha256 for item in snapshot.pending_successes] == [
            first_receipt,
            second_receipt,
        ]
        assert capture.sink._parser_inputs == {}  # type: ignore[attr-defined]
        assert capture.sink._starts == {}  # type: ignore[attr-defined]
    finally:
        store.close()


def test_downstream_failure_can_address_one_of_multiple_pending_receipts(
    tmp_path: Path,
) -> None:
    capture, store = _wrapped_contract(
        tmp_path,
        public_context=_public_context(call_count=2),
    )
    try:
        first_request, first_receipt = _record_success(capture)
        _, second_receipt = _record_success(capture)

        capture.sink.mark_downstream_incomplete(
            failure_class="response_contract",
            root_exception_class="ValueError",
            receipt_sha256=first_receipt,
        )

        snapshot = capture.sink.snapshot()
        assert [item.private_receipt_sha256 for item in snapshot.pending_successes] == [
            second_receipt
        ]
        assert snapshot.observations[0].attempt.request_ordinal == first_request.request_ordinal
        assert snapshot.observations[0].outcome == "downstream_incomplete"
    finally:
        store.close()


def test_ambiguous_downstream_failure_does_not_guess_a_response(tmp_path: Path) -> None:
    capture, store = _wrapped_contract(
        tmp_path,
        public_context=_public_context(call_count=2),
    )
    try:
        _record_success(capture)
        _record_success(capture)

        capture.sink.mark_downstream_incomplete(
            failure_class="response_contract",
            root_exception_class="ValueError",
        )

        snapshot = capture.sink.snapshot()
        assert len(snapshot.pending_successes) == 2
        assert snapshot.observations == ()
        assert snapshot.issues[-1].code == "downstream_incomplete_receipt_ambiguous"
    finally:
        store.close()


def test_bad_result_authority_cannot_leave_an_orphan_public_body(tmp_path: Path) -> None:
    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    try:
        request = capture.begin_request()
        captured = capture.sink.store_parser_input(
            _BODY,
            representation=PARSER_INPUT_REPRESENTATION,
        )
        bad_result = replace(_meta_result_receipt(), headers_sha256="f" * 64)
        receipt = _record_captured_success(
            capture,
            request,
            captured,
            result_set=bad_result,
        )

        snapshot = capture.sink.snapshot()
        assert capture.sink.replay_parser_input(receipt) == _BODY.encode()
        assert snapshot.objects == snapshot.observations == snapshot.pending_successes == ()
        assert snapshot.issues[-1].code == "response_observation_unavailable"
    finally:
        store.close()


def test_issue_exception_names_are_collapsed_to_public_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CredentialLeakError(Exception):
        pass

    def fail_version(_distribution: str) -> str:
        raise CredentialLeakError("must never enter public evidence")

    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    monkeypatch.setattr(
        "nbadb.extract.raw_request_capture.importlib.metadata.version",
        fail_version,
    )
    try:
        _record_success(capture)

        snapshot = capture.sink.snapshot()
        assert snapshot.objects == snapshot.observations == snapshot.pending_successes == ()
        assert snapshot.issues[-1].root_exception_class == "UnclassifiedError"
    finally:
        store.close()


def test_no_response_emits_typed_bodyless_incomplete_observation(tmp_path: Path) -> None:
    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    try:
        request = capture.begin_request()
        receipt = capture.sink.record_no_response_attempt(
            context=request,
            transport_kind="http_response",
            source_family="live",
            endpoint_id=_ENDPOINT_ID,
            endpoint_slug="scoreboard",
            parameters={},
            provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
            contract_sha256=_ENDPOINT_CONTRACT_SHA256,
            outcome="transport_failure_no_response",
            failure_class="transport_transient",
            root_exception_class="ConnectionError",
        )
        capture.record_receipt(request, receipt, successful=False)

        snapshot = capture.sink.snapshot()
        assert snapshot.objects == snapshot.pending_successes == snapshot.issues == ()
        assert len(snapshot.observations) == 1
        observation = snapshot.observations[0]
        assert observation.lifecycle == "incomplete"
        assert observation.outcome == "transport_failure_no_response"
        assert observation.body_disposition == "no_response"
        assert observation.body_object_sha256 is None
        assert observation.schema_version == 2
        assert observation.route_landing_count == 0
        assert observation.transport.status_code is None
        assert observation.transport.effective_status_code is None
    finally:
        store.close()


def test_failed_http_body_stays_private_and_emits_excluded_observation(tmp_path: Path) -> None:
    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    failure_body = '{"message":"provider unavailable"}'
    try:
        request = capture.begin_request()
        captured = capture.sink.store_parser_input(
            failure_body,
            representation=PARSER_INPUT_REPRESENTATION,
        )
        receipt = capture.sink.record_response_attempt(
            context=request,
            transport_kind="http_response",
            source_family="live",
            endpoint_id=_ENDPOINT_ID,
            endpoint_slug="scoreboard",
            parameters={},
            provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
            contract_sha256=_ENDPOINT_CONTRACT_SHA256,
            status_code=503,
            captured=captured,
            outcome="http_transient_error",
            failure_class="transport_transient",
            root_exception_class="UpstreamTransientHttpError",
            result_sets=(),
        )
        capture.record_receipt(request, receipt, successful=False)

        snapshot = capture.sink.snapshot()
        assert snapshot.objects == snapshot.pending_successes == snapshot.issues == ()
        observation = snapshot.observations[0]
        assert observation.body_disposition == "excluded_failure_body"
        assert observation.body_object_sha256 is None
        assert observation.schema_version == 2
        assert observation.route_landing_count == 0
        assert observation.transport.status_code == 503
        assert observation.transport.effective_status_code == 503
        assert capture.sink.replay_parser_input(receipt) == failure_body.encode()
    finally:
        store.close()


def test_parser_failure_emits_typed_excluded_body_observation(tmp_path: Path) -> None:
    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    failure_body = '{"meta":{"code":200},"scoreboard":{}}'
    try:
        request = capture.begin_request()
        captured = capture.sink.store_parser_input(
            failure_body,
            representation=PARSER_INPUT_REPRESENTATION,
        )
        receipt = capture.sink.record_response_attempt(
            context=request,
            transport_kind="http_response",
            source_family="live",
            endpoint_id=_ENDPOINT_ID,
            endpoint_slug="scoreboard",
            parameters={},
            provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
            contract_sha256=_ENDPOINT_CONTRACT_SHA256,
            status_code=200,
            captured=captured,
            outcome="parser_failure",
            failure_class="response_contract",
            root_exception_class="ValueError",
            result_sets=(),
        )
        capture.record_receipt(request, receipt, successful=False)

        snapshot = capture.sink.snapshot()
        assert snapshot.objects == snapshot.pending_successes == snapshot.issues == ()
        observation = snapshot.observations[0]
        assert observation.outcome == "parser_failure"
        assert observation.failure_class == "response_contract"
        assert observation.body_disposition == "excluded_failure_body"
        assert observation.body_object_sha256 is None
        assert observation.schema_version == 2
        assert observation.route_landing_count == 0
        assert observation.transport.status_code == 200
    finally:
        store.close()


def test_static_success_is_explicitly_bodyless_and_pending(tmp_path: Path) -> None:
    private, store = _private_contract(
        tmp_path,
        endpoint_contract_sha256=_STATIC_ENDPOINT_CONTRACT_SHA256,
    )
    capture = wrap_raw_request_capture_contract(private, _static_public_context())
    records = [
        {
            "id": 1,
            "last_name": "Player",
            "first_name": "Fixture",
            "full_name": "Fixture Player",
            "is_active": True,
        }
    ]
    try:
        request = capture.begin_request()
        captured = capture.sink.store_static_records(records)
        receipt = capture.sink.record_static_snapshot_attempt(
            context=request,
            endpoint_id=_STATIC_ENDPOINT_ID,
            endpoint_slug="players",
            provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
            contract_sha256=_STATIC_ENDPOINT_CONTRACT_SHA256,
            captured=captured,
            result_set=_static_result_receipt(),
        )
        capture.record_receipt(request, receipt, successful=True)

        snapshot = capture.sink.snapshot()
        assert snapshot.objects == snapshot.observations == snapshot.issues == ()
        assert snapshot.requires_transactional_finalization is True
        pending = snapshot.pending_successes[0]
        assert pending.outcome == "static_snapshot_success"
        assert pending.body_disposition == "declared_bodyless"
        assert pending.body_object is None
        assert pending.transport.transport_kind == "static_snapshot"
    finally:
        store.close()


@pytest.mark.parametrize("snapshot_materialized", [False, True])
def test_static_failure_emits_typed_public_safe_no_body_observation(
    tmp_path: Path,
    snapshot_materialized: bool,
) -> None:
    private, store = _private_contract(
        tmp_path,
        endpoint_contract_sha256=_STATIC_ENDPOINT_CONTRACT_SHA256,
    )
    capture = wrap_raw_request_capture_contract(private, _static_public_context())
    try:
        request = capture.begin_request()
        if snapshot_materialized:
            captured = capture.sink.store_static_records(
                [[1, "Player", "Fixture", "Fixture Player", True]]
            )
            receipt = capture.sink.record_response_attempt(
                context=request,
                transport_kind="static_provider_snapshot",
                source_family="static",
                endpoint_id=_STATIC_ENDPOINT_ID,
                endpoint_slug="players",
                parameters={},
                provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
                contract_sha256=_STATIC_ENDPOINT_CONTRACT_SHA256,
                status_code=None,
                captured=captured,
                outcome="contract_mismatch",
                failure_class="response_contract",
                root_exception_class="ResponseContractError",
                result_sets=(),
            )
        else:
            receipt = capture.sink.record_no_response_attempt(
                context=request,
                transport_kind="static_provider_snapshot",
                source_family="static",
                endpoint_id=_STATIC_ENDPOINT_ID,
                endpoint_slug="players",
                parameters={},
                provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
                contract_sha256=_STATIC_ENDPOINT_CONTRACT_SHA256,
                outcome="contract_mismatch",
                failure_class="response_contract",
                root_exception_class="ResponseContractError",
            )
        capture.record_receipt(request, receipt, successful=False)

        snapshot = capture.sink.snapshot()
        assert snapshot.objects == snapshot.pending_successes == snapshot.issues == ()
        assert snapshot.requires_transactional_finalization is False
        observation = snapshot.observations[0]
        assert observation.attempt.source_family == "static"
        assert observation.attempt.endpoint_id == _STATIC_ENDPOINT_ID
        assert observation.transport.transport_kind == "static_snapshot"
        assert observation.outcome == "transport_failure_no_response"
        assert observation.failure_class == "response_contract"
        assert observation.root_exception_class == "ResponseContractError"
        assert observation.body_disposition == "no_response"
        assert observation.body_object_sha256 is None
        assert observation.bodyless_evidence_sha256 is not None
        assert observation.result_occurrence_count == 0
        assert observation.route_landing_count == 0
    finally:
        store.close()


def test_downstream_failure_retains_body_as_incomplete_and_clears_pending_success(
    tmp_path: Path,
) -> None:
    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    try:
        _record_success(capture)
        capture.sink.mark_downstream_incomplete(
            failure_class="response_contract",
            root_exception_class="ValueError",
        )

        snapshot = capture.sink.snapshot()
        assert snapshot.pending_successes == ()
        assert snapshot.requires_transactional_finalization is False
        assert len(snapshot.objects) == len(snapshot.observations) == 1
        observation = snapshot.observations[0]
        assert observation.lifecycle == "incomplete"
        assert observation.outcome == "downstream_incomplete"
        assert observation.body_disposition == "public_parser_input"
        assert observation.body_object_sha256 == snapshot.objects[0].object_sha256
        assert observation.route_landing_count == 0
        assert decode_parser_input_object(snapshot.objects[0]) == _BODY.encode()
    finally:
        store.close()


class _ScoreBoardExtractor(BaseExtractor):
    endpoint_name = _ENDPOINT_ID

    async def extract(self, **_params: object) -> pl.DataFrame:
        return pl.DataFrame()


def test_base_validation_failure_marks_public_capture_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private, store = _private_contract(tmp_path)
    extractor = _ScoreBoardExtractor()
    extractor.begin_extraction_attempt()
    extractor.set_raw_request_capture_context(_public_context())
    extractor.set_capture_contract(private)
    capture = cast("RawRequestCaptureContract", extractor._capture_contract)
    try:
        _record_success(capture)

        class RejectingSchema:
            @staticmethod
            def validate(_frame: pl.DataFrame) -> pl.DataFrame:
                raise ValueError("test-only downstream rejection")

        monkeypatch.setattr("nbadb.extract.base.get_raw_schema", lambda _name: RejectingSchema)
        with pytest.raises(NbaDbValidationError, match="raw schema validation failed"):
            extractor._validate(pl.DataFrame())

        snapshot = extractor.raw_request_capture_snapshot()
        assert snapshot is not None
        assert snapshot.pending_successes == ()
        assert snapshot.observations[0].outcome == "downstream_incomplete"
        assert decode_parser_input_object(snapshot.objects[0]) == _BODY.encode()
    finally:
        store.close()


def test_base_stats_conversion_failure_marks_exact_response_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private, store = _private_contract(tmp_path)
    extractor = _ScoreBoardExtractor()
    extractor.begin_extraction_attempt()
    extractor.set_raw_request_capture_context(_public_context())
    extractor.set_capture_contract(private)
    capture = cast("RawRequestCaptureContract", extractor._capture_contract)
    try:
        _, receipt = _record_success(capture)
        packets = NbaApiResultPackets(
            (
                NbaApiResultPacket(
                    name="First",
                    provider_index=0,
                    canonical_index=0,
                    headers=("VALUE",),
                    frame=pl.DataFrame({"VALUE": [1]}),
                    response_receipt_sha256=receipt,
                ),
                NbaApiResultPacket(
                    name="Second",
                    provider_index=1,
                    canonical_index=0,
                    headers=("OTHER",),
                    frame=pl.DataFrame({"OTHER": [2]}),
                    response_receipt_sha256=receipt,
                ),
            )
        )
        monkeypatch.setattr(
            "nbadb.extract.base.fetch_stats_packets",
            lambda *_args, **_kwargs: packets,
        )

        with pytest.raises(ResponseContractError, match="duplicate canonical result indexes"):
            extractor._call_nba_api(LeagueGameLog, season="2024-25")

        snapshot = extractor.raw_request_capture_snapshot()
        assert snapshot is not None
        assert snapshot.pending_successes == ()
        assert snapshot.observations[0].outcome == "downstream_incomplete"
        assert snapshot.observations[0].body_object_sha256 == snapshot.objects[0].object_sha256
    finally:
        store.close()


def test_base_live_schema_failure_marks_exact_response_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private, store = _private_contract(tmp_path)
    extractor = _ScoreBoardExtractor()
    extractor.begin_extraction_attempt()
    extractor.set_raw_request_capture_context(_public_context())
    extractor.set_capture_contract(private)
    capture = cast("RawRequestCaptureContract", extractor._capture_contract)
    try:
        _, receipt = _record_success(capture)
        payload = NbaApiPayload(
            {"games": [{"gameId": "001"}]},
            response_receipt_sha256=receipt,
            provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
            endpoint_contract_sha256=_ENDPOINT_CONTRACT_SHA256,
        )

        class RejectingSchema:
            @staticmethod
            def validate(_frame: pl.DataFrame) -> pl.DataFrame:
                raise ValueError("test-only live schema rejection")

        monkeypatch.setattr(
            "nbadb.extract.base.fetch_live_payloads",
            lambda *_args, **_kwargs: payload,
        )
        monkeypatch.setattr(
            "nbadb.extract.base.normalize_live_landing_frame",
            lambda *_args, **_kwargs: RejectingSchema.validate(pl.DataFrame()),
        )

        with pytest.raises(NbaDbValidationError, match="raw schema validation failed"):
            extractor._from_nba_live(
                ScoreBoard,
                "games",
                source_endpoint="live_score_board",
                natural_keys=("game_id",),
            )

        snapshot = extractor.raw_request_capture_snapshot()
        assert snapshot is not None
        assert snapshot.pending_successes == ()
        assert snapshot.observations[0].outcome == "downstream_incomplete"
        assert snapshot.observations[0].body_object_sha256 == snapshot.objects[0].object_sha256
    finally:
        store.close()


def test_base_requires_public_context_before_private_capture(tmp_path: Path) -> None:
    private, store = _private_contract(tmp_path)
    extractor = _ScoreBoardExtractor()
    extractor.begin_extraction_attempt()
    extractor.set_capture_contract(private)
    try:
        with pytest.raises(
            ResponseContractError,
            match="public raw-request context must precede private capture installation",
        ):
            extractor.set_raw_request_capture_context(_public_context())
    finally:
        store.close()


def test_public_capture_contract_cannot_be_rewrapped_with_stale_state(tmp_path: Path) -> None:
    capture, store = _wrapped_contract(tmp_path, public_context=_public_context())
    try:
        with pytest.raises(ValueError, match="cannot be rewrapped"):
            wrap_raw_request_capture_contract(capture, _public_context())
    finally:
        store.close()
