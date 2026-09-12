"""Atomic pointer promotion for validated daily/monthly successor generations."""

from __future__ import annotations

import errno
import hashlib
import importlib
import json
import math
import os
import secrets
import shutil
import stat
import threading
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final, cast

from nbadb.core.artifact_identity import inventory_regular_tree
from nbadb.orchestrate import successor_crash_injection as crash_injection
from nbadb.orchestrate.successor_inventory import (
    InstalledPublicTreeInventory,
    measure_installed_public_tree,
)
from nbadb.orchestrate.successor_publication_inventory import (
    inspect_successor_candidate_publication,
    require_successor_publication_formats,
    validate_successor_publication_freshness,
)
from nbadb.orchestrate.successor_update_contract import (
    SuccessorGenerationState,
    SuccessorUpdateContractError,
    SuccessorUpdateTransaction,
    canonical_json_bytes,
)

if TYPE_CHECKING:
    import polars as pl

__all__ = [
    "CURRENT_SUCCESSOR_GENERATION_NAME",
    "SUCCESSOR_CANDIDATE_BASELINE_NAME",
    "SUCCESSOR_TRANSACTION_NAME",
    "SuccessorGenerationStore",
    "SuccessorGenerationStoreError",
    "SuccessorPrivateRetentionReceipts",
]

CURRENT_SUCCESSOR_GENERATION_NAME: Final = "current-successor-generation.json"
SUCCESSOR_CANDIDATE_BASELINE_NAME: Final = "successor-candidate-baseline.json"
SUCCESSOR_TRANSACTION_NAME: Final = "successor-update-transaction.json"
_STORE_LOCK_NAME: Final = ".successor-generation-store.lock"
_POINTER_SCHEMA_VERSION: Final = 2
_CANDIDATE_BASELINE_SCHEMA_VERSION: Final = 2
_MAX_CONTROL_BYTES: Final = 16 * 1024 * 1024
_PUBLICATION_INVENTORY_SCRATCH_NAME: Final = ".publication-inventory-scratch"
_PUBLICATION_INVENTORY_SNAPSHOT_MAX_BYTES: Final = 64 * 1024 * 1024


class SuccessorGenerationStoreError(RuntimeError):
    """Raised when candidate registration or pointer promotion is unsafe."""


@dataclass(frozen=True, slots=True)
class SuccessorPrivateRetentionReceipts:
    """Path-free private receipts named by the current/previous public window."""

    identity_sha256s: frozenset[str]
    planning_generation_ids: frozenset[str]


def _canonical_document(payload: object) -> bytes:
    return canonical_json_bytes(payload) + b"\n"


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _inventory_bytes(inventory: list[dict[str, Any]]) -> int:
    return sum(int(item["bytes"]) for item in inventory)


_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


def _exclusive_store_operation(method: Any) -> Any:
    @wraps(method)
    def locked(self: SuccessorGenerationStore, *args: Any, **kwargs: Any) -> Any:
        with self._exclusive_store_lock():
            return method(self, *args, **kwargs)

    return locked


