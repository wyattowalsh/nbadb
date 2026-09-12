from __future__ import annotations

import base64
import copy
import hashlib
import json
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from typer.testing import CliRunner

from nbadb.cli.app import app
from nbadb.core.artifact_identity import build_assured_artifact_manifest
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.kaggle import publication_rights as rights
from nbadb.kaggle.client import KaggleClient
from nbadb.kaggle.publication_rights import (
    QUALIFIED_RIGHTS_MATERIAL_CLASSES,
    QUALIFIED_RIGHTS_PUBLICATION_CONTEXT_NAME,
    QUALIFIED_RIGHTS_TRUST_STORE_RELATIVE_PATH,
    RIGHTS_EVIDENCE_RELATIVE_PATH,
    KagglePublicationRightsBlockedError,
    QualifiedRightsExpectedContextV1,
    assert_public_kaggle_publication_admitted,
    parse_qualified_rights_disposition,
    reconstruct_qualified_rights_expected_context,
    verify_qualified_rights_disposition,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"nbadb synthetic rights test key; never production authority").digest()
)
_OTHER_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"nbadb untrusted rights test key; never production authority").digest()
)
_PRIVACY_MATERIAL_CLASSES = frozenset(
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
_PROVIDER_HOSTS = ["api.nba.net", "cdn.nba.com", "stats.nba.com"]
_COMPETITIONS = ["g_league", "nba", "summer_league", "wnba"]
_PROVIDER_SCOPES = [
    "automated_access",
    "commercial_downstream_use",
    "comprehensive_regular_updates",
    "derived_exports",
    "exact_response_bodies",
    "live_near_live_and_archived_play_by_play",
    "local_retention",
    "public_redistribution",
    "transformation",
]
_DATASET = "synthetic-owner/synthetic-dataset"
_LICENSE = "CC-BY-SA-4.0"


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _signing_bytes(payload: dict[str, Any]) -> bytes:
    signing_payload = copy.deepcopy(payload)
    signing_payload.pop("canonical_receipt_sha256", None)
    signing_payload["signature"].pop("value_base64", None)
    return _canonical_bytes(signing_payload)


def _seal(
    payload: dict[str, Any],
    *,
    private_key: Ed25519PrivateKey = _TEST_PRIVATE_KEY,
    resign: bool = True,
) -> bytes:
    message = _signing_bytes(payload)
    payload["canonical_receipt_sha256"] = hashlib.sha256(message).hexdigest()
    if resign:
        payload["signature"]["value_base64"] = base64.b64encode(private_key.sign(message)).decode()
    return _canonical_bytes(payload)


def _effective_scopes() -> list[str]:
    scopes = {
        "automated_access",
        "kaggle_license",
        "privacy_and_publicity",
        "public_redistribution",
        *(_PROVIDER_SCOPES),
        *(f"provider_material:{value}" for value in _PROVIDER_MATERIAL_CLASSES),
        *(f"provider_host:{value}" for value in _PROVIDER_HOSTS),
        *(f"provider_competition:{value}" for value in _COMPETITIONS),
        *(f"material:{value}" for value in QUALIFIED_RIGHTS_MATERIAL_CLASSES),
        *(
            f"material_scope:{value}:public_redistribution"
            for value in QUALIFIED_RIGHTS_MATERIAL_CLASSES
        ),
        "privacy:exact_body_additive_fields",
        *(f"privacy_material:{value}" for value in _PRIVACY_MATERIAL_CLASSES),
        "privacy_jurisdiction:US",
        f"kaggle_target_sha256:{hashlib.sha256(_DATASET.encode()).hexdigest()}",
        "kaggle_visibility:public",
        f"kaggle_license:{_LICENSE}",
        "kaggle_license_scope:database_and_admitted_contents",
        "kaggle_commercial:true",
    }
    return sorted(scopes)


def _provider_scope_tokens() -> list[str]:
    return sorted(
        {
            *_PROVIDER_SCOPES,
            *(f"provider_material:{value}" for value in _PROVIDER_MATERIAL_CLASSES),
            *(f"provider_host:{value}" for value in _PROVIDER_HOSTS),
            *(f"provider_competition:{value}" for value in _COMPETITIONS),
        }
    )


def _privacy_scope_tokens() -> list[str]:
    return sorted(
        {
            "privacy_and_publicity",
            "privacy:exact_body_additive_fields",
            *(f"privacy_material:{value}" for value in _PRIVACY_MATERIAL_CLASSES),
            "privacy_jurisdiction:US",
        }
    )


def _kaggle_scope_tokens() -> list[str]:
    return sorted(
        {
            "kaggle_license",
            f"kaggle_target_sha256:{hashlib.sha256(_DATASET.encode()).hexdigest()}",
            "kaggle_visibility:public",
            f"kaggle_license:{_LICENSE}",
            "kaggle_license_scope:database_and_admitted_contents",
            "kaggle_commercial:true",
        }
    )


def _official_evidence() -> list[dict[str, Any]]:
    scopes = _effective_scopes()
    rows = [
        (
            "client-license",
            "client_license",
            "nba_api maintainers",
            "https://raw.githubusercontent.com/swar/nba_api/v1.11.4/LICENSE",
            "nba_api v1.11.4",
        ),
        (
            "kaggle-aup",
            "platform_aup",
            "Kaggle Inc.",
            "https://www.kaggle.com/aup",
            "effective 2025-06-22",
        ),
        (
            "kaggle-privacy",
            "platform_privacy",
            "Kaggle Inc.",
            "https://www.kaggle.com/privacy",
            "effective 2024-02-05",
        ),
        (
            "kaggle-terms",
            "platform_terms",
            "Kaggle Inc.",
            "https://www.kaggle.com/terms",
            "effective 2025-06-22",
        ),
        (
            "nba-privacy",
            "provider_privacy",
            "NBA Media Ventures LLC",
            "https://www.nba.com/privacy-policy",
            "last updated April 2026",
        ),
        (
            "nba-terms",
            "provider_terms",
            "NBA Media Ventures LLC",
            "https://www.nba.com/termsofuse",
            "last updated 2026-07-13",
        ),
    ]
    return [
        {
            "evidence_id": evidence_id,
            "source_type": source_type,
            "publisher": publisher,
            "url": url,
            "edition": edition,
            "retrieved_at_utc": "2026-08-27T12:00:00Z",
            "content_sha256": _sha256(evidence_id),
            "normalization_method": "synthetic test evidence; not production authority",
            "supersession_status": "current",
            "reviewed_scopes": scopes,
        }
        for evidence_id, source_type, publisher, url, edition in rows
    ]


def _publication_classifications() -> list[dict[str, str]]:
    items = [
        {
            "path": f"synthetic/{material_class}.json",
            "material_class": material_class,
        }
        for material_class in sorted(QUALIFIED_RIGHTS_MATERIAL_CLASSES)
    ]
    items.extend(
        {
            "path": path,
            "material_class": "dataset_metadata_documentation_and_code",
        }
        for path in (
            "assured-artifact-manifest.json",
            "dataset-metadata.json",
            QUALIFIED_RIGHTS_PUBLICATION_CONTEXT_NAME,
            "terminal-assurance-report.json",
        )
    )
    return sorted(items, key=lambda item: item["path"])


def _build_publication_root(tmp_path: Path) -> tuple[Path, QualifiedRightsExpectedContextV1]:
    root = tmp_path / "publication"
    for material_class in sorted(QUALIFIED_RIGHTS_MATERIAL_CLASSES):
        path = root / f"synthetic/{material_class}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic material: {material_class}\n".encode())
    (root / "terminal-assurance-report.json").write_bytes(
        _canonical_bytes({"schema_version": 7, "status": "synthetic-test-only"})
    )
    publication_context = {
        "schema": "QualifiedRightsPublicationContextArtifactV1",
        "official_source_evidence": _official_evidence(),
        "material_classifications": _publication_classifications(),
    }
    (root / QUALIFIED_RIGHTS_PUBLICATION_CONTEXT_NAME).write_bytes(
        _canonical_bytes(publication_context)
    )
    (root / "dataset-metadata.json").write_bytes(
        _canonical_bytes({"id": _DATASET, "licenses": [{"name": _LICENSE}]})
    )
    build_assured_artifact_manifest(
        root,
        chain_id="synthetic-rights-test-chain",
        source_sha="1" * 40,
        coverage_fingerprint="2" * 64,
    )
    return root, reconstruct_qualified_rights_expected_context(root)


