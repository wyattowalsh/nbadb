from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest
from nba_api.library.http import NBAResponse
from nba_api.live.nba.endpoints import BoxScore, Odds, PlayByPlay, ScoreBoard

from nbadb.contracts.raw_request_authority import canonical_semantic_parameters
from nbadb.contracts.raw_request_reconstruction import LiveSnapshotPlanAuthorityV2
from nbadb.core.config import NbaDbSettings
from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    LiveEndpointContract,
    LiveResultSetContract,
    owned_contract_sha256,
    pinned_live_contracts,
    pinned_live_endpoint_contract,
)
from nbadb.extract.nba_api_adapter import NbaDbLiveHTTP
from nbadb.extract.raw_request_capture import (
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.orchestrate.live_snapshot import LiveSnapshotExtraction, LiveSnapshotWarehouse
from nbadb.orchestrate.orchestrator import Orchestrator

if TYPE_CHECKING:
    from pathlib import Path


_PROVIDER_ENDPOINT_IDS = {
    "live_score_board": "ScoreBoard",
    "live_odds": "Odds",
    "live_play_by_play": "PlayByPlay",
    "live_box_score": "BoxScore",
}


class _ExactLiveAuthorityHarness:
    def __init__(self) -> None:
        self.provider_authority_sha256 = expected_nba_api_provider_authority()["authority_sha256"]
        self.context_calls: list[tuple[str, dict[str, object]]] = []
        self.plan_calls: list[tuple[str, tuple[str, ...]]] = []

    @staticmethod
    def _digest(label: str) -> str:
        return hashlib.sha256(label.encode()).hexdigest()

    def context_for(
        self,
        endpoint_name: str,
        params: dict[str, object],
    ) -> RawRequestCaptureContextV2:
        call_ordinal = len(self.context_calls)
        self.context_calls.append((endpoint_name, dict(params)))
        provider_endpoint_id = _PROVIDER_ENDPOINT_IDS[endpoint_name]
        _safe_json, _safe_sha256, provider_request_sha256 = canonical_semantic_parameters(
            "live",
            provider_endpoint_id,
            params,
        )
        return RawRequestCaptureContextV2(
            provider_authority_sha256=self.provider_authority_sha256,
            source_sha="a" * 40,
            run_id=7001,
            run_attempt=1,
            chain_id="live-chain",
            lane_id=f"live-call-{call_ordinal}",
            provider_calls=(
                RawProviderCallContextV2(
                    request_ordinal=0,
                    semantic_request_sha256=self._digest(
                        f"semantic:{call_ordinal}:{endpoint_name}"
                    ),
                    logical_invocation_sha256=self._digest(
                        f"logical:{call_ordinal}:{endpoint_name}"
                    ),
                    provider_call_role="primary",
                    provider_call_ordinal=0,
                    source_family="live",
                    endpoint_id=provider_endpoint_id,
                    provider_request_sha256=provider_request_sha256,
                    endpoint_contract_sha256=owned_contract_sha256(
                        pinned_live_contracts()[provider_endpoint_id]
                    ),
                    scope_sha256=self._digest(f"scope:{call_ordinal}:{endpoint_name}:{params!r}"),
                ),
            ),
        )

    def plan_for(
        self,
        endpoint_name: str,
        params: dict[str, object],
        route_ids: tuple[str, ...],
        snapshot_at: datetime,
        raw_snapshot: RawRequestCaptureSnapshotV2,
    ) -> tuple[LiveSnapshotPlanAuthorityV2, str]:
        assert len(raw_snapshot.pending_successes) == 1
        self.plan_calls.append((endpoint_name, route_ids))
        authority = LiveSnapshotPlanAuthorityV2.build(
            sealed_plan_bytes=json.dumps(
                {
                    "endpoint_name": endpoint_name,
                    "parameters": params,
                    "route_ids": route_ids,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            attempt=raw_snapshot.pending_successes[0].attempt,
            route_ids=route_ids,
            live_snapshot_at=snapshot_at,
        )
        return authority, authority.authority_sha256


def _settings(tmp_path: Path) -> NbaDbSettings:
    return NbaDbSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        formats=["duckdb"],
        sqlite_path=tmp_path / "data" / "live.sqlite",
        duckdb_path=tmp_path / "data" / "live.duckdb",
    )


def _live_response(payload: object) -> NBAResponse:
    return NBAResponse(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        200,
        "fixture://recurring-live",
    )


def _sample_live_value(sample_types: tuple[str, ...]) -> object:
    preferred = next((item for item in sample_types if item != "null"), "null")
    return {
        "array": [],
        "boolean": True,
        "integer": 1,
        "null": None,
        "number": 1.25,
        "object": {},
        "string": "fixture",
    }[preferred]


def _complete_live_result_container(
    result_set: LiveResultSetContract,
    contract: LiveEndpointContract,
) -> object:
    children = {
        child.parent_field_name: child
        for child in contract.result_sets
        if child.parent_result_set_name == result_set.name and child.parent_field_name is not None
    }
    scalar_projection = (
        len(result_set.fields) == 1
        and not result_set.fields[0].source_field
        and result_set.fields[0].name == "value"
    )
    if scalar_projection:
        record: object = _sample_live_value(result_set.fields[0].sample_types)
    else:
        values: dict[str, object] = {}
        for field in result_set.fields:
            child = children.get(field.name)
            values[field.name] = (
                _complete_live_result_container(child, contract)
                if child is not None
                else _sample_live_value(field.sample_types)
            )
        for name, child in children.items():
            values.setdefault(name, _complete_live_result_container(child, contract))
        record = values
    if result_set.container_kind == "nba_api_live_json_array":
        return [record]
    return record


def _complete_live_payload(endpoint_cls: type) -> dict[str, object]:
    contract = pinned_live_endpoint_contract(endpoint_cls)
    roots = {
        result_set.traversal_path[0]: result_set
        for result_set in contract.result_sets
        if result_set.parent_result_set_name is None
    }
    return {
        root_name: _complete_live_result_container(roots[root_name], contract)
        for root_name in contract.envelope_root_order
    }


def _public_recurring_extraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[LiveSnapshotExtraction, Path, _ExactLiveAuthorityHarness]:
    responses = iter(
        _live_response(_complete_live_payload(endpoint_cls))
        for endpoint_cls in (ScoreBoard, Odds, PlayByPlay, BoxScore)
    )
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: next(responses),
    )
    authority = _ExactLiveAuthorityHarness()
    warehouse = LiveSnapshotWarehouse(
        settings=_settings(tmp_path),
        public_recurring=True,
        raw_request_capture_context_factory=authority.context_for,
        live_plan_authority_binding_factory=authority.plan_for,
    )
    recurring = warehouse._recurring_receipts
    assert recurring is not None
    receipt_root = recurring.sink.root
    assert receipt_root.is_dir()
    extraction = warehouse.extract_source_calls(
        game_ids=["0022400001"],
        snapshot_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
    )
    return extraction, receipt_root, authority


def test_standalone_live_snapshot_fails_before_provider_or_persistence(tmp_path: Path) -> None:
    warehouse = LiveSnapshotWarehouse(settings=_settings(tmp_path))
    with (
        patch("nbadb.extract.base.fetch_live_payloads") as provider,
        pytest.raises(
            ParserInputCaptureIntegrityError,
            match="before exact W2 admission",
        ),
    ):
        warehouse.run(
            game_ids=["001"],
            snapshot_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
        )

    provider.assert_not_called()
    assert not _settings(tmp_path).duckdb_path.exists()


def test_public_recurring_without_exact_authority_fails_before_provider(
    tmp_path: Path,
) -> None:
    warehouse = LiveSnapshotWarehouse(
        settings=_settings(tmp_path),
        public_recurring=True,
    )
    recurring = warehouse._recurring_receipts
    assert recurring is not None
    receipt_root = recurring.sink.root
    with (
        patch.object(NbaDbLiveHTTP, "send_api_request") as provider,
        pytest.raises(
            ParserInputCaptureIntegrityError,
            match="requires exact Raw V2 capture",
        ),
    ):
        warehouse.extract_source_calls(snapshot_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC))

    provider.assert_not_called()
    assert not receipt_root.exists()


