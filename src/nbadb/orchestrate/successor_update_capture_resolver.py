"""Freshly reverify one retained successor-update Bronze generation."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, cast

from nbadb.core.errors import ExtractionError
from nbadb.extract.bronze import BronzeLimits
from nbadb.orchestrate.capture_session import (
    CaptureRunScope,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
)
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_update_contract import (
    ObservedDeltaReceipt,
    SuccessorUpdateContractError,
    SuccessorUpdateTransaction,
    UpdateScopeClosureEvidenceKind,
    require_live_and_scoreboard_update_delta_closure,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "RetainedBronzeUpdateResolver",
    "RetainedBronzeUpdateResolverError",
]

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | _NOFOLLOW
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)


class RetainedBronzeUpdateResolverError(RuntimeError):
    """Raised when retained update parser-input authority cannot be reverified."""


def _identity(observed: os.stat_result) -> tuple[int, int]:
    return observed.st_dev, observed.st_ino


def _expected_identity(value: object, *, label: str) -> tuple[int, int]:
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(item) is not int or item < 0 for item in value)
    ):
        raise RetainedBronzeUpdateResolverError(f"{label} must be a (device, inode) integer pair")
    return cast("tuple[int, int]", value)


def _exact_absolute_path(value: object, *, label: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise RetainedBronzeUpdateResolverError(f"{label} must be an absolute Path")
    try:
        resolved = value.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RetainedBronzeUpdateResolverError(f"{label} must exist") from exc
    if resolved != value:
        raise RetainedBronzeUpdateResolverError(
            f"{label} must be exact and cannot contain aliases or symlink ancestors"
        )
    return value


def _require_directory(
    observed: os.stat_result,
    *,
    label: str,
    owner_only: bool,
) -> None:
    if not stat.S_ISDIR(observed.st_mode):
        raise RetainedBronzeUpdateResolverError(f"{label} must be a directory")
    if (
        owner_only
        and os.name == "posix"
        and (observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != 0o700)
    ):
        raise RetainedBronzeUpdateResolverError(f"{label} must be an owner-only 0700 directory")


def _open_named_directory(
    path: Path,
    *,
    label: str,
    owner_only: bool,
    expected: tuple[int, int] | None = None,
) -> tuple[int, os.stat_result]:
    if not _NOFOLLOW:
        raise RetainedBronzeUpdateResolverError(
            "retained update verification requires POSIX O_NOFOLLOW support"
        )
    descriptor = -1
    try:
        descriptor = os.open(path, _DIRECTORY_FLAGS)
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        _require_directory(opened, label=label, owner_only=owner_only)
        _require_directory(named, label=label, owner_only=owner_only)
        if _identity(opened) != _identity(named):
            raise RetainedBronzeUpdateResolverError(f"{label} changed identity while opening")
        if expected is not None and _identity(opened) != expected:
            raise RetainedBronzeUpdateResolverError(f"{label} differs from its expected inode")
        return descriptor, opened
    except RetainedBronzeUpdateResolverError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise RetainedBronzeUpdateResolverError(f"{label} cannot be opened safely") from exc


def _open_direct_child_directory(
    parent_descriptor: int,
    child_name: str,
    *,
    label: str,
) -> tuple[int, os.stat_result]:
    descriptor = -1
    try:
        descriptor = os.open(child_name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(
            child_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        _require_directory(opened, label=label, owner_only=True)
        _require_directory(named, label=label, owner_only=True)
        if _identity(opened) != _identity(named):
            raise RetainedBronzeUpdateResolverError(f"{label} changed identity while opening")
        return descriptor, opened
    except RetainedBronzeUpdateResolverError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise RetainedBronzeUpdateResolverError(f"{label} cannot be opened safely") from exc


def _require_named_inode(
    path: Path,
    descriptor: int,
    expected: tuple[int, int],
    *,
    label: str,
    owner_only: bool,
) -> None:
    try:
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise RetainedBronzeUpdateResolverError(f"{label} changed identity") from exc
    _require_directory(opened, label=label, owner_only=owner_only)
    _require_directory(named, label=label, owner_only=owner_only)
    if _identity(opened) != expected or _identity(named) != expected:
        raise RetainedBronzeUpdateResolverError(f"{label} changed identity")


def _require_child_inode(
    parent_descriptor: int,
    child_name: str,
    child_descriptor: int,
    expected: tuple[int, int],
    *,
    label: str,
) -> None:
    try:
        opened = os.fstat(child_descriptor)
        named = os.stat(
            child_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise RetainedBronzeUpdateResolverError(f"{label} changed identity") from exc
    _require_directory(opened, label=label, owner_only=True)
    _require_directory(named, label=label, owner_only=True)
    if _identity(opened) != expected or _identity(named) != expected:
        raise RetainedBronzeUpdateResolverError(f"{label} changed identity")


def _overlaps(
    left: Path, right: Path, left_identity: tuple[int, int], right_identity: tuple[int, int]
) -> bool:
    return (
        left == right
        or left.is_relative_to(right)
        or right.is_relative_to(left)
        or left_identity == right_identity
        or _has_ancestor_identity(left, right_identity)
        or _has_ancestor_identity(right, left_identity)
    )


def _has_ancestor_identity(path: Path, identity: tuple[int, int]) -> bool:
    """Match ancestors by inode so case-folded aliases cannot hide overlap."""

    current = path
    while True:
        observed = os.stat(current, follow_symlinks=False)
        if _identity(observed) == identity:
            return True
        if current == current.parent:
            return False
        current = current.parent


class RetainedBronzeUpdateResolver:
    """Resolve only an exact, freshly inventoried retained Bronze-v6 generation."""

    def __init__(self, capture_base: Path, *, limits: BronzeLimits) -> None:
        if not isinstance(limits, BronzeLimits):
            raise RetainedBronzeUpdateResolverError("limits must be a BronzeLimits value")
        capture = _exact_absolute_path(capture_base, label="capture base")
        descriptor, observed = _open_named_directory(
            capture,
            label="capture base",
            owner_only=True,
        )
        os.close(descriptor)
        self._capture_base = capture
        self._capture_base_identity = _identity(observed)
        self._limits = limits

    @staticmethod
    def _scope(
        transaction: SuccessorUpdateTransaction,
        planning_request: SuccessorPlanningRequest,
    ) -> CaptureRunScope:
        if (
            planning_request.baseline_identity_sha256 != transaction.baseline.identity_sha256
            or planning_request.mode is not transaction.intent.mode
            or planning_request.source_sha != transaction.intent.source_sha
            or planning_request.cutoff_utc != transaction.intent.cutoff_utc
            or planning_request.as_of_utc != transaction.intent.as_of_utc
        ):
            raise RetainedBronzeUpdateResolverError(
                "planning request differs from the successor transaction"
            )
        return CaptureRunScope(
            semantic_source_sha=transaction.intent.source_sha,
            chain_id=transaction.baseline.chain_id,
            lane_id=transaction.generation_identity_sha256,
            workflow_run_id=planning_request.workflow_run_id,
            workflow_run_attempt=planning_request.workflow_run_attempt,
        )

    @staticmethod
    def _require_expected_identity(
        expected: PrivateGenerationIdentity,
        *,
        transaction: SuccessorUpdateTransaction,
        scope: CaptureRunScope,
    ) -> None:
        if (
            expected.semantic_source_sha != scope.semantic_source_sha
            or expected.chain_id != scope.chain_id
            or expected.lane_id != scope.lane_id
            or expected.workflow_run_id != scope.workflow_run_id
            or expected.workflow_run_attempt != scope.workflow_run_attempt
            or expected.provider_authority_sha256 != transaction.baseline.provider_authority_sha256
        ):
            raise RetainedBronzeUpdateResolverError(
                "expected private generation differs from the transaction or planning request"
            )

    def require_update_replacement_delta_closure(
        self,
        *,
        transaction: SuccessorUpdateTransaction,
        planning_request: SuccessorPlanningRequest,
        observed_delta_receipts: Sequence[ObservedDeltaReceipt] = (),
        sealed_live_game_ids: Sequence[object] | None = None,
        evidence_kind: UpdateScopeClosureEvidenceKind,
    ) -> tuple[ObservedDeltaReceipt, ...]:
        """Refuse capture, journal, or retained Bronze as live/scoreboard update closure."""

        if not isinstance(transaction, SuccessorUpdateTransaction):
            raise RetainedBronzeUpdateResolverError(
                "transaction must be a SuccessorUpdateTransaction"
            )
        if not isinstance(planning_request, SuccessorPlanningRequest):
            raise RetainedBronzeUpdateResolverError(
                "planning_request must be a SuccessorPlanningRequest"
            )
        if not isinstance(evidence_kind, UpdateScopeClosureEvidenceKind):
            raise RetainedBronzeUpdateResolverError(
                "evidence_kind must be an UpdateScopeClosureEvidenceKind"
            )
        self._scope(transaction, planning_request)
        try:
            return require_live_and_scoreboard_update_delta_closure(
                transaction.intent.requested_scopes,
                observed_delta_receipts=observed_delta_receipts,
                evidence_kind=evidence_kind,
                sealed_live_game_ids=sealed_live_game_ids,
            )
        except SuccessorUpdateContractError as exc:
            raise RetainedBronzeUpdateResolverError(str(exc)) from exc

    def verify(
        self,
        *,
        transaction: SuccessorUpdateTransaction,
        planning_request: SuccessorPlanningRequest,
        candidate_public_root: Path,
        expected_public_root_identity: tuple[int, int],
        expected_identity: PrivateGenerationIdentity,
    ) -> PrivateGenerationIdentity:
        """Freshly restore a sealed identity through exact private/public inodes."""

        if not isinstance(transaction, SuccessorUpdateTransaction):
            raise RetainedBronzeUpdateResolverError(
                "transaction must be a SuccessorUpdateTransaction"
            )
        if not isinstance(planning_request, SuccessorPlanningRequest):
            raise RetainedBronzeUpdateResolverError(
                "planning_request must be a SuccessorPlanningRequest"
            )
        if not isinstance(expected_identity, PrivateGenerationIdentity):
            raise RetainedBronzeUpdateResolverError(
                "expected_identity must be a PrivateGenerationIdentity"
            )
        public_expected = _expected_identity(
            expected_public_root_identity,
            label="expected_public_root_identity",
        )
        public_root = _exact_absolute_path(
            candidate_public_root,
            label="candidate public root",
        )
        scope = self._scope(transaction, planning_request)
        self._require_expected_identity(expected_identity, transaction=transaction, scope=scope)

        capture_descriptor = generation_descriptor = public_descriptor = -1
        session: PrivateCaptureSession | None = None
        try:
            capture_descriptor, capture_stat = _open_named_directory(
                self._capture_base,
                label="capture base",
                owner_only=True,
                expected=self._capture_base_identity,
            )
            generation_name = transaction.generation_identity_sha256
            generation_descriptor, generation_stat = _open_direct_child_directory(
                capture_descriptor,
                generation_name,
                label="retained update generation root",
            )
            public_descriptor, public_stat = _open_named_directory(
                public_root,
                label="candidate public root",
                owner_only=False,
                expected=public_expected,
            )
            capture_identity = _identity(capture_stat)
            generation_identity = _identity(generation_stat)
            public_identity = _identity(public_stat)
            generation_root = self._capture_base / generation_name
            if _overlaps(
                self._capture_base,
                public_root,
                capture_identity,
                public_identity,
            ) or _overlaps(
                generation_root,
                public_root,
                generation_identity,
                public_identity,
            ):
                raise RetainedBronzeUpdateResolverError(
                    "private capture and candidate public roots must be disjoint"
                )

            def bracket() -> None:
                _require_named_inode(
                    self._capture_base,
                    capture_descriptor,
                    capture_identity,
                    label="capture base",
                    owner_only=True,
                )
                _require_child_inode(
                    capture_descriptor,
                    generation_name,
                    generation_descriptor,
                    generation_identity,
                    label="retained update generation root",
                )
                _require_named_inode(
                    public_root,
                    public_descriptor,
                    public_identity,
                    label="candidate public root",
                    owner_only=False,
                )

            bracket()
            session = PrivateCaptureSession.open_existing(
                generation_root,
                limits=self._limits,
                public_roots=(public_root,),
                scope=scope,
                expected_root_identity=generation_identity,
            )
            bracket()
            restored = session.restore_sealed_identity_if_present()
            bracket()
            if restored is None:
                raise RetainedBronzeUpdateResolverError("retained update generation is not sealed")
            if restored.canonical_bytes != expected_identity.canonical_bytes:
                raise RetainedBronzeUpdateResolverError(
                    "fresh Bronze identity differs from the expected update authority"
                )
            closed = session.close()
            if (
                not isinstance(closed, PrivateGenerationIdentity)
                or closed.canonical_bytes != expected_identity.canonical_bytes
            ):
                raise RetainedBronzeUpdateResolverError(
                    "retained update generation changed while releasing ownership"
                )
            bracket()
            return restored
        except RetainedBronzeUpdateResolverError:
            raise
        except (ExtractionError, OSError, TypeError, ValueError) as exc:
            raise RetainedBronzeUpdateResolverError(
                "retained update Bronze generation is invalid"
            ) from exc
        finally:
            try:
                if session is not None:
                    session.close()
            finally:
                for descriptor in (
                    public_descriptor,
                    generation_descriptor,
                    capture_descriptor,
                ):
                    if descriptor >= 0:
                        os.close(descriptor)
