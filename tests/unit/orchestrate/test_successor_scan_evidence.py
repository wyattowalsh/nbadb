from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import duckdb
import pytest

import nbadb.orchestrate.successor_scan_evidence as scan_evidence_module
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.scanner import ScanFinding, ScanReport
from nbadb.orchestrate.successor_scan_evidence import (
    SuccessorFullPublicationScanner,
    SuccessorFullPublicationScanResult,
    SuccessorScanEvidenceError,
    filesystem_free_bytes,
    run_data_scanner_full_publication,
)
from nbadb.orchestrate.successor_update_contract import canonical_json_bytes
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _w2_database_authority(seed: str = "fixture") -> W2DatabaseAuthorityReceiptV1:
    def digest(label: str) -> str:
        return hashlib.sha256(f"{seed}:{label}".encode()).hexdigest()

    relation_counts = tuple(
        sorted(
            (
                table_name,
                1 if table_name == RAW_NBA_API_W2_OPERATION_TABLE else 0,
            )
            for table_name in (*PUBLIC_VALUE_AUTHORITY_TABLES, RAW_NBA_API_W2_OPERATION_TABLE)
        )
    )
    return W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=1,
        w2_source_call_admission_inventory_sha256=digest("admissions"),
        raw_authority_v2_bundle_count=1,
        raw_authority_v2_bundle_inventory_sha256=digest("raw-bundles"),
        raw_authority_v2_persistence_receipt_inventory_sha256=digest("raw-persistence"),
        w2_publication_receipt_count=1,
        w2_publication_receipt_inventory_sha256=digest("publications"),
        w2_exact_six_schema_inventory_sha256=digest("schemas"),
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=1,
        w2_relation_inventory_sha256=digest("relations"),
    )


def _create_database(path: Path, marker: str = "original") -> int:
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE TABLE marker(value VARCHAR)")
        connection.execute("INSERT INTO marker VALUES (?)", [marker])
    finally:
        connection.close()
    return path.stat().st_size


def _passing_report(
    *,
    duration: float = 0.0,
    findings: list[ScanFinding] | None = None,
    w2_database_authority: W2DatabaseAuthorityReceiptV1 | None = None,
) -> ScanReport:
    return ScanReport(
        findings=[] if findings is None else findings,
        evidence={
            "w2_database_authority": (
                _w2_database_authority() if w2_database_authority is None else w2_database_authority
            ).to_dict()
        },
        tables_scanned=7,
        checks_run=11,
        duration_seconds=duration,
    )


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path.resolve()
    public = root / "public"
    scratch = root / "scratch"
    public.mkdir(mode=0o755)
    scratch.mkdir(mode=0o700)
    database = public / "nba.duckdb"
    _create_database(database)
    return public, scratch, database


def _scanner(
    scratch: Path,
    scan_function: Callable[[duckdb.DuckDBPyConnection], ScanReport],
    *,
    max_database_bytes: int = 16 * 1024 * 1024,
    minimum_free_bytes: int = 1,
    deadline_monotonic: float = 100.0,
    headroom_seconds: float = 1.0,
    monotonic_clock: Callable[[], float] = lambda: 1.0,
    free_bytes_probe: Callable[[int], int] = filesystem_free_bytes,
    expected_scratch_root_identity: tuple[int, int] | None = None,
) -> SuccessorFullPublicationScanner:
    scratch_stat = scratch.stat()
    return SuccessorFullPublicationScanner(
        scratch_root=scratch,
        expected_scratch_root_identity=(
            expected_scratch_root_identity
            if expected_scratch_root_identity is not None
            else (scratch_stat.st_dev, scratch_stat.st_ino)
        ),
        max_database_bytes=max_database_bytes,
        minimum_free_bytes=minimum_free_bytes,
        deadline_monotonic=deadline_monotonic,
        headroom_seconds=headroom_seconds,
        monotonic_clock=monotonic_clock,
        free_bytes_probe=free_bytes_probe,
        scan_function=scan_function,
    )


def _scan_marker(connection: duckdb.DuckDBPyConnection) -> ScanReport:
    assert connection.execute("SELECT value FROM marker").fetchone() == ("original",)
    return _passing_report()


def _clock(values: list[float]) -> Callable[[], float]:
    iterator: Iterator[float] = iter(values)
    return lambda: next(iterator)