def test_exact_live_source_calls_retain_raw_body_and_plan_evidence_until_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    extraction, receipt_root, authority = _public_recurring_extraction(monkeypatch, tmp_path)

    assert receipt_root.is_dir()
    assert extraction.source_evidence_available
    assert extraction.game_ids == ("0022400001",)
    assert [call.call_ordinal for call in extraction.source_calls] == [0, 1, 2, 3]
    assert [call.endpoint_name for call in extraction.source_calls] == [
        "live_score_board",
        "live_odds",
        "live_play_by_play",
        "live_box_score",
    ]
    assert authority.context_calls == [
        ("live_score_board", {}),
        ("live_odds", {}),
        ("live_play_by_play", {"game_id": "0022400001"}),
        ("live_box_score", {"game_id": "0022400001"}),
    ]
    assert len(authority.plan_calls) == 4

    extraction.replay_exact_source_evidence()
    for source_call in extraction.source_calls:
        binding, raw_snapshot, plan, expected_plan_sha256 = (
            source_call.replay_exact_source_evidence()
        )
        assert raw_snapshot.objects
        assert len(raw_snapshot.pending_successes) == 1
        assert raw_snapshot.pending_successes[0].body_object is not None
        assert raw_snapshot.pending_successes[0].logical_receipt_sha256 == (
            binding.logical_call_receipt_sha256
        )
        assert plan.authority_sha256 == expected_plan_sha256
        assert set(plan.route_ids) == set(binding.result_route_ids)

    extraction.release_source_evidence()
    extraction.release_source_evidence()
    assert not receipt_root.exists()
    assert not extraction.source_evidence_available
    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="already released",
    ):
        extraction.replay_exact_source_evidence()


