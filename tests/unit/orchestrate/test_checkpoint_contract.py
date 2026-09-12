from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointContractError,
    CheckpointCoverageIdentity,
    CheckpointState,
    CheckpointTransaction,
    CheckpointTransitionError,
    CheckpointW2AuthorityIdentity,
)
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

_SOURCE_SHA = "a" * 40
_DATABASE_SHA = "b" * 64
_REPORT_SHA = "c" * 64
_ARTIFACT_DIGEST = "sha256:" + "d" * 64
_LANE_A_SHA = "e" * 64
_LANE_B_SHA = "f" * 64
_SEMANTIC_COVERAGE_SHA = "1" * 64


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8", errors="strict")).hexdigest()


def _w2_database_authority(seed: str = "fixture") -> W2DatabaseAuthorityReceiptV1:
    relation_counts = tuple(
        sorted(
            (
                table_name,
                1 if table_name == RAW_NBA_API_W2_OPERATION_TABLE else 0,
            )
            for table_name in (*PUBLIC_VALUE_AUTHORITY_TABLES, RAW_NBA_API_W2_OPERATION_TABLE)
        )
    )
    return W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=1,
        w2_source_call_admission_inventory_sha256=_digest(f"{seed}:admissions"),
        raw_authority_v2_bundle_count=1,
        raw_authority_v2_bundle_inventory_sha256=_digest(f"{seed}:raw-bundles"),
        raw_authority_v2_persistence_receipt_inventory_sha256=_digest(f"{seed}:raw-persistence"),
        w2_publication_receipt_count=1,
        w2_publication_receipt_inventory_sha256=_digest(f"{seed}:publications"),
        w2_exact_six_schema_inventory_sha256=_digest(f"{seed}:schemas"),
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=1,
        w2_relation_inventory_sha256=_digest(f"{seed}:relations"),
    )


def _w2_authority(seed: str = "fixture") -> CheckpointW2AuthorityIdentity:
    database_authority = _w2_database_authority(seed)
    return CheckpointW2AuthorityIdentity(
        database_authority=database_authority,
        database_authority_sha256=database_authority.receipt_sha256,
        expected_call_count=1,
        expected_call_inventory_sha256=_digest(f"{seed}:expected-calls"),
        database_authority_closed=True,
    )


def _lane_contracts() -> list[dict[str, object]]:
    return [
        {
            "lane_id": "lane-b",
            "coverage_units_hash": _LANE_B_SHA,
            "lane_index": 13,
            "planned_wave": 4,
            "schedule_priority": 99.0,
        },
        {
            "lane_id": "lane-a",
            "coverage_units_hash": _LANE_A_SHA,
            "lane_index": 8,
            "planned_wave": 1,
            "schedule_priority": 10.0,
        },
    ]


def _candidate() -> CheckpointTransaction:
    return CheckpointTransaction.candidate(
        chain_id="full-a1",
        source_sha=_SOURCE_SHA,
        generation=3,
        artifact_name="full-extraction-checkpoint-full-a1-iter-3",
        lane_contracts=_lane_contracts(),
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    )


def _built() -> CheckpointTransaction:
    return _candidate().mark_built(
        database_sha256=_DATABASE_SHA,
        report_sha256=_REPORT_SHA,
        w2_authority=_w2_authority(),
    )


def _receipt(transaction: CheckpointTransaction | None = None) -> CheckpointArtifactReceipt:
    transaction = transaction or _built()
    assert transaction.build is not None
    return CheckpointArtifactReceipt(
        artifact_id=12345,
        artifact_run_id=98765,
        artifact_run_attempt=1,
        artifact_name=transaction.artifact_name,
        artifact_digest=_ARTIFACT_DIGEST,
        artifact_size_bytes=4096,
        database_sha256=transaction.build.database_sha256,
        report_sha256=transaction.build.report_sha256,
        chain_id=transaction.identity.chain_id,
        source_sha=transaction.identity.source_sha,
        generation=transaction.identity.generation,
        coverage_fingerprint=transaction.identity.coverage.coverage_fingerprint,
        lane_inventory_sha256=(transaction.identity.coverage.lane_inventory_sha256),
        w2_authority_identity_sha256=transaction.build.w2_authority.identity_sha256,
    )


