from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.capture_session import CaptureRunScope, PrivateGenerationIdentity
from nbadb.orchestrate.successor_planning_generation_contract import PlanningDataMember
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_planning_wave_receipt import (
    PlanningWaveCallBinding,
    PlanningWaveCompletionReceipt,
    PlanningWaveCompletionReceiptError,
    PlanningWaveMemberBinding,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _receipt() -> PlanningWaveCompletionReceipt:
    root = _digest("logical-root")
    provider = _digest("provider")
    scope = CaptureRunScope(
        semantic_source_sha="a" * 40,
        chain_id="chain-1",
        lane_id="planning-wave-0",
        workflow_run_id=17,
        workflow_run_attempt=1,
    )
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=root,
        endpoint_name="schedule",
        logical_parameters_sha256=_digest("parameters"),
        provider_authority_sha256=provider,
        result_route_ids=("schedule_int.game_header", "schedule_int.line_score"),
    )
    binding_payload = [
        {
            "endpoint_name": binding.endpoint_name,
            "logical_call_receipt_sha256": binding.logical_call_receipt_sha256,
            "logical_parameters_sha256": binding.logical_parameters_sha256,
            "provider_authority_sha256": binding.provider_authority_sha256,
            "result_route_ids": list(binding.result_route_ids),
        }
    ]
    private = PrivateGenerationIdentity(
        manifest_sha256=_digest("manifest"),
        provider_authority_sha256=provider,
        semantic_source_sha=scope.semantic_source_sha,
        chain_id=scope.chain_id,
        lane_id=scope.lane_id,
        workflow_run_id=scope.workflow_run_id,
        workflow_run_attempt=scope.workflow_run_attempt,
        artifact_count=7,
        done_call_count=1,
        done_call_receipt_sha256s=(root,),
        done_call_bindings_sha256=_canonical_sha256(binding_payload),
        done_attempt_count=1,
        done_blob_count=1,
        orphan_call_count=0,
        orphan_attempt_count=0,
        orphan_blob_count=0,
        stored_bytes=4096,
    )
    scope_a = _digest("scope-a")
    scope_b = _digest("scope-b")
    member_a = PlanningDataMember(
        member_id="schedule-game-header",
        wave_index=0,
        producing_scope_sha256=scope_a,
        schema_sha256=_digest("schema-a"),
        content_sha256=_digest("content-a"),
        row_count=1,
        semantic=PlanningSemanticDescriptor.from_partition(
            semantic_kind=PlanningSemanticKind.GAME_DATE_INDEX,
            partition={"season": "2025-26", "season_type": "Regular Season"},
            semantic_schema_sha256=_digest("schema-a"),
            semantic_content_sha256=_digest("content-a"),
            value_count=1,
        ),
    )
    member_b = PlanningDataMember(
        member_id="schedule-line-score",
        wave_index=0,
        producing_scope_sha256=scope_b,
        schema_sha256=_digest("schema-b"),
        content_sha256=_digest("empty"),
        row_count=0,
        semantic=PlanningSemanticDescriptor.from_partition(
            semantic_kind=PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA,
            partition={},
            semantic_schema_sha256=_digest("schema-b"),
            semantic_content_sha256=_digest("empty"),
            value_count=0,
            typed_zero_reason_code="provider_success_empty",
        ),
        typed_zero_reason_code="provider_success_empty",
    )
    member_ids = tuple(sorted((member_a.identity_sha256, member_b.identity_sha256)))
    return PlanningWaveCompletionReceipt(
        planning_request_sha256=_digest("request"),
        planning_generation_id="successor-planning-v2-test",
        wave_index=0,
        parent_wave_identity_sha256=None,
        wave_admission_identity_sha256=_digest("admission"),
        sealed_dispatch_identity_sha256s=(_digest("dispatch"),),
        committed_calls=(
            PlanningWaveCallBinding(
                ordinal=0,
                sealed_dispatch_identity_sha256=_digest("dispatch"),
                committed_call_identity_sha256=_digest("call"),
                logical_call_receipt_sha256=root,
                member_identity_sha256s=member_ids,
            ),
        ),
        requested_scope_identity_sha256s=tuple(sorted((scope_a, scope_b))),
        completed_scope_identity_sha256s=tuple(sorted((scope_a, scope_b))),
        members=(
            PlanningWaveMemberBinding(member=member_b, logical_call_receipt_sha256=root),
            PlanningWaveMemberBinding(member=member_a, logical_call_receipt_sha256=root),
        ),
        logical_call_bindings=(binding,),
        capture_scope=scope,
        private_generation_identity=private,
        planning_database_sha256=_digest("database"),
        planning_database_bytes=8192,
        planning_database_schema_sha256=_digest("database-schema"),
    )


def test_completion_receipt_round_trips_one_multi_route_logical_root() -> None:
    receipt = _receipt()

    restored = PlanningWaveCompletionReceipt.from_canonical_bytes(receipt.canonical_bytes)

    assert restored == receipt
    assert len(restored.committed_calls) == 1
    assert len(restored.members) == 2
    assert restored.private_generation_identity.done_call_count == 1
    assert restored.identity_sha256 == hashlib.sha256(receipt.canonical_bytes).hexdigest()


