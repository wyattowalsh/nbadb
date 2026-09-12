from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import re
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, ClassVar, Literal, Self, cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    verify_assured_artifact_manifest,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority

RIGHTS_EVIDENCE_RELATIVE_PATH = Path(
    "artifacts/assurance/complete-nba-api-sink/rights-evidence.json"
)
RIGHTS_EVIDENCE_SCHEMA = "NbadbPublicationRightsEvidenceV1"
RIGHTS_EVIDENCE_SHA256 = "6bd56da7ad91a7f2828648786d3889cfd9aa082f70f12b8eb3ad829da3676cf8"
_MAX_RIGHTS_EVIDENCE_BYTES = 256 * 1024
_MAX_QUALIFIED_RIGHTS_BYTES = 2 * 1024 * 1024
_MAX_PUBLICATION_CONTEXT_BYTES = 4 * 1024 * 1024
_MAX_DATASET_METADATA_BYTES = 32 * 1024 * 1024
_MAX_TERMINAL_REPORT_BYTES = 256 * 1024 * 1024
_MAX_TRUST_STORE_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,199}\Z")
_KAGGLE_DATASET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}/[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z")
_REQUIRED_BLOCKED_MATERIALS = frozenset(
    {
        "provider-returned-statistics-and-parser-bodies",
        "public-kaggle-publication",
    }
)

QUALIFIED_RIGHTS_DISPOSITION_SCHEMA = "QualifiedRightsDispositionV1"
QUALIFIED_RIGHTS_PUBLICATION_CONTEXT_NAME = "qualified-rights-publication-context.json"
QUALIFIED_RIGHTS_TRUST_STORE_RELATIVE_PATH = Path("config/kaggle/qualified-rights-trust-store.json")
# Admission stays mechanically blocked until a qualified human review produces a
# repository-owned trust store and a maintainer pins its exact bytes here.  There is
# intentionally no environment override, fallback key, or generated default.
_PINNED_QUALIFIED_RIGHTS_TRUST_STORE_SHA256: str | None = None

QUALIFIED_RIGHTS_MATERIAL_CLASSES = frozenset(
    {
        "dataset_metadata_documentation_and_code",
        "derived_aggregates_and_views",
        "live_or_archived_play_by_play",
        "modeled_provider_rows",
        "nba_api_client_software",
        "odds_tracking_video_asset_metadata",
        "person_related_fields",
        "provider_exact_live_bodies",
        "provider_exact_stats_bodies",
        "provider_static_snapshots",
        "repo_synthetic_fixtures",
    }
)
_PROVIDER_MATERIAL_CLASSES = frozenset(
    {
        "derived_aggregates_and_views",
        "live_or_archived_play_by_play",
        "modeled_provider_rows",
        "odds_tracking_video_asset_metadata",
        "person_related_fields",
        "provider_exact_live_bodies",
        "provider_exact_stats_bodies",
        "provider_static_snapshots",
    }
)
_EXACT_BODY_MATERIAL_CLASSES = frozenset(
    {
        "provider_exact_live_bodies",
        "provider_exact_stats_bodies",
        "provider_static_snapshots",
    }
)
_PRIVACY_REVIEW_MATERIAL_CLASSES = frozenset(
    {
        "live_or_archived_play_by_play",
        "modeled_provider_rows",
        "odds_tracking_video_asset_metadata",
        "person_related_fields",
        "provider_exact_live_bodies",
        "provider_exact_stats_bodies",
        "provider_static_snapshots",
    }
)
_BASE_PROVIDER_SCOPES = frozenset(
    {
        "automated_access",
        "comprehensive_regular_updates",
        "derived_exports",
        "local_retention",
        "public_redistribution",
        "transformation",
    }
)
_KNOWN_PROVIDER_SCOPES = _BASE_PROVIDER_SCOPES | frozenset(
    {
        "commercial_downstream_use",
        "exact_response_bodies",
        "live_near_live_and_archived_play_by_play",
    }
)
_BASE_REVIEWER_SCOPES = frozenset(
    {
        "automated_access",
        "kaggle_license",
        "privacy_and_publicity",
        "public_redistribution",
    }
)
_REQUIRED_SOURCE_TYPES = frozenset(
    {
        "client_license",
        "platform_aup",
        "platform_privacy",
        "platform_terms",
        "provider_privacy",
        "provider_terms",
    }
)
_REQUIRED_ATTRIBUTION_SURFACES = frozenset(
    {
        "csv",
        "dataset_landing_page",
        "dataset_metadata",
        "duckdb",
        "parquet",
        "sqlite",
    }
)
_REQUIRED_PROVIDER_HOSTS = (
    "api.nba.net",
    "cdn.nba.com",
    "stats.nba.com",
)
_REQUIRED_COMPETITIONS = (
    "g_league",
    "nba",
    "summer_league",
    "wnba",
)

Sha256 = Annotated[str, Field(pattern=r"[0-9a-f]{64}", strict=True)]
GitSha = Annotated[str, Field(pattern=r"[0-9a-f]{40}", strict=True)]
NonEmptyText = Annotated[str, Field(min_length=1, max_length=16_384, strict=True)]
SafeIdentifier = Annotated[
    str,
    Field(pattern=r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,199}", strict=True),
]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]


class KagglePublicationRightsBlockedError(PermissionError):
    """Raised before any Kaggle publication work while rights remain blocked."""


def _strict_tuple(value: object, *, field: str) -> tuple[object, ...]:
    if type(value) is list:
        return tuple(value)
    if type(value) is tuple:
        return value
    raise ValueError(f"{field} must be a JSON array")


def _require_sorted_unique_strings(
    values: tuple[str, ...],
    *,
    field: str,
    allow_empty: bool = False,
) -> None:
    if not allow_empty and not values:
        raise ValueError(f"{field} must be nonempty")
    if any(type(value) is not str or not value for value in values):
        raise ValueError(f"{field} contains an invalid value")
    if tuple(sorted(values)) != values or len(values) != len(set(values)):
        raise ValueError(f"{field} must be sorted and unique")


def _parse_utc_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"{field} must be an exact UTC timestamp") from exc
    return parsed


def _validate_https_url(value: str, *, field: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"{field} must be an absolute credential-free HTTPS URL")


def _validate_public_file_path(value: str) -> None:
    if "\\" in value or "\x00" in value:
        raise ValueError("staged file path is invalid")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or value != path.as_posix() or ".." in path.parts:
        raise ValueError("staged file path is invalid")


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _qualified_signing_bytes_from_payload(payload: dict[str, Any]) -> bytes:
    signing_payload = copy.deepcopy(payload)
    signing_payload.pop("canonical_receipt_sha256", None)
    signature = signing_payload.get("signature")
    if type(signature) is not dict:
        raise ValueError("qualified rights signature object is invalid")
    signature.pop("value_base64", None)
    return _canonical_json_bytes(signing_payload)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class QualifiedReviewerV1(_StrictFrozenModel):
    reviewer_kind: Literal["qualified_human_legal_reviewer"]
    human_name: NonEmptyText
    organization: NonEmptyText
    role: NonEmptyText
    qualifications: tuple[NonEmptyText, ...]
    jurisdictions: tuple[SafeIdentifier, ...]
    qualification_evidence_sha256: Sha256
    is_ai_system: Literal[False]
    self_attestation_only: Literal[False]
    conflict_disclosure: NonEmptyText
    signed_scope: tuple[SafeIdentifier, ...]

    @field_validator("qualifications", "jurisdictions", "signed_scope", mode="before")
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_reviewer(self) -> Self:
        _require_sorted_unique_strings(self.qualifications, field="reviewer qualifications")
        _require_sorted_unique_strings(self.jurisdictions, field="reviewer jurisdictions")
        _require_sorted_unique_strings(self.signed_scope, field="reviewer signed scope")
        if not _BASE_REVIEWER_SCOPES.issubset(self.signed_scope):
            raise ValueError("reviewer signed scope is incomplete")
        return self


class QualifiedRightsSubjectV1(_StrictFrozenModel):
    repository_source_sha: GitSha
    provider_authority_sha256: Sha256
    schema_contract_sha256: Sha256
    staged_publication_manifest_sha256: Sha256
    staged_file_inventory_sha256: Sha256
    kaggle_dataset: NonEmptyText
    kaggle_visibility: Literal["public"]

    @model_validator(mode="after")
    def _validate_subject(self) -> Self:
        if _KAGGLE_DATASET_RE.fullmatch(self.kaggle_dataset) is None:
            raise ValueError("Kaggle dataset target is invalid")
        return self


