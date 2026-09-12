"""Nonterminal evidence partition over a request-universe candidate denominator.

This module cannot admit a denominator, prove a fixed point, schedule extraction,
or authorize publication.  It only conserves every field-period cell from one
independently checked request-universe candidate and partitions assertion-only
observations into unresolved, conflicting, and unjoinable evidence.  Digest
claims are retained for a later receipt-authority join but are never treated as
receipt authority by this slice.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from nbadb.orchestrate.request_universe_generation_contract import (
    CandidateBlockerV1,
    FieldPeriodDenominatorCellV1,
    RequestUniverseCandidateGenerationV1,
    TemporalScopeKind,
)
from nbadb.orchestrate.request_universe_generation_verifier import (
    RequestUniverseCandidateIndependentProofV1,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import Protocol

    from nbadb.orchestrate.request_universe_generation_contract import NestedPathSegment

    class _DictSerializable(Protocol):
        def to_dict(self) -> dict[str, object]: ...


__all__ = [
    "TEMPORAL_FIELD_EVIDENCE_SCHEMA_VERSION",
    "FieldEvidenceCellV1",
    "FieldEvidenceDispositionV1",
    "FieldEvidenceStateV1",
    "FieldObservationBindingV1",
    "TemporalFieldEvidenceCandidateV1",
    "TemporalFieldEvidenceContractError",
    "UnjoinableFieldObservationV1",
    "UnjoinableReasonV1",
    "canonical_temporal_field_evidence_json_bytes",
    "canonical_temporal_field_evidence_sha256",
    "compile_temporal_field_evidence_candidate_v1",
]

TEMPORAL_FIELD_EVIDENCE_SCHEMA_VERSION = 1

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,511}")
_SEASON_RE = re.compile(r"([0-9]{4})-([0-9]{2})")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_GAME_ID_RE = re.compile(r"[0-9]{10}")
_MAX_TEXT = 1_024
_MAX_PATH_SEGMENTS = 64
_MAX_CELLS = 5_000_000
_MAX_OBSERVATIONS = 10_000_000
_MAX_CANONICAL_BYTES = 256 * 1024 * 1024


class TemporalFieldEvidenceContractError(ValueError):
    """Raised when temporal-field evidence is lossy or inconsistently bound."""


class FieldEvidenceStateV1(StrEnum):
    """Closed observation vocabulary for this nonterminal evidence slice."""

    RESULT_MISSING = "result_missing"
    FIELD_MISSING = "field_missing"
    NULL = "null"
    PRESENT_EMPTY = "present_empty"
    POPULATED = "populated"
    VALID_EMPTY = "valid_empty"
    UNKNOWN = "unknown"
    TRANSIENT = "transient"


class FieldEvidenceDispositionV1(StrEnum):
    """Exact disposition of one conserved denominator cell."""

    EVIDENCED = "evidenced"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


class UnjoinableReasonV1(StrEnum):
    """Why a well-formed observation could not join the parent denominator."""

    PARENT_CANDIDATE_MISMATCH = "parent_candidate_mismatch"
    AUTHORITY_MISMATCH = "authority_mismatch"
    CELL_ABSENT = "cell_absent"
    CELL_IDENTITY_MISMATCH = "cell_identity_mismatch"


def canonical_temporal_field_evidence_json_bytes(payload: object) -> bytes:
    """Return the sole canonical JSON representation for this contract."""

    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise TemporalFieldEvidenceContractError(
            "temporal-field evidence is not canonical JSON"
        ) from exc


def canonical_temporal_field_evidence_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_temporal_field_evidence_json_bytes(payload)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise TemporalFieldEvidenceContractError(f"{field_name} must be an exact lowercase SHA-256")
    return value


def _require_safe_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise TemporalFieldEvidenceContractError(
            f"{field_name} must be an exact bounded safe identifier"
        )
    return value


def _require_text(value: object, *, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_TEXT
        or any(ord(character) < 0x20 for character in value)
    ):
        raise TemporalFieldEvidenceContractError(
            f"{field_name} must be exact bounded non-control text"
        )
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise TemporalFieldEvidenceContractError(f"{field_name} must be a nonnegative integer")
    return value


def _require_schema_identity(
    payload: Mapping[str, object],
    *,
    kind: str,
    label: str,
) -> None:
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != TEMPORAL_FIELD_EVIDENCE_SCHEMA_VERSION
        or type(payload.get("kind")) is not str
        or payload.get("kind") != kind
    ):
        raise TemporalFieldEvidenceContractError(f"{label} schema identity is invalid")


def _exact_typed_equal(left: object, right: object) -> bool:
    """Compare canonical data without Python's bool/int numeric coercion."""

    if type(left) is not type(right):
        return False
    if type(left) is dict:
        left_map = cast("dict[object, object]", left)
        right_map = cast("dict[object, object]", right)
        return set(left_map) == set(right_map) and all(
            _exact_typed_equal(left_map[key], right_map[key]) for key in left_map
        )
    if type(left) in {list, tuple}:
        left_values = cast("list[object] | tuple[object, ...]", left)
        right_values = cast("list[object] | tuple[object, ...]", right)
        return len(left_values) == len(right_values) and all(
            _exact_typed_equal(first, second)
            for first, second in zip(left_values, right_values, strict=True)
        )
    return left == right


def _strict_dto[T](
    value: object,
    *,
    dto_type: type[T],
    decoder: Callable[[Mapping[str, object]], T],
    label: str,
) -> T:
    if type(value) is not dto_type:
        raise TemporalFieldEvidenceContractError(f"{label} has a non-exact DTO type")
    try:
        payload = cast("_DictSerializable", value).to_dict()
        rebuilt = decoder(_mapping(payload, field_name=f"{label} payload"))
        rebuilt_payload = cast("_DictSerializable", rebuilt).to_dict()
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TemporalFieldEvidenceContractError(
            f"{label} fails strict nested reconstruction"
        ) from exc
    if not _exact_typed_equal(payload, rebuilt_payload):
        raise TemporalFieldEvidenceContractError(
            f"{label} differs after strict nested reconstruction"
        )
    return rebuilt


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if type(payload) is not dict or frozenset(payload) != expected:
        raise TemporalFieldEvidenceContractError(f"{label} has missing or unexpected fields")


def _mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TemporalFieldEvidenceContractError(
            f"{field_name} must be an exact string-keyed object"
        )
    return cast("Mapping[str, object]", value)


def _list(value: object, *, field_name: str, maximum: int) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise TemporalFieldEvidenceContractError(f"{field_name} must be an exact bounded array")
    return cast("list[object]", value)


def _nested_path(value: object) -> tuple[NestedPathSegment, ...]:
    if type(value) is not tuple or len(value) > _MAX_PATH_SEGMENTS:
        raise TemporalFieldEvidenceContractError("nested_path must be an exact bounded tuple")
    result: list[NestedPathSegment] = []
    for segment in value:
        if type(segment) is int:
            result.append(_require_nonnegative_int(segment, field_name="nested_path index"))
        else:
            result.append(_require_text(segment, field_name="nested_path segment"))
    return tuple(result)


def _nested_path_from_payload(value: object) -> tuple[NestedPathSegment, ...]:
    return _nested_path(tuple(_list(value, field_name="nested_path", maximum=_MAX_PATH_SEGMENTS)))


def _decode_canonical_mapping(raw: bytes, *, label: str) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise TemporalFieldEvidenceContractError(f"{label} canonical byte length is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise TemporalFieldEvidenceContractError(
                    f"{label} canonical JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                TemporalFieldEvidenceContractError(
                    f"{label} canonical JSON contains a non-finite number"
                )
            ),
        )
    except TemporalFieldEvidenceContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise TemporalFieldEvidenceContractError(
            f"{label} canonical input is not valid JSON"
        ) from exc
    payload = _mapping(decoded, field_name=f"{label} canonical root")
    if canonical_temporal_field_evidence_json_bytes(payload) != raw:
        raise TemporalFieldEvidenceContractError(f"{label} input is not exact canonical JSON")
    return payload


