"""Verified model/field authority admitted into raw-request generations.

The raw-request store must not accept caller-selected field or model digests.
This module derives both identities from a complete assurance generation only
after that generation has been independently revalidated against the current
source tree and the exact pinned ``nba_api`` checkout.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar, NoReturn, cast

from nbadb.contracts.assurance import (
    ANALYTICAL_NEEDS_NAME,
    BRONZE_CONTRACT_NAME,
    FIELD_FATE_NAME,
    FIELD_FATE_STRUCTURE_NAME,
    FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
    METRIC_NAME,
    MODEL_CANDIDATE_CENSUS_NAME,
    PROVIDER_SURFACE_NAME,
    RAW_REQUEST_SCHEMA_NAME,
    RUNTIME_CONTRACT_NAME,
    STABLE_MODEL_DISPOSITION_NAME,
    STAGING_ROUTE_NAME,
    STAR_SEMANTIC_INVENTORY_NAME,
    STAR_TABLE_NAME,
    TEMPORAL_NAME,
    UPSTREAM_CONTRACT_NAME,
    AssuranceGeneration,
    ContractAssuranceError,
    validate_assurance_generation,
)
from nbadb.contracts.assurance_admission import (
    AssuranceAdmissionError,
    require_production_admissible,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOWER_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")

_FIELD_AUTHORITY_CHILD_NAMES = (
    UPSTREAM_CONTRACT_NAME,
    RUNTIME_CONTRACT_NAME,
    PROVIDER_SURFACE_NAME,
    BRONZE_CONTRACT_NAME,
    RAW_REQUEST_SCHEMA_NAME,
    STAGING_ROUTE_NAME,
    FIELD_FATE_STRUCTURE_NAME,
    FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
    FIELD_FATE_NAME,
    TEMPORAL_NAME,
)
_MODEL_AUTHORITY_CHILD_NAMES = (
    STAR_TABLE_NAME,
    ANALYTICAL_NEEDS_NAME,
    MODEL_CANDIDATE_CENSUS_NAME,
    STABLE_MODEL_DISPOSITION_NAME,
    STAR_SEMANTIC_INVENTORY_NAME,
    METRIC_NAME,
)


class RawRequestAssuranceError(ValueError):
    """Raised when a raw-request model/field authority is not exact."""


def _fail(message: str) -> NoReturn:
    raise RawRequestAssuranceError(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RawRequestAssuranceError(
            "raw-request assurance authority is not canonical JSON"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _LOWER_SHA256.fullmatch(value) is None:
        _fail(f"{field} must be a lowercase SHA-256")
    return value


def _require_git_sha(value: object) -> str:
    if not isinstance(value, str) or _LOWER_GIT_SHA.fullmatch(value) is None:
        _fail("source_sha must be a lowercase 40-character Git SHA")
    return value


def _require_child_identities(
    value: object,
    *,
    field: str,
    expected_names: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple or any(
        type(item) is not tuple
        or len(item) != 2
        or not isinstance(item[0], str)
        or not isinstance(item[1], str)
        for item in value
    ):
        _fail(f"{field} must be an exact child-identity tuple")
    identities = cast("tuple[tuple[str, str], ...]", value)
    if tuple(name for name, _digest in identities) != expected_names:
        _fail(f"{field} membership or order differs from the canonical authority")
    for name, digest in identities:
        _require_sha256(digest, field=f"{field}.{name}")
    return identities


def _authority_digest(
    *,
    kind: str,
    source_sha: str,
    assurance_admission_sha256: str,
    assurance_manifest_sha256: str,
    generation_semantic_sha256: str,
    generation_index_sha256: str,
    provider_evidence_sha256: str,
    provider_authority_sha256: str,
    children: tuple[tuple[str, str], ...],
) -> str:
    return _sha256(
        {
            "schema_version": 2,
            "kind": kind,
            "source_sha": source_sha,
            "assurance_admission_sha256": assurance_admission_sha256,
            "assurance_manifest_sha256": assurance_manifest_sha256,
            "generation_semantic_sha256": generation_semantic_sha256,
            "generation_index_sha256": generation_index_sha256,
            "provider_evidence_sha256": provider_evidence_sha256,
            "provider_authority_sha256": provider_authority_sha256,
            "children": [{"name": name, "contract_sha256": digest} for name, digest in children],
        }
    )


@dataclass(frozen=True, slots=True)
class RawRequestAssuranceAuthorityV2:
    """Path-free field/model authority from one validated GREEN generation."""

    source_sha: str
    assurance_admission_sha256: str
    assurance_manifest_sha256: str
    generation_semantic_sha256: str
    generation_index_sha256: str
    provider_evidence_sha256: str
    provider_authority_sha256: str
    field_children: tuple[tuple[str, str], ...]
    model_children: tuple[tuple[str, str], ...]
    field_authority_sha256: str
    model_authority_sha256: str
    validation_provenance_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "nbadb_raw_request_assurance_authority_v2"

    def __post_init__(self) -> None:
        source_sha = _require_git_sha(self.source_sha)
        admission_sha256 = _require_sha256(
            self.assurance_admission_sha256,
            field="assurance_admission_sha256",
        )
        manifest_sha256 = _require_sha256(
            self.assurance_manifest_sha256,
            field="assurance_manifest_sha256",
        )
        semantic_sha256 = _require_sha256(
            self.generation_semantic_sha256,
            field="generation_semantic_sha256",
        )
        generation_index_sha256 = _require_sha256(
            self.generation_index_sha256,
            field="generation_index_sha256",
        )
        provider_evidence_sha256 = _require_sha256(
            self.provider_evidence_sha256,
            field="provider_evidence_sha256",
        )
        provider_authority_sha256 = _require_sha256(
            self.provider_authority_sha256,
            field="provider_authority_sha256",
        )
        field_children = _require_child_identities(
            self.field_children,
            field="field_children",
            expected_names=_FIELD_AUTHORITY_CHILD_NAMES,
        )
        model_children = _require_child_identities(
            self.model_children,
            field="model_children",
            expected_names=_MODEL_AUTHORITY_CHILD_NAMES,
        )
        expected_field = _authority_digest(
            kind="nbadb_raw_request_field_authority",
            source_sha=source_sha,
            assurance_admission_sha256=admission_sha256,
            assurance_manifest_sha256=manifest_sha256,
            generation_semantic_sha256=semantic_sha256,
            generation_index_sha256=generation_index_sha256,
            provider_evidence_sha256=provider_evidence_sha256,
            provider_authority_sha256=provider_authority_sha256,
            children=field_children,
        )
        expected_model = _authority_digest(
            kind="nbadb_raw_request_model_authority",
            source_sha=source_sha,
            assurance_admission_sha256=admission_sha256,
            assurance_manifest_sha256=manifest_sha256,
            generation_semantic_sha256=semantic_sha256,
            generation_index_sha256=generation_index_sha256,
            provider_evidence_sha256=provider_evidence_sha256,
            provider_authority_sha256=provider_authority_sha256,
            children=model_children,
        )
        if self.field_authority_sha256 != expected_field:
            _fail("field_authority_sha256 differs from the validated assurance children")
        if self.model_authority_sha256 != expected_model:
            _fail("model_authority_sha256 differs from the validated assurance children")
        _require_sha256(
            self.validation_provenance_sha256,
            field="validation_provenance_sha256",
        )

    def _provenance_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "assurance_admission_sha256": self.assurance_admission_sha256,
            "assurance_manifest_sha256": self.assurance_manifest_sha256,
            "generation_semantic_sha256": self.generation_semantic_sha256,
            "generation_index_sha256": self.generation_index_sha256,
            "provider_evidence_sha256": self.provider_evidence_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "field_children": [
                {"name": name, "contract_sha256": digest} for name, digest in self.field_children
            ],
            "model_children": [
                {"name": name, "contract_sha256": digest} for name, digest in self.model_children
            ],
            "field_authority_sha256": self.field_authority_sha256,
            "model_authority_sha256": self.model_authority_sha256,
        }


def _child_contract_identities(
    generation: AssuranceGeneration,
    names: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    records = generation.manifest.get("children")
    if not isinstance(records, list):
        _fail("validated assurance manifest has no child records")
    by_name: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            _fail("validated assurance child record is invalid")
        name = record.get("name")
        digest = record.get("contract_sha256")
        if not isinstance(name, str) or not isinstance(digest, str):
            _fail("validated assurance child identity is invalid")
        if name in by_name:
            _fail("validated assurance child identity is duplicated")
        by_name[name] = _require_sha256(digest, field=f"assurance_child.{name}")
    missing = tuple(name for name in names if name not in by_name)
    if missing:
        _fail("validated assurance generation lacks required authority children")
    return tuple((name, by_name[name]) for name in names)


def _compile_validated_raw_request_assurance_authority(
    generation: AssuranceGeneration,
    *,
    validation_provenance_sha256: str,
) -> RawRequestAssuranceAuthorityV2:
    """Derive the sole raw-request field/model authority from a validated generation."""

    if type(generation) is not AssuranceGeneration:
        _fail("raw-request assurance requires an exact validated generation")
    try:
        admission = require_production_admissible(generation.admission)
    except AssuranceAdmissionError as exc:
        raise RawRequestAssuranceError(
            "raw-request assurance requires a production-admissible generation"
        ) from exc
    if not generation.model_green or generation.semantic_sha256 != (
        admission.generation_semantic_sha256
    ):
        _fail("raw-request assurance generation is not exact MODEL-GREEN evidence")
    field_children = _child_contract_identities(
        generation,
        _FIELD_AUTHORITY_CHILD_NAMES,
    )
    model_children = _child_contract_identities(
        generation,
        _MODEL_AUTHORITY_CHILD_NAMES,
    )
    common = {
        "source_sha": admission.source_sha,
        "assurance_admission_sha256": admission.sha256,
        "assurance_manifest_sha256": admission.assurance_manifest_sha256,
        "generation_semantic_sha256": admission.generation_semantic_sha256,
        "generation_index_sha256": generation.generation_index_sha256,
        "provider_evidence_sha256": admission.provider_evidence_sha256,
        "provider_authority_sha256": admission.provider_authority_sha256,
    }
    return RawRequestAssuranceAuthorityV2(
        **common,
        field_children=field_children,
        model_children=model_children,
        field_authority_sha256=_authority_digest(
            kind="nbadb_raw_request_field_authority",
            children=field_children,
            **common,
        ),
        model_authority_sha256=_authority_digest(
            kind="nbadb_raw_request_model_authority",
            children=model_children,
            **common,
        ),
        validation_provenance_sha256=validation_provenance_sha256,
    )


def _build_assurance_provenance_boundary() -> tuple[
    Callable[..., RawRequestAssuranceAuthorityV2],
    Callable[[object], RawRequestAssuranceAuthorityV2],
]:
    """Keep issuance authority inside validation instead of a reusable public token."""

    signing_key = secrets.token_bytes(32)

    def provenance_sha256(value: RawRequestAssuranceAuthorityV2) -> str:
        return hmac.digest(
            signing_key,
            _canonical_bytes(value._provenance_payload()),
            "sha256",
        ).hex()

    def load(
        directory: Path | str,
        *,
        project_root: Path | str,
        endpoint_analysis_docs_root: Path | str,
    ) -> RawRequestAssuranceAuthorityV2:
        """Revalidate one exact generation and derive its raw-request authority."""

        try:
            generation = validate_assurance_generation(
                directory,
                project_root=project_root,
                endpoint_analysis_docs_root=endpoint_analysis_docs_root,
            )
        except ContractAssuranceError as exc:
            raise RawRequestAssuranceError(
                "raw-request assurance generation failed independent validation"
            ) from exc
        unsigned = _compile_validated_raw_request_assurance_authority(
            generation,
            validation_provenance_sha256="0" * 64,
        )
        return replace(
            unsigned,
            validation_provenance_sha256=provenance_sha256(unsigned),
        )

    def validate(value: object) -> RawRequestAssuranceAuthorityV2:
        if type(value) is not RawRequestAssuranceAuthorityV2:
            _fail("raw-request assurance authority must use the exact V2 contract")
        authority = value
        expected = provenance_sha256(authority)
        if not hmac.compare_digest(authority.validation_provenance_sha256, expected):
            _fail(
                "raw-request assurance authority lacks current-process independent "
                "generation provenance"
            )
        return authority

    return load, validate


load_raw_request_assurance_authority, validate_raw_request_assurance_authority = (
    _build_assurance_provenance_boundary()
)


__all__ = [
    "RawRequestAssuranceAuthorityV2",
    "RawRequestAssuranceError",
    "load_raw_request_assurance_authority",
    "validate_raw_request_assurance_authority",
]