def _condition_evidence_digest(
    evidence: list[dict[str, Any]],
    evidence_ids: list[str],
) -> str:
    by_id = {item["evidence_id"]: item for item in evidence}
    return _canonical_sha256([by_id[evidence_id] for evidence_id in evidence_ids])


def _qualified_payload(context: QualifiedRightsExpectedContextV1) -> dict[str, Any]:
    now = datetime.now(UTC).replace(microsecond=0)
    evidence = [
        item.model_dump(mode="json", round_trip=True) for item in context.official_source_evidence
    ]
    materials = []
    for inventory in context.material_inventory:
        material_class = inventory.material_class
        if material_class in _PROVIDER_MATERIAL_CLASSES:
            evidence_ids = ["nba-terms"]
        elif material_class == "dataset_metadata_documentation_and_code":
            evidence_ids = ["kaggle-terms"]
        else:
            evidence_ids = ["client-license"]
        materials.append(
            {
                "material_class": material_class,
                "decision": "admitted",
                "files": [
                    item.model_dump(mode="json", round_trip=True) for item in inventory.files
                ],
                "permitted_scopes": ["public_redistribution"],
                "jurisdictions": ["US"],
                "attribution_requirement": "Synthetic test-only attribution requirement.",
                "privacy_disposition_id": (
                    "privacy-review-1" if material_class in _PRIVACY_MATERIAL_CLASSES else None
                ),
                "evidence_ids": evidence_ids,
                "conditions": [],
            }
        )
    issued_at = now - timedelta(days=1)
    review_by = now + timedelta(days=30)
    conditions = [
        {
            "condition_id": "condition-kaggle",
            "description": "Synthetic Kaggle condition discharge.",
            "applies_to_scopes": _kaggle_scope_tokens(),
            "disposition": "discharged",
            "discharged_at_utc": _timestamp(now - timedelta(days=2)),
            "review_by_utc": _timestamp(now + timedelta(days=45)),
            "discharge_evidence_ids": ["kaggle-aup", "kaggle-privacy", "kaggle-terms"],
            "discharge_evidence_sha256": _condition_evidence_digest(
                evidence,
                ["kaggle-aup", "kaggle-privacy", "kaggle-terms"],
            ),
        },
        {
            "condition_id": "condition-privacy",
            "description": "Synthetic privacy condition discharge.",
            "applies_to_scopes": _privacy_scope_tokens(),
            "disposition": "discharged",
            "discharged_at_utc": _timestamp(now - timedelta(days=2)),
            "review_by_utc": _timestamp(now + timedelta(days=45)),
            "discharge_evidence_ids": ["kaggle-privacy", "nba-privacy"],
            "discharge_evidence_sha256": _condition_evidence_digest(
                evidence,
                ["kaggle-privacy", "nba-privacy"],
            ),
        },
        {
            "condition_id": "condition-provider",
            "description": "Synthetic access-control and revocation condition discharge.",
            "applies_to_scopes": _provider_scope_tokens(),
            "disposition": "discharged",
            "discharged_at_utc": _timestamp(now - timedelta(days=2)),
            "review_by_utc": _timestamp(now + timedelta(days=45)),
            "discharge_evidence_ids": ["nba-terms"],
            "discharge_evidence_sha256": _condition_evidence_digest(evidence, ["nba-terms"]),
        },
    ]
    return {
        "schema": "QualifiedRightsDispositionV1",
        "receipt_id": "synthetic-qualified-rights-receipt",
        "issued_at_utc": _timestamp(issued_at),
        "review_by_utc": _timestamp(review_by),
        "expires_at_utc": _timestamp(now + timedelta(days=60)),
        "reviewer": {
            "reviewer_kind": "qualified_human_legal_reviewer",
            "human_name": "Synthetic Test Reviewer",
            "organization": "Synthetic Test Authority",
            "role": "Qualified test legal reviewer",
            "qualifications": ["Synthetic credential-test qualification"],
            "jurisdictions": ["US"],
            "qualification_evidence_sha256": _sha256("qualification"),
            "is_ai_system": False,
            "self_attestation_only": False,
            "conflict_disclosure": "Synthetic test reviewer has no production authority.",
            "signed_scope": _effective_scopes(),
        },
        "subject": {
            "repository_source_sha": context.repository_source_sha,
            "provider_authority_sha256": context.provider_authority_sha256,
            "schema_contract_sha256": context.schema_contract_sha256,
            "staged_publication_manifest_sha256": (context.staged_publication_manifest_sha256),
            "staged_file_inventory_sha256": context.staged_file_inventory_sha256,
            "kaggle_dataset": context.kaggle_dataset,
            "kaggle_visibility": context.kaggle_visibility,
        },
        "official_source_evidence": evidence,
        "provider_authority": {
            "basis": "qualified_legal_review",
            "authority_document_sha256": _sha256("authority-document"),
            "counterparties": ["Dataset owner", "NBA Media Ventures LLC"],
            "covered_material_classes": sorted(_PROVIDER_MATERIAL_CLASSES),
            "covered_hosts": list(_PROVIDER_HOSTS),
            "covered_competitions": list(_COMPETITIONS),
            "covered_scopes": list(_PROVIDER_SCOPES),
            "access_control_conditions": ["condition-provider"],
            "rate_limit_disposition": "Synthetic reviewed rate-limit disposition.",
            "revocation_conditions": ["condition-provider"],
            "authority_evidence_ids": ["nba-terms"],
        },
        "material_dispositions": materials,
        "privacy_disposition": {
            "disposition_id": "privacy-review-1",
            "reviewed_material_classes": sorted(_PRIVACY_MATERIAL_CLASSES),
            "field_inventory_sha256": _sha256("field-inventory"),
            "exact_body_additive_field_review_sha256": _sha256("additive-fields"),
            "person_related_data_present": True,
            "minors_and_sensitive_data_reviewed": True,
            "publicity_rights_reviewed": True,
            "legal_basis": "Synthetic test-only reviewed basis.",
            "minimization_and_redaction": "Synthetic test-only minimization disposition.",
            "jurisdictions": ["US"],
            "data_subject_rights_process": "Synthetic access, correction, and deletion process.",
            "takedown_contact": "rights-test@example.invalid",
            "retention_and_deletion_policy": "Synthetic bounded retention and deletion policy.",
            "backups_and_mirrors_reviewed": True,
            "incident_response_process": "Synthetic test incident response process.",
            "evidence_ids": ["kaggle-privacy", "nba-privacy"],
            "condition_ids": ["condition-privacy"],
        },
        "kaggle_disposition": {
            "dataset": context.kaggle_dataset,
            "visibility": context.kaggle_visibility,
            "license_id": context.kaggle_license_id,
            "license_scope": "database_and_admitted_contents",
            "license_excluded_material_classes": [],
            "commercial_downstream_permitted": True,
            "uploader_rights_warranty_satisfied": True,
            "public_user_submission_grants_reviewed": True,
            "attribution_text": "Synthetic NBA.com and source attribution.",
            "attribution_surfaces": [
                "csv",
                "dataset_landing_page",
                "dataset_metadata",
                "duckdb",
                "parquet",
                "sqlite",
            ],
            "provider_terms_notice": "Synthetic provider-terms notice.",
            "takedown_contact": "rights-test@example.invalid",
            "terms_evidence_ids": ["kaggle-aup", "kaggle-privacy", "kaggle-terms"],
            "condition_ids": ["condition-kaggle"],
        },
        "conditions": conditions,
        "unresolved_questions": [],
        "publication_admission": "qualified",
        "signature": {
            "method": "ed25519",
            "signer_key_id": "synthetic-test-key",
            "value_base64": base64.b64encode(bytes(64)).decode(),
        },
        "canonical_receipt_sha256": "0" * 64,
    }


