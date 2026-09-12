from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, SupportsIndex, cast

RUN_KEY_DOMAIN_ID = "nbadb.vpn-cohort.run-key.v1"
RUN_KEY_VERSION = "hmac-sha256-v1"
PROBE_RECEIPT_DOMAIN = b"nbadb/vpn-cohort/probe-receipt/v1"
SELECTION_RECEIPT_DOMAIN = b"nbadb/vpn-cohort/selection-receipt/v1"
BARRIER_CHALLENGE_DOMAIN = b"nbadb/vpn-cohort/barrier-challenge/v1"
RECONNECT_RECEIPT_DOMAIN = b"nbadb/vpn-cohort/reconnect-receipt/v1"
RESELECTION_RECEIPT_DOMAIN = b"nbadb/vpn-cohort/reselection-receipt/v1"
ADMISSION_RECEIPT_DOMAIN = b"nbadb/vpn-cohort/admission-receipt/v1"
AUTHORITY_PROOF_DOMAIN = b"nbadb/vpn-cohort/authority-proof/v1"
SERVER_COMMITMENT_DOMAIN = b"nbadb/vpn-cohort/server-commitment/v1"
EXIT_COMMITMENT_DOMAIN = b"nbadb/vpn-cohort/exit-commitment/v1"

PROBE_SLOT_COUNT = 6
MINIMUM_COHORT_SIZE = 4
MAXIMUM_COHORT_SIZE = 6
MINIMUM_MASTER_SECRET_BYTES = 32
MINIMUM_BARRIER_NONCE_BYTES = 16

_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SLOT_RE = re.compile(r"slot-([0-5])")
_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
)


class VpnCohortControlError(RuntimeError):
    """Base class for sanitized, expected offline cohort-control failures."""


class InputValidationError(VpnCohortControlError):
    """Raised when an input does not satisfy the bounded control contract."""


class AuthorityMismatchError(VpnCohortControlError):
    """Raised when an artifact belongs to another derivation authority."""


class ReceiptIntegrityError(VpnCohortControlError):
    """Raised when a keyed receipt is malformed or fails authentication."""


class ProbeInventoryError(VpnCohortControlError):
    """Raised when the six-slot probe inventory is incomplete or ambiguous."""


class DuplicateCommitmentError(ProbeInventoryError):
    """Raised when independently assigned slots resolve to one opaque identity."""


class InsufficientCapacityError(ProbeInventoryError):
    """Raised when fewer than four independently valid slots remain."""


class BarrierAdmissionError(VpnCohortControlError):
    """Raised when reconnect evidence cannot authorize matrix admission."""


class ReselectionNotPermittedError(BarrierAdmissionError):
    """Raised when a requested downgrade is untyped or exceeds its one-use budget."""


class CommitmentKind(StrEnum):
    SERVER = "server"
    EXIT = "exit"


class FailureKind(StrEnum):
    AUTH_CAPACITY_LOSS = "auth_capacity_loss"
    CAPACITY_LOSS = "capacity_loss"
    PROCESS_FAILURE = "process_failure"
    ROUTE_FAILURE = "route_failure"
    GITHUB_FAILURE = "github_failure"
    NBA_FAILURE = "nba_failure"


RESELECTABLE_FAILURES = frozenset({FailureKind.AUTH_CAPACITY_LOSS, FailureKind.CAPACITY_LOSS})


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InputValidationError("receipt payload is not canonical JSON") from exc