class SuccessorGenerationStore:
    """Own frozen candidates and one atomically replaced current pointer.

    The store copies an admitted public baseline into an isolated candidate;
    private capture and later copy-plus-delta mutation remain external.  It
    accepts only a fully promoted transaction for current-pointer authority.
    The prior reference remains embedded in that pointer for rollback.  The
    POSIX permission freeze is cooperative and reversible, so every current
    read remeasures the referenced public tree and rejects permission, byte, or
    topology drift instead of treating the pointer alone as authority.
    """

    def __init__(
        self,
        root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
        expected_generations_identity: tuple[int, int] | None = None,
    ) -> None:
        if (expected_root_identity is None) != (expected_generations_identity is None):
            raise SuccessorGenerationStoreError(
                "bound generation store requires both directory identities"
            )
        for label, identity in (
            ("root", expected_root_identity),
            ("generations", expected_generations_identity),
        ):
            if identity is not None and (
                type(identity) is not tuple
                or len(identity) != 2
                or any(type(value) is not int or value < 0 for value in identity)
            ):
                raise SuccessorGenerationStoreError(
                    f"bound generation store {label} identity is invalid"
                )
        self.root = Path(root)
        self.generations_root = self.root / "generations"
        self.pointer_path = self.root / CURRENT_SUCCESSOR_GENERATION_NAME
        self._expected_root_identity = expected_root_identity
        self._expected_generations_identity = expected_generations_identity
        self._lock_state = threading.local()

    @staticmethod
    def candidate_name(transaction: SuccessorUpdateTransaction) -> str:
        if not isinstance(transaction, SuccessorUpdateTransaction):
            raise SuccessorGenerationStoreError(
                "candidate identity requires a SuccessorUpdateTransaction"
            )
        stable_identity = transaction.generation_identity_sha256
        return f"generation-{transaction.generation:08d}-{stable_identity[:16]}"

    def candidate_path(self, transaction: SuccessorUpdateTransaction) -> Path:
        return self.generations_root / self.candidate_name(transaction)

    @contextmanager
    def transaction_authority(self) -> Any:
        """Hold the store's reentrant cross-process lock across a transaction.

        Callers that must bind an external admission proof to a sequence of
        generation-store operations can use this context to prevent a current
        pointer or candidate lifecycle transition from interleaving between
        those operations.  Store methods remain safely reentrant inside it.
        """

        with self._exclusive_store_lock():
            yield

    @_exclusive_store_operation
    def prepare_candidate_from_baseline(
        self,
        baseline_public_root: Path,
        transaction: SuccessorUpdateTransaction,
        *,
        candidate_max_bytes: int,
        private_generation_estimated_bytes: int,
        rollback_reserve_bytes: int,
        minimum_free_bytes: int,
        monotonic_now_seconds: float,
        monotonic_deadline_seconds: float,
        minimum_deadline_headroom_seconds: float,
        expected_resume_installed_public_tree_sha256: str | None = None,
    ) -> Path:
        """Create or resume one copy-plus-delta candidate without mutating its parent.

        All capacity and deadline values are required caller evidence.  The
        store deliberately supplies no production defaults.  On first use it
        copies the exact admitted public baseline into a private temporary
        sibling, writes the candidate transaction, verifies both trees, and
        atomically renames the sibling into its canonical generation path.

        An untouched candidate resumes against the baseline inventory.  Once
        delta persistence has changed ``public/``, the caller must provide the
        exact inventory digest recovered from its durable receipts.  This keeps
        legitimate copy-plus-delta progress distinct from unexplained drift.
        """

        self._require_candidate_transaction(transaction)
        bounds = {
            "candidate_max_bytes": candidate_max_bytes,
            "private_generation_estimated_bytes": private_generation_estimated_bytes,
            "rollback_reserve_bytes": rollback_reserve_bytes,
            "minimum_free_bytes": minimum_free_bytes,
        }
        for field_name, value in bounds.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        for field_name, value in (
            ("monotonic_now_seconds", monotonic_now_seconds),
            ("monotonic_deadline_seconds", monotonic_deadline_seconds),
            ("minimum_deadline_headroom_seconds", minimum_deadline_headroom_seconds),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{field_name} must be positive and finite")
        if monotonic_deadline_seconds - monotonic_now_seconds < minimum_deadline_headroom_seconds:
            raise SuccessorGenerationStoreError(
                "successor candidate deadline headroom is insufficient"
            )
        if expected_resume_installed_public_tree_sha256 is not None:
            self._require_sha256(
                expected_resume_installed_public_tree_sha256,
                label="expected resume installed public tree",
            )

        self._ensure_store_layout()
        baseline = Path(baseline_public_root)
        baseline_measurement = self._measure_installed_public_tree(
            baseline,
            label="successor baseline public tree",
        )
        if (
            baseline_measurement.installed_public_tree_sha256
            != transaction.baseline.installed_public_tree_sha256
        ):
            raise SuccessorGenerationStoreError(
                "successor baseline installed public tree does not match transaction authority"
            )
        baseline_inventory = baseline_measurement.to_inventory()
        baseline_bytes = baseline_measurement.byte_count
        admission = self._candidate_baseline_document(
            transaction,
            baseline_inventory=baseline_inventory,
        )
        candidate_transaction = _canonical_document(transaction.to_dict())
        initial_candidate_bytes = baseline_bytes + len(admission) + len(candidate_transaction)
        if initial_candidate_bytes > candidate_max_bytes:
            raise SuccessorGenerationStoreError(
                "successor baseline exceeds the caller-supplied candidate byte bound"
            )

        candidate = self.candidate_path(transaction)
        if candidate.exists() or candidate.is_symlink():
            return self._resume_candidate_from_baseline(
                candidate,
                transaction,
                admission=admission,
                candidate_max_bytes=candidate_max_bytes,
                private_generation_estimated_bytes=private_generation_estimated_bytes,
                rollback_reserve_bytes=rollback_reserve_bytes,
                minimum_free_bytes=minimum_free_bytes,
                expected_installed_public_tree_sha256=(
                    expected_resume_installed_public_tree_sha256
                    or baseline_measurement.installed_public_tree_sha256
                ),
            )
        if (
            expected_resume_installed_public_tree_sha256 is not None
            and expected_resume_installed_public_tree_sha256
            != baseline_measurement.installed_public_tree_sha256
        ):
            raise SuccessorGenerationStoreError(
                "a new successor candidate must start from the exact installed baseline tree"
            )

        self._require_candidate_capacity(
            current_candidate_bytes=0,
            candidate_max_bytes=candidate_max_bytes,
            private_generation_estimated_bytes=private_generation_estimated_bytes,
            rollback_reserve_bytes=rollback_reserve_bytes,
            minimum_free_bytes=minimum_free_bytes,
        )
        temporary, temporary_descriptor = self._new_temporary_candidate(candidate)
        temporary_public = temporary / "public"
        public_descriptor = -1
        try:
            if temporary_descriptor >= 0:
                os.mkdir("public", mode=0o700, dir_fd=temporary_descriptor)
                public_descriptor = self._open_child_directory(
                    temporary_descriptor,
                    "public",
                    label="successor temporary public tree",
                )
                self._copy_inventory_directories_relative(
                    public_descriptor,
                    baseline_measurement.directories,
                )
                self._copy_inventory_files_relative(
                    baseline,
                    public_descriptor,
                    baseline_inventory,
                )
            else:
                temporary_public.mkdir(mode=0o700)
                self._copy_inventory_directories(
                    temporary_public,
                    baseline_measurement.directories,
                )
                self._copy_inventory_files(
                    baseline,
                    temporary_public,
                    baseline_inventory,
                )
            observed_baseline = self._measure_installed_public_tree(
                baseline,
                label="successor baseline public tree",
            )
            if observed_baseline != baseline_measurement:
                raise SuccessorGenerationStoreError(
                    "successor baseline public tree changed while copying"
                )
            observed_candidate = (
                self._measure_installed_public_tree_descriptor(
                    public_descriptor,
                    label="successor candidate public tree",
                )
                if public_descriptor >= 0
                else self._measure_installed_public_tree(
                    temporary_public,
                    label="successor candidate public tree",
                )
            )
            if observed_candidate != baseline_measurement:
                raise SuccessorGenerationStoreError(
                    "successor candidate copy does not match the admitted baseline"
                )
            if temporary_descriptor >= 0:
                self._fsync_inventory_directories_descriptor(
                    public_descriptor,
                    directories=baseline_measurement.directories,
                )
                self._atomic_write_relative(
                    temporary_descriptor,
                    SUCCESSOR_CANDIDATE_BASELINE_NAME,
                    admission,
                )
                self._atomic_write_relative(
                    temporary_descriptor,
                    SUCCESSOR_TRANSACTION_NAME,
                    candidate_transaction,
                )
                os.fsync(public_descriptor)
                os.fsync(temporary_descriptor)
                generations_descriptor = self._active_generations_descriptor()
                try:
                    os.stat(
                        candidate.name,
                        dir_fd=generations_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    raise SuccessorGenerationStoreError(
                        "successor candidate appeared during atomic construction"
                    )
                os.rename(
                    temporary.name,
                    candidate.name,
                    src_dir_fd=generations_descriptor,
                    dst_dir_fd=generations_descriptor,
                )
                os.fsync(generations_descriptor)
            else:
                self._fsync_inventory_directories(
                    temporary_public,
                    baseline_inventory,
                    directories=baseline_measurement.directories,
                )
                self._atomic_write(
                    temporary / SUCCESSOR_CANDIDATE_BASELINE_NAME,
                    admission,
                )
                self._atomic_write(
                    temporary / SUCCESSOR_TRANSACTION_NAME,
                    candidate_transaction,
                )
                self._fsync_directory(temporary_public)
                self._fsync_directory(temporary)
                if candidate.exists() or candidate.is_symlink():
                    raise SuccessorGenerationStoreError(
                        "successor candidate appeared during atomic construction"
                    )
                os.rename(temporary, candidate)
                self._fsync_directory(self.generations_root)
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise
            raise SuccessorGenerationStoreError(
                "successor candidate cannot be copied and installed atomically"
            ) from exc
        finally:
            if public_descriptor >= 0:
                os.close(public_descriptor)
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)

        return self._resume_candidate_from_baseline(
            candidate,
            transaction,
            admission=admission,
            candidate_max_bytes=candidate_max_bytes,
            private_generation_estimated_bytes=private_generation_estimated_bytes,
            rollback_reserve_bytes=rollback_reserve_bytes,
            minimum_free_bytes=minimum_free_bytes,
            expected_installed_public_tree_sha256=(
                baseline_measurement.installed_public_tree_sha256
            ),
            capacity_already_admitted=True,
        )

    @_exclusive_store_operation
    def record_promoted_candidate(
        self,
        candidate_root: Path,
        transaction: SuccessorUpdateTransaction,
    ) -> Path:
        """Persist exact promoted authority without changing the current pointer."""

        self._require_promoted(transaction)
        candidate = self._require_exact_candidate(candidate_root, transaction)
        public_root = candidate / "public"
        if (
            not public_root.is_dir()
            or public_root.is_symlink()
            or public_root.resolve() != candidate.resolve() / "public"
        ):
            raise SuccessorGenerationStoreError(
                "successor candidate must contain a regular public directory"
            )

        return self._record_transaction_locked(candidate, transaction)

    @_exclusive_store_operation
    def record_transaction(
        self,
        candidate_root: Path,
        transaction: SuccessorUpdateTransaction,
    ) -> Path:
        """Persist or advance one exact resumable transaction by one state."""

        return self._record_transaction_locked(candidate_root, transaction)

    def _record_transaction_locked(
        self,
        candidate_root: Path,
        transaction: SuccessorUpdateTransaction,
    ) -> Path:
        if not isinstance(transaction, SuccessorUpdateTransaction):
            raise SuccessorGenerationStoreError(
                "transaction persistence requires a SuccessorUpdateTransaction"
            )
        candidate = self._require_exact_candidate(candidate_root, transaction)
        transaction_path = candidate / SUCCESSOR_TRANSACTION_NAME
        encoded = _canonical_document(transaction.to_dict())
        candidate_descriptor = self._require_bound_candidate_descriptor(candidate)
        try:
            if candidate_descriptor >= 0:
                try:
                    os.stat(
                        SUCCESSOR_TRANSACTION_NAME,
                        dir_fd=candidate_descriptor,
                        follow_symlinks=False,
                    )
                    transaction_exists = True
                except FileNotFoundError:
                    transaction_exists = False
                observed = (
                    self._read_regular_file_relative(
                        candidate_descriptor,
                        SUCCESSOR_TRANSACTION_NAME,
                        label="successor candidate transaction",
                    )
                    if transaction_exists
                    else None
                )
            else:
                transaction_exists = transaction_path.exists() or transaction_path.is_symlink()
                observed = (
                    self._read_regular_file(
                        transaction_path,
                        label="successor candidate transaction",
                    )
                    if transaction_exists
                    else None
                )
            if observed is None:
                if transaction.state is not SuccessorGenerationState.CANDIDATE:
                    raise SuccessorGenerationStoreError(
                        "a successor transaction must be recorded as candidate before advancing"
                    )
            elif observed == encoded:
                return transaction_path
            else:
                prior = self._decode_transaction(observed)
                if self.candidate_name(prior) != self.candidate_name(transaction):
                    raise SuccessorGenerationStoreError(
                        "successor transaction identity changed while advancing its candidate"
                    )
                state_order = {
                    SuccessorGenerationState.CANDIDATE: 0,
                    SuccessorGenerationState.BUILT: 1,
                    SuccessorGenerationState.VALIDATED: 2,
                    SuccessorGenerationState.PROMOTED: 3,
                }
                if state_order[transaction.state] != state_order[prior.state] + 1:
                    raise SuccessorGenerationStoreError(
                        "successor transaction state must advance by exactly one transition"
                    )

            if candidate_descriptor >= 0:
                self._atomic_write_relative(
                    candidate_descriptor,
                    SUCCESSOR_TRANSACTION_NAME,
                    encoded,
                )
            else:
                self._atomic_write_candidate_control(
                    candidate,
                    SUCCESSOR_TRANSACTION_NAME,
                    encoded,
                )
            return transaction_path
        finally:
            if candidate_descriptor >= 0:
                try:
                    self._require_candidate_descriptor_current(
                        candidate,
                        candidate_descriptor,
                    )
                finally:
                    os.close(candidate_descriptor)

    @_exclusive_store_operation
    def load_transaction(self, candidate_root: Path) -> SuccessorUpdateTransaction:
        candidate = Path(candidate_root)
        try:
            candidate.relative_to(self.generations_root)
        except ValueError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate is outside the generation store"
            ) from exc
        if (
            not candidate.is_dir()
            or candidate.is_symlink()
            or candidate.resolve().parent != self.generations_root.resolve()
        ):
            raise SuccessorGenerationStoreError(
                "successor candidate must be a direct regular generation directory"
            )
        candidate_descriptor = self._require_bound_candidate_descriptor(candidate)
        try:
            encoded = (
                self._read_regular_file_relative(
                    candidate_descriptor,
                    SUCCESSOR_TRANSACTION_NAME,
                    label="successor candidate transaction",
                )
                if candidate_descriptor >= 0
                else self._read_regular_file(
                    candidate / SUCCESSOR_TRANSACTION_NAME,
                    label="successor candidate transaction",
                )
            )
        finally:
            if candidate_descriptor >= 0:
                os.close(candidate_descriptor)
        transaction = self._decode_transaction(encoded)
        if candidate.name != self.candidate_name(transaction):
            raise SuccessorGenerationStoreError(
                "successor candidate directory does not match its transaction identity"
            )
        return transaction

    @_exclusive_store_operation
    def promote(
        self,
        candidate_root: Path,
        transaction: SuccessorUpdateTransaction,
    ) -> dict[str, Any]:
        """Atomically make one recorded, fully validated candidate current."""

        self._require_promoted(transaction)
        candidate = self._require_exact_candidate(candidate_root, transaction)
        transaction_path = candidate / SUCCESSOR_TRANSACTION_NAME
        expected_transaction = _canonical_document(transaction.to_dict())
        candidate_descriptor = self._require_bound_candidate_descriptor(candidate)
        public_descriptor = -1
        try:
            if candidate_descriptor >= 0:
                observed_transaction = self._read_regular_file_relative(
                    candidate_descriptor,
                    SUCCESSOR_TRANSACTION_NAME,
                    label="successor candidate transaction",
                )
                public_descriptor = self._open_child_directory(
                    candidate_descriptor,
                    "public",
                    label="successor candidate public tree",
                )
                public_root = None
            else:
                observed_transaction = self._read_regular_file(
                    transaction_path,
                    label="successor candidate transaction",
                )
                public_root = candidate / "public"
            if observed_transaction != expected_transaction:
                raise SuccessorGenerationStoreError(
                    "successor candidate transaction does not match promotion authority"
                )

            current_pointer = self.read_current()
            current_reference = None if current_pointer is None else current_pointer["current"]
            expected_tree_sha256 = transaction.promoted_assurance.installed_public_tree_sha256
            new_reference = self._reference(
                transaction,
                installed_public_tree_sha256=expected_tree_sha256,
            )
            idempotent_reentry = current_reference == new_reference
            if current_reference is None and transaction.generation != 1:
                raise SuccessorGenerationStoreError(
                    "first successor promotion must begin at generation one"
                )
            if current_reference is not None and not idempotent_reentry:
                current_generation = current_reference.get("generation")
                if type(current_generation) is not int:
                    raise SuccessorGenerationStoreError(
                        "current successor generation has an invalid generation"
                    )
                if transaction.generation != current_generation + 1:
                    raise SuccessorGenerationStoreError(
                        "successor promotion must advance the current generation by exactly one"
                    )

            verified_tree = (
                self._measure_installed_public_tree_descriptor(
                    public_descriptor,
                    label="successor candidate public tree",
                )
                if public_descriptor >= 0
                else self._measure_installed_public_tree(
                    cast("Path", public_root),
                    label="successor candidate public tree",
                )
            )
            if verified_tree.installed_public_tree_sha256 != expected_tree_sha256:
                raise SuccessorGenerationStoreError(
                    "successor candidate installed public tree differs from promotion assurance"
                )
            if public_descriptor >= 0:
                self._freeze_public_tree_descriptor(
                    public_descriptor,
                    inventory=verified_tree.to_inventory(),
                    directories=verified_tree.directories,
                )
                verified_tree = self._measure_installed_public_tree_descriptor(
                    public_descriptor,
                    label="frozen successor candidate public tree",
                )
            else:
                self._freeze_public_tree(
                    cast("Path", public_root),
                    inventory=verified_tree.to_inventory(),
                    directories=verified_tree.directories,
                )
                verified_tree = self._measure_installed_public_tree(
                    cast("Path", public_root),
                    label="frozen successor candidate public tree",
                )
            if verified_tree.installed_public_tree_sha256 != expected_tree_sha256:
                raise SuccessorGenerationStoreError(
                    "frozen successor candidate installed public tree differs from "
                    "promotion assurance"
                )
            if public_descriptor >= 0:
                self._require_public_tree_frozen_descriptor(
                    public_descriptor,
                    inventory=verified_tree.to_inventory(),
                    directories=verified_tree.directories,
                )
            else:
                self._require_public_tree_frozen(
                    cast("Path", public_root),
                    inventory=verified_tree.to_inventory(),
                    directories=verified_tree.directories,
                )
            if candidate_descriptor >= 0:
                self._require_candidate_descriptor_current(candidate, candidate_descriptor)
            self._gate_publication_before_promote(candidate / "public", transaction)
            if idempotent_reentry:
                return cast("dict[str, Any]", current_pointer)

            pointer = {
                "schema_version": _POINTER_SCHEMA_VERSION,
                "current": new_reference,
                "previous": current_reference,
            }
            self._atomic_write_store_control(
                CURRENT_SUCCESSOR_GENERATION_NAME,
                _canonical_document(pointer),
            )
            crash_injection.after_durable_step(
                crash_injection.DurablePlanningStep.POINTER_ADVANCE,
                pointer="current",
                generation=transaction.generation,
                transaction_sha256=transaction.content_sha256,
            )
            if candidate_descriptor >= 0:
                self._require_candidate_descriptor_current(candidate, candidate_descriptor)
            return pointer
        finally:
            if public_descriptor >= 0:
                os.close(public_descriptor)
            if candidate_descriptor >= 0:
                os.close(candidate_descriptor)

    @contextmanager
    def candidate_mutation(
        self,
        candidate_root: Path,
        transaction: SuccessorUpdateTransaction,
    ) -> Any:
        """Serialize one authorized candidate writer against lifecycle operations."""

        with self._exclusive_store_lock():
            candidate = self._require_exact_candidate(candidate_root, transaction)
            stored = self.load_transaction(candidate)
            if stored.generation_identity_sha256 != transaction.generation_identity_sha256:
                raise SuccessorGenerationStoreError(
                    "successor candidate mutation authority differs from stored transaction"
                )
            if stored.state is SuccessorGenerationState.PROMOTED:
                raise SuccessorGenerationStoreError(
                    "promoted successor candidate public bytes are frozen"
                )
            yield candidate / "public"

    @_exclusive_store_operation
    def materialize_candidate_public_formats(
        self,
        candidate_root: Path,
        transaction: SuccessorUpdateTransaction,
        tables: Mapping[str, pl.DataFrame],
    ) -> Path:
        """Build DuckDB, SQLite, CSV, and Parquet under one candidate public root."""

        import polars as pl

        from nbadb.core.config import NbaDbSettings
        from nbadb.core.types import validate_sql_identifier
        from nbadb.load.multi import SUPPORTED_FORMATS, create_multi_loader

        if not isinstance(tables, Mapping) or not tables:
            raise SuccessorGenerationStoreError(
                "candidate public format materialization requires at least one table"
            )
        required_formats = ("duckdb", "sqlite", "csv", "parquet")
        if set(required_formats) != SUPPORTED_FORMATS:
            raise SuccessorGenerationStoreError(
                "candidate public tree requires DuckDB, SQLite, CSV, and Parquet"
            )
        validated_tables: list[tuple[str, pl.DataFrame]] = []
        for table_name, frame in tables.items():
            if not isinstance(table_name, str) or not table_name:
                raise SuccessorGenerationStoreError("candidate public format table name is invalid")
            try:
                safe_name = validate_sql_identifier(table_name)
            except ValueError as exc:
                raise SuccessorGenerationStoreError(
                    "candidate public format table name is invalid"
                ) from exc
            if not isinstance(frame, pl.DataFrame):
                raise SuccessorGenerationStoreError(
                    "candidate public format table is not a DataFrame"
                )
            validated_tables.append((safe_name, frame))
        validated_tables.sort(key=lambda item: item[0])
        if len({name for name, _frame in validated_tables}) != len(validated_tables):
            raise SuccessorGenerationStoreError("candidate public format table name is invalid")

        with self.candidate_mutation(candidate_root, transaction) as public_root:
            settings = NbaDbSettings(
                data_dir=public_root,
                formats=list(required_formats),
                sqlite_path=public_root / "nba.sqlite",
                duckdb_path=public_root / "nba.duckdb",
            )
            if (
                set(settings.formats) != set(required_formats)
                or settings.data_dir != public_root
                or settings.sqlite_path != public_root / "nba.sqlite"
                or settings.duckdb_path != public_root / "nba.duckdb"
            ):
                raise SuccessorGenerationStoreError(
                    "candidate public format destinations must stay under the candidate public root"
                )
            import duckdb

            connection = duckdb.connect(str(settings.duckdb_path))
            try:
                loader = create_multi_loader(settings, duckdb_conn=connection, strict=True)
                for table_name, frame in validated_tables:
                    loader.load(table_name, frame, mode="replace")
            except SuccessorGenerationStoreError:
                raise
            except Exception as exc:
                raise SuccessorGenerationStoreError(
                    "create_multi_loader failed to materialize the candidate public tree"
                ) from exc
            finally:
                connection.close()
            try:
                require_successor_publication_formats(public_root)
            except ValueError as exc:
                raise SuccessorGenerationStoreError(str(exc)) from exc
        return candidate_root / "public"

    @_exclusive_store_operation
    def collect_retired_generations(self) -> tuple[str, ...]:
        """Delete generations older than previous after durable promote success."""

        pointer = self.read_current()
        if pointer is None:
            raise SuccessorGenerationStoreError(
                "retired generation collection requires a durable promoted current pointer"
            )
        current_reference = cast("Mapping[str, object]", pointer["current"])
        previous_reference = pointer["previous"]
        current_name = cast("str", current_reference["candidate_name"])
        previous_name: str | None = None
        previous_generation: int | None = None
        retained = {current_name}
        if previous_reference is not None:
            previous_mapping = cast("Mapping[str, object]", previous_reference)
            previous_name = cast("str", previous_mapping["candidate_name"])
            previous_generation = cast("int", previous_mapping["generation"])
            retained.add(previous_name)
            previous_path = self.generations_root / previous_name
            if previous_path.is_symlink() or not previous_path.is_dir():
                raise SuccessorGenerationStoreError(
                    "retired generation collection requires the retained previous generation"
                )

        retired: list[tuple[int, str, Path]] = []
        for generation_dir in self._generation_directories():
            if generation_dir.name in retained:
                continue
            try:
                stored = self.load_transaction(generation_dir)
            except SuccessorGenerationStoreError as exc:
                raise SuccessorGenerationStoreError(
                    "refusing generation collection while a candidate, executing, "
                    "or unassured generation exists"
                ) from exc
            if stored.state is not SuccessorGenerationState.PROMOTED:
                raise SuccessorGenerationStoreError(
                    "refusing generation collection while a candidate, executing, "
                    "or unassured generation exists"
                )
            if previous_generation is None or stored.generation >= previous_generation:
                continue
            retired.append((stored.generation, generation_dir.name, generation_dir))

        collected: list[str] = []
        for _generation, name, generation_dir in sorted(retired):
            self._remove_generation_directory(generation_dir)
            collected.append(name)
        return tuple(collected)

    @_exclusive_store_operation
    def retained_private_receipts(self) -> SuccessorPrivateRetentionReceipts:
        """Re-read the locked current pointer and retain current/previous receipts.

        Candidate, executing, or unassured public generations refuse collection.
        A missing current pointer may retain nothing only when no public
        generation exists. Age is never consulted.
        """

        pointer = self.read_current()
        generation_dirs = self._generation_directories()
        if pointer is None:
            if generation_dirs:
                raise SuccessorGenerationStoreError(
                    "refusing private planning collection while a candidate, executing, "
                    "or unassured generation exists"
                )
            return SuccessorPrivateRetentionReceipts(
                identity_sha256s=frozenset(),
                planning_generation_ids=frozenset(),
            )

        current_reference = cast("Mapping[str, object]", pointer["current"])
        previous_reference = pointer["previous"]
        retained_names = {cast("str", current_reference["candidate_name"])}
        if previous_reference is not None:
            previous_mapping = cast("Mapping[str, object]", previous_reference)
            previous_name = cast("str", previous_mapping["candidate_name"])
            retained_names.add(previous_name)
            previous_path = self.generations_root / previous_name
            if previous_path.is_symlink() or not previous_path.is_dir():
                raise SuccessorGenerationStoreError(
                    "retired generation collection requires the retained previous generation"
                )

        identities: set[str] = set()
        for generation_dir in generation_dirs:
            try:
                stored = self.load_transaction(generation_dir)
            except SuccessorGenerationStoreError as exc:
                raise SuccessorGenerationStoreError(
                    "refusing private planning collection while a candidate, executing, "
                    "or unassured generation exists"
                ) from exc
            if stored.state is not SuccessorGenerationState.PROMOTED:
                raise SuccessorGenerationStoreError(
                    "refusing private planning collection while a candidate, executing, "
                    "or unassured generation exists"
                )
            if generation_dir.name not in retained_names:
                continue
            identities.update(self._transaction_private_receipts(stored))
        return SuccessorPrivateRetentionReceipts(
            identity_sha256s=frozenset(identities),
            planning_generation_ids=frozenset(),
        )

    @staticmethod
    def _transaction_private_receipts(transaction: SuccessorUpdateTransaction) -> frozenset[str]:
        receipts = {
            transaction.generation_identity_sha256,
            transaction.baseline.private_baseline_receipt_sha256,
            transaction.intent.planning_generation_manifest_sha256,
        }
        if transaction.assurance is not None:
            receipts.add(transaction.assurance.private_generation_receipt_sha256)
        return frozenset(receipts)

    @_exclusive_store_operation
    def read_current(self) -> dict[str, Any] | None:
        """Return current authority only after re-proving its frozen public tree."""

        if self._expected_root_identity is not None:
            root_descriptor = int(self._lock_state.root_descriptor)
            try:
                os.stat(
                    CURRENT_SUCCESSOR_GENERATION_NAME,
                    dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return None
            encoded = self._read_regular_file_relative(
                root_descriptor,
                CURRENT_SUCCESSOR_GENERATION_NAME,
                label="current successor generation pointer",
            )
        else:
            if not self.pointer_path.exists() and not self.pointer_path.is_symlink():
                return None
            encoded = self._read_regular_file(
                self.pointer_path,
                label="current successor generation pointer",
            )
        try:
            payload = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorGenerationStoreError(
                "current successor generation pointer is not valid JSON"
            ) from exc
        if not isinstance(payload, Mapping):
            raise SuccessorGenerationStoreError(
                "current successor generation pointer has an unsupported schema"
            )
        pointer = cast("Mapping[str, object]", payload)
        if set(pointer) != {"schema_version", "current", "previous"}:
            raise SuccessorGenerationStoreError(
                "current successor generation pointer has invalid fields"
            )
        if pointer["schema_version"] != _POINTER_SCHEMA_VERSION:
            raise SuccessorGenerationStoreError(
                "current successor generation pointer has an unsupported schema"
            )
        self._validate_reference(pointer["current"], label="current")
        if pointer["previous"] is not None:
            self._validate_reference(pointer["previous"], label="previous")
        if encoded != _canonical_document(payload):
            raise SuccessorGenerationStoreError(
                "current successor generation pointer is not canonical"
            )
        self._require_current_reference_authority(cast("Mapping[str, object]", pointer["current"]))
        return cast("dict[str, Any]", payload)

    @staticmethod
    def _require_candidate_transaction(transaction: SuccessorUpdateTransaction) -> None:
        if not isinstance(transaction, SuccessorUpdateTransaction):
            raise SuccessorGenerationStoreError(
                "candidate preparation requires a SuccessorUpdateTransaction"
            )
        if transaction.state is not SuccessorGenerationState.CANDIDATE:
            raise SuccessorGenerationStoreError(
                "candidate preparation requires the immutable candidate transaction"
            )

    def _ensure_store_layout(self) -> None:
        bound = self._expected_root_identity is not None
        if not bound:
            self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise SuccessorGenerationStoreError(
                "successor generation store root must be a regular directory"
            )
        if not bound:
            self.generations_root.mkdir(mode=0o700, exist_ok=True)
        if self.generations_root.is_symlink() or not self.generations_root.is_dir():
            raise SuccessorGenerationStoreError(
                "successor generations root must be a regular directory"
            )
        if bound:
            root_stat = os.stat(self.root, follow_symlinks=False)
            generations_stat = os.stat(self.generations_root, follow_symlinks=False)
            if (root_stat.st_dev, root_stat.st_ino) != self._expected_root_identity or (
                generations_stat.st_dev,
                generations_stat.st_ino,
            ) != self._expected_generations_identity:
                raise SuccessorGenerationStoreError(
                    "bound generation store directory identity changed"
                )

    def _require_bound_descriptor_identities(
        self,
        root_descriptor: int,
        generations_descriptor: int,
    ) -> None:
        if self._expected_root_identity is None:
            return
        root_open = os.fstat(root_descriptor)
        generations_open = os.fstat(generations_descriptor)
        root_current = os.stat(self.root, follow_symlinks=False)
        generations_current = os.stat(self.generations_root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(root_open.st_mode)
            or not stat.S_ISDIR(generations_open.st_mode)
            or (root_open.st_dev, root_open.st_ino) != self._expected_root_identity
            or (root_current.st_dev, root_current.st_ino) != self._expected_root_identity
            or (generations_open.st_dev, generations_open.st_ino)
            != self._expected_generations_identity
            or (generations_current.st_dev, generations_current.st_ino)
            != self._expected_generations_identity
        ):
            raise SuccessorGenerationStoreError("bound generation store directory identity changed")

    def _require_active_bound_authority(self) -> None:
        if self._expected_root_identity is None:
            return
        depth = int(getattr(self._lock_state, "depth", 0))
        root_descriptor = int(getattr(self._lock_state, "root_descriptor", -1))
        generations_descriptor = int(getattr(self._lock_state, "generations_descriptor", -1))
        if depth < 1 or root_descriptor < 0 or generations_descriptor < 0:
            raise SuccessorGenerationStoreError(
                "bound generation store operation lacks retained directory authority"
            )
        self._require_bound_descriptor_identities(
            root_descriptor,
            generations_descriptor,
        )

    @staticmethod
    def _directory_flags() -> int:
        return (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )

    def _active_generations_descriptor(self) -> int:
        depth = int(getattr(self._lock_state, "depth", 0))
        descriptor = int(getattr(self._lock_state, "generations_descriptor", -1))
        if depth < 1 or descriptor < 0 or self._expected_generations_identity is None:
            raise SuccessorGenerationStoreError(
                "bound generation store operation lacks retained directory authority"
            )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (
                opened.st_dev,
                opened.st_ino,
            )
            != self._expected_generations_identity
        ):
            raise SuccessorGenerationStoreError(
                "retained successor generations authority changed identity"
            )
        return descriptor

    def _open_child_directory(
        self,
        parent_descriptor: int,
        name: str,
        *,
        label: str,
    ) -> int:
        """Open one named child beneath a retained directory descriptor."""

        descriptor = -1
        try:
            descriptor = os.open(
                name,
                self._directory_flags(),
                dir_fd=parent_descriptor,
            )
            opened = os.fstat(descriptor)
            current = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise SuccessorGenerationStoreError(
                f"{label} cannot be opened under retained directory authority"
            ) from exc
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            os.close(descriptor)
            raise SuccessorGenerationStoreError(
                f"{label} changed while opening under retained authority"
            )
        return descriptor

    def _require_bound_candidate_descriptor(self, candidate: Path) -> int:
        if self._expected_root_identity is None:
            return -1
        if candidate.parent != self.generations_root:
            raise SuccessorGenerationStoreError(
                "successor candidate is outside the admitted generations root"
            )
        generations_descriptor = self._active_generations_descriptor()
        try:
            descriptor = os.open(
                candidate.name,
                self._directory_flags(),
                dir_fd=generations_descriptor,
            )
            opened = os.fstat(descriptor)
            current = os.stat(
                candidate.name,
                dir_fd=generations_descriptor,
                follow_symlinks=False,
            )
            if not stat.S_ISDIR(opened.st_mode) or (
                opened.st_dev,
                opened.st_ino,
            ) != (current.st_dev, current.st_ino):
                raise SuccessorGenerationStoreError(
                    "successor candidate changed under admitted generations authority"
                )
            return descriptor
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate cannot be opened under admitted authority"
            ) from exc

    def _require_candidate_descriptor_current(
        self,
        candidate: Path,
        descriptor: int,
    ) -> None:
        opened = os.fstat(descriptor)
        current = os.stat(
            candidate.name,
            dir_fd=self._active_generations_descriptor(),
            follow_symlinks=False,
        )
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise SuccessorGenerationStoreError(
                "successor candidate changed under admitted generations authority"
            )

    @contextmanager
    def _bound_candidate_write_authority(self, candidate: Path) -> Any:
        descriptor = self._require_bound_candidate_descriptor(candidate)
        try:
            yield descriptor
            if descriptor >= 0:
                self._require_candidate_descriptor_current(candidate, descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _atomic_write_candidate_control(
        self,
        candidate: Path,
        name: str,
        encoded: bytes,
    ) -> Path:
        if self._expected_root_identity is None:
            target = candidate / name
            self._atomic_write(target, encoded)
            return target
        with self._bound_candidate_write_authority(candidate) as candidate_descriptor:
            self._atomic_write_relative(candidate_descriptor, name, encoded)
        return candidate / name

    def _atomic_write_store_control(self, name: str, encoded: bytes) -> Path:
        if self._expected_root_identity is None:
            target = self.root / name
            self._atomic_write(target, encoded)
            return target
        self._require_active_bound_authority()
        self._atomic_write_relative(
            int(self._lock_state.root_descriptor),
            name,
            encoded,
        )
        return self.root / name

    @staticmethod
    def _atomic_write_relative(parent_descriptor: int, name: str, encoded: bytes) -> None:
        temporary_name = f".{name}.{secrets.token_hex(8)}.tmp"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=parent_descriptor,
            )
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short successor control write")
                view = view[written:]
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary_name,
                name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor generation control cannot be installed atomically"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_descriptor)

    @contextmanager
    def _exclusive_store_lock(self) -> Any:
        """Serialize store operations in-process and across cooperating processes."""

        self._ensure_store_layout()
        bound = self._expected_root_identity is not None
        root_descriptor = generations_descriptor = -1
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            if bound:
                try:
                    root_descriptor = os.open(self.root, directory_flags)
                    generations_descriptor = os.open(
                        "generations",
                        directory_flags,
                        dir_fd=root_descriptor,
                    )
                    self._require_bound_descriptor_identities(
                        root_descriptor,
                        generations_descriptor,
                    )
                except OSError as exc:
                    raise SuccessorGenerationStoreError(
                        "bound generation store topology cannot be re-proved"
                    ) from exc
                assert self._expected_root_identity is not None
                lock_key = (
                    "bound:"
                    f"{self._expected_root_identity[0]}:"
                    f"{self._expected_root_identity[1]}:{_STORE_LOCK_NAME}"
                )
            else:
                lock_key = str(self.root.resolve() / _STORE_LOCK_NAME)

            with _PROCESS_LOCKS_GUARD:
                process_lock = _PROCESS_LOCKS.setdefault(lock_key, threading.RLock())
            with process_lock:
                depth = int(getattr(self._lock_state, "depth", 0))
                if depth:
                    self._require_active_bound_authority()
                    self._lock_state.depth = depth + 1
                    try:
                        yield
                    finally:
                        try:
                            self._require_active_bound_authority()
                        finally:
                            self._lock_state.depth = depth
                    return
                if os.name != "posix":
                    raise SuccessorGenerationStoreError(
                        "successor generation store requires POSIX advisory file locking"
                    )
                lock_path = self.root / _STORE_LOCK_NAME
                flags = os.O_RDWR | os.O_CREAT
                for flag_name in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
                    flags |= getattr(os, flag_name, 0)
                descriptor = -1
                fcntl = importlib.import_module("fcntl")
                acquired = False
                try:
                    if bound:
                        self._require_bound_descriptor_identities(
                            root_descriptor,
                            generations_descriptor,
                        )
                        descriptor = os.open(
                            _STORE_LOCK_NAME,
                            flags,
                            0o600,
                            dir_fd=root_descriptor,
                        )
                    else:
                        descriptor = os.open(lock_path, flags, 0o600)
                    opened_lock = os.fstat(descriptor)
                    if not stat.S_ISREG(opened_lock.st_mode):
                        raise SuccessorGenerationStoreError(
                            "successor generation store lock must be a regular file"
                        )
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                    acquired = True
                    opened_lock = os.fstat(descriptor)
                    current_lock = (
                        os.stat(
                            _STORE_LOCK_NAME,
                            dir_fd=root_descriptor,
                            follow_symlinks=False,
                        )
                        if bound
                        else os.stat(lock_path, follow_symlinks=False)
                    )
                    if not stat.S_ISREG(current_lock.st_mode) or (
                        opened_lock.st_dev,
                        opened_lock.st_ino,
                    ) != (current_lock.st_dev, current_lock.st_ino):
                        raise SuccessorGenerationStoreError(
                            "successor generation store lock changed after acquisition"
                        )
                    self._require_bound_descriptor_identities(
                        root_descriptor,
                        generations_descriptor,
                    )
                    self._lock_state.root_descriptor = root_descriptor
                    self._lock_state.generations_descriptor = generations_descriptor
                    self._lock_state.depth = 1
                    try:
                        yield
                    finally:
                        self._require_bound_descriptor_identities(
                            root_descriptor,
                            generations_descriptor,
                        )
                except OSError as exc:
                    if acquired:
                        raise
                    raise SuccessorGenerationStoreError(
                        "successor generation store lock cannot be acquired"
                    ) from exc
                finally:
                    self._lock_state.depth = 0
                    self._lock_state.root_descriptor = -1
                    self._lock_state.generations_descriptor = -1
                    if descriptor >= 0:
                        with suppress(OSError):
                            fcntl.flock(descriptor, fcntl.LOCK_UN)
                        os.close(descriptor)
        finally:
            if generations_descriptor >= 0:
                os.close(generations_descriptor)
            if root_descriptor >= 0:
                os.close(root_descriptor)

    @staticmethod
    def _safe_inventory(root: Path, *, label: str) -> list[dict[str, Any]]:
        if root.is_symlink():
            raise SuccessorGenerationStoreError(f"{label} must not be a symlink")
        try:
            root_stat = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorGenerationStoreError(f"{label} cannot be inventoried safely") from exc
        if not stat.S_ISDIR(root_stat.st_mode):
            raise SuccessorGenerationStoreError(f"{label} must be a regular directory")
        try:
            inventory = inventory_regular_tree(root)
            path_stat = os.stat(root, follow_symlinks=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SuccessorGenerationStoreError(f"{label} cannot be inventoried safely") from exc
        if _stat_identity(root_stat) != _stat_identity(path_stat):
            raise SuccessorGenerationStoreError(f"{label} changed while inventorying")
        return inventory

    @staticmethod
    def _measure_installed_public_tree(
        root: Path,
        *,
        label: str,
    ) -> InstalledPublicTreeInventory:
        try:
            return measure_installed_public_tree(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SuccessorGenerationStoreError(f"{label} cannot be inventoried safely") from exc

    def _measure_installed_public_tree_descriptor(
        self,
        root_descriptor: int,
        *,
        label: str,
    ) -> InstalledPublicTreeInventory:
        """Measure exact topology and bytes below one retained directory."""

        if not getattr(os, "O_NOFOLLOW", 0):
            raise SuccessorGenerationStoreError(
                "installed public tree identity requires O_NOFOLLOW support"
            )
        child_flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        observations: dict[str | None, tuple[int, int, int, int, int]] = {}

        def inventory_directory(
            descriptor: int,
            *,
            prefix: PurePosixPath | None,
        ) -> tuple[list[str], list[tuple[str, int, str]]]:
            display_path = "." if prefix is None else prefix.as_posix()
            before = os.fstat(descriptor)
            if not stat.S_ISDIR(before.st_mode):
                raise SuccessorGenerationStoreError(
                    f"{label} contains a non-directory path: {display_path}"
                )
            with os.scandir(descriptor) as iterator:
                names = sorted(entry.name for entry in iterator)
            directories: list[str] = []
            files: list[tuple[str, int, str]] = []
            for name in names:
                relative = PurePosixPath(name) if prefix is None else prefix / name
                relative_path = relative.as_posix()
                child = os.open(name, child_flags, dir_fd=descriptor)
                try:
                    child_before = os.fstat(child)
                    if stat.S_ISDIR(child_before.st_mode):
                        directories.append(relative_path)
                        nested_directories, nested_files = inventory_directory(
                            child,
                            prefix=relative,
                        )
                        child_after = os.fstat(child)
                        if _stat_identity(child_before) != _stat_identity(child_after):
                            raise SuccessorGenerationStoreError(
                                f"{label} directory changed while inventorying: {relative_path}"
                            )
                        directories.extend(nested_directories)
                        files.extend(nested_files)
                    elif stat.S_ISREG(child_before.st_mode):
                        digest = hashlib.sha256()
                        while chunk := os.read(child, 1024 * 1024):
                            digest.update(chunk)
                        child_after = os.fstat(child)
                        if _stat_identity(child_before) != _stat_identity(child_after):
                            raise SuccessorGenerationStoreError(
                                f"{label} file changed while inventorying: {relative_path}"
                            )
                        files.append((relative_path, child_before.st_size, digest.hexdigest()))
                    else:
                        raise SuccessorGenerationStoreError(
                            f"{label} contains a non-regular entry: {relative_path}"
                        )
                finally:
                    os.close(child)
            after = os.fstat(descriptor)
            if _stat_identity(before) != _stat_identity(after):
                raise SuccessorGenerationStoreError(
                    f"{label} directory changed while inventorying: {display_path}"
                )
            observations[None if prefix is None else prefix.as_posix()] = _stat_identity(after)
            return directories, files

        try:
            opened_root = os.fstat(root_descriptor)
            if not stat.S_ISDIR(opened_root.st_mode):
                raise SuccessorGenerationStoreError(f"{label} root is not a regular directory")
            directories, files = inventory_directory(root_descriptor, prefix=None)
            for relative_path, expected in sorted(
                observations.items(),
                key=lambda item: "" if item[0] is None else item[0],
            ):
                descriptor = self._open_inventory_directory(
                    root_descriptor,
                    relative_path,
                )
                try:
                    observed = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
                if not stat.S_ISDIR(observed.st_mode) or _stat_identity(observed) != expected:
                    display_path = "." if relative_path is None else relative_path
                    raise SuccessorGenerationStoreError(
                        f"{label} directory changed after inventory: {display_path}"
                    )
            if _stat_identity(os.fstat(root_descriptor)) != _stat_identity(opened_root):
                raise SuccessorGenerationStoreError(f"{label} root changed while inventorying")
            return InstalledPublicTreeInventory(
                files=tuple(sorted(files, key=lambda item: item[0])),
                directories=tuple(sorted(directories)),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, SuccessorGenerationStoreError):
                raise
            raise SuccessorGenerationStoreError(f"{label} cannot be inventoried safely") from exc

    @staticmethod
    def _candidate_baseline_document(
        transaction: SuccessorUpdateTransaction,
        *,
        baseline_inventory: list[dict[str, Any]],
    ) -> bytes:
        payload = {
            "schema_version": _CANDIDATE_BASELINE_SCHEMA_VERSION,
            "kind": "successor_candidate_baseline",
            "generation": transaction.generation,
            "generation_identity_sha256": transaction.generation_identity_sha256,
            "baseline_identity_sha256": transaction.baseline.identity_sha256,
            "baseline_installed_public_tree_sha256": (
                transaction.baseline.installed_public_tree_sha256
            ),
            "baseline_public_file_count": len(baseline_inventory),
            "baseline_public_bytes": _inventory_bytes(baseline_inventory),
        }
        return _canonical_document(payload)

    def _resume_candidate_from_baseline(
        self,
        candidate: Path,
        transaction: SuccessorUpdateTransaction,
        *,
        admission: bytes,
        candidate_max_bytes: int,
        private_generation_estimated_bytes: int,
        rollback_reserve_bytes: int,
        minimum_free_bytes: int,
        expected_installed_public_tree_sha256: str,
        capacity_already_admitted: bool = False,
    ) -> Path:
        exact_candidate = self._require_exact_candidate(candidate, transaction)
        candidate_descriptor = self._require_bound_candidate_descriptor(exact_candidate)
        if candidate_descriptor >= 0:
            public_descriptor = -1
            try:
                self._require_prepared_candidate_layout_descriptor(candidate_descriptor)
                observed_transaction_bytes = self._read_regular_file_relative(
                    candidate_descriptor,
                    SUCCESSOR_TRANSACTION_NAME,
                    label="successor candidate transaction",
                )
                observed_transaction = self._decode_transaction(observed_transaction_bytes)
                if self.candidate_name(observed_transaction) != exact_candidate.name:
                    raise SuccessorGenerationStoreError(
                        "successor candidate directory does not match its transaction identity"
                    )
                if (
                    observed_transaction.generation_identity_sha256
                    != transaction.generation_identity_sha256
                ):
                    raise SuccessorGenerationStoreError(
                        "successor candidate transaction identity changed during resume"
                    )
                observed_admission = self._read_regular_file_relative(
                    candidate_descriptor,
                    SUCCESSOR_CANDIDATE_BASELINE_NAME,
                    label="successor candidate baseline authority",
                )
                if observed_admission != admission:
                    raise SuccessorGenerationStoreError(
                        "successor candidate baseline authority changed during resume"
                    )
                public_descriptor = self._open_child_directory(
                    candidate_descriptor,
                    "public",
                    label="successor candidate public tree",
                )
                public_measurement = self._measure_installed_public_tree_descriptor(
                    public_descriptor,
                    label="successor candidate public tree",
                )
                if (
                    public_measurement.installed_public_tree_sha256
                    != expected_installed_public_tree_sha256
                ):
                    raise SuccessorGenerationStoreError(
                        "successor candidate installed public tree differs from resume authority"
                    )
                self._require_prepared_candidate_layout_descriptor(candidate_descriptor)
                candidate_bytes = (
                    public_measurement.byte_count
                    + len(observed_admission)
                    + len(observed_transaction_bytes)
                )
                if candidate_bytes > candidate_max_bytes:
                    raise SuccessorGenerationStoreError(
                        "successor candidate exceeds the caller-supplied candidate byte bound"
                    )
                if not capacity_already_admitted:
                    self._require_candidate_capacity(
                        current_candidate_bytes=candidate_bytes,
                        candidate_max_bytes=candidate_max_bytes,
                        private_generation_estimated_bytes=(private_generation_estimated_bytes),
                        rollback_reserve_bytes=rollback_reserve_bytes,
                        minimum_free_bytes=minimum_free_bytes,
                    )
                self._require_candidate_descriptor_current(
                    exact_candidate,
                    candidate_descriptor,
                )
                return exact_candidate
            finally:
                if public_descriptor >= 0:
                    os.close(public_descriptor)
                os.close(candidate_descriptor)

        self._require_prepared_candidate_layout(exact_candidate)
        observed_transaction = self.load_transaction(exact_candidate)
        if (
            observed_transaction.generation_identity_sha256
            != transaction.generation_identity_sha256
        ):
            raise SuccessorGenerationStoreError(
                "successor candidate transaction identity changed during resume"
            )
        observed_admission = self._read_regular_file(
            exact_candidate / SUCCESSOR_CANDIDATE_BASELINE_NAME,
            label="successor candidate baseline authority",
        )
        if observed_admission != admission:
            raise SuccessorGenerationStoreError(
                "successor candidate baseline authority changed during resume"
            )
        public_root = exact_candidate / "public"
        public_measurement = self._measure_installed_public_tree(
            public_root,
            label="successor candidate public tree",
        )
        if public_measurement.installed_public_tree_sha256 != expected_installed_public_tree_sha256:
            raise SuccessorGenerationStoreError(
                "successor candidate installed public tree differs from resume authority"
            )
        candidate_inventory = self._safe_inventory(
            exact_candidate,
            label="successor candidate generation",
        )
        self._require_prepared_candidate_layout(exact_candidate)
        candidate_bytes = _inventory_bytes(candidate_inventory)
        if candidate_bytes > candidate_max_bytes:
            raise SuccessorGenerationStoreError(
                "successor candidate exceeds the caller-supplied candidate byte bound"
            )
        if not capacity_already_admitted:
            self._require_candidate_capacity(
                current_candidate_bytes=candidate_bytes,
                candidate_max_bytes=candidate_max_bytes,
                private_generation_estimated_bytes=private_generation_estimated_bytes,
                rollback_reserve_bytes=rollback_reserve_bytes,
                minimum_free_bytes=minimum_free_bytes,
            )
        return exact_candidate

    def _require_candidate_capacity(
        self,
        *,
        current_candidate_bytes: int,
        candidate_max_bytes: int,
        private_generation_estimated_bytes: int,
        rollback_reserve_bytes: int,
        minimum_free_bytes: int,
    ) -> None:
        remaining_candidate_bytes = candidate_max_bytes - current_candidate_bytes
        if remaining_candidate_bytes < 0:
            raise SuccessorGenerationStoreError(
                "successor candidate exceeds the caller-supplied candidate byte bound"
            )
        required_free_bytes = (
            remaining_candidate_bytes
            + private_generation_estimated_bytes
            + rollback_reserve_bytes
            + minimum_free_bytes
        )
        try:
            if self._expected_root_identity is not None:
                filesystem = os.fstatvfs(int(self._lock_state.root_descriptor))
                available_bytes = filesystem.f_bavail * filesystem.f_frsize
            else:
                available_bytes = shutil.disk_usage(self.root).free
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate disk capacity cannot be measured"
            ) from exc
        if available_bytes < required_free_bytes:
            message = (
                "insufficient disk capacity for successor candidate: "
                f"required={required_free_bytes}, available={available_bytes}"
            )
            raise OSError(errno.ENOSPC, message)

    def _new_temporary_candidate(self, candidate: Path) -> tuple[Path, int]:
        if self._expected_root_identity is not None:
            generations_descriptor = self._active_generations_descriptor()
            for _attempt in range(16):
                name = f".{candidate.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
                try:
                    os.mkdir(name, mode=0o700, dir_fd=generations_descriptor)
                except FileExistsError:
                    continue
                descriptor = -1
                try:
                    descriptor = os.open(
                        name,
                        self._directory_flags(),
                        dir_fd=generations_descriptor,
                    )
                    opened = os.fstat(descriptor)
                    current = os.stat(
                        name,
                        dir_fd=generations_descriptor,
                        follow_symlinks=False,
                    )
                    if not stat.S_ISDIR(opened.st_mode) or (
                        opened.st_dev,
                        opened.st_ino,
                    ) != (current.st_dev, current.st_ino):
                        raise SuccessorGenerationStoreError(
                            "successor temporary candidate changed after reservation"
                        )
                    return self.generations_root / name, descriptor
                except BaseException:
                    if descriptor >= 0:
                        os.close(descriptor)
                    raise
            raise SuccessorGenerationStoreError(
                "successor temporary candidate name could not be reserved"
            )

        for _attempt in range(16):
            temporary = self.generations_root / (
                f".{candidate.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
            )
            try:
                temporary.mkdir(mode=0o700)
            except FileExistsError:
                continue
            if temporary.is_symlink() or not temporary.is_dir():
                raise SuccessorGenerationStoreError(
                    "successor temporary candidate is not a regular directory"
                )
            return temporary, -1
        raise SuccessorGenerationStoreError(
            "successor temporary candidate name could not be reserved"
        )

    @staticmethod
    def _open_inventory_source(root_descriptor: int, relative_path: str) -> int:
        pure_path = PurePosixPath(relative_path)
        if (
            pure_path.is_absolute()
            or not pure_path.parts
            or any(part in {"", ".", ".."} for part in pure_path.parts)
        ):
            raise SuccessorGenerationStoreError(
                "successor baseline inventory contains an unsafe path"
            )
        directory_descriptor = os.dup(root_descriptor)
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        file_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            for part in pure_path.parts[:-1]:
                child_descriptor = os.open(
                    part,
                    directory_flags,
                    dir_fd=directory_descriptor,
                )
                os.close(directory_descriptor)
                directory_descriptor = child_descriptor
                if not stat.S_ISDIR(os.fstat(directory_descriptor).st_mode):
                    raise SuccessorGenerationStoreError(
                        "successor baseline inventory parent is not a directory"
                    )
            return os.open(
                pure_path.parts[-1],
                file_flags,
                dir_fd=directory_descriptor,
            )
        finally:
            os.close(directory_descriptor)

    @staticmethod
    def _ensure_destination_parent(root: Path, relative_path: str) -> Path:
        pure_path = PurePosixPath(relative_path)
        parent = root
        for part in pure_path.parts[:-1]:
            parent /= part
            with suppress(FileExistsError):
                parent.mkdir(mode=0o700)
            if parent.is_symlink() or not parent.is_dir():
                raise SuccessorGenerationStoreError(
                    "successor candidate copy encountered an unsafe directory collision"
                )
        return parent / pure_path.parts[-1]

    @staticmethod
    def _copy_inventory_directories(
        destination_root: Path,
        directories: tuple[str, ...],
    ) -> None:
        """Recreate the complete measured topology, including empty directories."""

        for relative_path in sorted(
            directories,
            key=lambda value: (len(PurePosixPath(value).parts), value),
        ):
            pure_path = PurePosixPath(relative_path)
            if (
                pure_path.is_absolute()
                or not pure_path.parts
                or any(part in {"", ".", ".."} for part in pure_path.parts)
                or pure_path.as_posix() != relative_path
            ):
                raise SuccessorGenerationStoreError(
                    "successor baseline directory inventory contains an unsafe path"
                )
            directory = destination_root.joinpath(*pure_path.parts)
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError as exc:
                raise SuccessorGenerationStoreError(
                    "successor candidate copy encountered a directory collision"
                ) from exc

    def _copy_inventory_directories_relative(
        self,
        destination_descriptor: int,
        directories: tuple[str, ...],
    ) -> None:
        """Recreate measured directories below one retained destination."""

        for relative_path in sorted(
            directories,
            key=lambda value: (len(PurePosixPath(value).parts), value),
        ):
            pure_path = PurePosixPath(relative_path)
            if (
                pure_path.is_absolute()
                or not pure_path.parts
                or any(part in {"", ".", ".."} for part in pure_path.parts)
                or pure_path.as_posix() != relative_path
            ):
                raise SuccessorGenerationStoreError(
                    "successor baseline directory inventory contains an unsafe path"
                )
            parent = pure_path.parent
            parent_descriptor = self._open_inventory_directory(
                destination_descriptor,
                None if parent == PurePosixPath(".") else parent.as_posix(),
            )
            try:
                os.mkdir(pure_path.name, mode=0o700, dir_fd=parent_descriptor)
            except FileExistsError as exc:
                raise SuccessorGenerationStoreError(
                    "successor candidate copy encountered a directory collision"
                ) from exc
            finally:
                os.close(parent_descriptor)

    @staticmethod
    def _open_destination_file(path: Path) -> int:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        return os.open(path, flags, 0o600)

    def _copy_inventory_files(
        self,
        source_root: Path,
        destination_root: Path,
        inventory: list[dict[str, Any]],
    ) -> None:
        if not getattr(os, "O_NOFOLLOW", 0):
            raise SuccessorGenerationStoreError(
                "successor candidate copy requires O_NOFOLLOW support"
            )
        root_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            source_descriptor = os.open(source_root, root_flags)
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor baseline public tree cannot be opened safely"
            ) from exc
        try:
            source_root_before = os.fstat(source_descriptor)
            if not stat.S_ISDIR(source_root_before.st_mode):
                raise SuccessorGenerationStoreError(
                    "successor baseline public tree must be a regular directory"
                )
            for item in inventory:
                relative_path = str(item["path"])
                source_file = self._open_inventory_source(
                    source_descriptor,
                    relative_path,
                )
                destination = self._ensure_destination_parent(
                    destination_root,
                    relative_path,
                )
                try:
                    source_before = os.fstat(source_file)
                    if not stat.S_ISREG(source_before.st_mode):
                        raise SuccessorGenerationStoreError(
                            "successor baseline inventory path is not a regular file"
                        )
                    digest = hashlib.sha256()
                    copied_bytes = 0
                    destination_descriptor = self._open_destination_file(destination)
                    with os.fdopen(destination_descriptor, "wb") as output:
                        while chunk := os.read(source_file, 1024 * 1024):
                            digest.update(chunk)
                            output.write(chunk)
                            copied_bytes += len(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    source_after = os.fstat(source_file)
                finally:
                    os.close(source_file)
                if _stat_identity(source_before) != _stat_identity(source_after):
                    raise SuccessorGenerationStoreError(
                        f"successor baseline file changed while copying: {relative_path}"
                    )
                if copied_bytes != item["bytes"] or digest.hexdigest() != item["sha256"]:
                    raise SuccessorGenerationStoreError(
                        f"successor baseline file differs from inventory: {relative_path}"
                    )
            source_root_after = os.fstat(source_descriptor)
            if _stat_identity(source_root_before) != _stat_identity(source_root_after):
                raise SuccessorGenerationStoreError(
                    "successor baseline public tree changed while copying"
                )
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise
            raise SuccessorGenerationStoreError(
                "successor baseline inventory cannot be copied safely"
            ) from exc
        finally:
            os.close(source_descriptor)

    def _copy_inventory_files_relative(
        self,
        source_root: Path,
        destination_descriptor: int,
        inventory: list[dict[str, Any]],
    ) -> None:
        """Copy admitted baseline bytes beneath one retained destination."""

        if not getattr(os, "O_NOFOLLOW", 0):
            raise SuccessorGenerationStoreError(
                "successor candidate copy requires O_NOFOLLOW support"
            )
        root_flags = self._directory_flags()
        destination_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            source_descriptor = os.open(source_root, root_flags)
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor baseline public tree cannot be opened safely"
            ) from exc
        try:
            source_root_before = os.fstat(source_descriptor)
            if not stat.S_ISDIR(source_root_before.st_mode):
                raise SuccessorGenerationStoreError(
                    "successor baseline public tree must be a regular directory"
                )
            for item in inventory:
                relative_path = str(item["path"])
                pure_path = PurePosixPath(relative_path)
                source_file = self._open_inventory_source(
                    source_descriptor,
                    relative_path,
                )
                parent = pure_path.parent
                destination_parent = self._open_inventory_directory(
                    destination_descriptor,
                    None if parent == PurePosixPath(".") else parent.as_posix(),
                )
                destination_file = -1
                try:
                    source_before = os.fstat(source_file)
                    if not stat.S_ISREG(source_before.st_mode):
                        raise SuccessorGenerationStoreError(
                            "successor baseline inventory path is not a regular file"
                        )
                    destination_file = os.open(
                        pure_path.name,
                        destination_flags,
                        0o600,
                        dir_fd=destination_parent,
                    )
                    digest = hashlib.sha256()
                    copied_bytes = 0
                    while chunk := os.read(source_file, 1024 * 1024):
                        digest.update(chunk)
                        view = memoryview(chunk)
                        while view:
                            written = os.write(destination_file, view)
                            if written <= 0:
                                raise OSError("short successor candidate copy write")
                            view = view[written:]
                        copied_bytes += len(chunk)
                    os.fchmod(destination_file, 0o600)
                    os.fsync(destination_file)
                    source_after = os.fstat(source_file)
                finally:
                    if destination_file >= 0:
                        os.close(destination_file)
                    os.close(destination_parent)
                    os.close(source_file)
                if _stat_identity(source_before) != _stat_identity(source_after):
                    raise SuccessorGenerationStoreError(
                        f"successor baseline file changed while copying: {relative_path}"
                    )
                if copied_bytes != item["bytes"] or digest.hexdigest() != item["sha256"]:
                    raise SuccessorGenerationStoreError(
                        f"successor baseline file differs from inventory: {relative_path}"
                    )
            source_root_after = os.fstat(source_descriptor)
            if _stat_identity(source_root_before) != _stat_identity(source_root_after):
                raise SuccessorGenerationStoreError(
                    "successor baseline public tree changed while copying"
                )
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise
            raise SuccessorGenerationStoreError(
                "successor baseline inventory cannot be copied safely"
            ) from exc
        finally:
            os.close(source_descriptor)

    @staticmethod
    def _require_prepared_candidate_layout(candidate: Path) -> None:
        expected = {
            "public": "directory",
            SUCCESSOR_CANDIDATE_BASELINE_NAME: "file",
            SUCCESSOR_TRANSACTION_NAME: "file",
        }
        try:
            with os.scandir(candidate) as iterator:
                entries = {entry.name: entry for entry in iterator}
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate layout cannot be inspected safely"
            ) from exc
        if set(entries) != set(expected):
            raise SuccessorGenerationStoreError(
                "successor candidate has unexpected or missing root entries"
            )
        for name, expected_kind in expected.items():
            try:
                entry_stat = entries[name].stat(follow_symlinks=False)
            except OSError as exc:
                raise SuccessorGenerationStoreError(
                    "successor candidate layout changed while inspecting"
                ) from exc
            is_expected = (
                stat.S_ISDIR(entry_stat.st_mode)
                if expected_kind == "directory"
                else stat.S_ISREG(entry_stat.st_mode)
            )
            if not is_expected or entries[name].is_symlink():
                raise SuccessorGenerationStoreError(
                    f"successor candidate {name} is not a regular {expected_kind}"
                )

    @staticmethod
    def _require_prepared_candidate_layout_descriptor(candidate_descriptor: int) -> None:
        expected = {
            "public": "directory",
            SUCCESSOR_CANDIDATE_BASELINE_NAME: "file",
            SUCCESSOR_TRANSACTION_NAME: "file",
        }
        try:
            with os.scandir(candidate_descriptor) as iterator:
                entries = {entry.name: entry for entry in iterator}
            if set(entries) != set(expected):
                raise SuccessorGenerationStoreError(
                    "successor candidate has unexpected or missing root entries"
                )
            for name, expected_kind in expected.items():
                entry_stat = entries[name].stat(follow_symlinks=False)
                is_expected = (
                    stat.S_ISDIR(entry_stat.st_mode)
                    if expected_kind == "directory"
                    else stat.S_ISREG(entry_stat.st_mode)
                )
                if not is_expected or entries[name].is_symlink():
                    raise SuccessorGenerationStoreError(
                        f"successor candidate {name} is not a regular {expected_kind}"
                    )
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate layout cannot be inspected safely"
            ) from exc

    def _fsync_inventory_directories(
        self,
        root: Path,
        inventory: list[dict[str, Any]],
        *,
        directories: tuple[str, ...] = (),
    ) -> None:
        directory_paths = {root}
        for relative_path in directories:
            directory_paths.add(root / relative_path)
        for item in inventory:
            relative_parent = PurePosixPath(str(item["path"])).parent
            current = root
            for part in relative_parent.parts:
                if part == ".":
                    continue
                current /= part
                directory_paths.add(current)
        for directory in sorted(
            directory_paths,
            key=lambda path: len(path.relative_to(root).parts),
            reverse=True,
        ):
            self._fsync_directory(directory)

    def _fsync_inventory_directories_descriptor(
        self,
        root_descriptor: int,
        *,
        directories: tuple[str, ...],
    ) -> None:
        for relative_path in sorted(
            directories,
            key=lambda value: len(PurePosixPath(value).parts),
            reverse=True,
        ):
            descriptor = self._open_inventory_directory(
                root_descriptor,
                relative_path,
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.fsync(root_descriptor)

    def _freeze_public_tree(
        self,
        root: Path,
        *,
        inventory: list[dict[str, Any]],
        directories: tuple[str, ...],
    ) -> None:
        """Apply a cooperative read-only freeze to every inventoried node.

        POSIX modes are reversible by the owner and are not claimed as durable
        immutability.  Pointer authority therefore also requires a fresh tree
        measurement and this permission check on every ``read_current``.
        """

        if not getattr(os, "O_NOFOLLOW", 0):
            raise SuccessorGenerationStoreError(
                "successor candidate freeze requires O_NOFOLLOW support"
            )
        root_descriptor = self._open_public_root(root)
        try:
            self._freeze_public_tree_descriptor(
                root_descriptor,
                inventory=inventory,
                directories=directories,
            )
        finally:
            os.close(root_descriptor)

    def _freeze_public_tree_descriptor(
        self,
        root_descriptor: int,
        *,
        inventory: list[dict[str, Any]],
        directories: tuple[str, ...],
    ) -> None:
        try:
            for item in inventory:
                descriptor = self._open_inventory_source(
                    root_descriptor,
                    str(item["path"]),
                )
                try:
                    path_stat = os.fstat(descriptor)
                    if not stat.S_ISREG(path_stat.st_mode):
                        raise SuccessorGenerationStoreError(
                            "successor candidate contains a non-regular promotion file"
                        )
                    os.fchmod(descriptor, stat.S_IMODE(path_stat.st_mode) & ~0o222)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)

            relative_directories: tuple[str | None, ...] = (*directories, None)
            for relative_path in sorted(
                relative_directories,
                key=lambda value: 0 if value is None else len(PurePosixPath(value).parts),
                reverse=True,
            ):
                descriptor = self._open_inventory_directory(
                    root_descriptor,
                    relative_path,
                )
                try:
                    directory_stat = os.fstat(descriptor)
                    if not stat.S_ISDIR(directory_stat.st_mode):
                        raise SuccessorGenerationStoreError(
                            "successor candidate contains a non-directory promotion path"
                        )
                    os.fchmod(
                        descriptor,
                        stat.S_IMODE(directory_stat.st_mode) & ~0o222,
                    )
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate changed while freezing promotion tree"
            ) from exc

    @staticmethod
    def _open_public_root(root: Path) -> int:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            descriptor = os.open(root, flags)
            root_stat = os.fstat(descriptor)
            if not stat.S_ISDIR(root_stat.st_mode):
                raise SuccessorGenerationStoreError(
                    "successor candidate public root is not a regular directory"
                )
            return descriptor
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate public root cannot be opened safely"
            ) from exc

    @staticmethod
    def _open_inventory_directory(
        root_descriptor: int,
        relative_path: str | None,
    ) -> int:
        descriptor = os.dup(root_descriptor)
        if relative_path is None:
            return descriptor
        pure_path = PurePosixPath(relative_path)
        if (
            pure_path.is_absolute()
            or not pure_path.parts
            or any(part in {"", ".", ".."} for part in pure_path.parts)
            or pure_path.as_posix() != relative_path
        ):
            os.close(descriptor)
            raise SuccessorGenerationStoreError(
                "successor public directory inventory contains an unsafe path"
            )
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            for part in pure_path.parts:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except OSError as exc:
            os.close(descriptor)
            raise SuccessorGenerationStoreError(
                "successor public directory inventory cannot be opened safely"
            ) from exc

    def _require_public_tree_frozen(
        self,
        root: Path,
        *,
        inventory: list[dict[str, Any]],
        directories: tuple[str, ...],
    ) -> None:
        """Require the cooperative freeze still to cover every measured node."""

        root_descriptor = self._open_public_root(root)
        try:
            self._require_public_tree_frozen_descriptor(
                root_descriptor,
                inventory=inventory,
                directories=directories,
            )
        finally:
            os.close(root_descriptor)

    def _require_public_tree_frozen_descriptor(
        self,
        root_descriptor: int,
        *,
        inventory: list[dict[str, Any]],
        directories: tuple[str, ...],
    ) -> None:
        try:
            for item in inventory:
                descriptor = self._open_inventory_source(
                    root_descriptor,
                    str(item["path"]),
                )
                try:
                    path_stat = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
                if not stat.S_ISREG(path_stat.st_mode) or stat.S_IMODE(path_stat.st_mode) & 0o222:
                    raise SuccessorGenerationStoreError(
                        "current successor public tree cooperative freeze has been reversed"
                    )
            for relative_path in (*directories, None):
                descriptor = self._open_inventory_directory(
                    root_descriptor,
                    relative_path,
                )
                try:
                    directory_stat = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
                if (
                    not stat.S_ISDIR(directory_stat.st_mode)
                    or stat.S_IMODE(directory_stat.st_mode) & 0o222
                ):
                    raise SuccessorGenerationStoreError(
                        "current successor public tree cooperative freeze has been reversed"
                    )
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "current successor public tree changed while checking cooperative freeze"
            ) from exc

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(path, flags)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate directory cannot be synchronized"
            ) from exc

    @staticmethod
    def _require_sha256(value: object, *, label: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"{label} must be a lowercase SHA-256")
        return value

    def _require_exact_candidate(
        self,
        candidate_root: Path,
        transaction: SuccessorUpdateTransaction,
    ) -> Path:
        candidate = Path(candidate_root)
        expected = self.candidate_path(transaction)
        if candidate != expected:
            raise SuccessorGenerationStoreError(
                "successor candidate path does not match its canonical transaction identity"
            )
        if (
            not candidate.is_dir()
            or candidate.is_symlink()
            or not self.generations_root.is_dir()
            or self.generations_root.is_symlink()
            or candidate.resolve().parent != self.generations_root.resolve()
        ):
            raise SuccessorGenerationStoreError(
                "successor candidate must be a direct regular generation directory"
            )
        return candidate

    @staticmethod
    def _require_promoted(transaction: SuccessorUpdateTransaction) -> None:
        if not isinstance(transaction, SuccessorUpdateTransaction):
            raise SuccessorGenerationStoreError("promotion requires a SuccessorUpdateTransaction")
        if transaction.state is not SuccessorGenerationState.PROMOTED:
            raise SuccessorGenerationStoreError(
                "only a validated promoted successor transaction may become current"
            )
        try:
            _ = transaction.promoted_assurance
        except SuccessorUpdateContractError as exc:
            raise SuccessorGenerationStoreError(
                "successor promotion authority is incomplete"
            ) from exc

    def _gate_publication_before_promote(
        self,
        public_root: Path,
        transaction: SuccessorUpdateTransaction,
    ) -> None:
        """Fail closed on missing formats, inventory/parity, or stale watermarks."""

        try:
            require_successor_publication_formats(public_root)
        except ValueError as exc:
            raise SuccessorGenerationStoreError(str(exc)) from exc
        admission = self._publication_inventory_admission()
        try:
            tables = inspect_successor_candidate_publication(public_root, **admission)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise SuccessorGenerationStoreError(
                f"successor candidate publication inventory failed: {exc}"
            ) from exc
        try:
            validate_successor_publication_freshness(
                public_root,
                as_of_utc=transaction.intent.as_of_utc,
                expected_tables=tables,
            )
        except ValueError as exc:
            raise SuccessorGenerationStoreError(
                f"successor candidate publication freshness failed: {exc}"
            ) from exc

    def _publication_inventory_admission(self) -> dict[str, Any]:
        scratch = self.root / _PUBLICATION_INVENTORY_SCRATCH_NAME
        if scratch.is_symlink():
            raise SuccessorGenerationStoreError(
                "publication inventory scratch must not be a symlink"
            )
        scratch.mkdir(mode=0o700, exist_ok=True)
        try:
            observed = os.stat(scratch, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "publication inventory scratch cannot be measured"
            ) from exc
        if not stat.S_ISDIR(observed.st_mode):
            raise SuccessorGenerationStoreError(
                "publication inventory scratch must be a regular directory"
            )
        return {
            "scratch_parent": scratch,
            "expected_scratch_root_identity": (observed.st_dev, observed.st_ino),
            "inventory_duckdb_snapshot_max_bytes": _PUBLICATION_INVENTORY_SNAPSHOT_MAX_BYTES,
            "inventory_sqlite_snapshot_max_bytes": _PUBLICATION_INVENTORY_SNAPSHOT_MAX_BYTES,
            "transform_scratch_max_bytes": _PUBLICATION_INVENTORY_SNAPSHOT_MAX_BYTES,
        }

    def _generation_directories(self) -> list[Path]:
        if not self.generations_root.is_dir() or self.generations_root.is_symlink():
            raise SuccessorGenerationStoreError(
                "successor generations root must be a regular directory"
            )
        children: list[Path] = []
        try:
            with os.scandir(self.generations_root) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor generations root cannot be listed"
            ) from exc
        for entry in entries:
            if entry.name.startswith("."):
                if entry.name.endswith(".tmp") and entry.is_dir(follow_symlinks=False):
                    raise SuccessorGenerationStoreError(
                        "refusing generation collection while a candidate, executing, "
                        "or unassured generation exists"
                    )
                continue
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                raise SuccessorGenerationStoreError(
                    "successor generations root contains a non-generation entry"
                )
            if not entry.name.startswith("generation-"):
                raise SuccessorGenerationStoreError(
                    "successor generations root contains a non-generation entry"
                )
            children.append(self.generations_root / entry.name)
        return children

    def _remove_generation_directory(self, path: Path) -> None:
        try:
            path.relative_to(self.generations_root)
        except ValueError as exc:
            raise SuccessorGenerationStoreError(
                "retired generation is outside the generation store"
            ) from exc
        if path.is_symlink() or not path.is_dir() or path.parent != self.generations_root:
            raise SuccessorGenerationStoreError(
                "retired generation must be a direct regular generation directory"
            )
        for root, dir_names, file_names in os.walk(path, topdown=True, followlinks=False):
            root_path = Path(root)
            os.chmod(root_path, 0o700)
            for name in (*dir_names, *file_names):
                child = root_path / name
                if child.is_symlink():
                    raise SuccessorGenerationStoreError("retired generation contains a symlink")
                os.chmod(child, 0o700 if child.is_dir() else 0o600)
        for root, dir_names, file_names in os.walk(path, topdown=False, followlinks=False):
            root_path = Path(root)
            for name in file_names:
                (root_path / name).unlink()
            for name in dir_names:
                (root_path / name).rmdir()
        path.rmdir()

    @staticmethod
    def _decode_transaction(encoded: bytes) -> SuccessorUpdateTransaction:
        try:
            payload = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate transaction is not valid JSON"
            ) from exc
        if not isinstance(payload, Mapping):
            raise SuccessorGenerationStoreError(
                "successor candidate transaction has an unsupported schema"
            )
        try:
            transaction = SuccessorUpdateTransaction.from_dict(
                cast("Mapping[str, object]", payload)
            )
        except SuccessorUpdateContractError as exc:
            raise SuccessorGenerationStoreError(
                "successor candidate transaction is invalid"
            ) from exc
        if encoded != _canonical_document(payload):
            raise SuccessorGenerationStoreError("successor candidate transaction is not canonical")
        return transaction

    def _reference(
        self,
        transaction: SuccessorUpdateTransaction,
        *,
        installed_public_tree_sha256: str,
    ) -> dict[str, object]:
        assurance = transaction.promoted_assurance
        return {
            "generation": transaction.generation,
            "candidate_name": self.candidate_name(transaction),
            "transaction_sha256": transaction.content_sha256,
            "assurance_sha256": assurance.identity_sha256,
            "data_tree_fingerprint": assurance.successor_data_tree_fingerprint,
            "installed_public_tree_sha256": installed_public_tree_sha256,
            "private_generation_receipt_sha256": (assurance.private_generation_receipt_sha256),
        }

    def _require_current_reference_authority(
        self,
        reference: Mapping[str, object],
    ) -> None:
        """Re-prove the referenced transaction, topology, bytes, and freeze."""

        candidate_name = cast("str", reference["candidate_name"])
        candidate = self.generations_root / candidate_name
        candidate_descriptor = self._require_bound_candidate_descriptor(candidate)
        public_descriptor = -1
        try:
            if candidate_descriptor >= 0:
                encoded = self._read_regular_file_relative(
                    candidate_descriptor,
                    SUCCESSOR_TRANSACTION_NAME,
                    label="successor candidate transaction",
                )
                transaction = self._decode_transaction(encoded)
                if candidate_name != self.candidate_name(transaction):
                    raise SuccessorGenerationStoreError(
                        "successor candidate directory does not match its transaction identity"
                    )
                public_descriptor = self._open_child_directory(
                    candidate_descriptor,
                    "public",
                    label="current successor public tree",
                )
                public_root = None
            else:
                transaction = self.load_transaction(candidate)
                public_root = candidate / "public"
            self._require_promoted(transaction)
            expected_digest = cast("str", reference["installed_public_tree_sha256"])
            if dict(reference) != self._reference(
                transaction,
                installed_public_tree_sha256=expected_digest,
            ):
                raise SuccessorGenerationStoreError(
                    "current successor generation reference differs from stored authority"
                )
            if transaction.promoted_assurance.installed_public_tree_sha256 != expected_digest:
                raise SuccessorGenerationStoreError(
                    "current successor installed public tree differs from transaction assurance"
                )
            measurement = (
                self._measure_installed_public_tree_descriptor(
                    public_descriptor,
                    label="current successor public tree",
                )
                if public_descriptor >= 0
                else self._measure_installed_public_tree(
                    cast("Path", public_root),
                    label="current successor public tree",
                )
            )
            if measurement.installed_public_tree_sha256 != expected_digest:
                raise SuccessorGenerationStoreError(
                    "current successor public tree differs from pointer authority"
                )
            if public_descriptor >= 0:
                self._require_public_tree_frozen_descriptor(
                    public_descriptor,
                    inventory=measurement.to_inventory(),
                    directories=measurement.directories,
                )
            else:
                self._require_public_tree_frozen(
                    cast("Path", public_root),
                    inventory=measurement.to_inventory(),
                    directories=measurement.directories,
                )
            if candidate_descriptor >= 0:
                self._require_candidate_descriptor_current(candidate, candidate_descriptor)
        finally:
            if public_descriptor >= 0:
                os.close(public_descriptor)
            if candidate_descriptor >= 0:
                os.close(candidate_descriptor)

    @staticmethod
    def _validate_reference(value: object, *, label: str) -> None:
        if not isinstance(value, Mapping):
            raise SuccessorGenerationStoreError(
                f"{label} successor generation reference must be an object"
            )
        reference = cast("Mapping[str, object]", value)
        expected = {
            "generation",
            "candidate_name",
            "transaction_sha256",
            "assurance_sha256",
            "data_tree_fingerprint",
            "installed_public_tree_sha256",
            "private_generation_receipt_sha256",
        }
        if set(reference) != expected:
            raise SuccessorGenerationStoreError(
                f"{label} successor generation reference has invalid fields"
            )
        generation = reference["generation"]
        if type(generation) is not int or generation < 1:
            raise SuccessorGenerationStoreError(
                f"{label} successor generation must be a positive integer"
            )
        candidate_name = reference["candidate_name"]
        prefix = f"generation-{generation:08d}-"
        if (
            not isinstance(candidate_name, str)
            or not candidate_name.startswith(prefix)
            or len(candidate_name) != len(prefix) + 16
            or any(character not in "0123456789abcdef" for character in candidate_name[-16:])
        ):
            raise SuccessorGenerationStoreError(f"{label} successor candidate name is invalid")
        for field_name in expected - {"generation", "candidate_name"}:
            digest = reference[field_name]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise SuccessorGenerationStoreError(
                    f"{label} successor {field_name} must be a lowercase SHA-256"
                )

    @staticmethod
    def _read_regular_file(path: Path, *, label: str) -> bytes:
        flags = os.O_RDONLY
        for flag_name in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
            flags |= getattr(os, flag_name, 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(path, flags)
            stat_before = os.fstat(descriptor)
            if not stat.S_ISREG(stat_before.st_mode):
                raise SuccessorGenerationStoreError(f"{label} must be a regular file")
            if stat_before.st_size > _MAX_CONTROL_BYTES:
                raise SuccessorGenerationStoreError(f"{label} exceeds the safe size limit")
            chunks: list[bytes] = []
            remaining = _MAX_CONTROL_BYTES + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            encoded = b"".join(chunks)
            stat_after = os.fstat(descriptor)
            path_after = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorGenerationStoreError(f"{label} cannot be read safely") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        identity_before = (
            stat_before.st_dev,
            stat_before.st_ino,
            stat_before.st_size,
            stat_before.st_mtime_ns,
        )
        identity_after = (
            stat_after.st_dev,
            stat_after.st_ino,
            stat_after.st_size,
            stat_after.st_mtime_ns,
        )
        path_identity = (path_after.st_dev, path_after.st_ino)
        descriptor_identity = (stat_after.st_dev, stat_after.st_ino)
        if (
            identity_before != identity_after
            or path_identity != descriptor_identity
            or len(encoded) != stat_after.st_size
            or len(encoded) > _MAX_CONTROL_BYTES
        ):
            raise SuccessorGenerationStoreError(f"{label} changed while reading")
        return encoded

    @staticmethod
    def _read_regular_file_relative(
        parent_descriptor: int,
        name: str,
        *,
        label: str,
    ) -> bytes:
        flags = os.O_RDONLY
        for flag_name in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
            flags |= getattr(os, flag_name, 0)
        descriptor = -1
        try:
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
            opened_before = os.fstat(descriptor)
            named_before = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            admitted = _stat_identity(opened_before)
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or admitted != _stat_identity(named_before)
                or opened_before.st_nlink != 1
            ):
                raise SuccessorGenerationStoreError(f"{label} must be one stable regular file")
            if opened_before.st_size > _MAX_CONTROL_BYTES:
                raise SuccessorGenerationStoreError(f"{label} exceeds the safe size limit")
            remaining = opened_before.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise SuccessorGenerationStoreError(f"{label} ended before its admitted size")
                chunks.append(chunk)
                remaining -= len(chunk)
            opened_after = os.fstat(descriptor)
            named_after = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if admitted != _stat_identity(opened_after) or admitted != _stat_identity(named_after):
                raise SuccessorGenerationStoreError(f"{label} changed while reading")
            return b"".join(chunks)
        except OSError as exc:
            raise SuccessorGenerationStoreError(f"{label} cannot be read safely") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _atomic_write(self, path: Path, encoded: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise SuccessorGenerationStoreError(
                "successor control file parent must not be a symlink"
            )
        temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError as exc:
            raise SuccessorGenerationStoreError(
                "successor control file cannot be written atomically"
            ) from exc
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()
