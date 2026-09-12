"""Reverify retained private Bronze generations for committed planning waves."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from nbadb.core.errors import ExtractionError
from nbadb.extract.bronze import BronzeLimits
from nbadb.orchestrate.capture_session import (
    CaptureSessionContractError,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
    require_planning_wave_ownership,
)
from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningRequest,
)
from nbadb.orchestrate.successor_planning_store import (
    CommittedPlanningWaveAuthority,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "RetainedBronzePlanningResolver",
    "RetainedBronzePlanningResolverError",
]

_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}")


class RetainedBronzePlanningResolverError(RuntimeError):
    """Raised when retained private planning evidence cannot be reverified."""


def _require_absolute_path(value: object, *, label: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise RetainedBronzePlanningResolverError(f"{label} must be an absolute Path")
    return Path(os.path.abspath(value))


def _reject_symlink_traversal(path: Path, *, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            observed = os.lstat(current)
        except OSError as exc:
            raise RetainedBronzePlanningResolverError(f"{label} must exist") from exc
        if stat.S_ISLNK(observed.st_mode):
            raise RetainedBronzePlanningResolverError(f"{label} cannot traverse a symlink")


def _existing_directory(path: Path, *, label: str, owner_only: bool) -> os.stat_result:
    _reject_symlink_traversal(path, label=label)
    try:
        observed = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise RetainedBronzePlanningResolverError(f"{label} must exist") from exc
    if not stat.S_ISDIR(observed.st_mode):
        raise RetainedBronzePlanningResolverError(f"{label} must be a regular directory")
    if (
        owner_only
        and os.name == "posix"
        and (observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != 0o700)
    ):
        raise RetainedBronzePlanningResolverError(f"{label} must be an owner-only 0700 directory")
    return observed


def _directory_identity(observed: os.stat_result) -> tuple[int, int]:
    return observed.st_dev, observed.st_ino


def _has_ancestor_identity(path: Path, identity: tuple[int, int]) -> bool:
    current = path
    while True:
        observed = os.stat(current, follow_symlinks=False)
        if _directory_identity(observed) == identity:
            return True
        if current == current.parent:
            return False
        current = current.parent


def _overlaps_existing(
    left: Path,
    right: Path,
    *,
    left_stat: os.stat_result,
    right_stat: os.stat_result,
) -> bool:
    """Reject lexical and same-inode ancestor aliases on case-folding filesystems."""

    left_identity = _directory_identity(left_stat)
    right_identity = _directory_identity(right_stat)
    return (
        left == right
        or left.is_relative_to(right)
        or right.is_relative_to(left)
        or left_identity == right_identity
        or _has_ancestor_identity(left, right_identity)
        or _has_ancestor_identity(right, left_identity)
    )


def _require_unchanged_directory(
    path: Path,
    expected: os.stat_result,
    *,
    label: str,
    owner_only: bool,
) -> os.stat_result:
    observed = _existing_directory(path, label=label, owner_only=owner_only)
    if _directory_identity(observed) != _directory_identity(expected):
        raise RetainedBronzePlanningResolverError(f"{label} changed identity")
    return observed


class RetainedBronzePlanningResolver:
    """Resolve a committed wave only by freshly inventorying retained Bronze v6."""

    def __init__(
        self,
        capture_base: Path,
        *,
        limits: BronzeLimits,
        public_roots: Sequence[Path],
        planning_store_root: Path,
    ) -> None:
        if not isinstance(limits, BronzeLimits):
            raise RetainedBronzePlanningResolverError("limits must be a BronzeLimits value")
        capture = _require_absolute_path(capture_base, label="capture base")
        planning = _require_absolute_path(planning_store_root, label="planning store root")
        public = tuple(_require_absolute_path(item, label="public root") for item in public_roots)
        if not public:
            raise RetainedBronzePlanningResolverError(
                "public_roots must contain at least one public root"
            )
        capture_stat = _existing_directory(capture, label="capture base", owner_only=True)
        planning_stat = _existing_directory(
            planning,
            label="planning store root",
            owner_only=True,
        )
        public_stats = tuple(
            _existing_directory(root, label="public root", owner_only=False) for root in public
        )
        roots = (capture, planning, *public)
        root_stats = (capture_stat, planning_stat, *public_stats)
        for index, left in enumerate(roots):
            for right_index in range(index + 1, len(roots)):
                if _overlaps_existing(
                    left,
                    roots[right_index],
                    left_stat=root_stats[index],
                    right_stat=root_stats[right_index],
                ):
                    raise RetainedBronzePlanningResolverError(
                        "capture, planning-store, and public roots must be disjoint"
                    )
        self._capture_base = capture
        self._limits = limits
        self._public_roots = public
        self._planning_store_root = planning
        self._capture_base_stat = capture_stat
        self._planning_store_root_stat = planning_stat
        self._public_root_stats = public_stats

    def verify(
        self,
        *,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        authority: CommittedPlanningWaveAuthority,
    ) -> PrivateGenerationIdentity:
        """Return identity only after a fresh exact Bronze inventory succeeds."""

        if not isinstance(request, SuccessorPlanningRequest):
            raise RetainedBronzePlanningResolverError("request must be a SuccessorPlanningRequest")
        if (
            not isinstance(planning_generation_id, str)
            or _SAFE_TOKEN_RE.fullmatch(planning_generation_id) is None
        ):
            raise RetainedBronzePlanningResolverError(
                "planning_generation_id must be a safe nonempty token"
            )
        if not isinstance(authority, CommittedPlanningWaveAuthority):
            raise RetainedBronzePlanningResolverError(
                "authority must be a CommittedPlanningWaveAuthority"
            )
        receipt = authority.completion_receipt
        private = authority.private_generation_identity
        if (
            receipt.planning_request_sha256 != request.identity_sha256
            or receipt.planning_generation_id != planning_generation_id
            or receipt.wave_index != authority.wave_index
            or receipt.capture_scope.semantic_source_sha != request.source_sha
            or receipt.capture_scope.workflow_run_id != request.workflow_run_id
            or receipt.capture_scope.workflow_run_attempt != request.workflow_run_attempt
            or private.semantic_source_sha != request.source_sha
            or private.workflow_run_id != request.workflow_run_id
            or private.workflow_run_attempt != request.workflow_run_attempt
            or receipt.private_generation_identity.canonical_bytes != private.canonical_bytes
            or hashlib.sha256(private.canonical_bytes).hexdigest()
            != authority.private_generation_identity_sha256
            or len(private.canonical_bytes) != authority.private_generation_identity_bytes
            or hashlib.sha256(receipt.canonical_bytes).hexdigest()
            != authority.completion_receipt_sha256
            or len(receipt.canonical_bytes) != authority.completion_receipt_bytes
        ):
            raise RetainedBronzePlanningResolverError(
                "committed planning wave authority differs from request or retained identity"
            )

        try:
            require_planning_wave_ownership(
                planning_generation_id=planning_generation_id,
                wave_index=authority.wave_index,
                chain_id=receipt.capture_scope.chain_id,
                lane_id=receipt.capture_scope.lane_id,
            )
            require_planning_wave_ownership(
                planning_generation_id=planning_generation_id,
                wave_index=authority.wave_index,
                chain_id=private.chain_id,
                lane_id=private.lane_id,
            )
        except CaptureSessionContractError as exc:
            raise RetainedBronzePlanningResolverError(
                "committed planning wave uses update-execution or otherwise "
                "foreign capture ownership"
            ) from exc

        capture_base_stat = _require_unchanged_directory(
            self._capture_base,
            self._capture_base_stat,
            label="capture base",
            owner_only=True,
        )
        planning_store_stat = _require_unchanged_directory(
            self._planning_store_root,
            self._planning_store_root_stat,
            label="planning store root",
            owner_only=True,
        )
        public_stats = tuple(
            _require_unchanged_directory(
                root,
                expected,
                label="public root",
                owner_only=False,
            )
            for root, expected in zip(
                self._public_roots,
                self._public_root_stats,
                strict=True,
            )
        )
        generation_root = self._capture_base / planning_generation_id
        wave_root = generation_root / f"wave-{authority.wave_index}"
        generation_stat = _existing_directory(
            generation_root,
            label="retained planning generation root",
            owner_only=True,
        )
        wave_stat = _existing_directory(
            wave_root,
            label="retained planning wave root",
            owner_only=True,
        )
        other_roots = (self._planning_store_root, *self._public_roots)
        other_stats = (planning_store_stat, *public_stats)
        for other, other_stat in zip(other_roots, other_stats, strict=True):
            if _overlaps_existing(
                wave_root,
                other,
                left_stat=wave_stat,
                right_stat=other_stat,
            ):
                raise RetainedBronzePlanningResolverError(
                    "retained planning wave root overlaps another authority root"
                )

        session: PrivateCaptureSession | None = None
        try:
            session = PrivateCaptureSession.open_existing(
                wave_root,
                limits=self._limits,
                public_roots=self._public_roots,
                scope=receipt.capture_scope,
                expected_root_identity=(wave_stat.st_dev, wave_stat.st_ino),
            )
            _require_unchanged_directory(
                self._capture_base,
                capture_base_stat,
                label="capture base",
                owner_only=True,
            )
            _require_unchanged_directory(
                generation_root,
                generation_stat,
                label="retained planning generation root",
                owner_only=True,
            )
            _require_unchanged_directory(
                wave_root,
                wave_stat,
                label="retained planning wave root",
                owner_only=True,
            )
            restored = session.restore_sealed_identity_if_present()
            if restored is None:
                raise RetainedBronzePlanningResolverError("retained planning wave is not sealed")
            if restored.canonical_bytes != private.canonical_bytes:
                raise RetainedBronzePlanningResolverError(
                    "fresh Bronze identity differs from committed planning authority"
                )
            member_roots = tuple(
                sorted({item.logical_call_receipt_sha256 for item in receipt.members})
            )
            binding_roots = tuple(
                item.logical_call_receipt_sha256 for item in receipt.logical_call_bindings
            )
            if (
                not restored.done_call_receipt_sha256s
                or restored.done_call_receipt_sha256s != member_roots
                or restored.done_call_receipt_sha256s != binding_roots
            ):
                raise RetainedBronzePlanningResolverError(
                    "sealed planning calls are not bound to planning-member receipts"
                )
            _require_unchanged_directory(
                self._capture_base,
                capture_base_stat,
                label="capture base",
                owner_only=True,
            )
            _require_unchanged_directory(
                generation_root,
                generation_stat,
                label="retained planning generation root",
                owner_only=True,
            )
            _require_unchanged_directory(
                wave_root,
                wave_stat,
                label="retained planning wave root",
                owner_only=True,
            )
            return restored
        except RetainedBronzePlanningResolverError:
            raise
        except (ExtractionError, OSError, TypeError, ValueError) as exc:
            raise RetainedBronzePlanningResolverError(
                "retained planning Bronze generation is invalid"
            ) from exc
        finally:
            if session is not None:
                session.close()