def test_coverage_identity_excludes_dispatch_fields_and_input_order() -> None:
    original = CheckpointCoverageIdentity.from_lane_contracts(
        _lane_contracts(),
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    )
    rescheduled = CheckpointCoverageIdentity.from_lane_contracts(
        [
            {
                "lane_id": "lane-a",
                "coverage_units_hash": _LANE_A_SHA,
                "lane_index": 1509,
                "planned_wave": 42,
                "schedule_priority": -1.0,
                "vpn_slot": 5,
            },
            {
                "lane_id": "lane-b",
                "coverage_units_hash": _LANE_B_SHA,
                "lane_index": 1510,
                "planned_wave": 42,
                "schedule_priority": -2.0,
                "vpn_slot": 1,
            },
        ],
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    )

    assert original == rescheduled
    assert original.coverage_fingerprint == rescheduled.coverage_fingerprint
    assert original.lane_inventory_sha256 == rescheduled.lane_inventory_sha256
    assert [lane.lane_id for lane in original.lanes] == ["lane-a", "lane-b"]


@given(order=st.permutations(tuple(range(8))))
def test_coverage_identity_is_invariant_to_arbitrary_lane_order(
    order: list[int],
) -> None:
    lane_contracts = [
        {
            "lane_id": f"lane-{index}",
            "coverage_units_hash": f"{index:064x}",
            "lane_index": index,
        }
        for index in range(8)
    ]
    baseline = CheckpointCoverageIdentity.from_lane_contracts(
        lane_contracts,
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    )
    permuted = CheckpointCoverageIdentity.from_lane_contracts(
        [
            {
                **lane_contracts[index],
                "lane_index": 10_000 + position,
            }
            for position, index in enumerate(order)
        ],
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    )

    assert permuted == baseline
    assert permuted.lane_inventory_sha256 == baseline.lane_inventory_sha256


def test_lane_inventory_digest_changes_when_stable_lane_contract_changes() -> None:
    original = CheckpointCoverageIdentity.from_lane_contracts(
        _lane_contracts(),
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    )
    changed = _lane_contracts()
    changed[0]["coverage_units_hash"] = "0" * 64

    assert (
        CheckpointCoverageIdentity.from_lane_contracts(
            changed,
            coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
        ).lane_inventory_sha256
        != original.lane_inventory_sha256
    )


def test_split_lane_inventory_can_bind_same_semantic_coverage_fingerprint() -> None:
    parent = CheckpointTransaction.candidate(
        chain_id="full-a1",
        source_sha=_SOURCE_SHA,
        generation=3,
        artifact_name="full-extraction-checkpoint-full-a1-iter-3",
        lane_contracts=[
            {
                "lane_id": "parent",
                "coverage_units_hash": "2" * 64,
            }
        ],
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    ).mark_built(
        database_sha256=_DATABASE_SHA,
        report_sha256=_REPORT_SHA,
        w2_authority=_w2_authority(),
    )
    descendants = CheckpointTransaction.candidate(
        chain_id="full-a1",
        source_sha=_SOURCE_SHA,
        generation=3,
        artifact_name="full-extraction-checkpoint-full-a1-iter-3",
        lane_contracts=[
            {
                "lane_id": "child-a",
                "coverage_units_hash": "3" * 64,
            },
            {
                "lane_id": "child-b",
                "coverage_units_hash": "4" * 64,
            },
        ],
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    ).mark_built(
        database_sha256=_DATABASE_SHA,
        report_sha256=_REPORT_SHA,
        w2_authority=_w2_authority(),
    )
    receipt = _receipt(parent)

    assert (
        parent.identity.coverage.coverage_fingerprint
        == descendants.identity.coverage.coverage_fingerprint
    )
    assert (
        parent.identity.coverage.lane_inventory_sha256
        != descendants.identity.coverage.lane_inventory_sha256
    )
    assert parent.mark_uploaded_verified(receipt).receipt == receipt
    with pytest.raises(CheckpointContractError, match="lane_inventory_sha256"):
        descendants.mark_uploaded_verified(receipt)


def test_coverage_identity_rejects_invalid_semantic_fingerprint() -> None:
    with pytest.raises(CheckpointContractError, match="coverage_fingerprint"):
        CheckpointCoverageIdentity.from_lane_contracts(
            _lane_contracts(),
            coverage_fingerprint="not-a-sha256",
        )