def _scope_kind_from_payload(value: object) -> TemporalScopeKind:
    if type(value) is not str:
        raise TemporalFieldEvidenceContractError("temporal_scope_kind is invalid")
    try:
        return TemporalScopeKind(value)
    except (TypeError, ValueError) as exc:
        raise TemporalFieldEvidenceContractError("temporal_scope_kind is invalid") from exc


def _require_scope_kind(value: object) -> TemporalScopeKind:
    if type(value) is not TemporalScopeKind:
        raise TemporalFieldEvidenceContractError(
            "temporal_scope_kind must be an exact TemporalScopeKind"
        )
    return value


def _scope_value(kind: TemporalScopeKind, value: object) -> str | int:
    if kind is TemporalScopeKind.CALENDAR_YEAR:
        if type(value) is not int or value < 1946 or value > 9999:
            raise TemporalFieldEvidenceContractError(
                "calendar_year temporal_scope_value is invalid"
            )
        return value
    if type(value) is not str:
        raise TemporalFieldEvidenceContractError(
            "temporal_scope_value must preserve the parent scalar type"
        )
    if kind is TemporalScopeKind.SEASON:
        match = _SEASON_RE.fullmatch(value)
        if match is None or int(match.group(2)) != (int(match.group(1)) + 1) % 100:
            raise TemporalFieldEvidenceContractError("season temporal_scope_value is invalid")
    elif kind is TemporalScopeKind.GAME_DATE:
        match = _DATE_RE.fullmatch(value)
        if match is None:
            raise TemporalFieldEvidenceContractError("game_date temporal_scope_value is invalid")
        try:
            date(*(int(part) for part in match.groups()))
        except ValueError as exc:
            raise TemporalFieldEvidenceContractError(
                "game_date temporal_scope_value is not a calendar date"
            ) from exc
    elif kind is TemporalScopeKind.GAME_ID and _GAME_ID_RE.fullmatch(value) is None:
        raise TemporalFieldEvidenceContractError("game_id temporal_scope_value is invalid")
    elif kind not in {
        TemporalScopeKind.SEASON,
        TemporalScopeKind.GAME_DATE,
        TemporalScopeKind.GAME_ID,
    }:
        _require_text(value, field_name=f"{kind.value} temporal_scope_value")
        if len(value) > 256:
            raise TemporalFieldEvidenceContractError(
                f"{kind.value} temporal_scope_value exceeds the bound"
            )
    return value


def _identity_fields_from_cell(cell: FieldPeriodDenominatorCellV1) -> dict[str, object]:
    return {
        "cell_id": cell.cell_id,
        "physical_call_id": cell.physical_call_id,
        "route_request_member_id": cell.route_request_member_id,
        "route_id": cell.route_id,
        "endpoint_name": cell.endpoint_name,
        "result_name": cell.result_name,
        "result_ordinal": cell.result_ordinal,
        "nested_path": list(cell.nested_path),
        "provider_field": cell.provider_field,
        "field_occurrence_ordinal": cell.field_occurrence_ordinal,
        "request_scope_sha256": cell.request_scope_sha256,
        "field_fate_contract_sha256": cell.field_fate_contract_sha256,
        "temporal_contract_sha256": cell.temporal_contract_sha256,
        "temporal_scope_kind": cell.temporal_scope_kind.value,
        "temporal_scope_value": cell.temporal_scope_value,
    }