def _digest_payload(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _frame(domain: bytes, *parts: bytes) -> bytes:
    framed = bytearray(domain)
    framed.extend(b"\x00")
    for part in parts:
        framed.extend(len(part).to_bytes(8, "big"))
        framed.extend(part)
    return bytes(framed)


def _exact_keys(payload: Mapping[str, object], expected: set[str], kind: str) -> None:
    if set(payload) != expected:
        raise InputValidationError(f"{kind} fields are not exact")


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InputValidationError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise InputValidationError(f"{field} keys must be strings")
    return cast("Mapping[str, object]", value)


def _sequence(value: object, field: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InputValidationError(f"{field} must be an array")
    return cast("Sequence[object]", value)


def _text(value: object, field: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise InputValidationError(f"{field} must be text")
    if not value or value != value.strip() or len(value) > maximum:
        raise InputValidationError(f"{field} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise InputValidationError(f"{field} is invalid")
    return value


def _integer(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputValidationError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise InputValidationError(f"{field} is outside the allowed range")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise InputValidationError(f"{field} must be boolean")
    return value


def _hex(value: object, field: str, pattern: re.Pattern[str]) -> str:
    normalized = _text(value, field).lower()
    if pattern.fullmatch(normalized) is None:
        raise InputValidationError(f"{field} has an invalid digest")
    return normalized


def _slot_label(value: object) -> str:
    label = _text(value, "slot label", maximum=8)
    if _SLOT_RE.fullmatch(label) is None:
        raise InputValidationError("slot label is invalid")
    return label


def _slot_index(label: str) -> int:
    match = _SLOT_RE.fullmatch(label)
    if match is None:
        raise InputValidationError("slot label is invalid")
    return int(match.group(1))


def slot_label(index: int) -> str:
    return f"slot-{_integer(index, 'slot index', minimum=0, maximum=5)}"


def _normalize_server(value: object) -> bytes:
    server = _text(value, "server identifier", maximum=253).lower()
    try:
        encoded = server.encode("ascii")
    except UnicodeEncodeError as exc:
        raise InputValidationError("server identifier is invalid") from exc
    if _HOST_RE.fullmatch(server) is None:
        raise InputValidationError("server identifier is invalid")
    return encoded


def _normalize_exit(value: object) -> bytes:
    raw = _text(value, "exit identifier", maximum=64)
    try:
        return ipaddress.ip_address(raw).compressed.encode("ascii")
    except ValueError as exc:
        raise InputValidationError("exit identifier is invalid") from exc


@dataclass(frozen=True, slots=True)
class RunAuthority:
    key_version: str
    derivation_domain_id: str
    repository_id: int
    run_id: int
    run_attempt: int
    source_sha: str
    workflow_digest: str
    authority_commitment: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": "VpnRunAuthorityV1",
            "key_version": self.key_version,
            "derivation_domain_id": self.derivation_domain_id,
            "repository_id": self.repository_id,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "source_sha": self.source_sha,
            "workflow_digest": self.workflow_digest,
            "authority_commitment": self.authority_commitment,
        }

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "run authority")
        _exact_keys(
            payload,
            {
                "schema",
                "key_version",
                "derivation_domain_id",
                "repository_id",
                "run_id",
                "run_attempt",
                "source_sha",
                "workflow_digest",
                "authority_commitment",
            },
            "run authority",
        )
        if payload["schema"] != "VpnRunAuthorityV1":
            raise InputValidationError("run authority schema is invalid")
        key_version = _text(payload["key_version"], "key version", maximum=64)
        if key_version != RUN_KEY_VERSION:
            raise InputValidationError("key version is not the current audited version")
        domain = _text(payload["derivation_domain_id"], "derivation domain", maximum=96)
        if domain != RUN_KEY_DOMAIN_ID:
            raise InputValidationError("derivation domain is not the fixed audited domain")
        return cls(
            key_version=key_version,
            derivation_domain_id=domain,
            repository_id=_integer(
                payload["repository_id"], "repository ID", minimum=1, maximum=2**63 - 1
            ),
            run_id=_integer(payload["run_id"], "run ID", minimum=1, maximum=2**63 - 1),
            run_attempt=_integer(
                payload["run_attempt"], "run attempt", minimum=1, maximum=1_000_000
            ),
            source_sha=_hex(payload["source_sha"], "source SHA", _SHA_RE),
            workflow_digest=_hex(payload["workflow_digest"], "workflow digest", _SHA256_RE),
            authority_commitment=_hex(
                payload["authority_commitment"], "authority commitment", _SHA256_RE
            ),
        )


class RunKeyContext:
    """Ephemeral run key with a deliberately redacted public representation.

    The context owns the only long-lived mutable key buffer in this module. ``close``
    overwrites that buffer and makes every keyed operation fail. Python cannot promise
    allocator-level erasure of transient interpreter copies, so consumers must still
    destroy the ephemeral runner after its last comparison.
    """

    __slots__ = ("_authority", "_closed", "_run_key")

    def __init__(self, run_key: bytes, authority: RunAuthority) -> None:
        self._run_key = bytearray(run_key)
        self._authority = authority
        self._closed = False

    @property
    def authority(self) -> RunAuthority:
        return self._authority

    @property
    def closed(self) -> bool:
        return self._closed

    def __repr__(self) -> str:
        return (
            "RunKeyContext(authority_commitment="
            f"{self._authority.authority_commitment!r}, key=<redacted>, closed={self._closed})"
        )

    def __reduce_ex__(self, _protocol: SupportsIndex, /) -> str | tuple[object, ...]:
        raise TypeError("run-key contexts cannot be serialized")

    def __copy__(self) -> Self:
        raise TypeError("run-key contexts cannot be copied")

    def __deepcopy__(self, _memo: object) -> Self:
        raise TypeError("run-key contexts cannot be copied")

    def __enter__(self) -> Self:
        self._require_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            for index in range(len(self._run_key)):
                self._run_key[index] = 0
            self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise AuthorityMismatchError("run-key context is closed")

    def _mac(self, domain: bytes, payload: Mapping[str, object]) -> str:
        self._require_open()
        message = _frame(domain, _canonical_bytes(payload))
        return hmac.new(self._run_key, message, hashlib.sha256).hexdigest()

    def _commit(self, kind: CommitmentKind, normalized: bytes) -> OpaqueCommitment:
        self._require_open()
        domain = (
            SERVER_COMMITMENT_DOMAIN if kind is CommitmentKind.SERVER else EXIT_COMMITMENT_DOMAIN
        )
        digest = hmac.new(self._run_key, _frame(domain, normalized), hashlib.sha256).hexdigest()
        return OpaqueCommitment(kind=kind, digest=digest)

    def commit_server(self, value: object) -> OpaqueCommitment:
        return self._commit(CommitmentKind.SERVER, _normalize_server(value))

    def commit_exit(self, value: object) -> OpaqueCommitment:
        return self._commit(CommitmentKind.EXIT, _normalize_exit(value))


def derive_run_key(
    *,
    master_secret: bytes | bytearray | memoryview,
    repository_id: int,
    run_id: int,
    run_attempt: int,
    source_sha: str,
    workflow_digest: str,
    key_version: str = RUN_KEY_VERSION,
    derivation_domain_id: str = RUN_KEY_DOMAIN_ID,
) -> RunKeyContext:
    if not isinstance(master_secret, (bytes, bytearray, memoryview)):
        raise InputValidationError("master secret must be bytes")
    secret = bytes(master_secret)
    if len(secret) < MINIMUM_MASTER_SECRET_BYTES:
        raise InputValidationError("master secret is too short")
    if len(secret) > 4096:
        raise InputValidationError("master secret is too long")
    version = _text(key_version, "key version", maximum=64)
    if version != RUN_KEY_VERSION:
        raise InputValidationError("key version is not the current audited version")
    domain_id = _text(derivation_domain_id, "derivation domain", maximum=96)
    if domain_id != RUN_KEY_DOMAIN_ID:
        raise InputValidationError("derivation domain is not the fixed audited domain")
    repository = _integer(repository_id, "repository ID", minimum=1, maximum=2**63 - 1)
    run = _integer(run_id, "run ID", minimum=1, maximum=2**63 - 1)
    attempt = _integer(run_attempt, "run attempt", minimum=1, maximum=1_000_000)
    source = _hex(source_sha, "source SHA", _SHA_RE)
    workflow = _hex(workflow_digest, "workflow digest", _SHA256_RE)
    derivation_input = _frame(
        domain_id.encode("utf-8"),
        version.encode("ascii"),
        str(repository).encode("ascii"),
        str(run).encode("ascii"),
        str(attempt).encode("ascii"),
        source.encode("ascii"),
        workflow.encode("ascii"),
    )
    run_key = hmac.new(secret, derivation_input, hashlib.sha256).digest()
    authority_commitment = hmac.new(
        run_key,
        _frame(AUTHORITY_PROOF_DOMAIN, domain_id.encode("utf-8"), version.encode("ascii")),
        hashlib.sha256,
    ).hexdigest()
    authority = RunAuthority(
        key_version=version,
        derivation_domain_id=domain_id,
        repository_id=repository,
        run_id=run,
        run_attempt=attempt,
        source_sha=source,
        workflow_digest=workflow,
        authority_commitment=authority_commitment,
    )
    return RunKeyContext(run_key, authority)


@dataclass(frozen=True, slots=True)
class OpaqueCommitment:
    kind: CommitmentKind
    digest: str

    def to_payload(self) -> dict[str, str]:
        return {"kind": self.kind.value, "digest": self.digest}

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "opaque commitment")
        _exact_keys(payload, {"kind", "digest"}, "opaque commitment")
        try:
            kind = CommitmentKind(_text(payload["kind"], "commitment kind", maximum=16))
        except ValueError as exc:
            raise InputValidationError("commitment kind is invalid") from exc
        return cls(kind=kind, digest=_hex(payload["digest"], "commitment digest", _SHA256_RE))


@dataclass(frozen=True, slots=True)
class CanaryChecks:
    process: bool
    route: bool
    github: bool
    nba: bool

    @property
    def all_passed(self) -> bool:
        return self.process and self.route and self.github and self.nba

    def to_payload(self) -> dict[str, bool]:
        return {
            "process": self.process,
            "route": self.route,
            "github": self.github,
            "nba": self.nba,
        }

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "canary checks")
        _exact_keys(payload, {"process", "route", "github", "nba"}, "canary checks")
        return cls(
            process=_boolean(payload["process"], "process check"),
            route=_boolean(payload["route"], "route check"),
            github=_boolean(payload["github"], "GitHub check"),
            nba=_boolean(payload["nba"], "NBA check"),
        )


def _failure(value: object) -> FailureKind | None:
    if value is None:
        return None
    try:
        return FailureKind(_text(value, "failure kind", maximum=32))
    except ValueError as exc:
        raise InputValidationError("failure kind is invalid") from exc


def _optional_commitment(value: object, expected_kind: CommitmentKind) -> OpaqueCommitment | None:
    if value is None:
        return None
    commitment = OpaqueCommitment.from_payload(value)
    if commitment.kind is not expected_kind:
        raise InputValidationError("commitment kind is in the wrong typed field")
    return commitment


def _validate_outcome(
    *,
    server: OpaqueCommitment | None,
    exit_identity: OpaqueCommitment | None,
    checks: CanaryChecks,
    failure: FailureKind | None,
) -> None:
    if not isinstance(checks, CanaryChecks) or any(
        type(value) is not bool
        for value in (checks.process, checks.route, checks.github, checks.nba)
    ):
        raise InputValidationError("canary checks must contain exact booleans")
    if failure is not None and not isinstance(failure, FailureKind):
        raise InputValidationError("failure kind is invalid")
    if server is not None and server.kind is not CommitmentKind.SERVER:
        raise InputValidationError("server commitment has the wrong kind")
    if exit_identity is not None and exit_identity.kind is not CommitmentKind.EXIT:
        raise InputValidationError("exit commitment has the wrong kind")
    if failure is None:
        if server is None or exit_identity is None or not checks.all_passed:
            raise InputValidationError("successful evidence is incomplete")
        return
    if checks.all_passed:
        raise InputValidationError("failed evidence cannot pass every canary")
    required_failed_check = {
        FailureKind.PROCESS_FAILURE: checks.process,
        FailureKind.ROUTE_FAILURE: checks.route,
        FailureKind.GITHUB_FAILURE: checks.github,
        FailureKind.NBA_FAILURE: checks.nba,
    }.get(failure)
    if required_failed_check is True:
        raise InputValidationError("failure kind does not match failed canary")


@dataclass(frozen=True, slots=True)
class ProbeReceipt:
    authority: RunAuthority
    slot_label: str
    server_commitment: OpaqueCommitment | None
    exit_commitment: OpaqueCommitment | None
    checks: CanaryChecks
    failure: FailureKind | None
    receipt_mac: str

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema": "VpnProbeReceiptV1",
            "authority": self.authority.to_payload(),
            "slot_label": self.slot_label,
            "server_commitment": (
                None if self.server_commitment is None else self.server_commitment.to_payload()
            ),
            "exit_commitment": (
                None if self.exit_commitment is None else self.exit_commitment.to_payload()
            ),
            "checks": self.checks.to_payload(),
            "failure": None if self.failure is None else self.failure.value,
        }

    def to_payload(self) -> dict[str, object]:
        return {**self._unsigned_payload(), "receipt_mac": self.receipt_mac}

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "probe receipt")
        _exact_keys(
            payload,
            {
                "schema",
                "authority",
                "slot_label",
                "server_commitment",
                "exit_commitment",
                "checks",
                "failure",
                "receipt_mac",
            },
            "probe receipt",
        )
        if payload["schema"] != "VpnProbeReceiptV1":
            raise InputValidationError("probe receipt schema is invalid")
        receipt = cls(
            authority=RunAuthority.from_payload(payload["authority"]),
            slot_label=_slot_label(payload["slot_label"]),
            server_commitment=_optional_commitment(
                payload["server_commitment"], CommitmentKind.SERVER
            ),
            exit_commitment=_optional_commitment(payload["exit_commitment"], CommitmentKind.EXIT),
            checks=CanaryChecks.from_payload(payload["checks"]),
            failure=_failure(payload["failure"]),
            receipt_mac=_hex(payload["receipt_mac"], "probe receipt MAC", _SHA256_RE),
        )
        _validate_outcome(
            server=receipt.server_commitment,
            exit_identity=receipt.exit_commitment,
            checks=receipt.checks,
            failure=receipt.failure,
        )
        return receipt


def _assert_authority(context: RunKeyContext, authority: RunAuthority) -> None:
    if authority != context.authority:
        raise AuthorityMismatchError("receipt derivation authority does not match this run context")


def _verify_mac(
    context: RunKeyContext,
    *,
    domain: bytes,
    payload: Mapping[str, object],
    receipt_mac: str,
) -> None:
    validated_mac = _hex(receipt_mac, "receipt MAC", _SHA256_RE)
    expected = context._mac(domain, payload)
    if not hmac.compare_digest(expected, validated_mac):
        raise ReceiptIntegrityError("receipt authentication failed")


def build_probe_receipt(
    context: RunKeyContext,
    *,
    slot_index: int,
    server_identifier: str | None,
    exit_identifier: str | None,
    checks: CanaryChecks,
    failure: FailureKind | None = None,
) -> ProbeReceipt:
    label = slot_label(slot_index)
    server = None if server_identifier is None else context.commit_server(server_identifier)
    exit_identity = None if exit_identifier is None else context.commit_exit(exit_identifier)
    _validate_outcome(server=server, exit_identity=exit_identity, checks=checks, failure=failure)
    draft = ProbeReceipt(
        authority=context.authority,
        slot_label=label,
        server_commitment=server,
        exit_commitment=exit_identity,
        checks=checks,
        failure=failure,
        receipt_mac="0" * 64,
    )
    return ProbeReceipt(
        authority=draft.authority,
        slot_label=draft.slot_label,
        server_commitment=draft.server_commitment,
        exit_commitment=draft.exit_commitment,
        checks=draft.checks,
        failure=draft.failure,
        receipt_mac=context._mac(PROBE_RECEIPT_DOMAIN, draft._unsigned_payload()),
    )


def validate_probe_receipt(
    context: RunKeyContext, value: ProbeReceipt | Mapping[str, object]
) -> ProbeReceipt:
    receipt = value if isinstance(value, ProbeReceipt) else ProbeReceipt.from_payload(value)
    _assert_authority(context, receipt.authority)
    _slot_label(receipt.slot_label)
    _validate_outcome(
        server=receipt.server_commitment,
        exit_identity=receipt.exit_commitment,
        checks=receipt.checks,
        failure=receipt.failure,
    )
    _verify_mac(
        context,
        domain=PROBE_RECEIPT_DOMAIN,
        payload=receipt._unsigned_payload(),
        receipt_mac=receipt.receipt_mac,
    )
    return receipt


@dataclass(frozen=True, slots=True)
class SelectedSlot:
    slot_label: str
    server_commitment: OpaqueCommitment
    exit_commitment: OpaqueCommitment

    def to_payload(self) -> dict[str, object]:
        return {
            "slot_label": self.slot_label,
            "server_commitment": self.server_commitment.to_payload(),
            "exit_commitment": self.exit_commitment.to_payload(),
        }

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "selected slot")
        _exact_keys(
            payload,
            {"slot_label", "server_commitment", "exit_commitment"},
            "selected slot",
        )
        server = OpaqueCommitment.from_payload(payload["server_commitment"])
        exit_identity = OpaqueCommitment.from_payload(payload["exit_commitment"])
        if (
            server.kind is not CommitmentKind.SERVER
            or exit_identity.kind is not CommitmentKind.EXIT
        ):
            raise InputValidationError("selected slot commitment kinds are invalid")
        return cls(
            slot_label=_slot_label(payload["slot_label"]),
            server_commitment=server,
            exit_commitment=exit_identity,
        )


@dataclass(frozen=True, slots=True)
class CohortSelection:
    authority: RunAuthority
    generation: int
    previous_selection_digest: str | None
    inventory_digest: str
    selected: tuple[SelectedSlot, ...]
    excluded_failure_counts: tuple[tuple[str, int], ...]
    distinct_server_count: int
    distinct_exit_count: int
    selection_mac: str
    selection_digest: str

    @property
    def cohort_size(self) -> int:
        return len(self.selected)

    @property
    def selected_labels(self) -> tuple[str, ...]:
        return tuple(item.slot_label for item in self.selected)

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema": "VpnCohortSelectionV1",
            "authority": self.authority.to_payload(),
            "generation": self.generation,
            "previous_selection_digest": self.previous_selection_digest,
            "inventory_digest": self.inventory_digest,
            "selected": [item.to_payload() for item in self.selected],
            "cohort_size": self.cohort_size,
            "excluded_failure_counts": {key: count for key, count in self.excluded_failure_counts},
            "distinct_server_count": self.distinct_server_count,
            "distinct_exit_count": self.distinct_exit_count,
        }

    def to_payload(self) -> dict[str, object]:
        return {
            **self._unsigned_payload(),
            "selection_mac": self.selection_mac,
            "selection_digest": self.selection_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "cohort selection")
        _exact_keys(
            payload,
            {
                "schema",
                "authority",
                "generation",
                "previous_selection_digest",
                "inventory_digest",
                "selected",
                "cohort_size",
                "excluded_failure_counts",
                "distinct_server_count",
                "distinct_exit_count",
                "selection_mac",
                "selection_digest",
            },
            "cohort selection",
        )
        if payload["schema"] != "VpnCohortSelectionV1":
            raise InputValidationError("cohort selection schema is invalid")
        selected = tuple(
            SelectedSlot.from_payload(item)
            for item in _sequence(payload["selected"], "selected slots")
        )
        cohort_size = _integer(
            payload["cohort_size"],
            "cohort size",
            minimum=MINIMUM_COHORT_SIZE,
            maximum=MAXIMUM_COHORT_SIZE,
        )
        if cohort_size != len(selected):
            raise InputValidationError("cohort size does not match selected slots")
        failure_payload = _mapping(payload["excluded_failure_counts"], "failure counts")
        failure_counts: list[tuple[str, int]] = []
        for key, count in failure_payload.items():
            failure_counts.append(
                (
                    _text(key, "failure aggregate", maximum=64),
                    _integer(
                        count,
                        "failure aggregate count",
                        minimum=1,
                        maximum=PROBE_SLOT_COUNT,
                    ),
                )
            )
        previous_raw = payload["previous_selection_digest"]
        previous = (
            None
            if previous_raw is None
            else _hex(previous_raw, "previous selection digest", _SHA256_RE)
        )
        return cls(
            authority=RunAuthority.from_payload(payload["authority"]),
            generation=_integer(payload["generation"], "generation", minimum=0, maximum=1),
            previous_selection_digest=previous,
            inventory_digest=_hex(
                payload["inventory_digest"], "probe inventory digest", _SHA256_RE
            ),
            selected=selected,
            excluded_failure_counts=tuple(sorted(failure_counts)),
            distinct_server_count=_integer(
                payload["distinct_server_count"],
                "distinct server count",
                minimum=MINIMUM_COHORT_SIZE,
                maximum=MAXIMUM_COHORT_SIZE,
            ),
            distinct_exit_count=_integer(
                payload["distinct_exit_count"],
                "distinct exit count",
                minimum=MINIMUM_COHORT_SIZE,
                maximum=MAXIMUM_COHORT_SIZE,
            ),
            selection_mac=_hex(payload["selection_mac"], "selection MAC", _SHA256_RE),
            selection_digest=_hex(payload["selection_digest"], "selection digest", _SHA256_RE),
        )


def _validate_probe_inventory(
    context: RunKeyContext,
    values: Sequence[ProbeReceipt | Mapping[str, object]],
) -> tuple[ProbeReceipt, ...]:
    if isinstance(values, (str, bytes)) or len(values) != PROBE_SLOT_COUNT:
        raise ProbeInventoryError("probe inventory must contain exactly six receipts")
    receipts = tuple(validate_probe_receipt(context, value) for value in values)
    labels = [receipt.slot_label for receipt in receipts]
    if set(labels) != {slot_label(index) for index in range(PROBE_SLOT_COUNT)}:
        raise ProbeInventoryError("probe inventory must contain every slot exactly once")
    if len(labels) != len(set(labels)):
        raise ProbeInventoryError("probe inventory contains a duplicate slot")
    for attribute, kind in (
        ("server_commitment", "server"),
        ("exit_commitment", "exit"),
    ):
        digests = [
            commitment.digest
            for receipt in receipts
            if (commitment := getattr(receipt, attribute)) is not None
        ]
        if len(digests) != len(set(digests)):
            raise DuplicateCommitmentError(
                f"probe inventory contains a duplicate {kind} commitment"
            )
    return tuple(sorted(receipts, key=lambda receipt: _slot_index(receipt.slot_label)))


def _build_selection(
    context: RunKeyContext,
    receipts: tuple[ProbeReceipt, ...],
    *,
    excluded_labels: frozenset[str],
    generation: int,
    previous_selection_digest: str | None,
    additional_failure_counts: Mapping[str, int] | None = None,
) -> CohortSelection:
    selected: list[SelectedSlot] = []
    failures = Counter[str]()
    for receipt in receipts:
        if receipt.slot_label in excluded_labels:
            continue
        if receipt.failure is not None:
            failures[receipt.failure.value] += 1
            continue
        if not receipt.checks.all_passed:
            raise ProbeInventoryError("successful probe receipt contains a failed canary")
        if receipt.server_commitment is None or receipt.exit_commitment is None:
            raise ProbeInventoryError("successful probe receipt is missing a commitment")
        selected.append(
            SelectedSlot(
                slot_label=receipt.slot_label,
                server_commitment=receipt.server_commitment,
                exit_commitment=receipt.exit_commitment,
            )
        )
    if additional_failure_counts is not None:
        for key, count in additional_failure_counts.items():
            failures[_text(key, "failure aggregate", maximum=64)] += _integer(
                count, "failure aggregate count", minimum=0, maximum=PROBE_SLOT_COUNT
            )
    if len(selected) < MINIMUM_COHORT_SIZE:
        raise InsufficientCapacityError("fewer than four independently valid VPN slots remain")
    if len(selected) > MAXIMUM_COHORT_SIZE:
        selected = selected[:MAXIMUM_COHORT_SIZE]
    inventory_digest = _digest_payload(
        {"probe_receipts": [receipt.to_payload() for receipt in receipts]}
    )
    servers = {item.server_commitment.digest for item in selected}
    exits = {item.exit_commitment.digest for item in selected}
    draft = CohortSelection(
        authority=context.authority,
        generation=generation,
        previous_selection_digest=previous_selection_digest,
        inventory_digest=inventory_digest,
        selected=tuple(selected),
        excluded_failure_counts=tuple(sorted(failures.items())),
        distinct_server_count=len(servers),
        distinct_exit_count=len(exits),
        selection_mac="0" * 64,
        selection_digest="0" * 64,
    )
    selection_mac = context._mac(SELECTION_RECEIPT_DOMAIN, draft._unsigned_payload())
    selection_digest = _digest_payload(
        {**draft._unsigned_payload(), "selection_mac": selection_mac}
    )
    return CohortSelection(
        authority=draft.authority,
        generation=draft.generation,
        previous_selection_digest=draft.previous_selection_digest,
        inventory_digest=draft.inventory_digest,
        selected=draft.selected,
        excluded_failure_counts=draft.excluded_failure_counts,
        distinct_server_count=draft.distinct_server_count,
        distinct_exit_count=draft.distinct_exit_count,
        selection_mac=selection_mac,
        selection_digest=selection_digest,
    )


def select_cohort(
    context: RunKeyContext,
    receipts: Sequence[ProbeReceipt | Mapping[str, object]],
) -> CohortSelection:
    """Select all valid slots from one exact six-slot inventory, blocking below four."""

    validated = _validate_probe_inventory(context, receipts)
    return _build_selection(
        context,
        validated,
        excluded_labels=frozenset(),
        generation=0,
        previous_selection_digest=None,
    )


def validate_selection(
    context: RunKeyContext, selection: CohortSelection | Mapping[str, object]
) -> CohortSelection:
    selection = (
        selection
        if isinstance(selection, CohortSelection)
        else CohortSelection.from_payload(selection)
    )
    _assert_authority(context, selection.authority)
    if selection.generation not in {0, 1}:
        raise ReceiptIntegrityError("selection generation is invalid")
    if selection.generation == 0 and selection.previous_selection_digest is not None:
        raise ReceiptIntegrityError("initial selection cannot name a predecessor")
    if selection.generation == 1:
        _hex(selection.previous_selection_digest, "previous selection digest", _SHA256_RE)
    if not MINIMUM_COHORT_SIZE <= selection.cohort_size <= MAXIMUM_COHORT_SIZE:
        raise ReceiptIntegrityError("selection cohort size is outside 4-6")
    labels = selection.selected_labels
    if labels != tuple(sorted(labels, key=_slot_index)) or len(labels) != len(set(labels)):
        raise ReceiptIntegrityError("selection slots are not exact and ordered")
    for item in selection.selected:
        SelectedSlot.from_payload(item.to_payload())
    server_digests = [item.server_commitment.digest for item in selection.selected]
    exit_digests = [item.exit_commitment.digest for item in selection.selected]
    if len(server_digests) != len(set(server_digests)):
        raise DuplicateCommitmentError("selection contains a duplicate server commitment")
    if len(exit_digests) != len(set(exit_digests)):
        raise DuplicateCommitmentError("selection contains a duplicate exit commitment")
    if selection.distinct_server_count != selection.cohort_size:
        raise ReceiptIntegrityError("selection server distinctness is inconsistent")
    if selection.distinct_exit_count != selection.cohort_size:
        raise ReceiptIntegrityError("selection exit distinctness is inconsistent")
    if selection.excluded_failure_counts != tuple(sorted(selection.excluded_failure_counts)):
        raise ReceiptIntegrityError("selection failure aggregates are not canonical")
    failure_names = [name for name, _count in selection.excluded_failure_counts]
    if len(failure_names) != len(set(failure_names)):
        raise ReceiptIntegrityError("selection failure aggregates are duplicated")
    for name, count in selection.excluded_failure_counts:
        _text(name, "failure aggregate", maximum=64)
        _integer(count, "failure aggregate count", minimum=1, maximum=PROBE_SLOT_COUNT)
    if sum(count for _name, count in selection.excluded_failure_counts) != (
        PROBE_SLOT_COUNT - selection.cohort_size
    ):
        raise ReceiptIntegrityError("selection failure aggregates do not conserve six slots")
    _hex(selection.inventory_digest, "probe inventory digest", _SHA256_RE)
    _hex(selection.selection_digest, "selection digest", _SHA256_RE)
    _verify_mac(
        context,
        domain=SELECTION_RECEIPT_DOMAIN,
        payload=selection._unsigned_payload(),
        receipt_mac=selection.selection_mac,
    )
    expected_digest = _digest_payload(
        {**selection._unsigned_payload(), "selection_mac": selection.selection_mac}
    )
    if not hmac.compare_digest(expected_digest, selection.selection_digest):
        raise ReceiptIntegrityError("selection digest is invalid")
    return selection


@dataclass(frozen=True, slots=True)
class BarrierChallenge:
    authority: RunAuthority
    selection_digest: str
    challenge_id: str
    challenge_mac: str

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema": "VpnReconnectBarrierChallengeV1",
            "authority": self.authority.to_payload(),
            "selection_digest": self.selection_digest,
            "challenge_id": self.challenge_id,
        }

    def to_payload(self) -> dict[str, object]:
        return {**self._unsigned_payload(), "challenge_mac": self.challenge_mac}

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "barrier challenge")
        _exact_keys(
            payload,
            {
                "schema",
                "authority",
                "selection_digest",
                "challenge_id",
                "challenge_mac",
            },
            "barrier challenge",
        )
        if payload["schema"] != "VpnReconnectBarrierChallengeV1":
            raise InputValidationError("barrier challenge schema is invalid")
        return cls(
            authority=RunAuthority.from_payload(payload["authority"]),
            selection_digest=_hex(payload["selection_digest"], "selection digest", _SHA256_RE),
            challenge_id=_hex(payload["challenge_id"], "challenge ID", _SHA256_RE),
            challenge_mac=_hex(payload["challenge_mac"], "challenge MAC", _SHA256_RE),
        )


def create_barrier_challenge(
    context: RunKeyContext,
    selection: CohortSelection,
    *,
    nonce: bytes | bytearray | memoryview,
) -> BarrierChallenge:
    validate_selection(context, selection)
    if not isinstance(nonce, (bytes, bytearray, memoryview)):
        raise InputValidationError("barrier nonce must be bytes")
    nonce_bytes = bytes(nonce)
    if not MINIMUM_BARRIER_NONCE_BYTES <= len(nonce_bytes) <= 256:
        raise InputValidationError("barrier nonce length is invalid")
    context._require_open()
    challenge_id = hmac.new(
        context._run_key,
        _frame(
            BARRIER_CHALLENGE_DOMAIN,
            selection.selection_digest.encode("ascii"),
            nonce_bytes,
        ),
        hashlib.sha256,
    ).hexdigest()
    draft = BarrierChallenge(
        authority=context.authority,
        selection_digest=selection.selection_digest,
        challenge_id=challenge_id,
        challenge_mac="0" * 64,
    )
    return BarrierChallenge(
        authority=draft.authority,
        selection_digest=draft.selection_digest,
        challenge_id=draft.challenge_id,
        challenge_mac=context._mac(BARRIER_CHALLENGE_DOMAIN, draft._unsigned_payload()),
    )


def validate_barrier_challenge(
    context: RunKeyContext,
    selection: CohortSelection,
    challenge: BarrierChallenge | Mapping[str, object],
) -> BarrierChallenge:
    selection = validate_selection(context, selection)
    challenge = (
        challenge
        if isinstance(challenge, BarrierChallenge)
        else BarrierChallenge.from_payload(challenge)
    )
    _assert_authority(context, challenge.authority)
    if challenge.selection_digest != selection.selection_digest:
        raise BarrierAdmissionError("barrier challenge belongs to another cohort selection")
    _hex(challenge.challenge_id, "barrier challenge ID", _SHA256_RE)
    _verify_mac(
        context,
        domain=BARRIER_CHALLENGE_DOMAIN,
        payload=challenge._unsigned_payload(),
        receipt_mac=challenge.challenge_mac,
    )
    return challenge


@dataclass(frozen=True, slots=True)
class ReconnectReceipt:
    authority: RunAuthority
    selection_digest: str
    challenge_id: str
    slot_label: str
    server_commitment: OpaqueCommitment | None
    exit_commitment: OpaqueCommitment | None
    checks: CanaryChecks
    failure: FailureKind | None
    receipt_mac: str

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema": "VpnReconnectReceiptV1",
            "authority": self.authority.to_payload(),
            "selection_digest": self.selection_digest,
            "challenge_id": self.challenge_id,
            "slot_label": self.slot_label,
            "server_commitment": (
                None if self.server_commitment is None else self.server_commitment.to_payload()
            ),
            "exit_commitment": (
                None if self.exit_commitment is None else self.exit_commitment.to_payload()
            ),
            "checks": self.checks.to_payload(),
            "failure": None if self.failure is None else self.failure.value,
        }

    def to_payload(self) -> dict[str, object]:
        return {**self._unsigned_payload(), "receipt_mac": self.receipt_mac}

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "reconnect receipt")
        _exact_keys(
            payload,
            {
                "schema",
                "authority",
                "selection_digest",
                "challenge_id",
                "slot_label",
                "server_commitment",
                "exit_commitment",
                "checks",
                "failure",
                "receipt_mac",
            },
            "reconnect receipt",
        )
        if payload["schema"] != "VpnReconnectReceiptV1":
            raise InputValidationError("reconnect receipt schema is invalid")
        receipt = cls(
            authority=RunAuthority.from_payload(payload["authority"]),
            selection_digest=_hex(payload["selection_digest"], "selection digest", _SHA256_RE),
            challenge_id=_hex(payload["challenge_id"], "challenge ID", _SHA256_RE),
            slot_label=_slot_label(payload["slot_label"]),
            server_commitment=_optional_commitment(
                payload["server_commitment"], CommitmentKind.SERVER
            ),
            exit_commitment=_optional_commitment(payload["exit_commitment"], CommitmentKind.EXIT),
            checks=CanaryChecks.from_payload(payload["checks"]),
            failure=_failure(payload["failure"]),
            receipt_mac=_hex(payload["receipt_mac"], "reconnect receipt MAC", _SHA256_RE),
        )
        _validate_outcome(
            server=receipt.server_commitment,
            exit_identity=receipt.exit_commitment,
            checks=receipt.checks,
            failure=receipt.failure,
        )
        return receipt


def build_reconnect_receipt(
    context: RunKeyContext,
    selection: CohortSelection,
    challenge: BarrierChallenge,
    *,
    slot: str,
    server_identifier: str | None,
    exit_identifier: str | None,
    checks: CanaryChecks,
    failure: FailureKind | None = None,
) -> ReconnectReceipt:
    validate_barrier_challenge(context, selection, challenge)
    label = _slot_label(slot)
    if label not in selection.selected_labels:
        raise BarrierAdmissionError("reconnect slot was not selected")
    server = None if server_identifier is None else context.commit_server(server_identifier)
    exit_identity = None if exit_identifier is None else context.commit_exit(exit_identifier)
    _validate_outcome(server=server, exit_identity=exit_identity, checks=checks, failure=failure)
    draft = ReconnectReceipt(
        authority=context.authority,
        selection_digest=selection.selection_digest,
        challenge_id=challenge.challenge_id,
        slot_label=label,
        server_commitment=server,
        exit_commitment=exit_identity,
        checks=checks,
        failure=failure,
        receipt_mac="0" * 64,
    )
    return ReconnectReceipt(
        authority=draft.authority,
        selection_digest=draft.selection_digest,
        challenge_id=draft.challenge_id,
        slot_label=draft.slot_label,
        server_commitment=draft.server_commitment,
        exit_commitment=draft.exit_commitment,
        checks=draft.checks,
        failure=draft.failure,
        receipt_mac=context._mac(RECONNECT_RECEIPT_DOMAIN, draft._unsigned_payload()),
    )


def validate_reconnect_receipt(
    context: RunKeyContext,
    selection: CohortSelection,
    challenge: BarrierChallenge,
    receipt: ReconnectReceipt | Mapping[str, object],
) -> ReconnectReceipt:
    selection = validate_selection(context, selection)
    challenge = validate_barrier_challenge(context, selection, challenge)
    receipt = (
        receipt if isinstance(receipt, ReconnectReceipt) else ReconnectReceipt.from_payload(receipt)
    )
    _assert_authority(context, receipt.authority)
    if receipt.selection_digest != selection.selection_digest:
        raise BarrierAdmissionError("reconnect receipt belongs to another cohort selection")
    if receipt.challenge_id != challenge.challenge_id:
        raise BarrierAdmissionError("reconnect receipt belongs to another barrier challenge")
    if receipt.slot_label not in selection.selected_labels:
        raise BarrierAdmissionError("reconnect receipt names an unselected slot")
    _validate_outcome(
        server=receipt.server_commitment,
        exit_identity=receipt.exit_commitment,
        checks=receipt.checks,
        failure=receipt.failure,
    )
    _verify_mac(
        context,
        domain=RECONNECT_RECEIPT_DOMAIN,
        payload=receipt._unsigned_payload(),
        receipt_mac=receipt.receipt_mac,
    )
    return receipt


def _validate_reconnect_set(
    context: RunKeyContext,
    selection: CohortSelection,
    challenge: BarrierChallenge,
    receipts: Sequence[ReconnectReceipt],
    *,
    permit_typed_loss: bool,
) -> tuple[ReconnectReceipt, ...]:
    if isinstance(receipts, (str, bytes)) or len(receipts) != selection.cohort_size:
        raise BarrierAdmissionError("reconnect barrier requires one receipt per selected slot")
    validated = tuple(
        validate_reconnect_receipt(context, selection, challenge, receipt) for receipt in receipts
    )
    labels = [receipt.slot_label for receipt in validated]
    if len(labels) != len(set(labels)):
        raise BarrierAdmissionError("reconnect barrier contains a replayed slot")
    if set(labels) != set(selection.selected_labels):
        raise BarrierAdmissionError("reconnect barrier is missing or adds a selected slot")
    expected_by_slot = {item.slot_label: item for item in selection.selected}
    for receipt in validated:
        expected = expected_by_slot[receipt.slot_label]
        if (
            receipt.server_commitment is not None
            and receipt.server_commitment != expected.server_commitment
        ):
            raise BarrierAdmissionError("reconnect server commitment changed")
        if (
            receipt.exit_commitment is not None
            and receipt.exit_commitment != expected.exit_commitment
        ):
            raise BarrierAdmissionError("reconnect exit commitment changed")
        if receipt.failure is None:
            if (
                receipt.server_commitment != expected.server_commitment
                or receipt.exit_commitment != expected.exit_commitment
                or not receipt.checks.all_passed
            ):
                raise BarrierAdmissionError("reconnect evidence is incomplete")
        else:
            if receipt.server_commitment != expected.server_commitment:
                raise BarrierAdmissionError(
                    "failed reconnect does not bind the selected server commitment"
                )
            if not permit_typed_loss or receipt.failure not in RESELECTABLE_FAILURES:
                raise BarrierAdmissionError("reconnect failure blocks admission")
    return tuple(sorted(validated, key=lambda receipt: _slot_index(receipt.slot_label)))


@dataclass(frozen=True, slots=True)
class ReselectionReceipt:
    authority: RunAuthority
    previous_selection_digest: str
    failed_challenge_id: str
    failed_slots: tuple[str, ...]
    failure_counts: tuple[tuple[str, int], ...]
    new_selection_digest: str
    attempt: int
    receipt_mac: str
    receipt_digest: str

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema": "VpnCohortReselectionV1",
            "authority": self.authority.to_payload(),
            "previous_selection_digest": self.previous_selection_digest,
            "failed_challenge_id": self.failed_challenge_id,
            "failed_slots": list(self.failed_slots),
            "failure_counts": {key: count for key, count in self.failure_counts},
            "new_selection_digest": self.new_selection_digest,
            "attempt": self.attempt,
            "reason": "typed_auth_or_capacity_loss",
        }

    def to_payload(self) -> dict[str, object]:
        return {
            **self._unsigned_payload(),
            "receipt_mac": self.receipt_mac,
            "receipt_digest": self.receipt_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "reselection receipt")
        _exact_keys(
            payload,
            {
                "schema",
                "authority",
                "previous_selection_digest",
                "failed_challenge_id",
                "failed_slots",
                "failure_counts",
                "new_selection_digest",
                "attempt",
                "reason",
                "receipt_mac",
                "receipt_digest",
            },
            "reselection receipt",
        )
        if payload["schema"] != "VpnCohortReselectionV1":
            raise InputValidationError("reselection receipt schema is invalid")
        if payload["reason"] != "typed_auth_or_capacity_loss":
            raise InputValidationError("reselection reason is invalid")
        failure_payload = _mapping(payload["failure_counts"], "reselection failure counts")
        failure_counts = tuple(
            sorted(
                (
                    _text(key, "failure kind", maximum=32),
                    _integer(
                        count,
                        "failure count",
                        minimum=1,
                        maximum=PROBE_SLOT_COUNT,
                    ),
                )
                for key, count in failure_payload.items()
            )
        )
        return cls(
            authority=RunAuthority.from_payload(payload["authority"]),
            previous_selection_digest=_hex(
                payload["previous_selection_digest"],
                "previous selection digest",
                _SHA256_RE,
            ),
            failed_challenge_id=_hex(
                payload["failed_challenge_id"], "failed challenge ID", _SHA256_RE
            ),
            failed_slots=tuple(
                _slot_label(item) for item in _sequence(payload["failed_slots"], "failed slots")
            ),
            failure_counts=failure_counts,
            new_selection_digest=_hex(
                payload["new_selection_digest"], "new selection digest", _SHA256_RE
            ),
            attempt=_integer(payload["attempt"], "reselection attempt", minimum=1, maximum=1),
            receipt_mac=_hex(payload["receipt_mac"], "reselection MAC", _SHA256_RE),
            receipt_digest=_hex(payload["receipt_digest"], "reselection digest", _SHA256_RE),
        )


