from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import nbadb.orchestrate.successor_publication_inventory as inventory_module
from nbadb.kaggle.client import KaggleClient

if TYPE_CHECKING:
    from typing import Any


def _file_receipt(path: Path) -> tuple[int, str]:
    byte_count = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            byte_count += len(chunk)
            digest.update(chunk)
    return byte_count, digest.hexdigest()


def _validate_file_resources(
    resources: list[dict[str, Any]],
    *,
    memory_limit_bytes: int | None = None,
    temp_max_bytes: int | None = None,
) -> None:
    duckdb_resource = resources[0]
    parquet_resource = resources[-1]
    parquet_path = Path(parquet_resource["source_path"])
    inventory_module.validate_authoritative_duckdb_parquet_values(
        Path(duckdb_resource["source_path"]),
        {"sample": parquet_path},
        expected_duckdb_bytes=duckdb_resource["bytes"],
        expected_duckdb_sha256=duckdb_resource["sha256"],
        expected_parquet_files={
            "sample": {
                parquet_path.name: (
                    parquet_resource["bytes"],
                    parquet_resource["sha256"],
                )
            }
        },
        memory_limit_bytes=memory_limit_bytes,
        temp_max_bytes=temp_max_bytes,
    )


def _source_backed_resources(
    root: Path,
    *,
    duckdb_rows: list[tuple[int, str | None]],
    parquet_rows: list[tuple[int, str | None]],
) -> list[dict[str, Any]]:
    root.mkdir()
    (root / "csv").mkdir()
    (root / "parquet" / "sample").mkdir(parents=True)
    duckdb_path = root / "nba.duckdb"
    duckdb_connection = duckdb.connect(str(duckdb_path))
    try:
        duckdb_connection.execute("CREATE TABLE sample (id BIGINT, label VARCHAR)")
        if duckdb_rows:
            duckdb_connection.executemany("INSERT INTO sample VALUES (?, ?)", duckdb_rows)
    finally:
        duckdb_connection.close()

    sqlite_path = root / "nba.sqlite"
    sqlite_connection = sqlite3.connect(sqlite_path)
    try:
        sqlite_connection.execute("CREATE TABLE sample (id INTEGER, label TEXT)")
        sqlite_connection.executemany(
            "INSERT INTO sample VALUES (?, ?)",
            [(index, f"sqlite-{index}") for index in range(len(duckdb_rows))],
        )
        sqlite_connection.commit()
    finally:
        sqlite_connection.close()
    csv_path = root / "csv" / "sample.csv"
    csv_path.write_text(
        "id,label\n" + "".join(f"{index},csv-{index}\n" for index in range(len(duckdb_rows))),
        encoding="utf-8",
    )
    parquet_path = root / "parquet" / "sample" / "sample.parquet"
    pq.write_table(
        pa.table(
            {
                "id": pa.array([row[0] for row in parquet_rows], type=pa.int64()),
                "label": pa.array([row[1] for row in parquet_rows], type=pa.string()),
            }
        ),
        parquet_path,
    )
    row_count = len(duckdb_rows)
    columns = ["id", "label"]
    duckdb_bytes, duckdb_sha256 = _file_receipt(duckdb_path)
    sqlite_bytes, sqlite_sha256 = _file_receipt(sqlite_path)
    csv_bytes, csv_sha256 = _file_receipt(csv_path)
    parquet_bytes, parquet_sha256 = _file_receipt(parquet_path)
    return [
        {
            "path": "nba.duckdb",
            "kind": "file",
            "source_path": str(duckdb_path.resolve()),
            "bytes": duckdb_bytes,
            "sha256": duckdb_sha256,
            "database_validation": {
                "engine": "duckdb",
                "tables": {"sample": row_count},
                "columns": {"sample": columns},
            },
        },
        {
            "path": "nba.sqlite",
            "kind": "file",
            "source_path": str(sqlite_path.resolve()),
            "bytes": sqlite_bytes,
            "sha256": sqlite_sha256,
            "database_validation": {
                "engine": "sqlite",
                "tables": {"sample": row_count},
                "columns": {"sample": columns},
            },
        },
        {
            "path": "csv/sample.csv",
            "kind": "file",
            "source_path": str(csv_path.resolve()),
            "bytes": csv_bytes,
            "sha256": csv_sha256,
            "csv_validation": {
                "row_count": row_count,
                "columns": columns,
            },
        },
        {
            "path": "parquet/sample/sample.parquet",
            "kind": "file",
            "source_path": str(parquet_path.resolve()),
            "bytes": parquet_bytes,
            "sha256": parquet_sha256,
            "parquet_validation": {
                "row_count": len(parquet_rows),
                "columns": columns,
            },
        },
    ]


