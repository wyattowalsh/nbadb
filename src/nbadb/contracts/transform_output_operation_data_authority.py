"""Acyclic PRECOMMIT evidence codecs for transform-output operations.

The durable DTOs in this module carry fixed context, singleton evidence, and
native count/root projections only.  Extraction-history-sized inventories are
streamed by verifier-owned F.6/F.9 code through the shared ordered prefix fold;
they are never embedded here.  These codecs never touch a database engine, admit an
operation, or seal postcommit authority.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal, Never, Self, cast

from nbadb.contracts.ordered_sha256_prefix_fold import (
    OrderedSha256PrefixFoldV1,
    empty_ordered_sha256_prefix_fold,
    extend_ordered_sha256_prefix_fold,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    CANONICAL_JSON_MAX_BYTES,
    DispositionEvidenceError,
    canonical_json_bytes_v1,
    decode_canonical_json_bytes_v1,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CumulativeConditionalStagingEvidenceInventoryV1",
    "CumulativeConditionalStagingEvidenceMemberV1",
    "DurableRawTerminalManifestLocatorV1",
    "FullExtractionBlockedRawMemberV1",
    "FullExtractionExecutableRawMemberV1",
    "FullExtractionRawOperationDenominatorV1",
    "OperationDataAuthorityError",
    "OperationDataEvidenceV1",
    "RawAuxiliaryTerminalMemberV1",
    "SuccessorRawOperationDenominatorV1",
    "VerifiedOperationRawSnapshotV1",
    "W2DatabaseAuthorityReceiptV1",
    "W2SourceMemberAttributionV1",
]

type ConditionalKind = Literal[
    "live_complete_node_tree",
    "stats_additive_result_cells",
]
type RawAuxiliaryRole = Literal["discovery_seed", "live_snapshot"]
type RawOperationKind = Literal["full_extraction", "successor"]
type OperationBaselineKind = Literal["initial_full_rebuild", "prior_assured_snapshot"]
type W2SourceMemberRole = Literal[
    "discovery_seed",
    "full_extraction_executable",
    "live_snapshot",
    "successor_delta",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z", flags=re.ASCII)
_SAFE_ROUTE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,511}\Z", flags=re.ASCII)
_STAGING_KEY_RE = re.compile(r"stg_[a-z0-9]+(?:_[a-z0-9]+)*\Z", flags=re.ASCII)
_MAX_INTEGER = (1 << 63) - 1
_SEAL_TOKEN = object()

_FULL_NORMALIZED_DOMAIN = "nbadb:f5:full-normalized-lane:v1"
_FULL_EXECUTABLE_DOMAIN = "nbadb:f5:full-executable-raw:v1"
_FULL_BLOCKED_DOMAIN = "nbadb:f5:full-blocked-raw:v1"
_RAW_TERMINAL_DOMAIN = "nbadb.operation-data.raw-terminal-locator.v1"
_W2_OPERATION_DOMAIN = "nbadb:f5:w2-operation:v1"
_W2_ADDED_DOMAIN = "nbadb:f5:w2-added:v1"
_W2_ATTRIBUTION_DOMAIN = "nbadb:f5:w2-attribution:v1"
_CONDITIONAL_MEMBER_DOMAIN = "nbadb:f5:conditional-member:v1"
_CONDITIONAL_ADDED_DOMAIN = "nbadb:f5:conditional-added:v1"
_CONDITIONAL_STAGING_KEY_DOMAIN = "nbadb:f5:conditional-staging-key:v1"
_CONDITIONAL_TYPED_SOURCE_DOMAIN = "nbadb:f5:conditional-typed-source:v1"

_CONDITIONAL_KIND_BY_STAGING_KEY: dict[str, ConditionalKind] = {
    "stg_nba_api_live_lossless_nodes": "live_complete_node_tree",
    "stg_nba_api_lossless_result_cells": "stats_additive_result_cells",
}


class OperationDataAuthorityError(ValueError):
    """PRECOMMIT operation-data evidence is malformed or cross-mixed."""


def _fail(message: str) -> Never:
    raise OperationDataAuthorityError(message)


def _canonical_bytes(value: object, *, label: str) -> bytes:
    try:
        return canonical_json_bytes_v1(value)
    except (DispositionEvidenceError, MemoryError, RecursionError) as exc:
        raise OperationDataAuthorityError(f"{label} is not bounded canonical JSON") from exc


def _decode(raw: object, *, label: str) -> Mapping[str, object]:
    try:
        decoded = decode_canonical_json_bytes_v1(raw, persisted=False)
    except (DispositionEvidenceError, MemoryError, RecursionError) as exc:
        raise OperationDataAuthorityError(f"{label} bytes are not exact canonical JSON") from exc
    if type(decoded) is not dict or any(type(key) is not str for key in decoded):
        _fail(f"{label} must contain one exact string-keyed object")
    return cast("Mapping[str, object]", decoded)


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _fail(f"{label} must be one exact string-keyed object")
    return cast("Mapping[str, object]", value)


def _exact_keys(value: Mapping[str, object], *, expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        _fail(
            f"{label} fields differ "
            f"(missing={','.join(sorted(expected - actual))}; "
            f"unexpected={','.join(sorted(actual - expected))})"
        )


def _schema(value: Mapping[str, object], *, kind: str, label: str) -> None:
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        _fail(f"{label} schema_version is invalid")
    if type(value["kind"]) is not str or value["kind"] != kind:
        _fail(f"{label} kind is invalid")


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _optional_sha256(value: object, *, label: str) -> str | None:
    return None if value is None else _sha256(value, label=label)


def _source_sha(value: object) -> str:
    if type(value) is not str or _SOURCE_SHA_RE.fullmatch(value) is None:
        _fail("source_sha must be one exact lowercase commit SHA")
    return value


def _safe_token(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_TOKEN_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact bounded safe token")
    return value


def _safe_route(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ROUTE_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact bounded route identity")
    return value


def _count(value: object, *, label: str, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or not minimum <= value <= _MAX_INTEGER:
        qualifier = "positive" if positive else "nonnegative"
        _fail(f"{label} must be one exact bounded {qualifier} integer")
    return value


def _digest(kind: str, identity_payload: Mapping[str, object]) -> str:
    digest = hashlib.sha256()
    digest.update(f"nbadb:{kind}:v1".encode("ascii"))
    digest.update(b"\x00")
    digest.update(_canonical_bytes(dict(identity_payload), label=f"{kind} digest preimage"))
    return digest.hexdigest()


def _empty_root(domain: str) -> str:
    try:
        value = empty_ordered_sha256_prefix_fold(domain=domain)
    except (ValueError, MemoryError, RecursionError) as exc:
        raise OperationDataAuthorityError("ordered prefix-fold empty root failed") from exc
    if type(value) is not OrderedSha256PrefixFoldV1 or value.count != 0:
        _fail("ordered prefix-fold returned a foreign empty result")
    return value.root_sha256


def _extended_root(
    *, domain: str, prior_count: int, prior_root_sha256: str, item_sha256: str
) -> str:
    try:
        value = extend_ordered_sha256_prefix_fold(
            domain=domain,
            prior_count=prior_count,
            prior_root_sha256=prior_root_sha256,
            appended_count=1,
            item_sha256s=(item_sha256,),
        )
    except (ValueError, MemoryError, RecursionError) as exc:
        raise OperationDataAuthorityError("ordered prefix-fold extension failed") from exc
    if type(value) is not OrderedSha256PrefixFoldV1 or value.count != prior_count + 1:
        _fail("ordered prefix-fold returned a foreign extension result")
    return value.root_sha256


def _require_empty_root(*, count: int, root: str, domain: str, label: str) -> None:
    if count == 0 and root != _empty_root(domain):
        _fail(f"{label} zero-count root differs from the exact empty prefix fold")


def _inventory_root(domain: str, item_sha256s: tuple[str, ...]) -> str:
    """Return the exact ordered prefix-fold root for one bounded tuple."""

    root = _empty_root(domain)
    for count, item_sha256 in enumerate(item_sha256s):
        _sha256(item_sha256, label="inventory item sha256")
        root = _extended_root(
            domain=domain,
            prior_count=count,
            prior_root_sha256=root,
            item_sha256=item_sha256,
        )
    return root


@dataclass(frozen=True, slots=True)
class _OperationContextV1:
    operation_sha256: str
    source_sha: str
    chain_id: str
    transaction_generation: int
    transaction_generation_identity_sha256: str
    duckdb_snapshot_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.operation_sha256, label="operation_sha256")
        _source_sha(self.source_sha)
        _safe_token(self.chain_id, label="chain_id")
        _count(self.transaction_generation, label="transaction_generation", positive=True)
        _sha256(
            self.transaction_generation_identity_sha256,
            label="transaction_generation_identity_sha256",
        )
        _sha256(self.duckdb_snapshot_sha256, label="duckdb_snapshot_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "chain_id": self.chain_id,
            "duckdb_snapshot_sha256": self.duckdb_snapshot_sha256,
            "operation_sha256": self.operation_sha256,
            "source_sha": self.source_sha,
            "transaction_generation": self.transaction_generation,
            "transaction_generation_identity_sha256": (self.transaction_generation_identity_sha256),
        }


def _context_from_payload(value: object, *, label: str) -> _OperationContextV1:
    payload = _mapping(value, label=label)
    _exact_keys(
        payload,
        expected=frozenset(
            {
                "chain_id",
                "duckdb_snapshot_sha256",
                "operation_sha256",
                "source_sha",
                "transaction_generation",
                "transaction_generation_identity_sha256",
            }
        ),
        label=label,
    )
    return _OperationContextV1(
        operation_sha256=cast("str", payload["operation_sha256"]),
        source_sha=cast("str", payload["source_sha"]),
        chain_id=cast("str", payload["chain_id"]),
        transaction_generation=cast("int", payload["transaction_generation"]),
        transaction_generation_identity_sha256=cast(
            "str", payload["transaction_generation_identity_sha256"]
        ),
        duckdb_snapshot_sha256=cast("str", payload["duckdb_snapshot_sha256"]),
    )


@dataclass(frozen=True, slots=True)
class DurableRawTerminalManifestLocatorV1:
    """HMAC-free stable identity for one replayed terminal Raw manifest."""

    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    scope_sha256: str
    route_authority_sha256: str
    request_closure_authority_sha256: str
    field_authority_sha256: str
    model_authority_sha256: str
    authority_set_sha256: str
    expected_call_count: int
    expected_call_inventory_sha256: str
    route_count: int
    route_inventory_sha256: str
    terminal_generation: int
    terminal_parent_manifest_sha256: str | None
    terminal_manifest_sha256: str
    terminal_operation_sha256: str
    terminal_receipt_count: int
    terminal_receipt_inventory_sha256: str
    terminal_manifest_canonical_byte_length: int
    terminal_manifest_canonical_sha256: str
    locator_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_durable_raw_terminal_manifest_locator_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("Raw terminal locator construction is private")
        _source_sha(self.source_sha)
        _count(self.run_id, label="run_id", positive=True)
        _count(self.run_attempt, label="run_attempt", positive=True)
        _safe_token(self.chain_id, label="chain_id")
        _safe_token(self.lane_id, label="lane_id")
        for label in (
            "scope_sha256",
            "route_authority_sha256",
            "request_closure_authority_sha256",
            "field_authority_sha256",
            "model_authority_sha256",
            "authority_set_sha256",
            "expected_call_inventory_sha256",
            "route_inventory_sha256",
            "terminal_manifest_sha256",
            "terminal_operation_sha256",
            "terminal_receipt_inventory_sha256",
            "terminal_manifest_canonical_sha256",
        ):
            _sha256(getattr(self, label), label=label)
        _count(self.expected_call_count, label="expected_call_count", positive=True)
        _count(self.route_count, label="route_count", positive=True)
        _count(self.terminal_generation, label="terminal_generation")
        parent = _optional_sha256(
            self.terminal_parent_manifest_sha256,
            label="terminal_parent_manifest_sha256",
        )
        if (self.terminal_generation == 0) != (parent is None):
            _fail("Raw terminal parent identity differs from its generation")
        _count(self.terminal_receipt_count, label="terminal_receipt_count", positive=True)
        _count(
            self.terminal_manifest_canonical_byte_length,
            label="terminal_manifest_canonical_byte_length",
            positive=True,
        )
        if self.terminal_manifest_canonical_byte_length > CANONICAL_JSON_MAX_BYTES:
            _fail("Raw terminal manifest canonical byte length exceeds its native codec bound")
        if self.terminal_receipt_count != self.expected_call_count:
            _fail("Raw terminal receipt count differs from its expected-call denominator")
        if self.locator_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("Raw terminal locator digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_set_sha256": self.authority_set_sha256,
            "chain_id": self.chain_id,
            "expected_call_count": self.expected_call_count,
            "expected_call_inventory_sha256": self.expected_call_inventory_sha256,
            "field_authority_sha256": self.field_authority_sha256,
            "lane_id": self.lane_id,
            "model_authority_sha256": self.model_authority_sha256,
            "request_closure_authority_sha256": self.request_closure_authority_sha256,
            "route_authority_sha256": self.route_authority_sha256,
            "route_count": self.route_count,
            "route_inventory_sha256": self.route_inventory_sha256,
            "run_attempt": self.run_attempt,
            "run_id": self.run_id,
            "scope_sha256": self.scope_sha256,
            "source_sha": self.source_sha,
            "terminal_generation": self.terminal_generation,
            "terminal_manifest_canonical_byte_length": (
                self.terminal_manifest_canonical_byte_length
            ),
            "terminal_manifest_canonical_sha256": self.terminal_manifest_canonical_sha256,
            "terminal_manifest_sha256": self.terminal_manifest_sha256,
            "terminal_operation_sha256": self.terminal_operation_sha256,
            "terminal_parent_manifest_sha256": self.terminal_parent_manifest_sha256,
            "terminal_receipt_count": self.terminal_receipt_count,
            "terminal_receipt_inventory_sha256": self.terminal_receipt_inventory_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "locator_sha256": self.locator_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not DurableRawTerminalManifestLocatorV1:
            _fail("Raw terminal locator serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="Raw terminal locator")

    @classmethod
    def _seal(cls, **values: object) -> Self:
        if cls is not DurableRawTerminalManifestLocatorV1:
            _fail("Raw terminal locator requires its exact DTO class")
        identity = {
            "schema_version": 1,
            "kind": cls.kind,
            **values,
        }
        return cls(
            **values,  # ty: ignore[invalid-argument-type]
            locator_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not DurableRawTerminalManifestLocatorV1:
            _fail("Raw terminal locator requires its exact DTO class")
        payload = _mapping(value, label="Raw terminal locator")
        fields = frozenset(
            {
                "authority_set_sha256",
                "chain_id",
                "expected_call_count",
                "expected_call_inventory_sha256",
                "field_authority_sha256",
                "lane_id",
                "locator_sha256",
                "model_authority_sha256",
                "request_closure_authority_sha256",
                "route_authority_sha256",
                "route_count",
                "route_inventory_sha256",
                "run_attempt",
                "run_id",
                "scope_sha256",
                "source_sha",
                "terminal_generation",
                "terminal_manifest_canonical_byte_length",
                "terminal_manifest_canonical_sha256",
                "terminal_manifest_sha256",
                "terminal_operation_sha256",
                "terminal_parent_manifest_sha256",
                "terminal_receipt_count",
                "terminal_receipt_inventory_sha256",
            }
        )
        _exact_keys(
            payload,
            expected=fields | {"schema_version", "kind"},
            label="Raw terminal locator",
        )
        _schema(payload, kind=cls.kind, label="Raw terminal locator")
        values = {name: payload[name] for name in fields}
        return cls(**values, _token=_SEAL_TOKEN)  # ty: ignore[invalid-argument-type]

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not DurableRawTerminalManifestLocatorV1:
            _fail("Raw terminal locator requires its exact DTO class")
        try:
            candidate = cls._from_payload(_decode(raw, label="Raw terminal locator"))
            canonical = candidate.canonical_bytes()
        except (MemoryError, RecursionError) as exc:
            raise OperationDataAuthorityError(
                "Raw terminal locator replay exceeded bounds"
            ) from exc
        if raw != canonical:
            _fail("Raw terminal locator bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class FullExtractionExecutableRawMemberV1:
    normalized_lane_sha256: str
    terminal_locator: DurableRawTerminalManifestLocatorV1
    member_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_full_extraction_executable_raw_member_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("full-extraction executable Raw member construction is private")
        _sha256(self.normalized_lane_sha256, label="normalized_lane_sha256")
        if type(self.terminal_locator) is not DurableRawTerminalManifestLocatorV1:
            _fail("executable Raw member requires one exact terminal locator")
        if self.member_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("executable Raw member digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "normalized_lane_sha256": self.normalized_lane_sha256,
            "terminal_locator": self.terminal_locator.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "member_sha256": self.member_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not FullExtractionExecutableRawMemberV1:
            _fail("executable Raw member serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="executable Raw member")

    @classmethod
    def _seal(
        cls, *, normalized_lane_sha256: str, terminal_locator: DurableRawTerminalManifestLocatorV1
    ) -> Self:
        if cls is not FullExtractionExecutableRawMemberV1:
            _fail("executable Raw member requires its exact DTO class")
        identity = {
            "schema_version": 1,
            "kind": cls.kind,
            "normalized_lane_sha256": normalized_lane_sha256,
            "terminal_locator": terminal_locator.to_dict(),
        }
        return cls(
            normalized_lane_sha256=normalized_lane_sha256,
            terminal_locator=terminal_locator,
            member_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not FullExtractionExecutableRawMemberV1:
            _fail("executable Raw member requires its exact DTO class")
        payload = _mapping(value, label="executable Raw member")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "normalized_lane_sha256",
                    "terminal_locator",
                    "member_sha256",
                }
            ),
            label="executable Raw member",
        )
        _schema(payload, kind=cls.kind, label="executable Raw member")
        return cls(
            normalized_lane_sha256=cast("str", payload["normalized_lane_sha256"]),
            terminal_locator=DurableRawTerminalManifestLocatorV1._from_payload(
                payload["terminal_locator"]
            ),
            member_sha256=cast("str", payload["member_sha256"]),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not FullExtractionExecutableRawMemberV1:
            _fail("executable Raw member requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="executable Raw member"))
        if raw != candidate.canonical_bytes():
            _fail("executable Raw member bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class FullExtractionBlockedRawMemberV1:
    normalized_lane_sha256: str
    blocked_evidence_sha256: str
    member_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_full_extraction_blocked_raw_member_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("full-extraction blocked Raw member construction is private")
        _sha256(self.normalized_lane_sha256, label="normalized_lane_sha256")
        _sha256(self.blocked_evidence_sha256, label="blocked_evidence_sha256")
        if self.member_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("blocked Raw member digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "blocked_evidence_sha256": self.blocked_evidence_sha256,
            "normalized_lane_sha256": self.normalized_lane_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "member_sha256": self.member_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not FullExtractionBlockedRawMemberV1:
            _fail("blocked Raw member serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="blocked Raw member")

    @classmethod
    def _seal(cls, *, normalized_lane_sha256: str, blocked_evidence_sha256: str) -> Self:
        if cls is not FullExtractionBlockedRawMemberV1:
            _fail("blocked Raw member requires its exact DTO class")
        identity = {
            "schema_version": 1,
            "kind": cls.kind,
            "blocked_evidence_sha256": blocked_evidence_sha256,
            "normalized_lane_sha256": normalized_lane_sha256,
        }
        return cls(
            normalized_lane_sha256=normalized_lane_sha256,
            blocked_evidence_sha256=blocked_evidence_sha256,
            member_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not FullExtractionBlockedRawMemberV1:
            _fail("blocked Raw member requires its exact DTO class")
        payload = _mapping(value, label="blocked Raw member")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "blocked_evidence_sha256",
                    "normalized_lane_sha256",
                    "member_sha256",
                }
            ),
            label="blocked Raw member",
        )
        _schema(payload, kind=cls.kind, label="blocked Raw member")
        return cls(
            normalized_lane_sha256=cast("str", payload["normalized_lane_sha256"]),
            blocked_evidence_sha256=cast("str", payload["blocked_evidence_sha256"]),
            member_sha256=cast("str", payload["member_sha256"]),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not FullExtractionBlockedRawMemberV1:
            _fail("blocked Raw member requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="blocked Raw member"))
        if raw != candidate.canonical_bytes():
            _fail("blocked Raw member bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class RawAuxiliaryTerminalMemberV1:
    auxiliary_role: RawAuxiliaryRole
    terminal_locator: DurableRawTerminalManifestLocatorV1
    member_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_raw_auxiliary_terminal_member_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("Raw auxiliary terminal member construction is private")
        if type(self.auxiliary_role) is not str or self.auxiliary_role not in {
            "discovery_seed",
            "live_snapshot",
        }:
            _fail("Raw auxiliary terminal role is invalid")
        if type(self.terminal_locator) is not DurableRawTerminalManifestLocatorV1:
            _fail("Raw auxiliary member requires one exact terminal locator")
        if self.member_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("Raw auxiliary terminal member digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "auxiliary_role": self.auxiliary_role,
            "terminal_locator": self.terminal_locator.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "member_sha256": self.member_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not RawAuxiliaryTerminalMemberV1:
            _fail("Raw auxiliary member serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="Raw auxiliary terminal member")

    @classmethod
    def _seal(
        cls,
        *,
        auxiliary_role: RawAuxiliaryRole,
        terminal_locator: DurableRawTerminalManifestLocatorV1,
    ) -> Self:
        if cls is not RawAuxiliaryTerminalMemberV1:
            _fail("Raw auxiliary member requires its exact DTO class")
        identity = {
            "schema_version": 1,
            "kind": cls.kind,
            "auxiliary_role": auxiliary_role,
            "terminal_locator": terminal_locator.to_dict(),
        }
        return cls(
            auxiliary_role=auxiliary_role,
            terminal_locator=terminal_locator,
            member_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not RawAuxiliaryTerminalMemberV1:
            _fail("Raw auxiliary member requires its exact DTO class")
        payload = _mapping(value, label="Raw auxiliary terminal member")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "auxiliary_role",
                    "terminal_locator",
                    "member_sha256",
                }
            ),
            label="Raw auxiliary terminal member",
        )
        _schema(payload, kind=cls.kind, label="Raw auxiliary terminal member")
        return cls(
            auxiliary_role=cast("RawAuxiliaryRole", payload["auxiliary_role"]),
            terminal_locator=DurableRawTerminalManifestLocatorV1._from_payload(
                payload["terminal_locator"]
            ),
            member_sha256=cast("str", payload["member_sha256"]),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not RawAuxiliaryTerminalMemberV1:
            _fail("Raw auxiliary member requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="Raw auxiliary terminal member"))
        if raw != candidate.canonical_bytes():
            _fail("Raw auxiliary terminal member bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class FullExtractionRawOperationDenominatorV1:
    """Durable scalar closure plus verifier-only exact member sidecars.

    The member tuples are excluded from durable JSON and equality: the public
    PRECOMMIT evidence remains bounded to native count/root projections. They
    exist only on freshly sealed in-memory values so the snapshot verifier can
    exact-join terminal locators before the scalar denominator is persisted.
    """

    operation_context: _OperationContextV1
    normalized_manifest_lane_count: int
    normalized_manifest_lane_inventory_sha256: str
    executable_lane_count: int
    executable_lane_inventory_sha256: str
    blocked_lane_count: int
    blocked_lane_inventory_sha256: str
    discovery_member: RawAuxiliaryTerminalMemberV1
    live_member: RawAuxiliaryTerminalMemberV1
    raw_terminal_member_count: int
    raw_terminal_inventory_sha256: str
    denominator_sha256: str
    normalized_manifest_lane_sha256s: tuple[str, ...] = field(default=(), repr=False, compare=False)
    executable_members: tuple[FullExtractionExecutableRawMemberV1, ...] = field(
        default=(), repr=False, compare=False
    )
    blocked_members: tuple[FullExtractionBlockedRawMemberV1, ...] = field(
        default=(), repr=False, compare=False
    )
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_full_extraction_raw_operation_denominator_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("full-extraction Raw denominator construction is private")
        if type(self.operation_context) is not _OperationContextV1:
            _fail("full-extraction Raw denominator lacks its exact operation context")
        _count(
            self.normalized_manifest_lane_count,
            label="normalized_manifest_lane_count",
            positive=True,
        )
        _count(self.executable_lane_count, label="executable_lane_count")
        _count(self.blocked_lane_count, label="blocked_lane_count")
        _count(self.raw_terminal_member_count, label="raw_terminal_member_count", positive=True)
        for label in (
            "normalized_manifest_lane_inventory_sha256",
            "executable_lane_inventory_sha256",
            "blocked_lane_inventory_sha256",
            "raw_terminal_inventory_sha256",
        ):
            _sha256(getattr(self, label), label=label)
        _require_empty_root(
            count=self.executable_lane_count,
            root=self.executable_lane_inventory_sha256,
            domain=_FULL_EXECUTABLE_DOMAIN,
            label="full-extraction executable inventory",
        )
        _require_empty_root(
            count=self.blocked_lane_count,
            root=self.blocked_lane_inventory_sha256,
            domain=_FULL_BLOCKED_DOMAIN,
            label="full-extraction blocked inventory",
        )
        if self.normalized_manifest_lane_count != (
            self.executable_lane_count + self.blocked_lane_count
        ):
            _fail("full-extraction executable/blocked counts do not partition the denominator")
        if self.raw_terminal_member_count != self.executable_lane_count + 2:
            _fail("full-extraction terminal count does not include executable plus auxiliaries")
        if (
            type(self.discovery_member) is not RawAuxiliaryTerminalMemberV1
            or self.discovery_member.auxiliary_role != "discovery_seed"
            or type(self.live_member) is not RawAuxiliaryTerminalMemberV1
            or self.live_member.auxiliary_role != "live_snapshot"
        ):
            _fail("full-extraction discovery/live auxiliary members are not exact")
        for locator in (
            self.discovery_member.terminal_locator,
            self.live_member.terminal_locator,
        ):
            if (
                locator.source_sha != self.operation_context.source_sha
                or locator.chain_id != self.operation_context.chain_id
            ):
                _fail("full-extraction Raw locator crosses operation source or chain")

        sidecars_present = bool(
            self.normalized_manifest_lane_sha256s or self.executable_members or self.blocked_members
        )
        if sidecars_present:
            if (
                type(self.normalized_manifest_lane_sha256s) is not tuple
                or type(self.executable_members) is not tuple
                or type(self.blocked_members) is not tuple
            ):
                _fail("full-extraction Raw member sidecars must be exact tuples")
            if any(
                type(member) is not FullExtractionExecutableRawMemberV1
                for member in self.executable_members
            ) or any(
                type(member) is not FullExtractionBlockedRawMemberV1
                for member in self.blocked_members
            ):
                _fail("full-extraction Raw member sidecars contain a foreign member")
            normalized = self.normalized_manifest_lane_sha256s
            for lane_sha256 in normalized:
                _sha256(lane_sha256, label="normalized_manifest_lane_sha256s item")
            if len(set(normalized)) != len(normalized):
                _fail("full-extraction normalized lane sidecar contains duplicates")
            executable_lanes = tuple(
                member.normalized_lane_sha256 for member in self.executable_members
            )
            blocked_lanes = tuple(member.normalized_lane_sha256 for member in self.blocked_members)
            if (
                len(normalized) != self.normalized_manifest_lane_count
                or len(self.executable_members) != self.executable_lane_count
                or len(self.blocked_members) != self.blocked_lane_count
                or set(executable_lanes) & set(blocked_lanes)
                or set(executable_lanes) | set(blocked_lanes) != set(normalized)
            ):
                _fail("full-extraction Raw member sidecars do not exact-partition lanes")
            expected_roots = (
                (
                    self.normalized_manifest_lane_inventory_sha256,
                    _inventory_root(_FULL_NORMALIZED_DOMAIN, normalized),
                ),
                (
                    self.executable_lane_inventory_sha256,
                    _inventory_root(
                        _FULL_EXECUTABLE_DOMAIN,
                        tuple(member.member_sha256 for member in self.executable_members),
                    ),
                ),
                (
                    self.blocked_lane_inventory_sha256,
                    _inventory_root(
                        _FULL_BLOCKED_DOMAIN,
                        tuple(member.member_sha256 for member in self.blocked_members),
                    ),
                ),
                (
                    self.raw_terminal_inventory_sha256,
                    _inventory_root(
                        _RAW_TERMINAL_DOMAIN,
                        (
                            *(
                                member.terminal_locator.locator_sha256
                                for member in self.executable_members
                            ),
                            self.discovery_member.terminal_locator.locator_sha256,
                            self.live_member.terminal_locator.locator_sha256,
                        ),
                    ),
                ),
            )
            if any(actual != expected for actual, expected in expected_roots):
                _fail("full-extraction Raw member sidecar root differs")
            for member in self.executable_members:
                locator = member.terminal_locator
                if (
                    locator.source_sha != self.operation_context.source_sha
                    or locator.chain_id != self.operation_context.chain_id
                ):
                    _fail("full-extraction executable locator crosses source or chain")
        if self.denominator_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("full-extraction Raw denominator digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "blocked_lane_count": self.blocked_lane_count,
            "blocked_lane_inventory_sha256": self.blocked_lane_inventory_sha256,
            "discovery_member": self.discovery_member.to_dict(),
            "executable_lane_count": self.executable_lane_count,
            "executable_lane_inventory_sha256": self.executable_lane_inventory_sha256,
            "live_member": self.live_member.to_dict(),
            "normalized_manifest_lane_count": self.normalized_manifest_lane_count,
            "normalized_manifest_lane_inventory_sha256": (
                self.normalized_manifest_lane_inventory_sha256
            ),
            "operation_context": self.operation_context.to_dict(),
            "raw_terminal_inventory_sha256": self.raw_terminal_inventory_sha256,
            "raw_terminal_member_count": self.raw_terminal_member_count,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "denominator_sha256": self.denominator_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not FullExtractionRawOperationDenominatorV1:
            _fail("full-extraction Raw serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="full-extraction Raw denominator")

    @classmethod
    def _seal(
        cls,
        *,
        operation_context: _OperationContextV1,
        discovery_member: RawAuxiliaryTerminalMemberV1,
        live_member: RawAuxiliaryTerminalMemberV1,
        normalized_manifest_lane_sha256s: tuple[str, ...] | None = None,
        executable_members: tuple[FullExtractionExecutableRawMemberV1, ...] | None = None,
        blocked_members: tuple[FullExtractionBlockedRawMemberV1, ...] | None = None,
        normalized_manifest_lane_count: int | None = None,
        normalized_manifest_lane_inventory_sha256: str | None = None,
        executable_lane_count: int | None = None,
        executable_lane_inventory_sha256: str | None = None,
        blocked_lane_count: int | None = None,
        blocked_lane_inventory_sha256: str | None = None,
        raw_terminal_inventory_sha256: str | None = None,
    ) -> Self:
        if cls is not FullExtractionRawOperationDenominatorV1:
            _fail("full-extraction Raw denominator requires its exact DTO class")
        enumerable = (
            normalized_manifest_lane_sha256s,
            executable_members,
            blocked_members,
        )
        scalar = (
            normalized_manifest_lane_count,
            normalized_manifest_lane_inventory_sha256,
            executable_lane_count,
            executable_lane_inventory_sha256,
            blocked_lane_count,
            blocked_lane_inventory_sha256,
            raw_terminal_inventory_sha256,
        )
        if any(value is not None for value in enumerable):
            if not all(value is not None for value in enumerable):
                _fail("full-extraction enumerable denominator inputs are all-or-none")
            if any(value is not None for value in scalar):
                _fail("full-extraction denominator cannot mix scalar and enumerable inputs")
            normalized = cast("tuple[str, ...]", normalized_manifest_lane_sha256s)
            executable = cast("tuple[FullExtractionExecutableRawMemberV1, ...]", executable_members)
            blocked = cast("tuple[FullExtractionBlockedRawMemberV1, ...]", blocked_members)
            normalized_count = len(normalized)
            normalized_root = _inventory_root(_FULL_NORMALIZED_DOMAIN, normalized)
            executable_count = len(executable)
            executable_root = _inventory_root(
                _FULL_EXECUTABLE_DOMAIN,
                tuple(member.member_sha256 for member in executable),
            )
            blocked_count = len(blocked)
            blocked_root = _inventory_root(
                _FULL_BLOCKED_DOMAIN,
                tuple(member.member_sha256 for member in blocked),
            )
            raw_terminal_root = _inventory_root(
                _RAW_TERMINAL_DOMAIN,
                (
                    *(member.terminal_locator.locator_sha256 for member in executable),
                    discovery_member.terminal_locator.locator_sha256,
                    live_member.terminal_locator.locator_sha256,
                ),
            )
        else:
            if not all(value is not None for value in scalar):
                _fail("full-extraction scalar denominator inputs are all required")
            normalized = ()
            executable = ()
            blocked = ()
            normalized_count = cast("int", normalized_manifest_lane_count)
            normalized_root = cast("str", normalized_manifest_lane_inventory_sha256)
            executable_count = cast("int", executable_lane_count)
            executable_root = cast("str", executable_lane_inventory_sha256)
            blocked_count = cast("int", blocked_lane_count)
            blocked_root = cast("str", blocked_lane_inventory_sha256)
            raw_terminal_root = cast("str", raw_terminal_inventory_sha256)
        values: dict[str, object] = {
            "blocked_lane_count": blocked_count,
            "blocked_lane_inventory_sha256": blocked_root,
            "discovery_member": discovery_member,
            "executable_lane_count": executable_count,
            "executable_lane_inventory_sha256": executable_root,
            "live_member": live_member,
            "normalized_manifest_lane_count": normalized_count,
            "normalized_manifest_lane_inventory_sha256": normalized_root,
            "operation_context": operation_context,
            "raw_terminal_inventory_sha256": raw_terminal_root,
            "raw_terminal_member_count": executable_count + 2,
        }
        identity = cls._identity_from_values(values)
        return cls(
            operation_context=operation_context,
            normalized_manifest_lane_count=normalized_count,
            normalized_manifest_lane_inventory_sha256=normalized_root,
            executable_lane_count=executable_count,
            executable_lane_inventory_sha256=executable_root,
            blocked_lane_count=blocked_count,
            blocked_lane_inventory_sha256=blocked_root,
            discovery_member=discovery_member,
            live_member=live_member,
            raw_terminal_member_count=executable_count + 2,
            raw_terminal_inventory_sha256=raw_terminal_root,
            denominator_sha256=_digest(cls.kind, identity),
            normalized_manifest_lane_sha256s=normalized,
            executable_members=executable,
            blocked_members=blocked,
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _identity_from_values(cls, values: Mapping[str, object]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": cls.kind,
            "blocked_lane_count": values["blocked_lane_count"],
            "blocked_lane_inventory_sha256": values["blocked_lane_inventory_sha256"],
            "discovery_member": cast(
                "RawAuxiliaryTerminalMemberV1", values["discovery_member"]
            ).to_dict(),
            "executable_lane_count": values["executable_lane_count"],
            "executable_lane_inventory_sha256": values["executable_lane_inventory_sha256"],
            "live_member": cast("RawAuxiliaryTerminalMemberV1", values["live_member"]).to_dict(),
            "normalized_manifest_lane_count": values["normalized_manifest_lane_count"],
            "normalized_manifest_lane_inventory_sha256": values[
                "normalized_manifest_lane_inventory_sha256"
            ],
            "operation_context": cast("_OperationContextV1", values["operation_context"]).to_dict(),
            "raw_terminal_inventory_sha256": values["raw_terminal_inventory_sha256"],
            "raw_terminal_member_count": values["raw_terminal_member_count"],
        }

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not FullExtractionRawOperationDenominatorV1:
            _fail("full-extraction Raw denominator requires its exact DTO class")
        payload = _mapping(value, label="full-extraction Raw denominator")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "blocked_lane_count",
                    "blocked_lane_inventory_sha256",
                    "denominator_sha256",
                    "discovery_member",
                    "executable_lane_count",
                    "executable_lane_inventory_sha256",
                    "live_member",
                    "normalized_manifest_lane_count",
                    "normalized_manifest_lane_inventory_sha256",
                    "operation_context",
                    "raw_terminal_inventory_sha256",
                    "raw_terminal_member_count",
                }
            ),
            label="full-extraction Raw denominator",
        )
        _schema(payload, kind=cls.kind, label="full-extraction Raw denominator")
        return cls(
            operation_context=_context_from_payload(
                payload["operation_context"], label="full-extraction operation context"
            ),
            normalized_manifest_lane_count=cast("int", payload["normalized_manifest_lane_count"]),
            normalized_manifest_lane_inventory_sha256=cast(
                "str", payload["normalized_manifest_lane_inventory_sha256"]
            ),
            executable_lane_count=cast("int", payload["executable_lane_count"]),
            executable_lane_inventory_sha256=cast(
                "str", payload["executable_lane_inventory_sha256"]
            ),
            blocked_lane_count=cast("int", payload["blocked_lane_count"]),
            blocked_lane_inventory_sha256=cast("str", payload["blocked_lane_inventory_sha256"]),
            discovery_member=RawAuxiliaryTerminalMemberV1._from_payload(
                payload["discovery_member"]
            ),
            live_member=RawAuxiliaryTerminalMemberV1._from_payload(payload["live_member"]),
            raw_terminal_member_count=cast("int", payload["raw_terminal_member_count"]),
            raw_terminal_inventory_sha256=cast("str", payload["raw_terminal_inventory_sha256"]),
            denominator_sha256=cast("str", payload["denominator_sha256"]),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not FullExtractionRawOperationDenominatorV1:
            _fail("full-extraction Raw denominator requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="full-extraction Raw denominator"))
        if raw != candidate.canonical_bytes():
            _fail("full-extraction Raw denominator bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class SuccessorRawOperationDenominatorV1:
    """Scalar append-only Raw denominator for one exact successor delta."""

    operation_context: _OperationContextV1
    prior_operation_data_evidence_sha256: str
    prior_raw_snapshot_sha256: str
    prior_raw_terminal_member_count: int
    prior_raw_terminal_inventory_sha256: str
    successor_execution_plan_sha256: str
    planning_generation_manifest_sha256: str
    planned_route_replacement_bindings_sha256: str
    dispatch_call_count: int
    dispatch_call_inventory_sha256: str
    requested_route_binding_count: int
    requested_route_binding_inventory_sha256: str
    delta_terminal_locator: DurableRawTerminalManifestLocatorV1
    cumulative_raw_terminal_member_count: int
    cumulative_raw_terminal_inventory_sha256: str
    denominator_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_successor_raw_operation_denominator_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("successor Raw denominator construction is private")
        if type(self.operation_context) is not _OperationContextV1:
            _fail("successor Raw denominator lacks its exact operation context")
        for label in (
            "prior_operation_data_evidence_sha256",
            "prior_raw_snapshot_sha256",
            "prior_raw_terminal_inventory_sha256",
            "successor_execution_plan_sha256",
            "planning_generation_manifest_sha256",
            "planned_route_replacement_bindings_sha256",
            "dispatch_call_inventory_sha256",
            "requested_route_binding_inventory_sha256",
            "cumulative_raw_terminal_inventory_sha256",
        ):
            _sha256(getattr(self, label), label=label)
        _count(
            self.prior_raw_terminal_member_count,
            label="prior_raw_terminal_member_count",
            positive=True,
        )
        _count(self.dispatch_call_count, label="dispatch_call_count", positive=True)
        _count(
            self.requested_route_binding_count,
            label="requested_route_binding_count",
            positive=True,
        )
        _count(
            self.cumulative_raw_terminal_member_count,
            label="cumulative_raw_terminal_member_count",
            positive=True,
        )
        if type(self.delta_terminal_locator) is not DurableRawTerminalManifestLocatorV1:
            _fail("successor Raw denominator requires one exact terminal delta locator")
        if (
            self.delta_terminal_locator.source_sha != self.operation_context.source_sha
            or self.delta_terminal_locator.chain_id != self.operation_context.chain_id
        ):
            _fail("successor delta locator crosses operation source or chain")
        if (
            self.delta_terminal_locator.expected_call_count != self.dispatch_call_count
            or self.delta_terminal_locator.expected_call_inventory_sha256
            != self.dispatch_call_inventory_sha256
            or self.delta_terminal_locator.route_count != self.requested_route_binding_count
            or self.delta_terminal_locator.route_inventory_sha256
            != self.requested_route_binding_inventory_sha256
        ):
            _fail("successor delta locator does not close its call/route denominator")
        if self.cumulative_raw_terminal_member_count != self.prior_raw_terminal_member_count + 1:
            _fail("successor cumulative Raw count is not one exact append")
        expected_root = _extended_root(
            domain=_RAW_TERMINAL_DOMAIN,
            prior_count=self.prior_raw_terminal_member_count,
            prior_root_sha256=self.prior_raw_terminal_inventory_sha256,
            item_sha256=self.delta_terminal_locator.locator_sha256,
        )
        if self.cumulative_raw_terminal_inventory_sha256 != expected_root:
            _fail("successor cumulative Raw root is not the exact delta extension")
        if self.denominator_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("successor Raw denominator digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "cumulative_raw_terminal_inventory_sha256": (
                self.cumulative_raw_terminal_inventory_sha256
            ),
            "cumulative_raw_terminal_member_count": self.cumulative_raw_terminal_member_count,
            "delta_terminal_locator": self.delta_terminal_locator.to_dict(),
            "dispatch_call_count": self.dispatch_call_count,
            "dispatch_call_inventory_sha256": self.dispatch_call_inventory_sha256,
            "operation_context": self.operation_context.to_dict(),
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
            "planning_generation_manifest_sha256": self.planning_generation_manifest_sha256,
            "prior_operation_data_evidence_sha256": self.prior_operation_data_evidence_sha256,
            "prior_raw_snapshot_sha256": self.prior_raw_snapshot_sha256,
            "prior_raw_terminal_inventory_sha256": self.prior_raw_terminal_inventory_sha256,
            "prior_raw_terminal_member_count": self.prior_raw_terminal_member_count,
            "requested_route_binding_count": self.requested_route_binding_count,
            "requested_route_binding_inventory_sha256": (
                self.requested_route_binding_inventory_sha256
            ),
            "successor_execution_plan_sha256": self.successor_execution_plan_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "denominator_sha256": self.denominator_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not SuccessorRawOperationDenominatorV1:
            _fail("successor Raw serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="successor Raw denominator")

    @classmethod
    def _seal(
        cls,
        *,
        operation_context: _OperationContextV1,
        prior_operation_data_evidence_sha256: str,
        prior_raw_snapshot_sha256: str,
        prior_raw_terminal_member_count: int,
        prior_raw_terminal_inventory_sha256: str,
        successor_execution_plan_sha256: str,
        planning_generation_manifest_sha256: str,
        planned_route_replacement_bindings_sha256: str,
        dispatch_call_count: int,
        dispatch_call_inventory_sha256: str,
        requested_route_binding_count: int,
        requested_route_binding_inventory_sha256: str,
        delta_terminal_locator: DurableRawTerminalManifestLocatorV1,
    ) -> Self:
        if cls is not SuccessorRawOperationDenominatorV1:
            _fail("successor Raw denominator requires its exact DTO class")
        cumulative_root = _extended_root(
            domain=_RAW_TERMINAL_DOMAIN,
            prior_count=prior_raw_terminal_member_count,
            prior_root_sha256=prior_raw_terminal_inventory_sha256,
            item_sha256=delta_terminal_locator.locator_sha256,
        )
        values: dict[str, object] = {
            "cumulative_raw_terminal_inventory_sha256": cumulative_root,
            "cumulative_raw_terminal_member_count": prior_raw_terminal_member_count + 1,
            "delta_terminal_locator": delta_terminal_locator,
            "dispatch_call_count": dispatch_call_count,
            "dispatch_call_inventory_sha256": dispatch_call_inventory_sha256,
            "operation_context": operation_context,
            "planned_route_replacement_bindings_sha256": (
                planned_route_replacement_bindings_sha256
            ),
            "planning_generation_manifest_sha256": planning_generation_manifest_sha256,
            "prior_operation_data_evidence_sha256": prior_operation_data_evidence_sha256,
            "prior_raw_snapshot_sha256": prior_raw_snapshot_sha256,
            "prior_raw_terminal_inventory_sha256": prior_raw_terminal_inventory_sha256,
            "prior_raw_terminal_member_count": prior_raw_terminal_member_count,
            "requested_route_binding_count": requested_route_binding_count,
            "requested_route_binding_inventory_sha256": (requested_route_binding_inventory_sha256),
            "successor_execution_plan_sha256": successor_execution_plan_sha256,
        }
        identity = cls._identity_from_values(values)
        return cls(
            operation_context=operation_context,
            prior_operation_data_evidence_sha256=prior_operation_data_evidence_sha256,
            prior_raw_snapshot_sha256=prior_raw_snapshot_sha256,
            prior_raw_terminal_member_count=prior_raw_terminal_member_count,
            prior_raw_terminal_inventory_sha256=prior_raw_terminal_inventory_sha256,
            successor_execution_plan_sha256=successor_execution_plan_sha256,
            planning_generation_manifest_sha256=planning_generation_manifest_sha256,
            planned_route_replacement_bindings_sha256=(planned_route_replacement_bindings_sha256),
            dispatch_call_count=dispatch_call_count,
            dispatch_call_inventory_sha256=dispatch_call_inventory_sha256,
            requested_route_binding_count=requested_route_binding_count,
            requested_route_binding_inventory_sha256=(requested_route_binding_inventory_sha256),
            delta_terminal_locator=delta_terminal_locator,
            cumulative_raw_terminal_member_count=prior_raw_terminal_member_count + 1,
            cumulative_raw_terminal_inventory_sha256=cumulative_root,
            denominator_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _identity_from_values(cls, values: Mapping[str, object]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": cls.kind,
            "cumulative_raw_terminal_inventory_sha256": values[
                "cumulative_raw_terminal_inventory_sha256"
            ],
            "cumulative_raw_terminal_member_count": values["cumulative_raw_terminal_member_count"],
            "delta_terminal_locator": cast(
                "DurableRawTerminalManifestLocatorV1", values["delta_terminal_locator"]
            ).to_dict(),
            "dispatch_call_count": values["dispatch_call_count"],
            "dispatch_call_inventory_sha256": values["dispatch_call_inventory_sha256"],
            "operation_context": cast("_OperationContextV1", values["operation_context"]).to_dict(),
            "planned_route_replacement_bindings_sha256": values[
                "planned_route_replacement_bindings_sha256"
            ],
            "planning_generation_manifest_sha256": values["planning_generation_manifest_sha256"],
            "prior_operation_data_evidence_sha256": values["prior_operation_data_evidence_sha256"],
            "prior_raw_snapshot_sha256": values["prior_raw_snapshot_sha256"],
            "prior_raw_terminal_inventory_sha256": values["prior_raw_terminal_inventory_sha256"],
            "prior_raw_terminal_member_count": values["prior_raw_terminal_member_count"],
            "requested_route_binding_count": values["requested_route_binding_count"],
            "requested_route_binding_inventory_sha256": values[
                "requested_route_binding_inventory_sha256"
            ],
            "successor_execution_plan_sha256": values["successor_execution_plan_sha256"],
        }

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not SuccessorRawOperationDenominatorV1:
            _fail("successor Raw denominator requires its exact DTO class")
        payload = _mapping(value, label="successor Raw denominator")
        keys = frozenset(
            {
                "schema_version",
                "kind",
                "cumulative_raw_terminal_inventory_sha256",
                "cumulative_raw_terminal_member_count",
                "delta_terminal_locator",
                "denominator_sha256",
                "dispatch_call_count",
                "dispatch_call_inventory_sha256",
                "operation_context",
                "planned_route_replacement_bindings_sha256",
                "planning_generation_manifest_sha256",
                "prior_operation_data_evidence_sha256",
                "prior_raw_snapshot_sha256",
                "prior_raw_terminal_inventory_sha256",
                "prior_raw_terminal_member_count",
                "requested_route_binding_count",
                "requested_route_binding_inventory_sha256",
                "successor_execution_plan_sha256",
            }
        )
        _exact_keys(payload, expected=keys, label="successor Raw denominator")
        _schema(payload, kind=cls.kind, label="successor Raw denominator")
        return cls(
            operation_context=_context_from_payload(
                payload["operation_context"], label="successor operation context"
            ),
            prior_operation_data_evidence_sha256=cast(
                "str", payload["prior_operation_data_evidence_sha256"]
            ),
            prior_raw_snapshot_sha256=cast("str", payload["prior_raw_snapshot_sha256"]),
            prior_raw_terminal_member_count=cast("int", payload["prior_raw_terminal_member_count"]),
            prior_raw_terminal_inventory_sha256=cast(
                "str", payload["prior_raw_terminal_inventory_sha256"]
            ),
            successor_execution_plan_sha256=cast("str", payload["successor_execution_plan_sha256"]),
            planning_generation_manifest_sha256=cast(
                "str", payload["planning_generation_manifest_sha256"]
            ),
            planned_route_replacement_bindings_sha256=cast(
                "str", payload["planned_route_replacement_bindings_sha256"]
            ),
            dispatch_call_count=cast("int", payload["dispatch_call_count"]),
            dispatch_call_inventory_sha256=cast("str", payload["dispatch_call_inventory_sha256"]),
            requested_route_binding_count=cast("int", payload["requested_route_binding_count"]),
            requested_route_binding_inventory_sha256=cast(
                "str", payload["requested_route_binding_inventory_sha256"]
            ),
            delta_terminal_locator=DurableRawTerminalManifestLocatorV1._from_payload(
                payload["delta_terminal_locator"]
            ),
            cumulative_raw_terminal_member_count=cast(
                "int", payload["cumulative_raw_terminal_member_count"]
            ),
            cumulative_raw_terminal_inventory_sha256=cast(
                "str", payload["cumulative_raw_terminal_inventory_sha256"]
            ),
            denominator_sha256=cast("str", payload["denominator_sha256"]),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not SuccessorRawOperationDenominatorV1:
            _fail("successor Raw denominator requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="successor Raw denominator"))
        if raw != candidate.canonical_bytes():
            _fail("successor Raw denominator bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class VerifiedOperationRawSnapshotV1:
    operation_context: _OperationContextV1
    operation_kind: RawOperationKind
    denominator: FullExtractionRawOperationDenominatorV1 | SuccessorRawOperationDenominatorV1
    denominator_sha256: str
    cumulative_raw_terminal_member_count: int
    cumulative_raw_terminal_inventory_sha256: str
    raw_snapshot_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_verified_operation_raw_snapshot_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("verified operation Raw snapshot construction is private")
        if type(self.operation_context) is not _OperationContextV1:
            _fail("verified Raw snapshot lacks its exact operation context")
        if self.operation_kind == "full_extraction":
            if type(self.denominator) is not FullExtractionRawOperationDenominatorV1:
                _fail("full-extraction Raw snapshot has a foreign denominator")
            count = self.denominator.raw_terminal_member_count
            root = self.denominator.raw_terminal_inventory_sha256
        elif self.operation_kind == "successor":
            if type(self.denominator) is not SuccessorRawOperationDenominatorV1:
                _fail("successor Raw snapshot has a foreign denominator")
            count = self.denominator.cumulative_raw_terminal_member_count
            root = self.denominator.cumulative_raw_terminal_inventory_sha256
        else:
            _fail("verified Raw snapshot operation kind is invalid")
        if self.denominator.operation_context != self.operation_context:
            _fail("verified Raw snapshot denominator crosses operation context")
        if (
            self.denominator_sha256 != self.denominator.denominator_sha256
            or self.cumulative_raw_terminal_member_count != count
            or self.cumulative_raw_terminal_inventory_sha256 != root
        ):
            _fail("verified Raw snapshot component projection differs")
        if self.raw_snapshot_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("verified Raw snapshot digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "cumulative_raw_terminal_inventory_sha256": (
                self.cumulative_raw_terminal_inventory_sha256
            ),
            "cumulative_raw_terminal_member_count": self.cumulative_raw_terminal_member_count,
            "denominator": self.denominator.to_dict(),
            "denominator_sha256": self.denominator_sha256,
            "operation_context": self.operation_context.to_dict(),
            "operation_kind": self.operation_kind,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "raw_snapshot_sha256": self.raw_snapshot_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not VerifiedOperationRawSnapshotV1:
            _fail("verified Raw snapshot serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="verified operation Raw snapshot")

    @classmethod
    def _seal(
        cls,
        *,
        operation_context: _OperationContextV1,
        operation_kind: RawOperationKind,
        denominator: FullExtractionRawOperationDenominatorV1 | SuccessorRawOperationDenominatorV1,
    ) -> Self:
        if cls is not VerifiedOperationRawSnapshotV1:
            _fail("verified Raw snapshot requires its exact DTO class")
        if type(denominator) is FullExtractionRawOperationDenominatorV1:
            count = denominator.raw_terminal_member_count
            root = denominator.raw_terminal_inventory_sha256
        elif type(denominator) is SuccessorRawOperationDenominatorV1:
            count = denominator.cumulative_raw_terminal_member_count
            root = denominator.cumulative_raw_terminal_inventory_sha256
        else:
            _fail("verified Raw snapshot requires one exact typed denominator")
        values: dict[str, object] = {
            "cumulative_raw_terminal_inventory_sha256": root,
            "cumulative_raw_terminal_member_count": count,
            "denominator": denominator,
            "denominator_sha256": denominator.denominator_sha256,
            "operation_context": operation_context,
            "operation_kind": operation_kind,
        }
        identity = cls._identity_from_values(values)
        return cls(
            operation_context=operation_context,
            operation_kind=operation_kind,
            denominator=denominator,
            denominator_sha256=denominator.denominator_sha256,
            cumulative_raw_terminal_member_count=count,
            cumulative_raw_terminal_inventory_sha256=root,
            raw_snapshot_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _identity_from_values(cls, values: Mapping[str, object]) -> dict[str, object]:
        denominator = cast(
            "FullExtractionRawOperationDenominatorV1 | SuccessorRawOperationDenominatorV1",
            values["denominator"],
        )
        return {
            "schema_version": 1,
            "kind": cls.kind,
            "cumulative_raw_terminal_inventory_sha256": values[
                "cumulative_raw_terminal_inventory_sha256"
            ],
            "cumulative_raw_terminal_member_count": values["cumulative_raw_terminal_member_count"],
            "denominator": denominator.to_dict(),
            "denominator_sha256": values["denominator_sha256"],
            "operation_context": cast("_OperationContextV1", values["operation_context"]).to_dict(),
            "operation_kind": values["operation_kind"],
        }

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not VerifiedOperationRawSnapshotV1:
            _fail("verified Raw snapshot requires its exact DTO class")
        payload = _mapping(value, label="verified operation Raw snapshot")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "cumulative_raw_terminal_inventory_sha256",
                    "cumulative_raw_terminal_member_count",
                    "denominator",
                    "denominator_sha256",
                    "operation_context",
                    "operation_kind",
                    "raw_snapshot_sha256",
                }
            ),
            label="verified operation Raw snapshot",
        )
        _schema(payload, kind=cls.kind, label="verified operation Raw snapshot")
        operation_kind = payload["operation_kind"]
        if operation_kind == "full_extraction":
            denominator = FullExtractionRawOperationDenominatorV1._from_payload(
                payload["denominator"]
            )
        elif operation_kind == "successor":
            denominator = SuccessorRawOperationDenominatorV1._from_payload(payload["denominator"])
        else:
            _fail("verified Raw snapshot operation kind is invalid")
        return cls(
            operation_context=_context_from_payload(
                payload["operation_context"], label="verified Raw operation context"
            ),
            operation_kind=cast("RawOperationKind", operation_kind),
            denominator=denominator,
            denominator_sha256=cast("str", payload["denominator_sha256"]),
            cumulative_raw_terminal_member_count=cast(
                "int", payload["cumulative_raw_terminal_member_count"]
            ),
            cumulative_raw_terminal_inventory_sha256=cast(
                "str", payload["cumulative_raw_terminal_inventory_sha256"]
            ),
            raw_snapshot_sha256=cast("str", payload["raw_snapshot_sha256"]),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not VerifiedOperationRawSnapshotV1:
            _fail("verified Raw snapshot requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="verified operation Raw snapshot"))
        if raw != candidate.canonical_bytes():
            _fail("verified operation Raw snapshot bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class W2SourceMemberAttributionV1:
    """One W2 operation attributed to one typed data-producing Raw member."""

    w2_operation_sha256: str
    source_member_role: W2SourceMemberRole
    source_member_sha256: str
    source_terminal_locator_sha256: str
    attribution_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_w2_source_member_attribution_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("W2 source-member attribution construction is private")
        _sha256(self.w2_operation_sha256, label="w2_operation_sha256")
        if type(self.source_member_role) is not str or self.source_member_role not in {
            "discovery_seed",
            "full_extraction_executable",
            "live_snapshot",
            "successor_delta",
        }:
            _fail("W2 source-member attribution role is invalid")
        _sha256(self.source_member_sha256, label="source_member_sha256")
        _sha256(
            self.source_terminal_locator_sha256,
            label="source_terminal_locator_sha256",
        )
        if self.attribution_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("W2 source-member attribution digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "source_member_role": self.source_member_role,
            "source_member_sha256": self.source_member_sha256,
            "source_terminal_locator_sha256": self.source_terminal_locator_sha256,
            "w2_operation_sha256": self.w2_operation_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "attribution_sha256": self.attribution_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not W2SourceMemberAttributionV1:
            _fail("W2 attribution serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="W2 source-member attribution")

    @classmethod
    def _seal(
        cls,
        *,
        w2_operation_sha256: str,
        source_member_role: W2SourceMemberRole,
        source_member_sha256: str,
        source_terminal_locator_sha256: str,
    ) -> Self:
        if cls is not W2SourceMemberAttributionV1:
            _fail("W2 attribution requires its exact DTO class")
        identity = {
            "schema_version": 1,
            "kind": cls.kind,
            "source_member_role": source_member_role,
            "source_member_sha256": source_member_sha256,
            "source_terminal_locator_sha256": source_terminal_locator_sha256,
            "w2_operation_sha256": w2_operation_sha256,
        }
        return cls(
            w2_operation_sha256=w2_operation_sha256,
            source_member_role=source_member_role,
            source_member_sha256=source_member_sha256,
            source_terminal_locator_sha256=source_terminal_locator_sha256,
            attribution_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not W2SourceMemberAttributionV1:
            _fail("W2 attribution requires its exact DTO class")
        payload = _mapping(value, label="W2 source-member attribution")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "attribution_sha256",
                    "source_member_role",
                    "source_member_sha256",
                    "source_terminal_locator_sha256",
                    "w2_operation_sha256",
                }
            ),
            label="W2 source-member attribution",
        )
        _schema(payload, kind=cls.kind, label="W2 source-member attribution")
        return cls(
            w2_operation_sha256=cast("str", payload["w2_operation_sha256"]),
            source_member_role=cast("W2SourceMemberRole", payload["source_member_role"]),
            source_member_sha256=cast("str", payload["source_member_sha256"]),
            source_terminal_locator_sha256=cast("str", payload["source_terminal_locator_sha256"]),
            attribution_sha256=cast("str", payload["attribution_sha256"]),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not W2SourceMemberAttributionV1:
            _fail("W2 attribution requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="W2 source-member attribution"))
        if raw != candidate.canonical_bytes():
            _fail("W2 source-member attribution bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class W2DatabaseAuthorityReceiptV1:
    """Scalar W2 multiset/attribution projections plus the public receipt."""

    operation_context: _OperationContextV1
    w2_baseline_kind: OperationBaselineKind
    prior_operation_data_evidence_sha256: str | None
    prior_w2_operation_count: int
    prior_w2_operation_inventory_sha256: str
    final_w2_operation_count: int
    final_w2_operation_inventory_sha256: str
    added_w2_operation_count: int
    added_w2_operation_inventory_sha256: str
    source_member_attribution_count: int
    source_member_attribution_inventory_sha256: str
    public_w2_database_receipt_sha256: str
    w2_required_logical_call_count: int
    w2_source_call_admission_inventory_sha256: str
    raw_authority_v2_bundle_count: int
    raw_authority_v2_bundle_inventory_sha256: str
    raw_authority_v2_persistence_receipt_inventory_sha256: str
    w2_publication_receipt_count: int
    w2_publication_receipt_inventory_sha256: str
    w2_exact_six_schema_inventory_sha256: str
    w2_relation_row_count: int
    w2_relation_inventory_sha256: str
    w2_operation_receipt_inventory_sha256: str
    w2_operation_persistence_receipt_inventory_sha256: str
    detailed_w2_multiset_sha256: str
    w2_database_authority_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_transform_output_w2_database_authority_receipt_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("detailed W2 database authority construction is private")
        if type(self.operation_context) is not _OperationContextV1:
            _fail("detailed W2 database authority lacks its exact operation context")
        if type(self.w2_baseline_kind) is not str or self.w2_baseline_kind not in {
            "initial_full_rebuild",
            "prior_assured_snapshot",
        }:
            _fail("detailed W2 baseline kind is invalid")
        prior_evidence = _optional_sha256(
            self.prior_operation_data_evidence_sha256,
            label="prior_operation_data_evidence_sha256",
        )
        if self.w2_baseline_kind == "initial_full_rebuild":
            if prior_evidence is not None or self.prior_w2_operation_count != 0:
                _fail("initial W2 baseline must have one exact empty prior denominator")
        elif prior_evidence is None:
            _fail("prior-assured W2 baseline lacks its prior evidence identity")

        for label in (
            "prior_w2_operation_count",
            "final_w2_operation_count",
            "added_w2_operation_count",
            "source_member_attribution_count",
            "w2_required_logical_call_count",
            "raw_authority_v2_bundle_count",
            "w2_publication_receipt_count",
            "w2_relation_row_count",
        ):
            _count(getattr(self, label), label=label)
        for label in (
            "prior_w2_operation_inventory_sha256",
            "final_w2_operation_inventory_sha256",
            "added_w2_operation_inventory_sha256",
            "source_member_attribution_inventory_sha256",
            "public_w2_database_receipt_sha256",
            "w2_source_call_admission_inventory_sha256",
            "raw_authority_v2_bundle_inventory_sha256",
            "raw_authority_v2_persistence_receipt_inventory_sha256",
            "w2_publication_receipt_inventory_sha256",
            "w2_exact_six_schema_inventory_sha256",
            "w2_relation_inventory_sha256",
            "w2_operation_receipt_inventory_sha256",
            "w2_operation_persistence_receipt_inventory_sha256",
            "detailed_w2_multiset_sha256",
        ):
            _sha256(getattr(self, label), label=label)
        for count, root, domain, label in (
            (
                self.prior_w2_operation_count,
                self.prior_w2_operation_inventory_sha256,
                _W2_OPERATION_DOMAIN,
                "prior W2 operation inventory",
            ),
            (
                self.final_w2_operation_count,
                self.final_w2_operation_inventory_sha256,
                _W2_OPERATION_DOMAIN,
                "final W2 operation inventory",
            ),
            (
                self.added_w2_operation_count,
                self.added_w2_operation_inventory_sha256,
                _W2_ADDED_DOMAIN,
                "added W2 operation inventory",
            ),
            (
                self.source_member_attribution_count,
                self.source_member_attribution_inventory_sha256,
                _W2_ATTRIBUTION_DOMAIN,
                "W2 source attribution inventory",
            ),
        ):
            _require_empty_root(count=count, root=root, domain=domain, label=label)
        if self.final_w2_operation_count != (
            self.prior_w2_operation_count + self.added_w2_operation_count
        ):
            _fail("W2 prior/final/addition count algebra differs")
        if self.source_member_attribution_count != self.added_w2_operation_count:
            _fail("W2 added-operation attribution count closure differs")
        if not (
            self.final_w2_operation_count
            == self.w2_required_logical_call_count
            == self.raw_authority_v2_bundle_count
            == self.w2_publication_receipt_count
        ):
            _fail("W2 final, call, Raw bundle, and publication counts differ")
        if self.detailed_w2_multiset_sha256 != _digest(
            "nbadb_detailed_w2_multiset_v1",
            self._multiset_payload(),
        ):
            _fail("detailed W2 multiset root differs")
        if self.w2_database_authority_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("detailed W2 database authority digest differs")

    def _multiset_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "nbadb_detailed_w2_multiset_v1",
            "added_w2_operation_count": self.added_w2_operation_count,
            "added_w2_operation_inventory_sha256": self.added_w2_operation_inventory_sha256,
            "final_w2_operation_count": self.final_w2_operation_count,
            "final_w2_operation_inventory_sha256": self.final_w2_operation_inventory_sha256,
            "prior_operation_data_evidence_sha256": (self.prior_operation_data_evidence_sha256),
            "prior_w2_operation_count": self.prior_w2_operation_count,
            "prior_w2_operation_inventory_sha256": self.prior_w2_operation_inventory_sha256,
            "source_member_attribution_count": self.source_member_attribution_count,
            "source_member_attribution_inventory_sha256": (
                self.source_member_attribution_inventory_sha256
            ),
            "w2_baseline_kind": self.w2_baseline_kind,
            "w2_operation_persistence_receipt_inventory_sha256": (
                self.w2_operation_persistence_receipt_inventory_sha256
            ),
            "w2_operation_receipt_inventory_sha256": (self.w2_operation_receipt_inventory_sha256),
        }

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "added_w2_operation_count": self.added_w2_operation_count,
            "added_w2_operation_inventory_sha256": self.added_w2_operation_inventory_sha256,
            "detailed_w2_multiset_sha256": self.detailed_w2_multiset_sha256,
            "final_w2_operation_count": self.final_w2_operation_count,
            "final_w2_operation_inventory_sha256": self.final_w2_operation_inventory_sha256,
            "operation_context": self.operation_context.to_dict(),
            "prior_operation_data_evidence_sha256": (self.prior_operation_data_evidence_sha256),
            "prior_w2_operation_count": self.prior_w2_operation_count,
            "prior_w2_operation_inventory_sha256": self.prior_w2_operation_inventory_sha256,
            "public_w2_database_receipt_sha256": self.public_w2_database_receipt_sha256,
            "raw_authority_v2_bundle_count": self.raw_authority_v2_bundle_count,
            "raw_authority_v2_bundle_inventory_sha256": (
                self.raw_authority_v2_bundle_inventory_sha256
            ),
            "raw_authority_v2_persistence_receipt_inventory_sha256": (
                self.raw_authority_v2_persistence_receipt_inventory_sha256
            ),
            "source_member_attribution_count": self.source_member_attribution_count,
            "source_member_attribution_inventory_sha256": (
                self.source_member_attribution_inventory_sha256
            ),
            "w2_baseline_kind": self.w2_baseline_kind,
            "w2_exact_six_schema_inventory_sha256": self.w2_exact_six_schema_inventory_sha256,
            "w2_operation_persistence_receipt_inventory_sha256": (
                self.w2_operation_persistence_receipt_inventory_sha256
            ),
            "w2_operation_receipt_inventory_sha256": (self.w2_operation_receipt_inventory_sha256),
            "w2_publication_receipt_count": self.w2_publication_receipt_count,
            "w2_publication_receipt_inventory_sha256": (
                self.w2_publication_receipt_inventory_sha256
            ),
            "w2_relation_inventory_sha256": self.w2_relation_inventory_sha256,
            "w2_relation_row_count": self.w2_relation_row_count,
            "w2_required_logical_call_count": self.w2_required_logical_call_count,
            "w2_source_call_admission_inventory_sha256": (
                self.w2_source_call_admission_inventory_sha256
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "w2_database_authority_sha256": self.w2_database_authority_sha256,
        }

    def canonical_bytes(self) -> bytes:
        if type(self) is not W2DatabaseAuthorityReceiptV1:
            _fail("W2 database authority serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="detailed W2 database authority")

    @classmethod
    def _seal(cls, **values: object) -> Self:
        if cls is not W2DatabaseAuthorityReceiptV1:
            _fail("W2 database authority requires its exact DTO class")
        multiset_payload = {
            "schema_version": 1,
            "kind": "nbadb_detailed_w2_multiset_v1",
            "added_w2_operation_count": values["added_w2_operation_count"],
            "added_w2_operation_inventory_sha256": values["added_w2_operation_inventory_sha256"],
            "final_w2_operation_count": values["final_w2_operation_count"],
            "final_w2_operation_inventory_sha256": values["final_w2_operation_inventory_sha256"],
            "prior_operation_data_evidence_sha256": values["prior_operation_data_evidence_sha256"],
            "prior_w2_operation_count": values["prior_w2_operation_count"],
            "prior_w2_operation_inventory_sha256": values["prior_w2_operation_inventory_sha256"],
            "source_member_attribution_count": values["source_member_attribution_count"],
            "source_member_attribution_inventory_sha256": values[
                "source_member_attribution_inventory_sha256"
            ],
            "w2_baseline_kind": values["w2_baseline_kind"],
            "w2_operation_persistence_receipt_inventory_sha256": values[
                "w2_operation_persistence_receipt_inventory_sha256"
            ],
            "w2_operation_receipt_inventory_sha256": values[
                "w2_operation_receipt_inventory_sha256"
            ],
        }
        detailed = _digest("nbadb_detailed_w2_multiset_v1", multiset_payload)
        identity = cls._identity_from_values(values, detailed=detailed)
        return cls(
            **values,  # ty: ignore[invalid-argument-type]
            detailed_w2_multiset_sha256=detailed,
            w2_database_authority_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _identity_from_values(
        cls, values: Mapping[str, object], *, detailed: str
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": cls.kind,
            "added_w2_operation_count": values["added_w2_operation_count"],
            "added_w2_operation_inventory_sha256": values["added_w2_operation_inventory_sha256"],
            "detailed_w2_multiset_sha256": detailed,
            "final_w2_operation_count": values["final_w2_operation_count"],
            "final_w2_operation_inventory_sha256": values["final_w2_operation_inventory_sha256"],
            "operation_context": cast("_OperationContextV1", values["operation_context"]).to_dict(),
            "prior_operation_data_evidence_sha256": values["prior_operation_data_evidence_sha256"],
            "prior_w2_operation_count": values["prior_w2_operation_count"],
            "prior_w2_operation_inventory_sha256": values["prior_w2_operation_inventory_sha256"],
            "public_w2_database_receipt_sha256": values["public_w2_database_receipt_sha256"],
            "raw_authority_v2_bundle_count": values["raw_authority_v2_bundle_count"],
            "raw_authority_v2_bundle_inventory_sha256": values[
                "raw_authority_v2_bundle_inventory_sha256"
            ],
            "raw_authority_v2_persistence_receipt_inventory_sha256": values[
                "raw_authority_v2_persistence_receipt_inventory_sha256"
            ],
            "source_member_attribution_count": values["source_member_attribution_count"],
            "source_member_attribution_inventory_sha256": values[
                "source_member_attribution_inventory_sha256"
            ],
            "w2_baseline_kind": values["w2_baseline_kind"],
            "w2_exact_six_schema_inventory_sha256": values["w2_exact_six_schema_inventory_sha256"],
            "w2_operation_persistence_receipt_inventory_sha256": values[
                "w2_operation_persistence_receipt_inventory_sha256"
            ],
            "w2_operation_receipt_inventory_sha256": values[
                "w2_operation_receipt_inventory_sha256"
            ],
            "w2_publication_receipt_count": values["w2_publication_receipt_count"],
            "w2_publication_receipt_inventory_sha256": values[
                "w2_publication_receipt_inventory_sha256"
            ],
            "w2_relation_inventory_sha256": values["w2_relation_inventory_sha256"],
            "w2_relation_row_count": values["w2_relation_row_count"],
            "w2_required_logical_call_count": values["w2_required_logical_call_count"],
            "w2_source_call_admission_inventory_sha256": values[
                "w2_source_call_admission_inventory_sha256"
            ],
        }

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not W2DatabaseAuthorityReceiptV1:
            _fail("W2 database authority requires its exact DTO class")
        payload = _mapping(value, label="detailed W2 database authority")
        fields = frozenset(
            {
                "added_w2_operation_count",
                "added_w2_operation_inventory_sha256",
                "detailed_w2_multiset_sha256",
                "final_w2_operation_count",
                "final_w2_operation_inventory_sha256",
                "operation_context",
                "prior_operation_data_evidence_sha256",
                "prior_w2_operation_count",
                "prior_w2_operation_inventory_sha256",
                "public_w2_database_receipt_sha256",
                "raw_authority_v2_bundle_count",
                "raw_authority_v2_bundle_inventory_sha256",
                "raw_authority_v2_persistence_receipt_inventory_sha256",
                "source_member_attribution_count",
                "source_member_attribution_inventory_sha256",
                "w2_baseline_kind",
                "w2_database_authority_sha256",
                "w2_exact_six_schema_inventory_sha256",
                "w2_operation_persistence_receipt_inventory_sha256",
                "w2_operation_receipt_inventory_sha256",
                "w2_publication_receipt_count",
                "w2_publication_receipt_inventory_sha256",
                "w2_relation_inventory_sha256",
                "w2_relation_row_count",
                "w2_required_logical_call_count",
                "w2_source_call_admission_inventory_sha256",
            }
        )
        _exact_keys(
            payload,
            expected=fields | {"schema_version", "kind"},
            label="detailed W2 database authority",
        )
        _schema(payload, kind=cls.kind, label="detailed W2 database authority")
        values = {name: payload[name] for name in fields if name != "operation_context"}
        return cls(
            operation_context=_context_from_payload(
                payload["operation_context"], label="W2 operation context"
            ),
            **values,  # ty: ignore[invalid-argument-type]
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not W2DatabaseAuthorityReceiptV1:
            _fail("W2 database authority requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="detailed W2 database authority"))
        if raw != candidate.canonical_bytes():
            _fail("detailed W2 database authority bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class CumulativeConditionalStagingEvidenceMemberV1:
    """One conditional staging member with an exact typed Raw source."""

    staging_key: str
    conditional_kind: ConditionalKind
    source_member_role: W2SourceMemberRole
    source_member_sha256: str
    source_terminal_locator_sha256: str
    route_id: str
    route_admission_sha256: str
    provider_authority_sha256: str
    route_authority_sha256: str
    landing_sha256: str
    persistence_receipt_sha256: str
    staging_schema_sha256: str
    staging_row_count: int
    staging_row_inventory_sha256: str
    member_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_cumulative_conditional_staging_evidence_member_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("conditional staging evidence member construction is private")
        if type(self.staging_key) is not str or _STAGING_KEY_RE.fullmatch(self.staging_key) is None:
            _fail("conditional staging key is invalid")
        expected_kind = _CONDITIONAL_KIND_BY_STAGING_KEY.get(self.staging_key)
        if self.conditional_kind != expected_kind:
            _fail("conditional staging kind differs from its exact staging key")
        if type(self.source_member_role) is not str or self.source_member_role not in {
            "discovery_seed",
            "full_extraction_executable",
            "live_snapshot",
            "successor_delta",
        }:
            _fail("conditional staging source role is invalid")
        allowed_roles = (
            {"live_snapshot", "successor_delta"}
            if self.conditional_kind == "live_complete_node_tree"
            else {"discovery_seed", "full_extraction_executable", "successor_delta"}
        )
        if self.source_member_role not in allowed_roles:
            _fail("conditional staging source role is incompatible with its conditional kind")
        _safe_route(self.route_id, label="conditional route_id")
        for label in (
            "source_member_sha256",
            "source_terminal_locator_sha256",
            "route_admission_sha256",
            "provider_authority_sha256",
            "route_authority_sha256",
            "landing_sha256",
            "persistence_receipt_sha256",
            "staging_schema_sha256",
            "staging_row_inventory_sha256",
        ):
            _sha256(getattr(self, label), label=label)
        _count(self.staging_row_count, label="staging_row_count", positive=True)
        if self.member_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("conditional staging evidence member digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "conditional_kind": self.conditional_kind,
            "landing_sha256": self.landing_sha256,
            "persistence_receipt_sha256": self.persistence_receipt_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "route_admission_sha256": self.route_admission_sha256,
            "route_authority_sha256": self.route_authority_sha256,
            "route_id": self.route_id,
            "source_member_role": self.source_member_role,
            "source_member_sha256": self.source_member_sha256,
            "source_terminal_locator_sha256": self.source_terminal_locator_sha256,
            "staging_key": self.staging_key,
            "staging_row_count": self.staging_row_count,
            "staging_row_inventory_sha256": self.staging_row_inventory_sha256,
            "staging_schema_sha256": self.staging_schema_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "member_sha256": self.member_sha256}

    def canonical_bytes(self) -> bytes:
        if type(self) is not CumulativeConditionalStagingEvidenceMemberV1:
            _fail("conditional staging member serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="conditional staging evidence member")

    @classmethod
    def _seal(cls, **values: object) -> Self:
        if cls is not CumulativeConditionalStagingEvidenceMemberV1:
            _fail("conditional staging member requires its exact DTO class")
        identity = {"schema_version": 1, "kind": cls.kind, **values}
        return cls(
            **values,  # ty: ignore[invalid-argument-type]
            member_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not CumulativeConditionalStagingEvidenceMemberV1:
            _fail("conditional staging member requires its exact DTO class")
        payload = _mapping(value, label="conditional staging evidence member")
        fields = frozenset(
            {
                "conditional_kind",
                "landing_sha256",
                "member_sha256",
                "persistence_receipt_sha256",
                "provider_authority_sha256",
                "route_admission_sha256",
                "route_authority_sha256",
                "route_id",
                "source_member_role",
                "source_member_sha256",
                "source_terminal_locator_sha256",
                "staging_key",
                "staging_row_count",
                "staging_row_inventory_sha256",
                "staging_schema_sha256",
            }
        )
        _exact_keys(
            payload,
            expected=fields | {"schema_version", "kind"},
            label="conditional staging evidence member",
        )
        _schema(payload, kind=cls.kind, label="conditional staging evidence member")
        return cls(
            **{  # ty: ignore[invalid-argument-type]
                name: payload[name] for name in fields
            },
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not CumulativeConditionalStagingEvidenceMemberV1:
            _fail("conditional staging member requires its exact DTO class")
        candidate = cls._from_payload(_decode(raw, label="conditional staging evidence member"))
        if raw != candidate.canonical_bytes():
            _fail("conditional staging evidence member bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class CumulativeConditionalStagingEvidenceInventoryV1:
    """Scalar conditional baseline/prior/current/addition projections."""

    operation_context: _OperationContextV1
    baseline_kind: OperationBaselineKind
    prior_operation_data_evidence_sha256: str | None
    prior_conditional_staging_authority_sha256: str | None
    baseline_member_count: int
    baseline_member_inventory_sha256: str
    prior_member_count: int
    prior_member_inventory_sha256: str
    current_member_count: int
    current_member_inventory_sha256: str
    added_member_count: int
    added_member_inventory_sha256: str
    staging_key_count: int
    staging_key_inventory_sha256: str
    typed_source_member_count: int
    typed_source_member_inventory_sha256: str
    conditional_staging_authority_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_cumulative_conditional_staging_evidence_inventory_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("cumulative conditional staging inventory construction is private")
        if type(self.operation_context) is not _OperationContextV1:
            _fail("conditional staging inventory lacks its exact operation context")
        if type(self.baseline_kind) is not str or self.baseline_kind not in {
            "initial_full_rebuild",
            "prior_assured_snapshot",
        }:
            _fail("conditional staging baseline kind is invalid")
        prior_evidence = _optional_sha256(
            self.prior_operation_data_evidence_sha256,
            label="prior_operation_data_evidence_sha256",
        )
        prior_authority = _optional_sha256(
            self.prior_conditional_staging_authority_sha256,
            label="prior_conditional_staging_authority_sha256",
        )
        if self.baseline_kind == "initial_full_rebuild":
            if (
                prior_evidence is not None
                or prior_authority is not None
                or self.baseline_member_count != 0
                or self.prior_member_count != 0
            ):
                _fail("initial conditional baseline must have exact empty prior projections")
        elif prior_evidence is None or prior_authority is None:
            _fail("prior-assured conditional baseline lacks its prior evidence anchors")

        for label in (
            "baseline_member_count",
            "prior_member_count",
            "current_member_count",
            "added_member_count",
            "staging_key_count",
            "typed_source_member_count",
        ):
            _count(getattr(self, label), label=label)
        for label in (
            "baseline_member_inventory_sha256",
            "prior_member_inventory_sha256",
            "current_member_inventory_sha256",
            "added_member_inventory_sha256",
            "staging_key_inventory_sha256",
            "typed_source_member_inventory_sha256",
        ):
            _sha256(getattr(self, label), label=label)
        for count, root, domain, label in (
            (
                self.baseline_member_count,
                self.baseline_member_inventory_sha256,
                _CONDITIONAL_MEMBER_DOMAIN,
                "conditional baseline inventory",
            ),
            (
                self.prior_member_count,
                self.prior_member_inventory_sha256,
                _CONDITIONAL_MEMBER_DOMAIN,
                "conditional prior inventory",
            ),
            (
                self.current_member_count,
                self.current_member_inventory_sha256,
                _CONDITIONAL_MEMBER_DOMAIN,
                "conditional current inventory",
            ),
            (
                self.added_member_count,
                self.added_member_inventory_sha256,
                _CONDITIONAL_ADDED_DOMAIN,
                "conditional addition inventory",
            ),
            (
                self.staging_key_count,
                self.staging_key_inventory_sha256,
                _CONDITIONAL_STAGING_KEY_DOMAIN,
                "conditional staging-key inventory",
            ),
            (
                self.typed_source_member_count,
                self.typed_source_member_inventory_sha256,
                _CONDITIONAL_TYPED_SOURCE_DOMAIN,
                "conditional typed-source inventory",
            ),
        ):
            _require_empty_root(count=count, root=root, domain=domain, label=label)
        if self.baseline_member_count > self.prior_member_count:
            _fail("conditional baseline count exceeds its prior projection")
        if self.current_member_count != self.prior_member_count + self.added_member_count:
            _fail("conditional prior/current/addition count algebra differs")
        if self.typed_source_member_count != self.current_member_count:
            _fail("conditional current members lack exact typed-source projections")
        if self.staging_key_count > len(_CONDITIONAL_KIND_BY_STAGING_KEY):
            _fail("conditional staging-key count exceeds the fixed staging-key universe")
        if (self.current_member_count == 0) != (self.staging_key_count == 0):
            _fail("conditional staging-key presence differs from member presence")
        if self.conditional_staging_authority_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("conditional staging authority digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "added_member_count": self.added_member_count,
            "added_member_inventory_sha256": self.added_member_inventory_sha256,
            "baseline_kind": self.baseline_kind,
            "baseline_member_count": self.baseline_member_count,
            "baseline_member_inventory_sha256": self.baseline_member_inventory_sha256,
            "current_member_count": self.current_member_count,
            "current_member_inventory_sha256": self.current_member_inventory_sha256,
            "operation_context": self.operation_context.to_dict(),
            "prior_conditional_staging_authority_sha256": (
                self.prior_conditional_staging_authority_sha256
            ),
            "prior_member_count": self.prior_member_count,
            "prior_member_inventory_sha256": self.prior_member_inventory_sha256,
            "prior_operation_data_evidence_sha256": (self.prior_operation_data_evidence_sha256),
            "staging_key_count": self.staging_key_count,
            "staging_key_inventory_sha256": self.staging_key_inventory_sha256,
            "typed_source_member_count": self.typed_source_member_count,
            "typed_source_member_inventory_sha256": (self.typed_source_member_inventory_sha256),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "conditional_staging_authority_sha256": (self.conditional_staging_authority_sha256),
        }

    def canonical_bytes(self) -> bytes:
        if type(self) is not CumulativeConditionalStagingEvidenceInventoryV1:
            _fail("conditional staging inventory serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="cumulative conditional staging inventory")

    @classmethod
    def _seal(cls, **values: object) -> Self:
        if cls is not CumulativeConditionalStagingEvidenceInventoryV1:
            _fail("conditional staging inventory requires its exact DTO class")
        identity = cls._identity_from_values(values)
        return cls(
            **values,  # ty: ignore[invalid-argument-type]
            conditional_staging_authority_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _identity_from_values(cls, values: Mapping[str, object]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": cls.kind,
            "added_member_count": values["added_member_count"],
            "added_member_inventory_sha256": values["added_member_inventory_sha256"],
            "baseline_kind": values["baseline_kind"],
            "baseline_member_count": values["baseline_member_count"],
            "baseline_member_inventory_sha256": values["baseline_member_inventory_sha256"],
            "current_member_count": values["current_member_count"],
            "current_member_inventory_sha256": values["current_member_inventory_sha256"],
            "operation_context": cast("_OperationContextV1", values["operation_context"]).to_dict(),
            "prior_conditional_staging_authority_sha256": values[
                "prior_conditional_staging_authority_sha256"
            ],
            "prior_member_count": values["prior_member_count"],
            "prior_member_inventory_sha256": values["prior_member_inventory_sha256"],
            "prior_operation_data_evidence_sha256": values["prior_operation_data_evidence_sha256"],
            "staging_key_count": values["staging_key_count"],
            "staging_key_inventory_sha256": values["staging_key_inventory_sha256"],
            "typed_source_member_count": values["typed_source_member_count"],
            "typed_source_member_inventory_sha256": values["typed_source_member_inventory_sha256"],
        }

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not CumulativeConditionalStagingEvidenceInventoryV1:
            _fail("conditional staging inventory requires its exact DTO class")
        payload = _mapping(value, label="cumulative conditional staging inventory")
        fields = frozenset(
            {
                "added_member_count",
                "added_member_inventory_sha256",
                "baseline_kind",
                "baseline_member_count",
                "baseline_member_inventory_sha256",
                "conditional_staging_authority_sha256",
                "current_member_count",
                "current_member_inventory_sha256",
                "operation_context",
                "prior_conditional_staging_authority_sha256",
                "prior_member_count",
                "prior_member_inventory_sha256",
                "prior_operation_data_evidence_sha256",
                "staging_key_count",
                "staging_key_inventory_sha256",
                "typed_source_member_count",
                "typed_source_member_inventory_sha256",
            }
        )
        _exact_keys(
            payload,
            expected=fields | {"schema_version", "kind"},
            label="cumulative conditional staging inventory",
        )
        _schema(payload, kind=cls.kind, label="cumulative conditional staging inventory")
        values = {name: payload[name] for name in fields if name != "operation_context"}
        return cls(
            operation_context=_context_from_payload(
                payload["operation_context"], label="conditional staging operation context"
            ),
            **values,  # ty: ignore[invalid-argument-type]
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not CumulativeConditionalStagingEvidenceInventoryV1:
            _fail("conditional staging inventory requires its exact DTO class")
        candidate = cls._from_payload(
            _decode(raw, label="cumulative conditional staging inventory")
        )
        if raw != candidate.canonical_bytes():
            _fail("cumulative conditional staging inventory bytes differ from exact replay")
        return cast("Self", candidate)


@dataclass(frozen=True, slots=True)
class OperationDataEvidenceV1:
    """Non-admitting same-snapshot Raw/W2/conditional PRECOMMIT evidence."""

    operation_context: _OperationContextV1
    raw_snapshot: VerifiedOperationRawSnapshotV1
    raw_snapshot_sha256: str
    w2_database_authority: W2DatabaseAuthorityReceiptV1
    w2_database_authority_sha256: str
    conditional_staging_inventory: CumulativeConditionalStagingEvidenceInventoryV1
    conditional_staging_authority_sha256: str
    operation_data_evidence_sha256: str
    _token: InitVar[object] = None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_operation_data_evidence_v1"

    def __post_init__(self, _token: object) -> None:
        if _token is not _SEAL_TOKEN:
            _fail("operation data evidence construction is private")
        if (
            type(self.operation_context) is not _OperationContextV1
            or type(self.raw_snapshot) is not VerifiedOperationRawSnapshotV1
            or type(self.w2_database_authority) is not W2DatabaseAuthorityReceiptV1
            or type(self.conditional_staging_inventory)
            is not CumulativeConditionalStagingEvidenceInventoryV1
        ):
            _fail("operation data evidence components must be exact typed DTOs")
        if not (
            self.raw_snapshot.operation_context
            == self.w2_database_authority.operation_context
            == self.conditional_staging_inventory.operation_context
            == self.operation_context
        ):
            _fail("operation data evidence components cross operation or snapshot")
        denominator = self.raw_snapshot.denominator
        if self.raw_snapshot.operation_kind == "full_extraction":
            if type(denominator) is not FullExtractionRawOperationDenominatorV1:
                _fail("full-extraction evidence has a foreign Raw denominator")
            if (
                self.w2_database_authority.w2_baseline_kind != "initial_full_rebuild"
                or self.conditional_staging_inventory.baseline_kind != "initial_full_rebuild"
            ):
                _fail("full-extraction operation data evidence has a prior baseline")
        elif self.raw_snapshot.operation_kind == "successor":
            if type(denominator) is not SuccessorRawOperationDenominatorV1:
                _fail("successor evidence has a foreign Raw denominator")
            prior = denominator.prior_operation_data_evidence_sha256
            if (
                self.w2_database_authority.w2_baseline_kind != "prior_assured_snapshot"
                or self.conditional_staging_inventory.baseline_kind != "prior_assured_snapshot"
                or self.w2_database_authority.prior_operation_data_evidence_sha256 != prior
                or self.conditional_staging_inventory.prior_operation_data_evidence_sha256 != prior
            ):
                _fail("successor operation data evidence prior-E anchors differ")
        else:
            _fail("operation data evidence Raw operation kind is invalid")
        if (
            self.raw_snapshot_sha256 != self.raw_snapshot.raw_snapshot_sha256
            or self.w2_database_authority_sha256
            != self.w2_database_authority.w2_database_authority_sha256
            or self.conditional_staging_authority_sha256
            != self.conditional_staging_inventory.conditional_staging_authority_sha256
        ):
            _fail("operation data evidence component root projection differs")
        if self.operation_data_evidence_sha256 != _digest(self.kind, self.identity_payload()):
            _fail("operation data evidence digest differs")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "conditional_staging_authority_sha256": (self.conditional_staging_authority_sha256),
            "conditional_staging_inventory": self.conditional_staging_inventory.to_dict(),
            "operation_context": self.operation_context.to_dict(),
            "raw_snapshot": self.raw_snapshot.to_dict(),
            "raw_snapshot_sha256": self.raw_snapshot_sha256,
            "w2_database_authority": self.w2_database_authority.to_dict(),
            "w2_database_authority_sha256": self.w2_database_authority_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "operation_data_evidence_sha256": self.operation_data_evidence_sha256,
        }

    def canonical_bytes(self) -> bytes:
        if type(self) is not OperationDataEvidenceV1:
            _fail("operation data evidence serialization requires its exact DTO class")
        return _canonical_bytes(self.to_dict(), label="operation data evidence")

    @classmethod
    def _seal(
        cls,
        *,
        raw_snapshot: VerifiedOperationRawSnapshotV1,
        w2_database_authority: W2DatabaseAuthorityReceiptV1,
        conditional_staging_inventory: CumulativeConditionalStagingEvidenceInventoryV1,
    ) -> Self:
        if cls is not OperationDataEvidenceV1:
            _fail("operation data evidence requires its exact DTO class")
        if type(raw_snapshot) is not VerifiedOperationRawSnapshotV1:
            _fail("operation data evidence requires one exact Raw snapshot")
        values: dict[str, object] = {
            "conditional_staging_authority_sha256": (
                conditional_staging_inventory.conditional_staging_authority_sha256
            ),
            "conditional_staging_inventory": conditional_staging_inventory,
            "operation_context": raw_snapshot.operation_context,
            "raw_snapshot": raw_snapshot,
            "raw_snapshot_sha256": raw_snapshot.raw_snapshot_sha256,
            "w2_database_authority": w2_database_authority,
            "w2_database_authority_sha256": (w2_database_authority.w2_database_authority_sha256),
        }
        identity = cls._identity_from_values(values)
        return cls(
            operation_context=raw_snapshot.operation_context,
            raw_snapshot=raw_snapshot,
            raw_snapshot_sha256=raw_snapshot.raw_snapshot_sha256,
            w2_database_authority=w2_database_authority,
            w2_database_authority_sha256=(w2_database_authority.w2_database_authority_sha256),
            conditional_staging_inventory=conditional_staging_inventory,
            conditional_staging_authority_sha256=(
                conditional_staging_inventory.conditional_staging_authority_sha256
            ),
            operation_data_evidence_sha256=_digest(cls.kind, identity),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def _identity_from_values(cls, values: Mapping[str, object]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": cls.kind,
            "conditional_staging_authority_sha256": values["conditional_staging_authority_sha256"],
            "conditional_staging_inventory": cast(
                "CumulativeConditionalStagingEvidenceInventoryV1",
                values["conditional_staging_inventory"],
            ).to_dict(),
            "operation_context": cast("_OperationContextV1", values["operation_context"]).to_dict(),
            "raw_snapshot": cast(
                "VerifiedOperationRawSnapshotV1", values["raw_snapshot"]
            ).to_dict(),
            "raw_snapshot_sha256": values["raw_snapshot_sha256"],
            "w2_database_authority": cast(
                "W2DatabaseAuthorityReceiptV1", values["w2_database_authority"]
            ).to_dict(),
            "w2_database_authority_sha256": values["w2_database_authority_sha256"],
        }

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        if cls is not OperationDataEvidenceV1:
            _fail("operation data evidence requires its exact DTO class")
        payload = _mapping(value, label="operation data evidence")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "conditional_staging_authority_sha256",
                    "conditional_staging_inventory",
                    "operation_context",
                    "operation_data_evidence_sha256",
                    "raw_snapshot",
                    "raw_snapshot_sha256",
                    "w2_database_authority",
                    "w2_database_authority_sha256",
                }
            ),
            label="operation data evidence",
        )
        _schema(payload, kind=cls.kind, label="operation data evidence")
        return cls(
            operation_context=_context_from_payload(
                payload["operation_context"], label="operation data evidence context"
            ),
            raw_snapshot=VerifiedOperationRawSnapshotV1._from_payload(payload["raw_snapshot"]),
            raw_snapshot_sha256=cast("str", payload["raw_snapshot_sha256"]),
            w2_database_authority=W2DatabaseAuthorityReceiptV1._from_payload(
                payload["w2_database_authority"]
            ),
            w2_database_authority_sha256=cast("str", payload["w2_database_authority_sha256"]),
            conditional_staging_inventory=(
                CumulativeConditionalStagingEvidenceInventoryV1._from_payload(
                    payload["conditional_staging_inventory"]
                )
            ),
            conditional_staging_authority_sha256=cast(
                "str", payload["conditional_staging_authority_sha256"]
            ),
            operation_data_evidence_sha256=cast("str", payload["operation_data_evidence_sha256"]),
            _token=_SEAL_TOKEN,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not OperationDataEvidenceV1:
            _fail("operation data evidence requires its exact DTO class")
        try:
            candidate = cls._from_payload(_decode(raw, label="operation data evidence"))
            canonical = candidate.canonical_bytes()
        except (MemoryError, RecursionError) as exc:
            raise OperationDataAuthorityError(
                "operation data evidence replay exceeded resource bounds"
            ) from exc
        if raw != canonical:
            _fail("operation data evidence bytes differ from exact replay")
        return cast("Self", candidate)
