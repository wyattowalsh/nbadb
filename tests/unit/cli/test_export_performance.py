from __future__ import annotations

import hashlib
import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import patch

import duckdb
import polars as pl
from typer.testing import CliRunner

from nbadb.cli.app import app
from nbadb.load.duckdb_loader import DuckDBLoader

if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_canonical_warehouse(path: Path, *, rows: int = 3) -> None:
    conn = duckdb.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE fact_export_probe AS
            SELECT
                i::BIGINT AS entity_id,
                CASE WHEN i = 1 THEN 'Jokić — 東京 🏀' ELSE 'row-' || i::VARCHAR END AS label,
                (i::DOUBLE / 8.0) AS metric,
                CASE WHEN i % 2 = 0 THEN NULL ELSE i::BIGINT END AS nullable_count
            FROM range(?) AS probe(i)
            """,
            [rows],
        )
        conn.execute(
            "CREATE TABLE dim_export_empty (entity_id BIGINT, label VARCHAR, metric DOUBLE)"
        )
        conn.execute("CHECKPOINT")
    finally:
        conn.close()


def _duckdb_snapshot(path: Path) -> tuple[list[tuple], list[tuple]]:
    conn = duckdb.connect(str(path), read_only=True)
    try:
        rows = conn.execute("SELECT * FROM fact_export_probe ORDER BY entity_id").fetchall()
        schema = conn.execute("DESCRIBE fact_export_probe").fetchall()
        return rows, schema
    finally:
        conn.close()


def test_duckdb_only_export_skips_dataframe_materialization_and_preserves_resource(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nba.duckdb"
    _create_canonical_warehouse(db_path, rows=250_000)
    before_digest = _sha256(db_path)
    before_snapshot = _duckdb_snapshot(db_path)

    with patch(
        "nbadb.load.multi.create_multi_loader",
        side_effect=AssertionError("DuckDB-only export must not construct a loader"),
    ) as loader_factory:
        result = runner.invoke(
            app,
            ["export", "--data-dir", str(tmp_path), "--format", "duckdb"],
        )

    assert result.exit_code == 0, result.output
    loader_factory.assert_not_called()
    assert "fact_export_probe: 250,000 rows" in result.output
    assert "formats: duckdb" in result.output
    assert _sha256(db_path) == before_digest
    assert _duckdb_snapshot(db_path) == before_snapshot


def test_export_rejects_an_empty_format_inventory_before_opening_duckdb(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nba.duckdb"
    _create_canonical_warehouse(db_path, rows=1)

    with patch("nbadb.cli.commands.export._build_settings") as build_settings:
        build_settings.return_value.formats = []
        result = runner.invoke(app, ["export", "--data-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "At least one export format" in result.output


def test_default_export_preserves_duckdb_and_projects_every_secondary_resource(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nba.duckdb"
    _create_canonical_warehouse(db_path)
    before_digest = _sha256(db_path)
    before_rows, before_schema = _duckdb_snapshot(db_path)

    with patch.object(
        DuckDBLoader,
        "load",
        side_effect=AssertionError("canonical DuckDB must not be rewritten"),
    ) as duckdb_load:
        result = runner.invoke(app, ["export", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    duckdb_load.assert_not_called()
    assert "Exported 2/2 tables" in result.output
    assert "sqlite, duckdb, csv, parquet" in result.output

    assert _sha256(db_path) == before_digest
    assert _duckdb_snapshot(db_path) == (before_rows, before_schema)

    csv_path = tmp_path / "csv" / "fact_export_probe.csv"
    parquet_path = tmp_path / "parquet" / "fact_export_probe" / "fact_export_probe.parquet"
    empty_csv_path = tmp_path / "csv" / "dim_export_empty.csv"
    empty_parquet_path = tmp_path / "parquet" / "dim_export_empty" / "dim_export_empty.parquet"
    assert csv_path.is_file()
    assert parquet_path.is_file()
    assert empty_csv_path.is_file()
    assert empty_parquet_path.is_file()

    expected = pl.DataFrame(
        before_rows,
        schema={
            "entity_id": pl.Int64,
            "label": pl.String,
            "metric": pl.Float64,
            "nullable_count": pl.Int64,
        },
        orient="row",
    )
    assert pl.read_csv(csv_path).equals(expected)
    assert pl.read_parquet(parquet_path).equals(expected)
    assert pl.read_csv(empty_csv_path).is_empty()
    assert pl.read_parquet(empty_parquet_path).is_empty()

    sqlite_path = tmp_path / "nba.sqlite"
    with sqlite3.connect(sqlite_path) as sqlite_conn:
        sqlite_rows = sqlite_conn.execute(
            "SELECT * FROM fact_export_probe ORDER BY entity_id"
        ).fetchall()
        empty_count = sqlite_conn.execute("SELECT COUNT(*) FROM dim_export_empty").fetchone()[0]
    assert sqlite_rows == before_rows
    assert empty_count == 0


def test_export_opens_canonical_duckdb_read_only_and_filters_only_duckdb_loader(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nba.duckdb"
    _create_canonical_warehouse(db_path, rows=1)
    original_connect = duckdb.connect

    with (
        patch("duckdb.connect", wraps=original_connect) as connect,
        patch("nbadb.load.multi.create_multi_loader") as loader_factory,
    ):
        result = runner.invoke(app, ["export", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert connect.call_args_list[0].kwargs == {"read_only": True}
    export_settings = loader_factory.call_args.args[0]
    assert export_settings.formats == ["sqlite", "csv", "parquet"]
    assert loader_factory.call_args.kwargs == {"strict": True}
    assert "formats: sqlite, duckdb, csv, parquet" in result.output