def test_orchestrator_live_w2_metadata_retains_exact_raw_and_plan_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    extraction, _receipt_root, _authority = _public_recurring_extraction(
        monkeypatch,
        tmp_path,
    )
    source_call = extraction.source_calls[0]
    binding, raw_snapshot, plan, plan_pin = source_call.replay_exact_source_evidence()

    metadata = Orchestrator._live_source_result_metadata(source_call)

    assert metadata["receipt_binding"] == binding
    assert metadata["raw_request_capture_snapshot"] == raw_snapshot
    assert metadata["plan_live_snapshot_at"] == plan.live_snapshot_at
    assert metadata["live_plan_bindings"] == ((plan, plan_pin),)
    assert metadata["result_route_ids_by_staging_key"] == (
        source_call.result_route_ids_by_staging_key
    )
    extraction.release_source_evidence()


def test_orchestrator_live_w2_journal_rejects_reordered_admissions_before_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tests.unit.orchestrate.test_extractor_runner import _w2_admission

    extraction, _receipt_root, _authority = _public_recurring_extraction(
        monkeypatch,
        tmp_path,
    )
    source_calls = extraction.source_calls[:2]
    bindings = tuple(call.replay_exact_source_evidence()[0] for call in source_calls)
    reordered = tuple(
        _w2_admission(binding.logical_call_receipt_sha256) for binding in reversed(bindings)
    )
    journal = MagicMock()

    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="ordered source-call authority",
    ):
        Orchestrator._complete_live_w2_journal_calls(
            journal,
            source_calls,
            reordered,
        )

    journal.record_success.assert_not_called()
    extraction.release_source_evidence()