def test_scanner_accepts_exact_expected_root_identity(tmp_path: Path) -> None:
    public, scratch, _ = _layout(tmp_path)
    observed = public.stat()

    result = _scanner(scratch, _scan_marker)(
        public,
        expected_root_identity=(observed.st_dev, observed.st_ino),
    )

    assert result.scan_evidence.status == "passed"
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("invalid_identity", [True, 1.5, [1, 2], (-1, 2)])
def test_scanner_rejects_invalid_expected_root_identity_before_scan(
    tmp_path: Path,
    invalid_identity: object,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    scan_called = False

    def scan(_connection: duckdb.DuckDBPyConnection) -> ScanReport:
        nonlocal scan_called
        scan_called = True
        return _passing_report()

    with pytest.raises(SuccessorScanEvidenceError, match="expected_root_identity is invalid"):
        _scanner(scratch, scan)(
            public,
            expected_root_identity=cast("tuple[int, int]", invalid_identity),
        )

    assert scan_called is False
    assert list(scratch.iterdir()) == []


def test_scanner_rejects_foreign_root_authority_before_scan_or_temp_copy(
    tmp_path: Path,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    observed = public.stat()
    scan_called = False

    def scan(_connection: duckdb.DuckDBPyConnection) -> ScanReport:
        nonlocal scan_called
        scan_called = True
        return _passing_report()

    with pytest.raises(SuccessorScanEvidenceError, match="root differs from expected authority"):
        _scanner(scratch, scan)(
            public,
            expected_root_identity=(observed.st_dev, observed.st_ino + 1),
        )

    assert scan_called is False
    assert list(scratch.iterdir()) == []


def test_scanner_rejects_foreign_scratch_authority_before_scan_or_temp_copy(
    tmp_path: Path,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    observed = scratch.stat()
    scan_called = False

    def scan(_connection: duckdb.DuckDBPyConnection) -> ScanReport:
        nonlocal scan_called
        scan_called = True
        return _passing_report()

    with pytest.raises(SuccessorScanEvidenceError, match="scratch root differs"):
        _scanner(
            scratch,
            scan,
            expected_scratch_root_identity=(observed.st_dev, observed.st_ino + 1),
        )(public)

    assert scan_called is False
    assert list(scratch.iterdir()) == []


def test_scanner_rejects_scratch_substitution_after_construction_without_writing_replacement(
    tmp_path: Path,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    scanner = _scanner(scratch, _scan_marker)
    retained = scratch.with_name("scratch-retained")
    scratch.rename(retained)
    scratch.mkdir(mode=0o700)

    with pytest.raises(SuccessorScanEvidenceError, match="scratch root differs"):
        scanner(public)

    assert list(scratch.iterdir()) == []
    assert list(retained.iterdir()) == []


def test_scanner_scratch_substitution_during_temp_reservation_never_writes_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    retained = scratch.with_name("scratch-retained")
    original_reserve = scan_evidence_module._reserve_private_temp

    def substitute(descriptor: int):
        scratch.rename(retained)
        scratch.mkdir(mode=0o700)
        return original_reserve(descriptor)

    monkeypatch.setattr(scan_evidence_module, "_reserve_private_temp", substitute)

    with pytest.raises(SuccessorScanEvidenceError, match="scratch root changed"):
        _scanner(scratch, _scan_marker)(public)

    assert list(scratch.iterdir()) == []
    assert list(retained.iterdir()) == []


def test_scanner_cleanup_never_removes_a_post_check_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    held = scratch / ".successor-scan-held"
    original = scan_evidence_module._require_named_directory
    substituted_name: str | None = None

    def substitute_after_cleanup_admission(
        parent_descriptor: int,
        name: str,
        descriptor: int,
        expected: os.stat_result,
        *,
        label: str,
    ) -> None:
        nonlocal substituted_name
        original(
            parent_descriptor,
            name,
            descriptor,
            expected,
            label=label,
        )
        if (
            substituted_name is None
            and label == "private scan temporary directory at cleanup admission"
        ):
            substituted_name = name
            (scratch / name).rename(held)
            (scratch / name).mkdir(mode=0o700)

    monkeypatch.setattr(
        scan_evidence_module,
        "_require_named_directory",
        substitute_after_cleanup_admission,
    )

    with pytest.raises(SuccessorScanEvidenceError, match="before cleanup removal changed"):
        _scanner(scratch, _scan_marker)(public)

    assert substituted_name is not None
    replacement = scratch / substituted_name
    assert replacement.is_dir()
    assert list(replacement.iterdir()) == []
    assert held.is_dir()
    assert list(held.iterdir()) == []

    replacement.rmdir()
    held.rmdir()
    result = _scanner(scratch, _scan_marker)(public)
    assert result.scan_evidence.status == "passed"
    assert list(scratch.iterdir()) == []


def test_scanner_cleanup_never_removes_a_post_final_proof_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    held = scratch / ".successor-scan-held"
    original = scan_evidence_module._require_named_directory
    substituted_name: str | None = None

    def substitute_after_final_proof(
        parent_descriptor: int,
        name: str,
        descriptor: int,
        expected: os.stat_result,
        *,
        label: str,
    ) -> None:
        nonlocal substituted_name
        original(
            parent_descriptor,
            name,
            descriptor,
            expected,
            label=label,
        )
        if (
            substituted_name is None
            and label == "private scan temporary directory before cleanup removal"
        ):
            substituted_name = name
            (scratch / name).rename(held)
            (scratch / name).mkdir(mode=0o700)

    monkeypatch.setattr(
        scan_evidence_module,
        "_require_named_directory",
        substitute_after_final_proof,
    )

    with pytest.raises(SuccessorScanEvidenceError, match="replaced at quarantine"):
        _scanner(scratch, _scan_marker)(public)

    assert substituted_name is not None
    replacement = scratch / substituted_name
    assert replacement.is_dir()
    assert list(replacement.iterdir()) == []
    assert held.is_dir()
    assert list(held.iterdir()) == []

    replacement.rmdir()
    held.rmdir()
    result = _scanner(scratch, _scan_marker)(public)
    assert result.scan_evidence.status == "passed"
    assert list(scratch.iterdir()) == []


def test_reserve_private_temp_validation_failure_removes_owned_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    parent = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY)
    real_geteuid = os.geteuid
    monkeypatch.setattr(scan_evidence_module.os, "geteuid", lambda: real_geteuid() + 1)
    try:
        with pytest.raises(SuccessorScanEvidenceError, match="temporary directory is invalid"):
            scan_evidence_module._reserve_private_temp(parent)
        assert list(scratch.iterdir()) == []
    finally:
        os.close(parent)


def test_reserve_private_temp_does_not_remove_a_name_substituted_after_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    held = scratch / "held"
    parent = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY)
    original_stat = scan_evidence_module.os.stat
    substituted: str | None = None

    def swap_after_name_proof(path: object, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal substituted
        result = original_stat(path, *args, **kwargs)
        if (
            substituted is None
            and kwargs.get("dir_fd") == parent
            and isinstance(path, str)
            and path.startswith(".successor-scan-")
        ):
            substituted = path
            os.rename(path, "held", src_dir_fd=parent, dst_dir_fd=parent)
            os.mkdir(path, 0o700, dir_fd=parent)
            return original_stat(path, *args, **kwargs)
        return result

    monkeypatch.setattr(scan_evidence_module.os, "stat", swap_after_name_proof)
    try:
        with pytest.raises(SuccessorScanEvidenceError, match="temporary directory is invalid"):
            scan_evidence_module._reserve_private_temp(parent)
        assert substituted is not None
        replacement = scratch / substituted
        assert replacement.is_dir()
        assert list(replacement.iterdir()) == []
        assert held.is_dir()
        assert list(held.iterdir()) == []
        assert replacement.stat().st_ino != held.stat().st_ino
    finally:
        os.close(parent)


def test_duration_and_input_order_do_not_change_canonical_bytes() -> None:
    findings = [
        ScanFinding(
            category="temporal",
            severity="info",
            table="fact_game",
            check="date_gap",
            message="one historical gap",
            details={"gap_days": 20},
        ),
        ScanFinding(
            category="missing_table",
            severity="warning",
            table="stg_optional",
            check="empty_staging_table",
            message="optional staging table is empty",
            details={"row_count": 0},
        ),
    ]
    database_sha256 = hashlib.sha256(b"database").hexdigest()

    first = SuccessorFullPublicationScanResult.from_scan_report(
        _passing_report(duration=0.001, findings=findings),
        database_sha256=database_sha256,
        database_bytes=8,
    )
    second = SuccessorFullPublicationScanResult.from_scan_report(
        _passing_report(duration=99_999.0, findings=list(reversed(findings))),
        database_sha256=database_sha256,
        database_bytes=8,
    )

    assert first.canonical_bytes == second.canonical_bytes
    assert first.report_sha256 == second.report_sha256
    assert b"duration" not in first.canonical_bytes


def test_warning_and_info_findings_are_allowed_but_errors_fail_closed() -> None:
    safe = [
        ScanFinding("temporal", "info", "fact_game", "date_gap", "gap", None),
        ScanFinding(
            "missing_table",
            "warning",
            "stg_optional",
            "empty_staging_table",
            "empty",
            {"row_count": 0},
        ),
    ]
    result = SuccessorFullPublicationScanResult.from_scan_report(
        _passing_report(findings=safe),
        database_sha256=hashlib.sha256(b"db").hexdigest(),
        database_bytes=2,
    )

    assert result.scan_evidence.error_count == 0
    assert result.to_dict()["summary"] == {
        "total": 2,
        "error": 0,
        "warning": 1,
        "info": 1,
        "tables_scanned": 7,
        "checks_run": 11,
    }

    with pytest.raises(SuccessorScanEvidenceError, match="contains errors"):
        SuccessorFullPublicationScanResult.from_scan_report(
            _passing_report(
                findings=[
                    ScanFinding(
                        "data_quality",
                        "error",
                        "fact_game",
                        "null_key_column",
                        "hard error",
                    )
                ]
            ),
            database_sha256=hashlib.sha256(b"db").hexdigest(),
            database_bytes=2,
        )


def test_exact_evidence_digest_and_strict_canonical_round_trip() -> None:
    result = SuccessorFullPublicationScanResult.from_scan_report(
        _passing_report(),
        database_sha256=hashlib.sha256(b"database").hexdigest(),
        database_bytes=8,
    )
    expected = canonical_json_bytes(result.to_dict()) + b"\n"

    assert result.canonical_bytes == expected
    assert result.report_sha256 == hashlib.sha256(expected).hexdigest()
    assert result.scan_evidence.report_sha256 == hashlib.sha256(expected).hexdigest()
    assert result.scan_evidence.status == "passed"
    assert result.scan_evidence.fail_on == "error"
    assert result.scan_evidence.full_publication is True
    assert result.w2_database_authority == _w2_database_authority()
    assert result.to_dict()["w2_database_authority"] == _w2_database_authority().to_dict()
    assert SuccessorFullPublicationScanResult.from_canonical_bytes(expected) == result


def test_w2_database_authority_is_mandatory_and_digest_bound() -> None:
    database_sha256 = hashlib.sha256(b"database").hexdigest()
    original = SuccessorFullPublicationScanResult.from_scan_report(
        _passing_report(w2_database_authority=_w2_database_authority("original")),
        database_sha256=database_sha256,
        database_bytes=8,
    )
    changed = SuccessorFullPublicationScanResult.from_scan_report(
        _passing_report(w2_database_authority=_w2_database_authority("changed")),
        database_sha256=database_sha256,
        database_bytes=8,
    )

    assert original.report_sha256 != changed.report_sha256
    assert original.canonical_bytes != changed.canonical_bytes

    missing = _passing_report()
    missing.evidence = {}
    with pytest.raises(SuccessorScanEvidenceError, match="typed W2 database authority"):
        SuccessorFullPublicationScanResult.from_scan_report(
            missing,
            database_sha256=database_sha256,
            database_bytes=8,
        )

    mutated = _passing_report()
    payload = dict(mutated.evidence["w2_database_authority"])
    payload["receipt_sha256"] = "f" * 64
    mutated.evidence["w2_database_authority"] = payload
    with pytest.raises(SuccessorScanEvidenceError, match="typed W2 database authority"):
        SuccessorFullPublicationScanResult.from_scan_report(
            mutated,
            database_sha256=database_sha256,
            database_bytes=8,
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda encoded: b" " + encoded,
        lambda encoded: encoded[:-1],
        lambda encoded: encoded + b"\n",
        lambda encoded: encoded.replace(b'"status":"passed"', b'"status": "passed"'),
    ],
)
def test_noncanonical_report_encodings_are_rejected(
    mutate: Callable[[bytes], bytes],
) -> None:
    result = SuccessorFullPublicationScanResult.from_scan_report(
        _passing_report(),
        database_sha256=hashlib.sha256(b"database").hexdigest(),
        database_bytes=8,
    )

    with pytest.raises(SuccessorScanEvidenceError, match="canonical"):
        SuccessorFullPublicationScanResult.from_canonical_bytes(mutate(result.canonical_bytes))


def test_duplicate_json_keys_and_unknown_fields_are_rejected() -> None:
    result = SuccessorFullPublicationScanResult.from_scan_report(
        _passing_report(),
        database_sha256=hashlib.sha256(b"database").hexdigest(),
        database_bytes=8,
    )
    duplicate = result.canonical_bytes.replace(b'{"database":', b'{"database":{},"database":', 1)
    with pytest.raises(SuccessorScanEvidenceError, match="duplicate"):
        SuccessorFullPublicationScanResult.from_canonical_bytes(duplicate)

    payload = result.to_dict()
    payload["unexpected"] = True
    encoded = canonical_json_bytes(payload) + b"\n"
    with pytest.raises(SuccessorScanEvidenceError, match="unexpected"):
        SuccessorFullPublicationScanResult.from_canonical_bytes(encoded)


@pytest.mark.parametrize(
    "details",
    [
        {"unsafe": float("nan")},
        {"unsafe": Path("relative")},
        {"unsafe": "/private/local/database"},
        {"unsafe": "result at /private/local/database"},
        {"Unsafe": "uppercase detail key"},
    ],
)
def test_non_safe_finding_details_are_rejected(details: object) -> None:
    with pytest.raises(SuccessorScanEvidenceError):
        SuccessorFullPublicationScanResult.from_scan_report(
            _passing_report(
                findings=[
                    ScanFinding(
                        "data_quality",
                        "warning",
                        "fact_game",
                        "safe_check",
                        "safe message",
                        details,  # type: ignore[arg-type]
                    )
                ]
            ),
            database_sha256=hashlib.sha256(b"database").hexdigest(),
            database_bytes=8,
        )


def test_duplicate_findings_are_rejected() -> None:
    finding = ScanFinding(
        "data_quality",
        "warning",
        "fact_game",
        "duplicate_keys",
        "duplicate rows",
        {"duplicates": 2},
    )

    with pytest.raises(SuccessorScanEvidenceError, match="duplicates"):
        SuccessorFullPublicationScanResult.from_scan_report(
            _passing_report(findings=[finding, finding]),
            database_sha256=hashlib.sha256(b"database").hexdigest(),
            database_bytes=8,
        )


def test_real_duckdb_copy_is_opened_read_only_and_cleaned(tmp_path: Path) -> None:
    public, scratch, database = _layout(tmp_path)
    expected_sha256 = hashlib.sha256(database.read_bytes()).hexdigest()

    def scan(connection: duckdb.DuckDBPyConnection) -> ScanReport:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("original",)
        with pytest.raises(duckdb.Error):
            connection.execute("CREATE TABLE forbidden(value INTEGER)")
        return _passing_report(duration=88.5)

    result = _scanner(scratch, scan)(public)

    assert result.database_sha256 == expected_sha256
    assert result.database_bytes == database.stat().st_size
    assert list(scratch.iterdir()) == []


def test_restored_public_db_swap_cannot_change_scanned_bytes_and_fails_identity(
    tmp_path: Path,
) -> None:
    public, scratch, database = _layout(tmp_path)
    evil = public / "evil.duckdb"
    _create_database(evil, marker="evil")
    original = public / "original.duckdb"
    scanned_original = False

    def scan(connection: duckdb.DuckDBPyConnection) -> ScanReport:
        nonlocal scanned_original
        os.replace(database, original)
        os.replace(evil, database)
        try:
            assert connection.execute("SELECT value FROM marker").fetchone() == ("original",)
            scanned_original = True
        finally:
            os.replace(database, evil)
            os.replace(original, database)
        return _passing_report()

    with pytest.raises(SuccessorScanEvidenceError, match="changed while held"):
        _scanner(scratch, scan)(public)
    assert scanned_original is True
    assert list(scratch.iterdir()) == []


def test_connect_time_private_path_swap_back_cannot_scan_foreign_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    foreign = public / "foreign.duckdb"
    _create_database(foreign, marker="foreign")
    original_connect = duckdb.connect
    scan_called = False

    def swapping_connect(
        database: str,
        *,
        read_only: bool = False,
        **kwargs: object,
    ) -> duckdb.DuckDBPyConnection:
        private_path = Path(database)
        assert private_path.parent.parent == scratch
        saved = private_path.with_name("snapshot.saved")
        os.replace(private_path, saved)
        os.replace(foreign, private_path)
        try:
            connection = original_connect(
                database,
                read_only=read_only,
                **kwargs,
            )
        finally:
            os.replace(private_path, foreign)
            os.replace(saved, private_path)
        return connection

    def scan(_connection: duckdb.DuckDBPyConnection) -> ScanReport:
        nonlocal scan_called
        scan_called = True
        return _passing_report()

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_scan_evidence.duckdb.connect",
        swapping_connect,
    )

    with pytest.raises(SuccessorScanEvidenceError, match="exact private snapshot inode"):
        _scanner(scratch, scan)(public)
    assert scan_called is False
    assert [path.name for path in scratch.iterdir()] == []
    assert foreign.is_file()


def test_connect_time_private_parent_swap_back_cannot_scan_foreign_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    foreign_directory = public / "foreign-scan-directory"
    foreign_directory.mkdir(mode=0o700)
    _create_database(foreign_directory / "nba.duckdb", marker="foreign")
    original_connect = duckdb.connect
    scan_called = False

    def swapping_connect(
        database: str,
        *,
        read_only: bool = False,
        **kwargs: object,
    ) -> duckdb.DuckDBPyConnection:
        private_path = Path(database)
        private_directory = private_path.parent
        saved_directory = scratch / ".snapshot-directory-saved"
        assert private_directory.parent == scratch
        os.replace(private_directory, saved_directory)
        os.replace(foreign_directory, private_directory)
        try:
            connection = original_connect(
                database,
                read_only=read_only,
                **kwargs,
            )
        finally:
            os.replace(private_directory, foreign_directory)
            os.replace(saved_directory, private_directory)
        return connection

    def scan(_connection: duckdb.DuckDBPyConnection) -> ScanReport:
        nonlocal scan_called
        scan_called = True
        return _passing_report()

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_scan_evidence.duckdb.connect",
        swapping_connect,
    )

    with pytest.raises(SuccessorScanEvidenceError, match="exact private snapshot inode"):
        _scanner(scratch, scan)(public)
    assert scan_called is False
    assert list(scratch.iterdir()) == []
    assert (foreign_directory / "nba.duckdb").is_file()


