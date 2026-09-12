"""Canonical completion authority for one durable successor-planning wave."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Self, cast

from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.capture_session import (
    CaptureRunScope,
    PrivateGenerationIdentity,
)
from nbadb.orchestrate.successor_planning_generation_contract import PlanningDataMember

__all__ = [
    "PLANNING_WAVE_COMPLETION_RECEIPT_SCHEMA_VERSION",
    "PlanningWaveCallBinding",
    "PlanningWaveCompletionReceipt",
    "PlanningWaveCompletionReceiptError",
    "PlanningWaveMemberBinding",
]

PLANNING_WAVE_COMPLETION_RECEIPT_SCHEMA_VERSION = 2

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}")


class PlanningWaveCompletionReceiptError(ValueError):
    """Raised when planning-wave completion authority is incomplete or drifts."""


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PlanningWaveCompletionReceiptError(
            "planning wave completion authority is not canonical JSON"
        ) from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PlanningWaveCompletionReceiptError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise PlanningWaveCompletionReceiptError(f"{field_name} must be a safe nonempty token")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise PlanningWaveCompletionReceiptError(f"{field_name} must be a nonnegative integer")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise PlanningWaveCompletionReceiptError(f"{field_name} must be a positive integer")
    return value


def _require_exact_fields(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if set(payload) != expected:
        raise PlanningWaveCompletionReceiptError(f"{label} fields are invalid")


def _require_sha256_tuple(
    values: object,
    *,
    field_name: str,
    sorted_values: bool,
    nonempty: bool = True,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise PlanningWaveCompletionReceiptError(f"{field_name} must be an immutable tuple")
    result = tuple(_require_sha256(item, field_name=field_name) for item in values)
    if nonempty and not result:
        raise PlanningWaveCompletionReceiptError(f"{field_name} must be nonempty")
    if len(result) != len(set(result)):
        raise PlanningWaveCompletionReceiptError(f"{field_name} contains duplicates")
    if sorted_values and result != tuple(sorted(result)):
        raise PlanningWaveCompletionReceiptError(f"{field_name} must use canonical sorted order")
    return result


def _sha256_tuple_from_list(
    value: object,
    *,
    field_name: str,
    sorted_values: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PlanningWaveCompletionReceiptError(f"{field_name} must be a list")
    result = tuple(_require_sha256(item, field_name=field_name) for item in value)
    return _require_sha256_tuple(
        result,
        field_name=field_name,
        sorted_values=sorted_values,
    )


def _logical_binding_payload(binding: LogicalCallReceiptBinding) -> dict[str, object]:
    return {
        "endpoint_name": binding.endpoint_name,
        "logical_call_receipt_sha256": binding.logical_call_receipt_sha256,
        "logical_parameters_sha256": binding.logical_parameters_sha256,
        "provider_authority_sha256": binding.provider_authority_sha256,
        "result_route_ids": list(binding.result_route_ids),
    }


def _logical_bindings_sha256(
    bindings: Sequence[LogicalCallReceiptBinding],
) -> str:
    return _sha256_bytes(
        _canonical_json_bytes([_logical_binding_payload(binding) for binding in bindings])
    )


def _capture_scope_payload(scope: CaptureRunScope) -> dict[str, str | int]:
    return scope.to_dict()


@dataclass(frozen=True, slots=True)
class PlanningWaveCallBinding:
    """One admitted logical call and its atomic committed member inventory."""

    ordinal: int
    sealed_dispatch_identity_sha256: str
    committed_call_identity_sha256: str
    logical_call_receipt_sha256: str
    member_identity_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.ordinal, field_name="ordinal")
        for field_name in (
            "sealed_dispatch_identity_sha256",
            "committed_call_identity_sha256",
            "logical_call_receipt_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_sha256_tuple(
            self.member_identity_sha256s,
            field_name="member_identity_sha256s",
            sorted_values=True,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "sealed_dispatch_identity_sha256": self.sealed_dispatch_identity_sha256,
            "committed_call_identity_sha256": self.committed_call_identity_sha256,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "member_identity_sha256s": list(self.member_identity_sha256s),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_fields(
            payload,
            expected=frozenset(
                {
                    "ordinal",
                    "sealed_dispatch_identity_sha256",
                    "committed_call_identity_sha256",
                    "logical_call_receipt_sha256",
                    "member_identity_sha256s",
                }
            ),
            label="planning wave call binding",
        )
        return cls(
            ordinal=_require_nonnegative_int(payload["ordinal"], field_name="ordinal"),
            sealed_dispatch_identity_sha256=_require_sha256(
                payload["sealed_dispatch_identity_sha256"],
                field_name="sealed_dispatch_identity_sha256",
            ),
            committed_call_identity_sha256=_require_sha256(
                payload["committed_call_identity_sha256"],
                field_name="committed_call_identity_sha256",
            ),
            logical_call_receipt_sha256=_require_sha256(
                payload["logical_call_receipt_sha256"],
                field_name="logical_call_receipt_sha256",
            ),
            member_identity_sha256s=_sha256_tuple_from_list(
                payload["member_identity_sha256s"],
                field_name="member_identity_sha256s",
                sorted_values=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class PlanningWaveMemberBinding:
    """Full planning-member value bound to its successful Bronze logical root."""

    member: PlanningDataMember
    logical_call_receipt_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.member, PlanningDataMember):
            raise PlanningWaveCompletionReceiptError("member binding requires a PlanningDataMember")
        _require_sha256(
            self.logical_call_receipt_sha256,
            field_name="logical_call_receipt_sha256",
        )

    @property
    def member_identity_sha256(self) -> str:
        return self.member.identity_sha256

    def to_dict(self) -> dict[str, object]:
        return {
            "member": self.member.to_dict(),
            "member_identity_sha256": self.member_identity_sha256,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_fields(
            payload,
            expected=frozenset(
                {
                    "member",
                    "member_identity_sha256",
                    "logical_call_receipt_sha256",
                }
            ),
            label="planning wave member binding",
        )
        raw_member = payload["member"]
        if not isinstance(raw_member, Mapping):
            raise PlanningWaveCompletionReceiptError("planning wave member must be an object")
        try:
            member = PlanningDataMember.from_dict(cast("Mapping[str, object]", raw_member))
        except ValueError as exc:
            raise PlanningWaveCompletionReceiptError("planning wave member is invalid") from exc
        result = cls(
            member=member,
            logical_call_receipt_sha256=_require_sha256(
                payload["logical_call_receipt_sha256"],
                field_name="logical_call_receipt_sha256",
            ),
        )
        if result.member_identity_sha256 != _require_sha256(
            payload["member_identity_sha256"],
            field_name="member_identity_sha256",
        ):
            raise PlanningWaveCompletionReceiptError(
                "planning member identity differs from its full member authority"
            )
        return result


@dataclass(frozen=True, slots=True)
class PlanningWaveCompletionReceipt:
    """Path-free complete cross-binding for one committed planning wave."""

    planning_request_sha256: str
    planning_generation_id: str
    wave_index: int
    parent_wave_identity_sha256: str | None
    wave_admission_identity_sha256: str
    sealed_dispatch_identity_sha256s: tuple[str, ...]
    committed_calls: tuple[PlanningWaveCallBinding, ...]
    requested_scope_identity_sha256s: tuple[str, ...]
    completed_scope_identity_sha256s: tuple[str, ...]
    members: tuple[PlanningWaveMemberBinding, ...]
    logical_call_bindings: tuple[LogicalCallReceiptBinding, ...]
    capture_scope: CaptureRunScope
    private_generation_identity: PrivateGenerationIdentity
    planning_database_sha256: str
    planning_database_bytes: int
    planning_database_schema_sha256: str
    logical_call_bindings_sha256: str = field(init=False)
    capture_scope_identity_sha256: str = field(init=False)
    private_generation_identity_sha256: str = field(init=False)
    body_sha256: str = field(init=False)

    schema_version: ClassVar[int] = PLANNING_WAVE_COMPLETION_RECEIPT_SCHEMA_VERSION
    kind: ClassVar[str] = "successor_planning_wave_completion_receipt"

    def __post_init__(self) -> None:
        if not isinstance(self.capture_scope, CaptureRunScope):
            raise PlanningWaveCompletionReceiptError("capture_scope is invalid")
        if not isinstance(self.private_generation_identity, PrivateGenerationIdentity):
            raise PlanningWaveCompletionReceiptError("private_generation_identity is invalid")
        _require_sha256(
            self.planning_request_sha256,
            field_name="planning_request_sha256",
        )
        _require_token(self.planning_generation_id, field_name="planning_generation_id")
        if type(self.wave_index) is not int or self.wave_index not in {0, 1}:
            raise PlanningWaveCompletionReceiptError("wave_index must be exactly 0 or 1")
        if self.wave_index == 0:
            if self.parent_wave_identity_sha256 is not None:
                raise PlanningWaveCompletionReceiptError("wave 0 cannot have a parent")
        elif self.parent_wave_identity_sha256 is None:
            raise PlanningWaveCompletionReceiptError("wave 1 requires a parent")
        else:
            _require_sha256(
                self.parent_wave_identity_sha256,
                field_name="parent_wave_identity_sha256",
            )
        _require_sha256(
            self.wave_admission_identity_sha256,
            field_name="wave_admission_identity_sha256",
        )
        dispatches = _require_sha256_tuple(
            self.sealed_dispatch_identity_sha256s,
            field_name="sealed_dispatch_identity_sha256s",
            sorted_values=False,
        )
        scopes = _require_sha256_tuple(
            self.requested_scope_identity_sha256s,
            field_name="requested_scope_identity_sha256s",
            sorted_values=True,
        )
        completed = _require_sha256_tuple(
            self.completed_scope_identity_sha256s,
            field_name="completed_scope_identity_sha256s",
            sorted_values=True,
        )
        if completed != scopes:
            raise PlanningWaveCompletionReceiptError(
                "completed scopes must exactly equal requested scopes"
            )

        calls = tuple(self.committed_calls)
        if not calls or any(not isinstance(call, PlanningWaveCallBinding) for call in calls):
            raise PlanningWaveCompletionReceiptError("committed_calls must contain call bindings")
        if tuple(call.ordinal for call in calls) != tuple(range(len(calls))):
            raise PlanningWaveCompletionReceiptError(
                "committed call ordinals must be contiguous from zero"
            )
        if tuple(call.sealed_dispatch_identity_sha256 for call in calls) != dispatches:
            raise PlanningWaveCompletionReceiptError(
                "committed calls differ from the ordered dispatch inventory"
            )
        call_roots = tuple(call.logical_call_receipt_sha256 for call in calls)
        if len(call_roots) != len(set(call_roots)):
            raise PlanningWaveCompletionReceiptError(
                "committed calls contain duplicate logical roots"
            )

        supplied_members = tuple(self.members)
        if not supplied_members or any(
            not isinstance(item, PlanningWaveMemberBinding) for item in supplied_members
        ):
            raise PlanningWaveCompletionReceiptError(
                "members must contain planning member bindings"
            )
        members = tuple(sorted(supplied_members, key=lambda item: item.member_identity_sha256))
        member_ids = tuple(item.member_identity_sha256 for item in members)
        if len(member_ids) != len(set(member_ids)):
            raise PlanningWaveCompletionReceiptError(
                "planning wave member inventory contains duplicates"
            )
        if any(item.member.wave_index != self.wave_index for item in members):
            raise PlanningWaveCompletionReceiptError(
                "planning wave contains a member from another wave"
            )
        member_scopes = tuple(sorted({item.member.producing_scope_sha256 for item in members}))
        if member_scopes != scopes:
            raise PlanningWaveCompletionReceiptError(
                "planning members do not exactly cover requested scopes"
            )
        call_member_ids = tuple(
            sorted(member_id for call in calls for member_id in call.member_identity_sha256s)
        )
        if call_member_ids != member_ids:
            raise PlanningWaveCompletionReceiptError(
                "committed calls do not exactly partition planning members"
            )
        root_by_member = {
            member_id: call.logical_call_receipt_sha256
            for call in calls
            for member_id in call.member_identity_sha256s
        }
        if any(
            root_by_member[item.member_identity_sha256] != item.logical_call_receipt_sha256
            for item in members
        ):
            raise PlanningWaveCompletionReceiptError(
                "planning member logical roots differ from committed calls"
            )

        supplied_bindings = tuple(self.logical_call_bindings)
        if not supplied_bindings or any(
            not isinstance(binding, LogicalCallReceiptBinding) for binding in supplied_bindings
        ):
            raise PlanningWaveCompletionReceiptError(
                "logical_call_bindings must contain binding values"
            )
        bindings = tuple(
            sorted(
                (
                    LogicalCallReceiptBinding(
                        logical_call_receipt_sha256=binding.logical_call_receipt_sha256,
                        endpoint_name=binding.endpoint_name,
                        logical_parameters_sha256=binding.logical_parameters_sha256,
                        provider_authority_sha256=binding.provider_authority_sha256,
                        result_route_ids=tuple(binding.result_route_ids),
                    )
                    for binding in supplied_bindings
                ),
                key=lambda item: item.logical_call_receipt_sha256,
            )
        )
        binding_roots = tuple(binding.logical_call_receipt_sha256 for binding in bindings)
        if binding_roots != tuple(sorted(call_roots)):
            raise PlanningWaveCompletionReceiptError(
                "logical call bindings do not exactly cover committed call roots"
            )
        provider_authorities = {binding.provider_authority_sha256 for binding in bindings}
        if provider_authorities != {self.private_generation_identity.provider_authority_sha256}:
            raise PlanningWaveCompletionReceiptError(
                "logical call provider authority differs from private generation"
            )
        bindings_sha256 = _logical_bindings_sha256(bindings)
        if (
            self.private_generation_identity.done_call_receipt_sha256s != binding_roots
            or self.private_generation_identity.done_call_count != len(bindings)
            or self.private_generation_identity.done_call_bindings_sha256 != bindings_sha256
        ):
            raise PlanningWaveCompletionReceiptError(
                "private generation logical-call authority differs"
            )

        scope_fields = {
            "semantic_source_sha": self.capture_scope.semantic_source_sha,
            "chain_id": self.capture_scope.chain_id,
            "lane_id": self.capture_scope.lane_id,
            "workflow_run_id": self.capture_scope.workflow_run_id,
            "workflow_run_attempt": self.capture_scope.workflow_run_attempt,
        }
        if any(
            getattr(self.private_generation_identity, field_name) != expected
            for field_name, expected in scope_fields.items()
        ):
            raise PlanningWaveCompletionReceiptError(
                "private generation differs from its exact capture scope"
            )
        _require_sha256(self.planning_database_sha256, field_name="planning_database_sha256")
        _require_positive_int(self.planning_database_bytes, field_name="planning_database_bytes")
        _require_sha256(
            self.planning_database_schema_sha256,
            field_name="planning_database_schema_sha256",
        )

        object.__setattr__(self, "committed_calls", calls)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "logical_call_bindings", bindings)
        object.__setattr__(self, "logical_call_bindings_sha256", bindings_sha256)
        object.__setattr__(
            self,
            "capture_scope_identity_sha256",
            self.capture_scope.identity_sha256,
        )
        object.__setattr__(
            self,
            "private_generation_identity_sha256",
            self.private_generation_identity.identity_sha256,
        )
        object.__setattr__(
            self,
            "body_sha256",
            _sha256_bytes(_canonical_json_bytes(self._body_dict())),
        )

    def _body_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "planning_request_sha256": self.planning_request_sha256,
            "planning_generation_id": self.planning_generation_id,
            "wave_index": self.wave_index,
            "parent_wave_identity_sha256": self.parent_wave_identity_sha256,
            "wave_admission_identity_sha256": self.wave_admission_identity_sha256,
            "sealed_dispatch_identity_sha256s": list(self.sealed_dispatch_identity_sha256s),
            "committed_calls": [call.to_dict() for call in self.committed_calls],
            "requested_scope_identity_sha256s": list(self.requested_scope_identity_sha256s),
            "completed_scope_identity_sha256s": list(self.completed_scope_identity_sha256s),
            "members": [member.to_dict() for member in self.members],
            "logical_call_bindings": [
                _logical_binding_payload(binding) for binding in self.logical_call_bindings
            ],
            "logical_call_bindings_sha256": self.logical_call_bindings_sha256,
            "capture_scope": _capture_scope_payload(self.capture_scope),
            "capture_scope_identity_sha256": self.capture_scope_identity_sha256,
            "private_generation_identity": self.private_generation_identity.to_dict(),
            "private_generation_identity_sha256": (self.private_generation_identity_sha256),
            "planning_database_sha256": self.planning_database_sha256,
            "planning_database_bytes": self.planning_database_bytes,
            "planning_database_schema_sha256": self.planning_database_schema_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body_dict(), "body_sha256": self.body_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @property
    def identity_sha256(self) -> str:
        return _sha256_bytes(self.canonical_bytes)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "planning_request_sha256",
                "planning_generation_id",
                "wave_index",
                "parent_wave_identity_sha256",
                "wave_admission_identity_sha256",
                "sealed_dispatch_identity_sha256s",
                "committed_calls",
                "requested_scope_identity_sha256s",
                "completed_scope_identity_sha256s",
                "members",
                "logical_call_bindings",
                "logical_call_bindings_sha256",
                "capture_scope",
                "capture_scope_identity_sha256",
                "private_generation_identity",
                "private_generation_identity_sha256",
                "planning_database_sha256",
                "planning_database_bytes",
                "planning_database_schema_sha256",
                "body_sha256",
            }
        )
        _require_exact_fields(payload, expected=expected, label="planning wave receipt")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise PlanningWaveCompletionReceiptError("planning wave receipt schema is invalid")
        raw_parent = payload["parent_wave_identity_sha256"]
        parent = (
            None
            if raw_parent is None
            else _require_sha256(raw_parent, field_name="parent_wave_identity_sha256")
        )
        calls = cls._decode_sequence(
            payload["committed_calls"],
            label="committed_calls",
            decoder=PlanningWaveCallBinding.from_dict,
        )
        members = cls._decode_sequence(
            payload["members"],
            label="members",
            decoder=PlanningWaveMemberBinding.from_dict,
        )
        bindings = cls._decode_logical_bindings(payload["logical_call_bindings"])
        capture_scope = cls._decode_capture_scope(payload["capture_scope"])
        raw_private = payload["private_generation_identity"]
        if not isinstance(raw_private, Mapping):
            raise PlanningWaveCompletionReceiptError(
                "private_generation_identity must be an object"
            )
        try:
            private = PrivateGenerationIdentity.from_dict(cast("Mapping[str, object]", raw_private))
        except ValueError as exc:
            raise PlanningWaveCompletionReceiptError(
                "private_generation_identity is invalid"
            ) from exc
        result = cls(
            planning_request_sha256=_require_sha256(
                payload["planning_request_sha256"], field_name="planning_request_sha256"
            ),
            planning_generation_id=_require_token(
                payload["planning_generation_id"], field_name="planning_generation_id"
            ),
            wave_index=_require_nonnegative_int(payload["wave_index"], field_name="wave_index"),
            parent_wave_identity_sha256=parent,
            wave_admission_identity_sha256=_require_sha256(
                payload["wave_admission_identity_sha256"],
                field_name="wave_admission_identity_sha256",
            ),
            sealed_dispatch_identity_sha256s=_sha256_tuple_from_list(
                payload["sealed_dispatch_identity_sha256s"],
                field_name="sealed_dispatch_identity_sha256s",
                sorted_values=False,
            ),
            committed_calls=cast("tuple[PlanningWaveCallBinding, ...]", calls),
            requested_scope_identity_sha256s=_sha256_tuple_from_list(
                payload["requested_scope_identity_sha256s"],
                field_name="requested_scope_identity_sha256s",
                sorted_values=True,
            ),
            completed_scope_identity_sha256s=_sha256_tuple_from_list(
                payload["completed_scope_identity_sha256s"],
                field_name="completed_scope_identity_sha256s",
                sorted_values=True,
            ),
            members=cast("tuple[PlanningWaveMemberBinding, ...]", members),
            logical_call_bindings=bindings,
            capture_scope=capture_scope,
            private_generation_identity=private,
            planning_database_sha256=_require_sha256(
                payload["planning_database_sha256"],
                field_name="planning_database_sha256",
            ),
            planning_database_bytes=_require_positive_int(
                payload["planning_database_bytes"],
                field_name="planning_database_bytes",
            ),
            planning_database_schema_sha256=_require_sha256(
                payload["planning_database_schema_sha256"],
                field_name="planning_database_schema_sha256",
            ),
        )
        for field_name in (
            "logical_call_bindings_sha256",
            "capture_scope_identity_sha256",
            "private_generation_identity_sha256",
            "body_sha256",
        ):
            supplied = _require_sha256(payload[field_name], field_name=field_name)
            if getattr(result, field_name) != supplied:
                raise PlanningWaveCompletionReceiptError(
                    f"{field_name} differs from its canonical authority"
                )
        if result.to_dict() != dict(payload):
            raise PlanningWaveCompletionReceiptError("planning wave receipt is not canonical")
        return result

    @staticmethod
    def _decode_sequence(
        value: object,
        *,
        label: str,
        decoder: Any,
    ) -> tuple[object, ...]:
        if not isinstance(value, list):
            raise PlanningWaveCompletionReceiptError(f"{label} must be a list")
        decoded: list[object] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise PlanningWaveCompletionReceiptError(f"{label} members must be objects")
            decoded.append(decoder(cast("Mapping[str, object]", item)))
        return tuple(decoded)

    @staticmethod
    def _decode_capture_scope(value: object) -> CaptureRunScope:
        if not isinstance(value, Mapping) or set(value) != {
            "semantic_source_sha",
            "chain_id",
            "lane_id",
            "workflow_run_id",
            "workflow_run_attempt",
        }:
            raise PlanningWaveCompletionReceiptError("capture_scope fields are invalid")
        scope_payload = cast("Mapping[str, object]", value)
        try:
            return CaptureRunScope(
                semantic_source_sha=cast("str", scope_payload["semantic_source_sha"]),
                chain_id=cast("str", scope_payload["chain_id"]),
                lane_id=cast("str", scope_payload["lane_id"]),
                workflow_run_id=cast("int", scope_payload["workflow_run_id"]),
                workflow_run_attempt=cast("int", scope_payload["workflow_run_attempt"]),
            )
        except (TypeError, ValueError) as exc:
            raise PlanningWaveCompletionReceiptError("capture_scope is invalid") from exc

    @staticmethod
    def _decode_logical_bindings(
        value: object,
    ) -> tuple[LogicalCallReceiptBinding, ...]:
        if not isinstance(value, list):
            raise PlanningWaveCompletionReceiptError("logical_call_bindings must be a list")
        expected = {
            "endpoint_name",
            "logical_call_receipt_sha256",
            "logical_parameters_sha256",
            "provider_authority_sha256",
            "result_route_ids",
        }
        result: list[LogicalCallReceiptBinding] = []
        try:
            for raw in value:
                if not isinstance(raw, Mapping) or set(raw) != expected:
                    raise PlanningWaveCompletionReceiptError(
                        "logical call binding fields are invalid"
                    )
                binding_payload = cast("Mapping[str, object]", raw)
                routes = binding_payload["result_route_ids"]
                if not isinstance(routes, list) or any(
                    not isinstance(route, str) for route in routes
                ):
                    raise PlanningWaveCompletionReceiptError(
                        "logical call binding routes are invalid"
                    )
                result.append(
                    LogicalCallReceiptBinding(
                        endpoint_name=cast("str", binding_payload["endpoint_name"]),
                        logical_call_receipt_sha256=cast(
                            "str", binding_payload["logical_call_receipt_sha256"]
                        ),
                        logical_parameters_sha256=cast(
                            "str", binding_payload["logical_parameters_sha256"]
                        ),
                        provider_authority_sha256=cast(
                            "str", binding_payload["provider_authority_sha256"]
                        ),
                        result_route_ids=tuple(cast("list[str]", routes)),
                    )
                )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, PlanningWaveCompletionReceiptError):
                raise
            raise PlanningWaveCompletionReceiptError("logical call binding is invalid") from exc
        return tuple(result)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        if not isinstance(encoded, bytes):
            raise PlanningWaveCompletionReceiptError("planning wave receipt encoding must be bytes")

        def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
            decoded: dict[str, object] = {}
            for key, value in pairs:
                if key in decoded:
                    raise PlanningWaveCompletionReceiptError(
                        f"planning wave receipt contains duplicate key {key!r}"
                    )
                decoded[key] = value
            return decoded

        def reject_constant(value: str) -> object:
            raise PlanningWaveCompletionReceiptError(
                f"planning wave receipt contains non-finite JSON value {value}"
            )

        try:
            decoded = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=pairs_hook,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlanningWaveCompletionReceiptError(
                "planning wave receipt is not strict UTF-8 JSON"
            ) from exc
        if not isinstance(decoded, dict) or _canonical_json_bytes(decoded) != encoded:
            raise PlanningWaveCompletionReceiptError(
                "planning wave receipt bytes are not canonical"
            )
        result = cls.from_dict(decoded)
        if result.canonical_bytes != encoded:
            raise PlanningWaveCompletionReceiptError(
                "planning wave receipt bytes differ from validated authority"
            )
        return result