def _material(payload: dict[str, Any], material_class: str) -> dict[str, Any]:
    return next(
        item
        for item in payload["material_dispositions"]
        if item["material_class"] == material_class
    )


def _write_trust_store(repository_root: Path, payload: dict[str, Any]) -> str:
    now = datetime.now(UTC).replace(microsecond=0)
    reviewer = payload["reviewer"]
    public_key = _TEST_PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    store: dict[str, Any] = {
        "schema": "QualifiedRightsTrustStoreV1",
        "authority_id": "synthetic-test-repository-trust",
        "issued_at_utc": _timestamp(now - timedelta(days=10)),
        "review_by_utc": _timestamp(now + timedelta(days=90)),
        "signers": [
            {
                "signer_key_id": "synthetic-test-key",
                "method": "ed25519",
                "public_key_base64": base64.b64encode(public_key).decode(),
                "reviewer_kind": reviewer["reviewer_kind"],
                "human_name": reviewer["human_name"],
                "organization": reviewer["organization"],
                "role": reviewer["role"],
                "qualifications": reviewer["qualifications"],
                "jurisdictions": reviewer["jurisdictions"],
                "qualification_evidence_sha256": reviewer["qualification_evidence_sha256"],
                "qualification_status": "qualified",
                "qualified_scopes": reviewer["signed_scope"],
                "valid_from_utc": _timestamp(now - timedelta(days=10)),
                "valid_until_utc": _timestamp(now + timedelta(days=365)),
                "revocation_status": "not_revoked",
                "revocation_checked_at_utc": _timestamp(now - timedelta(days=1)),
                "revocation_review_by_utc": _timestamp(now + timedelta(days=90)),
                "revocation_evidence_sha256": _sha256("synthetic-revocation-evidence"),
            }
        ],
        "canonical_trust_store_sha256": "0" * 64,
    }
    receipt_payload = copy.deepcopy(store)
    receipt_payload.pop("canonical_trust_store_sha256")
    store["canonical_trust_store_sha256"] = _canonical_sha256(receipt_payload)
    encoded = _canonical_bytes(store)
    path = repository_root / QUALIFIED_RIGHTS_TRUST_STORE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