def test_unrestored_public_database_swap_fails_closed_and_cleans_temp(
    tmp_path: Path,
) -> None:
    public, scratch, database = _layout(tmp_path)
    evil = public / "evil.duckdb"
    _create_database(evil, marker="evil")
    original = public / "original.duckdb"

    def scan(connection: duckdb.DuckDBPyConnection) -> ScanReport:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("original",)
        os.replace(database, original)
        os.replace(evil, database)
        return _passing_report()

    with pytest.raises(SuccessorScanEvidenceError, match="changed while held"):
        _scanner(scratch, scan)(public)
    assert list(scratch.iterdir()) == []


def test_unrestored_public_root_swap_fails_closed_and_cleans_temp(
    tmp_path: Path,
) -> None:
    public, scratch, _ = _layout(tmp_path)
    old_public = public.parent / "old-public"
    replacement = public.parent / "replacement"
    replacement.mkdir()
    _create_database(replacement / "nba.duckdb", marker="evil")

    def scan(connection: duckdb.DuckDBPyConnection) -> ScanReport:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("original",)
        os.replace(public, old_public)
        os.replace(replacement, public)
        return _passing_report()

    with pytest.raises(SuccessorScanEvidenceError, match="public root changed"):
        _scanner(scratch, scan)(public)
    assert list(scratch.iterdir()) == []


