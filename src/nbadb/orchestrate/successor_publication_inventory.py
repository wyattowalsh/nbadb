"""Descriptor-safe local evidence for a successor publication tree.

This module owns the local data-tree inspection used by successor terminal
assurance.  It inventories the fixed publication contract without calling
Kaggle code, tolerates but excludes either canonical control file during crash
reentry, validates cross-format table parity, and returns only path-free
schema-v6 evidence. DuckDB and Parquet are the authoritative logical-type
formats and therefore receive exact row-multiset value validation. SQLite and
CSV remain convenience projections: their table, row-count, and ordered-column
contracts are validated, but they are not falsely treated as type-lossless.
"""

from __future__ import annotations

import csv
import errno
import fcntl
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final, cast

import duckdb
import pyarrow.parquet as pq

from nbadb.core.types import validate_sql_identifier
from nbadb.orchestrate.seasons import season_string
from nbadb.orchestrate.successor_assurance import (
    SuccessorAssuranceContractError,
    SuccessorDatabaseEvidence,
    SuccessorPublicEvidence,
    SuccessorPublicResourceAttestation,
)
from nbadb.orchestrate.successor_inode import (
    directory_inode,
    remove_empty_owned_directory,
)
from nbadb.orchestrate.successor_transform_authority import (
    TransformOutputAttestation,
    _attest_exact_tables,
    build_successor_transform_attestations,
)
from nbadb.orchestrate.transformers import expected_transform_output_tables

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping, Sequence

__all__ = [
    "SuccessorPublicationInventoryEvidence",
    "build_successor_publication_inventory",
    "inspect_successor_candidate_publication",
    "read_successor_publication_watermarks",
    "require_successor_publication_formats",
    "successor_publication_freshness_season",
    "validate_successor_publication_freshness",
]

_REQUIRED_PUBLIC_FORMAT_FILES: Final = ("nba.duckdb", "nba.sqlite")
_REQUIRED_PUBLIC_FORMAT_DIRECTORIES: Final = ("csv", "parquet")
_WATERMARK_TYPE_LAST_LOAD: Final = "last_load"
_UTC_INSTANT_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"

_CONTROL_RESOURCES: Final = frozenset(
    {"assured-artifact-manifest.json", "terminal-assurance-report.json"}
)
_CONDITIONAL_RESOURCE_INCREMENT: Final = 2
_CONDITIONAL_TABLE_INCREMENT: Final = 1
_COPY_CHUNK_BYTES: Final = 4 * 1024 * 1024
_MIN_SCRATCH_RESERVE_BYTES: Final = 64 * 1024 * 1024
_MAX_AUTHORITATIVE_COLUMNS: Final = 2_048
_MAX_AUTHORITATIVE_PARQUET_FILES_PER_TABLE: Final = 512
_MAX_AUTHORITATIVE_PARTITION_COLUMNS: Final = 8
_MIN_VALUE_PARITY_MEMORY_BYTES: Final = 64 * 1024 * 1024
_MAX_VALUE_PARITY_MEMORY_BYTES: Final = 512 * 1024 * 1024
_MIN_VALUE_PARITY_TEMP_BYTES: Final = 64 * 1024 * 1024
_MAX_VALUE_PARITY_TEMP_BYTES: Final = 256 * 1024 * 1024 * 1024
_OPEN_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_OPEN_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_OPEN_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK
)


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _registered_public_raw_tables() -> tuple[frozenset[str], frozenset[str]]:
    """Return the public raw table sets under the exact-four private-only rule.

    The four provider-body authority relations are private-only: their public
    projection must be empty, and none of the four names may appear inside the
    exact-six public W2 value-authority catalog (or any other public surface).
    """

    from nbadb.orchestrate.raw_publication_inventory import (
        PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES,
        raw_request_authority_publication_tables,
    )
    from nbadb.orchestrate.w2_publication_inventory import (
        w2_public_value_authority_publication_tables,
    )

    raw_v2 = frozenset(entry.table_name for entry in raw_request_authority_publication_tables())
    w2 = frozenset(entry.table_name for entry in w2_public_value_authority_publication_tables())
    private_only = frozenset(PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES)
    if raw_v2 or len(w2) != 6 or raw_v2 & w2 or private_only & w2:
        raise SuccessorAssuranceContractError(
            "repository raw publication authorities must keep the exact-four "
            "private-only and the exact-six disjoint"
        )
    return raw_v2, w2


@dataclass(frozen=True, slots=True)
class SuccessorPublicationInventoryEvidence:
    """Path-free public-resource and database evidence from one stable tree."""

    public_evidence: SuccessorPublicEvidence
    database_evidence: SuccessorDatabaseEvidence
    transform_outputs: tuple[TransformOutputAttestation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.public_evidence, SuccessorPublicEvidence):
            raise TypeError("public_evidence must be SuccessorPublicEvidence")
        if not isinstance(self.database_evidence, SuccessorDatabaseEvidence):
            raise TypeError("database_evidence must be SuccessorDatabaseEvidence")
        if not isinstance(self.transform_outputs, tuple) or any(
            not isinstance(item, TransformOutputAttestation) for item in self.transform_outputs
        ):
            raise TypeError("transform_outputs must be transform attestations")
        expected_transforms = tuple(sorted(expected_transform_output_tables(include_live=True)))
        if not expected_transforms or len(expected_transforms) != len(set(expected_transforms)):
            raise SuccessorAssuranceContractError(
                "repository transform authority is not a unique convention-discovered universe"
            )
        observed_transforms = tuple(item.table_name for item in self.transform_outputs)
        if observed_transforms != expected_transforms:
            raise SuccessorAssuranceContractError(
                "publication transform authority differs from the current discovered universe"
            )
        duckdb_resource = self.public_evidence.resource("nba.duckdb")
        sqlite_resource = self.public_evidence.resource("nba.sqlite")
        if (
            duckdb_resource.kind != "file"
            or duckdb_resource.sha256 != self.database_evidence.duckdb_sha256
            or duckdb_resource.bytes != self.database_evidence.duckdb_bytes
            or sqlite_resource.kind != "file"
            or sqlite_resource.sha256 != self.database_evidence.sqlite_sha256
            or sqlite_resource.bytes != self.database_evidence.sqlite_bytes
        ):
            raise SuccessorAssuranceContractError(
                "database evidence differs from the public resource inventory"
            )


@dataclass(frozen=True, slots=True)
class _DataContract:
    resources: tuple[tuple[str, str], ...]
    tables: tuple[str, ...]
    partitioned_tables: frozenset[str]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, str]) -> _DataContract:
        resources = tuple(sorted(raw.items()))
        if not resources:
            raise ValueError("successor publication data contract must not be empty")
        if len(resources) != len({path for path, _kind in resources}):
            raise ValueError("successor publication data contract contains duplicate paths")
        kinds = {kind for _path, kind in resources}
        if not kinds <= {"file", "directory"}:
            raise ValueError("successor publication data contract contains an invalid kind")

        resource_map = dict(resources)
        if resource_map.get("nba.duckdb") != "file" or resource_map.get("nba.sqlite") != "file":
            raise ValueError("successor publication data contract requires both database files")

        csv_tables: set[str] = set()
        parquet_tables: set[str] = set()
        partitioned_tables: set[str] = set()
        for resource_path, kind in resources:
            path = PurePosixPath(resource_path)
            if (
                path.is_absolute()
                or path.as_posix() != resource_path
                or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
            ):
                raise ValueError(
                    f"successor publication data contract path is unsafe: {resource_path}"
                )
            if resource_path in {"nba.duckdb", "nba.sqlite"}:
                continue
            if len(path.parts) == 2 and path.parts[0] == "csv" and path.suffix == ".csv":
                if kind != "file":
                    raise ValueError(f"CSV publication resource must be a file: {resource_path}")
                table = path.stem
                validate_sql_identifier(table)
                if table in csv_tables:
                    raise ValueError(f"duplicate CSV publication table: {table}")
                csv_tables.add(table)
                continue
            if len(path.parts) == 2 and path.parts[0] == "parquet":
                if kind != "directory":
                    raise ValueError(
                        "partitioned Parquet publication resource must be a directory: "
                        f"{resource_path}"
                    )
                table = path.parts[1]
                validate_sql_identifier(table)
                if table in parquet_tables:
                    raise ValueError(f"duplicate Parquet publication table: {table}")
                parquet_tables.add(table)
                partitioned_tables.add(table)
                continue
            if (
                len(path.parts) == 3
                and path.parts[0] == "parquet"
                and path.suffix == ".parquet"
                and path.parts[2] == f"{path.parts[1]}.parquet"
            ):
                if kind != "file":
                    raise ValueError(
                        "unpartitioned Parquet publication resource must be a file: "
                        f"{resource_path}"
                    )
                table = path.parts[1]
                validate_sql_identifier(table)
                if table in parquet_tables:
                    raise ValueError(f"duplicate Parquet publication table: {table}")
                parquet_tables.add(table)
                continue
            raise ValueError(f"unexpected successor publication contract path: {resource_path}")

        if csv_tables != parquet_tables:
            raise ValueError(
                "successor publication CSV and Parquet table contracts differ: "
                f"missing_csv={sorted(parquet_tables - csv_tables)}; "
                f"missing_parquet={sorted(csv_tables - parquet_tables)}"
            )
        raw_tables = frozenset(table for table in csv_tables if table.startswith("raw_"))
        if raw_tables:
            raw_v2, w2 = _registered_public_raw_tables()
            expected_raw = raw_v2 | w2
            if raw_tables != expected_raw:
                raise ValueError(
                    "successor publication raw table universe differs from the registered "
                    "exact-four/exact-six authority: "
                    f"missing={sorted(expected_raw - raw_tables)}; "
                    f"unexpected={sorted(raw_tables - expected_raw)}"
                )
        return cls(
            resources=resources,
            tables=tuple(sorted(csv_tables)),
            partitioned_tables=frozenset(partitioned_tables),
        )


def _production_data_contract(root: Path | None = None) -> _DataContract:
    from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
    from nbadb.kaggle.metadata import expected_full_publication_resource_contract
    from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY

    complete = expected_full_publication_resource_contract(root)
    static_complete = expected_full_publication_resource_contract(
        include_lossless_fallback=False,
        include_live_lossless=False,
    )
    conditional_resources = {
        staging_key: {
            f"csv/{staging_key}.csv": "file",
            f"parquet/{staging_key}/{staging_key}.parquet": "file",
        }
        for staging_key in (
            LIVE_LOSSLESS_STAGING_KEY,
            LOSSLESS_FALLBACK_STAGING_KEY,
        )
    }
    present_conditionals = tuple(
        staging_key
        for staging_key, resources in conditional_resources.items()
        if set(complete) & set(resources)
    )
    expected_complete = {
        **static_complete,
        **{
            resource_id: kind
            for staging_key in present_conditionals
            for resource_id, kind in conditional_resources[staging_key].items()
        },
    }
    if complete != dict(sorted(expected_complete.items())):
        raise SuccessorAssuranceContractError(
            "repository publication contract differs from its conditional resource universe"
        )
    if {path: complete.get(path) for path in _CONTROL_RESOURCES} != {
        path: "file" for path in _CONTROL_RESOURCES
    }:
        raise SuccessorAssuranceContractError(
            "repository publication contract has invalid schema-v6 control resources"
        )
    data = {path: kind for path, kind in complete.items() if path not in _CONTROL_RESOURCES}
    contract = _DataContract.from_mapping(data)
    static_data = {
        path: kind for path, kind in static_complete.items() if path not in _CONTROL_RESOURCES
    }
    static_contract = _DataContract.from_mapping(static_data)
    expected_resource_increment = _CONDITIONAL_RESOURCE_INCREMENT * len(present_conditionals)
    expected_table_increment = _CONDITIONAL_TABLE_INCREMENT * len(present_conditionals)
    if len(contract.resources) != len(static_contract.resources) + expected_resource_increment:
        raise SuccessorAssuranceContractError(
            "repository publication data resources differ from conditional authority"
        )
    if len(contract.tables) != len(static_contract.tables) + expected_table_increment:
        raise SuccessorAssuranceContractError(
            "repository publication tables differ from conditional authority"
        )
    return contract