def test_full_publication_accepts_exact_duckdb_parquet_values_and_convenience_drift(
    tmp_path: Path,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "東京 🏀"), (2, None), (3, "")],
        parquet_rows=[(3, ""), (1, "東京 🏀"), (2, None)],
    )

    KaggleClient._validate_full_publication_format_parity(
        resources,
        require_authoritative_values=True,
    )


def test_full_publication_accepts_empty_authoritative_table(tmp_path: Path) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[],
        parquet_rows=[],
    )

    KaggleClient._validate_full_publication_format_parity(
        resources,
        require_authoritative_values=True,
    )


def test_authoritative_multiset_query_scans_each_authority_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "alpha"), (1, "alpha"), (2, None)],
        parquet_rows=[(2, None), (1, "alpha"), (1, "alpha")],
    )
    real_connect = duckdb.connect
    queries: list[str] = []

    class RecordingConnection:
        def __init__(self, connection: Any) -> None:
            self.connection = connection

        def execute(self, query: str, *args: object, **kwargs: object) -> Any:
            queries.append(query)
            return self.connection.execute(query, *args, **kwargs)

        def close(self) -> None:
            self.connection.close()

    def recording_connect(*args: object, **kwargs: object) -> RecordingConnection:
        return RecordingConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(inventory_module.duckdb, "connect", recording_connect)

    KaggleClient._validate_full_publication_format_parity(
        resources,
        require_authoritative_values=True,
    )

    parity_queries = [query for query in queries if 'SUM("__nbadb_delta' in query]
    assert len(parity_queries) == 1
    parity_query = parity_queries[0]
    assert parity_query.count('FROM "sample"') == 1
    assert parity_query.count("read_parquet(") == 1
    assert "EXCEPT ALL" not in parity_query


@pytest.mark.parametrize(
    ("memory_limit_bytes", "temp_max_bytes", "expected_message"),
    [
        (64 * 1024 * 1024 - 1, 64 * 1024 * 1024, "memory maximum is outside safe bounds"),
        (64 * 1024 * 1024, 64 * 1024 * 1024 - 1, "temporary maximum is outside safe bounds"),
    ],
)
def test_authoritative_value_parity_rejects_unsafe_resource_caps_before_scratch_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    memory_limit_bytes: int,
    temp_max_bytes: int,
    expected_message: str,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "alpha")],
        parquet_rows=[(1, "alpha")],
    )
    scratch_parent = tmp_path / "private-scratch"
    scratch_parent.mkdir()
    monkeypatch.setattr(inventory_module.tempfile, "tempdir", str(scratch_parent))

    with pytest.raises(ValueError, match=expected_message):
        _validate_file_resources(
            resources,
            memory_limit_bytes=memory_limit_bytes,
            temp_max_bytes=temp_max_bytes,
        )

    assert list(scratch_parent.iterdir()) == []


