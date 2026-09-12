"""Owned provider boundary for the exact pinned :mod:`nba_api` runtime.

The generated endpoint declarations and complex V2/V3 parsers remain owned by
``nba_api``.  This module owns the operational contract around them: one
bounded request, status and envelope validation, named result-set ordering,
lossless Polars construction, live JSON-root validation, and secret-safe
failure types.  Upstream response, endpoint, DataSet, and pandas objects do not
escape this boundary.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import polars as pl
import requests
from nba_api.library.http import NBAResponse
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library.http import STATS_HEADERS, NBAStatsHTTP, NBAStatsResponse
from requests.adapters import HTTPAdapter

from nbadb.core.errors import (
    ExtractionError,
    ParserInputCaptureIntegrityError,
    ResponseContractError,
    TransientError,
)
from nbadb.core.extraction_failures import (
    classify_exception,
    http_status_code,
    safe_root_error_type,
)
from nbadb.core.nba_api_contract import (
    NbaApiEndpointContract,
    NbaApiResponseModeContract,
    structured_data_set_columns,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_request_surface import (
    NbaApiRequestSurfaceError,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_runtime_contract import (
    LiveEndpointContract,
    LiveResultSetContract,
    StaticDatasetContract,
    endpoint_contract_sha256,
    owned_contract_sha256,
    pinned_endpoint_contract,
    pinned_live_contracts,
    pinned_live_endpoint_contract,
    pinned_runtime_contracts,
    pinned_static_dataset_contract,
)
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    STATIC_INPUT_REPRESENTATION,
    CapturedParserInput,
    Outcome,
    ParserInputCaptureSink,
    ParserInputContext,
    ParserInputReplaySource,
    RecordedParserInput,
    ResultSetReceipt,
    canonical_parameters_payload,
    canonical_parameters_sha256,
    parent_occurrence_states_digest,
)
from nbadb.extract.landing_projection import (
    apply_live_snapshot_contract,
    live_payload_to_frame,
    normalize_live_landing_frame,
    project_static_landing_frame,
)
from nbadb.extract.live_lossless import (
    NbaApiLiveLosslessLanding,
    build_live_lossless_landing,
    project_known_live_container,
    validate_live_lossless_frame,
)


@dataclass(frozen=True, slots=True)
class NbaApiReceiptEntry:
    """One ordered response attempt recorded for a logical provider call."""

    context: ParserInputContext
    receipt_sha256: str
    successful: bool


@dataclass(frozen=True, slots=True)
class NbaApiReceiptSnapshot:
    """Immutable receipt-ledger snapshot consumed by later runner binding."""

    entries: tuple[NbaApiReceiptEntry, ...]

    @property
    def receipt_sha256s(self) -> tuple[str, ...]:
        return tuple(entry.receipt_sha256 for entry in self.entries)

    @property
    def successful_response_ordinals(self) -> tuple[int, ...]:
        return tuple(index for index, entry in enumerate(self.entries) if entry.successful)


class NbaApiReceiptLedger:
    """Thread-safe request allocator and receipt ledger for one logical call."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_request_by_retry: dict[int, int] = {}
        self._allocated: dict[tuple[int, int], ParserInputContext] = {}
        self._allocation_order: list[tuple[int, int]] = []
        self._entries: dict[tuple[int, int], NbaApiReceiptEntry] = {}
        self._sealed_snapshot: NbaApiReceiptSnapshot | None = None

    def allocate(self, base: ParserInputContext) -> ParserInputContext:
        with self._lock:
            if self._sealed_snapshot is not None:
                raise ParserInputCaptureIntegrityError("parser-input receipt ledger is sealed")
            if base.request_ordinal != 0:
                raise ParserInputCaptureIntegrityError(
                    "parser-input retry contexts must begin at request ordinal zero"
                )
            seen_retries = set(self._next_request_by_retry)
            if not seen_retries:
                if base.retry_ordinal != 0:
                    raise ParserInputCaptureIntegrityError(
                        "parser-input retry ordinals must begin at zero"
                    )
            else:
                latest_retry = max(seen_retries)
                if base.retry_ordinal not in {latest_retry, latest_retry + 1}:
                    raise ParserInputCaptureIntegrityError(
                        "parser-input retry ordinals must be contiguous"
                    )
                if base.retry_ordinal == latest_retry + 1 and (
                    set(self._allocated) - set(self._entries)
                ):
                    raise ParserInputCaptureIntegrityError(
                        "parser-input prior retry has outstanding requests"
                    )
            next_ordinal = self._next_request_by_retry.get(base.retry_ordinal, 0)
            key = (base.retry_ordinal, next_ordinal)
            if key in self._allocated:
                raise ParserInputCaptureIntegrityError(
                    "parser-input request ordinal was already allocated"
                )
            context = replace(base, request_ordinal=next_ordinal)
            self._allocated[key] = context
            self._allocation_order.append(key)
            self._next_request_by_retry[base.retry_ordinal] = next_ordinal + 1
            return context

    def record(
        self,
        context: ParserInputContext,
        receipt_sha256: str,
        *,
        successful: bool,
    ) -> None:
        if (
            not isinstance(receipt_sha256, str)
            or len(receipt_sha256) != 64
            or any(character not in "0123456789abcdef" for character in receipt_sha256)
        ):
            raise ParserInputCaptureIntegrityError("parser-input receipt digest is invalid")
        key = (context.retry_ordinal, context.request_ordinal)
        with self._lock:
            if self._sealed_snapshot is not None:
                raise ParserInputCaptureIntegrityError("parser-input receipt ledger is sealed")
            if key not in self._allocated:
                raise ParserInputCaptureIntegrityError(
                    "parser-input receipt has no allocated request ordinal"
                )
            if self._allocated[key] != context:
                raise ParserInputCaptureIntegrityError(
                    "parser-input receipt context differs from its allocation"
                )
            if key in self._entries:
                raise ParserInputCaptureIntegrityError(
                    "parser-input request ordinal has multiple receipts"
                )
            self._entries[key] = NbaApiReceiptEntry(
                context=context,
                receipt_sha256=receipt_sha256,
                successful=successful,
            )

    def snapshot(self) -> NbaApiReceiptSnapshot:
        with self._lock:
            if self._sealed_snapshot is not None:
                return self._sealed_snapshot
            if set(self._allocated) - set(self._entries):
                raise ParserInputCaptureIntegrityError(
                    "parser-input receipt ledger has outstanding allocations"
                )
            if not self._allocation_order:
                raise ParserInputCaptureIntegrityError(
                    "parser-input receipt ledger cannot seal without requests"
                )
            self._sealed_snapshot = NbaApiReceiptSnapshot(
                tuple(self._entries[key] for key in self._allocation_order)
            )
            return self._sealed_snapshot


@dataclass(frozen=True, slots=True)
class NbaApiCaptureContract:
    """Required private-capture authority for one logical provider invocation."""

    sink: ParserInputCaptureSink
    context: ParserInputContext
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    receipt_ledger: NbaApiReceiptLedger = field(
        default_factory=NbaApiReceiptLedger,
        compare=False,
        repr=False,
    )

    def begin_request(self) -> ParserInputContext:
        return self.receipt_ledger.allocate(self.context)

    def record_receipt(
        self,
        context: ParserInputContext,
        receipt_sha256: str,
        *,
        successful: bool,
    ) -> None:
        self.receipt_ledger.record(context, receipt_sha256, successful=successful)

    def receipt_snapshot(self) -> NbaApiReceiptSnapshot:
        return self.receipt_ledger.snapshot()

    def for_retry(self, retry_ordinal: int) -> NbaApiCaptureContract:
        """Return a retry-scoped contract sharing this logical-call ledger."""

        if isinstance(retry_ordinal, bool) or not isinstance(retry_ordinal, int):
            raise ParserInputCaptureIntegrityError("retry ordinal must be an integer")
        return replace(
            self,
            context=replace(
                self.context,
                retry_ordinal=retry_ordinal,
                request_ordinal=0,
            ),
            receipt_ledger=self.receipt_ledger,
        )

    def for_endpoint_contract(self, endpoint_contract_sha256: str) -> NbaApiCaptureContract:
        """Bind another provider contract to the same logical-call ledger."""

        return replace(
            self,
            endpoint_contract_sha256=endpoint_contract_sha256,
            receipt_ledger=self.receipt_ledger,
        )


UnknownResponseState = Literal[
    "missing_result_envelope",
    "unknown_result_envelope",
    "generic_nested_json",
    "legacy_present_empty",
    "legacy_present_nonempty",
]
_UNKNOWN_RESPONSE_STATES = frozenset(
    {
        "missing_result_envelope",
        "unknown_result_envelope",
        "generic_nested_json",
        "legacy_present_empty",
        "legacy_present_nonempty",
    }
)


@dataclass(frozen=True, slots=True)
class NbaApiUnknownCell:
    """One exact canonical JSON value observed in an unknown legacy row."""

    value_kind: str
    canonical_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.value_kind, str) or not isinstance(self.canonical_json, str):
            raise ResponseContractError("unknown response cell tag is invalid")
        try:
            value = json.loads(self.canonical_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ResponseContractError("unknown response cell is not canonical JSON") from exc
        if (
            _canonical_json_value(value) != self.canonical_json
            or _json_value_kind(value) != self.value_kind
        ):
            raise ResponseContractError("unknown response cell canonical encoding drifted")


@dataclass(frozen=True, slots=True)
class NbaApiUnknownLegacyOccurrence:
    """One ordered provider occurrence with no inferred canonical result identity."""

    provider_index: int
    name: str
    headers: tuple[str, ...]
    rows: tuple[tuple[NbaApiUnknownCell, ...], ...]
    receipt: ResultSetReceipt

    def __post_init__(self) -> None:
        if (
            isinstance(self.provider_index, bool)
            or not isinstance(self.provider_index, int)
            or self.provider_index < 0
        ):
            raise ResponseContractError("unknown response provider index is invalid")
        if (
            not self.name
            or self.name.strip() != self.name
            or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}", self.name) is None
        ):
            raise ResponseContractError("unknown response result name is invalid")
        if (
            not isinstance(self.headers, tuple)
            or not isinstance(self.rows, tuple)
            or any(not isinstance(row, tuple) for row in self.rows)
            or any(not isinstance(cell, NbaApiUnknownCell) for row in self.rows for cell in row)
        ):
            raise ResponseContractError("unknown response occurrence is not immutable")
        if any(
            not isinstance(header, str) or not header or header.strip() != header
            for header in self.headers
        ):
            raise ResponseContractError("unknown response header is invalid")
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ResponseContractError("unknown response row width differs from its headers")
        normalized_rows = [[json.loads(cell.canonical_json) for cell in row] for row in self.rows]
        if (
            self.receipt.name != self.name
            or self.receipt.provider_index != self.provider_index
            or self.receipt.canonical_index is not None
            or self.receipt.headers_sha256 != _headers_sha256(self.headers)
            or self.receipt.row_count != len(self.rows)
            or self.receipt.json_path is not None
            or self.receipt.container_kind != "nba_api_result_set"
            or self.receipt.container_count != 1
            or self.receipt.missing_count != 0
            or self.receipt.null_count != 0
            or self.receipt.parent_observation_count != 1
            or self.receipt.parent_occurrence_states_sha256
            != parent_occurrence_states_digest(("present",))
            or self.receipt.observed_field_orders_sha256 != _headers_sha256(self.headers)
            or self.receipt.normalized_output_sha256
            != _normalized_output_sha256(self.headers, normalized_rows)
        ):
            raise ResponseContractError("unknown response occurrence receipt drifted")


@dataclass(frozen=True, slots=True)
class NbaApiUnknownResponse:
    """Body-bound observation for an endpoint with no declared result inventory."""

    endpoint_id: str
    endpoint_slug: str
    parameters_sha256: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    response_mode_authority_sha256: str
    parser_input_sha256: str
    canonical_payload_json: str
    canonical_payload_sha256: str
    state: UnknownResponseState
    legacy_envelope_name: str | None
    occurrences: tuple[NbaApiUnknownLegacyOccurrence, ...]
    response_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.endpoint_id, str)
            or not self.endpoint_id
            or self.endpoint_id.strip() != self.endpoint_id
            or not isinstance(self.endpoint_slug, str)
            or not self.endpoint_slug
            or self.endpoint_slug.strip() != self.endpoint_slug
        ):
            raise ResponseContractError("unknown response endpoint identity is invalid")
        if not isinstance(self.state, str) or self.state not in _UNKNOWN_RESPONSE_STATES:
            raise ResponseContractError("unknown response state is invalid")
        if not isinstance(self.occurrences, tuple):
            raise ResponseContractError("unknown response occurrences are not immutable")
        for field_name in (
            "parameters_sha256",
            "provider_authority_sha256",
            "endpoint_contract_sha256",
            "response_mode_authority_sha256",
            "parser_input_sha256",
            "canonical_payload_sha256",
        ):
            if _SHA256_RE.fullmatch(getattr(self, field_name)) is None:
                raise ResponseContractError(f"unknown response {field_name} is invalid")
        if self.response_receipt_sha256 is not None and (
            _SHA256_RE.fullmatch(self.response_receipt_sha256) is None
        ):
            raise ResponseContractError("unknown response receipt identity is invalid")
        try:
            canonical_payload = json.loads(self.canonical_payload_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ResponseContractError(
                "unknown response canonical payload is invalid JSON"
            ) from exc
        if (
            not isinstance(canonical_payload, dict)
            or _canonical_json_value(canonical_payload) != self.canonical_payload_json
            or hashlib.sha256(self.canonical_payload_json.encode("utf-8")).hexdigest()
            != self.canonical_payload_sha256
        ):
            raise ResponseContractError("unknown response canonical payload drifted")
        if self.state.startswith("legacy_") != (self.legacy_envelope_name is not None):
            raise ResponseContractError("unknown response legacy-envelope state is inconsistent")
        if self.legacy_envelope_name not in {None, "resultSets", "resultSet"}:
            raise ResponseContractError("unknown response legacy-envelope name is invalid")
        if [item.provider_index for item in self.occurrences] != list(range(len(self.occurrences))):
            raise ResponseContractError("unknown response occurrences are not ordered")
        has_rows = any(item.receipt.row_count for item in self.occurrences)
        if self.state == "legacy_present_nonempty" and not has_rows:
            raise ResponseContractError("unknown nonempty legacy response has no rows")
        if self.state == "legacy_present_empty" and has_rows:
            raise ResponseContractError("unknown empty legacy response contains rows")
        if not self.state.startswith("legacy_") and self.occurrences:
            raise ResponseContractError("unknown nonlegacy response contains result occurrences")

    @property
    def result_set_receipts(self) -> tuple[ResultSetReceipt, ...]:
        return tuple(item.receipt for item in self.occurrences)

    @property
    def outcome(self) -> Outcome:
        if self.state in {"missing_result_envelope", "legacy_present_empty"}:
            return "success_empty"
        return "success_nonempty"

    def bind_response_receipt(self, receipt_sha256: str) -> NbaApiUnknownResponse:
        if _SHA256_RE.fullmatch(receipt_sha256) is None:
            raise ResponseContractError("unknown response receipt identity is invalid")
        if self.response_receipt_sha256 not in {None, receipt_sha256}:
            raise ResponseContractError("unknown response receipt cannot be rebound")
        return replace(self, response_receipt_sha256=receipt_sha256)


class NbaApiPayload(dict[str, Any]):
    """An owned mapping that retains its private response-receipt identity."""

    response_receipt_sha256: str | None
    provider_authority_sha256: str | None
    endpoint_contract_sha256: str | None
    result_set_receipts: tuple[ResultSetReceipt, ...]
    live_lossless_landing: NbaApiLiveLosslessLanding | None
    unknown_response: NbaApiUnknownResponse | None

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        response_receipt_sha256: str | None = None,
        provider_authority_sha256: str | None = None,
        endpoint_contract_sha256: str | None = None,
        result_set_receipts: Sequence[ResultSetReceipt] = (),
        live_lossless_landing: NbaApiLiveLosslessLanding | None = None,
        unknown_response: NbaApiUnknownResponse | None = None,
    ) -> None:
        super().__init__(payload)
        self.response_receipt_sha256 = response_receipt_sha256
        self.provider_authority_sha256 = provider_authority_sha256
        self.endpoint_contract_sha256 = endpoint_contract_sha256
        self.result_set_receipts = tuple(result_set_receipts)
        self.live_lossless_landing = live_lossless_landing
        self.unknown_response = unknown_response


@dataclass(frozen=True, slots=True)
class NbaApiResultPacket:
    """An immutable, nbadb-owned result packet."""

    name: str
    provider_index: int
    canonical_index: int
    headers: tuple[str, ...]
    frame: pl.DataFrame
    response_receipt_sha256: str | None = None
    provider_authority_sha256: str | None = None
    endpoint_contract_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class RawAuthorityResultSetDerivation:
    """One result receipt independently rederived from public raw authority.

    The public raw tables retain the relational landing and staging receipts,
    while this value is derived only from the exact parser bytes (or the exact
    pinned bodyless static snapshot) and the embedded provider contracts.
    """

    result_set: ResultSetReceipt
    ordered_headers: tuple[str, ...]
    duplicate_name_ordinal: int