@dataclass(frozen=True, slots=True)
class _FileObservation:
    path: str
    identity: tuple[int, int, int, int, int, int]
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _TreeSnapshot:
    root_identity: tuple[int, int, int, int, int, int]
    directories: Mapping[str, tuple[int, int, int, int, int, int]]
    files: Mapping[str, _FileObservation]


def _data_contract_from_snapshot(snapshot: _TreeSnapshot) -> _DataContract:
    mapping: dict[str, str] = {}
    if "nba.duckdb" not in snapshot.files or "nba.sqlite" not in snapshot.files:
        raise ValueError(
            "successor candidate public tree is missing required publication "
            "format(s): nba.duckdb, nba.sqlite"
        )
    mapping["nba.duckdb"] = "file"
    mapping["nba.sqlite"] = "file"
    parquet_unpartitioned: set[str] = set()
    for path in snapshot.files:
        if path in _CONTROL_RESOURCES or path in {"nba.duckdb", "nba.sqlite"}:
            continue
        resource = PurePosixPath(path)
        if len(resource.parts) == 2 and resource.parts[0] == "csv" and resource.suffix == ".csv":
            mapping[path] = "file"
            continue
        if (
            len(resource.parts) == 3
            and resource.parts[0] == "parquet"
            and resource.suffix == ".parquet"
            and resource.parts[2] == f"{resource.parts[1]}.parquet"
        ):
            mapping[path] = "file"
            parquet_unpartitioned.add(resource.parts[1])
    for directory in snapshot.directories:
        if directory in {".", "csv", "parquet"}:
            continue
        resource = PurePosixPath(directory)
        if len(resource.parts) == 2 and resource.parts[0] == "parquet":
            table = resource.parts[1]
            if table not in parquet_unpartitioned:
                mapping[directory] = "directory"
    return _DataContract.from_mapping(mapping)


@dataclass(frozen=True, slots=True)
class _DatabaseSnapshot:
    path: Path
    descriptor: int
    identity: tuple[int, int, int, int, int, int]
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _AuthoritativeParquetFile:
    """One exact Parquet input plus partition values omitted from its payload."""

    location: str
    descriptor: int
    physical_columns: tuple[str, ...]
    partitions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _ScratchAuthority:
    path: Path
    descriptor: int
    identity: tuple[int, int]
    opened_identity: tuple[int, int, int, int]


def _directory_authority_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode)


def _positive_capacity(value: object, *, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _sha256_receipt(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _configure_authoritative_query_limits(
    connection: duckdb.DuckDBPyConnection,
    *,
    temporary_directory: Path,
    temp_max_bytes: int,
    memory_limit_bytes: int | None = None,
) -> None:
    temp_capacity = _positive_capacity(
        temp_max_bytes,
        label="authoritative value-parity temporary maximum",
    )
    if not _MIN_VALUE_PARITY_TEMP_BYTES <= temp_capacity <= _MAX_VALUE_PARITY_TEMP_BYTES:
        raise ValueError("authoritative value-parity temporary maximum is outside safe bounds")
    if memory_limit_bytes is None:
        memory_capacity = min(
            _MAX_VALUE_PARITY_MEMORY_BYTES,
            max(_MIN_VALUE_PARITY_MEMORY_BYTES, temp_capacity // 8),
        )
    else:
        memory_capacity = _positive_capacity(
            memory_limit_bytes,
            label="authoritative value-parity memory maximum",
        )
        if not _MIN_VALUE_PARITY_MEMORY_BYTES <= memory_capacity <= _MAX_VALUE_PARITY_MEMORY_BYTES:
            raise ValueError("authoritative value-parity memory maximum is outside safe bounds")
    connection.execute("PRAGMA disable_object_cache")
    connection.execute("SET temp_directory = ?", [str(temporary_directory)])
    connection.execute("SET max_temp_directory_size = ?", [f"{temp_capacity}B"])
    connection.execute("SET memory_limit = ?", [f"{memory_capacity}B"])
    connection.execute("SET preserve_insertion_order = false")
    connection.execute("SET threads = 1")


def _expected_directory_identity(value: object, *, label: str) -> tuple[int, int]:
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(part) is not int or part < 0 for part in value)
        or value[1] == 0
    ):
        raise ValueError(f"{label} is invalid")
    return cast("tuple[int, int]", value)


def _require_private_directory(value: os.stat_result, *, label: str) -> None:
    mode = stat.S_IMODE(value.st_mode)
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or mode & 0o077
        or mode & 0o700 != 0o700
    ):
        raise ValueError(f"{label} must be owner-only and owner-accessible")


def _require_scratch_path(authority: _ScratchAuthority, *, stage: str) -> None:
    try:
        held = os.fstat(authority.descriptor)
        named = os.stat(authority.path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"successor publication scratch root changed at {stage}") from exc
    if (
        _directory_authority_identity(held) != authority.opened_identity
        or _directory_authority_identity(named) != authority.opened_identity
        or (held.st_dev, held.st_ino) != authority.identity
    ):
        raise ValueError(f"successor publication scratch root changed at {stage}")


@contextmanager
def _open_scratch_authority(
    path: Path,
    *,
    expected_identity: tuple[int, int],
) -> Iterator[_ScratchAuthority]:
    scratch = Path(path)
    if not scratch.is_absolute():
        raise ValueError("successor publication scratch parent must be absolute")
    expected = _expected_directory_identity(
        expected_identity,
        label="successor publication expected scratch root identity",
    )
    try:
        named = os.stat(scratch, follow_symlinks=False)
    except OSError as exc:
        raise NotADirectoryError("successor publication scratch parent is unavailable") from exc
    _require_private_directory(named, label="successor publication scratch parent")
    if (named.st_dev, named.st_ino) != expected:
        raise ValueError("successor publication scratch root differs from expected authority")
    descriptor = -1
    try:
        descriptor = os.open(scratch, _DIRECTORY_FLAGS)
        opened = os.fstat(descriptor)
        if _identity(opened) != _identity(named):
            raise ValueError("successor publication scratch root changed before admission")
        authority = _ScratchAuthority(
            path=scratch,
            descriptor=descriptor,
            identity=expected,
            opened_identity=_directory_authority_identity(opened),
        )
        _require_scratch_path(authority, stage="admission")
        yield authority
        _require_scratch_path(authority, stage="release")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _scratch_free_bytes(authority: _ScratchAuthority) -> int:
    observed = os.fstatvfs(authority.descriptor)
    return observed.f_bavail * observed.f_frsize


def _write_snapshot_chunk(descriptor: int, payload: memoryview) -> int:
    return os.write(descriptor, payload)


def _reserve_private_directory(
    authority: _ScratchAuthority,
    *,
    prefix: str,
) -> tuple[str, int, os.stat_result]:
    for _ in range(128):
        name = f"{prefix}{secrets.token_hex(16)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=authority.descriptor)
        except FileExistsError:
            continue
        descriptor = -1
        expected_inode: tuple[int, int] | None = None
        try:
            descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=authority.descriptor)
            opened = os.fstat(descriptor)
            expected_inode = directory_inode(opened)
            named = os.stat(name, dir_fd=authority.descriptor, follow_symlinks=False)
            _require_private_directory(opened, label="successor publication private scratch")
            if directory_inode(opened) != directory_inode(named):
                raise ValueError("successor publication private scratch changed while reserving")
            return name, descriptor, opened
        except BaseException:
            if descriptor >= 0:
                try:
                    if expected_inode is None:
                        expected_inode = directory_inode(os.fstat(descriptor))
                    remove_empty_owned_directory(
                        authority.descriptor,
                        name,
                        descriptor,
                        expected_inode=expected_inode,
                        error=ValueError,
                        label="successor publication private scratch reservation",
                    )
                except (OSError, ValueError):
                    pass
                finally:
                    os.close(descriptor)
            raise
    raise ValueError("successor publication private scratch cannot be reserved")


def _require_private_directory_name(
    authority: _ScratchAuthority,
    name: str,
    descriptor: int,
    expected: os.stat_result,
    *,
    stage: str,
    require_root_path: bool = True,
) -> None:
    if require_root_path:
        _require_scratch_path(authority, stage=stage)
    try:
        held = os.fstat(descriptor)
        named = os.stat(name, dir_fd=authority.descriptor, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"successor publication private scratch changed at {stage}") from exc
    expected_identity = _directory_authority_identity(expected)
    if (
        _directory_authority_identity(held) != expected_identity
        or _directory_authority_identity(named) != expected_identity
    ):
        raise ValueError(f"successor publication private scratch changed at {stage}")


def _open_child(
    parent_descriptor: int,
    name: str,
    *,
    display_path: str,
) -> tuple[int, os.stat_result]:
    try:
        listed = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"successor public tree changed while stating: {display_path}") from exc
    if stat.S_ISLNK(listed.st_mode):
        raise ValueError(f"successor public tree must not contain symlinks: {display_path}")
    if not (stat.S_ISREG(listed.st_mode) or stat.S_ISDIR(listed.st_mode)):
        raise ValueError(f"successor public tree contains a special entry: {display_path}")
    flags = os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise ValueError(
                f"successor public tree must not contain symlinks: {display_path}"
            ) from exc
        raise ValueError(f"successor public tree changed while opening: {display_path}") from exc
    opened = os.fstat(descriptor)
    if _identity(opened) != _identity(listed):
        os.close(descriptor)
        raise ValueError(f"successor public tree entry changed while opening: {display_path}")
    return descriptor, opened


def _hash_descriptor(descriptor: int, *, display_path: str) -> tuple[int, str]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"successor public tree path is not a regular file: {display_path}")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    after = os.fstat(descriptor)
    if _identity(after) != _identity(before):
        raise ValueError(f"successor public tree file changed while hashing: {display_path}")
    return before.st_size, digest.hexdigest()


