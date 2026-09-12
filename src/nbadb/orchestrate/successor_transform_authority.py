"""Canonical DuckDB-derived transform-output authority for successor runs.

The ordinary pipeline may keep frame-local diagnostics, but exact recurring
updates need an identity that can be reproduced independently from the
installed DuckDB artifact.  This module derives that identity from ordered
DuckDB column names/types and a row-order-independent, duplicate-preserving
multiset of canonical row digests.

The pinned DuckDB API accepts a pathname, not a directory descriptor, for its
temporary directory.  A same-UID actor can substitute such a pathname after a
preflight check, so this authority deliberately disables DuckDB external spill
instead of weakening the descriptor-bound scratch contract.  Work that cannot
fit inside the bounded in-memory engine fails closed with an explicit
architectural error; the admitted scratch directory remains an empty sentinel
whose exact positive contract ceiling is still independently enforced.
"""

from __future__ import annotations

import hashlib
import math
import os
import secrets
import stat
import struct
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import duckdb
import pyarrow as pa

from nbadb.core.types import validate_sql_identifier
from nbadb.orchestrate.successor_inode import remove_empty_owned_directory
from nbadb.orchestrate.transformers import expected_transform_output_tables

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = [
    "TransformOutputAttestation",
    "build_transform_relation_attestations",
    "build_successor_transform_attestations",
]

_ROW_BATCH_SIZE: Final = 8_192
_HASH_BATCH_SIZE: Final = 8_192
_SCRATCH_MEMORY_LIMIT: Final = "256MB"
_DISABLED_TEMP_DIRECTORY: Final = ""
_DISABLED_TEMP_DIRECTORY_LIMIT: Final = "0B"
_DISABLED_SPILL_ERROR: Final = (
    "DuckDB external transform spill is disabled because its temp_directory "
    "cannot be bound to the admitted directory descriptor"
)
_SCHEMA_DOMAIN: Final = b"nbadb.successor.transform.schema.v1\0"
_ROW_DOMAIN: Final = b"nbadb.successor.transform.row.v1\0"
_CONTENT_DOMAIN: Final = b"nbadb.successor.transform.content.v1\0"
_OPEN_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_OPEN_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_OPEN_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK
)
_SIGNED_63_MAX: Final = (1 << 63) - 1

_BOOLEAN_TYPES: Final = frozenset({"BOOLEAN", "BOOL", "LOGICAL"})
_INTEGER_TYPES: Final = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "INT",
        "SIGNED",
        "BIGINT",
        "LONG",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
    }
)
_FLOAT32_TYPES: Final = frozenset({"REAL", "FLOAT4"})
_FLOAT64_TYPES: Final = frozenset({"DOUBLE", "FLOAT", "FLOAT8", "DOUBLE PRECISION"})
_STRING_TYPES: Final = frozenset({"VARCHAR", "TEXT", "STRING", "JSON"})
_BLOB_TYPES: Final = frozenset({"BLOB", "BYTEA", "BINARY", "VARBINARY"})
_DATE_TYPES: Final = frozenset({"DATE"})
_TIME_TYPES: Final = frozenset({"TIME", "TIME WITH TIME ZONE", "TIMETZ"})
_TIMESTAMP_TYPES: Final = frozenset(
    {
        "TIMESTAMP",
        "DATETIME",
        "TIMESTAMP_S",
        "TIMESTAMP_MS",
        "TIMESTAMP_NS",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMPTZ",
    }
)
_SPECIAL_STRING_TYPES: Final = frozenset({"UUID", "BIT"})


class SuccessorTransformAuthorityError(ValueError):
    """The installed DuckDB cannot prove the exact transform identity."""