def test_authoritative_value_parity_spills_within_cap_and_cleans_private_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    database = root / "nba.duckdb"
    parquet = root / "sample.parquet"
    connection = duckdb.connect(str(database))
    try:
        connection.execute(
            "CREATE TABLE sample AS "
            "SELECT i::BIGINT AS id, repeat(md5(i::VARCHAR), 4)::VARCHAR AS payload "
            "FROM range(400000) AS source(i)"
        )
        connection.execute(
            "COPY sample TO ? (FORMAT PARQUET, COMPRESSION 'uncompressed')",
            [str(parquet)],
        )
    finally:
        connection.close()

    database_receipt = _file_receipt(database)
    parquet_receipt = _file_receipt(parquet)
    scratch_parent = tmp_path / "private-scratch"
    scratch_parent.mkdir()
    monkeypatch.setattr(inventory_module.tempfile, "tempdir", str(scratch_parent))
    stop = threading.Event()
    spill_observed = threading.Event()
    maximum_spill_bytes = 0

    def observe_spill() -> None:
        nonlocal maximum_spill_bytes
        while not stop.wait(0.002):
            try:
                spill_files = tuple(scratch_parent.rglob("duckdb_temp_storage*.tmp"))
                spill_bytes = sum(path.stat().st_size for path in spill_files)
            except OSError:
                continue
            if spill_bytes:
                spill_observed.set()
                maximum_spill_bytes = max(maximum_spill_bytes, spill_bytes)

    observer = threading.Thread(target=observe_spill, daemon=True)
    observer.start()
    temp_max_bytes = 192 * 1024 * 1024
    try:
        inventory_module.validate_authoritative_duckdb_parquet_values(
            database.resolve(),
            {"sample": parquet.resolve()},
            expected_duckdb_bytes=database_receipt[0],
            expected_duckdb_sha256=database_receipt[1],
            expected_parquet_files={"sample": {parquet.name: parquet_receipt}},
            memory_limit_bytes=64 * 1024 * 1024,
            temp_max_bytes=temp_max_bytes,
        )
    finally:
        stop.set()
        observer.join(timeout=5)

    assert not observer.is_alive()
    assert spill_observed.is_set()
    assert 0 < maximum_spill_bytes <= temp_max_bytes
    assert list(scratch_parent.iterdir()) == []


def test_full_publication_rejects_equal_schema_and_count_authoritative_value_drift(
    tmp_path: Path,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "alpha")],
        parquet_rows=[(1, "beta")],
    )

    with pytest.raises(ValueError, match="row-multiset value parity failed"):
        KaggleClient._validate_full_publication_format_parity(
            resources,
            require_authoritative_values=True,
        )


def test_full_publication_authoritative_gate_requires_source_backed_resources(
    tmp_path: Path,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "alpha")],
        parquet_rows=[(1, "alpha")],
    )
    for resource in resources:
        resource.pop("source_path")

    with pytest.raises(ValueError, match="authoritative DuckDB source is missing"):
        KaggleClient._validate_full_publication_format_parity(
            resources,
            require_authoritative_values=True,
        )


def test_full_publication_rejects_narrower_authoritative_integer_type(
    tmp_path: Path,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "alpha")],
        parquet_rows=[(1, "alpha")],
    )
    parquet_path = Path(resources[-1]["source_path"])
    pq.write_table(
        pa.table(
            {
                "id": pa.array([1], type=pa.int8()),
                "label": pa.array(["alpha"], type=pa.string()),
            }
        ),
        parquet_path,
    )
    parquet_bytes, parquet_sha256 = _file_receipt(parquet_path)
    resources[-1]["bytes"] = parquet_bytes
    resources[-1]["sha256"] = parquet_sha256

    with pytest.raises(ValueError, match="logical-type parity failed"):
        KaggleClient._validate_full_publication_format_parity(
            resources,
            require_authoritative_values=True,
        )