def _inventory_directory(
    descriptor: int,
    *,
    prefix: PurePosixPath | None,
    directories: dict[str, tuple[int, int, int, int, int, int]],
    files: dict[str, _FileObservation],
) -> None:
    display = "." if prefix is None else prefix.as_posix()
    before = os.fstat(descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise ValueError(f"successor public tree path is not a directory: {display}")
    try:
        with os.scandir(descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
    except OSError as exc:
        raise ValueError(f"successor public tree directory cannot be read: {display}") from exc
    for name in names:
        relative = PurePosixPath(name) if prefix is None else prefix / name
        relative_path = relative.as_posix()
        if name.startswith("."):
            raise ValueError(f"successor public tree contains a hidden path: {relative_path}")
        child, child_stat = _open_child(descriptor, name, display_path=relative_path)
        try:
            if stat.S_ISDIR(child_stat.st_mode):
                _inventory_directory(
                    child,
                    prefix=relative,
                    directories=directories,
                    files=files,
                )
                continue
            byte_count, sha256 = _hash_descriptor(child, display_path=relative_path)
            files[relative_path] = _FileObservation(
                path=relative_path,
                identity=_identity(child_stat),
                bytes=byte_count,
                sha256=sha256,
            )
        finally:
            os.close(child)
    after = os.fstat(descriptor)
    if _identity(after) != _identity(before):
        raise ValueError(f"successor public tree directory changed while reading: {display}")
    directories[display] = _identity(after)


def _open_observed_path(
    root_descriptor: int,
    snapshot: _TreeSnapshot,
    relative_path: str,
    *,
    require_directory: bool,
) -> int:
    parts = PurePosixPath(relative_path).parts
    descriptor = os.dup(root_descriptor)
    current_parts: list[str] = []
    try:
        for index, part in enumerate(parts):
            current_parts.append(part)
            display = "/".join(current_parts)
            child, observed = _open_child(descriptor, part, display_path=display)
            os.close(descriptor)
            descriptor = child
            final = index == len(parts) - 1
            if not final:
                expected_directory = snapshot.directories.get(display)
                if (
                    expected_directory is None
                    or not stat.S_ISDIR(observed.st_mode)
                    or _identity(observed) != expected_directory
                ):
                    raise ValueError(
                        f"successor public tree directory changed after inventory: {display}"
                    )
        final_stat = os.fstat(descriptor)
        if require_directory:
            expected = snapshot.directories.get(relative_path)
            valid_kind = stat.S_ISDIR(final_stat.st_mode)
        else:
            observation = snapshot.files.get(relative_path)
            expected = observation.identity if observation is not None else None
            valid_kind = stat.S_ISREG(final_stat.st_mode)
        if expected is None or not valid_kind or _identity(final_stat) != expected:
            raise ValueError(
                f"successor public tree entry changed after inventory: {relative_path}"
            )
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _verify_tree(root_descriptor: int, snapshot: _TreeSnapshot) -> None:
    if _identity(os.fstat(root_descriptor)) != snapshot.root_identity:
        raise ValueError("successor public tree root changed after inventory")
    for path in sorted(snapshot.directories):
        if path == ".":
            continue
        descriptor = _open_observed_path(
            root_descriptor,
            snapshot,
            path,
            require_directory=True,
        )
        os.close(descriptor)
    for path, observation in sorted(snapshot.files.items()):
        descriptor = _open_observed_path(
            root_descriptor,
            snapshot,
            path,
            require_directory=False,
        )
        try:
            byte_count, sha256 = _hash_descriptor(descriptor, display_path=path)
        finally:
            os.close(descriptor)
        if (byte_count, sha256) != (observation.bytes, observation.sha256):
            raise ValueError(f"successor public tree file changed after inventory: {path}")


@contextmanager
def _open_public_root(
    root: Path,
    *,
    expected_root_identity: tuple[int, int] | None,
) -> Iterator[tuple[int, _TreeSnapshot]]:
    path = Path(root)
    if not path.is_absolute():
        raise ValueError("successor public root must be absolute")
    try:
        path_before = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise NotADirectoryError(f"successor public root is not a directory: {path}") from exc
    if not stat.S_ISDIR(path_before.st_mode):
        raise NotADirectoryError(f"successor public root is not a regular directory: {path}")
    if expected_root_identity is not None:
        if (
            type(expected_root_identity) is not tuple
            or len(expected_root_identity) != 2
            or any(type(value) is not int or value < 0 for value in expected_root_identity)
        ):
            raise ValueError("successor public expected root identity is invalid")
        if (path_before.st_dev, path_before.st_ino) != expected_root_identity:
            raise ValueError("successor public root differs from expected authority")
    if not _OPEN_NOFOLLOW:
        raise RuntimeError("successor public inventory requires O_NOFOLLOW support")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | _OPEN_NOFOLLOW
        | _OPEN_CLOEXEC
        | _OPEN_NONBLOCK
    )
    try:
        root_descriptor = os.open(path, flags)
    except OSError as exc:
        raise NotADirectoryError(f"successor public root is not a directory: {path}") from exc
    try:
        opened = os.fstat(root_descriptor)
        if not stat.S_ISDIR(opened.st_mode) or _identity(opened) != _identity(path_before):
            raise ValueError("successor public root changed before inventory")
        directories: dict[str, tuple[int, int, int, int, int, int]] = {}
        files: dict[str, _FileObservation] = {}
        _inventory_directory(
            root_descriptor,
            prefix=None,
            directories=directories,
            files=files,
        )
        snapshot = _TreeSnapshot(
            root_identity=_identity(opened),
            directories=directories,
            files=files,
        )
        _verify_tree(root_descriptor, snapshot)
        yield root_descriptor, snapshot
        _verify_tree(root_descriptor, snapshot)
        path_after = os.stat(path, follow_symlinks=False)
        if _identity(path_after) != snapshot.root_identity:
            raise ValueError("successor public root pathname changed while inspecting")
    finally:
        os.close(root_descriptor)


def _resource_for_file(
    path: str, observation: _FileObservation
) -> SuccessorPublicResourceAttestation:
    return SuccessorPublicResourceAttestation(
        resource_id=path,
        kind="file",
        bytes=observation.bytes,
        sha256=observation.sha256,
    )


def _directory_resource(
    resource_path: str,
    snapshot: _TreeSnapshot,
) -> SuccessorPublicResourceAttestation:
    prefix = f"{resource_path}/"
    children = [
        {
            "path": path.removeprefix(prefix),
            "bytes": observation.bytes,
            "sha256": observation.sha256,
        }
        for path, observation in sorted(snapshot.files.items())
        if path.startswith(prefix)
    ]
    if not children:
        raise ValueError(f"successor Parquet directory resource is empty: {resource_path}")
    return SuccessorPublicResourceAttestation(
        resource_id=resource_path,
        kind="directory",
        bytes=sum(int(child["bytes"]) for child in children),
        sha256=hashlib.sha256(_canonical_json_bytes(children)).hexdigest(),
    )


def _validate_tree_contract(snapshot: _TreeSnapshot, contract: _DataContract) -> None:
    expected_files = {path for path, kind in contract.resources if kind == "file"}
    expected_directories = {path for path, kind in contract.resources if kind == "directory"}
    actual_files = set(snapshot.files) - _CONTROL_RESOURCES
    actual_directories = set(snapshot.directories) - {"."}

    missing_files = sorted(expected_files - actual_files)
    missing_directories = sorted(expected_directories - actual_directories)
    unexpected_files = sorted(
        path
        for path in actual_files
        if path not in expected_files
        and not any(path.startswith(f"{directory}/") for directory in expected_directories)
    )

    required_structural_directories: set[str] = set()
    for resource_path, _kind in contract.resources:
        parent = PurePosixPath(resource_path).parent
        while parent != PurePosixPath("."):
            required_structural_directories.add(parent.as_posix())
            parent = parent.parent
    unexpected_directories = sorted(
        path
        for path in actual_directories
        if path not in required_structural_directories
        and path not in expected_directories
        and not any(path.startswith(f"{directory}/") for directory in expected_directories)
    )
    wrong_kind = sorted(
        (expected_files & actual_directories) | (expected_directories & actual_files)
    )
    if (
        missing_files
        or missing_directories
        or unexpected_files
        or unexpected_directories
        or wrong_kind
    ):
        raise ValueError(
            "successor public tree differs from the data-resource contract: "
            f"missing_files={missing_files}; missing_directories={missing_directories}; "
            f"unexpected_files={unexpected_files}; "
            f"unexpected_directories={unexpected_directories}; "
            f"wrong_kind={wrong_kind}"
        )

    for directory in sorted(expected_directories):
        prefix = f"{directory}/"
        resource_files = sorted(path for path in actual_files if path.startswith(prefix))
        if not resource_files:
            raise ValueError(f"successor Parquet directory resource is empty: {directory}")
        for file_path in resource_files:
            relative = PurePosixPath(file_path.removeprefix(prefix))
            if relative.suffix != ".parquet":
                raise ValueError(
                    f"successor Parquet directory contains a non-Parquet file: {file_path}"
                )
            for part in relative.parts[:-1]:
                key, separator, value = part.partition("=")
                if not separator or not key or not value:
                    raise ValueError(f"successor partition directory is not key=value: {file_path}")
                validate_sql_identifier(key)
        nested_directories = sorted(
            path for path in actual_directories if path.startswith(prefix) and path != directory
        )
        for nested in nested_directories:
            if not any(path.startswith(f"{nested}/") for path in resource_files):
                raise ValueError(f"successor Parquet tree contains an empty directory: {nested}")


def _read_csv(
    root_descriptor: int,
    snapshot: _TreeSnapshot,
    resource_path: str,
) -> tuple[int, tuple[str, ...]]:
    descriptor = _open_observed_path(
        root_descriptor,
        snapshot,
        resource_path,
        require_directory=False,
    )
    duplicate = os.dup(descriptor)
    try:
        with os.fdopen(duplicate, "r", encoding="utf-8-sig", newline="", closefd=True) as handle:
            reader = csv.reader(handle, strict=True)
            try:
                columns = next(reader)
            except StopIteration as exc:
                raise ValueError(f"successor CSV resource is empty: {resource_path}") from exc
            if (
                not columns
                or any(not column for column in columns)
                or len(columns) != len(set(columns))
            ):
                raise ValueError(f"successor CSV header is invalid: {resource_path}")
            row_count = 0
            for row_number, row in enumerate(reader, start=2):
                if len(row) != len(columns):
                    raise ValueError(
                        f"successor CSV row {row_number} has invalid width: {resource_path}"
                    )
                row_count += 1
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"successor CSV resource is unreadable: {resource_path}") from exc
    finally:
        os.close(descriptor)
    return row_count, tuple(columns)


def _read_parquet_file(
    root_descriptor: int,
    snapshot: _TreeSnapshot,
    resource_path: str,
) -> tuple[int, tuple[str, ...]]:
    descriptor = _open_observed_path(
        root_descriptor,
        snapshot,
        resource_path,
        require_directory=False,
    )
    duplicate = os.dup(descriptor)
    try:
        with os.fdopen(duplicate, "rb", closefd=True) as handle:
            metadata = pq.read_metadata(handle)
            columns = tuple(metadata.schema.to_arrow_schema().names)
    except Exception as exc:
        raise ValueError(f"successor Parquet metadata is unreadable: {resource_path}") from exc
    finally:
        os.close(descriptor)
    if len(columns) != len(set(columns)):
        raise ValueError(f"successor Parquet schema has duplicate columns: {resource_path}")
    return int(metadata.num_rows), columns


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _unused_internal_identifier(columns: Collection[str], stem: str) -> str:
    occupied = set(columns)
    for index in range(len(occupied) + 1):
        candidate = stem if index == 0 else f"{stem}_{index}"
        if candidate not in occupied:
            return candidate
    raise AssertionError("bounded internal identifier selection failed")


def _partition_items(
    relative_path: PurePosixPath,
    *,
    display_path: str,
) -> tuple[tuple[str, str], ...]:
    partitions: list[tuple[str, str]] = []
    for part in relative_path.parts[:-1]:
        key, separator, value = part.partition("=")
        if not separator or not key or not value:
            raise ValueError(
                f"authoritative Parquet partition directory is not key=value: {display_path}"
            )
        validate_sql_identifier(key)
        if any(existing == key for existing, _value in partitions):
            raise ValueError(f"authoritative Parquet partition key repeats: {display_path}")
        partitions.append((key, value))
    return tuple(partitions)


def _parquet_columns_from_descriptor(
    descriptor: int,
    *,
    display_path: str,
) -> tuple[str, ...]:
    duplicate = os.dup(descriptor)
    try:
        with os.fdopen(duplicate, "rb", closefd=True) as handle:
            metadata = pq.read_metadata(handle)
            columns = tuple(metadata.schema.to_arrow_schema().names)
    except Exception as exc:
        raise ValueError(f"authoritative Parquet metadata is unreadable: {display_path}") from exc
    if not columns or len(columns) != len(set(columns)):
        raise ValueError(
            f"authoritative Parquet schema is empty or has duplicate columns: {display_path}"
        )
    os.lseek(descriptor, 0, os.SEEK_SET)
    return columns


def _rewind_authoritative_files(files: Sequence[_AuthoritativeParquetFile]) -> None:
    for parquet_file in files:
        os.lseek(parquet_file.descriptor, 0, os.SEEK_SET)


