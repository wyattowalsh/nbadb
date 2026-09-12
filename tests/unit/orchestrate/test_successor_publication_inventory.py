from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import cast

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import nbadb.orchestrate.successor_publication_inventory as inventory_module
import nbadb.orchestrate.w2_database_assurance as w2_assurance_module
from nbadb.kaggle.metadata import expected_full_publication_resource_contract
from nbadb.orchestrate.raw_publication_inventory import (
    raw_request_authority_publication_tables,
)
from nbadb.orchestrate.successor_assurance import SuccessorPublicResourceAttestation
from nbadb.orchestrate.successor_publication_inventory import (
    _DatabaseSnapshot,
    _DataContract,
    _duckdb_tables,
    _identity,
    _inspect_publication_root,
    _production_data_contract,
    inspect_successor_candidate_publication,
    require_successor_publication_formats,
    successor_publication_freshness_season,
    validate_successor_publication_freshness,
)
from nbadb.orchestrate.w2_publication_inventory import (
    w2_public_value_authority_publication_tables,
)

_FILE_CONTRACT = _DataContract.from_mapping(
    {
        "nba.duckdb": "file",
        "nba.sqlite": "file",
        "csv/sample.csv": "file",
        "parquet/sample/sample.parquet": "file",
    }
)
_DIRECTORY_CONTRACT = _DataContract.from_mapping(
    {
        "nba.duckdb": "file",
        "nba.sqlite": "file",
        "csv/sample.csv": "file",
        "parquet/sample": "directory",
    }
)

_TEST_CAPACITY_BYTES = 64 * 1024 * 1024


def _scratch_kwargs(path: Path) -> dict[str, object]:
    scratch = path.resolve()
    observed = scratch.stat()
    return {
        "scratch_parent": scratch,
        "expected_scratch_root_identity": (observed.st_dev, observed.st_ino),
        "inventory_duckdb_snapshot_max_bytes": _TEST_CAPACITY_BYTES,
        "inventory_sqlite_snapshot_max_bytes": _TEST_CAPACITY_BYTES,
        "transform_scratch_max_bytes": _TEST_CAPACITY_BYTES,
    }


def _write_databases(
    root: Path, *, columns: tuple[str, ...], rows: list[tuple[object, ...]]
) -> None:
    definitions = ", ".join(
        f'"{column}" {"BIGINT" if column == "id" else "VARCHAR"}' for column in columns
    )
    placeholders = ", ".join("?" for _column in columns)

    duckdb_connection = duckdb.connect(str(root / "nba.duckdb"))
    try:
        duckdb_connection.execute(f"CREATE TABLE sample ({definitions})")
        if rows:
            duckdb_connection.executemany(
                f"INSERT INTO sample VALUES ({placeholders})",
                rows,
            )
    finally:
        duckdb_connection.close()

    sqlite_connection = sqlite3.connect(root / "nba.sqlite")
    try:
        sqlite_connection.execute(f"CREATE TABLE sample ({definitions})")
        if rows:
            sqlite_connection.executemany(
                f"INSERT INTO sample VALUES ({placeholders})",
                rows,
            )
        sqlite_connection.commit()
    finally:
        sqlite_connection.close()


def _truthful_file_tree(root: Path, *, value: str = "alpha") -> None:
    root.mkdir()
    (root / "csv").mkdir()
    (root / "parquet" / "sample").mkdir(parents=True)
    _write_databases(root, columns=("id", "label"), rows=[(1, value)])
    (root / "csv" / "sample.csv").write_text(
        f"id,label\n1,{value}\n",
        encoding="utf-8",
    )
    pq.write_table(
        pa.table({"id": [1], "label": [value]}),
        root / "parquet" / "sample" / "sample.parquet",
    )


def _truthful_directory_tree(root: Path) -> None:
    root.mkdir()
    (root / "csv").mkdir()
    partition = root / "parquet" / "sample" / "season_year=2025-26"
    partition.mkdir(parents=True)
    _write_databases(
        root,
        columns=("id", "season_year"),
        rows=[(1, "2025-26")],
    )
    (root / "csv" / "sample.csv").write_text(
        "id,season_year\n1,2025-26\n",
        encoding="utf-8",
    )
    pq.write_table(pa.table({"id": [1]}), partition / "part0.parquet")


def _typed_authoritative_tree(root: Path) -> None:
    root.mkdir()
    (root / "csv").mkdir()
    (root / "parquet" / "sample").mkdir(parents=True)
    duckdb_connection = duckdb.connect(str(root / "nba.duckdb"))
    try:
        duckdb_connection.execute(
            """
            CREATE TABLE sample (
                id BIGINT,
                amount DECIMAL(38, 9),
                label VARCHAR,
                played_on DATE,
                observed_at TIMESTAMP WITH TIME ZONE,
                optional_text VARCHAR
            )
            """
        )
        duckdb_connection.execute(
            """
            INSERT INTO sample VALUES
                (
                    9223372036854775806,
                    12345678901234567890123456789.123456789,
                    '東京 🏀',
                    DATE '2025-06-01',
                    TIMESTAMPTZ '2025-06-01 12:34:56.123456+00',
                    NULL
                ),
                (
                    -9223372036854775807,
                    -0.000000001,
                    '',
                    DATE '1946-11-01',
                    TIMESTAMPTZ '1946-11-01 01:02:03+00',
                    ''
                )
            """
        )
        duckdb_connection.execute(
            "COPY sample TO ? (FORMAT PARQUET)",
            [str(root / "parquet" / "sample" / "sample.parquet")],
        )
    finally:
        duckdb_connection.close()

    sqlite_connection = sqlite3.connect(root / "nba.sqlite")
    try:
        sqlite_connection.execute(
            "CREATE TABLE sample ("
            "id INTEGER, amount TEXT, label TEXT, played_on TEXT, "
            "observed_at TEXT, optional_text TEXT)"
        )
        sqlite_connection.executemany(
            "INSERT INTO sample VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "convenience", "sqlite one", "date", "instant", "null"),
                (2, "convenience", "sqlite two", "date", "instant", "empty"),
            ],
        )
        sqlite_connection.commit()
    finally:
        sqlite_connection.close()
    (root / "csv" / "sample.csv").write_text(
        "id,amount,label,played_on,observed_at,optional_text\n"
        "1,convenience,csv one,date,instant,null\n"
        "2,convenience,csv two,date,instant,empty\n",
        encoding="utf-8",
    )


