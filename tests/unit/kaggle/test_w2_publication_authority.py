"""Focused metadata and resource closure for the separate W2 public category."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.kaggle.metadata import (
    TABLE_CATEGORIES,
    _extract_column_schema,
    _resolve_export_inventory,
    expected_full_publication_resource_contract,
)
from nbadb.orchestrate.raw_publication_inventory import (
    PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES,
    RAW_REQUEST_AUTHORITY_CATEGORY,
    raw_request_authority_publication_tables,
)
from nbadb.orchestrate.successor_publication_inventory import _production_data_contract
from nbadb.orchestrate.w2_publication_inventory import (
    W2_PUBLIC_VALUE_AUTHORITY_CATEGORY,
    w2_public_value_authority_publication_tables,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_relation_shell(root: Path, table_name: str) -> None:
    fields = _extract_column_schema(table_name)
    assert fields is not None
    header = ",".join(str(field["name"]) for field in fields)
    csv_dir = root / "csv"
    parquet_dir = root / "parquet" / table_name
    csv_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    (csv_dir / f"{table_name}.csv").write_text(f"{header}\n", encoding="utf-8")
    (parquet_dir / f"{table_name}.parquet").write_bytes(b"parquet")


def test_w2_exact_six_is_present_on_every_full_publication_contract_surface() -> None:
    raw_entries = raw_request_authority_publication_tables()
    w2_entries = w2_public_value_authority_publication_tables()
    resource_contract = expected_full_publication_resource_contract()
    successor_contract = _production_data_contract()

    # The exact-four are private-only: their public projection is empty and
    # none of the four names may appear on any public contract surface.
    assert raw_entries == ()
    assert len(w2_entries) == 6
    assert TABLE_CATEGORIES[RAW_REQUEST_AUTHORITY_CATEGORY] == []
    assert TABLE_CATEGORIES[W2_PUBLIC_VALUE_AUTHORITY_CATEGORY] == [
        entry.table_name for entry in w2_entries
    ]
    successor_resources = dict(successor_contract.resources)
    for table_name in PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES:
        assert f"csv/{table_name}.csv" not in resource_contract
        assert f"parquet/{table_name}/{table_name}.parquet" not in resource_contract
        assert f"csv/{table_name}.csv" not in successor_resources
        assert f"parquet/{table_name}/{table_name}.parquet" not in successor_resources
    for entry in w2_entries:
        assert entry.table_name in successor_contract.tables
        assert resource_contract[f"csv/{entry.table_name}.csv"] == "file"
        assert resource_contract[f"parquet/{entry.table_name}/{entry.table_name}.parquet"] == "file"
        assert successor_resources[f"csv/{entry.table_name}.csv"] == "file"
        assert (
            successor_resources[f"parquet/{entry.table_name}/{entry.table_name}.parquet"] == "file"
        )
        fields = _extract_column_schema(entry.table_name)
        assert fields is not None
        assert tuple(field["name"] for field in fields) == entry.ordered_columns


def test_metadata_rejects_raw_v2_exports_without_the_w2_exact_six(tmp_path: Path) -> None:
    # A partial W2 exact-six export must fail closed even though the exact-four
    # no longer participate in the public surface at all.
    partial_w2 = w2_public_value_authority_publication_tables()[:5]
    for entry in partial_w2:
        _write_relation_shell(tmp_path, entry.table_name)
    connection = duckdb.connect(str(tmp_path / "nba.duckdb"))
    try:
        for entry in partial_w2:
            connection.execute(f'CREATE TABLE "{entry.table_name}" (marker INTEGER)')
    finally:
        connection.close()

    with pytest.raises(ValueError, match="missing part of the exact-four/exact-six"):
        _resolve_export_inventory(tmp_path)


def test_metadata_rejects_unregistered_seventh_w2_raw_relation(tmp_path: Path) -> None:
    for entry in (
        *raw_request_authority_publication_tables(),
        *w2_public_value_authority_publication_tables(),
    ):
        _write_relation_shell(tmp_path, entry.table_name)
    shadow = "raw_nba_api_w2_shadow"
    (tmp_path / "csv" / f"{shadow}.csv").write_text("value\n", encoding="utf-8")
    shadow_parquet = tmp_path / "parquet" / shadow
    shadow_parquet.mkdir()
    (shadow_parquet / f"{shadow}.parquet").write_bytes(b"parquet")

    with pytest.raises(ValueError, match="non-canonical raw authority tables"):
        _resolve_export_inventory(tmp_path)