def _authoritative_parquet_relation(
    table: str,
    database_columns: tuple[str, ...],
    files: Sequence[_AuthoritativeParquetFile],
) -> tuple[str, list[object]]:
    if not files:
        raise ValueError(f"authoritative Parquet resource is empty: {table}")
    if len(files) > _MAX_AUTHORITATIVE_PARQUET_FILES_PER_TABLE:
        raise ValueError(f"authoritative Parquet resource exceeds the file fan-in bound: {table}")
    if not database_columns or len(database_columns) > _MAX_AUTHORITATIVE_COLUMNS:
        raise ValueError(f"authoritative table exceeds the column bound: {table}")
    quoted_table = _quote_identifier(table)
    first_physical = files[0].physical_columns
    first_partition_keys = tuple(key for key, _value in files[0].partitions)
    if len(first_partition_keys) > _MAX_AUTHORITATIVE_PARTITION_COLUMNS:
        raise ValueError(
            f"authoritative Parquet resource exceeds the partition-column bound: {table}"
        )
    expected_physical = tuple(
        column for column in database_columns if column not in first_partition_keys
    )
    if (
        first_physical != expected_physical
        or any(column not in database_columns for column in first_partition_keys)
        or len(first_physical) + len(first_partition_keys) != len(database_columns)
    ):
        raise ValueError(f"authoritative DuckDB-Parquet schema parity failed for table: {table}")

    selects: list[str] = []
    parameters: list[object] = []
    for parquet_file in files:
        partition_keys = tuple(key for key, _value in parquet_file.partitions)
        if (
            parquet_file.physical_columns != first_physical
            or partition_keys != first_partition_keys
        ):
            raise ValueError(f"authoritative partitioned Parquet schemas differ for table: {table}")
        partition_values = dict(parquet_file.partitions)
        projection: list[str] = []
        for column in database_columns:
            quoted_column = _quote_identifier(column)
            if column in partition_values:
                projection.append(
                    "cast_to_type(?, "
                    f"(SELECT {quoted_column} FROM {quoted_table} LIMIT 1)) "
                    f"AS {quoted_column}"
                )
                parameters.append(partition_values[column])
            else:
                projection.append(quoted_column)
        selects.append(
            "SELECT "
            + ", ".join(projection)
            + " FROM read_parquet(?, hive_partitioning = false, union_by_name = false)"
        )
        parameters.append(parquet_file.location)
    return " UNION ALL ".join(selects), parameters


def _validate_authoritative_table_values(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    files: Sequence[_AuthoritativeParquetFile],
) -> None:
    """Require exact logical row-multiset equality without Python row materialization."""

    validate_sql_identifier(table)
    quoted_table = _quote_identifier(table)
    try:
        database_description = connection.execute(
            f"DESCRIBE SELECT * FROM {quoted_table}"
        ).fetchall()
    except duckdb.Error as exc:
        raise ValueError(f"authoritative DuckDB schema is unreadable for table: {table}") from exc
    database_schema = tuple((str(row[0]), str(row[1])) for row in database_description)
    database_columns = tuple(column for column, _logical_type in database_schema)
    if not database_columns or len(database_columns) != len(set(database_columns)):
        raise ValueError(f"authoritative DuckDB schema is empty or has duplicate columns: {table}")

    relation_sql, parameters = _authoritative_parquet_relation(
        table,
        database_columns,
        files,
    )
    try:
        _rewind_authoritative_files(files)
        parquet_description = connection.execute(
            f"DESCRIBE SELECT * FROM ({relation_sql}) AS __nbadb_parquet",
            parameters,
        ).fetchall()
    except (duckdb.Error, OSError) as exc:
        raise ValueError(f"authoritative Parquet schema is unreadable for table: {table}") from exc
    parquet_schema = tuple((str(row[0]), str(row[1])) for row in parquet_description)
    if parquet_schema != database_schema:
        raise ValueError(
            f"authoritative DuckDB-Parquet logical-type parity failed for table: {table}"
        )

    delta_column = _unused_internal_identifier(database_columns, "__nbadb_delta")
    balance_column = _unused_internal_identifier(
        (*database_columns, delta_column),
        "__nbadb_balance",
    )
    projected_columns = ", ".join(_quote_identifier(column) for column in database_columns)
    quoted_delta = _quote_identifier(delta_column)
    quoted_balance = _quote_identifier(balance_column)
    parity_sql = (
        "SELECT 1 FROM ("
        f"SELECT {projected_columns}, SUM({quoted_delta}) AS {quoted_balance} FROM ("
        f"SELECT {projected_columns}, 1::BIGINT AS {quoted_delta} FROM {quoted_table} "
        "UNION ALL "
        f"SELECT {projected_columns}, -1::BIGINT AS {quoted_delta} "
        f"FROM ({relation_sql}) AS __nbadb_parquet"
        ") AS __nbadb_authoritative_rows "
        f"GROUP BY {projected_columns} HAVING SUM({quoted_delta}) <> 0"
        ") AS __nbadb_authoritative_mismatch LIMIT 1"
    )
    try:
        _rewind_authoritative_files(files)
        mismatch = connection.execute(parity_sql, parameters).fetchone()
    except (duckdb.Error, OSError) as exc:
        raise ValueError(
            f"authoritative DuckDB-Parquet value comparison failed for table: {table}"
        ) from exc
    if mismatch is not None:
        raise ValueError(
            f"authoritative DuckDB-Parquet row-multiset value parity failed for table: {table}"
        )


@contextmanager
def _open_snapshot_authoritative_parquet_files(
    root_descriptor: int,
    snapshot: _TreeSnapshot,
    contract: _DataContract,
    table: str,
) -> Iterator[tuple[_AuthoritativeParquetFile, ...]]:
    if table in contract.partitioned_tables:
        root = f"parquet/{table}"
        prefix = f"{root}/"
        resource_paths = tuple(sorted(path for path in snapshot.files if path.startswith(prefix)))
    else:
        root = f"parquet/{table}"
        prefix = f"{root}/"
        resource_paths = (f"{root}/{table}.parquet",)

    descriptors: list[int] = []
    files: list[_AuthoritativeParquetFile] = []
    try:
        for resource_path in resource_paths:
            descriptor = _open_observed_path(
                root_descriptor,
                snapshot,
                resource_path,
                require_directory=False,
            )
            descriptors.append(descriptor)
            relative_path = PurePosixPath(resource_path.removeprefix(prefix))
            files.append(
                _AuthoritativeParquetFile(
                    location=f"/dev/fd/{descriptor}",
                    descriptor=descriptor,
                    physical_columns=_parquet_columns_from_descriptor(
                        descriptor,
                        display_path=resource_path,
                    ),
                    partitions=_partition_items(
                        relative_path,
                        display_path=resource_path,
                    ),
                )
            )
        yield tuple(files)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _path_parquet_resource_files(
    table: str,
    resource: Path,
) -> tuple[tuple[Path, PurePosixPath], ...]:
    if not resource.is_absolute():
        raise ValueError(f"authoritative Parquet resource must be absolute: {table}")
    try:
        resource_stat = os.stat(resource, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"authoritative Parquet resource is unavailable: {table}") from exc
    if stat.S_ISLNK(resource_stat.st_mode):
        raise ValueError(f"authoritative Parquet resource must not be a symlink: {table}")
    if stat.S_ISREG(resource_stat.st_mode):
        if resource.suffix != ".parquet":
            raise ValueError(f"authoritative Parquet resource is not Parquet: {table}")
        return ((resource, PurePosixPath(resource.name)),)
    if not stat.S_ISDIR(resource_stat.st_mode):
        raise ValueError(f"authoritative Parquet resource has an invalid kind: {table}")

    files: list[tuple[Path, PurePosixPath]] = []
    for candidate in sorted(resource.rglob("*")):
        candidate_stat = os.stat(candidate, follow_symlinks=False)
        relative = PurePosixPath(candidate.relative_to(resource).as_posix())
        if stat.S_ISLNK(candidate_stat.st_mode):
            raise ValueError(f"authoritative Parquet resource contains a symlink: {table}")
        if stat.S_ISDIR(candidate_stat.st_mode):
            continue
        if not stat.S_ISREG(candidate_stat.st_mode) or candidate.suffix != ".parquet":
            raise ValueError(f"authoritative Parquet resource contains a non-Parquet file: {table}")
        files.append((candidate, relative))
    if not files:
        raise ValueError(f"authoritative Parquet resource is empty: {table}")
    return tuple(files)


