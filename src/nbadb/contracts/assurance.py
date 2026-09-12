"""Atomic, exact-source pre-extraction contract assurance.

This module compiles the already implemented provider, bronze, silver, gold,
temporal, and metric contracts into one fresh generation.  It deliberately
keeps structural generation separate from the local ``MODEL-GREEN`` decision
and never treats this local evidence as populated-data assurance.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from nbadb.contracts.assurance_admission import (
    AssuranceAdmission,
    AssuranceAdmissionError,
    AuthorityUpdateMode,
    ModelStatus,
)

if TYPE_CHECKING:
    from nbadb.contracts.field_fate_contract import FieldFateContractBundle
    from nbadb.contracts.star_table_contract import StarModelContractInventory


class ContractAssuranceError(RuntimeError):
    """The atomic contract-assurance generation could not be proven."""


PROFILE_PRE_EXTRACTION: Final = "pre-extraction"
MANIFEST_NAME: Final = "assurance-manifest.json"
ADMISSION_NAME: Final = "assurance-admission.json"
GENERATION_INDEX_NAME: Final = "assurance-generation-index.json"
GENERATION_CONTEXT_NAME: Final = "generation-context.json"
PROVIDER_EVIDENCE_NAME: Final = "provider-evidence.json"
UPSTREAM_CONTRACT_NAME: Final = "endpoint-contract-bundle.json"
RUNTIME_CONTRACT_NAME: Final = "provider-runtime-contract.json"
IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME: Final = (
    "implicit-competition-current-source-authority.json"
)
TERMINAL_STATE_NAME: Final = "terminal-state-contract.json"
PROVIDER_SURFACE_NAME: Final = "provider-surface-inventory.json"
BRONZE_CONTRACT_NAME: Final = "bronze-contract.json"
FIXTURE_MANIFEST_NAME: Final = "fixture-manifest.json"
RAW_REQUEST_SCHEMA_NAME: Final = "raw-request-schema-contract.json"
STAGING_ROUTE_NAME: Final = "staging-route-contract.json"
STAR_TABLE_NAME: Final = "star-table-contract.json"
FIELD_FATE_STRUCTURE_NAME: Final = "field-fate-structure.json"
FIELD_FATE_STRUCTURE_VERIFICATION_NAME: Final = "field-fate-structure-verification.json"
ANALYTICAL_NEEDS_NAME: Final = "analytical-needs-authority.json"
MODEL_CANDIDATE_CENSUS_NAME: Final = "model-candidate-census.json"
STABLE_MODEL_DISPOSITION_NAME: Final = "stable-model-disposition.json"
STAR_SEMANTIC_INVENTORY_NAME: Final = "star-semantic-inventory.json"
FIELD_FATE_NAME: Final = "field-fate-contract.json"
TEMPORAL_NAME: Final = "temporal-availability-contract.json"
METRIC_NAME: Final = "metric-use-case-contract.json"
AUTHORITY_SEMANTIC_DIFF_NAME: Final = "authority-semantic-diff.json"

CHILD_NAMES: Final = (
    GENERATION_CONTEXT_NAME,
    PROVIDER_EVIDENCE_NAME,
    UPSTREAM_CONTRACT_NAME,
    RUNTIME_CONTRACT_NAME,
    IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME,
    TERMINAL_STATE_NAME,
    PROVIDER_SURFACE_NAME,
    BRONZE_CONTRACT_NAME,
    FIXTURE_MANIFEST_NAME,
    RAW_REQUEST_SCHEMA_NAME,
    STAGING_ROUTE_NAME,
    STAR_TABLE_NAME,
    FIELD_FATE_STRUCTURE_NAME,
    FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
    ANALYTICAL_NEEDS_NAME,
    MODEL_CANDIDATE_CENSUS_NAME,
    STABLE_MODEL_DISPOSITION_NAME,
    STAR_SEMANTIC_INVENTORY_NAME,
    FIELD_FATE_NAME,
    TEMPORAL_NAME,
    METRIC_NAME,
)
_PERSISTED_MODEL_AUTHORITY_NAMES: Final = (
    FIELD_FATE_STRUCTURE_NAME,
    FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
    ANALYTICAL_NEEDS_NAME,
    MODEL_CANDIDATE_CENSUS_NAME,
    STABLE_MODEL_DISPOSITION_NAME,
    STAR_SEMANTIC_INVENTORY_NAME,
)
CONTENT_REQUIRED_MEMBERS: Final = (*CHILD_NAMES, MANIFEST_NAME)
ROOT_CONTENT_REQUIRED_MEMBERS: Final = (
    *CONTENT_REQUIRED_MEMBERS,
    AUTHORITY_SEMANTIC_DIFF_NAME,
)
REQUIRED_MEMBERS: Final = (
    *ROOT_CONTENT_REQUIRED_MEMBERS,
    ADMISSION_NAME,
    GENERATION_INDEX_NAME,
)

_TOOL_DISTRIBUTIONS: Final = (
    "nba-api",
    "nbadb",
    "duckdb",
    "pandera",
    "polars",
    "sqlglot",
)
_SOURCE_ROOTS: Final = (
    Path("src/nbadb"),
    Path("tests/fixtures/nba_api_contract"),
)
_SOURCE_FILES: Final = (Path("pyproject.toml"), Path("uv.lock"))
_SHA256_LENGTH: Final = 64
_MAX_ASSURANCE_MEMBER_BYTES: Final = 64 * 1024 * 1024
_TERMINAL_POLICY_SHA256: Final = "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
_TERMINAL_PAYLOAD_SHA256: Final = "471f594174107ccb8f582a6ab0459a356acf9daebd75ac55464475b3df792f4d"
_REQUEST_SURFACE_SHA256: Final = "ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733"
_REQUEST_PAYLOAD_SHA256: Final = "b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052"
_COMPETITION_IDENTITY_AUTHORITY_SHA256: Final = (
    "dcbb1b9a9855b6d241651556f62911028d37b7a3678d0def9ae2a2a0779f8689"
)
_COMPETITION_IDENTITY_PAYLOAD_SHA256: Final = (
    "1420e8592f51ccdb03a6449dbd9514f87ad192ad4c14c6c7536844f85a0e3378"
)
_TERMINAL_PARENT_BINDINGS: Final = {
    "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
    "request_surface_sha256": _REQUEST_SURFACE_SHA256,
    "request_surface_payload_sha256": _REQUEST_PAYLOAD_SHA256,
    "competition_identity_authority_sha256": _COMPETITION_IDENTITY_AUTHORITY_SHA256,
    "competition_identity_payload_sha256": _COMPETITION_IDENTITY_PAYLOAD_SHA256,
}


@dataclass(frozen=True, slots=True)
class AssuranceGeneration:
    """One fully written and independently revalidated generation."""

    directory: Path
    manifest: dict[str, Any]
    admission: AssuranceAdmission
    generation_index: dict[str, Any]
    generation_index_sha256: str

    @property
    def semantic_sha256(self) -> str:
        value = self.manifest["generation_semantic_sha256"]
        if not isinstance(value, str):
            raise ContractAssuranceError("assurance semantic digest is invalid")
        return value

    @property
    def model_green(self) -> bool:
        gate_results = self.manifest["gate_results"]
        return bool(gate_results["model_green"])

    @property
    def admission_sha256(self) -> str:
        """Exact canonical digest of ``assurance-admission.json``."""

        return self.admission.sha256

    @property
    def admission_status(self) -> str:
        """Exact MODEL status carried by the observed admission."""

        return self.admission.model_status


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
        raise ContractAssuranceError(
            f"assurance payload is not canonical JSON: {type(exc).__name__}"
        ) from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_git_commit_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _object(value: object, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ContractAssuranceError(f"{context} must be a JSON object")
    return cast("dict[str, Any]", value)


def _array(value: object, *, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractAssuranceError(f"{context} must be a JSON array")
    return value


def _json_safe(value: object, *, context: str) -> object:
    """Serialize immutable contract dataclasses without private indexes."""

    from dataclasses import fields, is_dataclass

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractAssuranceError(f"{context} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractAssuranceError(f"{context} contains a non-string key")
            result[key] = _json_safe(item, context=f"{context}.{key}")
        return result
    if isinstance(value, list | tuple):
        return [_json_safe(item, context=f"{context}[{index}]") for index, item in enumerate(value)]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_safe(
                getattr(value, field.name),
                context=f"{context}.{field.name}",
            )
            for field in fields(value)
            if not field.name.startswith("_")
        }
    raise ContractAssuranceError(f"{context} contains unsupported type {type(value).__name__}")


def _run_git(project_root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", os.fspath(project_root), *args],
            check=False,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractAssuranceError(f"cannot freeze git context: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        raise ContractAssuranceError("cannot freeze git context: git command failed")
    return completed.stdout


def _source_inventory(project_root: Path) -> dict[str, object]:
    paths: list[Path] = []
    for relative_root in _SOURCE_ROOTS:
        root = project_root / relative_root
        if not root.is_dir() or root.is_symlink():
            raise ContractAssuranceError(
                f"required assurance source root is unavailable: {relative_root.as_posix()}"
            )
        paths.extend(
            path
            for path in root.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )
    for relative_path in _SOURCE_FILES:
        path = project_root / relative_path
        if not path.is_file() or path.is_symlink():
            raise ContractAssuranceError(
                f"required assurance source file is unavailable: {relative_path.as_posix()}"
            )
        paths.append(path)

    inventory: list[dict[str, object]] = []
    for path in sorted(set(paths), key=lambda item: item.relative_to(project_root).as_posix()):
        data = path.read_bytes()
        inventory.append(
            {
                "path": path.relative_to(project_root).as_posix(),
                "size": len(data),
                "sha256": _sha256_bytes(data),
            }
        )
    return {
        "file_count": len(inventory),
        "source_sha256": _sha256_json(inventory),
    }


def _dirty_inventory(project_root: Path) -> dict[str, object]:
    pathspec = [
        *(path.as_posix() for path in _SOURCE_ROOTS),
        *(path.as_posix() for path in _SOURCE_FILES),
    ]
    raw = _run_git(
        project_root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        *pathspec,
    )
    return {
        "path_record_count": len([item for item in raw.split(b"\0") if item]),
        "dirty_sha256": _sha256_bytes(raw),
    }


def _tool_context() -> dict[str, object]:
    distributions: dict[str, str] = {}
    for name in _TOOL_DISTRIBUTIONS:
        try:
            distributions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ContractAssuranceError(f"required generation tool is missing: {name}") from exc
    return {
        "python_implementation": sys.implementation.name,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "distributions": distributions,
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _freeze_generation_context(
    *,
    project_root: Path,
    endpoint_analysis_docs_root: Path,
    observed_at: str | None = None,
) -> dict[str, Any]:
    from nbadb.core.nba_api_provenance import (
        expected_nba_api_provider_authority,
        normalize_nba_api_provider_evidence_receipt,
        verify_nba_api_provider,
    )

    root = project_root.resolve()
    upstream_root = endpoint_analysis_docs_root.resolve()
    head = _run_git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if not _is_git_commit_sha(head):
        raise ContractAssuranceError("project HEAD is not a complete commit SHA")
    provider = verify_nba_api_provider(upstream_root, project_root=root)
    if provider.get("verified") is not True:
        errors = provider.get("errors")
        codes = ",".join(str(item) for item in errors) if isinstance(errors, list) else "invalid"
        raise ContractAssuranceError(f"exact provider verification failed: {codes}")
    try:
        evidence = normalize_nba_api_provider_evidence_receipt(provider.get("evidence_receipt"))
    except ValueError as exc:
        raise ContractAssuranceError("exact provider receipt validation failed") from exc

    semantic = {
        "schema_version": 1,
        "kind": "nbadb_contract_assurance_generation_context",
        "profile": PROFILE_PRE_EXTRACTION,
        "project": {
            "git_head_sha": head,
            **_source_inventory(root),
            **_dirty_inventory(root),
        },
        "provider": {
            "authority": expected_nba_api_provider_authority(),
            "evidence_receipt": evidence,
        },
        "tools": _tool_context(),
        "commands": {
            "generate": [
                "nbadb",
                "contract-assurance",
                "--profile",
                PROFILE_PRE_EXTRACTION,
                "--endpoint-analysis-docs-root",
                "<local-exact-nba-api-checkout>",
            ],
            "check": [
                "nbadb",
                "contract-assurance",
                "--profile",
                PROFILE_PRE_EXTRACTION,
                "--endpoint-analysis-docs-root",
                "<local-exact-nba-api-checkout>",
                "--check",
            ],
        },
    }
    return {
        "semantic": semantic,
        "observation": {
            "observed_at": observed_at or _utc_now(),
            "project_location": "local_project_root",
            "provider_location": "local_exact_provider_checkout",
        },
    }


def _fixture_manifest(project_root: Path) -> dict[str, Any]:
    from nbadb.core.nba_api_provenance import (
        NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
        NBA_API_UPSTREAM_TAG,
        NBA_API_VERSION,
    )

    fixture_root = project_root / "tests" / "fixtures" / "nba_api_contract"
    manifest_path = fixture_root / "manifest.json"
    try:
        manifest = _object(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            context="fixture manifest",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractAssuranceError("fixture manifest is unavailable or invalid") from exc
    body = dict(manifest)
    digest = body.pop("manifest_sha256", None)
    if not _is_sha256(digest) or digest != _sha256_json(body):
        raise ContractAssuranceError("fixture manifest digest is invalid")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "nbadb_nba_api_exact_release_fixture_manifest"
    ):
        raise ContractAssuranceError("fixture manifest identity is invalid")
    if manifest.get("provider") != {
        "distribution_version": NBA_API_VERSION,
        "runtime_contract_payload_sha256": NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
        "upstream_tag": NBA_API_UPSTREAM_TAG,
    }:
        raise ContractAssuranceError("fixture manifest provider parent is invalid")
    _validate_fixture_policy_payload(manifest)
    entries = _array(manifest.get("entries"), context="fixture manifest entries")
    if manifest.get("entries_sha256") != _sha256_json(entries):
        raise ContractAssuranceError("fixture entry inventory digest is invalid")
    ids = [item.get("id") for item in entries if isinstance(item, dict)]
    if len(ids) != len(entries) or ids != sorted(ids) or len(set(ids)) != len(ids):
        raise ContractAssuranceError("fixture entry identities are invalid")

    declared: set[str] = set()
    resolved_fixture_root = fixture_root.resolve()
    for raw_entry in entries:
        entry = _object(raw_entry, context="fixture entry")
        relative = entry.get("relative_path")
        if not isinstance(relative, str) or not relative:
            raise ContractAssuranceError("fixture entry path is invalid")
        path = project_root / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(resolved_fixture_root)
        ):
            raise ContractAssuranceError("fixture entry escapes its exact fixture root")
        payload_sha256 = _sha256_bytes(path.read_bytes())
        if (
            entry.get("source_path") != f"repo-authored:{relative}"
            or entry.get("source_sha256") != payload_sha256
            or entry.get("payload_sha256") != payload_sha256
            or entry.get("rights_policy_id") != "repo-synthetic-mit"
            or entry.get("sanitization_policy_id") != "synthetic-none"
        ):
            raise ContractAssuranceError("fixture entry content binding is invalid")
        declared.add(relative)
    observed = {
        path.relative_to(project_root).as_posix()
        for path in fixture_root.iterdir()
        if path.name != manifest_path.name
    }
    if declared != observed:
        raise ContractAssuranceError("fixture directory membership differs from its manifest")
    return manifest


def _validate_fixture_policy_payload(manifest: Mapping[str, Any]) -> None:
    expected_manifest_fields = {
        "entries",
        "entries_sha256",
        "kind",
        "manifest_sha256",
        "provider",
        "rights_policies",
        "sanitization_policies",
        "schema_version",
    }
    if set(manifest) != expected_manifest_fields:
        raise ContractAssuranceError("fixture manifest fields do not match the schema")
    if manifest.get("rights_policies") != {
        "repo-synthetic-mit": {
            "copied_nba_response_data": False,
            "copied_upstream_code": False,
            "copied_upstream_docs": False,
            "data_class": "repository_authored_synthetic_non_nba",
            "license_identifier": "MIT",
        }
    }:
        raise ContractAssuranceError("fixture rights policy contract is invalid")
    if manifest.get("sanitization_policies") != {
        "synthetic-none": "not_applicable_repo_authored_synthetic"
    }:
        raise ContractAssuranceError("fixture sanitization policy contract is invalid")
    expected_entry_fields = {
        "endpoint_contract_sha256",
        "endpoint_id",
        "fixture_kind",
        "id",
        "oracle",
        "payload_sha256",
        "relative_path",
        "rights_policy_id",
        "sanitization_policy_id",
        "source_path",
        "source_sha256",
    }
    entries = _array(manifest.get("entries"), context="fixture manifest entries")
    for raw_entry in entries:
        entry = _object(raw_entry, context="fixture entry")
        if set(entry) != expected_entry_fields:
            raise ContractAssuranceError("fixture entry fields do not match the schema")
        if (
            entry.get("rights_policy_id") != "repo-synthetic-mit"
            or entry.get("sanitization_policy_id") != "synthetic-none"
        ):
            raise ContractAssuranceError("fixture entry policy reference is invalid")


def _field_fate_payload(bundle: FieldFateContractBundle) -> dict[str, Any]:
    from nbadb.contracts import field_fate_contract as field_module

    summary = {
        "provider_field_occurrence_count": bundle.provider_field_occurrence_count,
        "top_level_provider_field_occurrence_count": (
            bundle.top_level_provider_field_occurrence_count
        ),
        "nested_projection_occurrence_count": bundle.nested_projection_occurrence_count,
        "unique_provider_field_identity_count": bundle.unique_provider_field_identity_count,
        "repeated_route_occurrence_count": bundle.repeated_route_occurrence_count,
        "storage_mapped_occurrence_count": bundle.storage_mapped_occurrence_count,
        "storage_unmapped_occurrence_count": bundle.storage_unmapped_occurrence_count,
        "storage_only_sink_occurrence_count": len(bundle.storage_only_sinks),
        "zero_field_route_count": len(bundle.zero_field_routes),
        "unresolved_provider_field_occurrence_count": (
            bundle.unresolved_provider_field_occurrence_count
        ),
        "source_family_counts": dict(bundle.source_family_counts),
        "mapping_transform_counts": dict(bundle.mapping_transform_counts),
        "storage_tier_counts": dict(bundle.storage_tier_counts),
        "candidate_evidence_summary": [
            {
                "kind": item.kind,
                "field_occurrence_count": item.field_occurrence_count,
                "target_count": item.target_count,
            }
            for item in bundle.candidate_evidence_summary
        ],
        "blocker_summary": [
            {
                "scope": item.scope,
                "code": item.code,
                "occurrence_count": item.occurrence_count,
            }
            for item in bundle.blocker_summary
        ],
        "model_green": bundle.model_green,
    }
    payload = field_module._bundle_payload(  # noqa: SLF001
        fields=bundle.fields,
        storage_only_sinks=bundle.storage_only_sinks,
        zero_field_routes=bundle.zero_field_routes,
        staging_route_contract_sha256=bundle.staging_route_contract_sha256,
        star_table_contract_sha256=bundle.star_table_contract_sha256,
        provider_authority_sha256=bundle.provider_authority_sha256,
        summary=summary,
    )
    result = dict(payload)
    result["digest"] = bundle.digest
    return result


def _star_table_payload(inventory: StarModelContractInventory) -> dict[str, Any]:
    from nbadb.contracts import star_table_contract as star_module

    tables: list[dict[str, object]] = []
    for table in inventory.tables:
        payload = star_module._table_payload(  # noqa: SLF001
            output_name=table.output_name,
            family=table.family,
            purpose=table.purpose,
            schema_class=table.schema_class,
            schema_module=table.schema_module,
            columns=table.columns,
            schema_sha256=table.schema_sha256,
            foreign_keys=table.foreign_keys,
            transform=table.transform,
            consumer_metadata=table.consumer_metadata,
            grain=table.grain,
            key_policy=table.key_policy,
            semantic_policies=table.semantic_policies,
            blockers=table.blockers,
            model_green=table.model_green,
        )
        tables.append({**payload, "contract_sha256": table.contract_sha256})
    return {
        "schema_version": 1,
        "kind": "nbadb_star_table_contract_inventory",
        "digest": inventory.contract_sha256,
        "model_green": inventory.model_green,
        "summary": {
            "table_count": len(inventory.tables),
            "family_counts": _json_safe(
                inventory.family_counts,
                context="star family counts",
            ),
            "blocker_summary": [
                _json_safe(item, context="star blocker") for item in inventory.blocker_summary
            ],
        },
        "tables": tables,
    }


def _verified_terminal_state_child(
    *,
    terminal_payload: Mapping[str, Any] | None = None,
    request_payload: Mapping[str, Any] | None = None,
    identity_payload: Mapping[str, Any] | None = None,
    provider_surface: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Reproduce the terminal child and its exact current successor bindings."""

    from nbadb.core.nba_api_competition_identity import (
        load_pinned_competition_identity_payload,
    )
    from nbadb.core.nba_api_competition_identity_verifier import (
        verify_pinned_competition_identity_authority,
    )
    from nbadb.core.nba_api_request_surface import (
        load_pinned_request_surface_payload,
        pinned_request_surface_authority,
    )
    from nbadb.core.nba_api_request_surface_verifier import (
        build_independent_package_inventory,
    )
    from nbadb.core.nba_api_surface_inventory import build_nba_api_surface_inventory
    from nbadb.core.nba_api_terminal_state import load_pinned_terminal_state_payload
    from nbadb.core.nba_api_terminal_state_verifier import (
        verify_pinned_terminal_state_authority,
    )

    checked_terminal = dict(load_pinned_terminal_state_payload())
    checked_request = dict(load_pinned_request_surface_payload())
    checked_identity = dict(load_pinned_competition_identity_payload())
    terminal = dict(checked_terminal if terminal_payload is None else terminal_payload)
    request = dict(checked_request if request_payload is None else request_payload)
    identity = dict(checked_identity if identity_payload is None else identity_payload)
    surface = dict(
        build_nba_api_surface_inventory() if provider_surface is None else provider_surface
    )
    terminal_proof = verify_pinned_terminal_state_authority()
    request_authority = pinned_request_surface_authority()
    request_inventory = build_independent_package_inventory()
    identity_proof = verify_pinned_competition_identity_authority()

    parent_bindings = {
        "terminal_policy_sha256": terminal.get("terminal_policy_sha256"),
        "request_surface_sha256": request.get("surface_sha256"),
        "request_surface_payload_sha256": request.get("payload_sha256"),
        "competition_identity_authority_sha256": identity.get("authority_sha256"),
        "competition_identity_payload_sha256": identity.get("payload_sha256"),
    }
    if parent_bindings != _TERMINAL_PARENT_BINDINGS:
        raise ContractAssuranceError("terminal successor parent authorities drifted")
    if (
        terminal != checked_terminal
        or terminal.get("payload_sha256") != _TERMINAL_PAYLOAD_SHA256
        or terminal_proof.verifier_id != "nbadb_independent_terminal_state_v1"
        or terminal_proof.terminal_policy_sha256 != _TERMINAL_POLICY_SHA256
        or terminal_proof.checked_payload_sha256 != _TERMINAL_PAYLOAD_SHA256
    ):
        raise ContractAssuranceError("terminal-state independent authority drifted")
    if (
        request != checked_request
        or request_authority.surface_sha256 != _REQUEST_SURFACE_SHA256
        or request_authority.terminal_policy_sha256 != _TERMINAL_POLICY_SHA256
        or surface.get("request_surface_sha256") != _REQUEST_SURFACE_SHA256
        or surface.get("independent_package_inventory") != asdict(request_inventory)
    ):
        raise ContractAssuranceError("request-surface independent inventory drifted")
    if (
        identity != checked_identity
        or identity_proof.verifier_id != "nbadb_independent_competition_identity_v2"
        or identity_proof.terminal_policy_sha256 != _TERMINAL_POLICY_SHA256
        or identity_proof.request_surface_sha256 != _REQUEST_SURFACE_SHA256
        or identity_proof.candidate_authority_sha256 != _COMPETITION_IDENTITY_AUTHORITY_SHA256
        or identity_proof.candidate_payload_sha256 != _COMPETITION_IDENTITY_PAYLOAD_SHA256
        or identity_proof.identity_requirement_count != 815
        or identity_proof.qualified_surface_contract_count != 8
        or identity_proof.finding_count != 0
        or identity_proof.findings
    ):
        raise ContractAssuranceError("competition-identity independent authority drifted")

    source_authorities = _object(
        identity.get("source_authorities"),
        context="competition identity source authorities",
    )
    if set(source_authorities) != {
        "competition",
        "competition_applicability",
        "identity_contract",
        "implicit_competition",
        "implicit_supersession_proof",
        "request_surface",
        "task_packet",
        "terminal_state",
    }:
        raise ContractAssuranceError("competition identity source authority membership drifted")
    if _object(
        source_authorities.get("terminal_state"),
        context="competition identity terminal source",
    ) != {
        "path": "src/nbadb/contracts/nba_api_terminal_state_v1_11_4.json",
        "resource_sha256": ("9389644949a92046ce3e00491842c3786812cfe043d727dbbdc6b0c84d2ab867"),
        "payload_sha256": _TERMINAL_PAYLOAD_SHA256,
        "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
    }:
        raise ContractAssuranceError("competition identity terminal source binding drifted")
    if _object(
        source_authorities.get("request_surface"),
        context="competition identity request source",
    ) != {
        "path": "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
        "resource_sha256": ("3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981"),
        "payload_sha256": _REQUEST_PAYLOAD_SHA256,
        "surface_sha256": _REQUEST_SURFACE_SHA256,
        "runtime_contract_payload_sha256": (
            "7c9b59c475cff6b0b9d3619bdfe9a3849e11619980f6d15a1cafd5f269f61b3b"
        ),
        "terminal_policy_sha256": _TERMINAL_POLICY_SHA256,
    }:
        raise ContractAssuranceError("competition identity request source binding drifted")
    return checked_terminal, dict(_TERMINAL_PARENT_BINDINGS)