class OfficialSourceEvidenceV1(_StrictFrozenModel):
    evidence_id: SafeIdentifier
    source_type: Literal[
        "client_license",
        "platform_aup",
        "platform_privacy",
        "platform_terms",
        "provider_api_terms",
        "provider_privacy",
        "provider_terms",
    ]
    publisher: NonEmptyText
    url: NonEmptyText
    edition: NonEmptyText
    retrieved_at_utc: NonEmptyText
    content_sha256: Sha256
    normalization_method: NonEmptyText
    supersession_status: Literal["current"]
    reviewed_scopes: tuple[SafeIdentifier, ...]

    @field_validator("reviewed_scopes", mode="before")
    @classmethod
    def _convert_reviewed_scopes(cls, value: object) -> tuple[object, ...]:
        return _strict_tuple(value, field="reviewed_scopes")

    @model_validator(mode="after")
    def _validate_evidence(self) -> Self:
        _validate_https_url(self.url, field="official source URL")
        _parse_utc_timestamp(self.retrieved_at_utc, field="retrieved_at_utc")
        _require_sorted_unique_strings(self.reviewed_scopes, field="reviewed scopes")
        return self


class StagedMaterialFileV1(_StrictFrozenModel):
    path: NonEmptyText
    bytes: NonNegativeInt
    sha256: Sha256

    @model_validator(mode="after")
    def _validate_file(self) -> Self:
        _validate_public_file_path(self.path)
        return self


class MaterialDispositionV1(_StrictFrozenModel):
    material_class: SafeIdentifier
    decision: Literal["admitted", "excluded"]
    files: tuple[StagedMaterialFileV1, ...]
    permitted_scopes: tuple[SafeIdentifier, ...]
    jurisdictions: tuple[SafeIdentifier, ...]
    attribution_requirement: NonEmptyText
    privacy_disposition_id: SafeIdentifier | None
    evidence_ids: tuple[SafeIdentifier, ...]
    conditions: tuple[SafeIdentifier, ...]

    @field_validator(
        "files",
        "permitted_scopes",
        "jurisdictions",
        "evidence_ids",
        "conditions",
        mode="before",
    )
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_material(self) -> Self:
        if self.material_class not in QUALIFIED_RIGHTS_MATERIAL_CLASSES:
            raise ValueError("qualified rights material class is unknown")
        file_paths = tuple(item.path for item in self.files)
        if tuple(sorted(file_paths)) != file_paths or len(file_paths) != len(set(file_paths)):
            raise ValueError("material files must have sorted unique paths")
        _require_sorted_unique_strings(
            self.permitted_scopes,
            field="material permitted scopes",
            allow_empty=self.decision == "excluded",
        )
        _require_sorted_unique_strings(
            self.jurisdictions,
            field="material jurisdictions",
            allow_empty=self.decision == "excluded",
        )
        _require_sorted_unique_strings(
            self.evidence_ids,
            field="material evidence IDs",
            allow_empty=self.decision == "excluded",
        )
        _require_sorted_unique_strings(
            self.conditions,
            field="material condition IDs",
            allow_empty=True,
        )
        if self.decision == "admitted" and not self.files:
            raise ValueError("an admitted material class must bind at least one staged file")
        if self.decision == "admitted" and "public_redistribution" not in self.permitted_scopes:
            raise ValueError("an admitted material class must grant public redistribution")
        if self.decision == "excluded" and (
            self.files
            or self.permitted_scopes
            or self.jurisdictions
            or self.evidence_ids
            or self.conditions
            or self.privacy_disposition_id is not None
        ):
            raise ValueError("an excluded material class cannot retain files or granted scope")
        return self


class ProviderAuthorityV1(_StrictFrozenModel):
    basis: Literal["express_written_permission", "qualified_legal_review"]
    authority_document_sha256: Sha256
    counterparties: tuple[NonEmptyText, ...]
    covered_material_classes: tuple[SafeIdentifier, ...]
    covered_hosts: tuple[NonEmptyText, ...]
    covered_competitions: tuple[SafeIdentifier, ...]
    covered_scopes: tuple[SafeIdentifier, ...]
    access_control_conditions: tuple[SafeIdentifier, ...]
    rate_limit_disposition: NonEmptyText
    revocation_conditions: tuple[SafeIdentifier, ...]
    authority_evidence_ids: tuple[SafeIdentifier, ...]

    @field_validator(
        "counterparties",
        "covered_material_classes",
        "covered_hosts",
        "covered_competitions",
        "covered_scopes",
        "access_control_conditions",
        "revocation_conditions",
        "authority_evidence_ids",
        mode="before",
    )
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_authority(self) -> Self:
        for field, values in (
            ("provider counterparties", self.counterparties),
            ("provider covered material classes", self.covered_material_classes),
            ("provider covered hosts", self.covered_hosts),
            ("provider covered competitions", self.covered_competitions),
            ("provider covered scopes", self.covered_scopes),
            ("provider access-control condition IDs", self.access_control_conditions),
            ("provider revocation condition IDs", self.revocation_conditions),
            ("provider authority evidence IDs", self.authority_evidence_ids),
        ):
            _require_sorted_unique_strings(values, field=field)
        for host in self.covered_hosts:
            if (
                host != host.lower()
                or ":" in host
                or "/" in host
                or urlsplit(f"https://{host}").hostname != host
            ):
                raise ValueError("provider covered host is invalid")
        if not set(self.covered_material_classes).issubset(_PROVIDER_MATERIAL_CLASSES):
            raise ValueError("provider authority covers a non-provider material class")
        if not set(self.covered_scopes).issubset(_KNOWN_PROVIDER_SCOPES):
            raise ValueError("provider authority contains an unsupported overbroad scope")
        return self


class PrivacyDispositionV1(_StrictFrozenModel):
    disposition_id: SafeIdentifier
    reviewed_material_classes: tuple[SafeIdentifier, ...]
    field_inventory_sha256: Sha256
    exact_body_additive_field_review_sha256: Sha256
    person_related_data_present: bool
    minors_and_sensitive_data_reviewed: Literal[True]
    publicity_rights_reviewed: Literal[True]
    legal_basis: NonEmptyText
    minimization_and_redaction: NonEmptyText
    jurisdictions: tuple[SafeIdentifier, ...]
    data_subject_rights_process: NonEmptyText
    takedown_contact: NonEmptyText
    retention_and_deletion_policy: NonEmptyText
    backups_and_mirrors_reviewed: Literal[True]
    incident_response_process: NonEmptyText
    evidence_ids: tuple[SafeIdentifier, ...]
    condition_ids: tuple[SafeIdentifier, ...]

    @field_validator(
        "reviewed_material_classes",
        "jurisdictions",
        "evidence_ids",
        "condition_ids",
        mode="before",
    )
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_privacy(self) -> Self:
        _require_sorted_unique_strings(
            self.reviewed_material_classes,
            field="privacy reviewed material classes",
            allow_empty=True,
        )
        _require_sorted_unique_strings(self.jurisdictions, field="privacy jurisdictions")
        _require_sorted_unique_strings(self.evidence_ids, field="privacy evidence IDs")
        _require_sorted_unique_strings(self.condition_ids, field="privacy condition IDs")
        if not set(self.reviewed_material_classes).issubset(_PRIVACY_REVIEW_MATERIAL_CLASSES):
            raise ValueError("privacy disposition covers an invalid material class")
        return self


class KaggleDispositionV1(_StrictFrozenModel):
    dataset: NonEmptyText
    visibility: Literal["public"]
    license_id: SafeIdentifier
    license_scope: Literal["database_only", "database_and_admitted_contents"]
    license_excluded_material_classes: tuple[SafeIdentifier, ...]
    commercial_downstream_permitted: bool
    uploader_rights_warranty_satisfied: Literal[True]
    public_user_submission_grants_reviewed: Literal[True]
    attribution_text: NonEmptyText
    attribution_surfaces: tuple[SafeIdentifier, ...]
    provider_terms_notice: NonEmptyText
    takedown_contact: NonEmptyText
    terms_evidence_ids: tuple[SafeIdentifier, ...]
    condition_ids: tuple[SafeIdentifier, ...]

    @field_validator(
        "license_excluded_material_classes",
        "attribution_surfaces",
        "terms_evidence_ids",
        "condition_ids",
        mode="before",
    )
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_kaggle(self) -> Self:
        if _KAGGLE_DATASET_RE.fullmatch(self.dataset) is None:
            raise ValueError("Kaggle dataset target is invalid")
        _require_sorted_unique_strings(
            self.license_excluded_material_classes,
            field="Kaggle license exclusions",
            allow_empty=True,
        )
        _require_sorted_unique_strings(
            self.attribution_surfaces,
            field="Kaggle attribution surfaces",
        )
        _require_sorted_unique_strings(self.terms_evidence_ids, field="Kaggle terms evidence IDs")
        _require_sorted_unique_strings(self.condition_ids, field="Kaggle condition IDs")
        if set(self.license_excluded_material_classes) - QUALIFIED_RIGHTS_MATERIAL_CLASSES:
            raise ValueError("Kaggle license excludes an unknown material class")
        if not _REQUIRED_ATTRIBUTION_SURFACES.issubset(self.attribution_surfaces):
            raise ValueError("Kaggle attribution surfaces are incomplete")
        return self