@contextmanager
def _open_path_authoritative_parquet_files(
    table: str,
    resource: Path,
    expected_files: Mapping[str, tuple[int, str]],
    *,
    snapshot_directory: Path,
) -> Iterator[tuple[_AuthoritativeParquetFile, ...]]:
    descriptors: list[tuple[int, tuple[int, int, int, int, int, int], int, str, str]] = []
    files: list[_AuthoritativeParquetFile] = []
    try:
        resource_files = _path_parquet_resource_files(table, resource)
        observed_paths = {relative_path.as_posix() for _path, relative_path in resource_files}
        if observed_paths != set(expected_files):
            raise ValueError(
                "authoritative Parquet receipt inventory differs for table: "
                f"{table}; missing={sorted(set(expected_files) - observed_paths)}; "
                f"unexpected={sorted(observed_paths - set(expected_files))}"
            )
        for path, relative_path in resource_files:
            relative_name = relative_path.as_posix()
            expected_bytes, expected_sha256 = expected_files[relative_name]
            if type(expected_bytes) is not int or expected_bytes < 0:
                raise ValueError(
                    f"authoritative Parquet byte receipt is invalid: {table}/{relative_name}"
                )
            expected_digest = _sha256_receipt(
                expected_sha256,
                label=f"authoritative Parquet receipt for {table}/{relative_name}",
            )
            source = -1
            target = -1
            snapshot_path = snapshot_directory / f"parquet-snapshot-{len(files)}"
            try:
                source = os.open(
                    path,
                    os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK,
                )
            except OSError as exc:
                raise ValueError(
                    f"authoritative Parquet resource cannot be opened: {table}"
                ) from exc
            try:
                opened = os.fstat(source)
                if not stat.S_ISREG(opened.st_mode):
                    raise ValueError(
                        f"authoritative Parquet resource contains a special file: {table}"
                    )
                try:
                    target = os.open(
                        snapshot_path,
                        os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                        0o600,
                    )
                except OSError as exc:
                    raise ValueError(
                        f"authoritative Parquet private snapshot cannot be created: {table}"
                    ) from exc
                digest = hashlib.sha256()
                copied = 0
                os.lseek(source, 0, os.SEEK_SET)
                while chunk := os.read(source, _COPY_CHUNK_BYTES):
                    if len(chunk) > expected_bytes - copied:
                        raise ValueError(
                            "authoritative Parquet file differs from its preflight receipt "
                            "because its size exceeds the receipt: "
                            f"{table}/{relative_name}"
                        )
                    digest.update(chunk)
                    copied += len(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = _write_snapshot_chunk(target, view)
                        if written <= 0:
                            raise OSError(
                                errno.EIO,
                                "authoritative Parquet snapshot made no progress",
                            )
                        view = view[written:]
                os.fsync(target)
                if (
                    copied != expected_bytes
                    or digest.hexdigest() != expected_digest
                    or _identity(os.fstat(source)) != _identity(opened)
                ):
                    raise ValueError(
                        "authoritative Parquet file differs from its preflight receipt: "
                        f"{table}/{relative_name}"
                    )
                os.fchmod(target, 0o400)
                target_bytes, target_sha256 = _hash_descriptor(
                    target,
                    display_path=f"authoritative Parquet snapshot:{table}/{relative_name}",
                )
                if (target_bytes, target_sha256) != (expected_bytes, expected_digest):
                    raise ValueError(
                        "authoritative Parquet private snapshot differs from its receipt: "
                        f"{table}/{relative_name}"
                    )
                snapshot_path.unlink()
                target_identity = _identity(os.fstat(target))
                descriptors.append(
                    (target, target_identity, expected_bytes, expected_digest, relative_name)
                )
                files.append(
                    _AuthoritativeParquetFile(
                        location=f"/dev/fd/{target}",
                        descriptor=target,
                        physical_columns=_parquet_columns_from_descriptor(
                            target,
                            display_path=f"{table}/{relative_name}",
                        ),
                        partitions=_partition_items(
                            relative_path,
                            display_path=f"{table}/{relative_name}",
                        ),
                    )
                )
                target = -1
            finally:
                if target >= 0:
                    os.close(target)
                    with suppress(FileNotFoundError):
                        snapshot_path.unlink()
                os.close(source)
        yield tuple(files)
        for (
            descriptor,
            expected_identity,
            expected_bytes,
            expected_digest,
            relative_name,
        ) in descriptors:
            observed_bytes, observed_digest = _hash_descriptor(
                descriptor,
                display_path=f"authoritative Parquet snapshot:{table}/{relative_name}",
            )
            if _identity(os.fstat(descriptor)) != expected_identity or (
                observed_bytes,
                observed_digest,
            ) != (expected_bytes, expected_digest):
                raise ValueError(
                    f"authoritative Parquet private snapshot changed while validating: {table}"
                )
    finally:
        for descriptor, _identity_value, _bytes, _digest, _relative_name in reversed(descriptors):
            os.close(descriptor)


@contextmanager
def _snapshot_received_duckdb(
    database: Path,
    *,
    temporary_directory: Path,
    expected_bytes: int,
    expected_sha256: str,
) -> Iterator[_DatabaseSnapshot]:
    if type(expected_bytes) is not int or expected_bytes < 0:
        raise ValueError("authoritative DuckDB byte receipt is invalid")
    expected_digest = _sha256_receipt(
        expected_sha256,
        label="authoritative DuckDB receipt",
    )
    listed = os.stat(database, follow_symlinks=False)
    source = -1
    target = -1
    try:
        source = os.open(
            database,
            os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK,
        )
        opened = os.fstat(source)
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(listed):
            raise ValueError("authoritative DuckDB changed before snapshot admission")
        snapshot_path = temporary_directory / "nba.duckdb"
        target = os.open(
            snapshot_path,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
            0o600,
        )
        digest = hashlib.sha256()
        copied = 0
        os.lseek(source, 0, os.SEEK_SET)
        while chunk := os.read(source, _COPY_CHUNK_BYTES):
            if len(chunk) > expected_bytes - copied:
                raise ValueError("authoritative DuckDB exceeds its preflight byte receipt")
            digest.update(chunk)
            copied += len(chunk)
            view = memoryview(chunk)
            while view:
                written = _write_snapshot_chunk(target, view)
                if written <= 0:
                    raise OSError(errno.EIO, "authoritative DuckDB snapshot made no progress")
                view = view[written:]
        os.fsync(target)
        if (
            copied != expected_bytes
            or digest.hexdigest() != expected_digest
            or _identity(os.fstat(source)) != _identity(opened)
        ):
            raise ValueError("authoritative DuckDB differs from its preflight receipt")
        os.fchmod(target, 0o400)
        target_bytes, target_sha256 = _hash_descriptor(
            target,
            display_path="authoritative DuckDB snapshot",
        )
        if (target_bytes, target_sha256) != (expected_bytes, expected_digest):
            raise ValueError("authoritative DuckDB private snapshot differs from its receipt")
        target_identity = _identity(os.fstat(target))
        named_target = os.stat(snapshot_path, follow_symlinks=False)
        if _identity(named_target) != target_identity:
            raise ValueError("authoritative DuckDB private snapshot pathname changed")
        yield _DatabaseSnapshot(
            path=snapshot_path,
            descriptor=target,
            identity=target_identity,
            bytes=target_bytes,
            sha256=target_sha256,
        )
        target_bytes, target_sha256 = _hash_descriptor(
            target,
            display_path="authoritative DuckDB snapshot",
        )
        named_target = os.stat(snapshot_path, follow_symlinks=False)
        if (
            _identity(os.fstat(target)) != target_identity
            or _identity(named_target) != target_identity
            or (target_bytes, target_sha256) != (expected_bytes, expected_digest)
        ):
            raise ValueError("authoritative DuckDB private snapshot changed during validation")
    finally:
        if target >= 0:
            os.close(target)
        if source >= 0:
            os.close(source)


def _require_received_duckdb_snapshot(
    snapshot: _DatabaseSnapshot,
    scratch: _ScratchAuthority,
    *,
    stage: str,
) -> None:
    _require_scratch_path(scratch, stage=stage)
    try:
        held = os.fstat(snapshot.descriptor)
        named = os.stat(snapshot.path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"authoritative DuckDB private snapshot changed at {stage}") from exc
    if (
        _identity(held) != snapshot.identity
        or _identity(named) != snapshot.identity
        or not stat.S_ISREG(held.st_mode)
        or stat.S_IMODE(held.st_mode) != 0o400
    ):
        raise ValueError(f"authoritative DuckDB private snapshot changed at {stage}")


def validate_authoritative_duckdb_parquet_values(
    duckdb_path: Path,
    parquet_resources: Mapping[str, Path],
    *,
    expected_duckdb_bytes: int,
    expected_duckdb_sha256: str,
    expected_parquet_files: Mapping[str, Mapping[str, tuple[int, str]]],
    memory_limit_bytes: int | None = None,
    temp_max_bytes: int | None = None,
) -> None:
    """Validate exact authoritative values for a source-backed publication bundle.

    The comparison is relational and order-independent. A signed count delta
    scans each authority once while preserving duplicate multiplicity; only a
    one-row mismatch sentinel reaches Python. DuckDB execution is constrained
    by explicit memory, file-fan-in, column, and private spill ceilings.
    """

    if type(expected_duckdb_bytes) is not int or expected_duckdb_bytes < 0:
        raise ValueError("authoritative DuckDB byte receipt is invalid")
    expected_duckdb_digest = _sha256_receipt(
        expected_duckdb_sha256,
        label="authoritative DuckDB receipt",
    )
    database = Path(duckdb_path)
    if not database.is_absolute():
        raise ValueError("authoritative DuckDB resource must be absolute")
    try:
        database_stat = os.stat(database, follow_symlinks=False)
    except OSError as exc:
        raise ValueError("authoritative DuckDB resource is unavailable") from exc
    if stat.S_ISLNK(database_stat.st_mode) or not stat.S_ISREG(database_stat.st_mode):
        raise ValueError("authoritative DuckDB resource must be a regular non-symlink")
    normalized_resources = {
        str(table): Path(resource) for table, resource in parquet_resources.items()
    }
    if not normalized_resources or len(normalized_resources) != len(parquet_resources):
        raise ValueError("authoritative Parquet resource inventory is empty or duplicated")
    for table in normalized_resources:
        validate_sql_identifier(table)
    if set(expected_parquet_files) != set(normalized_resources):
        raise ValueError("authoritative Parquet receipt tables differ from the resource inventory")
    normalized_receipts: dict[str, dict[str, tuple[int, str]]] = {}
    largest_table_bytes = 0
    for table, raw_receipts in expected_parquet_files.items():
        receipts = dict(raw_receipts)
        if not receipts or len(receipts) > _MAX_AUTHORITATIVE_PARQUET_FILES_PER_TABLE:
            raise ValueError(
                f"authoritative Parquet receipt file count is outside safe bounds: {table}"
            )
        normalized_table: dict[str, tuple[int, str]] = {}
        table_bytes = 0
        for relative_path, receipt in receipts.items():
            path = PurePosixPath(str(relative_path))
            if (
                not isinstance(relative_path, str)
                or path.is_absolute()
                or path.as_posix() != relative_path
                or path.suffix != ".parquet"
                or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
                or type(receipt) is not tuple
                or len(receipt) != 2
            ):
                raise ValueError(
                    f"authoritative Parquet receipt is malformed: {table}/{relative_path}"
                )
            byte_count, digest = receipt
            if type(byte_count) is not int or byte_count < 0:
                raise ValueError(
                    f"authoritative Parquet byte receipt is invalid: {table}/{relative_path}"
                )
            normalized_table[path.as_posix()] = (
                byte_count,
                _sha256_receipt(
                    digest,
                    label=f"authoritative Parquet receipt for {table}/{relative_path}",
                ),
            )
            table_bytes += byte_count
        normalized_receipts[table] = normalized_table
        largest_table_bytes = max(largest_table_bytes, table_bytes)

    if temp_max_bytes is None:
        requested_temp_bytes = min(
            _MAX_VALUE_PARITY_TEMP_BYTES,
            max(
                _MIN_VALUE_PARITY_TEMP_BYTES,
                _MIN_VALUE_PARITY_TEMP_BYTES + largest_table_bytes * 4,
            ),
        )
    else:
        requested_temp_bytes = temp_max_bytes
    temp_capacity = _positive_capacity(
        requested_temp_bytes,
        label="authoritative value-parity temporary maximum",
    )
    if not _MIN_VALUE_PARITY_TEMP_BYTES <= temp_capacity <= _MAX_VALUE_PARITY_TEMP_BYTES:
        raise ValueError("authoritative value-parity temporary maximum is outside safe bounds")
    if memory_limit_bytes is not None:
        memory_capacity = _positive_capacity(
            memory_limit_bytes,
            label="authoritative value-parity memory maximum",
        )
        if not _MIN_VALUE_PARITY_MEMORY_BYTES <= memory_capacity <= _MAX_VALUE_PARITY_MEMORY_BYTES:
            raise ValueError("authoritative value-parity memory maximum is outside safe bounds")

    with tempfile.TemporaryDirectory(prefix="nbadb-authoritative-value-parity-") as temporary_name:
        temporary_root = Path(temporary_name)
        temporary_descriptor = -1
        try:
            named_temporary = os.stat(temporary_root, follow_symlinks=False)
            _require_private_directory(
                named_temporary,
                label="authoritative value-parity private scratch",
            )
            temporary_descriptor = os.open(temporary_root, _DIRECTORY_FLAGS)
            opened_temporary = os.fstat(temporary_descriptor)
            if _directory_authority_identity(opened_temporary) != (
                _directory_authority_identity(named_temporary)
            ):
                raise ValueError("authoritative value-parity private scratch changed while opening")
            scratch = _ScratchAuthority(
                path=temporary_root,
                descriptor=temporary_descriptor,
                identity=(opened_temporary.st_dev, opened_temporary.st_ino),
                opened_identity=_directory_authority_identity(opened_temporary),
            )
            _require_scratch_path(scratch, stage="before authoritative snapshot creation")
            spill_directory = temporary_root / "spill"
            spill_directory.mkdir(mode=0o700)
            _require_private_directory(
                os.stat(spill_directory, follow_symlinks=False),
                label="authoritative value-parity spill directory",
            )
            free_space = os.statvfs(temporary_root)
            available_bytes = free_space.f_bavail * free_space.f_frsize
            required_bytes = (
                expected_duckdb_bytes
                + largest_table_bytes
                + temp_capacity
                + _MIN_SCRATCH_RESERVE_BYTES
            )
            if available_bytes < required_bytes:
                raise OSError(
                    errno.ENOSPC,
                    "authoritative value parity lacks private snapshot/spill capacity: "
                    f"required_bytes={required_bytes}; available_bytes={available_bytes}",
                )
            with _snapshot_received_duckdb(
                database,
                temporary_directory=temporary_root,
                expected_bytes=expected_duckdb_bytes,
                expected_sha256=expected_duckdb_digest,
            ) as database_snapshot:
                _require_received_duckdb_snapshot(
                    database_snapshot,
                    scratch,
                    stage="before authoritative engine open",
                )
                _prove_snapshot_flock_available(database_snapshot.descriptor)
                connection: duckdb.DuckDBPyConnection | None = None
                try:
                    connection = duckdb.connect(str(database_snapshot.path), read_only=True)
                except duckdb.Error as exc:
                    raise ValueError("authoritative DuckDB resource is unreadable") from exc
                try:
                    _require_duckdb_snapshot_lock(
                        database_snapshot.descriptor,
                        stage="after authoritative engine open",
                    )
                    _require_received_duckdb_snapshot(
                        database_snapshot,
                        scratch,
                        stage="after authoritative engine open",
                    )
                    _configure_authoritative_query_limits(
                        connection,
                        temporary_directory=spill_directory,
                        temp_max_bytes=temp_capacity,
                        memory_limit_bytes=memory_limit_bytes,
                    )
                    database_tables = tuple(
                        sorted(
                            str(row[0])
                            for row in connection.execute(
                                "SELECT table_name FROM information_schema.tables "
                                "WHERE table_schema = 'main' "
                                "AND table_name NOT LIKE '\\_%' ESCAPE '\\'"
                            ).fetchall()
                        )
                    )
                    expected_tables = tuple(sorted(normalized_resources))
                    if database_tables != expected_tables:
                        missing_parquet = sorted(set(database_tables) - set(expected_tables))
                        unexpected_parquet = sorted(set(expected_tables) - set(database_tables))
                        raise ValueError(
                            "authoritative DuckDB-Parquet table inventory differs: "
                            f"missing_parquet={missing_parquet}; "
                            f"unexpected_parquet={unexpected_parquet}"
                        )
                    for table in database_tables:
                        with _open_path_authoritative_parquet_files(
                            table,
                            normalized_resources[table],
                            normalized_receipts[table],
                            snapshot_directory=temporary_root,
                        ) as files:
                            _validate_authoritative_table_values(connection, table, files)
                    _require_duckdb_snapshot_lock(
                        database_snapshot.descriptor,
                        stage="after authoritative value read",
                    )
                    _require_received_duckdb_snapshot(
                        database_snapshot,
                        scratch,
                        stage="after authoritative value read",
                    )
                except duckdb.Error as exc:
                    raise ValueError("authoritative DuckDB-Parquet validation failed") from exc
                finally:
                    try:
                        connection.close()
                    finally:
                        _require_duckdb_snapshot_lock_released(database_snapshot.descriptor)
            _require_scratch_path(scratch, stage="after authoritative validation")
        finally:
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)