def _inspect(root: Path, contract: _DataContract = _FILE_CONTRACT):
    return _inspect_publication_root(
        root.resolve(),
        contract,
        **_scratch_kwargs(root.parent),
    )


def test_minimal_truthful_contract_slice_returns_exact_path_free_evidence(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)

    resources, database, transform_outputs = _inspect(root)

    assert tuple(resource.resource_id for resource in resources) == tuple(
        path for path, _kind in _FILE_CONTRACT.resources
    )
    assert all(isinstance(resource, SuccessorPublicResourceAttestation) for resource in resources)
    assert database.duckdb_sha256 == next(
        resource.sha256 for resource in resources if resource.resource_id == "nba.duckdb"
    )
    assert database.sqlite_sha256 == next(
        resource.sha256 for resource in resources if resource.resource_id == "nba.sqlite"
    )
    assert transform_outputs == ()
    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_slice_inventory_returns_db_derived_transform_attestation(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)

    _resources, _database, transforms = _inspect_publication_root(
        root.resolve(),
        _FILE_CONTRACT,
        **_scratch_kwargs(root.parent),
        transform_tables=("sample",),
    )

    assert len(transforms) == 1
    assert transforms[0].table_name == "sample"
    assert transforms[0].row_count == 1
    assert len(transforms[0].schema_sha256) == 64
    assert len(transforms[0].content_sha256) == 64
    assert not list(tmp_path.glob("nbadb-successor-transform-*"))