@dataclass(frozen=True, slots=True)
class FieldObservationBindingV1:
    """One assertion-only field state with complete join and digest identity.

    No field-value receipt authority exists in this slice.  The digest claims
    remain useful lossless inputs for a later authority join, but ``proofs_equal``
    is only a caller assertion and can never promote a cell to evidenced.
    """

    parent_candidate_sha256: str
    authority_generation_sha256: str
    observation_id: str
    cell_id: str
    physical_call_id: str
    route_request_member_id: str
    route_id: str
    endpoint_name: str
    result_name: str
    result_ordinal: int
    nested_path: tuple[NestedPathSegment, ...]
    provider_field: str
    field_occurrence_ordinal: int
    request_scope_sha256: str
    field_fate_contract_sha256: str
    temporal_contract_sha256: str
    temporal_scope_kind: TemporalScopeKind
    temporal_scope_value: str | int
    state: FieldEvidenceStateV1
    raw_authority_bundle_sha256: str
    request_observation_sha256: str
    provider_call_sha256: str
    provider_request_sha256: str
    result_occurrence_sha256: str
    logical_result_receipt_sha256: str
    route_receipt_sha256: str
    typed_value_receipt_sha256: str
    reconstruction_receipt_sha256: str
    proofs_equal: Literal[True]

    schema_version: ClassVar[int] = TEMPORAL_FIELD_EVIDENCE_SCHEMA_VERSION
    kind: ClassVar[str] = "field_observation_binding_v1"

    def __post_init__(self) -> None:
        _require_sha256(self.parent_candidate_sha256, field_name="parent_candidate_sha256")
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_safe_id(self.cell_id, field_name="cell_id")
        _require_safe_id(self.physical_call_id, field_name="physical_call_id")
        _require_safe_id(
            self.route_request_member_id,
            field_name="route_request_member_id",
        )
        _require_safe_id(self.route_id, field_name="route_id")
        _require_safe_id(self.endpoint_name, field_name="endpoint_name")
        _require_text(self.result_name, field_name="result_name")
        _require_nonnegative_int(self.result_ordinal, field_name="result_ordinal")
        object.__setattr__(self, "nested_path", _nested_path(self.nested_path))
        _require_text(self.provider_field, field_name="provider_field")
        _require_nonnegative_int(
            self.field_occurrence_ordinal,
            field_name="field_occurrence_ordinal",
        )
        for name in (
            "request_scope_sha256",
            "field_fate_contract_sha256",
            "temporal_contract_sha256",
            "raw_authority_bundle_sha256",
            "request_observation_sha256",
            "provider_call_sha256",
            "provider_request_sha256",
            "result_occurrence_sha256",
            "logical_result_receipt_sha256",
            "route_receipt_sha256",
            "typed_value_receipt_sha256",
            "reconstruction_receipt_sha256",
        ):
            _require_sha256(getattr(self, name), field_name=name)
        kind = _require_scope_kind(self.temporal_scope_kind)
        object.__setattr__(
            self,
            "temporal_scope_value",
            _scope_value(kind, self.temporal_scope_value),
        )
        if type(self.state) is not FieldEvidenceStateV1:
            raise TemporalFieldEvidenceContractError(
                "field evidence state must be an exact FieldEvidenceStateV1"
            )
        if self.proofs_equal is not True:
            raise TemporalFieldEvidenceContractError(
                "field observation requires equal raw and reconstructed proofs"
            )
        expected = (
            "field-observation-v1:"
            f"{canonical_temporal_field_evidence_sha256(self._identity_payload())}"
        )
        if self.observation_id != expected:
            raise TemporalFieldEvidenceContractError(
                "observation_id differs from its exact identity and receipts"
            )

    @classmethod
    def build(
        cls,
        *,
        parent_candidate_sha256: str,
        cell: FieldPeriodDenominatorCellV1,
        state: FieldEvidenceStateV1,
        raw_authority_bundle_sha256: str,
        request_observation_sha256: str,
        provider_call_sha256: str,
        provider_request_sha256: str,
        result_occurrence_sha256: str,
        logical_result_receipt_sha256: str,
        route_receipt_sha256: str,
        typed_value_receipt_sha256: str,
        reconstruction_receipt_sha256: str,
    ) -> FieldObservationBindingV1:
        cell = _strict_dto(
            cell,
            dto_type=FieldPeriodDenominatorCellV1,
            decoder=FieldPeriodDenominatorCellV1.from_dict,
            label="field observation parent cell",
        )
        if type(state) is not FieldEvidenceStateV1:
            raise TemporalFieldEvidenceContractError(
                "field evidence state must be an exact FieldEvidenceStateV1"
            )
        fields = _identity_fields_from_cell(cell)
        payload = {
            "schema_version": TEMPORAL_FIELD_EVIDENCE_SCHEMA_VERSION,
            "kind": cls.kind,
            "parent_candidate_sha256": parent_candidate_sha256,
            "authority_generation_sha256": cell.authority_generation_sha256,
            **fields,
            "state": state.value,
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "request_observation_sha256": request_observation_sha256,
            "provider_call_sha256": provider_call_sha256,
            "provider_request_sha256": provider_request_sha256,
            "result_occurrence_sha256": result_occurrence_sha256,
            "logical_result_receipt_sha256": logical_result_receipt_sha256,
            "route_receipt_sha256": route_receipt_sha256,
            "typed_value_receipt_sha256": typed_value_receipt_sha256,
            "reconstruction_receipt_sha256": reconstruction_receipt_sha256,
            "proofs_equal": True,
        }
        observation_id = f"field-observation-v1:{canonical_temporal_field_evidence_sha256(payload)}"
        return cls(
            parent_candidate_sha256=parent_candidate_sha256,
            authority_generation_sha256=cell.authority_generation_sha256,
            observation_id=observation_id,
            cell_id=cell.cell_id,
            physical_call_id=cell.physical_call_id,
            route_request_member_id=cell.route_request_member_id,
            route_id=cell.route_id,
            endpoint_name=cell.endpoint_name,
            result_name=cell.result_name,
            result_ordinal=cell.result_ordinal,
            nested_path=cell.nested_path,
            provider_field=cell.provider_field,
            field_occurrence_ordinal=cell.field_occurrence_ordinal,
            request_scope_sha256=cell.request_scope_sha256,
            field_fate_contract_sha256=cell.field_fate_contract_sha256,
            temporal_contract_sha256=cell.temporal_contract_sha256,
            temporal_scope_kind=cell.temporal_scope_kind,
            temporal_scope_value=cell.temporal_scope_value,
            state=state,
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            request_observation_sha256=request_observation_sha256,
            provider_call_sha256=provider_call_sha256,
            provider_request_sha256=provider_request_sha256,
            result_occurrence_sha256=result_occurrence_sha256,
            logical_result_receipt_sha256=logical_result_receipt_sha256,
            route_receipt_sha256=route_receipt_sha256,
            typed_value_receipt_sha256=typed_value_receipt_sha256,
            reconstruction_receipt_sha256=reconstruction_receipt_sha256,
            proofs_equal=True,
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "parent_candidate_sha256": self.parent_candidate_sha256,
            "authority_generation_sha256": self.authority_generation_sha256,
            "cell_id": self.cell_id,
            "physical_call_id": self.physical_call_id,
            "route_request_member_id": self.route_request_member_id,
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "result_name": self.result_name,
            "result_ordinal": self.result_ordinal,
            "nested_path": list(self.nested_path),
            "provider_field": self.provider_field,
            "field_occurrence_ordinal": self.field_occurrence_ordinal,
            "request_scope_sha256": self.request_scope_sha256,
            "field_fate_contract_sha256": self.field_fate_contract_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "temporal_scope_kind": self.temporal_scope_kind.value,
            "temporal_scope_value": self.temporal_scope_value,
            "state": self.state.value,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "request_observation_sha256": self.request_observation_sha256,
            "provider_call_sha256": self.provider_call_sha256,
            "provider_request_sha256": self.provider_request_sha256,
            "result_occurrence_sha256": self.result_occurrence_sha256,
            "logical_result_receipt_sha256": self.logical_result_receipt_sha256,
            "route_receipt_sha256": self.route_receipt_sha256,
            "typed_value_receipt_sha256": self.typed_value_receipt_sha256,
            "reconstruction_receipt_sha256": self.reconstruction_receipt_sha256,
            "proofs_equal": self.proofs_equal,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_payload(), "observation_id": self.observation_id}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_temporal_field_evidence_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "parent_candidate_sha256",
                "authority_generation_sha256",
                "observation_id",
                "cell_id",
                "physical_call_id",
                "route_request_member_id",
                "route_id",
                "endpoint_name",
                "result_name",
                "result_ordinal",
                "nested_path",
                "provider_field",
                "field_occurrence_ordinal",
                "request_scope_sha256",
                "field_fate_contract_sha256",
                "temporal_contract_sha256",
                "temporal_scope_kind",
                "temporal_scope_value",
                "state",
                "raw_authority_bundle_sha256",
                "request_observation_sha256",
                "provider_call_sha256",
                "provider_request_sha256",
                "result_occurrence_sha256",
                "logical_result_receipt_sha256",
                "route_receipt_sha256",
                "typed_value_receipt_sha256",
                "reconstruction_receipt_sha256",
                "proofs_equal",
            }
        )
        _require_exact_keys(payload, expected=expected, label="field observation")
        _require_schema_identity(payload, kind=cls.kind, label="field observation")
        if type(payload["state"]) is not str:
            raise TemporalFieldEvidenceContractError("field observation state is invalid")
        return cls(
            parent_candidate_sha256=cast("str", payload["parent_candidate_sha256"]),
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            observation_id=cast("str", payload["observation_id"]),
            cell_id=cast("str", payload["cell_id"]),
            physical_call_id=cast("str", payload["physical_call_id"]),
            route_request_member_id=cast("str", payload["route_request_member_id"]),
            route_id=cast("str", payload["route_id"]),
            endpoint_name=cast("str", payload["endpoint_name"]),
            result_name=cast("str", payload["result_name"]),
            result_ordinal=cast("int", payload["result_ordinal"]),
            nested_path=_nested_path_from_payload(payload["nested_path"]),
            provider_field=cast("str", payload["provider_field"]),
            field_occurrence_ordinal=cast("int", payload["field_occurrence_ordinal"]),
            request_scope_sha256=cast("str", payload["request_scope_sha256"]),
            field_fate_contract_sha256=cast("str", payload["field_fate_contract_sha256"]),
            temporal_contract_sha256=cast("str", payload["temporal_contract_sha256"]),
            temporal_scope_kind=_scope_kind_from_payload(payload["temporal_scope_kind"]),
            temporal_scope_value=cast("str | int", payload["temporal_scope_value"]),
            state=FieldEvidenceStateV1(payload["state"]),
            raw_authority_bundle_sha256=cast("str", payload["raw_authority_bundle_sha256"]),
            request_observation_sha256=cast("str", payload["request_observation_sha256"]),
            provider_call_sha256=cast("str", payload["provider_call_sha256"]),
            provider_request_sha256=cast("str", payload["provider_request_sha256"]),
            result_occurrence_sha256=cast("str", payload["result_occurrence_sha256"]),
            logical_result_receipt_sha256=cast("str", payload["logical_result_receipt_sha256"]),
            route_receipt_sha256=cast("str", payload["route_receipt_sha256"]),
            typed_value_receipt_sha256=cast("str", payload["typed_value_receipt_sha256"]),
            reconstruction_receipt_sha256=cast("str", payload["reconstruction_receipt_sha256"]),
            proofs_equal=cast("Literal[True]", payload["proofs_equal"]),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw, label="field observation"))
        if result.canonical_bytes != raw:
            raise TemporalFieldEvidenceContractError(
                "field observation differs after strict reconstruction"
            )
        return result