@dataclass(frozen=True, slots=True)
class RawAuthorityRouteFrameDerivation:
    """One no-network route frame reconstructed from raw response evidence.

    This frozen value is computation output, not admission authority.  In
    particular, ``live_snapshot_at`` is supplied by the reconstruction caller;
    Raw Authority V2 must separately require equality with the store-owned
    response receipt and the exact sealed plan/as-of authority.
    """

    route_id: str
    staging_key: str
    route_contract_sha256: str
    frame: pl.DataFrame
    source_result_ordinals: tuple[int, ...]
    row_count: int
    capture_response_receipt_sha256: str
    logical_parameters_sha256: str
    canonical_frame_format: str
    frame_content_hash_contract: str
    frame_schema_hash_contract: str
    frame_content_sha256: str
    frame_schema_sha256: str

    def __post_init__(self) -> None:
        from nbadb.orchestrate.staging_batches import (
            CANONICAL_FRAME_FORMAT,
            FRAME_CONTENT_HASH_CONTRACT,
            FRAME_SCHEMA_HASH_CONTRACT,
            frame_content_hash,
            frame_schema_hash,
        )

        if (
            type(self.route_id) is not str
            or not self.route_id
            or type(self.staging_key) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]*", self.staging_key) is None
            or type(self.frame) is not pl.DataFrame
            or type(self.source_result_ordinals) is not tuple
            or not self.source_result_ordinals
            or any(
                isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0
                for ordinal in self.source_result_ordinals
            )
            or self.source_result_ordinals != tuple(sorted(set(self.source_result_ordinals)))
            or isinstance(self.row_count, bool)
            or not isinstance(self.row_count, int)
            or self.row_count != self.frame.height
        ):
            raise ResponseContractError("raw route-frame derivation is not exactly typed")
        for digest in (
            self.route_contract_sha256,
            self.capture_response_receipt_sha256,
            self.logical_parameters_sha256,
            self.frame_content_sha256,
            self.frame_schema_sha256,
        ):
            if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
                raise ResponseContractError("raw route-frame derivation digest is invalid")
        if (
            self.canonical_frame_format != CANONICAL_FRAME_FORMAT
            or self.frame_content_hash_contract != FRAME_CONTENT_HASH_CONTRACT
            or self.frame_schema_hash_contract != FRAME_SCHEMA_HASH_CONTRACT
            or self.frame_content_sha256 != frame_content_hash(self.frame)
            or self.frame_schema_sha256 != frame_schema_hash(self.frame)
        ):
            raise ResponseContractError("raw route-frame derivation differs from Arrow V2")
        object.__setattr__(self, "frame", self.frame.clone())


@dataclass(frozen=True, slots=True)
class RawAuthorityStatsResultRows:
    """Exact row values rederived by the owned stats parser from public bytes.

    This is the production-parser side of value assurance.  It is deliberately
    not described as an independent verifier: callers must compare it with the
    separately implemented declarative decoder before admitting typed values.
    """

    result_set: ResultSetReceipt
    ordered_headers: tuple[str, ...]
    duplicate_name_ordinal: int
    rows: tuple[tuple[NbaApiUnknownCell, ...], ...]

    def __post_init__(self) -> None:
        if (
            type(self.result_set) is not ResultSetReceipt
            or type(self.ordered_headers) is not tuple
            or type(self.rows) is not tuple
            or any(type(row) is not tuple for row in self.rows)
            or any(type(cell) is not NbaApiUnknownCell for row in self.rows for cell in row)
            or isinstance(self.duplicate_name_ordinal, bool)
            or not isinstance(self.duplicate_name_ordinal, int)
            or self.duplicate_name_ordinal != 0
        ):
            raise ResponseContractError("raw stats row derivation is not exactly typed")
        if any(
            not isinstance(header, str) or not header or header.strip() != header
            for header in self.ordered_headers
        ) or len(set(self.ordered_headers)) != len(self.ordered_headers):
            raise ResponseContractError("raw stats row derivation headers are invalid")
        if any(len(row) != len(self.ordered_headers) for row in self.rows):
            raise ResponseContractError("raw stats row derivation width is invalid")
        normalized_rows = [[json.loads(cell.canonical_json) for cell in row] for row in self.rows]
        receipt = self.result_set
        if (
            receipt.container_kind != "nba_api_result_set"
            or receipt.provider_index is None
            or receipt.canonical_index is None
            or receipt.json_path is not None
            or receipt.headers_sha256 != _headers_sha256(self.ordered_headers)
            or receipt.row_count != len(self.rows)
            or receipt.container_count != 1
            or receipt.missing_count != 0
            or receipt.null_count != 0
            or receipt.parent_observation_count != 1
            or receipt.parent_occurrence_states_sha256
            != parent_occurrence_states_digest(("present",))
            or receipt.observed_field_orders_sha256 != _headers_sha256(self.ordered_headers)
            or receipt.normalized_output_sha256
            != _normalized_output_sha256(self.ordered_headers, normalized_rows)
        ):
            raise ResponseContractError("raw stats row derivation receipt drifted")


