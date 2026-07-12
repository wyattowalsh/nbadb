from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


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
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Lane-state attestation schema version is invalid")
    if not isinstance(payload.get("expected_empty"), bool):
        raise ValueError("Lane-state attestation expected_empty must be boolean")
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
    allow_attested_empty: bool = False,
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
        )
    ):
        raise ValueError("Expected lane-state bindings require an attestation file")

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
        else:
            journal_rows = 0
    finally:
        con.close()

    return {
        "path": str(path),
        "sha256": digest,
        "journal_present": journal_present,
        "journal_rows": journal_rows,
        "table_count": len(tables),
        "expected_empty": attested_empty,
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
    parser.add_argument("--allow-attested-empty", action="store_true")
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
                allow_attested_empty=args.allow_attested_empty,
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