class QualifiedRightsConditionV1(_StrictFrozenModel):
    condition_id: SafeIdentifier
    description: NonEmptyText
    applies_to_scopes: tuple[SafeIdentifier, ...]
    disposition: Literal["discharged"]
    discharged_at_utc: NonEmptyText
    review_by_utc: NonEmptyText
    discharge_evidence_ids: tuple[SafeIdentifier, ...]
    discharge_evidence_sha256: Sha256

    @field_validator("applies_to_scopes", "discharge_evidence_ids", mode="before")
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_condition(self) -> Self:
        _require_sorted_unique_strings(self.applies_to_scopes, field="condition scopes")
        _require_sorted_unique_strings(
            self.discharge_evidence_ids,
            field="condition discharge evidence IDs",
        )
        discharged = _parse_utc_timestamp(self.discharged_at_utc, field="discharged_at_utc")
        review_by = _parse_utc_timestamp(self.review_by_utc, field="condition review_by_utc")
        if discharged >= review_by:
            raise ValueError("condition discharge chronology is invalid")
        return self


class QualifiedRightsSignatureV1(_StrictFrozenModel):
    method: Literal["ed25519"]
    signer_key_id: SafeIdentifier
    value_base64: NonEmptyText

    @model_validator(mode="after")
    def _validate_signature_shape(self) -> Self:
        try:
            decoded = base64.b64decode(self.value_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("qualified rights signature is not strict base64") from exc
        if len(decoded) != 64:
            raise ValueError("qualified rights Ed25519 signature must be exactly 64 bytes")
        return self


def _provider_scope_tokens(provider: ProviderAuthorityV1) -> frozenset[str]:
    return frozenset(
        set(provider.covered_scopes)
        | {f"provider_material:{value}" for value in provider.covered_material_classes}
        | {f"provider_host:{value}" for value in provider.covered_hosts}
        | {f"provider_competition:{value}" for value in provider.covered_competitions}
    )


def _material_scope_tokens(material: MaterialDispositionV1) -> frozenset[str]:
    if material.decision != "admitted":
        return frozenset()
    return frozenset(
        {f"material:{material.material_class}"}
        | {
            f"material_scope:{material.material_class}:{scope}"
            for scope in material.permitted_scopes
        }
    )


def _privacy_scope_tokens(privacy: PrivacyDispositionV1) -> frozenset[str]:
    return frozenset(
        {"privacy_and_publicity", "privacy:exact_body_additive_fields"}
        | {f"privacy_material:{value}" for value in privacy.reviewed_material_classes}
        | {f"privacy_jurisdiction:{value}" for value in privacy.jurisdictions}
    )


def _kaggle_scope_tokens(kaggle: KaggleDispositionV1) -> frozenset[str]:
    target_digest = hashlib.sha256(kaggle.dataset.encode("utf-8", errors="strict")).hexdigest()
    return frozenset(
        {
            "kaggle_license",
            f"kaggle_target_sha256:{target_digest}",
            f"kaggle_visibility:{kaggle.visibility}",
            f"kaggle_license:{kaggle.license_id}",
            f"kaggle_license_scope:{kaggle.license_scope}",
            f"kaggle_commercial:{str(kaggle.commercial_downstream_permitted).lower()}",
        }
        | {
            f"kaggle_excluded_material:{value}"
            for value in kaggle.license_excluded_material_classes
        }
    )


def _effective_scopes(
    *,
    provider: ProviderAuthorityV1,
    materials: tuple[MaterialDispositionV1, ...],
    privacy: PrivacyDispositionV1,
    kaggle: KaggleDispositionV1,
) -> frozenset[str]:
    scopes = set(_BASE_REVIEWER_SCOPES)
    scopes.update(_provider_scope_tokens(provider))
    for material in materials:
        scopes.update(_material_scope_tokens(material))
    scopes.update(_privacy_scope_tokens(privacy))
    scopes.update(_kaggle_scope_tokens(kaggle))
    return frozenset(scopes)


def _inventory_payload(
    materials: tuple[MaterialDispositionV1, ...],
) -> list[dict[str, object]]:
    return sorted(
        (
            {
                "path": file.path,
                "bytes": file.bytes,
                "sha256": file.sha256,
                "material_class": material.material_class,
            }
            for material in materials
            for file in material.files
        ),
        key=lambda item: cast("str", item["path"]),
    )


def _inventory_sha256(materials: tuple[MaterialDispositionV1, ...]) -> str:
    return _canonical_sha256(_inventory_payload(materials))


def _evidence_digest(
    evidence_by_id: dict[str, OfficialSourceEvidenceV1],
    evidence_ids: tuple[str, ...],
) -> str:
    return _canonical_sha256(
        [
            evidence_by_id[evidence_id].model_dump(mode="json", round_trip=True)
            for evidence_id in evidence_ids
        ]
    )


def _require_evidence_scope(
    *,
    evidence_by_id: dict[str, OfficialSourceEvidenceV1],
    evidence_ids: tuple[str, ...],
    required_scopes: frozenset[str],
    label: str,
) -> None:
    for evidence_id in evidence_ids:
        if not required_scopes.issubset(evidence_by_id[evidence_id].reviewed_scopes):
            raise ValueError(f"{label} evidence signed scope is incomplete")


class QualifiedRightsDispositionV1(_StrictFrozenModel):
    """Receipt-bound rights credential; parsing never implies publication admission."""

    schema_name: Literal["QualifiedRightsDispositionV1"] = Field(alias="schema")
    receipt_id: SafeIdentifier
    issued_at_utc: NonEmptyText
    review_by_utc: NonEmptyText
    expires_at_utc: NonEmptyText
    reviewer: QualifiedReviewerV1
    subject: QualifiedRightsSubjectV1
    official_source_evidence: tuple[OfficialSourceEvidenceV1, ...]
    provider_authority: ProviderAuthorityV1
    material_dispositions: tuple[MaterialDispositionV1, ...]
    privacy_disposition: PrivacyDispositionV1
    kaggle_disposition: KaggleDispositionV1
    conditions: tuple[QualifiedRightsConditionV1, ...]
    unresolved_questions: tuple[NonEmptyText, ...]
    publication_admission: Literal["qualified"]
    signature: QualifiedRightsSignatureV1
    canonical_receipt_sha256: Sha256

    _sequence_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "official_source_evidence",
            "material_dispositions",
            "conditions",
            "unresolved_questions",
        }
    )

    @field_validator(
        "official_source_evidence",
        "material_dispositions",
        "conditions",
        "unresolved_questions",
        mode="before",
    )
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_complete_disposition(self) -> Self:
        issued_at = _parse_utc_timestamp(self.issued_at_utc, field="issued_at_utc")
        review_by = _parse_utc_timestamp(self.review_by_utc, field="review_by_utc")
        expires_at = _parse_utc_timestamp(self.expires_at_utc, field="expires_at_utc")
        if not issued_at < review_by <= expires_at:
            raise ValueError("qualified rights review and expiry chronology is invalid")
        if self.unresolved_questions:
            raise ValueError("qualified rights credential cannot contain unresolved questions")

        expected_provider = expected_nba_api_provider_authority().get("authority_sha256")
        if (
            type(expected_provider) is not str
            or _SHA256_RE.fullmatch(expected_provider) is None
            or self.subject.provider_authority_sha256 != expected_provider
        ):
            raise ValueError("qualified rights subject does not bind canonical provider authority")

        evidence_ids = tuple(item.evidence_id for item in self.official_source_evidence)
        if tuple(sorted(evidence_ids)) != evidence_ids or len(evidence_ids) != len(
            set(evidence_ids)
        ):
            raise ValueError("official source evidence must have sorted unique IDs")
        source_types = {item.source_type for item in self.official_source_evidence}
        if not _REQUIRED_SOURCE_TYPES.issubset(source_types):
            raise ValueError("official source evidence types are incomplete")
        evidence_by_id = {item.evidence_id: item for item in self.official_source_evidence}

        material_classes = tuple(item.material_class for item in self.material_dispositions)
        if tuple(sorted(material_classes)) != material_classes or len(material_classes) != len(
            set(material_classes)
        ):
            raise ValueError("material dispositions must have sorted unique classes")
        if set(material_classes) != QUALIFIED_RIGHTS_MATERIAL_CLASSES:
            raise ValueError("material dispositions are not exhaustive")
        material_by_class = {item.material_class: item for item in self.material_dispositions}
        staged_paths = [file.path for item in self.material_dispositions for file in item.files]
        if len(staged_paths) != len(set(staged_paths)):
            raise ValueError("staged files must belong to exactly one material class")
        if self.subject.staged_file_inventory_sha256 != _inventory_sha256(
            self.material_dispositions
        ):
            raise ValueError("qualified rights staged file inventory digest is invalid")

        admitted_provider_classes = {
            material_class
            for material_class in _PROVIDER_MATERIAL_CLASSES
            if material_by_class[material_class].decision == "admitted"
        }
        if set(self.provider_authority.covered_material_classes) != admitted_provider_classes:
            raise ValueError("provider material authority does not match admitted materials")
        required_provider_scopes = set(_BASE_PROVIDER_SCOPES)
        if admitted_provider_classes & _EXACT_BODY_MATERIAL_CLASSES:
            required_provider_scopes.add("exact_response_bodies")
        if "live_or_archived_play_by_play" in admitted_provider_classes:
            required_provider_scopes.add("live_near_live_and_archived_play_by_play")
        if self.kaggle_disposition.commercial_downstream_permitted:
            required_provider_scopes.add("commercial_downstream_use")
        if not required_provider_scopes.issubset(self.provider_authority.covered_scopes):
            raise ValueError("provider authority scope is incomplete")

        privacy_required = {
            material_class
            for material_class in _PRIVACY_REVIEW_MATERIAL_CLASSES
            if material_by_class[material_class].decision == "admitted"
        }
        if set(self.privacy_disposition.reviewed_material_classes) != privacy_required:
            raise ValueError("privacy material coverage is incomplete")
        if privacy_required and not self.privacy_disposition.person_related_data_present:
            raise ValueError("privacy disposition cannot deny present person-related material")
        for material_class in privacy_required:
            if (
                material_by_class[material_class].privacy_disposition_id
                != self.privacy_disposition.disposition_id
            ):
                raise ValueError("material privacy disposition binding is incomplete")

        excluded_materials = {
            item.material_class
            for item in self.material_dispositions
            if item.decision == "excluded"
        }
        if set(self.kaggle_disposition.license_excluded_material_classes) != excluded_materials:
            raise ValueError("Kaggle license exclusions do not match excluded materials")
        if self.kaggle_disposition.dataset != self.subject.kaggle_dataset:
            raise ValueError("Kaggle target is not bound to the credential subject")
        if self.kaggle_disposition.visibility != self.subject.kaggle_visibility:
            raise ValueError("Kaggle visibility is not bound to the credential subject")

        referenced_evidence_ids = set(self.provider_authority.authority_evidence_ids)
        referenced_evidence_ids.update(self.privacy_disposition.evidence_ids)
        referenced_evidence_ids.update(self.kaggle_disposition.terms_evidence_ids)
        for item in self.material_dispositions:
            referenced_evidence_ids.update(item.evidence_ids)
        for condition in self.conditions:
            referenced_evidence_ids.update(condition.discharge_evidence_ids)
        if not referenced_evidence_ids.issubset(evidence_by_id):
            raise ValueError("qualified rights credential references unknown source evidence")

        evidence_type_by_id = {
            item.evidence_id: item.source_type for item in self.official_source_evidence
        }
        provider_source_types = {
            evidence_type_by_id[evidence_id]
            for evidence_id in self.provider_authority.authority_evidence_ids
        }
        if not provider_source_types & {"provider_api_terms", "provider_terms"}:
            raise ValueError("provider authority source evidence is incomplete")
        privacy_source_types = {
            evidence_type_by_id[evidence_id]
            for evidence_id in self.privacy_disposition.evidence_ids
        }
        if privacy_required and not {
            "platform_privacy",
            "provider_privacy",
        }.issubset(privacy_source_types):
            raise ValueError("privacy source evidence is incomplete")
        kaggle_source_types = {
            evidence_type_by_id[evidence_id]
            for evidence_id in self.kaggle_disposition.terms_evidence_ids
        }
        if not {"platform_aup", "platform_privacy", "platform_terms"}.issubset(kaggle_source_types):
            raise ValueError("Kaggle source evidence is incomplete")
        client_material = material_by_class["nba_api_client_software"]
        if client_material.decision == "admitted" and "client_license" not in {
            evidence_type_by_id[evidence_id] for evidence_id in client_material.evidence_ids
        }:
            raise ValueError("nba_api client-license evidence is incomplete")

        provider_scopes = _provider_scope_tokens(self.provider_authority)
        privacy_scopes = _privacy_scope_tokens(self.privacy_disposition)
        kaggle_scopes = _kaggle_scope_tokens(self.kaggle_disposition)
        effective_scopes = _effective_scopes(
            provider=self.provider_authority,
            materials=self.material_dispositions,
            privacy=self.privacy_disposition,
            kaggle=self.kaggle_disposition,
        )
        if set(self.reviewer.signed_scope) != set(effective_scopes):
            raise ValueError("reviewer signed scope does not exactly cover effective admission")
        for evidence in self.official_source_evidence:
            if not set(evidence.reviewed_scopes).issubset(effective_scopes):
                raise ValueError("official evidence contains an ineffective or overbroad scope")
        _require_evidence_scope(
            evidence_by_id=evidence_by_id,
            evidence_ids=self.provider_authority.authority_evidence_ids,
            required_scopes=provider_scopes,
            label="provider authority",
        )
        for material in self.material_dispositions:
            if material.decision == "admitted":
                _require_evidence_scope(
                    evidence_by_id=evidence_by_id,
                    evidence_ids=material.evidence_ids,
                    required_scopes=_material_scope_tokens(material),
                    label=f"material {material.material_class}",
                )
        _require_evidence_scope(
            evidence_by_id=evidence_by_id,
            evidence_ids=self.privacy_disposition.evidence_ids,
            required_scopes=privacy_scopes,
            label="privacy",
        )
        _require_evidence_scope(
            evidence_by_id=evidence_by_id,
            evidence_ids=self.kaggle_disposition.terms_evidence_ids,
            required_scopes=kaggle_scopes,
            label="Kaggle",
        )

        condition_ids = tuple(item.condition_id for item in self.conditions)
        if tuple(sorted(condition_ids)) != condition_ids or len(condition_ids) != len(
            set(condition_ids)
        ):
            raise ValueError("qualified rights conditions must have sorted unique IDs")
        if not condition_ids:
            raise ValueError("qualified rights conditions must be nonempty")
        condition_by_id = {item.condition_id: item for item in self.conditions}
        condition_scope_requirements: dict[str, set[str]] = {}

        def bind_conditions(ids: tuple[str, ...], scopes: frozenset[str]) -> None:
            for condition_id in ids:
                condition_scope_requirements.setdefault(condition_id, set()).update(scopes)

        bind_conditions(
            self.provider_authority.access_control_conditions,
            provider_scopes,
        )
        bind_conditions(
            self.provider_authority.revocation_conditions,
            provider_scopes,
        )
        bind_conditions(self.privacy_disposition.condition_ids, privacy_scopes)
        bind_conditions(self.kaggle_disposition.condition_ids, kaggle_scopes)
        for material in self.material_dispositions:
            bind_conditions(material.conditions, _material_scope_tokens(material))
        if set(condition_scope_requirements) != set(condition_by_id):
            raise ValueError("qualified rights condition references are incomplete or unknown")
        for condition_id, required in condition_scope_requirements.items():
            condition = condition_by_id[condition_id]
            if set(condition.applies_to_scopes) != required:
                raise ValueError("qualified rights condition scope binding is invalid")
            if (
                _parse_utc_timestamp(
                    condition.discharged_at_utc,
                    field="condition discharged_at_utc",
                )
                > issued_at
                or _parse_utc_timestamp(
                    condition.review_by_utc,
                    field="condition review_by_utc",
                )
                < review_by
            ):
                raise ValueError("qualified rights condition discharge is not current")
            _require_evidence_scope(
                evidence_by_id=evidence_by_id,
                evidence_ids=condition.discharge_evidence_ids,
                required_scopes=frozenset(required),
                label=f"condition {condition_id}",
            )
            if condition.discharge_evidence_sha256 != _evidence_digest(
                evidence_by_id,
                condition.discharge_evidence_ids,
            ):
                raise ValueError("qualified rights condition discharge evidence digest is invalid")

        payload = self.model_dump(mode="json", round_trip=True, by_alias=True)
        expected_receipt_sha256 = hashlib.sha256(
            _qualified_signing_bytes_from_payload(payload)
        ).hexdigest()
        if self.canonical_receipt_sha256 != expected_receipt_sha256:
            raise ValueError("qualified rights canonical receipt digest is invalid")
        return self

    def signing_bytes(self) -> bytes:
        """Return the exact canonical bytes the pinned Ed25519 key must verify."""

        return _qualified_signing_bytes_from_payload(
            self.model_dump(mode="json", round_trip=True, by_alias=True)
        )


