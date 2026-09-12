from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar, Self, cast

from nbadb.orchestrate.checkpoint_contract import (
    CHECKPOINT_CONTRACT_SCHEMA_VERSION,
    CheckpointContractError,
    CheckpointState,
    CheckpointTransaction,
    CheckpointW2AuthorityIdentity,
)

__all__ = [
    "TERMINAL_CATCHUP_SCHEMA_VERSION",
    "CatchupComponentInventoryV1",
    "CoalescedTailDemandV1",
    "CommittedParentAuthorityV1",
    "FreshBaselineAuthorityV1",
    "FreshnessStatus",
    "GenerationArtifactReceiptV1",
    "GenerationBuildV1",
    "GenerationKind",
    "GenerationState",
    "ObservationCallV1",
    "ObservationWindowV1",
    "TailFreshnessReceiptV1",
    "TailGenerationIdentityV1",
    "TailGenerationTransactionV1",
    "TailTriggerDemandV1",
    "TerminalCatchupContractError",
    "TerminalCatchupIdentityV1",
    "TerminalCatchupTransactionV1",
    "TerminalCatchupTransitionError",
    "TriggerKind",
    "canonical_json_bytes",
]

TERMINAL_CATCHUP_SCHEMA_VERSION = 2
_CLOCK_CONTRACT = "utc-rfc3339-seconds-v1"


class TerminalCatchupContractError(ValueError):
    """Raised when catch-up or tail authority is incomplete or inconsistent."""


class TerminalCatchupTransitionError(TerminalCatchupContractError):
    """Raised when a generation attempts an illegal transaction transition."""


class GenerationKind(StrEnum):
    TERMINAL_CATCHUP = "terminal_catchup"
    TAIL = "tail"


class GenerationState(StrEnum):
    CANDIDATE = "candidate"
    BUILT = "built"
    UPLOADED_VERIFIED = "uploaded_verified"
    COMMITTED = "committed"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    NOT_FRESH = "not_fresh"
    CAPACITY_BLOCKED = "capacity_blocked"


class TriggerKind(StrEnum):
    DAILY = "daily"
    EVENT_DRIVEN = "event_driven"
    MANUAL = "manual"
    OPPORTUNISTIC = "opportunistic"


def canonical_json_bytes(value: object) -> bytes:
    """Return the deterministic JSON representation used by all identities."""
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TerminalCatchupContractError("value is not canonical JSON") from exc


def _reject_constant(value: str) -> None:
    raise TerminalCatchupContractError(f"non-finite JSON number is forbidden: {value}")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TerminalCatchupContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_canonical_json(encoded: bytes) -> Mapping[str, object]:
    if not isinstance(encoded, bytes) or not encoded:
        raise TerminalCatchupContractError("transaction bytes must be nonempty bytes")
    try:
        decoded = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerminalCatchupContractError("transaction bytes are not valid UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise TerminalCatchupContractError("transaction JSON must be an object")
    if canonical_json_bytes(decoded) != encoded:
        raise TerminalCatchupContractError("transaction JSON is not canonically encoded")
    return cast("Mapping[str, object]", decoded)


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if unexpected:
        details.append("unexpected=" + ",".join(unexpected))
    raise TerminalCatchupContractError(f"{label} fields are invalid: {'; '.join(details)}")


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TerminalCatchupContractError(f"{field_name} must be a string-keyed object")
    return cast("Mapping[str, object]", value)


def _require_exact_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise TerminalCatchupContractError(f"{field_name} must be a nonempty exact string")
    return value


def _require_sha256(value: object, *, field_name: str, prefixed: bool = False) -> str:
    raw = _require_exact_text(value, field_name=field_name)
    prefix = "sha256:" if prefixed else ""
    raw_hex = raw.removeprefix(prefix) if prefix else raw
    if prefix and not raw.startswith(prefix):
        raise TerminalCatchupContractError(f"{field_name} must be a lowercase SHA-256")
    if len(raw_hex) != 64 or any(character not in "0123456789abcdef" for character in raw_hex):
        raise TerminalCatchupContractError(f"{field_name} must be a lowercase SHA-256")
    return raw


def _require_source_sha(value: object, *, field_name: str = "source_sha") -> str:
    raw = _require_exact_text(value, field_name=field_name)
    if len(raw) != 40 or any(character not in "0123456789abcdef" for character in raw):
        raise TerminalCatchupContractError(
            f"{field_name} must be a 40-character lowercase commit SHA"
        )
    return raw


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise TerminalCatchupContractError(f"{field_name} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise TerminalCatchupContractError(f"{field_name} must be a nonnegative integer")
    return value


def _require_w2_authority(
    value: object,
    *,
    field_name: str,
) -> CheckpointW2AuthorityIdentity:
    if type(value) is not CheckpointW2AuthorityIdentity:
        raise TerminalCatchupContractError(
            f"{field_name} must be an exact CheckpointW2AuthorityIdentity"
        )
    authority = value
    if authority.database_authority_closed is not True:
        raise TerminalCatchupContractError(f"{field_name} must be closed")
    return authority


def _decode_w2_authority(
    value: object,
    *,
    field_name: str,
) -> CheckpointW2AuthorityIdentity:
    try:
        return CheckpointW2AuthorityIdentity.from_dict(
            _require_mapping(value, field_name=field_name)
        )
    except CheckpointContractError as exc:
        raise TerminalCatchupContractError(
            f"{field_name} is not an exact closed W2 authority"
        ) from exc


def _decode_checkpoint_transaction(value: object) -> CheckpointTransaction:
    try:
        return CheckpointTransaction.from_dict(
            _require_mapping(value, field_name="checkpoint_transaction")
        )
    except CheckpointContractError as exc:
        raise TerminalCatchupContractError(
            "checkpoint_transaction is not an exact schema-v2 committed checkpoint"
        ) from exc


def _require_exact_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise TerminalCatchupContractError(f"{field_name} must be a boolean")
    return value


def _parse_utc_timestamp(value: object, *, field_name: str) -> datetime:
    raw = _require_exact_text(value, field_name=field_name)
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise TerminalCatchupContractError(
            f"{field_name} must be canonical UTC YYYY-MM-DDTHH:MM:SSZ"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != raw:
        raise TerminalCatchupContractError(
            f"{field_name} must be canonical UTC YYYY-MM-DDTHH:MM:SSZ"
        )
    return parsed


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_sha256(value, field_name=field_name)


@dataclass(frozen=True, slots=True, order=True)
class ObservationCallV1:
    """Public-safe identity for one accepted provider observation."""

    call_id: str
    request_identity_sha256: str
    parser_input_body_sha256: str | None
    bodyless_receipt_sha256: str | None
    field_temporal_receipt_sha256: str
    observation_started_at: str
    observation_ended_at: str

    def __post_init__(self) -> None:
        _require_exact_text(self.call_id, field_name="call_id")
        _require_sha256(self.request_identity_sha256, field_name="request_identity_sha256")
        parser_body = _optional_sha256(
            self.parser_input_body_sha256,
            field_name="parser_input_body_sha256",
        )
        bodyless = _optional_sha256(
            self.bodyless_receipt_sha256,
            field_name="bodyless_receipt_sha256",
        )
        if (parser_body is None) == (bodyless is None):
            raise TerminalCatchupContractError(
                "observation call requires exactly one parser body or bodyless receipt"
            )
        _require_sha256(
            self.field_temporal_receipt_sha256,
            field_name="field_temporal_receipt_sha256",
        )
        started = _parse_utc_timestamp(
            self.observation_started_at,
            field_name="observation_started_at",
        )
        ended = _parse_utc_timestamp(
            self.observation_ended_at,
            field_name="observation_ended_at",
        )
        if started > ended:
            raise TerminalCatchupContractError("observation start must not follow its end")

    def to_dict(self) -> dict[str, object]:
        return {
            "call_id": self.call_id,
            "request_identity_sha256": self.request_identity_sha256,
            "parser_input_body_sha256": self.parser_input_body_sha256,
            "bodyless_receipt_sha256": self.bodyless_receipt_sha256,
            "field_temporal_receipt_sha256": self.field_temporal_receipt_sha256,
            "observation_started_at": self.observation_started_at,
            "observation_ended_at": self.observation_ended_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "call_id",
                    "request_identity_sha256",
                    "parser_input_body_sha256",
                    "bodyless_receipt_sha256",
                    "field_temporal_receipt_sha256",
                    "observation_started_at",
                    "observation_ended_at",
                }
            ),
            label="observation call",
        )
        return cls(
            call_id=cast("str", payload["call_id"]),
            request_identity_sha256=cast("str", payload["request_identity_sha256"]),
            parser_input_body_sha256=cast("str | None", payload["parser_input_body_sha256"]),
            bodyless_receipt_sha256=cast("str | None", payload["bodyless_receipt_sha256"]),
            field_temporal_receipt_sha256=cast("str", payload["field_temporal_receipt_sha256"]),
            observation_started_at=cast("str", payload["observation_started_at"]),
            observation_ended_at=cast("str", payload["observation_ended_at"]),
        )


@dataclass(frozen=True, slots=True)
class ObservationWindowV1:
    """Exact, sealed call inventory and its public body/field identities."""

    clock_contract: str
    calls: tuple[ObservationCallV1, ...]
    minimum_start: str
    maximum_accepted_end: str
    seal_at: str
    call_inventory_sha256: str = ""
    parser_body_inventory_sha256: str = ""
    bodyless_inventory_sha256: str = ""
    field_temporal_inventory_sha256: str = ""
    canonical_request_inventory_sha256: str = ""

    def __post_init__(self) -> None:
        if self.clock_contract != _CLOCK_CONTRACT:
            raise TerminalCatchupContractError("unsupported observation clock contract")
        if not self.calls or any(not isinstance(call, ObservationCallV1) for call in self.calls):
            raise TerminalCatchupContractError(
                "observation window requires ObservationCallV1 values"
            )
        normalized = tuple(sorted(self.calls))
        if normalized != self.calls:
            raise TerminalCatchupContractError("observation calls must be in canonical order")
        call_ids = [call.call_id for call in self.calls]
        if len(call_ids) != len(set(call_ids)):
            raise TerminalCatchupContractError("observation call IDs must be unique")

        starts = [
            _parse_utc_timestamp(call.observation_started_at, field_name="observation_started_at")
            for call in self.calls
        ]
        ends = [
            _parse_utc_timestamp(call.observation_ended_at, field_name="observation_ended_at")
            for call in self.calls
        ]
        minimum_start = _parse_utc_timestamp(self.minimum_start, field_name="minimum_start")
        maximum_end = _parse_utc_timestamp(
            self.maximum_accepted_end,
            field_name="maximum_accepted_end",
        )
        seal = _parse_utc_timestamp(self.seal_at, field_name="seal_at")
        if minimum_start != min(starts) or maximum_end != max(ends):
            raise TerminalCatchupContractError("observation window bounds do not match its calls")
        if any(end > seal for end in ends):
            raise TerminalCatchupContractError("post-seal observation is forbidden")
        expected = self._expected_digests()
        supplied = {
            "call_inventory_sha256": self.call_inventory_sha256,
            "parser_body_inventory_sha256": self.parser_body_inventory_sha256,
            "bodyless_inventory_sha256": self.bodyless_inventory_sha256,
            "field_temporal_inventory_sha256": self.field_temporal_inventory_sha256,
            "canonical_request_inventory_sha256": self.canonical_request_inventory_sha256,
        }
        for field_name, digest in expected.items():
            supplied_digest = supplied[field_name]
            if supplied_digest and supplied_digest != digest:
                raise TerminalCatchupContractError(
                    f"{field_name} does not match the observation inventory"
                )
            object.__setattr__(self, field_name, digest)

    @classmethod
    def sealed(cls, *, calls: Sequence[ObservationCallV1], seal_at: str) -> Self:
        normalized = tuple(sorted(calls))
        if not normalized:
            raise TerminalCatchupContractError("cannot seal an empty observation window")
        starts = [
            _parse_utc_timestamp(call.observation_started_at, field_name="observation_started_at")
            for call in normalized
        ]
        ends = [
            _parse_utc_timestamp(call.observation_ended_at, field_name="observation_ended_at")
            for call in normalized
        ]
        return cls(
            clock_contract=_CLOCK_CONTRACT,
            calls=normalized,
            minimum_start=min(starts).strftime("%Y-%m-%dT%H:%M:%SZ"),
            maximum_accepted_end=max(ends).strftime("%Y-%m-%dT%H:%M:%SZ"),
            seal_at=seal_at,
        )

    def _expected_digests(self) -> dict[str, str]:
        return {
            "call_inventory_sha256": _canonical_sha256([call.to_dict() for call in self.calls]),
            "parser_body_inventory_sha256": _canonical_sha256(
                [
                    {"call_id": call.call_id, "sha256": call.parser_input_body_sha256}
                    for call in self.calls
                    if call.parser_input_body_sha256 is not None
                ]
            ),
            "bodyless_inventory_sha256": _canonical_sha256(
                [
                    {"call_id": call.call_id, "sha256": call.bodyless_receipt_sha256}
                    for call in self.calls
                    if call.bodyless_receipt_sha256 is not None
                ]
            ),
            "field_temporal_inventory_sha256": _canonical_sha256(
                [
                    {
                        "call_id": call.call_id,
                        "sha256": call.field_temporal_receipt_sha256,
                    }
                    for call in self.calls
                ]
            ),
            "canonical_request_inventory_sha256": _canonical_sha256(
                [
                    {"call_id": call.call_id, "sha256": call.request_identity_sha256}
                    for call in self.calls
                ]
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "clock_contract": self.clock_contract,
            "calls": [call.to_dict() for call in self.calls],
            "minimum_start": self.minimum_start,
            "maximum_accepted_end": self.maximum_accepted_end,
            "seal_at": self.seal_at,
            "call_inventory_sha256": self.call_inventory_sha256,
            "parser_body_inventory_sha256": self.parser_body_inventory_sha256,
            "bodyless_inventory_sha256": self.bodyless_inventory_sha256,
            "field_temporal_inventory_sha256": self.field_temporal_inventory_sha256,
            "canonical_request_inventory_sha256": self.canonical_request_inventory_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "clock_contract",
                    "calls",
                    "minimum_start",
                    "maximum_accepted_end",
                    "seal_at",
                    "call_inventory_sha256",
                    "parser_body_inventory_sha256",
                    "bodyless_inventory_sha256",
                    "field_temporal_inventory_sha256",
                    "canonical_request_inventory_sha256",
                }
            ),
            label="observation window",
        )
        raw_calls = payload["calls"]
        if not isinstance(raw_calls, list):
            raise TerminalCatchupContractError("observation calls must be a list")
        return cls(
            clock_contract=cast("str", payload["clock_contract"]),
            calls=tuple(
                ObservationCallV1.from_dict(
                    _require_mapping(raw_call, field_name=f"observation call {index}")
                )
                for index, raw_call in enumerate(raw_calls)
            ),
            minimum_start=cast("str", payload["minimum_start"]),
            maximum_accepted_end=cast("str", payload["maximum_accepted_end"]),
            seal_at=cast("str", payload["seal_at"]),
            call_inventory_sha256=cast("str", payload["call_inventory_sha256"]),
            parser_body_inventory_sha256=cast("str", payload["parser_body_inventory_sha256"]),
            bodyless_inventory_sha256=cast("str", payload["bodyless_inventory_sha256"]),
            field_temporal_inventory_sha256=cast("str", payload["field_temporal_inventory_sha256"]),
            canonical_request_inventory_sha256=cast(
                "str", payload["canonical_request_inventory_sha256"]
            ),
        )


