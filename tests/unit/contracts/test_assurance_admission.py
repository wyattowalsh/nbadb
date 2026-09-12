from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from nbadb.contracts.assurance_admission import (
    AssuranceAdmission,
    AssuranceAdmissionError,
    AssuranceArtifactReceipt,
    ModelStatus,
    require_production_admissible,
)


def _admission(*, model_status: str = "GREEN") -> AssuranceAdmission:
    return AssuranceAdmission(
        source_sha="1" * 40,
        assurance_manifest_sha256="2" * 64,
        generation_semantic_sha256="3" * 64,
        provider_evidence_sha256="4" * 64,
        provider_authority_sha256="5" * 64,
        authority_semantic_diff_sha256="6" * 64,
        authority_update_mode="full",
        first_extraction=True,
        model_status=cast("ModelStatus", model_status),
    )


def _artifact_receipt(
    *,
    admission: AssuranceAdmission | None = None,
) -> AssuranceArtifactReceipt:
    bound_admission = admission or _admission()
    return AssuranceArtifactReceipt.bind(
        artifact_id=701,
        artifact_name="nbadb-contract-assurance-run-123-attempt-1",
        artifact_digest="sha256:" + "6" * 64,
        artifact_size_bytes=4096,
        artifact_run_id=123,
        artifact_run_attempt=1,
        owner_head_sha=bound_admission.source_sha,
        assurance_admission=bound_admission,
    )


def test_admission_round_trips_as_canonical_immutable_receipt() -> None:
    admission = _admission()

    payload = admission.to_dict()
    expected_json = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert admission.canonical_json == expected_json
    assert admission.sha256 == hashlib.sha256(expected_json.encode()).hexdigest()
    assert admission.digest == admission.sha256
    assert AssuranceAdmission.from_dict(dict(reversed(tuple(payload.items())))) == admission
    assert admission.is_production_admissible is True
    assert admission.require_production_admissible() is admission
    assert require_production_admissible(admission) is admission

    with pytest.raises(FrozenInstanceError):
        admission.model_status = "RED"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("source_sha", "1" * 39),
        ("source_sha", "A" * 40),
        ("assurance_manifest_sha256", "2" * 63),
        ("generation_semantic_sha256", "B" * 64),
        ("provider_evidence_sha256", "sha256:" + "4" * 64),
        ("provider_authority_sha256", "g" * 64),
        ("authority_semantic_diff_sha256", "6" * 63),
        ("authority_update_mode", "blocked"),
        ("first_extraction", 1),
        ("model_status", "green"),
        ("model_status", "UNKNOWN"),
    ],
)
def test_admission_rejects_invalid_identity_fields(field_name: str, value: object) -> None:
    payload = cast("dict[str, object]", _admission().to_dict())
    payload[field_name] = value

    with pytest.raises(AssuranceAdmissionError):
        AssuranceAdmission.from_dict(payload)


@pytest.mark.parametrize("field_name", list(_admission().to_dict()))
def test_admission_rejects_every_missing_field(field_name: str) -> None:
    payload = _admission().to_dict()
    del payload[field_name]

    with pytest.raises(AssuranceAdmissionError, match="fields are invalid"):
        AssuranceAdmission.from_dict(payload)


def test_admission_rejects_unknown_fields_and_keeps_red_model_advisory() -> None:
    payload = _admission().to_dict()
    payload["path"] = "/tmp/private-assurance"
    with pytest.raises(AssuranceAdmissionError, match="unexpected=path"):
        AssuranceAdmission.from_dict(payload)

    red = _admission(model_status="RED")
    assert red.model_status == "RED"
    assert red.is_production_admissible is True
    assert red.require_production_admissible() is red
    assert require_production_admissible(red) is red


def test_admission_requires_full_mode_for_first_extraction() -> None:
    payload = _admission().to_dict()
    payload["authority_update_mode"] = "recent_window"

    with pytest.raises(
        AssuranceAdmissionError,
        match="first extraction requires authority_update_mode full",
    ):
        AssuranceAdmission.from_dict(payload)