class ExpectedOfficialSourceEvidenceV1(OfficialSourceEvidenceV1):
    """Full independent source edition expected from the publication context artifact."""


class ExpectedMaterialInventoryV1(_StrictFrozenModel):
    material_class: SafeIdentifier
    files: tuple[StagedMaterialFileV1, ...]

    @field_validator("files", mode="before")
    @classmethod
    def _convert_files(cls, value: object) -> tuple[object, ...]:
        return _strict_tuple(value, field="files")

    @model_validator(mode="after")
    def _validate_inventory(self) -> Self:
        if self.material_class not in QUALIFIED_RIGHTS_MATERIAL_CLASSES:
            raise ValueError("expected material class is unknown")
        file_paths = tuple(item.path for item in self.files)
        if tuple(sorted(file_paths)) != file_paths or len(file_paths) != len(set(file_paths)):
            raise ValueError("expected material files must have sorted unique paths")
        return self


def _expected_inventory_payload(
    materials: tuple[ExpectedMaterialInventoryV1, ...],
) -> list[dict[str, object]]:
    return sorted(
        (
            {
                "path": file.path,
                "bytes": file.bytes,
                "sha256": file.sha256,
                "material_class": material.material_class,
            }
            for material in materials
            for file in material.files
        ),
        key=lambda item: cast("str", item["path"]),
    )