@dataclass(frozen=True, slots=True)
class FreshBaselineAuthorityV1:
    """Exact fresh attempt-one checkpoint authority; old state cannot satisfy it."""

    repository: str
    chain_id: str
    source_sha: str
    run_id: int
    run_attempt: int
    checkpoint_transaction: CheckpointTransaction
    checkpoint_generation: int
    checkpoint_state: GenerationState
    checkpoint_transaction_sha256: str
    checkpoint_artifact_id: int
    checkpoint_artifact_digest: str
    checkpoint_database_sha256: str
    checkpoint_report_sha256: str
    checkpoint_w2_authority: CheckpointW2AuthorityIdentity
    checkpoint_w2_authority_identity_sha256: str
    request_universe_generation_sha256: str
    fresh_empty_candidate: bool
    prior_state_reused: bool

    def __post_init__(self) -> None:
        _require_exact_text(self.repository, field_name="repository")
        _require_exact_text(self.chain_id, field_name="chain_id")
        _require_source_sha(self.source_sha)
        _require_positive_int(self.run_id, field_name="run_id")
        if _require_positive_int(self.run_attempt, field_name="run_attempt") != 1:
            raise TerminalCatchupContractError("fresh baseline authority requires attempt one")
        if type(self.checkpoint_transaction) is not CheckpointTransaction:
            raise TerminalCatchupContractError(
                "fresh baseline requires an exact CheckpointTransaction"
            )
        if (
            self.checkpoint_transaction.schema_version != CHECKPOINT_CONTRACT_SCHEMA_VERSION
            or self.checkpoint_transaction.state is not CheckpointState.COMMITTED
            or self.checkpoint_transaction.build is None
        ):
            raise TerminalCatchupContractError(
                "fresh baseline requires a committed schema-v2 checkpoint transaction"
            )
        _require_positive_int(self.checkpoint_generation, field_name="checkpoint_generation")
        if self.checkpoint_state is not GenerationState.COMMITTED:
            raise TerminalCatchupContractError(
                "fresh baseline authority requires a committed checkpoint"
            )
        _require_sha256(
            self.checkpoint_transaction_sha256,
            field_name="checkpoint_transaction_sha256",
        )
        _require_positive_int(self.checkpoint_artifact_id, field_name="checkpoint_artifact_id")
        _require_sha256(
            self.checkpoint_artifact_digest,
            field_name="checkpoint_artifact_digest",
            prefixed=True,
        )
        for field_name in (
            "checkpoint_database_sha256",
            "checkpoint_report_sha256",
            "request_universe_generation_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        checkpoint_w2_authority = _require_w2_authority(
            self.checkpoint_w2_authority,
            field_name="checkpoint_w2_authority",
        )
        _require_sha256(
            self.checkpoint_w2_authority_identity_sha256,
            field_name="checkpoint_w2_authority_identity_sha256",
        )
        if self.checkpoint_w2_authority_identity_sha256 != checkpoint_w2_authority.identity_sha256:
            raise TerminalCatchupContractError(
                "checkpoint W2 authority identity differs from its canonical receipt"
            )
        checkpoint_receipt = self.checkpoint_transaction.committed_receipt
        checkpoint_build = self.checkpoint_transaction.build
        checkpoint_identity = self.checkpoint_transaction.identity
        expected_checkpoint_bindings: tuple[tuple[str, object, object], ...] = (
            ("chain_id", self.chain_id, checkpoint_identity.chain_id),
            ("source_sha", self.source_sha, checkpoint_identity.source_sha),
            ("run_id", self.run_id, checkpoint_receipt.artifact_run_id),
            ("checkpoint_generation", self.checkpoint_generation, checkpoint_identity.generation),
            (
                "checkpoint_transaction_sha256",
                self.checkpoint_transaction_sha256,
                _canonical_sha256(self.checkpoint_transaction.to_dict()),
            ),
            ("checkpoint_artifact_id", self.checkpoint_artifact_id, checkpoint_receipt.artifact_id),
            (
                "checkpoint_artifact_digest",
                self.checkpoint_artifact_digest,
                checkpoint_receipt.artifact_digest,
            ),
            (
                "checkpoint_database_sha256",
                self.checkpoint_database_sha256,
                checkpoint_build.database_sha256,
            ),
            (
                "checkpoint_report_sha256",
                self.checkpoint_report_sha256,
                checkpoint_build.report_sha256,
            ),
            (
                "checkpoint_w2_authority",
                checkpoint_w2_authority,
                checkpoint_build.w2_authority,
            ),
            (
                "checkpoint_w2_authority_identity_sha256",
                self.checkpoint_w2_authority_identity_sha256,
                checkpoint_receipt.w2_authority_identity_sha256,
            ),
        )
        checkpoint_drift = [
            field_name
            for field_name, actual, expected in expected_checkpoint_bindings
            if actual != expected
        ]
        if checkpoint_drift:
            raise TerminalCatchupContractError(
                "fresh baseline drifts from its exact checkpoint transaction: "
                + ", ".join(checkpoint_drift)
            )
        if not _require_exact_bool(
            self.fresh_empty_candidate,
            field_name="fresh_empty_candidate",
        ):
            raise TerminalCatchupContractError("baseline must begin from a fresh empty candidate")
        if _require_exact_bool(self.prior_state_reused, field_name="prior_state_reused"):
            raise TerminalCatchupContractError(
                "prior checkpoint state cannot seed a fresh baseline"
            )

    @property
    def authority_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    @classmethod
    def from_committed_checkpoint(
        cls,
        *,
        repository: str,
        checkpoint: CheckpointTransaction,
        run_attempt: int,
        request_universe_generation_sha256: str,
    ) -> Self:
        """Create one fresh baseline from an exact committed schema-v2 checkpoint."""
        if type(checkpoint) is not CheckpointTransaction:
            raise TerminalCatchupContractError(
                "fresh baseline requires an exact CheckpointTransaction"
            )
        if checkpoint.schema_version != CHECKPOINT_CONTRACT_SCHEMA_VERSION:
            raise TerminalCatchupContractError(
                "fresh baseline requires checkpoint transaction schema version 3"
            )
        if checkpoint.state is not CheckpointState.COMMITTED:
            raise TerminalCatchupContractError("fresh baseline requires a committed checkpoint")
        if checkpoint.build is None:
            raise TerminalCatchupContractError("committed checkpoint lacks its build authority")
        receipt = checkpoint.committed_receipt
        w2_authority = _require_w2_authority(
            checkpoint.build.w2_authority,
            field_name="checkpoint_w2_authority",
        )
        if receipt.w2_authority_identity_sha256 != w2_authority.identity_sha256:
            raise TerminalCatchupContractError(
                "checkpoint artifact receipt has a foreign W2 authority identity"
            )
        return cls(
            repository=repository,
            chain_id=checkpoint.identity.chain_id,
            source_sha=checkpoint.identity.source_sha,
            run_id=receipt.artifact_run_id,
            run_attempt=run_attempt,
            checkpoint_transaction=checkpoint,
            checkpoint_generation=checkpoint.identity.generation,
            checkpoint_state=GenerationState.COMMITTED,
            checkpoint_transaction_sha256=_canonical_sha256(checkpoint.to_dict()),
            checkpoint_artifact_id=receipt.artifact_id,
            checkpoint_artifact_digest=receipt.artifact_digest,
            checkpoint_database_sha256=checkpoint.build.database_sha256,
            checkpoint_report_sha256=checkpoint.build.report_sha256,
            checkpoint_w2_authority=w2_authority,
            checkpoint_w2_authority_identity_sha256=w2_authority.identity_sha256,
            request_universe_generation_sha256=request_universe_generation_sha256,
            fresh_empty_candidate=True,
            prior_state_reused=False,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "repository": self.repository,
            "chain_id": self.chain_id,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "checkpoint_transaction": self.checkpoint_transaction.to_dict(),
            "checkpoint_generation": self.checkpoint_generation,
            "checkpoint_state": self.checkpoint_state.value,
            "checkpoint_transaction_sha256": self.checkpoint_transaction_sha256,
            "checkpoint_artifact_id": self.checkpoint_artifact_id,
            "checkpoint_artifact_digest": self.checkpoint_artifact_digest,
            "checkpoint_database_sha256": self.checkpoint_database_sha256,
            "checkpoint_report_sha256": self.checkpoint_report_sha256,
            "checkpoint_w2_authority": self.checkpoint_w2_authority.to_dict(),
            "checkpoint_w2_authority_identity_sha256": (
                self.checkpoint_w2_authority_identity_sha256
            ),
            "request_universe_generation_sha256": self.request_universe_generation_sha256,
            "fresh_empty_candidate": self.fresh_empty_candidate,
            "prior_state_reused": self.prior_state_reused,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "repository",
                    "chain_id",
                    "source_sha",
                    "run_id",
                    "run_attempt",
                    "checkpoint_transaction",
                    "checkpoint_generation",
                    "checkpoint_state",
                    "checkpoint_transaction_sha256",
                    "checkpoint_artifact_id",
                    "checkpoint_artifact_digest",
                    "checkpoint_database_sha256",
                    "checkpoint_report_sha256",
                    "checkpoint_w2_authority",
                    "checkpoint_w2_authority_identity_sha256",
                    "request_universe_generation_sha256",
                    "fresh_empty_candidate",
                    "prior_state_reused",
                }
            ),
            label="fresh baseline authority",
        )
        try:
            checkpoint_state = GenerationState(
                _require_exact_text(
                    payload["checkpoint_state"],
                    field_name="checkpoint_state",
                )
            )
        except ValueError as exc:
            raise TerminalCatchupContractError("unsupported checkpoint state") from exc
        return cls(
            repository=cast("str", payload["repository"]),
            chain_id=cast("str", payload["chain_id"]),
            source_sha=cast("str", payload["source_sha"]),
            run_id=cast("int", payload["run_id"]),
            run_attempt=cast("int", payload["run_attempt"]),
            checkpoint_transaction=_decode_checkpoint_transaction(
                payload["checkpoint_transaction"]
            ),
            checkpoint_generation=cast("int", payload["checkpoint_generation"]),
            checkpoint_state=checkpoint_state,
            checkpoint_transaction_sha256=cast("str", payload["checkpoint_transaction_sha256"]),
            checkpoint_artifact_id=cast("int", payload["checkpoint_artifact_id"]),
            checkpoint_artifact_digest=cast("str", payload["checkpoint_artifact_digest"]),
            checkpoint_database_sha256=cast("str", payload["checkpoint_database_sha256"]),
            checkpoint_report_sha256=cast("str", payload["checkpoint_report_sha256"]),
            checkpoint_w2_authority=_decode_w2_authority(
                payload["checkpoint_w2_authority"],
                field_name="checkpoint_w2_authority",
            ),
            checkpoint_w2_authority_identity_sha256=cast(
                "str",
                payload["checkpoint_w2_authority_identity_sha256"],
            ),
            request_universe_generation_sha256=cast(
                "str", payload["request_universe_generation_sha256"]
            ),
            fresh_empty_candidate=cast("bool", payload["fresh_empty_candidate"]),
            prior_state_reused=cast("bool", payload["prior_state_reused"]),
        )


