"""Policy-compliant private planning placement and receipt-bound garbage collection.

This leaf provisions caller-owned POSIX owner-only private planning storage and
collects only generations that no current/previous pointer, unresolved
coordinator checkpoint, or durable publication receipt still names.  It does
not invent a production volume, rotate secrets, or treat age as deletion
authority.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

from nbadb.orchestrate.successor_coordinator import (
    SuccessorCoordinatorCheckpoint,
    SuccessorCoordinatorCheckpointStore,
    SuccessorCoordinatorPhase,
)
from nbadb.orchestrate.successor_generation_store import (
    SuccessorGenerationStore,
    SuccessorGenerationStoreError,
    SuccessorPrivateRetentionReceipts,
)
from nbadb.orchestrate.successor_planner import deterministic_planning_generation_id
from nbadb.orchestrate.successor_planning_store import (
    PlanningStoreBudget,
    PlanningStoreCollectionResult,
    SuccessorPlanningStore,
    SuccessorPlanningStoreError,
)
from nbadb.orchestrate.successor_update_contract import canonical_sha256

__all__ = [
    "PRIVATE_PLANNING_PLACEMENT_SCHEMA_VERSION",
    "PrivatePlanningCollectionReport",
    "PrivatePlanningPlacementKind",
    "PrivatePlanningPublicationReceipt",
    "PrivatePlanningRetentionError",
    "PrivatePlanningStoragePlacement",
    "collect_unreferenced_private_planning_state",
    "provision_private_planning_storage",
    "require_private_planning_storage",
]

PRIVATE_PLANNING_PLACEMENT_SCHEMA_VERSION: Final = 1
_PLACEMENT_DOMAIN: Final = "nbadb.private-planning-storage-placement.v1"
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_PRIVATE_LOCK_MODE: Final = 0o600
_COMMITTED_OBJECT_MODE: Final = 0o400
_SHA256_LENGTH: Final = 64


class PrivatePlanningRetentionError(RuntimeError):
    """Raised when private planning placement or receipt-bound collection is unsafe."""


class PrivatePlanningPlacementKind(StrEnum):
    """Whether a caller-owned root is a local fixture or production placement."""

    FIXTURE = "fixture"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class PrivatePlanningStoragePlacement:
    """Path-free placement identity plus the caller-owned roots it binds."""

    kind: PrivatePlanningPlacementKind
    planning_store_root: Path
    planning_capture_root: Path | None
    update_capture_root: Path | None
    owner_uid: int
    encryption_at_rest_attested: bool
    application_encryption: bool
    identity_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PrivatePlanningPlacementKind):
            raise PrivatePlanningRetentionError("private planning placement kind is invalid")
        if not isinstance(self.planning_store_root, Path) or (
            not self.planning_store_root.is_absolute()
        ):
            raise PrivatePlanningRetentionError(
                "private planning store root must be an absolute Path"
            )
        for field_name in ("planning_capture_root", "update_capture_root"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, Path) or not value.is_absolute()):
                raise PrivatePlanningRetentionError(f"{field_name} must be an absolute Path")
        if type(self.owner_uid) is not int or self.owner_uid < 0:
            raise PrivatePlanningRetentionError("private planning owner uid is invalid")
        if type(self.encryption_at_rest_attested) is not bool:
            raise PrivatePlanningRetentionError("encryption_at_rest_attested must be a bool")
        if self.application_encryption is not False:
            raise PrivatePlanningRetentionError(
                "application-layer encryption is not implemented and must not be claimed"
            )
        _require_sha256(self.identity_sha256, field_name="placement identity")


@dataclass(frozen=True, slots=True)
class PrivatePlanningPublicationReceipt:
    """Path-free receipts named by one unresolved durable publication intent."""

    planning_generation_identity_sha256: str | None = None
    planning_generation_manifest_sha256: str | None = None
    private_baseline_receipt_sha256: str | None = None
    private_update_receipt_sha256: str | None = None
    planning_generation_id: str | None = None

    def __post_init__(self) -> None:
        named = 0
        for field_name in (
            "planning_generation_identity_sha256",
            "planning_generation_manifest_sha256",
            "private_baseline_receipt_sha256",
            "private_update_receipt_sha256",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            _require_sha256(value, field_name=field_name)
            named += 1
        if self.planning_generation_id is not None:
            if not isinstance(self.planning_generation_id, str) or not self.planning_generation_id:
                raise PrivatePlanningRetentionError(
                    "publication planning_generation_id must be a nonempty token"
                )
            named += 1
        if named == 0:
            raise PrivatePlanningRetentionError(
                "publication receipt must name at least one private authority"
            )


@dataclass(frozen=True, slots=True)
class PrivatePlanningCollectionReport:
    """Path-free identities deleted or retained by receipt-bound collection."""

    deleted_planning_generation_identity_sha256s: tuple[str, ...]
    deleted_planning_object_sha256s: tuple[str, ...]
    deleted_bronze_generation_identity_sha256s: tuple[str, ...]
    retained_planning_generation_identity_sha256s: tuple[str, ...]
    retained_private_receipt_sha256s: tuple[str, ...]


def provision_private_planning_storage(
    *,
    planning_store_root: Path,
    public_roots: Sequence[Path],
    monotonic_clock: Callable[[], float],
    planning_capture_root: Path | None = None,
    update_capture_root: Path | None = None,
    exclusion_roots: Sequence[Path] = (),
    placement_kind: PrivatePlanningPlacementKind = PrivatePlanningPlacementKind.FIXTURE,
    encryption_at_rest_attested: bool = False,
) -> PrivatePlanningStoragePlacement:
    """Create one caller-owned owner-only private planning store.

    The caller supplies every absolute path.  This function never guesses a
    default production location and never claims application ciphertext.
    """

    _require_posix_private_filesystem()
    if not isinstance(placement_kind, PrivatePlanningPlacementKind):
        raise PrivatePlanningRetentionError("private planning placement kind is invalid")
    if type(encryption_at_rest_attested) is not bool:
        raise PrivatePlanningRetentionError("encryption_at_rest_attested must be a bool")
    if (
        placement_kind is PrivatePlanningPlacementKind.PRODUCTION
        and encryption_at_rest_attested is not True
    ):
        raise PrivatePlanningRetentionError(
            "production private planning storage requires encryption-at-rest attestation"
        )

    store_root = _provision_owner_only_directory(
        planning_store_root,
        label="private planning store root",
    )
    capture_root = (
        None
        if planning_capture_root is None
        else _provision_owner_only_directory(
            planning_capture_root,
            label="private planning capture root",
        )
    )
    update_root = (
        None
        if update_capture_root is None
        else _provision_owner_only_directory(
            update_capture_root,
            label="private update capture root",
        )
    )
    public = _require_existing_public_roots(public_roots)
    exclusions = _require_existing_public_roots(exclusion_roots, label="exclusion root")
    private_roots = tuple(
        path for path in (store_root, capture_root, update_root) if path is not None
    )
    _require_disjoint_private_roots(private_roots, (*public, *exclusions))

    try:
        store = SuccessorPlanningStore(
            store_root,
            public_roots=public,
            monotonic_clock=monotonic_clock,
        )
        store.provision()
    except SuccessorPlanningStoreError as exc:
        raise PrivatePlanningRetentionError(str(exc)) from exc
    return _placement_from_roots(
        kind=placement_kind,
        planning_store_root=store_root,
        planning_capture_root=capture_root,
        update_capture_root=update_root,
        encryption_at_rest_attested=encryption_at_rest_attested,
    )


def require_private_planning_storage(
    *,
    planning_store_root: Path,
    public_roots: Sequence[Path],
    monotonic_clock: Callable[[], float],
    planning_capture_root: Path | None = None,
    update_capture_root: Path | None = None,
    exclusion_roots: Sequence[Path] = (),
    placement_kind: PrivatePlanningPlacementKind = PrivatePlanningPlacementKind.FIXTURE,
    encryption_at_rest_attested: bool = False,
) -> PrivatePlanningStoragePlacement:
    """Re-prove one already provisioned owner-only private planning store."""

    _require_posix_private_filesystem()
    if not isinstance(placement_kind, PrivatePlanningPlacementKind):
        raise PrivatePlanningRetentionError("private planning placement kind is invalid")
    if type(encryption_at_rest_attested) is not bool:
        raise PrivatePlanningRetentionError("encryption_at_rest_attested must be a bool")
    if (
        placement_kind is PrivatePlanningPlacementKind.PRODUCTION
        and encryption_at_rest_attested is not True
    ):
        raise PrivatePlanningRetentionError(
            "production private planning storage requires encryption-at-rest attestation"
        )

    store_root = _require_existing_owner_only_directory(
        planning_store_root,
        label="private planning store root",
    )
    capture_root = (
        None
        if planning_capture_root is None
        else _require_existing_owner_only_directory(
            planning_capture_root,
            label="private planning capture root",
        )
    )
    update_root = (
        None
        if update_capture_root is None
        else _require_existing_owner_only_directory(
            update_capture_root,
            label="private update capture root",
        )
    )
    public = _require_existing_public_roots(public_roots)
    exclusions = _require_existing_public_roots(exclusion_roots, label="exclusion root")
    private_roots = tuple(
        path for path in (store_root, capture_root, update_root) if path is not None
    )
    _require_disjoint_private_roots(private_roots, (*public, *exclusions))
    try:
        store = SuccessorPlanningStore(
            store_root,
            public_roots=public,
            monotonic_clock=monotonic_clock,
        )
        store.require_provisioned_layout()
    except SuccessorPlanningStoreError as exc:
        raise PrivatePlanningRetentionError(str(exc)) from exc
    return _placement_from_roots(
        kind=placement_kind,
        planning_store_root=store_root,
        planning_capture_root=capture_root,
        update_capture_root=update_root,
        encryption_at_rest_attested=encryption_at_rest_attested,
    )


def collect_unreferenced_private_planning_state(
    *,
    planning_store: SuccessorPlanningStore,
    generation_store: SuccessorGenerationStore,
    checkpoint_store: SuccessorCoordinatorCheckpointStore,
    budget: PlanningStoreBudget,
    planning_capture_root: Path | None = None,
    update_capture_root: Path | None = None,
    unresolved_publication_receipts: Sequence[PrivatePlanningPublicationReceipt] = (),
) -> PrivatePlanningCollectionReport:
    """Delete only private generations unreferenced by the retention window.

    Age is never consulted.  A missing current pointer may collect crash
    orphans only when no public generation exists.  Candidate, executing, or
    unassured public generations refuse the entire collection.
    """

    if not isinstance(planning_store, SuccessorPlanningStore):
        raise PrivatePlanningRetentionError("planning_store must be a SuccessorPlanningStore")
    if not isinstance(generation_store, SuccessorGenerationStore):
        raise PrivatePlanningRetentionError("generation_store must be a SuccessorGenerationStore")
    if not isinstance(checkpoint_store, SuccessorCoordinatorCheckpointStore):
        raise PrivatePlanningRetentionError(
            "checkpoint_store must be a SuccessorCoordinatorCheckpointStore"
        )
    if not isinstance(budget, PlanningStoreBudget):
        raise PrivatePlanningRetentionError("budget must be a PlanningStoreBudget")
    if any(
        not isinstance(item, PrivatePlanningPublicationReceipt)
        for item in unresolved_publication_receipts
    ):
        raise PrivatePlanningRetentionError(
            "unresolved publication receipts must be PrivatePlanningPublicationReceipt values"
        )

    try:
        window = generation_store.retained_private_receipts()
    except SuccessorGenerationStoreError as exc:
        raise PrivatePlanningRetentionError(str(exc)) from exc

    try:
        checkpoint = checkpoint_store.load()
    except Exception as exc:
        raise PrivatePlanningRetentionError(
            "unresolved coordinator checkpoint cannot be re-read"
        ) from exc

    retain_identities, retain_generation_ids = _retain_sets(
        window=window,
        checkpoint=checkpoint,
        publications=tuple(unresolved_publication_receipts),
        planning_store=planning_store,
    )
    try:
        planning_result = planning_store.collect_unreferenced(
            retain_identity_sha256s=retain_identities,
            retain_planning_generation_ids=retain_generation_ids,
            budget=budget,
        )
    except SuccessorPlanningStoreError as exc:
        raise PrivatePlanningRetentionError(str(exc)) from exc
    if not isinstance(planning_result, PlanningStoreCollectionResult):
        raise PrivatePlanningRetentionError("planning store collection result is invalid")

    bronze_retain_ids = frozenset(retain_generation_ids).union(
        planning_result.retained_planning_generation_ids
    )
    bronze_deleted = _collect_unreferenced_bronze_generations(
        roots=(planning_capture_root, update_capture_root),
        retain_identity_sha256s=retain_identities,
        retain_planning_generation_ids=bronze_retain_ids,
    )
    retained_receipts = tuple(sorted(retain_identities))
    return PrivatePlanningCollectionReport(
        deleted_planning_generation_identity_sha256s=(
            planning_result.deleted_generation_identity_sha256s
        ),
        deleted_planning_object_sha256s=planning_result.deleted_object_sha256s,
        deleted_bronze_generation_identity_sha256s=bronze_deleted,
        retained_planning_generation_identity_sha256s=(
            planning_result.retained_generation_identity_sha256s
        ),
        retained_private_receipt_sha256s=retained_receipts,
    )


def _retain_sets(
    *,
    window: SuccessorPrivateRetentionReceipts,
    checkpoint: SuccessorCoordinatorCheckpoint | None,
    publications: tuple[PrivatePlanningPublicationReceipt, ...],
    planning_store: SuccessorPlanningStore,
) -> tuple[frozenset[str], frozenset[str]]:
    identities: set[str] = set(window.identity_sha256s)
    generation_ids: set[str] = set(window.planning_generation_ids)
    if checkpoint is not None and checkpoint.phase is not SuccessorCoordinatorPhase.PROMOTED:
        identities.update(_checkpoint_identity_receipts(checkpoint, planning_store=planning_store))
        generation_ids.update(_checkpoint_planning_generation_ids(checkpoint))
    for receipt in publications:
        if receipt.planning_generation_identity_sha256 is not None:
            identities.add(receipt.planning_generation_identity_sha256)
        if receipt.planning_generation_manifest_sha256 is not None:
            identities.add(receipt.planning_generation_manifest_sha256)
        if receipt.private_baseline_receipt_sha256 is not None:
            identities.add(receipt.private_baseline_receipt_sha256)
        if receipt.private_update_receipt_sha256 is not None:
            identities.add(receipt.private_update_receipt_sha256)
        if receipt.planning_generation_id is not None:
            generation_ids.add(receipt.planning_generation_id)
    return frozenset(identities), frozenset(generation_ids)


def _checkpoint_identity_receipts(
    checkpoint: SuccessorCoordinatorCheckpoint,
    *,
    planning_store: SuccessorPlanningStore,
) -> frozenset[str]:
    receipts: set[str] = {checkpoint.baseline.private_baseline_receipt_sha256}
    planning_generation_id = _checkpoint_primary_planning_generation_id(checkpoint)
    receipts.add(
        planning_store.generation_identity(checkpoint.planning_request, planning_generation_id)
    )
    evidence = checkpoint.planning_evidence
    if evidence is not None:
        manifest = evidence.planning_generation_manifest
        receipts.add(manifest.identity_sha256)
        receipts.add(manifest.artifact_identity.planning_manifest_sha256)
        receipts.add(manifest.artifact_identity.private_generation_identity_sha256)
        for wave in manifest.waves:
            receipts.add(wave.private_generation_identity_sha256)
    if checkpoint.intent is not None:
        receipts.add(checkpoint.intent.planning_generation_manifest_sha256)
    if checkpoint.transaction is not None:
        receipts.add(checkpoint.transaction.generation_identity_sha256)
        receipts.add(checkpoint.transaction.baseline.private_baseline_receipt_sha256)
        receipts.add(checkpoint.transaction.intent.planning_generation_manifest_sha256)
        if checkpoint.transaction.assurance is not None:
            receipts.add(checkpoint.transaction.assurance.private_generation_receipt_sha256)
    if checkpoint.update_private_generation is not None:
        receipts.add(checkpoint.update_private_generation.identity_sha256)
    if checkpoint.assurance is not None:
        receipts.add(checkpoint.assurance.private_generation_receipt_sha256)
    return frozenset(receipts)


def _checkpoint_planning_generation_ids(
    checkpoint: SuccessorCoordinatorCheckpoint,
) -> frozenset[str]:
    return frozenset({_checkpoint_primary_planning_generation_id(checkpoint)})


def _checkpoint_primary_planning_generation_id(
    checkpoint: SuccessorCoordinatorCheckpoint,
) -> str:
    evidence = checkpoint.planning_evidence
    if evidence is not None:
        return evidence.planning_generation_manifest.artifact_identity.planning_generation_id
    return deterministic_planning_generation_id(checkpoint.planning_request)


def _collect_unreferenced_bronze_generations(
    *,
    roots: tuple[Path | None, ...],
    retain_identity_sha256s: frozenset[str],
    retain_planning_generation_ids: frozenset[str],
) -> tuple[str, ...]:
    deleted: list[str] = []
    for root in roots:
        if root is None:
            continue
        observed_root = _require_existing_owner_only_directory(
            root,
            label="private capture root",
        )
        for child in _owner_only_child_directories(observed_root, label="private capture root"):
            if _bronze_generation_retained(
                child,
                retain_identity_sha256s=retain_identity_sha256s,
                retain_planning_generation_ids=retain_planning_generation_ids,
            ):
                continue
            deleted.append(_bronze_deleted_identity(child))
            _remove_owner_only_tree(child, expected_parent=observed_root)
    return tuple(sorted(deleted))


def _bronze_generation_retained(
    path: Path,
    *,
    retain_identity_sha256s: frozenset[str],
    retain_planning_generation_ids: frozenset[str],
) -> bool:
    name = path.name
    return name in retain_planning_generation_ids or name in retain_identity_sha256s


def _bronze_deleted_identity(path: Path) -> str:
    if _is_sha256(path.name):
        return path.name
    return hashlib.sha256(path.name.encode("utf-8")).hexdigest()


def _placement_from_roots(
    *,
    kind: PrivatePlanningPlacementKind,
    planning_store_root: Path,
    planning_capture_root: Path | None,
    update_capture_root: Path | None,
    encryption_at_rest_attested: bool,
) -> PrivatePlanningStoragePlacement:
    owner_uid = os.geteuid()
    payload: dict[str, object] = {
        "domain": _PLACEMENT_DOMAIN,
        "schema_version": PRIVATE_PLANNING_PLACEMENT_SCHEMA_VERSION,
        "kind": kind.value,
        "encryption_at_rest_attested": encryption_at_rest_attested,
        "application_encryption": False,
        "owner_uid": owner_uid,
        "directory_mode": _PRIVATE_DIRECTORY_MODE,
        "lock_mode": _PRIVATE_LOCK_MODE,
        "committed_object_mode": _COMMITTED_OBJECT_MODE,
        "planning_store": _inode_payload(planning_store_root),
        "planning_capture": (
            None if planning_capture_root is None else _inode_payload(planning_capture_root)
        ),
        "update_capture": (
            None if update_capture_root is None else _inode_payload(update_capture_root)
        ),
    }
    return PrivatePlanningStoragePlacement(
        kind=kind,
        planning_store_root=planning_store_root,
        planning_capture_root=planning_capture_root,
        update_capture_root=update_capture_root,
        owner_uid=owner_uid,
        encryption_at_rest_attested=encryption_at_rest_attested,
        application_encryption=False,
        identity_sha256=canonical_sha256(payload),
    )


def _inode_payload(path: Path) -> dict[str, int]:
    observed = os.stat(path, follow_symlinks=False)
    return {"dev": observed.st_dev, "ino": observed.st_ino}


def _require_posix_private_filesystem() -> None:
    if os.name != "posix" or not getattr(os, "O_NOFOLLOW", 0):
        raise PrivatePlanningRetentionError(
            "private planning storage requires POSIX O_NOFOLLOW and advisory locks"
        )


def _require_existing_public_roots(
    roots: Sequence[Path],
    *,
    label: str = "public root",
) -> tuple[Path, ...]:
    if any(not isinstance(item, Path) for item in roots):
        raise PrivatePlanningRetentionError(f"every {label} must be an explicit Path")
    return tuple(_require_existing_regular_directory(item, label=label) for item in roots)


def _require_disjoint_private_roots(
    private_roots: Sequence[Path],
    forbidden_roots: Sequence[Path],
) -> None:
    observed_private = tuple((path, os.stat(path, follow_symlinks=False)) for path in private_roots)
    for index, (left, left_stat) in enumerate(observed_private):
        for right, right_stat in observed_private[index + 1 :]:
            if _paths_overlap(left, right, left_stat=left_stat, right_stat=right_stat):
                raise PrivatePlanningRetentionError(
                    "private planning roots must be pairwise disjoint"
                )
    for public_root in forbidden_roots:
        public_stat = os.stat(public_root, follow_symlinks=False)
        for private_root, private_stat in observed_private:
            if _paths_overlap(
                private_root,
                public_root,
                left_stat=private_stat,
                right_stat=public_stat,
            ):
                raise PrivatePlanningRetentionError(
                    "private planning storage must not overlap a public tree"
                )


def _provision_owner_only_directory(path: Path, *, label: str) -> Path:
    exact = _require_absolute_non_aliased_path(path, label=label)
    if exact.exists() or exact.is_symlink():
        return _require_existing_owner_only_directory(exact, label=label)
    parent = _require_existing_regular_directory(exact.parent, label=f"{label} parent")
    try:
        os.mkdir(exact, mode=_PRIVATE_DIRECTORY_MODE)
    except OSError as exc:
        raise PrivatePlanningRetentionError(f"{label} cannot be created") from exc
    observed = _require_existing_owner_only_directory(exact, label=label)
    parent_after = os.stat(parent, follow_symlinks=False)
    if not stat.S_ISDIR(parent_after.st_mode):
        raise PrivatePlanningRetentionError(f"{label} parent changed while created")
    return observed


def _require_existing_owner_only_directory(path: Path, *, label: str) -> Path:
    exact = _require_existing_regular_directory(path, label=label)
    try:
        observed = os.stat(exact, follow_symlinks=False)
    except OSError as exc:
        raise PrivatePlanningRetentionError(f"{label} cannot be inspected") from exc
    if os.geteuid() != observed.st_uid or stat.S_IMODE(observed.st_mode) != _PRIVATE_DIRECTORY_MODE:
        raise PrivatePlanningRetentionError(f"{label} must remain owner-only mode 0700")
    return exact


def _require_existing_regular_directory(path: Path, *, label: str) -> Path:
    exact = _require_absolute_non_aliased_path(path, label=label)
    try:
        observed = os.stat(exact, follow_symlinks=False)
    except OSError as exc:
        raise PrivatePlanningRetentionError(f"{label} must exist") from exc
    if exact.is_symlink() or not stat.S_ISDIR(observed.st_mode):
        raise PrivatePlanningRetentionError(f"{label} must be a non-symlink directory")
    return exact


def _require_absolute_non_aliased_path(path: Path, *, label: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise PrivatePlanningRetentionError(f"{label} must be an absolute Path")
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise PrivatePlanningRetentionError(f"{label} cannot be resolved exactly") from exc
    if resolved != path:
        raise PrivatePlanningRetentionError(
            f"{label} must not contain lexical aliases or symlink ancestors"
        )
    current = path
    while True:
        if current.is_symlink():
            raise PrivatePlanningRetentionError(
                f"{label} must not contain lexical aliases or symlink ancestors"
            )
        if current == current.parent:
            break
        current = current.parent
    return path


def _paths_overlap(
    left: Path,
    right: Path,
    *,
    left_stat: os.stat_result,
    right_stat: os.stat_result,
) -> bool:
    left_parts = tuple(part.casefold() for part in left.parts)
    right_parts = tuple(part.casefold() for part in right.parts)
    return (
        left == right
        or left.is_relative_to(right)
        or right.is_relative_to(left)
        or left_parts[: len(right_parts)] == right_parts
        or right_parts[: len(left_parts)] == left_parts
        or (left_stat.st_dev, left_stat.st_ino) == (right_stat.st_dev, right_stat.st_ino)
    )


def _owner_only_child_directories(root: Path, *, label: str) -> tuple[Path, ...]:
    try:
        with os.scandir(root) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as exc:
        raise PrivatePlanningRetentionError(f"{label} cannot be listed") from exc
    children: list[Path] = []
    for entry in entries:
        child = root / entry.name
        if entry.is_symlink():
            raise PrivatePlanningRetentionError(f"{label} contains a symlink")
        if entry.name.startswith("."):
            if entry.name.endswith(".tmp") and entry.is_dir(follow_symlinks=False):
                children.append(child)
                continue
            continue
        if not entry.is_dir(follow_symlinks=False):
            raise PrivatePlanningRetentionError(f"{label} contains a non-directory entry")
        children.append(child)
    return tuple(children)


def _remove_owner_only_tree(path: Path, *, expected_parent: Path) -> None:
    if path.parent != expected_parent or path.is_symlink() or not path.is_dir():
        raise PrivatePlanningRetentionError(
            "private capture generation must be a direct regular directory"
        )
    for root, dir_names, file_names in os.walk(path, topdown=True, followlinks=False):
        root_path = Path(root)
        os.chmod(root_path, _PRIVATE_DIRECTORY_MODE)
        for name in (*dir_names, *file_names):
            child = root_path / name
            if child.is_symlink():
                raise PrivatePlanningRetentionError("private capture generation contains a symlink")
            os.chmod(
                child,
                _PRIVATE_DIRECTORY_MODE if child.is_dir() else _PRIVATE_LOCK_MODE,
            )
    for root, dir_names, file_names in os.walk(path, topdown=False, followlinks=False):
        root_path = Path(root)
        for name in file_names:
            (root_path / name).unlink()
        for name in dir_names:
            (root_path / name).rmdir()
    path.rmdir()


def _require_sha256(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PrivatePlanningRetentionError(f"{field_name} must be a lowercase SHA-256")
    return value


def _is_sha256(value: str) -> bool:
    return len(value) == _SHA256_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )
