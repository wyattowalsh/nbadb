"""Pure fail-closed selection authority for an ``nba-api`` release.

Collection is deliberately out of scope for this module.  Callers inject the
exact official PyPI response bytes and canonical receipts produced by their
network, subprocess, and authenticated clock collectors.  This module validates
and joins those facts; it never performs network access, invokes a command,
reads a wall clock, or treats a local pin/installed version/boolean as execution
authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, NoReturn, Self, cast

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

if TYPE_CHECKING:
    from collections.abc import Mapping

PYPI_PROJECT_NAME = "nba_api"
PYPI_DISTRIBUTION_NAME = "nba-api"
PYPI_JSON_URL = "https://pypi.org/pypi/nba_api/json"
UPSTREAM_REPOSITORY = "https://github.com/swar/nba_api"

MAX_PYPI_INVENTORY_BYTES = 64 * 1024 * 1024
MAX_CANONICAL_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_SELECTION_DURATION = timedelta(hours=6)
MAX_POINT_OF_USE_DELAY = timedelta(minutes=5)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_VERSION_RE = re.compile(
    r"(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:(?P<pre_kind>a|b|rc)(?P<pre_number>0|[1-9]\d*))?"
    r"(?:(?:\.post)(?P<post_number>0|[1-9]\d*))?"
    r"(?:(?:\.dev)(?P<dev_number>0|[1-9]\d*))?\Z"
)
_SAFE_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,511}\Z")
_SAFE_GATE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class NbaApiReleaseSelectionError(ValueError):
    """Raised when any release-selection evidence fails closed."""


def _fail(message: str) -> NoReturn:
    raise NbaApiReleaseSelectionError(message)


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic minified UTF-8 JSON bytes."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiReleaseSelectionError("value is not canonical JSON") from exc


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_constant(value: str) -> NoReturn:
    _fail(f"JSON constant {value!r} is forbidden")


def _reject_float(value: str) -> NoReturn:
    _fail(f"JSON float {value!r} is forbidden")


def _object_from_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key {key!r} is forbidden")
        result[key] = value
    return result


def _decode_json_bytes(
    raw: bytes,
    *,
    label: str,
    maximum_bytes: int,
    canonical: bool,
) -> Mapping[str, object]:
    if type(raw) is not bytes:
        _fail(f"{label} must be exact bytes")
    if not raw or len(raw) > maximum_bytes:
        _fail(f"{label} byte length is invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NbaApiReleaseSelectionError(f"{label} must be UTF-8") from exc
    if text.startswith("\ufeff"):
        _fail(f"{label} must not contain a UTF-8 BOM")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
        )
    except (json.JSONDecodeError, RecursionError) as exc:
        raise NbaApiReleaseSelectionError(f"{label} is not valid JSON") from exc
    if type(value) is not dict:
        _fail(f"{label} must decode to one object")
    if canonical and canonical_json_bytes(value) != raw:
        _fail(f"{label} bytes are not exact canonical JSON")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    if set(value) != expected:
        _fail(f"{label} fields do not match the exact schema")


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _list(value: object, *, label: str) -> list[object]:
    if type(value) is not list:
        _fail(f"{label} must be an exact list")
    return cast("list[object]", value)


def _string(
    value: object,
    *,
    label: str,
    minimum: int = 1,
    maximum: int = 4096,
    ascii_only: bool = True,
) -> str:
    if type(value) is not str or not (minimum <= len(value) <= maximum):
        _fail(f"{label} must be a bounded string")
    if ascii_only and (not value.isascii() or not value.isprintable()):
        _fail(f"{label} must contain printable ASCII only")
    if "\x00" in value or "\r" in value or "\n" in value:
        _fail(f"{label} contains forbidden control characters")
    return value


def _integer(
    value: object,
    *,
    label: str,
    minimum: int = 0,
    maximum: int = 2**63 - 1,
) -> int:
    if type(value) is not int or not (minimum <= value <= maximum):
        _fail(f"{label} must be an exact bounded integer")
    return value


def _boolean(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be an exact boolean")
    return value


def _sha256(value: object, *, label: str) -> str:
    text = _string(value, label=label, minimum=64, maximum=64)
    if _SHA256_RE.fullmatch(text) is None:
        _fail(f"{label} must be a lowercase SHA-256 digest")
    return text


def _git_sha(value: object, *, label: str) -> str:
    text = _string(value, label=label, minimum=40, maximum=40)
    if _GIT_SHA_RE.fullmatch(text) is None:
        _fail(f"{label} must be a lowercase 40-character Git SHA")
    return text


def _timestamp(value: object, *, label: str) -> tuple[str, datetime]:
    text = _string(value, label=label, minimum=20, maximum=20)
    if _UTC_RE.fullmatch(text) is None:
        _fail(f"{label} must be exact whole-second UTC with a Z suffix")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise NbaApiReleaseSelectionError(f"{label} is not a valid UTC instant") from exc
    return text, parsed


def _digest_body(payload: Mapping[str, object], digest_field: str) -> str:
    body = dict(payload)
    body.pop(digest_field, None)
    return _sha256_bytes(canonical_json_bytes(body))


def _candidate_receipt_inventory_sha256(receipt_sha256s: tuple[str, ...]) -> str:
    if type(receipt_sha256s) is not tuple or not receipt_sha256s:
        _fail("candidate receipt SHA-256 inventory must be one nonempty exact tuple")
    if len(receipt_sha256s) > 1024:
        _fail("candidate receipt SHA-256 inventory exceeds its resource bound")
    normalized = [
        _sha256(value, label=f"candidate receipt SHA-256[{index}]")
        for index, value in enumerate(receipt_sha256s)
    ]
    if len(set(normalized)) != len(normalized):
        _fail("candidate receipt SHA-256 inventory contains duplicates")
    return _sha256_bytes(canonical_json_bytes(normalized))


def _python_version(value: object, *, label: str) -> tuple[str, Version]:
    text = _string(value, label=label, maximum=128)
    try:
        parsed = Version(text)
    except InvalidVersion as exc:
        raise NbaApiReleaseSelectionError(f"{label} is not a valid PEP 440 version") from exc
    if str(parsed) != text:
        _fail(f"{label} is not exact canonical PEP 440")
    if (
        len(parsed.release) != 3
        or parsed.epoch != 0
        or parsed.pre is not None
        or parsed.post is not None
        or parsed.dev is not None
        or parsed.local is not None
    ):
        _fail(f"{label} must be one exact major.minor.micro runtime version")
    return text, parsed


def _requires_python_specifier(
    constraint: str | None,
    *,
    label: str,
) -> SpecifierSet | None:
    if constraint is None:
        return None
    try:
        return SpecifierSet(constraint)
    except InvalidSpecifier as exc:
        raise NbaApiReleaseSelectionError(
            f"{label} is not a valid PEP 440 Requires-Python constraint"
        ) from exc


def _requires_python_allows(
    constraint: str | None,
    *,
    python_version: Version,
    label: str,
) -> None:
    specifier = _requires_python_specifier(constraint, label=label)
    if specifier is None:
        return
    if not specifier.contains(python_version, prereleases=True):
        _fail(f"{label} excludes the exact repository-stack Python version")


VersionClass = Literal["stable", "prerelease"]
ClockPhase = Literal["selection", "readback"]
CollectorOutcome = Literal["complete", "collector_failure"]
ProcessTermination = Literal[
    "exited",
    "signaled",
    "timed_out",
    "spawn_failure",
    "infrastructure_failure",
    "unobserved",
]
CommandResult = Literal[
    "passed",
    "provider_incompatible",
    "timed_out",
    "infrastructure_failure",
    "collector_failure",
]
CandidateOutcome = Literal[
    "compatible",
    "provider_incompatible",
    "evidence_failure",
]

_COMMAND_RESULTS = {
    "passed",
    "provider_incompatible",
    "timed_out",
    "infrastructure_failure",
    "collector_failure",
}
_EVIDENCE_FAILURE_RESULTS = {
    "timed_out",
    "infrastructure_failure",
    "collector_failure",
}

_CLOCK_PHASES = {"selection", "readback"}
_COLLECTOR_OUTCOMES = {"complete", "collector_failure"}
_PROCESS_TERMINATIONS = {
    "exited",
    "signaled",
    "timed_out",
    "spawn_failure",
    "infrastructure_failure",
    "unobserved",
}


def _provider_incompatible_exit_codes(
    value: object,
    *,
    label: str,
) -> tuple[int, ...]:
    if type(value) is not tuple or len(value) > 255:
        _fail(f"{label} must be one bounded exact tuple")
    codes = tuple(
        _integer(item, label=f"{label}[{index}]", minimum=1, maximum=255)
        for index, item in enumerate(value)
    )
    if len(set(codes)) != len(codes):
        _fail(f"{label} contains duplicate exit codes")
    if tuple(sorted(codes)) != codes:
        _fail(f"{label} must use strict ascending order")
    return codes


def _derive_command_result(
    *,
    provider_incompatible_exit_codes: tuple[int, ...],
    collector_outcome: CollectorOutcome,
    termination_kind: ProcessTermination,
    exit_code: int | None,
    signal_number: int | None,
) -> CommandResult:
    incompatible_exit_codes = _provider_incompatible_exit_codes(
        provider_incompatible_exit_codes,
        label="provider-incompatible exit codes",
    )
    if collector_outcome not in _COLLECTOR_OUTCOMES:
        _fail("command collector outcome is unclassified")
    if termination_kind not in _PROCESS_TERMINATIONS:
        _fail("command process termination is unclassified")
    if collector_outcome == "collector_failure":
        if termination_kind != "unobserved" or exit_code is not None or signal_number is not None:
            _fail("collector failure cannot project untrusted process termination evidence")
        return "collector_failure"
    if termination_kind == "unobserved":
        _fail("complete command collection must observe one exact process termination")
    if termination_kind == "exited":
        if exit_code is None or signal_number is not None:
            _fail("ordinary command exit requires only one exact exit code")
        _integer(exit_code, label="command exit code", maximum=255)
        if exit_code == 0:
            return "passed"
        if exit_code in incompatible_exit_codes:
            return "provider_incompatible"
        return "infrastructure_failure"
    if exit_code is not None:
        _fail("non-exit command termination cannot carry an exit code")
    if termination_kind == "signaled":
        if signal_number is None:
            _fail("signaled command termination requires one exact signal number")
        _integer(signal_number, label="command signal number", minimum=1, maximum=255)
        return "infrastructure_failure"
    if signal_number is not None:
        _fail("non-signal command termination cannot carry a signal number")
    if termination_kind == "timed_out":
        return "timed_out"
    return "infrastructure_failure"


@dataclass(frozen=True, slots=True)
class ExecutionClockReceiptV1:
    phase: ClockPhase
    repository_source_sha: str
    stack_identity_sha256: str
    compatibility_plan_sha256: str
    selection_nonce: str
    execution_kickoff_at_utc: str
    selection_completed_at_utc: str
    observed_now_at_utc: str
    collector_authority_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.phase not in _CLOCK_PHASES:
            _fail("execution-clock receipt phase is unclassified")
        _git_sha(self.repository_source_sha, label="execution-clock source SHA")
        _sha256(self.stack_identity_sha256, label="execution-clock stack SHA-256")
        _sha256(self.compatibility_plan_sha256, label="execution-clock plan SHA-256")
        _sha256(self.selection_nonce, label="execution-clock selection nonce")
        _, kickoff = _timestamp(self.execution_kickoff_at_utc, label="execution-clock kickoff")
        _, completed = _timestamp(
            self.selection_completed_at_utc,
            label="execution-clock selection completion",
        )
        _, observed_now = _timestamp(
            self.observed_now_at_utc,
            label="execution-clock observed now",
        )
        if not (
            kickoff <= completed <= observed_now
            and completed - kickoff <= MAX_SELECTION_DURATION
            and observed_now - completed <= MAX_POINT_OF_USE_DELAY
        ):
            _fail("execution-clock receipt is stale or has invalid chronology")
        _sha256(
            self.collector_authority_sha256,
            label="execution-clock collector authority SHA-256",
        )
        if _sha256(self.receipt_sha256, label="execution-clock receipt SHA-256") != (
            _digest_body(self.to_dict(), "receipt_sha256")
        ):
            _fail("execution-clock receipt digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "collector_authority_sha256": self.collector_authority_sha256,
            "compatibility_plan_sha256": self.compatibility_plan_sha256,
            "execution_kickoff_at_utc": self.execution_kickoff_at_utc,
            "kind": "nbadb_execution_clock_receipt",
            "observed_now_at_utc": self.observed_now_at_utc,
            "phase": self.phase,
            "receipt_sha256": self.receipt_sha256,
            "repository_source_sha": self.repository_source_sha,
            "schema_version": 1,
            "selection_completed_at_utc": self.selection_completed_at_utc,
            "selection_nonce": self.selection_nonce,
            "stack_identity_sha256": self.stack_identity_sha256,
        }


def _classify_version(version: str) -> tuple[VersionClass, tuple[int, int, int, int, int]]:
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        _fail(f"release key {version!r} uses unclassified version syntax")
    pre_kind = match.group("pre_kind")
    post_number = match.group("post_number")
    dev_number = match.group("dev_number")
    if post_number is not None and (pre_kind is not None or dev_number is not None):
        _fail(f"release key {version!r} uses an unclassified mixed release form")
    classification: VersionClass = (
        "prerelease" if pre_kind is not None or dev_number is not None else "stable"
    )
    stable_key = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        1 if post_number is not None else 0,
        int(post_number or 0),
    )
    return classification, stable_key


@dataclass(frozen=True, slots=True)
class ReleaseArchiveV1:
    filename: str
    package_type: Literal["sdist", "bdist_wheel"]
    sha256: str
    size_bytes: int
    requires_python: str | None
    yanked: bool

    def __post_init__(self) -> None:
        if (
            _SAFE_FILENAME_RE.fullmatch(
                _string(self.filename, label="archive filename", maximum=512)
            )
            is None
            or "/" in self.filename
            or "\\" in self.filename
        ):
            _fail("archive filename is not one safe basename")
        if self.package_type not in {"sdist", "bdist_wheel"}:
            _fail("archive package type is unclassified")
        _sha256(self.sha256, label="archive SHA-256")
        _integer(self.size_bytes, label="archive size", minimum=1)
        if self.requires_python is not None:
            _string(
                self.requires_python,
                label="archive Python constraint",
                maximum=1024,
            )
        _boolean(self.yanked, label="archive yanked")

    def to_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "package_type": self.package_type,
            "requires_python": self.requires_python,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "yanked": self.yanked,
        }


@dataclass(frozen=True, slots=True)
class ReleaseInventoryEntryV1:
    version: str
    classification: VersionClass
    yanked: bool
    archives: tuple[ReleaseArchiveV1, ...]
    archive_set_sha256: str

    def __post_init__(self) -> None:
        expected_class, _ = _classify_version(
            _string(self.version, label="release version", maximum=128)
        )
        if self.classification != expected_class:
            _fail("release classification differs from its version syntax")
        _boolean(self.yanked, label="release yanked")
        if type(self.archives) is not tuple or not self.archives:
            _fail("release archives must be one nonempty exact tuple")
        if any(type(item) is not ReleaseArchiveV1 for item in self.archives):
            _fail("release archives contain an invalid value")
        if tuple(sorted(self.archives, key=lambda item: item.filename)) != self.archives:
            _fail("release archives must be filename-sorted")
        if len({item.filename for item in self.archives}) != len(self.archives):
            _fail("release archive filenames must be unique")
        if len({item.sha256 for item in self.archives}) != len(self.archives):
            _fail("release archive SHA-256 values must be unique")
        yanked_values = {item.yanked for item in self.archives}
        if len(yanked_values) != 1 or self.yanked != next(iter(yanked_values)):
            _fail("partially yanked or inconsistent release archives are forbidden")
        if sum(item.package_type == "sdist" for item in self.archives) != 1:
            _fail("every release must contain exactly one source archive")
        if not any(item.package_type == "bdist_wheel" for item in self.archives):
            _fail("every release must contain at least one wheel archive")
        expected_digest = _sha256_bytes(
            canonical_json_bytes([item.to_dict() for item in self.archives])
        )
        if _sha256(self.archive_set_sha256, label="archive-set SHA-256") != expected_digest:
            _fail("release archive-set digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "archive_set_sha256": self.archive_set_sha256,
            "archives": [item.to_dict() for item in self.archives],
            "classification": self.classification,
            "version": self.version,
            "yanked": self.yanked,
        }


@dataclass(frozen=True, slots=True)
class CompatibilityCommandSpecV1:
    ordinal: int
    gate_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    provider_incompatible_exit_codes: tuple[int, ...]

    def __post_init__(self) -> None:
        _integer(self.ordinal, label="command ordinal", maximum=63)
        if (
            _SAFE_GATE_RE.fullmatch(
                _string(self.gate_id, label="compatibility gate ID", maximum=64)
            )
            is None
        ):
            _fail("compatibility gate ID is invalid")
        if type(self.argv) is not tuple or not self.argv or len(self.argv) > 64:
            _fail("compatibility command argv must be one bounded exact tuple")
        for index, argument in enumerate(self.argv):
            _string(argument, label=f"compatibility argv[{index}]", maximum=4096)
        _integer(
            self.timeout_seconds,
            label="compatibility command timeout",
            minimum=1,
            maximum=21_600,
        )
        _provider_incompatible_exit_codes(
            self.provider_incompatible_exit_codes,
            label="compatibility command provider-incompatible exit codes",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "gate_id": self.gate_id,
            "ordinal": self.ordinal,
            "provider_incompatible_exit_codes": list(self.provider_incompatible_exit_codes),
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class CompatibilityCommandReceiptV1:
    ordinal: int
    gate_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    provider_incompatible_exit_codes: tuple[int, ...]
    candidate_version: str
    candidate_archive_set_sha256: str
    repository_source_sha: str
    stack_identity_sha256: str
    compatibility_plan_sha256: str
    selection_nonce: str
    started_at_utc: str
    completed_at_utc: str
    collector_outcome: CollectorOutcome
    termination_kind: ProcessTermination
    exit_code: int | None
    signal_number: int | None
    stdout_size_bytes: int
    stdout_sha256: str
    stderr_size_bytes: int
    stderr_sha256: str
    result: CommandResult
    receipt_sha256: str

    def __post_init__(self) -> None:
        CompatibilityCommandSpecV1(
            ordinal=self.ordinal,
            gate_id=self.gate_id,
            argv=self.argv,
            timeout_seconds=self.timeout_seconds,
            provider_incompatible_exit_codes=self.provider_incompatible_exit_codes,
        )
        _classify_version(_string(self.candidate_version, label="candidate version"))
        _sha256(self.candidate_archive_set_sha256, label="candidate archive-set SHA-256")
        _git_sha(self.repository_source_sha, label="command repository source SHA")
        _sha256(self.stack_identity_sha256, label="command stack-identity SHA-256")
        _sha256(self.compatibility_plan_sha256, label="command plan SHA-256")
        _sha256(self.selection_nonce, label="selection nonce")
        _, started = _timestamp(self.started_at_utc, label="command start time")
        _, completed = _timestamp(self.completed_at_utc, label="command completion time")
        if completed < started:
            _fail("compatibility command completed before it started")
        if completed - started > timedelta(seconds=self.timeout_seconds):
            _fail("compatibility command exceeded its declared timeout")
        _integer(self.stdout_size_bytes, label="command stdout size")
        _sha256(self.stdout_sha256, label="command stdout SHA-256")
        _integer(self.stderr_size_bytes, label="command stderr size")
        _sha256(self.stderr_sha256, label="command stderr SHA-256")
        empty_sha256 = _sha256_bytes(b"")
        if self.stdout_size_bytes == 0 and self.stdout_sha256 != empty_sha256:
            _fail("empty command stdout has a nonempty digest")
        if self.stderr_size_bytes == 0 and self.stderr_sha256 != empty_sha256:
            _fail("empty command stderr has a nonempty digest")
        if self.stdout_size_bytes > 0 and self.stdout_sha256 == empty_sha256:
            _fail("nonempty command stdout has the empty-content digest")
        if self.stderr_size_bytes > 0 and self.stderr_sha256 == empty_sha256:
            _fail("nonempty command stderr has the empty-content digest")
        if self.result not in _COMMAND_RESULTS:
            _fail("command result is unclassified")
        expected_result = _derive_command_result(
            provider_incompatible_exit_codes=self.provider_incompatible_exit_codes,
            collector_outcome=self.collector_outcome,
            termination_kind=self.termination_kind,
            exit_code=self.exit_code,
            signal_number=self.signal_number,
        )
        if self.result != expected_result:
            _fail("command result does not match validator-derived process evidence")
        if _sha256(self.receipt_sha256, label="command receipt SHA-256") != _digest_body(
            self.to_dict(), "receipt_sha256"
        ):
            _fail("command receipt digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "candidate_archive_set_sha256": self.candidate_archive_set_sha256,
            "candidate_version": self.candidate_version,
            "compatibility_plan_sha256": self.compatibility_plan_sha256,
            "completed_at_utc": self.completed_at_utc,
            "collector_outcome": self.collector_outcome,
            "exit_code": self.exit_code,
            "gate_id": self.gate_id,
            "ordinal": self.ordinal,
            "provider_incompatible_exit_codes": list(self.provider_incompatible_exit_codes),
            "receipt_sha256": self.receipt_sha256,
            "repository_source_sha": self.repository_source_sha,
            "result": self.result,
            "selection_nonce": self.selection_nonce,
            "signal_number": self.signal_number,
            "stack_identity_sha256": self.stack_identity_sha256,
            "started_at_utc": self.started_at_utc,
            "stderr_sha256": self.stderr_sha256,
            "stderr_size_bytes": self.stderr_size_bytes,
            "stdout_sha256": self.stdout_sha256,
            "stdout_size_bytes": self.stdout_size_bytes,
            "timeout_seconds": self.timeout_seconds,
            "termination_kind": self.termination_kind,
        }


@dataclass(frozen=True, slots=True)
class CandidateCompatibilityReceiptV1:
    candidate_version: str
    candidate_archive_set_sha256: str
    repository_source_sha: str
    stack_identity_sha256: str
    compatibility_plan_sha256: str
    selection_nonce: str
    commands: tuple[CompatibilityCommandReceiptV1, ...]
    outcome: CandidateOutcome
    receipt_sha256: str

    def __post_init__(self) -> None:
        classification, _ = _classify_version(
            _string(self.candidate_version, label="candidate version")
        )
        if classification != "stable":
            _fail("compatibility receipts may bind stable candidates only")
        _sha256(self.candidate_archive_set_sha256, label="candidate archive-set SHA-256")
        _git_sha(self.repository_source_sha, label="candidate repository source SHA")
        _sha256(self.stack_identity_sha256, label="candidate stack-identity SHA-256")
        _sha256(self.compatibility_plan_sha256, label="candidate plan SHA-256")
        _sha256(self.selection_nonce, label="candidate selection nonce")
        if type(self.commands) is not tuple or not self.commands:
            _fail("candidate commands must be one nonempty exact tuple")
        if any(type(command) is not CompatibilityCommandReceiptV1 for command in self.commands):
            _fail("candidate commands contain an invalid receipt")
        command_results = {command.result for command in self.commands}
        if command_results & _EVIDENCE_FAILURE_RESULTS:
            expected_outcome = "evidence_failure"
        elif command_results == {"passed"}:
            expected_outcome = "compatible"
        else:
            expected_outcome = "provider_incompatible"
        if self.outcome != expected_outcome:
            _fail("candidate outcome does not match its command receipts")
        if _sha256(self.receipt_sha256, label="candidate receipt SHA-256") != _digest_body(
            self.to_dict(), "receipt_sha256"
        ):
            _fail("candidate compatibility receipt digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_archive_set_sha256": self.candidate_archive_set_sha256,
            "candidate_version": self.candidate_version,
            "commands": [command.to_dict() for command in self.commands],
            "compatibility_plan_sha256": self.compatibility_plan_sha256,
            "kind": "nbadb_nba_api_candidate_compatibility",
            "outcome": self.outcome,
            "receipt_sha256": self.receipt_sha256,
            "repository_source_sha": self.repository_source_sha,
            "schema_version": 1,
            "selection_nonce": self.selection_nonce,
            "stack_identity_sha256": self.stack_identity_sha256,
        }


@dataclass(frozen=True, slots=True)
class ObservedProviderAuthorityV1:
    distribution_version: str
    repository_source_sha: str
    stack_identity_sha256: str
    compatibility_plan_sha256: str
    selection_nonce: str
    selected_candidate_receipt_sha256: str
    candidate_receipt_inventory_sha256: str
    dependency_pin_version: str
    lock_version: str
    installed_version: str
    standalone_connector_version: str
    stats_headers_version: str
    live_headers_version: str
    generated_authority_version: str
    fixture_version: str
    parity_test_version: str
    locked_archive_sha256s: tuple[str, ...]
    provider_contract_sha256: str
    provider_evidence_sha256: str
    upstream_tag: str
    upstream_commit_sha: str
    upstream_tag_commit_sha: str
    upstream_tree_sha: str
    source_checkout_clean: bool
    source_inventory_file_count: int
    source_inventory_sha256: str
    installed_inventory_file_count: int
    installed_inventory_sha256: str
    source_installed_file_parity: bool
    license_identifier: str
    license_sha256: str
    docs_tools_bundle_sha256: str
    runtime_contract_payload_sha256: str
    runtime_endpoint_contract_count: int
    runtime_endpoint_contract_sha256: str
    live_contract_sha256: str
    static_contract_sha256: str
    bronze_contract_sha256: str
    metadata_ledger_sha256: str
    observed_at_utc: str
    authority_sha256: str

    def __post_init__(self) -> None:
        classification, _ = _classify_version(
            _string(self.distribution_version, label="observed distribution version")
        )
        if classification != "stable":
            _fail("observed provider authority must bind one stable release")
        _git_sha(self.repository_source_sha, label="observed provider repository source SHA")
        _sha256(self.stack_identity_sha256, label="observed provider stack SHA-256")
        _sha256(self.compatibility_plan_sha256, label="observed provider plan SHA-256")
        _sha256(self.selection_nonce, label="observed provider selection nonce")
        _sha256(
            self.selected_candidate_receipt_sha256,
            label="observed provider selected candidate receipt SHA-256",
        )
        _sha256(
            self.candidate_receipt_inventory_sha256,
            label="observed provider candidate inventory SHA-256",
        )
        version_fields = (
            self.dependency_pin_version,
            self.lock_version,
            self.installed_version,
            self.standalone_connector_version,
            self.stats_headers_version,
            self.live_headers_version,
            self.generated_authority_version,
            self.fixture_version,
            self.parity_test_version,
        )
        if any(version != self.distribution_version for version in version_fields):
            _fail("observed provider authority contains mixed dependency release versions")
        if type(self.locked_archive_sha256s) is not tuple or not self.locked_archive_sha256s:
            _fail("observed provider locked archives must be one nonempty exact tuple")
        if tuple(sorted(self.locked_archive_sha256s)) != self.locked_archive_sha256s:
            _fail("observed provider locked archive digests must be sorted")
        if len(set(self.locked_archive_sha256s)) != len(self.locked_archive_sha256s):
            _fail("observed provider locked archive digests must be unique")
        for digest in self.locked_archive_sha256s:
            _sha256(digest, label="locked provider archive SHA-256")
        for label, digest in (
            ("provider contract SHA-256", self.provider_contract_sha256),
            ("provider evidence SHA-256", self.provider_evidence_sha256),
            ("source inventory SHA-256", self.source_inventory_sha256),
            ("installed inventory SHA-256", self.installed_inventory_sha256),
            ("license SHA-256", self.license_sha256),
            ("docs/tools bundle SHA-256", self.docs_tools_bundle_sha256),
            ("runtime contract payload SHA-256", self.runtime_contract_payload_sha256),
            ("runtime endpoint contract SHA-256", self.runtime_endpoint_contract_sha256),
            ("live contract SHA-256", self.live_contract_sha256),
            ("static contract SHA-256", self.static_contract_sha256),
            ("bronze contract SHA-256", self.bronze_contract_sha256),
            ("metadata ledger SHA-256", self.metadata_ledger_sha256),
        ):
            _sha256(digest, label=label)
        if self.upstream_tag != f"v{self.distribution_version}":
            _fail("observed provider tag does not bind the selected version")
        _git_sha(self.upstream_commit_sha, label="upstream commit SHA")
        if self.upstream_tag_commit_sha != self.upstream_commit_sha:
            _fail("upstream tag target differs from the observed commit")
        _git_sha(self.upstream_tag_commit_sha, label="upstream tag commit SHA")
        _git_sha(self.upstream_tree_sha, label="upstream tree SHA")
        if _boolean(self.source_checkout_clean, label="source checkout clean") is not True:
            _fail("observed provider source checkout is not clean")
        _integer(
            self.source_inventory_file_count,
            label="source inventory file count",
            minimum=1,
        )
        _integer(
            self.installed_inventory_file_count,
            label="installed inventory file count",
            minimum=1,
        )
        if (
            self.source_inventory_file_count != self.installed_inventory_file_count
            or self.source_inventory_sha256 != self.installed_inventory_sha256
            or _boolean(
                self.source_installed_file_parity,
                label="source/installed file parity",
            )
            is not True
        ):
            _fail("observed source and installed inventories lack exact parity")
        _string(self.license_identifier, label="license identifier", maximum=128)
        _integer(
            self.runtime_endpoint_contract_count,
            label="runtime endpoint contract count",
            minimum=1,
        )
        _timestamp(self.observed_at_utc, label="provider authority observation time")
        if _sha256(self.authority_sha256, label="provider authority SHA-256") != _digest_body(
            self.to_dict(), "authority_sha256"
        ):
            _fail("observed provider authority digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_sha256": self.authority_sha256,
            "bronze_contract_sha256": self.bronze_contract_sha256,
            "candidate_receipt_inventory_sha256": self.candidate_receipt_inventory_sha256,
            "compatibility_plan_sha256": self.compatibility_plan_sha256,
            "dependency_pin_version": self.dependency_pin_version,
            "distribution_name": PYPI_DISTRIBUTION_NAME,
            "distribution_version": self.distribution_version,
            "docs_tools_bundle_sha256": self.docs_tools_bundle_sha256,
            "fixture_version": self.fixture_version,
            "generated_authority_version": self.generated_authority_version,
            "installed_inventory_file_count": self.installed_inventory_file_count,
            "installed_inventory_sha256": self.installed_inventory_sha256,
            "installed_version": self.installed_version,
            "kind": "nbadb_nba_api_observed_provider_authority",
            "license_identifier": self.license_identifier,
            "license_sha256": self.license_sha256,
            "live_contract_sha256": self.live_contract_sha256,
            "live_headers_version": self.live_headers_version,
            "lock_version": self.lock_version,
            "locked_archive_sha256s": list(self.locked_archive_sha256s),
            "metadata_ledger_sha256": self.metadata_ledger_sha256,
            "observed_at_utc": self.observed_at_utc,
            "parity_test_version": self.parity_test_version,
            "provider_contract_sha256": self.provider_contract_sha256,
            "provider_evidence_sha256": self.provider_evidence_sha256,
            "repository_source_sha": self.repository_source_sha,
            "runtime_contract_payload_sha256": self.runtime_contract_payload_sha256,
            "runtime_endpoint_contract_count": self.runtime_endpoint_contract_count,
            "runtime_endpoint_contract_sha256": self.runtime_endpoint_contract_sha256,
            "schema_version": 1,
            "selected_candidate_receipt_sha256": self.selected_candidate_receipt_sha256,
            "selection_nonce": self.selection_nonce,
            "source_checkout_clean": self.source_checkout_clean,
            "source_installed_file_parity": self.source_installed_file_parity,
            "source_inventory_file_count": self.source_inventory_file_count,
            "source_inventory_sha256": self.source_inventory_sha256,
            "standalone_connector_version": self.standalone_connector_version,
            "static_contract_sha256": self.static_contract_sha256,
            "stats_headers_version": self.stats_headers_version,
            "stack_identity_sha256": self.stack_identity_sha256,
            "upstream_commit_sha": self.upstream_commit_sha,
            "upstream_repository": UPSTREAM_REPOSITORY,
            "upstream_tag": self.upstream_tag,
            "upstream_tag_commit_sha": self.upstream_tag_commit_sha,
            "upstream_tree_sha": self.upstream_tree_sha,
        }


@dataclass(frozen=True, slots=True)
class NbaApiReleaseSelectionAuthorityV1:
    pypi_inventory_sha256: str
    pypi_inventory_size_bytes: int
    pypi_fetch_receipt_sha256: str
    pypi_inventory_retrieved_at_utc: str
    pypi_last_serial: int
    execution_kickoff_at_utc: str
    selection_completed_at_utc: str
    trusted_now_at_utc: str
    execution_clock_receipt: ExecutionClockReceiptV1
    execution_clock_receipt_sha256: str
    clock_collector_authority_sha256: str
    repository_source_sha: str
    stack_identity_sha256: str
    stack_python_version: str
    compatibility_plan_sha256: str
    selection_nonce: str
    release_inventory: tuple[ReleaseInventoryEntryV1, ...]
    release_inventory_sha256: str
    stable_candidate_versions: tuple[str, ...]
    compatibility_commands: tuple[CompatibilityCommandSpecV1, ...]
    candidate_receipts: tuple[CandidateCompatibilityReceiptV1, ...]
    candidate_receipt_sha256s: tuple[str, ...]
    candidate_receipt_inventory_sha256: str
    selected_version: str
    selected_archives: tuple[ReleaseArchiveV1, ...]
    selected_archive_set_sha256: str
    rejected_newer_versions: tuple[str, ...]
    selected_provider_authority: ObservedProviderAuthorityV1
    selected_provider_authority_sha256: str
    authority_sha256: str

    def __post_init__(self) -> None:
        _validate_selection_authority(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_sha256": self.authority_sha256,
            "candidate_receipt_inventory_sha256": self.candidate_receipt_inventory_sha256,
            "candidate_receipt_sha256s": list(self.candidate_receipt_sha256s),
            "candidate_receipts": [receipt.to_dict() for receipt in self.candidate_receipts],
            "compatibility_commands": [
                command.to_dict() for command in self.compatibility_commands
            ],
            "compatibility_plan_sha256": self.compatibility_plan_sha256,
            "clock_collector_authority_sha256": self.clock_collector_authority_sha256,
            "distribution_name": PYPI_DISTRIBUTION_NAME,
            "execution_clock_receipt": self.execution_clock_receipt.to_dict(),
            "execution_clock_receipt_sha256": self.execution_clock_receipt_sha256,
            "execution_kickoff_at_utc": self.execution_kickoff_at_utc,
            "kind": "nbadb_nba_api_release_selection_authority",
            "project_name": PYPI_PROJECT_NAME,
            "pypi_fetch_receipt_sha256": self.pypi_fetch_receipt_sha256,
            "pypi_inventory_retrieved_at_utc": self.pypi_inventory_retrieved_at_utc,
            "pypi_inventory_sha256": self.pypi_inventory_sha256,
            "pypi_inventory_size_bytes": self.pypi_inventory_size_bytes,
            "pypi_last_serial": self.pypi_last_serial,
            "rejected_newer_versions": list(self.rejected_newer_versions),
            "release_inventory": [entry.to_dict() for entry in self.release_inventory],
            "release_inventory_sha256": self.release_inventory_sha256,
            "repository_source_sha": self.repository_source_sha,
            "schema_version": 1,
            "selected_archive_set_sha256": self.selected_archive_set_sha256,
            "selected_archives": [archive.to_dict() for archive in self.selected_archives],
            "selected_provider_authority": self.selected_provider_authority.to_dict(),
            "selected_provider_authority_sha256": self.selected_provider_authority_sha256,
            "selected_version": self.selected_version,
            "selection_completed_at_utc": self.selection_completed_at_utc,
            "selection_nonce": self.selection_nonce,
            "stable_candidate_versions": list(self.stable_candidate_versions),
            "stack_identity_sha256": self.stack_identity_sha256,
            "stack_python_version": self.stack_python_version,
            "trusted_now_at_utc": self.trusted_now_at_utc,
        }

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_canonical_bytes(
        cls,
        raw: bytes,
        *,
        expected_authority_sha256: str,
        expected_pypi_inventory_sha256: str,
        expected_pypi_fetch_receipt_sha256: str,
        expected_repository_source_sha: str,
        expected_stack_identity_sha256: str,
        expected_compatibility_plan_sha256: str,
        expected_candidate_receipt_sha256s: tuple[str, ...],
        expected_candidate_receipt_inventory_sha256: str,
        expected_selected_provider_authority_sha256: str,
        expected_execution_clock_receipt_sha256: str,
        expected_clock_collector_authority_sha256: str,
        readback_clock_receipt_bytes: bytes,
        expected_readback_clock_receipt_sha256: str,
    ) -> Self:
        payload = _decode_json_bytes(
            raw,
            label="release-selection authority",
            maximum_bytes=MAX_CANONICAL_RECEIPT_BYTES,
            canonical=True,
        )
        authority = _authority_from_mapping(payload)
        readback_clock = _parse_execution_clock_receipt(
            readback_clock_receipt_bytes,
            label="readback execution-clock receipt",
            expected_phase="readback",
            expected_receipt_sha256=expected_readback_clock_receipt_sha256,
            expected_collector_authority_sha256=(expected_clock_collector_authority_sha256),
            expected_source_sha=authority.repository_source_sha,
            expected_stack_identity_sha256=authority.stack_identity_sha256,
            expected_compatibility_plan_sha256=authority.compatibility_plan_sha256,
            expected_selection_nonce=authority.selection_nonce,
            expected_execution_kickoff_at_utc=authority.execution_kickoff_at_utc,
            expected_selection_completed_at_utc=authority.selection_completed_at_utc,
        )
        _validate_external_authority_roots(
            authority,
            expected_authority_sha256=expected_authority_sha256,
            expected_pypi_inventory_sha256=expected_pypi_inventory_sha256,
            expected_pypi_fetch_receipt_sha256=expected_pypi_fetch_receipt_sha256,
            expected_repository_source_sha=expected_repository_source_sha,
            expected_stack_identity_sha256=expected_stack_identity_sha256,
            expected_compatibility_plan_sha256=expected_compatibility_plan_sha256,
            expected_candidate_receipt_sha256s=expected_candidate_receipt_sha256s,
            expected_candidate_receipt_inventory_sha256=(
                expected_candidate_receipt_inventory_sha256
            ),
            expected_selected_provider_authority_sha256=(
                expected_selected_provider_authority_sha256
            ),
            expected_execution_clock_receipt_sha256=(expected_execution_clock_receipt_sha256),
            expected_clock_collector_authority_sha256=(expected_clock_collector_authority_sha256),
            readback_clock=readback_clock,
        )
        return cast("Self", authority)


def _archive_filename_matches_version(
    *,
    filename: str,
    package_type: str,
    version: str,
) -> bool:
    if package_type == "sdist":
        return filename in {
            f"nba_api-{version}.tar.gz",
            f"nba-api-{version}.tar.gz",
        }
    return filename.startswith(f"nba_api-{version}-") and filename.endswith(".whl")


def _archive_from_pypi(value: object, *, version: str, label: str) -> ReleaseArchiveV1:
    payload = _mapping(value, label=label)
    filename = _string(payload.get("filename"), label=f"{label} filename", maximum=512)
    package_type = _string(
        payload.get("packagetype"),
        label=f"{label} package type",
        maximum=32,
    )
    if package_type not in {"sdist", "bdist_wheel"}:
        _fail(f"{label} contains an unclassified package type")
    if not _archive_filename_matches_version(
        filename=filename,
        package_type=package_type,
        version=version,
    ):
        _fail(f"{label} filename does not bind its release key")
    digests = _mapping(payload.get("digests"), label=f"{label} digests")
    requires_python_raw = payload.get("requires_python")
    requires_python = (
        None
        if requires_python_raw is None
        else _string(
            requires_python_raw,
            label=f"{label} Python constraint",
            maximum=1024,
        )
    )
    return ReleaseArchiveV1(
        filename=filename,
        package_type=cast("Literal['sdist', 'bdist_wheel']", package_type),
        sha256=_sha256(digests.get("sha256"), label=f"{label} SHA-256"),
        size_bytes=_integer(payload.get("size"), label=f"{label} size", minimum=1),
        requires_python=requires_python,
        yanked=_boolean(payload.get("yanked"), label=f"{label} yanked"),
    )


def _archive_from_mapping(value: object, *, version: str, label: str) -> ReleaseArchiveV1:
    payload = _mapping(value, label=label)
    _exact_keys(
        payload,
        {
            "filename",
            "package_type",
            "requires_python",
            "sha256",
            "size_bytes",
            "yanked",
        },
        label=label,
    )
    package_type = _string(payload["package_type"], label=f"{label} package type")
    if package_type not in {"sdist", "bdist_wheel"}:
        _fail(f"{label} package type is unclassified")
    filename = _string(payload["filename"], label=f"{label} filename", maximum=512)
    if not _archive_filename_matches_version(
        filename=filename,
        package_type=package_type,
        version=version,
    ):
        _fail(f"{label} filename does not bind its release version")
    requires_python_raw = payload["requires_python"]
    requires_python = (
        None
        if requires_python_raw is None
        else _string(
            requires_python_raw,
            label=f"{label} Python constraint",
            maximum=1024,
        )
    )
    return ReleaseArchiveV1(
        filename=filename,
        package_type=cast("Literal['sdist', 'bdist_wheel']", package_type),
        sha256=_sha256(payload["sha256"], label=f"{label} SHA-256"),
        size_bytes=_integer(payload["size_bytes"], label=f"{label} size", minimum=1),
        requires_python=requires_python,
        yanked=_boolean(payload["yanked"], label=f"{label} yanked"),
    )


def _release_entry_from_pypi(version: str, value: object) -> ReleaseInventoryEntryV1:
    classification, _ = _classify_version(version)
    raw_files = _list(value, label=f"PyPI release {version!r} files")
    if not raw_files:
        _fail(f"PyPI release {version!r} has no archive inventory")
    archives = tuple(
        sorted(
            (
                _archive_from_pypi(
                    raw,
                    version=version,
                    label=f"PyPI release {version!r} archive[{index}]",
                )
                for index, raw in enumerate(raw_files)
            ),
            key=lambda item: item.filename,
        )
    )
    archive_set_sha256 = _sha256_bytes(
        canonical_json_bytes([archive.to_dict() for archive in archives])
    )
    yanked_values = {archive.yanked for archive in archives}
    if len(yanked_values) != 1:
        _fail(f"PyPI release {version!r} is partially yanked")
    return ReleaseInventoryEntryV1(
        version=version,
        classification=classification,
        yanked=next(iter(yanked_values)),
        archives=archives,
        archive_set_sha256=archive_set_sha256,
    )


def _release_entry_from_mapping(value: object, *, label: str) -> ReleaseInventoryEntryV1:
    payload = _mapping(value, label=label)
    _exact_keys(
        payload,
        {"archive_set_sha256", "archives", "classification", "version", "yanked"},
        label=label,
    )
    version = _string(payload["version"], label=f"{label} version", maximum=128)
    classification = _string(
        payload["classification"],
        label=f"{label} classification",
        maximum=32,
    )
    if classification not in {"stable", "prerelease"}:
        _fail(f"{label} classification is invalid")
    archives = tuple(
        _archive_from_mapping(raw, version=version, label=f"{label} archive[{index}]")
        for index, raw in enumerate(_list(payload["archives"], label=f"{label} archives"))
    )
    return ReleaseInventoryEntryV1(
        version=version,
        classification=cast("VersionClass", classification),
        yanked=_boolean(payload["yanked"], label=f"{label} yanked"),
        archives=archives,
        archive_set_sha256=_sha256(
            payload["archive_set_sha256"],
            label=f"{label} archive-set SHA-256",
        ),
    )


def _normalized_file_identity(value: object, *, version: str, label: str) -> dict[str, object]:
    return _archive_from_pypi(value, version=version, label=label).to_dict()


def _release_inventory_from_pypi(
    payload: Mapping[str, object],
) -> tuple[tuple[ReleaseInventoryEntryV1, ...], int]:
    _exact_keys(
        payload,
        {"info", "last_serial", "releases", "urls", "vulnerabilities"},
        label="official PyPI inventory",
    )
    info = _mapping(payload["info"], label="PyPI info")
    if _string(info.get("name"), label="PyPI project name", maximum=128) != PYPI_PROJECT_NAME:
        _fail("PyPI inventory is not for the exact nba_api project")
    latest_version = _string(info.get("version"), label="PyPI latest version", maximum=128)
    _classify_version(latest_version)
    last_serial = _integer(payload["last_serial"], label="PyPI last serial", minimum=1)
    releases = _mapping(payload["releases"], label="PyPI releases")
    if not releases:
        _fail("PyPI release inventory is empty")
    entries: list[ReleaseInventoryEntryV1] = []
    for version, files in releases.items():
        _string(version, label="PyPI release key", maximum=128)
        entries.append(_release_entry_from_pypi(version, files))
    if latest_version not in releases:
        _fail("PyPI latest version is absent from the release inventory")
    top_urls = _list(payload["urls"], label="PyPI latest archive inventory")
    latest_files = _list(releases[latest_version], label="PyPI latest release files")
    top_normalized = sorted(
        (
            _normalized_file_identity(
                item,
                version=latest_version,
                label=f"PyPI latest URL archive[{index}]",
            )
            for index, item in enumerate(top_urls)
        ),
        key=lambda item: str(item["filename"]),
    )
    release_normalized = sorted(
        (
            _normalized_file_identity(
                item,
                version=latest_version,
                label=f"PyPI latest release archive[{index}]",
            )
            for index, item in enumerate(latest_files)
        ),
        key=lambda item: str(item["filename"]),
    )
    if top_normalized != release_normalized:
        _fail("PyPI latest URL inventory differs from its release inventory")
    _list(payload["vulnerabilities"], label="PyPI vulnerabilities")
    release_inventory = tuple(sorted(entries, key=lambda item: item.version))
    stable_candidates = _stable_candidates(release_inventory)
    if not stable_candidates or stable_candidates[0].version != latest_version:
        _fail("PyPI latest version disagrees with the newest non-yanked stable release")
    return release_inventory, last_serial


def _parse_fetch_receipt(
    raw: bytes,
    *,
    inventory_bytes: bytes,
    expected_receipt_sha256: str,
) -> tuple[str, str]:
    payload = _decode_json_bytes(
        raw,
        label="PyPI fetch receipt",
        maximum_bytes=MAX_CANONICAL_RECEIPT_BYTES,
        canonical=True,
    )
    _exact_keys(
        payload,
        {
            "body_sha256",
            "body_size_bytes",
            "content_type",
            "kind",
            "project_name",
            "receipt_sha256",
            "request_url",
            "response_url",
            "retrieved_at_utc",
            "schema_version",
            "status_code",
        },
        label="PyPI fetch receipt",
    )
    if payload["schema_version"] != 1 or payload["kind"] != "nbadb_pypi_inventory_fetch":
        _fail("PyPI fetch receipt schema or kind is invalid")
    if payload["project_name"] != PYPI_PROJECT_NAME:
        _fail("PyPI fetch receipt project is invalid")
    if payload["request_url"] != PYPI_JSON_URL or payload["response_url"] != PYPI_JSON_URL:
        _fail("PyPI fetch receipt URL is not the exact official JSON endpoint")
    if payload["status_code"] != 200 or payload["content_type"] != "application/json":
        _fail("PyPI fetch receipt does not prove one JSON HTTP 200 response")
    body_sha256 = _sha256(payload["body_sha256"], label="PyPI body SHA-256")
    if body_sha256 != _sha256_bytes(inventory_bytes):
        _fail("PyPI fetch receipt body digest differs from the injected inventory")
    if _integer(payload["body_size_bytes"], label="PyPI body size", minimum=1) != len(
        inventory_bytes
    ):
        _fail("PyPI fetch receipt body size differs from the injected inventory")
    retrieved_at_utc, _ = _timestamp(payload["retrieved_at_utc"], label="PyPI retrieval time")
    receipt_sha256 = _sha256(payload["receipt_sha256"], label="PyPI fetch receipt SHA-256")
    if receipt_sha256 != _digest_body(payload, "receipt_sha256"):
        _fail("PyPI fetch receipt digest is invalid")
    if receipt_sha256 != _sha256(expected_receipt_sha256, label="expected fetch receipt SHA-256"):
        _fail("PyPI fetch receipt is not the independently expected receipt")
    return retrieved_at_utc, receipt_sha256


def _parse_stack_identity(
    raw: bytes,
    *,
    expected_source_sha: str,
    expected_identity_sha256: str,
) -> tuple[str, str]:
    payload = _decode_json_bytes(
        raw,
        label="repository stack identity",
        maximum_bytes=MAX_CANONICAL_RECEIPT_BYTES,
        canonical=True,
    )
    _exact_keys(
        payload,
        {
            "identity_sha256",
            "installed_distributions_sha256",
            "kind",
            "platform_machine",
            "platform_system",
            "pyproject_sha256",
            "python_implementation",
            "python_version",
            "repository_source_sha",
            "repository_tree_sha256",
            "schema_version",
            "uv_lock_sha256",
        },
        label="repository stack identity",
    )
    if payload["schema_version"] != 1 or payload["kind"] != "nbadb_repository_stack_identity":
        _fail("repository stack identity schema or kind is invalid")
    source_sha = _git_sha(payload["repository_source_sha"], label="stack source SHA")
    if source_sha != expected_source_sha:
        _fail("repository stack identity is bound to another source SHA")
    for label, field in (
        ("repository tree SHA-256", "repository_tree_sha256"),
        ("pyproject SHA-256", "pyproject_sha256"),
        ("uv.lock SHA-256", "uv_lock_sha256"),
        ("installed distributions SHA-256", "installed_distributions_sha256"),
    ):
        _sha256(payload[field], label=label)
    for label, field in (
        ("Python implementation", "python_implementation"),
        ("platform system", "platform_system"),
        ("platform machine", "platform_machine"),
    ):
        _string(payload[field], label=label, maximum=128)
    python_version, _ = _python_version(payload["python_version"], label="Python version")
    identity_sha256 = _sha256(payload["identity_sha256"], label="stack identity SHA-256")
    if identity_sha256 != _digest_body(payload, "identity_sha256"):
        _fail("repository stack identity digest is invalid")
    if identity_sha256 != expected_identity_sha256:
        _fail("repository stack identity differs from the independently expected identity")
    return identity_sha256, python_version


def _command_spec_from_mapping(value: object, *, label: str) -> CompatibilityCommandSpecV1:
    payload = _mapping(value, label=label)
    _exact_keys(
        payload,
        {
            "argv",
            "gate_id",
            "ordinal",
            "provider_incompatible_exit_codes",
            "timeout_seconds",
        },
        label=label,
    )
    return CompatibilityCommandSpecV1(
        ordinal=_integer(payload["ordinal"], label=f"{label} ordinal", maximum=63),
        gate_id=_string(payload["gate_id"], label=f"{label} gate ID", maximum=64),
        argv=tuple(
            _string(argument, label=f"{label} argv[{index}]", maximum=4096)
            for index, argument in enumerate(_list(payload["argv"], label=f"{label} argv"))
        ),
        timeout_seconds=_integer(
            payload["timeout_seconds"],
            label=f"{label} timeout",
            minimum=1,
            maximum=21_600,
        ),
        provider_incompatible_exit_codes=tuple(
            _integer(
                item,
                label=f"{label} provider-incompatible exit code[{index}]",
                minimum=1,
                maximum=255,
            )
            for index, item in enumerate(
                _list(
                    payload["provider_incompatible_exit_codes"],
                    label=f"{label} provider-incompatible exit codes",
                )
            )
        ),
    )


def _parse_compatibility_plan(
    raw: bytes,
    *,
    expected_source_sha: str,
    expected_stack_identity_sha256: str,
    expected_plan_sha256: str,
) -> tuple[str, str, tuple[CompatibilityCommandSpecV1, ...]]:
    payload = _decode_json_bytes(
        raw,
        label="compatibility plan",
        maximum_bytes=MAX_CANONICAL_RECEIPT_BYTES,
        canonical=True,
    )
    _exact_keys(
        payload,
        {
            "commands",
            "kind",
            "plan_sha256",
            "repository_source_sha",
            "schema_version",
            "selection_nonce",
            "stack_identity_sha256",
        },
        label="compatibility plan",
    )
    if payload["schema_version"] != 1 or payload["kind"] != "nbadb_nba_api_compatibility_plan":
        _fail("compatibility plan schema or kind is invalid")
    source_sha = _git_sha(payload["repository_source_sha"], label="plan source SHA")
    if source_sha != expected_source_sha:
        _fail("compatibility plan is bound to another source SHA")
    if (
        _sha256(payload["stack_identity_sha256"], label="plan stack-identity SHA-256")
        != expected_stack_identity_sha256
    ):
        _fail("compatibility plan is bound to another repository stack")
    selection_nonce = _sha256(payload["selection_nonce"], label="selection nonce")
    commands = tuple(
        _command_spec_from_mapping(item, label=f"compatibility command[{index}]")
        for index, item in enumerate(_list(payload["commands"], label="compatibility commands"))
    )
    if not commands or len(commands) > 64:
        _fail("compatibility plan must declare a bounded nonempty command inventory")
    if tuple(command.ordinal for command in commands) != tuple(range(len(commands))):
        _fail("compatibility command ordinals must be exact contiguous order")
    if len({command.gate_id for command in commands}) != len(commands):
        _fail("compatibility gate IDs must be unique")
    argv_text = "\0".join(argument for command in commands for argument in command.argv)
    for required_placeholder in (
        "{candidate_version}",
        "{candidate_archive_set_sha256}",
    ):
        if required_placeholder not in argv_text:
            _fail("compatibility plan does not bind every command run to the candidate archives")
    scrubbed_argv = argv_text.replace("{candidate_version}", "").replace(
        "{candidate_archive_set_sha256}", ""
    )
    if "{" in scrubbed_argv or "}" in scrubbed_argv:
        _fail("compatibility plan contains an unclassified command placeholder")
    plan_sha256 = _sha256(payload["plan_sha256"], label="compatibility plan SHA-256")
    if plan_sha256 != _digest_body(payload, "plan_sha256"):
        _fail("compatibility plan digest is invalid")
    if plan_sha256 != expected_plan_sha256:
        _fail("compatibility plan differs from the independently expected plan")
    return selection_nonce, plan_sha256, commands


_EXECUTION_CLOCK_FIELDS = {
    "collector_authority_sha256",
    "compatibility_plan_sha256",
    "execution_kickoff_at_utc",
    "kind",
    "observed_now_at_utc",
    "phase",
    "receipt_sha256",
    "repository_source_sha",
    "schema_version",
    "selection_completed_at_utc",
    "selection_nonce",
    "stack_identity_sha256",
}


def _execution_clock_receipt_from_mapping(
    value: object,
    *,
    label: str,
) -> ExecutionClockReceiptV1:
    payload = _mapping(value, label=label)
    _exact_keys(payload, _EXECUTION_CLOCK_FIELDS, label=label)
    if payload["schema_version"] != 1 or payload["kind"] != "nbadb_execution_clock_receipt":
        _fail(f"{label} schema or kind is invalid")
    phase = _string(payload["phase"], label=f"{label} phase", maximum=32)
    if phase not in _CLOCK_PHASES:
        _fail(f"{label} phase is invalid")
    return ExecutionClockReceiptV1(
        phase=cast("ClockPhase", phase),
        repository_source_sha=_git_sha(
            payload["repository_source_sha"],
            label=f"{label} repository source SHA",
        ),
        stack_identity_sha256=_sha256(
            payload["stack_identity_sha256"],
            label=f"{label} stack SHA-256",
        ),
        compatibility_plan_sha256=_sha256(
            payload["compatibility_plan_sha256"],
            label=f"{label} plan SHA-256",
        ),
        selection_nonce=_sha256(
            payload["selection_nonce"],
            label=f"{label} selection nonce",
        ),
        execution_kickoff_at_utc=_timestamp(
            payload["execution_kickoff_at_utc"],
            label=f"{label} kickoff",
        )[0],
        selection_completed_at_utc=_timestamp(
            payload["selection_completed_at_utc"],
            label=f"{label} selection completion",
        )[0],
        observed_now_at_utc=_timestamp(
            payload["observed_now_at_utc"],
            label=f"{label} observed now",
        )[0],
        collector_authority_sha256=_sha256(
            payload["collector_authority_sha256"],
            label=f"{label} collector authority SHA-256",
        ),
        receipt_sha256=_sha256(
            payload["receipt_sha256"],
            label=f"{label} receipt SHA-256",
        ),
    )


def _parse_execution_clock_receipt(
    raw: bytes,
    *,
    label: str,
    expected_phase: ClockPhase,
    expected_receipt_sha256: str,
    expected_collector_authority_sha256: str,
    expected_source_sha: str,
    expected_stack_identity_sha256: str,
    expected_compatibility_plan_sha256: str,
    expected_selection_nonce: str,
    expected_execution_kickoff_at_utc: str | None = None,
    expected_selection_completed_at_utc: str | None = None,
) -> ExecutionClockReceiptV1:
    payload = _decode_json_bytes(
        raw,
        label=label,
        maximum_bytes=MAX_CANONICAL_RECEIPT_BYTES,
        canonical=True,
    )
    receipt = _execution_clock_receipt_from_mapping(payload, label=label)
    if (
        receipt.phase != expected_phase
        or receipt.receipt_sha256
        != _sha256(expected_receipt_sha256, label=f"expected {label} SHA-256")
        or receipt.collector_authority_sha256
        != _sha256(
            expected_collector_authority_sha256,
            label=f"expected {label} collector authority SHA-256",
        )
        or receipt.repository_source_sha != expected_source_sha
        or receipt.stack_identity_sha256 != expected_stack_identity_sha256
        or receipt.compatibility_plan_sha256 != expected_compatibility_plan_sha256
        or receipt.selection_nonce != expected_selection_nonce
        or (
            expected_execution_kickoff_at_utc is not None
            and receipt.execution_kickoff_at_utc != expected_execution_kickoff_at_utc
        )
        or (
            expected_selection_completed_at_utc is not None
            and receipt.selection_completed_at_utc != expected_selection_completed_at_utc
        )
    ):
        _fail(f"{label} differs from its authenticated execution authority")
    return receipt


def _render_candidate_argv(
    argv: tuple[str, ...],
    *,
    candidate_version: str,
    archive_set_sha256: str,
) -> tuple[str, ...]:
    return tuple(
        argument.replace("{candidate_version}", candidate_version).replace(
            "{candidate_archive_set_sha256}", archive_set_sha256
        )
        for argument in argv
    )


def _command_receipt_from_mapping(
    value: object,
    *,
    label: str,
) -> CompatibilityCommandReceiptV1:
    payload = _mapping(value, label=label)
    _exact_keys(
        payload,
        {
            "argv",
            "candidate_archive_set_sha256",
            "candidate_version",
            "collector_outcome",
            "compatibility_plan_sha256",
            "completed_at_utc",
            "exit_code",
            "gate_id",
            "ordinal",
            "provider_incompatible_exit_codes",
            "receipt_sha256",
            "repository_source_sha",
            "result",
            "selection_nonce",
            "signal_number",
            "stack_identity_sha256",
            "started_at_utc",
            "stderr_sha256",
            "stderr_size_bytes",
            "stdout_sha256",
            "stdout_size_bytes",
            "timeout_seconds",
            "termination_kind",
        },
        label=label,
    )
    result = _string(payload["result"], label=f"{label} result", maximum=32)
    if result not in _COMMAND_RESULTS:
        _fail(f"{label} result is invalid")
    collector_outcome = _string(
        payload["collector_outcome"],
        label=f"{label} collector outcome",
        maximum=32,
    )
    if collector_outcome not in _COLLECTOR_OUTCOMES:
        _fail(f"{label} collector outcome is invalid")
    termination_kind = _string(
        payload["termination_kind"],
        label=f"{label} termination kind",
        maximum=32,
    )
    if termination_kind not in _PROCESS_TERMINATIONS:
        _fail(f"{label} termination kind is invalid")
    exit_code_raw = payload["exit_code"]
    exit_code = (
        None
        if exit_code_raw is None
        else _integer(exit_code_raw, label=f"{label} exit code", maximum=255)
    )
    signal_number_raw = payload["signal_number"]
    signal_number = (
        None
        if signal_number_raw is None
        else _integer(
            signal_number_raw,
            label=f"{label} signal number",
            minimum=1,
            maximum=255,
        )
    )
    return CompatibilityCommandReceiptV1(
        ordinal=_integer(payload["ordinal"], label=f"{label} ordinal", maximum=63),
        gate_id=_string(payload["gate_id"], label=f"{label} gate ID", maximum=64),
        argv=tuple(
            _string(argument, label=f"{label} argv[{index}]", maximum=4096)
            for index, argument in enumerate(_list(payload["argv"], label=f"{label} argv"))
        ),
        timeout_seconds=_integer(
            payload["timeout_seconds"],
            label=f"{label} timeout",
            minimum=1,
            maximum=21_600,
        ),
        provider_incompatible_exit_codes=tuple(
            _integer(
                item,
                label=f"{label} provider-incompatible exit code[{index}]",
                minimum=1,
                maximum=255,
            )
            for index, item in enumerate(
                _list(
                    payload["provider_incompatible_exit_codes"],
                    label=f"{label} provider-incompatible exit codes",
                )
            )
        ),
        candidate_version=_string(payload["candidate_version"], label=f"{label} candidate version"),
        candidate_archive_set_sha256=_sha256(
            payload["candidate_archive_set_sha256"],
            label=f"{label} archive-set SHA-256",
        ),
        repository_source_sha=_git_sha(
            payload["repository_source_sha"], label=f"{label} source SHA"
        ),
        stack_identity_sha256=_sha256(
            payload["stack_identity_sha256"], label=f"{label} stack SHA-256"
        ),
        compatibility_plan_sha256=_sha256(
            payload["compatibility_plan_sha256"], label=f"{label} plan SHA-256"
        ),
        selection_nonce=_sha256(payload["selection_nonce"], label=f"{label} selection nonce"),
        started_at_utc=_timestamp(payload["started_at_utc"], label=f"{label} start time")[0],
        completed_at_utc=_timestamp(payload["completed_at_utc"], label=f"{label} completion time")[
            0
        ],
        collector_outcome=cast("CollectorOutcome", collector_outcome),
        termination_kind=cast("ProcessTermination", termination_kind),
        exit_code=exit_code,
        signal_number=signal_number,
        stdout_size_bytes=_integer(payload["stdout_size_bytes"], label=f"{label} stdout size"),
        stdout_sha256=_sha256(payload["stdout_sha256"], label=f"{label} stdout SHA-256"),
        stderr_size_bytes=_integer(payload["stderr_size_bytes"], label=f"{label} stderr size"),
        stderr_sha256=_sha256(payload["stderr_sha256"], label=f"{label} stderr SHA-256"),
        result=cast("CommandResult", result),
        receipt_sha256=_sha256(payload["receipt_sha256"], label=f"{label} receipt SHA-256"),
    )


def _candidate_receipt_from_mapping(
    value: object,
    *,
    label: str,
) -> CandidateCompatibilityReceiptV1:
    payload = _mapping(value, label=label)
    _exact_keys(
        payload,
        {
            "candidate_archive_set_sha256",
            "candidate_version",
            "commands",
            "compatibility_plan_sha256",
            "kind",
            "outcome",
            "receipt_sha256",
            "repository_source_sha",
            "schema_version",
            "selection_nonce",
            "stack_identity_sha256",
        },
        label=label,
    )
    if payload["schema_version"] != 1 or payload["kind"] != "nbadb_nba_api_candidate_compatibility":
        _fail(f"{label} schema or kind is invalid")
    outcome = _string(payload["outcome"], label=f"{label} outcome", maximum=32)
    if outcome not in {"compatible", "provider_incompatible", "evidence_failure"}:
        _fail(f"{label} outcome is invalid")
    return CandidateCompatibilityReceiptV1(
        candidate_version=_string(payload["candidate_version"], label=f"{label} candidate version"),
        candidate_archive_set_sha256=_sha256(
            payload["candidate_archive_set_sha256"],
            label=f"{label} archive-set SHA-256",
        ),
        repository_source_sha=_git_sha(
            payload["repository_source_sha"], label=f"{label} source SHA"
        ),
        stack_identity_sha256=_sha256(
            payload["stack_identity_sha256"], label=f"{label} stack SHA-256"
        ),
        compatibility_plan_sha256=_sha256(
            payload["compatibility_plan_sha256"], label=f"{label} plan SHA-256"
        ),
        selection_nonce=_sha256(payload["selection_nonce"], label=f"{label} selection nonce"),
        commands=tuple(
            _command_receipt_from_mapping(item, label=f"{label} command[{index}]")
            for index, item in enumerate(_list(payload["commands"], label=f"{label} commands"))
        ),
        outcome=cast("CandidateOutcome", outcome),
        receipt_sha256=_sha256(payload["receipt_sha256"], label=f"{label} receipt SHA-256"),
    )


_PROVIDER_AUTHORITY_FIELDS = {
    "authority_sha256",
    "bronze_contract_sha256",
    "candidate_receipt_inventory_sha256",
    "compatibility_plan_sha256",
    "dependency_pin_version",
    "distribution_name",
    "distribution_version",
    "docs_tools_bundle_sha256",
    "fixture_version",
    "generated_authority_version",
    "installed_inventory_file_count",
    "installed_inventory_sha256",
    "installed_version",
    "kind",
    "license_identifier",
    "license_sha256",
    "live_contract_sha256",
    "live_headers_version",
    "lock_version",
    "locked_archive_sha256s",
    "metadata_ledger_sha256",
    "observed_at_utc",
    "parity_test_version",
    "provider_contract_sha256",
    "provider_evidence_sha256",
    "repository_source_sha",
    "runtime_contract_payload_sha256",
    "runtime_endpoint_contract_count",
    "runtime_endpoint_contract_sha256",
    "schema_version",
    "selected_candidate_receipt_sha256",
    "selection_nonce",
    "source_checkout_clean",
    "source_installed_file_parity",
    "source_inventory_file_count",
    "source_inventory_sha256",
    "standalone_connector_version",
    "static_contract_sha256",
    "stats_headers_version",
    "stack_identity_sha256",
    "upstream_commit_sha",
    "upstream_repository",
    "upstream_tag",
    "upstream_tag_commit_sha",
    "upstream_tree_sha",
}


def _provider_authority_from_mapping(
    value: object,
    *,
    label: str,
) -> ObservedProviderAuthorityV1:
    payload = _mapping(value, label=label)
    _exact_keys(payload, _PROVIDER_AUTHORITY_FIELDS, label=label)
    if (
        payload["schema_version"] != 1
        or payload["kind"] != "nbadb_nba_api_observed_provider_authority"
        or payload["distribution_name"] != PYPI_DISTRIBUTION_NAME
        or payload["upstream_repository"] != UPSTREAM_REPOSITORY
    ):
        _fail(f"{label} schema, distribution, or upstream authority is invalid")
    version = _string(payload["distribution_version"], label=f"{label} version")
    return ObservedProviderAuthorityV1(
        distribution_version=version,
        repository_source_sha=_git_sha(
            payload["repository_source_sha"],
            label=f"{label} repository source SHA",
        ),
        stack_identity_sha256=_sha256(
            payload["stack_identity_sha256"],
            label=f"{label} stack SHA-256",
        ),
        compatibility_plan_sha256=_sha256(
            payload["compatibility_plan_sha256"],
            label=f"{label} plan SHA-256",
        ),
        selection_nonce=_sha256(
            payload["selection_nonce"],
            label=f"{label} selection nonce",
        ),
        selected_candidate_receipt_sha256=_sha256(
            payload["selected_candidate_receipt_sha256"],
            label=f"{label} selected candidate receipt SHA-256",
        ),
        candidate_receipt_inventory_sha256=_sha256(
            payload["candidate_receipt_inventory_sha256"],
            label=f"{label} candidate inventory SHA-256",
        ),
        dependency_pin_version=_string(
            payload["dependency_pin_version"], label=f"{label} dependency pin version"
        ),
        lock_version=_string(payload["lock_version"], label=f"{label} lock version"),
        installed_version=_string(payload["installed_version"], label=f"{label} installed version"),
        standalone_connector_version=_string(
            payload["standalone_connector_version"],
            label=f"{label} standalone connector version",
        ),
        stats_headers_version=_string(
            payload["stats_headers_version"], label=f"{label} stats headers version"
        ),
        live_headers_version=_string(
            payload["live_headers_version"], label=f"{label} live headers version"
        ),
        generated_authority_version=_string(
            payload["generated_authority_version"],
            label=f"{label} generated authority version",
        ),
        fixture_version=_string(payload["fixture_version"], label=f"{label} fixture version"),
        parity_test_version=_string(
            payload["parity_test_version"], label=f"{label} parity-test version"
        ),
        locked_archive_sha256s=tuple(
            _sha256(item, label=f"{label} locked archive[{index}] SHA-256")
            for index, item in enumerate(
                _list(payload["locked_archive_sha256s"], label=f"{label} locked archives")
            )
        ),
        provider_contract_sha256=_sha256(
            payload["provider_contract_sha256"], label=f"{label} provider contract SHA-256"
        ),
        provider_evidence_sha256=_sha256(
            payload["provider_evidence_sha256"], label=f"{label} provider evidence SHA-256"
        ),
        upstream_tag=_string(payload["upstream_tag"], label=f"{label} upstream tag"),
        upstream_commit_sha=_git_sha(
            payload["upstream_commit_sha"], label=f"{label} upstream commit SHA"
        ),
        upstream_tag_commit_sha=_git_sha(
            payload["upstream_tag_commit_sha"], label=f"{label} upstream tag commit SHA"
        ),
        upstream_tree_sha=_git_sha(
            payload["upstream_tree_sha"], label=f"{label} upstream tree SHA"
        ),
        source_checkout_clean=_boolean(
            payload["source_checkout_clean"], label=f"{label} source checkout clean"
        ),
        source_inventory_file_count=_integer(
            payload["source_inventory_file_count"],
            label=f"{label} source inventory count",
            minimum=1,
        ),
        source_inventory_sha256=_sha256(
            payload["source_inventory_sha256"], label=f"{label} source inventory SHA-256"
        ),
        installed_inventory_file_count=_integer(
            payload["installed_inventory_file_count"],
            label=f"{label} installed inventory count",
            minimum=1,
        ),
        installed_inventory_sha256=_sha256(
            payload["installed_inventory_sha256"],
            label=f"{label} installed inventory SHA-256",
        ),
        source_installed_file_parity=_boolean(
            payload["source_installed_file_parity"],
            label=f"{label} source/installed parity",
        ),
        license_identifier=_string(
            payload["license_identifier"], label=f"{label} license identifier", maximum=128
        ),
        license_sha256=_sha256(payload["license_sha256"], label=f"{label} license SHA-256"),
        docs_tools_bundle_sha256=_sha256(
            payload["docs_tools_bundle_sha256"], label=f"{label} docs/tools SHA-256"
        ),
        runtime_contract_payload_sha256=_sha256(
            payload["runtime_contract_payload_sha256"],
            label=f"{label} runtime payload SHA-256",
        ),
        runtime_endpoint_contract_count=_integer(
            payload["runtime_endpoint_contract_count"],
            label=f"{label} runtime endpoint count",
            minimum=1,
        ),
        runtime_endpoint_contract_sha256=_sha256(
            payload["runtime_endpoint_contract_sha256"],
            label=f"{label} runtime endpoint SHA-256",
        ),
        live_contract_sha256=_sha256(
            payload["live_contract_sha256"], label=f"{label} live contract SHA-256"
        ),
        static_contract_sha256=_sha256(
            payload["static_contract_sha256"], label=f"{label} static contract SHA-256"
        ),
        bronze_contract_sha256=_sha256(
            payload["bronze_contract_sha256"], label=f"{label} bronze contract SHA-256"
        ),
        metadata_ledger_sha256=_sha256(
            payload["metadata_ledger_sha256"], label=f"{label} metadata ledger SHA-256"
        ),
        observed_at_utc=_timestamp(payload["observed_at_utc"], label=f"{label} observation time")[
            0
        ],
        authority_sha256=_sha256(payload["authority_sha256"], label=f"{label} authority SHA-256"),
    )


def _stable_candidates(
    release_inventory: tuple[ReleaseInventoryEntryV1, ...],
) -> tuple[ReleaseInventoryEntryV1, ...]:
    candidates = [
        entry
        for entry in release_inventory
        if entry.classification == "stable" and not entry.yanked
    ]
    candidates.sort(key=lambda entry: _classify_version(entry.version)[1], reverse=True)
    return tuple(candidates)


def _validate_stable_candidate_python_constraints(
    candidates: tuple[ReleaseInventoryEntryV1, ...],
) -> None:
    for candidate_index, candidate in enumerate(candidates):
        for archive_index, archive in enumerate(candidate.archives):
            _requires_python_specifier(
                archive.requires_python,
                label=(
                    f"stable candidate[{candidate_index}] archive[{archive_index}] Requires-Python"
                ),
            )


def _validate_command_joins(
    receipt: CandidateCompatibilityReceiptV1,
    *,
    archive_set_sha256: str,
    source_sha: str,
    stack_identity_sha256: str,
    plan_sha256: str,
    selection_nonce: str,
    commands: tuple[CompatibilityCommandSpecV1, ...],
    lower_time: datetime,
    upper_time: datetime,
) -> None:
    expected_header = (
        receipt.candidate_archive_set_sha256 == archive_set_sha256
        and receipt.repository_source_sha == source_sha
        and receipt.stack_identity_sha256 == stack_identity_sha256
        and receipt.compatibility_plan_sha256 == plan_sha256
        and receipt.selection_nonce == selection_nonce
    )
    if not expected_header:
        _fail("candidate compatibility receipt is rebound to foreign authority")
    if len(receipt.commands) != len(commands):
        _fail("candidate compatibility receipt omits or adds a declared command")
    previous_completion = lower_time
    for spec, command in zip(commands, receipt.commands, strict=True):
        expected_argv = _render_candidate_argv(
            spec.argv,
            candidate_version=receipt.candidate_version,
            archive_set_sha256=archive_set_sha256,
        )
        if (
            command.ordinal != spec.ordinal
            or command.gate_id != spec.gate_id
            or command.argv != expected_argv
            or command.timeout_seconds != spec.timeout_seconds
            or command.provider_incompatible_exit_codes != spec.provider_incompatible_exit_codes
        ):
            _fail("candidate command receipt differs from the exact compatibility plan")
        if (
            command.candidate_version != receipt.candidate_version
            or command.candidate_archive_set_sha256 != archive_set_sha256
            or command.repository_source_sha != source_sha
            or command.stack_identity_sha256 != stack_identity_sha256
            or command.compatibility_plan_sha256 != plan_sha256
            or command.selection_nonce != selection_nonce
        ):
            _fail("candidate command receipt is rebound to foreign authority")
        _, started = _timestamp(command.started_at_utc, label="command start time")
        _, completed = _timestamp(command.completed_at_utc, label="command completion time")
        if started < previous_completion or completed > upper_time:
            _fail("candidate command chronology is stale, overlapping, or out of order")
        previous_completion = completed


def _validate_selection_authority(authority: NbaApiReleaseSelectionAuthorityV1) -> None:
    _sha256(authority.pypi_inventory_sha256, label="PyPI inventory SHA-256")
    _integer(
        authority.pypi_inventory_size_bytes,
        label="PyPI inventory size",
        minimum=1,
        maximum=MAX_PYPI_INVENTORY_BYTES,
    )
    _sha256(authority.pypi_fetch_receipt_sha256, label="PyPI fetch receipt SHA-256")
    _, retrieved_at = _timestamp(
        authority.pypi_inventory_retrieved_at_utc,
        label="PyPI inventory retrieval time",
    )
    _integer(authority.pypi_last_serial, label="PyPI last serial", minimum=1)
    _, execution_kickoff = _timestamp(
        authority.execution_kickoff_at_utc,
        label="execution kickoff time",
    )
    _, selection_completed = _timestamp(
        authority.selection_completed_at_utc,
        label="release selection completion time",
    )
    _, trusted_now = _timestamp(authority.trusted_now_at_utc, label="trusted point-of-use time")
    if not (
        execution_kickoff <= retrieved_at <= selection_completed <= trusted_now
        and selection_completed - execution_kickoff <= MAX_SELECTION_DURATION
        and trusted_now - selection_completed <= MAX_POINT_OF_USE_DELAY
    ):
        _fail("PyPI inventory or release-selection evidence is stale at point of use")
    _git_sha(authority.repository_source_sha, label="selection repository source SHA")
    _sha256(authority.stack_identity_sha256, label="selection stack-identity SHA-256")
    _, stack_python_version = _python_version(
        authority.stack_python_version,
        label="selection stack Python version",
    )
    _sha256(authority.compatibility_plan_sha256, label="selection plan SHA-256")
    _sha256(authority.selection_nonce, label="selection nonce")
    clock = authority.execution_clock_receipt
    if type(clock) is not ExecutionClockReceiptV1:
        _fail("selection execution-clock receipt is invalid")
    if (
        clock.phase != "selection"
        or clock.receipt_sha256 != authority.execution_clock_receipt_sha256
        or clock.collector_authority_sha256 != authority.clock_collector_authority_sha256
        or clock.repository_source_sha != authority.repository_source_sha
        or clock.stack_identity_sha256 != authority.stack_identity_sha256
        or clock.compatibility_plan_sha256 != authority.compatibility_plan_sha256
        or clock.selection_nonce != authority.selection_nonce
        or clock.execution_kickoff_at_utc != authority.execution_kickoff_at_utc
        or clock.selection_completed_at_utc != authority.selection_completed_at_utc
        or clock.observed_now_at_utc != authority.trusted_now_at_utc
    ):
        _fail("selection execution-clock receipt is rebound to foreign authority")
    _sha256(
        authority.execution_clock_receipt_sha256,
        label="selection execution-clock receipt SHA-256",
    )
    _sha256(
        authority.clock_collector_authority_sha256,
        label="selection clock collector authority SHA-256",
    )

    if type(authority.release_inventory) is not tuple or not authority.release_inventory:
        _fail("release inventory must be one nonempty exact tuple")
    if any(type(entry) is not ReleaseInventoryEntryV1 for entry in authority.release_inventory):
        _fail("release inventory contains an invalid entry")
    if tuple(sorted(authority.release_inventory, key=lambda entry: entry.version)) != (
        authority.release_inventory
    ):
        _fail("release inventory must use deterministic version-key order")
    if len({entry.version for entry in authority.release_inventory}) != len(
        authority.release_inventory
    ):
        _fail("release inventory contains duplicate version keys")
    expected_inventory_sha256 = _sha256_bytes(
        canonical_json_bytes([entry.to_dict() for entry in authority.release_inventory])
    )
    if (
        _sha256(authority.release_inventory_sha256, label="release inventory SHA-256")
        != expected_inventory_sha256
    ):
        _fail("normalized release inventory digest is invalid")

    stable = _stable_candidates(authority.release_inventory)
    _validate_stable_candidate_python_constraints(stable)
    expected_stable_versions = tuple(entry.version for entry in stable)
    if authority.stable_candidate_versions != expected_stable_versions or not stable:
        _fail("stable candidate order is incomplete or not newest-to-oldest")
    if type(authority.compatibility_commands) is not tuple or not authority.compatibility_commands:
        _fail("compatibility command inventory must be one nonempty exact tuple")
    if any(
        type(command) is not CompatibilityCommandSpecV1
        for command in authority.compatibility_commands
    ):
        _fail("compatibility command inventory contains an invalid command")
    if tuple(command.ordinal for command in authority.compatibility_commands) != tuple(
        range(len(authority.compatibility_commands))
    ):
        _fail("compatibility command order is invalid")
    if len({command.gate_id for command in authority.compatibility_commands}) != len(
        authority.compatibility_commands
    ):
        _fail("compatibility command gate IDs are not unique")
    expected_plan_sha256 = _sha256_bytes(
        canonical_json_bytes(
            {
                "commands": [command.to_dict() for command in authority.compatibility_commands],
                "kind": "nbadb_nba_api_compatibility_plan",
                "repository_source_sha": authority.repository_source_sha,
                "schema_version": 1,
                "selection_nonce": authority.selection_nonce,
                "stack_identity_sha256": authority.stack_identity_sha256,
            }
        )
    )
    if authority.compatibility_plan_sha256 != expected_plan_sha256:
        _fail("compatibility commands differ from the sealed compatibility plan")
    if type(authority.candidate_receipts) is not tuple or not authority.candidate_receipts:
        _fail("candidate receipt inventory must be one nonempty exact tuple")
    if len(authority.candidate_receipts) > len(stable):
        _fail("candidate receipt inventory contains an extra candidate")
    expected_receipt_versions = expected_stable_versions[: len(authority.candidate_receipts)]
    if tuple(receipt.candidate_version for receipt in authority.candidate_receipts) != (
        expected_receipt_versions
    ):
        _fail("candidate receipts omit, duplicate, or reorder stable releases")
    if len({receipt.receipt_sha256 for receipt in authority.candidate_receipts}) != len(
        authority.candidate_receipts
    ):
        _fail("candidate receipt inventory contains duplicate receipts")
    expected_receipt_sha256s = tuple(
        receipt.receipt_sha256 for receipt in authority.candidate_receipts
    )
    if authority.candidate_receipt_sha256s != expected_receipt_sha256s:
        _fail("candidate receipt SHA-256 inventory differs from the exact receipts")
    expected_receipt_inventory_sha256 = _candidate_receipt_inventory_sha256(
        expected_receipt_sha256s
    )
    if (
        _sha256(
            authority.candidate_receipt_inventory_sha256,
            label="candidate receipt inventory SHA-256",
        )
        != expected_receipt_inventory_sha256
    ):
        _fail("candidate receipt inventory root is invalid")

    compatible_indices = [
        index
        for index, receipt in enumerate(authority.candidate_receipts)
        if receipt.outcome == "compatible"
    ]
    if compatible_indices != [len(authority.candidate_receipts) - 1]:
        _fail("candidate receipt sequence must end at its first compatible release")
    if any(
        receipt.outcome != "provider_incompatible" for receipt in authority.candidate_receipts[:-1]
    ):
        _fail("candidate rejection evidence is not a provider incompatibility")
    candidate_lower_time = retrieved_at
    for entry, receipt in zip(stable, authority.candidate_receipts, strict=False):
        _validate_command_joins(
            receipt,
            archive_set_sha256=entry.archive_set_sha256,
            source_sha=authority.repository_source_sha,
            stack_identity_sha256=authority.stack_identity_sha256,
            plan_sha256=authority.compatibility_plan_sha256,
            selection_nonce=authority.selection_nonce,
            commands=authority.compatibility_commands,
            lower_time=candidate_lower_time,
            upper_time=selection_completed,
        )
        candidate_lower_time = _timestamp(
            receipt.commands[-1].completed_at_utc,
            label="candidate completion time",
        )[1]
    selected_entry = stable[len(authority.candidate_receipts) - 1]
    if authority.selected_version != selected_entry.version:
        _fail("selected version is not the first all-green stable candidate")
    if (
        authority.selected_archives != selected_entry.archives
        or authority.selected_archive_set_sha256 != selected_entry.archive_set_sha256
    ):
        _fail("selected archive inventory differs from the selected PyPI release")
    for index, archive in enumerate(authority.selected_archives):
        _requires_python_allows(
            archive.requires_python,
            python_version=stack_python_version,
            label=f"selected archive[{index}] Requires-Python",
        )
    if authority.rejected_newer_versions != tuple(
        receipt.candidate_version for receipt in authority.candidate_receipts[:-1]
    ):
        _fail("rejected-newer candidate inventory is invalid")

    provider = authority.selected_provider_authority
    if type(provider) is not ObservedProviderAuthorityV1:
        _fail("selected provider authority is invalid")
    if (
        provider.distribution_version != authority.selected_version
        or provider.authority_sha256 != authority.selected_provider_authority_sha256
        or provider.repository_source_sha != authority.repository_source_sha
        or provider.stack_identity_sha256 != authority.stack_identity_sha256
        or provider.compatibility_plan_sha256 != authority.compatibility_plan_sha256
        or provider.selection_nonce != authority.selection_nonce
        or provider.selected_candidate_receipt_sha256
        != authority.candidate_receipts[-1].receipt_sha256
        or provider.candidate_receipt_inventory_sha256
        != authority.candidate_receipt_inventory_sha256
        or provider.locked_archive_sha256s
        != tuple(sorted(archive.sha256 for archive in authority.selected_archives))
    ):
        _fail("selected provider authority is mixed or rebound to other archives")
    _, observed_at = _timestamp(provider.observed_at_utc, label="provider observation time")
    selected_candidate_completed = _timestamp(
        authority.candidate_receipts[-1].commands[-1].completed_at_utc,
        label="selected candidate completion time",
    )[1]
    if not (selected_candidate_completed <= observed_at <= selection_completed):
        _fail("selected provider observation is stale or outside the selection window")
    _sha256(
        authority.selected_provider_authority_sha256,
        label="selected provider authority SHA-256",
    )
    if _sha256(authority.authority_sha256, label="selection authority SHA-256") != (
        _digest_body(authority.to_dict(), "authority_sha256")
    ):
        _fail("release-selection authority digest is invalid")


def _validate_external_authority_roots(
    authority: NbaApiReleaseSelectionAuthorityV1,
    *,
    expected_authority_sha256: str,
    expected_pypi_inventory_sha256: str,
    expected_pypi_fetch_receipt_sha256: str,
    expected_repository_source_sha: str,
    expected_stack_identity_sha256: str,
    expected_compatibility_plan_sha256: str,
    expected_candidate_receipt_sha256s: tuple[str, ...],
    expected_candidate_receipt_inventory_sha256: str,
    expected_selected_provider_authority_sha256: str,
    expected_execution_clock_receipt_sha256: str,
    expected_clock_collector_authority_sha256: str,
    readback_clock: ExecutionClockReceiptV1,
) -> None:
    expected_receipt_inventory = _candidate_receipt_inventory_sha256(
        expected_candidate_receipt_sha256s
    )
    expected_receipt_inventory_root = _sha256(
        expected_candidate_receipt_inventory_sha256,
        label="expected candidate receipt inventory SHA-256",
    )
    if expected_receipt_inventory != expected_receipt_inventory_root:
        _fail("expected candidate receipt inventory root is internally inconsistent")

    if (
        authority.authority_sha256
        != _sha256(expected_authority_sha256, label="expected selection authority SHA-256")
        or authority.pypi_inventory_sha256
        != _sha256(expected_pypi_inventory_sha256, label="expected PyPI inventory SHA-256")
        or authority.pypi_fetch_receipt_sha256
        != _sha256(
            expected_pypi_fetch_receipt_sha256,
            label="expected PyPI fetch receipt SHA-256",
        )
        or authority.repository_source_sha
        != _git_sha(expected_repository_source_sha, label="expected repository source SHA")
        or authority.stack_identity_sha256
        != _sha256(
            expected_stack_identity_sha256,
            label="expected stack identity SHA-256",
        )
        or authority.compatibility_plan_sha256
        != _sha256(
            expected_compatibility_plan_sha256,
            label="expected compatibility plan SHA-256",
        )
        or authority.candidate_receipt_sha256s != expected_candidate_receipt_sha256s
        or authority.candidate_receipt_inventory_sha256 != expected_receipt_inventory_root
        or authority.selected_provider_authority_sha256
        != _sha256(
            expected_selected_provider_authority_sha256,
            label="expected selected provider authority SHA-256",
        )
        or authority.execution_clock_receipt_sha256
        != _sha256(
            expected_execution_clock_receipt_sha256,
            label="expected selection execution-clock receipt SHA-256",
        )
        or authority.clock_collector_authority_sha256
        != _sha256(
            expected_clock_collector_authority_sha256,
            label="expected clock collector authority SHA-256",
        )
    ):
        _fail("release-selection authority differs from its independent trust roots")

    _, trusted_now = _timestamp(
        readback_clock.observed_now_at_utc,
        label="authenticated readback point-of-use time",
    )
    _, sealed_trusted_now = _timestamp(
        authority.trusted_now_at_utc,
        label="sealed trusted point-of-use time",
    )
    _, selection_completed = _timestamp(
        authority.selection_completed_at_utc,
        label="release selection completion time",
    )
    if not (
        sealed_trusted_now <= trusted_now
        and selection_completed <= trusted_now
        and trusted_now - selection_completed <= MAX_POINT_OF_USE_DELAY
    ):
        _fail("release-selection authority is stale at canonical readback")


_SELECTION_AUTHORITY_FIELDS = {
    "authority_sha256",
    "candidate_receipt_inventory_sha256",
    "candidate_receipt_sha256s",
    "candidate_receipts",
    "compatibility_commands",
    "compatibility_plan_sha256",
    "clock_collector_authority_sha256",
    "distribution_name",
    "execution_clock_receipt",
    "execution_clock_receipt_sha256",
    "execution_kickoff_at_utc",
    "kind",
    "project_name",
    "pypi_fetch_receipt_sha256",
    "pypi_inventory_retrieved_at_utc",
    "pypi_inventory_sha256",
    "pypi_inventory_size_bytes",
    "pypi_last_serial",
    "rejected_newer_versions",
    "release_inventory",
    "release_inventory_sha256",
    "repository_source_sha",
    "schema_version",
    "selected_archive_set_sha256",
    "selected_archives",
    "selected_provider_authority",
    "selected_provider_authority_sha256",
    "selected_version",
    "selection_completed_at_utc",
    "selection_nonce",
    "stable_candidate_versions",
    "stack_identity_sha256",
    "stack_python_version",
    "trusted_now_at_utc",
}


def _authority_from_mapping(payload: Mapping[str, object]) -> NbaApiReleaseSelectionAuthorityV1:
    _exact_keys(payload, _SELECTION_AUTHORITY_FIELDS, label="release-selection authority")
    if (
        payload["schema_version"] != 1
        or payload["kind"] != "nbadb_nba_api_release_selection_authority"
        or payload["project_name"] != PYPI_PROJECT_NAME
        or payload["distribution_name"] != PYPI_DISTRIBUTION_NAME
    ):
        _fail("release-selection authority schema, project, or distribution is invalid")
    selected_version = _string(
        payload["selected_version"], label="selected release version", maximum=128
    )
    return NbaApiReleaseSelectionAuthorityV1(
        pypi_inventory_sha256=_sha256(
            payload["pypi_inventory_sha256"], label="PyPI inventory SHA-256"
        ),
        pypi_inventory_size_bytes=_integer(
            payload["pypi_inventory_size_bytes"],
            label="PyPI inventory size",
            minimum=1,
            maximum=MAX_PYPI_INVENTORY_BYTES,
        ),
        pypi_fetch_receipt_sha256=_sha256(
            payload["pypi_fetch_receipt_sha256"], label="PyPI fetch receipt SHA-256"
        ),
        pypi_inventory_retrieved_at_utc=_timestamp(
            payload["pypi_inventory_retrieved_at_utc"], label="PyPI retrieval time"
        )[0],
        pypi_last_serial=_integer(payload["pypi_last_serial"], label="PyPI last serial", minimum=1),
        execution_kickoff_at_utc=_timestamp(
            payload["execution_kickoff_at_utc"], label="execution kickoff time"
        )[0],
        selection_completed_at_utc=_timestamp(
            payload["selection_completed_at_utc"], label="selection completion time"
        )[0],
        trusted_now_at_utc=_timestamp(
            payload["trusted_now_at_utc"], label="trusted point-of-use time"
        )[0],
        execution_clock_receipt=_execution_clock_receipt_from_mapping(
            payload["execution_clock_receipt"],
            label="selection execution-clock receipt",
        ),
        execution_clock_receipt_sha256=_sha256(
            payload["execution_clock_receipt_sha256"],
            label="selection execution-clock receipt SHA-256",
        ),
        clock_collector_authority_sha256=_sha256(
            payload["clock_collector_authority_sha256"],
            label="clock collector authority SHA-256",
        ),
        repository_source_sha=_git_sha(
            payload["repository_source_sha"], label="repository source SHA"
        ),
        stack_identity_sha256=_sha256(
            payload["stack_identity_sha256"], label="stack identity SHA-256"
        ),
        stack_python_version=_python_version(
            payload["stack_python_version"],
            label="stack Python version",
        )[0],
        compatibility_plan_sha256=_sha256(
            payload["compatibility_plan_sha256"], label="compatibility plan SHA-256"
        ),
        selection_nonce=_sha256(payload["selection_nonce"], label="selection nonce"),
        release_inventory=tuple(
            _release_entry_from_mapping(item, label=f"release inventory[{index}]")
            for index, item in enumerate(
                _list(payload["release_inventory"], label="release inventory")
            )
        ),
        release_inventory_sha256=_sha256(
            payload["release_inventory_sha256"], label="release inventory SHA-256"
        ),
        stable_candidate_versions=tuple(
            _string(item, label=f"stable candidate[{index}]", maximum=128)
            for index, item in enumerate(
                _list(payload["stable_candidate_versions"], label="stable candidates")
            )
        ),
        compatibility_commands=tuple(
            _command_spec_from_mapping(item, label=f"compatibility command[{index}]")
            for index, item in enumerate(
                _list(payload["compatibility_commands"], label="compatibility commands")
            )
        ),
        candidate_receipts=tuple(
            _candidate_receipt_from_mapping(item, label=f"candidate receipt[{index}]")
            for index, item in enumerate(
                _list(payload["candidate_receipts"], label="candidate receipts")
            )
        ),
        candidate_receipt_sha256s=tuple(
            _sha256(item, label=f"candidate receipt SHA-256[{index}]")
            for index, item in enumerate(
                _list(
                    payload["candidate_receipt_sha256s"],
                    label="candidate receipt SHA-256 inventory",
                )
            )
        ),
        candidate_receipt_inventory_sha256=_sha256(
            payload["candidate_receipt_inventory_sha256"],
            label="candidate receipt inventory SHA-256",
        ),
        selected_version=selected_version,
        selected_archives=tuple(
            _archive_from_mapping(
                item,
                version=selected_version,
                label=f"selected archive[{index}]",
            )
            for index, item in enumerate(
                _list(payload["selected_archives"], label="selected archives")
            )
        ),
        selected_archive_set_sha256=_sha256(
            payload["selected_archive_set_sha256"], label="selected archive-set SHA-256"
        ),
        rejected_newer_versions=tuple(
            _string(item, label=f"rejected candidate[{index}]", maximum=128)
            for index, item in enumerate(
                _list(payload["rejected_newer_versions"], label="rejected candidates")
            )
        ),
        selected_provider_authority=_provider_authority_from_mapping(
            payload["selected_provider_authority"], label="selected provider authority"
        ),
        selected_provider_authority_sha256=_sha256(
            payload["selected_provider_authority_sha256"],
            label="selected provider authority SHA-256",
        ),
        authority_sha256=_sha256(payload["authority_sha256"], label="selection authority SHA-256"),
    )


def select_latest_compatible_release(
    *,
    pypi_inventory_bytes: bytes,
    pypi_fetch_receipt_bytes: bytes,
    repository_stack_identity_bytes: bytes,
    compatibility_plan_bytes: bytes,
    candidate_compatibility_receipt_bytes: tuple[bytes, ...],
    selected_provider_authority_bytes: bytes,
    execution_clock_receipt_bytes: bytes,
    expected_pypi_fetch_receipt_sha256: str,
    expected_repository_source_sha: str,
    expected_stack_identity_sha256: str,
    expected_compatibility_plan_sha256: str,
    expected_candidate_receipt_sha256s: tuple[str, ...],
    expected_candidate_receipt_inventory_sha256: str,
    expected_selected_provider_authority_sha256: str,
    expected_execution_clock_receipt_sha256: str,
    expected_clock_collector_authority_sha256: str,
) -> NbaApiReleaseSelectionAuthorityV1:
    """Validate injected evidence and freeze the first compatible stable release.

    Every ``expected_*`` digest/source value is an external trust-root input.
    The corresponding canonical bytes are still mandatory; a digest, constant,
    installed version, local pin, or success boolean alone is insufficient.
    """

    source_sha = _git_sha(
        expected_repository_source_sha,
        label="expected repository source SHA",
    )
    expected_stack_sha256 = _sha256(
        expected_stack_identity_sha256,
        label="expected stack identity SHA-256",
    )
    expected_plan_sha256 = _sha256(
        expected_compatibility_plan_sha256,
        label="expected compatibility plan SHA-256",
    )
    expected_provider_sha256 = _sha256(
        expected_selected_provider_authority_sha256,
        label="expected selected provider authority SHA-256",
    )
    expected_candidate_inventory_sha256 = _candidate_receipt_inventory_sha256(
        expected_candidate_receipt_sha256s
    )
    if expected_candidate_inventory_sha256 != _sha256(
        expected_candidate_receipt_inventory_sha256,
        label="expected candidate receipt inventory SHA-256",
    ):
        _fail("expected candidate receipt inventory root is internally inconsistent")

    stack_identity_sha256, stack_python_version = _parse_stack_identity(
        repository_stack_identity_bytes,
        expected_source_sha=source_sha,
        expected_identity_sha256=expected_stack_sha256,
    )
    selection_nonce, plan_sha256, compatibility_commands = _parse_compatibility_plan(
        compatibility_plan_bytes,
        expected_source_sha=source_sha,
        expected_stack_identity_sha256=stack_identity_sha256,
        expected_plan_sha256=expected_plan_sha256,
    )
    execution_clock = _parse_execution_clock_receipt(
        execution_clock_receipt_bytes,
        label="selection execution-clock receipt",
        expected_phase="selection",
        expected_receipt_sha256=expected_execution_clock_receipt_sha256,
        expected_collector_authority_sha256=expected_clock_collector_authority_sha256,
        expected_source_sha=source_sha,
        expected_stack_identity_sha256=stack_identity_sha256,
        expected_compatibility_plan_sha256=plan_sha256,
        expected_selection_nonce=selection_nonce,
    )
    kickoff_text = execution_clock.execution_kickoff_at_utc
    completion_text = execution_clock.selection_completed_at_utc
    trusted_now_text = execution_clock.observed_now_at_utc
    _, execution_kickoff = _timestamp(kickoff_text, label="execution kickoff time")
    _, selection_completed = _timestamp(completion_text, label="selection completion time")

    inventory_payload = _decode_json_bytes(
        pypi_inventory_bytes,
        label="official PyPI inventory",
        maximum_bytes=MAX_PYPI_INVENTORY_BYTES,
        canonical=False,
    )
    inventory_sha256 = _sha256_bytes(pypi_inventory_bytes)
    release_inventory, pypi_last_serial = _release_inventory_from_pypi(inventory_payload)
    retrieved_at_utc, fetch_receipt_sha256 = _parse_fetch_receipt(
        pypi_fetch_receipt_bytes,
        inventory_bytes=pypi_inventory_bytes,
        expected_receipt_sha256=expected_pypi_fetch_receipt_sha256,
    )
    _, retrieved_at = _timestamp(retrieved_at_utc, label="PyPI retrieval time")
    if not execution_kickoff <= retrieved_at <= selection_completed:
        _fail("PyPI inventory retrieval is stale or outside the selection window")

    if (
        type(candidate_compatibility_receipt_bytes) is not tuple
        or not candidate_compatibility_receipt_bytes
    ):
        _fail("candidate receipt byte inventory must be one nonempty exact tuple")
    candidate_receipts: list[CandidateCompatibilityReceiptV1] = []
    for index, raw in enumerate(candidate_compatibility_receipt_bytes):
        payload = _decode_json_bytes(
            raw,
            label=f"candidate receipt[{index}]",
            maximum_bytes=MAX_CANONICAL_RECEIPT_BYTES,
            canonical=True,
        )
        candidate_receipts.append(
            _candidate_receipt_from_mapping(payload, label=f"candidate receipt[{index}]")
        )
    candidate_receipt_sha256s = tuple(receipt.receipt_sha256 for receipt in candidate_receipts)
    if candidate_receipt_sha256s != expected_candidate_receipt_sha256s:
        _fail("candidate receipt inventory differs from its independent trust root")
    if any(receipt.outcome == "evidence_failure" for receipt in candidate_receipts):
        _fail("candidate compatibility evidence contains a non-provider failure")
    compatible_receipts = [
        receipt for receipt in candidate_receipts if receipt.outcome == "compatible"
    ]
    if len(compatible_receipts) != 1 or compatible_receipts[0] is not candidate_receipts[-1]:
        _fail("candidate evidence must stop at the first all-green release")
    if any(receipt.outcome != "provider_incompatible" for receipt in candidate_receipts[:-1]):
        _fail("newer candidate rejection is not proven provider incompatibility")

    provider_payload = _decode_json_bytes(
        selected_provider_authority_bytes,
        label="selected provider authority",
        maximum_bytes=MAX_CANONICAL_RECEIPT_BYTES,
        canonical=True,
    )
    selected_provider = _provider_authority_from_mapping(
        provider_payload,
        label="selected provider authority",
    )
    if selected_provider.authority_sha256 != expected_provider_sha256:
        _fail("selected provider authority differs from its independent trust root")

    stable = _stable_candidates(release_inventory)
    if not stable:
        _fail("official PyPI inventory has no non-yanked stable candidate")
    _validate_stable_candidate_python_constraints(stable)
    selected_version = candidate_receipts[-1].candidate_version
    selected_entry = next(
        (entry for entry in stable if entry.version == selected_version),
        None,
    )
    if selected_entry is None:
        _fail("compatible receipt does not identify a non-yanked stable release")
    _, parsed_stack_python_version = _python_version(
        stack_python_version,
        label="repository stack Python version",
    )
    for index, archive in enumerate(selected_entry.archives):
        _requires_python_allows(
            archive.requires_python,
            python_version=parsed_stack_python_version,
            label=f"selected archive[{index}] Requires-Python",
        )

    release_inventory_sha256 = _sha256_bytes(
        canonical_json_bytes([entry.to_dict() for entry in release_inventory])
    )
    stable_candidate_versions = tuple(entry.version for entry in stable)
    rejected_newer_versions = tuple(
        receipt.candidate_version for receipt in candidate_receipts[:-1]
    )
    candidate_receipt_tuple = tuple(candidate_receipts)
    body: dict[str, object] = {
        "candidate_receipt_inventory_sha256": expected_candidate_inventory_sha256,
        "candidate_receipt_sha256s": list(candidate_receipt_sha256s),
        "candidate_receipts": [receipt.to_dict() for receipt in candidate_receipt_tuple],
        "compatibility_commands": [command.to_dict() for command in compatibility_commands],
        "compatibility_plan_sha256": plan_sha256,
        "clock_collector_authority_sha256": execution_clock.collector_authority_sha256,
        "distribution_name": PYPI_DISTRIBUTION_NAME,
        "execution_clock_receipt": execution_clock.to_dict(),
        "execution_clock_receipt_sha256": execution_clock.receipt_sha256,
        "execution_kickoff_at_utc": kickoff_text,
        "kind": "nbadb_nba_api_release_selection_authority",
        "project_name": PYPI_PROJECT_NAME,
        "pypi_fetch_receipt_sha256": fetch_receipt_sha256,
        "pypi_inventory_retrieved_at_utc": retrieved_at_utc,
        "pypi_inventory_sha256": inventory_sha256,
        "pypi_inventory_size_bytes": len(pypi_inventory_bytes),
        "pypi_last_serial": pypi_last_serial,
        "rejected_newer_versions": list(rejected_newer_versions),
        "release_inventory": [entry.to_dict() for entry in release_inventory],
        "release_inventory_sha256": release_inventory_sha256,
        "repository_source_sha": source_sha,
        "schema_version": 1,
        "selected_archive_set_sha256": selected_entry.archive_set_sha256,
        "selected_archives": [archive.to_dict() for archive in selected_entry.archives],
        "selected_provider_authority": selected_provider.to_dict(),
        "selected_provider_authority_sha256": selected_provider.authority_sha256,
        "selected_version": selected_version,
        "selection_completed_at_utc": completion_text,
        "selection_nonce": selection_nonce,
        "stable_candidate_versions": list(stable_candidate_versions),
        "stack_identity_sha256": stack_identity_sha256,
        "stack_python_version": stack_python_version,
        "trusted_now_at_utc": trusted_now_text,
    }
    authority_sha256 = _sha256_bytes(canonical_json_bytes(body))
    return NbaApiReleaseSelectionAuthorityV1(
        pypi_inventory_sha256=inventory_sha256,
        pypi_inventory_size_bytes=len(pypi_inventory_bytes),
        pypi_fetch_receipt_sha256=fetch_receipt_sha256,
        pypi_inventory_retrieved_at_utc=retrieved_at_utc,
        pypi_last_serial=pypi_last_serial,
        execution_kickoff_at_utc=kickoff_text,
        selection_completed_at_utc=completion_text,
        trusted_now_at_utc=trusted_now_text,
        execution_clock_receipt=execution_clock,
        execution_clock_receipt_sha256=execution_clock.receipt_sha256,
        clock_collector_authority_sha256=execution_clock.collector_authority_sha256,
        repository_source_sha=source_sha,
        stack_identity_sha256=stack_identity_sha256,
        stack_python_version=stack_python_version,
        compatibility_plan_sha256=plan_sha256,
        selection_nonce=selection_nonce,
        release_inventory=release_inventory,
        release_inventory_sha256=release_inventory_sha256,
        stable_candidate_versions=stable_candidate_versions,
        compatibility_commands=compatibility_commands,
        candidate_receipts=candidate_receipt_tuple,
        candidate_receipt_sha256s=candidate_receipt_sha256s,
        candidate_receipt_inventory_sha256=expected_candidate_inventory_sha256,
        selected_version=selected_version,
        selected_archives=selected_entry.archives,
        selected_archive_set_sha256=selected_entry.archive_set_sha256,
        rejected_newer_versions=rejected_newer_versions,
        selected_provider_authority=selected_provider,
        selected_provider_authority_sha256=selected_provider.authority_sha256,
        authority_sha256=authority_sha256,
    )


__all__ = [
    "CandidateOutcome",
    "CandidateCompatibilityReceiptV1",
    "ClockPhase",
    "CollectorOutcome",
    "CommandResult",
    "CompatibilityCommandReceiptV1",
    "CompatibilityCommandSpecV1",
    "ExecutionClockReceiptV1",
    "NbaApiReleaseSelectionAuthorityV1",
    "NbaApiReleaseSelectionError",
    "ObservedProviderAuthorityV1",
    "ProcessTermination",
    "ReleaseArchiveV1",
    "ReleaseInventoryEntryV1",
    "canonical_json_bytes",
    "select_latest_compatible_release",
]