@dataclass(frozen=True, slots=True)
class FieldEvidenceCellV1:
    """One exact parent denominator cell with its derived evidence disposition."""

    authority_generation_sha256: str
    parent_cell_sha256: str
    cell_id: str
    physical_call_id: str
    route_request_member_id: str
    route_id: str
    endpoint_name: str
    result_name: str
    result_ordinal: int
    nested_path: tuple[NestedPathSegment, ...]
    provider_field: str
    field_occurrence_ordinal: int
    request_scope_sha256: str
    field_fate_contract_sha256: str
    temporal_contract_sha256: str
    temporal_scope_kind: TemporalScopeKind
    temporal_scope_value: str | int
    parent_state: Literal["evidence_insufficient"]
    state: str
    disposition: FieldEvidenceDispositionV1
    observation_ids: tuple[str, ...]
    observed_states: tuple[str, ...]

    schema_version: ClassVar[int] = TEMPORAL_FIELD_EVIDENCE_SCHEMA_VERSION
    kind: ClassVar[str] = "temporal_field_evidence_cell_v1"

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_sha256(self.parent_cell_sha256, field_name="parent_cell_sha256")
        _require_safe_id(self.cell_id, field_name="cell_id")
        _require_safe_id(self.physical_call_id, field_name="physical_call_id")
        _require_safe_id(
            self.route_request_member_id,
            field_name="route_request_member_id",
        )
        _require_safe_id(self.route_id, field_name="route_id")
        _require_safe_id(self.endpoint_name, field_name="endpoint_name")
        _require_text(self.result_name, field_name="result_name")
        _require_nonnegative_int(self.result_ordinal, field_name="result_ordinal")
        object.__setattr__(self, "nested_path", _nested_path(self.nested_path))
        _require_text(self.provider_field, field_name="provider_field")
        _require_nonnegative_int(
            self.field_occurrence_ordinal,
            field_name="field_occurrence_ordinal",
        )
        for name in (
            "request_scope_sha256",
            "field_fate_contract_sha256",
            "temporal_contract_sha256",
        ):
            _require_sha256(getattr(self, name), field_name=name)
        kind = _require_scope_kind(self.temporal_scope_kind)
        object.__setattr__(
            self,
            "temporal_scope_value",
            _scope_value(kind, self.temporal_scope_value),
        )
        if type(self.parent_state) is not str or self.parent_state != "evidence_insufficient":
            raise TemporalFieldEvidenceContractError(
                "parent cell state must remain evidence_insufficient"
            )
        if type(self.state) is not str:
            raise TemporalFieldEvidenceContractError("field cell state must be an exact string")
        if type(self.disposition) is not FieldEvidenceDispositionV1:
            raise TemporalFieldEvidenceContractError(
                "field disposition must be an exact FieldEvidenceDispositionV1"
            )
        disposition = self.disposition
        if type(self.observation_ids) is not tuple or any(
            type(item) is not str for item in self.observation_ids
        ):
            raise TemporalFieldEvidenceContractError("observation_ids must be an exact tuple")
        if self.observation_ids != tuple(sorted(set(self.observation_ids))):
            raise TemporalFieldEvidenceContractError(
                "observation_ids must be canonical sorted and unique"
            )
        for item in self.observation_ids:
            _require_safe_id(item, field_name="observation_id")
        if type(self.observed_states) is not tuple or any(
            type(item) is not str for item in self.observed_states
        ):
            raise TemporalFieldEvidenceContractError("observed_states must be an exact tuple")
        if self.observed_states != tuple(sorted(set(self.observed_states))):
            raise TemporalFieldEvidenceContractError(
                "observed_states must be canonical sorted and unique"
            )
        for item in self.observed_states:
            try:
                FieldEvidenceStateV1(item)
            except ValueError as exc:
                raise TemporalFieldEvidenceContractError("observed state is invalid") from exc
        expected_state, expected_disposition = _classify_states(self.observed_states)
        if self.state != expected_state or disposition is not expected_disposition:
            raise TemporalFieldEvidenceContractError(
                "field cell disposition differs from its exact observed states"
            )
        if bool(self.observation_ids) != bool(self.observed_states):
            raise TemporalFieldEvidenceContractError(
                "field cell observation identifiers and states disagree on presence"
            )
        if self.parent_cell_sha256 != canonical_temporal_field_evidence_sha256(
            self.to_parent_cell_dict()
        ):
            raise TemporalFieldEvidenceContractError(
                "parent_cell_sha256 differs from the reconstructed denominator cell"
            )

    @classmethod
    def from_parent(
        cls,
        cell: FieldPeriodDenominatorCellV1,
        observations: Sequence[FieldObservationBindingV1],
    ) -> FieldEvidenceCellV1:
        ordered = tuple(sorted(observations, key=lambda item: item.observation_id))
        states = tuple(sorted({item.state.value for item in ordered}))
        state, disposition = _classify_states(states)
        return cls(
            authority_generation_sha256=cell.authority_generation_sha256,
            parent_cell_sha256=canonical_temporal_field_evidence_sha256(cell.to_dict()),
            cell_id=cell.cell_id,
            physical_call_id=cell.physical_call_id,
            route_request_member_id=cell.route_request_member_id,
            route_id=cell.route_id,
            endpoint_name=cell.endpoint_name,
            result_name=cell.result_name,
            result_ordinal=cell.result_ordinal,
            nested_path=cell.nested_path,
            provider_field=cell.provider_field,
            field_occurrence_ordinal=cell.field_occurrence_ordinal,
            request_scope_sha256=cell.request_scope_sha256,
            field_fate_contract_sha256=cell.field_fate_contract_sha256,
            temporal_contract_sha256=cell.temporal_contract_sha256,
            temporal_scope_kind=cell.temporal_scope_kind,
            temporal_scope_value=cell.temporal_scope_value,
            parent_state="evidence_insufficient",
            state=state,
            disposition=disposition,
            observation_ids=tuple(item.observation_id for item in ordered),
            observed_states=states,
        )

    def to_parent_cell_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "field_period_denominator_cell_v1",
            "authority_generation_sha256": self.authority_generation_sha256,
            "cell_id": self.cell_id,
            "physical_call_id": self.physical_call_id,
            "route_request_member_id": self.route_request_member_id,
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "result_name": self.result_name,
            "result_ordinal": self.result_ordinal,
            "nested_path": list(self.nested_path),
            "provider_field": self.provider_field,
            "field_occurrence_ordinal": self.field_occurrence_ordinal,
            "request_scope_sha256": self.request_scope_sha256,
            "field_fate_contract_sha256": self.field_fate_contract_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "temporal_scope_kind": self.temporal_scope_kind.value,
            "temporal_scope_value": self.temporal_scope_value,
            "state": self.parent_state,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "parent_cell_sha256": self.parent_cell_sha256,
            "cell_id": self.cell_id,
            "physical_call_id": self.physical_call_id,
            "route_request_member_id": self.route_request_member_id,
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "result_name": self.result_name,
            "result_ordinal": self.result_ordinal,
            "nested_path": list(self.nested_path),
            "provider_field": self.provider_field,
            "field_occurrence_ordinal": self.field_occurrence_ordinal,
            "request_scope_sha256": self.request_scope_sha256,
            "field_fate_contract_sha256": self.field_fate_contract_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "temporal_scope_kind": self.temporal_scope_kind.value,
            "temporal_scope_value": self.temporal_scope_value,
            "parent_state": self.parent_state,
            "state": self.state,
            "disposition": self.disposition.value,
            "observation_ids": list(self.observation_ids),
            "observed_states": list(self.observed_states),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "authority_generation_sha256",
                "parent_cell_sha256",
                "cell_id",
                "physical_call_id",
                "route_request_member_id",
                "route_id",
                "endpoint_name",
                "result_name",
                "result_ordinal",
                "nested_path",
                "provider_field",
                "field_occurrence_ordinal",
                "request_scope_sha256",
                "field_fate_contract_sha256",
                "temporal_contract_sha256",
                "temporal_scope_kind",
                "temporal_scope_value",
                "parent_state",
                "state",
                "disposition",
                "observation_ids",
                "observed_states",
            }
        )
        _require_exact_keys(payload, expected=expected, label="field evidence cell")
        _require_schema_identity(payload, kind=cls.kind, label="field evidence cell")
        for name in ("parent_state", "state", "disposition"):
            if type(payload[name]) is not str:
                raise TemporalFieldEvidenceContractError(
                    f"field evidence cell {name} must be an exact string"
                )
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            parent_cell_sha256=cast("str", payload["parent_cell_sha256"]),
            cell_id=cast("str", payload["cell_id"]),
            physical_call_id=cast("str", payload["physical_call_id"]),
            route_request_member_id=cast("str", payload["route_request_member_id"]),
            route_id=cast("str", payload["route_id"]),
            endpoint_name=cast("str", payload["endpoint_name"]),
            result_name=cast("str", payload["result_name"]),
            result_ordinal=cast("int", payload["result_ordinal"]),
            nested_path=_nested_path_from_payload(payload["nested_path"]),
            provider_field=cast("str", payload["provider_field"]),
            field_occurrence_ordinal=cast("int", payload["field_occurrence_ordinal"]),
            request_scope_sha256=cast("str", payload["request_scope_sha256"]),
            field_fate_contract_sha256=cast("str", payload["field_fate_contract_sha256"]),
            temporal_contract_sha256=cast("str", payload["temporal_contract_sha256"]),
            temporal_scope_kind=_scope_kind_from_payload(payload["temporal_scope_kind"]),
            temporal_scope_value=cast("str | int", payload["temporal_scope_value"]),
            parent_state=cast("Literal['evidence_insufficient']", payload["parent_state"]),
            state=cast("str", payload["state"]),
            disposition=FieldEvidenceDispositionV1(cast("str", payload["disposition"])),
            observation_ids=tuple(
                cast("str", item)
                for item in _list(
                    payload["observation_ids"],
                    field_name="observation_ids",
                    maximum=_MAX_OBSERVATIONS,
                )
            ),
            observed_states=tuple(
                cast("str", item)
                for item in _list(
                    payload["observed_states"],
                    field_name="observed_states",
                    maximum=len(FieldEvidenceStateV1),
                )
            ),
        )


