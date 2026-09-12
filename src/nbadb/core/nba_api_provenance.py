"""Immutable authority checks for the pinned ``nba-api`` provider.

The provider remains an installed dependency, while nbadb independently binds
the exact release, source tree, archive hashes, and license used to generate
its extraction contracts.  The returned attestation contains no local paths.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import nba_api

from nbadb.core.nba_api_surface_inventory import build_distribution_record_authority

NBA_API_DISTRIBUTION = "nba-api"
NBA_API_VERSION = "1.11.4"
NBA_API_UPSTREAM_REPOSITORY = "https://github.com/swar/nba_api"
NBA_API_UPSTREAM_TAG = "v1.11.4"
NBA_API_UPSTREAM_COMMIT = "e0295f8333c3496b5754dbffbdf4c1c1dee3c2f4"
NBA_API_UPSTREAM_TREE = "5d3a8074795f6962f831d3fb69bb0ec18dbd8492"
NBA_API_SDIST_SHA256 = "1dccd70b78f36f64260e1f353c4a02c1644147c4a2a5ce42fbd9f637d70bad3e"
NBA_API_WHEEL_SHA256 = "f489b2a1d67ee4298f5173775b335d0e43e63455ed157a5612b542094b9f1963"
NBA_API_TREE_INVENTORY_SHA256 = "9391ba65b2c77c3cb0b7ba8d638c3c3b65592e8cae723ada31766cdba8274692"
NBA_API_LICENSE_IDENTIFIER = "MIT"
NBA_API_LICENSE_SHA256 = "8177a1a7718444dddfee53e17336b0a44f5a6245caa62645fe17db1524a61cb8"
NBA_API_INVENTORY_FILE_COUNT = 189
NBA_API_RUNTIME_CONTRACT_COUNT = 139
NBA_API_RUNTIME_CONTRACT_SHA256 = "a9838c5464d5410210fc3d5af3d3f75c1a796eb46ff999079749a1a4b77f4309"
NBA_API_LIVE_ENDPOINT_CONTRACT_COUNT = 4
NBA_API_LIVE_RESULT_SET_CONTRACT_COUNT = 33
NBA_API_LIVE_COLUMN_CONTRACT_COUNT = 430
NBA_API_LIVE_PARSED_COLUMN_CONTRACT_COUNT = 431
NBA_API_LIVE_CONTRACT_SHA256 = "18750aec673db6c1a2c7d43b7425ec90b4a354c193491664bf24b34d8cda7543"
NBA_API_STATIC_DATASET_CONTRACT_COUNT = 4
NBA_API_STATIC_MODELED_FIELD_CONTRACT_COUNT = 26
NBA_API_STATIC_CONTRACT_SHA256 = "ccd209d3d89356c9d368b8d45db94cf9c119d1329b2dc4764fbc112a1990caff"
NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256 = (
    "7c9b59c475cff6b0b9d3619bdfe9a3849e11619980f6d15a1cafd5f269f61b3b"
)
NBA_API_UPSTREAM_CONTRACT_BUNDLE_SHA256 = (
    "291fe01a2549d3d55caa864d20bfc2819e64d69a14467b4051827eb4956ce23f"
)
NBA_API_BRONZE_CONTRACT_SHA256 = "436407c5c1fe5765a4052917f182881abc76f5222db444aac57f5cb8d091e118"
NBA_API_METADATA_LEDGER_SHA256 = "e4d1356834f2b68ca7184cca745c72e2fa4c0bc128f28dbeed86e3265a8db2ce"


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _package_root(root: Path) -> Path | None:
    candidates = (root / "src" / "nba_api", root / "nba_api")
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


def _inventory(root: Path) -> tuple[int, str, dict[str, str]]:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".json"} and "__pycache__" not in path.parts
    )
    digests: dict[str, str] = {}
    aggregate = hashlib.sha256()
    for path in files:
        relative = f"nba_api/{path.relative_to(root).as_posix()}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digests[relative] = digest
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
    return len(files), aggregate.hexdigest(), digests


def _locked_archive_hashes(lock_path: Path) -> tuple[str | None, str | None, str | None]:
    try:
        payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None, None, None
    packages = payload.get("package")
    if not isinstance(packages, list):
        return None, None, None
    package = next(
        (
            candidate
            for candidate in packages
            if isinstance(candidate, dict) and candidate.get("name") == NBA_API_DISTRIBUTION
        ),
        None,
    )
    if not isinstance(package, dict):
        return None, None, None
    version = package.get("version")
    sdist = package.get("sdist")
    wheels = package.get("wheels")
    sdist_hash = sdist.get("hash") if isinstance(sdist, dict) else None
    wheel_hashes = (
        [wheel.get("hash") for wheel in wheels if isinstance(wheel, dict)]
        if isinstance(wheels, list)
        else []
    )
    wheel_hash = wheel_hashes[0] if len(wheel_hashes) == 1 else None
    return (
        str(version) if isinstance(version, str) else None,
        str(sdist_hash).removeprefix("sha256:") if isinstance(sdist_hash, str) else None,
        str(wheel_hash).removeprefix("sha256:") if isinstance(wheel_hash, str) else None,
    )


def _attestation_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def expected_nba_api_provider_contract() -> dict[str, Any]:
    """Return the immutable package/source/license identity contract."""

    contract: dict[str, Any] = {
        "schema_version": 1,
        "provider": "nba_api",
        "distribution_name": NBA_API_DISTRIBUTION,
        "distribution_version": NBA_API_VERSION,
        "upstream_repository": NBA_API_UPSTREAM_REPOSITORY,
        "upstream_tag": NBA_API_UPSTREAM_TAG,
        "upstream_commit_sha": NBA_API_UPSTREAM_COMMIT,
        "upstream_tree_sha": NBA_API_UPSTREAM_TREE,
        "sdist_sha256": NBA_API_SDIST_SHA256,
        "wheel_sha256": NBA_API_WHEEL_SHA256,
        "source_inventory_file_count": NBA_API_INVENTORY_FILE_COUNT,
        "source_inventory_sha256": NBA_API_TREE_INVENTORY_SHA256,
        "installed_inventory_sha256": NBA_API_TREE_INVENTORY_SHA256,
        "license_identifier": NBA_API_LICENSE_IDENTIFIER,
        "license_sha256": NBA_API_LICENSE_SHA256,
    }
    contract["attestation_sha256"] = _attestation_digest(contract)
    return contract


def _expected_provider_observation() -> dict[str, Any]:
    return {
        "installed_version": NBA_API_VERSION,
        "lock_version": NBA_API_VERSION,
        "locked_sdist_sha256": NBA_API_SDIST_SHA256,
        "locked_wheel_sha256": NBA_API_WHEEL_SHA256,
        "upstream_commit_sha": NBA_API_UPSTREAM_COMMIT,
        "upstream_tag_commit_sha": NBA_API_UPSTREAM_COMMIT,
        "upstream_tree_sha": NBA_API_UPSTREAM_TREE,
        "upstream_tracked_clean": True,
        "source_inventory_file_count": NBA_API_INVENTORY_FILE_COUNT,
        "source_inventory_sha256": NBA_API_TREE_INVENTORY_SHA256,
        "installed_inventory_file_count": NBA_API_INVENTORY_FILE_COUNT,
        "installed_inventory_sha256": NBA_API_TREE_INVENTORY_SHA256,
        "source_installed_file_parity": True,
        "license_sha256": NBA_API_LICENSE_SHA256,
    }


def _provider_evidence_receipt(observation: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "kind": "nbadb_nba_api_provider_evidence",
        "provider_contract_sha256": expected_nba_api_provider_contract()["attestation_sha256"],
        "observed": observation,
        "verified": not errors,
        "errors": errors,
    }
    receipt["evidence_sha256"] = _attestation_digest(receipt)
    return receipt


def expected_nba_api_provider_evidence_receipt() -> dict[str, Any]:
    """Return the canonical exact observation a verified checkout must produce."""

    return _provider_evidence_receipt(_expected_provider_observation(), [])


def normalize_nba_api_provider_evidence_receipt(raw: Any) -> dict[str, Any]:
    """Validate complete observed evidence instead of trusting a boolean flag."""

    if not isinstance(raw, dict):
        raise ValueError("provider evidence receipt must be an object")
    if set(raw) != {
        "schema_version",
        "kind",
        "provider_contract_sha256",
        "observed",
        "verified",
        "errors",
        "evidence_sha256",
    }:
        raise ValueError("provider evidence receipt fields do not match the schema")
    body = dict(raw)
    digest = body.pop("evidence_sha256")
    if not isinstance(digest, str) or digest != _attestation_digest(body):
        raise ValueError("provider evidence receipt digest is invalid")
    expected = expected_nba_api_provider_evidence_receipt()
    if raw != expected:
        raise ValueError("provider evidence receipt does not prove the exact pinned provider")
    return expected


def expected_nba_api_provider_authority() -> dict[str, Any]:
    """Return the complete provider/contract authority bound to extraction plans."""

    authority: dict[str, Any] = {
        "schema_version": 1,
        "provider_contract": expected_nba_api_provider_contract(),
        "provider_evidence_sha256": expected_nba_api_provider_evidence_receipt()["evidence_sha256"],
        "runtime_endpoint_contract_count": NBA_API_RUNTIME_CONTRACT_COUNT,
        "runtime_endpoint_contract_sha256": NBA_API_RUNTIME_CONTRACT_SHA256,
        "live_endpoint_contract_count": NBA_API_LIVE_ENDPOINT_CONTRACT_COUNT,
        "live_result_set_contract_count": NBA_API_LIVE_RESULT_SET_CONTRACT_COUNT,
        "live_column_contract_count": NBA_API_LIVE_COLUMN_CONTRACT_COUNT,
        "live_parsed_column_contract_count": NBA_API_LIVE_PARSED_COLUMN_CONTRACT_COUNT,
        "live_contract_sha256": NBA_API_LIVE_CONTRACT_SHA256,
        "static_dataset_contract_count": NBA_API_STATIC_DATASET_CONTRACT_COUNT,
        "static_modeled_field_contract_count": NBA_API_STATIC_MODELED_FIELD_CONTRACT_COUNT,
        "static_contract_sha256": NBA_API_STATIC_CONTRACT_SHA256,
        "runtime_contract_payload_sha256": NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
        "docs_tools_bundle_sha256": NBA_API_UPSTREAM_CONTRACT_BUNDLE_SHA256,
        "bronze_contract_sha256": NBA_API_BRONZE_CONTRACT_SHA256,
        "metadata_ledger_sha256": NBA_API_METADATA_LEDGER_SHA256,
    }
    authority["authority_sha256"] = _attestation_digest(authority)
    return authority


def normalize_nba_api_provider_authority(raw: Any) -> dict[str, Any]:
    """Require exact canonical provider authority with no compatibility fallback."""

    if not isinstance(raw, dict):
        raise ValueError("provider_authority must be an object")
    expected = expected_nba_api_provider_authority()
    if raw != expected:
        raise ValueError("provider_authority does not match the exact pinned contract")
    return expected


def validate_nba_api_provider_evidence(
    *,
    provider_provenance: Any,
    runtime_endpoint_contract_count: int,
    runtime_endpoint_contract_sha256: str,
    live_endpoint_contract_count: int,
    live_result_set_contract_count: int,
    live_column_contract_count: int,
    live_parsed_column_contract_count: int,
    live_contract_sha256: str,
    static_dataset_contract_count: int,
    static_modeled_field_contract_count: int,
    static_contract_sha256: str,
    runtime_contract_payload_sha256: str,
    docs_tools_bundle_sha256: Any,
    bronze_contract_sha256: Any,
    metadata_ledger_sha256: Any,
) -> dict[str, Any]:
    """Compare generated evidence with the immutable extraction authority."""

    authority = expected_nba_api_provider_authority()
    provenance_payload = provider_provenance if isinstance(provider_provenance, dict) else {}
    evidence_receipt = provenance_payload.get("evidence_receipt")
    try:
        normalized_evidence = normalize_nba_api_provider_evidence_receipt(evidence_receipt)
    except ValueError:
        normalized_evidence = None
    observed = {
        "provider_contract": provenance_payload.get("contract"),
        "provider_evidence_receipt": evidence_receipt,
        "provider_evidence_sha256": (
            normalized_evidence["evidence_sha256"] if normalized_evidence is not None else None
        ),
        "runtime_endpoint_contract_count": runtime_endpoint_contract_count,
        "runtime_endpoint_contract_sha256": runtime_endpoint_contract_sha256,
        "live_endpoint_contract_count": live_endpoint_contract_count,
        "live_result_set_contract_count": live_result_set_contract_count,
        "live_column_contract_count": live_column_contract_count,
        "live_parsed_column_contract_count": live_parsed_column_contract_count,
        "live_contract_sha256": live_contract_sha256,
        "static_dataset_contract_count": static_dataset_contract_count,
        "static_modeled_field_contract_count": static_modeled_field_contract_count,
        "static_contract_sha256": static_contract_sha256,
        "runtime_contract_payload_sha256": runtime_contract_payload_sha256,
        "docs_tools_bundle_sha256": docs_tools_bundle_sha256,
        "bronze_contract_sha256": bronze_contract_sha256,
        "metadata_ledger_sha256": metadata_ledger_sha256,
    }
    checks = {
        "provider_evidence_receipt_invalid": normalized_evidence is not None,
        "provider_contract_mismatch": (
            observed["provider_contract"] == authority["provider_contract"]
        ),
        "provider_evidence_digest_mismatch": (
            observed["provider_evidence_sha256"] == authority["provider_evidence_sha256"]
        ),
        "runtime_endpoint_contract_count_mismatch": (
            runtime_endpoint_contract_count == authority["runtime_endpoint_contract_count"]
        ),
        "runtime_endpoint_contract_digest_mismatch": (
            runtime_endpoint_contract_sha256 == authority["runtime_endpoint_contract_sha256"]
        ),
        "live_endpoint_contract_count_mismatch": (
            live_endpoint_contract_count == authority["live_endpoint_contract_count"]
        ),
        "live_result_set_contract_count_mismatch": (
            live_result_set_contract_count == authority["live_result_set_contract_count"]
        ),
        "live_column_contract_count_mismatch": (
            live_column_contract_count == authority["live_column_contract_count"]
        ),
        "live_parsed_column_contract_count_mismatch": (
            live_parsed_column_contract_count == authority["live_parsed_column_contract_count"]
        ),
        "live_contract_digest_mismatch": (
            live_contract_sha256 == authority["live_contract_sha256"]
        ),
        "static_dataset_contract_count_mismatch": (
            static_dataset_contract_count == authority["static_dataset_contract_count"]
        ),
        "static_modeled_field_contract_count_mismatch": (
            static_modeled_field_contract_count == authority["static_modeled_field_contract_count"]
        ),
        "static_contract_digest_mismatch": (
            static_contract_sha256 == authority["static_contract_sha256"]
        ),
        "runtime_contract_payload_digest_mismatch": (
            runtime_contract_payload_sha256 == authority["runtime_contract_payload_sha256"]
        ),
        "docs_tools_bundle_digest_mismatch": (
            docs_tools_bundle_sha256 == authority["docs_tools_bundle_sha256"]
        ),
        "bronze_contract_digest_mismatch": (
            bronze_contract_sha256 == authority["bronze_contract_sha256"]
        ),
        "metadata_ledger_digest_mismatch": (
            metadata_ledger_sha256 == authority["metadata_ledger_sha256"]
        ),
    }
    errors = [reason for reason, passed in checks.items() if not passed]
    return {
        "verified": not errors,
        "authority": authority,
        "observed": observed,
        "errors": errors,
    }


def verify_nba_api_provider(
    upstream_root: Path | str | None,
    *,
    project_root: Path | str,
) -> dict[str, Any]:
    """Return a deterministic exact-release attestation and all failures."""

    root = Path(upstream_root) if upstream_root is not None else None
    checkout_package = _package_root(root) if root is not None else None
    installed_package = Path(nba_api.__file__).resolve().parent
    errors: list[str] = []

    installed_version = importlib.metadata.version(NBA_API_DISTRIBUTION)
    try:
        distribution_record_authority = build_distribution_record_authority().to_dict()
    except ValueError:
        distribution_record_authority = None
        errors.append("installed_distribution_record_authority_mismatch")
    lock_version, locked_sdist, locked_wheel = _locked_archive_hashes(
        Path(project_root) / "uv.lock"
    )
    checkout_commit = _git(root, "rev-parse", "HEAD") if root is not None else None
    checkout_tree = _git(root, "rev-parse", "HEAD^{tree}") if root is not None else None
    tag_commit = (
        _git(root, "rev-parse", f"refs/tags/{NBA_API_UPSTREAM_TAG}^{{commit}}")
        if root is not None
        else None
    )
    tracked_status = (
        _git(root, "status", "--porcelain", "--untracked-files=all") if root is not None else None
    )

    installed_count, installed_digest, installed_files = _inventory(installed_package)
    if checkout_package is not None:
        source_count, source_digest, source_files = _inventory(checkout_package)
    else:
        source_count, source_digest, source_files = 0, "", {}
    license_digest = _sha256(root / "LICENSE") if root is not None else None

    checks: tuple[tuple[bool, str], ...] = (
        (root is not None and checkout_package is not None, "upstream_checkout_missing"),
        (installed_version == NBA_API_VERSION, "installed_version_mismatch"),
        (lock_version == NBA_API_VERSION, "lock_version_mismatch"),
        (locked_sdist == NBA_API_SDIST_SHA256, "locked_sdist_hash_mismatch"),
        (locked_wheel == NBA_API_WHEEL_SHA256, "locked_wheel_hash_mismatch"),
        (checkout_commit == NBA_API_UPSTREAM_COMMIT, "upstream_commit_mismatch"),
        (tag_commit == NBA_API_UPSTREAM_COMMIT, "upstream_tag_target_mismatch"),
        (checkout_tree == NBA_API_UPSTREAM_TREE, "upstream_tree_mismatch"),
        (tracked_status == "", "upstream_checkout_tracked_dirty"),
        (source_count == NBA_API_INVENTORY_FILE_COUNT, "source_inventory_count_mismatch"),
        (installed_count == NBA_API_INVENTORY_FILE_COUNT, "installed_inventory_count_mismatch"),
        (source_digest == NBA_API_TREE_INVENTORY_SHA256, "source_inventory_digest_mismatch"),
        (
            installed_digest == NBA_API_TREE_INVENTORY_SHA256,
            "installed_inventory_digest_mismatch",
        ),
        (source_files == installed_files, "installed_source_file_parity_mismatch"),
        (license_digest == NBA_API_LICENSE_SHA256, "upstream_license_digest_mismatch"),
    )
    errors.extend(reason for passed, reason in checks if not passed)

    contract = expected_nba_api_provider_contract()
    observation = {
        "installed_version": installed_version,
        "lock_version": lock_version,
        "locked_sdist_sha256": locked_sdist,
        "locked_wheel_sha256": locked_wheel,
        "upstream_commit_sha": checkout_commit,
        "upstream_tag_commit_sha": tag_commit,
        "upstream_tree_sha": checkout_tree,
        "upstream_tracked_clean": tracked_status == "",
        "source_inventory_file_count": source_count,
        "source_inventory_sha256": source_digest or None,
        "installed_inventory_file_count": installed_count,
        "installed_inventory_sha256": installed_digest,
        "source_installed_file_parity": source_files == installed_files,
        "license_sha256": license_digest,
    }
    return {
        "enabled": root is not None,
        "verified": not errors,
        "contract": contract,
        "observed": observation,
        "evidence_receipt": _provider_evidence_receipt(observation, errors),
        "distribution_record_authority": distribution_record_authority,
        "errors": errors,
    }