def test_slice_transform_attestation_changes_after_duckdb_mutation(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    _resources, _database, before = _inspect_publication_root(
        root.resolve(),
        _FILE_CONTRACT,
        **_scratch_kwargs(root.parent),
        transform_tables=("sample",),
    )

    connection = duckdb.connect(str(root / "nba.duckdb"))
    try:
        connection.execute("UPDATE sample SET label = 'changed'")
    finally:
        connection.close()
    (root / "csv" / "sample.csv").write_text("id,label\n1,changed\n", encoding="utf-8")
    sqlite_connection = sqlite3.connect(root / "nba.sqlite")
    try:
        sqlite_connection.execute("UPDATE sample SET label = 'changed'")
        sqlite_connection.commit()
    finally:
        sqlite_connection.close()
    pq.write_table(
        pa.table({"id": [1], "label": ["changed"]}),
        root / "parquet" / "sample" / "sample.parquet",
    )

    _resources, _database, after = _inspect_publication_root(
        root.resolve(),
        _FILE_CONTRACT,
        **_scratch_kwargs(root.parent),
        transform_tables=("sample",),
    )

    assert before[0].schema_sha256 == after[0].schema_sha256
    assert before[0].content_sha256 != after[0].content_sha256


def test_publication_inventory_accepts_exact_expected_root_identity(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    observed = root.stat()

    resources, database, transform_outputs = _inspect_publication_root(
        root.resolve(),
        _FILE_CONTRACT,
        **_scratch_kwargs(root.parent),
        expected_root_identity=(observed.st_dev, observed.st_ino),
    )

    assert len(resources) == len(_FILE_CONTRACT.resources)
    assert database.duckdb_bytes == (root / "nba.duckdb").stat().st_size
    assert transform_outputs == ()


@pytest.mark.parametrize("invalid_identity", [True, 1.5, [1, 2], (-1, 2)])
def test_publication_inventory_rejects_invalid_expected_root_identity_before_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_identity: object,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)

    def unexpected_parity(*args: object, **kwargs: object) -> None:
        raise AssertionError("parity must not run for invalid root authority")

    monkeypatch.setattr(inventory_module, "_validate_format_parity", unexpected_parity)

    with pytest.raises(ValueError, match="expected root identity is invalid"):
        _inspect_publication_root(
            root.resolve(),
            _FILE_CONTRACT,
            **_scratch_kwargs(root.parent),
            expected_root_identity=cast("tuple[int, int]", invalid_identity),
        )

    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_publication_inventory_rejects_foreign_root_before_parity_or_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    observed = root.stat()

    def unexpected_parity(*args: object, **kwargs: object) -> None:
        raise AssertionError("parity must not run for foreign root authority")

    monkeypatch.setattr(inventory_module, "_validate_format_parity", unexpected_parity)

    with pytest.raises(ValueError, match="root differs from expected authority"):
        _inspect_publication_root(
            root.resolve(),
            _FILE_CONTRACT,
            **_scratch_kwargs(root.parent),
            expected_root_identity=(observed.st_dev, observed.st_ino + 1),
        )

    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_default_scratch_parent_is_used_and_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    resources, _database, _transforms = _inspect_publication_root(
        root.resolve(),
        _FILE_CONTRACT,
        **_scratch_kwargs(tmp_path),
    )

    assert len(resources) == len(_FILE_CONTRACT.resources)
    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_partition_directory_preserves_kaggle_fingerprint_domain(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_directory_tree(root)

    resources, _database, _transforms = _inspect(root, _DIRECTORY_CONTRACT)

    resource = next(item for item in resources if item.resource_id == "parquet/sample")
    parquet_path = root / "parquet" / "sample" / "season_year=2025-26" / "part0.parquet"
    parquet_bytes = parquet_path.read_bytes()
    children = [
        {
            "path": "season_year=2025-26/part0.parquet",
            "bytes": len(parquet_bytes),
            "sha256": hashlib.sha256(parquet_bytes).hexdigest(),
        }
    ]
    expected = hashlib.sha256(
        json.dumps(children, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert resource.kind == "directory"
    assert resource.bytes == len(parquet_bytes)
    assert resource.sha256 == expected


def test_production_contract_maps_all_dynamic_data_resources_and_tables() -> None:
    complete = expected_full_publication_resource_contract()
    contract = _production_data_contract()

    assert len(contract.resources) == 2 + len(contract.tables) * 2
    assert len(complete) == len(contract.resources) + 2
    assert set(dict(contract.resources)) == set(complete) - {
        "assured-artifact-manifest.json",
        "terminal-assurance-report.json",
    }
    for table in contract.tables:
        assert dict(contract.resources)[f"csv/{table}.csv"] == "file"
        parquet_file = f"parquet/{table}/{table}.parquet"
        parquet_directory = f"parquet/{table}"
        assert (
            dict(contract.resources).get(parquet_directory) == "directory"
            if table in contract.partitioned_tables
            else dict(contract.resources).get(parquet_file) == "file"
        )


def _raw_publication_contract(table_names: set[str]) -> dict[str, str]:
    contract = {"nba.duckdb": "file", "nba.sqlite": "file"}
    for table_name in table_names:
        contract[f"csv/{table_name}.csv"] = "file"
        contract[f"parquet/{table_name}/{table_name}.parquet"] = "file"
    return contract


def test_data_contract_requires_exact_registered_raw_four_plus_w2_six() -> None:
    raw_names = {entry.table_name for entry in raw_request_authority_publication_tables()}
    w2_names = {entry.table_name for entry in w2_public_value_authority_publication_tables()}
    exact_names = raw_names | w2_names

    accepted = _DataContract.from_mapping(_raw_publication_contract(exact_names))
    assert set(accepted.tables) == exact_names

    with pytest.raises(ValueError, match="exact-four/exact-six"):
        _DataContract.from_mapping(_raw_publication_contract(exact_names - {next(iter(w2_names))}))
    with pytest.raises(ValueError, match="exact-four/exact-six"):
        _DataContract.from_mapping(
            _raw_publication_contract(exact_names | {"raw_nba_api_w2_shadow"})
        )


def _write_exact_raw_schema_database(
    path: Path,
    *,
    reverse_w2_table: str | None = None,
) -> tuple[str, ...]:
    raw_entries = raw_request_authority_publication_tables()
    w2_entries = w2_public_value_authority_publication_tables()
    connection = duckdb.connect(str(path))
    try:
        for entry in (*raw_entries, *w2_entries):
            columns = (
                tuple(entry.schema_type.to_schema().columns)
                if not hasattr(entry, "ordered_columns")
                else entry.ordered_columns
            )
            if entry.table_name == reverse_w2_table:
                columns = tuple(reversed(columns))
            definitions = ", ".join(f'"{column}" VARCHAR' for column in columns)
            connection.execute(f'CREATE TABLE "{entry.table_name}" ({definitions})')
    finally:
        connection.close()
    return tuple(sorted(entry.table_name for entry in (*raw_entries, *w2_entries)))


def _raw_database_snapshot(path: Path) -> tuple[_DatabaseSnapshot, int]:
    descriptor = os.open(path, os.O_RDONLY)
    payload = path.read_bytes()
    return (
        _DatabaseSnapshot(
            path=path,
            descriptor=descriptor,
            identity=_identity(os.fstat(descriptor)),
            bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        ),
        descriptor,
    )


def test_duckdb_inventory_requires_w2_ordered_schema_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "nba.duckdb"
    expected_tables = _write_exact_raw_schema_database(database)
    replay_calls: list[bool] = []

    def verified_replay(_connection: object, *, require_w2: bool) -> object:
        replay_calls.append(require_w2)
        return object()

    monkeypatch.setattr(
        w2_assurance_module,
        "verify_w2_database_authority",
        verified_replay,
    )
    snapshot, descriptor = _raw_database_snapshot(database)
    try:
        rows, columns, transforms = _duckdb_tables(snapshot, expected_tables)
    finally:
        os.close(descriptor)

    assert set(rows) == set(expected_tables)
    assert transforms == ()
    assert replay_calls == [True]
    for entry in w2_public_value_authority_publication_tables():
        assert columns[entry.table_name] == entry.ordered_columns


def test_duckdb_inventory_rejects_consistent_w2_schema_or_value_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_database = tmp_path / "schema.duckdb"
    w2_table = w2_public_value_authority_publication_tables()[0].table_name
    expected_tables = _write_exact_raw_schema_database(
        schema_database,
        reverse_w2_table=w2_table,
    )
    snapshot, descriptor = _raw_database_snapshot(schema_database)
    try:
        with pytest.raises(ValueError, match="W2 ordered schema differs"):
            _duckdb_tables(snapshot, expected_tables)
    finally:
        os.close(descriptor)

    value_database = tmp_path / "value.duckdb"
    expected_tables = _write_exact_raw_schema_database(value_database)

    def rejected_replay(_connection: object, *, require_w2: bool) -> object:
        assert require_w2 is True
        raise ValueError("durable value drift")

    monkeypatch.setattr(
        w2_assurance_module,
        "verify_w2_database_authority",
        rejected_replay,
    )
    snapshot, descriptor = _raw_database_snapshot(value_database)
    try:
        with pytest.raises(ValueError, match="values failed exact durable authority replay"):
            _duckdb_tables(snapshot, expected_tables)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing_files"),
        ("unexpected", "unexpected_files"),
        ("hidden", "hidden path"),
        ("kind", "wrong_kind"),
        ("symlink", "symlinks"),
    ],
)
def test_tree_contract_rejects_path_and_kind_attacks(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    csv_path = root / "csv" / "sample.csv"
    if mutation == "missing":
        csv_path.unlink()
    elif mutation == "unexpected":
        (root / "extra.txt").write_text("unexpected", encoding="utf-8")
    elif mutation == "hidden":
        (root / ".hidden").write_text("hidden", encoding="utf-8")
    elif mutation == "kind":
        parquet_path = root / "parquet" / "sample" / "sample.parquet"
        parquet_path.unlink()
        parquet_path.mkdir()
    else:
        csv_path.unlink()
        csv_path.symlink_to(tmp_path / "outside.csv")

    with pytest.raises(ValueError, match=message):
        _inspect(root)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_tree_contract_rejects_special_files(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    csv_path = root / "csv" / "sample.csv"
    csv_path.unlink()
    os.mkfifo(csv_path)

    with pytest.raises(ValueError, match="special entry"):
        _inspect(root)


def test_tree_contract_rejects_empty_partition_resource(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_directory_tree(root)
    parquet_file = root / "parquet" / "sample" / "season_year=2025-26" / "part0.parquet"
    parquet_file.unlink()

    with pytest.raises(ValueError, match="directory resource is empty"):
        _inspect(root, _DIRECTORY_CONTRACT)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("label,id\nalpha,1\n", "ordered-schema parity failed"),
        ("id,label\n1,alpha\n2,beta\n", "row-count parity failed"),
    ],
)
def test_format_parity_rejects_schema_and_row_count_differences(
    tmp_path: Path,
    contents: str,
    message: str,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    (root / "csv" / "sample.csv").write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        _inspect(root)


def test_authoritative_value_parity_accepts_exact_advanced_logical_values(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    _typed_authoritative_tree(root)

    resources, database, transforms = _inspect(root)

    assert len(resources) == len(_FILE_CONTRACT.resources)
    assert database.duckdb_bytes > 0
    assert transforms == ()


def test_authoritative_value_parity_rejects_same_schema_and_count_value_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    pq.write_table(
        pa.table({"id": pa.array([1], type=pa.int64()), "label": ["beta"]}),
        root / "parquet" / "sample" / "sample.parquet",
    )

    with pytest.raises(ValueError, match="row-multiset value parity failed"):
        _inspect(root)


def test_authoritative_value_parity_preserves_duplicate_multiplicity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    root.mkdir()
    (root / "csv").mkdir()
    (root / "parquet" / "sample").mkdir(parents=True)
    _write_databases(
        root,
        columns=("id", "label"),
        rows=[(1, "same"), (1, "same"), (2, "other")],
    )
    (root / "csv" / "sample.csv").write_text(
        "id,label\n1,csv\n2,csv\n3,csv\n",
        encoding="utf-8",
    )
    pq.write_table(
        pa.table(
            {
                "id": pa.array([1, 2, 2], type=pa.int64()),
                "label": ["same", "other", "other"],
            }
        ),
        root / "parquet" / "sample" / "sample.parquet",
    )

    with pytest.raises(ValueError, match="row-multiset value parity failed"):
        _inspect(root)


def test_authoritative_value_parity_internal_aliases_cannot_shadow_provider_columns(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    root.mkdir()
    (root / "csv").mkdir()
    (root / "parquet" / "sample").mkdir(parents=True)
    columns = ("id", "__nbadb_delta", "__nbadb_balance")
    _write_databases(
        root,
        columns=columns,
        rows=[
            (1, "provider-delta", "provider-balance"),
            (1, "provider-delta", "provider-balance"),
            (2, "other-delta", "other-balance"),
        ],
    )
    (root / "csv" / "sample.csv").write_text(
        "id,__nbadb_delta,__nbadb_balance\n"
        "1,provider-delta,provider-balance\n"
        "1,provider-delta,provider-balance\n"
        "2,other-delta,other-balance\n",
        encoding="utf-8",
    )
    parquet_path = root / "parquet" / "sample" / "sample.parquet"
    pq.write_table(
        pa.table(
            {
                "id": pa.array([2, 1, 1], type=pa.int64()),
                "__nbadb_delta": ["other-delta", "provider-delta", "provider-delta"],
                "__nbadb_balance": [
                    "other-balance",
                    "provider-balance",
                    "provider-balance",
                ],
            }
        ),
        parquet_path,
    )

    _inspect(root)

    pq.write_table(
        pa.table(
            {
                "id": pa.array([1, 2, 2], type=pa.int64()),
                "__nbadb_delta": ["provider-delta", "other-delta", "other-delta"],
                "__nbadb_balance": [
                    "provider-balance",
                    "other-balance",
                    "other-balance",
                ],
            }
        ),
        parquet_path,
    )
    with pytest.raises(ValueError, match="row-multiset value parity failed"):
        _inspect(root)


def test_authoritative_value_parity_distinguishes_null_from_empty_string(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    root.mkdir()
    (root / "csv").mkdir()
    (root / "parquet" / "sample").mkdir(parents=True)
    _write_databases(root, columns=("id", "label"), rows=[(1, None)])
    (root / "csv" / "sample.csv").write_text("id,label\n1,\n", encoding="utf-8")
    pq.write_table(
        pa.table(
            {
                "id": pa.array([1], type=pa.int64()),
                "label": pa.array([""], type=pa.string()),
            }
        ),
        root / "parquet" / "sample" / "sample.parquet",
    )

    with pytest.raises(ValueError, match="row-multiset value parity failed"):
        _inspect(root)


def test_sqlite_and_csv_remain_explicit_convenience_projections(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    sqlite_connection = sqlite3.connect(root / "nba.sqlite")
    try:
        sqlite_connection.execute("UPDATE sample SET label = 'sqlite-convenience'")
        sqlite_connection.commit()
    finally:
        sqlite_connection.close()
    (root / "csv" / "sample.csv").write_text(
        "id,label\n1,csv-convenience\n",
        encoding="utf-8",
    )

    resources, _database, _transforms = _inspect(root)

    assert len(resources) == len(_FILE_CONTRACT.resources)


def test_authoritative_partition_value_is_compared_to_duckdb(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_directory_tree(root)
    original = root / "parquet" / "sample" / "season_year=2025-26"
    original.rename(root / "parquet" / "sample" / "season_year=2024-25")

    with pytest.raises(ValueError, match="row-multiset value parity failed"):
        _inspect(root, _DIRECTORY_CONTRACT)


def test_file_tamper_after_parity_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    original = inventory_module._validate_format_parity

    def tampering_validator(*args, **kwargs) -> None:
        original(*args, **kwargs)
        (root / "csv" / "sample.csv").write_text(
            "id,label\n1,tampered\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(inventory_module, "_validate_format_parity", tampering_validator)

    with pytest.raises(ValueError, match="changed after inventory"):
        _inspect(root)


def test_database_path_swap_during_engine_read_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public"
    replacement_root = tmp_path / "replacement"
    _truthful_file_tree(root)
    _truthful_file_tree(replacement_root, value="foreign")
    replacement = replacement_root / "nba.duckdb"
    original = inventory_module._duckdb_tables

    def swapping_reader(snapshot, expected_tables: tuple[str, ...], **kwargs):
        result = original(snapshot, expected_tables, **kwargs)
        os.replace(replacement, root / "nba.duckdb")
        return result

    monkeypatch.setattr(inventory_module, "_duckdb_tables", swapping_reader)

    with pytest.raises(ValueError, match="changed after inventory"):
        _inspect(root)


def test_private_snapshot_swap_and_restore_during_engine_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public"
    replacement_root = tmp_path / "replacement"
    _truthful_file_tree(root)
    _truthful_file_tree(replacement_root, value="foreign")
    replacement = replacement_root / "nba.duckdb"
    original = inventory_module._duckdb_tables

    def swapping_reader(snapshot, expected_tables: tuple[str, ...], **kwargs):
        path = snapshot.path
        held = path.with_suffix(".held")
        path.rename(held)
        shutil.copyfile(replacement, path)
        try:
            return original(snapshot, expected_tables, **kwargs)
        finally:
            path.unlink()
            held.rename(path)

    monkeypatch.setattr(inventory_module, "_duckdb_tables", swapping_reader)

    with pytest.raises(ValueError, match="snapshot"):
        _inspect(root)


@pytest.mark.parametrize("engine", ["duckdb", "sqlite"])
def test_engine_open_is_bound_to_exact_snapshot_during_scratch_ancestor_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: str,
) -> None:
    anchor = tmp_path / "anchor"
    public = anchor / "public"
    scratch = anchor / "scratch"
    foreign = tmp_path / "foreign"
    held = tmp_path / "held"
    alternate = tmp_path / "alternate"
    anchor.mkdir()
    _truthful_file_tree(public)
    scratch.mkdir(mode=0o700)
    _truthful_file_tree(foreign, value="foreign")
    if engine == "sqlite":
        connection = sqlite3.connect(foreign / "nba.sqlite")
        try:
            connection.execute("INSERT INTO sample VALUES (2, 'foreign-extra')")
            connection.commit()
        finally:
            connection.close()

    original = duckdb.connect if engine == "duckdb" else sqlite3.connect
    fired = False

    def swapping_connect(database, *args, **kwargs):
        nonlocal fired
        raw = os.fspath(database)
        raw_path = raw[5:].split("?", 1)[0] if raw.startswith("file:") else raw
        path = Path(raw_path)
        engine_open = (
            path.name == "nba.duckdb"
            and path.parent.name.startswith("nbadb-successor-publication-")
            if engine == "duckdb"
            else raw == ":memory:"
        )
        if not fired and engine_open:
            fired = True
            if engine == "sqlite":
                path = next(scratch.glob("nbadb-successor-publication-*/nba.sqlite"))
            relative = path.relative_to(anchor)
            replacement = alternate / relative
            replacement.parent.mkdir(parents=True)
            os.link(foreign / f"nba.{engine}", replacement)
            anchor.rename(held)
            alternate.rename(anchor)
            try:
                connection = original(database, *args, **kwargs)
            finally:
                anchor.rename(alternate)
                held.rename(anchor)
            return connection
        return original(database, *args, **kwargs)

    target: tuple[object, str] = (duckdb, "connect") if engine == "duckdb" else (sqlite3, "connect")
    monkeypatch.setattr(*target, swapping_connect)

    def inspect_publication():
        return _inspect_publication_root(
            public.resolve(),
            _FILE_CONTRACT,
            **_scratch_kwargs(scratch),
        )

    if engine == "duckdb":
        with pytest.raises(ValueError, match="exact successor snapshot"):
            inspect_publication()
    else:
        resources, _database, _transforms = inspect_publication()
        assert fired
        assert len(resources) == len(_FILE_CONTRACT.resources)


def test_root_swap_and_swap_back_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public"
    foreign = tmp_path / "foreign"
    held = tmp_path / "held"
    _truthful_file_tree(root)
    _truthful_file_tree(foreign, value="foreign")
    original = inventory_module._validate_format_parity

    def swapping_validator(*args, **kwargs) -> None:
        root.rename(held)
        foreign.rename(root)
        try:
            original(*args, **kwargs)
        finally:
            root.rename(foreign)
            held.rename(root)

    monkeypatch.setattr(inventory_module, "_validate_format_parity", swapping_validator)

    with pytest.raises(ValueError, match="root changed|pathname changed"):
        _inspect(root)


def test_publication_inventory_does_not_import_kaggle_client() -> None:
    source = inspect.getsource(inventory_module)

    assert "KaggleClient" not in source
    assert "nbadb.kaggle.client" not in source


@pytest.mark.parametrize(
    "controls",
    [
        ("terminal-assurance-report.json",),
        ("assured-artifact-manifest.json",),
        ("assured-artifact-manifest.json", "terminal-assurance-report.json"),
    ],
)
def test_canonical_control_files_are_excluded_from_data_inventory(
    tmp_path: Path,
    controls: tuple[str, ...],
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    for control in controls:
        (root / control).write_text("{}\n", encoding="utf-8")

    resources, _database, _transforms = _inspect(root)

    assert tuple(resource.resource_id for resource in resources) == tuple(
        path for path, _kind in _FILE_CONTRACT.resources
    )


@pytest.mark.parametrize(
    "attack",
    [
        "symlink",
        pytest.param(
            "fifo",
            marks=pytest.mark.skipif(
                not hasattr(os, "mkfifo"),
                reason="FIFO creation is unavailable",
            ),
        ),
    ],
)
def test_canonical_control_files_must_be_regular_non_symlinks(
    tmp_path: Path,
    attack: str,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    control = root / "terminal-assurance-report.json"
    if attack == "symlink":
        target = tmp_path / "outside.json"
        target.write_text("{}\n", encoding="utf-8")
        control.symlink_to(target)
        message = "symlinks"
    else:
        os.mkfifo(control)
        message = "special entry"

    with pytest.raises(ValueError, match=message):
        _inspect(root)


def test_relative_public_root_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="must be absolute"):
        _inspect_publication_root(
            Path("public"),
            _FILE_CONTRACT,
            **_scratch_kwargs(tmp_path),
        )


def test_unexpected_nested_partition_layout_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_directory_tree(root)
    original = root / "parquet" / "sample" / "season_year=2025-26"
    unexpected = root / "parquet" / "sample" / "not-a-partition"
    original.rename(unexpected)

    with pytest.raises(ValueError, match="not key=value"):
        _inspect(root, _DIRECTORY_CONTRACT)


def test_empty_nested_partition_directory_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_directory_tree(root)
    (root / "parquet" / "sample" / "season_year=2024-25").mkdir()

    with pytest.raises(ValueError, match="empty directory"):
        _inspect(root, _DIRECTORY_CONTRACT)


def test_scratch_cleanup_survives_validation_failure(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    (root / "csv" / "sample.csv").write_text(
        "id,label\n1,alpha\n2,beta\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="row-count parity failed"):
        _inspect(root)

    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_contract_rejects_unpaired_or_malformed_resources() -> None:
    with pytest.raises(ValueError, match="CSV and Parquet table contracts differ"):
        _DataContract.from_mapping(
            {
                "nba.duckdb": "file",
                "nba.sqlite": "file",
                "csv/sample.csv": "file",
            }
        )
    with pytest.raises(ValueError, match="unexpected successor publication contract path"):
        _DataContract.from_mapping(
            {
                "nba.duckdb": "file",
                "nba.sqlite": "file",
                "csv/sample.csv": "file",
                "parquet/sample/sample.parquet": "file",
                "notes.txt": "file",
            }
        )


def test_directory_resource_rejects_non_parquet_and_symlink_descendants(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_directory_tree(root)
    partition = root / "parquet" / "sample" / "season_year=2025-26"
    (partition / "notes.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ValueError, match="non-Parquet file"):
        _inspect(root, _DIRECTORY_CONTRACT)

    (partition / "notes.txt").unlink()
    target = tmp_path / "outside.parquet"
    shutil.copyfile(partition / "part0.parquet", target)
    (partition / "linked.parquet").symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        _inspect(root, _DIRECTORY_CONTRACT)


def test_database_snapshot_caps_accept_exact_sizes_and_reject_each_over_cap(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    duckdb_bytes = (root / "nba.duckdb").stat().st_size
    sqlite_bytes = (root / "nba.sqlite").stat().st_size
    exact = _scratch_kwargs(tmp_path)
    exact["inventory_duckdb_snapshot_max_bytes"] = duckdb_bytes
    exact["inventory_sqlite_snapshot_max_bytes"] = sqlite_bytes

    resources, database, transforms = _inspect_publication_root(
        root.resolve(),
        _FILE_CONTRACT,
        **exact,
    )

    assert len(resources) == len(_FILE_CONTRACT.resources)
    assert database.duckdb_bytes == duckdb_bytes
    assert database.sqlite_bytes == sqlite_bytes
    assert transforms == ()
    for field, expected_name in (
        ("inventory_duckdb_snapshot_max_bytes", "nba.duckdb"),
        ("inventory_sqlite_snapshot_max_bytes", "nba.sqlite"),
    ):
        over_cap = dict(exact)
        over_cap[field] = int(over_cap[field]) - 1
        with pytest.raises(ValueError, match=rf"{expected_name} exceeds .* byte ceiling"):
            _inspect_publication_root(
                root.resolve(),
                _FILE_CONTRACT,
                **over_cap,
            )
        assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_database_snapshot_short_writes_complete_within_exact_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    original = inventory_module._write_snapshot_chunk

    def short_write(descriptor: int, payload: memoryview) -> int:
        return original(descriptor, payload[: max(1, len(payload) // 2)])

    monkeypatch.setattr(inventory_module, "_write_snapshot_chunk", short_write)

    resources, _database, _transforms = _inspect(root)

    assert len(resources) == len(_FILE_CONTRACT.resources)
    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_database_snapshot_no_progress_cleans_and_allows_reentry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    original = inventory_module._write_snapshot_chunk
    monkeypatch.setattr(
        inventory_module,
        "_write_snapshot_chunk",
        lambda _descriptor, _payload: 0,
    )

    with pytest.raises(OSError, match="made no progress"):
        _inspect(root)
    assert not list(tmp_path.glob("nbadb-successor-publication-*"))

    monkeypatch.setattr(inventory_module, "_write_snapshot_chunk", original)
    resources, _database, _transforms = _inspect(root)
    assert len(resources) == len(_FILE_CONTRACT.resources)
    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_scratch_root_substitution_never_receives_snapshot_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    scratch = tmp_path / "scratch"
    held = tmp_path / "scratch-held"
    _truthful_file_tree(public)
    scratch.mkdir(mode=0o700)
    original = inventory_module._reserve_private_directory
    fired = False

    def swap_root(*args, **kwargs):
        nonlocal fired
        if not fired:
            fired = True
            scratch.rename(held)
            scratch.mkdir(mode=0o700)
        return original(*args, **kwargs)

    monkeypatch.setattr(inventory_module, "_reserve_private_directory", swap_root)
    try:
        with pytest.raises(ValueError, match="scratch root changed"):
            _inspect_publication_root(
                public.resolve(),
                _FILE_CONTRACT,
                **_scratch_kwargs(scratch),
            )
        assert fired
        assert list(scratch.iterdir()) == []
        assert list(held.iterdir()) == []
    finally:
        if fired:
            scratch.rmdir()
            held.rename(scratch)


def test_database_snapshot_cleanup_never_removes_a_post_check_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    _truthful_file_tree(public)
    held = tmp_path / "nbadb-successor-publication-held"
    original = inventory_module._require_private_directory_name
    substituted_name: str | None = None

    def substitute_after_cleanup_admission(
        authority: inventory_module._ScratchAuthority,
        name: str,
        descriptor: int,
        expected: os.stat_result,
        *,
        stage: str,
        require_root_path: bool = True,
    ) -> None:
        nonlocal substituted_name
        original(
            authority,
            name,
            descriptor,
            expected,
            stage=stage,
            require_root_path=require_root_path,
        )
        if substituted_name is None and stage == "nba.duckdb cleanup admission":
            substituted_name = name
            (tmp_path / name).rename(held)
            (tmp_path / name).mkdir(mode=0o700)

    monkeypatch.setattr(
        inventory_module,
        "_require_private_directory_name",
        substitute_after_cleanup_admission,
    )

    with pytest.raises(ValueError, match="before cleanup removal"):
        _inspect(public)

    assert substituted_name is not None
    replacement = tmp_path / substituted_name
    assert replacement.is_dir()
    assert list(replacement.iterdir()) == []
    assert held.is_dir()
    assert list(held.iterdir()) == []

    replacement.rmdir()
    held.rmdir()
    resources, _database, _transforms = _inspect(public)
    assert len(resources) == len(_FILE_CONTRACT.resources)
    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_reserve_private_directory_validation_failure_removes_owned_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    parent = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY)
    try:
        observed = os.fstat(parent)
        authority = inventory_module._ScratchAuthority(
            path=scratch.resolve(),
            descriptor=parent,
            identity=(observed.st_dev, observed.st_ino),
            opened_identity=inventory_module._directory_authority_identity(observed),
        )
        real_geteuid = os.geteuid
        monkeypatch.setattr(inventory_module.os, "geteuid", lambda: real_geteuid() + 1)
        with pytest.raises(ValueError, match="must be owner-only"):
            inventory_module._reserve_private_directory(
                authority,
                prefix="nbadb-successor-publication-",
            )
        assert list(scratch.iterdir()) == []
    finally:
        os.close(parent)


def test_reserve_private_directory_does_not_remove_a_name_substituted_after_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    held = scratch / "held"
    parent = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY)
    original_stat = inventory_module.os.stat
    substituted: str | None = None

    def swap_after_name_proof(path: object, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal substituted
        result = original_stat(path, *args, **kwargs)
        if (
            substituted is None
            and kwargs.get("dir_fd") == parent
            and isinstance(path, str)
            and path.startswith("nbadb-successor-publication-")
        ):
            substituted = path
            os.rename(path, "held", src_dir_fd=parent, dst_dir_fd=parent)
            os.mkdir(path, 0o700, dir_fd=parent)
            return original_stat(path, *args, **kwargs)
        return result

    try:
        observed = os.fstat(parent)
        authority = inventory_module._ScratchAuthority(
            path=scratch.resolve(),
            descriptor=parent,
            identity=(observed.st_dev, observed.st_ino),
            opened_identity=inventory_module._directory_authority_identity(observed),
        )
        monkeypatch.setattr(inventory_module.os, "stat", swap_after_name_proof)
        with pytest.raises(ValueError, match="changed while reserving"):
            inventory_module._reserve_private_directory(
                authority,
                prefix="nbadb-successor-publication-",
            )
        assert substituted is not None
        replacement = scratch / substituted
        assert replacement.is_dir()
        assert list(replacement.iterdir()) == []
        assert held.is_dir()
        assert list(held.iterdir()) == []
        assert replacement.stat().st_ino != held.stat().st_ino
    finally:
        os.close(parent)


def test_require_formats_rejects_missing_parquet_root(tmp_path: Path) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    shutil.rmtree(root / "parquet")

    with pytest.raises(ValueError, match="missing required publication format"):
        require_successor_publication_formats(root)


def test_publication_freshness_requires_last_load_equal_to_as_of_season(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    as_of_utc = "2026-08-13T00:00:00Z"
    expected = successor_publication_freshness_season(as_of_utc)
    assert expected == "2025-26"

    connection = duckdb.connect(str(root / "nba.duckdb"))
    try:
        connection.execute(
            """
            CREATE TABLE _pipeline_watermarks (
                table_name VARCHAR NOT NULL,
                watermark_type VARCHAR NOT NULL,
                watermark_value VARCHAR,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count_at_watermark BIGINT,
                PRIMARY KEY (table_name, watermark_type)
            )
            """
        )
        connection.execute(
            "INSERT INTO _pipeline_watermarks "
            "(table_name, watermark_type, watermark_value, row_count_at_watermark) "
            "VALUES ('sample', 'last_load', '2024-25', 1)"
        )
    finally:
        connection.close()

    with pytest.raises(ValueError, match="publication freshness failed"):
        validate_successor_publication_freshness(
            root,
            as_of_utc=as_of_utc,
            expected_tables=("sample",),
        )

    connection = duckdb.connect(str(root / "nba.duckdb"))
    try:
        connection.execute(
            "UPDATE _pipeline_watermarks SET watermark_value = ? "
            "WHERE table_name = 'sample' AND watermark_type = 'last_load'",
            [expected],
        )
    finally:
        connection.close()

    assert (
        validate_successor_publication_freshness(
            root,
            as_of_utc=as_of_utc,
            expected_tables=("sample",),
        )
        == expected
    )


def _write_sample_watermarks(root: Path, *, season: str) -> None:
    connection = duckdb.connect(str(root / "nba.duckdb"))
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS _pipeline_watermarks (
                table_name VARCHAR NOT NULL,
                watermark_type VARCHAR NOT NULL,
                watermark_value VARCHAR,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count_at_watermark BIGINT,
                PRIMARY KEY (table_name, watermark_type)
            )
            """
        )
        connection.execute("DELETE FROM _pipeline_watermarks")
        connection.execute(
            "INSERT INTO _pipeline_watermarks "
            "(table_name, watermark_type, watermark_value, row_count_at_watermark) "
            "VALUES ('sample', 'last_load', ?, 1)",
            [season],
        )
    finally:
        connection.close()


def test_inspect_successor_candidate_publication_accepts_matching_four_format_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "public"
    _truthful_file_tree(root)
    _write_sample_watermarks(root, season="2025-26")

    tables = inspect_successor_candidate_publication(
        root.resolve(),
        **_scratch_kwargs(tmp_path),
    )

    assert tables == ("sample",)


def test_inspect_successor_candidate_publication_rejects_schema_and_row_count_mismatch(
    tmp_path: Path,
) -> None:
    schema_root = tmp_path / "schema"
    _truthful_file_tree(schema_root)
    (schema_root / "csv" / "sample.csv").write_text("label,id\nalpha,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ordered-schema parity failed"):
        inspect_successor_candidate_publication(
            schema_root.resolve(),
            **_scratch_kwargs(tmp_path),
        )

    rows_root = tmp_path / "rows"
    _truthful_file_tree(rows_root)
    (rows_root / "csv" / "sample.csv").write_text(
        "id,label\n1,alpha\n2,beta\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="row-count parity failed"):
        inspect_successor_candidate_publication(
            rows_root.resolve(),
            **_scratch_kwargs(tmp_path),
        )


def test_database_snapshot_cleanup_never_removes_a_post_final_proof_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    _truthful_file_tree(public)
    held = tmp_path / "nbadb-successor-publication-held"
    original = inventory_module._require_private_directory_name
    substituted_name: str | None = None

    def substitute_after_final_proof(
        authority: inventory_module._ScratchAuthority,
        name: str,
        descriptor: int,
        expected: os.stat_result,
        *,
        stage: str,
        require_root_path: bool = True,
    ) -> None:
        nonlocal substituted_name
        original(
            authority,
            name,
            descriptor,
            expected,
            stage=stage,
            require_root_path=require_root_path,
        )
        if substituted_name is None and stage == "nba.duckdb before cleanup removal":
            substituted_name = name
            (tmp_path / name).rename(held)
            (tmp_path / name).mkdir(mode=0o700)

    monkeypatch.setattr(
        inventory_module,
        "_require_private_directory_name",
        substitute_after_final_proof,
    )

    with pytest.raises(ValueError, match="replaced at quarantine"):
        _inspect(public)

    assert substituted_name is not None
    replacement = tmp_path / substituted_name
    assert replacement.is_dir()
    assert list(replacement.iterdir()) == []
    assert held.is_dir()
    assert list(held.iterdir()) == []

    replacement.rmdir()
    held.rmdir()
    resources, _database, _transforms = _inspect(public)
    assert len(resources) == len(_FILE_CONTRACT.resources)
    assert not list(tmp_path.glob("nbadb-successor-publication-*"))


def test_database_snapshot_growth_during_copy_cleans_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    _truthful_file_tree(public)
    original_write = inventory_module._write_snapshot_chunk
    grew = False

    def grow_source(target: int, view: memoryview) -> int:
        nonlocal grew
        if not grew:
            grew = True
            with (public / "nba.duckdb").open("ab") as handle:
                handle.write(b"XXXXXX")
        return original_write(target, view)

    monkeypatch.setattr(inventory_module, "_write_snapshot_chunk", grow_source)

    with pytest.raises(ValueError, match="changed while snapshotting|grew|differs from source"):
        _inspect(public)

    assert grew
    assert not list(tmp_path.glob("nbadb-successor-publication-*"))