@contextmanager
def _pinned_test_trust(
    tmp_path: Path,
    payload: dict[str, Any],
) -> Iterator[None]:
    repository_root = tmp_path / "synthetic-repository-root"
    digest = _write_trust_store(repository_root, payload)
    with (
        patch.object(rights, "_PINNED_QUALIFIED_RIGHTS_TRUST_STORE_SHA256", digest),
        patch.object(rights, "_default_project_root", return_value=repository_root),
    ):
        yield


def _credential_fixture(
    tmp_path: Path,
) -> tuple[Path, QualifiedRightsExpectedContextV1, dict[str, Any]]:
    publication_root, context = _build_publication_root(tmp_path)
    return publication_root, context, _qualified_payload(context)


def test_checked_in_rights_receipt_mechanically_blocks_publication() -> None:
    with pytest.raises(
        KagglePublicationRightsBlockedError,
        match="provider-data publication authority",
    ):
        assert_public_kaggle_publication_admitted()


def test_upload_blocks_before_local_claim_or_kaggle_import(tmp_path: Path) -> None:
    client = KaggleClient()
    with (
        patch.object(client, "_local_upload_claim", return_value=nullcontext()) as claim,
        patch.dict("sys.modules", {"kagglehub": None}),
        pytest.raises(KagglePublicationRightsBlockedError),
    ):
        client.upload(tmp_path)
    claim.assert_not_called()


def test_private_claimed_path_cannot_bypass_rights_gate(tmp_path: Path) -> None:
    client = KaggleClient()
    with (
        patch.dict("sys.modules", {"kagglehub": None}),
        pytest.raises(KagglePublicationRightsBlockedError),
    ):
        client._upload_claimed(tmp_path)


def test_cli_blocks_before_client_or_metadata_preparation(tmp_path: Path) -> None:
    with (
        patch(
            "nbadb.cli.commands.upload._build_settings",
            return_value=SimpleNamespace(data_dir=tmp_path),
        ),
        patch(
            "nbadb.orchestrate.successor_publication_authority.successor_publication_requested",
            return_value=False,
        ),
        patch("nbadb.kaggle.client.KaggleClient") as client,
    ):
        result = CliRunner().invoke(app, ["upload"])

    assert result.exit_code == 1
    assert "provider-data publication authority" in result.output
    client.assert_not_called()


def test_missing_rights_receipt_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(KagglePublicationRightsBlockedError, match="unavailable"):
        assert_public_kaggle_publication_admitted(project_root=tmp_path)


