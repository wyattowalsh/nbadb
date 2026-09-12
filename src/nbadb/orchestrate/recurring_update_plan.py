"""Canonical admission contract for bounded daily and monthly update planning.

The values in this module are deliberately persistence- and network-free.  A caller
must first resolve and verify an exact remote parent version, resolve every request
parameter, and seal the temporal window.  Only then can it construct a plan.  In
particular, no constructor consults a clock, a watermark, a cache, or a ``latest``
alias.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self, cast

__all__ = [
    "RECURRING_UPDATE_PLAN_SCHEMA_VERSION",
    "EndpointOverlapScopeV1",
    "GapRepairRequestV1",
    "RecurringUpdateMode",
    "RecurringUpdatePlanError",
    "RecurringUpdatePlanV1",
    "TailGenerationV1",
    "canonical_json_bytes",
    "canonical_sha256",
]

RECURRING_UPDATE_PLAN_SCHEMA_VERSION = 1

_MAX_JSON_BYTES = 2 * 1024 * 1024
_MAX_REQUEST_JSON_BYTES = 256 * 1024
_MAX_OVERLAP_SCOPES = 512
_MAX_GAP_REPAIR_REQUESTS = 4096
_MAX_PARAMETER_ITEMS = 128
_MAX_PARAMETER_SEQUENCE_ITEMS = 512
_MAX_SIGNED_63 = (1 << 63) - 1

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")
_PARAMETER_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_REASON_CODE_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,127}")
_DATASET_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_UTC_INSTANT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

_EXECUTABLE_REQUEST_DOMAIN = "nbadb.recurring-update.executable-request.v1"
_UPDATE_TRANSACTION_DOMAIN = "nbadb.recurring-update.transaction.v1"
_PARENT_AUTHORITY_DOMAIN = "nbadb.recurring-update.verified-parent.v1"

type _ParameterScalar = str | int | bool | None
type _FrozenParameterValue = _ParameterScalar | tuple[_ParameterScalar, ...]
type _FrozenParameterItems = tuple[tuple[str, _FrozenParameterValue], ...]


class RecurringUpdatePlanError(ValueError):
    """Raised when a recurring plan is ambiguous, mutable, or inconsistent."""


class RecurringUpdateMode(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"


def canonical_json_bytes(payload: object) -> bytes:
    """Return the only JSON encoding admitted to plan identities and receipts."""

    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RecurringUpdatePlanError("value is not canonical JSON") from exc


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_bounded_json(payload: object, *, label: str, maximum: int) -> None:
    if len(canonical_json_bytes(payload)) > maximum:
        raise RecurringUpdatePlanError(f"{label} exceeds the bounded contract size")


def _reject_constant(value: str) -> None:
    raise RecurringUpdatePlanError(f"non-finite JSON number is forbidden: {value}")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RecurringUpdatePlanError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_canonical_json(encoded: bytes) -> Mapping[str, object]:
    if type(encoded) is not bytes or not encoded:
        raise RecurringUpdatePlanError("plan bytes must be nonempty bytes")
    if len(encoded) > _MAX_JSON_BYTES:
        raise RecurringUpdatePlanError("plan bytes exceed the bounded contract size")
    try:
        decoded = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecurringUpdatePlanError("plan bytes are not valid UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise RecurringUpdatePlanError("plan JSON must be an object")
    if canonical_json_bytes(decoded) != encoded:
        raise RecurringUpdatePlanError("plan JSON is not canonically encoded")
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
    raise RecurringUpdatePlanError(f"{label} fields are invalid: {'; '.join(details)}")


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise RecurringUpdatePlanError(f"{field_name} must be a string-keyed object")
    return cast("Mapping[str, object]", value)


def _require_list(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise RecurringUpdatePlanError(f"{field_name} must be a list")
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise RecurringUpdatePlanError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_safe_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise RecurringUpdatePlanError(f"{field_name} must be an exact safe token")
    return value


def _require_reason_code(value: object) -> str:
    if not isinstance(value, str) or _REASON_CODE_RE.fullmatch(value) is None:
        raise RecurringUpdatePlanError("reason_code must be a stable lowercase reason code")
    return value


def _require_dataset_ref(value: object) -> str:
    if not isinstance(value, str) or _DATASET_REF_RE.fullmatch(value) is None:
        raise RecurringUpdatePlanError("dataset_ref must be an exact owner/dataset reference")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1 or value > _MAX_SIGNED_63:
        raise RecurringUpdatePlanError(f"{field_name} must be a positive signed-63-bit integer")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_SIGNED_63:
        raise RecurringUpdatePlanError(f"{field_name} must be a nonnegative signed-63-bit integer")
    return value


def _require_utc_instant(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _UTC_INSTANT_RE.fullmatch(value) is None:
        raise RecurringUpdatePlanError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RecurringUpdatePlanError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise RecurringUpdatePlanError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        )
    return value


def _as_utc(value: str, *, field_name: str) -> datetime:
    return datetime.strptime(
        _require_utc_instant(value, field_name=field_name),
        "%Y-%m-%dT%H:%M:%SZ",
    )


def _require_parameter_scalar(value: object, *, field_name: str) -> _ParameterScalar:
    if value is None or type(value) is bool:
        return cast("_ParameterScalar", value)
    if type(value) is int:
        if not -_MAX_SIGNED_63 <= value <= _MAX_SIGNED_63:
            raise RecurringUpdatePlanError(f"{field_name} integer is outside signed-63-bit range")
        return value
    if type(value) is str:
        if len(value) > 1024:
            raise RecurringUpdatePlanError(f"{field_name} string exceeds 1024 characters")
        return value
    raise RecurringUpdatePlanError(
        f"{field_name} must be an immutable JSON scalar; floats and nested values are forbidden"
    )


def _freeze_parameters(parameters: Mapping[str, object]) -> _FrozenParameterItems:
    if len(parameters) > _MAX_PARAMETER_ITEMS:
        raise RecurringUpdatePlanError("parameters exceed the bounded item count")
    items: list[tuple[str, _FrozenParameterValue]] = []
    for key in sorted(parameters):
        if _PARAMETER_KEY_RE.fullmatch(key) is None:
            raise RecurringUpdatePlanError("parameter keys must be exact safe identifiers")
        value = parameters[key]
        if isinstance(value, (list, tuple)):
            if len(value) > _MAX_PARAMETER_SEQUENCE_ITEMS:
                raise RecurringUpdatePlanError(
                    f"parameter {key} exceeds the bounded sequence item count"
                )
            frozen_value: _FrozenParameterValue = tuple(
                _require_parameter_scalar(item, field_name=f"parameters.{key}") for item in value
            )
        else:
            frozen_value = _require_parameter_scalar(value, field_name=f"parameters.{key}")
        items.append((key, frozen_value))
    return tuple(items)


def _validate_frozen_parameters(parameter_items: object) -> _FrozenParameterItems:
    if type(parameter_items) is not tuple:
        raise RecurringUpdatePlanError("parameter_items must be an immutable canonical tuple")
    if any(type(item) is not tuple or len(item) != 2 for item in parameter_items):
        raise RecurringUpdatePlanError("parameter_items must contain exact key/value tuples")
    typed_items = cast("tuple[tuple[object, object], ...]", parameter_items)
    keys: list[str] = []
    thawed: dict[str, object] = {}
    for raw_key, raw_value in typed_items:
        if not isinstance(raw_key, str):
            raise RecurringUpdatePlanError("parameter keys must be strings")
        keys.append(raw_key)
        if type(raw_value) is tuple:
            thawed[raw_key] = list(raw_value)
        else:
            thawed[raw_key] = raw_value
    if len(keys) != len(set(keys)):
        raise RecurringUpdatePlanError("parameter inventory contains duplicate keys")
    expected = _freeze_parameters(thawed)
    if parameter_items != expected:
        raise RecurringUpdatePlanError(
            "parameter_items must be an immutable canonical sorted tuple inventory"
        )
    return cast("_FrozenParameterItems", parameter_items)


def _parameters_dict(parameter_items: _FrozenParameterItems) -> dict[str, object]:
    return {key: list(value) if type(value) is tuple else value for key, value in parameter_items}


@dataclass(frozen=True, slots=True)
class EndpointOverlapScopeV1:
    """One exact executable request whose window overlaps the new event cutoff."""

    endpoint_name: str
    request_key: str
    request_contract_sha256: str
    scope_start_utc: str
    scope_end_utc: str
    parameter_items: _FrozenParameterItems

    def __post_init__(self) -> None:
        _require_safe_token(self.endpoint_name, field_name="endpoint_name")
        _require_safe_token(self.request_key, field_name="request_key")
        _require_sha256(self.request_contract_sha256, field_name="request_contract_sha256")
        start = _as_utc(self.scope_start_utc, field_name="scope_start_utc")
        end = _as_utc(self.scope_end_utc, field_name="scope_end_utc")
        if start >= end:
            raise RecurringUpdatePlanError("overlap scope_start_utc must precede scope_end_utc")
        _validate_frozen_parameters(self.parameter_items)
        _require_bounded_json(
            self._identity_payload(),
            label="overlap request",
            maximum=_MAX_REQUEST_JSON_BYTES,
        )

    @classmethod
    def from_parameters(
        cls,
        *,
        endpoint_name: str,
        request_key: str,
        request_contract_sha256: str,
        scope_start_utc: str,
        scope_end_utc: str,
        parameters: Mapping[str, object],
    ) -> Self:
        if not isinstance(parameters, Mapping):
            raise RecurringUpdatePlanError("parameters must be a mapping")
        return cls(
            endpoint_name=endpoint_name,
            request_key=request_key,
            request_contract_sha256=request_contract_sha256,
            scope_start_utc=scope_start_utc,
            scope_end_utc=scope_end_utc,
            parameter_items=_freeze_parameters(parameters),
        )

    @property
    def parameters(self) -> dict[str, object]:
        return _parameters_dict(self.parameter_items)

    @property
    def uniqueness_key(self) -> tuple[str, str]:
        return (self.endpoint_name, self.request_key)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.endpoint_name, self.request_key, self.request_identity_sha256)

    @property
    def request_identity_sha256(self) -> str:
        return canonical_sha256(self._identity_payload())

    def _identity_payload(self) -> dict[str, object]:
        return {
            "domain": _EXECUTABLE_REQUEST_DOMAIN,
            "endpoint_name": self.endpoint_name,
            "request_contract_sha256": self.request_contract_sha256,
            "scope_start_utc": self.scope_start_utc,
            "scope_end_utc": self.scope_end_utc,
            "parameters": self.parameters,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint_name": self.endpoint_name,
            "request_key": self.request_key,
            "request_contract_sha256": self.request_contract_sha256,
            "scope_start_utc": self.scope_start_utc,
            "scope_end_utc": self.scope_end_utc,
            "parameters": self.parameters,
            "request_identity_sha256": self.request_identity_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "endpoint_name",
                    "request_key",
                    "request_contract_sha256",
                    "scope_start_utc",
                    "scope_end_utc",
                    "parameters",
                    "request_identity_sha256",
                }
            ),
            label="endpoint overlap scope",
        )
        result = cls.from_parameters(
            endpoint_name=_require_safe_token(payload["endpoint_name"], field_name="endpoint_name"),
            request_key=_require_safe_token(payload["request_key"], field_name="request_key"),
            request_contract_sha256=_require_sha256(
                payload["request_contract_sha256"], field_name="request_contract_sha256"
            ),
            scope_start_utc=_require_utc_instant(
                payload["scope_start_utc"], field_name="scope_start_utc"
            ),
            scope_end_utc=_require_utc_instant(
                payload["scope_end_utc"], field_name="scope_end_utc"
            ),
            parameters=_require_mapping(payload["parameters"], field_name="parameters"),
        )
        if result.request_identity_sha256 != _require_sha256(
            payload["request_identity_sha256"], field_name="request_identity_sha256"
        ):
            raise RecurringUpdatePlanError(
                "overlap request identity differs from its exact executable request"
            )
        return result


@dataclass(frozen=True, slots=True)
class GapRepairRequestV1:
    """One explicit request for a known gap older than the rolling tail window."""

    endpoint_name: str
    request_key: str
    request_contract_sha256: str
    gap_start_utc: str
    gap_end_utc: str
    reason_code: str
    parameter_items: _FrozenParameterItems

    def __post_init__(self) -> None:
        _require_safe_token(self.endpoint_name, field_name="endpoint_name")
        _require_safe_token(self.request_key, field_name="request_key")
        _require_sha256(self.request_contract_sha256, field_name="request_contract_sha256")
        start = _as_utc(self.gap_start_utc, field_name="gap_start_utc")
        end = _as_utc(self.gap_end_utc, field_name="gap_end_utc")
        if start >= end:
            raise RecurringUpdatePlanError("gap_start_utc must precede gap_end_utc")
        _require_reason_code(self.reason_code)
        _validate_frozen_parameters(self.parameter_items)
        _require_bounded_json(
            self._identity_payload(),
            label="gap-repair request",
            maximum=_MAX_REQUEST_JSON_BYTES,
        )

    @classmethod
    def from_parameters(
        cls,
        *,
        endpoint_name: str,
        request_key: str,
        request_contract_sha256: str,
        gap_start_utc: str,
        gap_end_utc: str,
        reason_code: str,
        parameters: Mapping[str, object],
    ) -> Self:
        if not isinstance(parameters, Mapping):
            raise RecurringUpdatePlanError("parameters must be a mapping")
        return cls(
            endpoint_name=endpoint_name,
            request_key=request_key,
            request_contract_sha256=request_contract_sha256,
            gap_start_utc=gap_start_utc,
            gap_end_utc=gap_end_utc,
            reason_code=reason_code,
            parameter_items=_freeze_parameters(parameters),
        )

    @property
    def parameters(self) -> dict[str, object]:
        return _parameters_dict(self.parameter_items)

    @property
    def uniqueness_key(self) -> tuple[str, str, str, str]:
        return (
            self.endpoint_name,
            self.request_key,
            self.gap_start_utc,
            self.gap_end_utc,
        )

    @property
    def sort_key(self) -> tuple[str, str, str, str, str]:
        return (*self.uniqueness_key, self.request_identity_sha256)

    @property
    def request_identity_sha256(self) -> str:
        return canonical_sha256(self._identity_payload())

    def _identity_payload(self) -> dict[str, object]:
        return {
            "domain": _EXECUTABLE_REQUEST_DOMAIN,
            "endpoint_name": self.endpoint_name,
            "request_contract_sha256": self.request_contract_sha256,
            "scope_start_utc": self.gap_start_utc,
            "scope_end_utc": self.gap_end_utc,
            "parameters": self.parameters,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "endpoint_name": self.endpoint_name,
            "request_key": self.request_key,
            "request_contract_sha256": self.request_contract_sha256,
            "gap_start_utc": self.gap_start_utc,
            "gap_end_utc": self.gap_end_utc,
            "reason_code": self.reason_code,
            "parameters": self.parameters,
            "request_identity_sha256": self.request_identity_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "endpoint_name",
                    "request_key",
                    "request_contract_sha256",
                    "gap_start_utc",
                    "gap_end_utc",
                    "reason_code",
                    "parameters",
                    "request_identity_sha256",
                }
            ),
            label="gap repair request",
        )
        result = cls.from_parameters(
            endpoint_name=_require_safe_token(payload["endpoint_name"], field_name="endpoint_name"),
            request_key=_require_safe_token(payload["request_key"], field_name="request_key"),
            request_contract_sha256=_require_sha256(
                payload["request_contract_sha256"], field_name="request_contract_sha256"
            ),
            gap_start_utc=_require_utc_instant(
                payload["gap_start_utc"], field_name="gap_start_utc"
            ),
            gap_end_utc=_require_utc_instant(payload["gap_end_utc"], field_name="gap_end_utc"),
            reason_code=_require_reason_code(payload["reason_code"]),
            parameters=_require_mapping(payload["parameters"], field_name="parameters"),
        )
        if result.request_identity_sha256 != _require_sha256(
            payload["request_identity_sha256"], field_name="request_identity_sha256"
        ):
            raise RecurringUpdatePlanError(
                "gap-repair request identity differs from its exact executable request"
            )
        return result


@dataclass(frozen=True, slots=True)
class TailGenerationV1:
    """A sealed, exact, bounded inventory for one recurring tail generation."""

    event_cutoff_utc: str
    as_of_utc: str
    window_start_utc: str
    window_end_utc: str
    sealed_at_utc: str
    overlap_scopes: tuple[EndpointOverlapScopeV1, ...]
    gap_repair_requests: tuple[GapRepairRequestV1, ...]
    request_identities: tuple[str, ...]

    schema_version: ClassVar[int] = RECURRING_UPDATE_PLAN_SCHEMA_VERSION
    kind: ClassVar[str] = "tail_generation"

    def __post_init__(self) -> None:
        window_start = _as_utc(self.window_start_utc, field_name="window_start_utc")
        event_cutoff = _as_utc(self.event_cutoff_utc, field_name="event_cutoff_utc")
        window_end = _as_utc(self.window_end_utc, field_name="window_end_utc")
        as_of = _as_utc(self.as_of_utc, field_name="as_of_utc")
        sealed_at = _as_utc(self.sealed_at_utc, field_name="sealed_at_utc")
        if not window_start <= event_cutoff <= window_end <= as_of <= sealed_at:
            raise RecurringUpdatePlanError(
                "time order must be window_start <= event_cutoff <= window_end <= as_of <= seal"
            )

        if type(self.overlap_scopes) is not tuple or not self.overlap_scopes:
            raise RecurringUpdatePlanError("overlap_scopes must be a nonempty immutable tuple")
        if len(self.overlap_scopes) > _MAX_OVERLAP_SCOPES:
            raise RecurringUpdatePlanError("overlap scopes exceed the bounded request count")
        if any(not isinstance(scope, EndpointOverlapScopeV1) for scope in self.overlap_scopes):
            raise RecurringUpdatePlanError(
                "overlap_scopes must contain EndpointOverlapScopeV1 values"
            )
        expected_overlap_order = tuple(sorted(self.overlap_scopes, key=lambda item: item.sort_key))
        if self.overlap_scopes != expected_overlap_order:
            raise RecurringUpdatePlanError("overlap_scopes must use canonical sorted order")
        overlap_keys = [scope.uniqueness_key for scope in self.overlap_scopes]
        if len(overlap_keys) != len(set(overlap_keys)):
            raise RecurringUpdatePlanError(
                "overlap_scopes contain duplicate or conflicting endpoint request keys"
            )
        for scope in self.overlap_scopes:
            scope_start = _as_utc(scope.scope_start_utc, field_name="scope_start_utc")
            scope_end = _as_utc(scope.scope_end_utc, field_name="scope_end_utc")
            if not window_start <= scope_start <= event_cutoff <= scope_end <= window_end:
                raise RecurringUpdatePlanError(
                    "each endpoint overlap scope must stay inside the tail window "
                    "and cover the cutoff"
                )

        if type(self.gap_repair_requests) is not tuple:
            raise RecurringUpdatePlanError("gap_repair_requests must be an immutable tuple")
        if len(self.gap_repair_requests) > _MAX_GAP_REPAIR_REQUESTS:
            raise RecurringUpdatePlanError("gap repairs exceed the bounded request count")
        if any(not isinstance(item, GapRepairRequestV1) for item in self.gap_repair_requests):
            raise RecurringUpdatePlanError(
                "gap_repair_requests must contain GapRepairRequestV1 values"
            )
        expected_gap_order = tuple(sorted(self.gap_repair_requests, key=lambda item: item.sort_key))
        if self.gap_repair_requests != expected_gap_order:
            raise RecurringUpdatePlanError("gap_repair_requests must use canonical sorted order")
        gap_keys = [item.uniqueness_key for item in self.gap_repair_requests]
        if len(gap_keys) != len(set(gap_keys)):
            raise RecurringUpdatePlanError(
                "gap_repair_requests contain duplicate or conflicting request identities"
            )
        if any(
            _as_utc(item.gap_end_utc, field_name="gap_end_utc") >= window_start
            for item in self.gap_repair_requests
        ):
            raise RecurringUpdatePlanError(
                "gap-repair requests must end strictly before the rolling tail window"
            )

        if type(self.request_identities) is not tuple:
            raise RecurringUpdatePlanError("request_identities must be an immutable tuple")
        supplied_identities = tuple(
            _require_sha256(value, field_name="request_identities")
            for value in self.request_identities
        )
        expected_identities = tuple(
            sorted(scope.request_identity_sha256 for scope in self.overlap_scopes)
            + sorted(item.request_identity_sha256 for item in self.gap_repair_requests)
        )
        expected_identities = tuple(sorted(expected_identities))
        if len(expected_identities) != len(set(expected_identities)):
            raise RecurringUpdatePlanError("derived request identities contain a collision")
        if supplied_identities != expected_identities:
            raise RecurringUpdatePlanError(
                "request_identities must exactly equal the canonical deduplicated request inventory"
            )
        _require_bounded_json(
            self.to_dict(),
            label="tail generation",
            maximum=_MAX_JSON_BYTES,
        )

    @classmethod
    def build(
        cls,
        *,
        event_cutoff_utc: str,
        as_of_utc: str,
        window_start_utc: str,
        window_end_utc: str,
        sealed_at_utc: str,
        overlap_scopes: Sequence[EndpointOverlapScopeV1],
        gap_repair_requests: Sequence[GapRepairRequestV1],
    ) -> Self:
        """Freeze explicitly resolved inputs; this method never supplies defaults."""

        overlaps = tuple(sorted(overlap_scopes, key=lambda item: item.sort_key))
        gaps = tuple(sorted(gap_repair_requests, key=lambda item: item.sort_key))
        identities = tuple(
            sorted(
                [scope.request_identity_sha256 for scope in overlaps]
                + [item.request_identity_sha256 for item in gaps]
            )
        )
        return cls(
            event_cutoff_utc=event_cutoff_utc,
            as_of_utc=as_of_utc,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            sealed_at_utc=sealed_at_utc,
            overlap_scopes=overlaps,
            gap_repair_requests=gaps,
            request_identities=identities,
        )

    @property
    def overlap_scopes_sha256(self) -> str:
        return canonical_sha256([scope.to_dict() for scope in self.overlap_scopes])

    @property
    def gap_repair_requests_sha256(self) -> str:
        return canonical_sha256([item.to_dict() for item in self.gap_repair_requests])

    @property
    def request_identities_sha256(self) -> str:
        return canonical_sha256(list(self.request_identities))

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "event_cutoff_utc": self.event_cutoff_utc,
            "as_of_utc": self.as_of_utc,
            "window_start_utc": self.window_start_utc,
            "window_end_utc": self.window_end_utc,
            "sealed_at_utc": self.sealed_at_utc,
            "overlap_scopes": [scope.to_dict() for scope in self.overlap_scopes],
            "overlap_scopes_sha256": self.overlap_scopes_sha256,
            "gap_repair_requests": [item.to_dict() for item in self.gap_repair_requests],
            "gap_repair_requests_sha256": self.gap_repair_requests_sha256,
            "request_identities": list(self.request_identities),
            "request_identities_sha256": self.request_identities_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "event_cutoff_utc",
                    "as_of_utc",
                    "window_start_utc",
                    "window_end_utc",
                    "sealed_at_utc",
                    "overlap_scopes",
                    "overlap_scopes_sha256",
                    "gap_repair_requests",
                    "gap_repair_requests_sha256",
                    "request_identities",
                    "request_identities_sha256",
                }
            ),
            label="tail generation",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringUpdatePlanError("tail generation schema is invalid")
        raw_overlaps = _require_list(payload["overlap_scopes"], field_name="overlap_scopes")
        raw_gaps = _require_list(payload["gap_repair_requests"], field_name="gap_repair_requests")
        raw_identities = _require_list(
            payload["request_identities"], field_name="request_identities"
        )
        result = cls(
            event_cutoff_utc=_require_utc_instant(
                payload["event_cutoff_utc"], field_name="event_cutoff_utc"
            ),
            as_of_utc=_require_utc_instant(payload["as_of_utc"], field_name="as_of_utc"),
            window_start_utc=_require_utc_instant(
                payload["window_start_utc"], field_name="window_start_utc"
            ),
            window_end_utc=_require_utc_instant(
                payload["window_end_utc"], field_name="window_end_utc"
            ),
            sealed_at_utc=_require_utc_instant(
                payload["sealed_at_utc"], field_name="sealed_at_utc"
            ),
            overlap_scopes=tuple(
                EndpointOverlapScopeV1.from_dict(
                    _require_mapping(item, field_name=f"overlap_scopes[{index}]")
                )
                for index, item in enumerate(raw_overlaps)
            ),
            gap_repair_requests=tuple(
                GapRepairRequestV1.from_dict(
                    _require_mapping(item, field_name=f"gap_repair_requests[{index}]")
                )
                for index, item in enumerate(raw_gaps)
            ),
            request_identities=tuple(
                _require_sha256(item, field_name=f"request_identities[{index}]")
                for index, item in enumerate(raw_identities)
            ),
        )
        expected_digests = (
            (
                "overlap_scopes_sha256",
                result.overlap_scopes_sha256,
                payload["overlap_scopes_sha256"],
            ),
            (
                "gap_repair_requests_sha256",
                result.gap_repair_requests_sha256,
                payload["gap_repair_requests_sha256"],
            ),
            (
                "request_identities_sha256",
                result.request_identities_sha256,
                payload["request_identities_sha256"],
            ),
        )
        mismatches = [
            field_name
            for field_name, actual, supplied in expected_digests
            if actual != _require_sha256(supplied, field_name=field_name)
        ]
        if mismatches:
            raise RecurringUpdatePlanError(
                "tail generation inventory digest differs: " + ", ".join(mismatches)
            )
        return result

    @classmethod
    def from_bytes(cls, encoded: bytes) -> Self:
        return cls.from_dict(_decode_canonical_json(encoded))


@dataclass(frozen=True, slots=True)
class RecurringUpdatePlanV1:
    """Parent-bound recurring plan with recovery-stable transaction identity."""

    mode: RecurringUpdateMode
    dataset_ref: str
    parent_dataset_version: int
    parent_dataset_version_ref: str
    parent_authority_sha256: str
    tail_generation: TailGenerationV1
    update_transaction_id: str
    recovery_generation: int
    recovery_parent_plan_sha256: str | None

    schema_version: ClassVar[int] = RECURRING_UPDATE_PLAN_SCHEMA_VERSION
    kind: ClassVar[str] = "recurring_update_plan"

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RecurringUpdateMode):
            raise RecurringUpdatePlanError("mode must be a RecurringUpdateMode")
        dataset_ref = _require_dataset_ref(self.dataset_ref)
        version = _require_positive_int(
            self.parent_dataset_version, field_name="parent_dataset_version"
        )
        expected_version_ref = f"{dataset_ref}/versions/{version}"
        if self.parent_dataset_version_ref != expected_version_ref:
            raise RecurringUpdatePlanError(
                "parent_dataset_version_ref must name the exact positive version; "
                "unversioned and latest aliases are forbidden"
            )
        _require_sha256(self.parent_authority_sha256, field_name="parent_authority_sha256")
        if not isinstance(self.tail_generation, TailGenerationV1):
            raise RecurringUpdatePlanError("tail_generation must be a TailGenerationV1")
        supplied_transaction_id = _require_sha256(
            self.update_transaction_id, field_name="update_transaction_id"
        )
        if supplied_transaction_id != self.expected_update_transaction_id:
            raise RecurringUpdatePlanError(
                "update_transaction_id differs from the immutable parent and tail plan"
            )
        recovery_generation = _require_nonnegative_int(
            self.recovery_generation, field_name="recovery_generation"
        )
        if recovery_generation == 0:
            if self.recovery_parent_plan_sha256 is not None:
                raise RecurringUpdatePlanError("initial plan cannot claim a recovery parent plan")
        elif self.recovery_parent_plan_sha256 is None:
            raise RecurringUpdatePlanError(
                "recovery plan requires the exact prior plan content digest"
            )
        else:
            _require_sha256(
                self.recovery_parent_plan_sha256,
                field_name="recovery_parent_plan_sha256",
            )
        _require_bounded_json(
            self.to_dict(),
            label="recurring update plan",
            maximum=_MAX_JSON_BYTES,
        )

    @classmethod
    def create_initial(
        cls,
        *,
        mode: RecurringUpdateMode,
        dataset_ref: str,
        parent_dataset_version: int,
        parent_dataset_version_ref: str,
        parent_authority_sha256: str,
        tail_generation: TailGenerationV1,
    ) -> Self:
        transaction_id = cls._derive_update_transaction_id(
            mode=mode,
            dataset_ref=dataset_ref,
            parent_dataset_version=parent_dataset_version,
            parent_dataset_version_ref=parent_dataset_version_ref,
            parent_authority_sha256=parent_authority_sha256,
            tail_generation=tail_generation,
        )
        return cls(
            mode=mode,
            dataset_ref=dataset_ref,
            parent_dataset_version=parent_dataset_version,
            parent_dataset_version_ref=parent_dataset_version_ref,
            parent_authority_sha256=parent_authority_sha256,
            tail_generation=tail_generation,
            update_transaction_id=transaction_id,
            recovery_generation=0,
            recovery_parent_plan_sha256=None,
        )

    @classmethod
    def recover_from(
        cls,
        previous: RecurringUpdatePlanV1,
        *,
        mode: RecurringUpdateMode,
        dataset_ref: str,
        parent_dataset_version: int,
        parent_dataset_version_ref: str,
        parent_authority_sha256: str,
        tail_generation: TailGenerationV1,
    ) -> Self:
        """Create a recovery receipt only when every semantic authority is unchanged."""

        if not isinstance(previous, RecurringUpdatePlanV1):
            raise RecurringUpdatePlanError("previous must be a RecurringUpdatePlanV1")
        comparisons: tuple[tuple[str, object, object], ...] = (
            ("mode", mode, previous.mode),
            ("dataset_ref", dataset_ref, previous.dataset_ref),
            (
                "parent_dataset_version",
                parent_dataset_version,
                previous.parent_dataset_version,
            ),
            (
                "parent_dataset_version_ref",
                parent_dataset_version_ref,
                previous.parent_dataset_version_ref,
            ),
            (
                "parent_authority_sha256",
                parent_authority_sha256,
                previous.parent_authority_sha256,
            ),
            (
                "tail_generation",
                tail_generation.identity_sha256,
                previous.tail_generation.identity_sha256,
            ),
        )
        drift = [field_name for field_name, actual, wanted in comparisons if actual != wanted]
        if drift:
            raise RecurringUpdatePlanError(
                "recovery authority drift requires a new transaction: " + ", ".join(drift)
            )
        return cls(
            mode=mode,
            dataset_ref=dataset_ref,
            parent_dataset_version=parent_dataset_version,
            parent_dataset_version_ref=parent_dataset_version_ref,
            parent_authority_sha256=parent_authority_sha256,
            tail_generation=tail_generation,
            update_transaction_id=previous.update_transaction_id,
            recovery_generation=previous.recovery_generation + 1,
            recovery_parent_plan_sha256=previous.content_sha256,
        )

    @classmethod
    def _derive_update_transaction_id(
        cls,
        *,
        mode: RecurringUpdateMode,
        dataset_ref: str,
        parent_dataset_version: int,
        parent_dataset_version_ref: str,
        parent_authority_sha256: str,
        tail_generation: TailGenerationV1,
    ) -> str:
        if not isinstance(mode, RecurringUpdateMode):
            raise RecurringUpdatePlanError("mode must be a RecurringUpdateMode")
        normalized_dataset_ref = _require_dataset_ref(dataset_ref)
        normalized_version = _require_positive_int(
            parent_dataset_version, field_name="parent_dataset_version"
        )
        expected_ref = f"{normalized_dataset_ref}/versions/{normalized_version}"
        if parent_dataset_version_ref != expected_ref:
            raise RecurringUpdatePlanError(
                "parent_dataset_version_ref must name the exact positive version; "
                "unversioned and latest aliases are forbidden"
            )
        normalized_authority = _require_sha256(
            parent_authority_sha256, field_name="parent_authority_sha256"
        )
        if not isinstance(tail_generation, TailGenerationV1):
            raise RecurringUpdatePlanError("tail_generation must be a TailGenerationV1")
        return canonical_sha256(
            {
                "domain": _UPDATE_TRANSACTION_DOMAIN,
                "mode": mode.value,
                "parent": {
                    "domain": _PARENT_AUTHORITY_DOMAIN,
                    "dataset_ref": normalized_dataset_ref,
                    "dataset_version": normalized_version,
                    "dataset_version_ref": parent_dataset_version_ref,
                    "authority_sha256": normalized_authority,
                },
                "tail_generation": tail_generation.to_dict(),
                "tail_generation_sha256": tail_generation.identity_sha256,
            }
        )

    @property
    def expected_update_transaction_id(self) -> str:
        return self._derive_update_transaction_id(
            mode=self.mode,
            dataset_ref=self.dataset_ref,
            parent_dataset_version=self.parent_dataset_version,
            parent_dataset_version_ref=self.parent_dataset_version_ref,
            parent_authority_sha256=self.parent_authority_sha256,
            tail_generation=self.tail_generation,
        )

    @property
    def parent_identity_sha256(self) -> str:
        return canonical_sha256(
            {
                "domain": _PARENT_AUTHORITY_DOMAIN,
                "dataset_ref": self.dataset_ref,
                "dataset_version": self.parent_dataset_version,
                "dataset_version_ref": self.parent_dataset_version_ref,
                "authority_sha256": self.parent_authority_sha256,
            }
        )

    def assert_parent_authority(
        self,
        *,
        dataset_ref: str,
        parent_dataset_version: int,
        parent_dataset_version_ref: str,
        parent_authority_sha256: str,
    ) -> None:
        """Fail closed when a handoff no longer names this exact verified parent."""

        expected = (
            ("dataset_ref", dataset_ref, self.dataset_ref),
            (
                "parent_dataset_version",
                parent_dataset_version,
                self.parent_dataset_version,
            ),
            (
                "parent_dataset_version_ref",
                parent_dataset_version_ref,
                self.parent_dataset_version_ref,
            ),
            (
                "parent_authority_sha256",
                parent_authority_sha256,
                self.parent_authority_sha256,
            ),
        )
        drift = [field_name for field_name, actual, wanted in expected if actual != wanted]
        if drift:
            raise RecurringUpdatePlanError("verified parent authority drift: " + ", ".join(drift))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "mode": self.mode.value,
            "dataset_ref": self.dataset_ref,
            "parent_dataset_version": self.parent_dataset_version,
            "parent_dataset_version_ref": self.parent_dataset_version_ref,
            "parent_authority_sha256": self.parent_authority_sha256,
            "parent_identity_sha256": self.parent_identity_sha256,
            "tail_generation": self.tail_generation.to_dict(),
            "tail_generation_sha256": self.tail_generation.identity_sha256,
            "update_transaction_id": self.update_transaction_id,
            "recovery_generation": self.recovery_generation,
            "recovery_parent_plan_sha256": self.recovery_parent_plan_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_bytes(self) -> bytes:
        return self.canonical_bytes

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "mode",
                    "dataset_ref",
                    "parent_dataset_version",
                    "parent_dataset_version_ref",
                    "parent_authority_sha256",
                    "parent_identity_sha256",
                    "tail_generation",
                    "tail_generation_sha256",
                    "update_transaction_id",
                    "recovery_generation",
                    "recovery_parent_plan_sha256",
                }
            ),
            label="recurring update plan",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringUpdatePlanError("recurring update plan schema is invalid")
        try:
            mode = RecurringUpdateMode(_require_safe_token(payload["mode"], field_name="mode"))
        except ValueError as exc:
            raise RecurringUpdatePlanError("unsupported recurring update mode") from exc
        tail = TailGenerationV1.from_dict(
            _require_mapping(payload["tail_generation"], field_name="tail_generation")
        )
        raw_recovery_parent = payload["recovery_parent_plan_sha256"]
        if raw_recovery_parent is not None:
            raw_recovery_parent = _require_sha256(
                raw_recovery_parent, field_name="recovery_parent_plan_sha256"
            )
        result = cls(
            mode=mode,
            dataset_ref=_require_dataset_ref(payload["dataset_ref"]),
            parent_dataset_version=_require_positive_int(
                payload["parent_dataset_version"], field_name="parent_dataset_version"
            ),
            parent_dataset_version_ref=cast("str", payload["parent_dataset_version_ref"]),
            parent_authority_sha256=_require_sha256(
                payload["parent_authority_sha256"], field_name="parent_authority_sha256"
            ),
            tail_generation=tail,
            update_transaction_id=_require_sha256(
                payload["update_transaction_id"], field_name="update_transaction_id"
            ),
            recovery_generation=_require_nonnegative_int(
                payload["recovery_generation"], field_name="recovery_generation"
            ),
            recovery_parent_plan_sha256=raw_recovery_parent,
        )
        expected_digests = (
            (
                "parent_identity_sha256",
                result.parent_identity_sha256,
                payload["parent_identity_sha256"],
            ),
            (
                "tail_generation_sha256",
                result.tail_generation.identity_sha256,
                payload["tail_generation_sha256"],
            ),
        )
        mismatches = [
            field_name
            for field_name, actual, supplied in expected_digests
            if actual != _require_sha256(supplied, field_name=field_name)
        ]
        if mismatches:
            raise RecurringUpdatePlanError(
                "recurring plan authority digest differs: " + ", ".join(mismatches)
            )
        return result

    @classmethod
    def from_bytes(cls, encoded: bytes) -> Self:
        return cls.from_dict(_decode_canonical_json(encoded))