@dataclass(frozen=True, slots=True)
class ReselectionDecision:
    selection: CohortSelection
    receipt: ReselectionReceipt


def validate_reselection_receipt(
    context: RunKeyContext,
    previous_selection: CohortSelection,
    new_selection: CohortSelection,
    receipt: ReselectionReceipt | Mapping[str, object],
) -> ReselectionReceipt:
    previous_selection = validate_selection(context, previous_selection)
    new_selection = validate_selection(context, new_selection)
    receipt = (
        receipt
        if isinstance(receipt, ReselectionReceipt)
        else ReselectionReceipt.from_payload(receipt)
    )
    _assert_authority(context, receipt.authority)
    if receipt.attempt != 1:
        raise ReselectionNotPermittedError("only reselection attempt one is valid")
    if previous_selection.generation != 0 or new_selection.generation != 1:
        raise ReselectionNotPermittedError("reselection generations are invalid")
    if receipt.previous_selection_digest != previous_selection.selection_digest:
        raise ReselectionNotPermittedError("reselection predecessor is invalid")
    if new_selection.previous_selection_digest != previous_selection.selection_digest:
        raise ReselectionNotPermittedError("new selection predecessor is invalid")
    if receipt.new_selection_digest != new_selection.selection_digest:
        raise ReselectionNotPermittedError("reselection successor is invalid")
    if not receipt.failed_slots or tuple(sorted(receipt.failed_slots, key=_slot_index)) != (
        receipt.failed_slots
    ):
        raise ReselectionNotPermittedError("reselection failed slots are invalid")
    if len(receipt.failed_slots) != len(set(receipt.failed_slots)):
        raise ReselectionNotPermittedError("reselection failed slots are duplicated")
    if set(receipt.failed_slots) & set(new_selection.selected_labels):
        raise ReselectionNotPermittedError("failed slot survived reselection")
    if set(receipt.failed_slots) - set(previous_selection.selected_labels):
        raise ReselectionNotPermittedError("reselection failed slot was not previously selected")
    if set(new_selection.selected_labels) != (
        set(previous_selection.selected_labels) - set(receipt.failed_slots)
    ):
        raise ReselectionNotPermittedError("reselection changed an unfailed slot")
    if receipt.failure_counts != tuple(sorted(receipt.failure_counts)):
        raise ReselectionNotPermittedError("reselection failure counts are not canonical")
    if len({name for name, _count in receipt.failure_counts}) != len(receipt.failure_counts):
        raise ReselectionNotPermittedError("reselection failure counts are duplicated")
    allowed_failure_names = {failure.value for failure in RESELECTABLE_FAILURES}
    if any(name not in allowed_failure_names for name, _count in receipt.failure_counts):
        raise ReselectionNotPermittedError("reselection failure type is not permitted")
    if sum(count for _name, count in receipt.failure_counts) != len(receipt.failed_slots):
        raise ReselectionNotPermittedError("reselection failure counts are inconsistent")
    _hex(receipt.failed_challenge_id, "failed challenge ID", _SHA256_RE)
    _verify_mac(
        context,
        domain=RESELECTION_RECEIPT_DOMAIN,
        payload=receipt._unsigned_payload(),
        receipt_mac=receipt.receipt_mac,
    )
    expected_digest = _digest_payload(
        {**receipt._unsigned_payload(), "receipt_mac": receipt.receipt_mac}
    )
    if not hmac.compare_digest(expected_digest, receipt.receipt_digest):
        raise ReceiptIntegrityError("reselection receipt digest is invalid")
    return receipt