@contextmanager
def _database_snapshot(
    root_descriptor: int,
    snapshot: _TreeSnapshot,
    resource_path: str,
    *,
    scratch: _ScratchAuthority,
    max_snapshot_bytes: int,
) -> Iterator[_DatabaseSnapshot]:
    observation = snapshot.files[resource_path]
    capacity = _positive_capacity(max_snapshot_bytes, label=f"{resource_path} snapshot maximum")
    if observation.bytes > capacity:
        raise ValueError(f"successor {resource_path} exceeds its snapshot byte ceiling")
    required_bytes = observation.bytes + _MIN_SCRATCH_RESERVE_BYTES
    if _scratch_free_bytes(scratch) < required_bytes:
        raise OSError(
            "successor publication database snapshot lacks scratch capacity: "
            f"required_bytes={required_bytes}"
        )
    _require_scratch_path(scratch, stage=f"before {resource_path} snapshot")

    source = _open_observed_path(
        root_descriptor,
        snapshot,
        resource_path,
        require_directory=False,
    )
    temporary_name: str | None = None
    temporary_before: os.stat_result | None = None
    temporary_descriptor = -1
    target = -1
    target_inode: tuple[int, int] | None = None
    target_identity: tuple[int, int, int, int, int, int] | None = None
    try:
        temporary_name, temporary_descriptor, temporary_before = _reserve_private_directory(
            scratch,
            prefix="nbadb-successor-publication-",
        )
        target_name = PurePosixPath(resource_path).name
        target_path = scratch.path / temporary_name / target_name
        try:
            target = os.open(
                target_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                0o600,
                dir_fd=temporary_descriptor,
            )
            target_created = os.fstat(target)
            target_inode = directory_inode(target_created)
            target_identity = _identity(target_created)
            named_created = os.stat(
                target_name,
                dir_fd=temporary_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(target_created.st_mode)
                or _identity(named_created) != target_identity
                or target_created.st_uid != os.geteuid()
                or stat.S_IMODE(target_created.st_mode) != 0o600
            ):
                raise ValueError("successor database snapshot is not a private regular file")

            digest = hashlib.sha256()
            copied = 0
            written_total = 0
            os.lseek(source, 0, os.SEEK_SET)
            while chunk := os.read(source, _COPY_CHUNK_BYTES):
                if len(chunk) > capacity - copied:
                    raise ValueError(
                        f"successor {resource_path} exceeds its snapshot byte ceiling while copying"
                    )
                view = memoryview(chunk)
                while view:
                    if len(view) > capacity - written_total:
                        raise ValueError(
                            f"successor {resource_path} exceeds its snapshot byte ceiling "
                            "before write"
                        )
                    written = _write_snapshot_chunk(target, view)
                    if written <= 0:
                        raise OSError(errno.EIO, "database snapshot copy made no progress")
                    written_total += written
                    view = view[written:]
                digest.update(chunk)
                copied += len(chunk)
            os.fsync(target)
            if copied != written_total or (copied, digest.hexdigest()) != (
                observation.bytes,
                observation.sha256,
            ):
                raise ValueError(f"successor database changed while snapshotting: {resource_path}")
            if _identity(os.fstat(source)) != observation.identity:
                raise ValueError(f"successor database changed while snapshotting: {resource_path}")
            os.fchmod(target, 0o400)
            target_before = os.fstat(target)
            target_identity = _identity(target_before)
            named_target = os.stat(
                target_name,
                dir_fd=temporary_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(target_before.st_mode)
                or _identity(named_target) != target_identity
                or stat.S_IMODE(target_before.st_mode) != 0o400
            ):
                raise ValueError("successor database snapshot is not owner-read-only")
            target_bytes, target_sha256 = _hash_descriptor(
                target,
                display_path=f"snapshot:{resource_path}",
            )
            target_before = os.fstat(target)
            target_identity = _identity(target_before)
            if target_bytes > capacity or (target_bytes, target_sha256) != (
                observation.bytes,
                observation.sha256,
            ):
                raise ValueError(
                    f"successor database snapshot differs from source: {resource_path}"
                )
            _require_private_directory_name(
                scratch,
                temporary_name,
                temporary_descriptor,
                temporary_before,
                stage=f"before {resource_path} engine validation",
            )
            yield _DatabaseSnapshot(
                path=target_path,
                descriptor=target,
                identity=target_identity,
                bytes=target_bytes,
                sha256=target_sha256,
            )
            target_bytes, target_sha256 = _hash_descriptor(
                target,
                display_path=f"snapshot:{resource_path}",
            )
            target_after = os.fstat(target)
            if _identity(target_after) != target_identity or (
                target_bytes,
                target_sha256,
            ) != (observation.bytes, observation.sha256):
                raise ValueError(
                    f"successor database snapshot changed during validation: {resource_path}"
                )
            named_target = os.stat(
                target_name,
                dir_fd=temporary_descriptor,
                follow_symlinks=False,
            )
            if _identity(named_target) != _identity(target_after):
                raise ValueError(f"successor database snapshot pathname changed: {resource_path}")
            with os.scandir(temporary_descriptor) as iterator:
                names = sorted(entry.name for entry in iterator)
            if names != [target_name]:
                raise ValueError("successor database validation created unexpected scratch files")
            _require_private_directory_name(
                scratch,
                temporary_name,
                temporary_descriptor,
                temporary_before,
                stage=f"after {resource_path} engine validation",
            )
        finally:
            if target >= 0:
                os.close(target)
                target = -1
            if temporary_descriptor >= 0:
                try:
                    if temporary_name is None or temporary_before is None:
                        raise ValueError(
                            "successor publication private scratch lacks cleanup authority"
                        )
                    name_error: BaseException | None = None
                    try:
                        _require_private_directory_name(
                            scratch,
                            temporary_name,
                            temporary_descriptor,
                            temporary_before,
                            stage=f"{resource_path} cleanup admission",
                            require_root_path=False,
                        )
                    except BaseException as exc:
                        name_error = exc
                    if target_inode is not None:
                        named = os.stat(
                            target_name,
                            dir_fd=temporary_descriptor,
                            follow_symlinks=False,
                        )
                        if directory_inode(named) != target_inode:
                            raise ValueError("successor database snapshot changed before cleanup")
                        os.unlink(target_name, dir_fd=temporary_descriptor)
                    with os.scandir(temporary_descriptor) as iterator:
                        if any(True for _ in iterator):
                            raise ValueError("successor publication private scratch is not empty")
                    if name_error is not None:
                        raise name_error
                    _require_private_directory_name(
                        scratch,
                        temporary_name,
                        temporary_descriptor,
                        temporary_before,
                        stage=f"{resource_path} before cleanup removal",
                        require_root_path=False,
                    )
                    remove_empty_owned_directory(
                        scratch.descriptor,
                        temporary_name,
                        temporary_descriptor,
                        expected_inode=directory_inode(temporary_before),
                        error=ValueError,
                        label=f"{resource_path} before cleanup removal",
                    )
                    temporary_name = None
                finally:
                    os.close(temporary_descriptor)
                    temporary_descriptor = -1
            if temporary_name is not None:
                raise ValueError(
                    "successor publication private scratch was not removed by authority"
                )
            _require_scratch_path(scratch, stage=f"after {resource_path} cleanup")
    finally:
        os.close(source)


def _prove_snapshot_flock_available(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as exc:
        raise ValueError(
            "successor DuckDB snapshot does not support the required lock contract"
        ) from exc


def _require_duckdb_snapshot_lock(descriptor: int, *, stage: str) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
            return
        raise ValueError(f"successor DuckDB snapshot lock proof failed at {stage}") from exc
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    raise ValueError(f"DuckDB did not lock the exact successor snapshot at {stage}")


def _require_duckdb_snapshot_lock_released(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as exc:
        raise ValueError("DuckDB did not release the exact successor snapshot") from exc


def _duckdb_tables(
    snapshot: _DatabaseSnapshot,
    expected_tables: tuple[str, ...],
    *,
    transform_tables: tuple[str, ...] = (),
    require_complete_transform_outputs: bool = False,
    transform_scratch_parent: Path | None = None,
    expected_transform_scratch_parent_identity: tuple[int, int] | None = None,
    transform_scratch_max_bytes: int | None = None,
) -> tuple[
    dict[str, int],
    dict[str, tuple[str, ...]],
    tuple[TransformOutputAttestation, ...],
]:
    expected_raw = frozenset(table for table in expected_tables if table.startswith("raw_"))
    registered_w2 = _registered_public_raw_tables()[1] if expected_raw else frozenset()
    expected_w2 = frozenset(expected_tables) & registered_w2
    if expected_w2 and expected_w2 != registered_w2:
        raise ValueError("successor DuckDB contract contains a partial W2 exact-six authority")
    _prove_snapshot_flock_available(snapshot.descriptor)
    try:
        connection = duckdb.connect(str(snapshot.path), read_only=True)
    except duckdb.Error as exc:
        raise ValueError("successor DuckDB snapshot is unreadable") from exc
    try:
        _require_duckdb_snapshot_lock(snapshot.descriptor, stage="after engine open")
        table_names = tuple(
            sorted(
                str(row[0])
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'main' AND table_name NOT LIKE '\\_%' ESCAPE '\\'"
                ).fetchall()
            )
        )
        if table_names != expected_tables:
            raise ValueError(
                "successor DuckDB public table inventory differs: "
                f"missing={sorted(set(expected_tables) - set(table_names))}; "
                f"unexpected={sorted(set(table_names) - set(expected_tables))}"
            )
        rows: dict[str, int] = {}
        columns: dict[str, tuple[str, ...]] = {}
        for table in table_names:
            validate_sql_identifier(table)
            quoted_table = f'"{table}"'
            row = connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()
            rows[table] = int(row[0]) if row is not None else 0
            columns[table] = tuple(
                str(column[0])
                for column in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
                    [table],
                ).fetchall()
            )
        if expected_w2:
            from nbadb.orchestrate.w2_database_assurance import (
                verify_w2_database_authority,
            )
            from nbadb.orchestrate.w2_publication_inventory import (
                w2_public_value_authority_publication_tables,
            )

            entries = w2_public_value_authority_publication_tables()
            if (
                type(entries) is not tuple
                or len(entries) != 6
                or frozenset(entry.table_name for entry in entries) != registered_w2
            ):
                raise ValueError("successor W2 publication registry is not exact-six")
            schema_drift = {
                entry.table_name: {
                    "expected": list(entry.ordered_columns),
                    "observed": list(columns[entry.table_name]),
                }
                for entry in entries
                if columns[entry.table_name] != entry.ordered_columns
            }
            if schema_drift:
                raise ValueError(
                    "successor W2 ordered schema differs from its publication authority: "
                    f"differences={schema_drift}"
                )
            try:
                verify_w2_database_authority(connection, require_w2=True)
            except Exception as exc:
                raise ValueError(
                    "successor W2 database values failed exact durable authority replay"
                ) from exc
        if require_complete_transform_outputs:
            if (
                transform_scratch_parent is None
                or expected_transform_scratch_parent_identity is None
                or transform_scratch_max_bytes is None
            ):
                raise ValueError("successor transform scratch authority is missing")
            transform_outputs = build_successor_transform_attestations(
                connection,
                scratch_parent=transform_scratch_parent,
                expected_scratch_parent_identity=expected_transform_scratch_parent_identity,
                transform_scratch_max_bytes=transform_scratch_max_bytes,
            )
        elif transform_tables:
            if (
                transform_scratch_parent is None
                or expected_transform_scratch_parent_identity is None
                or transform_scratch_max_bytes is None
            ):
                raise ValueError("successor transform scratch authority is missing")
            transform_outputs = _attest_exact_tables(
                connection,
                transform_tables,
                scratch_parent=transform_scratch_parent,
                expected_scratch_parent_identity=expected_transform_scratch_parent_identity,
                transform_scratch_max_bytes=transform_scratch_max_bytes,
            )
        else:
            transform_outputs = ()
        _require_duckdb_snapshot_lock(snapshot.descriptor, stage="after engine read")
    except duckdb.Error as exc:
        raise ValueError("successor DuckDB snapshot validation failed") from exc
    finally:
        try:
            connection.close()
        finally:
            _require_duckdb_snapshot_lock_released(snapshot.descriptor)
    return rows, columns, transform_outputs