def test_coverage_identity_accepts_empty_lane_inventory() -> None:
    identity = CheckpointCoverageIdentity.from_lane_contracts(
        [],
        coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
    )

    assert identity.lanes == ()
    assert identity.coverage_fingerprint == _SEMANTIC_COVERAGE_SHA


def test_coverage_identity_rejects_duplicate_lane_ids() -> None:
    lanes = _lane_contracts()
    lanes[1]["lane_id"] = lanes[0]["lane_id"]

    with pytest.raises(CheckpointContractError, match="lane IDs must be unique"):
        CheckpointCoverageIdentity.from_lane_contracts(
            lanes,
            coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
        )


def test_coverage_identity_rejects_untyped_direct_lane_values() -> None:
    with pytest.raises(CheckpointContractError, match="LaneCoverageIdentity"):
        CheckpointCoverageIdentity(
            lanes=cast("Any", ("not-a-lane",)),
            coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("lane_id", ""),
        ("lane_id", " padded"),
        ("coverage_units_hash", "not-a-digest"),
        ("coverage_units_hash", "A" * 64),
    ],
)
def test_coverage_identity_rejects_invalid_stable_fields(
    field_name: str,
    value: object,
) -> None:
    lanes = _lane_contracts()
    lanes[0][field_name] = value

    with pytest.raises(CheckpointContractError):
        CheckpointCoverageIdentity.from_lane_contracts(
            lanes,
            coverage_fingerprint=_SEMANTIC_COVERAGE_SHA,
        )


def test_transaction_happy_path_binds_verified_receipt_before_commit() -> None:
    candidate = _candidate()
    built = candidate.mark_built(
        database_sha256=_DATABASE_SHA,
        report_sha256=_REPORT_SHA,
        w2_authority=_w2_authority(),
    )
    uploaded = built.mark_uploaded_verified(_receipt(built))
    committed = uploaded.commit()

    assert candidate.state is CheckpointState.CANDIDATE
    assert built.state is CheckpointState.BUILT
    assert uploaded.state is CheckpointState.UPLOADED_VERIFIED
    assert committed.state is CheckpointState.COMMITTED
    assert committed.committed_receipt == _receipt(built)
    assert committed.identity == candidate.identity


@pytest.mark.parametrize(
    ("factory", "operation", "message"),
    [
        (
            _built,
            lambda transaction: transaction.mark_built(
                database_sha256=_DATABASE_SHA,
                report_sha256=_REPORT_SHA,
                w2_authority=_w2_authority(),
            ),
            "expected candidate",
        ),
        (
            _candidate,
            lambda transaction: transaction.mark_uploaded_verified(_receipt()),
            "expected built",
        ),
        (_candidate, lambda transaction: transaction.commit(), "expected uploaded_verified"),
        (_built, lambda transaction: transaction.commit(), "expected uploaded_verified"),
    ],
)
def test_illegal_transitions_fail_closed(
    factory: Any,
    operation: Any,
    message: str,
) -> None:
    with pytest.raises(CheckpointTransitionError, match=message):
        operation(factory())


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("artifact_name", "other-artifact"),
        ("database_sha256", "0" * 64),
        ("report_sha256", "0" * 64),
        ("chain_id", "other-chain"),
        ("source_sha", "0" * 40),
        ("generation", 4),
        ("coverage_fingerprint", "0" * 64),
        ("lane_inventory_sha256", "0" * 64),
        ("w2_authority_identity_sha256", "0" * 64),
    ],
)
def test_uploaded_verified_rejects_receipt_binding_mismatch(
    field_name: str,
    value: object,
) -> None:
    built = _built()
    receipt = replace(_receipt(built), **{field_name: value})

    with pytest.raises(CheckpointContractError, match=field_name):
        built.mark_uploaded_verified(receipt)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("artifact_id", 0),
        ("artifact_id", True),
        ("artifact_run_id", -1),
        ("artifact_digest", "d" * 64),
        ("artifact_digest", "sha256:" + "D" * 64),
        ("artifact_size_bytes", 0),
    ],
)
def test_receipt_rejects_invalid_artifact_identity(
    field_name: str,
    value: object,
) -> None:
    receipt = _receipt()

    with pytest.raises(CheckpointContractError):
        replace(receipt, **{field_name: value})