def _classify_states(
    states: Sequence[str],
) -> tuple[str, FieldEvidenceDispositionV1]:
    if not states:
        return "evidence_insufficient", FieldEvidenceDispositionV1.UNRESOLVED
    if len(states) > 1:
        return "evidence_insufficient", FieldEvidenceDispositionV1.CONFLICT
    # No current dependency supplies a typed field-value/reconstruction receipt
    # authority.  A single caller assertion is therefore conserved but cannot
    # establish even a populated/null/empty state.
    FieldEvidenceStateV1(states[0])
    return "evidence_insufficient", FieldEvidenceDispositionV1.UNRESOLVED


@dataclass(frozen=True, slots=True)
class UnjoinableFieldObservationV1:
    """Lossless summary of a well-formed observation excluded from the join."""

    observation_id: str
    cell_id: str
    reason: UnjoinableReasonV1
    observation_sha256: str

    schema_version: ClassVar[int] = TEMPORAL_FIELD_EVIDENCE_SCHEMA_VERSION
    kind: ClassVar[str] = "unjoinable_field_observation_v1"

    def __post_init__(self) -> None:
        _require_safe_id(self.observation_id, field_name="observation_id")
        _require_safe_id(self.cell_id, field_name="cell_id")
        if type(self.reason) is not UnjoinableReasonV1:
            raise TemporalFieldEvidenceContractError(
                "unjoinable reason must be an exact UnjoinableReasonV1"
            )
        _require_sha256(self.observation_sha256, field_name="observation_sha256")

    @classmethod
    def from_observation(
        cls,
        observation: FieldObservationBindingV1,
        *,
        reason: UnjoinableReasonV1,
    ) -> UnjoinableFieldObservationV1:
        return cls(
            observation_id=observation.observation_id,
            cell_id=observation.cell_id,
            reason=reason,
            observation_sha256=canonical_temporal_field_evidence_sha256(observation.to_dict()),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "observation_id": self.observation_id,
            "cell_id": self.cell_id,
            "reason": self.reason.value,
            "observation_sha256": self.observation_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "observation_id",
                    "cell_id",
                    "reason",
                    "observation_sha256",
                }
            ),
            label="unjoinable observation",
        )
        _require_schema_identity(payload, kind=cls.kind, label="unjoinable observation")
        if type(payload["reason"]) is not str:
            raise TemporalFieldEvidenceContractError("unjoinable observation reason is invalid")
        return cls(
            observation_id=cast("str", payload["observation_id"]),
            cell_id=cast("str", payload["cell_id"]),
            reason=UnjoinableReasonV1(payload["reason"]),
            observation_sha256=cast("str", payload["observation_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class TemporalFieldEvidenceCandidateV1:
    """Conserved, nonterminal partition of one exact parent denominator."""

    authority_generation_sha256: str
    parent_candidate_sha256: str
    parent_proof_sha256: str
    parent_source_inputs_sha256: str
    parent_field_period_inventory_sha256: str
    parent_blocker_inventory_sha256: str
    denominator_count: int
    denominator_inventory_sha256: str
    evidence_cells: tuple[FieldEvidenceCellV1, ...]
    joined_observations: tuple[FieldObservationBindingV1, ...]
    unjoinable_observations: tuple[UnjoinableFieldObservationV1, ...]
    parent_blockers: tuple[CandidateBlockerV1, ...]
    evidenced_cell_ids: tuple[str, ...]
    unresolved_cell_ids: tuple[str, ...]
    conflict_cell_ids: tuple[str, ...]
    evidence_cell_inventory_sha256: str
    joined_observation_inventory_sha256: str
    unjoinable_observation_inventory_sha256: str
    parent_blocker_inventory_sha256_copy: str
    evidenced_partition_sha256: str
    unresolved_partition_sha256: str
    conflict_partition_sha256: str
    denominator_admitted: Literal[False] = False
    terminal: Literal[False] = False
    release_eligible: Literal[False] = False

    schema_version: ClassVar[int] = TEMPORAL_FIELD_EVIDENCE_SCHEMA_VERSION
    kind: ClassVar[str] = "temporal_field_evidence_candidate_v1"

    def __post_init__(self) -> None:
        authority = _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        for name in (
            "parent_candidate_sha256",
            "parent_proof_sha256",
            "parent_source_inputs_sha256",
            "parent_field_period_inventory_sha256",
            "parent_blocker_inventory_sha256",
            "denominator_inventory_sha256",
            "evidence_cell_inventory_sha256",
            "joined_observation_inventory_sha256",
            "unjoinable_observation_inventory_sha256",
            "parent_blocker_inventory_sha256_copy",
            "evidenced_partition_sha256",
            "unresolved_partition_sha256",
            "conflict_partition_sha256",
        ):
            _require_sha256(getattr(self, name), field_name=name)
        _require_nonnegative_int(self.denominator_count, field_name="denominator_count")
        cells = _canonical_tuple(
            self.evidence_cells,
            label="evidence_cells",
            item_type=FieldEvidenceCellV1,
            decoder=FieldEvidenceCellV1.from_dict,
            key=lambda item: item.cell_id,
            maximum=_MAX_CELLS,
        )
        observations = _canonical_tuple(
            self.joined_observations,
            label="joined_observations",
            item_type=FieldObservationBindingV1,
            decoder=FieldObservationBindingV1.from_dict,
            key=lambda item: item.observation_id,
            maximum=_MAX_OBSERVATIONS,
        )
        unjoinable = _canonical_tuple(
            self.unjoinable_observations,
            label="unjoinable_observations",
            item_type=UnjoinableFieldObservationV1,
            decoder=UnjoinableFieldObservationV1.from_dict,
            key=lambda item: item.observation_id,
            maximum=_MAX_OBSERVATIONS,
        )
        blockers = _canonical_tuple(
            self.parent_blockers,
            label="parent_blockers",
            item_type=CandidateBlockerV1,
            decoder=CandidateBlockerV1.from_dict,
            key=lambda item: item.identity_sha256,
            maximum=_MAX_OBSERVATIONS,
        )
        for name in (
            "evidenced_cell_ids",
            "unresolved_cell_ids",
            "conflict_cell_ids",
        ):
            values = getattr(self, name)
            if type(values) is not tuple or values != tuple(sorted(set(values))):
                raise TemporalFieldEvidenceContractError(
                    f"{name} must be a canonical sorted unique tuple"
                )
            for value in values:
                _require_safe_id(value, field_name=name)
        if self.denominator_count != len(cells):
            raise TemporalFieldEvidenceContractError(
                "denominator_count differs from the conserved evidence cells"
            )
        parent_cells = [item.to_parent_cell_dict() for item in cells]
        denominator_digest = canonical_temporal_field_evidence_sha256(parent_cells)
        if (
            self.denominator_inventory_sha256 != denominator_digest
            or self.parent_field_period_inventory_sha256 != denominator_digest
        ):
            raise TemporalFieldEvidenceContractError(
                "denominator inventory differs from exact reconstructed parent cells"
            )
        if any(item.authority_generation_sha256 != authority for item in cells):
            raise TemporalFieldEvidenceContractError("evidence cells use mixed authority")
        if any(
            item.authority_generation_sha256 != authority
            or item.parent_candidate_sha256 != self.parent_candidate_sha256
            for item in observations
        ):
            raise TemporalFieldEvidenceContractError(
                "joined observations are not bound to the exact parent authority"
            )
        cell_by_id = {item.cell_id: item for item in cells}
        observations_by_cell: dict[str, list[FieldObservationBindingV1]] = {
            cell_id: [] for cell_id in cell_by_id
        }
        for observation in observations:
            cell = cell_by_id.get(observation.cell_id)
            if cell is None or not _observation_matches_cell(observation, cell):
                raise TemporalFieldEvidenceContractError(
                    "joined observation differs from its exact denominator cell"
                )
            observations_by_cell[observation.cell_id].append(observation)
        for cell in cells:
            expected_ids = tuple(
                sorted(item.observation_id for item in observations_by_cell[cell.cell_id])
            )
            expected_states = tuple(
                sorted({item.state.value for item in observations_by_cell[cell.cell_id]})
            )
            if cell.observation_ids != expected_ids or cell.observed_states != expected_states:
                raise TemporalFieldEvidenceContractError(
                    "evidence cell differs from its joined observation inventory"
                )
        expected_partitions = _partitions(cells)
        if (
            self.evidenced_cell_ids,
            self.unresolved_cell_ids,
            self.conflict_cell_ids,
        ) != expected_partitions:
            raise TemporalFieldEvidenceContractError(
                "evidence partitions do not exactly conserve the denominator"
            )
        if self.evidenced_cell_ids:
            raise TemporalFieldEvidenceContractError(
                "assertion-only observations cannot populate the evidenced partition"
            )
        all_ids = (
            *self.evidenced_cell_ids,
            *self.unresolved_cell_ids,
            *self.conflict_cell_ids,
        )
        if len(all_ids) != len(cells) or set(all_ids) != set(cell_by_id):
            raise TemporalFieldEvidenceContractError(
                "evidence partitions are not disjoint and exhaustive"
            )
        joined_ids = {item.observation_id for item in observations}
        if joined_ids & {item.observation_id for item in unjoinable}:
            raise TemporalFieldEvidenceContractError(
                "an observation cannot be both joined and unjoinable"
            )
        expected_digests = {
            "evidence_cell_inventory_sha256": canonical_temporal_field_evidence_sha256(
                [item.to_dict() for item in cells]
            ),
            "joined_observation_inventory_sha256": canonical_temporal_field_evidence_sha256(
                [item.to_dict() for item in observations]
            ),
            "unjoinable_observation_inventory_sha256": canonical_temporal_field_evidence_sha256(
                [item.to_dict() for item in unjoinable]
            ),
            "parent_blocker_inventory_sha256_copy": canonical_temporal_field_evidence_sha256(
                [item.to_dict() for item in blockers]
            ),
            "evidenced_partition_sha256": canonical_temporal_field_evidence_sha256(
                list(self.evidenced_cell_ids)
            ),
            "unresolved_partition_sha256": canonical_temporal_field_evidence_sha256(
                list(self.unresolved_cell_ids)
            ),
            "conflict_partition_sha256": canonical_temporal_field_evidence_sha256(
                list(self.conflict_cell_ids)
            ),
        }
        for name, expected in expected_digests.items():
            if getattr(self, name) != expected:
                raise TemporalFieldEvidenceContractError(f"{name} differs from its inventory")
        if self.parent_blocker_inventory_sha256_copy != self.parent_blocker_inventory_sha256:
            raise TemporalFieldEvidenceContractError("parent blockers were not conserved exactly")
        if (
            self.denominator_admitted is not False
            or self.terminal is not False
            or self.release_eligible is not False
        ):
            raise TemporalFieldEvidenceContractError(
                "temporal-field evidence cannot admit a denominator or finality"
            )
        object.__setattr__(self, "evidence_cells", cells)
        object.__setattr__(self, "joined_observations", observations)
        object.__setattr__(self, "unjoinable_observations", unjoinable)
        object.__setattr__(self, "parent_blockers", blockers)

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_temporal_field_evidence_json_bytes(self.to_dict())

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "parent_candidate_sha256": self.parent_candidate_sha256,
            "parent_proof_sha256": self.parent_proof_sha256,
            "parent_source_inputs_sha256": self.parent_source_inputs_sha256,
            "parent_field_period_inventory_sha256": (self.parent_field_period_inventory_sha256),
            "parent_blocker_inventory_sha256": self.parent_blocker_inventory_sha256,
            "denominator_count": self.denominator_count,
            "denominator_inventory_sha256": self.denominator_inventory_sha256,
            "evidence_cell_count": len(self.evidence_cells),
            "joined_observation_count": len(self.joined_observations),
            "unjoinable_observation_count": len(self.unjoinable_observations),
            "parent_blocker_count": len(self.parent_blockers),
            "evidenced_cell_count": len(self.evidenced_cell_ids),
            "unresolved_cell_count": len(self.unresolved_cell_ids),
            "conflict_cell_count": len(self.conflict_cell_ids),
            "evidence_cell_inventory_sha256": self.evidence_cell_inventory_sha256,
            "joined_observation_inventory_sha256": (self.joined_observation_inventory_sha256),
            "unjoinable_observation_inventory_sha256": (
                self.unjoinable_observation_inventory_sha256
            ),
            "parent_blocker_inventory_sha256_copy": (self.parent_blocker_inventory_sha256_copy),
            "evidenced_partition_sha256": self.evidenced_partition_sha256,
            "unresolved_partition_sha256": self.unresolved_partition_sha256,
            "conflict_partition_sha256": self.conflict_partition_sha256,
            "evidence_cells": [item.to_dict() for item in self.evidence_cells],
            "joined_observations": [item.to_dict() for item in self.joined_observations],
            "unjoinable_observations": [item.to_dict() for item in self.unjoinable_observations],
            "parent_blockers": [item.to_dict() for item in self.parent_blockers],
            "evidenced_cell_ids": list(self.evidenced_cell_ids),
            "unresolved_cell_ids": list(self.unresolved_cell_ids),
            "conflict_cell_ids": list(self.conflict_cell_ids),
            "denominator_admitted": self.denominator_admitted,
            "terminal": self.terminal,
            "release_eligible": self.release_eligible,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "authority_generation_sha256",
                "parent_candidate_sha256",
                "parent_proof_sha256",
                "parent_source_inputs_sha256",
                "parent_field_period_inventory_sha256",
                "parent_blocker_inventory_sha256",
                "denominator_count",
                "denominator_inventory_sha256",
                "evidence_cell_count",
                "joined_observation_count",
                "unjoinable_observation_count",
                "parent_blocker_count",
                "evidenced_cell_count",
                "unresolved_cell_count",
                "conflict_cell_count",
                "evidence_cell_inventory_sha256",
                "joined_observation_inventory_sha256",
                "unjoinable_observation_inventory_sha256",
                "parent_blocker_inventory_sha256_copy",
                "evidenced_partition_sha256",
                "unresolved_partition_sha256",
                "conflict_partition_sha256",
                "evidence_cells",
                "joined_observations",
                "unjoinable_observations",
                "parent_blockers",
                "evidenced_cell_ids",
                "unresolved_cell_ids",
                "conflict_cell_ids",
                "denominator_admitted",
                "terminal",
                "release_eligible",
            }
        )
        _require_exact_keys(payload, expected=expected, label="temporal-field candidate")
        _require_schema_identity(payload, kind=cls.kind, label="temporal-field candidate")
        cells = tuple(
            FieldEvidenceCellV1.from_dict(_mapping(item, field_name="evidence cell"))
            for item in _list(
                payload["evidence_cells"],
                field_name="evidence_cells",
                maximum=_MAX_CELLS,
            )
        )
        observations = tuple(
            FieldObservationBindingV1.from_dict(_mapping(item, field_name="joined observation"))
            for item in _list(
                payload["joined_observations"],
                field_name="joined_observations",
                maximum=_MAX_OBSERVATIONS,
            )
        )
        unjoinable = tuple(
            UnjoinableFieldObservationV1.from_dict(
                _mapping(item, field_name="unjoinable observation")
            )
            for item in _list(
                payload["unjoinable_observations"],
                field_name="unjoinable_observations",
                maximum=_MAX_OBSERVATIONS,
            )
        )
        blockers = tuple(
            CandidateBlockerV1.from_dict(_mapping(item, field_name="parent blocker"))
            for item in _list(
                payload["parent_blockers"],
                field_name="parent_blockers",
                maximum=_MAX_OBSERVATIONS,
            )
        )
        counts = {
            "evidence_cell_count": len(cells),
            "joined_observation_count": len(observations),
            "unjoinable_observation_count": len(unjoinable),
            "parent_blocker_count": len(blockers),
        }
        for name, expected_count in counts.items():
            observed_count = _require_nonnegative_int(payload[name], field_name=name)
            if observed_count != expected_count:
                raise TemporalFieldEvidenceContractError(f"{name} differs from its inventory")
        evidenced_ids = _id_tuple_from_payload(payload["evidenced_cell_ids"], "evidenced")
        unresolved_ids = _id_tuple_from_payload(payload["unresolved_cell_ids"], "unresolved")
        conflict_ids = _id_tuple_from_payload(payload["conflict_cell_ids"], "conflict")
        partition_counts = {
            "evidenced_cell_count": len(evidenced_ids),
            "unresolved_cell_count": len(unresolved_ids),
            "conflict_cell_count": len(conflict_ids),
        }
        for name, expected_count in partition_counts.items():
            observed_count = _require_nonnegative_int(payload[name], field_name=name)
            if observed_count != expected_count:
                raise TemporalFieldEvidenceContractError(f"{name} differs from its partition")
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            parent_candidate_sha256=cast("str", payload["parent_candidate_sha256"]),
            parent_proof_sha256=cast("str", payload["parent_proof_sha256"]),
            parent_source_inputs_sha256=cast("str", payload["parent_source_inputs_sha256"]),
            parent_field_period_inventory_sha256=cast(
                "str", payload["parent_field_period_inventory_sha256"]
            ),
            parent_blocker_inventory_sha256=cast("str", payload["parent_blocker_inventory_sha256"]),
            denominator_count=cast("int", payload["denominator_count"]),
            denominator_inventory_sha256=cast("str", payload["denominator_inventory_sha256"]),
            evidence_cells=cells,
            joined_observations=observations,
            unjoinable_observations=unjoinable,
            parent_blockers=blockers,
            evidenced_cell_ids=evidenced_ids,
            unresolved_cell_ids=unresolved_ids,
            conflict_cell_ids=conflict_ids,
            evidence_cell_inventory_sha256=cast("str", payload["evidence_cell_inventory_sha256"]),
            joined_observation_inventory_sha256=cast(
                "str", payload["joined_observation_inventory_sha256"]
            ),
            unjoinable_observation_inventory_sha256=cast(
                "str", payload["unjoinable_observation_inventory_sha256"]
            ),
            parent_blocker_inventory_sha256_copy=cast(
                "str", payload["parent_blocker_inventory_sha256_copy"]
            ),
            evidenced_partition_sha256=cast("str", payload["evidenced_partition_sha256"]),
            unresolved_partition_sha256=cast("str", payload["unresolved_partition_sha256"]),
            conflict_partition_sha256=cast("str", payload["conflict_partition_sha256"]),
            denominator_admitted=cast("Literal[False]", payload["denominator_admitted"]),
            terminal=cast("Literal[False]", payload["terminal"]),
            release_eligible=cast("Literal[False]", payload["release_eligible"]),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw, label="temporal-field candidate"))
        if result.canonical_bytes != raw:
            raise TemporalFieldEvidenceContractError(
                "temporal-field candidate differs after strict reconstruction"
            )
        return result


def _id_tuple_from_payload(value: object, label: str) -> tuple[str, ...]:
    return tuple(
        cast("str", item)
        for item in _list(value, field_name=f"{label}_cell_ids", maximum=_MAX_CELLS)
    )


def _canonical_tuple[T](
    value: object,
    *,
    label: str,
    item_type: type[T],
    decoder: Callable[[Mapping[str, object]], T],
    key: Callable[[T], str],
    maximum: int,
) -> tuple[T, ...]:
    if type(value) is not tuple or len(value) > maximum:
        raise TemporalFieldEvidenceContractError(f"{label} must be an exact bounded tuple")
    rebuilt = tuple(
        _strict_dto(item, dto_type=item_type, decoder=decoder, label=f"{label} item")
        for item in value
    )
    expected = tuple(sorted(rebuilt, key=key))
    identities = tuple(key(item) for item in rebuilt)
    if rebuilt != expected or len(identities) != len(set(identities)):
        raise TemporalFieldEvidenceContractError(f"{label} must be canonical sorted and unique")
    return rebuilt


def _strict_parent_candidate(
    value: object,
) -> RequestUniverseCandidateGenerationV1:
    if type(value) is not RequestUniverseCandidateGenerationV1:
        raise TemporalFieldEvidenceContractError(
            "parent_candidate must be an exact RequestUniverseCandidateGenerationV1"
        )
    try:
        raw = value.canonical_bytes
        rebuilt = RequestUniverseCandidateGenerationV1.from_canonical_bytes(raw)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TemporalFieldEvidenceContractError(
            "parent candidate fails strict nested reconstruction"
        ) from exc
    if rebuilt.canonical_bytes != raw:
        raise TemporalFieldEvidenceContractError(
            "parent candidate differs after strict nested reconstruction"
        )
    return rebuilt


