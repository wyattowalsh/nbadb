"""Externally pinned logical-to-provider parameter authority.

Provider wrappers may expose stable logical parameter names which differ from
the pinned ``nba_api`` constructor names.  Raw Authority V2 keeps both
identities exact: the journal/staging logical-call digest is never rewritten,
and the captured provider attempt retains its independently canonicalized safe
parameter digest.  This contract is the pre-provider receipt which proves the
intentional relationship between those two authorities.

Constructing a receipt does not make it trusted.  Consumers must receive a
separate expected receipt SHA-256 from sealed plan/request-closure authority
and call :func:`verify_logical_provider_parameter_binding`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Never, cast

from nbadb.contracts.raw_request_authority import canonical_semantic_parameters
from nbadb.extract.bronze import canonical_parameters_sha256
from nbadb.extract.raw_request_capture import (
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
)

__all__ = [
    "MAX_LOGICAL_PROVIDER_PARAMETER_BINDING_BYTES",
    "LogicalProviderParameterBindingError",
    "LogicalProviderParameterBindingV1",
    "LogicalProviderParameterEntryV1",
    "compile_logical_provider_parameter_binding",
    "verify_logical_provider_parameter_binding",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_MAX_PROVIDER_CALLS = 4096
_MAX_ROUTE_IDS = 4096
MAX_LOGICAL_PROVIDER_PARAMETER_BINDING_BYTES = 2 * 1024 * 1024


class LogicalProviderParameterBindingError(ValueError):
    """Logical/provider parameter authority is malformed or unpinned."""


def _fail(message: str) -> Never:
    raise LogicalProviderParameterBindingError(message) from None


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact safe identifier")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        _fail("logical/provider parameter binding is not canonical JSON")


def _decode_canonical_object(encoded: object) -> dict[str, object]:
    if (
        type(encoded) is not bytes
        or not encoded
        or len(encoded) > MAX_LOGICAL_PROVIDER_PARAMETER_BINDING_BYTES
    ):
        _fail("logical/provider parameter binding bytes are invalid or unbounded")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        materialized: dict[str, object] = {}
        for key, value in pairs:
            if key in materialized:
                _fail("logical/provider parameter binding repeats a JSON field")
            materialized[key] = value
        return materialized

    try:
        decoded = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: _fail(
                "logical/provider parameter binding contains a non-finite number"
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _fail("logical/provider parameter binding bytes are not exact JSON")
    if type(decoded) is not dict or _canonical_bytes(decoded) != encoded:
        _fail("logical/provider parameter binding bytes are not canonical")
    return cast("dict[str, object]", decoded)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _provider_call_sha256(call: RawProviderCallContextV2) -> str:
    return _canonical_sha256(
        {
            "semantic_request_sha256": call.semantic_request_sha256,
            "logical_invocation_sha256": call.logical_invocation_sha256,
            "provider_call_role": call.provider_call_role,
            "provider_call_ordinal": call.provider_call_ordinal,
            "source_family": call.source_family,
            "endpoint_id": call.endpoint_id,
            "provider_request_sha256": call.provider_request_sha256,
            "competition_identity_sha256": call.competition_identity_sha256,
            "scope_sha256": call.scope_sha256,
            "pagination_sha256": call.pagination_sha256,
            "page_ordinal": call.page_ordinal,
        }
    )


@dataclass(frozen=True, slots=True)
class LogicalProviderParameterEntryV1:
    """One provider-call parameter identity admitted before transport."""

    entry_sha256: str
    request_ordinal: int
    provider_call_ordinal: int
    provider_call_sha256: str
    provider_request_sha256: str
    safe_parameters_sha256: str
    source_family: str
    endpoint_id: str
    endpoint_contract_sha256: str

    schema_version = 1
    kind = "logical_provider_parameter_entry_v1"

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "request_ordinal": self.request_ordinal,
            "provider_call_ordinal": self.provider_call_ordinal,
            "provider_call_sha256": self.provider_call_sha256,
            "provider_request_sha256": self.provider_request_sha256,
            "safe_parameters_sha256": self.safe_parameters_sha256,
            "source_family": self.source_family,
            "endpoint_id": self.endpoint_id,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
        }

    def __post_init__(self) -> None:
        _sha256(self.entry_sha256, label="provider parameter entry")
        if (
            type(self.request_ordinal) is not int
            or self.request_ordinal < 0
            or type(self.provider_call_ordinal) is not int
            or self.provider_call_ordinal < 0
        ):
            _fail("provider parameter entry ordinals must be nonnegative integers")
        for label, value in (
            ("provider call", self.provider_call_sha256),
            ("provider request", self.provider_request_sha256),
            ("safe provider parameters", self.safe_parameters_sha256),
            ("provider endpoint contract", self.endpoint_contract_sha256),
        ):
            _sha256(value, label=label)
        if self.source_family not in {"stats", "live", "static"}:
            _fail("provider parameter entry has a foreign source family")
        _safe_id(self.endpoint_id, label="provider endpoint ID")
        if self.entry_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("provider parameter entry digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        call: RawProviderCallContextV2,
        semantic_parameters: Mapping[str, object],
    ) -> LogicalProviderParameterEntryV1:
        if cls is not LogicalProviderParameterEntryV1:
            _fail("provider parameter entry builder requires the exact class")
        if type(call) is not RawProviderCallContextV2:
            _fail("provider parameter entry requires one exact public call context")
        if not isinstance(semantic_parameters, Mapping):
            _fail("provider semantic parameters must be a mapping")
        try:
            _safe_json, safe_parameters_sha256, provider_request_sha256 = (
                canonical_semantic_parameters(
                    call.source_family,
                    call.endpoint_id,
                    semantic_parameters,
                )
            )
        except Exception:
            _fail("provider semantic parameters differ from pinned request authority")
        if provider_request_sha256 != call.provider_request_sha256:
            _fail("provider semantic parameters differ from their pre-provider call")
        values = {
            "request_ordinal": call.request_ordinal,
            "provider_call_ordinal": call.provider_call_ordinal,
            "provider_call_sha256": _provider_call_sha256(call),
            "provider_request_sha256": provider_request_sha256,
            "safe_parameters_sha256": safe_parameters_sha256,
            "source_family": call.source_family,
            "endpoint_id": call.endpoint_id,
            "endpoint_contract_sha256": call.endpoint_contract_sha256,
        }
        identity = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        return cls(entry_sha256=_canonical_sha256(identity), **values)

    def to_dict(self) -> dict[str, object]:
        return {"entry_sha256": self.entry_sha256, **self.identity_payload()}

    @classmethod
    def from_dict(cls, value: object) -> LogicalProviderParameterEntryV1:
        if cls is not LogicalProviderParameterEntryV1 or type(value) is not dict:
            _fail("provider parameter entry replay requires one exact mapping")
        row = cast("dict[str, object]", value)
        expected = {
            "entry_sha256",
            "schema_version",
            "kind",
            "request_ordinal",
            "provider_call_ordinal",
            "provider_call_sha256",
            "provider_request_sha256",
            "safe_parameters_sha256",
            "source_family",
            "endpoint_id",
            "endpoint_contract_sha256",
        }
        if set(row) != expected or row.get("schema_version") != 1 or row.get("kind") != cls.kind:
            _fail("provider parameter entry replay has a foreign field shape")
        try:
            return cls(
                entry_sha256=cast("str", row["entry_sha256"]),
                request_ordinal=cast("int", row["request_ordinal"]),
                provider_call_ordinal=cast("int", row["provider_call_ordinal"]),
                provider_call_sha256=cast("str", row["provider_call_sha256"]),
                provider_request_sha256=cast("str", row["provider_request_sha256"]),
                safe_parameters_sha256=cast("str", row["safe_parameters_sha256"]),
                source_family=cast("str", row["source_family"]),
                endpoint_id=cast("str", row["endpoint_id"]),
                endpoint_contract_sha256=cast("str", row["endpoint_contract_sha256"]),
            )
        except LogicalProviderParameterBindingError:
            raise
        except Exception:
            _fail("provider parameter entry failed exact replay")


@dataclass(frozen=True, slots=True)
class LogicalProviderParameterBindingV1:
    """One call-level, externally pinned logical/provider parameter join."""

    binding_sha256: str
    logical_endpoint_name: str
    logical_parameters_sha256: str
    result_route_ids: tuple[str, ...]
    provider_entries: tuple[LogicalProviderParameterEntryV1, ...]

    schema_version = 1
    kind = "logical_provider_parameter_binding_v1"

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "logical_endpoint_name": self.logical_endpoint_name,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "result_route_ids": list(self.result_route_ids),
            "provider_entries": [item.to_dict() for item in self.provider_entries],
        }

    def __post_init__(self) -> None:
        _sha256(self.binding_sha256, label="logical/provider parameter binding")
        _safe_id(self.logical_endpoint_name, label="logical endpoint name")
        _sha256(self.logical_parameters_sha256, label="logical parameters")
        if (
            type(self.result_route_ids) is not tuple
            or not self.result_route_ids
            or len(self.result_route_ids) > _MAX_ROUTE_IDS
            or self.result_route_ids != tuple(sorted(self.result_route_ids))
            or len(self.result_route_ids) != len(set(self.result_route_ids))
            or any(type(item) is not str for item in self.result_route_ids)
        ):
            _fail("logical/provider binding route inventory is not exact")
        for route_id in self.result_route_ids:
            _safe_id(route_id, label="logical/provider route ID")
        if (
            type(self.provider_entries) is not tuple
            or not self.provider_entries
            or len(self.provider_entries) > _MAX_PROVIDER_CALLS
            or any(
                type(item) is not LogicalProviderParameterEntryV1 for item in self.provider_entries
            )
        ):
            _fail("logical/provider binding provider inventory is not exact")
        request_ordinals = tuple(item.request_ordinal for item in self.provider_entries)
        provider_ordinals = tuple(item.provider_call_ordinal for item in self.provider_entries)
        provider_calls = tuple(item.provider_call_sha256 for item in self.provider_entries)
        if (
            request_ordinals != tuple(range(len(request_ordinals)))
            or provider_ordinals != tuple(sorted(provider_ordinals))
            or len(provider_ordinals) != len(set(provider_ordinals))
            or len(provider_calls) != len(set(provider_calls))
        ):
            _fail("logical/provider binding entries are unordered or non-bijective")
        if self.binding_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("logical/provider binding digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        logical_endpoint_name: str,
        logical_parameters_sha256: str,
        result_route_ids: tuple[str, ...],
        provider_entries: tuple[LogicalProviderParameterEntryV1, ...],
    ) -> LogicalProviderParameterBindingV1:
        if cls is not LogicalProviderParameterBindingV1:
            _fail("logical/provider binding builder requires the exact class")
        values = {
            "logical_endpoint_name": logical_endpoint_name,
            "logical_parameters_sha256": logical_parameters_sha256,
            "result_route_ids": result_route_ids,
            "provider_entries": provider_entries,
        }
        identity = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "logical_endpoint_name": logical_endpoint_name,
            "logical_parameters_sha256": logical_parameters_sha256,
            "result_route_ids": list(result_route_ids),
            "provider_entries": [item.to_dict() for item in provider_entries],
        }
        return cls(binding_sha256=_canonical_sha256(identity), **values)

    def to_dict(self) -> dict[str, object]:
        return {"binding_sha256": self.binding_sha256, **self.identity_payload()}

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_canonical_bytes(cls, encoded: object) -> LogicalProviderParameterBindingV1:
        if cls is not LogicalProviderParameterBindingV1:
            _fail("logical/provider binding byte replay requires the exact class")
        rebuilt = cls.from_dict(_decode_canonical_object(encoded))
        if rebuilt.canonical_bytes() != encoded:
            _fail("logical/provider binding byte replay is not exact")
        return rebuilt

    @classmethod
    def from_dict(cls, value: object) -> LogicalProviderParameterBindingV1:
        if cls is not LogicalProviderParameterBindingV1 or type(value) is not dict:
            _fail("logical/provider binding replay requires one exact mapping")
        row = cast("dict[str, object]", value)
        expected = {
            "binding_sha256",
            "schema_version",
            "kind",
            "logical_endpoint_name",
            "logical_parameters_sha256",
            "result_route_ids",
            "provider_entries",
        }
        if set(row) != expected or row.get("schema_version") != 1 or row.get("kind") != cls.kind:
            _fail("logical/provider binding replay has a foreign field shape")
        raw_routes = row["result_route_ids"]
        raw_entries = row["provider_entries"]
        if type(raw_routes) is not list or type(raw_entries) is not list:
            _fail("logical/provider binding replay has foreign inventories")
        try:
            return cls(
                binding_sha256=cast("str", row["binding_sha256"]),
                logical_endpoint_name=cast("str", row["logical_endpoint_name"]),
                logical_parameters_sha256=cast("str", row["logical_parameters_sha256"]),
                result_route_ids=tuple(cast("list[str]", raw_routes)),
                provider_entries=tuple(
                    LogicalProviderParameterEntryV1.from_dict(item)
                    for item in cast("list[object]", raw_entries)
                ),
            )
        except LogicalProviderParameterBindingError:
            raise
        except Exception:
            _fail("logical/provider binding failed exact replay")


def compile_logical_provider_parameter_binding(
    *,
    raw_request_context: object,
    logical_endpoint_name: object,
    logical_parameters: object,
    result_route_ids: object,
    provider_semantic_parameters: object,
) -> LogicalProviderParameterBindingV1:
    """Compile a binding before transport from explicit planning authorities."""

    if type(raw_request_context) is not RawRequestCaptureContextV2:
        _fail("logical/provider compiler requires one exact raw-request context")
    if type(logical_endpoint_name) is not str or not isinstance(logical_parameters, Mapping):
        _fail("logical/provider compiler requires exact logical request authority")
    if type(result_route_ids) is not tuple or any(
        type(item) is not str for item in result_route_ids
    ):
        _fail("logical/provider compiler requires one exact route tuple")
    if (
        type(provider_semantic_parameters) is not tuple
        or len(provider_semantic_parameters) != len(raw_request_context.provider_calls)
        or any(not isinstance(item, Mapping) for item in provider_semantic_parameters)
    ):
        _fail("logical/provider compiler parameter inventory differs from provider calls")
    provider_parameters = cast(
        "tuple[Mapping[str, object], ...]",
        provider_semantic_parameters,
    )
    entries = tuple(
        LogicalProviderParameterEntryV1.build(
            call=call,
            semantic_parameters=parameters,
        )
        for call, parameters in zip(
            raw_request_context.provider_calls,
            provider_parameters,
            strict=True,
        )
    )
    try:
        logical_parameters_sha256 = canonical_parameters_sha256(
            cast("Mapping[str, Any]", logical_parameters)
        )
    except Exception:
        _fail("logical/provider compiler logical parameters are not canonical")
    return LogicalProviderParameterBindingV1.build(
        logical_endpoint_name=logical_endpoint_name,
        logical_parameters_sha256=logical_parameters_sha256,
        result_route_ids=cast("tuple[str, ...]", result_route_ids),
        provider_entries=entries,
    )


def verify_logical_provider_parameter_binding(
    value: object,
    *,
    expected_binding_sha256: object,
) -> LogicalProviderParameterBindingV1:
    """Replay one receipt and require its separately supplied external pin."""

    if type(value) is not LogicalProviderParameterBindingV1:
        _fail("logical/provider verification requires the exact binding DTO")
    expected = _sha256(
        expected_binding_sha256,
        label="expected logical/provider parameter binding",
    )
    try:
        replayed = LogicalProviderParameterBindingV1.from_canonical_bytes(value.canonical_bytes())
    except Exception:
        _fail("logical/provider binding failed canonical replay")
    if replayed is value or replayed != value or replayed.binding_sha256 != expected:
        _fail("logical/provider binding differs from its external pin")
    return replayed