def reselect_after_typed_loss(
    context: RunKeyContext,
    probes: Sequence[ProbeReceipt | Mapping[str, object]],
    selection: CohortSelection,
    challenge: BarrierChallenge,
    reconnect_receipts: Sequence[ReconnectReceipt],
    *,
    prior_reselection: ReselectionReceipt | None = None,
) -> ReselectionDecision:
    validate_selection(context, selection)
    if selection.generation != 0 or prior_reselection is not None:
        raise ReselectionNotPermittedError("the one permitted reselection is already consumed")
    validated_reconnects = _validate_reconnect_set(
        context,
        selection,
        challenge,
        reconnect_receipts,
        permit_typed_loss=True,
    )
    failures = tuple(receipt for receipt in validated_reconnects if receipt.failure is not None)
    if not failures or any(receipt.failure not in RESELECTABLE_FAILURES for receipt in failures):
        raise ReselectionNotPermittedError("reselection requires typed auth or capacity loss")
    failed_labels = tuple(receipt.slot_label for receipt in failures)
    validated_probes = _validate_probe_inventory(context, probes)
    failure_counts = Counter(receipt.failure.value for receipt in failures if receipt.failure)
    new_selection = _build_selection(
        context,
        validated_probes,
        excluded_labels=frozenset(failed_labels),
        generation=1,
        previous_selection_digest=selection.selection_digest,
        additional_failure_counts={
            f"reconnect_{key}": count for key, count in failure_counts.items()
        },
    )
    draft = ReselectionReceipt(
        authority=context.authority,
        previous_selection_digest=selection.selection_digest,
        failed_challenge_id=challenge.challenge_id,
        failed_slots=failed_labels,
        failure_counts=tuple(sorted(failure_counts.items())),
        new_selection_digest=new_selection.selection_digest,
        attempt=1,
        receipt_mac="0" * 64,
        receipt_digest="0" * 64,
    )
    receipt_mac = context._mac(RESELECTION_RECEIPT_DOMAIN, draft._unsigned_payload())
    receipt_digest = _digest_payload({**draft._unsigned_payload(), "receipt_mac": receipt_mac})
    receipt = ReselectionReceipt(
        authority=draft.authority,
        previous_selection_digest=draft.previous_selection_digest,
        failed_challenge_id=draft.failed_challenge_id,
        failed_slots=draft.failed_slots,
        failure_counts=draft.failure_counts,
        new_selection_digest=draft.new_selection_digest,
        attempt=draft.attempt,
        receipt_mac=receipt_mac,
        receipt_digest=receipt_digest,
    )
    validate_reselection_receipt(context, selection, new_selection, receipt)
    return ReselectionDecision(selection=new_selection, receipt=receipt)


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    authority: RunAuthority
    selection_digest: str
    challenge_id: str
    admitted: tuple[SelectedSlot, ...]
    reconnect_inventory_digest: str
    reselection_count: int
    reselection_receipt_digest: str | None
    admission_mac: str
    admission_digest: str

    @property
    def cohort_size(self) -> int:
        return len(self.admitted)

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schema": "VpnCohortAdmissionV1",
            "authority": self.authority.to_payload(),
            "selection_digest": self.selection_digest,
            "challenge_id": self.challenge_id,
            "admitted": [item.to_payload() for item in self.admitted],
            "cohort_size": self.cohort_size,
            "reconnect_inventory_digest": self.reconnect_inventory_digest,
            "reselection_count": self.reselection_count,
            "reselection_receipt_digest": self.reselection_receipt_digest,
        }

    def to_payload(self) -> dict[str, object]:
        return {
            **self._unsigned_payload(),
            "admission_mac": self.admission_mac,
            "admission_digest": self.admission_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> Self:
        payload = _mapping(value, "admission receipt")
        _exact_keys(
            payload,
            {
                "schema",
                "authority",
                "selection_digest",
                "challenge_id",
                "admitted",
                "cohort_size",
                "reconnect_inventory_digest",
                "reselection_count",
                "reselection_receipt_digest",
                "admission_mac",
                "admission_digest",
            },
            "admission receipt",
        )
        if payload["schema"] != "VpnCohortAdmissionV1":
            raise InputValidationError("admission receipt schema is invalid")
        admitted = tuple(
            SelectedSlot.from_payload(item)
            for item in _sequence(payload["admitted"], "admitted slots")
        )
        cohort_size = _integer(
            payload["cohort_size"],
            "cohort size",
            minimum=MINIMUM_COHORT_SIZE,
            maximum=MAXIMUM_COHORT_SIZE,
        )
        if cohort_size != len(admitted):
            raise InputValidationError("admission cohort size is inconsistent")
        reselection_raw = payload["reselection_receipt_digest"]
        reselection_digest = (
            None
            if reselection_raw is None
            else _hex(reselection_raw, "reselection receipt digest", _SHA256_RE)
        )
        return cls(
            authority=RunAuthority.from_payload(payload["authority"]),
            selection_digest=_hex(payload["selection_digest"], "selection digest", _SHA256_RE),
            challenge_id=_hex(payload["challenge_id"], "challenge ID", _SHA256_RE),
            admitted=admitted,
            reconnect_inventory_digest=_hex(
                payload["reconnect_inventory_digest"],
                "reconnect inventory digest",
                _SHA256_RE,
            ),
            reselection_count=_integer(
                payload["reselection_count"], "reselection count", minimum=0, maximum=1
            ),
            reselection_receipt_digest=reselection_digest,
            admission_mac=_hex(payload["admission_mac"], "admission MAC", _SHA256_RE),
            admission_digest=_hex(payload["admission_digest"], "admission digest", _SHA256_RE),
        )


def admit_reconnected_cohort(
    context: RunKeyContext,
    selection: CohortSelection,
    challenge: BarrierChallenge,
    reconnect_receipts: Sequence[ReconnectReceipt],
    *,
    previous_selection: CohortSelection | None = None,
    reselection_receipt: ReselectionReceipt | None = None,
) -> AdmissionReceipt:
    validate_selection(context, selection)
    validate_barrier_challenge(context, selection, challenge)
    if selection.generation == 0:
        if previous_selection is not None or reselection_receipt is not None:
            raise BarrierAdmissionError("initial admission cannot claim reselection")
        reselection_count = 0
        reselection_digest = None
    else:
        if previous_selection is None or reselection_receipt is None:
            raise BarrierAdmissionError("reselected admission requires its exact receipt")
        validate_reselection_receipt(context, previous_selection, selection, reselection_receipt)
        reselection_count = 1
        reselection_digest = reselection_receipt.receipt_digest
    validated = _validate_reconnect_set(
        context,
        selection,
        challenge,
        reconnect_receipts,
        permit_typed_loss=False,
    )
    reconnect_inventory_digest = _digest_payload(
        {"reconnect_receipts": [receipt.to_payload() for receipt in validated]}
    )
    draft = AdmissionReceipt(
        authority=context.authority,
        selection_digest=selection.selection_digest,
        challenge_id=challenge.challenge_id,
        admitted=selection.selected,
        reconnect_inventory_digest=reconnect_inventory_digest,
        reselection_count=reselection_count,
        reselection_receipt_digest=reselection_digest,
        admission_mac="0" * 64,
        admission_digest="0" * 64,
    )
    admission_mac = context._mac(ADMISSION_RECEIPT_DOMAIN, draft._unsigned_payload())
    admission_digest = _digest_payload(
        {**draft._unsigned_payload(), "admission_mac": admission_mac}
    )
    admission = AdmissionReceipt(
        authority=draft.authority,
        selection_digest=draft.selection_digest,
        challenge_id=draft.challenge_id,
        admitted=draft.admitted,
        reconnect_inventory_digest=draft.reconnect_inventory_digest,
        reselection_count=draft.reselection_count,
        reselection_receipt_digest=draft.reselection_receipt_digest,
        admission_mac=admission_mac,
        admission_digest=admission_digest,
    )
    return validate_admission_receipt(
        context,
        selection,
        challenge,
        admission,
        previous_selection=previous_selection,
        reselection_receipt=reselection_receipt,
    )


def validate_admission_receipt(
    context: RunKeyContext,
    selection: CohortSelection,
    challenge: BarrierChallenge,
    receipt: AdmissionReceipt | Mapping[str, object],
    *,
    previous_selection: CohortSelection | None = None,
    reselection_receipt: ReselectionReceipt | None = None,
) -> AdmissionReceipt:
    selection = validate_selection(context, selection)
    challenge = validate_barrier_challenge(context, selection, challenge)
    receipt = (
        receipt if isinstance(receipt, AdmissionReceipt) else AdmissionReceipt.from_payload(receipt)
    )
    _assert_authority(context, receipt.authority)
    if receipt.selection_digest != selection.selection_digest:
        raise BarrierAdmissionError("admission receipt belongs to another selection")
    if receipt.challenge_id != challenge.challenge_id:
        raise BarrierAdmissionError("admission receipt belongs to another barrier")
    if receipt.admitted != selection.selected or receipt.cohort_size != selection.cohort_size:
        raise BarrierAdmissionError("admission receipt changed the selected commitment set")
    _hex(receipt.reconnect_inventory_digest, "reconnect inventory digest", _SHA256_RE)
    if selection.generation == 0:
        if (
            previous_selection is not None
            or reselection_receipt is not None
            or receipt.reselection_count != 0
            or receipt.reselection_receipt_digest is not None
        ):
            raise BarrierAdmissionError("initial admission has invalid reselection authority")
    else:
        if previous_selection is None or reselection_receipt is None:
            raise BarrierAdmissionError("reselected admission is missing its authority")
        validated_reselection = validate_reselection_receipt(
            context, previous_selection, selection, reselection_receipt
        )
        if receipt.reselection_count != 1 or (
            receipt.reselection_receipt_digest != validated_reselection.receipt_digest
        ):
            raise BarrierAdmissionError("admission reselection authority is inconsistent")
    _verify_mac(
        context,
        domain=ADMISSION_RECEIPT_DOMAIN,
        payload=receipt._unsigned_payload(),
        receipt_mac=receipt.admission_mac,
    )
    expected_digest = _digest_payload(
        {**receipt._unsigned_payload(), "admission_mac": receipt.admission_mac}
    )
    if not hmac.compare_digest(expected_digest, receipt.admission_digest):
        raise ReceiptIntegrityError("admission digest is invalid")
    return receipt