class QualifiedRightsExpectedContextV1(_StrictFrozenModel):
    """Sealed context reconstructed only from fixed publication artifacts."""

    repository_source_sha: GitSha
    provider_authority_sha256: Sha256
    schema_contract_sha256: Sha256
    staged_publication_manifest_sha256: Sha256
    staged_file_inventory_sha256: Sha256
    publication_context_artifact_sha256: Sha256
    dataset_metadata_sha256: Sha256
    terminal_assurance_report_sha256: Sha256
    kaggle_dataset: NonEmptyText
    kaggle_visibility: Literal["public"]
    kaggle_license_id: SafeIdentifier
    required_provider_hosts: tuple[NonEmptyText, ...]
    required_competitions: tuple[SafeIdentifier, ...]
    official_source_evidence: tuple[ExpectedOfficialSourceEvidenceV1, ...]
    material_inventory: tuple[ExpectedMaterialInventoryV1, ...]
    canonical_context_sha256: Sha256

    @field_validator(
        "required_provider_hosts",
        "required_competitions",
        "official_source_evidence",
        "material_inventory",
        mode="before",
    )
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_context(self) -> Self:
        if _KAGGLE_DATASET_RE.fullmatch(self.kaggle_dataset) is None:
            raise ValueError("expected Kaggle dataset target is invalid")
        _require_sorted_unique_strings(
            self.required_provider_hosts,
            field="expected provider hosts",
        )
        _require_sorted_unique_strings(
            self.required_competitions,
            field="expected competitions",
        )
        if self.required_provider_hosts != _REQUIRED_PROVIDER_HOSTS:
            raise ValueError("expected provider hosts differ from repository policy")
        if self.required_competitions != _REQUIRED_COMPETITIONS:
            raise ValueError("expected competitions differ from repository policy")
        canonical_provider = expected_nba_api_provider_authority().get("authority_sha256")
        if self.provider_authority_sha256 != canonical_provider:
            raise ValueError("expected provider authority is not canonical")
        if self.schema_contract_sha256 != self.terminal_assurance_report_sha256:
            raise ValueError("expected schema contract is not the exact terminal assurance report")
        evidence_ids = tuple(item.evidence_id for item in self.official_source_evidence)
        if tuple(sorted(evidence_ids)) != evidence_ids or len(evidence_ids) != len(
            set(evidence_ids)
        ):
            raise ValueError("expected official evidence IDs must be sorted and unique")
        material_classes = tuple(item.material_class for item in self.material_inventory)
        if (
            tuple(sorted(material_classes)) != material_classes
            or set(material_classes) != QUALIFIED_RIGHTS_MATERIAL_CLASSES
        ):
            raise ValueError("expected material inventory is not exhaustive and sorted")
        staged_paths = [file.path for item in self.material_inventory for file in item.files]
        if len(staged_paths) != len(set(staged_paths)):
            raise ValueError("expected staged files must have exactly one material class")
        if self.staged_file_inventory_sha256 != _canonical_sha256(
            _expected_inventory_payload(self.material_inventory)
        ):
            raise ValueError("expected staged file inventory digest is invalid")
        payload = self.model_dump(mode="json", round_trip=True)
        context_digest = payload.pop("canonical_context_sha256")
        if context_digest != _canonical_sha256(payload):
            raise ValueError("expected qualified-rights context seal is invalid")
        return self


class PublicationMaterialClassificationV1(_StrictFrozenModel):
    path: NonEmptyText
    material_class: SafeIdentifier

    @model_validator(mode="after")
    def _validate_classification(self) -> Self:
        _validate_public_file_path(self.path)
        if self.material_class not in QUALIFIED_RIGHTS_MATERIAL_CLASSES:
            raise ValueError("publication context material class is unknown")
        return self


class QualifiedRightsPublicationContextArtifactV1(_StrictFrozenModel):
    schema_name: Literal["QualifiedRightsPublicationContextArtifactV1"] = Field(alias="schema")
    official_source_evidence: tuple[ExpectedOfficialSourceEvidenceV1, ...]
    material_classifications: tuple[PublicationMaterialClassificationV1, ...]

    @field_validator("official_source_evidence", "material_classifications", mode="before")
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_artifact(self) -> Self:
        evidence_ids = tuple(item.evidence_id for item in self.official_source_evidence)
        if tuple(sorted(evidence_ids)) != evidence_ids or len(evidence_ids) != len(
            set(evidence_ids)
        ):
            raise ValueError("publication context evidence must be sorted and unique")
        paths = tuple(item.path for item in self.material_classifications)
        if tuple(sorted(paths)) != paths or len(paths) != len(set(paths)):
            raise ValueError("publication context classifications must be sorted and unique")
        return self