@dataclass(frozen=True, slots=True)
class CatchupComponentInventoryV1:
    baseline_to_cutoff_sha256: str
    overlap_refresh_sha256: str
    hole_repair_sha256: str
    live_snapshot_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "baseline_to_cutoff_sha256",
            "overlap_refresh_sha256",
            "hole_repair_sha256",
            "live_snapshot_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)

    @property
    def inventory_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "baseline_to_cutoff_sha256": self.baseline_to_cutoff_sha256,
            "overlap_refresh_sha256": self.overlap_refresh_sha256,
            "hole_repair_sha256": self.hole_repair_sha256,
            "live_snapshot_sha256": self.live_snapshot_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "baseline_to_cutoff_sha256",
                    "overlap_refresh_sha256",
                    "hole_repair_sha256",
                    "live_snapshot_sha256",
                }
            ),
            label="catch-up component inventory",
        )
        return cls(
            baseline_to_cutoff_sha256=cast("str", payload["baseline_to_cutoff_sha256"]),
            overlap_refresh_sha256=cast("str", payload["overlap_refresh_sha256"]),
            hole_repair_sha256=cast("str", payload["hole_repair_sha256"]),
            live_snapshot_sha256=cast("str", payload["live_snapshot_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class TerminalCatchupIdentityV1:
    generation_id: str
    baseline_authority: FreshBaselineAuthorityV1
    source_sha: str
    semantic_diff_sha256: str
    request_universe_generation_sha256: str
    public_observation_inventory_sha256: str
    parser_body_inventory_sha256: str
    bodyless_inventory_sha256: str
    field_temporal_authority_sha256: str
    model_contract_sha256: str
    event_cutoff: str
    overlap_scope_sha256: str
    hole_repair_inventory_sha256: str
    live_snapshot_sha256: str
    observation_window: ObservationWindowV1
    components: CatchupComponentInventoryV1
    canonical_request_inventory_sha256: str
    w2_expected_call_count: int
    w2_expected_call_inventory_sha256: str

    def __post_init__(self) -> None:
        _require_exact_text(self.generation_id, field_name="generation_id")
        if not isinstance(self.baseline_authority, FreshBaselineAuthorityV1):
            raise TerminalCatchupContractError(
                "baseline_authority must be a FreshBaselineAuthorityV1"
            )
        _require_source_sha(self.source_sha)
        if self.source_sha != self.baseline_authority.source_sha:
            raise TerminalCatchupContractError("catch-up source drifts from its baseline")
        for field_name in (
            "semantic_diff_sha256",
            "request_universe_generation_sha256",
            "public_observation_inventory_sha256",
            "parser_body_inventory_sha256",
            "bodyless_inventory_sha256",
            "field_temporal_authority_sha256",
            "model_contract_sha256",
            "overlap_scope_sha256",
            "hole_repair_inventory_sha256",
            "live_snapshot_sha256",
            "canonical_request_inventory_sha256",
            "w2_expected_call_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_nonnegative_int(
            self.w2_expected_call_count,
            field_name="w2_expected_call_count",
        )
        baseline_w2 = self.baseline_authority.checkpoint_w2_authority
        if self.w2_expected_call_count < baseline_w2.expected_call_count:
            raise TerminalCatchupContractError(
                "catch-up W2 expected-call count cannot downgrade its checkpoint"
            )
        if (
            self.request_universe_generation_sha256
            != self.baseline_authority.request_universe_generation_sha256
        ):
            raise TerminalCatchupContractError("catch-up request universe drifts from baseline")
        cutoff = _parse_utc_timestamp(self.event_cutoff, field_name="event_cutoff")
        if not isinstance(self.observation_window, ObservationWindowV1):
            raise TerminalCatchupContractError("observation_window must be an ObservationWindowV1")
        if cutoff > _parse_utc_timestamp(self.observation_window.seal_at, field_name="seal_at"):
            raise TerminalCatchupContractError("catch-up event cutoff cannot follow its seal")
        if not isinstance(self.components, CatchupComponentInventoryV1):
            raise TerminalCatchupContractError("components must be a CatchupComponentInventoryV1")
        expected = (
            (
                "public_observation_inventory_sha256",
                self.public_observation_inventory_sha256,
                self.observation_window.call_inventory_sha256,
            ),
            (
                "parser_body_inventory_sha256",
                self.parser_body_inventory_sha256,
                self.observation_window.parser_body_inventory_sha256,
            ),
            (
                "bodyless_inventory_sha256",
                self.bodyless_inventory_sha256,
                self.observation_window.bodyless_inventory_sha256,
            ),
            (
                "field_temporal_authority_sha256",
                self.field_temporal_authority_sha256,
                self.observation_window.field_temporal_inventory_sha256,
            ),
            (
                "canonical_request_inventory_sha256",
                self.canonical_request_inventory_sha256,
                self.observation_window.canonical_request_inventory_sha256,
            ),
            (
                "hole_repair_inventory_sha256",
                self.hole_repair_inventory_sha256,
                self.components.hole_repair_sha256,
            ),
            (
                "live_snapshot_sha256",
                self.live_snapshot_sha256,
                self.components.live_snapshot_sha256,
            ),
        )
        mismatches = [field_name for field_name, actual, wanted in expected if actual != wanted]
        if mismatches:
            raise TerminalCatchupContractError(
                "catch-up authority inventory mismatch: " + ", ".join(mismatches)
            )

    @property
    def kind(self) -> GenerationKind:
        return GenerationKind.TERMINAL_CATCHUP

    @property
    def identity_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    @property
    def parent_authority_sha256(self) -> str:
        return self.baseline_authority.authority_sha256

    @property
    def component_inventory_sha256(self) -> str:
        return self.components.inventory_sha256

    def to_dict(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "baseline_authority": self.baseline_authority.to_dict(),
            "source_sha": self.source_sha,
            "semantic_diff_sha256": self.semantic_diff_sha256,
            "request_universe_generation_sha256": self.request_universe_generation_sha256,
            "public_observation_inventory_sha256": self.public_observation_inventory_sha256,
            "parser_body_inventory_sha256": self.parser_body_inventory_sha256,
            "bodyless_inventory_sha256": self.bodyless_inventory_sha256,
            "field_temporal_authority_sha256": self.field_temporal_authority_sha256,
            "model_contract_sha256": self.model_contract_sha256,
            "event_cutoff": self.event_cutoff,
            "overlap_scope_sha256": self.overlap_scope_sha256,
            "hole_repair_inventory_sha256": self.hole_repair_inventory_sha256,
            "live_snapshot_sha256": self.live_snapshot_sha256,
            "observation_window": self.observation_window.to_dict(),
            "components": self.components.to_dict(),
            "canonical_request_inventory_sha256": self.canonical_request_inventory_sha256,
            "w2_expected_call_count": self.w2_expected_call_count,
            "w2_expected_call_inventory_sha256": (self.w2_expected_call_inventory_sha256),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "generation_id",
                "baseline_authority",
                "source_sha",
                "semantic_diff_sha256",
                "request_universe_generation_sha256",
                "public_observation_inventory_sha256",
                "parser_body_inventory_sha256",
                "bodyless_inventory_sha256",
                "field_temporal_authority_sha256",
                "model_contract_sha256",
                "event_cutoff",
                "overlap_scope_sha256",
                "hole_repair_inventory_sha256",
                "live_snapshot_sha256",
                "observation_window",
                "components",
                "canonical_request_inventory_sha256",
                "w2_expected_call_count",
                "w2_expected_call_inventory_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="terminal catch-up identity")
        return cls(
            generation_id=cast("str", payload["generation_id"]),
            baseline_authority=FreshBaselineAuthorityV1.from_dict(
                _require_mapping(payload["baseline_authority"], field_name="baseline_authority")
            ),
            source_sha=cast("str", payload["source_sha"]),
            semantic_diff_sha256=cast("str", payload["semantic_diff_sha256"]),
            request_universe_generation_sha256=cast(
                "str", payload["request_universe_generation_sha256"]
            ),
            public_observation_inventory_sha256=cast(
                "str", payload["public_observation_inventory_sha256"]
            ),
            parser_body_inventory_sha256=cast("str", payload["parser_body_inventory_sha256"]),
            bodyless_inventory_sha256=cast("str", payload["bodyless_inventory_sha256"]),
            field_temporal_authority_sha256=cast("str", payload["field_temporal_authority_sha256"]),
            model_contract_sha256=cast("str", payload["model_contract_sha256"]),
            event_cutoff=cast("str", payload["event_cutoff"]),
            overlap_scope_sha256=cast("str", payload["overlap_scope_sha256"]),
            hole_repair_inventory_sha256=cast("str", payload["hole_repair_inventory_sha256"]),
            live_snapshot_sha256=cast("str", payload["live_snapshot_sha256"]),
            observation_window=ObservationWindowV1.from_dict(
                _require_mapping(payload["observation_window"], field_name="observation_window")
            ),
            components=CatchupComponentInventoryV1.from_dict(
                _require_mapping(payload["components"], field_name="components")
            ),
            canonical_request_inventory_sha256=cast(
                "str", payload["canonical_request_inventory_sha256"]
            ),
            w2_expected_call_count=cast("int", payload["w2_expected_call_count"]),
            w2_expected_call_inventory_sha256=cast(
                "str",
                payload["w2_expected_call_inventory_sha256"],
            ),
        )


@dataclass(frozen=True, slots=True)
class CommittedParentAuthorityV1:
    kind: GenerationKind
    state: GenerationState
    generation_id: str
    source_sha: str
    semantic_diff_sha256: str
    request_universe_generation_sha256: str
    event_cutoff: str
    observation_seal_at: str
    transaction_sha256: str
    artifact_id: int
    artifact_digest: str
    w2_authority: CheckpointW2AuthorityIdentity
    w2_authority_identity_sha256: str

    def __post_init__(self) -> None:
        if self.kind not in {GenerationKind.TERMINAL_CATCHUP, GenerationKind.TAIL}:
            raise TerminalCatchupContractError("parent kind must be committed catch-up or tail")
        if self.state is not GenerationState.COMMITTED:
            raise TerminalCatchupContractError("parent authority must be committed")
        _require_exact_text(self.generation_id, field_name="generation_id")
        _require_source_sha(self.source_sha)
        for field_name in (
            "semantic_diff_sha256",
            "request_universe_generation_sha256",
            "transaction_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        cutoff = _parse_utc_timestamp(self.event_cutoff, field_name="event_cutoff")
        seal = _parse_utc_timestamp(self.observation_seal_at, field_name="observation_seal_at")
        if cutoff > seal:
            raise TerminalCatchupContractError("parent event cutoff cannot follow its seal")
        _require_positive_int(self.artifact_id, field_name="artifact_id")
        _require_sha256(self.artifact_digest, field_name="artifact_digest", prefixed=True)
        w2_authority = _require_w2_authority(
            self.w2_authority,
            field_name="w2_authority",
        )
        _require_sha256(
            self.w2_authority_identity_sha256,
            field_name="w2_authority_identity_sha256",
        )
        if self.w2_authority_identity_sha256 != w2_authority.identity_sha256:
            raise TerminalCatchupContractError(
                "committed parent W2 authority identity differs from its canonical receipt"
            )

    @property
    def authority_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "state": self.state.value,
            "generation_id": self.generation_id,
            "source_sha": self.source_sha,
            "semantic_diff_sha256": self.semantic_diff_sha256,
            "request_universe_generation_sha256": self.request_universe_generation_sha256,
            "event_cutoff": self.event_cutoff,
            "observation_seal_at": self.observation_seal_at,
            "transaction_sha256": self.transaction_sha256,
            "artifact_id": self.artifact_id,
            "artifact_digest": self.artifact_digest,
            "w2_authority": self.w2_authority.to_dict(),
            "w2_authority_identity_sha256": self.w2_authority_identity_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "kind",
                    "state",
                    "generation_id",
                    "source_sha",
                    "semantic_diff_sha256",
                    "request_universe_generation_sha256",
                    "event_cutoff",
                    "observation_seal_at",
                    "transaction_sha256",
                    "artifact_id",
                    "artifact_digest",
                    "w2_authority",
                    "w2_authority_identity_sha256",
                }
            ),
            label="committed parent authority",
        )
        try:
            kind = GenerationKind(_require_exact_text(payload["kind"], field_name="kind"))
            state = GenerationState(_require_exact_text(payload["state"], field_name="state"))
        except ValueError as exc:
            raise TerminalCatchupContractError(
                "unsupported committed parent kind or state"
            ) from exc
        return cls(
            kind=kind,
            state=state,
            generation_id=cast("str", payload["generation_id"]),
            source_sha=cast("str", payload["source_sha"]),
            semantic_diff_sha256=cast("str", payload["semantic_diff_sha256"]),
            request_universe_generation_sha256=cast(
                "str", payload["request_universe_generation_sha256"]
            ),
            event_cutoff=cast("str", payload["event_cutoff"]),
            observation_seal_at=cast("str", payload["observation_seal_at"]),
            transaction_sha256=cast("str", payload["transaction_sha256"]),
            artifact_id=cast("int", payload["artifact_id"]),
            artifact_digest=cast("str", payload["artifact_digest"]),
            w2_authority=_decode_w2_authority(
                payload["w2_authority"],
                field_name="w2_authority",
            ),
            w2_authority_identity_sha256=cast(
                "str",
                payload["w2_authority_identity_sha256"],
            ),
        )


@dataclass(frozen=True, slots=True)
class TailGenerationIdentityV1:
    generation_id: str
    parent: CommittedParentAuthorityV1
    source_sha: str
    semantic_diff_sha256: str
    request_universe_generation_sha256: str
    event_cutoff: str
    overlap_scope_sha256: str
    parser_body_inventory_sha256: str
    bodyless_inventory_sha256: str
    field_temporal_authority_sha256: str
    canonical_request_inventory_sha256: str
    observation_window: ObservationWindowV1
    w2_expected_call_count: int
    w2_expected_call_inventory_sha256: str

    def __post_init__(self) -> None:
        _require_exact_text(self.generation_id, field_name="generation_id")
        if not isinstance(self.parent, CommittedParentAuthorityV1):
            raise TerminalCatchupContractError("parent must be a CommittedParentAuthorityV1")
        _require_source_sha(self.source_sha)
        for field_name in (
            "semantic_diff_sha256",
            "request_universe_generation_sha256",
            "overlap_scope_sha256",
            "parser_body_inventory_sha256",
            "bodyless_inventory_sha256",
            "field_temporal_authority_sha256",
            "canonical_request_inventory_sha256",
            "w2_expected_call_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_nonnegative_int(
            self.w2_expected_call_count,
            field_name="w2_expected_call_count",
        )
        if self.w2_expected_call_count < self.parent.w2_authority.expected_call_count:
            raise TerminalCatchupContractError(
                "tail W2 expected-call count cannot downgrade its committed parent"
            )
        expected_parent = (
            ("source_sha", self.source_sha, self.parent.source_sha),
            (
                "semantic_diff_sha256",
                self.semantic_diff_sha256,
                self.parent.semantic_diff_sha256,
            ),
            (
                "request_universe_generation_sha256",
                self.request_universe_generation_sha256,
                self.parent.request_universe_generation_sha256,
            ),
        )
        drift = [field_name for field_name, actual, wanted in expected_parent if actual != wanted]
        if drift:
            raise TerminalCatchupContractError(
                "tail authority drift requires a fresh baseline: " + ", ".join(drift)
            )
        cutoff = _parse_utc_timestamp(self.event_cutoff, field_name="event_cutoff")
        parent_cutoff = _parse_utc_timestamp(self.parent.event_cutoff, field_name="parent cutoff")
        if cutoff <= parent_cutoff:
            raise TerminalCatchupContractError("tail cutoff must advance beyond its parent")
        if not isinstance(self.observation_window, ObservationWindowV1):
            raise TerminalCatchupContractError("observation_window must be an ObservationWindowV1")
        if cutoff > _parse_utc_timestamp(
            self.observation_window.seal_at,
            field_name="seal_at",
        ):
            raise TerminalCatchupContractError("tail event cutoff cannot follow its seal")
        parent_seal = _parse_utc_timestamp(
            self.parent.observation_seal_at,
            field_name="parent observation seal",
        )
        if any(
            _parse_utc_timestamp(call.observation_ended_at, field_name="observation_ended_at")
            <= parent_seal
            for call in self.observation_window.calls
        ):
            raise TerminalCatchupContractError(
                "tail observations must end after the committed parent seal"
            )
        expected_inventory = (
            (
                "parser_body_inventory_sha256",
                self.parser_body_inventory_sha256,
                self.observation_window.parser_body_inventory_sha256,
            ),
            (
                "bodyless_inventory_sha256",
                self.bodyless_inventory_sha256,
                self.observation_window.bodyless_inventory_sha256,
            ),
            (
                "field_temporal_authority_sha256",
                self.field_temporal_authority_sha256,
                self.observation_window.field_temporal_inventory_sha256,
            ),
            (
                "canonical_request_inventory_sha256",
                self.canonical_request_inventory_sha256,
                self.observation_window.canonical_request_inventory_sha256,
            ),
        )
        mismatches = [
            field_name for field_name, actual, wanted in expected_inventory if actual != wanted
        ]
        if mismatches:
            raise TerminalCatchupContractError(
                "tail authority inventory mismatch: " + ", ".join(mismatches)
            )

    @property
    def kind(self) -> GenerationKind:
        return GenerationKind.TAIL

    @property
    def identity_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    @property
    def parent_authority_sha256(self) -> str:
        return self.parent.authority_sha256

    @property
    def component_inventory_sha256(self) -> str:
        return _canonical_sha256(
            {
                "overlap_scope_sha256": self.overlap_scope_sha256,
                "call_inventory_sha256": self.observation_window.call_inventory_sha256,
                "parser_body_inventory_sha256": self.parser_body_inventory_sha256,
                "bodyless_inventory_sha256": self.bodyless_inventory_sha256,
                "field_temporal_authority_sha256": self.field_temporal_authority_sha256,
                "canonical_request_inventory_sha256": self.canonical_request_inventory_sha256,
                "w2_expected_call_count": self.w2_expected_call_count,
                "w2_expected_call_inventory_sha256": (self.w2_expected_call_inventory_sha256),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "parent": self.parent.to_dict(),
            "source_sha": self.source_sha,
            "semantic_diff_sha256": self.semantic_diff_sha256,
            "request_universe_generation_sha256": self.request_universe_generation_sha256,
            "event_cutoff": self.event_cutoff,
            "overlap_scope_sha256": self.overlap_scope_sha256,
            "parser_body_inventory_sha256": self.parser_body_inventory_sha256,
            "bodyless_inventory_sha256": self.bodyless_inventory_sha256,
            "field_temporal_authority_sha256": self.field_temporal_authority_sha256,
            "canonical_request_inventory_sha256": self.canonical_request_inventory_sha256,
            "observation_window": self.observation_window.to_dict(),
            "w2_expected_call_count": self.w2_expected_call_count,
            "w2_expected_call_inventory_sha256": (self.w2_expected_call_inventory_sha256),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "generation_id",
                    "parent",
                    "source_sha",
                    "semantic_diff_sha256",
                    "request_universe_generation_sha256",
                    "event_cutoff",
                    "overlap_scope_sha256",
                    "parser_body_inventory_sha256",
                    "bodyless_inventory_sha256",
                    "field_temporal_authority_sha256",
                    "canonical_request_inventory_sha256",
                    "observation_window",
                    "w2_expected_call_count",
                    "w2_expected_call_inventory_sha256",
                }
            ),
            label="tail generation identity",
        )
        return cls(
            generation_id=cast("str", payload["generation_id"]),
            parent=CommittedParentAuthorityV1.from_dict(
                _require_mapping(payload["parent"], field_name="parent")
            ),
            source_sha=cast("str", payload["source_sha"]),
            semantic_diff_sha256=cast("str", payload["semantic_diff_sha256"]),
            request_universe_generation_sha256=cast(
                "str", payload["request_universe_generation_sha256"]
            ),
            event_cutoff=cast("str", payload["event_cutoff"]),
            overlap_scope_sha256=cast("str", payload["overlap_scope_sha256"]),
            parser_body_inventory_sha256=cast("str", payload["parser_body_inventory_sha256"]),
            bodyless_inventory_sha256=cast("str", payload["bodyless_inventory_sha256"]),
            field_temporal_authority_sha256=cast("str", payload["field_temporal_authority_sha256"]),
            canonical_request_inventory_sha256=cast(
                "str", payload["canonical_request_inventory_sha256"]
            ),
            observation_window=ObservationWindowV1.from_dict(
                _require_mapping(payload["observation_window"], field_name="observation_window")
            ),
            w2_expected_call_count=cast("int", payload["w2_expected_call_count"]),
            w2_expected_call_inventory_sha256=cast(
                "str",
                payload["w2_expected_call_inventory_sha256"],
            ),
        )


GenerationIdentityV1 = TerminalCatchupIdentityV1 | TailGenerationIdentityV1


@dataclass(frozen=True, slots=True)
class GenerationBuildV1:
    database_sha256: str
    report_sha256: str
    component_inventory_sha256: str
    w2_authority: CheckpointW2AuthorityIdentity

    def __post_init__(self) -> None:
        for field_name in (
            "database_sha256",
            "report_sha256",
            "component_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_w2_authority(self.w2_authority, field_name="w2_authority")

    def to_dict(self) -> dict[str, object]:
        return {
            "database_sha256": self.database_sha256,
            "report_sha256": self.report_sha256,
            "component_inventory_sha256": self.component_inventory_sha256,
            "w2_authority": self.w2_authority.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "database_sha256",
                    "report_sha256",
                    "component_inventory_sha256",
                    "w2_authority",
                }
            ),
            label="generation build",
        )
        return cls(
            database_sha256=cast("str", payload["database_sha256"]),
            report_sha256=cast("str", payload["report_sha256"]),
            component_inventory_sha256=cast("str", payload["component_inventory_sha256"]),
            w2_authority=_decode_w2_authority(
                payload["w2_authority"],
                field_name="w2_authority",
            ),
        )


