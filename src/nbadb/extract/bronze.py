"""Private, replayable parser-input capture for extraction attempts.

The pinned provider exposes the cleaned decoded string consumed by its parser,
not the original HTTP wire bytes. This module persists that exact UTF-8
representation outside the public warehouse, with immutable secret-safe
receipts and full-SHA content identities.

Response-attempt receipts are diagnostic evidence. Only a verified logical-call
receipt named in a sealed generation manifest can contribute durable coverage.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib
import io
import json
import math
import os
import re
import secrets
import shutil
import stat
import tempfile
import threading
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from nbadb.core.artifact_identity import inventory_regular_tree
from nbadb.core.errors import ExtractionError
from nbadb.core.extraction_failures import (
    SAFE_ROOT_ERROR_NAMES,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_fcntl: Any = importlib.import_module("fcntl") if os.name == "posix" else None

_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_OPEN_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_OPEN_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_OPEN_DIRECTORY = getattr(os, "O_DIRECTORY", 0)

PARSER_INPUT_REPRESENTATION = "nbadb_exact_decoded_response_text_utf8"
STATIC_INPUT_REPRESENTATION = "nba_api_static_canonical_json_utf8"
BRONZE_SCHEMA_VERSION = 6

# This codec remains provisional until the repository's representative-corpus
# benchmark is checked in and the capacity gate is green. The contract digest
# prevents an implementation change from masquerading as the same generation.
DEFAULT_CODEC = "gzip-6-provisional"
_CODEC_CONTRACT = {
    "codec": DEFAULT_CODEC,
    "format": "gzip",
    "compresslevel": 6,
    "mtime": 0,
    "identity_basis": "uncompressed_representation_bytes",
}
CODEC_CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(_CODEC_CONTRACT, sort_keys=True, separators=(",", ":")).encode("ascii")
).hexdigest()

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}")
_SAFE_RESULT_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}")
_SECRET_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|key|password|proxy|secret|token|user)",
    re.IGNORECASE,
)
_BLOB_NAME_RE = re.compile(r"([0-9a-f]{64})\.payload\.gz")
_RECEIPT_NAME_RE = re.compile(r"([0-9a-f]{64})\.json")

_MAX_PARAMETER_COUNT = 256
_MAX_PARAMETER_KEY_CHARS = 128
_MAX_PARAMETER_STRING_CHARS = 4096
_MAX_PARAMETER_LIST_ITEMS = 1024

_RESULT_CONTAINER_KINDS = frozenset(
    {
        "nba_api_result_set",
        "nba_api_static_records",
        "nba_api_live_json_array",
        "nba_api_live_json_object",
    }
)
_LIVE_RESULT_CONTAINER_KINDS = frozenset({"nba_api_live_json_array", "nba_api_live_json_object"})

_OUTCOMES = frozenset(
    {
        "success_nonempty",
        "success_empty",
        "http_transient_error",
        "http_application_error",
        "malformed_json",
        "application_error_envelope",
        "contract_mismatch",
        "parser_failure",
        "transport_failure_no_response",
        "cancelled_before_response",
    }
)
_SUCCESS_OUTCOMES = frozenset({"success_nonempty", "success_empty"})
_NO_RESPONSE_OUTCOMES = frozenset({"transport_failure_no_response", "cancelled_before_response"})
_FAILURE_CLASSES = frozenset(
    {
        "transport_transient",
        "response_contract",
        "application",
        "vpn_egress",
        "runner_infrastructure",
        "timeout_progress",
        "timeout_stalled",
        "contract_blocked",
    }
)
_ROOT_EXCEPTION_CLASSES = SAFE_ROOT_ERROR_NAMES
_SOURCE_FAMILIES = frozenset({"stats", "live", "static"})
_TRANSPORT_KINDS = frozenset({"http_response", "static_provider_snapshot"})

Outcome = Literal[
    "success_nonempty",
    "success_empty",
    "http_transient_error",
    "http_application_error",
    "malformed_json",
    "application_error_envelope",
    "contract_mismatch",
    "parser_failure",
    "transport_failure_no_response",
    "cancelled_before_response",
]
TransportKind = Literal["http_response", "static_provider_snapshot"]


class ParserInputCapacityError(ExtractionError):
    """A parser input or private generation exceeded a configured hard limit."""


@dataclass(frozen=True, slots=True)
class BronzeLimits:
    """Fail-closed limits; callers must choose evidence-backed values."""

    max_response_bytes: int
    max_generation_stored_bytes: int
    minimum_free_bytes: int
    max_receipt_bytes: int = 1_000_000
    max_receipt_count: int = 1_000_000
    max_checkpoint_bytes: int | None = None
    minimum_deadline_headroom_seconds: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "max_response_bytes",
            "max_generation_stored_bytes",
            "minimum_free_bytes",
            "max_receipt_bytes",
            "max_receipt_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.max_checkpoint_bytes is not None and (
            isinstance(self.max_checkpoint_bytes, bool)
            or not isinstance(self.max_checkpoint_bytes, int)
            or self.max_checkpoint_bytes <= 0
        ):
            raise ValueError("max_checkpoint_bytes must be a positive integer when present")
        headroom = self.minimum_deadline_headroom_seconds
        if headroom is not None and (
            isinstance(headroom, bool)
            or not isinstance(headroom, int | float)
            or not math.isfinite(headroom)
            or headroom <= 0
        ):
            raise ValueError(
                "minimum_deadline_headroom_seconds must be positive and finite when present"
            )
        if (self.max_checkpoint_bytes is None) != (headroom is None):
            raise ValueError(
                "checkpoint-byte and deadline-headroom limits must be configured together"
            )


@dataclass(frozen=True, slots=True)
class ParserInputContext:
    """Allowlisted execution provenance for one logical provider invocation."""

    attempt_id: str
    retry_ordinal: int = 0
    request_ordinal: int = 0
    workflow_run_id: int | None = None
    workflow_run_attempt: int | None = None
    chain_id: str | None = None
    lane_id: str | None = None
    semantic_source_sha: str | None = None

    def __post_init__(self) -> None:
        _validate_token("attempt_id", self.attempt_id)
        for field_name in ("retry_ordinal", "request_ordinal"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in ("workflow_run_id", "workflow_run_attempt"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{field_name} must be a positive integer when present")
        for field_name in ("chain_id", "lane_id"):
            value = getattr(self, field_name)
            if value is not None:
                _validate_token(field_name, value)
        if self.semantic_source_sha is not None:
            _validate_git_sha("semantic_source_sha", self.semantic_source_sha)


@dataclass(frozen=True, slots=True)
class LogicalCallReceiptBinding:
    """Public-safe root binding one successful endpoint call to its routes."""

    logical_call_receipt_sha256: str
    endpoint_name: str
    logical_parameters_sha256: str
    provider_authority_sha256: str
    result_route_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_sha256(
            "logical_call_receipt_sha256",
            self.logical_call_receipt_sha256,
        )
        _validate_token("endpoint_name", self.endpoint_name)
        _validate_sha256("logical_parameters_sha256", self.logical_parameters_sha256)
        _validate_sha256("provider_authority_sha256", self.provider_authority_sha256)
        routes = tuple(_validate_token("result_route_id", route) for route in self.result_route_ids)
        if not routes or routes != tuple(sorted(set(routes))):
            raise ValueError("result_route_ids must be a sorted unique nonempty tuple")


def _logical_call_binding_payload(
    binding: LogicalCallReceiptBinding,
) -> dict[str, object]:
    return {
        "endpoint_name": binding.endpoint_name,
        "logical_call_receipt_sha256": binding.logical_call_receipt_sha256,
        "logical_parameters_sha256": binding.logical_parameters_sha256,
        "provider_authority_sha256": binding.provider_authority_sha256,
        "result_route_ids": list(binding.result_route_ids),
    }


def _logical_call_bindings_from_payload(
    payload: object,
) -> tuple[LogicalCallReceiptBinding, ...]:
    if not isinstance(payload, list):
        raise ValueError("done_call_bindings must be a list")
    expected_keys = {
        "endpoint_name",
        "logical_call_receipt_sha256",
        "logical_parameters_sha256",
        "provider_authority_sha256",
        "result_route_ids",
    }
    bindings: list[LogicalCallReceiptBinding] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise ValueError("done_call_bindings members do not match the schema")
        binding_payload = cast("dict[str, object]", item)
        endpoint_name = binding_payload["endpoint_name"]
        root = binding_payload["logical_call_receipt_sha256"]
        parameter_digest = binding_payload["logical_parameters_sha256"]
        provider_digest = binding_payload["provider_authority_sha256"]
        routes = binding_payload["result_route_ids"]
        if any(
            not isinstance(value, str)
            for value in (endpoint_name, root, parameter_digest, provider_digest)
        ):
            raise ValueError("done_call_bindings identities must be strings")
        if not isinstance(routes, list):
            raise ValueError("done_call_bindings result routes must be a list")
        route_ids: list[str] = []
        for route in routes:
            if not isinstance(route, str):
                raise ValueError("done_call_bindings result routes must be strings")
            route_ids.append(route)
        bindings.append(
            LogicalCallReceiptBinding(
                logical_call_receipt_sha256=cast("str", root),
                endpoint_name=cast("str", endpoint_name),
                logical_parameters_sha256=cast("str", parameter_digest),
                provider_authority_sha256=cast("str", provider_digest),
                result_route_ids=tuple(route_ids),
            )
        )
    roots = tuple(binding.logical_call_receipt_sha256 for binding in bindings)
    if roots != tuple(sorted(set(roots))):
        raise ValueError("done_call_bindings must be ordered by unique receipt root")
    if payload != [_logical_call_binding_payload(binding) for binding in bindings]:
        raise ValueError("done_call_bindings are not canonical")
    return tuple(bindings)


@dataclass(frozen=True, slots=True)
class CapturedParserInput:
    representation: str
    response_sha256: str
    object_sha256: str
    uncompressed_bytes: int
    stored_sha256: str
    stored_bytes: int
    codec: str
    relative_path: str

    def __post_init__(self) -> None:
        if self.representation not in {
            PARSER_INPUT_REPRESENTATION,
            STATIC_INPUT_REPRESENTATION,
        }:
            raise ValueError("unsupported parser-input representation")
        _validate_sha256("response_sha256", self.response_sha256)
        _validate_sha256("object_sha256", self.object_sha256)
        _validate_sha256("stored_sha256", self.stored_sha256)
        if (
            isinstance(self.uncompressed_bytes, bool)
            or not isinstance(self.uncompressed_bytes, int)
            or self.uncompressed_bytes < 0
        ):
            raise ValueError("uncompressed_bytes must be a non-negative integer")
        if (
            isinstance(self.stored_bytes, bool)
            or not isinstance(self.stored_bytes, int)
            or self.stored_bytes <= 0
        ):
            raise ValueError("stored_bytes must be a positive integer")
        if self.codec != DEFAULT_CODEC:
            raise ValueError("unsupported parser-input codec")
        relative = Path(self.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("parser-input relative_path is unsafe")
        expected = _blob_relative_path(self.object_sha256)
        if relative.as_posix() != expected.as_posix():
            raise ValueError("parser-input relative_path is not canonical")


@dataclass(frozen=True, slots=True)
class ResultSetReceipt:
    name: str
    provider_index: int | None
    canonical_index: int | None
    headers_sha256: str
    row_count: int
    json_path: str | None
    container_kind: str
    container_count: int
    missing_count: int
    null_count: int
    parent_observation_count: int
    parent_occurrence_states_sha256: str
    observed_field_orders_sha256: str
    normalized_output_sha256: str

    def __post_init__(self) -> None:
        if _SAFE_RESULT_NAME_RE.fullmatch(self.name) is None:
            raise ValueError("result-set name is not a safe bounded identifier")
        if self.provider_index is not None and (
            isinstance(self.provider_index, bool)
            or not isinstance(self.provider_index, int)
            or self.provider_index < 0
        ):
            raise ValueError("provider_index must be a non-negative integer when present")
        for field_name in (
            "row_count",
            "container_count",
            "missing_count",
            "null_count",
            "parent_observation_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.canonical_index is not None and (
            isinstance(self.canonical_index, bool)
            or not isinstance(self.canonical_index, int)
            or self.canonical_index < 0
        ):
            raise ValueError("canonical_index must be a non-negative integer when present")
        if self.json_path is not None and (
            not isinstance(self.json_path, str) or not self.json_path.startswith("$.")
        ):
            raise ValueError("json_path must be an absolute JSON path when present")
        if self.container_kind not in _RESULT_CONTAINER_KINDS:
            raise ValueError("container_kind is not in the fixed result-set contract")
        if self.parent_observation_count != (
            self.container_count + self.missing_count + self.null_count
        ):
            raise ValueError("parent observations do not reconcile with result-set states")
        if self.row_count and not self.container_count:
            raise ValueError("nonempty result sets require at least one present container")
        if (
            self.container_kind == "nba_api_live_json_object"
            and self.row_count != self.container_count
        ):
            raise ValueError("live object result-set rows must reconcile with containers")
        _validate_sha256("headers_sha256", self.headers_sha256)
        _validate_sha256(
            "parent_occurrence_states_sha256",
            self.parent_occurrence_states_sha256,
        )
        _validate_sha256("observed_field_orders_sha256", self.observed_field_orders_sha256)
        _validate_sha256("normalized_output_sha256", self.normalized_output_sha256)


@dataclass(frozen=True, slots=True)
class RecordedParserInput:
    """One fully verified response-attempt receipt and its immutable parser input."""

    receipt_sha256: str
    transport_kind: TransportKind
    source_family: str
    endpoint_id: str
    endpoint_slug: str
    parameters_sha256: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    status_code: int | None
    outcome: Outcome
    result_sets: tuple[ResultSetReceipt, ...]
    captured: CapturedParserInput
    parser_input: bytes


class ParserInputReplaySource(Protocol):
    """Read-only verified input boundary used by no-network adapter replay."""

    def load_recorded_attempt(self, receipt_sha256: str) -> RecordedParserInput: ...


class ParserInputCaptureSink(ParserInputReplaySource, Protocol):
    """Adapter-facing capture interface; implementations must be thread-safe."""

    def replay_parser_input(self, receipt_sha256: str) -> bytes: ...

    def store_parser_input(
        self,
        payload: str,
        *,
        representation: str,
    ) -> CapturedParserInput: ...

    def store_static_records(self, records: object) -> CapturedParserInput: ...

    def record_response_attempt(
        self,
        *,
        context: ParserInputContext,
        transport_kind: TransportKind,
        source_family: str,
        endpoint_id: str,
        endpoint_slug: str,
        parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        contract_sha256: str,
        status_code: int | None,
        captured: CapturedParserInput,
        outcome: Outcome,
        failure_class: str | None,
        root_exception_class: str | None,
        result_sets: Sequence[ResultSetReceipt],
        effective_status_code: int | None = None,
    ) -> str: ...

    def record_static_snapshot_attempt(
        self,
        *,
        context: ParserInputContext,
        endpoint_id: str,
        endpoint_slug: str,
        provider_authority_sha256: str,
        contract_sha256: str,
        captured: CapturedParserInput,
        result_set: ResultSetReceipt,
    ) -> str: ...

    def record_no_response_attempt(
        self,
        *,
        context: ParserInputContext,
        transport_kind: TransportKind,
        source_family: str,
        endpoint_id: str,
        endpoint_slug: str,
        parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        contract_sha256: str,
        outcome: Outcome,
        failure_class: str,
        root_exception_class: str,
    ) -> str: ...

    def record_logical_call(
        self,
        *,
        context: ParserInputContext,
        logical_endpoint_id: str,
        logical_parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        response_receipt_sha256s: Sequence[str],
        successful_response_ordinals: Sequence[int],
        result_route_ids: Sequence[str],
    ) -> str: ...


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _validate_parameter_scalar(key: str, value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        if isinstance(value, str) and len(value) > _MAX_PARAMETER_STRING_CHARS:
            raise ValueError(f"request parameter {key!r} exceeds the string limit")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"request parameter {key!r} must be finite")
        return value
    raise ValueError(f"request parameter {key!r} has an unsupported value type")


def _safe_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    if len(parameters) > _MAX_PARAMETER_COUNT:
        raise ValueError("request parameter count exceeds the bounded contract")
    validated: list[tuple[str, Any]] = []
    for key, value in parameters.items():
        if not isinstance(key, str):
            raise ValueError("request parameter keys must be strings")
        if len(key) > _MAX_PARAMETER_KEY_CHARS or not key:
            raise ValueError("request parameter key exceeds the bounded contract")
        if _SECRET_KEY_RE.search(key):
            raise ValueError("request parameters contain a forbidden key")
        if isinstance(value, (list, tuple)):
            if len(value) > _MAX_PARAMETER_LIST_ITEMS:
                raise ValueError(f"request parameter {key!r} exceeds the list limit")
            validated.append((key, [_validate_parameter_scalar(key, item) for item in value]))
        else:
            validated.append((key, _validate_parameter_scalar(key, value)))
    return dict(sorted(validated))


def canonical_parameters_payload(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical secret-safe JSON payload for logical parameters.

    The returned object is detached from the caller's mapping and sequences so it
    can be persisted without retaining mutable caller-owned values.
    """

    return _safe_parameters(parameters)