class _QualifiedRightsTrustedSignerV1(_StrictFrozenModel):
    signer_key_id: SafeIdentifier
    method: Literal["ed25519"]
    public_key_base64: NonEmptyText
    reviewer_kind: Literal["qualified_human_legal_reviewer"]
    human_name: NonEmptyText
    organization: NonEmptyText
    role: NonEmptyText
    qualifications: tuple[NonEmptyText, ...]
    jurisdictions: tuple[SafeIdentifier, ...]
    qualification_evidence_sha256: Sha256
    qualification_status: Literal["qualified"]
    qualified_scopes: tuple[SafeIdentifier, ...]
    valid_from_utc: NonEmptyText
    valid_until_utc: NonEmptyText
    revocation_status: Literal["not_revoked"]
    revocation_checked_at_utc: NonEmptyText
    revocation_review_by_utc: NonEmptyText
    revocation_evidence_sha256: Sha256

    @field_validator("qualifications", "jurisdictions", "qualified_scopes", mode="before")
    @classmethod
    def _convert_sequences(cls, value: object, info: Any) -> tuple[object, ...]:
        return _strict_tuple(value, field=info.field_name)

    @model_validator(mode="after")
    def _validate_signer(self) -> Self:
        _require_sorted_unique_strings(self.qualifications, field="trusted signer qualifications")
        _require_sorted_unique_strings(self.jurisdictions, field="trusted signer jurisdictions")
        _require_sorted_unique_strings(self.qualified_scopes, field="trusted signer scopes")
        try:
            public_key = base64.b64decode(self.public_key_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("trusted Ed25519 public key is not strict base64") from exc
        if len(public_key) != 32:
            raise ValueError("trusted Ed25519 public key must be exactly 32 bytes")
        valid_from = _parse_utc_timestamp(self.valid_from_utc, field="signer valid_from_utc")
        valid_until = _parse_utc_timestamp(self.valid_until_utc, field="signer valid_until_utc")
        revoked_at = _parse_utc_timestamp(
            self.revocation_checked_at_utc,
            field="signer revocation_checked_at_utc",
        )
        revocation_review = _parse_utc_timestamp(
            self.revocation_review_by_utc,
            field="signer revocation_review_by_utc",
        )
        if valid_from >= valid_until or revoked_at >= revocation_review:
            raise ValueError("trusted signer chronology is invalid")
        return self


class _QualifiedRightsTrustStoreV1(_StrictFrozenModel):
    schema_name: Literal["QualifiedRightsTrustStoreV1"] = Field(alias="schema")
    authority_id: SafeIdentifier
    issued_at_utc: NonEmptyText
    review_by_utc: NonEmptyText
    signers: tuple[_QualifiedRightsTrustedSignerV1, ...]
    canonical_trust_store_sha256: Sha256

    @field_validator("signers", mode="before")
    @classmethod
    def _convert_signers(cls, value: object) -> tuple[object, ...]:
        return _strict_tuple(value, field="signers")

    @model_validator(mode="after")
    def _validate_store(self) -> Self:
        issued = _parse_utc_timestamp(self.issued_at_utc, field="trust store issued_at_utc")
        review_by = _parse_utc_timestamp(self.review_by_utc, field="trust store review_by_utc")
        if issued >= review_by:
            raise ValueError("qualified-rights trust-store chronology is invalid")
        key_ids = tuple(item.signer_key_id for item in self.signers)
        if not key_ids or tuple(sorted(key_ids)) != key_ids or len(key_ids) != len(set(key_ids)):
            raise ValueError("qualified-rights trust-store keys must be sorted and unique")
        payload = self.model_dump(mode="json", round_trip=True, by_alias=True)
        digest = payload.pop("canonical_trust_store_sha256")
        if digest != _canonical_sha256(payload):
            raise ValueError("qualified-rights trust-store receipt digest is invalid")
        return self


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON object contains a duplicate key")
        result[key] = value
    return result


def _strict_json_object(encoded: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise KagglePublicationRightsBlockedError(
            f"Kaggle publication is blocked: {label} JSON is invalid"
        ) from exc
    if type(payload) is not dict:
        raise KagglePublicationRightsBlockedError(
            f"Kaggle publication is blocked: {label} must be an object"
        )
    return cast("dict[str, Any]", payload)


def parse_qualified_rights_disposition(encoded: bytes) -> QualifiedRightsDispositionV1:
    """Parse exact bounded credential bytes without treating structure as admission."""

    if type(encoded) is not bytes or not encoded or len(encoded) > _MAX_QUALIFIED_RIGHTS_BYTES:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights credential bytes are invalid"
        )
    payload = _strict_json_object(encoded, label="qualified rights credential")
    try:
        return QualifiedRightsDispositionV1.model_validate(payload, strict=True)
    except ValidationError as exc:
        first_error = exc.errors(include_url=False, include_context=False)[0]
        location = ".".join(str(part) for part in first_error["loc"]) or "credential"
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights credential is invalid at "
            f"{location}: {first_error['msg']}"
        ) from exc


def _read_stable_regular_file(path: Path, *, label: str, maximum_bytes: int) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise KagglePublicationRightsBlockedError(
            f"Kaggle publication is blocked: {label} is unavailable"
        ) from exc
    if path.is_symlink() or not stat.S_ISREG(before.st_mode):
        raise KagglePublicationRightsBlockedError(
            f"Kaggle publication is blocked: {label} must be a regular non-symlink file"
        )
    if before.st_size <= 0 or before.st_size > maximum_bytes:
        raise KagglePublicationRightsBlockedError(
            f"Kaggle publication is blocked: {label} size is invalid"
        )
    try:
        encoded = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise KagglePublicationRightsBlockedError(
            f"Kaggle publication is blocked: {label} cannot be read"
        ) from exc
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_identity != after_identity or len(encoded) != before.st_size:
        raise KagglePublicationRightsBlockedError(
            f"Kaggle publication is blocked: {label} changed while being read"
        )
    return encoded


def _metadata_target_and_license(encoded: bytes) -> tuple[str, str]:
    payload = _strict_json_object(encoded, label="dataset metadata")
    dataset = payload.get("id")
    licenses = payload.get("licenses")
    if (
        type(dataset) is not str
        or _KAGGLE_DATASET_RE.fullmatch(dataset) is None
        or type(licenses) is not list
        or len(licenses) != 1
        or type(licenses[0]) is not dict
        or set(licenses[0]) != {"name"}
        or type(licenses[0].get("name")) is not str
        or _SAFE_ID_RE.fullmatch(licenses[0]["name"]) is None
    ):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: dataset metadata target or license is invalid"
        )
    return dataset, cast("str", licenses[0]["name"])


def _parse_publication_context_artifact(
    encoded: bytes,
) -> QualifiedRightsPublicationContextArtifactV1:
    payload = _strict_json_object(encoded, label="qualified-rights publication context")
    try:
        return QualifiedRightsPublicationContextArtifactV1.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified-rights publication context is invalid"
        ) from exc


def reconstruct_qualified_rights_expected_context(
    publication_root: Path,
) -> QualifiedRightsExpectedContextV1:
    """Rebuild and seal the credential context from the exact publication tree."""

    if not isinstance(publication_root, Path):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified-rights publication root is invalid"
        )
    try:
        root_lstat = publication_root.lstat()
        root = publication_root.resolve(strict=True)
        root_stat = root.stat()
    except OSError as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified-rights publication root is unavailable"
        ) from exc
    if (
        publication_root.is_symlink()
        or not stat.S_ISDIR(root_stat.st_mode)
        or (root_lstat.st_dev, root_lstat.st_ino) != (root_stat.st_dev, root_stat.st_ino)
    ):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified-rights publication root is invalid"
        )
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    try:
        assured = verify_assured_artifact_manifest(
            root,
            expected_root_identity=root_identity,
        )
    except (OSError, ValueError) as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: exact assured publication artifacts are invalid"
        ) from exc

    assured_bytes = _read_stable_regular_file(
        root / ASSURED_ARTIFACT_MANIFEST_NAME,
        label="assured publication manifest",
        maximum_bytes=64 * 1024 * 1024,
    )
    metadata_bytes = _read_stable_regular_file(
        root / "dataset-metadata.json",
        label="dataset metadata",
        maximum_bytes=_MAX_DATASET_METADATA_BYTES,
    )
    report_bytes = _read_stable_regular_file(
        root / "terminal-assurance-report.json",
        label="terminal assurance report",
        maximum_bytes=_MAX_TERMINAL_REPORT_BYTES,
    )
    context_bytes = _read_stable_regular_file(
        root / QUALIFIED_RIGHTS_PUBLICATION_CONTEXT_NAME,
        label="qualified-rights publication context",
        maximum_bytes=_MAX_PUBLICATION_CONTEXT_BYTES,
    )
    context_artifact = _parse_publication_context_artifact(context_bytes)
    dataset, license_id = _metadata_target_and_license(metadata_bytes)

    raw_files = assured.get("files")
    if type(raw_files) is not list:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: assured publication inventory is invalid"
        )
    complete_files: list[dict[str, object]] = []
    for raw_file in raw_files:
        if type(raw_file) is not dict:
            raise KagglePublicationRightsBlockedError(
                "Kaggle publication is blocked: assured publication inventory is invalid"
            )
        complete_files.append(
            {
                "path": raw_file.get("path"),
                "bytes": raw_file.get("bytes"),
                "sha256": raw_file.get("sha256"),
            }
        )
    complete_files.append(
        {
            "path": ASSURED_ARTIFACT_MANIFEST_NAME,
            "bytes": len(assured_bytes),
            "sha256": hashlib.sha256(assured_bytes).hexdigest(),
        }
    )
    complete_files.append(
        {
            "path": "dataset-metadata.json",
            "bytes": len(metadata_bytes),
            "sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        }
    )
    complete_files.sort(key=lambda item: cast("str", item["path"]))
    if any(
        type(item["path"]) is not str
        or type(item["bytes"]) is not int
        or type(item["sha256"]) is not str
        for item in complete_files
    ):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: assured publication inventory is invalid"
        )
    classifications = {
        item.path: item.material_class for item in context_artifact.material_classifications
    }
    file_paths = {cast("str", item["path"]) for item in complete_files}
    if set(classifications) != file_paths:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: publication material classification is not exact"
        )

    files_by_class: dict[str, list[dict[str, object]]] = {
        material_class: [] for material_class in QUALIFIED_RIGHTS_MATERIAL_CLASSES
    }
    for item in complete_files:
        path = cast("str", item["path"])
        files_by_class[classifications[path]].append(item)
    material_inventory = [
        {
            "material_class": material_class,
            "files": files_by_class[material_class],
        }
        for material_class in sorted(QUALIFIED_RIGHTS_MATERIAL_CLASSES)
    ]
    inventory_with_classes = [
        {
            **item,
            "material_class": classifications[cast("str", item["path"])],
        }
        for item in complete_files
    ]
    canonical_provider = expected_nba_api_provider_authority().get("authority_sha256")
    if type(canonical_provider) is not str or _SHA256_RE.fullmatch(canonical_provider) is None:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: canonical provider authority is unavailable"
        )
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    context_payload: dict[str, object] = {
        "repository_source_sha": assured.get("source_sha"),
        "provider_authority_sha256": canonical_provider,
        "schema_contract_sha256": report_sha256,
        "staged_publication_manifest_sha256": hashlib.sha256(assured_bytes).hexdigest(),
        "staged_file_inventory_sha256": _canonical_sha256(inventory_with_classes),
        "publication_context_artifact_sha256": hashlib.sha256(context_bytes).hexdigest(),
        "dataset_metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "terminal_assurance_report_sha256": report_sha256,
        "kaggle_dataset": dataset,
        "kaggle_visibility": "public",
        "kaggle_license_id": license_id,
        "required_provider_hosts": list(_REQUIRED_PROVIDER_HOSTS),
        "required_competitions": list(_REQUIRED_COMPETITIONS),
        "official_source_evidence": [
            item.model_dump(mode="json", round_trip=True)
            for item in context_artifact.official_source_evidence
        ],
        "material_inventory": material_inventory,
    }
    context_payload["canonical_context_sha256"] = _canonical_sha256(context_payload)
    try:
        expected = QualifiedRightsExpectedContextV1.model_validate(context_payload, strict=True)
    except ValidationError as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: reconstructed qualified-rights context is invalid"
        ) from exc

    try:
        assured_after = verify_assured_artifact_manifest(
            root,
            expected_root_identity=root_identity,
        )
    except (OSError, ValueError) as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: publication artifacts changed during reconstruction"
        ) from exc
    if assured_after != assured:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: publication artifacts changed during reconstruction"
        )
    for path, prior, label, limit in (
        (
            root / ASSURED_ARTIFACT_MANIFEST_NAME,
            assured_bytes,
            "assured publication manifest",
            64 * 1024 * 1024,
        ),
        (
            root / "dataset-metadata.json",
            metadata_bytes,
            "dataset metadata",
            _MAX_DATASET_METADATA_BYTES,
        ),
        (
            root / "terminal-assurance-report.json",
            report_bytes,
            "terminal assurance report",
            _MAX_TERMINAL_REPORT_BYTES,
        ),
        (
            root / QUALIFIED_RIGHTS_PUBLICATION_CONTEXT_NAME,
            context_bytes,
            "qualified-rights publication context",
            _MAX_PUBLICATION_CONTEXT_BYTES,
        ),
    ):
        if _read_stable_regular_file(path, label=label, maximum_bytes=limit) != prior:
            raise KagglePublicationRightsBlockedError(
                "Kaggle publication is blocked: publication artifacts changed during reconstruction"
            )
    return expected