@dataclass(frozen=True, slots=True)
class GenerationArtifactReceiptV1:
    artifact_id: int
    artifact_run_id: int
    artifact_name: str
    artifact_digest: str
    artifact_size_bytes: int
    generation_kind: GenerationKind
    generation_id: str
    source_sha: str
    identity_sha256: str
    parent_authority_sha256: str
    database_sha256: str
    report_sha256: str
    component_inventory_sha256: str
    w2_authority: CheckpointW2AuthorityIdentity
    w2_authority_identity_sha256: str

    def __post_init__(self) -> None:
        _require_positive_int(self.artifact_id, field_name="artifact_id")
        _require_positive_int(self.artifact_run_id, field_name="artifact_run_id")
        _require_exact_text(self.artifact_name, field_name="artifact_name")
        _require_sha256(self.artifact_digest, field_name="artifact_digest", prefixed=True)
        _require_positive_int(self.artifact_size_bytes, field_name="artifact_size_bytes")
        if not isinstance(self.generation_kind, GenerationKind):
            raise TerminalCatchupContractError("generation_kind must be a GenerationKind")
        _require_exact_text(self.generation_id, field_name="generation_id")
        _require_source_sha(self.source_sha)
        for field_name in (
            "identity_sha256",
            "parent_authority_sha256",
            "database_sha256",
            "report_sha256",
            "component_inventory_sha256",
            "w2_authority_identity_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        w2_authority = _require_w2_authority(
            self.w2_authority,
            field_name="w2_authority",
        )
        if self.w2_authority_identity_sha256 != w2_authority.identity_sha256:
            raise TerminalCatchupContractError(
                "artifact receipt W2 identity differs from its canonical authority"
            )

    def validate_binding(
        self,
        *,
        identity: GenerationIdentityV1,
        artifact_name: str,
        build: GenerationBuildV1,
    ) -> None:
        expected = (
            ("artifact_name", self.artifact_name, artifact_name),
            ("generation_kind", self.generation_kind, identity.kind),
            ("generation_id", self.generation_id, identity.generation_id),
            ("source_sha", self.source_sha, identity.source_sha),
            ("identity_sha256", self.identity_sha256, identity.identity_sha256),
            (
                "parent_authority_sha256",
                self.parent_authority_sha256,
                identity.parent_authority_sha256,
            ),
            ("database_sha256", self.database_sha256, build.database_sha256),
            ("report_sha256", self.report_sha256, build.report_sha256),
            (
                "component_inventory_sha256",
                self.component_inventory_sha256,
                build.component_inventory_sha256,
            ),
            ("w2_authority", self.w2_authority, build.w2_authority),
            (
                "w2_authority_identity_sha256",
                self.w2_authority_identity_sha256,
                build.w2_authority.identity_sha256,
            ),
        )
        mismatches = [field_name for field_name, actual, wanted in expected if actual != wanted]
        if mismatches:
            raise TerminalCatchupContractError(
                "artifact receipt does not bind the built generation: " + ", ".join(mismatches)
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_run_id": self.artifact_run_id,
            "artifact_name": self.artifact_name,
            "artifact_digest": self.artifact_digest,
            "artifact_size_bytes": self.artifact_size_bytes,
            "generation_kind": self.generation_kind.value,
            "generation_id": self.generation_id,
            "source_sha": self.source_sha,
            "identity_sha256": self.identity_sha256,
            "parent_authority_sha256": self.parent_authority_sha256,
            "database_sha256": self.database_sha256,
            "report_sha256": self.report_sha256,
            "component_inventory_sha256": self.component_inventory_sha256,
            "w2_authority": self.w2_authority.to_dict(),
            "w2_authority_identity_sha256": self.w2_authority_identity_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "artifact_id",
                    "artifact_run_id",
                    "artifact_name",
                    "artifact_digest",
                    "artifact_size_bytes",
                    "generation_kind",
                    "generation_id",
                    "source_sha",
                    "identity_sha256",
                    "parent_authority_sha256",
                    "database_sha256",
                    "report_sha256",
                    "component_inventory_sha256",
                    "w2_authority",
                    "w2_authority_identity_sha256",
                }
            ),
            label="generation artifact receipt",
        )
        try:
            kind = GenerationKind(
                _require_exact_text(payload["generation_kind"], field_name="generation_kind")
            )
        except ValueError as exc:
            raise TerminalCatchupContractError("unsupported artifact generation kind") from exc
        return cls(
            artifact_id=cast("int", payload["artifact_id"]),
            artifact_run_id=cast("int", payload["artifact_run_id"]),
            artifact_name=cast("str", payload["artifact_name"]),
            artifact_digest=cast("str", payload["artifact_digest"]),
            artifact_size_bytes=cast("int", payload["artifact_size_bytes"]),
            generation_kind=kind,
            generation_id=cast("str", payload["generation_id"]),
            source_sha=cast("str", payload["source_sha"]),
            identity_sha256=cast("str", payload["identity_sha256"]),
            parent_authority_sha256=cast("str", payload["parent_authority_sha256"]),
            database_sha256=cast("str", payload["database_sha256"]),
            report_sha256=cast("str", payload["report_sha256"]),
            component_inventory_sha256=cast("str", payload["component_inventory_sha256"]),
            w2_authority=_decode_w2_authority(
                payload["w2_authority"],
                field_name="w2_authority",
            ),
            w2_authority_identity_sha256=cast(
                "str",
                payload["w2_authority_identity_sha256"],
            ),
        )


