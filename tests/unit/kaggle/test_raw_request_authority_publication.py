from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.kaggle.metadata import (
    CATEGORY_LABELS,
    TABLE_CATEGORIES,
    TABLE_DESCRIPTIONS,
    _build_resources,
    _extract_column_schema,
    _render_table_catalog,
    _render_what_you_get,
    _resolve_export_inventory,
    expected_full_publication_resource_contract,
)
from nbadb.orchestrate.raw_publication_inventory import (
    PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES,
    RAW_REQUEST_AUTHORITY_CATEGORY,
    raw_request_authority_private_tables,
    raw_request_authority_publication_tables,
)
from nbadb.orchestrate.w2_publication_inventory import (
    W2_PUBLIC_VALUE_AUTHORITY_CATEGORY,
    w2_public_value_authority_publication_tables,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_raw_authority_exports(root: Path) -> None:
    csv_dir = root / "csv"
    parquet_dir = root / "parquet"
    csv_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(root / "nba.duckdb"))
    try:
        entries = w2_public_value_authority_publication_tables()
        for entry in entries:
            fields = _extract_column_schema(entry.table_name)
            assert fields is not None
            header = ",".join(str(field["name"]) for field in fields)
            (csv_dir / f"{entry.table_name}.csv").write_text(
                f"{header}\n",
                encoding="utf-8",
            )
            table_dir = parquet_dir / entry.table_name
            table_dir.mkdir()
            (table_dir / f"{entry.table_name}.parquet").write_bytes(b"parquet")
            connection.execute(f'CREATE TABLE "{entry.table_name}" (marker INTEGER)')
    finally:
        connection.close()


def test_full_publication_contract_includes_every_fixed_raw_table_in_both_formats() -> None:
    contract = expected_full_publication_resource_contract()

    # The exact-four provider-body authority relations are private-only: they
    # must never appear on the public resource contract in either format.
    for table_name in PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES:
        assert f"csv/{table_name}.csv" not in contract
        assert f"parquet/{table_name}/{table_name}.parquet" not in contract
    for entry in w2_public_value_authority_publication_tables():
        assert contract[f"csv/{entry.table_name}.csv"] == "file"
        assert contract[f"parquet/{entry.table_name}/{entry.table_name}.parquet"] == "file"
    assert contract["nba.duckdb"] == contract["nba.sqlite"] == "file"


def test_raw_tables_have_public_category_descriptions_and_exact_schemas() -> None:
    # The public raw authority category is empty by design: every raw authority
    # table that remains public is classified under the W2 value authority.
    assert raw_request_authority_publication_tables() == ()
    assert TABLE_CATEGORIES[RAW_REQUEST_AUTHORITY_CATEGORY] == []
    assert CATEGORY_LABELS[RAW_REQUEST_AUTHORITY_CATEGORY] == "Raw Request Authority"
    for table_name in PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES:
        assert table_name not in TABLE_DESCRIPTIONS
        assert table_name not in _render_table_catalog()


def test_w2_tables_have_separate_exact_six_category_without_widening_raw_v2() -> None:
    raw_entries = raw_request_authority_publication_tables()
    private_entries = raw_request_authority_private_tables()
    w2_entries = w2_public_value_authority_publication_tables()

    assert raw_entries == ()
    assert len(private_entries) == 4
    assert {entry.table_name for entry in private_entries} == set(
        PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES
    )
    assert len(w2_entries) == 6
    assert not (
        {entry.table_name for entry in private_entries} & {entry.table_name for entry in w2_entries}
    )
    assert TABLE_CATEGORIES[RAW_REQUEST_AUTHORITY_CATEGORY] == [
        entry.table_name for entry in raw_entries
    ]
    assert TABLE_CATEGORIES[W2_PUBLIC_VALUE_AUTHORITY_CATEGORY] == [
        entry.table_name for entry in w2_entries
    ]
    assert CATEGORY_LABELS[W2_PUBLIC_VALUE_AUTHORITY_CATEGORY] == "W2 Public Value Authority"
    assert all(TABLE_DESCRIPTIONS[entry.table_name] == entry.description for entry in w2_entries)
    assert f"| W2 Public Value Authority | {len(w2_entries)} |" in _render_what_you_get()
    assert f"### W2 Public Value Authority ({len(w2_entries)})" in _render_table_catalog()


def test_exact_raw_export_tree_is_emitted_as_described_resources(tmp_path: Path) -> None:
    _write_raw_authority_exports(tmp_path)

    assert _resolve_export_inventory(tmp_path).raw_authority_tables == len(
        raw_request_authority_publication_tables()
    )
    assert _resolve_export_inventory(tmp_path).w2_authority_tables == len(
        w2_public_value_authority_publication_tables()
    )
    resources = _build_resources(tmp_path, validate_csv_headers=True)
    by_path = {resource["path"]: resource for resource in resources}
    for table_name in PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES:
        assert f"csv/{table_name}.csv" not in by_path
        assert f"parquet/{table_name}/{table_name}.parquet" not in by_path
    for entry in w2_public_value_authority_publication_tables():
        csv = by_path[f"csv/{entry.table_name}.csv"]
        parquet = by_path[f"parquet/{entry.table_name}/{entry.table_name}.parquet"]
        assert csv["description"] == parquet["description"] == entry.description
        assert csv["name"].endswith("(W2 Authority)")
        assert parquet["name"].endswith("W2 Authority (Parquet)")
        assert [field["name"] for field in csv["schema"]["fields"]] == list(entry.ordered_columns)
        assert csv["schema"] == parquet["schema"]


def test_unexpected_raw_export_is_rejected_before_metadata_enumeration(
    tmp_path: Path,
) -> None:
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "raw_nba_api_shadow.csv").write_text("value\n", encoding="utf-8")

    with pytest.raises(ValueError, match="non-canonical raw authority tables"):
        _build_resources(tmp_path)


def test_absent_raw_export_inventory_reports_zero_available_tables(tmp_path: Path) -> None:
    inventory = _resolve_export_inventory(tmp_path)
    assert inventory.raw_authority_tables == 0
    assert inventory.w2_authority_tables == 0


@pytest.mark.parametrize("present_format", ["csv", "parquet"])
def test_partial_raw_format_inventory_is_rejected(
    tmp_path: Path,
    present_format: str,
) -> None:
    table_name = w2_public_value_authority_publication_tables()[0].table_name
    if present_format == "csv":
        csv_dir = tmp_path / "csv"
        csv_dir.mkdir()
        (csv_dir / f"{table_name}.csv").write_text("value\n", encoding="utf-8")
    else:
        table_dir = tmp_path / "parquet" / table_name
        table_dir.mkdir(parents=True)
        (table_dir / f"{table_name}.parquet").write_bytes(b"parquet")

    with pytest.raises(ValueError, match="CSV and Parquet raw authority exports differ"):
        _resolve_export_inventory(tmp_path)


def test_metadata_catalog_mutation_cannot_widen_fixed_raw_inventory(monkeypatch) -> None:
    monkeypatch.setitem(
        TABLE_CATEGORIES,
        RAW_REQUEST_AUTHORITY_CATEGORY,
        [
            *(entry.table_name for entry in raw_request_authority_publication_tables()),
            "raw_nba_api_shadow",
        ],
    )

    with pytest.raises(RuntimeError, match="catalog drifted"):
        expected_full_publication_resource_contract()