def _validate_snapshot_authoritative_values(
    database_snapshot: _DatabaseSnapshot,
    root_descriptor: int,
    snapshot: _TreeSnapshot,
    contract: _DataContract,
    *,
    temp_max_bytes: int,
) -> None:
    _prove_snapshot_flock_available(database_snapshot.descriptor)
    temp_capacity = _positive_capacity(
        temp_max_bytes,
        label="authoritative value-parity temporary maximum",
    )
    if not _MIN_VALUE_PARITY_TEMP_BYTES <= temp_capacity <= _MAX_VALUE_PARITY_TEMP_BYTES:
        raise ValueError("authoritative value-parity temporary maximum is outside safe bounds")
    free_space = os.statvfs(database_snapshot.path.parent)
    available_bytes = free_space.f_bavail * free_space.f_frsize
    required_bytes = temp_capacity + _MIN_SCRATCH_RESERVE_BYTES
    if available_bytes < required_bytes:
        raise OSError(
            errno.ENOSPC,
            "successor authoritative value parity lacks spill capacity: "
            f"required_bytes={required_bytes}; available_bytes={available_bytes}",
        )

    with tempfile.TemporaryDirectory(
        prefix="nbadb-authoritative-value-parity-",
        dir=database_snapshot.path.parent,
    ) as temporary_name:
        try:
            connection = duckdb.connect(str(database_snapshot.path), read_only=True)
        except duckdb.Error as exc:
            raise ValueError("successor authoritative DuckDB snapshot is unreadable") from exc
        try:
            _configure_authoritative_query_limits(
                connection,
                temporary_directory=Path(temporary_name),
                temp_max_bytes=temp_capacity,
            )
            _require_duckdb_snapshot_lock(
                database_snapshot.descriptor,
                stage="after authoritative engine open",
            )
            for table in contract.tables:
                with _open_snapshot_authoritative_parquet_files(
                    root_descriptor,
                    snapshot,
                    contract,
                    table,
                ) as files:
                    _validate_authoritative_table_values(connection, table, files)
            _require_duckdb_snapshot_lock(
                database_snapshot.descriptor,
                stage="after authoritative value read",
            )
        except duckdb.Error as exc:
            raise ValueError("successor authoritative DuckDB-Parquet validation failed") from exc
        finally:
            try:
                connection.close()
            finally:
                _require_duckdb_snapshot_lock_released(database_snapshot.descriptor)


def _read_snapshot_bytes(snapshot: _DatabaseSnapshot) -> bytes:
    before = os.fstat(snapshot.descriptor)
    if _identity(before) != snapshot.identity:
        raise ValueError("successor SQLite snapshot changed before descriptor read")
    os.lseek(snapshot.descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    observed_bytes = 0
    digest = hashlib.sha256()
    while chunk := os.read(snapshot.descriptor, _COPY_CHUNK_BYTES):
        observed_bytes += len(chunk)
        if observed_bytes > snapshot.bytes:
            raise ValueError("successor SQLite snapshot grew during descriptor read")
        digest.update(chunk)
        chunks.append(chunk)
    after = os.fstat(snapshot.descriptor)
    if (
        _identity(after) != snapshot.identity
        or observed_bytes != snapshot.bytes
        or digest.hexdigest() != snapshot.sha256
    ):
        raise ValueError("successor SQLite snapshot changed during descriptor read")
    return b"".join(chunks)


def _sqlite_tables(
    snapshot: _DatabaseSnapshot, expected_tables: tuple[str, ...]
) -> tuple[dict[str, int], dict[str, tuple[str, ...]]]:
    payload = _read_snapshot_bytes(snapshot)
    try:
        connection = sqlite3.connect(":memory:")
    except sqlite3.DatabaseError as exc:
        raise ValueError("successor SQLite in-memory connection is unavailable") from exc
    try:
        connection.deserialize(payload)
        connection.execute("PRAGMA query_only = ON")
    except sqlite3.DatabaseError as exc:
        connection.close()
        raise ValueError("successor SQLite snapshot is unreadable") from exc
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if quick_check is None or str(quick_check[0]).lower() != "ok":
            raise ValueError("successor SQLite snapshot failed quick_check")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("successor SQLite snapshot failed foreign_key_check")
        table_names = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '\\_%' ESCAPE '\\' "
                "ORDER BY name"
            ).fetchall()
        )
        if table_names != expected_tables:
            raise ValueError(
                "successor SQLite public table inventory differs: "
                f"missing={sorted(set(expected_tables) - set(table_names))}; "
                f"unexpected={sorted(set(table_names) - set(expected_tables))}"
            )
        rows: dict[str, int] = {}
        columns: dict[str, tuple[str, ...]] = {}
        for table in table_names:
            validate_sql_identifier(table)
            quoted_table = f'"{table}"'
            row = connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()
            rows[table] = int(row[0]) if row is not None else 0
            columns[table] = tuple(
                str(column[1])
                for column in connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
            )
    except sqlite3.DatabaseError as exc:
        raise ValueError("successor SQLite snapshot validation failed") from exc
    finally:
        connection.close()
    return rows, columns


def _validate_format_parity(
    root_descriptor: int,
    snapshot: _TreeSnapshot,
    contract: _DataContract,
    *,
    scratch_parent: Path,
    expected_scratch_root_identity: tuple[int, int],
    inventory_duckdb_snapshot_max_bytes: int,
    inventory_sqlite_snapshot_max_bytes: int,
    transform_scratch_max_bytes: int,
    transform_tables: tuple[str, ...] = (),
    require_complete_transform_outputs: bool = False,
) -> tuple[TransformOutputAttestation, ...]:
    duckdb_max = _positive_capacity(
        inventory_duckdb_snapshot_max_bytes,
        label="inventory_duckdb_snapshot_max_bytes",
    )
    sqlite_max = _positive_capacity(
        inventory_sqlite_snapshot_max_bytes,
        label="inventory_sqlite_snapshot_max_bytes",
    )
    transform_max = _positive_capacity(
        transform_scratch_max_bytes,
        label="transform_scratch_max_bytes",
    )
    with _open_scratch_authority(
        scratch_parent,
        expected_identity=expected_scratch_root_identity,
    ) as scratch:
        with _database_snapshot(
            root_descriptor,
            snapshot,
            "nba.duckdb",
            scratch=scratch,
            max_snapshot_bytes=duckdb_max,
        ) as database_snapshot:
            duckdb_rows, duckdb_columns, transform_outputs = _duckdb_tables(
                database_snapshot,
                contract.tables,
                transform_tables=transform_tables,
                require_complete_transform_outputs=require_complete_transform_outputs,
                transform_scratch_parent=scratch.path,
                expected_transform_scratch_parent_identity=scratch.identity,
                transform_scratch_max_bytes=transform_max,
            )
            _validate_snapshot_authoritative_values(
                database_snapshot,
                root_descriptor,
                snapshot,
                contract,
                temp_max_bytes=transform_max,
            )
        with _database_snapshot(
            root_descriptor,
            snapshot,
            "nba.sqlite",
            scratch=scratch,
            max_snapshot_bytes=sqlite_max,
        ) as database_snapshot:
            sqlite_rows, sqlite_columns = _sqlite_tables(database_snapshot, contract.tables)

    row_differences: dict[str, dict[str, int]] = {}
    schema_differences: dict[str, dict[str, list[str]]] = {}
    for table in contract.tables:
        csv_path = f"csv/{table}.csv"
        parquet_resource = dict(contract.resources)
        if table in contract.partitioned_tables:
            parquet_root = f"parquet/{table}"
            prefix = f"{parquet_root}/"
            parquet_files = sorted(path for path in snapshot.files if path.startswith(prefix))
            physical_columns: tuple[str, ...] | None = None
            partition_columns: tuple[str, ...] | None = None
            parquet_row_count = 0
            for parquet_path in parquet_files:
                row_count, columns = _read_parquet_file(
                    root_descriptor,
                    snapshot,
                    parquet_path,
                )
                relative = PurePosixPath(parquet_path.removeprefix(prefix))
                observed_partitions = tuple(part.partition("=")[0] for part in relative.parts[:-1])
                if len(observed_partitions) != len(set(observed_partitions)):
                    raise ValueError(f"successor Parquet partition key repeats: {parquet_path}")
                if set(columns) & set(observed_partitions):
                    raise ValueError(
                        f"successor Parquet partition columns are stored physically: {parquet_path}"
                    )
                if physical_columns is None:
                    physical_columns = columns
                    partition_columns = observed_partitions
                elif columns != physical_columns or observed_partitions != partition_columns:
                    raise ValueError(
                        f"successor partitioned Parquet schemas differ: {parquet_root}"
                    )
                parquet_row_count += row_count
            if physical_columns is None or partition_columns is None:
                raise ValueError(f"successor Parquet directory resource is empty: {parquet_root}")
            parquet_columns = (*physical_columns, *partition_columns)
        else:
            parquet_path = f"parquet/{table}/{table}.parquet"
            if parquet_resource.get(parquet_path) != "file":
                raise ValueError(f"successor Parquet file contract is missing: {table}")
            parquet_row_count, parquet_columns = _read_parquet_file(
                root_descriptor,
                snapshot,
                parquet_path,
            )
            physical_columns = parquet_columns
            partition_columns = ()

        csv_row_count, csv_columns = _read_csv(root_descriptor, snapshot, csv_path)
        counts = {
            "duckdb": duckdb_rows[table],
            "sqlite": sqlite_rows[table],
            "csv": csv_row_count,
            "parquet": parquet_row_count,
        }
        if len(set(counts.values())) != 1:
            row_differences[table] = counts
        database_schema = duckdb_columns[table]
        expected_physical = tuple(
            column for column in database_schema if column not in partition_columns
        )
        parquet_mismatch = (
            physical_columns != expected_physical
            or any(column not in database_schema for column in partition_columns)
            or len(physical_columns) + len(partition_columns) != len(database_schema)
        )
        if (
            sqlite_columns[table] != database_schema
            or csv_columns != database_schema
            or parquet_mismatch
        ):
            schema_differences[table] = {
                "duckdb": list(database_schema),
                "sqlite": list(sqlite_columns[table]),
                "csv": list(csv_columns),
                "parquet": list(parquet_columns),
            }
    if row_differences:
        sample = dict(list(row_differences.items())[:20])
        raise ValueError(
            "successor publication row-count parity failed: "
            f"mismatch_count={len(row_differences)}; differences={sample}"
        )
    if schema_differences:
        sample = dict(list(schema_differences.items())[:20])
        raise ValueError(
            "successor publication ordered-schema parity failed: "
            f"mismatch_count={len(schema_differences)}; differences={sample}"
        )
    return transform_outputs