def test_duckdb_swap_and_restore_cannot_escape_preflight_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "alpha")],
        parquet_rows=[(1, "alpha")],
    )
    foreign_resources = _source_backed_resources(
        tmp_path / "foreign",
        duckdb_rows=[(1, "foreign")],
        parquet_rows=[(1, "foreign")],
    )
    database = Path(resources[0]["source_path"])
    foreign_database = Path(foreign_resources[0]["source_path"])
    held_database = tmp_path / "held.duckdb"
    real_open = inventory_module.os.open
    fired = False

    def swapping_open(path: object, *args: object, **kwargs: object) -> int:
        nonlocal fired
        if not fired and os.fspath(path) == os.fspath(database):
            fired = True
            database.rename(held_database)
            foreign_database.rename(database)
            try:
                descriptor = real_open(path, *args, **kwargs)
            finally:
                database.rename(foreign_database)
                held_database.rename(database)
            return descriptor
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(inventory_module.os, "open", swapping_open)

    with pytest.raises(ValueError, match="changed before snapshot admission"):
        KaggleClient._validate_full_publication_format_parity(
            resources,
            require_authoritative_values=True,
        )
    assert fired


def test_private_duckdb_snapshot_swap_and_restore_cannot_change_engine_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "alpha")],
        parquet_rows=[(1, "alpha")],
    )
    foreign_resources = _source_backed_resources(
        tmp_path / "foreign",
        duckdb_rows=[(1, "foreign")],
        parquet_rows=[(1, "foreign")],
    )
    source_database = Path(resources[0]["source_path"])
    foreign_database = Path(foreign_resources[0]["source_path"])
    real_connect = duckdb.connect
    fired = False

    def swapping_connect(database: object, *args: object, **kwargs: object) -> object:
        nonlocal fired
        database_path = Path(os.fspath(database))
        if (
            not fired
            and database_path != source_database
            and database_path.name == "nba.duckdb"
            and database_path.parent.name.startswith("nbadb-authoritative-value-parity-")
        ):
            fired = True
            held_database = database_path.with_name("held-authoritative.duckdb")
            database_path.rename(held_database)
            foreign_database.rename(database_path)
            try:
                connection = real_connect(database, *args, **kwargs)
            finally:
                database_path.rename(foreign_database)
                held_database.rename(database_path)
            return connection
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(inventory_module.duckdb, "connect", swapping_connect)

    with pytest.raises(
        ValueError, match="private snapshot changed at after authoritative engine open"
    ):
        KaggleClient._validate_full_publication_format_parity(
            resources,
            require_authoritative_values=True,
        )
    assert fired


def test_parquet_swap_and_restore_cannot_escape_preflight_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "alpha")],
        parquet_rows=[(1, "alpha")],
    )
    foreign_resources = _source_backed_resources(
        tmp_path / "foreign",
        duckdb_rows=[(1, "foreign")],
        parquet_rows=[(1, "foreign")],
    )
    parquet = Path(resources[-1]["source_path"])
    foreign_parquet = Path(foreign_resources[-1]["source_path"])
    held_parquet = tmp_path / "held.parquet"
    real_open = inventory_module.os.open
    fired = False

    def swapping_open(path: object, *args: object, **kwargs: object) -> int:
        nonlocal fired
        if not fired and os.fspath(path) == os.fspath(parquet):
            fired = True
            parquet.rename(held_parquet)
            foreign_parquet.rename(parquet)
            try:
                descriptor = real_open(path, *args, **kwargs)
            finally:
                parquet.rename(foreign_parquet)
                held_parquet.rename(parquet)
            return descriptor
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(inventory_module.os, "open", swapping_open)

    with pytest.raises(ValueError, match="differs from its preflight receipt"):
        KaggleClient._validate_full_publication_format_parity(
            resources,
            require_authoritative_values=True,
        )
    assert fired


def test_full_publication_rejects_authoritative_duplicate_multiplicity_drift(
    tmp_path: Path,
) -> None:
    resources = _source_backed_resources(
        tmp_path / "data",
        duckdb_rows=[(1, "same"), (1, "same"), (2, "other")],
        parquet_rows=[(1, "same"), (2, "other"), (2, "other")],
    )

    with pytest.raises(ValueError, match="row-multiset value parity failed"):
        KaggleClient._validate_full_publication_format_parity(
            resources,
            require_authoritative_values=True,
        )