@pytest.mark.parametrize(
    "factory",
    [
        _candidate,
        _built,
        lambda: _built().mark_uploaded_verified(_receipt()),
        lambda: _built().mark_uploaded_verified(_receipt()).commit(),
    ],
)
def test_transaction_serialization_round_trip(factory: Any) -> None:
    transaction = factory()

    assert CheckpointTransaction.from_dict(transaction.to_dict()) == transaction


def test_deserialization_rejects_forged_lane_inventory_digest() -> None:
    payload = _candidate().to_dict()
    payload["identity"]["coverage"]["lane_inventory_sha256"] = "0" * 64

    with pytest.raises(CheckpointContractError, match="digest does not match"):
        CheckpointTransaction.from_dict(payload)


def test_deserialization_rejects_committed_state_without_receipt() -> None:
    payload = _built().to_dict()
    payload["state"] = CheckpointState.COMMITTED.value

    with pytest.raises(CheckpointContractError, match="missing=receipt"):
        CheckpointTransaction.from_dict(payload)


def test_deserialization_rejects_candidate_with_build_payload() -> None:
    payload = _candidate().to_dict()
    payload["build"] = {
        "database_sha256": _DATABASE_SHA,
        "report_sha256": _REPORT_SHA,
    }

    with pytest.raises(CheckpointContractError, match="unexpected=build"):
        CheckpointTransaction.from_dict(payload)


def test_deserialization_rejects_build_missing_w2_authority() -> None:
    payload = _built().to_dict()
    del payload["build"]["w2_authority"]

    with pytest.raises(CheckpointContractError, match="missing=w2_authority"):
        CheckpointTransaction.from_dict(payload)


def test_deserialization_rejects_foreign_w2_database_authority() -> None:
    payload = _built().to_dict()
    payload["build"]["w2_authority"]["w2_database_authority"]["kind"] = "foreign"

    with pytest.raises(CheckpointContractError, match="foreign database receipt"):
        CheckpointTransaction.from_dict(payload)


def test_deserialization_revalidates_receipt_binding() -> None:
    transaction = _built().mark_uploaded_verified(_receipt())
    payload = transaction.to_dict()
    payload["receipt"]["chain_id"] = "forged-chain"

    with pytest.raises(CheckpointContractError, match="chain_id"):
        CheckpointTransaction.from_dict(payload)


def test_committed_receipt_is_unavailable_before_commit() -> None:
    with pytest.raises(CheckpointTransitionError, match="expected committed"):
        assert _built().mark_uploaded_verified(_receipt()).committed_receipt


class TestArtifactRunAttemptV3:
    """Checkpoint contract v3 binds the artifact owner's exact run attempt."""

    def test_receipt_round_trips_run_attempt(self) -> None:
        receipt = _receipt()
        assert receipt.artifact_run_attempt >= 1
        payload = receipt.to_dict()
        assert payload["artifact_run_attempt"] == receipt.artifact_run_attempt
        assert CheckpointArtifactReceipt.from_dict(payload) == receipt

    def test_missing_attempt_key_rejected(self) -> None:
        payload = _receipt().to_dict()
        del payload["artifact_run_attempt"]
        with pytest.raises(CheckpointContractError, match="missing=artifact_run_attempt"):
            CheckpointArtifactReceipt.from_dict(payload)

    @pytest.mark.parametrize("bad", [0, -1])
    def test_nonpositive_attempt_rejected(self, bad: int) -> None:
        payload = _receipt().to_dict()
        payload["artifact_run_attempt"] = bad
        with pytest.raises(CheckpointContractError, match="artifact_run_attempt"):
            CheckpointArtifactReceipt.from_dict(payload)

    def test_v2_transaction_payload_rejected(self) -> None:
        transaction = _built()
        payload = transaction.to_dict()
        assert payload["schema_version"] == 3
        payload["schema_version"] = 2
        with pytest.raises(CheckpointContractError, match="schema version"):
            CheckpointTransaction.from_dict(payload)

    def test_attempt_is_never_inferred_from_artifact_name(self) -> None:
        payload = _receipt().to_dict()
        # A name carrying an attempt-like token must not satisfy the field.
        payload["artifact_name"] = "full-extraction-checkpoint-attempt-7"
        with pytest.raises(CheckpointContractError, match="artifact_run_attempt"):
            payload.pop("artifact_run_attempt")
            CheckpointArtifactReceipt.from_dict(payload)