def _require_exact_qualified_context(
    credential: QualifiedRightsDispositionV1,
    expected: QualifiedRightsExpectedContextV1,
) -> None:
    subject = credential.subject
    exact_subject_fields = (
        ("repository source", subject.repository_source_sha, expected.repository_source_sha),
        (
            "provider authority",
            subject.provider_authority_sha256,
            expected.provider_authority_sha256,
        ),
        ("schema contract", subject.schema_contract_sha256, expected.schema_contract_sha256),
        (
            "staged publication manifest",
            subject.staged_publication_manifest_sha256,
            expected.staged_publication_manifest_sha256,
        ),
        ("Kaggle dataset", subject.kaggle_dataset, expected.kaggle_dataset),
        ("Kaggle visibility", subject.kaggle_visibility, expected.kaggle_visibility),
        (
            "Kaggle license",
            credential.kaggle_disposition.license_id,
            expected.kaggle_license_id,
        ),
    )
    for field, actual, wanted in exact_subject_fields:
        if actual != wanted:
            raise KagglePublicationRightsBlockedError(
                f"Kaggle publication is blocked: qualified rights {field} drifted"
            )
    if credential.provider_authority.covered_hosts != expected.required_provider_hosts:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights provider host coverage drifted"
        )
    if credential.provider_authority.covered_competitions != expected.required_competitions:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights competition coverage drifted"
        )

    actual_materials = {
        item.material_class: tuple((file.path, file.bytes, file.sha256) for file in item.files)
        for item in credential.material_dispositions
    }
    expected_materials = {
        item.material_class: tuple((file.path, file.bytes, file.sha256) for file in item.files)
        for item in expected.material_inventory
    }
    excluded = {
        item.material_class
        for item in credential.material_dispositions
        if item.decision == "excluded"
    }
    leaked = sorted(
        material_class for material_class in excluded if expected_materials[material_class]
    )
    if leaked:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: excluded qualified-rights material is staged"
        )
    if actual_materials != expected_materials:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights staged material inventory drifted"
        )
    if subject.staged_file_inventory_sha256 != expected.staged_file_inventory_sha256:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights staged file inventory drifted"
        )

    actual_evidence = tuple(
        item.model_dump(mode="json", round_trip=True)
        for item in credential.official_source_evidence
    )
    expected_evidence = tuple(
        item.model_dump(mode="json", round_trip=True) for item in expected.official_source_evidence
    )
    if actual_evidence != expected_evidence:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights official source evidence drifted"
        )


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_pinned_qualified_rights_trust_store() -> _QualifiedRightsTrustStoreV1:
    pinned_sha256 = _PINNED_QUALIFIED_RIGHTS_TRUST_STORE_SHA256
    if pinned_sha256 is None:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: repository-pinned qualified-rights trust store "
            "is not configured"
        )
    if type(pinned_sha256) is not str or _SHA256_RE.fullmatch(pinned_sha256) is None:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: repository-pinned qualified-rights trust-store "
            "digest is invalid"
        )
    try:
        repository_root = _default_project_root().resolve(strict=True)
    except OSError as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: repository trust root is unavailable"
        ) from exc
    encoded = _read_stable_regular_file(
        repository_root / QUALIFIED_RIGHTS_TRUST_STORE_RELATIVE_PATH,
        label="repository-pinned qualified-rights trust store",
        maximum_bytes=_MAX_TRUST_STORE_BYTES,
    )
    if hashlib.sha256(encoded).hexdigest() != pinned_sha256:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified-rights trust store is not the "
            "repository-pinned exact authority"
        )
    payload = _strict_json_object(encoded, label="qualified-rights trust store")
    try:
        store = _QualifiedRightsTrustStoreV1.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified-rights trust store is invalid"
        ) from exc
    canonical = _canonical_json_bytes(store.model_dump(mode="json", round_trip=True, by_alias=True))
    if encoded != canonical:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified-rights trust-store bytes are not canonical"
        )
    return store


def _decode_signature(signature: QualifiedRightsSignatureV1) -> bytes:
    try:
        decoded = base64.b64decode(signature.value_base64, validate=True)
    except (binascii.Error, ValueError) as exc:  # pragma: no cover - model already checks this
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights signature is invalid"
        ) from exc
    if len(decoded) != 64:  # pragma: no cover - model already checks this
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights signature is invalid"
        )
    return decoded