@dataclass(frozen=True, slots=True)
class _GenerationTransactionV1:
    kind: GenerationKind
    state: GenerationState
    identity: GenerationIdentityV1
    artifact_name: str
    build: GenerationBuildV1 | None = None
    receipt: GenerationArtifactReceiptV1 | None = None

    schema_version: ClassVar[int] = TERMINAL_CATCHUP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.kind, GenerationKind):
            raise TerminalCatchupContractError("kind must be a GenerationKind")
        if not isinstance(self.state, GenerationState):
            raise TerminalCatchupContractError("state must be a GenerationState")
        if not isinstance(self.identity, (TerminalCatchupIdentityV1, TailGenerationIdentityV1)):
            raise TerminalCatchupContractError("identity has an unsupported generation type")
        if self.kind is not self.identity.kind:
            raise TerminalCatchupContractError("transaction kind does not match its identity")
        _require_exact_text(self.artifact_name, field_name="artifact_name")
        expects_build = self.state is not GenerationState.CANDIDATE
        expects_receipt = self.state in {
            GenerationState.UPLOADED_VERIFIED,
            GenerationState.COMMITTED,
        }
        if (self.build is not None) != expects_build:
            raise TerminalCatchupContractError(
                f"{self.state.value} generation has an invalid build contract"
            )
        if (self.receipt is not None) != expects_receipt:
            raise TerminalCatchupContractError(
                f"{self.state.value} generation has an invalid artifact receipt"
            )
        if self.build is not None:
            if not isinstance(self.build, GenerationBuildV1):
                raise TerminalCatchupContractError("build must be a GenerationBuildV1")
            if self.build.component_inventory_sha256 != self.identity.component_inventory_sha256:
                raise TerminalCatchupContractError("build component inventory drifts from identity")
            expected_w2 = (
                self.identity.w2_expected_call_count,
                self.identity.w2_expected_call_inventory_sha256,
            )
            observed_w2 = (
                self.build.w2_authority.expected_call_count,
                self.build.w2_authority.expected_call_inventory_sha256,
            )
            if observed_w2 != expected_w2:
                raise TerminalCatchupContractError(
                    "build W2 authority differs from the candidate expected-call identity"
                )
        if self.receipt is not None:
            if not isinstance(self.receipt, GenerationArtifactReceiptV1):
                raise TerminalCatchupContractError("receipt must be a GenerationArtifactReceiptV1")
            assert self.build is not None
            self.receipt.validate_binding(
                identity=self.identity,
                artifact_name=self.artifact_name,
                build=self.build,
            )

    def mark_built(
        self,
        *,
        database_sha256: str,
        report_sha256: str,
        w2_authority: CheckpointW2AuthorityIdentity,
    ) -> Self:
        self._require_state(GenerationState.CANDIDATE, operation="mark built")
        return replace(
            self,
            state=GenerationState.BUILT,
            build=GenerationBuildV1(
                database_sha256=database_sha256,
                report_sha256=report_sha256,
                component_inventory_sha256=self.identity.component_inventory_sha256,
                w2_authority=w2_authority,
            ),
        )

    def mark_uploaded_verified(self, receipt: GenerationArtifactReceiptV1) -> Self:
        self._require_state(
            GenerationState.BUILT,
            operation="mark uploaded and verified",
        )
        assert self.build is not None
        receipt.validate_binding(
            identity=self.identity,
            artifact_name=self.artifact_name,
            build=self.build,
        )
        return replace(
            self,
            state=GenerationState.UPLOADED_VERIFIED,
            receipt=receipt,
        )

    def commit(self) -> Self:
        self._require_state(GenerationState.UPLOADED_VERIFIED, operation="commit")
        return replace(self, state=GenerationState.COMMITTED)

    def _require_state(self, expected: GenerationState, *, operation: str) -> None:
        if self.state is expected:
            return
        raise TerminalCatchupTransitionError(
            f"cannot {operation} {self.kind.value} from {self.state.value}; "
            f"expected {expected.value}"
        )

    @property
    def transaction_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    @property
    def committed_receipt(self) -> GenerationArtifactReceiptV1:
        self._require_state(GenerationState.COMMITTED, operation="read committed receipt")
        assert self.receipt is not None
        return self.receipt

    def committed_authority(self) -> CommittedParentAuthorityV1:
        receipt = self.committed_receipt
        assert self.build is not None
        return CommittedParentAuthorityV1(
            kind=self.kind,
            state=GenerationState.COMMITTED,
            generation_id=self.identity.generation_id,
            source_sha=self.identity.source_sha,
            semantic_diff_sha256=self.identity.semantic_diff_sha256,
            request_universe_generation_sha256=(self.identity.request_universe_generation_sha256),
            event_cutoff=self.identity.event_cutoff,
            observation_seal_at=self.identity.observation_window.seal_at,
            transaction_sha256=self.transaction_sha256,
            artifact_id=receipt.artifact_id,
            artifact_digest=receipt.artifact_digest,
            w2_authority=self.build.w2_authority,
            w2_authority_identity_sha256=self.build.w2_authority.identity_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "state": self.state.value,
            "identity": self.identity.to_dict(),
            "identity_sha256": self.identity.identity_sha256,
            "artifact_name": self.artifact_name,
        }
        if self.build is not None:
            payload["build"] = self.build.to_dict()
        if self.receipt is not None:
            payload["receipt"] = self.receipt.to_dict()
        return payload

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def _from_dict(cls, payload: Mapping[str, object], *, expected_kind: GenerationKind) -> Self:
        raw_state = _require_exact_text(payload.get("state"), field_name="state")
        try:
            state = GenerationState(raw_state)
            kind = GenerationKind(_require_exact_text(payload.get("kind"), field_name="kind"))
        except ValueError as exc:
            raise TerminalCatchupContractError("unsupported transaction kind or state") from exc
        if kind is not expected_kind:
            raise TerminalCatchupContractError("transaction kind does not match decoder")
        expected_keys = {
            "schema_version",
            "kind",
            "state",
            "identity",
            "identity_sha256",
            "artifact_name",
        }
        if state is not GenerationState.CANDIDATE:
            expected_keys.add("build")
        if state in {GenerationState.UPLOADED_VERIFIED, GenerationState.COMMITTED}:
            expected_keys.add("receipt")
        _require_exact_keys(
            payload,
            expected=frozenset(expected_keys),
            label=f"{state.value} {kind.value} transaction",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != TERMINAL_CATCHUP_SCHEMA_VERSION
        ):
            raise TerminalCatchupContractError("unsupported generation transaction schema")
        raw_identity = _require_mapping(payload["identity"], field_name="identity")
        identity: GenerationIdentityV1
        if kind is GenerationKind.TERMINAL_CATCHUP:
            identity = TerminalCatchupIdentityV1.from_dict(raw_identity)
        else:
            identity = TailGenerationIdentityV1.from_dict(raw_identity)
        supplied_identity = _require_sha256(
            payload["identity_sha256"],
            field_name="identity_sha256",
        )
        if supplied_identity != identity.identity_sha256:
            raise TerminalCatchupContractError("transaction identity digest is invalid")
        build = (
            None
            if state is GenerationState.CANDIDATE
            else GenerationBuildV1.from_dict(_require_mapping(payload["build"], field_name="build"))
        )
        receipt = (
            GenerationArtifactReceiptV1.from_dict(
                _require_mapping(payload["receipt"], field_name="receipt")
            )
            if state in {GenerationState.UPLOADED_VERIFIED, GenerationState.COMMITTED}
            else None
        )
        return cls(
            kind=kind,
            state=state,
            identity=identity,
            artifact_name=cast("str", payload["artifact_name"]),
            build=build,
            receipt=receipt,
        )