LOSSLESS_FALLBACK_STAGING_KEY = "stg_nba_api_lossless_result_cells"
LOSSLESS_FALLBACK_SCHEMA: dict[str, type[pl.DataType]] = {
    "response_receipt_sha256": pl.String,
    "provider_authority_sha256": pl.String,
    "endpoint_contract_sha256": pl.String,
    "response_mode_authority_sha256": pl.String,
    "parser_input_sha256": pl.String,
    "canonical_payload_sha256": pl.String,
    "parameters_sha256": pl.String,
    "endpoint_id": pl.String,
    "endpoint_slug": pl.String,
    "response_state": pl.String,
    "legacy_envelope_name": pl.String,
    "record_kind": pl.String,
    "result_set_name": pl.String,
    "result_set_occurrence": pl.Int64,
    "provider_index": pl.Int64,
    "canonical_index": pl.Int64,
    "header_name": pl.String,
    "header_ordinal": pl.Int64,
    "row_ordinal": pl.Int64,
    "node_ordinal": pl.Int64,
    "parent_node_ordinal": pl.Int64,
    "json_path": pl.String,
    "parent_json_path": pl.String,
    "depth": pl.Int64,
    "object_key": pl.String,
    "object_key_ordinal": pl.Int64,
    "array_ordinal": pl.Int64,
    "presence_kind": pl.String,
    "value_kind": pl.String,
    "canonical_json": pl.String,
    "anomaly_codes_json": pl.String,
}
_LOSSLESS_FALLBACK_RECORD_KINDS = frozenset(
    {"result_set", "missing_expected", "header", "row", "cell"}
)
_LOSSLESS_FALLBACK_VALUE_KINDS = frozenset(
    {"null", "boolean", "integer", "number", "string", "array", "object"}
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class NbaApiLosslessFallback:
    """Deterministic query projection for a successful drifted stats response.

    The exact decoded response retained by private bronze remains the replay
    authority.  This frame is the universal relational fallback used when a
    response cannot safely enter its pinned wide packet contract.
    """

    endpoint_slug: str
    reason_codes: tuple[str, ...]
    provider_result_set_count: int
    expected_result_set_count: int
    result_set_receipts: tuple[ResultSetReceipt, ...]
    frame: pl.DataFrame
    response_receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.endpoint_slug:
            raise ResponseContractError("lossless fallback endpoint slug must be nonempty")
        if not self.reason_codes or self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ResponseContractError(
                "lossless fallback reason codes must be sorted, unique, and nonempty"
            )
        for field_name in ("provider_result_set_count", "expected_result_set_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ResponseContractError(
                    f"lossless fallback {field_name} must be a nonnegative integer"
                )
        if self.response_receipt_sha256 is not None and (
            _SHA256_RE.fullmatch(self.response_receipt_sha256) is None
        ):
            raise ResponseContractError(
                "lossless fallback response receipt must be a lowercase SHA-256"
            )
        validate_lossless_fallback_frame(
            self.frame,
            expected_response_receipt_sha256=self.response_receipt_sha256,
        )

    @property
    def result_route_index(self) -> int:
        """Reserved route index immediately after the pinned wide routes."""

        return self.expected_result_set_count

    def bind_response_receipt(self, receipt_sha256: str) -> NbaApiLosslessFallback:
        if _SHA256_RE.fullmatch(receipt_sha256) is None:
            raise ResponseContractError(
                "lossless fallback response receipt must be a lowercase SHA-256"
            )
        return replace(
            self,
            response_receipt_sha256=receipt_sha256,
            frame=self.frame.with_columns(
                pl.lit(receipt_sha256, dtype=pl.String).alias("response_receipt_sha256")
            ),
        )


class NbaApiResultPackets(tuple[NbaApiResultPacket, ...]):
    """Tuple-compatible packet batch with optional out-of-band fallback data."""

    lossless_fallback: NbaApiLosslessFallback | None
    unknown_response: NbaApiUnknownResponse | None

    def __new__(
        cls,
        packets: Sequence[NbaApiResultPacket] = (),
        *,
        lossless_fallback: NbaApiLosslessFallback | None = None,
        unknown_response: NbaApiUnknownResponse | None = None,
    ) -> NbaApiResultPackets:
        value = super().__new__(cls, tuple(packets))
        value.lossless_fallback = lossless_fallback
        value.unknown_response = unknown_response
        return value


class UpstreamHttpError(ExtractionError):
    """A non-success HTTP response with status retained for classification."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"upstream HTTP status {status_code}")


class UpstreamTransientHttpError(TransientError):
    """A retryable upstream HTTP or JSON-envelope status."""

    def __init__(self, status_code: int, *, source: str = "HTTP") -> None:
        self.status_code = status_code
        super().__init__(f"upstream {source} status {status_code}")


class UpstreamApplicationError(ExtractionError):
    """A deterministic upstream error envelope."""

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(detail)


def _raise_upstream_status(status: int, *, source: str) -> None:
    if status == 429 or status >= 500:
        raise UpstreamTransientHttpError(status, source=source)
    if source == "HTTP":
        raise UpstreamHttpError(status)
    raise UpstreamApplicationError(
        f"upstream JSON error envelope (status {status})",
        status_code=status,
    )


class _ThreadLocalSessionMixin:
    _thread_local = threading.local()

    @classmethod
    def get_session(cls) -> requests.Session:
        session = getattr(cls._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            # Extraction routing is explicit.  Ambient HTTP(S)_PROXY values
            # must not silently change the egress contract.
            session.trust_env = False
            adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            cls._thread_local.session = session
        return session

    @classmethod
    def evict_session(cls) -> None:
        session = getattr(cls._thread_local, "session", None)
        if session is not None:
            session.close()
            del cls._thread_local.session


class NbaDbStatsHTTP(_ThreadLocalSessionMixin, NBAStatsHTTP):
    """Pinned request construction with per-thread, environment-free sessions."""

    _thread_local = threading.local()
    headers = dict(STATS_HEADERS)

    def clean_contents(self, contents: str) -> str:
        """Preserve exact decoded text; nbadb owns error-envelope classification."""

        return contents


class NbaDbLiveHTTP(_ThreadLocalSessionMixin, NBALiveHTTP):
    """Pinned live request construction with an isolated session pool."""

    _thread_local = threading.local()
    headers = dict(NBALiveHTTP.headers)


def _ordered_headers(
    supplied: Mapping[str, str] | None,
    expected: Mapping[str, str],
) -> dict[str, str]:
    if supplied is None:
        return dict(expected)
    if tuple(supplied.items()) != tuple(expected.items()):
        raise ResponseContractError("custom provider headers do not match the ordered contract")
    if any(not isinstance(value, str) for value in supplied.values()):
        raise ResponseContractError("custom provider headers must contain string values")
    return dict(supplied)


def _response_status(response: object) -> int:
    raw = getattr(response, "_status_code", None)
    if raw is None:
        raise ResponseContractError("provider response omitted a valid HTTP status")
    try:
        status = int(raw)
    except (TypeError, ValueError) as exc:
        raise ResponseContractError("provider response omitted a valid HTTP status") from exc
    if not 100 <= status <= 599:
        raise ResponseContractError("provider response contained an invalid HTTP status")
    return status


def _optional_response_status(response: object) -> int | None:
    try:
        return _response_status(response)
    except ResponseContractError:
        return None


def _response_parser_input(response: object) -> str:
    get_response = getattr(response, "get_response", None)
    if not callable(get_response):
        raise ResponseContractError("provider response omitted its parser input")
    parser_input = get_response()
    if not isinstance(parser_input, str):
        raise ResponseContractError("provider parser input must be decoded text")
    return parser_input


def _root_exception_class(exc: BaseException) -> str:
    return safe_root_error_type(exc)


def _failure_receipt_contract(exc: Exception) -> tuple[Outcome, str]:
    failure_class = classify_exception(exc)
    if isinstance(exc, UpstreamTransientHttpError):
        return "http_transient_error", "transport_transient"
    if isinstance(exc, UpstreamHttpError):
        return "http_application_error", "application"
    if isinstance(exc, UpstreamApplicationError):
        return "application_error_envelope", "application"
    if safe_root_error_type(exc) == "JSONDecodeError":
        return "malformed_json", "response_contract"
    if isinstance(exc, ResponseContractError):
        return "contract_mismatch", failure_class
    return "parser_failure", failure_class


def _capture_response(
    response: object,
    capture: NbaApiCaptureContract | None,
) -> tuple[CapturedParserInput | None, str]:
    """Read one immutable parser input and optionally persist those exact bytes."""

    parser_input = _response_parser_input(response)
    captured = (
        None
        if capture is None
        else capture.sink.store_parser_input(
            parser_input,
            representation=PARSER_INPUT_REPRESENTATION,
        )
    )
    return captured, parser_input


def _headers_sha256(headers: Sequence[str]) -> str:
    encoded = json.dumps(list(headers), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_output_sha256(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    return _canonical_value_sha256(
        {
            "headers": list(headers),
            "rows": [list(row) for row in rows],
        }
    )


def _observed_field_orders_sha256(rows: Sequence[object]) -> str:
    return _canonical_value_sha256([list(row) if isinstance(row, Mapping) else [] for row in rows])


def _canonical_value_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json_value(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResponseContractError(
            "provider fallback value is not a canonical JSON value"
        ) from exc


def _json_value_kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list | tuple):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    raise ResponseContractError("provider fallback value has a non-JSON runtime type")


def validate_lossless_fallback_frame(
    frame: pl.DataFrame,
    *,
    expected_response_receipt_sha256: str | None = None,
) -> None:
    """Validate the fixed universal fallback frame without schema inference."""

    if frame.columns != list(LOSSLESS_FALLBACK_SCHEMA) or dict(frame.schema) != (
        LOSSLESS_FALLBACK_SCHEMA
    ):
        raise ResponseContractError("lossless fallback frame schema differs from its contract")
    if frame.is_empty():
        raise ResponseContractError("lossless fallback frame must retain an observation record")

    rows = frame.to_dicts()
    observed_receipts = {
        row["response_receipt_sha256"] for row in rows if row["response_receipt_sha256"] is not None
    }
    if expected_response_receipt_sha256 is None:
        if observed_receipts:
            raise ResponseContractError(
                "unbound lossless fallback frame contains a response receipt"
            )
    elif (
        _SHA256_RE.fullmatch(expected_response_receipt_sha256) is None
        or observed_receipts != {expected_response_receipt_sha256}
        or any(row["response_receipt_sha256"] is None for row in rows)
    ):
        raise ResponseContractError("lossless fallback frame does not match its response receipt")

    endpoints = {row["endpoint_slug"] for row in rows}
    if len(endpoints) != 1 or not next(iter(endpoints), None):
        raise ResponseContractError("lossless fallback frame endpoint identity is invalid")
    reason_payloads = {row["anomaly_codes_json"] for row in rows}
    if len(reason_payloads) != 1:
        raise ResponseContractError("lossless fallback reason inventory is inconsistent")
    reason_payload = next(iter(reason_payloads))
    try:
        reasons = json.loads(cast("str", reason_payload))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResponseContractError("lossless fallback reason inventory is invalid") from exc
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not item for item in reasons)
        or reasons != sorted(set(reasons))
        or _canonical_json_value(reasons) != reason_payload
    ):
        raise ResponseContractError("lossless fallback reason inventory is not canonical")

    response_states = {row["response_state"] for row in rows}
    if response_states != {None}:
        if None in response_states or len(response_states) != 1:
            raise ResponseContractError(
                "lossless fallback mixes unknown-response and declared-result authority"
            )
        from nbadb.extract.stats_lossless import validate_unknown_stats_lossless_frame

        validate_unknown_stats_lossless_frame(
            frame,
            expected_response_receipt_sha256=expected_response_receipt_sha256,
        )
        return

    declared_only_nullable_columns = (
        "provider_authority_sha256",
        "endpoint_contract_sha256",
        "response_mode_authority_sha256",
        "parser_input_sha256",
        "canonical_payload_sha256",
        "parameters_sha256",
        "endpoint_id",
        "legacy_envelope_name",
        "node_ordinal",
        "parent_node_ordinal",
        "json_path",
        "parent_json_path",
        "depth",
        "object_key",
        "object_key_ordinal",
        "array_ordinal",
        "presence_kind",
    )
    if any(
        row[field_name] is not None for row in rows for field_name in declared_only_nullable_columns
    ):
        raise ResponseContractError(
            "declared-result fallback contains unknown-response-only authority"
        )

    result_rows: dict[int, dict[str, Any]] = {}
    missing_rows: list[dict[str, Any]] = []
    header_rows: dict[int, list[dict[str, Any]]] = {}
    row_rows: dict[int, list[dict[str, Any]]] = {}
    cell_rows: dict[tuple[int, int], list[dict[str, Any]]] = {}
    occurrences: Counter[str] = Counter()
    for row in rows:
        record_kind = row["record_kind"]
        if record_kind not in _LOSSLESS_FALLBACK_RECORD_KINDS:
            raise ResponseContractError("lossless fallback record kind is invalid")
        for field_name in (
            "result_set_occurrence",
            "provider_index",
            "canonical_index",
            "header_ordinal",
            "row_ordinal",
        ):
            value = row[field_name]
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ResponseContractError(
                    f"lossless fallback {field_name} must be nonnegative or null"
                )
        if not isinstance(row["result_set_name"], str) or not row["result_set_name"]:
            raise ResponseContractError("lossless fallback result-set name is invalid")
        if record_kind == "result_set":
            provider_index = row["provider_index"]
            if provider_index is None or provider_index in result_rows:
                raise ResponseContractError(
                    "lossless fallback provider result-set occurrence is duplicated"
                )
            expected_occurrence = occurrences[row["result_set_name"]]
            if row["result_set_occurrence"] != expected_occurrence:
                raise ResponseContractError(
                    "lossless fallback result-set occurrence is not contiguous"
                )
            occurrences[row["result_set_name"]] += 1
            result_rows[provider_index] = row
        elif record_kind == "missing_expected":
            if row["provider_index"] is not None or row["canonical_index"] is None:
                raise ResponseContractError("lossless fallback missing-result identity is invalid")
            missing_rows.append(row)
        else:
            provider_index = row["provider_index"]
            if provider_index is None:
                raise ResponseContractError(
                    "lossless fallback child record omitted its provider occurrence"
                )
            if record_kind == "header":
                if row["header_ordinal"] is None or row["row_ordinal"] is not None:
                    raise ResponseContractError("lossless fallback header ordinal is invalid")
                header_rows.setdefault(provider_index, []).append(row)
            elif record_kind == "row":
                if row["row_ordinal"] is None or row["header_ordinal"] is not None:
                    raise ResponseContractError("lossless fallback row ordinal is invalid")
                row_rows.setdefault(provider_index, []).append(row)
            else:
                if row["row_ordinal"] is None or row["header_ordinal"] is None:
                    raise ResponseContractError("lossless fallback cell ordinals are invalid")
                cell_rows.setdefault((provider_index, row["row_ordinal"]), []).append(row)

        value_kind = row["value_kind"]
        canonical_json = row["canonical_json"]
        if (value_kind is None) != (canonical_json is None):
            raise ResponseContractError("lossless fallback value tag is incomplete")
        if value_kind is not None:
            if value_kind not in _LOSSLESS_FALLBACK_VALUE_KINDS:
                raise ResponseContractError("lossless fallback value kind is invalid")
            try:
                value = json.loads(canonical_json)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ResponseContractError(
                    "lossless fallback canonical JSON value is invalid"
                ) from exc
            if (
                _canonical_json_value(value) != canonical_json
                or _json_value_kind(value) != value_kind
            ):
                raise ResponseContractError(
                    "lossless fallback value tag differs from canonical JSON"
                )

    if sorted(result_rows) != list(range(len(result_rows))):
        raise ResponseContractError(
            "lossless fallback provider result-set indexes are not contiguous"
        )
    if [row["canonical_index"] for row in missing_rows] != sorted(
        row["canonical_index"] for row in missing_rows
    ):
        raise ResponseContractError(
            "lossless fallback missing-result records are not in canonical order"
        )
    for provider_index, result_row in result_rows.items():
        identity = (
            result_row["result_set_name"],
            result_row["result_set_occurrence"],
            result_row["canonical_index"],
        )
        headers = header_rows.get(provider_index, [])
        observed_rows = row_rows.get(provider_index, [])
        if [row["header_ordinal"] for row in headers] != list(range(len(headers))):
            raise ResponseContractError("lossless fallback header ordinals are not contiguous")
        if [row["row_ordinal"] for row in observed_rows] != list(range(len(observed_rows))):
            raise ResponseContractError("lossless fallback row ordinals are not contiguous")
        for child in (
            headers
            + observed_rows
            + [
                item
                for key, items in cell_rows.items()
                if key[0] == provider_index
                for item in items
            ]
        ):
            if (
                child["result_set_name"],
                child["result_set_occurrence"],
                child["canonical_index"],
            ) != identity:
                raise ResponseContractError(
                    "lossless fallback child identity differs from its result set"
                )
        for row_record in observed_rows:
            row_ordinal = cast("int", row_record["row_ordinal"])
            decoded_row = json.loads(cast("str", row_record["canonical_json"]))
            cells = cell_rows.get((provider_index, row_ordinal), [])
            if not isinstance(decoded_row, list):
                if cells:
                    raise ResponseContractError(
                        "lossless fallback non-sequence row cannot contain cell records"
                    )
                continue
            if [cell["header_ordinal"] for cell in cells] != list(range(len(cells))):
                raise ResponseContractError("lossless fallback cell ordinals are not contiguous")
            if [json.loads(cast("str", cell["canonical_json"])) for cell in cells] != decoded_row:
                raise ResponseContractError(
                    "lossless fallback cells do not reconstruct their provider row"
                )


def _record_response_failure(
    *,
    capture: NbaApiCaptureContract | None,
    captured: CapturedParserInput | None,
    response: object,
    source_family: str,
    endpoint_id: str,
    endpoint_slug: str,
    parameters: Mapping[str, Any],
    context: ParserInputContext | None,
    exc: Exception,
) -> str | None:
    if capture is None:
        return None
    if captured is None:
        raise ResponseContractError("provider response was not captured before failure") from exc
    if context is None:
        raise ResponseContractError("provider response omitted its request context") from exc
    outcome, failure_class = _failure_receipt_contract(exc)
    effective_status = http_status_code(exc)
    receipt = capture.sink.record_response_attempt(
        context=context,
        transport_kind="http_response",
        source_family=source_family,
        endpoint_id=endpoint_id,
        endpoint_slug=endpoint_slug,
        parameters=parameters,
        provider_authority_sha256=capture.provider_authority_sha256,
        contract_sha256=capture.endpoint_contract_sha256,
        status_code=_optional_response_status(response),
        effective_status_code=effective_status,
        captured=captured,
        outcome=outcome,
        failure_class=failure_class,
        root_exception_class=_root_exception_class(exc),
        result_sets=(),
    )
    capture.record_receipt(context, receipt, successful=False)
    return receipt


def _record_no_response_failure(
    *,
    capture: NbaApiCaptureContract | None,
    source_family: str,
    endpoint_id: str,
    endpoint_slug: str,
    parameters: Mapping[str, Any],
    context: ParserInputContext | None,
    exc: Exception,
) -> str | None:
    if capture is None:
        return None
    if context is None:
        raise ResponseContractError("provider request omitted its capture context") from exc
    _outcome, failure_class = _failure_receipt_contract(exc)
    receipt = capture.sink.record_no_response_attempt(
        context=context,
        transport_kind="http_response",
        source_family=source_family,
        endpoint_id=endpoint_id,
        endpoint_slug=endpoint_slug,
        parameters=parameters,
        provider_authority_sha256=capture.provider_authority_sha256,
        contract_sha256=capture.endpoint_contract_sha256,
        outcome="transport_failure_no_response",
        failure_class=failure_class,
        root_exception_class=_root_exception_class(exc),
    )
    capture.record_receipt(context, receipt, successful=False)
    return receipt


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ResponseContractError("provider JSON contains duplicate object keys")
        payload[key] = value
    return payload


def _validated_response_dict(
    response: object,
    *,
    parser_input: str | None = None,
) -> dict[str, Any]:
    status = _response_status(response)
    if not 200 <= status < 300:
        _raise_upstream_status(status, source="HTTP")
    if parser_input is None:
        parser_input = _response_parser_input(response)
    try:
        decoded = json.loads(
            parser_input,
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except ResponseContractError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResponseContractError("provider returned malformed JSON") from exc
    if not isinstance(decoded, dict):
        raise ResponseContractError("provider JSON root must be an object")
    get_dict = getattr(response, "get_dict", None)
    if not callable(get_dict):
        raise ResponseContractError("provider response omitted get_dict")
    try:
        payload = get_dict()
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResponseContractError("provider returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise ResponseContractError("provider JSON root must be an object")
    if payload != decoded:
        raise ResponseContractError("provider parsed JSON differs from its parser input")

    _validate_decoded_response_envelope(payload)
    return payload


def _validate_decoded_response_envelope(payload: Mapping[str, Any]) -> None:
    """Apply the production JSON error-envelope gate to one decoded body."""

    status_candidates = (
        payload.get("statusCode"),
        payload.get("status"),
        payload.get("code"),
        payload.get("meta", {}).get("code") if isinstance(payload.get("meta"), dict) else None,
    )
    for candidate in status_candidates:
        if isinstance(candidate, int) and candidate >= 400:
            _raise_upstream_status(candidate, source="JSON error envelope")
    has_result_envelope = "resultSets" in payload or "resultSet" in payload
    if not has_result_envelope and any(key in payload for key in ("Message", "message", "error")):
        raise UpstreamApplicationError("upstream JSON error envelope")


def _flatten_headers(raw_headers: object) -> tuple[str, ...]:
    if not isinstance(raw_headers, (list, tuple)) or not raw_headers:
        raise ResponseContractError("result-set headers must be a non-empty sequence")
    if all(isinstance(header, str) for header in raw_headers):
        headers = tuple(str(header) for header in raw_headers)
    elif isinstance(raw_headers, list) and all(isinstance(header, dict) for header in raw_headers):
        headers = structured_data_set_columns(raw_headers)
    else:
        raise ResponseContractError("result-set headers have mixed or unsupported forms")
    if not headers or any(not header.strip() for header in headers):
        raise ResponseContractError("result-set headers contain an empty column")
    if len(set(headers)) != len(headers):
        raise ResponseContractError("result-set headers contain duplicate columns")
    return headers


def _validated_rows(raw_rows: object, width: int) -> tuple[tuple[Any, ...], ...]:
    if not isinstance(raw_rows, list):
        raise ResponseContractError("result-set rows must be a list")
    rows: list[tuple[Any, ...]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, (list, tuple)):
            raise ResponseContractError("result-set row must be a sequence")
        if len(raw_row) != width:
            raise ResponseContractError("result-set row width does not match headers")
        rows.append(tuple(raw_row))
    return tuple(rows)


def rows_to_polars(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> pl.DataFrame:
    """Construct a lossless Polars frame from an already validated packet."""

    schema = list(headers)
    if not rows:
        return pl.DataFrame({name: pl.Series(name, [], dtype=pl.Null) for name in schema})
    for column_index, name in enumerate(schema):
        value_types = {type(row[column_index]) for row in rows if row[column_index] is not None}
        if len(value_types) > 1:
            raise ResponseContractError(
                f"result-set column {name!r} contains heterogeneous JSON value types"
            )
    try:
        return pl.DataFrame(
            list(rows),
            schema=schema,
            orient="row",
            infer_schema_length=None,
        )
    except (TypeError, ValueError, pl.exceptions.PolarsError) as exc:
        raise ResponseContractError("result-set values cannot be represented losslessly") from exc


def _fallback_headers(raw_headers: object) -> tuple[tuple[str | None, ...], tuple[object, ...]]:
    """Return effective header names plus their canonical fallback values."""

    if not isinstance(raw_headers, (list, tuple)):
        return (), ()
    raw_items = tuple(raw_headers)
    if all(isinstance(item, str) for item in raw_items):
        names = tuple(cast("str", item) for item in raw_items)
        return names, tuple(names)
    if isinstance(raw_headers, list) and all(isinstance(item, dict) for item in raw_headers):
        try:
            names = structured_data_set_columns(raw_headers)
        except (KeyError, TypeError, ValueError, IndexError):
            names = ()
        if names:
            return tuple(names), tuple(names)
    names = tuple(item if isinstance(item, str) else None for item in raw_items)
    return names, raw_items


def _fallback_ordered_headers(raw_headers: object) -> tuple[str, ...]:
    """Return the closed string-only header projection for raw authority.

    The conditional fallback rows retain every exact raw header value and its
    ordinal.  The relational raw-request authority deliberately exposes only
    a complete ordered string header sequence; unsupported or mixed header
    containers therefore project to the empty sequence instead of inventing
    names or collapsing ordinals.
    """

    names, _raw_values = _fallback_headers(raw_headers)
    if any(type(name) is not str or not name for name in names):
        return ()
    return cast("tuple[str, ...]", names)


def _header_anomalies(
    expected: Sequence[str] | None,
    observed: Sequence[str | None],
) -> set[str]:
    reasons: set[str] = set()
    if any(name is None for name in observed):
        reasons.add("unsupported_header_shape")
    observed_names = tuple(name for name in observed if name is not None)
    if len(set(observed_names)) != len(observed_names):
        reasons.add("duplicate_header")
    if expected is None:
        return reasons
    expected_counter = Counter(expected)
    observed_counter = Counter(observed_names)
    if observed_counter - expected_counter:
        reasons.add("additive_header")
    if expected_counter - observed_counter:
        reasons.add("removed_header")
    if expected_counter == observed_counter and tuple(expected) != observed_names:
        reasons.add("reordered_header")
    return reasons


def _result_set_fallback_anomalies(
    provider_sets: Sequence[tuple[str, object, object]],
    expected: Sequence[tuple[str, tuple[str, ...]]],
) -> tuple[set[str], list[set[str]]]:
    expected_by_name = {name: headers for name, headers in expected}
    expected_names = [name for name, _headers in expected]
    provider_names = [name for name, _headers, _rows in provider_sets]
    global_reasons: set[str] = set()
    if Counter(provider_names) - Counter(expected_names):
        global_reasons.add("additive_result_set")
    if Counter(expected_names) - Counter(provider_names):
        global_reasons.add("missing_result_set")
    if any(count > 1 for count in Counter(provider_names).values()):
        global_reasons.add("duplicate_result_set_name")

    per_set: list[set[str]] = []
    for name, raw_headers, raw_rows in provider_sets:
        headers, _header_values = _fallback_headers(raw_headers)
        reasons = _header_anomalies(expected_by_name.get(name), headers)
        if not isinstance(raw_headers, (list, tuple)):
            reasons.add("unsupported_header_shape")
        if not isinstance(raw_rows, list):
            reasons.add("unsupported_row_container")
            per_set.append(reasons)
            global_reasons.update(reasons)
            continue
        widths: set[int] = set()
        kinds_by_ordinal: dict[int, set[str]] = {}
        for raw_row in raw_rows:
            if not isinstance(raw_row, (list, tuple)):
                reasons.add("non_sequence_row")
                continue
            widths.add(len(raw_row))
            if len(raw_row) != len(headers):
                reasons.add("ragged_row")
            for ordinal, value in enumerate(raw_row):
                kind = _json_value_kind(value)
                if kind != "null":
                    kinds_by_ordinal.setdefault(ordinal, set()).add(kind)
        if len(widths) > 1:
            reasons.add("ragged_row")
        if any(len(kinds) > 1 for kinds in kinds_by_ordinal.values()):
            reasons.add("heterogeneous_column")
        per_set.append(reasons)
        global_reasons.update(reasons)
    return global_reasons, per_set


def _fallback_frame(
    *,
    endpoint_slug: str,
    provider_sets: Sequence[tuple[str, object, object]],
    expected: Sequence[tuple[str, tuple[str, ...]]],
    reasons: set[str],
    per_set_reasons: Sequence[set[str]],
) -> tuple[pl.DataFrame, tuple[ResultSetReceipt, ...]]:
    expected_by_name = {name: (index, headers) for index, (name, headers) in enumerate(expected)}
    provider_name_counts = Counter(name for name, _headers, _rows in provider_sets)
    occurrences: Counter[str] = Counter()
    reason_payload = _canonical_json_value(sorted(reasons))
    records: list[dict[str, object | None]] = []
    result_receipts: list[ResultSetReceipt] = []

    def add_record(
        *,
        record_kind: str,
        name: str,
        occurrence: int,
        provider_index: int | None,
        canonical_index: int | None,
        header_name: str | None = None,
        header_ordinal: int | None = None,
        row_ordinal: int | None = None,
        value: object | None = None,
        has_value: bool = False,
    ) -> None:
        records.append(
            {
                "response_receipt_sha256": None,
                "endpoint_slug": endpoint_slug,
                "record_kind": record_kind,
                "result_set_name": name,
                "result_set_occurrence": occurrence,
                "provider_index": provider_index,
                "canonical_index": canonical_index,
                "header_name": header_name,
                "header_ordinal": header_ordinal,
                "row_ordinal": row_ordinal,
                "value_kind": _json_value_kind(value) if has_value else None,
                "canonical_json": _canonical_json_value(value) if has_value else None,
                "anomaly_codes_json": reason_payload,
            }
        )

    for provider_index, (name, raw_headers, raw_rows) in enumerate(provider_sets):
        occurrence = occurrences[name]
        occurrences[name] += 1
        expected_match = expected_by_name.get(name)
        canonical_index = (
            expected_match[0]
            if expected_match is not None and provider_name_counts[name] == 1
            else None
        )
        add_record(
            record_kind="result_set",
            name=name,
            occurrence=occurrence,
            provider_index=provider_index,
            canonical_index=canonical_index,
        )
        header_names, header_values = _fallback_headers(raw_headers)
        for header_ordinal, header_value in enumerate(header_values):
            header_name = (
                header_names[header_ordinal] if header_ordinal < len(header_names) else None
            )
            add_record(
                record_kind="header",
                name=name,
                occurrence=occurrence,
                provider_index=provider_index,
                canonical_index=canonical_index,
                header_name=header_name,
                header_ordinal=header_ordinal,
                value=header_value,
                has_value=True,
            )

        rows = raw_rows if isinstance(raw_rows, list) else []
        for row_ordinal, raw_row in enumerate(rows):
            add_record(
                record_kind="row",
                name=name,
                occurrence=occurrence,
                provider_index=provider_index,
                canonical_index=canonical_index,
                row_ordinal=row_ordinal,
                value=raw_row,
                has_value=True,
            )
            if not isinstance(raw_row, (list, tuple)):
                continue
            for header_ordinal, value in enumerate(raw_row):
                header_name = (
                    header_names[header_ordinal] if header_ordinal < len(header_names) else None
                )
                add_record(
                    record_kind="cell",
                    name=name,
                    occurrence=occurrence,
                    provider_index=provider_index,
                    canonical_index=canonical_index,
                    header_name=header_name,
                    header_ordinal=header_ordinal,
                    row_ordinal=row_ordinal,
                    value=value,
                    has_value=True,
                )

        normalized_rows = raw_rows if isinstance(raw_rows, list) else []
        headers_digest = _headers_sha256(_fallback_ordered_headers(raw_headers))
        result_receipts.append(
            ResultSetReceipt(
                name=name,
                provider_index=provider_index,
                canonical_index=None,
                headers_sha256=headers_digest,
                row_count=len(normalized_rows),
                json_path=None,
                container_kind="nba_api_result_set",
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
                observed_field_orders_sha256=headers_digest,
                normalized_output_sha256=_canonical_value_sha256(
                    {
                        "headers": raw_headers,
                        "rows": raw_rows,
                        "anomalies": sorted(per_set_reasons[provider_index]),
                    }
                ),
            )
        )

    for canonical_index, (name, expected_headers) in enumerate(expected):
        if provider_name_counts[name]:
            continue
        add_record(
            record_kind="missing_expected",
            name=name,
            occurrence=0,
            provider_index=None,
            canonical_index=canonical_index,
        )
        headers_digest = _headers_sha256(expected_headers)
        result_receipts.append(
            ResultSetReceipt(
                name=name,
                provider_index=None,
                canonical_index=None,
                headers_sha256=headers_digest,
                row_count=0,
                json_path=None,
                container_kind="nba_api_result_set",
                container_count=0,
                missing_count=1,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("missing",)),
                observed_field_orders_sha256=headers_digest,
                normalized_output_sha256=_normalized_output_sha256(expected_headers, ()),
            )
        )

    frame = pl.DataFrame(records, schema=LOSSLESS_FALLBACK_SCHEMA, orient="row")
    validate_lossless_fallback_frame(frame)
    return frame, tuple(result_receipts)


def _legacy_data_sets(payload: Mapping[str, Any]) -> list[tuple[str, object, object]]:
    roots = [name for name in ("resultSets", "resultSet") if name in payload]
    if len(roots) != 1:
        raise ResponseContractError("provider must return exactly one result-set envelope")
    raw_sets = payload[roots[0]]
    if isinstance(raw_sets, dict):
        raw_sets = [raw_sets]
    if not isinstance(raw_sets, list):
        raise ResponseContractError("result-set envelope must contain an object or list")

    packets: list[tuple[str, object, object]] = []
    for raw_set in raw_sets:
        if not isinstance(raw_set, dict):
            raise ResponseContractError("result-set entry must be an object")
        name = raw_set.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ResponseContractError("result-set entry omitted its name")
        if "headers" not in raw_set or "rowSet" not in raw_set:
            raise ResponseContractError("result-set entry omitted headers or rows")
        packets.append((name, raw_set["headers"], raw_set["rowSet"]))
    return packets


def _unknown_legacy_occurrences(
    raw_sets: object,
) -> tuple[NbaApiUnknownLegacyOccurrence, ...]:
    if isinstance(raw_sets, dict):
        entries = [raw_sets]
    elif isinstance(raw_sets, list):
        entries = raw_sets
    else:
        raise ResponseContractError(
            "unknown response legacy envelope must contain an object or list"
        )

    occurrences: list[NbaApiUnknownLegacyOccurrence] = []
    for provider_index, raw_set in enumerate(entries):
        if not isinstance(raw_set, dict):
            raise ResponseContractError("unknown response result occurrence must be an object")
        name = raw_set.get("name")
        raw_headers = raw_set.get("headers")
        raw_rows = raw_set.get("rowSet")
        if (
            not isinstance(name, str)
            or not name
            or name.strip() != name
            or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}", name) is None
        ):
            raise ResponseContractError("unknown response result occurrence name is malformed")
        if not isinstance(raw_headers, list) or any(
            not isinstance(header, str) or not header or header.strip() != header
            for header in raw_headers
        ):
            raise ResponseContractError("unknown response result headers are malformed")
        if not isinstance(raw_rows, list):
            raise ResponseContractError("unknown response result rows are malformed")
        headers = tuple(cast("str", header) for header in raw_headers)
        rows: list[tuple[NbaApiUnknownCell, ...]] = []
        normalized_rows: list[list[Any]] = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, list) or len(raw_row) != len(headers):
                raise ResponseContractError(
                    "unknown response result row width differs from its headers"
                )
            cells = tuple(
                NbaApiUnknownCell(
                    value_kind=_json_value_kind(value),
                    canonical_json=_canonical_json_value(value),
                )
                for value in raw_row
            )
            rows.append(cells)
            normalized_rows.append(raw_row)
        headers_sha256 = _headers_sha256(headers)
        receipt = ResultSetReceipt(
            name=name,
            provider_index=provider_index,
            canonical_index=None,
            headers_sha256=headers_sha256,
            row_count=len(rows),
            json_path=None,
            container_kind="nba_api_result_set",
            container_count=1,
            missing_count=0,
            null_count=0,
            parent_observation_count=1,
            parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
            observed_field_orders_sha256=headers_sha256,
            normalized_output_sha256=_normalized_output_sha256(headers, normalized_rows),
        )
        occurrences.append(
            NbaApiUnknownLegacyOccurrence(
                provider_index=provider_index,
                name=name,
                headers=headers,
                rows=tuple(rows),
                receipt=receipt,
            )
        )
    return tuple(occurrences)


def _parse_unknown_stats_payload(
    *,
    contract: NbaApiEndpointContract,
    endpoint_slug: str,
    parameters: Mapping[str, Any],
    payload: Mapping[str, Any],
    parser_input: str,
) -> NbaApiUnknownResponse:
    response_mode: NbaApiResponseModeContract = contract.response_contract
    if (
        response_mode.response_mode != "unknown_dynamic_response"
        or response_mode.endpoint_slug != endpoint_slug
        or response_mode.runtime_class_name != contract.runtime_class_name
        or response_mode.module_name != contract.module_name
    ):
        raise ResponseContractError("endpoint lacks exact unknown response-mode authority")

    # Reject non-finite or otherwise noncanonical JSON values even when the
    # provider decoder accepted them.  The exact parser bytes remain the body
    # authority; this digest is an independently reproducible structural tag.
    canonical_payload = _canonical_json_value(payload)
    roots = [name for name in ("resultSets", "resultSet") if name in payload]
    legacy_envelope_name: str | None = None
    occurrences: tuple[NbaApiUnknownLegacyOccurrence, ...] = ()
    state: UnknownResponseState
    if len(roots) > 1:
        raise ResponseContractError("unknown response contains ambiguous legacy envelopes")
    if roots:
        legacy_envelope_name = roots[0]
        occurrences = _unknown_legacy_occurrences(payload[legacy_envelope_name])
        state = (
            "legacy_present_nonempty"
            if any(item.receipt.row_count for item in occurrences)
            else "legacy_present_empty"
        )
    elif not payload:
        state = "missing_result_envelope"
    elif any(isinstance(value, dict | list) for value in payload.values()):
        state = "generic_nested_json"
    else:
        state = "unknown_result_envelope"

    return NbaApiUnknownResponse(
        endpoint_id=contract.runtime_class_name,
        endpoint_slug=endpoint_slug,
        parameters_sha256=canonical_parameters_sha256(parameters),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=endpoint_contract_sha256(contract),
        response_mode_authority_sha256=response_mode.authority_sha256,
        parser_input_sha256=hashlib.sha256(parser_input.encode("utf-8")).hexdigest(),
        canonical_payload_json=canonical_payload,
        canonical_payload_sha256=hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
        state=state,
        legacy_envelope_name=legacy_envelope_name,
        occurrences=occurrences,
    )


def _custom_data_sets(parser_input: str, endpoint_slug: str) -> list[tuple[str, object, object]]:
    """Run the pinned custom parser over the already-read immutable body."""

    immutable_response = NBAStatsResponse(parser_input, 200, "nbadb://immutable-parser-input")
    try:
        parsed = immutable_response.get_data_sets(endpoint_slug)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ResponseContractError("pinned custom parser rejected the response") from exc
    if not isinstance(parsed, dict):
        raise ResponseContractError("custom parser result must be a named mapping")

    packets: list[tuple[str, object, object]] = []
    for name, raw_set in parsed.items():
        if not isinstance(name, str) or not isinstance(raw_set, dict):
            raise ResponseContractError("custom parser returned an invalid result set")
        if "headers" not in raw_set or "data" not in raw_set:
            raise ResponseContractError("custom parser omitted headers or rows")
        packets.append((name, raw_set["headers"], raw_set["data"]))
    return packets


def _resolve_endpoint_contract(
    endpoint_cls: type,
    supplied: NbaApiEndpointContract | None,
) -> NbaApiEndpointContract:
    try:
        contract = pinned_endpoint_contract(endpoint_cls)
    except ValueError as exc:
        raise ResponseContractError("runtime endpoint lacks pinned nbadb authority") from exc
    if supplied is not None and supplied != contract:
        raise ResponseContractError(
            "supplied endpoint contract differs from pinned nbadb authority"
        )
    if (
        contract.runtime_class_name != endpoint_cls.__name__
        or contract.module_name != endpoint_cls.__module__
        or contract.endpoint_slug != getattr(endpoint_cls, "endpoint", None)
    ):
        raise ResponseContractError("runtime endpoint identity differs from pinned nbadb authority")
    try:
        _response_contract = contract.response_contract
    except ValueError as exc:
        raise ResponseContractError(
            "runtime endpoint response mode lacks pinned authority"
        ) from exc
    return contract


def _expected_result_sets(
    contract: NbaApiEndpointContract,
    endpoint_slug: str,
) -> list[tuple[str, tuple[str, ...]]]:
    if contract.endpoint_slug != endpoint_slug:
        raise ResponseContractError("provider response slug differs from pinned nbadb authority")
    expected: list[tuple[str, tuple[str, ...]]] = []
    for result_set in contract.result_sets:
        name = result_set.result_set_name
        if name is None:
            raise ResponseContractError("pinned nbadb result-set name is absent")
        headers = result_set.expected_columns
        if len(set(headers)) != len(headers):
            raise ResponseContractError("pinned nbadb contract contains duplicate columns")
        expected.append((name, headers))
    if not expected:
        raise ResponseContractError("pinned nbadb contract declares no result sets")
    return expected


def _strict_stats_packets(
    provider_sets: Sequence[tuple[str, object, object]],
    expected: Sequence[tuple[str, tuple[str, ...]]],
) -> tuple[tuple[NbaApiResultPacket, ...], tuple[ResultSetReceipt, ...]]:
    expected_names = [name for name, _headers in expected]
    provider_names = [name for name, _headers, _rows in provider_sets]
    if not provider_sets:
        raise ResponseContractError("provider returned no result sets")
    if len(set(provider_names)) != len(provider_names):
        raise ResponseContractError("provider returned duplicate result-set names")
    if set(provider_names) != set(expected_names):
        raise ResponseContractError(
            "provider result-set inventory differs from the endpoint contract"
        )
    by_name = {
        name: (index, raw_headers, raw_rows)
        for index, (name, raw_headers, raw_rows) in enumerate(provider_sets)
    }
    packets: list[NbaApiResultPacket] = []
    result_receipts: list[ResultSetReceipt] = []
    for canonical_index, (name, expected_headers) in enumerate(expected):
        provider_index, raw_headers, raw_rows = by_name[name]
        headers = _flatten_headers(raw_headers)
        if headers != expected_headers:
            raise ResponseContractError("provider columns differ from the endpoint contract")
        rows = _validated_rows(raw_rows, len(headers))
        packets.append(
            NbaApiResultPacket(
                name=name,
                provider_index=provider_index,
                canonical_index=canonical_index,
                headers=headers,
                frame=rows_to_polars(headers, rows),
            )
        )
        result_receipts.append(
            ResultSetReceipt(
                name=name,
                provider_index=provider_index,
                canonical_index=canonical_index,
                headers_sha256=_headers_sha256(headers),
                row_count=len(rows),
                json_path=None,
                container_kind="nba_api_result_set",
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
                observed_field_orders_sha256=_headers_sha256(headers),
                normalized_output_sha256=_normalized_output_sha256(headers, rows),
            )
        )
    return tuple(packets), tuple(result_receipts)


def _safe_known_packets_during_fallback(
    provider_sets: Sequence[tuple[str, object, object]],
    expected: Sequence[tuple[str, tuple[str, ...]]],
) -> tuple[NbaApiResultPacket, ...]:
    """Return wide packets only when every pinned route is independently exact."""

    by_name: dict[str, list[tuple[int, object, object]]] = {}
    for provider_index, (name, raw_headers, raw_rows) in enumerate(provider_sets):
        by_name.setdefault(name, []).append((provider_index, raw_headers, raw_rows))
    packets: list[NbaApiResultPacket] = []
    try:
        for canonical_index, (name, expected_headers) in enumerate(expected):
            occurrences = by_name.get(name, [])
            if len(occurrences) != 1:
                return ()
            provider_index, raw_headers, raw_rows = occurrences[0]
            headers = _flatten_headers(raw_headers)
            if headers != expected_headers:
                return ()
            rows = _validated_rows(raw_rows, len(headers))
            packets.append(
                NbaApiResultPacket(
                    name=name,
                    provider_index=provider_index,
                    canonical_index=canonical_index,
                    headers=headers,
                    frame=rows_to_polars(headers, rows),
                )
            )
    except ResponseContractError:
        return ()
    return tuple(packets)


def _parse_stats_packets(
    response: object,
    *,
    endpoint_slug: str,
    contract: NbaApiEndpointContract,
    parser_input: str | None = None,
) -> tuple[NbaApiResultPackets, tuple[ResultSetReceipt, ...]]:
    """Run strict-known parsing with a deterministic successful-drift fallback."""

    if parser_input is None:
        parser_input = _response_parser_input(response)
    payload = _validated_response_dict(response, parser_input=parser_input)
    provider_sets = (
        _custom_data_sets(parser_input, endpoint_slug)
        if contract.parser_kind == "custom_nested"
        else _legacy_data_sets(payload)
    )
    expected = _expected_result_sets(contract, endpoint_slug)
    try:
        packets, receipts = _strict_stats_packets(provider_sets, expected)
    except ResponseContractError as strict_error:
        try:
            reasons, per_set_reasons = _result_set_fallback_anomalies(
                provider_sets,
                expected,
            )
            if not reasons:
                reasons.add("unrepresentable_typed_frame")
            frame, receipts = _fallback_frame(
                endpoint_slug=endpoint_slug,
                provider_sets=provider_sets,
                expected=expected,
                reasons=reasons,
                per_set_reasons=per_set_reasons,
            )
        except ResponseContractError as fallback_error:
            raise strict_error from fallback_error
        fallback = NbaApiLosslessFallback(
            endpoint_slug=endpoint_slug,
            reason_codes=tuple(sorted(reasons)),
            provider_result_set_count=len(provider_sets),
            expected_result_set_count=len(expected),
            result_set_receipts=receipts,
            frame=frame,
        )
        safe_packets = _safe_known_packets_during_fallback(provider_sets, expected)
        return (
            NbaApiResultPackets(safe_packets, lossless_fallback=fallback),
            receipts,
        )
    return NbaApiResultPackets(packets), receipts


def _validate_capture_contract(
    capture: NbaApiCaptureContract | None,
    endpoint_contract: NbaApiEndpointContract,
) -> str:
    digest = endpoint_contract_sha256(endpoint_contract)
    if capture is not None:
        expected_provider_digest = expected_nba_api_provider_authority()["authority_sha256"]
        if (
            capture.provider_authority_sha256 != expected_provider_digest
            or capture.endpoint_contract_sha256 != digest
        ):
            raise ResponseContractError(
                "capture authority differs from the pinned endpoint contract"
            )
    return digest


def _stats_request_contract(
    endpoint_cls: type,
    kwargs: Mapping[str, Any],
) -> tuple[str, dict[str, Any], object, dict[str, str], object]:
    """Resolve the owned declaration inputs without performing transport."""

    try:
        endpoint = endpoint_cls(get_request=False, **dict(kwargs))
    except TypeError as exc:
        raise ResponseContractError("endpoint declaration rejected controlled invocation") from exc
    endpoint_slug = getattr(endpoint, "endpoint", None)
    parameters = getattr(endpoint, "parameters", None)
    if not isinstance(endpoint_slug, str) or not endpoint_slug:
        raise ResponseContractError("endpoint declaration omitted its slug")
    if not isinstance(parameters, dict):
        raise ResponseContractError("endpoint declaration omitted its parameter mapping")
    supplied_headers = getattr(endpoint, "headers", None)
    return (
        endpoint_slug,
        parameters,
        getattr(endpoint, "proxy", None),
        _ordered_headers(supplied_headers, NbaDbStatsHTTP.headers),
        getattr(endpoint, "timeout", None),
    )


def _load_owned_replay_attempt(
    source: ParserInputReplaySource,
    receipt_sha256: str,
    *,
    source_family: str,
    transport_kind: str,
    endpoint_id: str,
    endpoint_slug: str,
    parameters: Mapping[str, Any],
    endpoint_contract_sha256: str,
) -> RecordedParserInput:
    """Verify a recorded attempt against independently resolved runtime authority."""

    attempt = source.load_recorded_attempt(receipt_sha256)
    expected_provider = expected_nba_api_provider_authority()["authority_sha256"]
    expected_representation = (
        STATIC_INPUT_REPRESENTATION
        if transport_kind == "static_provider_snapshot"
        else PARSER_INPUT_REPRESENTATION
    )
    if (
        attempt.receipt_sha256 != receipt_sha256
        or attempt.source_family != source_family
        or attempt.transport_kind != transport_kind
        or attempt.endpoint_id != endpoint_id
        or attempt.endpoint_slug != endpoint_slug
        or attempt.parameters_sha256 != canonical_parameters_sha256(parameters)
        or attempt.provider_authority_sha256 != expected_provider
        or attempt.endpoint_contract_sha256 != endpoint_contract_sha256
        or attempt.captured.representation != expected_representation
    ):
        raise ResponseContractError("recorded attempt differs from the pinned provider contract")
    parser_input_sha256 = hashlib.sha256(attempt.parser_input).hexdigest()
    parser_object_sha256 = hashlib.sha256(
        attempt.captured.representation.encode("ascii") + b"\0" + attempt.parser_input
    ).hexdigest()
    if (
        len(attempt.parser_input) != attempt.captured.uncompressed_bytes
        or parser_input_sha256 != attempt.captured.response_sha256
        or parser_object_sha256 != attempt.captured.object_sha256
    ):
        raise ResponseContractError("recorded parser input differs from its body authority")
    if attempt.outcome not in {"success_nonempty", "success_empty"}:
        raise ResponseContractError("recorded attempt is not a successful parser input")
    if transport_kind == "http_response" and (
        attempt.status_code is None or not 200 <= attempt.status_code < 300
    ):
        raise ResponseContractError("recorded HTTP attempt is not a successful response")
    if transport_kind == "static_provider_snapshot" and attempt.status_code is not None:
        raise ResponseContractError("recorded static attempt contains an HTTP status")
    return attempt


def _replay_response_text(attempt: RecordedParserInput) -> str:
    try:
        return attempt.parser_input.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ResponseContractError("recorded parser input is not valid UTF-8") from exc


def _verify_replayed_result_sets(
    attempt: RecordedParserInput,
    result_sets: Sequence[ResultSetReceipt],
) -> None:
    observed = tuple(result_sets)
    observed_outcome = (
        "success_nonempty" if any(item.row_count for item in observed) else "success_empty"
    )
    if observed != attempt.result_sets or observed_outcome != attempt.outcome:
        raise ResponseContractError("replayed result-set receipts differ from the recorded attempt")


def _verify_replayed_unknown_response(
    attempt: RecordedParserInput,
    response: NbaApiUnknownResponse,
) -> None:
    if (
        response.result_set_receipts != attempt.result_sets
        or response.outcome != attempt.outcome
        or response.parser_input_sha256 != attempt.captured.response_sha256
        or response.endpoint_id != attempt.endpoint_id
        or response.endpoint_slug != attempt.endpoint_slug
        or response.parameters_sha256 != attempt.parameters_sha256
        or response.provider_authority_sha256 != attempt.provider_authority_sha256
        or response.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
    ):
        raise ResponseContractError("replayed unknown response differs from its recorded authority")


def _request_stats_response(
    endpoint_cls: type,
    kwargs: Mapping[str, Any],
    *,
    capture: NbaApiCaptureContract | None,
) -> tuple[
    str,
    object,
    dict[str, Any],
    CapturedParserInput | None,
    str,
    ParserInputContext | None,
]:
    endpoint_slug, parameters, proxy, headers, timeout = _stats_request_contract(
        endpoint_cls, kwargs
    )
    request_context = capture.begin_request() if capture is not None else None
    try:
        response = NbaDbStatsHTTP().send_api_request(
            endpoint=endpoint_slug,
            parameters=parameters,
            proxy=proxy,
            headers=headers,
            timeout=timeout,
        )
    except Exception as exc:
        _record_no_response_failure(
            capture=capture,
            source_family="stats",
            endpoint_id=endpoint_cls.__name__,
            endpoint_slug=endpoint_slug,
            parameters=parameters,
            context=request_context,
            exc=exc,
        )
        raise
    captured, parser_input = _capture_response(response, capture)
    return endpoint_slug, response, parameters, captured, parser_input, request_context


def fetch_stats_payload(
    endpoint_cls: type,
    *,
    capture: NbaApiCaptureContract | None = None,
    endpoint_contract: NbaApiEndpointContract | None = None,
    **kwargs: Any,
) -> NbaApiPayload:
    """Execute one stats request and return a validated JSON object."""

    owned_contract = _resolve_endpoint_contract(endpoint_cls, endpoint_contract)
    contract_digest = _validate_capture_contract(capture, owned_contract)

    (
        endpoint_slug,
        response,
        parameters,
        captured,
        parser_input,
        request_context,
    ) = _request_stats_response(
        endpoint_cls,
        kwargs,
        capture=capture,
    )
    unknown_response: NbaApiUnknownResponse | None = None
    try:
        payload = _validated_response_dict(response, parser_input=parser_input)
        if owned_contract.response_mode == "unknown_dynamic_response":
            unknown_response = _parse_unknown_stats_payload(
                contract=owned_contract,
                endpoint_slug=endpoint_slug,
                parameters=parameters,
                payload=payload,
                parser_input=parser_input,
            )
    except Exception as exc:
        _record_response_failure(
            capture=capture,
            captured=captured,
            response=response,
            source_family="stats",
            endpoint_id=endpoint_cls.__name__,
            endpoint_slug=endpoint_slug,
            parameters=parameters,
            context=request_context,
            exc=exc,
        )
        raise
    receipt: str | None = None
    if capture is not None:
        if captured is None:
            raise ResponseContractError("provider response capture is required")
        if request_context is None:
            raise ResponseContractError("provider response omitted its request context")
        result_set_receipts = (
            unknown_response.result_set_receipts if unknown_response is not None else ()
        )
        outcome: Outcome = (
            unknown_response.outcome
            if unknown_response is not None
            else ("success_nonempty" if payload else "success_empty")
        )
        receipt = capture.sink.record_response_attempt(
            context=request_context,
            transport_kind="http_response",
            source_family="stats",
            endpoint_id=endpoint_cls.__name__,
            endpoint_slug=endpoint_slug,
            parameters=parameters,
            provider_authority_sha256=capture.provider_authority_sha256,
            contract_sha256=capture.endpoint_contract_sha256,
            status_code=_response_status(response),
            captured=captured,
            outcome=outcome,
            failure_class=None,
            root_exception_class=None,
            result_sets=result_set_receipts,
        )
        capture.record_receipt(request_context, receipt, successful=True)
        if unknown_response is not None:
            unknown_response = unknown_response.bind_response_receipt(receipt)
    return NbaApiPayload(
        payload,
        response_receipt_sha256=receipt,
        provider_authority_sha256=(capture.provider_authority_sha256 if capture else None),
        endpoint_contract_sha256=contract_digest,
        result_set_receipts=(
            unknown_response.result_set_receipts if unknown_response is not None else ()
        ),
        unknown_response=unknown_response,
    )


def fetch_stats_packets(
    endpoint_cls: type,
    *,
    capture: NbaApiCaptureContract | None = None,
    endpoint_contract: NbaApiEndpointContract | None = None,
    **kwargs: Any,
) -> NbaApiResultPackets:
    """Execute one stats request and return tuple-compatible owned packets."""

    owned_contract = _resolve_endpoint_contract(endpoint_cls, endpoint_contract)
    owned_contract_sha256 = _validate_capture_contract(capture, owned_contract)

    (
        endpoint_slug,
        response,
        parameters,
        captured,
        parser_input,
        request_context,
    ) = _request_stats_response(
        endpoint_cls,
        kwargs,
        capture=capture,
    )
    unknown_response: NbaApiUnknownResponse | None = None
    try:
        if owned_contract.response_mode == "unknown_dynamic_response":
            payload = _validated_response_dict(response, parser_input=parser_input)
            unknown_response = _parse_unknown_stats_payload(
                contract=owned_contract,
                endpoint_slug=endpoint_slug,
                parameters=parameters,
                payload=payload,
                parser_input=parser_input,
            )
            result_receipts = unknown_response.result_set_receipts
            packets = NbaApiResultPackets((), unknown_response=unknown_response)
        else:
            packets, result_receipts = _parse_stats_packets(
                response,
                endpoint_slug=endpoint_slug,
                contract=owned_contract,
                parser_input=parser_input,
            )
    except Exception as exc:
        _record_response_failure(
            capture=capture,
            captured=captured,
            response=response,
            source_family="stats",
            endpoint_id=endpoint_cls.__name__,
            endpoint_slug=endpoint_slug,
            parameters=parameters,
            context=request_context,
            exc=exc,
        )
        raise

    if capture is not None:
        if captured is None:
            raise ResponseContractError("provider response capture is required")
        if request_context is None:
            raise ResponseContractError("provider response omitted its request context")
        response_receipt_sha256 = capture.sink.record_response_attempt(
            context=request_context,
            transport_kind="http_response",
            source_family="stats",
            endpoint_id=endpoint_cls.__name__,
            endpoint_slug=endpoint_slug,
            parameters=parameters,
            provider_authority_sha256=capture.provider_authority_sha256,
            contract_sha256=capture.endpoint_contract_sha256,
            status_code=_response_status(response),
            captured=captured,
            outcome=(
                unknown_response.outcome
                if unknown_response is not None
                else (
                    "success_nonempty"
                    if any(result_set.row_count for result_set in result_receipts)
                    else "success_empty"
                )
            ),
            failure_class=None,
            root_exception_class=None,
            result_sets=result_receipts,
        )
        capture.record_receipt(
            request_context,
            response_receipt_sha256,
            successful=True,
        )
        if unknown_response is not None:
            unknown_response = unknown_response.bind_response_receipt(response_receipt_sha256)
        packets = NbaApiResultPackets(
            tuple(
                replace(
                    packet,
                    response_receipt_sha256=response_receipt_sha256,
                    provider_authority_sha256=capture.provider_authority_sha256,
                    endpoint_contract_sha256=owned_contract_sha256,
                )
                for packet in packets
            ),
            lossless_fallback=(
                packets.lossless_fallback.bind_response_receipt(response_receipt_sha256)
                if packets.lossless_fallback is not None
                else None
            ),
            unknown_response=unknown_response,
        )
    return packets


def replay_stats_packets(
    source: ParserInputReplaySource,
    response_receipt_sha256: str,
    endpoint_cls: type,
    *,
    endpoint_contract: NbaApiEndpointContract | None = None,
    **kwargs: Any,
) -> NbaApiResultPackets:
    """Replay one recorded stats response through the owned parser without transport."""

    contract = _resolve_endpoint_contract(endpoint_cls, endpoint_contract)
    contract_digest = endpoint_contract_sha256(contract)
    endpoint_slug, parameters, _proxy, _headers, _timeout = _stats_request_contract(
        endpoint_cls, kwargs
    )
    attempt = _load_owned_replay_attempt(
        source,
        response_receipt_sha256,
        source_family="stats",
        transport_kind="http_response",
        endpoint_id=endpoint_cls.__name__,
        endpoint_slug=endpoint_slug,
        parameters=parameters,
        endpoint_contract_sha256=contract_digest,
    )
    parser_input = _replay_response_text(attempt)
    response = NBAStatsResponse(
        parser_input,
        cast("int", attempt.status_code),
        "private-bronze://stats-replay",
    )
    unknown_response: NbaApiUnknownResponse | None = None
    if contract.response_mode == "unknown_dynamic_response":
        payload = _validated_response_dict(response, parser_input=parser_input)
        unknown_response = _parse_unknown_stats_payload(
            contract=contract,
            endpoint_slug=endpoint_slug,
            parameters=parameters,
            payload=payload,
            parser_input=parser_input,
        )
        _verify_replayed_unknown_response(attempt, unknown_response)
        unknown_response = unknown_response.bind_response_receipt(attempt.receipt_sha256)
        packets = NbaApiResultPackets((), unknown_response=unknown_response)
    else:
        packets, result_sets = _parse_stats_packets(
            response,
            endpoint_slug=endpoint_slug,
            contract=contract,
            parser_input=parser_input,
        )
        _verify_replayed_result_sets(attempt, result_sets)
    return NbaApiResultPackets(
        tuple(
            replace(
                packet,
                response_receipt_sha256=attempt.receipt_sha256,
                provider_authority_sha256=attempt.provider_authority_sha256,
                endpoint_contract_sha256=attempt.endpoint_contract_sha256,
            )
            for packet in packets
        ),
        lossless_fallback=(
            packets.lossless_fallback.bind_response_receipt(attempt.receipt_sha256)
            if packets.lossless_fallback is not None
            else None
        ),
        unknown_response=unknown_response,
    )


def replay_stats_payload(
    source: ParserInputReplaySource,
    response_receipt_sha256: str,
    endpoint_cls: type,
    *,
    endpoint_contract: NbaApiEndpointContract | None = None,
    **kwargs: Any,
) -> NbaApiPayload:
    """Replay one payload-only stats response without performing transport."""

    contract = _resolve_endpoint_contract(endpoint_cls, endpoint_contract)
    contract_digest = endpoint_contract_sha256(contract)
    endpoint_slug, parameters, _proxy, _headers, _timeout = _stats_request_contract(
        endpoint_cls, kwargs
    )
    attempt = _load_owned_replay_attempt(
        source,
        response_receipt_sha256,
        source_family="stats",
        transport_kind="http_response",
        endpoint_id=endpoint_cls.__name__,
        endpoint_slug=endpoint_slug,
        parameters=parameters,
        endpoint_contract_sha256=contract_digest,
    )
    parser_input = _replay_response_text(attempt)
    response = NBAStatsResponse(
        parser_input,
        cast("int", attempt.status_code),
        "private-bronze://stats-payload-replay",
    )
    payload = _validated_response_dict(response, parser_input=parser_input)
    unknown_response: NbaApiUnknownResponse | None = None
    if contract.response_mode == "unknown_dynamic_response":
        unknown_response = _parse_unknown_stats_payload(
            contract=contract,
            endpoint_slug=endpoint_slug,
            parameters=parameters,
            payload=payload,
            parser_input=parser_input,
        )
        _verify_replayed_unknown_response(attempt, unknown_response)
        unknown_response = unknown_response.bind_response_receipt(attempt.receipt_sha256)
    else:
        expected_outcome = "success_nonempty" if payload else "success_empty"
        if attempt.result_sets or attempt.outcome != expected_outcome:
            raise ResponseContractError(
                "replayed payload receipt differs from the recorded attempt"
            )
    return NbaApiPayload(
        payload,
        response_receipt_sha256=attempt.receipt_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256=attempt.endpoint_contract_sha256,
        result_set_receipts=(
            unknown_response.result_set_receipts if unknown_response is not None else ()
        ),
        unknown_response=unknown_response,
    )


def _resolve_static_contract(dataset_id: str) -> StaticDatasetContract:
    try:
        contract = pinned_static_dataset_contract(dataset_id)
    except ValueError as exc:
        raise ResponseContractError("static dataset lacks pinned nbadb authority") from exc
    if (
        contract.source_family != "static"
        or contract.dataset_id != dataset_id
        or contract.model_disposition != "defined_and_implemented"
        or contract.implementation_status != "complete"
    ):
        raise ResponseContractError("static dataset is not an implemented league snapshot")
    return contract


def _validate_static_capture_contract(
    capture: NbaApiCaptureContract | None,
    contract: StaticDatasetContract,
) -> str:
    digest = owned_contract_sha256(contract)
    if capture is not None:
        expected_provider_digest = expected_nba_api_provider_authority()["authority_sha256"]
        if (
            capture.provider_authority_sha256 != expected_provider_digest
            or capture.endpoint_contract_sha256 != digest
        ):
            raise ResponseContractError("capture authority differs from the pinned static contract")
    return digest


def _record_static_failure(
    *,
    capture: NbaApiCaptureContract | None,
    contract: StaticDatasetContract,
    context: ParserInputContext | None,
    captured: CapturedParserInput | None,
    exc: Exception,
) -> str | None:
    if capture is None:
        return None
    if context is None:
        raise ResponseContractError("static provider omitted its capture context") from exc
    outcome, failure_class = _failure_receipt_contract(exc)
    if captured is None:
        receipt = capture.sink.record_no_response_attempt(
            context=context,
            transport_kind="static_provider_snapshot",
            source_family="static",
            endpoint_id=contract.dataset_id,
            endpoint_slug=contract.source_symbol,
            parameters={},
            provider_authority_sha256=capture.provider_authority_sha256,
            contract_sha256=capture.endpoint_contract_sha256,
            outcome=outcome,
            failure_class=failure_class,
            root_exception_class=_root_exception_class(exc),
        )
    else:
        receipt = capture.sink.record_response_attempt(
            context=context,
            transport_kind="static_provider_snapshot",
            source_family="static",
            endpoint_id=contract.dataset_id,
            endpoint_slug=contract.source_symbol,
            parameters={},
            provider_authority_sha256=capture.provider_authority_sha256,
            contract_sha256=capture.endpoint_contract_sha256,
            status_code=None,
            captured=captured,
            outcome=outcome,
            failure_class=failure_class,
            root_exception_class=_root_exception_class(exc),
            result_sets=(),
        )
    capture.record_receipt(context, receipt, successful=False)
    return receipt


def _static_source_rows(contract: StaticDatasetContract) -> list[list[Any]]:
    try:
        data_module = importlib.import_module("nba_api.stats.library.data")
        source_rows = getattr(data_module, contract.source_symbol)
    except (AttributeError, ImportError) as exc:
        raise ResponseContractError("static provider source is unavailable") from exc
    if not isinstance(source_rows, list) or any(not isinstance(row, list) for row in source_rows):
        raise ResponseContractError("static provider source must be a list of row lists")
    return copy.deepcopy(cast("list[list[Any]]", source_rows))


def _validate_static_rows(
    contract: StaticDatasetContract,
    source_rows: list[list[Any]],
) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
    headers = tuple(field.name for field in contract.raw_fields)
    rows: list[tuple[Any, ...]] = []
    for source_row in source_rows:
        if len(source_row) != len(headers):
            raise ResponseContractError("static provider row width differs from pinned authority")
        for field_contract, value in zip(contract.raw_fields, source_row, strict=True):
            if type(value).__name__ != field_contract.sample_type:
                raise ResponseContractError(
                    "static provider value type differs from pinned authority"
                )
        rows.append(tuple(source_row))

    raw_records = [dict(zip(headers, row, strict=True)) for row in rows]
    projected_records = [
        {field: record[field] for field in contract.projected_fields} for record in raw_records
    ]
    identifiers = [record["id"] for record in raw_records]
    if (
        len(source_rows) != contract.row_count
        or len(set(identifiers)) != contract.unique_id_count
        or any(
            isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0
            for identifier in identifiers
        )
        or _canonical_value_sha256(source_rows) != contract.source_rows_sha256
        or _canonical_value_sha256(raw_records) != contract.raw_records_sha256
        or _canonical_value_sha256(projected_records) != contract.projected_records_sha256
    ):
        raise ResponseContractError("static provider content differs from pinned authority")
    return headers, tuple(rows)


def _parse_static_packet(
    contract: StaticDatasetContract,
    source_rows: list[list[Any]],
) -> tuple[NbaApiResultPacket, ResultSetReceipt]:
    """Run the shared pure static snapshot-to-packet contract path."""

    headers, rows = _validate_static_rows(contract, source_rows)
    result_name = f"{contract.source_symbol}_shape_1"
    result_set = ResultSetReceipt(
        name=result_name,
        provider_index=0,
        canonical_index=0,
        headers_sha256=_headers_sha256(headers),
        row_count=len(rows),
        json_path=None,
        container_kind="nba_api_static_records",
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_observation_count=1,
        parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
        observed_field_orders_sha256=_headers_sha256(headers),
        normalized_output_sha256=_normalized_output_sha256(headers, rows),
    )
    return (
        NbaApiResultPacket(
            name=result_name,
            provider_index=0,
            canonical_index=0,
            headers=headers,
            frame=rows_to_polars(headers, rows),
        ),
        result_set,
    )


def fetch_static_packet(
    dataset_id: str,
    *,
    capture: NbaApiCaptureContract | None = None,
) -> NbaApiResultPacket:
    """Return one exact pinned static snapshot captured before provider projection."""

    contract = _resolve_static_contract(dataset_id)
    contract_digest = _validate_static_capture_contract(capture, contract)
    request_context = capture.begin_request() if capture is not None else None
    captured: CapturedParserInput | None = None
    try:
        source_rows = _static_source_rows(contract)
        if capture is not None:
            captured = capture.sink.store_static_records(source_rows)
        packet, result_set = _parse_static_packet(contract, source_rows)
    except Exception as exc:
        error = (
            exc
            if isinstance(exc, ResponseContractError)
            else ResponseContractError("static provider snapshot could not be parsed")
        )
        _record_static_failure(
            capture=capture,
            contract=contract,
            context=request_context,
            captured=captured,
            exc=error,
        )
        if error is exc:
            raise
        raise error from exc

    receipt: str | None = None
    if capture is not None:
        if captured is None or request_context is None:
            raise ResponseContractError("static provider snapshot was not captured")
        receipt = capture.sink.record_static_snapshot_attempt(
            context=request_context,
            endpoint_id=contract.dataset_id,
            endpoint_slug=contract.source_symbol,
            provider_authority_sha256=capture.provider_authority_sha256,
            contract_sha256=contract_digest,
            captured=captured,
            result_set=result_set,
        )
        capture.record_receipt(request_context, receipt, successful=True)
    return replace(
        packet,
        response_receipt_sha256=receipt,
        provider_authority_sha256=(capture.provider_authority_sha256 if capture else None),
        endpoint_contract_sha256=contract_digest,
    )


def replay_static_packet(
    source: ParserInputReplaySource,
    response_receipt_sha256: str,
    dataset_id: str,
) -> NbaApiResultPacket:
    """Replay one recorded static snapshot without importing the provider data module."""

    contract = _resolve_static_contract(dataset_id)
    contract_digest = owned_contract_sha256(contract)
    attempt = _load_owned_replay_attempt(
        source,
        response_receipt_sha256,
        source_family="static",
        transport_kind="static_provider_snapshot",
        endpoint_id=contract.dataset_id,
        endpoint_slug=contract.source_symbol,
        parameters={},
        endpoint_contract_sha256=contract_digest,
    )
    raw_text = _replay_response_text(attempt)
    try:
        source_rows = json.loads(
            raw_text,
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResponseContractError("recorded static parser input is malformed JSON") from exc
    if (
        not isinstance(source_rows, list)
        or any(not isinstance(row, list) for row in source_rows)
        or json.dumps(
            source_rows,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        != raw_text
    ):
        raise ResponseContractError("recorded static parser input is not canonical row JSON")
    packet, result_set = _parse_static_packet(
        contract,
        cast("list[list[Any]]", source_rows),
    )
    _verify_replayed_result_sets(attempt, (result_set,))
    return replace(
        packet,
        response_receipt_sha256=attempt.receipt_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256=attempt.endpoint_contract_sha256,
    )


def _json_root(payload: Mapping[str, Any], root: str) -> Any:
    if not root.startswith("$."):
        raise ResponseContractError("live packet contract contains an invalid JSON root")
    value: Any = payload
    for part in root[2:].split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ResponseContractError("live response omitted a required JSON root")
        value = value[part]
    return value


def _live_headers_sha256(headers: Mapping[str, str]) -> str:
    encoded = json.dumps(
        [[key, value] for key, value in headers.items()],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_live_contract(endpoint_cls: type) -> LiveEndpointContract:
    try:
        contract = pinned_live_endpoint_contract(endpoint_cls)
    except ValueError as exc:
        raise ResponseContractError("live endpoint lacks pinned nbadb authority") from exc
    if (
        contract.base_url != getattr(NbaDbLiveHTTP, "base_url", None)
        or tuple(NbaDbLiveHTTP.headers) != contract.ordered_header_names
        or _live_headers_sha256(NbaDbLiveHTTP.headers) != contract.ordered_headers_sha256
    ):
        raise ResponseContractError("live HTTP runtime differs from pinned nbadb authority")
    runtime_expected = getattr(endpoint_cls, "expected_data", None)
    if not isinstance(runtime_expected, Mapping) or tuple(runtime_expected) != (
        contract.envelope_root_order
    ):
        raise ResponseContractError("live envelope roots differ from pinned nbadb authority")
    return contract


def _live_request_contract(
    contract: LiveEndpointContract,
    kwargs: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if "get_request" in kwargs:
        raise ResponseContractError("live get_request policy is adapter-owned")
    transport_names = {"proxy", "headers", "timeout"}
    domain_values = {key: value for key, value in kwargs.items() if key not in transport_names}
    parameter_names = {parameter.name for parameter in contract.parameters}
    if set(domain_values) - parameter_names:
        raise ResponseContractError("live request contains an unknown domain parameter")

    effective: dict[str, Any] = {}
    receipt_parameters: dict[str, Any] = {}
    for parameter in contract.parameters:
        if parameter.name in domain_values:
            value = domain_values[parameter.name]
        elif parameter.has_default:
            value = parameter.default
        else:
            raise ResponseContractError("live request omitted a required domain parameter")
        if value is None and not parameter.nullable:
            raise ResponseContractError("live request contains a non-nullable null parameter")
        if parameter.pattern is not None and (
            not isinstance(value, str) or re.fullmatch(parameter.pattern, value) is None
        ):
            raise ResponseContractError("live request parameter violates its pinned pattern")
        effective[parameter.name] = value
        receipt_parameters[parameter.query_name] = value

    transport = {key: kwargs[key] for key in transport_names if key in kwargs}
    return effective, transport, receipt_parameters


def _live_endpoint_declaration(
    endpoint_cls: type,
    contract: LiveEndpointContract,
    domain_parameters: Mapping[str, Any],
    transport_parameters: Mapping[str, Any],
) -> tuple[object, str, dict[str, str]]:
    """Resolve the owned live declaration inputs without performing transport."""

    try:
        endpoint = endpoint_cls(
            get_request=False,
            **dict(domain_parameters),
            **dict(transport_parameters),
        )
    except TypeError as exc:
        raise ResponseContractError("live endpoint rejected controlled invocation") from exc
    try:
        endpoint_url = contract.endpoint_url_template.format(**domain_parameters)
    except (KeyError, ValueError) as exc:
        raise ResponseContractError("live endpoint URL could not be resolved") from exc
    supplied_headers = getattr(endpoint, "headers", None)
    return endpoint, endpoint_url, _ordered_headers(supplied_headers, NbaDbLiveHTTP.headers)


def _selected_live_result_sets(
    contract: LiveEndpointContract,
    packet_result_sets: Mapping[str, str],
) -> tuple[tuple[str, LiveResultSetContract], ...]:
    if not packet_result_sets:
        raise ResponseContractError("live request selected no result sets")
    by_name = {result_set.name: result_set for result_set in contract.result_sets}
    selected: list[tuple[str, LiveResultSetContract]] = []
    seen: set[str] = set()
    for output_name, result_set_name in packet_result_sets.items():
        if not isinstance(output_name, str) or not output_name:
            raise ResponseContractError("live output name is invalid")
        result_set = by_name.get(result_set_name)
        if result_set is None:
            raise ResponseContractError(
                "requested live result set is absent from pinned nbadb authority"
            )
        if result_set.name in seen:
            raise ResponseContractError("live result set was selected more than once")
        if "*" in result_set.traversal_path:
            raise ResponseContractError("nested wildcard live result sets require bronze replay")
        seen.add(result_set.name)
        selected.append((output_name, result_set))
    return tuple(selected)


def _json_value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    raise ResponseContractError("live result set contains a non-JSON value")


def _validate_live_field_value(field: object, value: object) -> None:
    field_contract = cast("Any", field)
    value_type = _json_value_type(value)
    allowed = set(field_contract.sample_types)
    if value_type == "null" and field_contract.nullable:
        return
    if value_type == "integer" and "number" in allowed:
        return
    if value_type not in allowed:
        raise ResponseContractError("live field value type differs from pinned authority")


def _validate_live_result_container(
    result_set: LiveResultSetContract,
    value: object,
    child_field_names: set[str],
    *,
    allow_additive_drift: bool,
) -> tuple[tuple[object, ...], tuple[str, ...]]:
    if result_set.container_kind == "nba_api_live_json_array":
        if not isinstance(value, list):
            raise ResponseContractError("live result set must be an array")
        records = tuple(value)
    elif result_set.container_kind == "nba_api_live_json_object":
        if not isinstance(value, Mapping):
            raise ResponseContractError("live result set must be an object")
        records = (value,)
    else:
        raise ResponseContractError("live result set has an unsupported container contract")

    scalar_projection = (
        len(result_set.fields) == 1
        and not result_set.fields[0].source_field
        and result_set.fields[0].name == "value"
    )
    if scalar_projection:
        for item in records:
            _validate_live_field_value(result_set.fields[0], item)
        return records, ()

    allowed_fields = {field.name for field in result_set.fields}
    allowed_fields.update(child_field_names)
    required_fields = {
        field.name for field in result_set.fields if field.key_presence == "required"
    }
    anomaly_codes: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ResponseContractError("live result set must contain only objects")
        if any(not isinstance(key, str) for key in record):
            raise ResponseContractError("live result-set object contains a non-string field")
        unknown = set(record) - allowed_fields
        if unknown:
            if not allow_additive_drift:
                raise ResponseContractError("live result set contains additive unclassified fields")
            anomaly_codes.add("additive_field")
        if required_fields - set(record):
            raise ResponseContractError("live result set omitted required fields")
        fields_by_name = {field.name: field for field in result_set.fields}
        for name, item in record.items():
            field = fields_by_name.get(name)
            if field is not None:
                _validate_live_field_value(field, item)
    return records, tuple(sorted(anomaly_codes))


@dataclass(frozen=True, slots=True)
class _LiveResultObservation:
    containers: tuple[object, ...]
    rows: tuple[object, ...]
    parent_occurrence_states: tuple[str, ...]

    @property
    def missing_count(self) -> int:
        return self.parent_occurrence_states.count("missing")

    @property
    def null_count(self) -> int:
        return self.parent_occurrence_states.count("null")

    @property
    def parent_occurrence_states_sha256(self) -> str:
        return parent_occurrence_states_digest(self.parent_occurrence_states)

    @property
    def observed_field_orders_sha256(self) -> str:
        return _observed_field_orders_sha256(self.rows)

    @property
    def normalized_output_sha256(self) -> str:
        return _canonical_value_sha256(
            {
                "containers": list(self.containers),
                "missing_count": self.missing_count,
                "null_count": self.null_count,
            }
        )


def _validate_live_envelope(
    endpoint_contract: LiveEndpointContract,
    payload: Mapping[str, Any],
    *,
    allow_additive_drift: bool,
) -> tuple[dict[str, _LiveResultObservation], tuple[str, ...]]:
    observations: dict[str, _LiveResultObservation] = {}
    anomaly_codes: set[str] = set()
    expected_roots = endpoint_contract.envelope_root_order
    actual_roots = tuple(payload)
    missing_roots = set(expected_roots) - set(actual_roots)
    if missing_roots:
        raise ResponseContractError("live response omitted a required envelope root")
    additive_roots = set(actual_roots) - set(expected_roots)
    known_root_order = tuple(root for root in actual_roots if root in expected_roots)
    if additive_roots:
        if not allow_additive_drift:
            raise ResponseContractError("live response envelope roots differ from pinned authority")
        anomaly_codes.add("additive_envelope_root")
    if known_root_order != expected_roots:
        if not allow_additive_drift:
            raise ResponseContractError("live response envelope roots differ from pinned authority")
        anomaly_codes.add("reordered_envelope_root")
    result_sets_by_name = {item.name: item for item in endpoint_contract.result_sets}
    for result_set in endpoint_contract.result_sets:
        parent_occurrence_states: list[str] = []
        if result_set.parent_result_set_name is None:
            root_name = result_set.json_path.removeprefix("$.")
            if root_name not in payload:
                raise ResponseContractError("live response omitted a required envelope root")
            result_containers = (payload[root_name],)
            parent_occurrence_states.append("present")
        else:
            parent_field_name = result_set.parent_field_name
            if parent_field_name is None:
                raise ResponseContractError("live nested result set omitted its parent field")
            parent = result_sets_by_name[result_set.parent_result_set_name]
            parent_field = next(
                (field for field in parent.fields if field.name == parent_field_name),
                None,
            )
            nested: list[object] = []
            for parent_row in observations[parent.name].rows:
                if not isinstance(parent_row, Mapping):
                    raise ResponseContractError("live nested result-set parent is not an object")
                parent_mapping = cast("Mapping[str, object]", parent_row)
                if parent_field_name not in parent_mapping:
                    parent_occurrence_states.append("missing")
                    if parent_field is not None and parent_field.key_presence == "required":
                        raise ResponseContractError("live response omitted a required nested field")
                    continue
                value = parent_mapping[parent_field_name]
                if value is None:
                    parent_occurrence_states.append("null")
                    if parent_field is not None and not parent_field.nullable:
                        raise ResponseContractError("live nested result-set field cannot be null")
                    continue
                parent_occurrence_states.append("present")
                nested.append(value)
            result_containers = tuple(nested)

        child_fields = {
            child.parent_field_name
            for child in endpoint_contract.result_sets
            if child.parent_result_set_name == result_set.name
            and child.parent_field_name is not None
        }
        result_rows: list[object] = []
        for container in result_containers:
            records, container_anomalies = _validate_live_result_container(
                result_set,
                container,
                child_fields,
                allow_additive_drift=allow_additive_drift,
            )
            result_rows.extend(records)
            anomaly_codes.update(container_anomalies)
        observations[result_set.name] = _LiveResultObservation(
            containers=result_containers,
            rows=tuple(result_rows),
            parent_occurrence_states=tuple(parent_occurrence_states),
        )
    return observations, tuple(sorted(anomaly_codes))


def _parse_live_payloads(
    response: object,
    *,
    parser_input: str | None = None,
    endpoint_contract: LiveEndpointContract,
    selected_result_sets: Sequence[tuple[str, LiveResultSetContract]],
    endpoint_slug: str,
    request_parameters: Mapping[str, Any],
    provider_authority_sha256: str,
    endpoint_contract_sha256: str,
    allow_additive_drift: bool,
) -> tuple[
    dict[str, Any],
    tuple[ResultSetReceipt, ...],
    NbaApiLiveLosslessLanding,
]:
    """Run the shared pure live response-to-payload contract path."""

    payload = _validated_response_dict(response, parser_input=parser_input)
    observations, anomaly_codes = _validate_live_envelope(
        endpoint_contract,
        payload,
        allow_additive_drift=allow_additive_drift,
    )

    values: dict[str, Any] = {}
    for attr, result_set in selected_result_sets:
        selected_containers = observations[result_set.name].containers
        if not selected_containers:
            raise ResponseContractError("selected live result set is absent from response")
        if len(selected_containers) != 1:
            raise ResponseContractError("selected live result set is not a single root packet")
        selected_value = selected_containers[0]
        values[attr] = (
            project_known_live_container(
                selected_value,
                result_set=result_set,
                contract=endpoint_contract,
            )
            if anomaly_codes
            else selected_value
        )

    result_receipts: list[ResultSetReceipt] = []
    for result_set in endpoint_contract.result_sets:
        observation = observations[result_set.name]
        headers = tuple(field.name for field in result_set.fields)
        result_receipts.append(
            ResultSetReceipt(
                name=result_set.name,
                provider_index=None,
                canonical_index=result_set.ordinal,
                headers_sha256=_headers_sha256(headers),
                row_count=len(observation.rows),
                json_path=result_set.json_path,
                container_kind=result_set.container_kind,
                container_count=len(observation.containers),
                missing_count=observation.missing_count,
                null_count=observation.null_count,
                parent_observation_count=len(observation.parent_occurrence_states),
                parent_occurrence_states_sha256=observation.parent_occurrence_states_sha256,
                observed_field_orders_sha256=observation.observed_field_orders_sha256,
                normalized_output_sha256=observation.normalized_output_sha256,
            )
        )
    receipts = tuple(result_receipts)
    landing = build_live_lossless_landing(
        payload,
        contract=endpoint_contract,
        endpoint_slug=endpoint_slug,
        request_parameters=request_parameters,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256,
        result_set_receipts=receipts,
        anomaly_codes=anomaly_codes,
    )
    return values, receipts, landing


def _raw_authority_contract_digest(
    source_family: str,
    endpoint_id: str,
    *,
    provider_authority_sha256: str,
    endpoint_contract_sha256_value: str,
) -> NbaApiEndpointContract | LiveEndpointContract | StaticDatasetContract:
    """Resolve one public observation against the exact embedded authority."""

    expected_provider = expected_nba_api_provider_authority()["authority_sha256"]
    if provider_authority_sha256 != expected_provider:
        raise ResponseContractError("raw authority references a foreign provider contract")
    if source_family == "stats":
        contract = pinned_runtime_contracts().get(endpoint_id)
        expected_digest = None if contract is None else endpoint_contract_sha256(contract)
    elif source_family == "live":
        contract = pinned_live_contracts().get(endpoint_id)
        expected_digest = None if contract is None else owned_contract_sha256(contract)
    elif source_family == "static":
        try:
            contract = pinned_static_dataset_contract(endpoint_id)
        except ValueError:
            contract = None
        expected_digest = None if contract is None else owned_contract_sha256(contract)
    else:
        contract = None
        expected_digest = None
    if contract is None or endpoint_contract_sha256_value != expected_digest:
        raise ResponseContractError("raw authority lacks its exact pinned endpoint contract")
    return contract


def validate_raw_authority_contract_identity(
    *,
    source_family: str,
    endpoint_id: str,
    provider_authority_sha256: str,
    endpoint_contract_sha256_value: str,
) -> None:
    """Fail closed unless one public observation names the exact pinned authority."""

    _raw_authority_contract_digest(
        source_family,
        endpoint_id,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256_value=endpoint_contract_sha256_value,
    )


def _raw_authority_json_object(parser_input: bytes) -> tuple[str, dict[str, Any]]:
    def _reject_nonfinite(_value: str) -> object:
        raise ResponseContractError("raw authority parser input contains a non-finite value")

    try:
        text = parser_input.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ResponseContractError("raw authority parser input is not exact UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_json_object_without_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except ResponseContractError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResponseContractError("raw authority parser input is malformed JSON") from exc
    if not isinstance(payload, dict) or text.encode("utf-8") != parser_input:
        raise ResponseContractError("raw authority parser input must be one exact JSON object")
    return text, payload


def _raw_authority_stats_fallback_derivations(
    *,
    provider_sets: Sequence[tuple[str, object, object]],
    expected: Sequence[tuple[str, tuple[str, ...]]],
    reasons: set[str],
    per_set_reasons: Sequence[set[str]],
) -> tuple[RawAuthorityResultSetDerivation, ...]:
    """Derive fallback receipts without constructing the cell-level fallback frame."""

    provider_name_counts = Counter(name for name, _headers, _rows in provider_sets)
    duplicate_names: Counter[str] = Counter()
    derived: list[RawAuthorityResultSetDerivation] = []
    for provider_index, (name, raw_headers, raw_rows) in enumerate(provider_sets):
        headers = _fallback_ordered_headers(raw_headers)
        normalized_rows = raw_rows if isinstance(raw_rows, list) else []
        headers_digest = _canonical_value_sha256(list(headers))
        receipt = ResultSetReceipt(
            name=name,
            provider_index=provider_index,
            canonical_index=None,
            headers_sha256=headers_digest,
            row_count=len(normalized_rows),
            json_path=None,
            container_kind="nba_api_result_set",
            container_count=1,
            missing_count=0,
            null_count=0,
            parent_observation_count=1,
            parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
            observed_field_orders_sha256=headers_digest,
            normalized_output_sha256=_canonical_value_sha256(
                {
                    "headers": raw_headers,
                    "rows": raw_rows,
                    "anomalies": sorted(per_set_reasons[provider_index]),
                }
            ),
        )
        duplicate_ordinal = duplicate_names[name]
        duplicate_names[name] += 1
        derived.append(
            RawAuthorityResultSetDerivation(
                result_set=receipt,
                ordered_headers=headers,
                duplicate_name_ordinal=duplicate_ordinal,
            )
        )

    for _canonical_index, (name, expected_headers) in enumerate(expected):
        if provider_name_counts[name]:
            continue
        headers_digest = _headers_sha256(expected_headers)
        receipt = ResultSetReceipt(
            name=name,
            provider_index=None,
            canonical_index=None,
            headers_sha256=headers_digest,
            row_count=0,
            json_path=None,
            container_kind="nba_api_result_set",
            container_count=0,
            missing_count=1,
            null_count=0,
            parent_observation_count=1,
            parent_occurrence_states_sha256=parent_occurrence_states_digest(("missing",)),
            observed_field_orders_sha256=headers_digest,
            normalized_output_sha256=_normalized_output_sha256(expected_headers, ()),
        )
        duplicate_ordinal = duplicate_names[name]
        duplicate_names[name] += 1
        derived.append(
            RawAuthorityResultSetDerivation(
                result_set=receipt,
                ordered_headers=expected_headers,
                duplicate_name_ordinal=duplicate_ordinal,
            )
        )
    if not reasons or not derived:
        raise ResponseContractError("raw authority fallback derivation lacks drift evidence")
    return tuple(derived)


def rederive_raw_authority_stats_fallback(
    *,
    endpoint_id: str,
    parser_input: bytes,
    provider_authority_sha256: str,
    endpoint_contract_sha256_value: str,
) -> NbaApiLosslessFallback:
    """Rebuild the exact unbound stats fallback frame from public raw bytes."""

    contract = _raw_authority_contract_digest(
        "stats",
        endpoint_id,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256_value=endpoint_contract_sha256_value,
    )
    if not isinstance(contract, NbaApiEndpointContract) or not contract.endpoint_slug:
        raise ResponseContractError("stats raw authority lacks its endpoint slug")
    text, payload = _raw_authority_json_object(parser_input)
    _validate_decoded_response_envelope(payload)
    provider_sets = (
        _custom_data_sets(text, contract.endpoint_slug)
        if contract.parser_kind == "custom_nested"
        else _legacy_data_sets(payload)
    )
    expected = _expected_result_sets(contract, contract.endpoint_slug)
    reasons, per_set_reasons = _result_set_fallback_anomalies(provider_sets, expected)
    if not reasons:
        try:
            _strict_stats_packets(provider_sets, expected)
        except ResponseContractError:
            reasons.add("unrepresentable_typed_frame")
        else:
            raise ResponseContractError("stats raw authority does not require lossless fallback")
    frame, receipts = _fallback_frame(
        endpoint_slug=contract.endpoint_slug,
        provider_sets=provider_sets,
        expected=expected,
        reasons=reasons,
        per_set_reasons=per_set_reasons,
    )
    return NbaApiLosslessFallback(
        endpoint_slug=contract.endpoint_slug,
        reason_codes=tuple(sorted(reasons)),
        provider_result_set_count=len(provider_sets),
        expected_result_set_count=len(expected),
        result_set_receipts=receipts,
        frame=frame,
    )


def rederive_raw_authority_unknown_stats_response(
    *,
    endpoint_id: str,
    parser_input: bytes,
    safe_parameters_json: str,
    provider_authority_sha256: str,
    endpoint_contract_sha256_value: str,
) -> NbaApiUnknownResponse:
    """Rebuild an unbound unknown-response projection from exact public bytes."""

    contract = _raw_authority_contract_digest(
        "stats",
        endpoint_id,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256_value=endpoint_contract_sha256_value,
    )
    if (
        not isinstance(contract, NbaApiEndpointContract)
        or not contract.endpoint_slug
        or contract.response_mode != "unknown_dynamic_response"
    ):
        raise ResponseContractError("stats raw authority lacks unknown-response authority")
    text, payload = _raw_authority_json_object(parser_input)
    _validate_decoded_response_envelope(payload)
    if not isinstance(safe_parameters_json, str):
        raise ResponseContractError("raw unknown-response parameters are not canonical JSON")
    _parameter_text, parameters = _raw_authority_json_object(
        safe_parameters_json.encode("utf-8", errors="strict")
    )
    if _canonical_json_value(parameters) != safe_parameters_json:
        raise ResponseContractError("raw unknown-response parameters are not canonical JSON")
    try:
        request_surface = pinned_request_surface_authority()
        endpoint_surface = request_surface.endpoint("stats", endpoint_id)
        materialized_request = materialize_provider_request(
            endpoint_surface,
            parameters,
            request_surface_sha256=request_surface.surface_sha256,
            runtime_contract_payload_sha256=(request_surface.runtime_contract_payload_sha256),
        )
        materialized = dict(materialized_request.materialized_parameters)
        wire_parameters = {
            parameter.query_name: materialized[parameter.name]
            for parameter in endpoint_surface.parameters
        }
    except (KeyError, NbaApiRequestSurfaceError) as exc:
        raise ResponseContractError(
            "raw unknown-response parameters differ from pinned wire authority"
        ) from exc
    return _parse_unknown_stats_payload(
        contract=contract,
        endpoint_slug=contract.endpoint_slug,
        parameters=wire_parameters,
        payload=payload,
        parser_input=text,
    )


def _raw_authority_stats_rows_from_packets(
    provider_sets: Sequence[tuple[str, object, object]],
    packets: Sequence[NbaApiResultPacket],
) -> tuple[RawAuthorityStatsResultRows, ...]:
    derived: list[RawAuthorityStatsResultRows] = []
    duplicate_names: Counter[str] = Counter()
    for packet in packets:
        if packet.provider_index >= len(provider_sets):
            raise ResponseContractError("stats raw row provider ordinal is out of range")
        provider_name, _raw_headers, raw_rows = provider_sets[packet.provider_index]
        if provider_name != packet.name:
            raise ResponseContractError("stats raw row provider identity drifted")
        rows = _validated_rows(raw_rows, len(packet.headers))
        normalized_rows = [list(row) for row in rows]
        receipt = ResultSetReceipt(
            name=packet.name,
            provider_index=packet.provider_index,
            canonical_index=packet.canonical_index,
            headers_sha256=_headers_sha256(packet.headers),
            row_count=len(rows),
            json_path=None,
            container_kind="nba_api_result_set",
            container_count=1,
            missing_count=0,
            null_count=0,
            parent_observation_count=1,
            parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
            observed_field_orders_sha256=_headers_sha256(packet.headers),
            normalized_output_sha256=_normalized_output_sha256(
                packet.headers,
                normalized_rows,
            ),
        )
        duplicate_ordinal = duplicate_names[packet.name]
        duplicate_names[packet.name] += 1
        derived.append(
            RawAuthorityStatsResultRows(
                result_set=receipt,
                ordered_headers=packet.headers,
                duplicate_name_ordinal=duplicate_ordinal,
                rows=tuple(
                    tuple(
                        NbaApiUnknownCell(
                            value_kind=_json_value_kind(value),
                            canonical_json=_canonical_json_value(value),
                        )
                        for value in row
                    )
                    for row in rows
                ),
            )
        )
    return tuple(derived)


def rederive_raw_authority_stats_wide_rows(
    *,
    endpoint_id: str,
    parser_input: bytes,
    provider_authority_sha256: str,
    endpoint_contract_sha256_value: str,
) -> tuple[RawAuthorityStatsResultRows, ...]:
    """Rebuild exactly the response-wide safe wide projection from public bytes.

    A successful stats fallback either admits every pinned packet that the
    production parser can represent losslessly or admits none of them.  Extra
    provider result sets do not suppress otherwise exact pinned packets.  An
    empty return is therefore authoritative evidence that every declared wide
    route must have committed zero rows for this response.
    """

    contract = _raw_authority_contract_digest(
        "stats",
        endpoint_id,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256_value=endpoint_contract_sha256_value,
    )
    if not isinstance(contract, NbaApiEndpointContract) or not contract.endpoint_slug:
        raise ResponseContractError("stats raw wide authority lacks its endpoint slug")
    text, payload = _raw_authority_json_object(parser_input)
    _validate_decoded_response_envelope(payload)
    provider_sets = (
        _custom_data_sets(text, contract.endpoint_slug)
        if contract.parser_kind == "custom_nested"
        else _legacy_data_sets(payload)
    )
    expected = _expected_result_sets(contract, contract.endpoint_slug)
    packets = _safe_known_packets_during_fallback(provider_sets, expected)
    if packets and len(packets) != len(expected):
        raise ResponseContractError("stats raw wide projection is only partially admitted")
    return _raw_authority_stats_rows_from_packets(provider_sets, packets)


def rederive_raw_authority_stats_rows(
    *,
    endpoint_id: str,
    parser_input: bytes,
    provider_authority_sha256: str,
    endpoint_contract_sha256_value: str,
) -> tuple[RawAuthorityStatsResultRows, ...]:
    """Reparse exact public bytes into strict-known stats rows and receipts.

    The owned ``nba_api`` parser is used for both legacy envelopes and every
    pinned custom-nested parser.  Successful drift belongs to the separate
    lossless-fallback replay API and therefore fails this strict-wide helper.
    """

    contract = _raw_authority_contract_digest(
        "stats",
        endpoint_id,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256_value=endpoint_contract_sha256_value,
    )
    if not isinstance(contract, NbaApiEndpointContract) or not contract.endpoint_slug:
        raise ResponseContractError("stats raw row authority lacks its endpoint slug")
    text, payload = _raw_authority_json_object(parser_input)
    _validate_decoded_response_envelope(payload)
    provider_sets = (
        _custom_data_sets(text, contract.endpoint_slug)
        if contract.parser_kind == "custom_nested"
        else _legacy_data_sets(payload)
    )
    expected = _expected_result_sets(contract, contract.endpoint_slug)
    packets, receipts = _strict_stats_packets(provider_sets, expected)
    derived = _raw_authority_stats_rows_from_packets(provider_sets, packets)
    if tuple(item.result_set for item in derived) != receipts:
        raise ResponseContractError("stats raw row receipts differ from strict parsing")
    if not derived:
        raise ResponseContractError("stats raw row authority produced no result sets")
    return tuple(derived)


def rederive_raw_authority_result_sets(
    *,
    source_family: str,
    endpoint_id: str,
    parser_input: bytes | None,
    provider_authority_sha256: str,
    endpoint_contract_sha256_value: str,
) -> tuple[RawAuthorityResultSetDerivation, ...]:
    """Independently rederive exact result receipts for publication assurance.

    Stats and live receipts are derived from the immutable stored parser bytes.
    Static receipts are bodyless by contract and are derived from the installed
    exact-pin static snapshot after its embedded content digests are verified.
    Unsupported or foreign provider identities fail closed.
    """

    contract = _raw_authority_contract_digest(
        source_family,
        endpoint_id,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256_value=endpoint_contract_sha256_value,
    )
    if source_family == "static":
        if parser_input is not None or not isinstance(contract, StaticDatasetContract):
            raise ResponseContractError("static raw authority must be exactly bodyless")
        source_rows = _static_source_rows(contract)
        _packet, receipt = _parse_static_packet(contract, source_rows)
        return (
            RawAuthorityResultSetDerivation(
                result_set=receipt,
                ordered_headers=tuple(field.name for field in contract.raw_fields),
                duplicate_name_ordinal=0,
            ),
        )

    if parser_input is None:
        raise ResponseContractError("stats/live raw authority omitted its parser bytes")
    text, payload = _raw_authority_json_object(parser_input)
    _validate_decoded_response_envelope(payload)
    if source_family == "stats":
        if not isinstance(contract, NbaApiEndpointContract) or not contract.endpoint_slug:
            raise ResponseContractError("stats raw authority lacks its endpoint slug")
        provider_sets = (
            _custom_data_sets(text, contract.endpoint_slug)
            if contract.parser_kind == "custom_nested"
            else _legacy_data_sets(payload)
        )
        expected = _expected_result_sets(contract, contract.endpoint_slug)
        reasons, per_set_reasons = _result_set_fallback_anomalies(provider_sets, expected)
        if not reasons:
            try:
                packets, receipts = _strict_stats_packets(provider_sets, expected)
            except ResponseContractError:
                reasons.add("unrepresentable_typed_frame")
            else:
                duplicate_names: Counter[str] = Counter()
                derived: list[RawAuthorityResultSetDerivation] = []
                for packet, receipt in zip(packets, receipts, strict=True):
                    duplicate_ordinal = duplicate_names[receipt.name]
                    duplicate_names[receipt.name] += 1
                    derived.append(
                        RawAuthorityResultSetDerivation(
                            result_set=receipt,
                            ordered_headers=packet.headers,
                            duplicate_name_ordinal=duplicate_ordinal,
                        )
                    )
                return tuple(derived)
        return _raw_authority_stats_fallback_derivations(
            provider_sets=provider_sets,
            expected=expected,
            reasons=reasons,
            per_set_reasons=per_set_reasons,
        )

    if not isinstance(contract, LiveEndpointContract):
        raise ResponseContractError("live raw authority lacks its exact contract")
    observations, _anomaly_codes = _validate_live_envelope(
        contract,
        payload,
        allow_additive_drift=True,
    )
    derived = []
    for result_set in contract.result_sets:
        observation = observations[result_set.name]
        headers = tuple(field.name for field in result_set.fields)
        receipt = ResultSetReceipt(
            name=result_set.name,
            provider_index=None,
            canonical_index=result_set.ordinal,
            headers_sha256=_headers_sha256(headers),
            row_count=len(observation.rows),
            json_path=result_set.json_path,
            container_kind=result_set.container_kind,
            container_count=len(observation.containers),
            missing_count=observation.missing_count,
            null_count=observation.null_count,
            parent_observation_count=len(observation.parent_occurrence_states),
            parent_occurrence_states_sha256=observation.parent_occurrence_states_sha256,
            observed_field_orders_sha256=observation.observed_field_orders_sha256,
            normalized_output_sha256=observation.normalized_output_sha256,
        )
        derived.append(
            RawAuthorityResultSetDerivation(
                result_set=receipt,
                ordered_headers=headers,
                duplicate_name_ordinal=0,
            )
        )
    return tuple(derived)


def _raw_authority_safe_parameters(safe_parameters_json: str) -> dict[str, Any]:
    if type(safe_parameters_json) is not str or len(safe_parameters_json) > 32_768:
        raise ResponseContractError("raw route-frame parameters must be bounded canonical JSON")

    def _reject_nonfinite(_value: str) -> object:
        raise ResponseContractError("raw route-frame parameters contain a non-finite value")

    try:
        decoded = json.loads(
            safe_parameters_json,
            object_pairs_hook=_json_object_without_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except ResponseContractError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResponseContractError("raw route-frame parameters are malformed JSON") from exc
    if not isinstance(decoded, dict):
        raise ResponseContractError("raw route-frame parameters must be a JSON object")
    try:
        safe = canonical_parameters_payload(decoded)
        canonical = json.dumps(
            safe,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResponseContractError("raw route-frame parameters are not public-safe") from exc
    if canonical != safe_parameters_json:
        raise ResponseContractError("raw route-frame parameters are not exact canonical JSON")
    return safe


def _raw_authority_route_frame_derivation(
    *,
    route_id: str,
    staging_key: str,
    route_contract_sha256: str,
    frame: pl.DataFrame,
    source_result_ordinals: tuple[int, ...],
    capture_response_receipt_sha256: str,
    logical_parameters_sha256: str,
) -> RawAuthorityRouteFrameDerivation:
    from nbadb.orchestrate.staging_batches import (
        CANONICAL_FRAME_FORMAT,
        FRAME_CONTENT_HASH_CONTRACT,
        FRAME_SCHEMA_HASH_CONTRACT,
        frame_content_hash,
        frame_schema_hash,
    )

    return RawAuthorityRouteFrameDerivation(
        route_id=route_id,
        staging_key=staging_key,
        route_contract_sha256=route_contract_sha256,
        frame=frame,
        source_result_ordinals=source_result_ordinals,
        row_count=frame.height,
        capture_response_receipt_sha256=capture_response_receipt_sha256,
        logical_parameters_sha256=logical_parameters_sha256,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        frame_content_sha256=frame_content_hash(frame),
        frame_schema_sha256=frame_schema_hash(frame),
    )


def rederive_raw_authority_route_frames(
    *,
    source_family: str,
    endpoint_name: str,
    endpoint_id: str,
    selected_route_ids: tuple[str, ...],
    parser_input: bytes | None,
    safe_parameters_json: str,
    provider_authority_sha256: str,
    endpoint_contract_sha256_value: str,
    capture_response_receipt_sha256: str,
    live_snapshot_at: datetime | None,
) -> tuple[RawAuthorityRouteFrameDerivation, ...]:
    """Reconstruct every static/live landing frame without provider transport.

    This is a pure computation boundary, not a Raw Authority V2 admission API.
    The caller-supplied capture receipt and live snapshot are bound into the
    output, but final admission must separately join them to the store-owned
    capture authority and the exact sealed plan/as-of authority.
    """

    from nbadb.contracts.staging_route_contract import (
        admit_conditional_live_lossless_route,
        staging_route_contract_bundle,
    )
    from nbadb.extract.live.endpoints import LIVE_PACKET_CONTRACTS
    from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY

    if source_family not in {"static", "live"}:
        raise ResponseContractError("raw route-frame source must be static or live")
    if type(endpoint_name) is not str or not endpoint_name or ":" in endpoint_name:
        raise ResponseContractError("raw route-frame endpoint name is invalid")
    if (
        type(selected_route_ids) is not tuple
        or not selected_route_ids
        or selected_route_ids != tuple(sorted(set(selected_route_ids)))
        or any(type(route_id) is not str or not route_id for route_id in selected_route_ids)
    ):
        raise ResponseContractError("raw route-frame route inventory is not canonical")
    if (
        type(capture_response_receipt_sha256) is not str
        or _SHA256_RE.fullmatch(capture_response_receipt_sha256) is None
    ):
        raise ResponseContractError("raw route-frame capture receipt is invalid")

    contract = _raw_authority_contract_digest(
        source_family,
        endpoint_id,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256_value=endpoint_contract_sha256_value,
    )
    parameters = _raw_authority_safe_parameters(safe_parameters_json)
    logical_parameters_sha256 = canonical_parameters_sha256(parameters)

    bundle = staging_route_contract_bundle()
    fixed_routes = tuple(
        sorted(
            (
                route
                for route in bundle.routes
                if route.endpoint_name == endpoint_name and route.source_family == source_family
            ),
            key=lambda route: route.ordinal,
        )
    )
    if not fixed_routes:
        raise ResponseContractError("raw route-frame endpoint has no current fixed routes")
    if (
        bundle.provider_authority_sha256 != provider_authority_sha256
        or any(
            route.provider_authority_sha256 != provider_authority_sha256 for route in fixed_routes
        )
        or any(route.provider_endpoint_id != endpoint_id for route in fixed_routes)
        or any(
            route.endpoint_contract_sha256 != endpoint_contract_sha256_value
            for route in fixed_routes
        )
        or any(route.classified_status != "bound_provider_packet" for route in fixed_routes)
    ):
        raise ResponseContractError("raw route-frame routes differ from current provider authority")

    conditional_route_ids: tuple[str, ...] = ()
    if source_family == "live":
        if not isinstance(contract, LiveEndpointContract):
            raise ResponseContractError("raw live route-frame lacks its pinned live contract")
        conditional_route_ids = (
            f"{endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:{len(contract.result_sets)}",
        )
    expected_selected = tuple(
        sorted((*tuple(route.route_id for route in fixed_routes), *conditional_route_ids))
    )
    if selected_route_ids != expected_selected:
        raise ResponseContractError("raw route-frame selection differs from current route closure")

    if source_family == "static":
        if (
            not isinstance(contract, StaticDatasetContract)
            or parser_input is not None
            or parameters
            or safe_parameters_json != "{}"
            or live_snapshot_at is not None
            or len(fixed_routes) != 1
        ):
            raise ResponseContractError("static route-frame reconstruction contract differs")
        source_rows = _static_source_rows(contract)
        packet, receipt = _parse_static_packet(contract, source_rows)
        frame = project_static_landing_frame(contract.dataset_id, packet.frame)
        route = fixed_routes[0]
        if tuple(frame.columns) != route.storage_columns:
            raise ResponseContractError("static route-frame columns differ from current route")
        canonical_ordinal = receipt.canonical_index
        if canonical_ordinal is None:
            raise ResponseContractError("static route-frame omitted its result ordinal")
        return (
            _raw_authority_route_frame_derivation(
                route_id=route.route_id,
                staging_key=route.staging_key,
                route_contract_sha256=route.contract_sha256,
                frame=frame,
                source_result_ordinals=(canonical_ordinal,),
                capture_response_receipt_sha256=capture_response_receipt_sha256,
                logical_parameters_sha256=logical_parameters_sha256,
            ),
        )

    if not isinstance(contract, LiveEndpointContract):
        raise ResponseContractError("raw live route-frame lacks its exact live contract")
    live_contract = contract
    if (
        type(parser_input) is not bytes
        or not parser_input
        or not isinstance(live_snapshot_at, datetime)
        or live_snapshot_at.tzinfo is None
        or live_snapshot_at.utcoffset() != timedelta(0)
    ):
        raise ResponseContractError(
            "live route-frame requires exact parser bytes and an aware UTC snapshot"
        )
    normalized_snapshot_at = live_snapshot_at.astimezone(UTC)

    runtime_identities = {
        (route.provider_runtime_module, route.provider_runtime_class) for route in fixed_routes
    }
    if len(runtime_identities) != 1:
        raise ResponseContractError("raw live route-frame spans runtime endpoint identities")
    runtime_module, runtime_class_name = next(iter(runtime_identities))
    try:
        endpoint_cls = getattr(importlib.import_module(runtime_module), runtime_class_name)
    except (AttributeError, ImportError) as exc:
        raise ResponseContractError("raw live route-frame runtime endpoint is unavailable") from exc
    resolved_contract = _resolve_live_contract(endpoint_cls)
    if resolved_contract != live_contract:
        raise ResponseContractError("raw live route-frame runtime contract differs")

    packets: list[Any] = []
    for route in fixed_routes:
        candidates = tuple(
            packet for packet in LIVE_PACKET_CONTRACTS if packet.staging_key == route.staging_key
        )
        if len(candidates) != 1:
            raise ResponseContractError("raw live route-frame lacks one exact packet contract")
        packet = candidates[0]
        result_set = packet.provider_result_set
        if (
            packet.upstream_endpoint != endpoint_id
            or packet.source_endpoint != route.canonical_result_set_name
            or result_set.name != route.provider_result_set_name
            or result_set.ordinal != route.provider_result_set_ordinal
        ):
            raise ResponseContractError("raw live packet differs from its current route")
        packets.append(packet)
    if len({packet.attr for packet in packets}) != len(packets):
        raise ResponseContractError("raw live route-frame packet outputs are ambiguous")

    domain_parameters, transport_parameters, request_parameters = _live_request_contract(
        live_contract,
        parameters,
    )
    if transport_parameters or domain_parameters != parameters:
        raise ResponseContractError("raw live route-frame parameters differ from exact semantics")
    _endpoint, _endpoint_url, _headers = _live_endpoint_declaration(
        endpoint_cls,
        live_contract,
        domain_parameters,
        {},
    )
    packet_result_sets = {packet.attr: packet.result_set_name for packet in packets}
    selected_result_sets = _selected_live_result_sets(live_contract, packet_result_sets)
    text, _payload = _raw_authority_json_object(parser_input)
    response = NBAResponse(text, 200, "private-raw-authority://live-route-replay")
    values, result_receipts, landing = _parse_live_payloads(
        response,
        parser_input=text,
        endpoint_contract=live_contract,
        selected_result_sets=selected_result_sets,
        endpoint_slug=live_contract.endpoint_slug,
        request_parameters=request_parameters,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256_value,
        allow_additive_drift=True,
    )
    if tuple(receipt.canonical_index for receipt in result_receipts) != tuple(
        range(len(live_contract.result_sets))
    ):
        raise ResponseContractError("raw live route-frame result receipt inventory differs")

    derivations: list[RawAuthorityRouteFrameDerivation] = []
    for route, packet in zip(fixed_routes, packets, strict=True):
        frame = live_payload_to_frame(
            values[packet.attr],
            field_projections=dict(packet.typed_projections),
        )
        frame = apply_live_snapshot_contract(
            frame,
            source_endpoint=packet.source_endpoint,
            natural_keys=packet.natural_keys,
            snapshot_at=normalized_snapshot_at,
            params=domain_parameters,
        )
        try:
            frame = normalize_live_landing_frame(frame, source_endpoint=packet.source_endpoint)
        except Exception as exc:
            raise ResponseContractError("raw live route-frame failed its exact raw schema") from exc
        result_ordinal = packet.provider_result_set.ordinal
        derivations.append(
            _raw_authority_route_frame_derivation(
                route_id=route.route_id,
                staging_key=route.staging_key,
                route_contract_sha256=route.contract_sha256,
                frame=frame,
                source_result_ordinals=(result_ordinal,),
                capture_response_receipt_sha256=capture_response_receipt_sha256,
                logical_parameters_sha256=logical_parameters_sha256,
            )
        )

    admission = admit_conditional_live_lossless_route(
        endpoint_name=endpoint_name,
        static_route_ids=tuple(route.route_id for route in fixed_routes),
        conditional_route_ids=conditional_route_ids,
        provider_authority_sha256=provider_authority_sha256,
    )
    landing = landing.bind_response_receipt(capture_response_receipt_sha256).bind_snapshot(
        normalized_snapshot_at
    )
    validate_live_lossless_frame(
        landing.frame,
        expected_response_receipt_sha256=capture_response_receipt_sha256,
        expected_result_set_count=len(live_contract.result_sets),
        expected_snapshot_at=normalized_snapshot_at,
        expected_endpoint_id=endpoint_id,
        expected_endpoint_slug=live_contract.endpoint_slug,
        expected_anomaly_codes=landing.reason_codes,
    )
    if tuple(landing.frame.columns) != admission.storage_columns:
        raise ResponseContractError("raw live node frame columns differ from current route")
    request_parameter_values = landing.frame["request_parameters_json"].unique().to_list()
    if not request_parameter_values or any(
        not isinstance(value, str)
        or admission.logical_parameters_sha256(value) != logical_parameters_sha256
        for value in request_parameter_values
    ):
        raise ResponseContractError("raw live node frame differs from its logical parameters")
    derivations.append(
        _raw_authority_route_frame_derivation(
            route_id=admission.route_id,
            staging_key=admission.staging_key,
            route_contract_sha256=admission.contract_sha256,
            frame=landing.frame,
            source_result_ordinals=tuple(range(len(live_contract.result_sets))),
            capture_response_receipt_sha256=capture_response_receipt_sha256,
            logical_parameters_sha256=logical_parameters_sha256,
        )
    )
    return tuple(derivations)


def fetch_live_payloads(
    endpoint_cls: type,
    packet_result_sets: Mapping[str, str],
    *,
    capture: NbaApiCaptureContract | None = None,
    allow_additive_drift: bool = False,
    **kwargs: Any,
) -> NbaApiPayload:
    """Execute one live request and return validated, nbadb-owned payloads."""

    if not isinstance(allow_additive_drift, bool):
        raise ResponseContractError("live additive-drift policy must be boolean")
    endpoint_contract = _resolve_live_contract(endpoint_cls)
    selected_result_sets = _selected_live_result_sets(endpoint_contract, packet_result_sets)
    domain_parameters, transport_parameters, request_parameters = _live_request_contract(
        endpoint_contract, kwargs
    )
    contract_digest = owned_contract_sha256(endpoint_contract)
    if capture is not None:
        expected_provider_digest = expected_nba_api_provider_authority()["authority_sha256"]
        if (
            capture.provider_authority_sha256 != expected_provider_digest
            or capture.endpoint_contract_sha256 != contract_digest
        ):
            raise ResponseContractError("capture authority differs from the pinned live contract")

    endpoint, endpoint_url, headers = _live_endpoint_declaration(
        endpoint_cls,
        endpoint_contract,
        domain_parameters,
        transport_parameters,
    )
    request_context = capture.begin_request() if capture is not None else None
    try:
        response = NbaDbLiveHTTP().send_api_request(
            endpoint=endpoint_url,
            parameters={},
            proxy=getattr(endpoint, "proxy", None),
            headers=headers,
            timeout=getattr(endpoint, "timeout", None),
        )
    except Exception as exc:
        _record_no_response_failure(
            capture=capture,
            source_family="live",
            endpoint_id=endpoint_contract.endpoint_id,
            endpoint_slug=endpoint_contract.endpoint_slug,
            parameters=request_parameters,
            context=request_context,
            exc=exc,
        )
        raise
    captured, parser_input = _capture_response(response, capture)
    try:
        values, result_receipts, live_lossless_landing = _parse_live_payloads(
            response,
            parser_input=parser_input,
            endpoint_contract=endpoint_contract,
            selected_result_sets=selected_result_sets,
            endpoint_slug=endpoint_contract.endpoint_slug,
            request_parameters=request_parameters,
            provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
            endpoint_contract_sha256=contract_digest,
            allow_additive_drift=allow_additive_drift,
        )
    except Exception as exc:
        _record_response_failure(
            capture=capture,
            captured=captured,
            response=response,
            source_family="live",
            endpoint_id=endpoint_contract.endpoint_id,
            endpoint_slug=endpoint_contract.endpoint_slug,
            parameters=request_parameters,
            context=request_context,
            exc=exc,
        )
        raise

    receipt: str | None = None
    if capture is not None:
        if captured is None:
            raise ResponseContractError("provider response capture is required")
        if request_context is None:
            raise ResponseContractError("provider response omitted its request context")
        receipt = capture.sink.record_response_attempt(
            context=request_context,
            transport_kind="http_response",
            source_family="live",
            endpoint_id=endpoint_contract.endpoint_id,
            endpoint_slug=endpoint_contract.endpoint_slug,
            parameters=request_parameters,
            provider_authority_sha256=capture.provider_authority_sha256,
            contract_sha256=contract_digest,
            status_code=_response_status(response),
            captured=captured,
            outcome=(
                "success_nonempty"
                if any(result_set.row_count for result_set in result_receipts)
                else "success_empty"
            ),
            failure_class=None,
            root_exception_class=None,
            result_sets=result_receipts,
        )
        capture.record_receipt(request_context, receipt, successful=True)
        live_lossless_landing = live_lossless_landing.bind_response_receipt(receipt)
    return NbaApiPayload(
        values,
        response_receipt_sha256=receipt,
        provider_authority_sha256=(capture.provider_authority_sha256 if capture else None),
        endpoint_contract_sha256=contract_digest,
        result_set_receipts=result_receipts,
        live_lossless_landing=live_lossless_landing,
    )


def replay_live_payloads(
    source: ParserInputReplaySource,
    response_receipt_sha256: str,
    endpoint_cls: type,
    packet_result_sets: Mapping[str, str],
    *,
    allow_additive_drift: bool = False,
    **kwargs: Any,
) -> NbaApiPayload:
    """Replay one recorded live response through the owned parser without transport."""

    if not isinstance(allow_additive_drift, bool):
        raise ResponseContractError("live additive-drift policy must be boolean")
    endpoint_contract = _resolve_live_contract(endpoint_cls)
    selected_result_sets = _selected_live_result_sets(endpoint_contract, packet_result_sets)
    domain_parameters, transport_parameters, request_parameters = _live_request_contract(
        endpoint_contract, kwargs
    )
    _endpoint, _endpoint_url, _headers = _live_endpoint_declaration(
        endpoint_cls,
        endpoint_contract,
        domain_parameters,
        transport_parameters,
    )
    contract_digest = owned_contract_sha256(endpoint_contract)
    attempt = _load_owned_replay_attempt(
        source,
        response_receipt_sha256,
        source_family="live",
        transport_kind="http_response",
        endpoint_id=endpoint_contract.endpoint_id,
        endpoint_slug=endpoint_contract.endpoint_slug,
        parameters=request_parameters,
        endpoint_contract_sha256=contract_digest,
    )
    response = NBAResponse(
        _replay_response_text(attempt),
        cast("int", attempt.status_code),
        "private-bronze://live-replay",
    )
    values, result_sets, live_lossless_landing = _parse_live_payloads(
        response,
        endpoint_contract=endpoint_contract,
        selected_result_sets=selected_result_sets,
        endpoint_slug=endpoint_contract.endpoint_slug,
        request_parameters=request_parameters,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256=attempt.endpoint_contract_sha256,
        allow_additive_drift=allow_additive_drift,
    )
    _verify_replayed_result_sets(attempt, result_sets)
    live_lossless_landing = live_lossless_landing.bind_response_receipt(attempt.receipt_sha256)
    return NbaApiPayload(
        values,
        response_receipt_sha256=attempt.receipt_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256=attempt.endpoint_contract_sha256,
        result_set_receipts=result_sets,
        live_lossless_landing=live_lossless_landing,
    )
