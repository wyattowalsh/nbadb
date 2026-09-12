"""Admit recurring publication only with schema-v7 successor authority.

Generic scan evidence and a leftover full-extraction schema-v3 terminal report
cannot authorize daily or monthly publication.  This gate inspects the public
data directory the hosted workflows already hand to scan and upload.

A claimed schema-v7 successor tree may enter Kaggle mutation only through
durable intent plus exact version/inventory/hash readback. Generic scan or
byte upload cannot substitute. Immediately before mutation the supplied
schema-v7 report must belong to the exact promoted schema-v6 transaction
and current-pointer identity re-read from the generation store.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Final, cast

from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME,
)
from nbadb.orchestrate.successor_assurance import (
    SUCCESSOR_TERMINAL_ASSURANCE_SCHEMA_VERSION,
    SuccessorAssuranceContractError,
    SuccessorTerminalAssuranceReportV7,
    validate_successor_terminal_assurance_report,
)
from nbadb.orchestrate.successor_generation_store import (
    SuccessorGenerationStore,
    SuccessorGenerationStoreError,
)
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_update_contract import (
    SuccessorAssuranceIdentity,
    SuccessorGenerationState,
)

__all__ = [
    "SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED",
    "SUCCESSOR_DURABLE_PUBLICATION_REQUIRED",
    "SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED",
    "SuccessorPublicationAuthorityError",
    "bind_successor_report_to_current_authority",
    "open_successor_generation_store",
    "require_successor_current_publication_authority",
    "require_successor_durable_publication",
    "require_successor_publication_authority",
    "successor_publication_requested",
]

SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED: Final = (
    "schema-v7 successor authority is required; generic scan or "
    "full-extraction terminal report cannot substitute"
)
SUCCESSOR_DURABLE_PUBLICATION_REQUIRED: Final = (
    "schema-v7 successor publication requires durable intent and "
    "exact version/inventory/hash readback"
)
SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED: Final = (
    "Schema-v7 successor publication requires an explicit current generation store"
)


class SuccessorPublicationAuthorityError(ValueError):
    """Raised when recurring publication lacks successor authority or durable readback."""


def _successor_report_payload(data_dir: Path) -> dict[str, object] | None:
    if not isinstance(data_dir, Path) or data_dir.is_symlink() or not data_dir.is_dir():
        return None
    report_path = data_dir / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
    if report_path.is_symlink() or not report_path.is_file():
        return None
    try:
        payload = json.loads(report_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def successor_publication_requested(
    data_dir: Path,
    *,
    successor_generation_store: SuccessorGenerationStore | None = None,
) -> bool:
    """True when a successor store is requested or the tree claims schema-v7."""

    if successor_generation_store is not None:
        return True
    payload = _successor_report_payload(data_dir)
    return (
        payload is not None
        and payload.get("schema_version") == SUCCESSOR_TERMINAL_ASSURANCE_SCHEMA_VERSION
    )


def require_successor_publication_authority(
    data_dir: Path,
    *,
    successor_generation_store: SuccessorGenerationStore | None = None,
    require_current_authority: bool = False,
) -> SuccessorTerminalAssuranceReportV7:
    """Return the validated schema-v7 report or fail closed."""

    if not isinstance(data_dir, Path):
        raise SuccessorPublicationAuthorityError(SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED)
    if data_dir.is_symlink() or not data_dir.is_dir():
        raise SuccessorPublicationAuthorityError(SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED)

    report_path = data_dir / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
    if report_path.is_symlink() or not report_path.is_file():
        raise SuccessorPublicationAuthorityError(SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED)

    try:
        encoded = report_path.read_bytes()
        payload = json.loads(encoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuccessorPublicationAuthorityError(SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != SUCCESSOR_TERMINAL_ASSURANCE_SCHEMA_VERSION
    ):
        raise SuccessorPublicationAuthorityError(SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED)

    try:
        report = validate_successor_terminal_assurance_report(encoded)
    except SuccessorAssuranceContractError as exc:
        raise SuccessorPublicationAuthorityError(
            f"schema-v7 successor authority is invalid: {exc}"
        ) from exc
    if require_current_authority:
        bind_successor_report_to_current_authority(
            data_dir,
            report,
            successor_generation_store=successor_generation_store,
        )
    return report


def require_successor_durable_publication(
    data_dir: Path,
    *,
    full_publication: bool,
    verify_remote: bool,
    require_durable_intent: bool,
    publication_ledger: object | None,
    successor_generation_store: SuccessorGenerationStore | None = None,
) -> SuccessorTerminalAssuranceReportV7:
    """Admit one schema-v7 successor tree only through durable verified publication."""

    report = require_successor_publication_authority(data_dir)
    if (
        full_publication is not True
        or verify_remote is not True
        or require_durable_intent is not True
        or publication_ledger is None
    ):
        raise SuccessorPublicationAuthorityError(SUCCESSOR_DURABLE_PUBLICATION_REQUIRED)
    bind_successor_report_to_current_authority(
        data_dir,
        report,
        successor_generation_store=successor_generation_store,
    )
    return report


def open_successor_generation_store(root: Path) -> SuccessorGenerationStore:
    """Open one explicit generation store or fail closed."""

    if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
        raise SuccessorPublicationAuthorityError(SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED)
    return SuccessorGenerationStore(root)


def bind_successor_report_to_current_authority(
    data_dir: Path,
    report: SuccessorTerminalAssuranceReportV7,
    *,
    successor_generation_store: SuccessorGenerationStore | None,
) -> None:
    """Bind one validated schema-v7 report to the store's current pointer."""

    if successor_generation_store is None:
        raise SuccessorPublicationAuthorityError(SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED)
    if not isinstance(report, SuccessorTerminalAssuranceReportV7):
        raise SuccessorPublicationAuthorityError(SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED)
    manifest_path = data_dir / ASSURED_ARTIFACT_MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise SuccessorPublicationAuthorityError(SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED)
    try:
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        installed = measure_installed_public_tree(data_dir)
    except (OSError, TypeError, ValueError) as exc:
        raise SuccessorPublicationAuthorityError(
            SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED
        ) from exc
    identity = report.to_successor_assurance_identity(
        successor_assured_manifest_sha256=manifest_sha256,
        installed_public_tree_sha256=installed.installed_public_tree_sha256,
    )
    try:
        require_successor_current_publication_authority(
            data_root=data_dir,
            generation_store=successor_generation_store,
            assurance_identity=identity,
            installed_public_tree_sha256=installed.installed_public_tree_sha256,
        )
    except ValueError as exc:
        raise SuccessorPublicationAuthorityError(str(exc)) from exc