class TerminalCatchupTransactionV1(_GenerationTransactionV1):
    @classmethod
    def candidate(
        cls,
        *,
        identity: TerminalCatchupIdentityV1,
        artifact_name: str,
    ) -> Self:
        return cls(
            kind=GenerationKind.TERMINAL_CATCHUP,
            state=GenerationState.CANDIDATE,
            identity=identity,
            artifact_name=artifact_name,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        return cls._from_dict(payload, expected_kind=GenerationKind.TERMINAL_CATCHUP)

    @classmethod
    def from_bytes(cls, encoded: bytes) -> Self:
        return cls.from_dict(_decode_canonical_json(encoded))


class TailGenerationTransactionV1(_GenerationTransactionV1):
    @classmethod
    def candidate(
        cls,
        *,
        identity: TailGenerationIdentityV1,
        artifact_name: str,
    ) -> Self:
        return cls(
            kind=GenerationKind.TAIL,
            state=GenerationState.CANDIDATE,
            identity=identity,
            artifact_name=artifact_name,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        return cls._from_dict(payload, expected_kind=GenerationKind.TAIL)

    @classmethod
    def from_bytes(cls, encoded: bytes) -> Self:
        return cls.from_dict(_decode_canonical_json(encoded))


@dataclass(frozen=True, slots=True, order=True)
class TailTriggerDemandV1:
    trigger_id: str
    trigger_kind: TriggerKind
    parent_authority_sha256: str
    desired_cutoff: str

    def __post_init__(self) -> None:
        _require_exact_text(self.trigger_id, field_name="trigger_id")
        if not isinstance(self.trigger_kind, TriggerKind):
            raise TerminalCatchupContractError("trigger_kind must be a TriggerKind")
        _require_sha256(
            self.parent_authority_sha256,
            field_name="parent_authority_sha256",
        )
        _parse_utc_timestamp(self.desired_cutoff, field_name="desired_cutoff")

    def to_dict(self) -> dict[str, str]:
        return {
            "trigger_id": self.trigger_id,
            "trigger_kind": self.trigger_kind.value,
            "parent_authority_sha256": self.parent_authority_sha256,
            "desired_cutoff": self.desired_cutoff,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {"trigger_id", "trigger_kind", "parent_authority_sha256", "desired_cutoff"}
            ),
            label="tail trigger demand",
        )
        try:
            kind = TriggerKind(
                _require_exact_text(payload["trigger_kind"], field_name="trigger_kind")
            )
        except ValueError as exc:
            raise TerminalCatchupContractError("unsupported trigger kind") from exc
        return cls(
            trigger_id=cast("str", payload["trigger_id"]),
            trigger_kind=kind,
            parent_authority_sha256=cast("str", payload["parent_authority_sha256"]),
            desired_cutoff=cast("str", payload["desired_cutoff"]),
        )


@dataclass(frozen=True, slots=True)
class TailFreshnessReceiptV1:
    trigger_id: str
    trigger_kind: TriggerKind
    parent_authority_sha256: str
    generation_id: str
    requested_cutoff: str
    effective_desired_cutoff: str
    admission_sha256: str
    provider_observation_sha256: str | None
    committed_tail_transaction_sha256: str | None
    status: FreshnessStatus

    def __post_init__(self) -> None:
        _require_exact_text(self.trigger_id, field_name="trigger_id")
        if not isinstance(self.trigger_kind, TriggerKind):
            raise TerminalCatchupContractError("trigger_kind must be a TriggerKind")
        _require_sha256(
            self.parent_authority_sha256,
            field_name="parent_authority_sha256",
        )
        _require_exact_text(self.generation_id, field_name="generation_id")
        requested = _parse_utc_timestamp(self.requested_cutoff, field_name="requested_cutoff")
        effective = _parse_utc_timestamp(
            self.effective_desired_cutoff,
            field_name="effective_desired_cutoff",
        )
        if requested > effective:
            raise TerminalCatchupContractError("effective cutoff cannot precede a trigger cutoff")
        _require_sha256(self.admission_sha256, field_name="admission_sha256")
        _optional_sha256(
            self.provider_observation_sha256,
            field_name="provider_observation_sha256",
        )
        _optional_sha256(
            self.committed_tail_transaction_sha256,
            field_name="committed_tail_transaction_sha256",
        )
        if not isinstance(self.status, FreshnessStatus):
            raise TerminalCatchupContractError("status must be a FreshnessStatus")
        if self.status is FreshnessStatus.FRESH:
            if (
                self.provider_observation_sha256 is None
                or self.committed_tail_transaction_sha256 is None
            ):
                raise TerminalCatchupContractError(
                    "fresh status requires provider and committed-tail evidence"
                )
        elif self.status is FreshnessStatus.NOT_FRESH:
            if (
                self.provider_observation_sha256 is None
                or self.committed_tail_transaction_sha256 is not None
            ):
                raise TerminalCatchupContractError(
                    "not_fresh requires provider evidence and no fabricated tail"
                )
        elif (
            self.provider_observation_sha256 is not None
            or self.committed_tail_transaction_sha256 is not None
        ):
            raise TerminalCatchupContractError(
                "capacity_blocked cannot claim provider work or a committed tail"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "trigger_id": self.trigger_id,
            "trigger_kind": self.trigger_kind.value,
            "parent_authority_sha256": self.parent_authority_sha256,
            "generation_id": self.generation_id,
            "requested_cutoff": self.requested_cutoff,
            "effective_desired_cutoff": self.effective_desired_cutoff,
            "admission_sha256": self.admission_sha256,
            "provider_observation_sha256": self.provider_observation_sha256,
            "committed_tail_transaction_sha256": self.committed_tail_transaction_sha256,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "trigger_id",
                    "trigger_kind",
                    "parent_authority_sha256",
                    "generation_id",
                    "requested_cutoff",
                    "effective_desired_cutoff",
                    "admission_sha256",
                    "provider_observation_sha256",
                    "committed_tail_transaction_sha256",
                    "status",
                }
            ),
            label="tail freshness receipt",
        )
        try:
            trigger_kind = TriggerKind(
                _require_exact_text(payload["trigger_kind"], field_name="trigger_kind")
            )
            status = FreshnessStatus(_require_exact_text(payload["status"], field_name="status"))
        except ValueError as exc:
            raise TerminalCatchupContractError("unsupported trigger or freshness status") from exc
        return cls(
            trigger_id=cast("str", payload["trigger_id"]),
            trigger_kind=trigger_kind,
            parent_authority_sha256=cast("str", payload["parent_authority_sha256"]),
            generation_id=cast("str", payload["generation_id"]),
            requested_cutoff=cast("str", payload["requested_cutoff"]),
            effective_desired_cutoff=cast("str", payload["effective_desired_cutoff"]),
            admission_sha256=cast("str", payload["admission_sha256"]),
            provider_observation_sha256=cast("str | None", payload["provider_observation_sha256"]),
            committed_tail_transaction_sha256=cast(
                "str | None", payload["committed_tail_transaction_sha256"]
            ),
            status=status,
        )


