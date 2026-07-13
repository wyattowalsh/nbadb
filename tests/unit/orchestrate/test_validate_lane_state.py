from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.orchestrate.workload_contract import (
    PlayerTeamSeasonWorkloadStore,
    build_player_team_season_workload_scope,
)

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
    workload_contract: dict[str, object] | None = None,
    schema_version: int | object | None = None,
) -> None:
    if schema_version is None:
        schema_version = 2 if workload_contract is not None else 1
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "source_sha": "source-sha",
        "chain_id": "chain-1",
        "lane_id": "lane-1",
        "coverage_units_hash": "b" * 64,
        "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "expected_empty": expected_empty,
    }
    if workload_contract is not None:
        payload["workload_contract"] = workload_contract
    if schema_version == 3:
        payload.update(
            {
                "run_id": "12345",
                "artifact_name": "extraction-lane-chain-1-lane-1",
                "attested": True,
            }
        )
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _write_workload_database(path: Path, params: dict[str, object]) -> None:
    conn = duckdb.connect(str(path))
    conn.execute(
        "create table _extraction_journal(endpoint varchar, params varchar, status varchar)"
    )
    conn.execute(
        "insert into _extraction_journal values (?, ?, 'done')",
        ["player_index", json.dumps(params)],
    )
    conn.close()


def _workload_scope(tmp_path: Path, params: dict[str, object]):
    anchor = tmp_path / "workload" / "nba.duckdb"
    anchor.parent.mkdir()
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(anchor)
    store.upsert(
        [params],  # type: ignore[list-item]
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )
    scope = build_player_team_season_workload_scope(
        store,
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )
    return anchor, store, scope


def _v3_expected_bindings() -> dict[str, str]:
    return {
        "expected_source_sha": "source-sha",
        "expected_chain_id": "chain-1",
        "expected_lane_id": "lane-1",
        "expected_coverage_units_hash": "b" * 64,
        "expected_run_id": "12345",
        "expected_artifact_name": "extraction-lane-chain-1-lane-1",
    }


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


def test_validate_lane_state_accepts_exact_schema_v3_attestation(tmp_path: Path) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_database(db_path)
    _write_attestation(attestation_path, db_path, schema_version=3)

    report = module.validate_lane_state(
        db_path,
        require_journal=True,
        attestation_path=attestation_path,
        **_v3_expected_bindings(),
    )

    assert report["journal_rows"] == 1
    assert report["sha256"] == hashlib.sha256(db_path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("argument", "message"),
    [
        ("expected_run_id", "requires expected run_id and artifact_name"),
        ("expected_artifact_name", "requires expected run_id and artifact_name"),
    ],
)
def test_validate_lane_state_schema_v3_requires_expected_artifact_bindings(
    tmp_path: Path,
    argument: str,
    message: str,
) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_database(db_path)
    _write_attestation(attestation_path, db_path, schema_version=3)
    bindings = _v3_expected_bindings()
    bindings[argument] = ""

    with pytest.raises(ValueError, match=message):
        module.validate_lane_state(
            db_path,
            attestation_path=attestation_path,
            **bindings,
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("source_sha", "wrong-source", "source_sha does not match"),
        ("chain_id", "wrong-chain", "chain_id does not match"),
        ("lane_id", "wrong-lane", "lane_id does not match"),
        ("coverage_units_hash", "0" * 64, "coverage_units_hash does not match"),
        ("database_sha256", "0" * 64, "database_sha256 does not match"),
        ("run_id", "54321", "run_id does not match"),
        ("run_id", None, "run_id does not match"),
        ("artifact_name", "wrong-artifact", "artifact_name does not match"),
        ("artifact_name", None, "artifact_name does not match"),
    ],
)
def test_validate_lane_state_schema_v3_rejects_identity_tampering(
    tmp_path: Path,
    field: str,
    replacement: object,
    message: str,
) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_database(db_path)
    _write_attestation(attestation_path, db_path, schema_version=3)
    payload = json.loads(attestation_path.read_text(encoding="utf-8"))
    if replacement is None:
        payload.pop(field)
    else:
        payload[field] = replacement
    attestation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        module.validate_lane_state(
            db_path,
            attestation_path=attestation_path,
            **_v3_expected_bindings(),
        )


@pytest.mark.parametrize("attested", [False, None])
def test_validate_lane_state_schema_v3_requires_explicit_attested_true(
    tmp_path: Path,
    attested: bool | None,
) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_database(db_path)
    _write_attestation(attestation_path, db_path, schema_version=3)
    payload = json.loads(attestation_path.read_text(encoding="utf-8"))
    if attested is None:
        payload.pop("attested")
    else:
        payload["attested"] = attested
    attestation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must be explicitly attested"):
        module.validate_lane_state(
            db_path,
            attestation_path=attestation_path,
            **_v3_expected_bindings(),
        )