def require_successor_current_publication_authority(
    *,
    data_root: Path,
    generation_store: SuccessorGenerationStore,
    assurance_identity: SuccessorAssuranceIdentity,
    installed_public_tree_sha256: str,
) -> None:
    """Bind schema-v7 publication to the store's exact frozen current tree."""

    if not isinstance(generation_store, SuccessorGenerationStore):
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor publication generation store is invalid"
        )
    try:
        current_pointer = generation_store.read_current()
    except SuccessorGenerationStoreError as exc:
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor current generation authority is invalid"
        ) from exc
    if current_pointer is None:
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor publication has no current generation authority"
        )

    current_reference = cast("dict[str, Any]", current_pointer["current"])
    candidate_name = cast("str", current_reference["candidate_name"])
    candidate_root = generation_store.generations_root / candidate_name
    current_public_root = candidate_root / "public"
    try:
        resolved_data_root = data_root.resolve(strict=True)
        resolved_current_public_root = current_public_root.resolve(strict=True)
        data_stat = os.stat(resolved_data_root, follow_symlinks=False)
        current_stat = os.stat(resolved_current_public_root, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor current public directory cannot be resolved safely"
        ) from exc
    if resolved_data_root != resolved_current_public_root or (
        data_stat.st_dev,
        data_stat.st_ino,
    ) != (current_stat.st_dev, current_stat.st_ino):
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor publication data directory is not the exact current "
            "candidate public directory"
        )

    try:
        transaction = generation_store.load_transaction(candidate_root)
    except SuccessorGenerationStoreError as exc:
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor current transaction cannot be loaded safely"
        ) from exc
    if transaction.state is not SuccessorGenerationState.PROMOTED:
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor current transaction is not PROMOTED"
        )
    promoted_assurance = transaction.promoted_assurance
    expected_reference = {
        "generation": transaction.generation,
        "candidate_name": generation_store.candidate_name(transaction),
        "transaction_sha256": transaction.content_sha256,
        "assurance_sha256": promoted_assurance.identity_sha256,
        "data_tree_fingerprint": (promoted_assurance.successor_data_tree_fingerprint),
        "installed_public_tree_sha256": (promoted_assurance.installed_public_tree_sha256),
        "private_generation_receipt_sha256": (promoted_assurance.private_generation_receipt_sha256),
    }
    if current_reference != expected_reference:
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor current pointer differs from its PROMOTED transaction"
        )
    if (
        promoted_assurance != assurance_identity
        or promoted_assurance.identity_sha256 != assurance_identity.identity_sha256
    ):
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor report assurance identity differs from the exact "
            "PROMOTED transaction"
        )
    if (
        installed_public_tree_sha256 != promoted_assurance.installed_public_tree_sha256
        or current_reference["installed_public_tree_sha256"] != installed_public_tree_sha256
    ):
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor installed public tree differs from current promotion authority"
        )
    try:
        rechecked_pointer = generation_store.read_current()
    except SuccessorGenerationStoreError as exc:
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor current generation changed during validation"
        ) from exc
    if rechecked_pointer != current_pointer:
        raise SuccessorPublicationAuthorityError(
            "Schema-v7 successor current generation changed during validation"
        )
