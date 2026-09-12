from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from nbadb.core.nba_api_terminal_state_verifier import (
    NbaApiTerminalStateVerificationError,
    build_independent_terminal_state_payload,
    verify_terminal_state_authority_file,
)

if TYPE_CHECKING:
    from pathlib import Path

_POLICY_FIELDS = {
    "accounting_state_contracts",
    "domain_separators",
    "incomplete_request_states",
    "kind",
    "nba_api_version",
    "optional_absent_contract",
    "release_terminal_request_states",
    "result_occurrence_states",
    "schema_version",
    "task_id",
    "wire_request_states",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _resign(payload: dict[str, object]) -> None:
    payload["source_inventory_sha256"] = _digest(payload["source_inventory"])
    payload["terminal_policy_sha256"] = _digest({key: payload[key] for key in _POLICY_FIELDS})
    body = dict(payload)
    body.pop("payload_sha256", None)
    payload["payload_sha256"] = _digest(body)


def _unavailable_relabel_candidate(evidence_kind: str) -> dict[str, object]:
    payload = deepcopy(build_independent_terminal_state_payload())
    contracts = payload["accounting_state_contracts"]
    assert isinstance(contracts, list)
    unavailable = contracts[2]
    assert isinstance(unavailable, dict)
    unavailable["evidence_kind"] = evidence_kind
    unavailable["requires_independent_verification"] = False
    unavailable["requires_typed_upstream_unavailable_evidence"] = False
    _resign(payload)
    return payload


def _assert_rejected(tmp_path: Path, label: str, payload: dict[str, object]) -> None:
    candidate = tmp_path / f"{label}.json"
    candidate.write_bytes(_canonical(payload) + b"\n")
    with pytest.raises(NbaApiTerminalStateVerificationError, match="independent policy"):
        verify_terminal_state_authority_file(candidate)


def test_timeout_cannot_be_relabelled_upstream_unavailable(tmp_path: Path) -> None:
    _assert_rejected(
        tmp_path,
        "timeout-as-unavailable",
        _unavailable_relabel_candidate("transport_timeout"),
    )


def test_parser_or_response_error_cannot_be_relabelled_upstream_unavailable(
    tmp_path: Path,
) -> None:
    _assert_rejected(
        tmp_path,
        "parser-error-as-unavailable",
        _unavailable_relabel_candidate("parser_or_response_contract_failure"),
    )


def test_retry_exhaustion_cannot_be_relabelled_upstream_unavailable(
    tmp_path: Path,
) -> None:
    _assert_rejected(
        tmp_path,
        "retry-exhaustion-as-unavailable",
        _unavailable_relabel_candidate("retry_exhaustion"),
    )


def test_vpn_or_infrastructure_failure_cannot_be_release_terminal(
    tmp_path: Path,
) -> None:
    _assert_rejected(
        tmp_path,
        "vpn-infrastructure-as-release",
        _unavailable_relabel_candidate("vpn_or_infrastructure_failure"),
    )


def test_budget_or_cap_exhaustion_cannot_be_release_terminal(tmp_path: Path) -> None:
    _assert_rejected(
        tmp_path,
        "budget-cap-as-release",
        _unavailable_relabel_candidate("budget_or_cap_exhaustion"),
    )


def test_contract_blocked_or_implementation_gap_cannot_be_release_terminal(
    tmp_path: Path,
) -> None:
    _assert_rejected(
        tmp_path,
        "contract-gap-as-release",
        _unavailable_relabel_candidate("implementation_or_modeled_contract_gap"),
    )


def test_optional_absent_result_cannot_be_request_success(tmp_path: Path) -> None:
    payload = deepcopy(build_independent_terminal_state_payload())
    contracts = payload["accounting_state_contracts"]
    assert isinstance(contracts, list)
    success_empty = contracts[1]
    assert isinstance(success_empty, dict)
    success_empty["required_result_occurrence"] = "absent_optional"
    _resign(payload)
    _assert_rejected(tmp_path, "optional-absent-as-success", payload)
