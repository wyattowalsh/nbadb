"""Tests for nbadb.orchestrate.extractor_runner."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

import nbadb.orchestrate.extractor_runner as extractor_runner_module
from nbadb.contracts.raw_request_authority import (
    RequestObservationV2,
    canonical_semantic_parameters,
)
from nbadb.contracts.w2_operation import W2OperationPersistenceReceiptV1
from nbadb.core.config import NbaDbSettings
from nbadb.core.errors import (
    ExtractionError,
    ParserInputCaptureIntegrityError,
    TransientError,
)
from nbadb.core.errors import (
    ValidationError as NbaDbValidationError,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    owned_contract_sha256,
    pinned_live_contracts,
)
from nbadb.extract.base import BaseExtractor
from nbadb.extract.bronze import (
    DEFAULT_CODEC,
    PARSER_INPUT_REPRESENTATION,
    STATIC_INPUT_REPRESENTATION,
    BronzeCaptureStore,
    BronzeLimits,
    CapturedParserInput,
    LogicalCallReceiptBinding,
    ParserInputContext,
    RecordedParserInput,
    ResultSetReceipt,
    parent_occurrence_states_digest,
)
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
    RawRequestCaptureContract,
    RawRequestCaptureIssueV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.orchestrate.execution_policy import build_execution_policy
from nbadb.orchestrate.extractor_runner import (
    ExtractorRunner,
    PatternExtractionResult,
    _AdaptiveThrottle,
    _DeferredExtraction,
    _ExtractionTaskResult,
    _FailedExtraction,
    _JournaledExtraction,
    _PendingJournalSuccess,
    _record_chunk_completion_heartbeat,
    _sync_extract,
)
from nbadb.orchestrate.resilience import (
    _CircuitBreaker,
    _LatencyTracker,
    _ResponseContractCircuit,
)
from nbadb.orchestrate.staging_map import StagingEntry
from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1
from tests.unit.contracts.test_raw_request_finalization import (
    _case as _raw_finalization_case,
)
from tests.unit.contracts.test_w2_operation_builder import _build as _build_w2_operation

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extractor(
    df: pl.DataFrame | None = None,
    dfs: list[pl.DataFrame] | None = None,
    exc: Exception | None = None,
):
    """Build a mock extractor class + instance."""

    class _Ext:
        category = "default"

        async def extract(self, **kwargs):
            if exc:
                raise exc
            return df if df is not None else pl.DataFrame()

        async def extract_all(self, **kwargs):
            if exc:
                raise exc
            return dfs if dfs is not None else []

    return _Ext


def _make_journal(*, already_done: bool = False, failed: list | None = None):
    j = MagicMock()
    j.was_extracted.return_value = already_done
    j.was_extracted_batch.return_value = set()
    j.get_failed.return_value = failed or []
    return j


def _make_settings(**overrides):
    s = MagicMock()
    s.semaphore_tiers = {"default": 5}
    s.endpoint_semaphore_limits = {}
    s.pbp_chunk_size = 50
    s.default_chunk_size = 500
    s.thread_pool_size = 4
    s.adaptive_rate_min = 1.0
    s.adaptive_rate_recovery = 50
    s.endpoint_rate_limits = {}
    s.endpoint_request_timeouts = {}
    s.endpoint_chunk_size_limits = {}
    s.endpoint_retry_budgets = {}
    s.zero_progress_abort_endpoints = set()
    s.response_contract_circuit_thresholds = {}
    s.extract_max_retries = 0  # disable retries in unit tests by default
    s.extract_retry_base_delay = 0.0
    s.circuit_breaker_threshold = 5
    s.circuit_breaker_max_wait = 600.0
    s.latency_window_size = 10
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_record_chunk_completion_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    heartbeat_path = tmp_path / "chunk-heartbeat"
    monkeypatch.setenv("NBADB_EXTRACTION_HEARTBEAT_PATH", str(heartbeat_path))

    _record_chunk_completion_heartbeat()

    assert heartbeat_path.is_file()


def test_endpoint_coverage_and_runner_import_without_w2_cycle(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(repo_root / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import nbadb.core.endpoint_coverage; import nbadb.orchestrate.extractor_runner",
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr


def test_compatibility_persistence_helper_propagates_w2_callback_result() -> None:
    admission = _w2_admission("a" * 64)

    def persist(_frames: dict[str, pl.DataFrame]) -> tuple[W2SourceCallAdmissionV1, ...]:
        return (admission,)

    result = ExtractorRunner._persist_chunk_results(
        persist,
        {},
        pattern="season",
        chunk_index=0,
        chunk_params=[],
        entries=[],
        expected_staging_keys=[],
        source_results=[],
    )

    assert result == (admission,)


def _make_registry(extractor_cls):
    r = MagicMock()
    r.get.return_value = extractor_cls
    return r


_RAW_CAPTURE_SOURCE_SHA = "a" * 40
_RAW_CAPTURE_SEMANTIC_REQUEST_SHA256 = "1" * 64
_RAW_CAPTURE_LOGICAL_INVOCATION_SHA256 = "2" * 64
_RAW_CAPTURE_SCOPE_SHA256 = "3" * 64
_RAW_CAPTURE_ENDPOINT_ID = "ScoreBoard"
_RAW_CAPTURE_ENDPOINT_CONTRACT_SHA256 = owned_contract_sha256(
    pinned_live_contracts()[_RAW_CAPTURE_ENDPOINT_ID]
)
_RAW_CAPTURE_PROVIDER_AUTHORITY_SHA256 = cast(
    "str",
    expected_nba_api_provider_authority()["authority_sha256"],
)
_RAW_CAPTURE_BODY = '{"meta":{"version":1,"request":"fixture","time":"now","code":200}}'
_RAW_CAPTURE_PLAN_SNAPSHOT_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _raw_capture_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@cache
def _w2_admission_operation():
    return _build_w2_operation()


def _w2_admission(logical_call_receipt_sha256: str) -> W2SourceCallAdmissionV1:
    operation = _w2_admission_operation()
    persistence = W2OperationPersistenceReceiptV1.build(
        operation=operation,
        post_commit_readback_row=operation.to_row(),
        replayed=False,
    )
    return W2SourceCallAdmissionV1.build(
        logical_call_receipt_sha256=logical_call_receipt_sha256,
        raw_authority_persistence_receipt_sha256=_raw_capture_sha256(
            f"runner-persistence:{logical_call_receipt_sha256}".encode()
        ),
        operation=operation,
        persistence_receipt=persistence,
    )


def _recorded_static_attempt(
    pending: PendingRawRequestSuccessV2,
    *,
    parser_input: bytes = b'[[1,"static"]]',
) -> RecordedParserInput:
    response_sha256 = _raw_capture_sha256(parser_input)
    object_sha256 = _raw_capture_sha256(b"recorded-static-object")
    captured = CapturedParserInput(
        representation=STATIC_INPUT_REPRESENTATION,
        response_sha256=response_sha256,
        object_sha256=object_sha256,
        uncompressed_bytes=len(parser_input),
        stored_sha256=_raw_capture_sha256(b"stored-static-packet"),
        stored_bytes=1,
        codec=DEFAULT_CODEC,
        relative_path=(f"blobs/sha256/{object_sha256[:2]}/{object_sha256}.payload.gz"),
    )
    return RecordedParserInput(
        receipt_sha256=pending.private_receipt_sha256,
        transport_kind="static_provider_snapshot",
        source_family="static",
        endpoint_id=pending.attempt.endpoint_id,
        endpoint_slug="static-players",
        parameters_sha256=pending.attempt.safe_parameters_sha256,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256=pending.attempt.endpoint_contract_sha256,
        status_code=None,
        outcome="success_nonempty",
        result_sets=tuple(item.result_set for item in pending.results),
        captured=captured,
        parser_input=parser_input,
    )


def _raw_capture_result_receipt() -> ResultSetReceipt:
    headers = ("version", "request", "time", "code")
    return ResultSetReceipt(
        name="meta",
        provider_index=None,
        canonical_index=0,
        headers_sha256=_raw_capture_sha256(
            json.dumps(list(headers), separators=(",", ":")).encode()
        ),
        row_count=1,
        json_path="$.meta",
        container_kind="nba_api_live_json_object",
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_observation_count=1,
        parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
        observed_field_orders_sha256=_raw_capture_sha256(b"observed-meta-fields"),
        normalized_output_sha256=_raw_capture_sha256(b"normalized-meta-output"),
    )


def _raw_capture_public_context(
    *,
    lane_id: str = "lane-1",
) -> RawRequestCaptureContextV2:
    _, _, provider_request_sha256 = canonical_semantic_parameters(
        "live",
        _RAW_CAPTURE_ENDPOINT_ID,
        {},
    )
    return RawRequestCaptureContextV2(
        provider_authority_sha256=_RAW_CAPTURE_PROVIDER_AUTHORITY_SHA256,
        source_sha=_RAW_CAPTURE_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain-1",
        lane_id=lane_id,
        provider_calls=(
            RawProviderCallContextV2(
                request_ordinal=0,
                semantic_request_sha256=_RAW_CAPTURE_SEMANTIC_REQUEST_SHA256,
                logical_invocation_sha256=(_RAW_CAPTURE_LOGICAL_INVOCATION_SHA256),
                provider_call_role="primary",
                provider_call_ordinal=0,
                source_family="live",
                endpoint_id=_RAW_CAPTURE_ENDPOINT_ID,
                provider_request_sha256=provider_request_sha256,
                endpoint_contract_sha256=(_RAW_CAPTURE_ENDPOINT_CONTRACT_SHA256),
                scope_sha256=_RAW_CAPTURE_SCOPE_SHA256,
            ),
        ),
    )


def _raw_capture_factories(
    tmp_path: Path,
) -> tuple[
    Callable[[str, dict[str, object]], NbaApiCaptureContract],
    Callable[[str, dict[str, object]], RawRequestCaptureContextV2],
    list[BronzeCaptureStore],
]:
    stores: list[BronzeCaptureStore] = []
    logical_call_ordinal = 0

    def private_factory(
        endpoint_name: str,
        params: dict[str, object],
    ) -> NbaApiCaptureContract:
        nonlocal logical_call_ordinal
        assert endpoint_name == _RAW_CAPTURE_ENDPOINT_ID
        assert params == {}
        logical_call_ordinal += 1
        store = BronzeCaptureStore(
            tmp_path / f"private-{logical_call_ordinal}" / "bronze",
            public_roots=(tmp_path / "public",),
            limits=BronzeLimits(
                max_response_bytes=1_000_000,
                max_generation_stored_bytes=2_000_000,
                minimum_free_bytes=1,
            ),
        )
        stores.append(store)
        return NbaApiCaptureContract(
            sink=store,
            context=ParserInputContext(
                attempt_id=f"runner-raw-capture-{logical_call_ordinal}",
                workflow_run_id=101,
                workflow_run_attempt=1,
                chain_id="chain-1",
                lane_id="lane-1",
                semantic_source_sha=_RAW_CAPTURE_SOURCE_SHA,
            ),
            provider_authority_sha256=_RAW_CAPTURE_PROVIDER_AUTHORITY_SHA256,
            endpoint_contract_sha256=_RAW_CAPTURE_ENDPOINT_CONTRACT_SHA256,
        )

    def public_factory(
        endpoint_name: str,
        params: dict[str, object],
    ) -> RawRequestCaptureContextV2:
        assert endpoint_name == _RAW_CAPTURE_ENDPOINT_ID
        assert params == {}
        return _raw_capture_public_context()

    return private_factory, public_factory, stores


def _raw_capture_extractor(
    *,
    failed_attempts: int = 0,
    downstream_failure: bool = False,
    malformed_snapshot: bool = False,
    cross_context_snapshot: bool = False,
    include_capture_issue: bool = False,
):
    state: dict[str, object] = {"attempts": 0, "orders": []}

    class _RawCaptureExtractor(BaseExtractor):
        endpoint_name = _RAW_CAPTURE_ENDPOINT_ID
        category = "default"

        def begin_extraction_attempt(self) -> None:
            cast("list[list[str]]", state["orders"]).append(["begin"])
            super().begin_extraction_attempt()

        def set_logical_request_params(self, params) -> None:
            cast("list[list[str]]", state["orders"])[-1].append("logical")
            super().set_logical_request_params(params)

        def set_raw_request_capture_context(self, context) -> None:
            cast("list[list[str]]", state["orders"])[-1].append("public")
            super().set_raw_request_capture_context(context)

        def set_capture_contract(self, contract) -> None:
            cast("list[list[str]]", state["orders"])[-1].append("private")
            super().set_capture_contract(contract)

        def _perform(self) -> list[pl.DataFrame]:
            state["attempts"] = cast("int", state["attempts"]) + 1
            capture = cast("RawRequestCaptureContract", self._capture_contract)
            request = capture.begin_request()
            if request.retry_ordinal < failed_attempts:
                receipt = capture.sink.record_no_response_attempt(
                    context=request,
                    transport_kind="http_response",
                    source_family="live",
                    endpoint_id=_RAW_CAPTURE_ENDPOINT_ID,
                    endpoint_slug="scoreboard",
                    parameters={},
                    provider_authority_sha256=(_RAW_CAPTURE_PROVIDER_AUTHORITY_SHA256),
                    contract_sha256=_RAW_CAPTURE_ENDPOINT_CONTRACT_SHA256,
                    outcome="transport_failure_no_response",
                    failure_class="transport_transient",
                    root_exception_class="ConnectionError",
                )
                capture.record_receipt(request, receipt, successful=False)
                raise ConnectionError("test-only transient")
            captured = capture.sink.store_parser_input(
                _RAW_CAPTURE_BODY,
                representation=PARSER_INPUT_REPRESENTATION,
            )
            receipt = capture.sink.record_response_attempt(
                context=request,
                transport_kind="http_response",
                source_family="live",
                endpoint_id=_RAW_CAPTURE_ENDPOINT_ID,
                endpoint_slug="scoreboard",
                parameters={},
                provider_authority_sha256=_RAW_CAPTURE_PROVIDER_AUTHORITY_SHA256,
                contract_sha256=_RAW_CAPTURE_ENDPOINT_CONTRACT_SHA256,
                status_code=200,
                captured=captured,
                outcome="success_nonempty",
                failure_class=None,
                root_exception_class=None,
                result_sets=(_raw_capture_result_receipt(),),
            )
            capture.record_receipt(request, receipt, successful=True)
            if downstream_failure:
                exc = ValueError("test-only downstream failure")
                self._mark_raw_request_downstream_incomplete(
                    exc,
                    receipt_sha256=receipt,
                )
                raise exc
            return [pl.DataFrame({"value": [1]}), pl.DataFrame({"value": [2]})]

        async def extract(self, **_params: object) -> pl.DataFrame:
            return self._perform()[0]

        async def extract_all(self, **_params: object) -> list[pl.DataFrame]:
            return self._perform()

        def raw_request_capture_snapshot(self) -> RawRequestCaptureSnapshotV2:
            snapshot = super().raw_request_capture_snapshot()
            assert snapshot is not None
            if malformed_snapshot:
                return cast("RawRequestCaptureSnapshotV2", object())
            if include_capture_issue:
                attempts = (
                    *(item.attempt for item in snapshot.observations),
                    *(item.attempt for item in snapshot.pending_successes),
                )
                assert attempts
                snapshot = replace(
                    snapshot,
                    issues=(
                        RawRequestCaptureIssueV2(
                            code="test_capture_issue",
                            retry_ordinal=attempts[0].retry_ordinal,
                            request_ordinal=attempts[0].request_ordinal,
                            root_exception_class=None,
                        ),
                    ),
                )
            if not cross_context_snapshot or not snapshot.pending_successes:
                return snapshot
            pending = snapshot.pending_successes[0]
            foreign_attempt = pending.attempt.model_copy(update={"lane_id": "foreign-lane"})
            return replace(
                snapshot,
                pending_successes=(replace(pending, attempt=foreign_attempt),),
            )

    return _RawCaptureExtractor, state


def _close_raw_capture_stores(stores: list[BronzeCaptureStore]) -> None:
    for store in stores:
        store.close()


class TestPublicRawRequestCaptureCarry:
    def test_runner_imports_only_v2_public_capture_symbols(self) -> None:
        removed_v1_names = {
            "ParserInputObjectV1",
            "PendingRawRequestSuccessV1",
            "PendingResultOccurrenceV1",
            "RawRequestCaptureContextV1",
            "RawRequestCaptureIssueV1",
            "RawRequestCaptureSnapshotV1",
            "RequestAttemptIdentityV1",
            "RequestObservationV1",
        }

        assert removed_v1_names.isdisjoint(vars(extractor_runner_module))

    def test_w2_admissions_replay_and_bind_in_pending_order(self) -> None:
        snapshot, first_binding, _receipts = _raw_finalization_case("live")
        second_binding = replace(
            first_binding,
            logical_call_receipt_sha256=_raw_capture_sha256(b"second-logical-call"),
        )
        pending = [
            _PendingJournalSuccess(
                endpoint_name=first_binding.endpoint_name,
                params_json="{}",
                rows=1,
                receipt_binding=first_binding,
                raw_request_capture_snapshot=snapshot,
            ),
            _PendingJournalSuccess(
                endpoint_name=second_binding.endpoint_name,
                params_json="{}",
                rows=0,
                receipt_binding=second_binding,
                raw_request_capture_snapshot=snapshot,
            ),
        ]
        supplied = (
            _w2_admission(first_binding.logical_call_receipt_sha256),
            _w2_admission(second_binding.logical_call_receipt_sha256),
        )

        admitted = ExtractorRunner._bind_chunk_w2_admissions(
            pending,
            supplied,
            callback_invoked=True,
            require_w2_operation=True,
        )

        assert tuple(
            item.w2_admission.logical_call_receipt_sha256
            for item in admitted
            if item.w2_admission is not None
        ) == (
            first_binding.logical_call_receipt_sha256,
            second_binding.logical_call_receipt_sha256,
        )
        assert admitted[0].w2_admission == supplied[0]
        assert admitted[0].w2_admission is not supplied[0]
        assert admitted[1].pending.rows == 0

    @pytest.mark.parametrize("callback_result", [None, ()])
    def test_zero_row_w2_success_requires_one_exact_admission(
        self,
        callback_result: tuple[W2SourceCallAdmissionV1, ...] | None,
    ) -> None:
        snapshot, binding, _receipts = _raw_finalization_case("live")
        pending = _PendingJournalSuccess(
            endpoint_name=binding.endpoint_name,
            params_json="{}",
            rows=0,
            receipt_binding=binding,
            raw_request_capture_snapshot=snapshot,
        )

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="returned no|count differs",
        ):
            ExtractorRunner._bind_chunk_w2_admissions(
                [pending],
                callback_result,
                callback_invoked=True,
                require_w2_operation=True,
            )

    def test_w2_failure_only_callback_requires_exact_empty_tuple(self) -> None:
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="failure-only persistence",
        ):
            ExtractorRunner._bind_chunk_w2_admissions(
                [],
                None,
                callback_invoked=True,
                require_w2_operation=True,
            )

        assert (
            ExtractorRunner._bind_chunk_w2_admissions(
                [],
                (),
                callback_invoked=True,
                require_w2_operation=True,
            )
            == ()
        )

    def test_w2_admission_rejects_reorder_alias_and_foreign_before_journal(self) -> None:
        snapshot, first_binding, _receipts = _raw_finalization_case("live")
        second_binding = replace(
            first_binding,
            logical_call_receipt_sha256=_raw_capture_sha256(b"second-logical-call"),
        )
        pending = [
            _PendingJournalSuccess(
                first_binding.endpoint_name,
                "{}",
                1,
                receipt_binding=first_binding,
                raw_request_capture_snapshot=snapshot,
            ),
            _PendingJournalSuccess(
                second_binding.endpoint_name,
                "{}",
                1,
                receipt_binding=second_binding,
                raw_request_capture_snapshot=snapshot,
            ),
        ]
        first = _w2_admission(first_binding.logical_call_receipt_sha256)
        second = _w2_admission(second_binding.logical_call_receipt_sha256)

        with pytest.raises(ParserInputCaptureIntegrityError, match="ordered pending"):
            ExtractorRunner._bind_chunk_w2_admissions(
                pending,
                (second, first),
                callback_invoked=True,
                require_w2_operation=True,
            )
        with pytest.raises(ParserInputCaptureIntegrityError, match="aliased"):
            ExtractorRunner._bind_chunk_w2_admissions(
                pending,
                (first, first),
                callback_invoked=True,
                require_w2_operation=True,
            )
        with pytest.raises(ParserInputCaptureIntegrityError, match="foreign W2"):
            ExtractorRunner._bind_chunk_w2_admissions(
                pending[:1],
                cast("tuple[W2SourceCallAdmissionV1, ...]", (object(),)),
                callback_invoked=True,
                require_w2_operation=True,
            )

    def test_w2_admission_sanitizes_hostile_replay_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        snapshot, binding, _receipts = _raw_finalization_case("live")
        pending = _PendingJournalSuccess(
            binding.endpoint_name,
            "{}",
            1,
            receipt_binding=binding,
            raw_request_capture_snapshot=snapshot,
        )
        admission = _w2_admission(binding.logical_call_receipt_sha256)

        def hostile_replay(_cls: object, _value: object) -> W2SourceCallAdmissionV1:
            raise RuntimeError("HOSTILE_W2_SECRET_SENTINEL")

        monkeypatch.setattr(
            W2SourceCallAdmissionV1,
            "from_canonical_bytes",
            classmethod(hostile_replay),
        )
        with pytest.raises(ParserInputCaptureIntegrityError) as exc_info:
            ExtractorRunner._bind_chunk_w2_admissions(
                [pending],
                (admission,),
                callback_invoked=True,
                require_w2_operation=True,
            )

        assert "HOSTILE_W2_SECRET_SENTINEL" not in str(exc_info.value)

    def test_later_journal_failure_preserves_current_and_remaining_parser_inputs(self) -> None:
        snapshot, first_binding, _receipts = _raw_finalization_case("live")
        second_binding = replace(
            first_binding,
            logical_call_receipt_sha256=_raw_capture_sha256(b"second-logical-call"),
        )
        events: list[str] = []
        pending = [
            _PendingJournalSuccess(
                first_binding.endpoint_name,
                '{"call":1}',
                1,
                receipt_binding=first_binding,
                raw_request_capture_snapshot=snapshot,
                discard_parser_inputs=lambda: events.append("discard-first"),
            ),
            _PendingJournalSuccess(
                second_binding.endpoint_name,
                '{"call":2}',
                1,
                receipt_binding=second_binding,
                raw_request_capture_snapshot=snapshot,
                discard_parser_inputs=lambda: events.append("discard-second"),
            ),
        ]
        admissions = ExtractorRunner._bind_chunk_w2_admissions(
            pending,
            (
                _w2_admission(first_binding.logical_call_receipt_sha256),
                _w2_admission(second_binding.logical_call_receipt_sha256),
            ),
            callback_invoked=True,
            require_w2_operation=True,
        )
        journal = _make_journal()

        def journal_success(
            _endpoint: str,
            params: str,
            _rows: int,
            **_kwargs: object,
        ) -> None:
            events.append(f"journal-{params}")
            if params == '{"call":2}':
                raise RuntimeError("journal unavailable")

        journal.record_success.side_effect = journal_success
        runner = ExtractorRunner(
            _make_registry(_make_extractor()),
            _make_settings(),
            journal,
        )
        try:
            with pytest.raises(RuntimeError, match="journal unavailable"):
                runner._commit_chunk_journal_successes(
                    admissions,
                    PatternExtractionResult(frames={}),
                    discard_parser_inputs=True,
                )
        finally:
            runner.shutdown()

        assert events == [
            'journal-{"call":1}',
            "discard-first",
            'journal-{"call":2}',
        ]
        assert journal.record_success.call_count == 2
        assert all(
            type(call.kwargs["w2_admission"]) is W2SourceCallAdmissionV1
            for call in journal.record_success.call_args_list
        )

    def test_public_capture_factory_requires_private_capture(self) -> None:
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="requires private parser-input capture",
        ):
            ExtractorRunner(
                _make_registry(_make_extractor()),
                _make_settings(),
                _make_journal(),
                raw_request_capture_context_factory=lambda *_args: _raw_capture_public_context(),
            )

    def test_late_public_capture_configuration_is_one_shot_and_preplanning(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, _state = _raw_capture_extractor()
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            _make_journal(),
            capture_contract_factory=private_factory,
        )
        preplanned = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            _make_journal(),
            capture_contract_factory=private_factory,
        )
        no_private = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            _make_journal(),
        )
        try:
            runner.configure_raw_request_capture_context_factory(public_factory)
            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="already configured",
            ):
                runner.configure_raw_request_capture_context_factory(public_factory)

            preplanned.planned_calls = 1
            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="before planning",
            ):
                preplanned.configure_raw_request_capture_context_factory(public_factory)

            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="requires private parser-input capture",
            ):
                no_private.configure_raw_request_capture_context_factory(public_factory)
        finally:
            runner.shutdown()
            preplanned.shutdown()
            no_private.shutdown()
            _close_raw_capture_stores(stores)

    @pytest.mark.asyncio
    async def test_exact_snapshot_reaches_journal_task_and_source_result(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, _state = _raw_capture_extractor()
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        journal = _make_journal()
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            journal,
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=public_factory,
        )

        async def invoke(extractor: BaseExtractor) -> pl.DataFrame:
            return await extractor.extract()

        try:
            journaled = await runner._run_with_journal(
                _RAW_CAPTURE_ENDPOINT_ID,
                "{}",
                params={},
                fn=invoke,
                result_route_ids=(f"{_RAW_CAPTURE_ENDPOINT_ID}:stg_score_board:0",),
                defer_journal_success=True,
                return_failures=True,
            )
            assert isinstance(journaled, _JournaledExtraction)
            snapshot = journaled.raw_request_capture_snapshot
            assert snapshot is not None
            assert snapshot is journaled.success.raw_request_capture_snapshot
            assert snapshot.requires_transactional_finalization
            assert len(snapshot.objects) == len(snapshot.pending_successes) == 1
            assert snapshot.observations == snapshot.issues == ()
            pending = snapshot.pending_successes[0]
            assert type(pending) is PendingRawRequestSuccessV2
            assert pending.logical_receipt_sha256 is None
            assert pending.aggregate_route_ids == ()
            assert not hasattr(pending, "route_landings")
            ExtractorRunner._validate_raw_request_capture_snapshot_shape(snapshot)

            task_result = _ExtractionTaskResult(
                frames={"stg_score_board": cast("pl.DataFrame", journaled.data)},
                pending_success=journaled.success,
                raw_request_capture_snapshot=snapshot,
                source_endpoint_name=_RAW_CAPTURE_ENDPOINT_ID,
                source_params_json="{}",
                expected_staging_keys=("stg_score_board",),
            )
            source_results = runner._source_results_for_persistence(
                [task_result],
                plan_live_snapshot_at=_RAW_CAPTURE_PLAN_SNAPSHOT_AT,
            )
            assert source_results[0]["raw_request_capture_snapshot"] is snapshot
            assert source_results[0]["recorded_static_attempts"] == ()
            assert source_results[0]["plan_live_snapshot_at"] == _RAW_CAPTURE_PLAN_SNAPSHOT_AT
            journal.record_success.assert_not_called()
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)

    def test_selected_static_packet_is_reloaded_and_carried_exactly(self) -> None:
        snapshot, binding, _receipts = _raw_finalization_case("static")
        pending = snapshot.pending_successes[0]
        recorded = _recorded_static_attempt(pending)
        contract = MagicMock()
        contract.sink.load_recorded_attempt.return_value = recorded

        reloaded = ExtractorRunner._recorded_static_attempts_for_snapshot(
            snapshot,
            cast("NbaApiCaptureContract", contract),
        )
        assert reloaded == (recorded,)
        contract.sink.load_recorded_attempt.assert_called_once_with(pending.private_receipt_sha256)

        success = _PendingJournalSuccess(
            endpoint_name=binding.endpoint_name,
            params_json="{}",
            rows=recorded.result_sets[0].row_count,
            receipt_binding=binding,
            raw_request_capture_snapshot=snapshot,
            recorded_static_attempts=reloaded,
        )
        source = ExtractorRunner._source_results_for_persistence(
            [
                _ExtractionTaskResult(
                    frames={},
                    pending_success=success,
                    raw_request_capture_snapshot=snapshot,
                    source_endpoint_name=binding.endpoint_name,
                    source_params_json="{}",
                    expected_staging_keys=(),
                )
            ]
        )[0]
        assert source["recorded_static_attempts"] is success.recorded_static_attempts

    def test_selected_static_packet_rejects_mutated_exact_bytes(self) -> None:
        snapshot, _binding, _receipts = _raw_finalization_case("static")
        recorded = _recorded_static_attempt(snapshot.pending_successes[0])
        contract = MagicMock()
        contract.sink.load_recorded_attempt.return_value = replace(
            recorded,
            parser_input=recorded.parser_input + b" ",
        )

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="differs from its exact capture authority",
        ):
            ExtractorRunner._recorded_static_attempts_for_snapshot(
                snapshot,
                cast("NbaApiCaptureContract", contract),
            )

    @pytest.mark.asyncio
    async def test_snapshot_admission_rejects_forged_attempt_and_terminal_authority(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, _state = _raw_capture_extractor()
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            _make_journal(),
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=public_factory,
        )

        async def invoke(extractor: BaseExtractor) -> pl.DataFrame:
            return await extractor.extract()

        try:
            journaled = await runner._run_with_journal(
                _RAW_CAPTURE_ENDPOINT_ID,
                "{}",
                params={},
                fn=invoke,
                result_route_ids=(f"{_RAW_CAPTURE_ENDPOINT_ID}:stg_score_board:0",),
                defer_journal_success=True,
                return_failures=True,
            )
            assert isinstance(journaled, _JournaledExtraction)
            snapshot = journaled.raw_request_capture_snapshot
            assert snapshot is not None
            pending = snapshot.pending_successes[0]

            forged_attempt = pending.attempt.model_copy(deep=True)
            object.__setattr__(forged_attempt, "attempt_sha256", "f" * 64)
            forged_snapshot = replace(
                snapshot,
                pending_successes=(replace(pending, attempt=forged_attempt),),
            )
            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="invalid attempt authority",
            ):
                ExtractorRunner._validate_raw_request_capture_snapshot_shape(forged_snapshot)

            assert pending.body_object is not None
            terminal = RequestObservationV2.build(
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
                result_occurrence_sha256s=("a" * 64,),
                route_landing_sha256s=("b" * 64,),
                capture_response_receipt_sha256=pending.private_receipt_sha256,
                logical_receipt_sha256="c" * 64,
            )
            terminal_snapshot = replace(
                snapshot,
                observations=(terminal,),
                pending_successes=(),
            )
            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="cannot self-seal a terminal",
            ):
                ExtractorRunner._validate_raw_request_capture_snapshot_shape(terminal_snapshot)

            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="exact V2 DTO",
            ):
                ExtractorRunner._validate_raw_request_capture_snapshot_shape(
                    cast("RawRequestCaptureSnapshotV2", object())
                )
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)

    @pytest.mark.asyncio
    async def test_retry_aggregates_failed_attempt_and_pending_success_before_journal(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, state = _raw_capture_extractor(failed_attempts=1)
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        journal = _make_journal()
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(extract_max_retries=1),
            journal,
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=public_factory,
        )
        persisted: list[RawRequestCaptureSnapshotV2] = []

        def persist_chunk(
            _frames: dict[str, pl.DataFrame],
            *,
            source_results: list[dict[str, object]],
        ) -> tuple[W2SourceCallAdmissionV1, ...]:
            journal.record_success.assert_not_called()
            assert len(source_results) == 1
            snapshot = source_results[0]["raw_request_capture_snapshot"]
            assert isinstance(snapshot, RawRequestCaptureSnapshotV2)
            persisted.append(snapshot)
            binding = source_results[0]["receipt_binding"]
            assert type(binding) is LogicalCallReceiptBinding
            return (_w2_admission(binding.logical_call_receipt_sha256),)

        entry = StagingEntry(
            _RAW_CAPTURE_ENDPOINT_ID,
            "stg_score_board",
            "live",
        )
        try:
            result = await runner.run_pattern_result(
                "live",
                [{}],
                [entry],
                persist_chunk_results=persist_chunk,
                required_route_ids=(f"{_RAW_CAPTURE_ENDPOINT_ID}:stg_score_board:0",),
                snapshot_at=_RAW_CAPTURE_PLAN_SNAPSHOT_AT,
            )

            assert result.success_count == 1
            assert state["attempts"] == 2
            assert state["orders"] == [
                ["begin", "logical", "public", "private"],
                ["begin", "logical", "public", "private"],
            ]
            assert len(persisted) == 1
            snapshot = persisted[0]
            assert len(snapshot.objects) == 1
            assert [item.attempt.retry_ordinal for item in snapshot.observations] == [0]
            assert snapshot.observations[0].lifecycle == "incomplete"
            assert snapshot.observations[0].outcome == "transport_failure_no_response"
            assert [item.attempt.retry_ordinal for item in snapshot.pending_successes] == [1]
            assert snapshot.pending_successes[0].logical_receipt_sha256 is None
            assert snapshot.pending_successes[0].aggregate_route_ids == ()
            assert all(
                observation.lifecycle != "selected_terminal"
                for observation in snapshot.observations
            )
            assert snapshot.issues == ()
            assert result.raw_request_capture_snapshot == snapshot
            assert runner.raw_request_capture_snapshot() == snapshot
            journal.record_success.assert_called_once()
            journal.record_start.assert_called_once_with(
                _RAW_CAPTURE_ENDPOINT_ID,
                "{}",
                require_receipt=True,
                require_w2_operation=True,
            )
            journal.was_extracted_batch.assert_called_once_with(
                [(_RAW_CAPTURE_ENDPOINT_ID, "{}")],
                require_receipt=True,
                require_w2_operation=True,
            )
            assert (
                type(journal.record_success.call_args.kwargs["w2_admission"])
                is W2SourceCallAdmissionV1
            )
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)

    @pytest.mark.asyncio
    async def test_terminal_failure_preserves_every_attempt_snapshot(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, state = _raw_capture_extractor(
            failed_attempts=3,
            include_capture_issue=True,
        )
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        journal = _make_journal()
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(extract_max_retries=1),
            journal,
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=public_factory,
        )
        entry = StagingEntry(
            _RAW_CAPTURE_ENDPOINT_ID,
            "stg_score_board",
            "live",
        )
        try:
            result = await runner.run_pattern_result("live", [{}], [entry])

            assert result.failure_count == 1
            assert state["attempts"] == 2
            snapshot = result.raw_request_capture_snapshot
            assert snapshot is not None
            assert snapshot.objects == snapshot.pending_successes == ()
            assert [item.attempt.retry_ordinal for item in snapshot.observations] == [0, 1]
            assert {item.outcome for item in snapshot.observations} == {
                "transport_failure_no_response"
            }
            assert all(type(item) is RequestObservationV2 for item in snapshot.observations)
            assert all(item.lifecycle == "incomplete" for item in snapshot.observations)
            assert all(item.route_landing_count == 0 for item in snapshot.observations)
            assert [item.retry_ordinal for item in snapshot.issues] == [0, 1]
            assert runner.raw_request_capture_snapshot() == snapshot
            journal.record_success.assert_not_called()
            journal.record_failure.assert_called_once()
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)

    @pytest.mark.asyncio
    async def test_downstream_failure_preserves_exact_incomplete_body_observation(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, state = _raw_capture_extractor(downstream_failure=True)
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            _make_journal(),
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=public_factory,
        )
        entry = StagingEntry(
            _RAW_CAPTURE_ENDPOINT_ID,
            "stg_score_board",
            "live",
        )
        try:
            result = await runner.run_pattern_result("live", [{}], [entry])

            assert state["attempts"] == 1
            assert result.failure_count == 1
            snapshot = result.raw_request_capture_snapshot
            assert snapshot is not None
            assert snapshot.pending_successes == snapshot.issues == ()
            assert len(snapshot.objects) == len(snapshot.observations) == 1
            observation = snapshot.observations[0]
            assert type(observation) is RequestObservationV2
            assert observation.lifecycle == "incomplete"
            assert observation.outcome == "downstream_incomplete"
            assert observation.body_disposition == "public_parser_input"
            assert observation.body_object_sha256 == snapshot.objects[0].object_sha256
            assert observation.result_occurrence_count == 0
            assert observation.route_landing_count == 0
            assert observation.logical_receipt_sha256 is None
            ExtractorRunner._validate_raw_request_capture_snapshot_shape(snapshot)
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)

    @pytest.mark.asyncio
    async def test_terminal_failure_callback_receives_snapshot_without_frames(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, state = _raw_capture_extractor(failed_attempts=3)
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        journal = _make_journal()
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(extract_max_retries=1),
            journal,
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=public_factory,
        )
        persisted: list[RawRequestCaptureSnapshotV2] = []

        def persist_failure(
            frames: dict[str, pl.DataFrame],
            *,
            failure_raw_request_capture_snapshots: tuple[
                RawRequestCaptureSnapshotV2,
                ...,
            ],
        ) -> tuple[W2SourceCallAdmissionV1, ...]:
            assert frames == {}
            journal.record_success.assert_not_called()
            assert len(failure_raw_request_capture_snapshots) == 1
            persisted.extend(failure_raw_request_capture_snapshots)
            return ()

        entry = StagingEntry(
            _RAW_CAPTURE_ENDPOINT_ID,
            "stg_score_board",
            "live",
        )
        try:
            result = await runner.run_pattern_result(
                "live",
                [{}],
                [entry],
                persist_chunk_results=persist_failure,
            )

            assert state["attempts"] == 2
            assert result.failure_count == 1
            assert len(persisted) == 1
            assert [item.attempt.retry_ordinal for item in persisted[0].observations] == [0, 1]
            assert persisted[0].pending_successes == ()
            journal.record_success.assert_not_called()
            journal.record_failure.assert_called_once()
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)

    @pytest.mark.asyncio
    async def test_multi_result_carries_one_call_snapshot_without_cross_result_copy(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, state = _raw_capture_extractor()
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        journal = _make_journal()
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            journal,
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=public_factory,
        )
        persisted_sources: list[list[dict[str, object]]] = []

        def persist_chunk(
            _frames: dict[str, pl.DataFrame],
            *,
            source_results: list[dict[str, object]],
        ) -> tuple[W2SourceCallAdmissionV1, ...]:
            journal.record_success.assert_not_called()
            persisted_sources.append(source_results)
            binding = source_results[0]["receipt_binding"]
            assert type(binding) is LogicalCallReceiptBinding
            return (_w2_admission(binding.logical_call_receipt_sha256),)

        entries = [
            StagingEntry(
                _RAW_CAPTURE_ENDPOINT_ID,
                "stg_score_board",
                "live",
                result_set_index=0,
                use_multi=True,
            ),
            StagingEntry(
                _RAW_CAPTURE_ENDPOINT_ID,
                "stg_score_board_extra",
                "live",
                result_set_index=1,
                use_multi=True,
            ),
        ]
        try:
            with patch(
                "nbadb.orchestrate.extractor_runner.get_multi_entries",
                return_value={_RAW_CAPTURE_ENDPOINT_ID: entries},
            ):
                result = await runner.run_pattern_result(
                    "live",
                    [{}],
                    entries,
                    persist_chunk_results=persist_chunk,
                    required_route_ids=(
                        f"{_RAW_CAPTURE_ENDPOINT_ID}:stg_score_board:0",
                        f"{_RAW_CAPTURE_ENDPOINT_ID}:stg_score_board_extra:1",
                    ),
                    snapshot_at=_RAW_CAPTURE_PLAN_SNAPSHOT_AT,
                )

            assert result.success_count == 1
            assert state["attempts"] == 1
            assert len(persisted_sources) == 1
            assert len(persisted_sources[0]) == 1
            source = persisted_sources[0][0]
            assert source["expected_staging_keys"] == (
                "stg_score_board",
                "stg_score_board_extra",
            )
            snapshot = source["raw_request_capture_snapshot"]
            assert isinstance(snapshot, RawRequestCaptureSnapshotV2)
            assert len(snapshot.pending_successes) == 1
            assert snapshot.pending_successes[0].attempt.request_ordinal == 0
            journal.record_success.assert_called_once()
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("malformed_snapshot", "cross_context_snapshot"),
        [(True, False), (False, True)],
    )
    async def test_malformed_or_cross_context_snapshot_fails_before_journal_success(
        self,
        tmp_path: Path,
        malformed_snapshot: bool,
        cross_context_snapshot: bool,
    ) -> None:
        extractor_cls, state = _raw_capture_extractor(
            malformed_snapshot=malformed_snapshot,
            cross_context_snapshot=cross_context_snapshot,
        )
        private_factory, public_factory, stores = _raw_capture_factories(tmp_path)
        journal = _make_journal()
        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            journal,
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=public_factory,
        )
        entry = StagingEntry(
            _RAW_CAPTURE_ENDPOINT_ID,
            "stg_score_board",
            "live",
        )
        try:
            result = await runner.run_pattern_result("live", [{}], [entry])

            assert state["attempts"] == 1
            assert result.failure_count == 1
            assert result.success_count == 0
            journal.record_success.assert_not_called()
            assert journal.record_failure.call_args.args[2] == ("ParserInputCaptureIntegrityError")
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)

    @pytest.mark.asyncio
    async def test_missing_context_factory_result_blocks_provider_work(
        self,
        tmp_path: Path,
    ) -> None:
        extractor_cls, state = _raw_capture_extractor()
        private_factory, _public_factory, stores = _raw_capture_factories(tmp_path)
        journal = _make_journal()

        def missing_context(
            _endpoint_name: str,
            _params: dict[str, object],
        ) -> RawRequestCaptureContextV2:
            return cast("RawRequestCaptureContextV2", None)

        runner = ExtractorRunner(
            _make_registry(extractor_cls),
            _make_settings(),
            journal,
            capture_contract_factory=private_factory,
            raw_request_capture_context_factory=missing_context,
        )
        entry = StagingEntry(
            _RAW_CAPTURE_ENDPOINT_ID,
            "stg_score_board",
            "live",
        )
        try:
            result = await runner.run_pattern_result("live", [{}], [entry])

            assert state["attempts"] == 0
            assert result.failure_count == 1
            journal.record_success.assert_not_called()
            assert journal.record_failure.call_args.args[2] == ("ParserInputCaptureIntegrityError")
        finally:
            runner.shutdown()
            _close_raw_capture_stores(stores)


class TestSyncExtractBoundary:
    def test_wraps_retryable_errors_as_transient(self):
        class _Ext:
            endpoint_name = "ep1"

            async def extract(self, **kwargs):
                raise ConnectionError("boom")

        with pytest.raises(TransientError, match="ep1: transient extraction failure"):
            _sync_extract(_Ext())

    def test_wraps_non_retryable_errors_as_extraction(self):
        class _Ext:
            endpoint_name = "ep1"

            async def extract(self, **kwargs):
                raise RuntimeError("boom")

        with pytest.raises(ExtractionError, match="ep1: extraction failed"):
            _sync_extract(_Ext())

    def test_preserves_existing_taxonomy_errors(self):
        class _Ext:
            endpoint_name = "ep1"

            async def extract(self, **kwargs):
                raise NbaDbValidationError("already translated")

        with pytest.raises(NbaDbValidationError, match="already translated"):
            _sync_extract(_Ext())


# ---------------------------------------------------------------------------
# _extract_single tests
# ---------------------------------------------------------------------------


class TestExtractSingle:
    @pytest.mark.asyncio
    async def test_skip_when_already_extracted(self):
        journal = _make_journal(already_done=True)
        settings = _make_settings()
        registry = _make_registry(_make_extractor())
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})
        assert result is None
        journal.was_extracted.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_data_on_success(self):
        df = pl.DataFrame({"a": [1, 2, 3]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})
        assert isinstance(result, dict)
        assert "stg_ep1" in result
        assert result["stg_ep1"].shape[0] == 3
        journal.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_records_failure_with_type_name(self):
        """HR-A-001: record_failure should use the translated error type, not str(exc)."""
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(exc=ConnectionError("proxy://secret:1234")))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})
        assert result is None
        call_args = journal.record_failure.call_args
        error_msg = call_args[0][2]
        assert error_msg == "ConnectionError"
        assert "secret" not in error_msg

    @pytest.mark.asyncio
    async def test_retries_on_transient_error(self):
        """Retry transient errors up to extract_max_retries times."""
        call_count = 0
        df = pl.DataFrame({"a": [1]})

        class _FlakyExt:
            endpoint_name = "ep1"
            category = "default"

            async def extract(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("transient")
                return df

        journal = _make_journal(already_done=False)
        settings = _make_settings(extract_max_retries=3, extract_retry_base_delay=0.0)
        registry = MagicMock()
        registry.get.return_value = _FlakyExt
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})
        assert result is not None
        assert call_count == 3  # 2 failures + 1 success
        journal.record_success.assert_called_once()
        journal.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_endpoint_returns_none(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = MagicMock()
        registry.get.side_effect = KeyError("no such endpoint")
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("missing_ep", "stg_missing", "season")
        result = await runner._extract_single(entry, {})
        assert result is None


# ---------------------------------------------------------------------------
# _extract_multi tests
# ---------------------------------------------------------------------------


class TestExtractMulti:
    @pytest.mark.asyncio
    async def test_skip_when_already_extracted(self):
        """HR-A-010: Single was_extracted check for the endpoint+params."""
        journal = _make_journal(already_done=True)
        settings = _make_settings()
        registry = _make_registry(_make_extractor())
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry("ep_multi", "stg_b", "season", result_set_index=1, use_multi=True),
        ]
        result = await runner._extract_multi("ep_multi", entries, {"season": "2024-25"})
        assert result is None
        assert journal.was_extracted.call_count == 1

    @pytest.mark.asyncio
    async def test_fans_out_result_sets(self):
        df0 = pl.DataFrame({"x": [1]})
        df1 = pl.DataFrame({"y": [2, 3]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(dfs=[df0, df1]))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry("ep_multi", "stg_b", "season", result_set_index=1, use_multi=True),
        ]
        result = await runner._extract_multi("ep_multi", entries, {"season": "2024-25"})
        assert isinstance(result, dict)
        assert result["stg_a"].shape[0] == 1
        assert result["stg_b"].shape[0] == 2

    @pytest.mark.asyncio
    async def test_records_failure_with_type_name(self):
        """HR-A-001: multi-path record_failure uses the translated type name."""
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(exc=TimeoutError("proxy://secret:9999")))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
        ]
        result = await runner._extract_multi("ep_multi", entries, {"season": "2024-25"})
        assert result is None
        error_msg = journal.record_failure.call_args[0][2]
        assert error_msg == "TimeoutError"
        assert "secret" not in error_msg

    @pytest.mark.asyncio
    async def test_required_out_of_range_index_fails(self):
        df0 = pl.DataFrame({"x": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(dfs=[df0]))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry("ep_multi", "stg_b", "season", result_set_index=5, use_multi=True),
        ]
        result = await runner._extract_multi_result("ep_multi", entries, {})
        assert result is not None
        assert isinstance(result, _FailedExtraction)
        assert result.status == "unexpected"
        assert result.error == "MissingRequiredResultSet:stg_b:5"
        journal.record_failure.assert_called_with(
            "ep_multi",
            "{}",
            "MissingRequiredResultSet:stg_b:5",
        )

    @pytest.mark.asyncio
    async def test_optional_out_of_range_index_returns_empty_df_without_warning(self):
        df0 = pl.DataFrame({"x": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(dfs=[df0]))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry(
                "ep_multi",
                "stg_optional",
                "season",
                result_set_index=5,
                use_multi=True,
                allow_missing_result_set=True,
            ),
        ]
        with patch("nbadb.orchestrate.extractor_runner.logger.warning") as warning:
            result = await runner._extract_multi("ep_multi", entries, {})

        assert isinstance(result, dict)
        assert result["stg_a"].shape[0] == 1
        assert result["stg_optional"].is_empty()
        warning.assert_not_called()


# ---------------------------------------------------------------------------
# run_pattern tests
# ---------------------------------------------------------------------------


class TestRunPattern:
    @pytest.mark.asyncio
    async def test_run_pattern_single_entries(self):
        df = pl.DataFrame({"col": [10, 20]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern("season", [{"season": "2024-25"}], [entry])
        assert "stg_ep1" in result
        assert result["stg_ep1"].shape[0] == 2

    @pytest.mark.asyncio
    async def test_run_pattern_empty_params_returns_empty(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor())
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern("season", [], [entry])
        assert "stg_ep1" not in result or result.get("stg_ep1", pl.DataFrame()).is_empty()

    @pytest.mark.asyncio
    async def test_run_pattern_tolerates_schema_drift_across_param_sets(self):
        class _SchemaDriftExtractor:
            category = "default"

            async def extract(self, **kwargs):
                season = kwargs.get("season")
                if season == "2024-25":
                    return pl.DataFrame({"a": [1], "b": [2]})
                return pl.DataFrame({"a": [3], "c": [4]})

        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_SchemaDriftExtractor)
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern(
            "season",
            [{"season": "2024-25"}, {"season": "2025-26"}],
            [entry],
        )

        assert "stg_ep1" in result
        assert result["stg_ep1"].shape[0] == 2
        assert set(result["stg_ep1"].columns) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_run_pattern_explicit_skip_does_not_increment_journal_skip_counter(self):
        df = pl.DataFrame({"col": [10, 20]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            [entry],
            skip_items={("ep1", '{"season": "2024-25"}')},
        )

        assert result.get("stg_ep1", pl.DataFrame()).is_empty()
        assert runner.skipped == 1
        assert runner.skipped_due_to_journal == 0

    @pytest.mark.asyncio
    async def test_run_pattern_result_treats_explicit_retry_skip_as_complete(self):
        df = pl.DataFrame({"col": [10, 20]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern_result(
            "season",
            [{"season": "2024-25"}],
            [entry],
            skip_items={("ep1", '{"season": "2024-25"}')},
        )

        assert result.is_complete
        assert result.retry_skip_count == 1
        assert result.failure_count == 0

    @pytest.mark.asyncio
    async def test_run_pattern_persists_chunk_before_journal_success(self):
        class _SeasonEchoExtractor:
            category = "default"

            async def extract(self, **kwargs):
                return pl.DataFrame({"season": [kwargs["season"]]})

        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_SeasonEchoExtractor)
        runner = ExtractorRunner(registry, settings, journal)
        persist_events: list[str] = []

        def persist_chunk(frames: dict[str, pl.DataFrame]) -> None:
            assert journal.record_success.call_count == len(persist_events)
            persist_events.append(frames["stg_ep1"]["season"].item())

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern(
            "season",
            [{"season": "2024-25"}, {"season": "2025-26"}],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert persist_events == ["2024-25", "2025-26"]
        assert result["stg_ep1"].shape[0] == 2
        assert journal.record_success.call_count == 2

    @pytest.mark.asyncio
    async def test_run_pattern_passes_source_results_for_single_entries(self):
        df = pl.DataFrame({"season": ["2024-25"]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)
        captured_sources: list[list[dict[str, object]]] = []

        def persist_chunk(
            frames: dict[str, pl.DataFrame],
            *,
            expected_staging_keys: list[str],
            source_results: list[dict[str, object]],
        ) -> None:
            captured_sources.append(source_results)
            assert expected_staging_keys == ["stg_ep1"]
            source_frames = cast("dict[str, pl.DataFrame]", source_results[0]["frames"])
            assert source_frames["stg_ep1"].equals(frames["stg_ep1"])

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert len(captured_sources) == 1
        assert captured_sources[0][0]["source_endpoint_name"] == "ep1"
        assert captured_sources[0][0]["source_params_json"] == '{"season": "2024-25"}'
        assert captured_sources[0][0]["expected_staging_keys"] == ("stg_ep1",)
        source_frames = cast("dict[str, pl.DataFrame]", captured_sources[0][0]["frames"])
        assert source_frames["stg_ep1"].equals(df)
        journal.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_pattern_passes_source_results_for_multi_endpoint(self):
        df0 = pl.DataFrame({"a": [1]})
        df1 = pl.DataFrame({"b": [2]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(dfs=[df0, df1]))
        runner = ExtractorRunner(registry, settings, journal)
        captured_sources: list[list[dict[str, object]]] = []

        def persist_chunk(
            _frames: dict[str, pl.DataFrame],
            *,
            source_results: list[dict[str, object]],
        ) -> None:
            captured_sources.append(source_results)

        entries = [
            StagingEntry("schedule", "stg_schedule", "season", result_set_index=0, use_multi=True),
            StagingEntry(
                "schedule",
                "stg_schedule_weeks",
                "season",
                result_set_index=1,
                use_multi=True,
            ),
        ]
        await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            entries,
            persist_chunk_results=persist_chunk,
        )

        assert len(captured_sources) == 1
        assert captured_sources[0][0]["source_endpoint_name"] == "schedule"
        assert captured_sources[0][0]["source_params_json"] == '{"season": "2024-25"}'
        assert captured_sources[0][0]["expected_staging_keys"] == (
            "stg_schedule",
            "stg_schedule_weeks",
        )
        source_frames = cast("dict[str, pl.DataFrame]", captured_sources[0][0]["frames"])
        assert source_frames["stg_schedule"].equals(df0)
        assert source_frames["stg_schedule_weeks"].equals(df1)
        journal.record_success.assert_called_once()

    def test_source_results_for_persistence_requires_source_identity(self):
        result = _ExtractionTaskResult(
            frames={"stg_ep1": pl.DataFrame({"a": [1]})},
            pending_success=_PendingJournalSuccess("ep1", "{}", 1),
        )

        with pytest.raises(RuntimeError, match="missing source identity"):
            ExtractorRunner._source_results_for_persistence([result])

    @pytest.mark.asyncio
    async def test_run_pattern_does_not_mark_success_when_chunk_persist_fails(self):
        df = pl.DataFrame({"col": [10, 20]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        def fail_persist(_frames: dict[str, pl.DataFrame]) -> None:
            raise RuntimeError("staging unavailable")

        entry = StagingEntry("ep1", "stg_ep1", "season")
        with pytest.raises(RuntimeError, match="staging unavailable"):
            await runner.run_pattern(
                "season",
                [{"season": "2024-25"}],
                [entry],
                persist_chunk_results=fail_persist,
            )

        journal.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_pattern_persists_empty_chunk_before_journal_success(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(df=pl.DataFrame()))
        runner = ExtractorRunner(registry, settings, journal)
        persist_events: list[list[str]] = []

        def persist_chunk(
            frames: dict[str, pl.DataFrame],
            *,
            expected_staging_keys: list[str],
        ) -> None:
            assert frames == {}
            assert journal.record_success.call_count == 0
            persist_events.append(expected_staging_keys)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert persist_events == [["stg_ep1"]]
        assert result.get("stg_ep1", pl.DataFrame()).is_empty()
        journal.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_pattern_filters_chunk_metadata_for_callback_signature(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(df=pl.DataFrame({"season": ["2024-25"]})))
        runner = ExtractorRunner(registry, settings, journal)
        chunk_indexes: list[int] = []

        def persist_chunk(
            frames: dict[str, pl.DataFrame],
            *,
            chunk_index: int,
        ) -> None:
            assert "stg_ep1" in frames
            chunk_indexes.append(chunk_index)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert chunk_indexes == [0]

    @pytest.mark.asyncio
    async def test_deferred_multi_replay_preserves_eligible_entry_subset(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor())
        runner = ExtractorRunner(registry, settings, journal)
        active = StagingEntry("ep_multi", "stg_active", "season", use_multi=True)
        filtered = StagingEntry("ep_multi", "stg_filtered", "season", use_multi=True)
        captured_entries: list[list[StagingEntry]] = []

        async def _capture_extract_multi_result(
            endpoint_name,
            entries,
            params,
            **kwargs,
        ):
            captured_entries.append(entries)
            return {}

        runner._extract_multi_result = cast("Any", _capture_extract_multi_result)

        await runner._replay_deferred_chunk(
            [
                _DeferredExtraction(
                    endpoint_name="ep_multi",
                    params={"season": "2024-25"},
                    wait_seconds=0,
                    eligible_staging_keys=("stg_active",),
                )
            ],
            single_by_key={},
            multi_by_ep={"ep_multi": [active, filtered]},
            on_progress=None,
            defer_journal_success=False,
        )

        assert captured_entries == [[active]]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("endpoint_name", "staging_key"),
        [
            ("scoreboard_v2", "stg_scoreboard"),
            ("scoreboard_v3", "stg_scoreboard_v3_metadata"),
        ],
    )
    async def test_run_pattern_replays_retryable_scoreboard_date_after_cooldown(
        self, endpoint_name: str, staging_key: str
    ):
        call_count = 0
        df = pl.DataFrame({"col": [10, 20]})

        class _ScoreboardExt:
            category = "game_log"

            async def extract_all(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("transient")
                return [df]

        journal = _make_journal(already_done=False)
        settings = _make_settings(extract_max_retries=0, extract_retry_base_delay=0.0)
        registry = _make_registry(_ScoreboardExt)
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry(
            endpoint_name,
            staging_key,
            "date",
            result_set_index=0,
            use_multi=True,
        )
        with patch(
            "nbadb.orchestrate.extractor_runner.asyncio.sleep",
            new=AsyncMock(),
        ) as mock_sleep:
            result = await runner.run_pattern("date", [{"game_date": "02/11/1968"}], [entry])

        assert result[staging_key].shape[0] == 2
        assert call_count == 2
        assert runner.failed_current_run == 0
        journal.record_success.assert_called_once()
        journal.record_failure.assert_not_called()
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("endpoint_name", "staging_key"),
        [
            ("scoreboard_v2", "stg_scoreboard"),
            ("scoreboard_v3", "stg_scoreboard_v3_metadata"),
        ],
    )
    async def test_run_pattern_final_late_recovery_failure_records_once(
        self, endpoint_name: str, staging_key: str
    ):
        call_count = 0

        class _ScoreboardExt:
            category = "game_log"

            async def extract_all(self, **kwargs):
                nonlocal call_count
                call_count += 1
                raise ConnectionError("still transient")

        journal = _make_journal(already_done=False)
        settings = _make_settings(extract_max_retries=0, extract_retry_base_delay=0.0)
        registry = _make_registry(_ScoreboardExt)
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry(
            endpoint_name,
            staging_key,
            "date",
            result_set_index=0,
            use_multi=True,
        )
        with patch(
            "nbadb.orchestrate.extractor_runner.asyncio.sleep",
            new=AsyncMock(),
        ) as mock_sleep:
            result = await runner.run_pattern("date", [{"game_date": "02/11/1968"}], [entry])

        assert result == {}
        assert call_count == 2
        assert runner.failed_current_run == 1
        journal.record_success.assert_not_called()
        journal.record_failure.assert_called_once_with(
            endpoint_name,
            '{"game_date": "02/11/1968"}',
            "ConnectionError",
        )
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    async def test_non_scoreboard_date_failure_does_not_defer(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(extract_max_retries=0, extract_retry_base_delay=0.0)
        registry = _make_registry(_make_extractor(exc=ConnectionError("boom")))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("video_status", "stg_video_status", "date")
        with patch(
            "nbadb.orchestrate.extractor_runner.asyncio.sleep",
            new=AsyncMock(),
        ) as mock_sleep:
            result = await runner.run_pattern("date", [{"game_date": "02/11/1968"}], [entry])

        assert result == {}
        assert runner.failed_current_run == 1
        journal.record_failure.assert_called_once_with(
            "video_status",
            '{"game_date": "02/11/1968"}',
            "ConnectionError",
        )
        mock_sleep.assert_not_awaited()


# ---------------------------------------------------------------------------
# _AdaptiveThrottle tests
# ---------------------------------------------------------------------------


class TestAdaptiveThrottle:
    def test_initial_rate_equals_base(self):
        t = _AdaptiveThrottle(base_rate=10.0)
        assert t.current_rate == 10.0

    def test_failure_reduces_rate(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0)
        new_rate = t.record_failure()
        assert new_rate is not None
        assert new_rate < 10.0
        assert t.current_rate == pytest.approx(7.0, abs=0.01)

    def test_multiple_failures_converge_to_min(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0)
        for _ in range(50):
            t.record_failure()
        assert t.current_rate == pytest.approx(1.0, abs=0.01)

    def test_recovery_after_sustained_success(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0, recovery_threshold=5)
        # Drive rate down
        for _ in range(5):
            t.record_failure()
        low_rate = t.current_rate
        assert low_rate < 10.0
        # Recover
        for _ in range(5):
            t.record_success()
        assert t.current_rate > low_rate

    def test_recovery_does_not_exceed_base_rate(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0, recovery_threshold=3)
        # Small dip then lots of recovery
        t.record_failure()
        for _ in range(100):
            t.record_success()
        assert t.current_rate <= 10.0

    def test_failure_resets_consecutive_success(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0, recovery_threshold=5)
        t.record_failure()  # drop rate
        for _ in range(4):
            t.record_success()
        rate_before = t.current_rate
        t.record_failure()  # resets consecutive counter
        for _ in range(4):
            t.record_success()
        # Should NOT have recovered since we never hit 5 consecutive
        assert t.current_rate <= rate_before

    def test_no_rate_change_returns_none_on_success(self):
        t = _AdaptiveThrottle(base_rate=10.0, recovery_threshold=50)
        # At base rate, no change expected
        result = t.record_success()
        assert result is None


class TestAdaptiveThrottleIntegration:
    @pytest.mark.asyncio
    async def test_runner_backs_off_on_failure(self):
        """Verify the runner replaces its rate limiter after extraction failure."""
        journal = _make_journal(already_done=False)
        settings = _make_settings(adaptive_rate_recovery=5)
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)

        original_limiter = runner._rate_limiter
        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner._extract_single(entry, {"season": "2024-25"})

        # Rate limiter should have been replaced with a slower one
        assert runner._rate_limiter is not original_limiter
        assert runner._adaptive.current_rate < 10.0

    @pytest.mark.asyncio
    async def test_prepare_extractor_sets_endpoint_timeout_override(self):
        class _Ext(BaseExtractor):
            endpoint_name = "ep1"
            category = "default"

            async def extract(self, **kwargs):
                return pl.DataFrame({"timeout": [self._request_timeout_override]})

        journal = _make_journal(already_done=False)
        settings = _make_settings(endpoint_request_timeouts={"ep1": 45})
        registry = MagicMock()
        registry.get.return_value = _Ext
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})

        assert isinstance(result, dict)
        assert result["stg_ep1"]["timeout"][0] == 45

    @pytest.mark.asyncio
    async def test_runner_recovers_after_sustained_success(self):
        """Verify the runner increases rate after consecutive successes."""
        df = pl.DataFrame({"a": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(adaptive_rate_recovery=3)
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)

        # First: drive rate down
        runner._adaptive.record_failure()
        runner._adaptive.record_failure()
        low_rate = runner._adaptive.current_rate

        # Now: run 3 successful extractions to trigger recovery
        for i in range(3):
            entry = StagingEntry(f"ep{i}", f"stg_ep{i}", "season")
            await runner._extract_single(entry, {"season": "2024-25"})

        assert runner._adaptive.current_rate > low_rate

    @pytest.mark.asyncio
    async def test_isolated_endpoint_failure_does_not_back_off_global_rate(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(endpoint_rate_limits={"ep1": 2.0})
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)
        original_limiter = runner._rate_limiter

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner._extract_single(entry, {"season": "2024-25"})

        assert runner._rate_limiter is original_limiter
        assert runner._adaptive.current_rate == 10.0

    @pytest.mark.asyncio
    async def test_isolated_endpoint_uses_endpoint_limiter_instead_of_global_limiter(self):
        class _TrackedAsyncContext:
            def __init__(self):
                self.entered = 0

            async def __aenter__(self):
                self.entered += 1
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        df = pl.DataFrame({"a": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(endpoint_rate_limits={"ep1": 2.0})
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)
        global_limiter = _TrackedAsyncContext()
        endpoint_limiter = _TrackedAsyncContext()
        runner._rate_limiter = cast("Any", global_limiter)
        runner._endpoint_rate_limiters["ep1"] = cast("Any", endpoint_limiter)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})

        assert result is not None
        assert global_limiter.entered == 0
        assert endpoint_limiter.entered == 1

    @pytest.mark.asyncio
    async def test_family_isolation_uses_family_limiter_without_backing_off_global_rate(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_family_overrides={"ep1": "player_history"},
            family_rate_limits={"player_history": 2.0},
        )
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)
        original_limiter = runner._rate_limiter

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner._extract_single(entry, {"season": "2024-25"})

        assert runner._rate_limiter is original_limiter
        assert runner._adaptive.current_rate == 10.0
        assert "player_history" in runner._family_rate_limiters

    def test_endpoint_semaphore_override_takes_precedence(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(endpoint_semaphore_limits={"ep1": 1})
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        semaphore = runner._get_semaphore("ep1", "default")
        assert semaphore._value == 1

    def test_family_semaphore_override_applies_when_endpoint_override_missing(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_family_overrides={"ep1": "player_history"},
            family_semaphore_limits={"player_history": 2},
        )
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        semaphore = runner._get_semaphore("ep1", "default")
        assert semaphore._value == 2

    def test_chunk_size_is_reduced_for_isolated_family(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_family_overrides={"ep1": "player_history"},
            family_chunk_multipliers={"player_history": 0.25},
            adaptive_chunk_min_size=10,
            adaptive_chunk_max_size=500,
            default_chunk_size=400,
        )
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        chunk_size = runner._chunk_size_for_entries(
            "player", [StagingEntry("ep1", "stg_ep1", "player")]
        )
        assert chunk_size == 100

    def test_direct_profile_player_history_chunk_size_fits_lane_timeout(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_family_overrides={"player_dash_game_splits": "player_history"},
            family_chunk_multipliers={
                "default": 1.0,
                "box_score": 1.0,
                "play_by_play": 0.5,
                "player_history": 0.001,
                "team_history": 0.5,
            },
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=100,
            default_chunk_size=1000,
        )
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        chunk_size = runner._chunk_size_for_entries(
            "player_season",
            [
                StagingEntry(
                    "player_dash_game_splits", "stg_player_dash_game_splits", "player_season"
                )
            ],
        )

        assert chunk_size == 1

    def test_endpoint_chunk_size_limit_can_be_smaller_than_adaptive_floor(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_chunk_size_limits={"video_details_asset": 10},
            adaptive_chunk_min_size=25,
            adaptive_chunk_max_size=1000,
            default_chunk_size=1000,
        )
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        chunk_size = runner._chunk_size_for_entries(
            "player_team_season",
            [
                StagingEntry(
                    "video_details_asset",
                    "stg_video_details_asset",
                    "player_team_season",
                )
            ],
        )

        assert chunk_size == 10

    def test_default_settings_isolate_slow_player_history_endpoints(self):
        settings = NbaDbSettings()

        assert settings.endpoint_semaphore_limits["player_awards"] == 1
        assert settings.endpoint_rate_limits["player_awards"] == 1.0
        assert settings.endpoint_request_timeouts["player_awards"] == 120
        assert settings.endpoint_semaphore_limits["player_career_stats"] == 1
        assert settings.endpoint_rate_limits["player_career_stats"] == 1.0
        assert settings.endpoint_request_timeouts["player_career_stats"] == 120
        assert settings.endpoint_semaphore_limits["video_details_asset"] == 2
        assert settings.endpoint_rate_limits["video_details_asset"] == 2.0
        assert settings.endpoint_request_timeouts["video_details_asset"] == 15
        assert settings.endpoint_chunk_size_limits["video_details_asset"] == 10
        assert settings.endpoint_chunk_size_limits["win_probability"] == 10
        assert settings.endpoint_retry_budgets["video_details_asset"] == 0
        assert settings.zero_progress_abort_endpoints == {
            "video_details_asset",
            "win_probability",
        }
        assert settings.response_contract_circuit_thresholds == {
            "win_probability": 3,
        }
        assert build_execution_policy("video_details_asset", settings=settings).retry_budget == 0

    @pytest.mark.asyncio
    async def test_response_contract_circuit_suppresses_queued_calls_without_completion(
        self,
    ):
        class _MalformedWinProbability:
            category = "play_by_play"
            endpoint_name = "win_probability"
            calls = 0

            async def extract_all(self, **_kwargs):
                type(self).calls += 1
                raise json.JSONDecodeError("invalid payload", "", 0)

        class _CountingLimiter:
            entries = 0

            async def __aenter__(self):
                type(self).entries += 1

            async def __aexit__(self, *_args):
                return None

        journal = _make_journal(already_done=False)
        settings = _make_settings(
            default_chunk_size=10,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=10,
            endpoint_semaphore_limits={"win_probability": 1},
            endpoint_rate_limits={"win_probability": 100.0},
            endpoint_chunk_size_limits={"win_probability": 10},
            response_contract_circuit_thresholds={"win_probability": 3},
            zero_progress_abort_endpoints={"win_probability"},
        )
        runner = ExtractorRunner(
            _make_registry(_MalformedWinProbability),
            settings,
            journal,
        )
        runner._endpoint_rate_limiters["win_probability"] = cast("Any", _CountingLimiter())
        entry = StagingEntry(
            "win_probability",
            "stg_win_probability",
            "game",
            result_set_index=0,
            use_multi=True,
        )

        result = await runner.run_pattern_result(
            "game",
            [{"game_id": f"00224{index:05d}"} for index in range(1_241)],
            [entry],
        )

        assert _MalformedWinProbability.calls == 3
        assert _CountingLimiter.entries == 3
        assert result.eligible_calls == 1_241
        assert result.scheduled_calls == 10
        assert result.unattempted_eligible_calls == 1_231
        assert result.success_count == 0
        assert result.failure_count == 10
        assert not result.is_complete
        assert (
            sum("ResponseContractCircuitOpen:JSONDecodeError" in error for error in result.errors)
            == 7
        )
        assert any(error.startswith("zero_progress_chunk_abort:") for error in result.errors)
        assert result.response_contract_circuit == {
            "win_probability": {
                "threshold": 3,
                "failure_signature": "JSONDecodeError",
                "consecutive_failures": 3,
                "open": True,
                "upstream_attempts": 3,
                "suppressions": 7,
                "unattempted_calls": 1_231,
                "preserved_outstanding_calls": 1_238,
            }
        }
        assert journal.record_start.call_count == 10
        assert journal.record_failure.call_count == 10
        journal.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_response_contract_circuit_does_not_suppress_transport_failures(
        self,
    ):
        class _TransientWinProbability:
            category = "play_by_play"
            endpoint_name = "win_probability"
            calls = 0

            async def extract_all(self, **_kwargs):
                type(self).calls += 1
                raise ConnectionError("temporary outage")

        journal = _make_journal(already_done=False)
        settings = _make_settings(
            default_chunk_size=4,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=4,
            endpoint_semaphore_limits={"win_probability": 1},
            endpoint_chunk_size_limits={"win_probability": 4},
            response_contract_circuit_thresholds={"win_probability": 1},
        )
        runner = ExtractorRunner(
            _make_registry(_TransientWinProbability),
            settings,
            journal,
        )
        entry = StagingEntry(
            "win_probability",
            "stg_win_probability",
            "game",
            result_set_index=0,
            use_multi=True,
        )

        result = await runner.run_pattern_result(
            "game",
            [{"game_id": f"002240000{index}"} for index in range(4)],
            [entry],
        )

        assert _TransientWinProbability.calls == 4
        assert result.failure_count == 4
        assert not any("ResponseContractCircuitOpen" in error for error in result.errors)
        assert result.response_contract_circuit["win_probability"]["upstream_attempts"] == 4
        assert result.response_contract_circuit["win_probability"]["suppressions"] == 0

    @pytest.mark.asyncio
    async def test_endpoint_retry_budget_overrides_global_budget(self):
        class _CountingExtractor:
            category = "default"
            endpoint_name = "video_details_asset"
            calls = 0

            async def extract(self, **_kwargs):
                type(self).calls += 1
                raise TimeoutError("boom")

        journal = _make_journal(already_done=False)
        settings = _make_settings(
            extract_max_retries=6,
            endpoint_retry_budgets={"video_details_asset": 0},
        )
        registry = _make_registry(_CountingExtractor)
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )
        result = await runner._extract_single(entry, {"season": "2024-25"})

        assert result is None
        assert _CountingExtractor.calls == 1
        journal.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_progress_endpoint_aborts_after_first_fully_failed_chunk(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            default_chunk_size=100,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=100,
            endpoint_chunk_size_limits={"video_details_asset": 2},
            zero_progress_abort_endpoints={"video_details_asset"},
        )
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal)
        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )

        result = await runner.run_pattern_result(
            "player_team_season",
            [{"season": f"20{year:02d}-{year + 1:02d}"} for year in range(20, 25)],
            [entry],
        )

        assert result.eligible_calls == 5
        assert result.scheduled_calls == 2
        assert result.unattempted_eligible_calls == 3
        assert result.success_count == 0
        assert result.failure_count == 2
        assert any(error.startswith("zero_progress_chunk_abort:") for error in result.errors)
        assert journal.record_start.call_count == 2

    @pytest.mark.asyncio
    async def test_zero_progress_endpoint_continues_after_any_success(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            default_chunk_size=100,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=100,
            endpoint_chunk_size_limits={"video_details_asset": 2},
            zero_progress_abort_endpoints={"video_details_asset"},
        )
        registry = _make_registry(_make_extractor(df=pl.DataFrame()))
        runner = ExtractorRunner(registry, settings, journal)
        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )

        result = await runner.run_pattern_result(
            "player_team_season",
            [{"season": f"20{year:02d}-{year + 1:02d}"} for year in range(20, 25)],
            [entry],
        )

        assert result.eligible_calls == 5
        assert result.success_count == 5
        assert result.failure_count == 0
        assert not any(error.startswith("zero_progress_chunk_abort:") for error in result.errors)
        assert journal.record_start.call_count == 5

    @pytest.mark.asyncio
    async def test_zero_progress_abort_counts_only_newly_attempted_calls(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            default_chunk_size=2,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=2,
            endpoint_chunk_size_limits={"video_details_asset": 2},
            zero_progress_abort_endpoints={"video_details_asset"},
        )
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal)
        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )
        params = [{"season": "2020-21"}, {"season": "2021-22"}]
        skipped = {
            (
                "video_details_asset",
                '{"season": "2020-21"}',
            )
        }

        result = await runner.run_pattern_result(
            "player_team_season",
            params,
            [entry],
            skip_items=skipped,
        )

        assert result.eligible_calls == 2
        assert result.retry_skip_count == 1
        assert result.failure_count == 1
        assert any("attempted=1:skipped=1" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_zero_progress_abort_preserves_prior_empty_chunk_durability(self):
        class _MixedExtractor:
            category = "default"
            endpoint_name = "video_details_asset"

            async def extract(self, **params):
                if params["season"] in {"2020-21", "2021-22"}:
                    return pl.DataFrame()
                raise TimeoutError("boom")

        journal = _make_journal(already_done=False)
        events: list[str] = []
        journal.record_success.side_effect = lambda *_args: events.append("journal-success")
        settings = _make_settings(
            default_chunk_size=2,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=2,
            endpoint_chunk_size_limits={"video_details_asset": 2},
            zero_progress_abort_endpoints={"video_details_asset"},
        )
        runner = ExtractorRunner(_make_registry(_MixedExtractor), settings, journal)
        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )

        def persist_chunk(
            frames,
            *,
            expected_staging_keys,
            source_results,
            **_metadata,
        ):
            assert frames == {}
            assert expected_staging_keys == ["stg_video_details_asset"]
            assert len(source_results) == 2
            events.append("persist-empty-chunk")

        result = await runner.run_pattern_result(
            "player_team_season",
            [
                {"season": "2020-21"},
                {"season": "2021-22"},
                {"season": "2022-23"},
                {"season": "2023-24"},
                {"season": "2024-25"},
            ],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert result.eligible_calls == 5
        assert result.scheduled_calls == 4
        assert result.unattempted_eligible_calls == 1
        assert result.success_count == 2
        assert result.failure_count == 2
        assert events == ["persist-empty-chunk", "journal-success", "journal-success"]
        assert any("chunk=1:attempted=2:skipped=0" in error for error in result.errors)
        assert journal.record_start.call_count == 4

    @pytest.mark.asyncio
    async def test_waits_for_open_circuit_breaker_instead_of_skipping(self):
        df = pl.DataFrame({"a": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        with (
            patch(
                "nbadb.orchestrate.resilience._CircuitBreaker.is_open",
                side_effect=[True, False],
            ),
            patch("nbadb.orchestrate.resilience._CircuitBreaker.retry_after", return_value=0.0),
            patch(
                "nbadb.orchestrate.extractor_runner.asyncio.sleep",
                new=AsyncMock(),
            ) as mock_sleep,
        ):
            result = await runner._extract_single(entry, {"season": "2024-25"})

        assert isinstance(result, dict)
        assert result["stg_ep1"].shape[0] == 1
        mock_sleep.assert_awaited_once_with(1.0)
        journal.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_circuit_breaker_timeout_records_failure(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(circuit_breaker_max_wait=5.0)
        registry = _make_registry(_make_extractor(df=pl.DataFrame({"a": [1]})))
        runner = ExtractorRunner(registry, settings, journal)
        runner._circuit_breaker = MagicMock()
        runner._circuit_breaker.is_open.side_effect = [True, True]
        runner._circuit_breaker.retry_after.return_value = 10.0

        entry = StagingEntry("ep1", "stg_ep1", "season")
        with (
            patch(
                "nbadb.orchestrate.extractor_runner.time.monotonic",
                side_effect=[0.0, 0.0, 5.1],
            ),
            patch(
                "nbadb.orchestrate.extractor_runner.asyncio.sleep",
                new=AsyncMock(),
            ) as mock_sleep,
        ):
            result = await runner._extract_single(entry, {"season": "2024-25"})

        assert result is None
        mock_sleep.assert_awaited_once_with(5.0)
        journal.record_failure.assert_called_once()
        assert journal.record_failure.call_args.args[2] == "_CircuitBreakerTimeoutError"


# ---------------------------------------------------------------------------
# _drive_coroutine tests
# ---------------------------------------------------------------------------


class TestDriveCoroutine:
    def test_sync_coroutine_returns_value(self):
        from nbadb.orchestrate.extractor_runner import _drive_coroutine

        async def _coro():
            return 42

        assert _drive_coroutine(_coro()) == 42

    def test_raises_on_real_async(self):
        import asyncio

        from nbadb.orchestrate.extractor_runner import _drive_coroutine

        async def _coro():
            await asyncio.sleep(0)
            return 42

        with pytest.raises(RuntimeError, match="yielded unexpectedly"):
            _drive_coroutine(_coro())


# ---------------------------------------------------------------------------
# _sync_extract / _sync_extract_all tests
# ---------------------------------------------------------------------------


class TestSyncExtract:
    def test_basic_call(self):
        from nbadb.orchestrate.extractor_runner import _sync_extract

        class _Ext:
            async def extract(self, **kw):
                return pl.DataFrame({"x": [1]})

        result = _sync_extract(_Ext())
        assert result.shape == (1, 1)

    def test_passes_kwargs(self):
        from nbadb.orchestrate.extractor_runner import _sync_extract

        class _Ext:
            async def extract(self, **kw):
                return pl.DataFrame({"season": [kw["season"]]})

        result = _sync_extract(_Ext(), season="2024-25")
        assert result["season"][0] == "2024-25"


class TestSyncExtractAll:
    def test_basic_call(self):
        from nbadb.orchestrate.extractor_runner import _sync_extract_all

        class _Ext:
            async def extract_all(self, **kw):
                return [pl.DataFrame({"x": [1]}), pl.DataFrame({"y": [2]})]

        result = _sync_extract_all(_Ext())
        assert len(result) == 2
        assert result[0].shape == (1, 1)


# ---------------------------------------------------------------------------
# _is_retryable tests
# ---------------------------------------------------------------------------


class TestIsRetryable:
    @pytest.mark.parametrize(
        "exc_type",
        [ConnectionError, ConnectionResetError],
    )
    def test_retryable_exceptions(self, exc_type):
        assert ExtractorRunner._is_retryable(exc_type("msg")) is True

    def test_ssl_error_is_retryable(self):
        class SSLError(Exception):
            pass

        assert ExtractorRunner._is_retryable(SSLError("msg")) is True

    @pytest.mark.parametrize(
        "exc_type",
        [ValueError, IndexError, TypeError],
    )
    def test_non_retryable_exceptions(self, exc_type):
        assert ExtractorRunner._is_retryable(exc_type("msg")) is False

    def test_json_decode_error(self):
        import json

        exc = json.JSONDecodeError("msg", "doc", 0)
        assert ExtractorRunner._is_retryable(exc) is False


# ---------------------------------------------------------------------------
# _collect_results tests
# ---------------------------------------------------------------------------


class TestCollectResults:
    def test_base_exception_logged(self):
        accum = {"k": []}
        ExtractorRunner._collect_results([RuntimeError("boom")], accum, None)
        assert accum["k"] == []

    def test_none_skipped(self):
        accum = {"k": []}
        ExtractorRunner._collect_results([None], accum, None)
        assert accum["k"] == []

    def test_dict_result_merged(self):
        df = pl.DataFrame({"a": [1]})
        accum = {"k": []}
        ExtractorRunner._collect_results([{"k": df}], accum, None)
        assert len(accum["k"]) == 1

    def test_unexpected_type_logged(self):
        accum = {"k": []}
        ExtractorRunner._collect_results(cast("Any", ["unexpected_string"]), accum, None)
        assert accum["k"] == []

    def test_empty_df_not_added(self):
        accum = {"k": []}
        ExtractorRunner._collect_results([{"k": pl.DataFrame()}], accum, None)
        assert accum["k"] == []

    def test_progress_not_called_on_exception(self):
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results([RuntimeError("boom")], accum, progress)
        progress.advance_pattern.assert_not_called()

    def test_progress_called_on_success(self):
        df = pl.DataFrame({"a": [1]})
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results([{"k": df}], accum, progress)
        progress.advance_pattern.assert_called_once_with(success=True, rows=1)

    def test_progress_not_called_on_unexpected_type(self):
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results(cast("Any", ["bad"]), accum, progress)
        progress.advance_pattern.assert_not_called()


# ---------------------------------------------------------------------------
# _concat_accum tests
# ---------------------------------------------------------------------------


class TestConcatAccum:
    def test_empty_list_excluded(self):
        result = ExtractorRunner._concat_accum({"k": []})
        assert "k" not in result

    def test_single_frame(self):
        df = pl.DataFrame({"a": [1, 2]})
        result = ExtractorRunner._concat_accum({"k": [df]})
        assert result["k"].shape[0] == 2

    def test_multiple_frames(self):
        df1 = pl.DataFrame({"a": [1]})
        df2 = pl.DataFrame({"a": [2]})
        result = ExtractorRunner._concat_accum({"k": [df1, df2]})
        assert result["k"].shape[0] == 2

    def test_schema_drift_diagonal(self):
        df1 = pl.DataFrame({"a": [1], "b": [2]})
        df2 = pl.DataFrame({"a": [3], "c": [4]})
        result = ExtractorRunner._concat_accum({"k": [df1, df2]})
        assert set(result["k"].columns) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# _CircuitBreaker unit tests (HR-T-001)
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_trips_after_threshold(self):
        cb = _CircuitBreaker(threshold=3, recovery_seconds=60.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")
        assert cb.is_open("ep1") is False  # 2 < threshold
        cb.record_failure("ep1")
        assert cb.is_open("ep1") is True  # 3 >= threshold

    def test_recovery_allows_probe(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=1.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")
        assert cb.is_open("ep1") is True

        # Simulate recovery window elapsed
        with patch("nbadb.orchestrate.resilience.time") as mock_time:
            # First call to is_open reads monotonic for the trip
            # After recovery, monotonic should show elapsed time
            mock_time.monotonic.return_value = 999999.0
            assert cb.is_open("ep1") is False  # half-open: probe allowed

    def test_half_open_blocks_second_probe(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=1.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")

        with patch("nbadb.orchestrate.resilience.time") as mock_time:
            mock_time.monotonic.return_value = 999999.0
            # First probe allowed
            assert cb.is_open("ep1") is False
            # Second probe blocked (first still in flight)
            assert cb.is_open("ep1") is True

    def test_record_success_clears_probe(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=1.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")

        with patch("nbadb.orchestrate.resilience.time") as mock_time:
            mock_time.monotonic.return_value = 999999.0
            cb.is_open("ep1")  # transition to half-open, adds to probing set

        cb.record_success("ep1")
        assert "ep1" not in cb._half_open_probing
        assert cb.is_open("ep1") is False  # fully closed

    def test_record_failure_retrips(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=1.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")

        with patch("nbadb.orchestrate.resilience.time") as mock_time:
            mock_time.monotonic.return_value = 999999.0
            cb.is_open("ep1")  # half-open probe

        # Probe fails → re-trip
        cb.record_failure("ep1")
        assert "ep1" not in cb._half_open_probing
        assert cb.is_open("ep1") is True  # re-tripped

    def test_retry_after_returns_remaining_cooldown(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=10.0)
        with patch("nbadb.orchestrate.resilience.time.monotonic", return_value=100.0):
            cb.record_failure("ep1")
            cb.record_failure("ep1")
        with patch("nbadb.orchestrate.resilience.time.monotonic", return_value=104.0):
            assert cb.retry_after("ep1") == pytest.approx(6.0)


class TestResponseContractCircuit:
    def test_opens_only_after_repeated_identical_signature(self):
        circuit = _ResponseContractCircuit({"win_probability": 2})

        assert not circuit.record_failure("win_probability", "JSONDecodeError")
        assert circuit.blocked_signature("win_probability") is None
        assert circuit.record_failure("win_probability", "JSONDecodeError")
        assert circuit.blocked_signature("win_probability") == "JSONDecodeError"

    def test_signature_change_and_success_reset_consecutive_failures(self):
        circuit = _ResponseContractCircuit({"win_probability": 2})

        assert not circuit.record_failure("win_probability", "JSONDecodeError")
        assert not circuit.record_failure("win_probability", "UnexpectedResultShape")
        assert circuit.blocked_signature("win_probability") is None
        circuit.record_success("win_probability")
        assert not circuit.record_failure("win_probability", "UnexpectedResultShape")
        assert circuit.blocked_signature("win_probability") is None

    def test_unconfigured_endpoint_never_opens(self):
        circuit = _ResponseContractCircuit({"win_probability": 1})

        assert not circuit.record_failure("play_by_play", "JSONDecodeError")
        assert circuit.blocked_signature("play_by_play") is None

    def test_summary_tracks_upstream_attempts_and_preserved_suppressions(self):
        circuit = _ResponseContractCircuit({"win_probability": 1})
        circuit.record_upstream_attempt("win_probability")
        assert circuit.record_failure("win_probability", "JSONDecodeError")
        circuit.record_suppression("win_probability")

        assert circuit.summary() == {
            "win_probability": {
                "threshold": 1,
                "failure_signature": "JSONDecodeError",
                "consecutive_failures": 1,
                "open": True,
                "upstream_attempts": 1,
                "suppressions": 1,
                "unattempted_calls": 0,
                "preserved_outstanding_calls": 1,
            }
        }


# ---------------------------------------------------------------------------
# deprecated_after enforcement (HR-T-003)
# ---------------------------------------------------------------------------


class TestBuildChunkTasksDeprecated:
    def test_deprecated_entry_is_skipped(self):
        import asyncio

        settings = _make_settings()
        journal = _make_journal()
        registry = MagicMock()
        runner = ExtractorRunner(
            registry=registry,
            settings=settings,
            journal=journal,
            rate_limit=10.0,
        )

        deprecated_entry = StagingEntry(
            "old_ep", "stg_old", "season", deprecated_after="2020-01-01"
        )
        active_entry = StagingEntry("new_ep", "stg_new", "season")

        async def _run():
            return runner._build_chunk_tasks(
                single_entries=[deprecated_entry, active_entry],
                multi_by_ep={},
                chunk=[{"season": "2024-25"}],
                already_done=set(),
                on_progress=None,
            )

        batch = asyncio.run(_run())

        # Only the active entry should produce a task
        assert len(batch.tasks) == 1
        assert batch.eligible_calls == 1
        assert batch.support_skip_count == 1
        assert runner.skipped >= 1

    def test_non_deprecated_entry_proceeds(self):
        import asyncio

        settings = _make_settings()
        journal = _make_journal()
        registry = MagicMock()
        runner = ExtractorRunner(
            registry=registry,
            settings=settings,
            journal=journal,
            rate_limit=10.0,
        )

        entry = StagingEntry("ep1", "stg_ep1", "season")

        async def _run():
            return runner._build_chunk_tasks(
                single_entries=[entry],
                multi_by_ep={},
                chunk=[{"season": "2024-25"}],
                already_done=set(),
                on_progress=None,
            )

        batch = asyncio.run(_run())
        assert len(batch.tasks) == 1
        assert batch.eligible_calls == 1
        assert runner.skipped == 0


class TestSeasonYear:
    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"season": "2024-25"}, 2024),
            ({"season": "2024"}, 2024),
            ({"game_id": "0024800127"}, 1948),
            ({"game_id": "0020000730"}, 2000),
            ({"game_id": "0021500232"}, 2015),
            ({"game_id": "001"}, None),
        ],
    )
    def test_extracts_season_year_from_params(self, params, expected):
        assert ExtractorRunner._season_year(params) == expected


class TestBuildChunkTasksMinSeason:
    def test_game_entry_min_season_uses_game_id_year(self):
        import asyncio

        settings = _make_settings()
        journal = _make_journal()
        registry = MagicMock()
        runner = ExtractorRunner(
            registry=registry,
            settings=settings,
            journal=journal,
            rate_limit=10.0,
        )

        entry = StagingEntry(
            "box_score_misc",
            "stg_box_score_misc",
            "game",
            result_set_index=0,
            use_multi=True,
            min_season=1996,
        )

        async def _run():
            return runner._build_chunk_tasks(
                single_entries=[],
                multi_by_ep={"box_score_misc": [entry]},
                chunk=[{"game_id": "0024800127"}],
                already_done=set(),
                on_progress=None,
            )

        batch = asyncio.run(_run())

        assert batch.tasks == []
        assert batch.eligible_calls == 0
        assert batch.support_skip_count == 1
        assert runner.skipped == 1


# ---------------------------------------------------------------------------
# _LatencyTracker tests
# ---------------------------------------------------------------------------


class TestLatencyTracker:
    def test_record_and_percentile(self):
        lt = _LatencyTracker(window_size=10)
        for i in range(1, 11):
            lt.record("ep1", float(i))
        p50 = lt.percentile("ep1", 50)
        assert p50 is not None
        assert 4.0 <= p50 <= 6.0

    def test_percentile_empty_returns_none(self):
        lt = _LatencyTracker()
        assert lt.percentile("missing", 50) is None

    def test_summary(self):
        lt = _LatencyTracker(window_size=100)
        for i in range(1, 51):
            lt.record("ep1", float(i))
        s = lt.summary("ep1")
        assert s is not None
        assert "p50" in s
        assert "p95" in s
        assert "p99" in s
        assert s["count"] == 50.0

    def test_summary_missing_returns_none(self):
        lt = _LatencyTracker()
        assert lt.summary("missing") is None

    def test_all_summaries(self):
        lt = _LatencyTracker()
        lt.record("ep1", 1.0)
        lt.record("ep2", 2.0)
        sums = lt.all_summaries()
        assert "ep1" in sums
        assert "ep2" in sums

    def test_deque_window_eviction(self):
        lt = _LatencyTracker(window_size=3)
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            lt.record("ep1", v)
        # Window of 3 → only last 3 values (3.0, 4.0, 5.0)
        summary = lt.summary("ep1")
        assert summary is not None
        assert summary["count"] == 3.0
        p50 = lt.percentile("ep1", 50)
        assert p50 == 4.0


class TestSealedDispatchFanout:
    @pytest.mark.asyncio
    async def test_run_pattern_result_rejects_out_of_manifest_derived_fanout(self):
        journal = _make_journal()
        settings = _make_settings()
        extractor_cls = _make_extractor()
        registry = _make_registry(extractor_cls)
        admissions: list[tuple[str, dict[str, object], tuple[str, ...]]] = []
        runner = ExtractorRunner(
            registry,
            settings,
            journal,
            call_admission=lambda endpoint, params, routes: admissions.append(
                (endpoint, params, routes)
            ),
        )
        entry = StagingEntry("boxscore", "stg_boxscore", "game")
        sealed = {"game_id": "0022400001"}
        extra = {"game_id": "0022400999"}

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="later-derived or out-of-manifest fan-out",
        ):
            await runner.run_pattern_result(
                "game",
                [sealed, extra],
                [entry],
                required_route_ids=("boxscore:stg_boxscore:0",),
            )

        registry.get.assert_not_called()
        journal.record_start.assert_not_called()
        journal.was_extracted_batch.assert_not_called()
        assert admissions == []

    @pytest.mark.asyncio
    async def test_successor_runner_rejects_unsealed_param_fanout(self):
        journal = _make_journal()
        settings = _make_settings()
        extractor_cls = _make_extractor()
        registry = _make_registry(extractor_cls)
        admissions: list[object] = []
        runner = ExtractorRunner(
            registry,
            settings,
            journal,
            call_admission=lambda *_args: admissions.append(_args),
        )
        entry = StagingEntry("boxscore", "stg_boxscore", "game")

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="later-derived or out-of-manifest fan-out",
        ):
            await runner.run_pattern_result(
                "game",
                [{"game_id": "0022400001"}, {"game_id": "0022400999"}],
                [entry],
            )

        registry.get.assert_not_called()
        journal.record_start.assert_not_called()
        assert admissions == []
