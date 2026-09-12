"""Exact mutation inventory for current transform-output disposition semantics.

This module names protected DTO fields only.  It does not author dispositions,
approve semantic claims, or admit materialization or publication.
"""

from __future__ import annotations

from dataclasses import fields

from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
)

__all__ = [
    "DERIVED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1",
    "DERIVED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1",
    "PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1",
    "PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1",
    "TransformOutputDispositionProtectedFieldError",
    "validate_transform_output_disposition_protected_fields_v1",
]


class TransformOutputDispositionProtectedFieldError(ValueError):
    """The protected-field inventory differs from the current typed DTOs."""


PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1: tuple[str, ...] = (
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
)

DERIVED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1: tuple[str, ...] = ("entry_sha256",)

PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1: tuple[str, ...] = (
    "execute",
    "primary_materialize",
    "stable_load",
    "transform_publication",
    "chat_ceiling",
)

DERIVED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1: tuple[str, ...] = ("policy_sha256",)


def _require_exact_inventory(
    *,
    label: str,
    observed: tuple[str, ...],
    protected: tuple[str, ...],
    derived: tuple[str, ...],
) -> None:
    declared = (*protected, *derived)
    if len(set(declared)) != len(declared) or observed != declared:
        raise TransformOutputDispositionProtectedFieldError(
            f"{label} protected and derived fields differ from the typed DTO"
        )


def validate_transform_output_disposition_protected_fields_v1() -> None:
    """Fail closed if either current typed DTO changes without inventory review."""

    _require_exact_inventory(
        label="current disposition entry",
        observed=tuple(item.name for item in fields(CurrentTransformOutputDispositionV1)),
        protected=PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1,
        derived=DERIVED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1,
    )
    _require_exact_inventory(
        label="capability policy",
        observed=tuple(item.name for item in fields(TransformOutputCapabilityPolicyV1)),
        protected=PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1,
        derived=DERIVED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1,
    )


validate_transform_output_disposition_protected_fields_v1()