def canonical_parameters_sha256(parameters: Mapping[str, Any]) -> str:
    """Return a full digest without persisting parameter values in receipts."""

    return _sha256(_canonical_json_bytes(canonical_parameters_payload(parameters)))


def result_sets_digest(result_sets: Sequence[ResultSetReceipt]) -> str:
    return _sha256(_canonical_json_bytes([asdict(result_set) for result_set in result_sets]))


def parent_occurrence_states_digest(states: Sequence[str]) -> str:
    """Bind the ordered present/null/missing state of parent observations."""

    allowed = frozenset({"present", "missing", "null"})
    values = tuple(states)
    if any(state not in allowed for state in values):
        raise ValueError("parent occurrence state is not in the fixed result-set contract")
    return _sha256(_canonical_json_bytes(values))


def _validate_sha256(name: str, value: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase full SHA-256")
    return value


def _validate_git_sha(name: str, value: str) -> str:
    if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase full Git SHA-1")
    return value


def _validate_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_token(name: str, value: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} is not a safe bounded identifier")
    return value


def _validate_failure_metadata(
    *,
    transport_kind: str,
    outcome: str,
    failure_class: str | None,
    root_exception_class: str | None,
    status_code: int | None,
    effective_status_code: int | None,
    parser_input_representation: str | None,
) -> None:
    if transport_kind not in _TRANSPORT_KINDS:
        raise ValueError("transport_kind is not in the fixed provider contract")
    if outcome not in _OUTCOMES:
        raise ValueError("outcome is not in the fixed parser-input contract")
    if status_code is not None and (
        isinstance(status_code, bool)
        or not isinstance(status_code, int)
        or not 100 <= status_code <= 599
    ):
        raise ValueError("status_code must be an HTTP status when present")
    if effective_status_code is not None and (
        isinstance(effective_status_code, bool)
        or not isinstance(effective_status_code, int)
        or not 100 <= effective_status_code <= 599
    ):
        raise ValueError("effective_status_code must be an HTTP status when present")
    has_parser_input = parser_input_representation is not None
    if transport_kind == "static_provider_snapshot":
        if status_code is not None or effective_status_code is not None:
            raise ValueError("static provider snapshots cannot carry HTTP status")
        if (
            parser_input_representation is not None
            and parser_input_representation != STATIC_INPUT_REPRESENTATION
        ):
            raise ValueError("static provider snapshots require canonical static input")
        if outcome in {
            "http_transient_error",
            "http_application_error",
            "application_error_envelope",
            "malformed_json",
            "transport_failure_no_response",
        }:
            raise ValueError("static provider snapshots cannot carry HTTP outcomes")
        if outcome in _SUCCESS_OUTCOMES:
            if failure_class is not None or root_exception_class is not None:
                raise ValueError("successful outcomes cannot carry failure metadata")
            if not has_parser_input:
                raise ValueError("successful static outcomes require a captured snapshot")
            return
        if failure_class not in _FAILURE_CLASSES:
            raise ValueError("failure_class is not in the fixed extraction taxonomy")
        if root_exception_class not in _ROOT_EXCEPTION_CLASSES:
            raise ValueError("root_exception_class is not in the fixed safe allowlist")
        if outcome == "cancelled_before_response" and has_parser_input:
            raise ValueError("cancelled static snapshots cannot carry parser input")
        return

    if (
        parser_input_representation is not None
        and parser_input_representation != PARSER_INPUT_REPRESENTATION
    ):
        raise ValueError("HTTP responses require the exact decoded-response parser input")
    outcome_status = effective_status_code if effective_status_code is not None else status_code
    if outcome in _SUCCESS_OUTCOMES:
        if failure_class is not None or root_exception_class is not None:
            raise ValueError("successful outcomes cannot carry failure metadata")
        if (
            status_code is None
            or not 200 <= status_code < 300
            or (effective_status_code is not None and not 200 <= effective_status_code < 300)
            or not has_parser_input
        ):
            raise ValueError("successful outcomes require a captured 2xx response")
        return
    if failure_class not in _FAILURE_CLASSES:
        raise ValueError("failure_class is not in the fixed extraction taxonomy")
    if root_exception_class not in _ROOT_EXCEPTION_CLASSES:
        raise ValueError("root_exception_class is not in the fixed safe allowlist")
    if outcome in _NO_RESPONSE_OUTCOMES:
        if status_code is not None or effective_status_code is not None or has_parser_input:
            raise ValueError("no-response outcomes cannot carry response evidence")
        return
    if not has_parser_input:
        raise ValueError("response outcomes require captured parser input")
    if outcome == "http_transient_error" and not (
        outcome_status == 429 or (outcome_status is not None and outcome_status >= 500)
    ):
        raise ValueError("transient HTTP outcomes require status 429 or 5xx")
    if outcome == "http_application_error" and not (
        outcome_status is not None and 400 <= outcome_status < 500 and outcome_status != 429
    ):
        raise ValueError("application HTTP outcomes require deterministic 4xx status")


def _validate_transport_source(transport_kind: str, source_family: str) -> None:
    if transport_kind not in _TRANSPORT_KINDS:
        raise ValueError("transport_kind is not in the fixed provider contract")
    if source_family not in _SOURCE_FAMILIES:
        raise ValueError("source_family is not in the fixed provider contract")
    is_static = transport_kind == "static_provider_snapshot"
    if is_static != (source_family == "static"):
        raise ValueError("transport kind and source family disagree")


def _validate_transport_endpoint(
    transport_kind: str,
    endpoint_id: str,
    endpoint_slug: str,
) -> None:
    if transport_kind == "static_provider_snapshot" and endpoint_id != f"static_{endpoint_slug}":
        raise ValueError("static endpoint identity is not canonical")


def _validate_outcome_result_sets(
    outcome: str,
    result_sets: Sequence[ResultSetReceipt],
) -> None:
    if outcome == "success_empty" and any(item.row_count for item in result_sets):
        raise ValueError("success_empty cannot contain nonempty result sets")
    if (
        outcome == "success_nonempty"
        and result_sets
        and not any(item.row_count for item in result_sets)
    ):
        raise ValueError("success_nonempty requires a nonempty result set")


def _validate_transport_result_sets(
    transport_kind: str,
    source_family: str,
    endpoint_slug: str,
    outcome: str,
    result_sets: Sequence[ResultSetReceipt],
) -> None:
    if source_family == "live":
        if any(
            item.provider_index is not None
            or item.canonical_index is None
            or item.json_path is None
            or item.container_kind not in _LIVE_RESULT_CONTAINER_KINDS
            for item in result_sets
        ):
            raise ValueError("live response result-set identity is not canonical")
        return
    if source_family == "stats":
        fallback = bool(result_sets) and any(item.canonical_index is None for item in result_sets)
        if fallback:
            if outcome not in _SUCCESS_OUTCOMES:
                raise ValueError("failed stats responses cannot carry fallback result sets")
            provider_indexes: list[int] = []
            for item in result_sets:
                if (
                    item.canonical_index is not None
                    or item.json_path is not None
                    or item.container_kind != "nba_api_result_set"
                    or item.parent_observation_count != 1
                    or item.null_count
                ):
                    raise ValueError("stats fallback result-set identity is not canonical")
                if item.provider_index is None:
                    if (
                        item.row_count
                        or item.container_count
                        or item.missing_count != 1
                        or item.parent_occurrence_states_sha256
                        != parent_occurrence_states_digest(("missing",))
                    ):
                        raise ValueError(
                            "missing stats fallback result-set identity is not canonical"
                        )
                else:
                    provider_indexes.append(item.provider_index)
                    if (
                        item.container_count != 1
                        or item.missing_count
                        or item.parent_occurrence_states_sha256
                        != parent_occurrence_states_digest(("present",))
                    ):
                        raise ValueError(
                            "present stats fallback result-set identity is not canonical"
                        )
            if provider_indexes != list(range(len(provider_indexes))):
                raise ValueError(
                    "stats fallback result sets do not preserve provider occurrence order"
                )
            return
        if any(
            item.provider_index is None
            or item.canonical_index is None
            or item.json_path is not None
            or item.container_kind != "nba_api_result_set"
            or item.parent_observation_count != 1
            or item.container_count != 1
            or item.missing_count
            or item.null_count
            or item.parent_occurrence_states_sha256 != parent_occurrence_states_digest(("present",))
            for item in result_sets
        ):
            raise ValueError("stats response result-set identity is not canonical")
        return
    if outcome not in _SUCCESS_OUTCOMES:
        if result_sets:
            raise ValueError("failed static snapshots cannot carry parsed result sets")
        return
    if len(result_sets) != 1:
        raise ValueError("static snapshot requires exactly one result-set receipt")
    result_set = result_sets[0]
    if (
        result_set.name != f"{endpoint_slug}_shape_1"
        or result_set.provider_index != 0
        or result_set.canonical_index != 0
        or result_set.json_path is not None
        or result_set.container_kind != "nba_api_static_records"
        or result_set.parent_observation_count != 1
        or result_set.container_count != 1
        or result_set.missing_count
        or result_set.null_count
        or result_set.parent_occurrence_states_sha256
        != parent_occurrence_states_digest(("present",))
    ):
        raise ValueError("static snapshot result-set identity is not canonical")


def _blob_relative_path(object_sha256: str) -> Path:
    return Path("blobs") / "sha256" / object_sha256[:2] / f"{object_sha256}.payload.gz"


def _receipt_relative_path(kind: str, digest: str) -> Path:
    return Path("receipts") / kind / digest[:2] / f"{digest}.json"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _existing_symlink(path: Path) -> Path | None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return current
        if not current.exists():
            break
    return None


def _atomic_write_new(path: Path, payload: bytes) -> bool:
    """Publish without clobbering; return False when an identical winner exists."""

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        try:
            os.link(temporary_path, path)
            published = True
            _fsync_directory(path.parent)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ExtractionError(
                    "immutable parser-input path disagrees with content"
                ) from None
        return published
    finally:
        temporary_path.unlink(missing_ok=True)


def _descriptor_identity(observed: os.stat_result) -> tuple[int, int]:
    return observed.st_dev, observed.st_ino


def _descriptor_entry_identity(
    observed: os.stat_result,
) -> tuple[int, int, int, int, int, int]:
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def _validate_root_identity(value: object) -> tuple[int, int]:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value)
        or value[1] == 0
    ):
        raise ValueError("expected_root_identity must be a (device, inode) integer pair")
    return cast("tuple[int, int]", value)