def test_database_symlink_and_special_file_are_rejected(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    scratch = root / "scratch"
    scratch.mkdir(mode=0o700)

    public_symlink = root / "public-symlink"
    public_symlink.mkdir()
    target = public_symlink / "target.duckdb"
    _create_database(target)
    (public_symlink / "nba.duckdb").symlink_to(target)
    with pytest.raises(SuccessorScanEvidenceError, match="opened safely"):
        _scanner(scratch, _scan_marker)(public_symlink)

    public_fifo = root / "public-fifo"
    public_fifo.mkdir()
    os.mkfifo(public_fifo / "nba.duckdb")
    with pytest.raises(SuccessorScanEvidenceError, match="stable regular file"):
        _scanner(scratch, _scan_marker)(public_fifo)
    assert list(scratch.iterdir()) == []


def test_public_root_symlink_is_rejected(tmp_path: Path) -> None:
    public, scratch, _ = _layout(tmp_path)
    public_link = public.parent / "public-link"
    public_link.symlink_to(public, target_is_directory=True)

    with pytest.raises(SuccessorScanEvidenceError, match="opened safely"):
        _scanner(scratch, _scan_marker)(public_link)


def test_oversize_database_and_insufficient_free_space_fail_before_temp(
    tmp_path: Path,
) -> None:
    public, scratch, database = _layout(tmp_path)
    size = database.stat().st_size

    with pytest.raises(
        SuccessorScanEvidenceError,
        match="max_database_bytes",
    ):
        _scanner(
            scratch,
            _scan_marker,
            max_database_bytes=size - 1,
        )(public)
    with pytest.raises(SuccessorScanEvidenceError, match="lacks free space"):
        _scanner(
            scratch,
            _scan_marker,
            minimum_free_bytes=1,
            free_bytes_probe=lambda _descriptor: size,
        )(public)
    assert list(scratch.iterdir()) == []


def test_scan_snapshot_accepts_exact_byte_ceiling(tmp_path: Path) -> None:
    public, scratch, database = _layout(tmp_path)

    result = _scanner(
        scratch,
        _scan_marker,
        max_database_bytes=database.stat().st_size,
    )(public)

    assert result.scan_evidence.status == "passed"
    assert list(scratch.iterdir()) == []


def test_scan_snapshot_short_writes_complete_within_exact_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, scratch, database = _layout(tmp_path)
    original = scan_evidence_module._write_destination

    def short_write(descriptor: int, payload: memoryview) -> int:
        return original(descriptor, payload[: max(1, len(payload) // 2)])

    monkeypatch.setattr(scan_evidence_module, "_write_destination", short_write)

    result = _scanner(
        scratch,
        _scan_marker,
        max_database_bytes=database.stat().st_size,
    )(public)

    assert result.scan_evidence.status == "passed"
    assert list(scratch.iterdir()) == []


def test_scan_snapshot_no_progress_cleans_and_allows_reentry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public, scratch, _database = _layout(tmp_path)
    original = scan_evidence_module._write_destination
    monkeypatch.setattr(
        scan_evidence_module,
        "_write_destination",
        lambda _descriptor, _payload: 0,
    )

    with pytest.raises(SuccessorScanEvidenceError, match="stopped making progress"):
        _scanner(scratch, _scan_marker)(public)
    assert list(scratch.iterdir()) == []

    monkeypatch.setattr(scan_evidence_module, "_write_destination", original)
    result = _scanner(scratch, _scan_marker)(public)
    assert result.scan_evidence.status == "passed"
    assert list(scratch.iterdir()) == []


def test_deadline_headroom_and_clock_regression_fail_closed(tmp_path: Path) -> None:
    public, scratch, _ = _layout(tmp_path)

    with pytest.raises(SuccessorScanEvidenceError, match="deadline headroom"):
        _scanner(
            scratch,
            _scan_marker,
            deadline_monotonic=10,
            headroom_seconds=2,
            monotonic_clock=lambda: 8,
        )(public)

    with pytest.raises(SuccessorScanEvidenceError, match="clock regressed"):
        _scanner(
            scratch,
            _scan_marker,
            monotonic_clock=_clock([2, 1]),
        )(public)
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize("nested", [False, True])
def test_scratch_overlap_is_rejected(tmp_path: Path, nested: bool) -> None:
    root = tmp_path.resolve()
    public = root / "public"
    public.mkdir(mode=0o700)
    _create_database(public / "nba.duckdb")
    scratch = public / "scratch" if nested else public
    if nested:
        scratch.mkdir(mode=0o700)

    with pytest.raises(SuccessorScanEvidenceError, match="overlap"):
        _scanner(scratch, _scan_marker)(public)


def test_scratch_must_be_preprovisioned_owner_only(tmp_path: Path) -> None:
    public, scratch, _ = _layout(tmp_path)
    scratch.chmod(0o755)

    with pytest.raises(SuccessorScanEvidenceError, match="owner-only"):
        _scanner(scratch, _scan_marker)(public)


def test_scratch_root_symlink_is_rejected(tmp_path: Path) -> None:
    public, scratch, _ = _layout(tmp_path)
    scratch_link = scratch.parent / "scratch-link"
    scratch_link.symlink_to(scratch, target_is_directory=True)

    with pytest.raises(SuccessorScanEvidenceError, match="opened safely"):
        _scanner(scratch_link, _scan_marker)(public)


def test_scan_failure_still_cleans_owned_temp(tmp_path: Path) -> None:
    public, scratch, _ = _layout(tmp_path)

    def fail(_connection: duckdb.DuckDBPyConnection) -> ScanReport:
        raise RuntimeError("injected failure")

    with pytest.raises(SuccessorScanEvidenceError, match="scan failed"):
        _scanner(scratch, fail)(public)
    assert list(scratch.iterdir()) == []


def test_invalid_duration_is_rejected_without_affecting_cleanup(tmp_path: Path) -> None:
    public, scratch, _ = _layout(tmp_path)

    with pytest.raises(SuccessorScanEvidenceError, match="duration"):
        _scanner(
            scratch,
            lambda _connection: _passing_report(duration=float("nan")),
        )(public)
    assert list(scratch.iterdir()) == []


def test_production_scan_callable_forwards_full_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[bool] = []
    expected = _passing_report()

    class FakeScanner:
        def __init__(self, connection: object) -> None:
            assert connection is sentinel

        def scan(self, *, full_publication: bool) -> ScanReport:
            observed.append(full_publication)
            return expected

    sentinel = duckdb.connect(":memory:")
    monkeypatch.setattr(
        "nbadb.orchestrate.successor_scan_evidence.DataScanner",
        FakeScanner,
    )

    try:
        assert run_data_scanner_full_publication(sentinel) is expected
        assert observed == [True]
    finally:
        sentinel.close()


def test_constructor_requires_explicit_valid_operational_evidence(tmp_path: Path) -> None:
    scratch = tmp_path.resolve() / "scratch"
    scratch.mkdir(mode=0o700)
    values = {
        "scratch_root": scratch,
        "expected_scratch_root_identity": (scratch.stat().st_dev, scratch.stat().st_ino),
        "max_database_bytes": 1,
        "minimum_free_bytes": 0,
        "deadline_monotonic": 10.0,
        "headroom_seconds": 1.0,
        "monotonic_clock": lambda: 1.0,
        "free_bytes_probe": lambda _descriptor: 1,
        "scan_function": _scan_marker,
    }

    with pytest.raises(
        SuccessorScanEvidenceError,
        match="max_database_bytes",
    ):
        SuccessorFullPublicationScanner(**{**values, "max_database_bytes": 0})
    with pytest.raises(SuccessorScanEvidenceError, match="minimum_free_bytes"):
        SuccessorFullPublicationScanner(**{**values, "minimum_free_bytes": -1})
    with pytest.raises(SuccessorScanEvidenceError, match="deadline_monotonic"):
        SuccessorFullPublicationScanner(**{**values, "deadline_monotonic": float("inf")})
    with pytest.raises(SuccessorScanEvidenceError, match="headroom_seconds"):
        SuccessorFullPublicationScanner(**{**values, "headroom_seconds": 0})
    with pytest.raises(SuccessorScanEvidenceError, match="expected_scratch_root_identity"):
        SuccessorFullPublicationScanner(**{**values, "expected_scratch_root_identity": (1, 0)})


def test_path_free_report_does_not_leak_public_or_scratch_paths(tmp_path: Path) -> None:
    public, scratch, _ = _layout(tmp_path)
    result = _scanner(scratch, _scan_marker)(public)

    assert str(public).encode() not in result.canonical_bytes
    assert str(scratch).encode() not in result.canonical_bytes
    decoded = json.loads(result.canonical_bytes)
    assert set(decoded) == {
        "schema_version",
        "kind",
        "status",
        "fail_on",
        "full_publication",
        "database",
        "summary",
        "w2_database_authority",
        "findings",
    }