@pytest.mark.parametrize("schema_version", [None, True, 0, 4, "3"])
def test_validate_lane_state_rejects_malformed_attestation_schema(
    tmp_path: Path,
    schema_version: object,
) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_database(db_path)
    _write_attestation(attestation_path, db_path)
    payload = json.loads(attestation_path.read_text(encoding="utf-8"))
    if schema_version is None:
        payload.pop("schema_version")
    else:
        payload["schema_version"] = schema_version
    attestation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="schema version is invalid"):
        module.validate_lane_state(
            db_path,
            attestation_path=attestation_path,
            **_v3_expected_bindings(),
        )


def test_validate_lane_state_cli_accepts_schema_v3_artifact_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_database(db_path)
    _write_attestation(attestation_path, db_path, schema_version=3)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_lane_state.py",
            str(db_path),
            "--require-journal",
            "--attestation-path",
            str(attestation_path),
            "--expected-source-sha",
            "source-sha",
            "--expected-chain-id",
            "chain-1",
            "--expected-lane-id",
            "lane-1",
            "--expected-coverage-units-hash",
            "b" * 64,
            "--expected-run-id",
            "12345",
            "--expected-artifact-name",
            "extraction-lane-chain-1-lane-1",
        ],
    )

    assert module.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["journal_rows"] == 1


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


def test_validate_lane_state_binds_active_workload_generation(tmp_path: Path) -> None:
    module = _load_module()
    params = {
        "player_id": 1,
        "team_id": 10,
        "season": "2024-25",
        "season_type": "Regular Season",
    }
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_workload_database(db_path, params)
    workload_anchor, store, scope = _workload_scope(tmp_path, params)
    _write_attestation(
        attestation_path,
        db_path,
        workload_contract=dict(scope.contract),
    )
    kwargs = {
        "attestation_path": attestation_path,
        "expected_source_sha": "source-sha",
        "expected_chain_id": "chain-1",
        "expected_lane_id": "lane-1",
        "expected_coverage_units_hash": "b" * 64,
        "workload_duckdb_path": workload_anchor,
        "workload_season_start": 2024,
        "workload_season_end": 2024,
        "workload_season_types": ("Regular Season",),
    }

    report = module.validate_lane_state(db_path, **kwargs)
    assert report["workload_integrity"] == scope.contract["integrity"]

    store.upsert(
        [
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ],
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )
    with pytest.raises(ValueError, match="does not match the active generation"):
        module.validate_lane_state(db_path, **kwargs)


def test_validate_lane_state_accepts_append_only_workload_growth_outside_lane_scope(
    tmp_path: Path,
) -> None:
    module = _load_module()
    params = {
        "player_id": 1,
        "team_id": 10,
        "season": "2024-25",
        "season_type": "Regular Season",
    }
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_workload_database(db_path, params)
    workload_anchor, store, scope = _workload_scope(tmp_path, params)
    _write_attestation(
        attestation_path,
        db_path,
        workload_contract=dict(scope.contract),
    )

    original_integrity = scope.contract["integrity"]
    store.upsert(
        [
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2025-26",
                "season_type": "Regular Season",
            }
        ],
        seasons=["2025-26"],
        season_types=["Regular Season"],
    )

    report = module.validate_lane_state(
        db_path,
        attestation_path=attestation_path,
        expected_source_sha="source-sha",
        expected_chain_id="chain-1",
        expected_lane_id="lane-1",
        expected_coverage_units_hash="b" * 64,
        workload_duckdb_path=workload_anchor,
        workload_season_start=2024,
        workload_season_end=2024,
        workload_season_types=("Regular Season",),
    )

    assert report["workload_integrity"] != original_integrity


def test_validate_lane_state_rejects_unexpected_workload_identity(tmp_path: Path) -> None:
    module = _load_module()
    expected = {
        "player_id": 1,
        "team_id": 10,
        "season": "2024-25",
        "season_type": "Regular Season",
    }
    unexpected = {**expected, "player_id": 99, "team_id": 990}
    db_path = tmp_path / "nba.duckdb"
    attestation_path = tmp_path / "lane-state-attestation.json"
    _write_workload_database(db_path, unexpected)
    workload_anchor, _store, scope = _workload_scope(tmp_path, expected)
    _write_attestation(
        attestation_path,
        db_path,
        workload_contract=dict(scope.contract),
    )

    with pytest.raises(ValueError, match="unexpected player/team/season workload identities"):
        module.validate_lane_state(
            db_path,
            attestation_path=attestation_path,
            expected_source_sha="source-sha",
            expected_chain_id="chain-1",
            expected_lane_id="lane-1",
            expected_coverage_units_hash="b" * 64,
            workload_duckdb_path=workload_anchor,
            workload_season_start=2024,
            workload_season_end=2024,
            workload_season_types=("Regular Season",),
        )