def _require_trusted_signer_and_verify_signature(
    *,
    credential: QualifiedRightsDispositionV1,
    trust_store: _QualifiedRightsTrustStoreV1,
    now: datetime,
) -> None:
    trust_store_issued_at = _parse_utc_timestamp(
        trust_store.issued_at_utc,
        field="trust store issued_at_utc",
    )
    trust_store_review_by = _parse_utc_timestamp(
        trust_store.review_by_utc,
        field="trust store review_by_utc",
    )
    if now < trust_store_issued_at or now >= trust_store_review_by:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: repository-pinned qualified-rights trust store "
            "is not currently valid"
        )
    signer = next(
        (
            item
            for item in trust_store.signers
            if item.signer_key_id == credential.signature.signer_key_id
        ),
        None,
    )
    if signer is None:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified-rights signer is not repository-trusted"
        )
    reviewer = credential.reviewer
    exact_identity = (
        signer.method == credential.signature.method,
        signer.reviewer_kind == reviewer.reviewer_kind,
        signer.human_name == reviewer.human_name,
        signer.organization == reviewer.organization,
        signer.role == reviewer.role,
        signer.qualifications == reviewer.qualifications,
        signer.jurisdictions == reviewer.jurisdictions,
        signer.qualification_evidence_sha256 == reviewer.qualification_evidence_sha256,
    )
    if not all(exact_identity):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: repository-trusted signer does not match the "
            "qualified human reviewer"
        )
    effective_scopes = _effective_scopes(
        provider=credential.provider_authority,
        materials=credential.material_dispositions,
        privacy=credential.privacy_disposition,
        kaggle=credential.kaggle_disposition,
    )
    material_jurisdictions = {
        jurisdiction
        for material in credential.material_dispositions
        if material.decision == "admitted"
        for jurisdiction in material.jurisdictions
    }
    required_jurisdictions = (
        set(reviewer.jurisdictions)
        | set(credential.privacy_disposition.jurisdictions)
        | material_jurisdictions
    )
    if not effective_scopes.issubset(
        signer.qualified_scopes
    ) or not required_jurisdictions.issubset(signer.jurisdictions):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: repository-trusted signer qualification scope "
            "is incomplete"
        )
    issued_at = _parse_utc_timestamp(credential.issued_at_utc, field="issued_at_utc")
    expires_at = _parse_utc_timestamp(credential.expires_at_utc, field="expires_at_utc")
    valid_from = _parse_utc_timestamp(signer.valid_from_utc, field="signer valid_from_utc")
    valid_until = _parse_utc_timestamp(signer.valid_until_utc, field="signer valid_until_utc")
    revocation_checked = _parse_utc_timestamp(
        signer.revocation_checked_at_utc,
        field="signer revocation_checked_at_utc",
    )
    revocation_review_by = _parse_utc_timestamp(
        signer.revocation_review_by_utc,
        field="signer revocation_review_by_utc",
    )
    if (
        issued_at < valid_from
        or expires_at > valid_until
        or now >= valid_until
        or revocation_checked > now
        or now >= revocation_review_by
    ):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: repository-trusted signer qualification or "
            "revocation evidence is not current"
        )
    try:
        public_key_bytes = base64.b64decode(signer.public_key_base64, validate=True)
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(_decode_signature(credential.signature), credential.signing_bytes())
    except ImportError as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: actual Ed25519 verification support is unavailable"
        ) from exc
    except (InvalidSignature, TypeError, ValueError, binascii.Error) as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights Ed25519 signature verification failed"
        ) from exc


def verify_qualified_rights_disposition(
    encoded: bytes,
    *,
    publication_root: Path,
) -> QualifiedRightsDispositionV1:
    """Verify exact artifacts and a repository-pinned qualified-human Ed25519 signature."""

    credential = parse_qualified_rights_disposition(encoded)
    expected_context = reconstruct_qualified_rights_expected_context(publication_root)
    _require_exact_qualified_context(credential, expected_context)
    now = datetime.now(UTC)
    issued_at = _parse_utc_timestamp(credential.issued_at_utc, field="issued_at_utc")
    review_by = _parse_utc_timestamp(credential.review_by_utc, field="review_by_utc")
    expires_at = _parse_utc_timestamp(credential.expires_at_utc, field="expires_at_utc")
    if issued_at > now or now >= review_by or now >= expires_at:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights credential is not currently valid"
        )
    trust_store = _load_pinned_qualified_rights_trust_store()
    _require_trusted_signer_and_verify_signature(
        credential=credential,
        trust_store=trust_store,
        now=now,
    )
    return credential


def _require_string(value: Any, *, field: str) -> str:
    if type(value) is not str or not value:
        raise KagglePublicationRightsBlockedError(
            f"Kaggle publication is blocked: invalid rights evidence field {field}"
        )
    return value


def _load_blocking_rights_evidence(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve(strict=True)
    evidence_path = root / RIGHTS_EVIDENCE_RELATIVE_PATH
    try:
        metadata = evidence_path.lstat()
    except OSError as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: the required rights evidence is unavailable"
        ) from exc
    if evidence_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: rights evidence must be a regular non-symlink file"
        )
    if metadata.st_size <= 0 or metadata.st_size > _MAX_RIGHTS_EVIDENCE_BYTES:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: rights evidence size is invalid"
        )
    try:
        payload_bytes = evidence_path.read_bytes()
    except OSError as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: rights evidence cannot be read"
        ) from exc
    if len(payload_bytes) != metadata.st_size:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: rights evidence changed while being read"
        )
    if hashlib.sha256(payload_bytes).hexdigest() != RIGHTS_EVIDENCE_SHA256:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: rights evidence is not the reviewed exact receipt"
        )
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: rights evidence is not valid JSON"
        ) from exc
    if type(payload) is not dict:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: rights evidence must be a JSON object"
        )
    return payload


def assert_public_kaggle_publication_admitted(
    *,
    project_root: Path | None = None,
    qualified_disposition: bytes | None = None,
    publication_root: Path | None = None,
) -> None:
    """Require the V1 blocker or an explicit artifact-bound qualified credential.

    Existing callers provide no qualified inputs and remain mechanically blocked by
    the exact checked-in V1 evidence.  A future integration must explicitly provide
    credential bytes and the exact publication root.  Trust is never caller supplied:
    only an exact repository-pinned trust-store file can authorize Ed25519 verification,
    and this repository currently pins none.
    """

    if qualified_disposition is not None:
        if project_root is not None:
            raise KagglePublicationRightsBlockedError(
                "Kaggle publication is blocked: qualified rights inputs are ambiguous"
            )
        if publication_root is None:
            raise KagglePublicationRightsBlockedError(
                "Kaggle publication is blocked: qualified rights publication artifacts "
                "are unavailable"
            )
        verify_qualified_rights_disposition(
            qualified_disposition,
            publication_root=publication_root,
        )
        return
    if publication_root is not None:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: qualified rights credential bytes are unavailable"
        )

    payload = _load_blocking_rights_evidence(project_root or _default_project_root())
    if _require_string(payload.get("schema"), field="schema") != RIGHTS_EVIDENCE_SCHEMA:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: unsupported rights evidence schema"
        )
    if (
        _require_string(payload.get("publication_admission"), field="publication_admission")
        != "blocked"
    ):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: schema V1 cannot grant publication admission"
        )
    reviewer = payload.get("reviewer")
    if type(reviewer) is not dict or reviewer.get("disposition") != "blocked":
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: reviewed disposition is invalid"
        )
    materials = payload.get("materials")
    if type(materials) is not list:
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: reviewed materials are invalid"
        )
    blocked_materials = {
        item.get("id")
        for item in materials
        if type(item) is dict and item.get("classification") == "blocked"
    }
    if not _REQUIRED_BLOCKED_MATERIALS.issubset(blocked_materials):
        raise KagglePublicationRightsBlockedError(
            "Kaggle publication is blocked: required blocked materials are absent"
        )
    raise KagglePublicationRightsBlockedError(
        "Kaggle publication is blocked by the reviewed rights receipt: provider-data "
        "publication authority, including exact parser bodies, is not admitted"
    )


__all__ = [
    "ExpectedMaterialInventoryV1",
    "ExpectedOfficialSourceEvidenceV1",
    "KaggleDispositionV1",
    "KagglePublicationRightsBlockedError",
    "MaterialDispositionV1",
    "OfficialSourceEvidenceV1",
    "PrivacyDispositionV1",
    "ProviderAuthorityV1",
    "PublicationMaterialClassificationV1",
    "QUALIFIED_RIGHTS_DISPOSITION_SCHEMA",
    "QUALIFIED_RIGHTS_MATERIAL_CLASSES",
    "QUALIFIED_RIGHTS_PUBLICATION_CONTEXT_NAME",
    "QUALIFIED_RIGHTS_TRUST_STORE_RELATIVE_PATH",
    "QualifiedReviewerV1",
    "QualifiedRightsConditionV1",
    "QualifiedRightsDispositionV1",
    "QualifiedRightsExpectedContextV1",
    "QualifiedRightsPublicationContextArtifactV1",
    "QualifiedRightsSignatureV1",
    "QualifiedRightsSubjectV1",
    "RIGHTS_EVIDENCE_RELATIVE_PATH",
    "RIGHTS_EVIDENCE_SCHEMA",
    "RIGHTS_EVIDENCE_SHA256",
    "StagedMaterialFileV1",
    "assert_public_kaggle_publication_admitted",
    "parse_qualified_rights_disposition",
    "reconstruct_qualified_rights_expected_context",
    "verify_qualified_rights_disposition",
]