def test_completion_receipt_deeply_freezes_mutable_constructor_inputs() -> None:
    receipt = _receipt()
    calls = list(receipt.committed_calls)
    mutable_routes = list(receipt.logical_call_bindings[0].result_route_ids)
    binding = replace(receipt.logical_call_bindings[0], result_route_ids=mutable_routes)

    frozen = replace(receipt, committed_calls=calls, logical_call_bindings=(binding,))
    authority = frozen.identity_sha256
    calls.clear()
    mutable_routes.clear()

    assert frozen.committed_calls == receipt.committed_calls
    assert frozen.logical_call_bindings[0].result_route_ids == (
        "schedule_int.game_header",
        "schedule_int.line_score",
    )
    assert frozen.identity_sha256 == authority


@pytest.mark.parametrize("field_name", ["members", "logical_call_bindings"])
def test_completion_receipt_wraps_invalid_nested_constructor_values(
    field_name: str,
) -> None:
    receipt = _receipt()

    with pytest.raises(PlanningWaveCompletionReceiptError, match=field_name):
        replace(receipt, **{field_name: (object(),)})


def test_completion_receipt_rejects_member_to_logical_root_substitution() -> None:
    receipt = _receipt()
    foreign = replace(receipt.members[0], logical_call_receipt_sha256=_digest("foreign"))

    with pytest.raises(PlanningWaveCompletionReceiptError, match="member logical roots"):
        replace(receipt, members=(foreign, receipt.members[1]))


def test_completion_receipt_rejects_private_root_or_provider_drift() -> None:
    receipt = _receipt()
    foreign_private = replace(
        receipt.private_generation_identity,
        done_call_receipt_sha256s=(_digest("foreign-root"),),
    )

    with pytest.raises(PlanningWaveCompletionReceiptError, match="logical-call authority"):
        replace(receipt, private_generation_identity=foreign_private)

    foreign_binding = replace(
        receipt.logical_call_bindings[0],
        provider_authority_sha256=_digest("foreign-provider"),
    )
    with pytest.raises(PlanningWaveCompletionReceiptError, match="provider authority"):
        replace(receipt, logical_call_bindings=(foreign_binding,))


def test_completion_receipt_rejects_scope_member_and_database_drift() -> None:
    receipt = _receipt()
    with pytest.raises(PlanningWaveCompletionReceiptError, match="exactly equal requested"):
        replace(
            receipt,
            completed_scope_identity_sha256s=receipt.completed_scope_identity_sha256s[:-1],
        )
    with pytest.raises(PlanningWaveCompletionReceiptError, match="positive integer"):
        replace(receipt, planning_database_bytes=0)
    with pytest.raises(PlanningWaveCompletionReceiptError, match="capture scope"):
        replace(
            receipt,
            capture_scope=replace(receipt.capture_scope, lane_id="foreign-wave"),
        )


def test_completion_receipt_v2_rejects_old_v1_and_nested_semantic_tamper() -> None:
    receipt = _receipt()
    old_schema = receipt.to_dict()
    old_schema["schema_version"] = 1
    with pytest.raises(PlanningWaveCompletionReceiptError, match="schema"):
        PlanningWaveCompletionReceipt.from_dict(old_schema)

    semantic_tamper = receipt.to_dict()
    members = semantic_tamper["members"]
    assert isinstance(members, list)
    first_binding = members[0]
    assert isinstance(first_binding, dict)
    member = first_binding["member"]
    assert isinstance(member, dict)
    semantic = member["semantic"]
    assert isinstance(semantic, dict)
    semantic["semantic_content_sha256"] = _digest("foreign-semantic-content")
    with pytest.raises(PlanningWaveCompletionReceiptError, match="member"):
        PlanningWaveCompletionReceipt.from_dict(semantic_tamper)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload | {"schema_version": True},
        lambda payload: payload | {"body_sha256": "0" * 64},
        lambda payload: {key: value for key, value in payload.items() if key != "body_sha256"},
        lambda payload: payload | {"unknown": 1},
    ],
)
def test_completion_receipt_decoder_rejects_schema_digest_and_field_drift(
    mutation: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    receipt = _receipt()
    payload = mutation(receipt.to_dict())

    with pytest.raises(PlanningWaveCompletionReceiptError):
        PlanningWaveCompletionReceipt.from_dict(payload)


@pytest.mark.parametrize(
    "encoded",
    [
        b"{}\n",
        b'{"kind":"successor_planning_wave_completion_receipt"}',
        b'{"schema_version":NaN}',
        b'{"schema_version":2,"schema_version":2}',
        b"\xff",
    ],
)
def test_completion_receipt_rejects_noncanonical_or_malformed_bytes(encoded: bytes) -> None:
    with pytest.raises(PlanningWaveCompletionReceiptError):
        PlanningWaveCompletionReceipt.from_canonical_bytes(encoded)