def test_modified_rights_receipt_cannot_turn_v1_into_admission(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[3] / RIGHTS_EVIDENCE_RELATIVE_PATH
    target = tmp_path / RIGHTS_EVIDENCE_RELATIVE_PATH
    target.parent.mkdir(parents=True)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["publication_admission"] = "admitted"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(KagglePublicationRightsBlockedError, match="exact receipt"):
        assert_public_kaggle_publication_admitted(project_root=tmp_path)


def test_symlinked_rights_receipt_fails_closed(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[3] / RIGHTS_EVIDENCE_RELATIVE_PATH
    target = tmp_path / RIGHTS_EVIDENCE_RELATIVE_PATH
    target.parent.mkdir(parents=True)
    target.symlink_to(source)

    with pytest.raises(KagglePublicationRightsBlockedError, match="non-symlink"):
        assert_public_kaggle_publication_admitted(project_root=tmp_path)


def test_real_ed25519_and_exact_artifacts_are_required_for_synthetic_positive(
    tmp_path: Path,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    encoded = _seal(payload)

    with _pinned_test_trust(tmp_path, payload):
        verified = verify_qualified_rights_disposition(
            encoded,
            publication_root=publication_root,
        )
        assert_public_kaggle_publication_admitted(
            qualified_disposition=encoded,
            publication_root=publication_root,
        )

    assert verified == parse_qualified_rights_disposition(encoded)
    assert verified.signing_bytes() == _signing_bytes(payload)


def test_production_has_no_embedded_trust_store_or_default_credential(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)

    with pytest.raises(KagglePublicationRightsBlockedError, match="trust store is not configured"):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_partial_or_ambiguous_qualified_inputs_cannot_bypass_v1(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    encoded = _seal(payload)

    with pytest.raises(KagglePublicationRightsBlockedError, match="artifacts are unavailable"):
        assert_public_kaggle_publication_admitted(qualified_disposition=encoded)
    with pytest.raises(KagglePublicationRightsBlockedError, match="bytes are unavailable"):
        assert_public_kaggle_publication_admitted(publication_root=publication_root)
    with pytest.raises(KagglePublicationRightsBlockedError, match="inputs are ambiguous"):
        assert_public_kaggle_publication_admitted(
            project_root=tmp_path,
            qualified_disposition=encoded,
            publication_root=publication_root,
        )


def _payload_inventory_sha256(payload: dict[str, Any]) -> str:
    inventory = sorted(
        (
            {
                "path": file["path"],
                "bytes": file["bytes"],
                "sha256": file["sha256"],
                "material_class": material["material_class"],
            }
            for material in payload["material_dispositions"]
            for file in material["files"]
        ),
        key=lambda item: item["path"],
    )
    return _canonical_sha256(inventory)


def _payload_effective_scopes(payload: dict[str, Any]) -> list[str]:
    provider = payload["provider_authority"]
    privacy = payload["privacy_disposition"]
    kaggle = payload["kaggle_disposition"]
    scopes = {
        "automated_access",
        "kaggle_license",
        "privacy_and_publicity",
        "public_redistribution",
        *(provider["covered_scopes"]),
        *(f"provider_material:{value}" for value in provider["covered_material_classes"]),
        *(f"provider_host:{value}" for value in provider["covered_hosts"]),
        *(f"provider_competition:{value}" for value in provider["covered_competitions"]),
        "privacy:exact_body_additive_fields",
        *(f"privacy_material:{value}" for value in privacy["reviewed_material_classes"]),
        *(f"privacy_jurisdiction:{value}" for value in privacy["jurisdictions"]),
        f"kaggle_target_sha256:{hashlib.sha256(kaggle['dataset'].encode()).hexdigest()}",
        f"kaggle_visibility:{kaggle['visibility']}",
        f"kaggle_license:{kaggle['license_id']}",
        f"kaggle_license_scope:{kaggle['license_scope']}",
        f"kaggle_commercial:{str(kaggle['commercial_downstream_permitted']).lower()}",
        *(
            f"kaggle_excluded_material:{value}"
            for value in kaggle["license_excluded_material_classes"]
        ),
    }
    for material in payload["material_dispositions"]:
        if material["decision"] == "admitted":
            scopes.add(f"material:{material['material_class']}")
            scopes.update(
                f"material_scope:{material['material_class']}:{scope}"
                for scope in material["permitted_scopes"]
            )
    return sorted(scopes)


def _condition(payload: dict[str, Any], condition_id: str) -> dict[str, Any]:
    return next(item for item in payload["conditions"] if item["condition_id"] == condition_id)


def _refresh_condition_digests(payload: dict[str, Any]) -> None:
    evidence_by_id = {item["evidence_id"]: item for item in payload["official_source_evidence"]}
    for condition in payload["conditions"]:
        condition["discharge_evidence_sha256"] = _canonical_sha256(
            [evidence_by_id[evidence_id] for evidence_id in condition["discharge_evidence_ids"]]
        )


def _rewrite_trust_store(
    repository_root: Path,
    mutate: Any,
) -> str:
    path = repository_root / QUALIFIED_RIGHTS_TRUST_STORE_RELATIVE_PATH
    store = json.loads(path.read_bytes())
    mutate(store)
    receipt_payload = copy.deepcopy(store)
    receipt_payload.pop("canonical_trust_store_sha256", None)
    store["canonical_trust_store_sha256"] = _canonical_sha256(receipt_payload)
    encoded = _canonical_bytes(store)
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


@contextmanager
def _mutated_pinned_test_trust(
    tmp_path: Path,
    payload: dict[str, Any],
    mutate: Any,
) -> Iterator[None]:
    repository_root = tmp_path / "synthetic-mutated-repository-root"
    _write_trust_store(repository_root, payload)
    digest = _rewrite_trust_store(repository_root, mutate)
    with (
        patch.object(rights, "_PINNED_QUALIFIED_RIGHTS_TRUST_STORE_SHA256", digest),
        patch.object(rights, "_default_project_root", return_value=repository_root),
    ):
        yield


def test_all_zero_signature_cannot_pass_actual_ed25519_verification(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    encoded = _seal(payload)
    sealed = json.loads(encoded)
    sealed["signature"]["value_base64"] = base64.b64encode(bytes(64)).decode()

    with (
        _pinned_test_trust(tmp_path, payload),
        pytest.raises(KagglePublicationRightsBlockedError, match="Ed25519 signature"),
    ):
        verify_qualified_rights_disposition(
            _canonical_bytes(sealed),
            publication_root=publication_root,
        )


def test_caller_cannot_supply_an_ignore_everything_verifier(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    admission: Any = verify_qualified_rights_disposition

    with pytest.raises(TypeError, match="signature_verifier"):
        admission(
            _seal(payload),
            publication_root=publication_root,
            signature_verifier=object(),
        )


def test_caller_cannot_self_project_expected_context_from_credential(tmp_path: Path) -> None:
    publication_root, context, payload = _credential_fixture(tmp_path)
    admission: Any = verify_qualified_rights_disposition
    projected = context.model_copy(update={"repository_source_sha": "f" * 40})

    with pytest.raises(TypeError, match="expected_context"):
        admission(
            _seal(payload),
            publication_root=publication_root,
            expected_context=projected,
        )


def test_unresealed_credential_tamper_breaks_canonical_receipt(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    encoded = _seal(payload)
    tampered = json.loads(encoded)
    tampered["subject"]["repository_source_sha"] = "f" * 40

    with pytest.raises(KagglePublicationRightsBlockedError, match="canonical receipt digest"):
        parse_qualified_rights_disposition(_canonical_bytes(tampered))


def test_resealed_credential_signed_by_untrusted_key_is_rejected(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)

    with (
        _pinned_test_trust(tmp_path, payload),
        pytest.raises(KagglePublicationRightsBlockedError, match="Ed25519 signature"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload, private_key=_OTHER_PRIVATE_KEY),
            publication_root=publication_root,
        )


def test_canonical_provider_authority_digest_cannot_be_rebound_and_resealed(
    tmp_path: Path,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["subject"]["provider_authority_sha256"] = "f" * 64

    with pytest.raises(KagglePublicationRightsBlockedError, match="canonical provider authority"):
        parse_qualified_rights_disposition(_seal(payload))


def test_staged_inventory_digest_is_algebraically_bound_inside_credential(
    tmp_path: Path,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["subject"]["staged_file_inventory_sha256"] = "f" * 64

    with pytest.raises(KagglePublicationRightsBlockedError, match="inventory digest is invalid"):
        parse_qualified_rights_disposition(_seal(payload))


def test_fully_resealed_material_digest_relabel_does_not_match_exact_artifacts(
    tmp_path: Path,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    target = _material(payload, "provider_exact_stats_bodies")["files"][0]
    target["sha256"] = "f" * 64
    payload["subject"]["staged_file_inventory_sha256"] = _payload_inventory_sha256(payload)

    with (
        _pinned_test_trust(tmp_path, payload),
        pytest.raises(KagglePublicationRightsBlockedError, match="material inventory drifted"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("repository_source_sha", "f" * 40, "repository source drifted"),
        ("schema_contract_sha256", "f" * 64, "schema contract drifted"),
        (
            "staged_publication_manifest_sha256",
            "f" * 64,
            "staged publication manifest drifted",
        ),
    ],
)
def test_signed_subject_drift_cannot_override_reconstructed_artifacts(
    tmp_path: Path,
    field: str,
    replacement: str,
    message: str,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["subject"][field] = replacement

    with (
        _pinned_test_trust(tmp_path, payload),
        pytest.raises(KagglePublicationRightsBlockedError, match=message),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


@pytest.mark.parametrize("field", ["source_type", "edition", "content_sha256"])
def test_official_source_type_or_edition_relabel_cannot_override_artifact_context(
    tmp_path: Path,
    field: str,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    nba_terms = next(
        item for item in payload["official_source_evidence"] if item["evidence_id"] == "nba-terms"
    )
    if field == "source_type":
        nba_terms["source_type"] = "provider_api_terms"
    elif field == "edition":
        nba_terms["edition"] = "attacker relabeled edition"
    else:
        nba_terms["content_sha256"] = "f" * 64

    with pytest.raises(KagglePublicationRightsBlockedError):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_reviewer_scope_relabel_is_rejected_even_when_resealed(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["reviewer"]["signed_scope"].remove("exact_response_bodies")
    payload["reviewer"]["signed_scope"].append("worldwide_sublicense")
    payload["reviewer"]["signed_scope"].sort()

    with pytest.raises(KagglePublicationRightsBlockedError, match="signed scope"):
        parse_qualified_rights_disposition(_seal(payload))


def test_referenced_evidence_scope_must_cover_effective_provider_scope(
    tmp_path: Path,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    nba_terms = next(
        item for item in payload["official_source_evidence"] if item["evidence_id"] == "nba-terms"
    )
    nba_terms["reviewed_scopes"].remove("exact_response_bodies")

    with pytest.raises(KagglePublicationRightsBlockedError, match="evidence signed scope"):
        parse_qualified_rights_disposition(_seal(payload))


def test_material_scope_relabel_cannot_override_artifact_evidence_scope(
    tmp_path: Path,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    baseline_for_trust = copy.deepcopy(payload)
    material = _material(payload, "provider_exact_stats_bodies")
    material["permitted_scopes"].append("commercial_sublicense")
    material["permitted_scopes"].sort()
    new_scopes = _payload_effective_scopes(payload)
    payload["reviewer"]["signed_scope"] = new_scopes
    for evidence in payload["official_source_evidence"]:
        evidence["reviewed_scopes"] = new_scopes
    _refresh_condition_digests(payload)

    with (
        _pinned_test_trust(tmp_path, baseline_for_trust),
        pytest.raises(KagglePublicationRightsBlockedError, match="source evidence drifted"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("scope_relabel", "condition scope binding"),
        ("missing_discharge", "discharge evidence IDs"),
        ("digest_relabel", "discharge evidence digest"),
        ("stale_discharge", "condition discharge is not current"),
        ("unknown_reference", "condition references"),
    ],
)
def test_conditions_require_exact_scoped_current_discharge_evidence(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    provider_condition = _condition(payload, "condition-provider")
    if mutation == "scope_relabel":
        provider_condition["applies_to_scopes"][-1] = "transformation_relabel"
        provider_condition["applies_to_scopes"].sort()
    elif mutation == "missing_discharge":
        provider_condition["discharge_evidence_ids"] = []
    elif mutation == "digest_relabel":
        provider_condition["discharge_evidence_sha256"] = "f" * 64
    elif mutation == "stale_discharge":
        provider_condition["review_by_utc"] = payload["issued_at_utc"]
    else:
        payload["provider_authority"]["access_control_conditions"] = ["condition-unknown"]

    with pytest.raises(KagglePublicationRightsBlockedError, match=message):
        parse_qualified_rights_disposition(_seal(payload))


def test_condition_source_scope_cannot_be_relabelled(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    provider_condition = _condition(payload, "condition-provider")
    provider_condition["applies_to_scopes"].remove("exact_response_bodies")

    with pytest.raises(KagglePublicationRightsBlockedError, match="condition scope binding"):
        parse_qualified_rights_disposition(_seal(payload))


def test_omitted_material_class_is_rejected_even_when_resealed(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["material_dispositions"].pop()

    with pytest.raises(KagglePublicationRightsBlockedError, match="not exhaustive"):
        parse_qualified_rights_disposition(_seal(payload))


def test_excluded_material_present_in_exact_artifacts_is_rejected(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    excluded_class = "repo_synthetic_fixtures"
    excluded = _material(payload, excluded_class)
    excluded.update(
        {
            "decision": "excluded",
            "files": [],
            "permitted_scopes": [],
            "jurisdictions": [],
            "privacy_disposition_id": None,
            "evidence_ids": [],
            "conditions": [],
        }
    )
    payload["kaggle_disposition"]["license_excluded_material_classes"] = [excluded_class]
    payload["subject"]["staged_file_inventory_sha256"] = _payload_inventory_sha256(payload)
    new_scopes = _payload_effective_scopes(payload)
    payload["reviewer"]["signed_scope"] = new_scopes
    for evidence in payload["official_source_evidence"]:
        evidence["reviewed_scopes"] = new_scopes
    _condition(payload, "condition-kaggle")["applies_to_scopes"] = sorted(
        set(_kaggle_scope_tokens()) | {f"kaggle_excluded_material:{excluded_class}"}
    )
    evidence_by_id = {item["evidence_id"]: item for item in payload["official_source_evidence"]}
    for condition in payload["conditions"]:
        condition["discharge_evidence_sha256"] = _canonical_sha256(
            [evidence_by_id[evidence_id] for evidence_id in condition["discharge_evidence_ids"]]
        )

    with (
        _pinned_test_trust(tmp_path, payload),
        pytest.raises(KagglePublicationRightsBlockedError, match="excluded.*material is staged"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_excluded_material_cannot_retain_a_staged_file(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    excluded = _material(payload, "repo_synthetic_fixtures")
    excluded.update(
        {
            "decision": "excluded",
            "permitted_scopes": [],
            "jurisdictions": [],
            "privacy_disposition_id": None,
            "evidence_ids": [],
        }
    )
    payload["kaggle_disposition"]["license_excluded_material_classes"] = ["repo_synthetic_fixtures"]

    with pytest.raises(KagglePublicationRightsBlockedError, match="cannot retain files"):
        parse_qualified_rights_disposition(_seal(payload))


def test_assured_material_bytes_changed_after_manifest_are_rejected(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    target = publication_root / "synthetic/provider_exact_stats_bodies.json"
    target.write_bytes(b"attacker changed staged bytes\n")

    with pytest.raises(KagglePublicationRightsBlockedError, match="assured publication artifacts"):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_dataset_metadata_target_and_license_are_reconstructed_not_supplied(
    tmp_path: Path,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    (publication_root / "dataset-metadata.json").write_bytes(
        _canonical_bytes({"id": "attacker/other-dataset", "licenses": [{"name": "OTHER-LICENSE"}]})
    )

    with pytest.raises(KagglePublicationRightsBlockedError, match="Kaggle dataset drifted"):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_terminal_schema_artifact_drift_invalidates_assured_tree(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    (publication_root / "terminal-assurance-report.json").write_bytes(
        _canonical_bytes({"schema_version": 999, "status": "attacker"})
    )

    with pytest.raises(KagglePublicationRightsBlockedError, match="assured publication artifacts"):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_publication_context_path_classification_must_cover_exact_tree(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    context_path = publication_root / QUALIFIED_RIGHTS_PUBLICATION_CONTEXT_NAME
    artifact = json.loads(context_path.read_bytes())
    artifact["material_classifications"].pop()
    context_path.write_bytes(_canonical_bytes(artifact))

    with pytest.raises(KagglePublicationRightsBlockedError, match="assured publication artifacts"):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_symlinked_publication_root_is_rejected(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    symlink = tmp_path / "publication-link"
    symlink.symlink_to(publication_root, target_is_directory=True)

    with pytest.raises(KagglePublicationRightsBlockedError, match="root is invalid"):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=symlink,
        )


def test_trust_store_identity_must_match_qualified_human_reviewer(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)

    def mutate(store: dict[str, Any]) -> None:
        store["signers"][0]["human_name"] = "Different Human"

    with (
        _mutated_pinned_test_trust(tmp_path, payload, mutate),
        pytest.raises(KagglePublicationRightsBlockedError, match="does not match"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_trust_store_signer_qualification_scope_must_cover_every_effective_scope(
    tmp_path: Path,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)

    def mutate(store: dict[str, Any]) -> None:
        store["signers"][0]["qualified_scopes"].remove("exact_response_bodies")

    with (
        _mutated_pinned_test_trust(tmp_path, payload, mutate),
        pytest.raises(KagglePublicationRightsBlockedError, match="qualification scope"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


@pytest.mark.parametrize("revocation_mutation", ["revoked", "stale"])
def test_revoked_or_stale_signer_authority_cannot_admit(
    tmp_path: Path,
    revocation_mutation: str,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)

    def mutate(store: dict[str, Any]) -> None:
        signer = store["signers"][0]
        if revocation_mutation == "revoked":
            signer["revocation_status"] = "revoked"
        else:
            signer["revocation_review_by_utc"] = _timestamp(datetime.now(UTC) - timedelta(days=1))

    with (
        _mutated_pinned_test_trust(tmp_path, payload, mutate),
        pytest.raises(KagglePublicationRightsBlockedError, match="trust store|revocation"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_wrong_pinned_trust_store_digest_is_rejected(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    repository_root = tmp_path / "wrong-pin-repository"
    _write_trust_store(repository_root, payload)
    with (
        patch.object(rights, "_PINNED_QUALIFIED_RIGHTS_TRUST_STORE_SHA256", "f" * 64),
        patch.object(rights, "_default_project_root", return_value=repository_root),
        pytest.raises(KagglePublicationRightsBlockedError, match="repository-pinned exact"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_future_issued_pinned_trust_store_is_rejected(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)

    def mutate(store: dict[str, Any]) -> None:
        store["issued_at_utc"] = _timestamp(datetime.now(UTC) + timedelta(days=1))

    with (
        _mutated_pinned_test_trust(tmp_path, payload, mutate),
        pytest.raises(
            KagglePublicationRightsBlockedError,
            match="trust store is not currently valid",
        ),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_symlinked_pinned_trust_store_is_rejected(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    source_root = tmp_path / "source-trust"
    digest = _write_trust_store(source_root, payload)
    source = source_root / QUALIFIED_RIGHTS_TRUST_STORE_RELATIVE_PATH
    repository_root = tmp_path / "symlink-trust"
    target = repository_root / QUALIFIED_RIGHTS_TRUST_STORE_RELATIVE_PATH
    target.parent.mkdir(parents=True)
    target.symlink_to(source)

    with (
        patch.object(rights, "_PINNED_QUALIFIED_RIGHTS_TRUST_STORE_SHA256", digest),
        patch.object(rights, "_default_project_root", return_value=repository_root),
        pytest.raises(KagglePublicationRightsBlockedError, match="non-symlink"),
    ):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


@pytest.mark.parametrize("state", ["expired", "future"])
def test_expired_or_not_yet_effective_credential_is_rejected(
    tmp_path: Path,
    state: str,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    now = datetime.now(UTC).replace(microsecond=0)
    if state == "expired":
        payload["issued_at_utc"] = _timestamp(now - timedelta(days=3))
        payload["review_by_utc"] = _timestamp(now - timedelta(days=2))
        payload["expires_at_utc"] = _timestamp(now - timedelta(days=1))
        for condition in payload["conditions"]:
            condition["discharged_at_utc"] = _timestamp(now - timedelta(days=4))
    else:
        payload["issued_at_utc"] = _timestamp(now + timedelta(days=1))
        payload["review_by_utc"] = _timestamp(now + timedelta(days=2))
        payload["expires_at_utc"] = _timestamp(now + timedelta(days=3))

    with pytest.raises(KagglePublicationRightsBlockedError, match="not currently valid"):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("reviewer_kind", "ai_system"),
        ("human_name", ""),
        ("qualifications", []),
        ("jurisdictions", []),
        ("is_ai_system", True),
        ("self_attestation_only", True),
    ],
)
def test_unnamed_unqualified_ai_or_self_attesting_reviewer_is_rejected(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["reviewer"][field] = replacement

    with pytest.raises(KagglePublicationRightsBlockedError, match="reviewer"):
        parse_qualified_rights_disposition(_seal(payload))


@pytest.mark.parametrize(
    "missing_scope",
    [
        "commercial_downstream_use",
        "exact_response_bodies",
        "live_near_live_and_archived_play_by_play",
        "public_redistribution",
    ],
)
def test_required_provider_scope_cannot_be_omitted(
    tmp_path: Path,
    missing_scope: str,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["provider_authority"]["covered_scopes"].remove(missing_scope)

    with pytest.raises(KagglePublicationRightsBlockedError, match="authority scope is incomplete"):
        parse_qualified_rights_disposition(_seal(payload))


def test_provider_authority_cannot_claim_unmodeled_overbroad_scope(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["provider_authority"]["covered_scopes"].append("worldwide_sublicense")
    payload["provider_authority"]["covered_scopes"].sort()

    with pytest.raises(KagglePublicationRightsBlockedError, match="unsupported overbroad scope"):
        parse_qualified_rights_disposition(_seal(payload))


def test_privacy_material_coverage_cannot_be_incomplete(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["privacy_disposition"]["reviewed_material_classes"].remove("person_related_fields")

    with pytest.raises(KagglePublicationRightsBlockedError, match="privacy material coverage"):
        parse_qualified_rights_disposition(_seal(payload))


def test_person_related_material_cannot_be_denied_by_privacy_disposition(
    tmp_path: Path,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["privacy_disposition"]["person_related_data_present"] = False

    with pytest.raises(KagglePublicationRightsBlockedError, match="cannot deny present"):
        parse_qualified_rights_disposition(_seal(payload))


@pytest.mark.parametrize("coverage", ["host", "competition"])
def test_provider_host_and_competition_coverage_matches_repository_policy_and_artifacts(
    tmp_path: Path,
    coverage: str,
) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    field = "covered_hosts" if coverage == "host" else "covered_competitions"
    payload["provider_authority"][field].pop()
    new_scopes = _payload_effective_scopes(payload)
    payload["reviewer"]["signed_scope"] = new_scopes
    for evidence in payload["official_source_evidence"]:
        evidence["reviewed_scopes"] = new_scopes
    provider_scopes = sorted(
        {
            *(payload["provider_authority"]["covered_scopes"]),
            *(
                f"provider_material:{value}"
                for value in payload["provider_authority"]["covered_material_classes"]
            ),
            *(f"provider_host:{value}" for value in payload["provider_authority"]["covered_hosts"]),
            *(
                f"provider_competition:{value}"
                for value in payload["provider_authority"]["covered_competitions"]
            ),
        }
    )
    _condition(payload, "condition-provider")["applies_to_scopes"] = provider_scopes
    evidence_by_id = {item["evidence_id"]: item for item in payload["official_source_evidence"]}
    for condition in payload["conditions"]:
        condition["discharge_evidence_sha256"] = _canonical_sha256(
            [evidence_by_id[item] for item in condition["discharge_evidence_ids"]]
        )

    with pytest.raises(KagglePublicationRightsBlockedError, match=f"{coverage} coverage drifted"):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_kaggle_license_relabel_is_not_admitted(tmp_path: Path) -> None:
    publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["kaggle_disposition"]["license_id"] = "OTHER-LICENSE"

    with pytest.raises(KagglePublicationRightsBlockedError):
        verify_qualified_rights_disposition(
            _seal(payload),
            publication_root=publication_root,
        )


def test_official_source_type_inventory_cannot_be_incomplete(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["official_source_evidence"] = [
        item
        for item in payload["official_source_evidence"]
        if item["evidence_id"] != "client-license"
    ]
    _material(payload, "nba_api_client_software")["evidence_ids"] = ["nba-terms"]

    with pytest.raises(KagglePublicationRightsBlockedError, match="evidence types are incomplete"):
        parse_qualified_rights_disposition(_seal(payload))


def test_unresolved_questions_block_qualification(tmp_path: Path) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["unresolved_questions"] = ["Unresolved provider publication authority."]

    with pytest.raises(KagglePublicationRightsBlockedError, match="unresolved questions"):
        parse_qualified_rights_disposition(_seal(payload))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("method", "rsa"),
        ("value_base64", base64.b64encode(b"short").decode()),
    ],
)
def test_unsigned_or_wrong_method_credential_is_rejected(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    payload["signature"][field] = replacement
    encoded = _canonical_bytes(payload) if field == "value_base64" else _seal(payload)

    with pytest.raises(KagglePublicationRightsBlockedError, match="signature"):
        parse_qualified_rights_disposition(encoded)


def test_duplicate_json_keys_are_rejected_before_model_validation() -> None:
    encoded = b'{"schema":"QualifiedRightsDispositionV1","schema":"QualifiedRightsDispositionV1"}'

    with pytest.raises(KagglePublicationRightsBlockedError, match="JSON is invalid"):
        parse_qualified_rights_disposition(encoded)


def test_one_staged_file_cannot_be_classified_as_two_material_classes(
    tmp_path: Path,
) -> None:
    _publication_root, _context, payload = _credential_fixture(tmp_path)
    first_file = payload["material_dispositions"][0]["files"][0]
    payload["material_dispositions"][1]["files"][0] = copy.deepcopy(first_file)

    with pytest.raises(KagglePublicationRightsBlockedError, match="exactly one material class"):
        parse_qualified_rights_disposition(_seal(payload))


def test_reconstructed_expected_context_has_independent_canonical_seal(tmp_path: Path) -> None:
    _publication_root, context, _payload = _credential_fixture(tmp_path)
    dumped = context.model_dump(mode="json", round_trip=True)
    dumped["repository_source_sha"] = "f" * 40

    with pytest.raises(ValueError, match="context seal"):
        QualifiedRightsExpectedContextV1.model_validate(dumped, strict=True)


def test_subject_provider_digest_equals_embedded_canonical_authority(tmp_path: Path) -> None:
    _publication_root, context, payload = _credential_fixture(tmp_path)
    canonical = expected_nba_api_provider_authority()["authority_sha256"]

    assert context.provider_authority_sha256 == canonical
    assert payload["subject"]["provider_authority_sha256"] == canonical
