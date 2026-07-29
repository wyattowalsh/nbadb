from __future__ import annotations

from dataclasses import replace
from typing import Any

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
)

_SOURCE_SHA = "a" * 40
_DATABASE_SHA = "b" * 64
_REPORT_SHA = "c" * 64
_ARTIFACT_DIGEST = "sha256:" + "d" * 64
_LANE_A_SHA = "e" * 64
_LANE_B_SHA = "f" * 64
_SEMANTIC_COVERAGE_SHA = "1" * 64


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
    )


def _receipt(transaction: CheckpointTransaction | None = None) -> CheckpointArtifactReceipt:
    transaction = transaction or _built()
    assert transaction.build is not None
    return CheckpointArtifactReceipt(
        artifact_id=12345,
        artifact_run_id=98765,
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
            lanes=("not-a-lane",),  # type: ignore[arg-type]
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


def test_deserialization_revalidates_receipt_binding() -> None:
    transaction = _built().mark_uploaded_verified(_receipt())
    payload = transaction.to_dict()
    payload["receipt"]["chain_id"] = "forged-chain"

    with pytest.raises(CheckpointContractError, match="chain_id"):
        CheckpointTransaction.from_dict(payload)


def test_committed_receipt_is_unavailable_before_commit() -> None:
    with pytest.raises(CheckpointTransitionError, match="expected committed"):
        assert _built().mark_uploaded_verified(_receipt()).committed_receipt