def _open_authorized_directory(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    label: str,
) -> int:
    """Open an absolute directory one component at a time and bind its inode."""

    if os.name != "posix" or not _OPEN_NOFOLLOW or not _OPEN_DIRECTORY:
        raise RuntimeError("private bronze descriptor authority requires POSIX O_NOFOLLOW")
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError(f"{label} must be an absolute Path")
    identity = _validate_root_identity(expected_identity)
    absolute = Path(os.path.abspath(path))
    descriptor = -1
    try:
        parts = absolute.parts
        descriptor = os.open(
            parts[0],
            os.O_RDONLY | _OPEN_DIRECTORY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK,
        )
        for component in parts[1:]:
            child = os.open(
                component,
                os.O_RDONLY | _OPEN_DIRECTORY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        opened = os.fstat(descriptor)
        named = os.stat(absolute, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or _descriptor_identity(opened) != identity
            or _descriptor_identity(named) != identity
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o700
        ):
            raise ExtractionError(f"{label} authority is invalid")
        return descriptor
    except (OSError, ValueError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(f"{label} cannot be opened safely") from exc


def _open_generation_under_authorized_parent(
    parent_descriptor: int,
    generation_name: str,
) -> tuple[int, tuple[int, int]]:
    if (
        not isinstance(generation_name, str)
        or _SAFE_ID_RE.fullmatch(generation_name) is None
        or generation_name in {".", ".."}
    ):
        raise ValueError("private bronze generation_name is invalid")
    created = False
    created_identity: tuple[int, int] | None = None
    try:
        try:
            os.mkdir(generation_name, mode=0o700, dir_fd=parent_descriptor)
            created = True
            created_stat = os.stat(
                generation_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            created_identity = _descriptor_identity(created_stat)
        except FileExistsError:
            pass
        descriptor = os.open(
            generation_name,
            os.O_RDONLY | _OPEN_DIRECTORY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK,
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(descriptor)
        named = os.stat(
            generation_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        identity = _descriptor_identity(opened)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or identity != _descriptor_identity(named)
            or (created_identity is not None and identity != created_identity)
            or opened.st_uid != os.geteuid()
        ):
            raise ExtractionError("private bronze generation authority is invalid")
        if created:
            os.fchmod(descriptor, 0o700)
            os.fsync(parent_descriptor)
            opened = os.fstat(descriptor)
        if stat.S_IMODE(opened.st_mode) != 0o700:
            raise ExtractionError("private bronze generation must be owner-only 0700")
        return descriptor, identity
    except (OSError, ValueError) as exc:
        if "descriptor" in locals():
            with suppress(OSError):
                os.close(descriptor)
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError("private bronze generation cannot be opened safely") from exc


def _validate_relative_descriptor_path(path: Path) -> tuple[str, ...]:
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ExtractionError("private bronze descriptor path is invalid")
    return path.parts


def _open_relative_descriptor(
    root_descriptor: int,
    relative: Path,
    *,
    directory: bool = False,
    read_write: bool = False,
) -> int:
    if not _OPEN_NOFOLLOW:
        raise RuntimeError("private bronze retained restore requires O_NOFOLLOW support")
    parts = _validate_relative_descriptor_path(relative)
    parent_descriptor = root_descriptor
    opened_parents: list[int] = []
    try:
        for part in parts[:-1]:
            descriptor = os.open(
                part,
                os.O_RDONLY | _OPEN_DIRECTORY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK,
                dir_fd=parent_descriptor,
            )
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise ExtractionError("private bronze descriptor path parent is not a directory")
            opened_parents.append(descriptor)
            parent_descriptor = descriptor
        flags = (os.O_RDWR if read_write else os.O_RDONLY) | _OPEN_NOFOLLOW | _OPEN_CLOEXEC
        if directory:
            flags |= _OPEN_DIRECTORY
        else:
            flags |= _OPEN_NONBLOCK
        return os.open(parts[-1], flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise ExtractionError("private bronze descriptor path is unavailable or unsafe") from exc
    finally:
        for descriptor in reversed(opened_parents):
            os.close(descriptor)


def _read_regular_descriptor(descriptor: int, *, display_path: str) -> bytes:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ExtractionError(f"private bronze path is not a regular file: {display_path}")
    if before.st_nlink != 1:
        raise ExtractionError(f"private bronze path is aliased: {display_path}")
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    after = os.fstat(descriptor)
    if _descriptor_entry_identity(before) != _descriptor_entry_identity(after):
        raise ExtractionError(f"private bronze file changed while reading: {display_path}")
    return b"".join(chunks)


def _hash_regular_descriptor(descriptor: int, *, display_path: str) -> tuple[int, str]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ExtractionError(f"private bronze path is not a regular file: {display_path}")
    if before.st_nlink != 1:
        raise ExtractionError(f"private bronze path is aliased: {display_path}")
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    after = os.fstat(descriptor)
    if _descriptor_entry_identity(before) != _descriptor_entry_identity(after):
        raise ExtractionError(f"private bronze file changed while hashing: {display_path}")
    return before.st_size, digest.hexdigest()


def _read_relative_regular(root_descriptor: int, relative: Path) -> bytes:
    descriptor = _open_relative_descriptor(root_descriptor, relative)
    try:
        return _read_regular_descriptor(descriptor, display_path=relative.as_posix())
    finally:
        os.close(descriptor)


def _inventory_directory_descriptor(
    directory_descriptor: int,
    *,
    prefix: Path | None,
    excluded_paths: frozenset[str],
    observations: dict[str, tuple[int, int, int, int, int, int]],
) -> list[dict[str, Any]]:
    display_path = "." if prefix is None else prefix.as_posix()
    before = os.fstat(directory_descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise ExtractionError("private bronze inventory root is not a directory")
    try:
        with os.scandir(directory_descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
    except OSError as exc:
        raise ExtractionError("private bronze generation cannot be inventoried safely") from exc
    inventory: list[dict[str, Any]] = []
    for name in names:
        relative = Path(name) if prefix is None else prefix / name
        descriptor = _open_relative_descriptor(directory_descriptor, Path(name))
        try:
            observed = os.fstat(descriptor)
            if stat.S_ISDIR(observed.st_mode):
                inventory.extend(
                    _inventory_directory_descriptor(
                        descriptor,
                        prefix=relative,
                        excluded_paths=excluded_paths,
                        observations=observations,
                    )
                )
                after_child = os.fstat(descriptor)
                if _descriptor_entry_identity(observed) != _descriptor_entry_identity(after_child):
                    raise ExtractionError(
                        "private bronze directory changed while inventorying: "
                        f"{relative.as_posix()}"
                    )
                continue
            if relative.as_posix() in excluded_paths:
                if not stat.S_ISREG(observed.st_mode):
                    raise ExtractionError("private bronze excluded path is not a regular file")
                observations[relative.as_posix()] = _descriptor_entry_identity(observed)
                continue
            byte_count, sha256 = _hash_regular_descriptor(
                descriptor,
                display_path=relative.as_posix(),
            )
            observations[relative.as_posix()] = _descriptor_entry_identity(os.fstat(descriptor))
            inventory.append(
                {
                    "path": relative.as_posix(),
                    "bytes": byte_count,
                    "sha256": sha256,
                }
            )
        finally:
            os.close(descriptor)
    after = os.fstat(directory_descriptor)
    if _descriptor_entry_identity(before) != _descriptor_entry_identity(after):
        raise ExtractionError(
            f"private bronze directory changed while inventorying: {display_path}"
        )
    observations[display_path] = _descriptor_entry_identity(after)
    inventory.sort(key=lambda item: item["path"])
    return inventory


def _verify_inventory_observations(
    root_descriptor: int,
    observations: dict[str, tuple[int, int, int, int, int, int]],
) -> None:
    """Recheck every entry after the complete recursive descriptor snapshot."""

    for relative_path, expected in sorted(observations.items()):
        descriptor = (
            os.dup(root_descriptor)
            if relative_path == "."
            else _open_relative_descriptor(
                root_descriptor,
                Path(relative_path),
                directory=stat.S_ISDIR(expected[2]),
            )
        )
        try:
            observed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if _descriptor_entry_identity(observed) != expected:
            raise ExtractionError(f"private bronze path changed after inventory: {relative_path}")


def _inventory_relative_regular_tree(
    root_descriptor: int,
    *,
    excluded_paths: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    observations: dict[str, tuple[int, int, int, int, int, int]] = {}
    inventory = _inventory_directory_descriptor(
        root_descriptor,
        prefix=None,
        excluded_paths=excluded_paths,
        observations=observations,
    )
    _verify_inventory_observations(root_descriptor, observations)
    return inventory


class BronzeCaptureStore:
    """Private content-addressed parser-input and receipt store.

    One process owns a generation through an advisory lock. Calls within that
    process are serialized by a reentrant lock, providing atomic accounting and
    a race-free seal boundary.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        limits: BronzeLimits,
        public_roots: Sequence[Path | str],
        codec: str = DEFAULT_CODEC,
    ) -> None:
        if codec != DEFAULT_CODEC:
            raise ValueError("unsupported parser-input codec")
        requested_root = Path(root).absolute()
        symlink = _existing_symlink(requested_root)
        if symlink is not None:
            raise ValueError("private bronze root cannot traverse a symlink")
        resolved_public_roots = tuple(Path(item).absolute().resolve() for item in public_roots)
        resolved_root = requested_root.resolve()
        for public_root in resolved_public_roots:
            if (
                resolved_root == public_root
                or resolved_root.is_relative_to(public_root)
                or public_root.is_relative_to(resolved_root)
            ):
                raise ValueError("private bronze root and public data tree must be disjoint")

        requested_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(requested_root, 0o700)
        self.root = requested_root.resolve()
        self.public_roots = resolved_public_roots
        self.limits = limits
        self.codec = codec
        self._root_fd = -1
        self._root_identity: tuple[int, int] | None = None
        self._lock_identity: tuple[int, int] | None = None
        self._descriptor_writer = False
        self._thread_lock = threading.RLock()
        self._lock_fd = self._acquire_process_lock()
        self._stored_bytes, self._receipt_count = self._scan_usage()
        self._manifest: dict[str, Any] | None = None
        manifest_path = self.root / "manifest.json"
        self._sealed = manifest_path.exists()
        try:
            if self._sealed:
                loaded_manifest = self.load_sealed_manifest()
                assert loaded_manifest is not None
                self._manifest = loaded_manifest
        except Exception:
            self.close()
            raise

    @classmethod
    def create_under_authorized_parent(
        cls,
        parent_root: Path,
        generation_name: str,
        *,
        expected_parent_identity: tuple[int, int],
        limits: BronzeLimits,
        public_roots: Sequence[Path | str],
        codec: str = DEFAULT_CODEC,
    ) -> BronzeCaptureStore:
        """Create or resume one writer below an exact caller-authorized parent.

        The generation directory is created and opened relative to the retained
        parent descriptor.  Every subsequent store mutation is relative to the
        pinned generation descriptor, so replacement of either pathname cannot
        redirect capture bytes into a foreign tree.
        """

        if codec != DEFAULT_CODEC:
            raise ValueError("unsupported parser-input codec")
        if not isinstance(parent_root, Path) or not parent_root.is_absolute():
            raise ValueError("private bronze parent_root must be an absolute Path")
        parent_identity = _validate_root_identity(expected_parent_identity)
        requested_parent = Path(os.path.abspath(parent_root))
        requested_root = requested_parent / generation_name
        resolved_public_roots = tuple(Path(item).absolute().resolve() for item in public_roots)
        for public_root in resolved_public_roots:
            if (
                requested_root == public_root
                or requested_root.is_relative_to(public_root)
                or public_root.is_relative_to(requested_root)
            ):
                raise ValueError("private bronze root and public data tree must be disjoint")

        parent_descriptor = _open_authorized_directory(
            requested_parent,
            expected_identity=parent_identity,
            label="private bronze parent root",
        )
        root_descriptor = -1
        instance = cls.__new__(cls)
        try:
            root_descriptor, root_identity = _open_generation_under_authorized_parent(
                parent_descriptor,
                generation_name,
            )
            instance.root = requested_root
            instance.public_roots = resolved_public_roots
            instance.limits = limits
            instance.codec = codec
            instance._root_fd = root_descriptor
            instance._root_identity = root_identity
            instance._lock_identity = None
            instance._descriptor_writer = True
            instance._thread_lock = threading.RLock()
            instance._lock_fd = -1
            instance._manifest = None
            instance._sealed = False
            instance._lock_fd = instance._acquire_process_lock()
            instance._sealed = instance._relative_entry_exists(Path("manifest.json"))
            instance._stored_bytes, instance._receipt_count = instance._scan_usage()
            if instance._sealed:
                loaded_manifest = instance.load_sealed_manifest()
                assert loaded_manifest is not None
                instance._manifest = loaded_manifest
            return instance
        except Exception:
            instance.close()
            raise
        finally:
            os.close(parent_descriptor)

    @classmethod
    def open_existing(
        cls,
        root: Path | str,
        *,
        limits: BronzeLimits,
        public_roots: Sequence[Path | str],
        expected_root_identity: tuple[int, int],
        codec: str = DEFAULT_CODEC,
    ) -> BronzeCaptureStore:
        """Open one sealed generation through a caller-authorized root inode.

        Unlike the writer constructor, this path never creates or chmods any
        filesystem object. The existing root, lock, manifest, receipts, and
        blobs remain descriptor-relative to the authorized root inode for the
        complete retained-generation verification.
        """

        if codec != DEFAULT_CODEC:
            raise ValueError("unsupported parser-input codec")
        identity = _validate_root_identity(expected_root_identity)
        requested_root = Path(root).absolute()
        symlink = _existing_symlink(requested_root)
        if symlink is not None:
            raise ValueError("private bronze root cannot traverse a symlink")
        resolved_public_roots = tuple(Path(item).absolute().resolve() for item in public_roots)
        try:
            resolved_root = requested_root.resolve(strict=True)
        except OSError as exc:
            raise ExtractionError("existing private bronze root is unavailable") from exc
        for public_root in resolved_public_roots:
            if (
                resolved_root == public_root
                or resolved_root.is_relative_to(public_root)
                or public_root.is_relative_to(resolved_root)
            ):
                raise ValueError("private bronze root and public data tree must be disjoint")
        if not _OPEN_NOFOLLOW:
            raise RuntimeError("private bronze retained restore requires O_NOFOLLOW support")
        try:
            root_descriptor = os.open(
                requested_root,
                os.O_RDONLY | _OPEN_DIRECTORY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK,
            )
        except OSError as exc:
            raise ExtractionError("existing private bronze root is unavailable or unsafe") from exc
        instance = cls.__new__(cls)
        instance.root = requested_root
        instance.public_roots = resolved_public_roots
        instance.limits = limits
        instance.codec = codec
        instance._root_fd = root_descriptor
        instance._root_identity = identity
        instance._lock_identity = None
        instance._descriptor_writer = False
        instance._thread_lock = threading.RLock()
        instance._lock_fd = -1
        instance._manifest = None
        instance._sealed = True
        try:
            root_stat = os.fstat(root_descriptor)
            if not stat.S_ISDIR(root_stat.st_mode) or _descriptor_identity(root_stat) != identity:
                raise ExtractionError("existing private bronze root changed identity before open")
            if os.name == "posix" and (
                root_stat.st_uid != os.geteuid() or stat.S_IMODE(root_stat.st_mode) != 0o700
            ):
                raise ExtractionError("existing private bronze root must be owner-only 0700")
            instance._lock_fd = instance._acquire_process_lock()
            instance._stored_bytes, instance._receipt_count = instance._scan_usage()
            loaded_manifest = instance.load_sealed_manifest()
            if loaded_manifest is None:
                raise ExtractionError("existing private bronze generation is not sealed")
            instance._manifest = loaded_manifest
            return instance
        except Exception:
            instance.close()
            raise

    def _acquire_process_lock(self) -> int:
        if _fcntl is None:
            raise RuntimeError("private bronze capture requires advisory file locking")
        try:
            if self._root_fd >= 0:
                if self._descriptor_writer:
                    created = False
                    try:
                        descriptor = os.open(
                            ".capture.lock",
                            os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                            0o600,
                            dir_fd=self._root_fd,
                        )
                        created = True
                    except FileExistsError:
                        descriptor = _open_relative_descriptor(
                            self._root_fd,
                            Path(".capture.lock"),
                            read_write=True,
                        )
                    if created:
                        os.fchmod(descriptor, 0o600)
                        os.fsync(self._root_fd)
                else:
                    descriptor = _open_relative_descriptor(
                        self._root_fd,
                        Path(".capture.lock"),
                        read_write=True,
                    )
                self._require_existing_lock_descriptor(descriptor)
            else:
                lock_path = self.root / ".capture.lock"
                descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
                os.chmod(lock_path, 0o600)
            try:
                _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except OSError as exc:
                raise ExtractionError("private bronze generation already has a writer") from exc
            if self._root_fd >= 0:
                self._require_existing_lock_descriptor(descriptor)
                self._lock_identity = _descriptor_identity(os.fstat(descriptor))
            return descriptor
        except Exception:
            if "descriptor" in locals():
                with suppress(OSError):
                    os.close(descriptor)
            raise

    def _require_existing_lock_descriptor(self, descriptor: int) -> None:
        opened = os.fstat(descriptor)
        try:
            current = os.stat(
                ".capture.lock",
                dir_fd=self._root_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ExtractionError("existing private bronze lock is unavailable") from exc
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or _descriptor_identity(opened) != _descriptor_identity(current)
            or opened.st_nlink != 1
            or current.st_nlink != 1
        ):
            raise ExtractionError("existing private bronze lock is invalid or aliased")
        if os.name == "posix" and (
            opened.st_uid != os.geteuid()
            or current.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or stat.S_IMODE(current.st_mode) != 0o600
        ):
            raise ExtractionError("existing private bronze lock must be owner-only 0600")

    def close(self) -> None:
        descriptor = getattr(self, "_lock_fd", -1)
        if descriptor >= 0:
            self._lock_fd = -1
            if _fcntl is not None:
                _fcntl.flock(descriptor, _fcntl.LOCK_UN)
            os.close(descriptor)
        root_descriptor = getattr(self, "_root_fd", -1)
        if root_descriptor >= 0:
            self._root_fd = -1
            os.close(root_descriptor)

    def load_sealed_manifest(self) -> dict[str, Any] | None:
        """Return a freshly revalidated sealed manifest, or ``None`` if unsealed.

        The returned mapping comes from a new canonical JSON decode and shares
        no mutable containers with the store's cached seal state.  A seal is
        never served from that cache: every call revalidates the manifest bytes,
        the complete Bronze-v6 artifact inventory, and every referenced receipt
        and parser-input object against a newly derived canonical manifest.
        """

        with self._thread_lock:
            manifest_path = self.root / "manifest.json"
            if not self._sealed:
                if (
                    self._relative_entry_exists(Path("manifest.json"))
                    if self._root_fd >= 0
                    else manifest_path.exists() or manifest_path.is_symlink()
                ):
                    raise ExtractionError(
                        "private bronze manifest appeared outside the seal transition"
                    )
                return None

            loaded_manifest = self._read_manifest(manifest_path)
            try:
                observed_manifest = self.build_manifest(
                    provider_authority_sha256=loaded_manifest.get("provider_authority_sha256", ""),
                    semantic_source_sha=loaded_manifest.get("semantic_source_sha"),
                    chain_id=loaded_manifest.get("chain_id"),
                    lane_id=loaded_manifest.get("lane_id"),
                    workflow_run_id=_validate_positive_int(
                        "workflow_run_id", loaded_manifest.get("workflow_run_id")
                    ),
                    workflow_run_attempt=_validate_positive_int(
                        "workflow_run_attempt",
                        loaded_manifest.get("workflow_run_attempt"),
                    ),
                    done_call_receipt_sha256s=loaded_manifest.get("done_call_receipt_sha256s", []),
                )
            except ExtractionError:
                raise
            except (TypeError, ValueError) as exc:
                raise ExtractionError("sealed private bronze manifest contract is invalid") from exc
            if loaded_manifest != observed_manifest:
                raise ExtractionError("sealed private bronze contents disagree with the manifest")
            return loaded_manifest

    def __enter__(self) -> BronzeCaptureStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - explicit close is preferred.
        with suppress(Exception):
            self.close()

    def _scan_usage(self) -> tuple[int, int]:
        if self._root_fd >= 0:
            self._require_pinned_root()
            inventory = _inventory_relative_regular_tree(
                self._root_fd,
                excluded_paths=frozenset({".capture.lock"}),
            )
            return (
                sum(item["bytes"] for item in inventory),
                sum(
                    1
                    for item in inventory
                    if len(Path(item["path"]).parts) == 4
                    and Path(item["path"]).parts[:2]
                    in {("receipts", "attempts"), ("receipts", "calls")}
                    and Path(item["path"]).suffix == ".json"
                ),
            )
        stored_bytes = 0
        receipt_count = 0
        for directory, directories, files in os.walk(self.root, followlinks=False):
            directory_path = Path(directory)
            for name in directories:
                if (directory_path / name).is_symlink():
                    raise ExtractionError("private bronze generation contains a symlink")
            for name in files:
                path = directory_path / name
                if path.is_symlink():
                    raise ExtractionError("private bronze generation contains a symlink")
                if path == self.root / ".capture.lock":
                    continue
                stored_bytes += path.stat().st_size
                if path.parent.parent.name in {"attempts", "calls"} and path.suffix == ".json":
                    receipt_count += 1
        return stored_bytes, receipt_count

    def _ensure_open(self) -> None:
        if self._sealed:
            raise ExtractionError("private bronze generation is sealed")

    def _relative_entry_exists(self, relative: Path) -> bool:
        self._require_pinned_root()
        parts = _validate_relative_descriptor_path(relative)
        if len(parts) != 1:
            raise ExtractionError("private bronze root entry path is invalid")
        try:
            os.stat(parts[0], dir_fd=self._root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ExtractionError("private bronze root entry cannot be inspected") from exc
        return True

    def _open_private_parent_descriptor(self, relative: Path) -> tuple[int, str]:
        """Retain the exact parent inode for one descriptor-relative publication."""

        self._require_pinned_root()
        parts = _validate_relative_descriptor_path(relative)
        current = os.dup(self._root_fd)
        try:
            for part in parts[:-1]:
                created_identity: tuple[int, int] | None = None
                try:
                    child = os.open(
                        part,
                        os.O_RDONLY
                        | _OPEN_DIRECTORY
                        | _OPEN_NOFOLLOW
                        | _OPEN_CLOEXEC
                        | _OPEN_NONBLOCK,
                        dir_fd=current,
                    )
                except FileNotFoundError:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                    else:
                        created = os.stat(part, dir_fd=current, follow_symlinks=False)
                        created_identity = _descriptor_identity(created)
                    child = os.open(
                        part,
                        os.O_RDONLY
                        | _OPEN_DIRECTORY
                        | _OPEN_NOFOLLOW
                        | _OPEN_CLOEXEC
                        | _OPEN_NONBLOCK,
                        dir_fd=current,
                    )
                    if created_identity is not None:
                        os.fchmod(child, 0o700)
                        os.fsync(current)
                opened = os.fstat(child)
                named = os.stat(part, dir_fd=current, follow_symlinks=False)
                if (
                    not stat.S_ISDIR(opened.st_mode)
                    or not stat.S_ISDIR(named.st_mode)
                    or _descriptor_identity(opened) != _descriptor_identity(named)
                    or (
                        created_identity is not None
                        and _descriptor_identity(opened) != created_identity
                    )
                    or opened.st_uid != os.geteuid()
                    or stat.S_IMODE(opened.st_mode) != 0o700
                ):
                    os.close(child)
                    raise ExtractionError("private bronze publication parent is invalid")
                os.close(current)
                current = child
            return current, parts[-1]
        except (OSError, ValueError) as exc:
            os.close(current)
            if isinstance(exc, ExtractionError):
                raise
            raise ExtractionError("private bronze publication parent is unsafe") from exc

    @staticmethod
    def _read_published_leaf(parent_descriptor: int, leaf: str) -> bytes | None:
        descriptor = -1
        try:
            try:
                descriptor = os.open(
                    leaf,
                    os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK,
                    dir_fd=parent_descriptor,
                )
            except FileNotFoundError:
                return None
            before = os.fstat(descriptor)
            named = os.stat(leaf, dir_fd=parent_descriptor, follow_symlinks=False)
            if (
                not stat.S_ISREG(before.st_mode)
                or not stat.S_ISREG(named.st_mode)
                or _descriptor_identity(before) != _descriptor_identity(named)
                or before.st_nlink != 1
                or named.st_nlink != 1
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600
            ):
                raise ExtractionError("immutable parser-input path is invalid or aliased")
            payload = _read_regular_descriptor(descriptor, display_path=leaf)
            named_after = os.stat(leaf, dir_fd=parent_descriptor, follow_symlinks=False)
            after = os.fstat(descriptor)
            if _descriptor_entry_identity(before) != _descriptor_entry_identity(
                after
            ) or _descriptor_identity(after) != _descriptor_identity(named_after):
                raise ExtractionError("immutable parser-input path changed while reading")
            return payload
        except OSError as exc:
            raise ExtractionError("immutable parser-input path cannot be read safely") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _publish_pinned(self, relative: Path, payload: bytes, *, receipt: bool) -> bool:
        parent_descriptor, leaf = self._open_private_parent_descriptor(relative)
        temp_name: str | None = None
        temp_descriptor = -1
        try:
            existing = self._read_published_leaf(parent_descriptor, leaf)
            if existing is not None:
                if existing != payload:
                    raise ExtractionError("immutable parser-input path disagrees with content")
                return False
            self._ensure_capacity(len(payload), receipt=receipt)
            for _ in range(128):
                candidate = f".{leaf}.{secrets.token_hex(16)}.tmp"
                try:
                    temp_descriptor = os.open(
                        candidate,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                        0o600,
                        dir_fd=parent_descriptor,
                    )
                    temp_name = candidate
                    break
                except FileExistsError:
                    continue
            if temp_descriptor < 0 or temp_name is None:
                raise ExtractionError("private bronze temporary file cannot be reserved")
            os.fchmod(temp_descriptor, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(temp_descriptor, view)
                if written <= 0:
                    raise OSError("private bronze write made no progress")
                view = view[written:]
            os.fsync(temp_descriptor)
            temp_stat = os.fstat(temp_descriptor)
            if (
                not stat.S_ISREG(temp_stat.st_mode)
                or temp_stat.st_uid != os.geteuid()
                or stat.S_IMODE(temp_stat.st_mode) != 0o600
                or temp_stat.st_nlink != 1
                or temp_stat.st_size != len(payload)
            ):
                raise ExtractionError("private bronze temporary file is invalid")
            published = False
            try:
                os.link(
                    temp_name,
                    leaf,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                published = True
            except FileExistsError:
                winner = self._read_published_leaf(parent_descriptor, leaf)
                if winner != payload:
                    raise ExtractionError(
                        "immutable parser-input path disagrees with content"
                    ) from None
            os.unlink(temp_name, dir_fd=parent_descriptor)
            temp_name = None
            os.fsync(parent_descriptor)
            observed = self._read_published_leaf(parent_descriptor, leaf)
            if observed != payload:
                raise ExtractionError("immutable parser-input publication differs")
            return published
        except OSError as exc:
            raise ExtractionError("immutable parser-input publication failed") from exc
        finally:
            if temp_descriptor >= 0:
                os.close(temp_descriptor)
            if temp_name is not None:
                with suppress(OSError):
                    os.unlink(temp_name, dir_fd=parent_descriptor)
            os.close(parent_descriptor)

    def _ensure_private_parent(self, path: Path) -> None:
        if self._root_fd >= 0:
            try:
                relative = path.relative_to(self.root)
            except ValueError as exc:
                raise ExtractionError("private bronze path escaped its generation root") from exc
            descriptor, _leaf = self._open_private_parent_descriptor(relative)
            os.close(descriptor)
            return
        try:
            relative_parent = path.parent.relative_to(self.root)
        except ValueError as exc:
            raise ExtractionError("private bronze path escaped its generation root") from exc
        current = self.root
        for part in relative_parent.parts:
            current /= part
            if current.is_symlink():
                raise ExtractionError("private bronze path traverses a symlink")
            if not current.exists():
                parent = current.parent
                current.mkdir(mode=0o700)
                os.chmod(current, 0o700)
                _fsync_directory(parent)
            elif not current.is_dir():
                raise ExtractionError("private bronze path has a non-directory parent")

    def _ensure_capacity(self, additional_stored_bytes: int, *, receipt: bool = False) -> None:
        if additional_stored_bytes < 0:
            raise ValueError("additional_stored_bytes cannot be negative")
        if receipt and self._receipt_count + 1 > self.limits.max_receipt_count:
            raise ParserInputCapacityError("private parser-input receipt-count limit exceeded")
        free_bytes = (
            os.fstatvfs(self._root_fd).f_bavail * os.fstatvfs(self._root_fd).f_frsize
            if self._root_fd >= 0
            else shutil.disk_usage(self.root).free
        )
        if free_bytes - additional_stored_bytes < self.limits.minimum_free_bytes:
            raise ParserInputCapacityError("private parser-input free-space reserve exceeded")
        if self._stored_bytes + additional_stored_bytes > self.limits.max_generation_stored_bytes:
            raise ParserInputCapacityError("private parser-input generation limit exceeded")

    def admit_capture(
        self,
        *,
        estimated_checkpoint_bytes: int,
        monotonic_now_seconds: float,
        monotonic_deadline_seconds: float,
    ) -> None:
        """Validate caller-measured checkpoint capacity and finalization headroom.

        This is deliberately opt-in until production has evidence-backed values.
        No default checkpoint or deadline limit is inferred by the store.
        """

        if (
            isinstance(estimated_checkpoint_bytes, bool)
            or not isinstance(estimated_checkpoint_bytes, int)
            or estimated_checkpoint_bytes <= 0
        ):
            raise ValueError("estimated_checkpoint_bytes must be a positive integer")
        for name, value in (
            ("monotonic_now_seconds", monotonic_now_seconds),
            ("monotonic_deadline_seconds", monotonic_deadline_seconds),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive and finite")

        with self._thread_lock:
            self._ensure_open()
            checkpoint_limit = self.limits.max_checkpoint_bytes
            deadline_headroom = self.limits.minimum_deadline_headroom_seconds
            if checkpoint_limit is None or deadline_headroom is None:
                raise ParserInputCapacityError(
                    "private parser-input admission limits are not configured"
                )
            if estimated_checkpoint_bytes > checkpoint_limit:
                raise ParserInputCapacityError("private checkpoint byte limit exceeded")
            remaining = monotonic_deadline_seconds - monotonic_now_seconds
            if remaining < deadline_headroom:
                raise ParserInputCapacityError("private capture deadline headroom is insufficient")
            free_bytes = (
                os.fstatvfs(self._root_fd).f_bavail * os.fstatvfs(self._root_fd).f_frsize
                if self._root_fd >= 0
                else shutil.disk_usage(self.root).free
            )
            if free_bytes - estimated_checkpoint_bytes < self.limits.minimum_free_bytes:
                raise ParserInputCapacityError("private checkpoint free-space reserve exceeded")

    def _publish(self, path: Path, payload: bytes, *, receipt: bool = False) -> bool:
        self._ensure_open()
        if self._root_fd >= 0:
            try:
                relative = path.relative_to(self.root)
            except ValueError as exc:
                raise ExtractionError("private bronze path escaped its generation root") from exc
            published = self._publish_pinned(relative, payload, receipt=receipt)
            if published:
                self._stored_bytes += len(payload)
                if receipt:
                    self._receipt_count += 1
            return published
        self._ensure_private_parent(path)
        if path.is_symlink():
            raise ExtractionError("immutable parser-input path is a symlink")
        if path.exists():
            if not path.is_file() or path.read_bytes() != payload:
                raise ExtractionError("immutable parser-input path disagrees with content")
            return False
        self._ensure_capacity(len(payload), receipt=receipt)
        published = _atomic_write_new(path, payload)
        if published:
            self._stored_bytes += len(payload)
            if receipt:
                self._receipt_count += 1
        return published

    def _store_raw(self, raw: bytes, *, representation: str) -> CapturedParserInput:
        if len(raw) > self.limits.max_response_bytes:
            raise ParserInputCapacityError("parser input exceeds the per-response limit")
        response_sha256 = _sha256(raw)
        object_sha256 = _sha256(representation.encode("ascii") + b"\0" + raw)
        relative_path = _blob_relative_path(object_sha256)
        path = self.root / relative_path
        stored = gzip.compress(raw, compresslevel=6, mtime=0)
        with self._thread_lock:
            self._ensure_open()
            if self._root_fd >= 0:
                self._publish(path, stored)
                observed = self._read_pinned_regular(path)
                captured = CapturedParserInput(
                    representation=representation,
                    response_sha256=response_sha256,
                    object_sha256=object_sha256,
                    uncompressed_bytes=len(raw),
                    stored_sha256=_sha256(observed),
                    stored_bytes=len(observed),
                    codec=self.codec,
                    relative_path=relative_path.as_posix(),
                )
                if self._verify_captured(captured) != raw:
                    raise ExtractionError("parser-input object failed post-write verification")
                return captured
            self._ensure_private_parent(path)
            if path.exists():
                captured = CapturedParserInput(
                    representation=representation,
                    response_sha256=response_sha256,
                    object_sha256=object_sha256,
                    uncompressed_bytes=len(raw),
                    stored_sha256=_sha256(path.read_bytes()),
                    stored_bytes=path.stat().st_size,
                    codec=self.codec,
                    relative_path=relative_path.as_posix(),
                )
                if self._verify_captured(captured) != raw:
                    raise ExtractionError("existing parser-input object failed verification")
                return captured
            self._publish(path, stored)
            captured = CapturedParserInput(
                representation=representation,
                response_sha256=response_sha256,
                object_sha256=object_sha256,
                uncompressed_bytes=len(raw),
                stored_sha256=_sha256(stored),
                stored_bytes=len(stored),
                codec=self.codec,
                relative_path=relative_path.as_posix(),
            )
            if self._verify_captured(captured) != raw:
                raise ExtractionError("parser-input object failed post-write verification")
            return captured

    def store_parser_input(
        self,
        payload: str,
        *,
        representation: str,
    ) -> CapturedParserInput:
        if representation != PARSER_INPUT_REPRESENTATION:
            raise ValueError("HTTP parser input requires the decoded-response representation")
        if not isinstance(payload, str):
            raise TypeError("HTTP parser input must be the provider's decoded string")
        try:
            raw = payload.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("HTTP parser input is not valid UTF-8 text") from exc
        return self._store_raw(raw, representation=representation)

    def store_static_records(self, records: object) -> CapturedParserInput:
        """Canonicalize a static provider snapshot before storing it."""

        try:
            raw = _canonical_json_bytes(records)
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise ValueError("static provider records are not canonical JSON values") from exc
        return self._store_raw(raw, representation=STATIC_INPUT_REPRESENTATION)

    def _bounded_decompress(
        self,
        path: Path,
        *,
        expected_stored_bytes: int,
        stored: bytes | None = None,
    ) -> bytes:
        if stored is not None:
            stored_bytes = len(stored)
        elif self._root_fd >= 0:
            stored = self._read_pinned_regular(path)
            stored_bytes = len(stored)
        else:
            stored_bytes = -1
        if stored is not None:
            if stored_bytes != expected_stored_bytes:
                raise ExtractionError("stored parser-input length mismatch")
            if stored_bytes > self.limits.max_generation_stored_bytes:
                raise ParserInputCapacityError("stored parser input exceeds the generation limit")
            source: Any = io.BytesIO(stored)
        else:
            if path.is_symlink() or not path.is_file():
                raise ExtractionError("parser-input object is unavailable")
            if _existing_symlink(path) is not None:
                raise ExtractionError("parser-input object path traverses a symlink")
            stored_bytes = path.stat().st_size
            if stored_bytes != expected_stored_bytes:
                raise ExtractionError("stored parser-input length mismatch")
            if stored_bytes > self.limits.max_generation_stored_bytes:
                raise ParserInputCapacityError("stored parser input exceeds the generation limit")
            source = path
        output = bytearray()
        try:
            with gzip.open(source, "rb") as handle:
                while True:
                    chunk = handle.read(min(64 * 1024, self.limits.max_response_bytes + 1))
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > self.limits.max_response_bytes:
                        raise ParserInputCapacityError(
                            "decoded parser input exceeds the per-response limit"
                        )
        except (EOFError, OSError) as exc:
            raise ExtractionError("stored parser-input compression is invalid") from exc
        return bytes(output)

    def _verify_captured(self, captured: CapturedParserInput) -> bytes:
        path = self.root / _blob_relative_path(captured.object_sha256)
        if path.relative_to(self.root).as_posix() != captured.relative_path:
            raise ExtractionError("parser-input receipt does not use its canonical object path")
        if self._root_fd >= 0:
            stored = self._read_pinned_regular(path)
        else:
            stored = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
        if len(stored) != captured.stored_bytes or _sha256(stored) != captured.stored_sha256:
            raise ExtractionError("stored parser-input digest mismatch")
        decoded = self._bounded_decompress(
            path,
            expected_stored_bytes=captured.stored_bytes,
            stored=stored,
        )
        if len(decoded) != captured.uncompressed_bytes:
            raise ExtractionError("decoded parser-input length mismatch")
        if _sha256(decoded) != captured.response_sha256:
            raise ExtractionError("decoded parser-input digest mismatch")
        identity = captured.representation.encode("ascii") + b"\0" + decoded
        if _sha256(identity) != captured.object_sha256:
            raise ExtractionError("parser-input object identity mismatch")
        return decoded

    def _write_receipt(self, kind: str, payload: dict[str, Any]) -> str:
        encoded = _canonical_json_bytes(payload)
        if len(encoded) > self.limits.max_receipt_bytes:
            raise ParserInputCapacityError("parser-input receipt exceeds the receipt limit")
        digest = _sha256(encoded)
        path = self.root / _receipt_relative_path(kind, digest)
        with self._thread_lock:
            self._publish(path, encoded, receipt=True)
        return digest

    @staticmethod
    def _context_payload(context: ParserInputContext) -> dict[str, Any]:
        return {key: value for key, value in asdict(context).items() if value is not None}

    @staticmethod
    def _validate_result_sets(
        result_sets: Sequence[ResultSetReceipt],
    ) -> tuple[ResultSetReceipt, ...]:
        values = tuple(result_sets)
        # Strict-known stats packets, live projections, and static snapshots all
        # carry canonical indexes.  A successful stats response that drifts from
        # its pinned tabular contract instead uses the existing nullable
        # canonical-index field as the lossless-fallback discriminator.  In that
        # mode provider names are observations rather than keys, so duplicate
        # names are valid and provider occurrence is retained by provider_index.
        fallback_stats = bool(values) and any(
            item.canonical_index is None
            and item.json_path is None
            and item.container_kind == "nba_api_result_set"
            for item in values
        )
        if not fallback_stats and len({item.name for item in values}) != len(values):
            raise ValueError("response receipt has duplicate result-set names")
        provider_indexes = [
            item.provider_index for item in values if item.provider_index is not None
        ]
        if len(set(provider_indexes)) != len(provider_indexes):
            raise ValueError("response receipt has duplicate provider indexes")
        if provider_indexes and (
            (not fallback_stats and len(provider_indexes) != len(values))
            or sorted(provider_indexes) != list(range(len(provider_indexes)))
        ):
            raise ValueError("response receipt provider indexes are not a complete permutation")
        canonical = [item.canonical_index for item in values if item.canonical_index is not None]
        if len(set(canonical)) != len(canonical):
            raise ValueError("response receipt has duplicate canonical indexes")
        if canonical and (
            fallback_stats or len(canonical) != len(values) or canonical != list(range(len(values)))
        ):
            raise ValueError("response receipt canonical indexes do not match receipt order")
        if fallback_stats:
            present = [item for item in values if item.provider_index is not None]
            missing = [item for item in values if item.provider_index is None]
            if values != tuple(present + missing):
                raise ValueError(
                    "fallback result-set receipts must order provider occurrences "
                    "before missing sets"
                )
            if [item.provider_index for item in present] != list(range(len(present))):
                raise ValueError(
                    "fallback result-set receipts do not preserve provider occurrence order"
                )
        return values

    def record_response_attempt(
        self,
        *,
        context: ParserInputContext,
        transport_kind: TransportKind,
        source_family: str,
        endpoint_id: str,
        endpoint_slug: str,
        parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        contract_sha256: str,
        status_code: int | None,
        captured: CapturedParserInput,
        outcome: Outcome,
        failure_class: str | None,
        root_exception_class: str | None,
        result_sets: Sequence[ResultSetReceipt],
        effective_status_code: int | None = None,
    ) -> str:
        with self._thread_lock:
            self._ensure_open()
            self._verify_captured(captured)
            validated_result_sets = self._validate_result_sets(result_sets)
            _validate_failure_metadata(
                transport_kind=transport_kind,
                outcome=outcome,
                failure_class=failure_class,
                root_exception_class=root_exception_class,
                status_code=status_code,
                effective_status_code=effective_status_code,
                parser_input_representation=captured.representation,
            )
            _validate_outcome_result_sets(outcome, validated_result_sets)
            _validate_transport_source(transport_kind, source_family)
            _validate_transport_endpoint(transport_kind, endpoint_id, endpoint_slug)
            _validate_transport_result_sets(
                transport_kind,
                source_family,
                endpoint_slug,
                outcome,
                validated_result_sets,
            )
            payload = {
                "schema_version": BRONZE_SCHEMA_VERSION,
                "kind": "response_attempt",
                "context": self._context_payload(context),
                "transport_kind": transport_kind,
                "source_family": source_family,
                "endpoint_id": _validate_token("endpoint_id", endpoint_id),
                "endpoint_slug": _validate_token("endpoint_slug", endpoint_slug),
                "parameters_sha256": canonical_parameters_sha256(parameters),
                "provider_authority_sha256": _validate_sha256(
                    "provider_authority_sha256", provider_authority_sha256
                ),
                "endpoint_contract_sha256": _validate_sha256("contract_sha256", contract_sha256),
                "status_code": status_code,
                "effective_status_code": effective_status_code,
                "parser_input": asdict(captured),
                "outcome": outcome,
                "failure_class": failure_class,
                "root_exception_class": root_exception_class,
                "result_sets": [asdict(result_set) for result_set in validated_result_sets],
                "result_sets_sha256": result_sets_digest(validated_result_sets),
                "codec_contract_sha256": CODEC_CONTRACT_SHA256,
            }
            return self._write_receipt("attempts", payload)

    def record_static_snapshot_attempt(
        self,
        *,
        context: ParserInputContext,
        endpoint_id: str,
        endpoint_slug: str,
        provider_authority_sha256: str,
        contract_sha256: str,
        captured: CapturedParserInput,
        result_set: ResultSetReceipt,
    ) -> str:
        """Record one successful local provider snapshot without fabricating HTTP status."""

        outcome: Outcome = "success_nonempty" if result_set.row_count else "success_empty"
        return self.record_response_attempt(
            context=context,
            transport_kind="static_provider_snapshot",
            source_family="static",
            endpoint_id=endpoint_id,
            endpoint_slug=endpoint_slug,
            parameters={},
            provider_authority_sha256=provider_authority_sha256,
            contract_sha256=contract_sha256,
            status_code=None,
            captured=captured,
            outcome=outcome,
            failure_class=None,
            root_exception_class=None,
            result_sets=(result_set,),
        )

    def record_no_response_attempt(
        self,
        *,
        context: ParserInputContext,
        transport_kind: TransportKind,
        source_family: str,
        endpoint_id: str,
        endpoint_slug: str,
        parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        contract_sha256: str,
        outcome: Outcome,
        failure_class: str,
        root_exception_class: str,
    ) -> str:
        with self._thread_lock:
            self._ensure_open()
            _validate_failure_metadata(
                transport_kind=transport_kind,
                outcome=outcome,
                failure_class=failure_class,
                root_exception_class=root_exception_class,
                status_code=None,
                effective_status_code=None,
                parser_input_representation=None,
            )
            _validate_transport_source(transport_kind, source_family)
            _validate_transport_endpoint(transport_kind, endpoint_id, endpoint_slug)
            payload = {
                "schema_version": BRONZE_SCHEMA_VERSION,
                "kind": "response_attempt",
                "context": self._context_payload(context),
                "transport_kind": transport_kind,
                "source_family": source_family,
                "endpoint_id": _validate_token("endpoint_id", endpoint_id),
                "endpoint_slug": _validate_token("endpoint_slug", endpoint_slug),
                "parameters_sha256": canonical_parameters_sha256(parameters),
                "provider_authority_sha256": _validate_sha256(
                    "provider_authority_sha256", provider_authority_sha256
                ),
                "endpoint_contract_sha256": _validate_sha256("contract_sha256", contract_sha256),
                "status_code": None,
                "effective_status_code": None,
                "parser_input": None,
                "outcome": outcome,
                "failure_class": failure_class,
                "root_exception_class": root_exception_class,
                "result_sets": [],
                "result_sets_sha256": result_sets_digest(()),
                "codec_contract_sha256": CODEC_CONTRACT_SHA256,
            }
            return self._write_receipt("attempts", payload)

    @staticmethod
    def _contexts_match(call_context: ParserInputContext, attempt: ParserInputContext) -> bool:
        return all(
            getattr(call_context, field_name) == getattr(attempt, field_name)
            for field_name in (
                "attempt_id",
                "workflow_run_id",
                "workflow_run_attempt",
                "chain_id",
                "lane_id",
                "semantic_source_sha",
            )
        )

    @staticmethod
    def _validate_attempt_order(attempts: Sequence[Mapping[str, Any]]) -> None:
        expected_retry = 0
        expected_request = 0
        for attempt in attempts:
            context = ParserInputContext(**attempt["context"])
            actual = (context.retry_ordinal, context.request_ordinal)
            expected = (expected_retry, expected_request)
            if actual != expected:
                if expected_request > 0 and actual == (expected_retry + 1, 0):
                    expected_retry += 1
                    expected_request = 0
                else:
                    raise ExtractionError(
                        "logical-call response attempts are not contiguous and ordered"
                    )
            expected_request += 1

    @staticmethod
    def _response_contracts_payload(
        attempts: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, str]]:
        return [
            {
                "source_family": str(attempt["source_family"]),
                "transport_kind": str(attempt["transport_kind"]),
                "endpoint_id": str(attempt["endpoint_id"]),
                "endpoint_slug": str(attempt["endpoint_slug"]),
                "parameters_sha256": str(attempt["parameters_sha256"]),
                "endpoint_contract_sha256": str(attempt["endpoint_contract_sha256"]),
            }
            for attempt in attempts
        ]

    def record_logical_call(
        self,
        *,
        context: ParserInputContext,
        logical_endpoint_id: str,
        logical_parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        response_receipt_sha256s: Sequence[str],
        successful_response_ordinals: Sequence[int],
        result_route_ids: Sequence[str],
    ) -> str:
        with self._thread_lock:
            self._ensure_open()
            if not response_receipt_sha256s:
                raise ValueError("logical call must reference at least one response attempt")
            receipts = tuple(
                _validate_sha256("response_receipt_sha256", digest)
                for digest in response_receipt_sha256s
            )
            if len(set(receipts)) != len(receipts):
                raise ValueError("logical call cannot contain duplicate response receipts")
            ordinals = tuple(successful_response_ordinals)
            if (
                not ordinals
                or tuple(sorted(set(ordinals))) != ordinals
                or any(
                    isinstance(ordinal, bool)
                    or not isinstance(ordinal, int)
                    or ordinal < 0
                    or ordinal >= len(receipts)
                    for ordinal in ordinals
                )
            ):
                raise ValueError("successful response ordinals must be unique ordered indexes")
            routes = tuple(
                sorted(
                    _validate_token("result_route_id", route_id) for route_id in result_route_ids
                )
            )
            if not routes or len(set(routes)) != len(routes):
                raise ValueError("logical call requires unique nonempty result-route identities")
            if context.retry_ordinal != 0 or context.request_ordinal != 0:
                raise ValueError("logical-call context must begin at retry and request zero")
            endpoint = _validate_token("logical_endpoint_id", logical_endpoint_id)
            parameter_digest = canonical_parameters_sha256(logical_parameters)
            provider_digest = _validate_sha256(
                "provider_authority_sha256", provider_authority_sha256
            )
            attempt_payloads = [self._load_attempt(digest) for digest in receipts]
            self._validate_attempt_order(attempt_payloads)
            source_family = attempt_payloads[0]["source_family"]
            for attempt in attempt_payloads:
                attempt_context = ParserInputContext(**attempt["context"])
                if not self._contexts_match(context, attempt_context):
                    raise ExtractionError("logical call crosses parser-input attempt scopes")
                if (
                    attempt["provider_authority_sha256"] != provider_digest
                    or attempt["source_family"] != source_family
                ):
                    raise ExtractionError(
                        "logical call crosses provider authority or source family"
                    )
            actual_successes = tuple(
                index
                for index, attempt in enumerate(attempt_payloads)
                if attempt["outcome"] in _SUCCESS_OUTCOMES
            )
            if actual_successes != ordinals:
                raise ExtractionError("logical call success ordinals disagree with attempts")
            response_contracts = self._response_contracts_payload(attempt_payloads)
            payload = {
                "schema_version": BRONZE_SCHEMA_VERSION,
                "kind": "logical_call",
                "context": self._context_payload(context),
                "logical_endpoint_id": endpoint,
                "logical_parameters_sha256": parameter_digest,
                "source_family": source_family,
                "provider_authority_sha256": provider_digest,
                "response_receipt_sha256s": list(receipts),
                "response_contracts_sha256": _sha256(_canonical_json_bytes(response_contracts)),
                "successful_response_ordinals": list(ordinals),
                "result_route_ids": list(routes),
            }
            return self._write_receipt("calls", payload)

    def _read_json(self, path: Path, *, expected_digest: str | None = None) -> dict[str, Any]:
        if self._root_fd >= 0:
            raw = self._read_pinned_regular(path)
            size = len(raw)
        else:
            if path.is_symlink() or not path.is_file() or _existing_symlink(path) is not None:
                raise ExtractionError("parser-input receipt path is unavailable or unsafe")
            size = path.stat().st_size
            raw = path.read_bytes()
        if size > self.limits.max_receipt_bytes:
            raise ParserInputCapacityError("parser-input receipt exceeds the receipt limit")
        if expected_digest is not None and _sha256(raw) != expected_digest:
            raise ExtractionError("parser-input receipt digest mismatch")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExtractionError("parser-input receipt is not canonical JSON") from exc
        if not isinstance(value, dict):
            raise ExtractionError("parser-input receipt root must be an object")
        if _canonical_json_bytes(value) != raw:
            raise ExtractionError("parser-input receipt is not canonical JSON")
        return cast("dict[str, Any]", value)

    def _read_pinned_regular(self, path: Path) -> bytes:
        self._require_pinned_root()
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise ExtractionError("private bronze path escaped its pinned root") from exc
        return _read_relative_regular(self._root_fd, relative)

    def _require_pinned_root(self) -> None:
        if self._root_fd < 0 or self._root_identity is None:
            raise ExtractionError("private bronze root descriptor is unavailable")
        observed = os.fstat(self._root_fd)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or _descriptor_identity(observed) != self._root_identity
        ):
            raise ExtractionError("private bronze pinned root changed identity")
        if self._lock_fd < 0 or self._lock_identity is None:
            raise ExtractionError("private bronze retained lock is unavailable")
        self._require_existing_lock_descriptor(self._lock_fd)
        if _descriptor_identity(os.fstat(self._lock_fd)) != self._lock_identity:
            raise ExtractionError("private bronze retained lock changed identity")

    @staticmethod
    def _expect_exact_keys(payload: Mapping[str, Any], expected: set[str], kind: str) -> None:
        if set(payload) != expected:
            raise ExtractionError(f"{kind} receipt fields do not match the schema")

    def _load_attempt(self, digest: str) -> dict[str, Any]:
        _validate_sha256("attempt_receipt_sha256", digest)
        path = self.root / _receipt_relative_path("attempts", digest)
        payload = self._read_json(path, expected_digest=digest)
        self._expect_exact_keys(
            payload,
            {
                "schema_version",
                "kind",
                "context",
                "transport_kind",
                "source_family",
                "endpoint_id",
                "endpoint_slug",
                "parameters_sha256",
                "provider_authority_sha256",
                "endpoint_contract_sha256",
                "status_code",
                "effective_status_code",
                "parser_input",
                "outcome",
                "failure_class",
                "root_exception_class",
                "result_sets",
                "result_sets_sha256",
                "codec_contract_sha256",
            },
            "attempt",
        )
        if (
            payload["schema_version"] != BRONZE_SCHEMA_VERSION
            or payload["kind"] != "response_attempt"
        ):
            raise ExtractionError("attempt receipt schema identity is invalid")
        if payload["codec_contract_sha256"] != CODEC_CONTRACT_SHA256:
            raise ExtractionError("attempt receipt codec contract is invalid")
        if not isinstance(payload["context"], dict):
            raise ExtractionError("attempt receipt context is invalid")
        ParserInputContext(**payload["context"])
        try:
            _validate_transport_source(payload["transport_kind"], payload["source_family"])
            _validate_transport_endpoint(
                payload["transport_kind"],
                payload["endpoint_id"],
                payload["endpoint_slug"],
            )
        except ValueError as exc:
            raise ExtractionError("attempt receipt transport contract is invalid") from exc
        _validate_token("endpoint_id", payload["endpoint_id"])
        _validate_token("endpoint_slug", payload["endpoint_slug"])
        _validate_sha256("parameters_sha256", payload["parameters_sha256"])
        _validate_sha256("provider_authority_sha256", payload["provider_authority_sha256"])
        _validate_sha256("endpoint_contract_sha256", payload["endpoint_contract_sha256"])
        parser_input = payload["parser_input"]
        captured: CapturedParserInput | None = None
        if parser_input is not None:
            if not isinstance(parser_input, dict):
                raise ExtractionError("attempt parser-input contract is invalid")
            try:
                captured = CapturedParserInput(**parser_input)
            except (TypeError, ValueError) as exc:
                raise ExtractionError("attempt parser-input contract is invalid") from exc
            self._verify_captured(captured)
        raw_result_sets = payload["result_sets"]
        if not isinstance(raw_result_sets, list):
            raise ExtractionError("attempt result-set inventory is invalid")
        try:
            result_sets = self._validate_result_sets(
                tuple(ResultSetReceipt(**item) for item in raw_result_sets)
            )
        except (TypeError, ValueError) as exc:
            raise ExtractionError("attempt result-set inventory is invalid") from exc
        if payload["result_sets_sha256"] != result_sets_digest(result_sets):
            raise ExtractionError("attempt result-set digest is invalid")
        try:
            _validate_failure_metadata(
                transport_kind=payload["transport_kind"],
                outcome=payload["outcome"],
                failure_class=payload["failure_class"],
                root_exception_class=payload["root_exception_class"],
                status_code=payload["status_code"],
                effective_status_code=payload["effective_status_code"],
                parser_input_representation=(captured.representation if captured else None),
            )
            _validate_outcome_result_sets(payload["outcome"], result_sets)
            _validate_transport_result_sets(
                payload["transport_kind"],
                payload["source_family"],
                payload["endpoint_slug"],
                payload["outcome"],
                result_sets,
            )
        except ValueError as exc:
            raise ExtractionError("attempt outcome contract is invalid") from exc
        return payload

    def _load_call(self, digest: str) -> dict[str, Any]:
        _validate_sha256("call_receipt_sha256", digest)
        path = self.root / _receipt_relative_path("calls", digest)
        payload = self._read_json(path, expected_digest=digest)
        self._expect_exact_keys(
            payload,
            {
                "schema_version",
                "kind",
                "context",
                "logical_endpoint_id",
                "logical_parameters_sha256",
                "source_family",
                "provider_authority_sha256",
                "response_receipt_sha256s",
                "response_contracts_sha256",
                "successful_response_ordinals",
                "result_route_ids",
            },
            "logical-call",
        )
        if payload["schema_version"] != BRONZE_SCHEMA_VERSION or payload["kind"] != "logical_call":
            raise ExtractionError("logical-call receipt schema identity is invalid")
        if not isinstance(payload["context"], dict):
            raise ExtractionError("logical-call context is invalid")
        call_context = ParserInputContext(**payload["context"])
        if call_context.retry_ordinal != 0 or call_context.request_ordinal != 0:
            raise ExtractionError("logical-call context does not begin at zero")
        _validate_token("logical_endpoint_id", payload["logical_endpoint_id"])
        _validate_sha256("logical_parameters_sha256", payload["logical_parameters_sha256"])
        if payload["source_family"] not in _SOURCE_FAMILIES:
            raise ExtractionError("logical-call source family is invalid")
        _validate_sha256("provider_authority_sha256", payload["provider_authority_sha256"])
        _validate_sha256("response_contracts_sha256", payload["response_contracts_sha256"])
        receipts = payload["response_receipt_sha256s"]
        ordinals = payload["successful_response_ordinals"]
        routes = payload["result_route_ids"]
        if not isinstance(receipts, list) or not receipts or len(set(receipts)) != len(receipts):
            raise ExtractionError("logical-call response receipts are invalid")
        if not isinstance(ordinals, list) or not ordinals or sorted(set(ordinals)) != ordinals:
            raise ExtractionError("logical-call success ordinals are invalid")
        if not isinstance(routes, list) or not routes or routes != sorted(set(routes)):
            raise ExtractionError("logical-call route inventory is invalid")
        for route in routes:
            _validate_token("result_route_id", route)
        attempts = [self._load_attempt(item) for item in receipts]
        self._validate_attempt_order(attempts)
        for attempt in attempts:
            attempt_context = ParserInputContext(**attempt["context"])
            if not self._contexts_match(call_context, attempt_context):
                raise ExtractionError("logical-call attempt scope is invalid")
            if (
                attempt["provider_authority_sha256"] != payload["provider_authority_sha256"]
                or attempt["source_family"] != payload["source_family"]
            ):
                raise ExtractionError("logical-call attempt contract is invalid")
        if payload["response_contracts_sha256"] != _sha256(
            _canonical_json_bytes(self._response_contracts_payload(attempts))
        ):
            raise ExtractionError("logical-call response-contract digest is invalid")
        actual = [
            index
            for index, attempt in enumerate(attempts)
            if attempt["outcome"] in _SUCCESS_OUTCOMES
        ]
        if actual != ordinals:
            raise ExtractionError("logical-call success inventory is invalid")
        return payload

    def load_completed_logical_call_binding(
        self,
        receipt_sha256: str,
        *,
        expected_endpoint_name: str,
        expected_provider_authority_sha256: str,
        expected_logical_parameters_sha256: str,
        expected_result_route_ids: Sequence[str],
    ) -> LogicalCallReceiptBinding:
        """Load one canonical successful logical-call receipt under exact authority."""

        with self._thread_lock:
            try:
                if isinstance(expected_result_route_ids, str):
                    raise ValueError("expected_result_route_ids must be a sequence of route IDs")
                expected = LogicalCallReceiptBinding(
                    logical_call_receipt_sha256=receipt_sha256,
                    endpoint_name=expected_endpoint_name,
                    logical_parameters_sha256=expected_logical_parameters_sha256,
                    provider_authority_sha256=expected_provider_authority_sha256,
                    result_route_ids=tuple(expected_result_route_ids),
                )
                payload = self._load_call(expected.logical_call_receipt_sha256)
                observed = LogicalCallReceiptBinding(
                    logical_call_receipt_sha256=expected.logical_call_receipt_sha256,
                    endpoint_name=payload["logical_endpoint_id"],
                    logical_parameters_sha256=payload["logical_parameters_sha256"],
                    provider_authority_sha256=payload["provider_authority_sha256"],
                    result_route_ids=tuple(payload["result_route_ids"]),
                )
            except ExtractionError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise ExtractionError("logical-call receipt contract is invalid") from exc
            if observed != expected:
                raise ExtractionError("logical-call receipt binding has expected-authority drift")
            return observed

    def load_generation_contexts(self) -> tuple[ParserInputContext, ...]:
        """Return every verified attempt/call context in an unsealed generation.

        Capture-session recovery uses this path-free inventory only to advance
        its next logical-call ordinal.  The method inventories the complete
        regular artifact tree and revalidates every receipt before returning;
        unknown files, malformed receipts, or foreign context shapes fail
        closed rather than being ignored.
        """

        with self._thread_lock:
            _artifacts, _blobs, attempts, calls = self._inventory_artifacts()
            contexts: list[ParserInputContext] = []
            for digest in sorted(attempts):
                payload = self._load_attempt(digest)
                contexts.append(ParserInputContext(**payload["context"]))
            for digest in sorted(calls):
                payload = self._load_call(digest)
                contexts.append(ParserInputContext(**payload["context"]))
            return tuple(
                sorted(
                    contexts,
                    key=lambda item: (
                        item.attempt_id,
                        item.retry_ordinal,
                        item.request_ordinal,
                    ),
                )
            )

    def load_recorded_attempt(self, receipt_sha256: str) -> RecordedParserInput:
        """Load and verify an attempt receipt and its content-addressed parser input."""

        with self._thread_lock:
            try:
                digest = _validate_sha256("receipt_sha256", receipt_sha256)
                payload = self._load_attempt(digest)
            except (KeyError, TypeError, ValueError) as exc:
                raise ExtractionError("attempt receipt contract is invalid") from exc
            parser_input = payload["parser_input"]
            if parser_input is None:
                raise ExtractionError("attempt receipt has no replayable parser input")
            try:
                captured = CapturedParserInput(**parser_input)
            except (TypeError, ValueError) as exc:
                raise ExtractionError("attempt parser-input contract is invalid") from exc
            raw_result_sets = payload["result_sets"]
            try:
                result_sets = tuple(ResultSetReceipt(**item) for item in raw_result_sets)
            except (TypeError, ValueError) as exc:
                raise ExtractionError("attempt result-set inventory is invalid") from exc
            return RecordedParserInput(
                receipt_sha256=digest,
                transport_kind=payload["transport_kind"],
                source_family=payload["source_family"],
                endpoint_id=payload["endpoint_id"],
                endpoint_slug=payload["endpoint_slug"],
                parameters_sha256=payload["parameters_sha256"],
                provider_authority_sha256=payload["provider_authority_sha256"],
                endpoint_contract_sha256=payload["endpoint_contract_sha256"],
                status_code=payload["status_code"],
                outcome=payload["outcome"],
                result_sets=result_sets,
                captured=captured,
                parser_input=self._verify_captured(captured),
            )

    def replay_parser_input(self, receipt_sha256: str) -> bytes:
        """Return verified raw parser input for compatibility with byte-level consumers."""

        return self.load_recorded_attempt(receipt_sha256).parser_input

    def _inventory_artifacts(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, Path], dict[str, Path], dict[str, Path]]:
        artifacts: list[dict[str, Any]] = []
        blobs: dict[str, Path] = {}
        attempts: dict[str, Path] = {}
        calls: dict[str, Path] = {}
        if self._root_fd >= 0:
            self._require_pinned_root()
            secure_inventory = _inventory_relative_regular_tree(
                self._root_fd,
                excluded_paths=frozenset({".capture.lock", "manifest.json"}),
            )
        else:
            try:
                secure_inventory = inventory_regular_tree(
                    self.root,
                    excluded_paths=frozenset({".capture.lock", "manifest.json"}),
                )
            except (NotADirectoryError, RuntimeError, ValueError) as exc:
                raise ExtractionError(
                    "private bronze generation cannot be inventoried safely"
                ) from exc
        for item in secure_inventory:
            relative = Path(item["path"])
            path = self.root / relative
            digest: str | None = None
            if len(relative.parts) == 4 and relative.parts[:2] == ("blobs", "sha256"):
                match = _BLOB_NAME_RE.fullmatch(relative.name)
                if match is not None and relative.parts[2] == match.group(1)[:2]:
                    digest = match.group(1)
                    blobs[digest] = path
            elif len(relative.parts) == 4 and relative.parts[0] == "receipts":
                kind = relative.parts[1]
                match = _RECEIPT_NAME_RE.fullmatch(relative.name)
                if (
                    kind in {"attempts", "calls"}
                    and match is not None
                    and relative.parts[2] == match.group(1)[:2]
                ):
                    digest = match.group(1)
                    (attempts if kind == "attempts" else calls)[digest] = path
            if digest is None:
                raise ExtractionError("private bronze generation contains an unknown artifact")
            if relative.parts[0] == "receipts" and item["sha256"] != digest:
                raise ExtractionError("private bronze receipt filename digest is invalid")
            artifacts.append(
                {
                    "path": relative.as_posix(),
                    "size_bytes": item["bytes"],
                    "sha256": item["sha256"],
                }
            )
        return artifacts, blobs, attempts, calls

    def build_manifest(
        self,
        *,
        provider_authority_sha256: str,
        semantic_source_sha: str | None,
        chain_id: str | None,
        lane_id: str | None,
        workflow_run_id: int,
        workflow_run_attempt: int,
        done_call_receipt_sha256s: Sequence[str],
    ) -> dict[str, Any]:
        with self._thread_lock:
            provider_digest = _validate_sha256(
                "provider_authority_sha256", provider_authority_sha256
            )
            if semantic_source_sha is not None:
                _validate_git_sha("semantic_source_sha", semantic_source_sha)
            if chain_id is not None:
                _validate_token("chain_id", chain_id)
            if lane_id is not None:
                _validate_token("lane_id", lane_id)
            execution_run_id = _validate_positive_int("workflow_run_id", workflow_run_id)
            execution_run_attempt = _validate_positive_int(
                "workflow_run_attempt", workflow_run_attempt
            )
            done_calls = tuple(sorted(set(done_call_receipt_sha256s)))
            if len(done_calls) != len(done_call_receipt_sha256s):
                raise ValueError("done logical-call inventory contains duplicates")
            artifacts, blobs, attempts, calls = self._inventory_artifacts()
            for digest in attempts:
                attempt = self._load_attempt(digest)
                if attempt["provider_authority_sha256"] != provider_digest:
                    raise ExtractionError(
                        "private bronze attempt has generation provider-authority drift"
                    )
            for digest in calls:
                call = self._load_call(digest)
                if call["provider_authority_sha256"] != provider_digest:
                    raise ExtractionError(
                        "private bronze logical call has generation provider-authority drift"
                    )
            if any(digest not in calls for digest in done_calls):
                raise ExtractionError("done logical-call inventory contains a dangling receipt")

            done_attempts: set[str] = set()
            done_blob_objects: set[str] = set()
            done_call_bindings: list[LogicalCallReceiptBinding] = []
            uncompressed_bytes_by_object: dict[str, int] = {}
            for digest in done_calls:
                call = self._load_call(digest)
                if call["provider_authority_sha256"] != provider_digest:
                    raise ExtractionError("done logical call has provider-authority drift")
                call_context = ParserInputContext(**call["context"])
                for field_name, expected in (
                    ("semantic_source_sha", semantic_source_sha),
                    ("chain_id", chain_id),
                    ("lane_id", lane_id),
                ):
                    if expected is not None and getattr(call_context, field_name) != expected:
                        raise ExtractionError("done logical call has generation-scope drift")
                if (
                    call_context.workflow_run_id != execution_run_id
                    or call_context.workflow_run_attempt != execution_run_attempt
                ):
                    raise ExtractionError("done logical call has generation-execution drift")
                done_call_bindings.append(
                    LogicalCallReceiptBinding(
                        logical_call_receipt_sha256=digest,
                        endpoint_name=call["logical_endpoint_id"],
                        logical_parameters_sha256=call["logical_parameters_sha256"],
                        provider_authority_sha256=call["provider_authority_sha256"],
                        result_route_ids=tuple(call["result_route_ids"]),
                    )
                )
                for attempt_digest in call["response_receipt_sha256s"]:
                    done_attempts.add(attempt_digest)
                    attempt = self._load_attempt(attempt_digest)
                    parser_input = attempt["parser_input"]
                    if parser_input is not None:
                        captured = CapturedParserInput(**parser_input)
                        done_blob_objects.add(captured.object_sha256)
                        uncompressed_bytes_by_object[captured.object_sha256] = (
                            captured.uncompressed_bytes
                        )

            all_blob_objects = set(blobs)
            referenced_blob_objects: set[str] = set()
            for digest in attempts:
                parser_input = self._load_attempt(digest)["parser_input"]
                if parser_input is not None:
                    referenced_blob_objects.add(parser_input["object_sha256"])
            if not referenced_blob_objects <= all_blob_objects:
                raise ExtractionError("attempt inventory references a missing parser-input object")

            artifact_set_sha256 = _sha256(
                _canonical_json_bytes(
                    [(item["path"], item["sha256"], item["size_bytes"]) for item in artifacts]
                )
            )
            binding_payloads = [
                _logical_call_binding_payload(binding) for binding in done_call_bindings
            ]
            manifest: dict[str, Any] = {
                "schema_version": BRONZE_SCHEMA_VERSION,
                "kind": "private_parser_input_generation",
                "sealed": True,
                "representation": PARSER_INPUT_REPRESENTATION,
                "static_representation": STATIC_INPUT_REPRESENTATION,
                "codec": self.codec,
                "codec_contract_sha256": CODEC_CONTRACT_SHA256,
                "provider_authority_sha256": provider_digest,
                "semantic_source_sha": semantic_source_sha,
                "chain_id": chain_id,
                "lane_id": lane_id,
                "workflow_run_id": execution_run_id,
                "workflow_run_attempt": execution_run_attempt,
                "artifacts": artifacts,
                "artifact_count": len(artifacts),
                "artifact_set_sha256": artifact_set_sha256,
                "stored_bytes": sum(item["size_bytes"] for item in artifacts),
                "done_call_receipt_sha256s": list(done_calls),
                "done_call_count": len(done_calls),
                "done_call_bindings": binding_payloads,
                "done_call_bindings_sha256": _sha256(_canonical_json_bytes(binding_payloads)),
                "done_attempt_receipt_sha256s": sorted(done_attempts),
                "done_attempt_count": len(done_attempts),
                "done_blob_object_sha256s": sorted(done_blob_objects),
                "done_blob_count": len(done_blob_objects),
                "done_uncompressed_bytes": sum(uncompressed_bytes_by_object.values()),
                "orphan_call_receipt_sha256s": sorted(set(calls) - set(done_calls)),
                "orphan_attempt_receipt_sha256s": sorted(set(attempts) - done_attempts),
                "orphan_blob_object_sha256s": sorted(all_blob_objects - done_blob_objects),
            }
            manifest["manifest_sha256"] = _sha256(_canonical_json_bytes(manifest))
            return manifest

    def write_manifest(
        self,
        *,
        provider_authority_sha256: str,
        semantic_source_sha: str | None,
        chain_id: str | None,
        lane_id: str | None,
        workflow_run_id: int,
        workflow_run_attempt: int,
        done_call_receipt_sha256s: Sequence[str],
    ) -> dict[str, Any]:
        with self._thread_lock:
            execution_run_id = _validate_positive_int("workflow_run_id", workflow_run_id)
            execution_run_attempt = _validate_positive_int(
                "workflow_run_attempt", workflow_run_attempt
            )
            if self._sealed:
                if self._manifest is None:
                    raise ExtractionError("sealed private bronze manifest is unavailable")
                requested = {
                    "provider_authority_sha256": provider_authority_sha256,
                    "semantic_source_sha": semantic_source_sha,
                    "chain_id": chain_id,
                    "lane_id": lane_id,
                    "workflow_run_id": execution_run_id,
                    "workflow_run_attempt": execution_run_attempt,
                    "done_call_receipt_sha256s": sorted(done_call_receipt_sha256s),
                }
                if any(self._manifest.get(key) != value for key, value in requested.items()):
                    raise ExtractionError("sealed private bronze manifest scope is immutable")
                return dict(self._manifest)
            manifest = self.build_manifest(
                provider_authority_sha256=provider_authority_sha256,
                semantic_source_sha=semantic_source_sha,
                chain_id=chain_id,
                lane_id=lane_id,
                workflow_run_id=execution_run_id,
                workflow_run_attempt=execution_run_attempt,
                done_call_receipt_sha256s=done_call_receipt_sha256s,
            )
            encoded = _canonical_json_bytes(manifest)
            if len(encoded) > self.limits.max_receipt_bytes:
                raise ParserInputCapacityError("private bronze manifest exceeds the receipt limit")
            if not self._publish(self.root / "manifest.json", encoded):
                raise ExtractionError("private bronze manifest already exists")
            self._manifest = manifest
            self._sealed = True
            return dict(manifest)

    def _read_manifest(self, path: Path) -> dict[str, Any]:
        manifest = self._read_json(path)
        if (
            manifest.get("schema_version") != BRONZE_SCHEMA_VERSION
            or manifest.get("kind") != "private_parser_input_generation"
            or manifest.get("sealed") is not True
        ):
            raise ExtractionError("private bronze manifest identity is invalid")
        expected = manifest.get("manifest_sha256")
        if not isinstance(expected, str):
            raise ExtractionError("private bronze manifest digest is absent")
        body = dict(manifest)
        body.pop("manifest_sha256", None)
        if _sha256(_canonical_json_bytes(body)) != expected:
            raise ExtractionError("private bronze manifest digest is invalid")
        try:
            _validate_positive_int("workflow_run_id", manifest.get("workflow_run_id"))
            _validate_positive_int("workflow_run_attempt", manifest.get("workflow_run_attempt"))
        except ValueError as exc:
            raise ExtractionError("private bronze manifest execution identity is invalid") from exc
        try:
            bindings = _logical_call_bindings_from_payload(manifest.get("done_call_bindings"))
            raw_binding_digest = manifest.get("done_call_bindings_sha256")
            if not isinstance(raw_binding_digest, str):
                raise ValueError("done_call_bindings_sha256 must be a string")
            binding_digest = _validate_sha256(
                "done_call_bindings_sha256",
                raw_binding_digest,
            )
        except ValueError as exc:
            raise ExtractionError("private bronze manifest binding contract is invalid") from exc
        binding_roots = [binding.logical_call_receipt_sha256 for binding in bindings]
        if binding_roots != manifest.get("done_call_receipt_sha256s"):
            raise ExtractionError(
                "private bronze manifest binding roots do not reconcile with done calls"
            )
        if binding_digest != _sha256(
            _canonical_json_bytes([_logical_call_binding_payload(binding) for binding in bindings])
        ):
            raise ExtractionError("private bronze manifest binding digest is invalid")
        return manifest