@dataclass(frozen=True, slots=True)
class TransformOutputAttestation:
    """One canonical, path-free transform-table identity."""

    table_name: str
    row_count: int
    schema_sha256: str
    content_sha256: str

    def __post_init__(self) -> None:
        validate_sql_identifier(self.table_name)
        if type(self.row_count) is not int or self.row_count < 0:
            raise SuccessorTransformAuthorityError("transform row_count is invalid")
        for field_name in ("schema_sha256", "content_sha256"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise SuccessorTransformAuthorityError(f"transform {field_name} is invalid")

    def to_dict(self) -> dict[str, str | int]:
        return {
            "table_name": self.table_name,
            "row_count": self.row_count,
            "schema_sha256": self.schema_sha256,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class _TransformScratch:
    parent_path: Path
    parent_descriptor: int
    parent_identity: tuple[int, int, int, int]
    name: str
    descriptor: int
    identity: tuple[int, int, int, int]
    spill_descriptor: int
    spill_identity: tuple[int, int, int, int]
    connection: duckdb.DuckDBPyConnection
    max_bytes: int


def _canonical_field(payload: bytes) -> bytes:
    return len(payload).to_bytes(8, "big") + payload


def _schema_digest(table: str, columns: tuple[tuple[str, str], ...]) -> str:
    digest = hashlib.sha256()
    digest.update(_SCHEMA_DOMAIN)
    digest.update(_canonical_field(table.encode("utf-8")))
    digest.update(len(columns).to_bytes(8, "big"))
    for name, data_type in columns:
        digest.update(_canonical_field(name.encode("utf-8")))
        digest.update(_canonical_field(data_type.encode("ascii", errors="strict")))
    return digest.hexdigest()


def _normalized_type(data_type: str) -> str:
    normalized = " ".join(data_type.upper().split())
    if (
        "[" in normalized
        or normalized.startswith(("LIST(", "STRUCT(", "MAP(", "UNION("))
        or normalized.endswith("[]")
    ):
        raise SuccessorTransformAuthorityError(
            f"nested DuckDB transform type is unsupported: {data_type}"
        )
    if normalized.startswith("DECIMAL(") or normalized.startswith("NUMERIC("):
        return "DECIMAL"
    if normalized.startswith(("VARCHAR(", "CHAR(", "CHARACTER(", "BPCHAR(")):
        return "VARCHAR"
    return normalized


def _float_payload(value: object, *, bits: int) -> bytes:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise SuccessorTransformAuthorityError("DuckDB floating value has an invalid runtime type")
    number = float(value)
    if math.isnan(number):
        return b"Q"
    if math.isinf(number):
        return b"P" if number > 0 else b"M"
    if number == 0.0:
        return b"Z-" if math.copysign(1.0, number) < 0 else b"Z+"
    if bits == 32:
        return b"F4" + struct.pack(">f", number)
    return b"F8" + struct.pack(">d", number)


def _value_payload(value: object, data_type: str) -> bytes:
    if value is None:
        return b"N"
    normalized = _normalized_type(data_type)
    if normalized in _BOOLEAN_TYPES:
        if type(value) is not bool:
            raise SuccessorTransformAuthorityError("DuckDB boolean value has an invalid type")
        return b"B1" if value else b"B0"
    if normalized in _INTEGER_TYPES:
        if type(value) is not int:
            raise SuccessorTransformAuthorityError("DuckDB integer value has an invalid type")
        return b"I" + str(value).encode("ascii")
    if normalized in _FLOAT32_TYPES:
        return _float_payload(value, bits=32)
    if normalized in _FLOAT64_TYPES:
        return _float_payload(value, bits=64)
    if normalized == "DECIMAL":
        if not isinstance(value, Decimal):
            raise SuccessorTransformAuthorityError("DuckDB decimal value has an invalid type")
        return b"D" + format(value, "f").encode("ascii")
    if normalized in _STRING_TYPES or normalized == "VARCHAR":
        if not isinstance(value, str):
            raise SuccessorTransformAuthorityError("DuckDB string value has an invalid type")
        return b"S" + value.encode("utf-8")
    if normalized in _SPECIAL_STRING_TYPES:
        return b"U" + str(value).encode("ascii", errors="strict")
    if normalized in _BLOB_TYPES:
        if not isinstance(value, bytes | bytearray | memoryview):
            raise SuccessorTransformAuthorityError("DuckDB blob value has an invalid type")
        return b"X" + bytes(value)
    if normalized in _DATE_TYPES:
        if not isinstance(value, date) or isinstance(value, datetime):
            raise SuccessorTransformAuthorityError("DuckDB date value has an invalid type")
        return b"A" + value.isoformat().encode("ascii")
    if normalized in _TIME_TYPES:
        if not isinstance(value, time):
            raise SuccessorTransformAuthorityError("DuckDB time value has an invalid type")
        return b"T" + value.isoformat(timespec="microseconds").encode("ascii")
    if normalized in _TIMESTAMP_TYPES:
        if not isinstance(value, datetime):
            raise SuccessorTransformAuthorityError("DuckDB timestamp value has an invalid type")
        return b"V" + value.isoformat(timespec="microseconds").encode("ascii")
    if normalized in {"SQLNULL", "NULL"}:
        raise SuccessorTransformAuthorityError("non-null value observed in DuckDB NULL column")
    raise SuccessorTransformAuthorityError(f"unsupported DuckDB transform type: {data_type}")


def _row_digest(values: Sequence[object], data_types: tuple[str, ...]) -> bytes:
    if len(values) != len(data_types):
        raise SuccessorTransformAuthorityError("DuckDB transform row width changed during readback")
    digest = hashlib.sha256()
    digest.update(_ROW_DOMAIN)
    digest.update(len(values).to_bytes(8, "big"))
    for value, data_type in zip(values, data_types, strict=True):
        digest.update(_canonical_field(_value_payload(value, data_type)))
    return digest.digest()


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode)


def _expected_identity(value: object) -> tuple[int, int]:
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(part) is not int or part < 0 for part in value)
        or value[1] == 0
    ):
        raise SuccessorTransformAuthorityError(
            "successor transform expected scratch parent identity is invalid"
        )
    return cast("tuple[int, int]", value)


