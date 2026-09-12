"""Deterministic full-publication scan evidence for successor candidates.

The public candidate is never scanned by pathname.  This module pins its
``nba.duckdb`` through ``O_NOFOLLOW`` descriptors, copies the exact bytes into
an owned private temporary directory, and opens only that immutable copy in
DuckDB read-only mode.  The resulting report deliberately excludes paths,
wall-clock timestamps, and scan duration.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, ClassVar, Final, Self, cast

import duckdb

from nbadb.orchestrate.scanner import DataScanner, ScanFinding, ScanReport
from nbadb.orchestrate.successor_assurance import SuccessorScanEvidence
from nbadb.orchestrate.successor_inode import (
    directory_inode,
    remove_empty_owned_directory,
)
from nbadb.orchestrate.successor_update_contract import canonical_json_bytes
from nbadb.orchestrate.w2_database_assurance import (
    W2DatabaseAuthorityError,
    W2DatabaseAuthorityReceiptV1,
)

__all__ = [
    "SUCCESSOR_FULL_PUBLICATION_SCAN_KIND",
    "SUCCESSOR_FULL_PUBLICATION_SCAN_SCHEMA_VERSION",
    "SuccessorFullPublicationScanFinding",
    "SuccessorFullPublicationScanResult",
    "SuccessorFullPublicationScanner",
    "SuccessorScanEvidenceError",
    "filesystem_free_bytes",
    "run_data_scanner_full_publication",
]

SUCCESSOR_FULL_PUBLICATION_SCAN_SCHEMA_VERSION: Final = 1
SUCCESSOR_FULL_PUBLICATION_SCAN_KIND: Final = "successor_full_publication_scan"

_DATABASE_NAME: Final = "nba.duckdb"
_MAX_CANONICAL_REPORT_BYTES: Final = 64 * 1024 * 1024
_MAX_FINDINGS: Final = 100_000
_MAX_TEXT_BYTES: Final = 16 * 1024
_MAX_DETAIL_DEPTH: Final = 12
_MAX_DETAIL_ITEMS: Final = 10_000
_COPY_CHUNK_BYTES: Final = 1024 * 1024
_OPEN_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_OPEN_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_OPEN_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK
)
_REGULAR_FLAGS: Final = os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK

_CATEGORIES: Final = frozenset({"cross_table", "temporal", "missing_table", "data_quality"})
_SEVERITIES: Final = frozenset({"error", "warning", "info"})
_SAFE_NAME_CHARACTERS: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.:-")
_ABSOLUTE_PATH_FRAGMENT_RE: Final = re.compile(
    r"(?<![A-Za-z0-9])(?:/[^\s\])},;]*|\\[^\s\])},;]*|[A-Za-z]:[\\/][^\s\])},;]*)"
)

type ScanFunction = Callable[[duckdb.DuckDBPyConnection], ScanReport]
type MonotonicClock = Callable[[], float]
type FreeBytesProbe = Callable[[int], int]


class SuccessorScanEvidenceError(ValueError):
    """Raised when deterministic scan evidence cannot be proven."""


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str] | frozenset[str],
    *,
    label: str,
) -> None:
    actual = set(payload)
    if actual == set(expected):
        return
    missing = sorted(set(expected) - actual)
    unexpected = sorted(actual - set(expected))
    raise SuccessorScanEvidenceError(
        f"{label} fields are invalid: missing={missing}; unexpected={unexpected}"
    )


def _require_nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SuccessorScanEvidenceError(f"{label} must be a nonnegative integer")
    return value


def _require_positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorScanEvidenceError(f"{label} must be a positive integer")
    return value


def _require_finite_number(
    value: object,
    *,
    label: str,
    minimum: float,
    strict: bool,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SuccessorScanEvidenceError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (result <= minimum if strict else result < minimum):
        comparison = "greater than" if strict else "at least"
        raise SuccessorScanEvidenceError(f"{label} must be {comparison} {minimum}")
    return result


def _require_sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SuccessorScanEvidenceError(f"{label} must be a lowercase SHA-256")
    return value


def _looks_absolute(value: str) -> bool:
    lowered = value.casefold()
    return "file://" in lowered or _ABSOLUTE_PATH_FRAGMENT_RE.search(value) is not None


def _require_safe_text(
    value: object,
    *,
    label: str,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise SuccessorScanEvidenceError(f"{label} must be a nonempty string")
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise SuccessorScanEvidenceError(f"{label} exceeds the schema byte limit")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SuccessorScanEvidenceError(f"{label} contains control characters")
    if _looks_absolute(value):
        raise SuccessorScanEvidenceError(f"{label} must not contain an absolute path")
    return value


def _require_safe_name(value: object, *, label: str) -> str:
    text = _require_safe_text(value, label=label)
    if len(text) > 256 or text[0] not in "abcdefghijklmnopqrstuvwxyz":
        raise SuccessorScanEvidenceError(f"{label} is not an exact safe name")
    if any(character not in _SAFE_NAME_CHARACTERS for character in text):
        raise SuccessorScanEvidenceError(f"{label} is not an exact safe name")
    return text


def _freeze_json_value(value: object, *, label: str, depth: int = 0) -> Any:
    if depth > _MAX_DETAIL_DEPTH:
        raise SuccessorScanEvidenceError(f"{label} exceeds the maximum detail depth")
    if value is None or type(value) in {bool, int}:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SuccessorScanEvidenceError(f"{label} contains a non-finite number")
        return value
    if isinstance(value, str):
        return _require_safe_text(value, label=label, allow_empty=True)
    if isinstance(value, Mapping):
        if len(value) > _MAX_DETAIL_ITEMS:
            raise SuccessorScanEvidenceError(f"{label} has too many entries")
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            safe_key = _require_safe_name(key, label=f"{label} key")
            if safe_key in normalized:
                raise SuccessorScanEvidenceError(f"{label} contains a duplicate key")
            normalized[safe_key] = _freeze_json_value(
                child,
                label=f"{label}.{safe_key}",
                depth=depth + 1,
            )
        return normalized
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_DETAIL_ITEMS:
            raise SuccessorScanEvidenceError(f"{label} has too many items")
        return [
            _freeze_json_value(
                child,
                label=f"{label}[{index}]",
                depth=depth + 1,
            )
            for index, child in enumerate(value)
        ]
    raise SuccessorScanEvidenceError(f"{label} contains a non-JSON-safe value")


def _canonical_details(value: object, *, label: str) -> bytes:
    frozen = _freeze_json_value(value, label=label)
    return canonical_json_bytes(frozen)


@dataclass(frozen=True, slots=True)
class SuccessorFullPublicationScanFinding:
    """One strictly canonical, path-free scan finding."""

    category: str
    severity: str
    table: str
    check: str
    message: str
    details_canonical_bytes: bytes | None = None

    def __post_init__(self) -> None:
        if self.category not in _CATEGORIES:
            raise SuccessorScanEvidenceError("scan finding category is invalid")
        if self.severity not in _SEVERITIES:
            raise SuccessorScanEvidenceError("scan finding severity is invalid")
        _require_safe_name(self.table, label="scan finding table")
        _require_safe_name(self.check, label="scan finding check")
        _require_safe_text(self.message, label="scan finding message")
        encoded = self.details_canonical_bytes
        if encoded is None:
            return
        if type(encoded) is not bytes:
            raise SuccessorScanEvidenceError("scan finding details must be canonical bytes")
        if len(encoded) > _MAX_CANONICAL_REPORT_BYTES:
            raise SuccessorScanEvidenceError("scan finding details exceed the schema byte limit")
        try:
            payload = _strict_json_loads(encoded, label="scan finding details")
        except SuccessorScanEvidenceError:
            raise
        normalized = _freeze_json_value(payload, label="scan finding details")
        if canonical_json_bytes(normalized) != encoded:
            raise SuccessorScanEvidenceError("scan finding details are not canonical JSON")

    @classmethod
    def from_scan_finding(cls, finding: ScanFinding) -> Self:
        if not isinstance(finding, ScanFinding):
            raise SuccessorScanEvidenceError("scan finding shape is invalid")
        category = finding.category
        severity = finding.severity
        table = finding.table
        check = finding.check
        message = finding.message
        details = finding.details
        return cls(
            category=category,
            severity=severity,
            table=table,
            check=check,
            message=message,
            details_canonical_bytes=(
                None
                if details is None
                else _canonical_details(details, label="scan finding details")
            ),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {"category", "severity", "table", "check", "message", "details"},
            label="scan finding",
        )
        category = payload["category"]
        severity = payload["severity"]
        table = payload["table"]
        check = payload["check"]
        message = payload["message"]
        if not all(isinstance(value, str) for value in (category, severity, table, check, message)):
            raise SuccessorScanEvidenceError("scan finding string fields are invalid")
        details = payload["details"]
        return cls(
            category=cast("str", category),
            severity=cast("str", severity),
            table=cast("str", table),
            check=cast("str", check),
            message=cast("str", message),
            details_canonical_bytes=(
                None
                if details is None
                else _canonical_details(details, label="scan finding details")
            ),
        )

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        details: object = None
        if self.details_canonical_bytes is not None:
            details = _strict_json_loads(
                self.details_canonical_bytes,
                label="scan finding details",
            )
        return {
            "category": self.category,
            "severity": self.severity,
            "table": self.table,
            "check": self.check,
            "message": self.message,
            "details": details,
        }


@dataclass(frozen=True, slots=True)
class SuccessorFullPublicationScanResult:
    """Path-free canonical authority for one immutable database scan."""

    database_sha256: str
    database_bytes: int
    tables_scanned: int
    checks_run: int
    w2_database_authority: W2DatabaseAuthorityReceiptV1
    findings: tuple[SuccessorFullPublicationScanFinding, ...]
    report_sha256: str = field(init=False)
    scan_evidence: SuccessorScanEvidence = field(init=False)

    schema_version: ClassVar[int] = SUCCESSOR_FULL_PUBLICATION_SCAN_SCHEMA_VERSION
    kind: ClassVar[str] = SUCCESSOR_FULL_PUBLICATION_SCAN_KIND

    def __post_init__(self) -> None:
        _require_sha256(self.database_sha256, label="scan database_sha256")
        _require_positive_int(self.database_bytes, label="scan database_bytes")
        _require_nonnegative_int(self.tables_scanned, label="scan tables_scanned")
        _require_nonnegative_int(self.checks_run, label="scan checks_run")
        if type(self.w2_database_authority) is not W2DatabaseAuthorityReceiptV1:
            raise SuccessorScanEvidenceError(
                "scan W2 database authority must be the exact typed receipt"
            )
        try:
            replayed_w2 = W2DatabaseAuthorityReceiptV1.from_canonical_bytes(
                self.w2_database_authority.canonical_bytes()
            )
        except W2DatabaseAuthorityError as exc:
            raise SuccessorScanEvidenceError(
                "scan W2 database authority failed exact canonical replay"
            ) from exc
        if replayed_w2 != self.w2_database_authority:
            raise SuccessorScanEvidenceError(
                "scan W2 database authority differs after canonical replay"
            )
        if not isinstance(self.findings, tuple) or len(self.findings) > _MAX_FINDINGS:
            raise SuccessorScanEvidenceError("scan findings must be a bounded tuple")
        if not all(
            isinstance(finding, SuccessorFullPublicationScanFinding) for finding in self.findings
        ):
            raise SuccessorScanEvidenceError("scan findings are not fully validated")
        expected = tuple(sorted(self.findings, key=lambda finding: finding.canonical_bytes))
        if self.findings != expected:
            raise SuccessorScanEvidenceError("scan findings are not canonically sorted")
        canonical_findings = tuple(finding.canonical_bytes for finding in self.findings)
        if len(canonical_findings) != len(set(canonical_findings)):
            raise SuccessorScanEvidenceError("scan findings contain duplicates")
        error_count = sum(finding.severity == "error" for finding in self.findings)
        if error_count:
            raise SuccessorScanEvidenceError("full-publication scan contains errors")
        encoded = self.canonical_bytes
        if len(encoded) > _MAX_CANONICAL_REPORT_BYTES:
            raise SuccessorScanEvidenceError("successor scan report exceeds the schema byte limit")
        report_sha256 = hashlib.sha256(encoded).hexdigest()
        object.__setattr__(self, "report_sha256", report_sha256)
        object.__setattr__(
            self,
            "scan_evidence",
            SuccessorScanEvidence(
                report_sha256=report_sha256,
                status="passed",
                fail_on="error",
                full_publication=True,
                error_count=0,
            ),
        )

    @classmethod
    def from_scan_report(
        cls,
        report: ScanReport,
        *,
        database_sha256: str,
        database_bytes: int,
    ) -> Self:
        if not isinstance(report, ScanReport):
            raise SuccessorScanEvidenceError("scan function did not return a ScanReport")
        if not isinstance(report.findings, list) or len(report.findings) > _MAX_FINDINGS:
            raise SuccessorScanEvidenceError("scan findings must be a bounded list")
        if type(report.evidence) is not dict:
            raise SuccessorScanEvidenceError("scan evidence must be one exact built-in mapping")
        w2_payload = report.evidence.get("w2_database_authority")
        try:
            w2_database_authority = W2DatabaseAuthorityReceiptV1.from_dict(w2_payload)
        except W2DatabaseAuthorityError as exc:
            raise SuccessorScanEvidenceError(
                "scan lacks an exact typed W2 database authority receipt"
            ) from exc
        _require_finite_number(
            report.duration_seconds,
            label="scan duration_seconds",
            minimum=0.0,
            strict=False,
        )
        findings = tuple(
            sorted(
                (
                    SuccessorFullPublicationScanFinding.from_scan_finding(finding)
                    for finding in report.findings
                ),
                key=lambda finding: finding.canonical_bytes,
            )
        )
        return cls(
            database_sha256=database_sha256,
            database_bytes=database_bytes,
            tables_scanned=report.tables_scanned,
            checks_run=report.checks_run,
            w2_database_authority=w2_database_authority,
            findings=findings,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "schema_version",
                "kind",
                "status",
                "fail_on",
                "full_publication",
                "database",
                "summary",
                "w2_database_authority",
                "findings",
            },
            label="successor scan report",
        )
        if payload["schema_version"] != cls.schema_version or payload["kind"] != cls.kind:
            raise SuccessorScanEvidenceError("successor scan schema or kind is invalid")
        if (
            payload["status"] != "passed"
            or payload["fail_on"] != "error"
            or payload["full_publication"] is not True
        ):
            raise SuccessorScanEvidenceError("successor scan did not pass fail-on-error assurance")
        database = _require_mapping(payload["database"], label="scan database")
        _require_exact_keys(database, {"sha256", "bytes"}, label="scan database")
        summary = _require_mapping(payload["summary"], label="scan summary")
        _require_exact_keys(
            summary,
            {"total", "error", "warning", "info", "tables_scanned", "checks_run"},
            label="scan summary",
        )
        finding_payloads = payload["findings"]
        if not isinstance(finding_payloads, list) or len(finding_payloads) > _MAX_FINDINGS:
            raise SuccessorScanEvidenceError("scan findings must be a bounded list")
        findings = tuple(
            SuccessorFullPublicationScanFinding.from_dict(
                _require_mapping(item, label=f"scan finding[{index}]")
            )
            for index, item in enumerate(finding_payloads)
        )
        try:
            w2_database_authority = W2DatabaseAuthorityReceiptV1.from_dict(
                payload["w2_database_authority"]
            )
        except W2DatabaseAuthorityError as exc:
            raise SuccessorScanEvidenceError(
                "successor scan W2 database authority is invalid"
            ) from exc
        result = cls(
            database_sha256=_require_sha256(database["sha256"], label="scan database_sha256"),
            database_bytes=_require_positive_int(database["bytes"], label="scan database_bytes"),
            tables_scanned=_require_nonnegative_int(
                summary["tables_scanned"], label="scan tables_scanned"
            ),
            checks_run=_require_nonnegative_int(summary["checks_run"], label="scan checks_run"),
            w2_database_authority=w2_database_authority,
            findings=findings,
        )
        if result._summary() != dict(summary):
            raise SuccessorScanEvidenceError("scan summary differs from its findings")
        return result

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        if type(encoded) is not bytes:
            raise SuccessorScanEvidenceError("successor scan report must be bytes")
        if len(encoded) > _MAX_CANONICAL_REPORT_BYTES:
            raise SuccessorScanEvidenceError("successor scan report exceeds the schema byte limit")
        if not encoded.endswith(b"\n") or encoded.endswith(b"\n\n"):
            raise SuccessorScanEvidenceError("successor scan report is not canonical JSON")
        payload = _strict_json_loads(encoded[:-1], label="successor scan report")
        result = cls.from_dict(_require_mapping(payload, label="successor scan report"))
        if result.canonical_bytes != encoded:
            raise SuccessorScanEvidenceError("successor scan report is not canonical JSON")
        return result

    def _summary(self) -> dict[str, int]:
        warning_count = sum(finding.severity == "warning" for finding in self.findings)
        info_count = sum(finding.severity == "info" for finding in self.findings)
        return {
            "total": len(self.findings),
            "error": 0,
            "warning": warning_count,
            "info": info_count,
            "tables_scanned": self.tables_scanned,
            "checks_run": self.checks_run,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"

    @property
    def content_sha256(self) -> str:
        return self.report_sha256

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "status": "passed",
            "fail_on": "error",
            "full_publication": True,
            "database": {
                "sha256": self.database_sha256,
                "bytes": self.database_bytes,
            },
            "summary": self._summary(),
            "w2_database_authority": self.w2_database_authority.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SuccessorScanEvidenceError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _reject_json_constant(value: str) -> object:
    raise SuccessorScanEvidenceError(f"JSON constant is not finite: {value}")


def _strict_json_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise SuccessorScanEvidenceError(f"JSON object contains duplicate key: {key}")
        payload[key] = value
    return payload


def _strict_json_loads(encoded: bytes, *, label: str) -> object:
    try:
        text = encoded.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise SuccessorScanEvidenceError(f"{label} is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise SuccessorScanEvidenceError(f"{label} is not valid JSON") from exc


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid)


def _open_absolute_directory(path: Path, *, label: str) -> tuple[int, os.stat_result]:
    if os.name != "posix" or not _OPEN_NOFOLLOW:
        raise SuccessorScanEvidenceError("successor scanning requires POSIX O_NOFOLLOW")
    if not isinstance(path, Path) or not path.is_absolute():
        raise SuccessorScanEvidenceError(f"{label} must be an absolute Path")
    absolute = Path(os.path.abspath(path))
    parts = PurePath(absolute).parts
    descriptor = -1
    try:
        descriptor = os.open(parts[0], _DIRECTORY_FLAGS)
        for component in parts[1:]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        opened = os.fstat(descriptor)
        named = os.stat(absolute, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise SuccessorScanEvidenceError(f"{label} changed while opening")
        return descriptor, opened
    except (OSError, ValueError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if isinstance(exc, SuccessorScanEvidenceError):
            raise
        raise SuccessorScanEvidenceError(f"{label} cannot be opened safely") from exc


def _open_named_regular(
    directory_descriptor: int,
    name: str,
    *,
    label: str,
) -> tuple[int, os.stat_result]:
    descriptor = -1
    try:
        descriptor = os.open(name, _REGULAR_FLAGS, dir_fd=directory_descriptor)
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise SuccessorScanEvidenceError(f"{label} must be a stable regular file")
        return descriptor, opened
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise SuccessorScanEvidenceError(f"{label} cannot be opened safely") from exc


def _require_same_named_regular(
    directory_descriptor: int,
    name: str,
    descriptor: int,
    expected: os.stat_result,
    *,
    label: str,
) -> None:
    try:
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorScanEvidenceError(f"{label} changed while held") from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(named.st_mode)
        or _stat_identity(opened) != _stat_identity(expected)
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
    ):
        raise SuccessorScanEvidenceError(f"{label} changed while held")


def _require_same_directory(
    path: Path,
    descriptor: int,
    expected: os.stat_result,
    *,
    label: str,
) -> None:
    try:
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorScanEvidenceError(f"{label} changed while held") from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or _directory_identity(opened) != _directory_identity(expected)
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
    ):
        raise SuccessorScanEvidenceError(f"{label} changed while held")


def _require_private_scratch(value: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) & 0o077
        or stat.S_IMODE(value.st_mode) & 0o700 != 0o700
    ):
        raise SuccessorScanEvidenceError(
            "successor scan scratch root must be owner-only and owner-accessible"
        )


def _reject_root_overlap(
    public_root: Path,
    public_stat: os.stat_result,
    scratch_root: Path,
    scratch_stat: os.stat_result,
) -> None:
    if (public_stat.st_dev, public_stat.st_ino) == (scratch_stat.st_dev, scratch_stat.st_ino):
        raise SuccessorScanEvidenceError("successor scan scratch and public roots overlap")
    public = Path(os.path.abspath(public_root))
    scratch = Path(os.path.abspath(scratch_root))
    try:
        common = Path(os.path.commonpath((public, scratch)))
    except ValueError as exc:
        raise SuccessorScanEvidenceError("successor scan root comparison failed") from exc
    if common in {public, scratch}:
        raise SuccessorScanEvidenceError("successor scan scratch and public roots overlap")
    public_parts = tuple(part.casefold() for part in public.parts)
    scratch_parts = tuple(part.casefold() for part in scratch.parts)
    if (
        public_parts[: len(scratch_parts)] == scratch_parts
        or scratch_parts[: len(public_parts)] == public_parts
    ):
        raise SuccessorScanEvidenceError("successor scan scratch and public roots overlap")


def _hash_descriptor(descriptor: int, *, label: str) -> tuple[int, str, os.stat_result]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise SuccessorScanEvidenceError(f"{label} must be a regular file")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    observed = 0
    while chunk := os.read(descriptor, _COPY_CHUNK_BYTES):
        digest.update(chunk)
        observed += len(chunk)
    after = os.fstat(descriptor)
    if _stat_identity(before) != _stat_identity(after) or observed != before.st_size:
        raise SuccessorScanEvidenceError(f"{label} changed while hashing")
    return observed, digest.hexdigest(), after


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = _write_destination(descriptor, view)
        if written <= 0:
            raise SuccessorScanEvidenceError("private database copy stopped making progress")
        view = view[written:]


def _write_destination(descriptor: int, payload: memoryview) -> int:
    return os.write(descriptor, payload)


def _prove_snapshot_flock_available(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as exc:
        raise SuccessorScanEvidenceError(
            "private database snapshot does not support the required flock contract"
        ) from exc


def _require_duckdb_shared_snapshot_lock(descriptor: int, *, stage: str) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
            return
        raise SuccessorScanEvidenceError(f"DuckDB snapshot lock proof failed at {stage}") from exc
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    raise SuccessorScanEvidenceError(
        f"DuckDB is not locked to the exact private snapshot inode at {stage}"
    )


def _require_duckdb_snapshot_lock_released(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as exc:
        raise SuccessorScanEvidenceError(
            "DuckDB did not release the exact private snapshot inode"
        ) from exc


def _copy_database(
    source_descriptor: int,
    source_before: os.stat_result,
    destination_descriptor: int,
    *,
    max_bytes: int,
) -> tuple[int, str, os.stat_result]:
    os.lseek(source_descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    observed = 0
    while chunk := os.read(source_descriptor, _COPY_CHUNK_BYTES):
        if len(chunk) > max_bytes - observed:
            raise SuccessorScanEvidenceError(
                "source database exceeds scan_database_snapshot_max_bytes while copying"
            )
        _write_all(destination_descriptor, chunk)
        digest.update(chunk)
        observed += len(chunk)
        if observed > source_before.st_size:
            raise SuccessorScanEvidenceError("source database grew while copying")
    os.fsync(destination_descriptor)
    source_after = os.fstat(source_descriptor)
    if _stat_identity(source_before) != _stat_identity(source_after):
        raise SuccessorScanEvidenceError("source database changed while copying")
    if observed != source_before.st_size:
        raise SuccessorScanEvidenceError("source database byte count changed while copying")
    return observed, digest.hexdigest(), source_after


def _reserve_private_temp(
    scratch_descriptor: int,
) -> tuple[str, int, os.stat_result]:
    for _ in range(128):
        name = f".successor-scan-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=scratch_descriptor)
        except FileExistsError:
            continue
        descriptor = -1
        expected_inode: tuple[int, int] | None = None
        try:
            descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=scratch_descriptor)
            opened = os.fstat(descriptor)
            expected_inode = directory_inode(opened)
            named = os.stat(name, dir_fd=scratch_descriptor, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or directory_inode(opened) != directory_inode(named)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) != 0o700
            ):
                raise SuccessorScanEvidenceError("private scan temporary directory is invalid")
            return name, descriptor, opened
        except BaseException:
            if descriptor >= 0:
                try:
                    if expected_inode is None:
                        expected_inode = directory_inode(os.fstat(descriptor))
                    remove_empty_owned_directory(
                        scratch_descriptor,
                        name,
                        descriptor,
                        expected_inode=expected_inode,
                        error=SuccessorScanEvidenceError,
                        label="private scan temporary directory reservation",
                    )
                except (OSError, SuccessorScanEvidenceError):
                    pass
                finally:
                    os.close(descriptor)
            raise
    raise SuccessorScanEvidenceError("private scan temporary directory cannot be reserved")


def _open_private_destination(temp_descriptor: int) -> tuple[int, os.stat_result]:
    descriptor = -1
    try:
        descriptor = os.open(
            _DATABASE_NAME,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
            0o600,
            dir_fd=temp_descriptor,
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise SuccessorScanEvidenceError("private database copy is invalid")
        return descriptor, opened
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise SuccessorScanEvidenceError("private database copy cannot be created") from exc


def _require_named_directory(
    parent_descriptor: int,
    name: str,
    descriptor: int,
    expected: os.stat_result,
    *,
    label: str,
) -> None:
    try:
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorScanEvidenceError(f"{label} changed while held") from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(named.st_mode)
        or _directory_identity(opened) != _directory_identity(expected)
        or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
    ):
        raise SuccessorScanEvidenceError(f"{label} changed while held")


def _cleanup_private_temp(
    scratch_descriptor: int,
    temp_name: str,
    temp_descriptor: int,
    temp_identity: os.stat_result,
    destination_descriptor: int,
    destination_identity: tuple[int, int] | None,
) -> None:
    try:
        name_error: BaseException | None = None
        try:
            _require_named_directory(
                scratch_descriptor,
                temp_name,
                temp_descriptor,
                temp_identity,
                label="private scan temporary directory at cleanup admission",
            )
        except BaseException as exc:
            name_error = exc
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
            destination_descriptor = -1
        if destination_identity is not None:
            named = os.stat(_DATABASE_NAME, dir_fd=temp_descriptor, follow_symlinks=False)
            if (
                not stat.S_ISREG(named.st_mode)
                or (named.st_dev, named.st_ino) != destination_identity
            ):
                raise SuccessorScanEvidenceError("private database copy changed before cleanup")
        with os.scandir(temp_descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
        expected_names = [] if destination_identity is None else [_DATABASE_NAME]
        if names != expected_names:
            raise SuccessorScanEvidenceError("private scan directory contains unexpected entries")
        if destination_identity is not None:
            os.unlink(_DATABASE_NAME, dir_fd=temp_descriptor)
        with os.scandir(temp_descriptor) as iterator:
            if any(True for _ in iterator):
                raise SuccessorScanEvidenceError("private scan directory is not empty")
        if name_error is not None:
            raise name_error
        _require_named_directory(
            scratch_descriptor,
            temp_name,
            temp_descriptor,
            temp_identity,
            label="private scan temporary directory before cleanup removal",
        )
        remove_empty_owned_directory(
            scratch_descriptor,
            temp_name,
            temp_descriptor,
            expected_inode=directory_inode(temp_identity),
            error=SuccessorScanEvidenceError,
            label="private scan temporary directory before cleanup removal",
        )
    finally:
        if destination_descriptor >= 0:
            os.close(destination_descriptor)
        os.close(temp_descriptor)


def filesystem_free_bytes(directory_descriptor: int) -> int:
    """Return descriptor-bound writable free bytes for an explicit filesystem."""

    if type(directory_descriptor) is not int or directory_descriptor < 0:
        raise SuccessorScanEvidenceError("free-space descriptor is invalid")
    observed = os.fstatvfs(directory_descriptor)
    return observed.f_bavail * observed.f_frsize


def run_data_scanner_full_publication(
    connection: duckdb.DuckDBPyConnection,
) -> ScanReport:
    """Run the repository hard scan on an already read-only DuckDB connection."""

    if not isinstance(connection, duckdb.DuckDBPyConnection):
        raise SuccessorScanEvidenceError("scan connection must be a DuckDB connection")
    return DataScanner(connection).scan(full_publication=True)


@dataclass(frozen=True, slots=True)
class SuccessorFullPublicationScanner:
    """Callable, descriptor-safe full-publication scanner for assurance builders."""

    scratch_root: Path
    expected_scratch_root_identity: tuple[int, int]
    max_database_bytes: int
    minimum_free_bytes: int
    deadline_monotonic: float
    headroom_seconds: float
    monotonic_clock: MonotonicClock
    free_bytes_probe: FreeBytesProbe
    scan_function: ScanFunction

    def __post_init__(self) -> None:
        if not isinstance(self.scratch_root, Path) or not self.scratch_root.is_absolute():
            raise SuccessorScanEvidenceError("scratch_root must be an absolute Path")
        if (
            type(self.expected_scratch_root_identity) is not tuple
            or len(self.expected_scratch_root_identity) != 2
            or any(
                type(value) is not int or value < 0 for value in self.expected_scratch_root_identity
            )
            or self.expected_scratch_root_identity[1] == 0
        ):
            raise SuccessorScanEvidenceError("expected_scratch_root_identity is invalid")
        _require_positive_int(self.max_database_bytes, label="max_database_bytes")
        _require_nonnegative_int(self.minimum_free_bytes, label="minimum_free_bytes")
        _require_finite_number(
            self.deadline_monotonic,
            label="deadline_monotonic",
            minimum=0.0,
            strict=True,
        )
        _require_finite_number(
            self.headroom_seconds,
            label="headroom_seconds",
            minimum=0.0,
            strict=True,
        )
        if not callable(self.monotonic_clock):
            raise SuccessorScanEvidenceError("monotonic_clock must be callable")
        if not callable(self.free_bytes_probe):
            raise SuccessorScanEvidenceError("free_bytes_probe must be callable")
        if not callable(self.scan_function):
            raise SuccessorScanEvidenceError("scan_function must be callable")

    def _require_time_headroom(
        self,
        *,
        stage: str,
        previous: float | None,
    ) -> float:
        try:
            clock_value = self.monotonic_clock()
        except Exception as exc:
            raise SuccessorScanEvidenceError(f"monotonic clock failed at {stage}") from exc
        observed = _require_finite_number(
            clock_value,
            label=f"monotonic clock at {stage}",
            minimum=0.0,
            strict=False,
        )
        if previous is not None and observed < previous:
            raise SuccessorScanEvidenceError(f"monotonic clock regressed at {stage}")
        if observed + self.headroom_seconds >= self.deadline_monotonic:
            raise SuccessorScanEvidenceError(f"successor scan lacks deadline headroom at {stage}")
        return observed

    def _free_bytes(self, descriptor: int, *, stage: str) -> int:
        try:
            observed = self.free_bytes_probe(descriptor)
        except Exception as exc:
            raise SuccessorScanEvidenceError(
                f"successor scan free-space probe failed at {stage}"
            ) from exc
        return _require_nonnegative_int(observed, label=f"free bytes at {stage}")

    def __call__(
        self,
        public_root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> SuccessorFullPublicationScanResult:
        if not isinstance(public_root, Path) or not public_root.is_absolute():
            raise SuccessorScanEvidenceError("public_root must be an absolute Path")
        if expected_root_identity is not None and (
            type(expected_root_identity) is not tuple
            or len(expected_root_identity) != 2
            or any(type(value) is not int or value < 0 for value in expected_root_identity)
        ):
            raise SuccessorScanEvidenceError("expected_root_identity is invalid")
        last_monotonic = self._require_time_headroom(
            stage="admission",
            previous=None,
        )

        public_descriptor = scratch_descriptor = source_descriptor = -1
        temp_descriptor = destination_descriptor = -1
        temp_name: str | None = None
        temp_before: os.stat_result | None = None
        cleanup_identity: tuple[int, int] | None = None
        public_before: os.stat_result | None = None
        scratch_before: os.stat_result | None = None
        source_before: os.stat_result | None = None
        result: SuccessorFullPublicationScanResult | None = None
        primary_error: BaseException | None = None
        try:
            public_descriptor, public_before = _open_absolute_directory(
                public_root,
                label="successor public root",
            )
            if (
                expected_root_identity is not None
                and (public_before.st_dev, public_before.st_ino) != expected_root_identity
            ):
                raise SuccessorScanEvidenceError(
                    "successor public root differs from expected authority"
                )
            scratch_descriptor, scratch_before = _open_absolute_directory(
                self.scratch_root,
                label="successor scan scratch root",
            )
            if (
                scratch_before.st_dev,
                scratch_before.st_ino,
            ) != self.expected_scratch_root_identity:
                raise SuccessorScanEvidenceError(
                    "successor scan scratch root differs from expected authority"
                )
            _require_private_scratch(scratch_before)
            _reject_root_overlap(
                public_root,
                public_before,
                self.scratch_root,
                scratch_before,
            )
            source_descriptor, source_before = _open_named_regular(
                public_descriptor,
                _DATABASE_NAME,
                label="successor public nba.duckdb",
            )
            database_bytes = _require_positive_int(
                source_before.st_size,
                label="successor public nba.duckdb bytes",
            )
            if database_bytes > self.max_database_bytes:
                raise SuccessorScanEvidenceError(
                    "successor public nba.duckdb exceeds max_database_bytes"
                )
            free_before = self._free_bytes(scratch_descriptor, stage="before copy")
            if free_before < self.minimum_free_bytes + database_bytes:
                raise SuccessorScanEvidenceError(
                    "successor scan scratch lacks free space for the database and retained floor"
                )
            last_monotonic = self._require_time_headroom(
                stage="before copy",
                previous=last_monotonic,
            )

            temp_name, temp_descriptor, temp_before = _reserve_private_temp(scratch_descriptor)
            destination_descriptor, destination_created = _open_private_destination(temp_descriptor)
            cleanup_identity = (
                destination_created.st_dev,
                destination_created.st_ino,
            )
            copied_bytes, copied_sha256, source_after = _copy_database(
                source_descriptor,
                source_before,
                destination_descriptor,
                max_bytes=self.max_database_bytes,
            )
            _require_same_named_regular(
                public_descriptor,
                _DATABASE_NAME,
                source_descriptor,
                source_after,
                label="successor public nba.duckdb",
            )
            os.fchmod(destination_descriptor, 0o400)
            destination_before = os.fstat(destination_descriptor)
            if (
                destination_before.st_uid != os.geteuid()
                or stat.S_IMODE(destination_before.st_mode) != 0o400
            ):
                raise SuccessorScanEvidenceError("private database copy is not owner-read-only")
            private_bytes, private_sha256, destination_after_hash = _hash_descriptor(
                destination_descriptor,
                label="private database copy",
            )
            if (
                copied_bytes != private_bytes
                or copied_sha256 != private_sha256
                or copied_bytes != database_bytes
            ):
                raise SuccessorScanEvidenceError("private database copy differs from its source")
            _require_same_named_regular(
                temp_descriptor,
                _DATABASE_NAME,
                destination_descriptor,
                destination_after_hash,
                label="private database copy",
            )
            cleanup_identity = (
                destination_after_hash.st_dev,
                destination_after_hash.st_ino,
            )
            _prove_snapshot_flock_available(destination_descriptor)
            if self._free_bytes(scratch_descriptor, stage="after copy") < self.minimum_free_bytes:
                raise SuccessorScanEvidenceError(
                    "successor scan scratch fell below its retained free-space floor"
                )
            last_monotonic = self._require_time_headroom(
                stage="before engine open",
                previous=last_monotonic,
            )
            _require_same_directory(
                public_root,
                public_descriptor,
                public_before,
                label="successor public root",
            )
            _require_same_directory(
                self.scratch_root,
                scratch_descriptor,
                scratch_before,
                label="successor scan scratch root",
            )
            _require_named_directory(
                scratch_descriptor,
                temp_name,
                temp_descriptor,
                temp_before,
                label="private scan temporary directory",
            )

            private_database_path = self.scratch_root / temp_name / _DATABASE_NAME
            connection: duckdb.DuckDBPyConnection | None = None
            engine_error: BaseException | None = None
            try:
                connection = duckdb.connect(str(private_database_path), read_only=True)
                _require_duckdb_shared_snapshot_lock(
                    destination_descriptor,
                    stage="after engine open",
                )
                report = self.scan_function(connection)
                _require_duckdb_shared_snapshot_lock(
                    destination_descriptor,
                    stage="after engine scan",
                )
            except BaseException as exc:
                engine_error = exc
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except BaseException as exc:
                        if engine_error is None:
                            engine_error = exc
                        else:
                            engine_error = SuccessorScanEvidenceError(
                                "full-publication scan and DuckDB close both failed"
                            )
                    try:
                        _require_duckdb_snapshot_lock_released(destination_descriptor)
                    except BaseException as exc:
                        if engine_error is None:
                            engine_error = exc
                        else:
                            engine_error = SuccessorScanEvidenceError(
                                "full-publication scan and DuckDB lock release both failed"
                            )
            if engine_error is not None:
                if isinstance(engine_error, SuccessorScanEvidenceError):
                    raise engine_error
                if not isinstance(engine_error, Exception):
                    raise engine_error
                raise SuccessorScanEvidenceError("full-publication scan failed") from engine_error
            last_monotonic = self._require_time_headroom(
                stage="after engine scan",
                previous=last_monotonic,
            )

            final_private_bytes, final_private_sha256, final_private_stat = _hash_descriptor(
                destination_descriptor,
                label="private database copy",
            )
            if (
                final_private_bytes != copied_bytes
                or final_private_sha256 != copied_sha256
                or _stat_identity(final_private_stat) != _stat_identity(destination_after_hash)
            ):
                raise SuccessorScanEvidenceError("private database copy changed while scanning")
            _require_same_named_regular(
                temp_descriptor,
                _DATABASE_NAME,
                destination_descriptor,
                destination_after_hash,
                label="private database copy",
            )
            _require_same_named_regular(
                public_descriptor,
                _DATABASE_NAME,
                source_descriptor,
                source_before,
                label="successor public nba.duckdb",
            )
            _require_same_directory(
                public_root,
                public_descriptor,
                public_before,
                label="successor public root",
            )
            result = SuccessorFullPublicationScanResult.from_scan_report(
                report,
                database_sha256=copied_sha256,
                database_bytes=copied_bytes,
            )
        except BaseException as exc:
            primary_error = exc
        finally:
            cleanup_error: BaseException | None = None
            if (
                temp_name is not None
                and temp_descriptor >= 0
                and temp_before is not None
                and scratch_descriptor >= 0
            ):
                try:
                    _cleanup_private_temp(
                        scratch_descriptor,
                        temp_name,
                        temp_descriptor,
                        temp_before,
                        destination_descriptor,
                        cleanup_identity,
                    )
                    temp_descriptor = -1
                    destination_descriptor = -1
                except BaseException as exc:
                    cleanup_error = exc
            else:
                if destination_descriptor >= 0:
                    os.close(destination_descriptor)
                    destination_descriptor = -1
                if temp_descriptor >= 0:
                    os.close(temp_descriptor)
                    temp_descriptor = -1
                if temp_name is not None and scratch_descriptor >= 0:
                    cleanup_error = SuccessorScanEvidenceError(
                        "private scan temporary directory lacks cleanup authority"
                    )
            try:
                if public_descriptor >= 0 and public_before is not None:
                    _require_same_directory(
                        public_root,
                        public_descriptor,
                        public_before,
                        label="successor public root",
                    )
                if public_descriptor >= 0 and source_descriptor >= 0 and source_before is not None:
                    _require_same_named_regular(
                        public_descriptor,
                        _DATABASE_NAME,
                        source_descriptor,
                        source_before,
                        label="successor public nba.duckdb",
                    )
                if scratch_descriptor >= 0 and scratch_before is not None:
                    _require_same_directory(
                        self.scratch_root,
                        scratch_descriptor,
                        scratch_before,
                        label="successor scan scratch root",
                    )
                    if (
                        primary_error is None
                        and cleanup_error is None
                        and self._free_bytes(
                            scratch_descriptor,
                            stage="after cleanup",
                        )
                        < self.minimum_free_bytes
                    ):
                        raise SuccessorScanEvidenceError(
                            "successor scan scratch is below its final free-space floor"
                        )
                    if primary_error is None and cleanup_error is None:
                        last_monotonic = self._require_time_headroom(
                            stage="after cleanup",
                            previous=last_monotonic,
                        )
            except BaseException as exc:
                if cleanup_error is None and primary_error is None:
                    cleanup_error = exc
            if source_descriptor >= 0:
                os.close(source_descriptor)
            if scratch_descriptor >= 0:
                os.close(scratch_descriptor)
            if public_descriptor >= 0:
                os.close(public_descriptor)
            if cleanup_error is not None:
                if primary_error is not None:
                    raise SuccessorScanEvidenceError(
                        "successor scan failed and private cleanup or final identity "
                        "verification failed"
                    ) from cleanup_error
                raise cleanup_error
        if primary_error is not None:
            if isinstance(primary_error, SuccessorScanEvidenceError):
                raise primary_error
            if not isinstance(primary_error, Exception):
                raise primary_error
            raise SuccessorScanEvidenceError(
                "successor full-publication scan failed"
            ) from primary_error
        if result is None:
            raise SuccessorScanEvidenceError("successor full-publication scan produced no result")
        return result