def _inspect_publication_root(
    root: Path,
    contract: _DataContract,
    *,
    scratch_parent: Path,
    expected_scratch_root_identity: tuple[int, int],
    inventory_duckdb_snapshot_max_bytes: int,
    inventory_sqlite_snapshot_max_bytes: int,
    transform_scratch_max_bytes: int,
    expected_root_identity: tuple[int, int] | None = None,
    transform_tables: tuple[str, ...] = (),
    require_complete_transform_outputs: bool = False,
) -> tuple[
    tuple[SuccessorPublicResourceAttestation, ...],
    SuccessorDatabaseEvidence,
    tuple[TransformOutputAttestation, ...],
]:
    with _open_public_root(
        root,
        expected_root_identity=expected_root_identity,
    ) as (root_descriptor, snapshot):
        _validate_tree_contract(snapshot, contract)
        transform_outputs = _validate_format_parity(
            root_descriptor,
            snapshot,
            contract,
            scratch_parent=scratch_parent,
            expected_scratch_root_identity=expected_scratch_root_identity,
            inventory_duckdb_snapshot_max_bytes=inventory_duckdb_snapshot_max_bytes,
            inventory_sqlite_snapshot_max_bytes=inventory_sqlite_snapshot_max_bytes,
            transform_scratch_max_bytes=transform_scratch_max_bytes,
            transform_tables=transform_tables,
            require_complete_transform_outputs=require_complete_transform_outputs,
        )
        resources = tuple(
            _resource_for_file(resource_path, snapshot.files[resource_path])
            if kind == "file"
            else _directory_resource(resource_path, snapshot)
            for resource_path, kind in contract.resources
        )
        duckdb_resource = snapshot.files["nba.duckdb"]
        sqlite_resource = snapshot.files["nba.sqlite"]
        database_evidence = SuccessorDatabaseEvidence(
            duckdb_sha256=duckdb_resource.sha256,
            duckdb_bytes=duckdb_resource.bytes,
            sqlite_sha256=sqlite_resource.sha256,
            sqlite_bytes=sqlite_resource.bytes,
        )
    return resources, database_evidence, transform_outputs


def inspect_successor_candidate_publication(
    root: Path,
    *,
    scratch_parent: Path,
    expected_scratch_root_identity: tuple[int, int],
    inventory_duckdb_snapshot_max_bytes: int,
    inventory_sqlite_snapshot_max_bytes: int,
    transform_scratch_max_bytes: int,
    expected_root_identity: tuple[int, int] | None = None,
) -> tuple[str, ...]:
    """Validate one candidate's four-format schema, row-count, digest, and parity.

    The production publication contract stays with
    ``build_successor_publication_inventory``.  Pre-promote validation derives
    the table contract from the observed DuckDB/SQLite/CSV/Parquet tree so a
    real candidate can fail closed on mismatch without inventing the full
    Kaggle resource set.
    """

    publication_root = Path(root)
    require_successor_publication_formats(publication_root)
    if not publication_root.is_absolute():
        publication_root = publication_root.resolve()
    with _open_public_root(
        publication_root,
        expected_root_identity=expected_root_identity,
    ) as (root_descriptor, snapshot):
        contract = _data_contract_from_snapshot(snapshot)
        if not contract.tables:
            raise ValueError("successor candidate publication tree has no public tables")
        _validate_tree_contract(snapshot, contract)
        _validate_format_parity(
            root_descriptor,
            snapshot,
            contract,
            scratch_parent=scratch_parent,
            expected_scratch_root_identity=expected_scratch_root_identity,
            inventory_duckdb_snapshot_max_bytes=inventory_duckdb_snapshot_max_bytes,
            inventory_sqlite_snapshot_max_bytes=inventory_sqlite_snapshot_max_bytes,
            transform_scratch_max_bytes=transform_scratch_max_bytes,
        )
    return contract.tables


def require_successor_publication_formats(root: Path) -> None:
    """Fail closed unless DuckDB, SQLite, CSV, and Parquet roots are present."""

    path = Path(root)
    try:
        root_stat = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError("successor publication root cannot be read") from exc
    if path.is_symlink() or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("successor publication root must be a regular directory")

    missing: list[str] = []
    for name in _REQUIRED_PUBLIC_FORMAT_FILES:
        resource = path / name
        try:
            resource_stat = os.stat(resource, follow_symlinks=False)
        except OSError:
            missing.append(name)
            continue
        if resource.is_symlink() or not stat.S_ISREG(resource_stat.st_mode):
            missing.append(name)
    for name in _REQUIRED_PUBLIC_FORMAT_DIRECTORIES:
        resource = path / name
        try:
            resource_stat = os.stat(resource, follow_symlinks=False)
        except OSError:
            missing.append(name)
            continue
        if resource.is_symlink() or not stat.S_ISDIR(resource_stat.st_mode):
            missing.append(name)
    if missing:
        raise ValueError(
            "successor candidate public tree is missing required publication "
            f"format(s): {', '.join(missing)}"
        )


def successor_publication_freshness_season(as_of_utc: str) -> str:
    """Return the NBA season implied by successor intent ``as_of_utc``."""

    if not isinstance(as_of_utc, str):
        raise ValueError("as_of_utc must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.strptime(as_of_utc, _UTC_INSTANT_FORMAT)
    except ValueError as exc:
        raise ValueError("as_of_utc must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ") from exc
    if parsed.strftime(_UTC_INSTANT_FORMAT) != as_of_utc:
        raise ValueError("as_of_utc must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ")
    year = parsed.year if parsed.month >= 10 else parsed.year - 1
    return season_string(year)


def read_successor_publication_watermarks(root: Path) -> dict[str, str]:
    """Read ``last_load`` watermarks from the candidate DuckDB."""

    duckdb_path = Path(root) / "nba.duckdb"
    try:
        duckdb_stat = os.stat(duckdb_path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError("successor publication freshness requires nba.duckdb") from exc
    if duckdb_path.is_symlink() or not stat.S_ISREG(duckdb_stat.st_mode):
        raise ValueError("successor publication freshness requires nba.duckdb")

    try:
        connection = duckdb.connect(str(duckdb_path), read_only=True)
    except duckdb.Error as exc:
        raise ValueError("successor publication watermarks are unreadable") from exc
    try:
        present = connection.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = '_pipeline_watermarks'"
        ).fetchone()
        if present is None:
            raise ValueError("successor publication freshness requires _pipeline_watermarks")
        rows = connection.execute(
            "SELECT table_name, watermark_value FROM _pipeline_watermarks "
            "WHERE watermark_type = ? ORDER BY table_name",
            [_WATERMARK_TYPE_LAST_LOAD],
        ).fetchall()
    except duckdb.Error as exc:
        raise ValueError("successor publication watermarks are unreadable") from exc
    finally:
        connection.close()

    watermarks: dict[str, str] = {}
    for table_name, watermark_value in rows:
        if not isinstance(table_name, str) or not table_name:
            raise ValueError("successor publication watermark table_name is invalid")
        if not isinstance(watermark_value, str) or not watermark_value:
            raise ValueError("successor publication watermark_value is invalid")
        if table_name in watermarks:
            raise ValueError(f"duplicate last_load watermark: {table_name}")
        watermarks[table_name] = watermark_value
    return watermarks


def validate_successor_publication_freshness(
    root: Path,
    *,
    as_of_utc: str,
    expected_tables: Sequence[str] | None = None,
) -> str:
    """Require every expected table's ``last_load`` to equal the as-of season."""

    expected_season = successor_publication_freshness_season(as_of_utc)
    if expected_tables is None:
        expected = tuple(sorted(expected_transform_output_tables(include_live=True)))
        if not expected or len(expected) != len(set(expected)):
            raise SuccessorAssuranceContractError(
                "repository transform authority is not a unique convention-discovered universe"
            )
    else:
        expected = tuple(expected_tables)
        if not expected or any(not isinstance(table, str) or not table for table in expected):
            raise ValueError("successor publication freshness tables are invalid")
    watermarks = read_successor_publication_watermarks(root)
    stale_or_missing = [table for table in expected if watermarks.get(table) != expected_season]
    if stale_or_missing:
        sample = stale_or_missing[:20]
        raise ValueError(
            "successor publication freshness failed: "
            f"expected last_load={expected_season}; "
            f"stale_or_missing_count={len(stale_or_missing)}; "
            f"stale_or_missing={sample}"
        )
    return expected_season


def build_successor_publication_inventory(
    root: Path,
    *,
    scratch_parent: Path,
    expected_scratch_root_identity: tuple[int, int],
    inventory_duckdb_snapshot_max_bytes: int,
    inventory_sqlite_snapshot_max_bytes: int,
    transform_scratch_max_bytes: int,
    expected_root_identity: tuple[int, int] | None = None,
    as_of_utc: str | None = None,
) -> SuccessorPublicationInventoryEvidence:
    """Validate one exact local successor tree and return schema-v6 evidence.

    ``root`` must contain the complete convention-discovered non-control data
    resources and, when present, the two fixed lossless-fallback exports. Either
    canonical control file may also exist as a regular non-symlink file; controls
    are excluded from returned evidence.  Database validation uses private
    descriptor-streamed snapshots.  SQLite consumes exact held-descriptor bytes;
    DuckDB's live advisory lock proves it opened that held inode rather than a
    swapped pathname.  ``scratch_parent`` is a pre-provisioned owner-only
    authority.  Each snapshot and transform spill is hard-bound to its exact
    aggregate-capacity contract field and removed before this function returns.
    When ``as_of_utc`` is supplied, ``last_load`` watermarks must equal the
    successor season implied by that instant.
    """

    publication_root = Path(root)
    require_successor_publication_formats(publication_root)
    contract = _production_data_contract(publication_root)
    resources, database_evidence, transform_outputs = _inspect_publication_root(
        publication_root,
        contract,
        scratch_parent=scratch_parent,
        expected_scratch_root_identity=expected_scratch_root_identity,
        inventory_duckdb_snapshot_max_bytes=inventory_duckdb_snapshot_max_bytes,
        inventory_sqlite_snapshot_max_bytes=inventory_sqlite_snapshot_max_bytes,
        transform_scratch_max_bytes=transform_scratch_max_bytes,
        expected_root_identity=expected_root_identity,
        require_complete_transform_outputs=True,
    )
    if as_of_utc is not None:
        validate_successor_publication_freshness(
            publication_root,
            as_of_utc=as_of_utc,
        )
    public_evidence = SuccessorPublicEvidence(resources=resources)
    return SuccessorPublicationInventoryEvidence(
        public_evidence=public_evidence,
        database_evidence=database_evidence,
        transform_outputs=transform_outputs,
    )