def test_orchestrator_live_w2_journal_commits_each_exact_admission_in_call_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tests.unit.orchestrate.test_extractor_runner import _w2_admission

    extraction, _receipt_root, _authority = _public_recurring_extraction(
        monkeypatch,
        tmp_path,
    )
    source_calls = extraction.source_calls[:2]
    admissions = tuple(
        _w2_admission(source_call.replay_exact_source_evidence()[0].logical_call_receipt_sha256)
        for source_call in source_calls
    )
    journal = MagicMock()

    Orchestrator._complete_live_w2_journal_calls(
        journal,
        source_calls,
        admissions,
    )

    assert [call.args[:2] for call in journal.record_success.call_args_list] == [
        (source_call.endpoint_name, source_call.parameters_json) for source_call in source_calls
    ]
    assert [
        call.kwargs["w2_admission"].logical_call_receipt_sha256
        for call in journal.record_success.call_args_list
    ] == [
        source_call.replay_exact_source_evidence()[0].logical_call_receipt_sha256
        for source_call in source_calls
    ]
    extraction.release_source_evidence()


def test_exact_live_source_replay_rejects_reordered_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    extraction, _receipt_root, _authority = _public_recurring_extraction(
        monkeypatch,
        tmp_path,
    )
    reordered = replace(extraction, source_calls=tuple(reversed(extraction.source_calls)))

    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="ordering differs",
    ):
        reordered.replay_exact_source_evidence()
    extraction.release_source_evidence()


def test_foreign_raw_context_is_rejected_before_live_transport(tmp_path: Path) -> None:
    authority = _ExactLiveAuthorityHarness()
    warehouse = LiveSnapshotWarehouse(
        settings=_settings(tmp_path),
        public_recurring=True,
        raw_request_capture_context_factory=cast("Any", lambda *_args: object()),
        live_plan_authority_binding_factory=authority.plan_for,
    )
    recurring = warehouse._recurring_receipts
    assert recurring is not None
    receipt_root = recurring.sink.root
    with (
        patch.object(NbaDbLiveHTTP, "send_api_request") as provider,
        pytest.raises(
            ParserInputCaptureIntegrityError,
            match="foreign authority",
        ),
    ):
        warehouse.extract_source_calls(snapshot_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC))

    provider.assert_not_called()
    assert not receipt_root.exists()


def test_changed_live_plan_pin_fails_closed_and_releases_private_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority = _ExactLiveAuthorityHarness()
    responses = iter((_live_response(_complete_live_payload(ScoreBoard)),))
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: next(responses),
    )

    def changed_pin(
        endpoint_name: str,
        params: dict[str, object],
        route_ids: tuple[str, ...],
        snapshot_at: datetime,
        raw_snapshot: RawRequestCaptureSnapshotV2,
    ) -> tuple[LiveSnapshotPlanAuthorityV2, str]:
        plan, _pin = authority.plan_for(
            endpoint_name,
            params,
            route_ids,
            snapshot_at,
            raw_snapshot,
        )
        return plan, "f" * 64

    warehouse = LiveSnapshotWarehouse(
        settings=_settings(tmp_path),
        public_recurring=True,
        raw_request_capture_context_factory=authority.context_for,
        live_plan_authority_binding_factory=changed_pin,
    )
    recurring = warehouse._recurring_receipts
    assert recurring is not None
    receipt_root = recurring.sink.root
    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="crosses its exact response or routes",
    ):
        warehouse.extract_source_calls(snapshot_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC))

    assert not receipt_root.exists()


def test_exact_live_source_replay_rejects_foreign_or_missing_children(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    extraction, _receipt_root, _authority = _public_recurring_extraction(
        monkeypatch,
        tmp_path,
    )
    first = extraction.source_calls[0]
    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="lacks exact Raw V2",
    ):
        replace(first, raw_request_capture_snapshot=None).replay_exact_source_evidence()
    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="lacks exact Raw V2",
    ):
        replace(first, live_plan_authority=cast("Any", object())).replay_exact_source_evidence()
    extraction.release_source_evidence()
