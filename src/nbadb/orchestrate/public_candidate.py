"""Build a sanitized public candidate from an explicit relation allowlist.

The builder creates a fresh root and recreates each declared relation in new
DuckDB, SQLite, CSV, and Parquet resources.  It never copies a private
checkpoint/database wholesale and never uses a denylist to decide what is
public.  The exact-four provider-body authority relations are unconditionally
rejected.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import duckdb

from nbadb.contracts.public_data_disposition import (
    PublicDataDispositionV1,
    PublicRelationDispositionV1,
    PublicResourceDispositionV1,
)
from nbadb.contracts.receipt_digest import canonical_receipt_bytes
from nbadb.orchestrate.raw_publication_inventory import (
    PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CandidateRelationSpec",
    "PublicCandidateBuild",
    "PublicCandidateError",
    "build_public_candidate",
]

_TABLE_RE: Final = re.compile(r"[a-z][a-z0-9_]*\Z", flags=re.ASCII)
_BINARY_TYPES: Final = frozenset({"BLOB", "BINARY", "VARBINARY", "BYTEA", "BYTES"})


class PublicCandidateError(ValueError):
    """A public candidate source, allowlist, or generated tree is invalid."""


@dataclass(frozen=True, slots=True)
class CandidateRelationSpec:
    """One explicitly approved source relation."""

    table_name: str
    category: str

    def __post_init__(self) -> None:
        if not isinstance(self.table_name, str) or _TABLE_RE.fullmatch(self.table_name) is None:
            raise PublicCandidateError("table_name must be lowercase snake_case")
        if self.table_name in PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES:
            raise PublicCandidateError(
                f"private provider-body relation cannot enter a public candidate: {self.table_name}"
            )
        if not isinstance(self.category, str) or not self.category.strip():
            raise PublicCandidateError("category must be a nonempty string")


@dataclass(frozen=True, slots=True)
class PublicCandidateBuild:
    """Fresh candidate root plus its exact public disposition."""

    root: Path
    disposition: PublicDataDispositionV1


def _quote_identifier(value: str) -> str:
    if _TABLE_RE.fullmatch(value) is None:
        raise PublicCandidateError(f"unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    rows = connection.execute(f"DESCRIBE {_quote_identifier(table_name)}").fetchall()
    if not rows:
        raise PublicCandidateError(f"declared relation is absent: {table_name}")
    names = tuple(str(row[0]) for row in rows)
    types = tuple(str(row[1]).upper() for row in rows)
    if len(names) != len(set(names)) or any(not name for name in names):
        raise PublicCandidateError(f"declared relation has invalid columns: {table_name}")
    if any(any(token in physical for token in _BINARY_TYPES) for physical in types):
        raise PublicCandidateError(f"public relation has a binary physical type: {table_name}")
    ordered = sorted(zip(names, types, strict=True), key=lambda pair: pair[0])
    return tuple(name for name, _ in ordered), tuple(physical for _, physical in ordered)


def _sqlite_type(duckdb_type: str) -> str:
    upper = duckdb_type.upper()
    if any(token in upper for token in ("INT", "BOOL")):
        return "INTEGER"
    if any(token in upper for token in ("DOUBLE", "REAL", "FLOAT", "DECIMAL", "NUMERIC")):
        return "REAL"
    return "TEXT"


def _copy_relation_to_sqlite(
    source: duckdb.DuckDBPyConnection,
    target: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
    physical_types: tuple[str, ...],
) -> None:
    quoted_table = _quote_identifier(table_name)
    quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
    declarations = ", ".join(
        f"{_quote_identifier(column)} {_sqlite_type(physical)}"
        for column, physical in zip(columns, physical_types, strict=True)
    )
    target.execute(f"CREATE TABLE {quoted_table} ({declarations})")
    placeholders = ", ".join("?" for _ in columns)
    cursor = source.execute(f"SELECT {quoted_columns} FROM {quoted_table}")
    while rows := cursor.fetchmany(1_000):
        normalized = [
            tuple(
                json.dumps(value, sort_keys=True, separators=(",", ":"))
                if isinstance(value, (dict, list, tuple))
                else value
                for value in row
            )
            for row in rows
        ]
        target.executemany(
            f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})",
            normalized,
        )


def _resource(
    root: Path,
    relative: str,
    media_type: str,
    relation_name: str | None = None,
) -> PublicResourceDispositionV1:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise PublicCandidateError(f"candidate resource is not one regular file: {relative}")
    return PublicResourceDispositionV1(
        path=relative,
        size_bytes=path.stat().st_size,
        sha256=_file_sha256(path),
        media_type=media_type,
        relation_name=relation_name,
    )


def _inventory_payload(
    resources: tuple[PublicResourceDispositionV1, ...],
) -> list[dict[str, object]]:
    return [
        {"path": item.path, "sha256": item.sha256, "size_bytes": item.size_bytes}
        for item in resources
    ]


def build_public_candidate(
    *,
    source_duckdb: Path,
    target_root: Path,
    relation_specs: tuple[CandidateRelationSpec, ...],
) -> PublicCandidateBuild:
    """Recreate an exact positive-allowlist candidate in a brand-new root."""

    if not relation_specs:
        raise PublicCandidateError("public candidate requires at least one declared relation")
    names = tuple(spec.table_name for spec in relation_specs)
    if len(names) != len(set(names)) or names != tuple(sorted(names)):
        raise PublicCandidateError("relation_specs must be unique and sorted by table_name")
    if source_duckdb.is_symlink() or not source_duckdb.is_file():
        raise PublicCandidateError("source_duckdb must be one regular file")
    if target_root.exists() or target_root.is_symlink():
        raise PublicCandidateError("target_root must not already exist")

    target_root.mkdir(mode=0o755, parents=False)
    csv_root = target_root / "csv"
    parquet_root = target_root / "parquet"
    csv_root.mkdir(mode=0o755)
    parquet_root.mkdir(mode=0o755)
    target_duckdb = target_root / "nba.duckdb"
    target_sqlite = target_root / "nba.sqlite"

    relation_entries: list[PublicRelationDispositionV1] = []
    with (
        duckdb.connect(str(source_duckdb), read_only=True) as source,
        duckdb.connect(str(target_duckdb)) as target,
    ):
        sqlite = sqlite3.connect(target_sqlite)
        try:
            for spec in relation_specs:
                columns, physical_types = _schema(source, spec.table_name)
                relation_entries.append(
                    PublicRelationDispositionV1.build(
                        table_name=spec.table_name,
                        category=spec.category,
                        ordered_columns=columns,
                        physical_types=physical_types,
                    )
                )
                quoted_table = _quote_identifier(spec.table_name)
                quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
                frame = source.execute(
                    f"SELECT {quoted_columns} FROM {quoted_table}"
                ).to_arrow_table()
                target.register("_candidate_frame", frame)
                try:
                    target.execute(
                        f"CREATE TABLE {quoted_table} AS "
                        f"SELECT {quoted_columns} FROM _candidate_frame"
                    )
                finally:
                    target.unregister("_candidate_frame")
                _copy_relation_to_sqlite(
                    source,
                    sqlite,
                    spec.table_name,
                    columns,
                    physical_types,
                )
                csv_path = csv_root / f"{spec.table_name}.csv"
                parquet_path = parquet_root / f"{spec.table_name}.parquet"
                csv_sql_path = str(csv_path).replace("'", "''")
                parquet_sql_path = str(parquet_path).replace("'", "''")
                target.execute(
                    f"COPY (SELECT {quoted_columns} FROM {quoted_table}) "
                    f"TO '{csv_sql_path}' (FORMAT CSV, HEADER)"
                )
                target.execute(
                    f"COPY (SELECT {quoted_columns} FROM {quoted_table}) "
                    f"TO '{parquet_sql_path}' (FORMAT PARQUET)"
                )
            target.execute("CHECKPOINT")
            sqlite.commit()
        finally:
            sqlite.close()

    with duckdb.connect(str(target_duckdb), read_only=True) as candidate:
        observed = {
            str(row[0])
            for row in candidate.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        }
    if observed != set(names):
        raise PublicCandidateError("candidate DuckDB contains undeclared relations")

    resources: list[PublicResourceDispositionV1] = [
        _resource(target_root, "nba.duckdb", "application/vnd.duckdb"),
        _resource(target_root, "nba.sqlite", "application/vnd.sqlite3"),
    ]
    for spec in relation_specs:
        resources.extend(
            (
                _resource(
                    target_root,
                    f"csv/{spec.table_name}.csv",
                    "text/csv",
                    spec.table_name,
                ),
                _resource(
                    target_root,
                    f"parquet/{spec.table_name}.parquet",
                    "application/vnd.apache.parquet",
                    spec.table_name,
                ),
            )
        )
    ordered_resources = tuple(sorted(resources, key=lambda item: item.path))
    inventory = _inventory_payload(ordered_resources)
    candidate_inventory_sha256 = hashlib.sha256(canonical_receipt_bytes(inventory)).hexdigest()
    candidate_tree_sha256 = hashlib.sha256(
        canonical_receipt_bytes(
            {"schema_version": 1, "resources": inventory, "relations": list(names)}
        )
    ).hexdigest()
    disposition = PublicDataDispositionV1.build(
        candidate_tree_sha256=candidate_tree_sha256,
        candidate_inventory_sha256=candidate_inventory_sha256,
        relation_entries=tuple(relation_entries),
        resource_entries=ordered_resources,
    )
    disposition_path = target_root / "public-data-disposition.json"
    descriptor = os.open(
        disposition_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical_receipt_bytes(disposition.to_payload()))
        handle.flush()
        os.fsync(handle.fileno())
    return PublicCandidateBuild(root=target_root, disposition=disposition)