def test_full_publication_reconstructs_and_compares_partition_values(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "csv").mkdir()
    parquet_root = root / "parquet" / "sample"
    duckdb_path = root / "nba.duckdb"
    duckdb_connection = duckdb.connect(str(duckdb_path))
    try:
        duckdb_connection.execute(
            "CREATE TABLE sample (id BIGINT, season_year VARCHAR, label VARCHAR)"
        )
        duckdb_connection.execute(
            "INSERT INTO sample VALUES (1, '2024-25', 'alpha'), (2, '2025-26', 'beta')"
        )
    finally:
        duckdb_connection.close()
    sqlite_path = root / "nba.sqlite"
    sqlite_connection = sqlite3.connect(sqlite_path)
    try:
        sqlite_connection.execute("CREATE TABLE sample (id INTEGER, season_year TEXT, label TEXT)")
        sqlite_connection.executemany(
            "INSERT INTO sample VALUES (?, ?, ?)",
            [(1, "convenience", "sqlite"), (2, "convenience", "sqlite")],
        )
        sqlite_connection.commit()
    finally:
        sqlite_connection.close()
    csv_path = root / "csv" / "sample.csv"
    csv_path.write_text(
        "id,season_year,label\n1,convenience,csv\n2,convenience,csv\n",
        encoding="utf-8",
    )
    parquet_files: list[dict[str, Any]] = []
    for identifier, season, label in (
        (1, "2024-25", "alpha"),
        (2, "2025-26", "beta"),
    ):
        relative_path = f"season_year={season}/part0.parquet"
        parquet_path = parquet_root / relative_path
        parquet_path.parent.mkdir(parents=True)
        pq.write_table(
            pa.table(
                {
                    "id": pa.array([identifier], type=pa.int64()),
                    "label": [label],
                }
            ),
            parquet_path,
        )
        parquet_bytes, parquet_sha256 = _file_receipt(parquet_path)
        parquet_files.append(
            {
                "path": relative_path,
                "bytes": parquet_bytes,
                "sha256": parquet_sha256,
                "parquet_validation": {
                    "row_count": 1,
                    "columns": ["id", "label"],
                },
            }
        )
    columns = ["id", "season_year", "label"]
    duckdb_bytes, duckdb_sha256 = _file_receipt(duckdb_path)
    sqlite_bytes, sqlite_sha256 = _file_receipt(sqlite_path)
    csv_bytes, csv_sha256 = _file_receipt(csv_path)
    resources: list[dict[str, Any]] = [
        {
            "path": "nba.duckdb",
            "kind": "file",
            "source_path": str(duckdb_path.resolve()),
            "bytes": duckdb_bytes,
            "sha256": duckdb_sha256,
            "database_validation": {
                "engine": "duckdb",
                "tables": {"sample": 2},
                "columns": {"sample": columns},
            },
        },
        {
            "path": "nba.sqlite",
            "kind": "file",
            "source_path": str(sqlite_path.resolve()),
            "bytes": sqlite_bytes,
            "sha256": sqlite_sha256,
            "database_validation": {
                "engine": "sqlite",
                "tables": {"sample": 2},
                "columns": {"sample": columns},
            },
        },
        {
            "path": "csv/sample.csv",
            "kind": "file",
            "source_path": str(csv_path.resolve()),
            "bytes": csv_bytes,
            "sha256": csv_sha256,
            "csv_validation": {"row_count": 2, "columns": columns},
        },
        {
            "path": "parquet/sample",
            "kind": "directory",
            "source_path": str(parquet_root.resolve()),
            "files": parquet_files,
        },
    ]

    KaggleClient._validate_full_publication_format_parity(
        resources,
        require_authoritative_values=True,
    )

    (parquet_root / "season_year=2024-25").rename(parquet_root / "season_year=2023-24")
    parquet_files[0]["path"] = "season_year=2023-24/part0.parquet"
    with pytest.raises(ValueError, match="row-multiset value parity failed"):
        KaggleClient._validate_full_publication_format_parity(
            resources,
            require_authoritative_values=True,
        )