def _verified_implicit_competition_current_source_child(
    *,
    source_payload: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Authenticate the packaged current-source authority and its live source bytes."""

    from nbadb.contracts.implicit_competition_source_authority_loader import (
        ImplicitCompetitionSourceAuthorityLoadError,
        load_implicit_competition_current_source_authority,
    )
    from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority

    try:
        authority = load_implicit_competition_current_source_authority()
    except ImplicitCompetitionSourceAuthorityLoadError as exc:
        raise ContractAssuranceError(
            "implicit-competition current-source authority cannot be authenticated"
        ) from exc
    checked = cast("dict[str, Any]", authority.to_dict())
    observed = checked if source_payload is None else dict(source_payload)
    if observed != checked:
        raise ContractAssuranceError(
            "implicit-competition current-source child differs from the authenticated authority"
        )
    generation_proof = _object(
        checked.get("generation_proof"),
        context="implicit-competition current-source generation proof",
    )
    candidate = _object(
        generation_proof.get("candidate"),
        context="implicit-competition current-source candidate",
    )
    review = _object(
        checked.get("review"),
        context="implicit-competition current-source review",
    )
    provider_authority_sha256 = candidate.get("provider_authority_sha256")
    if provider_authority_sha256 != expected_nba_api_provider_authority()["authority_sha256"]:
        raise ContractAssuranceError(
            "implicit-competition current-source provider authority drifted"
        )
    bindings = {
        "provider_authority_sha256": str(provider_authority_sha256),
        "predecessor_receipt_sha256": str(candidate["predecessor_receipt_sha256"]),
        "source_inventory_sha256": str(candidate["source_inventory_sha256"]),
        "generation_proof_sha256": str(generation_proof["proof_sha256"]),
        "review_receipt_sha256": str(review["receipt_sha256"]),
    }
    if any(not _is_sha256(value) for value in bindings.values()):
        raise ContractAssuranceError(
            "implicit-competition current-source parent binding is invalid"
        )
    return checked, bindings


def _compile_profile_children(
    *,
    project_root: Path,
    endpoint_analysis_docs_root: Path,
    generation_context: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    from nbadb.contracts.field_fate_contract import compile_field_fate_contracts
    from nbadb.contracts.field_fate_structure import compile_field_fate_structure
    from nbadb.contracts.field_fate_structure_verifier import (
        verify_field_fate_structure_independently,
    )
    from nbadb.contracts.metric_use_case_contract import metric_use_case_registry
    from nbadb.contracts.model_candidate_census import (
        canonical_analytical_needs_authority_v1,
        compile_model_candidate_census,
    )
    from nbadb.contracts.raw_request_schema_contract import (
        compile_raw_request_schema_contract,
    )
    from nbadb.contracts.stable_model_disposition import (
        compile_stable_model_disposition_inventory,
        draft_required_model_dispositions,
    )
    from nbadb.contracts.staging_route_contract import (
        staging_route_contract_bundle,
        validate_staging_route_contract_bundle,
    )
    from nbadb.contracts.star_semantic_inventory import (
        compile_star_semantic_inventory,
    )
    from nbadb.contracts.star_table_contract import compile_star_table_contracts
    from nbadb.contracts.temporal_availability_contract import (
        temporal_availability_contract_bundle,
        validate_temporal_availability_contract_bundle,
    )
    from nbadb.core.nba_api_contract import (
        build_nba_api_bronze_contracts_from_bundle,
        build_nba_api_upstream_contract_bundle,
        discover_runtime_endpoint_contracts,
    )
    from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
    from nbadb.core.nba_api_runtime_contract import (
        build_pinned_runtime_contract_payload,
        load_pinned_runtime_contract_payload,
    )
    from nbadb.core.nba_api_surface_inventory import build_nba_api_surface_inventory

    # A check is two actual compiler passes, not two serializations of ambient
    # process caches.  Clear every profile-level cached compiler input before
    # freezing this pass's child set.
    discover_runtime_endpoint_contracts.cache_clear()
    staging_route_contract_bundle.cache_clear()
    temporal_availability_contract_bundle.cache_clear()
    metric_use_case_registry.cache_clear()

    semantic_context = _object(
        generation_context.get("semantic"),
        context="generation semantic context",
    )
    provider_context = _object(
        semantic_context.get("provider"),
        context="generation provider context",
    )
    evidence = _object(
        provider_context.get("evidence_receipt"),
        context="generation provider evidence",
    )
    authority = expected_nba_api_provider_authority()
    if provider_context.get("authority") != authority:
        raise ContractAssuranceError("generation provider authority drifted")

    upstream = build_nba_api_upstream_contract_bundle(
        endpoint_analysis_docs_root,
        project_root=project_root,
    )
    upstream_provider = _object(
        upstream.get("provider_provenance"),
        context="upstream provider provenance",
    )
    if upstream_provider.get("evidence_receipt") != evidence:
        raise ContractAssuranceError("upstream bundle provider receipt drifted")
    if upstream.get("bundle_digest") != authority["docs_tools_bundle_sha256"]:
        raise ContractAssuranceError("endpoint docs/tools bundle disagrees with authority")

    bronze = build_nba_api_bronze_contracts_from_bundle(upstream)
    if (
        bronze.get("source_bundle_digest") != upstream.get("bundle_digest")
        or bronze.get("bronze_contract_digest") != authority["bronze_contract_sha256"]
    ):
        raise ContractAssuranceError("bronze contract parent or digest is invalid")

    runtime = build_pinned_runtime_contract_payload(endpoint_analysis_docs_root)
    if runtime != load_pinned_runtime_contract_payload():
        raise ContractAssuranceError("fresh runtime contract differs from pinned authority")
    if runtime.get("payload_sha256") != authority["runtime_contract_payload_sha256"]:
        raise ContractAssuranceError("runtime contract digest disagrees with authority")

    provider_surface = build_nba_api_surface_inventory()
    current_source, _current_source_parents = _verified_implicit_competition_current_source_child()
    terminal, _terminal_parents = _verified_terminal_state_child(
        provider_surface=provider_surface,
    )
    route = staging_route_contract_bundle()
    validate_staging_route_contract_bundle(route)
    star = compile_star_table_contracts()
    field_structure = compile_field_fate_structure(endpoint_analysis_docs_root)
    field_structure_verification = verify_field_fate_structure_independently(
        field_structure,
        endpoint_analysis_docs_root,
    )
    analytical_needs = canonical_analytical_needs_authority_v1()
    model_candidate_census = compile_model_candidate_census(
        field_structure=field_structure,
        star_inventory=star,
        analytical_needs=analytical_needs,
        route_bundle=route,
    )
    stable_model_disposition = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=(
            model_candidate_census.candidate_source_authority_sha256
        ),
        candidates=model_candidate_census.to_stable_candidates(),
        dispositions=draft_required_model_dispositions(
            candidate_source_authority_sha256=(
                model_candidate_census.candidate_source_authority_sha256
            ),
            candidates=model_candidate_census.to_stable_candidates(),
        ),
        review_receipts=(),
    )
    star_semantic_inventory = compile_star_semantic_inventory(
        structural_inventory=star,
        stable_disposition_inventory=stable_model_disposition,
        semantic_contracts=(),
        review_receipts=(),
    )
    field = compile_field_fate_contracts()
    temporal = temporal_availability_contract_bundle()
    validate_temporal_availability_contract_bundle(temporal)
    metric = metric_use_case_registry()
    raw_request_schema = compile_raw_request_schema_contract()

    if (
        route.provider_authority_sha256 != authority["authority_sha256"]
        or route.pinned_contract_payload_sha256 != runtime["payload_sha256"]
    ):
        raise ContractAssuranceError("staging-route provider parent is invalid")
    if (
        field.staging_route_contract_sha256 != route.digest
        or field.star_table_contract_sha256 != star.contract_sha256
        or field.provider_authority_sha256 != authority["authority_sha256"]
    ):
        raise ContractAssuranceError("field-fate parent digest is invalid")
    if (
        field_structure.route_bindings.staging_route_contract_sha256 != route.digest
        or field_structure_verification.structure_sha256 != field_structure.identity_sha256
        or field_structure_verification.staging_route_contract_sha256 != route.digest
        or field_structure_verification.authority_mode != "exact_checkout"
        or field_structure_verification.open_blocker_count != 0
        or not field_structure_verification.verified_against_current_authorities
    ):
        raise ContractAssuranceError("field-fate structure or independent verification is invalid")
    if (
        model_candidate_census.field_fate_structure_sha256 != field_structure.identity_sha256
        or model_candidate_census.staging_route_contract_sha256 != route.digest
        or model_candidate_census.star_model_contract_sha256 != star.contract_sha256
        or model_candidate_census.analytical_needs_authority_sha256
        != analytical_needs.authority_sha256
        or stable_model_disposition.candidate_source_authority_sha256
        != model_candidate_census.candidate_source_authority_sha256
        or stable_model_disposition.candidates != model_candidate_census.candidates
        or star_semantic_inventory.structural_inventory_sha256 != star.contract_sha256
        or star_semantic_inventory.stable_inventory_sha256
        != stable_model_disposition.inventory_sha256
    ):
        raise ContractAssuranceError("model-candidate or disposition parent digest is invalid")
    if temporal.staging_route_contract_sha256 != route.digest:
        raise ContractAssuranceError("temporal parent digest is invalid")
    if metric.star_contract_sha256 != star.contract_sha256:
        raise ContractAssuranceError("metric parent digest is invalid")

    return {
        PROVIDER_EVIDENCE_NAME: evidence,
        UPSTREAM_CONTRACT_NAME: _redact_upstream_locations(upstream),
        RUNTIME_CONTRACT_NAME: runtime,
        IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME: current_source,
        TERMINAL_STATE_NAME: terminal,
        PROVIDER_SURFACE_NAME: provider_surface,
        BRONZE_CONTRACT_NAME: bronze,
        FIXTURE_MANIFEST_NAME: _fixture_manifest(project_root),
        RAW_REQUEST_SCHEMA_NAME: raw_request_schema.to_dict(),
        STAGING_ROUTE_NAME: route.to_dict(),
        STAR_TABLE_NAME: _star_table_payload(star),
        FIELD_FATE_STRUCTURE_NAME: field_structure.to_dict(),
        FIELD_FATE_STRUCTURE_VERIFICATION_NAME: field_structure_verification.to_dict(),
        ANALYTICAL_NEEDS_NAME: analytical_needs.to_dict(),
        MODEL_CANDIDATE_CENSUS_NAME: model_candidate_census.to_dict(),
        STABLE_MODEL_DISPOSITION_NAME: stable_model_disposition.to_dict(),
        STAR_SEMANTIC_INVENTORY_NAME: star_semantic_inventory.to_dict(),
        FIELD_FATE_NAME: _field_fate_payload(field),
        TEMPORAL_NAME: temporal.to_dict(),
        METRIC_NAME: metric.to_dict(),
    }


def _resolve_persisted_validation_roots(
    *,
    project_root: Path | str | None,
    endpoint_analysis_docs_root: Path | str | None,
) -> tuple[Path, Path]:
    project = (Path(project_root) if project_root is not None else Path.cwd()).resolve()
    if endpoint_analysis_docs_root is not None:
        return project, Path(endpoint_analysis_docs_root).resolve()

    configured_roots = {
        Path(value).resolve()
        for variable in ("NBADB_NBA_API_DOCS_ROOT", "ENDPOINT_ANALYSIS_DOCS_ROOT")
        if (value := os.environ.get(variable))
    }
    if not configured_roots:
        raise ContractAssuranceError(
            "persisted assurance validation requires the exact nba_api checkout root"
        )
    if len(configured_roots) != 1:
        raise ContractAssuranceError(
            "persisted assurance validation has conflicting nba_api checkout roots"
        )
    return project, configured_roots.pop()


def _recompile_persisted_model_authorities(
    *,
    endpoint_analysis_docs_root: Path,
) -> dict[str, dict[str, Any]]:
    """Rebuild model denominators without trusting their persisted projections."""

    from nbadb.contracts import field_fate_structure as field_structure_module
    from nbadb.contracts import (
        field_fate_structure_verifier as field_structure_verifier_module,
    )
    from nbadb.contracts.model_candidate_census import (
        canonical_analytical_needs_authority_v1,
        compile_model_candidate_census,
    )
    from nbadb.contracts.stable_model_disposition import (
        compile_stable_model_disposition_inventory,
        draft_required_model_dispositions,
    )
    from nbadb.contracts.staging_route_contract import (
        staging_route_contract_bundle,
        validate_staging_route_contract_bundle,
    )
    from nbadb.contracts.star_semantic_inventory import (
        compile_star_semantic_inventory,
    )
    from nbadb.contracts.star_table_contract import compile_star_table_contracts

    # A persisted readback must be a new authority pass.  In particular, it may
    # not accept objects retained by the generation compiler's process caches.
    field_structure_module._compile_field_fate_structure.cache_clear()  # noqa: SLF001
    field_structure_verifier_module._expected_current_rows.cache_clear()  # noqa: SLF001
    staging_route_contract_bundle.cache_clear()

    route = staging_route_contract_bundle()
    validate_staging_route_contract_bundle(route)
    star = compile_star_table_contracts()
    field_structure = field_structure_module.compile_field_fate_structure(
        endpoint_analysis_docs_root
    )
    field_structure_verification = (
        field_structure_verifier_module.verify_field_fate_structure_independently(
            field_structure,
            endpoint_analysis_docs_root,
        )
    )
    analytical_needs = canonical_analytical_needs_authority_v1()
    census = compile_model_candidate_census(
        field_structure=field_structure,
        star_inventory=star,
        analytical_needs=analytical_needs,
        route_bundle=route,
    )
    dispositions = draft_required_model_dispositions(
        candidate_source_authority_sha256=census.candidate_source_authority_sha256,
        candidates=census.to_stable_candidates(),
    )
    stable_inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=census.candidate_source_authority_sha256,
        candidates=census.to_stable_candidates(),
        dispositions=dispositions,
        review_receipts=(),
    )
    star_semantic_inventory = compile_star_semantic_inventory(
        structural_inventory=star,
        stable_disposition_inventory=stable_inventory,
        semantic_contracts=(),
        review_receipts=(),
    )
    return {
        FIELD_FATE_STRUCTURE_NAME: field_structure.to_dict(),
        FIELD_FATE_STRUCTURE_VERIFICATION_NAME: field_structure_verification.to_dict(),
        ANALYTICAL_NEEDS_NAME: analytical_needs.to_dict(),
        MODEL_CANDIDATE_CENSUS_NAME: census.to_dict(),
        STABLE_MODEL_DISPOSITION_NAME: stable_inventory.to_dict(),
        STAR_SEMANTIC_INVENTORY_NAME: star_semantic_inventory.to_dict(),
    }


def _validate_persisted_model_authorities(
    children: Mapping[str, Mapping[str, Any]],
    generation_context: Mapping[str, Any],
    *,
    project_root: Path | str | None,
    endpoint_analysis_docs_root: Path | str | None,
) -> None:
    project, upstream = _resolve_persisted_validation_roots(
        project_root=project_root,
        endpoint_analysis_docs_root=endpoint_analysis_docs_root,
    )
    current_context = _freeze_generation_context(
        project_root=project,
        endpoint_analysis_docs_root=upstream,
    )
    _assert_same_frozen_context(generation_context, current_context)
    try:
        expected = _recompile_persisted_model_authorities(
            endpoint_analysis_docs_root=upstream,
        )
    except (RuntimeError, ValueError) as exc:
        if isinstance(exc, ContractAssuranceError):
            raise
        raise ContractAssuranceError(
            "persisted model authorities cannot be independently recompiled"
        ) from exc
    after_context = _freeze_generation_context(
        project_root=project,
        endpoint_analysis_docs_root=upstream,
    )
    _assert_same_frozen_context(current_context, after_context)
    if set(expected) != set(_PERSISTED_MODEL_AUTHORITY_NAMES):
        raise ContractAssuranceError(
            "persisted model authority recompile returned an incomplete denominator"
        )
    for name in _PERSISTED_MODEL_AUTHORITY_NAMES:
        if children.get(name) != expected[name]:
            raise ContractAssuranceError(
                f"persisted assurance child differs from current authority: {name}"
            )


def _upstream_semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    semantic = dict(payload)
    semantic.pop("docs_root", None)
    metadata = semantic.get("metadata_ledger")
    if isinstance(metadata, dict):
        semantic["metadata_ledger"] = {
            key: value for key, value in metadata.items() if key != "docs_root"
        }
    return semantic


def _redact_upstream_locations(payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    if redacted.get("docs_root") is not None:
        redacted["docs_root"] = "<local-exact-nba-api-checkout>"
    metadata = redacted.get("metadata_ledger")
    if isinstance(metadata, dict):
        redacted["metadata_ledger"] = dict(metadata)
        if redacted["metadata_ledger"].get("docs_root") is not None:
            redacted["metadata_ledger"]["docs_root"] = "<local-exact-nba-api-checkout>"
    return redacted


def _validate_generation_context_payload(payload: Mapping[str, Any]) -> None:
    from nbadb.core.nba_api_provenance import (
        expected_nba_api_provider_authority,
        normalize_nba_api_provider_evidence_receipt,
    )

    if set(payload) != {"semantic", "observation"}:
        raise ContractAssuranceError("generation context fields do not match the schema")
    semantic = _object(payload.get("semantic"), context="generation context")
    if set(semantic) != {
        "schema_version",
        "kind",
        "profile",
        "project",
        "provider",
        "tools",
        "commands",
    }:
        raise ContractAssuranceError("generation semantic fields do not match the schema")
    if (
        semantic.get("schema_version") != 1
        or semantic.get("kind") != "nbadb_contract_assurance_generation_context"
        or semantic.get("profile") != PROFILE_PRE_EXTRACTION
    ):
        raise ContractAssuranceError("generation context identity is invalid")
    project = _object(semantic.get("project"), context="generation project context")
    if set(project) != {
        "git_head_sha",
        "file_count",
        "source_sha256",
        "path_record_count",
        "dirty_sha256",
    }:
        raise ContractAssuranceError("generation project fields do not match the schema")
    if not _is_git_commit_sha(project.get("git_head_sha")):
        raise ContractAssuranceError("generation project HEAD is not an exact Git SHA-1")
    if (
        isinstance(project.get("file_count"), bool)
        or not isinstance(project.get("file_count"), int)
        or project["file_count"] <= 0
        or isinstance(project.get("path_record_count"), bool)
        or not isinstance(project.get("path_record_count"), int)
        or project["path_record_count"] < 0
        or not _is_sha256(project.get("source_sha256"))
        or not _is_sha256(project.get("dirty_sha256"))
    ):
        raise ContractAssuranceError("generation project digests or counts are invalid")
    provider = _object(semantic.get("provider"), context="generation provider context")
    if set(provider) != {"authority", "evidence_receipt"}:
        raise ContractAssuranceError("generation provider fields do not match the schema")
    if provider.get("authority") != expected_nba_api_provider_authority():
        raise ContractAssuranceError("generation provider authority is invalid")
    try:
        normalize_nba_api_provider_evidence_receipt(provider.get("evidence_receipt"))
    except ValueError as exc:
        raise ContractAssuranceError("generation provider evidence is invalid") from exc
    _object(semantic.get("tools"), context="generation tool context")
    _object(semantic.get("commands"), context="generation command context")
    observation = _object(payload.get("observation"), context="generation observation")
    if set(observation) != {"observed_at", "project_location", "provider_location"}:
        raise ContractAssuranceError("generation observation fields do not match the schema")
    if (
        not isinstance(observation.get("observed_at"), str)
        or observation.get("project_location") != "local_project_root"
        or observation.get("provider_location") != "local_exact_provider_checkout"
    ):
        raise ContractAssuranceError("generation observation contains an invalid location")


def _validate_embedded_contract(name: str, payload: dict[str, Any]) -> None:
    from nbadb.core.nba_api_provenance import (
        NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
        NBA_API_UPSTREAM_TAG,
        NBA_API_VERSION,
        expected_nba_api_provider_authority,
        normalize_nba_api_provider_evidence_receipt,
    )

    authority = expected_nba_api_provider_authority()
    if name == GENERATION_CONTEXT_NAME:
        _validate_generation_context_payload(payload)
        return
    if name == PROVIDER_EVIDENCE_NAME:
        try:
            normalize_nba_api_provider_evidence_receipt(payload)
        except ValueError as exc:
            raise ContractAssuranceError("provider evidence child is invalid") from exc
        return
    if name == UPSTREAM_CONTRACT_NAME:
        body = _upstream_semantic_payload(payload)
        digest = body.pop("bundle_digest", None)
        if (
            not _is_sha256(digest)
            or digest != _sha256_json(body)
            or digest != authority["docs_tools_bundle_sha256"]
        ):
            raise ContractAssuranceError("endpoint contract bundle digest is invalid")
        return
    if name == RUNTIME_CONTRACT_NAME:
        body = dict(payload)
        digest = body.pop("payload_sha256", None)
        if (
            not _is_sha256(digest)
            or digest != _sha256_json(body)
            or digest != authority["runtime_contract_payload_sha256"]
        ):
            raise ContractAssuranceError("runtime contract child digest is invalid")
        return
    if name == IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME:
        expected, _parents = _verified_implicit_competition_current_source_child(
            source_payload=payload,
        )
        if payload != expected:
            raise ContractAssuranceError("implicit-competition current-source child is invalid")
        return
    if name == TERMINAL_STATE_NAME:
        expected, _parents = _verified_terminal_state_child(terminal_payload=payload)
        body = dict(payload)
        digest = body.pop("payload_sha256", None)
        if not _is_sha256(digest) or digest != _sha256_json(body):
            raise ContractAssuranceError("terminal-state child digest is invalid")
        if payload != expected:
            raise ContractAssuranceError(
                "terminal-state child differs from the exact checked authority"
            )
        return
    if name == PROVIDER_SURFACE_NAME:
        from nbadb.core.nba_api_surface_inventory import build_nba_api_surface_inventory

        body = dict(payload)
        digest = body.pop("inventory_sha256", None)
        if not _is_sha256(digest) or digest != _sha256_json(body):
            raise ContractAssuranceError("provider surface inventory digest is invalid")
        try:
            expected = build_nba_api_surface_inventory()
        except ValueError as exc:
            raise ContractAssuranceError(
                "provider surface inventory cannot be independently rebuilt"
            ) from exc
        if payload != expected:
            raise ContractAssuranceError(
                "provider surface inventory differs from the exact installed source"
            )
        return
    if name == BRONZE_CONTRACT_NAME:
        body = dict(payload)
        digest = body.pop("bronze_contract_digest", None)
        body.pop("source_bundle_digest", None)
        if (
            not _is_sha256(digest)
            or digest != _sha256_json(body)
            or digest != authority["bronze_contract_sha256"]
        ):
            raise ContractAssuranceError("bronze contract child digest is invalid")
        return
    if name == FIXTURE_MANIFEST_NAME:
        _validate_fixture_policy_payload(payload)
        if (
            payload.get("schema_version") != 1
            or payload.get("kind") != "nbadb_nba_api_exact_release_fixture_manifest"
            or payload.get("provider")
            != {
                "distribution_version": NBA_API_VERSION,
                "runtime_contract_payload_sha256": (NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256),
                "upstream_tag": NBA_API_UPSTREAM_TAG,
            }
        ):
            raise ContractAssuranceError("fixture child identity is invalid")
        body = dict(payload)
        digest = body.pop("manifest_sha256", None)
        if not _is_sha256(digest) or digest != _sha256_json(body):
            raise ContractAssuranceError("fixture child digest is invalid")
        return
    if name == RAW_REQUEST_SCHEMA_NAME:
        from nbadb.contracts.raw_request_schema_contract import (
            RawRequestSchemaContractError,
            RawRequestSchemaContractV2,
            compile_raw_request_schema_contract,
        )

        try:
            parsed = RawRequestSchemaContractV2.from_dict(payload)
            expected = compile_raw_request_schema_contract()
        except RawRequestSchemaContractError as exc:
            raise ContractAssuranceError("raw-request schema child is invalid") from exc
        if parsed != expected or payload != expected.to_dict():
            raise ContractAssuranceError(
                "raw-request schema child differs from the exact public schema"
            )
        return
    if name == FIELD_FATE_STRUCTURE_NAME:
        if payload.get("schema_version") != 3 or payload.get("kind") != "field_fate_structure":
            raise ContractAssuranceError("field-fate structure child identity is invalid")
        provider_sources = _object(
            payload.get("provider_sources"),
            context="field-fate provider sources",
        )
        route_bindings = _object(
            payload.get("route_bindings"),
            context="field-fate route bindings",
        )
        storage_sinks = _object(
            payload.get("storage_sinks"),
            context="field-fate storage sinks",
        )
        if (
            payload.get("provider_sources_sha256") != _sha256_json(provider_sources)
            or payload.get("route_bindings_sha256") != _sha256_json(route_bindings)
            or payload.get("storage_sinks_sha256") != _sha256_json(storage_sinks)
            or payload.get("lossless_bindings_sha256")
            != _sha256_json(
                _array(
                    payload.get("lossless_bindings"),
                    context="field-fate lossless bindings",
                )
            )
            or payload.get("blockers_sha256")
            != _sha256_json(
                _array(payload.get("blockers"), context="field-fate structure blockers")
            )
        ):
            raise ContractAssuranceError("field-fate structure child digest is invalid")
        return
    if name == FIELD_FATE_STRUCTURE_VERIFICATION_NAME:
        from nbadb.contracts.field_fate_structure_verifier import (
            FieldFateStructureVerificationError,
            parse_field_fate_structure_verification,
        )

        try:
            receipt = parse_field_fate_structure_verification(_canonical_bytes(payload) + b"\n")
        except FieldFateStructureVerificationError as exc:
            raise ContractAssuranceError(
                "field-fate structure verification child is invalid"
            ) from exc
        if (
            receipt.authority_mode != "exact_checkout"
            or receipt.open_blocker_count != 0
            or not receipt.verified_against_current_authorities
        ):
            raise ContractAssuranceError(
                "field-fate structure verification is not exact-checkout green"
            )
        return
    if name == ANALYTICAL_NEEDS_NAME:
        from nbadb.contracts.model_candidate_census import (
            AnalyticalNeedsAuthorityV1,
            ModelCandidateCensusError,
            canonical_analytical_needs_authority_v1,
        )

        try:
            parsed_needs = AnalyticalNeedsAuthorityV1.from_dict(payload)
        except ModelCandidateCensusError as exc:
            raise ContractAssuranceError("analytical-needs child is invalid") from exc
        expected_needs = canonical_analytical_needs_authority_v1()
        if parsed_needs != expected_needs or payload != expected_needs.to_dict():
            raise ContractAssuranceError(
                "analytical-needs child differs from the canonical authority"
            )
        return
    if name == MODEL_CANDIDATE_CENSUS_NAME:
        from nbadb.contracts.model_candidate_census import (
            ModelCandidateCensusError,
            ModelCandidateCensusV1,
        )

        try:
            census = ModelCandidateCensusV1.from_dict(payload)
        except ModelCandidateCensusError as exc:
            raise ContractAssuranceError("model-candidate census child is invalid") from exc
        if census.to_dict() != payload:
            raise ContractAssuranceError("model-candidate census child is noncanonical")
        return
    if name == STABLE_MODEL_DISPOSITION_NAME:
        from nbadb.contracts.stable_model_disposition import (
            StableModelDispositionError,
            StableModelDispositionInventoryV1,
        )

        try:
            disposition = StableModelDispositionInventoryV1.from_dict(payload)
        except StableModelDispositionError as exc:
            raise ContractAssuranceError("stable-model disposition child is invalid") from exc
        if disposition.to_dict() != payload:
            raise ContractAssuranceError("stable-model disposition child is noncanonical")
        return
    if name == STAR_SEMANTIC_INVENTORY_NAME:
        from nbadb.contracts.star_semantic_inventory import (
            StarSemanticInventoryError,
            StarSemanticInventoryV1,
        )

        try:
            semantic_inventory = StarSemanticInventoryV1.from_dict(payload)
        except StarSemanticInventoryError as exc:
            raise ContractAssuranceError("star semantic inventory child is invalid") from exc
        if semantic_inventory.to_dict() != payload:
            raise ContractAssuranceError("star semantic inventory child is noncanonical")
        return
    if name == STAGING_ROUTE_NAME:
        expected = {
            "schema_version": payload.get("schema_version"),
            "kind": payload.get("kind"),
            "provider_authority_sha256": payload.get("provider_authority_sha256"),
            "pinned_contract_payload_sha256": payload.get("pinned_contract_payload_sha256"),
            "routes": payload.get("routes"),
        }
        if payload.get("digest") != _sha256_json(expected):
            raise ContractAssuranceError("staging-route child digest is invalid")
        return
    if name == FIELD_FATE_NAME:
        body = dict(payload)
        digest = body.pop("digest", None)
        if not _is_sha256(digest) or digest != _sha256_json(body):
            raise ContractAssuranceError("field-fate child digest is invalid")
        return
    if name == STAR_TABLE_NAME:
        tables = _array(payload.get("tables"), context="star tables")
        for raw_table in tables:
            table = _object(raw_table, context="star table")
            body = dict(table)
            digest = body.pop("contract_sha256", None)
            if not _is_sha256(digest) or digest != _sha256_json(body):
                raise ContractAssuranceError("star table contract digest is invalid")
        summary = _object(payload.get("summary"), context="star summary")
        expected = {
            "tables": [
                {
                    "output_name": table.get("output_name"),
                    "contract_sha256": table.get("contract_sha256"),
                }
                for table in tables
            ],
            "family_counts": summary.get("family_counts"),
            "blocker_summary": summary.get("blocker_summary"),
            "model_green": payload.get("model_green"),
        }
        if payload.get("digest") != _sha256_json(expected):
            raise ContractAssuranceError("star inventory digest is invalid")
        return
    if name == TEMPORAL_NAME:
        expected = {
            "schema_version": payload.get("schema_version"),
            "kind": payload.get("kind"),
            "staging_route_contract_sha256": payload.get("staging_route_contract_sha256"),
            "source_rules": payload.get("source_rules"),
            "scopes": payload.get("scopes"),
        }
        if payload.get("digest") != _sha256_json(expected):
            raise ContractAssuranceError("temporal child digest is invalid")
        return
    if name == METRIC_NAME:
        metrics = _array(payload.get("metrics"), context="metric contracts")
        for raw_metric in metrics:
            metric = _object(raw_metric, context="metric contract")
            metric_body = dict(metric)
            metric_sha = metric_body.pop("contract_sha256", None)
            if not _is_sha256(metric_sha) or metric_sha != _sha256_json(metric_body):
                raise ContractAssuranceError("metric contract digest is invalid")
        summary = _object(payload.get("summary"), context="metric summary")
        expected = {
            "schema_version": payload.get("schema_version"),
            "kind": payload.get("kind"),
            "star_contract_sha256": payload.get("star_contract_sha256"),
            "kind_counts": sorted(
                _object(summary.get("kind_counts"), context="metric kind counts").items()
            ),
            "expression_counts": sorted(
                _object(
                    summary.get("expression_counts"),
                    context="metric expression counts",
                ).items()
            ),
            "blocker_counts": sorted(
                _object(
                    summary.get("blocker_counts"),
                    context="metric blocker counts",
                ).items()
            ),
            "metrics": [
                {
                    "metric_id": _object(item, context="metric contract").get("metric_id"),
                    "contract_sha256": _object(
                        item,
                        context="metric contract",
                    ).get("contract_sha256"),
                }
                for item in metrics
            ],
        }
        if payload.get("digest") != _sha256_json(expected):
            raise ContractAssuranceError("metric child digest is invalid")
        return
    raise ContractAssuranceError(f"unknown assurance child: {name}")


def _child_semantic_sha256(name: str, payload: dict[str, Any]) -> str:
    _validate_embedded_contract(name, payload)
    if name == GENERATION_CONTEXT_NAME:
        return _sha256_json(payload["semantic"])
    if name == UPSTREAM_CONTRACT_NAME:
        return _sha256_json(_upstream_semantic_payload(payload))
    return _sha256_json(payload)


def _contract_digest(name: str, payload: Mapping[str, Any]) -> str:
    if name in {
        FIELD_FATE_STRUCTURE_NAME,
        FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
    }:
        return _sha256_json(payload)
    field = {
        PROVIDER_EVIDENCE_NAME: "evidence_sha256",
        UPSTREAM_CONTRACT_NAME: "bundle_digest",
        RUNTIME_CONTRACT_NAME: "payload_sha256",
        IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME: "authority_sha256",
        TERMINAL_STATE_NAME: "payload_sha256",
        PROVIDER_SURFACE_NAME: "inventory_sha256",
        BRONZE_CONTRACT_NAME: "bronze_contract_digest",
        FIXTURE_MANIFEST_NAME: "manifest_sha256",
        RAW_REQUEST_SCHEMA_NAME: "contract_sha256",
        STAGING_ROUTE_NAME: "digest",
        STAR_TABLE_NAME: "digest",
        ANALYTICAL_NEEDS_NAME: "authority_sha256",
        MODEL_CANDIDATE_CENSUS_NAME: "census_sha256",
        STABLE_MODEL_DISPOSITION_NAME: "inventory_sha256",
        STAR_SEMANTIC_INVENTORY_NAME: "inventory_sha256",
        FIELD_FATE_NAME: "digest",
        TEMPORAL_NAME: "digest",
        METRIC_NAME: "digest",
    }.get(name)
    if field is None:
        raise ContractAssuranceError(f"child has no contract digest: {name}")
    value = payload.get(field)
    if not isinstance(value, str) or not _is_sha256(value):
        raise ContractAssuranceError(f"child contract digest is invalid: {name}")
    return value


def _parent_digests(
    name: str,
    payload: Mapping[str, Any],
    *,
    generation_context_sha256: str,
    children: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    parents = {"generation_context_sha256": generation_context_sha256}
    if name == GENERATION_CONTEXT_NAME:
        return {}
    if name == PROVIDER_EVIDENCE_NAME:
        parents["provider_contract_sha256"] = str(payload["provider_contract_sha256"])
    elif name == UPSTREAM_CONTRACT_NAME:
        provenance = _object(payload.get("provider_provenance"), context="upstream provenance")
        receipt = _object(
            provenance.get("evidence_receipt"),
            context="upstream provider receipt",
        )
        parents["provider_evidence_sha256"] = str(receipt["evidence_sha256"])
    elif name == RUNTIME_CONTRACT_NAME:
        parents["provider_evidence_sha256"] = _contract_digest(
            PROVIDER_EVIDENCE_NAME,
            children[PROVIDER_EVIDENCE_NAME],
        )
    elif name == IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME:
        _current_source, current_source_parents = (
            _verified_implicit_competition_current_source_child(
                source_payload=payload,
            )
        )
        parents.update(current_source_parents)
    elif name == TERMINAL_STATE_NAME:
        _terminal, terminal_parents = _verified_terminal_state_child(
            terminal_payload=payload,
        )
        parents.update(terminal_parents)
    elif name == PROVIDER_SURFACE_NAME:
        parents["provider_evidence_sha256"] = _contract_digest(
            PROVIDER_EVIDENCE_NAME,
            children[PROVIDER_EVIDENCE_NAME],
        )
        parents["runtime_contract_sha256"] = str(payload["runtime_contract_payload_sha256"])
        parents["request_surface_sha256"] = str(payload["request_surface_sha256"])
    elif name == BRONZE_CONTRACT_NAME:
        parents["source_bundle_sha256"] = str(payload["source_bundle_digest"])
    elif name == FIXTURE_MANIFEST_NAME:
        provider = _object(payload.get("provider"), context="fixture provider")
        parents["runtime_contract_sha256"] = str(provider["runtime_contract_payload_sha256"])
    elif name == RAW_REQUEST_SCHEMA_NAME:
        pass
    elif name == STAGING_ROUTE_NAME:
        parents["provider_authority_sha256"] = str(payload["provider_authority_sha256"])
        parents["runtime_contract_sha256"] = str(payload["pinned_contract_payload_sha256"])
    elif name == STAR_TABLE_NAME:
        pass
    elif name == FIELD_FATE_STRUCTURE_NAME:
        provider_sources = _object(
            payload.get("provider_sources"),
            context="field-fate provider sources",
        )
        route_bindings = _object(
            payload.get("route_bindings"),
            context="field-fate route bindings",
        )
        parents["runtime_contract_sha256"] = str(
            provider_sources["pinned_runtime_contract_payload_sha256"]
        )
        parents["staging_route_contract_sha256"] = str(
            route_bindings["staging_route_contract_sha256"]
        )
        parents["upstream_contract_sha256"] = _contract_digest(
            UPSTREAM_CONTRACT_NAME,
            children[UPSTREAM_CONTRACT_NAME],
        )
    elif name == FIELD_FATE_STRUCTURE_VERIFICATION_NAME:
        parents["field_fate_structure_sha256"] = str(payload["structure_sha256"])
        parents["staging_route_contract_sha256"] = str(payload["staging_route_contract_sha256"])
    elif name == ANALYTICAL_NEEDS_NAME:
        pass
    elif name == MODEL_CANDIDATE_CENSUS_NAME:
        parents["field_fate_structure_sha256"] = str(payload["field_fate_structure_sha256"])
        parents["staging_route_contract_sha256"] = str(payload["staging_route_contract_sha256"])
        parents["star_table_contract_sha256"] = str(payload["star_model_contract_sha256"])
        parents["analytical_needs_authority_sha256"] = str(
            payload["analytical_needs_authority_sha256"]
        )
    elif name == STABLE_MODEL_DISPOSITION_NAME:
        parents["candidate_source_authority_sha256"] = str(
            payload["candidate_source_authority_sha256"]
        )
        parents["model_candidate_census_sha256"] = _contract_digest(
            MODEL_CANDIDATE_CENSUS_NAME,
            children[MODEL_CANDIDATE_CENSUS_NAME],
        )
    elif name == STAR_SEMANTIC_INVENTORY_NAME:
        parents["star_table_contract_sha256"] = str(payload["structural_inventory_sha256"])
        parents["stable_model_disposition_sha256"] = str(payload["stable_inventory_sha256"])
    elif name == FIELD_FATE_NAME:
        parents["provider_authority_sha256"] = str(payload["provider_authority_sha256"])
        parents["staging_route_contract_sha256"] = str(payload["staging_route_contract_sha256"])
        parents["star_table_contract_sha256"] = str(payload["star_table_contract_sha256"])
    elif name == TEMPORAL_NAME:
        parents["staging_route_contract_sha256"] = str(payload["staging_route_contract_sha256"])
    elif name == METRIC_NAME:
        parents["star_table_contract_sha256"] = str(payload["star_contract_sha256"])
    else:
        raise ContractAssuranceError(f"unknown assurance child: {name}")
    return parents


def _validate_parent_graph(
    children: Mapping[str, Mapping[str, Any]],
    *,
    generation_context_sha256: str,
) -> dict[str, dict[str, str]]:
    from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
    from nbadb.core.nba_api_request_surface import pinned_request_surface_authority

    if set(children) != set(CHILD_NAMES):
        raise ContractAssuranceError("compiled assurance child membership is invalid")
    parents = {
        name: _parent_digests(
            name,
            children[name],
            generation_context_sha256=generation_context_sha256,
            children=children,
        )
        for name in CHILD_NAMES
    }
    authority = expected_nba_api_provider_authority()
    evidence_sha = _contract_digest(
        PROVIDER_EVIDENCE_NAME,
        children[PROVIDER_EVIDENCE_NAME],
    )
    upstream_sha = _contract_digest(
        UPSTREAM_CONTRACT_NAME,
        children[UPSTREAM_CONTRACT_NAME],
    )
    runtime_sha = _contract_digest(
        RUNTIME_CONTRACT_NAME,
        children[RUNTIME_CONTRACT_NAME],
    )
    _current_source, current_source_parents = _verified_implicit_competition_current_source_child(
        source_payload=children[IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME],
    )
    request_surface_sha = pinned_request_surface_authority().surface_sha256
    route_sha = _contract_digest(STAGING_ROUTE_NAME, children[STAGING_ROUTE_NAME])
    star_sha = _contract_digest(STAR_TABLE_NAME, children[STAR_TABLE_NAME])
    structure_sha = _contract_digest(
        FIELD_FATE_STRUCTURE_NAME,
        children[FIELD_FATE_STRUCTURE_NAME],
    )
    analytical_needs_sha = _contract_digest(
        ANALYTICAL_NEEDS_NAME,
        children[ANALYTICAL_NEEDS_NAME],
    )
    census = children[MODEL_CANDIDATE_CENSUS_NAME]
    expected_edges = {
        (UPSTREAM_CONTRACT_NAME, "provider_evidence_sha256"): evidence_sha,
        (RUNTIME_CONTRACT_NAME, "provider_evidence_sha256"): evidence_sha,
        (TERMINAL_STATE_NAME, "terminal_policy_sha256"): _TERMINAL_POLICY_SHA256,
        (TERMINAL_STATE_NAME, "request_surface_sha256"): _REQUEST_SURFACE_SHA256,
        (TERMINAL_STATE_NAME, "request_surface_payload_sha256"): _REQUEST_PAYLOAD_SHA256,
        (
            TERMINAL_STATE_NAME,
            "competition_identity_authority_sha256",
        ): _COMPETITION_IDENTITY_AUTHORITY_SHA256,
        (
            TERMINAL_STATE_NAME,
            "competition_identity_payload_sha256",
        ): _COMPETITION_IDENTITY_PAYLOAD_SHA256,
        (PROVIDER_SURFACE_NAME, "provider_evidence_sha256"): evidence_sha,
        (PROVIDER_SURFACE_NAME, "runtime_contract_sha256"): runtime_sha,
        (PROVIDER_SURFACE_NAME, "request_surface_sha256"): request_surface_sha,
        (BRONZE_CONTRACT_NAME, "source_bundle_sha256"): upstream_sha,
        (FIXTURE_MANIFEST_NAME, "runtime_contract_sha256"): runtime_sha,
        (STAGING_ROUTE_NAME, "provider_authority_sha256"): authority["authority_sha256"],
        (STAGING_ROUTE_NAME, "runtime_contract_sha256"): runtime_sha,
        (FIELD_FATE_STRUCTURE_NAME, "runtime_contract_sha256"): runtime_sha,
        (FIELD_FATE_STRUCTURE_NAME, "staging_route_contract_sha256"): route_sha,
        (FIELD_FATE_STRUCTURE_NAME, "upstream_contract_sha256"): upstream_sha,
        (
            FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
            "field_fate_structure_sha256",
        ): structure_sha,
        (
            FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
            "staging_route_contract_sha256",
        ): route_sha,
        (MODEL_CANDIDATE_CENSUS_NAME, "field_fate_structure_sha256"): structure_sha,
        (MODEL_CANDIDATE_CENSUS_NAME, "staging_route_contract_sha256"): route_sha,
        (MODEL_CANDIDATE_CENSUS_NAME, "star_table_contract_sha256"): star_sha,
        (
            MODEL_CANDIDATE_CENSUS_NAME,
            "analytical_needs_authority_sha256",
        ): analytical_needs_sha,
        (
            STABLE_MODEL_DISPOSITION_NAME,
            "candidate_source_authority_sha256",
        ): str(census["candidate_source_authority_sha256"]),
        (
            STABLE_MODEL_DISPOSITION_NAME,
            "model_candidate_census_sha256",
        ): _contract_digest(MODEL_CANDIDATE_CENSUS_NAME, census),
        (
            STAR_SEMANTIC_INVENTORY_NAME,
            "star_table_contract_sha256",
        ): star_sha,
        (
            STAR_SEMANTIC_INVENTORY_NAME,
            "stable_model_disposition_sha256",
        ): _contract_digest(
            STABLE_MODEL_DISPOSITION_NAME,
            children[STABLE_MODEL_DISPOSITION_NAME],
        ),
        (FIELD_FATE_NAME, "provider_authority_sha256"): authority["authority_sha256"],
        (FIELD_FATE_NAME, "staging_route_contract_sha256"): route_sha,
        (FIELD_FATE_NAME, "star_table_contract_sha256"): star_sha,
        (TEMPORAL_NAME, "staging_route_contract_sha256"): route_sha,
        (METRIC_NAME, "star_table_contract_sha256"): star_sha,
    }
    expected_edges.update(
        {
            (IMPLICIT_COMPETITION_CURRENT_SOURCE_NAME, parent_name): parent_sha256
            for parent_name, parent_sha256 in current_source_parents.items()
        }
    )
    for (child, parent_name), expected in expected_edges.items():
        if parents[child].get(parent_name) != expected:
            raise ContractAssuranceError(f"assurance parent mismatch: {child}:{parent_name}")
    if parents[TERMINAL_STATE_NAME] != {
        "generation_context_sha256": generation_context_sha256,
        **_TERMINAL_PARENT_BINDINGS,
    }:
        raise ContractAssuranceError("terminal-state assurance parent membership drifted")
    return parents


def _model_blockers(children: Mapping[str, Mapping[str, Any]]) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    structure_verification_summary = _object(
        children[FIELD_FATE_STRUCTURE_VERIFICATION_NAME].get("summary"),
        context="field-fate structure verification summary",
    )
    structure_open_count = structure_verification_summary.get("open_blocker_count")
    if isinstance(structure_open_count, int) and structure_open_count:
        blockers.append(
            {
                "child": FIELD_FATE_STRUCTURE_VERIFICATION_NAME,
                "scope": "provider_field",
                "code": "field_fate_structure_open_blocker",
                "occurrence_count": structure_open_count,
            }
        )
    census_summary = _object(
        children[MODEL_CANDIDATE_CENSUS_NAME].get("summary"),
        context="model-candidate census summary",
    )
    for code, count in sorted(
        _object(
            census_summary.get("blocker_code_counts"),
            context="model-candidate census blockers",
        ).items()
    ):
        if isinstance(count, int) and count:
            blockers.append(
                {
                    "child": MODEL_CANDIDATE_CENSUS_NAME,
                    "scope": "model_candidate",
                    "code": code,
                    "occurrence_count": count,
                }
            )
    disposition_blocker_counts: dict[str, int] = {}
    for raw in _array(
        children[STABLE_MODEL_DISPOSITION_NAME].get("blockers"),
        context="stable-model disposition blockers",
    ):
        item = _object(raw, context="stable-model disposition blocker")
        code = item.get("code")
        if not isinstance(code, str):
            raise ContractAssuranceError("stable-model disposition blocker code is invalid")
        disposition_blocker_counts[code] = disposition_blocker_counts.get(code, 0) + 1
    for code, count in sorted(disposition_blocker_counts.items()):
        blockers.append(
            {
                "child": STABLE_MODEL_DISPOSITION_NAME,
                "scope": "model_candidate",
                "code": code,
                "occurrence_count": count,
            }
        )
    semantic_blocker_counts: dict[str, int] = {}
    for raw in _array(
        children[STAR_SEMANTIC_INVENTORY_NAME].get("blockers"),
        context="star semantic inventory blockers",
    ):
        item = _object(raw, context="star semantic inventory blocker")
        code = item.get("code")
        if not isinstance(code, str):
            raise ContractAssuranceError("star semantic blocker code is invalid")
        semantic_blocker_counts[code] = semantic_blocker_counts.get(code, 0) + 1
    for code, count in sorted(semantic_blocker_counts.items()):
        blockers.append(
            {
                "child": STAR_SEMANTIC_INVENTORY_NAME,
                "scope": "public_table",
                "code": code,
                "occurrence_count": count,
            }
        )
    field_summary = _object(children[FIELD_FATE_NAME].get("summary"), context="field summary")
    for raw in _array(field_summary.get("blocker_summary"), context="field blockers"):
        item = _object(raw, context="field blocker")
        blockers.append(
            {
                "child": FIELD_FATE_NAME,
                "scope": item.get("scope"),
                "code": item.get("code"),
                "occurrence_count": item.get("occurrence_count"),
            }
        )
    star_summary = _object(children[STAR_TABLE_NAME].get("summary"), context="star summary")
    for raw in _array(star_summary.get("blocker_summary"), context="star blockers"):
        item = _object(raw, context="star blocker")
        blockers.append(
            {
                "child": STAR_TABLE_NAME,
                "scope": "public_table",
                "code": item.get("code"),
                "occurrence_count": item.get("occurrence_count"),
                "table_count": item.get("table_count"),
            }
        )
    temporal_summary = _object(
        children[TEMPORAL_NAME].get("summary"),
        context="temporal summary",
    )
    unknown_count = temporal_summary.get("unknown_availability_scope_count")
    if isinstance(unknown_count, int) and unknown_count:
        blockers.append(
            {
                "child": TEMPORAL_NAME,
                "scope": "route_scope",
                "code": "availability_unknown_pending_reviewed_evidence",
                "occurrence_count": unknown_count,
            }
        )
    metric_summary = _object(children[METRIC_NAME].get("summary"), context="metric summary")
    for code, count in sorted(
        _object(metric_summary.get("blocker_counts"), context="metric blockers").items()
    ):
        if isinstance(count, int) and count:
            blockers.append(
                {
                    "child": METRIC_NAME,
                    "scope": "public_numeric_column",
                    "code": code,
                    "occurrence_count": count,
                }
            )
    bronze_summary = _object(
        children[BRONZE_CONTRACT_NAME].get("summary"),
        context="bronze summary",
    )
    blocking_bronze = bronze_summary.get("blocking_zero_column_table_count")
    if isinstance(blocking_bronze, int) and blocking_bronze:
        blockers.append(
            {
                "child": BRONZE_CONTRACT_NAME,
                "scope": "bronze_table",
                "code": "blocking_zero_column_contract",
                "occurrence_count": blocking_bronze,
            }
        )
    blockers.extend(
        [
            {
                "child": "not-generated",
                "scope": "local_assurance",
                "code": "independent_local_test_receipt_not_bound",
                "occurrence_count": 1,
                "revalidation": "bind an exact local-test receipt to this generation",
            },
            {
                "child": "not-generated",
                "scope": "local_assurance",
                "code": "independent_review_receipt_not_bound",
                "occurrence_count": 1,
                "revalidation": "bind an independent review receipt to this generation",
            },
        ]
    )
    return sorted(
        blockers,
        key=lambda item: (
            str(item.get("child")),
            str(item.get("scope")),
            str(item.get("code")),
        ),
    )


def _generation_semantic_payload(
    *,
    context_sha256: str,
    child_records: Sequence[Mapping[str, Any]],
    blockers: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nbadb_pre_extraction_assurance_generation",
        "profile": PROFILE_PRE_EXTRACTION,
        "generation_context_sha256": context_sha256,
        "children": [
            {
                "name": record["name"],
                "semantic_sha256": record["semantic_sha256"],
                "contract_sha256": record["contract_sha256"],
                "parents": record["parents"],
            }
            for record in child_records
        ],
        "model_blockers": list(blockers),
        "data_green": "UNPROVEN",
    }


def _manifest_semantic_payload(manifest: Mapping[str, Any]) -> dict[str, object]:
    records = _array(manifest.get("children"), context="assurance child records")
    return {
        "schema_version": manifest.get("schema_version"),
        "kind": manifest.get("kind"),
        "profile": manifest.get("profile"),
        "required_members": manifest.get("required_members"),
        "generation_context_sha256": manifest.get("generation_context_sha256"),
        "source_sha256": manifest.get("source_sha256"),
        "dirty_sha256": manifest.get("dirty_sha256"),
        "provider_evidence_sha256": manifest.get("provider_evidence_sha256"),
        "tools": manifest.get("tools"),
        "commands": manifest.get("commands"),
        "children": [
            {
                "name": _object(record, context="assurance child record").get("name"),
                "semantic_sha256": _object(
                    record,
                    context="assurance child record",
                ).get("semantic_sha256"),
                "contract_sha256": _object(
                    record,
                    context="assurance child record",
                ).get("contract_sha256"),
                "parents": _object(record, context="assurance child record").get("parents"),
            }
            for record in records
        ],
        "model_blockers": manifest.get("model_blockers"),
        "generation_semantic_sha256": manifest.get("generation_semantic_sha256"),
        "data_green": _object(
            manifest.get("gate_results"),
            context="assurance gate results",
        ).get("data_green"),
    }


def _authority_diff_verifier_sha256() -> str:
    """Bind the exact independent semantic-diff verifier implementation."""

    from nbadb.contracts.authority_semantic_diff_verifier import (
        authority_semantic_diff_verifier_source_sha256,
    )

    try:
        return authority_semantic_diff_verifier_source_sha256()
    except ValueError as exc:
        raise ContractAssuranceError("cannot inspect the authority semantic-diff verifier") from exc


def _first_extraction_authority_diff(
    *,
    generation_context: Mapping[str, Any],
    manifest_file_sha256: str,
    generation_semantic_sha256: str,
    child_records: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """Build and independently reproduce choice B's mandatory full decision."""

    from nbadb.contracts.authority_semantic_diff import (
        AuthorityChildIdentity,
        AuthoritySemanticAtom,
        AuthoritySnapshot,
        DeltaBounds,
        build_authority_semantic_diff,
    )
    from nbadb.contracts.authority_semantic_diff_verifier import (
        build_verified_authority_semantic_diff,
    )

    semantic = _object(generation_context.get("semantic"), context="generation context")
    project = _object(semantic.get("project"), context="generation project context")
    verifier_sha256 = _authority_diff_verifier_sha256()
    mandatory_child_ids = tuple(sorted(CHILD_NAMES))
    identities = tuple(
        sorted(
            AuthorityChildIdentity(
                child_id=cast("str", record.get("name")),
                child_sha256=cast("str", record.get("contract_sha256")),
                parent_authority_sha256=manifest_file_sha256,
                semantic_atom_inventory_sha256=_sha256_json([]),
                semantic_atom_count=0,
            )
            for record in child_records
        )
    )
    semantic_atoms = tuple(
        sorted(
            AuthoritySemanticAtom(
                atom_id=f"child:{cast('str', record.get('name'))}",
                child_id=cast("str", record.get("name")),
                category="assurance_child",
                semantic_sha256=cast("str", record.get("contract_sha256")),
                affected_scopes=(),
                addition_classification="breaking",
                mutation_classification="breaking",
                evidence_sha256=cast("str", record.get("contract_sha256")),
            )
            for record in child_records
        )
    )
    current = AuthoritySnapshot(
        source_sha=cast("str", project.get("git_head_sha")),
        authority_sha256=manifest_file_sha256,
        manifest_sha256=manifest_file_sha256,
        generation_semantic_sha256=generation_semantic_sha256,
        mandatory_child_ids=mandatory_child_ids,
        children=identities,
        semantic_atoms=semantic_atoms,
        complete=True,
        independent_verifier_sha256=verifier_sha256,
    )
    receipt = build_authority_semantic_diff(
        previous=None,
        current=current,
        first_extraction=True,
        preferred_delta_mode=None,
        delta_bounds=DeltaBounds(),
    )
    verified = build_verified_authority_semantic_diff(receipt)
    if (
        verified.decision != receipt
        or verified.decision.selected_mode != "full"
        or verified.decision.decision_reason != "first_extraction_requires_full"
        or verified.verification.verification_status != "verified"
    ):
        raise ContractAssuranceError(
            "first-extraction authority semantic diff did not select the mandatory full mode"
        )
    return verified.to_dict()


def _assurance_admission(
    *,
    generation_context: Mapping[str, Any],
    assurance_manifest_sha256: str,
    generation_semantic_sha256: str,
    authority_semantic_diff_sha256: str,
    authority_update_mode: object,
    first_extraction: object,
    model_status: object,
) -> AssuranceAdmission:
    """Build the exact admission bound to one final content manifest."""

    semantic = _object(generation_context.get("semantic"), context="generation context")
    project = _object(semantic.get("project"), context="generation project context")
    provider = _object(semantic.get("provider"), context="generation provider context")
    evidence = _object(
        provider.get("evidence_receipt"),
        context="generation provider evidence",
    )
    authority = _object(provider.get("authority"), context="generation provider authority")
    try:
        return AssuranceAdmission(
            source_sha=cast("str", project.get("git_head_sha")),
            assurance_manifest_sha256=assurance_manifest_sha256,
            generation_semantic_sha256=generation_semantic_sha256,
            provider_evidence_sha256=cast("str", evidence.get("evidence_sha256")),
            provider_authority_sha256=cast("str", authority.get("authority_sha256")),
            authority_semantic_diff_sha256=authority_semantic_diff_sha256,
            authority_update_mode=cast("AuthorityUpdateMode", authority_update_mode),
            first_extraction=cast("bool", first_extraction),
            model_status=cast("ModelStatus", model_status),
        )
    except AssuranceAdmissionError as exc:
        raise ContractAssuranceError("assurance admission evidence is invalid") from exc


def _generation_index_payload(
    *,
    manifest_size: int,
    manifest_sha256: str,
    authority_diff_size: int,
    authority_diff_sha256: str,
    admission_size: int,
    admission_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nbadb_contract_assurance_generation_index",
        "profile": PROFILE_PRE_EXTRACTION,
        "required_members": list(REQUIRED_MEMBERS),
        "members": [
            {
                "name": MANIFEST_NAME,
                "size": manifest_size,
                "file_sha256": manifest_sha256,
            },
            {
                "name": AUTHORITY_SEMANTIC_DIFF_NAME,
                "size": authority_diff_size,
                "file_sha256": authority_diff_sha256,
            },
            {
                "name": ADMISSION_NAME,
                "size": admission_size,
                "file_sha256": admission_sha256,
            },
        ],
    }


def _validate_generation_index_payload(
    payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if set(payload) != {
        "schema_version",
        "kind",
        "profile",
        "required_members",
        "members",
    }:
        raise ContractAssuranceError("assurance generation index fields do not match the schema")
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
        or payload.get("kind") != "nbadb_contract_assurance_generation_index"
        or payload.get("profile") != PROFILE_PRE_EXTRACTION
        or payload.get("required_members") != list(REQUIRED_MEMBERS)
    ):
        raise ContractAssuranceError("assurance generation index identity is invalid")
    raw_records = _array(payload.get("members"), context="assurance root member records")
    records = [_object(item, context="assurance root member record") for item in raw_records]
    if [record.get("name") for record in records] != [
        MANIFEST_NAME,
        AUTHORITY_SEMANTIC_DIFF_NAME,
        ADMISSION_NAME,
    ]:
        raise ContractAssuranceError("assurance root member order or membership is invalid")
    by_name: dict[str, dict[str, Any]] = {}
    for record in records:
        if set(record) != {"name", "size", "file_sha256"}:
            raise ContractAssuranceError("assurance root member fields do not match the schema")
        name = record.get("name")
        size = record.get("size")
        if (
            not isinstance(name, str)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or not _is_sha256(record.get("file_sha256"))
        ):
            raise ContractAssuranceError("assurance root member identity is invalid")
        by_name[name] = record
    return by_name


def _write_json_new(path: Path, payload: Mapping[str, Any]) -> tuple[int, str]:
    encoded = _canonical_bytes(payload)
    if len(encoded) > _MAX_ASSURANCE_MEMBER_BYTES:
        raise ContractAssuranceError("assurance member exceeds the bounded size limit")
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError as exc:
        raise ContractAssuranceError(f"assurance member already exists: {path.name}") from exc
    return len(encoded), _sha256_bytes(encoded)


def _read_regular_member(path: Path, *, context: str) -> bytes:
    """Read one bounded regular file without following a swapped symlink/FIFO."""

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ContractAssuranceError(f"{context} is not a regular file") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ContractAssuranceError(f"{context} is not a regular file")
        if opened.st_size < 0 or opened.st_size > _MAX_ASSURANCE_MEMBER_BYTES:
            raise ContractAssuranceError(f"{context} exceeds the bounded size limit")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            encoded = stream.read(_MAX_ASSURANCE_MEMBER_BYTES + 1)
        finished = os.fstat(descriptor)
        try:
            current = os.lstat(path)
        except OSError as exc:
            raise ContractAssuranceError(f"{context} changed during validation") from exc
        opened_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        finished_identity = (
            finished.st_dev,
            finished.st_ino,
            finished.st_size,
            finished.st_mtime_ns,
            finished.st_ctime_ns,
        )
        if (
            opened_identity != finished_identity
            or not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
            or len(encoded) != opened.st_size
        ):
            raise ContractAssuranceError(f"{context} changed during validation")
        return encoded
    finally:
        os.close(descriptor)


def _decode_json_member(encoded: bytes, *, context: str) -> dict[str, Any]:
    try:
        return _object(json.loads(encoded.decode("utf-8")), context=context)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractAssuranceError(f"{context} is not canonical JSON") from exc


def _read_json_file(path: Path, *, context: str) -> dict[str, Any]:
    return _decode_json_member(_read_regular_member(path, context=context), context=context)


def _write_generation(
    *,
    output_dir: Path,
    generation_context: dict[str, Any],
    compiled_children: Mapping[str, dict[str, Any]],
    expected_semantic_sha256: str | None,
    before_manifest: Callable[[], None] | None = None,
    validation_project_root: Path | str | None = None,
    validation_endpoint_analysis_docs_root: Path | str | None = None,
) -> AssuranceGeneration:
    context_sha = _child_semantic_sha256(GENERATION_CONTEXT_NAME, generation_context)
    children: dict[str, dict[str, Any]] = {
        GENERATION_CONTEXT_NAME: generation_context,
        **compiled_children,
    }
    if set(children) != set(CHILD_NAMES):
        raise ContractAssuranceError("compiled assurance profile membership is invalid")
    semantic_digests = {name: _child_semantic_sha256(name, children[name]) for name in CHILD_NAMES}
    parents = _validate_parent_graph(children, generation_context_sha256=context_sha)
    blockers = _model_blockers(children)

    try:
        output_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise ContractAssuranceError("assurance generation directory already exists") from exc
    except OSError as exc:
        raise ContractAssuranceError("cannot create fresh assurance generation directory") from exc
    if output_dir.is_symlink():
        raise ContractAssuranceError("assurance generation directory cannot be a symlink")

    child_records: list[dict[str, Any]] = []
    for name in CHILD_NAMES:
        size, file_sha = _write_json_new(output_dir / name, children[name])
        child_records.append(
            {
                "name": name,
                "size": size,
                "file_sha256": file_sha,
                "semantic_sha256": semantic_digests[name],
                "contract_sha256": (
                    context_sha
                    if name == GENERATION_CONTEXT_NAME
                    else _contract_digest(name, children[name])
                ),
                "parents": parents[name],
            }
        )

    observed_before_manifest = {path.name for path in output_dir.iterdir()}
    if observed_before_manifest != set(CHILD_NAMES):
        raise ContractAssuranceError(
            "assurance directory has stale, extra, or missing children before manifest"
        )
    if before_manifest is not None:
        before_manifest()

    semantic_payload = _generation_semantic_payload(
        context_sha256=context_sha,
        child_records=child_records,
        blockers=blockers,
    )
    semantic_sha = _sha256_json(semantic_payload)
    if expected_semantic_sha256 is not None and semantic_sha != expected_semantic_sha256:
        raise ContractAssuranceError("second assurance generation has a different semantic digest")
    deterministic_status = "GREEN" if expected_semantic_sha256 is not None else "NOT_CHECKED"
    model_green = not blockers and deterministic_status == "GREEN"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "nbadb_pre_extraction_assurance_manifest",
        "profile": PROFILE_PRE_EXTRACTION,
        "required_members": list(CONTENT_REQUIRED_MEMBERS),
        "generation_context_sha256": context_sha,
        "source_sha256": generation_context["semantic"]["project"]["source_sha256"],
        "dirty_sha256": generation_context["semantic"]["project"]["dirty_sha256"],
        "provider_evidence_sha256": generation_context["semantic"]["provider"]["evidence_receipt"][
            "evidence_sha256"
        ],
        "tools": generation_context["semantic"]["tools"],
        "commands": generation_context["semantic"]["commands"],
        "children": child_records,
        "model_blockers": blockers,
        "generation_semantic_sha256": semantic_sha,
        "gate_results": {
            "structural_generation": "GREEN",
            "semantic_determinism": deterministic_status,
            "model_green": model_green,
            "model_status": "GREEN" if model_green else "RED",
            "data_green": "UNPROVEN",
            "populated_data_correctness": "NOT_EVALUATED",
            "live_availability": "NOT_EVALUATED",
            "publication": "NOT_EVALUATED",
            "external_gates": {
                "exact_sha_ci": "OPEN_EXTERNAL",
                "vpn_and_nba_probing": "OPEN_EXTERNAL",
                "extraction": "OPEN_EXTERNAL",
                "kaggle_readback": "OPEN_EXTERNAL",
                "permission_review": "OPEN_EXTERNAL",
            },
        },
        "observation": {
            "generated_at": _utc_now(),
            "output_location": "fresh_generation_directory",
            "reference_generation_semantic_sha256": expected_semantic_sha256,
        },
    }
    manifest["manifest_semantic_sha256"] = _sha256_json(_manifest_semantic_payload(manifest))
    manifest["manifest_sha256"] = _sha256_json(manifest)
    manifest_size, manifest_file_sha256 = _write_json_new(output_dir / MANIFEST_NAME, manifest)

    authority_diff = _first_extraction_authority_diff(
        generation_context=generation_context,
        manifest_file_sha256=manifest_file_sha256,
        generation_semantic_sha256=semantic_sha,
        child_records=child_records,
    )
    authority_diff_size, authority_diff_sha256 = _write_json_new(
        output_dir / AUTHORITY_SEMANTIC_DIFF_NAME,
        authority_diff,
    )
    authority_diff_decision = _object(
        authority_diff.get("decision"),
        context="verified authority semantic-diff decision",
    )

    observed_before_admission = {path.name for path in output_dir.iterdir()}
    if observed_before_admission != set(ROOT_CONTENT_REQUIRED_MEMBERS):
        raise ContractAssuranceError(
            "assurance directory has stale, extra, or missing content before admission"
        )
    admission = _assurance_admission(
        generation_context=generation_context,
        assurance_manifest_sha256=manifest_file_sha256,
        generation_semantic_sha256=semantic_sha,
        authority_semantic_diff_sha256=authority_diff_sha256,
        authority_update_mode=authority_diff_decision.get("selected_mode"),
        first_extraction=authority_diff_decision.get("first_extraction"),
        model_status=manifest["gate_results"]["model_status"],
    )
    admission_size, admission_sha256 = _write_json_new(
        output_dir / ADMISSION_NAME,
        admission.to_dict(),
    )
    if admission_sha256 != admission.sha256:
        raise ContractAssuranceError("assurance admission canonical digest is inconsistent")

    observed_before_index = {path.name for path in output_dir.iterdir()}
    if observed_before_index != set((*ROOT_CONTENT_REQUIRED_MEMBERS, ADMISSION_NAME)):
        raise ContractAssuranceError(
            "assurance directory has stale, extra, or missing content before root index"
        )
    generation_index = _generation_index_payload(
        manifest_size=manifest_size,
        manifest_sha256=manifest_file_sha256,
        authority_diff_size=authority_diff_size,
        authority_diff_sha256=authority_diff_sha256,
        admission_size=admission_size,
        admission_sha256=admission_sha256,
    )
    _write_json_new(output_dir / GENERATION_INDEX_NAME, generation_index)
    return validate_assurance_generation(
        output_dir,
        project_root=validation_project_root,
        endpoint_analysis_docs_root=validation_endpoint_analysis_docs_root,
    )


