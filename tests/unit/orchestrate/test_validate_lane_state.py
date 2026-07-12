from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pytest

if TYPE_CHECKING:
    from types import ModuleType


def _load_module() -> ModuleType:
    path = Path(__file__).parents[3] / ".github" / "scripts" / "validate_lane_state.py"
    spec = importlib.util.spec_from_file_location("validate_lane_state", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_database(path: Path, *, journal: bool = True) -> None:
    conn = duckdb.connect(str(path))
    if journal:
        conn.execute(
            "create table _extraction_journal(endpoint varchar, params varchar, status varchar)"
        )
        conn.execute("insert into _extraction_journal values ('endpoint', '{}', 'done')")
    else:
        conn.execute("create table stg_example(value integer)")
    conn.close()


def _write_attestation(
    path: Path,
    db_path: Path,
    *,
    expected_empty: bool = False,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_sha": "source-sha",
                "chain_id": "chain-1",
                "lane_id": "lane-1",
                "coverage_units_hash": "b" * 64,
                "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
                "expected_empty": expected_empty,
            }
        ),
        encoding="utf-8",
    )


def test_validate_lane_state_binds_digest_and_journal(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    _write_database(db_path)
    digest = hashlib.sha256(db_path.read_bytes()).hexdigest()

    report = module.validate_lane_state(
        db_path,
        expected_sha256=digest,
        require_journal=True,
    )

    assert report["sha256"] == digest
    assert report["journal_present"] is True
    assert report["journal_rows"] == 1


def test_validate_lane_state_rejects_digest_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    _write_database(db_path)

    with pytest.raises(ValueError, match="does not match"):
        module.validate_lane_state(db_path, expected_sha256="0" * 64)


def test_validate_lane_state_requires_journal_for_attested_resume(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    _write_database(db_path, journal=False)

    assert module.validate_lane_state(db_path)["journal_present"] is False
    with pytest.raises(ValueError, match="missing _extraction_journal"):
        module.validate_lane_state(db_path, require_journal=True)


def test_validate_lane_state_rejects_symlink(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    _write_database(db_path)
    link = tmp_path / "linked.duckdb"
    link.symlink_to(db_path)

    with pytest.raises(ValueError, match="regular database file"):
        module.validate_lane_state(link)


def test_validate_lane_state_rejects_companion_wal(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    _write_database(db_path)
    Path(f"{db_path}.wal").write_bytes(b"")

    with pytest.raises(ValueError, match="unattested DuckDB WAL"):
        module.validate_lane_state(db_path)


def test_validate_lane_state_binds_exact_snapshot_attestation(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_database(db_path)
    _write_attestation(attestation_path, db_path)

    report = module.validate_lane_state(
        db_path,
        require_journal=True,
        attestation_path=attestation_path,
        expected_source_sha="source-sha",
        expected_chain_id="chain-1",
        expected_lane_id="lane-1",
        expected_coverage_units_hash="b" * 64,
    )

    assert report["expected_empty"] is False
    assert report["journal_rows"] == 1


def test_validate_lane_state_rejects_attestation_binding_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_database(db_path)
    _write_attestation(attestation_path, db_path)

    with pytest.raises(ValueError, match="source_sha does not match"):
        module.validate_lane_state(
            db_path,
            attestation_path=attestation_path,
            expected_source_sha="different-source",
            expected_chain_id="chain-1",
            expected_lane_id="lane-1",
            expected_coverage_units_hash="b" * 64,
        )


def test_validate_lane_state_allows_only_explicit_attested_empty_database(
    tmp_path: Path,
) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    conn = duckdb.connect(str(db_path))
    conn.close()
    _write_attestation(attestation_path, db_path, expected_empty=True)
    kwargs = {
        "attestation_path": attestation_path,
        "expected_source_sha": "source-sha",
        "expected_chain_id": "chain-1",
        "expected_lane_id": "lane-1",
        "expected_coverage_units_hash": "b" * 64,
        "require_journal": True,
    }

    with pytest.raises(ValueError, match="missing _extraction_journal"):
        module.validate_lane_state(db_path, **kwargs)

    report = module.validate_lane_state(db_path, allow_attested_empty=True, **kwargs)
    assert report["expected_empty"] is True
    assert report["journal_present"] is False
