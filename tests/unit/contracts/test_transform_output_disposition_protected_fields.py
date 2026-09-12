from __future__ import annotations

from dataclasses import fields

import pytest

from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    TransformOutputDispositionAuditMetadataV1,
)
from nbadb.contracts.transform_output_disposition_protected_fields import (
    DERIVED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1,
    DERIVED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1,
    PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1,
    PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1,
    TransformOutputDispositionProtectedFieldError,
    validate_transform_output_disposition_protected_fields_v1,
)


def test_protected_and_derived_inventories_exactly_partition_current_dtos() -> None:
    validate_transform_output_disposition_protected_fields_v1()
    assert tuple(item.name for item in fields(CurrentTransformOutputDispositionV1)) == (
        *PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1,
        *DERIVED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1,
    )
    assert tuple(item.name for item in fields(TransformOutputCapabilityPolicyV1)) == (
        *PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1,
        *DERIVED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1,
    )


def test_protected_inventory_contains_every_semantic_and_capability_surface() -> None:
    assert set(PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1) == {
        "output_name",
        "family",
        "table_contract_sha256",
        "schema_identity_sha256",
        "transform_identity_sha256",
        "ordered_columns_sha256",
        "dependency_identity_sha256",
        "state",
        "capability_policy",
        "semantic_claims",
        "reason_code",
        "evidence_references",
        "revalidation_triggers",
    }
    assert set(PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1) == {
        "execute",
        "primary_materialize",
        "stable_load",
        "transform_publication",
        "chat_ceiling",
    }


def test_audit_labels_never_enter_the_protected_semantic_inventory() -> None:
    audit_fields = {item.name for item in fields(TransformOutputDispositionAuditMetadataV1)}
    protected = set(PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1) | set(
        PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1
    )
    assert protected.isdisjoint(audit_fields)
    assert {
        "author_task_id",
        "author_role",
        "reviewer_task_id",
        "reviewer_role",
        "establishes_independence",
    }.isdisjoint(protected)


def test_inventory_validation_fails_closed_when_a_declared_field_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nbadb.contracts import transform_output_disposition_protected_fields as module

    monkeypatch.setattr(
        module,
        "PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1",
        PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1[:-1],
    )
    with pytest.raises(TransformOutputDispositionProtectedFieldError, match="typed DTO"):
        module.validate_transform_output_disposition_protected_fields_v1()
