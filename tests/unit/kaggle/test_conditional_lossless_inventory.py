from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import duckdb
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.kaggle.metadata import expected_full_publication_resource_contract
from nbadb.orchestrate.staging_map import (
    LOSSLESS_FALLBACK_STAGING_KEY,
    get_all_staging_keys,
)
from nbadb.orchestrate.successor_assurance import (
    SuccessorPublicEvidence,
    SuccessorPublicResourceAttestation,
)
from nbadb.orchestrate.successor_publication_inventory import _production_data_contract

_CSV_RESOURCE = f"csv/{LOSSLESS_FALLBACK_STAGING_KEY}.csv"
_PARQUET_RESOURCE = (
    f"parquet/{LOSSLESS_FALLBACK_STAGING_KEY}/{LOSSLESS_FALLBACK_STAGING_KEY}.parquet"
)
_LIVE_CSV_RESOURCE = f"csv/{LIVE_LOSSLESS_STAGING_KEY}.csv"
_LIVE_PARQUET_RESOURCE = f"parquet/{LIVE_LOSSLESS_STAGING_KEY}/{LIVE_LOSSLESS_STAGING_KEY}.parquet"
_CONTROLS = {"assured-artifact-manifest.json", "terminal-assurance-report.json"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _write_staging_export(root: Path, table_name: str) -> None:
    csv_dir = root / "csv"
    parquet_table_dir = root / "parquet" / table_name
    csv_dir.mkdir(parents=True, exist_ok=True)
    parquet_table_dir.mkdir(parents=True, exist_ok=True)
    (csv_dir / f"{table_name}.csv").write_text("value\n1\n", encoding="utf-8")
    (parquet_table_dir / f"{table_name}.parquet").write_bytes(b"parquet-receipt")
    connection = duckdb.connect(str(root / "nba.duckdb"))
    try:
        connection.execute(f'CREATE TABLE "{table_name}" (value INTEGER)')
    finally:
        connection.close()


def _public_evidence(
    *,
    include_fallback: bool,
    include_live_lossless: bool = False,
) -> SuccessorPublicEvidence:
    contract = expected_full_publication_resource_contract(
        include_lossless_fallback=include_fallback,
        include_live_lossless=include_live_lossless,
    )
    return SuccessorPublicEvidence(
        resources=tuple(
            SuccessorPublicResourceAttestation(
                resource_id=resource_id,
                kind=kind,
                bytes=index + 1,
                sha256=_digest(resource_id),
            )
            for index, (resource_id, kind) in enumerate(
                item for item in sorted(contract.items()) if item[0] not in _CONTROLS
            )
        )
    )


def test_static_inventory_is_unchanged_when_fallback_is_absent(tmp_path: Path) -> None:
    contract = expected_full_publication_resource_contract(tmp_path)
    static_contract = expected_full_publication_resource_contract()

    assert contract == static_contract
    assert _CSV_RESOURCE not in contract
    assert _PARQUET_RESOURCE not in contract
    assert _LIVE_CSV_RESOURCE not in contract
    assert _LIVE_PARQUET_RESOURCE not in contract
    assert LOSSLESS_FALLBACK_STAGING_KEY not in get_all_staging_keys()
    assert LOSSLESS_FALLBACK_STAGING_KEY not in get_all_staging_keys(present_keys=set())
    assert _production_data_contract().tables == _production_data_contract(tmp_path).tables


def test_present_fallback_adds_only_one_table_and_two_resources(tmp_path: Path) -> None:
    _write_staging_export(tmp_path, LOSSLESS_FALLBACK_STAGING_KEY)

    contract = expected_full_publication_resource_contract(tmp_path)
    static_contract = expected_full_publication_resource_contract()
    data_contract = _production_data_contract(tmp_path)
    static_data_contract = _production_data_contract()

    assert len(contract) == len(static_contract) + 2
    assert set(contract) - set(static_contract) == {_CSV_RESOURCE, _PARQUET_RESOURCE}
    assert contract[_CSV_RESOURCE] == "file"
    assert contract[_PARQUET_RESOURCE] == "file"
    assert len(data_contract.tables) == len(static_data_contract.tables) + 1
    assert LOSSLESS_FALLBACK_STAGING_KEY in data_contract.tables
    assert get_all_staging_keys(present_keys={LOSSLESS_FALLBACK_STAGING_KEY})[-1] == (
        LOSSLESS_FALLBACK_STAGING_KEY
    )


def test_present_live_lossless_adds_only_one_table_and_two_resources(
    tmp_path: Path,
) -> None:
    _write_staging_export(tmp_path, LIVE_LOSSLESS_STAGING_KEY)

    contract = expected_full_publication_resource_contract(tmp_path)
    static_contract = expected_full_publication_resource_contract()
    data_contract = _production_data_contract(tmp_path)
    static_data_contract = _production_data_contract()

    assert len(contract) == len(static_contract) + 2
    assert set(contract) - set(static_contract) == {
        _LIVE_CSV_RESOURCE,
        _LIVE_PARQUET_RESOURCE,
    }
    assert len(data_contract.tables) == len(static_data_contract.tables) + 1
    assert LIVE_LOSSLESS_STAGING_KEY in data_contract.tables
    assert LIVE_LOSSLESS_STAGING_KEY not in get_all_staging_keys()
    assert LIVE_LOSSLESS_STAGING_KEY in get_all_staging_keys(
        present_keys={LIVE_LOSSLESS_STAGING_KEY}
    )


def test_both_conditionals_add_exactly_two_tables_and_four_resources(
    tmp_path: Path,
) -> None:
    _write_staging_export(tmp_path, LOSSLESS_FALLBACK_STAGING_KEY)
    _write_staging_export(tmp_path, LIVE_LOSSLESS_STAGING_KEY)

    contract = expected_full_publication_resource_contract(tmp_path)
    static_contract = expected_full_publication_resource_contract()
    data_contract = _production_data_contract(tmp_path)
    static_data_contract = _production_data_contract()

    assert len(contract) == len(static_contract) + 4
    assert set(contract) - set(static_contract) == {
        _CSV_RESOURCE,
        _PARQUET_RESOURCE,
        _LIVE_CSV_RESOURCE,
        _LIVE_PARQUET_RESOURCE,
    }
    assert len(data_contract.tables) == len(static_data_contract.tables) + 2


@pytest.mark.parametrize(
    ("include_fallback", "include_live_lossless"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_public_assurance_accepts_exact_absent_or_present_inventory(
    include_fallback: bool,
    include_live_lossless: bool,
) -> None:
    contract = expected_full_publication_resource_contract(
        include_lossless_fallback=include_fallback,
        include_live_lossless=include_live_lossless,
    )
    evidence = _public_evidence(
        include_fallback=include_fallback,
        include_live_lossless=include_live_lossless,
    )

    assert evidence.resource_count == len(contract)
    assert evidence.data_resource_count == len(contract) - len(_CONTROLS)


def test_partial_conditional_export_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "csv").mkdir()
    (tmp_path / "parquet").mkdir()
    (tmp_path / "csv" / f"{LOSSLESS_FALLBACK_STAGING_KEY}.csv").write_text(
        "value\n1\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="CSV and Parquet staging exports differ"):
        expected_full_publication_resource_contract(tmp_path)


def test_database_only_fallback_cannot_hide_missing_exports(tmp_path: Path) -> None:
    connection = duckdb.connect(str(tmp_path / "nba.duckdb"))
    try:
        connection.execute(f'CREATE TABLE "{LOSSLESS_FALLBACK_STAGING_KEY}" (value INTEGER)')
    finally:
        connection.close()

    with pytest.raises(ValueError, match="Conditional staging exports differ"):
        expected_full_publication_resource_contract(tmp_path)


def test_unknown_staging_export_cannot_masquerade_as_conditional(tmp_path: Path) -> None:
    _write_staging_export(tmp_path, "stg_unknown_lossless_result_cells")

    with pytest.raises(ValueError, match="non-canonical staging tables"):
        expected_full_publication_resource_contract(tmp_path)


def test_explicit_inventory_override_must_match_observed_tree(tmp_path: Path) -> None:
    _write_staging_export(tmp_path, LOSSLESS_FALLBACK_STAGING_KEY)

    with pytest.raises(ValueError, match="override differs"):
        expected_full_publication_resource_contract(
            tmp_path,
            include_lossless_fallback=False,
        )


def test_live_inventory_override_must_match_observed_tree(tmp_path: Path) -> None:
    _write_staging_export(tmp_path, LIVE_LOSSLESS_STAGING_KEY)

    with pytest.raises(ValueError, match="override differs"):
        expected_full_publication_resource_contract(
            tmp_path,
            include_live_lossless=False,
        )