def _max_scratch_bytes(value: object) -> int:
    if type(value) is not int or not 1 <= value <= _SIGNED_63_MAX:
        raise SuccessorTransformAuthorityError(
            "transform_scratch_max_bytes must be a positive signed-63 integer"
        )
    return value


def _require_private_directory(value: os.stat_result, *, label: str) -> None:
    mode = stat.S_IMODE(value.st_mode)
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or mode & 0o077
        or mode & 0o700 != 0o700
    ):
        raise SuccessorTransformAuthorityError(f"{label} must be owner-only and owner-accessible")


def _require_named_parent(
    parent_path: Path,
    parent_descriptor: int,
    expected: tuple[int, int, int, int],
    *,
    stage: str,
) -> None:
    try:
        held = os.fstat(parent_descriptor)
        named = os.stat(parent_path, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorTransformAuthorityError(
            f"successor transform scratch parent changed at {stage}"
        ) from exc
    if _directory_identity(held) != expected or _directory_identity(named) != expected:
        raise SuccessorTransformAuthorityError(
            f"successor transform scratch parent changed at {stage}"
        )


def _require_named_child(
    parent_descriptor: int,
    name: str,
    descriptor: int,
    expected: tuple[int, int, int, int],
    *,
    label: str,
    stage: str,
) -> None:
    try:
        held = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorTransformAuthorityError(f"{label} changed at {stage}") from exc
    if _directory_identity(held) != expected or _directory_identity(named) != expected:
        raise SuccessorTransformAuthorityError(f"{label} changed at {stage}")


def _scratch_logical_bytes(spill_descriptor: int, *, max_bytes: int) -> int:
    total = 0
    try:
        with os.scandir(spill_descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
    except OSError as exc:
        raise SuccessorTransformAuthorityError("successor transform spill cannot be read") from exc
    for name in names:
        try:
            observed = os.stat(name, dir_fd=spill_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorTransformAuthorityError(
                "successor transform spill changed while measuring"
            ) from exc
        if not stat.S_ISREG(observed.st_mode):
            raise SuccessorTransformAuthorityError(
                "successor transform spill contains a non-regular entry"
            )
        if observed.st_size > max_bytes - total:
            raise SuccessorTransformAuthorityError(
                "successor transform spill exceeds transform_scratch_max_bytes"
            )
        total += observed.st_size
    return total


def _require_scratch(authority: _TransformScratch, *, stage: str) -> int:
    _require_named_parent(
        authority.parent_path,
        authority.parent_descriptor,
        authority.parent_identity,
        stage=stage,
    )
    _require_named_child(
        authority.parent_descriptor,
        authority.name,
        authority.descriptor,
        authority.identity,
        label="successor transform private scratch",
        stage=stage,
    )
    _require_named_child(
        authority.descriptor,
        "spill",
        authority.spill_descriptor,
        authority.spill_identity,
        label="successor transform spill",
        stage=stage,
    )
    return _scratch_logical_bytes(
        authority.spill_descriptor,
        max_bytes=authority.max_bytes,
    )


@contextmanager
def _private_scratch(
    scratch_parent: Path,
    *,
    expected_scratch_parent_identity: tuple[int, int],
    transform_scratch_max_bytes: int,
) -> Iterator[_TransformScratch]:
    parent = Path(scratch_parent)
    if not parent.is_absolute():
        raise SuccessorTransformAuthorityError(
            "successor transform scratch parent must be absolute"
        )
    expected = _expected_identity(expected_scratch_parent_identity)
    maximum = _max_scratch_bytes(transform_scratch_max_bytes)
    try:
        named_parent = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorTransformAuthorityError(
            "successor transform scratch parent is unavailable"
        ) from exc
    _require_private_directory(named_parent, label="successor transform scratch parent")
    if (named_parent.st_dev, named_parent.st_ino) != expected:
        raise SuccessorTransformAuthorityError(
            "successor transform scratch parent differs from expected authority"
        )

    parent_descriptor = scratch_descriptor = spill_descriptor = -1
    name: str | None = None
    connection: duckdb.DuckDBPyConnection | None = None
    parent_identity: tuple[int, int, int, int] | None = None
    scratch_identity: tuple[int, int, int, int] | None = None
    spill_identity: tuple[int, int, int, int] | None = None
    primary_error: BaseException | None = None
    try:
        parent_descriptor = os.open(parent, _DIRECTORY_FLAGS)
        opened_parent = os.fstat(parent_descriptor)
        parent_identity = _directory_identity(opened_parent)
        if parent_identity != _directory_identity(named_parent):
            raise SuccessorTransformAuthorityError(
                "successor transform scratch parent changed before admission"
            )
        _require_named_parent(parent, parent_descriptor, parent_identity, stage="admission")

        for _ in range(128):
            candidate = f"nbadb-successor-transform-{secrets.token_hex(16)}"
            try:
                os.mkdir(candidate, mode=0o700, dir_fd=parent_descriptor)
            except FileExistsError:
                continue
            name = candidate
            break
        if name is None:
            raise SuccessorTransformAuthorityError(
                "successor transform private scratch cannot be reserved"
            )
        scratch_descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
        scratch_stat = os.fstat(scratch_descriptor)
        _require_private_directory(scratch_stat, label="successor transform private scratch")
        scratch_identity = _directory_identity(scratch_stat)
        _require_named_child(
            parent_descriptor,
            name,
            scratch_descriptor,
            scratch_identity,
            label="successor transform private scratch",
            stage="reservation",
        )
        os.mkdir("spill", mode=0o700, dir_fd=scratch_descriptor)
        spill_descriptor = os.open("spill", _DIRECTORY_FLAGS, dir_fd=scratch_descriptor)
        spill_stat = os.fstat(spill_descriptor)
        _require_private_directory(spill_stat, label="successor transform spill")
        spill_identity = _directory_identity(spill_stat)

        connection = duckdb.connect(":memory:")
        connection.execute("SET threads = 1")
        connection.execute("SET memory_limit = ?", [_SCRATCH_MEMORY_LIMIT])
        connection.execute(
            "SET temp_directory = ?",
            [_DISABLED_TEMP_DIRECTORY],
        )
        connection.execute(
            "SET max_temp_directory_size = ?",
            [_DISABLED_TEMP_DIRECTORY_LIMIT],
        )
        configured = connection.execute(
            "SELECT current_setting('temp_directory'), current_setting('max_temp_directory_size')"
        ).fetchone()
        if configured != ("", "0 bytes"):
            raise SuccessorTransformAuthorityError(
                "DuckDB transform spill could not be disabled exactly"
            )
        authority = _TransformScratch(
            parent_path=parent,
            parent_descriptor=parent_descriptor,
            parent_identity=parent_identity,
            name=name,
            descriptor=scratch_descriptor,
            identity=scratch_identity,
            spill_descriptor=spill_descriptor,
            spill_identity=spill_identity,
            connection=connection,
            max_bytes=maximum,
        )
        _require_scratch(authority, stage="engine admission")
        try:
            yield authority
            _require_scratch(authority, stage="engine release")
        except BaseException as exc:
            primary_error = exc
    except BaseException as exc:
        primary_error = exc
    finally:
        cleanup_error: BaseException | None = None
        if connection is not None:
            try:
                connection.close()
            except BaseException as exc:
                cleanup_error = exc
        if spill_descriptor >= 0:
            spill_name_is_authorized = False
            try:
                try:
                    _scratch_logical_bytes(spill_descriptor, max_bytes=maximum)
                except BaseException as exc:
                    if cleanup_error is None and primary_error is None:
                        cleanup_error = exc
                if scratch_descriptor >= 0 and spill_identity is not None:
                    try:
                        _require_named_child(
                            scratch_descriptor,
                            "spill",
                            spill_descriptor,
                            spill_identity,
                            label="successor transform spill",
                            stage="cleanup",
                        )
                        spill_name_is_authorized = True
                    except BaseException as exc:
                        if cleanup_error is None:
                            cleanup_error = exc
                try:
                    with os.scandir(spill_descriptor) as iterator:
                        child_names = sorted(entry.name for entry in iterator)
                except BaseException as exc:
                    child_names = []
                    if cleanup_error is None:
                        cleanup_error = exc
                for child in child_names:
                    try:
                        observed = os.stat(
                            child,
                            dir_fd=spill_descriptor,
                            follow_symlinks=False,
                        )
                        if not stat.S_ISREG(observed.st_mode):
                            raise SuccessorTransformAuthorityError(
                                "successor transform spill cleanup found a non-regular entry"
                            )
                        os.unlink(child, dir_fd=spill_descriptor)
                    except BaseException as exc:
                        if cleanup_error is None:
                            cleanup_error = exc
            finally:
                if (
                    spill_name_is_authorized
                    and scratch_descriptor >= 0
                    and spill_identity is not None
                    and cleanup_error is None
                ):
                    try:
                        remove_empty_owned_directory(
                            scratch_descriptor,
                            "spill",
                            spill_descriptor,
                            expected_inode=(spill_identity[0], spill_identity[1]),
                            error=SuccessorTransformAuthorityError,
                            label="successor transform spill",
                        )
                    except BaseException as exc:
                        cleanup_error = exc
                os.close(spill_descriptor)
                spill_descriptor = -1
        if scratch_descriptor >= 0:
            scratch_name_is_authorized = False
            try:
                if parent_descriptor >= 0 and name is not None and scratch_identity is not None:
                    try:
                        _require_named_child(
                            parent_descriptor,
                            name,
                            scratch_descriptor,
                            scratch_identity,
                            label="successor transform private scratch",
                            stage="cleanup",
                        )
                        scratch_name_is_authorized = True
                    except BaseException as exc:
                        if cleanup_error is None:
                            cleanup_error = exc
                try:
                    with os.scandir(scratch_descriptor) as iterator:
                        not_empty = any(True for _ in iterator)
                except BaseException as exc:
                    not_empty = True
                    if cleanup_error is None:
                        cleanup_error = exc
                if not_empty and cleanup_error is None:
                    cleanup_error = SuccessorTransformAuthorityError(
                        "successor transform private scratch is not empty"
                    )
                if (
                    scratch_name_is_authorized
                    and parent_descriptor >= 0
                    and name is not None
                    and scratch_identity is not None
                    and cleanup_error is None
                ):
                    remove_empty_owned_directory(
                        parent_descriptor,
                        name,
                        scratch_descriptor,
                        expected_inode=(scratch_identity[0], scratch_identity[1]),
                        error=SuccessorTransformAuthorityError,
                        label="successor transform private scratch",
                    )
            finally:
                os.close(scratch_descriptor)
                scratch_descriptor = -1
        if parent_descriptor >= 0:
            try:
                if parent_identity is not None:
                    try:
                        _require_named_parent(
                            parent,
                            parent_descriptor,
                            parent_identity,
                            stage="cleanup",
                        )
                    except BaseException as exc:
                        if cleanup_error is None and primary_error is None:
                            cleanup_error = exc
            finally:
                os.close(parent_descriptor)
        if cleanup_error is not None:
            if primary_error is not None:
                raise SuccessorTransformAuthorityError(
                    "successor transform authority failed and scratch cleanup failed"
                ) from cleanup_error
            raise cleanup_error
    if primary_error is not None:
        raise primary_error


def _table_columns(
    source: duckdb.DuckDBPyConnection,
    table: str,
) -> tuple[tuple[str, str], ...]:
    rows = source.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    if not rows:
        raise SuccessorTransformAuthorityError(
            f"transform table is absent or has no columns: {table}"
        )
    columns = tuple((str(name), str(data_type)) for name, data_type in rows)
    names = tuple(name for name, _data_type in columns)
    if len(names) != len(set(names)) or any(not name for name in names):
        raise SuccessorTransformAuthorityError(f"transform table has invalid columns: {table}")
    for _name, data_type in columns:
        _normalized_type(data_type)
    return columns


def _insert_hash_batch(
    scratch: _TransformScratch,
    digests: list[bytes],
) -> None:
    if not digests:
        return
    view_name = f"digest_batch_{uuid.uuid4().hex}"
    connection = scratch.connection
    _require_scratch(scratch, stage="before digest batch")
    connection.register(view_name, pa.table({"digest": pa.array(digests, type=pa.binary(32))}))
    try:
        connection.execute(f'INSERT INTO row_digests SELECT digest FROM "{view_name}"')
    finally:
        connection.unregister(view_name)
    _require_scratch(scratch, stage="after digest batch")


def _attest_table(
    source: duckdb.DuckDBPyConnection,
    scratch: _TransformScratch,
    physical_table: str,
    *,
    semantic_table: str | None = None,
) -> TransformOutputAttestation:
    validate_sql_identifier(physical_table)
    table = physical_table if semantic_table is None else semantic_table
    validate_sql_identifier(table)
    columns = _table_columns(source, physical_table)
    schema_sha256 = _schema_digest(table, columns)
    data_types = tuple(data_type for _name, data_type in columns)
    connection = scratch.connection
    _require_scratch(scratch, stage=f"before table {table}")

    quoted = f'"{physical_table}"'
    try:
        connection.execute("DROP TABLE IF EXISTS row_digests")
        connection.execute("CREATE TEMP TABLE row_digests (digest BLOB NOT NULL)")
        reader = source.execute(f"SELECT * FROM {quoted}").to_arrow_reader(
            batch_size=_ROW_BATCH_SIZE
        )
        row_count = 0
        for batch in reader:
            digests: list[bytes] = []
            for row_index in range(batch.num_rows):
                values = tuple(
                    batch.column(column_index)[row_index].as_py()
                    for column_index in range(batch.num_columns)
                )
                digests.append(_row_digest(values, data_types))
            _insert_hash_batch(scratch, digests)
            row_count += batch.num_rows
    except duckdb.OutOfMemoryException as exc:
        raise SuccessorTransformAuthorityError(f"{_DISABLED_SPILL_ERROR}: {table}") from exc
    except (duckdb.Error, pa.ArrowException) as exc:
        raise SuccessorTransformAuthorityError(f"transform table readback failed: {table}") from exc

    digest = hashlib.sha256()
    digest.update(_CONTENT_DOMAIN)
    digest.update(_canonical_field(table.encode("utf-8")))
    digest.update(bytes.fromhex(schema_sha256))
    digest.update(row_count.to_bytes(8, "big"))
    try:
        _require_scratch(scratch, stage=f"before grouping table {table}")
        grouped = connection.execute(
            "SELECT digest, COUNT(*) AS multiplicity "
            "FROM row_digests GROUP BY digest ORDER BY digest"
        )
        while rows := grouped.fetchmany(_HASH_BATCH_SIZE):
            for row_digest, multiplicity in rows:
                if not isinstance(row_digest, bytes) or len(row_digest) != 32:
                    raise SuccessorTransformAuthorityError("scratch row digest is invalid")
                count = int(multiplicity)
                if count <= 0:
                    raise SuccessorTransformAuthorityError("scratch row multiplicity is invalid")
                digest.update(row_digest)
                digest.update(count.to_bytes(8, "big"))
        connection.execute("DROP TABLE row_digests")
    except duckdb.OutOfMemoryException as exc:
        raise SuccessorTransformAuthorityError(f"{_DISABLED_SPILL_ERROR}: {table}") from exc
    except duckdb.Error as exc:
        raise SuccessorTransformAuthorityError(
            f"transform scratch aggregation failed: {table}"
        ) from exc
    _require_scratch(scratch, stage=f"after table {table}")
    return TransformOutputAttestation(
        table_name=table,
        row_count=row_count,
        schema_sha256=schema_sha256,
        content_sha256=digest.hexdigest(),
    )


def _require_exact_main_tables(
    source: duckdb.DuckDBPyConnection,
    physical_tables: tuple[str, ...],
) -> None:
    database_row = source.execute("SELECT current_database()").fetchone()
    if database_row is None or len(database_row) != 1 or type(database_row[0]) is not str:
        raise SuccessorTransformAuthorityError("transform database identity is unavailable")
    database_name = database_row[0]
    catalog_rows = source.execute(
        """
        SELECT database_name, schema_name, table_name, temporary, 'table' AS relation_kind
        FROM duckdb_tables()
        WHERE schema_name = 'main'
        UNION ALL
        SELECT database_name, schema_name, view_name, temporary, 'view' AS relation_kind
        FROM duckdb_views()
        WHERE schema_name = 'main'
        """
    ).fetchall()
    for physical_table in physical_tables:
        matches = tuple(
            row
            for row in catalog_rows
            if type(row[2]) is str and row[2].lower() == physical_table.lower()
        )
        exact = tuple(
            row
            for row in matches
            if row[0] == database_name
            and row[2] == physical_table
            and row[3] is False
            and row[4] == "table"
        )
        if len(exact) != 1 or len(matches) != 1:
            raise SuccessorTransformAuthorityError(
                f"transform physical relation is absent, ambiguous, temporary, or a view: "
                f"{physical_table}"
            )


def build_transform_relation_attestations(
    source: duckdb.DuckDBPyConnection,
    relations: tuple[tuple[str, str], ...],
    *,
    scratch_parent: Path,
    expected_scratch_parent_identity: tuple[int, int],
    transform_scratch_max_bytes: int,
) -> tuple[TransformOutputAttestation, ...]:
    """Attest exact physical tables under verifier-derived semantic output names."""

    if not isinstance(source, duckdb.DuckDBPyConnection):
        raise TypeError("source must be a DuckDBPyConnection")
    if (
        type(relations) is not tuple
        or not relations
        or any(
            type(item) is not tuple or len(item) != 2 or any(type(name) is not str for name in item)
            for item in relations
        )
    ):
        raise SuccessorTransformAuthorityError(
            "transform relation authority must be one nonempty exact tuple of string pairs"
        )
    for physical_table, semantic_table in relations:
        validate_sql_identifier(physical_table)
        validate_sql_identifier(semantic_table)
    physical_tables = tuple(item[0] for item in relations)
    semantic_tables = tuple(item[1] for item in relations)
    if len(set(physical_tables)) != len(physical_tables):
        raise SuccessorTransformAuthorityError(
            "transform physical relation authority is duplicated"
        )
    if len(set(semantic_tables)) != len(semantic_tables):
        raise SuccessorTransformAuthorityError(
            "transform semantic relation authority is duplicated"
        )
    ordered = tuple(sorted(relations, key=lambda item: item[1]))
    _require_exact_main_tables(source, physical_tables)
    with _private_scratch(
        scratch_parent,
        expected_scratch_parent_identity=expected_scratch_parent_identity,
        transform_scratch_max_bytes=transform_scratch_max_bytes,
    ) as scratch:
        return tuple(
            _attest_table(
                source,
                scratch,
                physical_table,
                semantic_table=semantic_table,
            )
            for physical_table, semantic_table in ordered
        )


def _attest_exact_tables(
    source: duckdb.DuckDBPyConnection,
    tables: Sequence[str],
    *,
    scratch_parent: Path,
    expected_scratch_parent_identity: tuple[int, int],
    transform_scratch_max_bytes: int,
) -> tuple[TransformOutputAttestation, ...]:
    normalized = tuple(sorted(tables))
    if not normalized or len(normalized) != len(set(normalized)):
        raise SuccessorTransformAuthorityError("transform table authority is empty or duplicated")
    for table in normalized:
        validate_sql_identifier(table)
    try:
        return build_transform_relation_attestations(
            source,
            tuple((table, table) for table in normalized),
            scratch_parent=scratch_parent,
            expected_scratch_parent_identity=expected_scratch_parent_identity,
            transform_scratch_max_bytes=transform_scratch_max_bytes,
        )
    except SuccessorTransformAuthorityError as exc:
        missing: list[str] = []
        for table in normalized:
            observed = source.execute(
                "SELECT EXISTS(SELECT 1 FROM duckdb_tables() "
                "WHERE database_name = current_database() AND schema_name = 'main' "
                "AND table_name = ? AND NOT temporary)",
                [table],
            ).fetchone()
            if observed is None or len(observed) != 1 or observed[0] is not True:
                missing.append(table)
        if missing:
            raise SuccessorTransformAuthorityError(
                "transform table authority is incomplete: missing=" + ",".join(missing[:20])
            ) from exc
        raise


def build_successor_transform_attestations(
    source: duckdb.DuckDBPyConnection,
    *,
    scratch_parent: Path,
    expected_scratch_parent_identity: tuple[int, int],
    transform_scratch_max_bytes: int,
) -> tuple[TransformOutputAttestation, ...]:
    """Re-derive the exact schema-backed successor transform authority from DuckDB."""

    if not isinstance(source, duckdb.DuckDBPyConnection):
        raise TypeError("source must be a DuckDBPyConnection")
    expected = tuple(sorted(expected_transform_output_tables(include_live=True)))
    result = _attest_exact_tables(
        source,
        expected,
        scratch_parent=scratch_parent,
        expected_scratch_parent_identity=expected_scratch_parent_identity,
        transform_scratch_max_bytes=transform_scratch_max_bytes,
    )
    if tuple(item.table_name for item in result) != expected:
        raise SuccessorTransformAuthorityError("transform attestation universe differs")
    return result
