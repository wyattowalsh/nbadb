from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import pickle
import sys
from dataclasses import replace
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "vpn_cohort_control.py"
MASTER_SECRET = b"test-only-vpn-cohort-master-key!!"
ALTERNATE_MASTER_SECRET = b"another-test-only-vpn-master-key"
SOURCE_SHA = "a" * 40
WORKFLOW_DIGEST = "b" * 64


def _load_module():
    spec = importlib.util.spec_from_file_location("github_vpn_cohort_control", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def module():
    return _load_module()


def _context(module, *, run_attempt: int = 1, master: bytes = MASTER_SECRET, **kwargs):
    return module.derive_run_key(
        master_secret=master,
        repository_id=987654321,
        run_id=123456789,
        run_attempt=run_attempt,
        source_sha=SOURCE_SHA,
        workflow_digest=WORKFLOW_DIGEST,
        **kwargs,
    )


def _passed_checks(module):
    return module.CanaryChecks(process=True, route=True, github=True, nba=True)


def _failed_checks(module):
    return module.CanaryChecks(process=False, route=False, github=False, nba=False)


def _server(slot_index: int) -> str:
    return f"us{slot_index + 1}.nordvpn.example"


def _exit(slot_index: int) -> str:
    return f"203.0.113.{slot_index + 1}"


def _probe_inventory(module, context, *, valid_count: int = 6):
    receipts = []
    for index in range(6):
        valid = index < valid_count
        receipts.append(
            module.build_probe_receipt(
                context,
                slot_index=index,
                server_identifier=_server(index),
                exit_identifier=_exit(index),
                checks=_passed_checks(module) if valid else _failed_checks(module),
                failure=None if valid else module.FailureKind.AUTH_CAPACITY_LOSS,
            )
        )
    return receipts


def _successful_reconnects(module, context, selection, challenge):
    return [
        module.build_reconnect_receipt(
            context,
            selection,
            challenge,
            slot=item.slot_label,
            server_identifier=_server(int(item.slot_label.removeprefix("slot-"))),
            exit_identifier=_exit(int(item.slot_label.removeprefix("slot-"))),
            checks=_passed_checks(module),
        )
        for item in selection.selected
    ]


def _reconnects_with_failure(
    module,
    context,
    selection,
    challenge,
    *,
    failed_label: str,
    failure,
):
    receipts = []
    for item in selection.selected:
        index = int(item.slot_label.removeprefix("slot-"))
        is_failed = item.slot_label == failed_label
        receipts.append(
            module.build_reconnect_receipt(
                context,
                selection,
                challenge,
                slot=item.slot_label,
                server_identifier=_server(index),
                exit_identifier=None if is_failed else _exit(index),
                checks=_failed_checks(module) if is_failed else _passed_checks(module),
                failure=failure if is_failed else None,
            )
        )
    return receipts


def test_run_key_and_commitments_are_deterministic_and_domain_separated(module) -> None:
    first = _context(module)
    second = _context(module)

    assert first.authority == second.authority
    assert first.commit_server("203.0.113.9") == second.commit_server("203.0.113.9")
    assert first.commit_exit("203.0.113.9") == second.commit_exit("203.0.113.9")
    assert first.commit_server("203.0.113.9").digest != first.commit_exit("203.0.113.9").digest
    assert first.commit_server("US1.NORDVPN.EXAMPLE") == first.commit_server("us1.nordvpn.example")
    assert "key=<redacted>" in repr(first)
    assert MASTER_SECRET.decode() not in repr(first)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(first)
    with pytest.raises(TypeError, match="cannot be copied"):
        copy.copy(first)
    with pytest.raises(TypeError, match="cannot be copied"):
        copy.deepcopy(first)

    first.close()
    assert first.closed is True
    with pytest.raises(module.AuthorityMismatchError, match="closed"):
        first.commit_server("us1.nordvpn.example")


def test_commitments_reject_foreign_run_attempt_or_domain(module) -> None:
    context = _context(module)
    receipt = _probe_inventory(module, context)[0]
    foreign_attempt = _context(module, run_attempt=2)
    wrong_master = _context(module, master=ALTERNATE_MASTER_SECRET)

    assert context.commit_server(_server(0)) != foreign_attempt.commit_server(_server(0))
    for foreign in (foreign_attempt, wrong_master):
        with pytest.raises(module.AuthorityMismatchError):
            module.validate_probe_receipt(foreign, receipt)

    with pytest.raises(module.InputValidationError, match="fixed audited domain"):
        _context(module, derivation_domain_id="nbadb.vpn-cohort.run-key.test-v2")
    with pytest.raises(module.InputValidationError, match="current audited version"):
        _context(module, key_version="hmac-sha256-v2")

    tampered_payload = receipt.to_payload()
    tampered_payload["checks"] = {
        "process": True,
        "route": True,
        "github": True,
        "nba": False,
    }
    tampered_payload["failure"] = module.FailureKind.NBA_FAILURE.value
    with pytest.raises(module.ReceiptIntegrityError):
        module.validate_probe_receipt(context, tampered_payload)


def test_marker_payload_never_contains_server_or_exit_ip(module) -> None:
    context = _context(module)
    receipt = _probe_inventory(module, context)[0]
    encoded = json.dumps(receipt.to_payload(), sort_keys=True)

    assert _server(0) not in encoded
    assert _exit(0) not in encoded
    assert MASTER_SECRET.decode() not in encoded
    assert "master_secret" not in encoded
    assert "run_key" not in encoded
    assert receipt.to_payload()["server_commitment"]["kind"] == "server"
    assert receipt.to_payload()["exit_commitment"]["kind"] == "exit"
    restored = module.ProbeReceipt.from_payload(json.loads(encoded))
    assert module.validate_probe_receipt(context, restored) == receipt

    with pytest.raises(module.InputValidationError, match="exact booleans"):
        module.build_probe_receipt(
            context,
            slot_index=0,
            server_identifier=_server(0),
            exit_identifier=_exit(0),
            checks=module.CanaryChecks(process=1, route=True, github=True, nba=True),
        )


@pytest.mark.parametrize("valid_count", [6, 5, 4])
def test_selector_prefers_six_then_five_then_four(module, valid_count: int) -> None:
    context = _context(module)
    selection = module.select_cohort(
        context, _probe_inventory(module, context, valid_count=valid_count)
    )

    assert selection.cohort_size == valid_count
    assert selection.selected_labels == tuple(f"slot-{index}" for index in range(valid_count))
    assert selection.distinct_server_count == valid_count
    assert selection.distinct_exit_count == valid_count
    assert selection.generation == 0
    module.validate_selection(context, selection)
    restored = module.CohortSelection.from_payload(json.loads(json.dumps(selection.to_payload())))
    assert module.validate_selection(context, restored) == selection


def test_selector_blocks_below_four_or_on_duplicate_commitment(module) -> None:
    context = _context(module)
    with pytest.raises(module.InsufficientCapacityError, match="fewer than four"):
        module.select_cohort(context, _probe_inventory(module, context, valid_count=3))

    duplicate = _probe_inventory(module, context)
    duplicate[5] = module.build_probe_receipt(
        context,
        slot_index=5,
        server_identifier=_server(0),
        exit_identifier=_exit(5),
        checks=_passed_checks(module),
    )
    with pytest.raises(module.DuplicateCommitmentError, match="server"):
        module.select_cohort(context, duplicate)

    duplicate_exit = _probe_inventory(module, context)
    duplicate_exit[5] = module.build_probe_receipt(
        context,
        slot_index=5,
        server_identifier=_server(5),
        exit_identifier=_exit(0),
        checks=_passed_checks(module),
    )
    with pytest.raises(module.DuplicateCommitmentError, match="exit"):
        module.select_cohort(context, duplicate_exit)

    with pytest.raises(module.ProbeInventoryError, match="exactly six"):
        module.select_cohort(context, duplicate[:-1])


def test_permutation_does_not_change_selected_cohort(module) -> None:
    context = _context(module)
    inventory = _probe_inventory(module, context, valid_count=5)

    forward = module.select_cohort(context, inventory)
    for permutation in itertools.permutations(inventory):
        permuted_selection = module.select_cohort(context, permutation)
        assert forward == permuted_selection
        assert forward.to_payload() == permuted_selection.to_payload()


def test_reconnect_barrier_admits_every_selected_slot_once(module) -> None:
    context = _context(module)
    selection = module.select_cohort(context, _probe_inventory(module, context))
    challenge = module.create_barrier_challenge(context, selection, nonce=b"barrier-one-nonce")
    reconnects = _successful_reconnects(module, context, selection, challenge)

    restored_challenge = module.BarrierChallenge.from_payload(challenge.to_payload())
    assert module.validate_barrier_challenge(context, selection, restored_challenge) == challenge
    restored_reconnect = module.ReconnectReceipt.from_payload(reconnects[0].to_payload())
    assert (
        module.validate_reconnect_receipt(context, selection, challenge, restored_reconnect)
        == reconnects[0]
    )

    admission = module.admit_reconnected_cohort(
        context, selection, challenge, list(reversed(reconnects))
    )

    assert admission.cohort_size == 6
    assert tuple(item.slot_label for item in admission.admitted) == selection.selected_labels
    assert admission.selection_digest == selection.selection_digest
    assert admission.challenge_id == challenge.challenge_id
    assert admission.reselection_count == 0
    encoded = json.dumps(admission.to_payload(), sort_keys=True)
    assert not any(raw in encoded for raw in [*map(_server, range(6)), *map(_exit, range(6))])
    restored_admission = module.AdmissionReceipt.from_payload(json.loads(encoded))
    assert (
        module.validate_admission_receipt(context, selection, challenge, restored_admission)
        == admission
    )


def test_reconnect_barrier_rejects_missing_foreign_or_replayed_slot(module) -> None:
    context = _context(module)
    selection = module.select_cohort(context, _probe_inventory(module, context))
    challenge = module.create_barrier_challenge(context, selection, nonce=b"barrier-one-nonce")
    reconnects = _successful_reconnects(module, context, selection, challenge)

    with pytest.raises(module.BarrierAdmissionError, match="one receipt"):
        module.admit_reconnected_cohort(context, selection, challenge, reconnects[:-1])

    replayed = [*reconnects[:-1], reconnects[0]]
    with pytest.raises(module.BarrierAdmissionError, match="replayed"):
        module.admit_reconnected_cohort(context, selection, challenge, replayed)

    next_challenge = module.create_barrier_challenge(context, selection, nonce=b"barrier-two-nonce")
    with pytest.raises(module.BarrierAdmissionError, match="another barrier"):
        module.admit_reconnected_cohort(context, selection, next_challenge, reconnects)

    foreign_context = _context(module, run_attempt=2)
    foreign_selection = module.select_cohort(
        foreign_context, _probe_inventory(module, foreign_context)
    )
    foreign_challenge = module.create_barrier_challenge(
        foreign_context, foreign_selection, nonce=b"foreign-barrier-nonce"
    )
    foreign_receipt = _successful_reconnects(
        module, foreign_context, foreign_selection, foreign_challenge
    )[0]
    mixed = [foreign_receipt, *reconnects[1:]]
    with pytest.raises(module.AuthorityMismatchError):
        module.admit_reconnected_cohort(context, selection, challenge, mixed)


def test_only_one_typed_auth_capacity_reselection_is_permitted(module) -> None:
    context = _context(module)
    probes = _probe_inventory(module, context)
    selection = module.select_cohort(context, probes)
    challenge = module.create_barrier_challenge(context, selection, nonce=b"barrier-one-nonce")
    reconnects = _reconnects_with_failure(
        module,
        context,
        selection,
        challenge,
        failed_label="slot-5",
        failure=module.FailureKind.AUTH_CAPACITY_LOSS,
    )

    decision = module.reselect_after_typed_loss(context, probes, selection, challenge, reconnects)
    assert decision.selection.cohort_size == 5
    assert decision.selection.generation == 1
    assert decision.receipt.failed_slots == ("slot-5",)
    assert decision.receipt.failure_counts == (("auth_capacity_loss", 1),)
    assert "slot-5" not in decision.selection.selected_labels
    restored_reselection = module.ReselectionReceipt.from_payload(decision.receipt.to_payload())
    assert (
        module.validate_reselection_receipt(
            context, selection, decision.selection, restored_reselection
        )
        == decision.receipt
    )

    next_challenge = module.create_barrier_challenge(
        context, decision.selection, nonce=b"barrier-two-nonce"
    )
    next_reconnects = _successful_reconnects(module, context, decision.selection, next_challenge)
    admission = module.admit_reconnected_cohort(
        context,
        decision.selection,
        next_challenge,
        next_reconnects,
        previous_selection=selection,
        reselection_receipt=decision.receipt,
    )
    assert admission.cohort_size == 5
    assert admission.reselection_count == 1

    with pytest.raises(module.ReselectionNotPermittedError, match="already consumed"):
        module.reselect_after_typed_loss(
            context,
            probes,
            selection,
            challenge,
            reconnects,
            prior_reselection=decision.receipt,
        )

    route_failure = replace(
        reconnects[-1],
        failure=module.FailureKind.ROUTE_FAILURE,
        receipt_mac="0" * 64,
    )
    route_failure = module.build_reconnect_receipt(
        context,
        selection,
        challenge,
        slot=route_failure.slot_label,
        server_identifier=_server(5),
        exit_identifier=None,
        checks=_failed_checks(module),
        failure=module.FailureKind.ROUTE_FAILURE,
    )
    with pytest.raises(module.BarrierAdmissionError, match="blocks admission"):
        module.reselect_after_typed_loss(
            context, probes, selection, challenge, [*reconnects[:-1], route_failure]
        )


def test_reselection_blocks_when_typed_loss_would_leave_three(module) -> None:
    context = _context(module)
    probes = _probe_inventory(module, context, valid_count=4)
    selection = module.select_cohort(context, probes)
    challenge = module.create_barrier_challenge(context, selection, nonce=b"barrier-one-nonce")
    reconnects = _reconnects_with_failure(
        module,
        context,
        selection,
        challenge,
        failed_label="slot-3",
        failure=module.FailureKind.CAPACITY_LOSS,
    )

    with pytest.raises(module.InsufficientCapacityError, match="fewer than four"):
        module.reselect_after_typed_loss(context, probes, selection, challenge, reconnects)