def test_artifact_receipt_round_trips_and_cross_binds_inner_receipt() -> None:
    receipt = _artifact_receipt()
    payload = receipt.to_dict()
    expected_json = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert receipt.assurance_admission_sha256 == receipt.assurance_admission.sha256
    assert receipt.canonical_json == expected_json
    assert receipt.sha256 == hashlib.sha256(expected_json.encode()).hexdigest()
    assert receipt.digest == receipt.sha256
    assert receipt.is_production_admissible is True
    assert receipt.require_production_admissible() is receipt
    assert require_production_admissible(receipt) is receipt
    receipt.validate_binding(AssuranceAdmission.from_dict(receipt.assurance_admission.to_dict()))
    assert AssuranceArtifactReceipt.from_dict(payload) == receipt

    with pytest.raises(FrozenInstanceError):
        receipt.artifact_id = 702  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("artifact_id", 0),
        ("artifact_id", True),
        ("artifact_name", "/tmp/assurance"),
        ("artifact_name", "parent/child"),
        ("artifact_name", "parent\\child"),
        ("artifact_name", "."),
        ("artifact_name", ""),
        ("artifact_digest", "6" * 64),
        ("artifact_digest", "sha256:" + "A" * 64),
        ("artifact_size_bytes", 0),
        ("artifact_run_id", -1),
        ("artifact_run_attempt", False),
        ("owner_head_sha", "7" * 64),
        ("owner_head_sha", "F" * 40),
    ],
)
def test_artifact_receipt_rejects_invalid_identity_fields(
    field_name: str,
    value: object,
) -> None:
    payload = _artifact_receipt().to_dict()
    payload[field_name] = value

    with pytest.raises(AssuranceAdmissionError):
        AssuranceArtifactReceipt.from_dict(payload)


@pytest.mark.parametrize("field_name", list(_artifact_receipt().to_dict()))
def test_artifact_receipt_rejects_every_missing_field(field_name: str) -> None:
    payload = _artifact_receipt().to_dict()
    del payload[field_name]

    with pytest.raises(AssuranceAdmissionError, match="fields are invalid"):
        AssuranceArtifactReceipt.from_dict(payload)


def test_artifact_receipt_rejects_unknown_or_non_object_inner_receipt() -> None:
    payload = _artifact_receipt().to_dict()
    payload["message"] = "untrusted diagnostic"
    with pytest.raises(AssuranceAdmissionError, match="unexpected=message"):
        AssuranceArtifactReceipt.from_dict(payload)

    payload = _artifact_receipt().to_dict()
    payload["assurance_admission"] = []
    with pytest.raises(AssuranceAdmissionError, match="must be an object"):
        AssuranceArtifactReceipt.from_dict(payload)


def test_artifact_receipt_rejects_inner_digest_and_owner_cross_binding_drift() -> None:
    payload = _artifact_receipt().to_dict()
    payload["assurance_admission_sha256"] = "8" * 64
    with pytest.raises(AssuranceAdmissionError, match="digest does not match"):
        AssuranceArtifactReceipt.from_dict(payload)

    payload = _artifact_receipt().to_dict()
    payload["owner_head_sha"] = "9" * 40
    with pytest.raises(AssuranceAdmissionError, match="owner head does not match"):
        AssuranceArtifactReceipt.from_dict(payload)

    payload = _artifact_receipt().to_dict()
    inner = payload["assurance_admission"]
    assert isinstance(inner, dict)
    inner["provider_authority_sha256"] = "a" * 64
    with pytest.raises(AssuranceAdmissionError, match="digest does not match"):
        AssuranceArtifactReceipt.from_dict(payload)


def test_artifact_receipt_rejects_unknown_inner_fields() -> None:
    payload = _artifact_receipt().to_dict()
    inner = payload["assurance_admission"]
    assert isinstance(inner, dict)
    inner["diagnostic_message"] = "not part of the immutable identity"

    with pytest.raises(AssuranceAdmissionError, match="unexpected=diagnostic_message"):
        AssuranceArtifactReceipt.from_dict(payload)


def test_artifact_receipt_rejects_separately_loaded_admission_drift() -> None:
    receipt = _artifact_receipt()
    other_payload = receipt.assurance_admission.to_dict()
    other_payload["provider_evidence_sha256"] = "a" * 64
    other = AssuranceAdmission.from_dict(other_payload)

    with pytest.raises(AssuranceAdmissionError, match="does not match the supplied"):
        receipt.validate_binding(other)


def test_artifact_receipt_keeps_red_model_advisory() -> None:
    receipt = _artifact_receipt(admission=_admission(model_status="RED"))

    assert receipt.assurance_admission.model_status == "RED"
    assert receipt.is_production_admissible is True
    assert receipt.require_production_admissible() is receipt
    assert require_production_admissible(receipt) is receipt