def _assert_same_frozen_context(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> None:
    if first.get("semantic") != second.get("semantic"):
        raise ContractAssuranceError(
            "relevant source, dirty state, provider, or tool context changed during generation"
        )


def generate_pre_extraction_assurance(
    *,
    endpoint_analysis_docs_root: Path | str,
    output_dir: Path | str,
    project_root: Path | str | None = None,
    expected_semantic_sha256: str | None = None,
) -> AssuranceGeneration:
    """Generate one exact pre-extraction assurance set in a new directory."""

    project = (Path(project_root) if project_root is not None else Path.cwd()).resolve()
    upstream = Path(endpoint_analysis_docs_root).resolve()
    destination = Path(output_dir)
    if expected_semantic_sha256 is not None and not _is_sha256(expected_semantic_sha256):
        raise ContractAssuranceError("expected assurance semantic digest is invalid")
    if destination.exists() or destination.is_symlink():
        raise ContractAssuranceError("assurance generation directory must be brand-new")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ContractAssuranceError("assurance generation parent must be an existing directory")

    before = _freeze_generation_context(
        project_root=project,
        endpoint_analysis_docs_root=upstream,
    )
    compiled = _compile_profile_children(
        project_root=project,
        endpoint_analysis_docs_root=upstream,
        generation_context=before,
    )

    def _validate_frozen_context_before_manifest() -> None:
        after = _freeze_generation_context(
            project_root=project,
            endpoint_analysis_docs_root=upstream,
        )
        _assert_same_frozen_context(before, after)

    return _write_generation(
        output_dir=destination,
        generation_context=before,
        compiled_children=compiled,
        expected_semantic_sha256=expected_semantic_sha256,
        before_manifest=_validate_frozen_context_before_manifest,
        validation_project_root=project,
        validation_endpoint_analysis_docs_root=upstream,
    )


def _fresh_generation_path(output_root: Path) -> Path:
    for _attempt in range(32):
        candidate = output_root / f"generation-{uuid.uuid4().hex}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise ContractAssuranceError("cannot allocate a fresh assurance generation name")


def check_pre_extraction_assurance(
    *,
    endpoint_analysis_docs_root: Path | str,
    output_root: Path | str = Path("artifacts/contract-assurance/pre-extraction"),
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Generate twice and return the second, deterministic assurance receipt."""

    root = Path(output_root)
    if root.is_symlink():
        raise ContractAssuranceError("assurance output root cannot be a symlink")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ContractAssuranceError("cannot create assurance output root") from exc
    first = generate_pre_extraction_assurance(
        endpoint_analysis_docs_root=endpoint_analysis_docs_root,
        output_dir=_fresh_generation_path(root),
        project_root=project_root,
    )
    second = generate_pre_extraction_assurance(
        endpoint_analysis_docs_root=endpoint_analysis_docs_root,
        output_dir=_fresh_generation_path(root),
        project_root=project_root,
        expected_semantic_sha256=first.semantic_sha256,
    )
    return {
        "schema_version": 1,
        "kind": "nbadb_pre_extraction_assurance_check",
        "profile": PROFILE_PRE_EXTRACTION,
        "first_generation_location": "first_fresh_generation_directory",
        "assurance_location": "second_fresh_generation_directory",
        "generation_semantic_sha256": second.semantic_sha256,
        "semantic_determinism": "GREEN",
        "structural_generation": "GREEN",
        "model_green": second.model_green,
        "model_status": "GREEN" if second.model_green else "RED",
        "assurance_admission_location": ADMISSION_NAME,
        "assurance_admission_sha256": second.admission_sha256,
        "assurance_admission_status": second.admission_status,
        "assurance_generation_index_location": GENERATION_INDEX_NAME,
        "assurance_generation_index_sha256": second.generation_index_sha256,
        "data_green": "UNPROVEN",
        "model_blockers": second.manifest["model_blockers"],
    }


def validate_assurance_generation(
    directory: Path | str,
    *,
    project_root: Path | str | None = None,
    endpoint_analysis_docs_root: Path | str | None = None,
) -> AssuranceGeneration:
    """Validate bytes, graph, and freshly rederived current model authorities."""

    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ContractAssuranceError("assurance generation must be a regular directory")
    observed = {path.name for path in root.iterdir()}
    if observed != set(REQUIRED_MEMBERS):
        raise ContractAssuranceError("assurance generation has stale, extra, or missing members")

    index_encoded = _read_regular_member(
        root / GENERATION_INDEX_NAME,
        context="assurance generation index",
    )
    generation_index = _decode_json_member(
        index_encoded,
        context="assurance generation index",
    )
    if _canonical_bytes(generation_index) != index_encoded:
        raise ContractAssuranceError("assurance generation index is not canonical JSON")
    root_records = _validate_generation_index_payload(generation_index)

    rooted_members: dict[str, tuple[bytes, dict[str, Any]]] = {}
    for name in (MANIFEST_NAME, AUTHORITY_SEMANTIC_DIFF_NAME, ADMISSION_NAME):
        encoded = _read_regular_member(root / name, context=f"assurance root member {name}")
        record = root_records[name]
        if record.get("size") != len(encoded) or record.get("file_sha256") != _sha256_bytes(
            encoded
        ):
            raise ContractAssuranceError(f"assurance root member bytes differ: {name}")
        payload = _decode_json_member(encoded, context=f"assurance root member {name}")
        if _canonical_bytes(payload) != encoded:
            raise ContractAssuranceError(f"assurance root member is not canonical JSON: {name}")
        rooted_members[name] = (encoded, payload)

    manifest_encoded, manifest = rooted_members[MANIFEST_NAME]
    body = dict(manifest)
    manifest_sha = body.pop("manifest_sha256", None)
    if not _is_sha256(manifest_sha) or manifest_sha != _sha256_json(body):
        raise ContractAssuranceError("assurance manifest byte digest is invalid")
    if manifest.get("manifest_semantic_sha256") != _sha256_json(
        _manifest_semantic_payload(manifest)
    ):
        raise ContractAssuranceError("assurance manifest semantic digest is invalid")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "nbadb_pre_extraction_assurance_manifest"
        or manifest.get("profile") != PROFILE_PRE_EXTRACTION
        or manifest.get("required_members") != list(CONTENT_REQUIRED_MEMBERS)
    ):
        raise ContractAssuranceError("assurance manifest identity or membership is invalid")

    _admission_encoded, admission_payload = rooted_members[ADMISSION_NAME]
    try:
        admission = AssuranceAdmission.from_dict(admission_payload)
    except AssuranceAdmissionError as exc:
        raise ContractAssuranceError("assurance admission member is invalid") from exc
    if admission.sha256 != root_records[ADMISSION_NAME]["file_sha256"]:
        raise ContractAssuranceError("assurance admission canonical digest differs")

    raw_records = _array(manifest.get("children"), context="assurance child records")
    records = [_object(item, context="assurance child record") for item in raw_records]
    if [record.get("name") for record in records] != list(CHILD_NAMES):
        raise ContractAssuranceError("assurance child record order or membership is invalid")

    children: dict[str, dict[str, Any]] = {}
    for record in records:
        name = record["name"]
        if not isinstance(name, str):
            raise ContractAssuranceError("assurance child name is invalid")
        path = root / name
        encoded = _read_regular_member(path, context=f"assurance child {name}")
        if record.get("size") != len(encoded) or record.get("file_sha256") != _sha256_bytes(
            encoded
        ):
            raise ContractAssuranceError(f"assurance child bytes differ: {name}")
        child = _decode_json_member(encoded, context=f"assurance child {name}")
        if _canonical_bytes(child) != encoded:
            raise ContractAssuranceError(f"assurance child is not canonical JSON: {name}")
        semantic_sha = _child_semantic_sha256(name, child)
        if record.get("semantic_sha256") != semantic_sha:
            raise ContractAssuranceError(f"assurance child semantic digest differs: {name}")
        contract_sha = (
            semantic_sha if name == GENERATION_CONTEXT_NAME else _contract_digest(name, child)
        )
        if record.get("contract_sha256") != contract_sha:
            raise ContractAssuranceError(f"assurance child contract digest differs: {name}")
        children[name] = child

    context_sha = _child_semantic_sha256(
        GENERATION_CONTEXT_NAME,
        children[GENERATION_CONTEXT_NAME],
    )
    if manifest.get("generation_context_sha256") != context_sha:
        raise ContractAssuranceError("manifest generation context parent is invalid")
    parents = _validate_parent_graph(children, generation_context_sha256=context_sha)
    for record in records:
        name = record["name"]
        if record.get("parents") != parents[name]:
            raise ContractAssuranceError(f"manifest child parent digests differ: {name}")

    _validate_persisted_model_authorities(
        children,
        children[GENERATION_CONTEXT_NAME],
        project_root=project_root,
        endpoint_analysis_docs_root=endpoint_analysis_docs_root,
    )

    blockers = _model_blockers(children)
    if manifest.get("model_blockers") != blockers:
        raise ContractAssuranceError("manifest model blockers differ from child evidence")
    expected_semantic = _sha256_json(
        _generation_semantic_payload(
            context_sha256=context_sha,
            child_records=records,
            blockers=blockers,
        )
    )
    if manifest.get("generation_semantic_sha256") != expected_semantic:
        raise ContractAssuranceError("assurance generation semantic digest is invalid")

    authority_diff_encoded, authority_diff_payload = rooted_members[AUTHORITY_SEMANTIC_DIFF_NAME]
    from nbadb.contracts.authority_semantic_diff import AuthoritySemanticDiffError
    from nbadb.contracts.authority_semantic_diff_verifier import (
        verify_verified_authority_semantic_diff_bytes,
    )

    try:
        verified_authority_diff = verify_verified_authority_semantic_diff_bytes(
            authority_diff_encoded
        )
    except AuthoritySemanticDiffError as exc:
        raise ContractAssuranceError("authority semantic-diff envelope is invalid") from exc
    expected_authority_diff = _first_extraction_authority_diff(
        generation_context=children[GENERATION_CONTEXT_NAME],
        manifest_file_sha256=_sha256_bytes(manifest_encoded),
        generation_semantic_sha256=expected_semantic,
        child_records=records,
    )
    if authority_diff_payload != expected_authority_diff:
        raise ContractAssuranceError(
            "authority semantic-diff receipt differs from the exact assurance generation"
        )
    authority_diff_decision = verified_authority_diff.decision
    gate_results = _object(manifest.get("gate_results"), context="assurance gate results")
    deterministic = gate_results.get("semantic_determinism")
    expected_model_green = not blockers and deterministic == "GREEN"
    if (
        gate_results.get("structural_generation") != "GREEN"
        or gate_results.get("model_green") is not expected_model_green
        or gate_results.get("model_status") != ("GREEN" if expected_model_green else "RED")
        or gate_results.get("data_green") != "UNPROVEN"
    ):
        raise ContractAssuranceError("assurance gate result is inconsistent with evidence")
    expected_admission = _assurance_admission(
        generation_context=children[GENERATION_CONTEXT_NAME],
        assurance_manifest_sha256=_sha256_bytes(manifest_encoded),
        generation_semantic_sha256=expected_semantic,
        authority_semantic_diff_sha256=_sha256_bytes(authority_diff_encoded),
        authority_update_mode=authority_diff_decision.selected_mode,
        first_extraction=authority_diff_decision.first_extraction,
        model_status=gate_results.get("model_status"),
    )
    if admission != expected_admission:
        raise ContractAssuranceError("assurance admission does not match generation evidence")
    return AssuranceGeneration(
        directory=root,
        manifest=manifest,
        admission=admission,
        generation_index=generation_index,
        generation_index_sha256=_sha256_bytes(index_encoded),
    )


__all__ = [
    "ADMISSION_NAME",
    "ANALYTICAL_NEEDS_NAME",
    "AUTHORITY_SEMANTIC_DIFF_NAME",
    "AssuranceGeneration",
    "CHILD_NAMES",
    "CONTENT_REQUIRED_MEMBERS",
    "ContractAssuranceError",
    "FIELD_FATE_STRUCTURE_NAME",
    "FIELD_FATE_STRUCTURE_VERIFICATION_NAME",
    "GENERATION_INDEX_NAME",
    "MANIFEST_NAME",
    "MODEL_CANDIDATE_CENSUS_NAME",
    "PROFILE_PRE_EXTRACTION",
    "PROVIDER_SURFACE_NAME",
    "RAW_REQUEST_SCHEMA_NAME",
    "REQUIRED_MEMBERS",
    "ROOT_CONTENT_REQUIRED_MEMBERS",
    "STABLE_MODEL_DISPOSITION_NAME",
    "STAR_SEMANTIC_INVENTORY_NAME",
    "check_pre_extraction_assurance",
    "generate_pre_extraction_assurance",
    "validate_assurance_generation",
]
