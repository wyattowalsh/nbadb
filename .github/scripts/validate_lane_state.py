from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from nbadb.orchestrate.seasons import season_range
from nbadb.orchestrate.workload_contract import (
    PlayerTeamSeasonWorkloadScope,
    PlayerTeamSeasonWorkloadStore,
    build_player_team_season_workload_scope,
    player_team_season_workload_base_unit,
    player_team_season_workload_scope_identity,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_attestation(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Lane-state attestation must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Lane-state attestation is not valid JSON") from exc
    schema_version = payload.get("schema_version") if isinstance(payload, dict) else None
    if type(schema_version) is not int or schema_version not in {1, 2, 3}:
        raise ValueError("Lane-state attestation schema version is invalid")
    if not isinstance(payload.get("expected_empty"), bool):
        raise ValueError("Lane-state attestation expected_empty must be boolean")
    if schema_version >= 2:
        workload_contract = payload.get("workload_contract")
        if workload_contract is not None and not isinstance(workload_contract, dict):
            raise ValueError("Lane-state attestation workload_contract must be an object or null")
    return payload


def validate_lane_state(
    path: Path,
    *,
    expected_sha256: str = "",
    require_journal: bool = False,
    attestation_path: Path | None = None,
    expected_source_sha: str = "",
    expected_chain_id: str = "",
    expected_lane_id: str = "",
    expected_coverage_units_hash: str = "",
    expected_run_id: str = "",
    expected_artifact_name: str = "",
    allow_attested_empty: bool = False,
    workload_duckdb_path: Path | None = None,
    workload_season_start: int | None = None,
    workload_season_end: int | None = None,
    workload_season_types: tuple[str, ...] = (),
) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Lane state must be a regular database file: {path}")
    wal_path = Path(f"{path}.wal")
    if wal_path.exists():
        raise ValueError(f"Lane state has an unattested DuckDB WAL: {wal_path}")

    digest = _sha256(path)
    if expected_sha256:
        normalized = expected_sha256.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("Expected lane-state SHA-256 is invalid")
        if digest != normalized:
            raise ValueError("Lane-state SHA-256 does not match the manifest attestation")

    attestation: dict[str, Any] | None = None
    if attestation_path is not None:
        attestation = _load_attestation(attestation_path)
        bound_values = {
            "source_sha": expected_source_sha,
            "chain_id": expected_chain_id,
            "lane_id": expected_lane_id,
            "coverage_units_hash": expected_coverage_units_hash,
        }
        if attestation["schema_version"] >= 3:
            if not expected_run_id or not expected_artifact_name:
                raise ValueError(
                    "Lane-state attestation schema v3 requires expected run_id and artifact_name"
                )
            if attestation.get("attested") is not True:
                raise ValueError("Lane-state attestation schema v3 must be explicitly attested")
            bound_values.update(
                {
                    "run_id": expected_run_id,
                    "artifact_name": expected_artifact_name,
                }
            )
        for key, expected in bound_values.items():
            actual = str(attestation.get(key) or "")
            if not expected or actual != expected:
                raise ValueError(f"Lane-state attestation {key} does not match")
        if str(attestation.get("database_sha256") or "").lower() != digest:
            raise ValueError("Lane-state attestation database_sha256 does not match")
    elif any(
        (
            expected_source_sha,
            expected_chain_id,
            expected_lane_id,
            expected_coverage_units_hash,
            expected_run_id,
            expected_artifact_name,
        )
    ):
        raise ValueError("Expected lane-state bindings require an attestation file")

    workload_scope: PlayerTeamSeasonWorkloadScope | None = None
    if workload_duckdb_path is not None:
        if (
            attestation is None
            or workload_season_start is None
            or workload_season_end is None
            or workload_season_start > workload_season_end
            or not workload_season_types
        ):
            raise ValueError("Workload-bound lane state requires an attestation and exact scope")
        workload_scope = build_player_team_season_workload_scope(
            PlayerTeamSeasonWorkloadStore.from_duckdb_path(workload_duckdb_path),
            seasons=season_range(workload_season_start, workload_season_end),
            season_types=list(workload_season_types),
        )
        attested_contract = attestation.get("workload_contract")
        if not isinstance(attested_contract, dict) or not isinstance(
            attested_contract.get("integrity"), dict
        ):
            raise ValueError("Lane-state attestation workload_contract is missing or invalid")
        try:
            attested_identity = player_team_season_workload_scope_identity(attested_contract)
            active_identity = player_team_season_workload_scope_identity(workload_scope.contract)
        except ValueError as exc:
            raise ValueError(f"Lane-state workload scope identity is invalid: {exc}") from exc
        if attested_identity != active_identity:
            raise ValueError(
                "Lane-state attestation workload scope does not match the active generation"
            )
    elif attestation is not None and attestation.get("workload_contract") is not None:
        raise ValueError("Lane-state attestation has an unexpected workload_contract")

    attested_empty = bool(
        allow_attested_empty and attestation and attestation.get("expected_empty") is True
    )

    import duckdb

    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = {
            str(row[0])
            for row in con.execute(
                "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
            ).fetchall()
        }
        journal_present = "_extraction_journal" in tables
        if require_journal and not journal_present and not attested_empty:
            raise ValueError("Attested lane state is missing _extraction_journal")
        if (
            not journal_present
            and not attested_empty
            and not any(table.startswith("stg_") for table in tables)
        ):
            raise ValueError("Lane state contains neither extraction journal nor staging tables")
        if journal_present:
            columns = {
                str(row[0])
                for row in con.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'main' AND table_name = '_extraction_journal'
                    """
                ).fetchall()
            }
            required_columns = {"endpoint", "params", "status"}
            if not required_columns <= columns:
                missing = ",".join(sorted(required_columns - columns))
                raise ValueError(f"Extraction journal is missing required columns: {missing}")
            row = con.execute("SELECT count(*) FROM _extraction_journal").fetchone()
            if row is None:
                raise ValueError("Extraction journal row count is unavailable")
            journal_rows = int(row[0])
            journal_params = [
                str(row[0] or "")
                for row in con.execute("SELECT params FROM _extraction_journal").fetchall()
            ]
        else:
            journal_rows = 0
            journal_params = []
    finally:
        con.close()

    if workload_scope is not None:
        invalid_identity_count = 0
        unexpected_identities: set[tuple[int, str, int, int]] = set()
        for raw_params in journal_params:
            try:
                params = json.loads(raw_params)
            except (json.JSONDecodeError, TypeError):
                params = None
            identity = (
                player_team_season_workload_base_unit(params) if isinstance(params, dict) else None
            )
            if identity is None:
                invalid_identity_count += 1
            elif identity not in workload_scope.base_units:
                unexpected_identities.add(identity)
        if invalid_identity_count:
            raise ValueError(
                "Extraction journal contains invalid player/team/season workload identities: "
                f"{invalid_identity_count}"
            )
        if unexpected_identities:
            samples = ", ".join(str(identity) for identity in sorted(unexpected_identities)[:10])
            raise ValueError(
                "Extraction journal contains unexpected player/team/season workload identities: "
                f"{samples}"
            )

    return {
        "path": str(path),
        "sha256": digest,
        "journal_present": journal_present,
        "journal_rows": journal_rows,
        "table_count": len(tables),
        "expected_empty": attested_empty,
        "workload_integrity": (
            workload_scope.contract["integrity"] if workload_scope is not None else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a resumable extraction lane database")
    parser.add_argument("path", type=Path)
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--require-journal", action="store_true")
    parser.add_argument("--attestation-path", type=Path)
    parser.add_argument("--expected-source-sha", default="")
    parser.add_argument("--expected-chain-id", default="")
    parser.add_argument("--expected-lane-id", default="")
    parser.add_argument("--expected-coverage-units-hash", default="")
    parser.add_argument("--expected-run-id", default="")
    parser.add_argument("--expected-artifact-name", default="")
    parser.add_argument("--allow-attested-empty", action="store_true")
    parser.add_argument("--workload-duckdb-path", type=Path)
    parser.add_argument("--workload-season-start", type=int)
    parser.add_argument("--workload-season-end", type=int)
    parser.add_argument("--workload-season-types", default="")
    args = parser.parse_args()
    print(
        json.dumps(
            validate_lane_state(
                args.path,
                expected_sha256=args.expected_sha256,
                require_journal=args.require_journal,
                attestation_path=args.attestation_path,
                expected_source_sha=args.expected_source_sha,
                expected_chain_id=args.expected_chain_id,
                expected_lane_id=args.expected_lane_id,
                expected_coverage_units_hash=args.expected_coverage_units_hash,
                expected_run_id=args.expected_run_id,
                expected_artifact_name=args.expected_artifact_name,
                allow_attested_empty=args.allow_attested_empty,
                workload_duckdb_path=args.workload_duckdb_path,
                workload_season_start=args.workload_season_start,
                workload_season_end=args.workload_season_end,
                workload_season_types=tuple(
                    value for value in args.workload_season_types.split(",") if value
                ),
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