@dataclass(frozen=True, slots=True)
class CoalescedTailDemandV1:
    parent: CommittedParentAuthorityV1
    generation_id: str
    demands: tuple[TailTriggerDemandV1, ...]
    desired_cutoff: str

    schema_version: ClassVar[int] = TERMINAL_CATCHUP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.parent, CommittedParentAuthorityV1):
            raise TerminalCatchupContractError("parent must be a CommittedParentAuthorityV1")
        _require_exact_text(self.generation_id, field_name="generation_id")
        if not self.demands or any(
            not isinstance(demand, TailTriggerDemandV1) for demand in self.demands
        ):
            raise TerminalCatchupContractError("coalesced demand requires trigger demands")
        normalized = tuple(sorted(self.demands))
        if normalized != self.demands:
            raise TerminalCatchupContractError("trigger demands must be in canonical order")
        trigger_ids = [demand.trigger_id for demand in self.demands]
        if len(trigger_ids) != len(set(trigger_ids)):
            raise TerminalCatchupContractError("trigger IDs must be unique")
        if any(
            demand.parent_authority_sha256 != self.parent.authority_sha256
            for demand in self.demands
        ):
            raise TerminalCatchupContractError("coalesced demand contains a foreign parent")
        desired = _parse_utc_timestamp(self.desired_cutoff, field_name="desired_cutoff")
        maximum = max(
            _parse_utc_timestamp(demand.desired_cutoff, field_name="desired_cutoff")
            for demand in self.demands
        )
        if desired != maximum:
            raise TerminalCatchupContractError(
                "coalesced desired cutoff must equal the monotonic maximum"
            )

    @classmethod
    def create(
        cls,
        *,
        parent: CommittedParentAuthorityV1,
        generation_id: str,
        demand: TailTriggerDemandV1,
    ) -> Self:
        return cls(
            parent=parent,
            generation_id=generation_id,
            demands=(demand,),
            desired_cutoff=demand.desired_cutoff,
        )

    def add(self, demand: TailTriggerDemandV1) -> Self:
        demands = tuple(sorted((*self.demands, demand)))
        desired = max(
            _parse_utc_timestamp(item.desired_cutoff, field_name="desired_cutoff")
            for item in demands
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        return replace(self, demands=demands, desired_cutoff=desired)

    def finish(
        self,
        *,
        status: FreshnessStatus,
        admission_sha256: str,
        provider_observation_sha256: str | None,
        committed_tail: TailGenerationTransactionV1 | None,
    ) -> tuple[TailFreshnessReceiptV1, ...]:
        _require_sha256(admission_sha256, field_name="admission_sha256")
        tail_sha256: str | None = None
        if status is FreshnessStatus.FRESH:
            if committed_tail is None or committed_tail.state is not GenerationState.COMMITTED:
                raise TerminalCatchupContractError("fresh status requires one committed tail")
            if not isinstance(committed_tail.identity, TailGenerationIdentityV1):
                raise TerminalCatchupContractError("fresh status requires a tail identity")
            if committed_tail.identity.parent.authority_sha256 != self.parent.authority_sha256:
                raise TerminalCatchupContractError("committed tail has a foreign parent")
            if committed_tail.identity.generation_id != self.generation_id:
                raise TerminalCatchupContractError("committed tail generation ID is inconsistent")
            if _parse_utc_timestamp(
                committed_tail.identity.event_cutoff,
                field_name="tail event_cutoff",
            ) < _parse_utc_timestamp(self.desired_cutoff, field_name="desired_cutoff"):
                raise TerminalCatchupContractError("committed tail does not reach desired cutoff")
            if provider_observation_sha256 is None:
                raise TerminalCatchupContractError("fresh status requires provider evidence")
            tail_sha256 = committed_tail.transaction_sha256
        elif committed_tail is not None:
            raise TerminalCatchupContractError("non-fresh status cannot relabel a tail transaction")
        if status is FreshnessStatus.NOT_FRESH and provider_observation_sha256 is None:
            raise TerminalCatchupContractError("not_fresh status requires provider evidence")
        if status is FreshnessStatus.CAPACITY_BLOCKED and provider_observation_sha256 is not None:
            raise TerminalCatchupContractError("capacity_blocked cannot claim provider evidence")
        return tuple(
            TailFreshnessReceiptV1(
                trigger_id=demand.trigger_id,
                trigger_kind=demand.trigger_kind,
                parent_authority_sha256=self.parent.authority_sha256,
                generation_id=self.generation_id,
                requested_cutoff=demand.desired_cutoff,
                effective_desired_cutoff=self.desired_cutoff,
                admission_sha256=admission_sha256,
                provider_observation_sha256=provider_observation_sha256,
                committed_tail_transaction_sha256=tail_sha256,
                status=status,
            )
            for demand in self.demands
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "parent": self.parent.to_dict(),
            "generation_id": self.generation_id,
            "demands": [demand.to_dict() for demand in self.demands],
            "desired_cutoff": self.desired_cutoff,
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {"schema_version", "parent", "generation_id", "demands", "desired_cutoff"}
            ),
            label="coalesced tail demand",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != TERMINAL_CATCHUP_SCHEMA_VERSION
        ):
            raise TerminalCatchupContractError("unsupported coalesced-demand schema")
        raw_demands = payload["demands"]
        if not isinstance(raw_demands, list):
            raise TerminalCatchupContractError("demands must be a list")
        return cls(
            parent=CommittedParentAuthorityV1.from_dict(
                _require_mapping(payload["parent"], field_name="parent")
            ),
            generation_id=cast("str", payload["generation_id"]),
            demands=tuple(
                TailTriggerDemandV1.from_dict(
                    _require_mapping(raw_demand, field_name=f"demand {index}")
                )
                for index, raw_demand in enumerate(raw_demands)
            ),
            desired_cutoff=cast("str", payload["desired_cutoff"]),
        )

    @classmethod
    def from_bytes(cls, encoded: bytes) -> Self:
        return cls.from_dict(_decode_canonical_json(encoded))