def _strict_parent_proof(
    value: object,
) -> RequestUniverseCandidateIndependentProofV1:
    if type(value) is not RequestUniverseCandidateIndependentProofV1:
        raise TemporalFieldEvidenceContractError(
            "parent_proof must be an exact independent candidate proof"
        )
    try:
        raw = value.canonical_bytes
        rebuilt = RequestUniverseCandidateIndependentProofV1.from_canonical_bytes(raw)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise TemporalFieldEvidenceContractError(
            "parent proof fails strict nested reconstruction"
        ) from exc
    if rebuilt.canonical_bytes != raw:
        raise TemporalFieldEvidenceContractError(
            "parent proof differs after strict nested reconstruction"
        )
    return rebuilt


def _observation_identity(observation: FieldObservationBindingV1) -> tuple[object, ...]:
    return (
        observation.cell_id,
        observation.physical_call_id,
        observation.route_request_member_id,
        observation.route_id,
        observation.endpoint_name,
        observation.result_name,
        observation.result_ordinal,
        observation.nested_path,
        observation.provider_field,
        observation.field_occurrence_ordinal,
        observation.request_scope_sha256,
        observation.field_fate_contract_sha256,
        observation.temporal_contract_sha256,
        observation.temporal_scope_kind,
        observation.temporal_scope_value,
    )


def _cell_identity(cell: FieldEvidenceCellV1) -> tuple[object, ...]:
    return (
        cell.cell_id,
        cell.physical_call_id,
        cell.route_request_member_id,
        cell.route_id,
        cell.endpoint_name,
        cell.result_name,
        cell.result_ordinal,
        cell.nested_path,
        cell.provider_field,
        cell.field_occurrence_ordinal,
        cell.request_scope_sha256,
        cell.field_fate_contract_sha256,
        cell.temporal_contract_sha256,
        cell.temporal_scope_kind,
        cell.temporal_scope_value,
    )


def _observation_matches_cell(
    observation: FieldObservationBindingV1,
    cell: FieldEvidenceCellV1,
) -> bool:
    return _exact_typed_equal(_observation_identity(observation), _cell_identity(cell))


def _observation_matches_parent(
    observation: FieldObservationBindingV1,
    cell: FieldPeriodDenominatorCellV1,
) -> bool:
    return _exact_typed_equal(
        _observation_identity(observation),
        (
            cell.cell_id,
            cell.physical_call_id,
            cell.route_request_member_id,
            cell.route_id,
            cell.endpoint_name,
            cell.result_name,
            cell.result_ordinal,
            cell.nested_path,
            cell.provider_field,
            cell.field_occurrence_ordinal,
            cell.request_scope_sha256,
            cell.field_fate_contract_sha256,
            cell.temporal_contract_sha256,
            cell.temporal_scope_kind,
            cell.temporal_scope_value,
        ),
    )


def _partitions(
    cells: Sequence[FieldEvidenceCellV1],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    evidenced = tuple(
        item.cell_id for item in cells if item.disposition is FieldEvidenceDispositionV1.EVIDENCED
    )
    unresolved = tuple(
        item.cell_id for item in cells if item.disposition is FieldEvidenceDispositionV1.UNRESOLVED
    )
    conflict = tuple(
        item.cell_id for item in cells if item.disposition is FieldEvidenceDispositionV1.CONFLICT
    )
    return evidenced, unresolved, conflict


def _validate_parent_binding(
    candidate: RequestUniverseCandidateGenerationV1,
    proof: RequestUniverseCandidateIndependentProofV1,
) -> None:
    if (
        proof.authority_generation_sha256 != candidate.authority_generation_sha256
        or proof.source_inputs_sha256 != candidate.source_inputs_sha256
        or proof.candidate_generation_sha256 != candidate.identity_sha256
        or proof.logical_call_inventory_sha256 != candidate.logical_call_inventory_sha256
        or proof.route_member_inventory_sha256 != candidate.route_member_inventory_sha256
        or proof.field_period_inventory_sha256 != candidate.field_period_inventory_sha256
        or proof.blocker_inventory_sha256 != candidate.blocker_inventory_sha256
        or proof.logical_call_count != len(candidate.logical_calls)
        or proof.route_member_count != len(candidate.route_members)
        or proof.field_period_cell_count != len(candidate.field_period_cells)
        or proof.blocker_count != len(candidate.blockers)
        or proof.exact_inventory_equal is not True
        or proof.candidate_only is not True
        or proof.terminal is not False
        or proof.release_eligible is not False
        or candidate.terminal is not False
        or candidate.release_eligible is not False
    ):
        raise TemporalFieldEvidenceContractError(
            "parent candidate and independent proof are not exactly bound"
        )


def compile_temporal_field_evidence_candidate_v1(
    *,
    parent_candidate: RequestUniverseCandidateGenerationV1,
    parent_proof: RequestUniverseCandidateIndependentProofV1,
    observations: Sequence[FieldObservationBindingV1] = (),
) -> TemporalFieldEvidenceCandidateV1:
    """Conserve one exact parent denominator and partition explicit evidence."""

    parent_candidate = _strict_parent_candidate(parent_candidate)
    parent_proof = _strict_parent_proof(parent_proof)
    if type(observations) is not tuple or len(observations) > _MAX_OBSERVATIONS:
        raise TemporalFieldEvidenceContractError("observations must be an exact bounded tuple")
    _validate_parent_binding(parent_candidate, parent_proof)
    observation_values = tuple(
        _strict_dto(
            item,
            dto_type=FieldObservationBindingV1,
            decoder=FieldObservationBindingV1.from_dict,
            label="field observation",
        )
        for item in observations
    )
    ordered_observations = tuple(sorted(observation_values, key=lambda item: item.observation_id))
    observation_ids = tuple(item.observation_id for item in ordered_observations)
    if len(observation_ids) != len(set(observation_ids)):
        raise TemporalFieldEvidenceContractError("duplicate observation identities are forbidden")

    parent_by_id = {item.cell_id: item for item in parent_candidate.field_period_cells}
    joined: list[FieldObservationBindingV1] = []
    unjoinable: list[UnjoinableFieldObservationV1] = []
    by_cell: dict[str, list[FieldObservationBindingV1]] = {cell_id: [] for cell_id in parent_by_id}
    for observation in ordered_observations:
        reason: UnjoinableReasonV1 | None = None
        parent_cell = parent_by_id.get(observation.cell_id)
        if observation.parent_candidate_sha256 != parent_candidate.identity_sha256:
            reason = UnjoinableReasonV1.PARENT_CANDIDATE_MISMATCH
        elif (
            observation.authority_generation_sha256 != parent_candidate.authority_generation_sha256
        ):
            reason = UnjoinableReasonV1.AUTHORITY_MISMATCH
        elif parent_cell is None:
            reason = UnjoinableReasonV1.CELL_ABSENT
        elif not _observation_matches_parent(observation, parent_cell):
            reason = UnjoinableReasonV1.CELL_IDENTITY_MISMATCH
        if reason is not None:
            unjoinable.append(
                UnjoinableFieldObservationV1.from_observation(
                    observation,
                    reason=reason,
                )
            )
            continue
        joined.append(observation)
        by_cell[observation.cell_id].append(observation)

    evidence_cells = tuple(
        FieldEvidenceCellV1.from_parent(cell, by_cell[cell.cell_id])
        for cell in parent_candidate.field_period_cells
    )
    evidenced_ids, unresolved_ids, conflict_ids = _partitions(evidence_cells)
    unjoinable_tuple = tuple(sorted(unjoinable, key=lambda item: item.observation_id))
    joined_tuple = tuple(sorted(joined, key=lambda item: item.observation_id))
    blockers = parent_candidate.blockers
    return TemporalFieldEvidenceCandidateV1(
        authority_generation_sha256=parent_candidate.authority_generation_sha256,
        parent_candidate_sha256=parent_candidate.identity_sha256,
        parent_proof_sha256=parent_proof.identity_sha256,
        parent_source_inputs_sha256=parent_candidate.source_inputs_sha256,
        parent_field_period_inventory_sha256=parent_candidate.field_period_inventory_sha256,
        parent_blocker_inventory_sha256=parent_candidate.blocker_inventory_sha256,
        denominator_count=len(parent_candidate.field_period_cells),
        denominator_inventory_sha256=parent_candidate.field_period_inventory_sha256,
        evidence_cells=evidence_cells,
        joined_observations=joined_tuple,
        unjoinable_observations=unjoinable_tuple,
        parent_blockers=blockers,
        evidenced_cell_ids=evidenced_ids,
        unresolved_cell_ids=unresolved_ids,
        conflict_cell_ids=conflict_ids,
        evidence_cell_inventory_sha256=canonical_temporal_field_evidence_sha256(
            [item.to_dict() for item in evidence_cells]
        ),
        joined_observation_inventory_sha256=canonical_temporal_field_evidence_sha256(
            [item.to_dict() for item in joined_tuple]
        ),
        unjoinable_observation_inventory_sha256=canonical_temporal_field_evidence_sha256(
            [item.to_dict() for item in unjoinable_tuple]
        ),
        parent_blocker_inventory_sha256_copy=canonical_temporal_field_evidence_sha256(
            [item.to_dict() for item in blockers]
        ),
        evidenced_partition_sha256=canonical_temporal_field_evidence_sha256(list(evidenced_ids)),
        unresolved_partition_sha256=canonical_temporal_field_evidence_sha256(list(unresolved_ids)),
        conflict_partition_sha256=canonical_temporal_field_evidence_sha256(list(conflict_ids)),
        denominator_admitted=False,
        terminal=False,
        release_eligible=False,
    )
