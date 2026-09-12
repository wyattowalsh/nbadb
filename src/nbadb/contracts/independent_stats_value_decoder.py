"""Independent, bounded decoding of exact pinned NBA Stats response values.

The decoder deliberately does not execute provider parser code.  Endpoint and
contract identities are admitted from the generated nbadb runtime registry;
the raw response bytes are then decoded through the explicit grammars below.
The resulting rows are suitable as a second value authority for typed-field
verification.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, cast

import polars as pl

from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_runtime_contracts,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nbadb.core.nba_api_contract import NbaApiEndpointContract


MAX_PARSER_INPUT_BYTES: Final = 64 * 1024 * 1024
MAX_JSON_DEPTH: Final = 64
MAX_JSON_NODES: Final = 2_000_000
MAX_JSON_CONTAINER_ITEMS: Final = 2_000_000
MAX_JSON_STRING_BYTES: Final = 4 * 1024 * 1024
MAX_JSON_TOTAL_STRING_BYTES: Final = 64 * 1024 * 1024
MAX_JSON_NUMBER_TOKEN_BYTES: Final = 64
MAX_JSON_INTEGER_ABS: Final = (1 << 63) - 1
MAX_RESULT_ROUTES: Final = 256
MAX_RESULT_HEADERS: Final = 4_096
MAX_RESULT_ROWS: Final = 1_000_000
MAX_TOTAL_OUTPUT_CELLS: Final = 10_000_000
MAX_TOTAL_OUTPUT_VALUE_BYTES: Final = 128 * 1024 * 1024
MAX_RESULT_CANONICAL_BYTES: Final = 128 * 1024 * 1024

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_RESULT_NAME_RE: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}\Z")
_METADATA_KEY_RE: Final = re.compile(r"[^a-z0-9]+")
_IDENTIFIER_RE: Final = re.compile(r"[^a-zA-Z0-9]+")

_OBSERVED_PER_SET_ANOMALY_CODES: Final = frozenset(
    {
        "additive_header",
        "duplicate_header",
        "heterogeneous_column",
        "ragged_row",
        "removed_header",
        "reordered_header",
        "non_sequence_row",
        "unsupported_header_shape",
        "unsupported_row_container",
    }
)
_OBSERVED_GLOBAL_ANOMALY_CODES: Final = frozenset(
    {
        *_OBSERVED_PER_SET_ANOMALY_CODES,
        "additive_result_set",
        "duplicate_result_set_name",
        "missing_result_set",
        "unknown_dynamic_response",
        "unrepresentable_typed_frame",
    }
)
_OBSERVED_RESULTS_DIGEST_CONTRACT: Final = "decoded_observed_stats_results_v1"
_OBSERVED_RESPONSE_DIGEST_CONTRACT: Final = "decoded_observed_stats_response_v1"

_TEAM_FIELDS: Final = (
    "teamId",
    "teamCity",
    "teamName",
    "teamTricode",
    "teamSlug",
)
_PLAYER_FIELDS: Final = (
    "personId",
    "firstName",
    "familyName",
    "nameI",
    "playerSlug",
    "position",
    "comment",
    "jerseyNum",
)

_GENERIC_BOXSCORE_ROOTS: Final = MappingProxyType(
    {
        "BoxScoreAdvancedV3": "boxScoreAdvanced",
        "BoxScoreDefensiveV2": "boxScoreDefensive",
        "BoxScoreFourFactorsV3": "boxScoreFourFactors",
        "BoxScoreHustleV2": "boxScoreHustle",
        "BoxScoreMiscV3": "boxScoreMisc",
        "BoxScorePlayerTrackV3": "boxScorePlayerTrack",
        "BoxScoreScoringV3": "boxScoreScoring",
        "BoxScoreUsageV3": "boxScoreUsage",
    }
)

CUSTOM_NESTED_ENDPOINT_IDS: Final = frozenset(
    {
        *_GENERIC_BOXSCORE_ROOTS,
        "BoxScoreMatchupsV3",
        "BoxScoreSummaryV3",
        "BoxScoreTraditionalV3",
        "GravityLeaders",
        "ISTStandings",
        "PlayByPlayV3",
        "ScheduleLeagueV2",
        "ScheduleLeagueV2Int",
        "ScoreboardV3",
    }
)
CUSTOM_NESTED_RESULT_ROUTE_COUNT: Final = 44


class IndependentStatsValueDecoderError(ValueError):
    """Raised when raw stats bytes cannot prove exact pinned result values."""


def _fail(message: str) -> IndependentStatsValueDecoderError:
    return IndependentStatsValueDecoderError(message)


def _is_exact_pinned_zero_header_route(
    *,
    canonical_ordinal: int,
    result_name: str,
) -> bool:
    """Return whether the DTO identity names one unique pinned zero-header route."""

    matches = 0
    for contract in pinned_runtime_contracts().values():
        if canonical_ordinal >= len(contract.result_sets):
            continue
        route = contract.result_sets[canonical_ordinal]
        if route.result_set_name == result_name and tuple(route.expected_columns) == ():
            matches += 1
    return matches == 1


def _canonical_json_bytes(value: object, *, maximum: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise _fail("decoded stats values are not bounded canonical JSON") from exc
    if len(encoded) > maximum:
        raise _fail("decoded stats canonical value bytes exceed their bound")
    return encoded


def _normalized_output_sha256(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    encoded = _canonical_json_bytes(
        {
            "headers": list(headers),
            "rows": [list(row) for row in rows],
        },
        maximum=MAX_RESULT_CANONICAL_BYTES,
    )
    return hashlib.sha256(encoded).hexdigest()


def _observed_output_sha256(
    *,
    raw_headers: object,
    raw_rows: object,
    anomaly_codes: Sequence[str],
) -> str:
    """Reproduce the production lossless-result digest from independent values."""

    encoded = _canonical_json_bytes(
        {
            "headers": raw_headers,
            "rows": raw_rows,
            "anomalies": list(anomaly_codes),
        },
        maximum=MAX_RESULT_CANONICAL_BYTES,
    )
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DecodedStatsResultV1:
    """One exact provider-ordered result decoded from immutable parser bytes.

    Rows are retained as private canonical JSON.  Each accessor returns a new
    object graph, so mutable JSON list/object cells cannot mutate the receipt.
    """

    provider_ordinal: int
    canonical_ordinal: int
    duplicate_name_ordinal: int
    result_name: str
    ordered_headers: tuple[str, ...]
    normalized_output_sha256: str
    _canonical_rows_json: bytes = field(repr=False)

    def __post_init__(self) -> None:
        for value, label, maximum in (
            (self.provider_ordinal, "provider ordinal", MAX_RESULT_ROUTES - 1),
            (self.canonical_ordinal, "canonical ordinal", MAX_RESULT_ROUTES - 1),
            (self.duplicate_name_ordinal, "duplicate-name ordinal", MAX_RESULT_ROUTES - 1),
        ):
            if type(value) is not int or value < 0 or value > maximum:
                raise _fail(f"decoded stats {label} is invalid")
        if self.duplicate_name_ordinal != 0:
            raise _fail("declared stats results cannot carry a duplicate-name ordinal")
        if (
            type(self.result_name) is not str
            or not self.result_name
            or self.result_name.strip() != self.result_name
        ):
            raise _fail("decoded stats result name is invalid")
        if (
            type(self.ordered_headers) is not tuple
            or len(self.ordered_headers) > MAX_RESULT_HEADERS
            or any(
                type(header) is not str or not header or header.strip() != header
                for header in self.ordered_headers
            )
            or len(set(self.ordered_headers)) != len(self.ordered_headers)
            or (
                not self.ordered_headers
                and not _is_exact_pinned_zero_header_route(
                    canonical_ordinal=self.canonical_ordinal,
                    result_name=self.result_name,
                )
            )
        ):
            raise _fail("decoded stats result headers are invalid")
        if (
            type(self.normalized_output_sha256) is not str
            or _SHA256_RE.fullmatch(self.normalized_output_sha256) is None
        ):
            raise _fail("decoded stats output digest is invalid")
        rows = self._decode_rows()
        if len(rows) > MAX_RESULT_ROWS or any(
            len(row) != len(self.ordered_headers) for row in rows
        ):
            raise _fail("decoded stats result row width is invalid")
        expected_digest = _normalized_output_sha256(self.ordered_headers, rows)
        if expected_digest != self.normalized_output_sha256:
            raise _fail("decoded stats output digest differs from its rows")

    @classmethod
    def _from_rows(
        cls,
        *,
        provider_ordinal: int,
        canonical_ordinal: int,
        result_name: str,
        ordered_headers: tuple[str, ...],
        rows: Sequence[Sequence[object]],
    ) -> DecodedStatsResultV1:
        canonical_rows = _canonical_json_bytes(
            [list(row) for row in rows], maximum=MAX_RESULT_CANONICAL_BYTES
        )
        return cls(
            provider_ordinal=provider_ordinal,
            canonical_ordinal=canonical_ordinal,
            duplicate_name_ordinal=0,
            result_name=result_name,
            ordered_headers=ordered_headers,
            normalized_output_sha256=_normalized_output_sha256(ordered_headers, rows),
            _canonical_rows_json=canonical_rows,
        )

    def _decode_rows(self) -> tuple[tuple[object, ...], ...]:
        if (
            type(self._canonical_rows_json) is not bytes
            or not self._canonical_rows_json
            or len(self._canonical_rows_json) > MAX_RESULT_CANONICAL_BYTES
        ):
            raise _fail("decoded stats canonical rows are invalid")
        value = _decode_json_bytes(self._canonical_rows_json, require_object=False)
        if type(value) is not list:
            raise _fail("decoded stats canonical rows are not an array")
        rows: list[tuple[object, ...]] = []
        for row in value:
            if type(row) is not list:
                raise _fail("decoded stats canonical row is not an array")
            rows.append(tuple(cast("list[object]", row)))
        return tuple(rows)

    @property
    def name(self) -> str:
        """Return the exact declared result name."""

        return self.result_name

    @property
    def rows(self) -> tuple[tuple[object, ...], ...]:
        """Return a mutation-isolated tuple of exact JSON-compatible rows."""

        return self._decode_rows()

    @property
    def records(self) -> tuple[Mapping[str, object], ...]:
        """Return immutable header/value records in exact header order."""

        return tuple(
            MappingProxyType(dict(zip(self.ordered_headers, row, strict=True)))
            for row in self._decode_rows()
        )

    @property
    def row_count(self) -> int:
        """Return the exact decoded row denominator, including zero."""

        return len(self._decode_rows())

    @property
    def canonical_rows_json(self) -> bytes:
        """Return the immutable canonical row representation."""

        return self._canonical_rows_json


ObservedStatsPresence = Literal["present", "present_empty", "missing"]
ObservedStatsResponseMode = Literal["declared_result_sets", "unknown_dynamic_response"]


@dataclass(frozen=True, slots=True)
class DecodedObservedStatsResultV1:
    """One observed result retained independently without schema projection.

    Provider and canonical ordinals are nullable by design: a missing expected
    result has no provider ordinal, while an additive or duplicate provider
    result has no unambiguous canonical ordinal. The exact raw header and row
    containers live in private canonical JSON. This preserves unsupported
    objects/scalars, non-sequence row occurrences, duplicate headers, ragged
    rows, nested values, and zero-width multiplicity without exposing mutable
    authority.
    """

    provider_ordinal: int | None
    canonical_ordinal: int | None
    duplicate_name_ordinal: int
    result_name: str
    response_mode: ObservedStatsResponseMode
    presence: ObservedStatsPresence
    ordered_headers: tuple[str, ...]
    effective_header_names: tuple[str | None, ...]
    anomaly_codes: tuple[str, ...]
    normalized_output_sha256: str
    _canonical_raw_headers_json: bytes = field(repr=False)
    _canonical_rows_json: bytes = field(repr=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider_ordinal, "provider ordinal"),
            (self.canonical_ordinal, "canonical ordinal"),
        ):
            if value is not None and (
                type(value) is not int or value < 0 or value >= MAX_RESULT_ROUTES
            ):
                raise _fail(f"observed stats {label} is invalid")
        if (
            type(self.duplicate_name_ordinal) is not int
            or self.duplicate_name_ordinal < 0
            or self.duplicate_name_ordinal >= MAX_RESULT_ROUTES
        ):
            raise _fail("observed stats duplicate-name ordinal is invalid")
        if type(self.result_name) is not str or _RESULT_NAME_RE.fullmatch(self.result_name) is None:
            raise _fail("observed stats result name is invalid")
        if type(self.response_mode) is not str or self.response_mode not in {
            "declared_result_sets",
            "unknown_dynamic_response",
        }:
            raise _fail("observed stats result response mode is invalid")
        if type(self.presence) is not str or self.presence not in {
            "present",
            "present_empty",
            "missing",
        }:
            raise _fail("observed stats result presence is invalid")
        if (
            type(self.ordered_headers) is not tuple
            or len(self.ordered_headers) > MAX_RESULT_HEADERS
            or any(type(header) is not str for header in self.ordered_headers)
        ):
            raise _fail("observed stats result headers are invalid")
        if (
            type(self.effective_header_names) is not tuple
            or len(self.effective_header_names) > MAX_RESULT_HEADERS
            or any(
                name is not None and type(name) is not str for name in self.effective_header_names
            )
            or self.ordered_headers
            != tuple(name for name in self.effective_header_names if name is not None)
        ):
            raise _fail("observed stats effective header names are invalid")
        if (
            type(self.anomaly_codes) is not tuple
            or any(
                type(code) is not str or code not in _OBSERVED_PER_SET_ANOMALY_CODES
                for code in self.anomaly_codes
            )
            or self.anomaly_codes != tuple(sorted(set(self.anomaly_codes)))
        ):
            raise _fail("observed stats per-result anomaly codes are invalid")
        if (
            type(self.normalized_output_sha256) is not str
            or _SHA256_RE.fullmatch(self.normalized_output_sha256) is None
        ):
            raise _fail("observed stats output digest is invalid")

        raw_headers = self._decode_raw_headers()
        raw_rows = self._decode_raw_rows()
        effective_header_names, _header_values = _observed_legacy_header_details(raw_headers)
        if effective_header_names != self.effective_header_names:
            raise _fail("observed stats raw headers differ from their ordered projection")
        if self.ordered_headers != tuple(
            name for name in self.effective_header_names if name is not None
        ):
            raise _fail("observed stats ordered headers differ from their effective names")
        row_occurrences = raw_rows if type(raw_rows) is list else []
        if self.presence == "missing":
            if (
                self.provider_ordinal is not None
                or self.canonical_ordinal is None
                or self.duplicate_name_ordinal != 0
                or raw_rows != []
                or self.anomaly_codes
                or raw_headers != list(self.ordered_headers)
            ):
                raise _fail("observed stats missing-result identity is invalid")
            expected_digest = _normalized_output_sha256(self.ordered_headers, ())
        else:
            if self.provider_ordinal is None:
                raise _fail("observed stats present result lacks a provider ordinal")
            if self.canonical_ordinal is not None and self.duplicate_name_ordinal != 0:
                raise _fail("observed stats duplicate result has a canonical ordinal")
            expected_presence = "present" if row_occurrences else "present_empty"
            if self.presence != expected_presence:
                raise _fail("observed stats result presence differs from its raw row container")
            if self.response_mode == "unknown_dynamic_response":
                if (
                    self.canonical_ordinal is not None
                    or self.anomaly_codes
                    or type(raw_headers) is not list
                    or any(
                        type(header) is not str or not header or header.strip() != header
                        for header in cast("list[object]", raw_headers)
                    )
                    or type(raw_rows) is not list
                    or any(
                        type(row) is not list
                        or len(cast("list[object]", row)) != len(self.ordered_headers)
                        for row in cast("list[object]", raw_rows)
                    )
                ):
                    raise _fail("observed unknown-dynamic result grammar is invalid")
                expected_digest = _normalized_output_sha256(
                    self.ordered_headers,
                    cast("list[list[object]]", raw_rows),
                )
            else:
                expected_anomalies = _observed_per_set_anomalies(
                    expected_headers=None,
                    raw_headers=raw_headers,
                    observed_header_names=self.effective_header_names,
                    raw_rows=raw_rows,
                    compare_expected_headers=False,
                )
                structural_anomalies = tuple(
                    code
                    for code in expected_anomalies
                    if code
                    in {
                        "duplicate_header",
                        "heterogeneous_column",
                        "non_sequence_row",
                        "ragged_row",
                        "unsupported_header_shape",
                        "unsupported_row_container",
                    }
                )
                observed_structural = tuple(
                    code
                    for code in self.anomaly_codes
                    if code
                    in {
                        "duplicate_header",
                        "heterogeneous_column",
                        "non_sequence_row",
                        "ragged_row",
                        "unsupported_header_shape",
                        "unsupported_row_container",
                    }
                )
                if structural_anomalies != observed_structural:
                    raise _fail("observed stats structural anomalies differ from raw containers")
                expected_digest = _observed_output_sha256(
                    raw_headers=raw_headers,
                    raw_rows=raw_rows,
                    anomaly_codes=self.anomaly_codes,
                )
        if expected_digest != self.normalized_output_sha256:
            raise _fail("observed stats output digest differs from its raw values")

    @classmethod
    def _from_present(
        cls,
        *,
        provider_ordinal: int,
        canonical_ordinal: int | None,
        duplicate_name_ordinal: int,
        result_name: str,
        response_mode: ObservedStatsResponseMode,
        raw_headers: object,
        ordered_headers: tuple[str, ...],
        effective_header_names: tuple[str | None, ...],
        raw_rows: object,
        anomaly_codes: tuple[str, ...],
    ) -> DecodedObservedStatsResultV1:
        row_count = len(raw_rows) if type(raw_rows) is list else 0
        return cls(
            provider_ordinal=provider_ordinal,
            canonical_ordinal=canonical_ordinal,
            duplicate_name_ordinal=duplicate_name_ordinal,
            result_name=result_name,
            response_mode=response_mode,
            presence="present" if row_count else "present_empty",
            ordered_headers=ordered_headers,
            effective_header_names=effective_header_names,
            anomaly_codes=anomaly_codes,
            normalized_output_sha256=(
                _normalized_output_sha256(
                    cast("list[str]", raw_headers),
                    cast("list[list[object]]", raw_rows),
                )
                if response_mode == "unknown_dynamic_response"
                else _observed_output_sha256(
                    raw_headers=raw_headers,
                    raw_rows=raw_rows,
                    anomaly_codes=anomaly_codes,
                )
            ),
            _canonical_raw_headers_json=_canonical_json_bytes(
                raw_headers, maximum=MAX_RESULT_CANONICAL_BYTES
            ),
            _canonical_rows_json=_canonical_json_bytes(
                raw_rows, maximum=MAX_RESULT_CANONICAL_BYTES
            ),
        )

    @classmethod
    def _from_missing(
        cls,
        *,
        canonical_ordinal: int,
        result_name: str,
        ordered_headers: tuple[str, ...],
    ) -> DecodedObservedStatsResultV1:
        return cls(
            provider_ordinal=None,
            canonical_ordinal=canonical_ordinal,
            duplicate_name_ordinal=0,
            result_name=result_name,
            response_mode="declared_result_sets",
            presence="missing",
            ordered_headers=ordered_headers,
            effective_header_names=ordered_headers,
            anomaly_codes=(),
            normalized_output_sha256=_normalized_output_sha256(ordered_headers, ()),
            _canonical_raw_headers_json=_canonical_json_bytes(
                list(ordered_headers), maximum=MAX_RESULT_CANONICAL_BYTES
            ),
            _canonical_rows_json=b"[]",
        )

    def _decode_raw_headers(self) -> object:
        value = _decode_json_bytes(self._canonical_raw_headers_json, require_object=False)
        return value

    def _decode_raw_rows(self) -> object:
        value = _decode_json_bytes(self._canonical_rows_json, require_object=False)
        return value

    def _decode_rows(self) -> tuple[object, ...]:
        value = self._decode_raw_rows()
        if type(value) is not list:
            return ()
        rows: list[object] = []
        cells = 0
        for raw_row in cast("list[object]", value):
            if type(raw_row) is list:
                row = cast("list[object]", raw_row)
                if len(row) > MAX_RESULT_HEADERS:
                    raise _fail("observed stats canonical row width exceeds its bound")
                cells += len(row)
                isolated: object = tuple(row)
            else:
                isolated = raw_row
            if cells > MAX_TOTAL_OUTPUT_CELLS:
                raise _fail("observed stats canonical rows exceed their cell bound")
            rows.append(isolated)
        if len(rows) > MAX_RESULT_ROWS:
            raise _fail("observed stats canonical rows exceed their row bound")
        return tuple(rows)

    @property
    def name(self) -> str:
        """Return the exact observed result name."""

        return self.result_name

    @property
    def rows(self) -> tuple[object, ...]:
        """Return every list-container row occurrence, including non-sequences."""

        return self._decode_rows()

    @property
    def row_count(self) -> int:
        """Return the exact row multiplicity, including zero-width rows."""

        raw_rows = self._decode_raw_rows()
        return len(raw_rows) if type(raw_rows) is list else 0

    @property
    def cell_count(self) -> int:
        """Return the exact ragged cell denominator."""

        return sum(len(row) for row in self._decode_rows() if type(row) is tuple)

    @property
    def canonical_raw_headers_json(self) -> bytes:
        """Return immutable canonical bytes for the unprojected raw headers."""

        return self._canonical_raw_headers_json

    @property
    def raw_headers(self) -> tuple[object, ...]:
        """Return raw header items when the parser container is an array."""

        raw_headers = self._decode_raw_headers()
        return tuple(raw_headers) if type(raw_headers) is list else ()

    @property
    def raw_header_container(self) -> object:
        """Return a mutation-isolated copy of the exact raw header container."""

        return self._decode_raw_headers()

    @property
    def raw_header_container_kind(self) -> str:
        """Return the exact JSON kind of the raw header container."""

        return _json_value_kind(self._decode_raw_headers())

    @property
    def fallback_header_values(self) -> tuple[object, ...]:
        """Return the exact header values emitted by the lossless frame."""

        _names, values = _observed_legacy_header_details(self._decode_raw_headers())
        return values

    @property
    def raw_row_container(self) -> object:
        """Return a mutation-isolated copy of the exact raw row container."""

        return self._decode_raw_rows()

    @property
    def raw_row_container_kind(self) -> str:
        """Return the exact JSON kind of the raw row container."""

        return _json_value_kind(self._decode_raw_rows())

    @property
    def sequence_rows_by_ordinal(self) -> tuple[tuple[int, tuple[object, ...]], ...]:
        """Return exact sequence rows without erasing non-sequence ordinals."""

        return tuple(
            (ordinal, row) for ordinal, row in enumerate(self._decode_rows()) if type(row) is tuple
        )

    @property
    def canonical_rows_json(self) -> bytes:
        """Return immutable canonical bytes for the exact raw row container."""

        return self._canonical_rows_json

    @property
    def canonical_raw_rows_json(self) -> bytes:
        """Return immutable canonical bytes for the exact raw row container."""

        return self._canonical_rows_json


def _revalidate_observed_result(
    result: object,
) -> DecodedObservedStatsResultV1:
    if type(result) is not DecodedObservedStatsResultV1:
        raise _fail("observed stats response contains a foreign result DTO")
    exact = result
    return DecodedObservedStatsResultV1(
        provider_ordinal=exact.provider_ordinal,
        canonical_ordinal=exact.canonical_ordinal,
        duplicate_name_ordinal=exact.duplicate_name_ordinal,
        result_name=exact.result_name,
        response_mode=exact.response_mode,
        presence=exact.presence,
        ordered_headers=exact.ordered_headers,
        effective_header_names=exact.effective_header_names,
        anomaly_codes=exact.anomaly_codes,
        normalized_output_sha256=exact.normalized_output_sha256,
        _canonical_raw_headers_json=exact.canonical_raw_headers_json,
        _canonical_rows_json=exact.canonical_rows_json,
    )


def _observed_result_identity(result: DecodedObservedStatsResultV1) -> dict[str, object]:
    return {
        "provider_ordinal": result.provider_ordinal,
        "canonical_ordinal": result.canonical_ordinal,
        "duplicate_name_ordinal": result.duplicate_name_ordinal,
        "result_name": result.result_name,
        "response_mode": result.response_mode,
        "presence": result.presence,
        "ordered_headers": list(result.ordered_headers),
        "effective_header_names": list(result.effective_header_names),
        "anomaly_codes": list(result.anomaly_codes),
        "normalized_output_sha256": result.normalized_output_sha256,
        "raw_header_container_kind": result.raw_header_container_kind,
        "raw_row_container_kind": result.raw_row_container_kind,
        "raw_row_occurrence_count": result.row_count,
        "sequence_row_count": len(result.sequence_rows_by_ordinal),
        "cell_count": result.cell_count,
        "raw_headers_sha256": hashlib.sha256(result.canonical_raw_headers_json).hexdigest(),
        "rows_sha256": hashlib.sha256(result.canonical_rows_json).hexdigest(),
    }


def _observed_results_sha256(results: Sequence[DecodedObservedStatsResultV1]) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            {
                "contract_id": _OBSERVED_RESULTS_DIGEST_CONTRACT,
                "results": [_observed_result_identity(result) for result in results],
            },
            maximum=MAX_RESULT_CANONICAL_BYTES,
        )
    ).hexdigest()


def _observed_typed_frame_is_representable(
    result: DecodedObservedStatsResultV1,
    *,
    expected_headers: tuple[str, ...],
) -> bool:
    """Independently apply the pinned typed-wide construction boundary."""

    if result.provider_ordinal is None:
        return True
    if not expected_headers or result.effective_header_names != expected_headers:
        return False
    raw_headers = result.raw_header_container
    raw_rows = result.raw_row_container
    if type(raw_headers) is not list or type(raw_rows) is not list:
        return False
    if any(type(row) is not list or len(row) != len(expected_headers) for row in raw_rows):
        return False
    rows = cast("list[list[object]]", raw_rows)
    if not rows:
        return True
    try:
        pl.DataFrame(
            rows,
            schema=list(expected_headers),
            orient="row",
            infer_schema_length=None,
        )
    except (TypeError, ValueError, pl.exceptions.PolarsError):
        return False
    return True


def _observed_global_reason_codes(
    *,
    results: Sequence[DecodedObservedStatsResultV1],
    expected_headers_by_name: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    expected_names = tuple(expected_headers_by_name)
    provider_names = [
        result.result_name for result in results if result.provider_ordinal is not None
    ]
    provider_counts = Counter(provider_names)
    expected_counts = Counter(expected_names)
    reasons = {
        code
        for result in results
        if result.provider_ordinal is not None
        for code in result.anomaly_codes
    }
    if provider_counts - expected_counts:
        reasons.add("additive_result_set")
    if expected_counts - provider_counts:
        reasons.add("missing_result_set")
    if any(count > 1 for count in provider_counts.values()):
        reasons.add("duplicate_result_set_name")
    if not reasons and any(
        not _observed_typed_frame_is_representable(
            result,
            expected_headers=expected_headers_by_name[result.result_name],
        )
        for result in results
        if result.provider_ordinal is not None
    ):
        reasons.add("unrepresentable_typed_frame")
    return tuple(sorted(reasons))


def _observed_response_sha256(
    *,
    endpoint_id: str,
    endpoint_slug: str,
    response_mode: ObservedStatsResponseMode,
    provider_result_set_count: int,
    expected_result_set_count: int,
    reason_codes: Sequence[str],
    results_sha256: str,
) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            {
                "contract_id": _OBSERVED_RESPONSE_DIGEST_CONTRACT,
                "endpoint_id": endpoint_id,
                "endpoint_slug": endpoint_slug,
                "response_mode": response_mode,
                "provider_result_set_count": provider_result_set_count,
                "expected_result_set_count": expected_result_set_count,
                "reason_codes": list(reason_codes),
                "results_sha256": results_sha256,
            },
            maximum=MAX_RESULT_CANONICAL_BYTES,
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class DecodedObservedStatsResponseV1:
    """Whole-response evidence for one independently decoded stats fallback."""

    endpoint_id: str
    endpoint_slug: str
    response_mode: ObservedStatsResponseMode
    provider_result_set_count: int
    expected_result_set_count: int
    reason_codes: tuple[str, ...]
    results: tuple[DecodedObservedStatsResultV1, ...]
    results_sha256: str
    response_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.endpoint_id) is not str
            or not self.endpoint_id
            or self.endpoint_id.strip() != self.endpoint_id
            or type(self.endpoint_slug) is not str
            or not self.endpoint_slug
            or self.endpoint_slug.strip() != self.endpoint_slug
        ):
            raise _fail("observed stats response endpoint identity is invalid")
        if type(self.response_mode) is not str or self.response_mode not in {
            "declared_result_sets",
            "unknown_dynamic_response",
        }:
            raise _fail("observed stats response mode is invalid")
        minimum_expected_results = 0 if self.response_mode == "unknown_dynamic_response" else 1
        for value, label, minimum in (
            (self.provider_result_set_count, "provider result count", 0),
            (
                self.expected_result_set_count,
                "expected result count",
                minimum_expected_results,
            ),
        ):
            if type(value) is not int or value < minimum or value > MAX_RESULT_ROUTES:
                raise _fail(f"observed stats response {label} is invalid")
        if (
            type(self.reason_codes) is not tuple
            or any(
                type(code) is not str or code not in _OBSERVED_GLOBAL_ANOMALY_CODES
                for code in self.reason_codes
            )
            or not self.reason_codes
            or self.reason_codes != tuple(sorted(set(self.reason_codes)))
        ):
            raise _fail("observed stats response reason codes are invalid")
        if (
            type(self.results) is not tuple
            or (not self.results and self.response_mode != "unknown_dynamic_response")
            or len(self.results) > MAX_RESULT_ROUTES
        ):
            raise _fail("observed stats response result inventory is invalid")
        if (
            type(self.results_sha256) is not str
            or _SHA256_RE.fullmatch(self.results_sha256) is None
            or type(self.response_sha256) is not str
            or _SHA256_RE.fullmatch(self.response_sha256) is None
        ):
            raise _fail("observed stats response digest is invalid")

        contracts = pinned_runtime_contracts()
        contract = contracts.get(self.endpoint_id)
        if (
            contract is None
            or contract.endpoint_slug != self.endpoint_slug
            or contract.response_mode != self.response_mode
            or len(contract.result_sets) != self.expected_result_set_count
        ):
            raise _fail("observed stats response differs from its pinned endpoint contract")
        expected_names: list[str] = []
        expected_headers: list[tuple[str, ...]] = []
        for route in contract.result_sets:
            name = route.result_set_name
            if type(name) is not str or _RESULT_NAME_RE.fullmatch(name) is None:
                raise _fail("observed stats response pinned result name is invalid")
            expected_names.append(name)
            expected_headers.append(tuple(route.expected_columns))

        validated = tuple(_revalidate_observed_result(result) for result in self.results)
        object.__setattr__(self, "results", validated)
        if any(result.response_mode != self.response_mode for result in validated):
            raise _fail("observed stats response mixes result response modes")
        provider_results = validated[: self.provider_result_set_count]
        missing_results = validated[self.provider_result_set_count :]
        if (
            len(provider_results) != self.provider_result_set_count
            or any(result.provider_ordinal is None for result in provider_results)
            or any(result.provider_ordinal is not None for result in missing_results)
            or tuple(result.provider_ordinal for result in provider_results)
            != tuple(range(self.provider_result_set_count))
        ):
            raise _fail("observed stats response provider order is incomplete")

        provider_counts = Counter(result.result_name for result in provider_results)
        duplicate_ordinals: Counter[str] = Counter()
        for result in provider_results:
            if result.duplicate_name_ordinal != duplicate_ordinals[result.result_name]:
                raise _fail("observed stats response duplicate-name order is incomplete")
            duplicate_ordinals[result.result_name] += 1
            if self.response_mode == "unknown_dynamic_response":
                expected_ordinal = None
                required_canonical = None
            else:
                try:
                    expected_ordinal = expected_names.index(result.result_name)
                except ValueError:
                    expected_ordinal = None
                required_canonical = (
                    expected_ordinal
                    if expected_ordinal is not None and provider_counts[result.result_name] == 1
                    else None
                )
            if result.canonical_ordinal != required_canonical:
                raise _fail("observed stats response canonical provider binding is invalid")
            if self.response_mode == "unknown_dynamic_response":
                if result.anomaly_codes:
                    raise _fail("observed unknown-dynamic result invented drift reasons")
            else:
                expected_result_headers = (
                    None if expected_ordinal is None else expected_headers[expected_ordinal]
                )
                expected_anomalies = _observed_per_set_anomalies(
                    expected_headers=expected_result_headers,
                    raw_headers=result.raw_header_container,
                    observed_header_names=result.effective_header_names,
                    raw_rows=result.raw_row_container,
                )
                if result.anomaly_codes != expected_anomalies:
                    raise _fail("observed stats result anomalies differ from exact decoded drift")

        if self.response_mode == "unknown_dynamic_response":
            if missing_results or expected_names or self.expected_result_set_count != 0:
                raise _fail("observed unknown-dynamic response invented expected results")
            expected_reasons = ("unknown_dynamic_response",)
        else:
            missing_by_name = {result.result_name: result for result in missing_results}
            required_missing = {name for name in expected_names if provider_counts[name] == 0}
            if (
                len(missing_by_name) != len(missing_results)
                or set(missing_by_name) != required_missing
            ):
                raise _fail("observed stats response missing-result inventory is invalid")
            for canonical_ordinal, name in enumerate(expected_names):
                missing = missing_by_name.get(name)
                if missing is not None and (
                    missing.canonical_ordinal != canonical_ordinal
                    or missing.ordered_headers != expected_headers[canonical_ordinal]
                    or missing.presence != "missing"
                ):
                    raise _fail("observed stats response missing-result binding is invalid")
            expected_reasons = _observed_global_reason_codes(
                results=validated,
                expected_headers_by_name=dict(zip(expected_names, expected_headers, strict=True)),
            )
        if self.reason_codes != expected_reasons:
            raise _fail("observed stats response reasons differ from exact decoded drift")
        expected_results_sha256 = _observed_results_sha256(validated)
        if self.results_sha256 != expected_results_sha256:
            raise _fail("observed stats response result digest is invalid")
        expected_response_sha256 = _observed_response_sha256(
            endpoint_id=self.endpoint_id,
            endpoint_slug=self.endpoint_slug,
            response_mode=self.response_mode,
            provider_result_set_count=self.provider_result_set_count,
            expected_result_set_count=self.expected_result_set_count,
            reason_codes=self.reason_codes,
            results_sha256=self.results_sha256,
        )
        if self.response_sha256 != expected_response_sha256:
            raise _fail("observed stats response digest differs from its evidence")

    @classmethod
    def _build(
        cls,
        *,
        endpoint_id: str,
        endpoint_slug: str,
        response_mode: ObservedStatsResponseMode,
        expected_headers_by_name: Mapping[str, tuple[str, ...]],
        results: tuple[DecodedObservedStatsResultV1, ...],
    ) -> DecodedObservedStatsResponseV1:
        provider_result_set_count = sum(result.provider_ordinal is not None for result in results)
        reason_codes = (
            ("unknown_dynamic_response",)
            if response_mode == "unknown_dynamic_response"
            else _observed_global_reason_codes(
                results=results,
                expected_headers_by_name=expected_headers_by_name,
            )
        )
        results_sha256 = _observed_results_sha256(results)
        return cls(
            endpoint_id=endpoint_id,
            endpoint_slug=endpoint_slug,
            response_mode=response_mode,
            provider_result_set_count=provider_result_set_count,
            expected_result_set_count=len(expected_headers_by_name),
            reason_codes=reason_codes,
            results=results,
            results_sha256=results_sha256,
            response_sha256=_observed_response_sha256(
                endpoint_id=endpoint_id,
                endpoint_slug=endpoint_slug,
                response_mode=response_mode,
                provider_result_set_count=provider_result_set_count,
                expected_result_set_count=len(expected_headers_by_name),
                reason_codes=reason_codes,
                results_sha256=results_sha256,
            ),
        )


def _reject_duplicate_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("stats parser input contains duplicate JSON object keys")
        result[key] = value
    return result


def _bounded_json_integer(token: str) -> int:
    if len(token.encode("ascii", errors="strict")) > MAX_JSON_NUMBER_TOKEN_BYTES:
        raise _fail("stats parser input contains an unbounded integer token")
    try:
        value = int(token)
    except ValueError as exc:  # pragma: no cover - json validates numeric grammar first
        raise _fail("stats parser input contains an invalid integer token") from exc
    if abs(value) > MAX_JSON_INTEGER_ABS:
        raise _fail("stats parser input integer exceeds the exact bound")
    return value


def _bounded_json_float(token: str) -> float:
    if len(token.encode("ascii", errors="strict")) > MAX_JSON_NUMBER_TOKEN_BYTES:
        raise _fail("stats parser input contains an unbounded number token")
    try:
        value = float(token)
    except ValueError as exc:  # pragma: no cover - json validates numeric grammar first
        raise _fail("stats parser input contains an invalid number token") from exc
    if not math.isfinite(value):
        raise _fail("stats parser input contains a non-finite number")
    return value


def _reject_json_constant(_token: str) -> object:
    raise _fail("stats parser input contains a non-finite JSON constant")


def _validate_json_budget(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    container_items = 0
    string_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise _fail("stats parser input JSON node budget is exhausted")
        if depth > MAX_JSON_DEPTH:
            raise _fail("stats parser input JSON depth exceeds its bound")
        if type(item) is dict:
            exact = cast("dict[str, object]", item)
            container_items += len(exact)
            for key, child in exact.items():
                if type(key) is not str:
                    raise _fail("stats parser input object has a foreign key type")
                encoded = key.encode("utf-8", errors="strict")
                if len(encoded) > MAX_JSON_STRING_BYTES:
                    raise _fail("stats parser input key exceeds its byte bound")
                string_bytes += len(encoded)
                stack.append((child, depth + 1))
        elif type(item) is list:
            exact_list = cast("list[object]", item)
            container_items += len(exact_list)
            stack.extend((child, depth + 1) for child in exact_list)
        elif type(item) is str:
            encoded = item.encode("utf-8", errors="strict")
            if len(encoded) > MAX_JSON_STRING_BYTES:
                raise _fail("stats parser input string exceeds its byte bound")
            string_bytes += len(encoded)
        elif type(item) is int:
            if abs(item) > MAX_JSON_INTEGER_ABS:
                raise _fail("stats parser input integer exceeds the exact bound")
        elif type(item) is float:
            if not math.isfinite(item):
                raise _fail("stats parser input contains a non-finite number")
        elif item is not None and type(item) is not bool:
            raise _fail("stats parser input contains a non-JSON value")
        if container_items > MAX_JSON_CONTAINER_ITEMS:
            raise _fail("stats parser input container budget is exhausted")
        if string_bytes > MAX_JSON_TOTAL_STRING_BYTES:
            raise _fail("stats parser input cumulative string budget is exhausted")


def _decode_json_bytes(parser_input: bytes, *, require_object: bool) -> object:
    if (
        type(parser_input) is not bytes
        or not parser_input
        or len(parser_input) > MAX_PARSER_INPUT_BYTES
    ):
        raise _fail("stats parser input bytes are absent or exceed their bound")
    try:
        value = json.loads(
            parser_input,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_int=_bounded_json_integer,
            parse_float=_bounded_json_float,
            parse_constant=_reject_json_constant,
        )
    except IndependentStatsValueDecoderError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, MemoryError) as exc:
        raise _fail("stats parser input cannot be decoded as exact JSON") from exc
    _validate_json_budget(value)
    if require_object and type(value) is not dict:
        raise _fail("stats parser input root must be an object")
    return value


@dataclass(slots=True)
class _OutputBudget:
    rows: int = 0
    cells: int = 0
    value_bytes: int = 0

    def add_row(self, row: Sequence[object], *, width: int) -> tuple[object, ...]:
        if type(width) is not int or width < 0 or width > MAX_RESULT_HEADERS:
            raise _fail("stats result width is invalid")
        if len(row) != width:
            raise _fail("stats result row width differs from its headers")
        return self.add_observed_row(row)

    def add_observed_row(self, row: Sequence[object]) -> tuple[object, ...]:
        """Consume one bounded row without projecting it to a declared width."""

        width = len(row)
        if width > MAX_RESULT_HEADERS:
            raise _fail("observed stats result row width exceeds its bound")
        if self.rows >= MAX_RESULT_ROWS:
            raise _fail("stats result row budget is exhausted")
        if self.cells > MAX_TOTAL_OUTPUT_CELLS - width:
            raise _fail("stats result cumulative cell budget is exhausted")
        row_weight = sum(_json_value_upper_bound(value) for value in row)
        if self.value_bytes > MAX_TOTAL_OUTPUT_VALUE_BYTES - row_weight:
            raise _fail("stats result cumulative value-byte budget is exhausted")
        self.rows += 1
        self.cells += width
        self.value_bytes += row_weight
        return tuple(row)

    def add_observed_result(self, *, raw_headers: object, raw_rows: object) -> None:
        """Bound exact fallback containers before DTO canonical allocation."""

        header_count = len(raw_headers) if type(raw_headers) is list else 0
        if header_count > MAX_RESULT_HEADERS:
            raise _fail("observed stats raw header denominator exceeds its bound")
        row_count = len(raw_rows) if type(raw_rows) is list else 0
        if row_count > MAX_RESULT_ROWS or self.rows > MAX_RESULT_ROWS - row_count:
            raise _fail("stats result row budget is exhausted")
        cells = 0
        if type(raw_rows) is list:
            for raw_row in cast("list[object]", raw_rows):
                if type(raw_row) is not list:
                    continue
                width = len(cast("list[object]", raw_row))
                if width > MAX_RESULT_HEADERS:
                    raise _fail("observed stats result row width exceeds its bound")
                if cells > MAX_TOTAL_OUTPUT_CELLS - width:
                    raise _fail("stats result cumulative cell budget is exhausted")
                cells += width
        if self.cells > MAX_TOTAL_OUTPUT_CELLS - cells:
            raise _fail("stats result cumulative cell budget is exhausted")
        value_weight = _json_value_upper_bound(raw_headers) + _json_value_upper_bound(raw_rows)
        if self.value_bytes > MAX_TOTAL_OUTPUT_VALUE_BYTES - value_weight:
            raise _fail("stats result cumulative value-byte budget is exhausted")
        self.rows += row_count
        self.cells += cells
        self.value_bytes += value_weight


def _json_value_upper_bound(value: object) -> int:
    total = 0
    stack = [value]
    while stack:
        item = stack.pop()
        if item is None:
            total += 4
        elif type(item) is bool:
            total += 5
        elif type(item) is int:
            total += len(str(item))
        elif type(item) is float:
            total += len(repr(item)) + 2
        elif type(item) is str:
            total += 2 + 6 * len(item.encode("utf-8", errors="strict"))
        elif type(item) is list:
            exact_list = cast("list[object]", item)
            total += 2 + len(exact_list)
            stack.extend(exact_list)
        elif type(item) is dict:
            exact = cast("dict[str, object]", item)
            total += 2 + 2 * len(exact)
            for key, child in exact.items():
                total += 2 + 6 * len(key.encode("utf-8", errors="strict"))
                stack.append(child)
        else:  # pragma: no cover - input JSON validation guards this
            raise _fail("stats result contains a non-JSON value")
        if total > MAX_TOTAL_OUTPUT_VALUE_BYTES:
            raise _fail("stats result value exceeds its byte bound")
    return total


@dataclass(frozen=True, slots=True)
class _RawResult:
    name: str
    headers: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


def _object(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _fail(f"{label} must be an object")
    return cast("dict[str, object]", value)


def _array(value: object, *, label: str) -> list[object]:
    if type(value) is not list:
        raise _fail(f"{label} must be an array")
    exact = cast("list[object]", value)
    if len(exact) > MAX_RESULT_ROWS:
        raise _fail(f"{label} exceeds the row bound")
    return exact


def _required_object(parent: Mapping[str, object], key: str, *, label: str) -> dict[str, object]:
    if key not in parent:
        raise _fail(f"{label} is absent")
    return _object(parent[key], label=label)


def _optional_object(parent: Mapping[str, object], key: str, *, label: str) -> dict[str, object]:
    if key not in parent:
        return {}
    return _object(parent[key], label=label)


def _optional_array(parent: Mapping[str, object], key: str, *, label: str) -> list[object]:
    if key not in parent:
        return []
    return _array(parent[key], label=label)


def _values(record: Mapping[str, object], fields: Sequence[str]) -> tuple[object, ...]:
    return tuple(record.get(name) for name in fields)


def _headers_by_name(contract: NbaApiEndpointContract) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for route in contract.result_sets:
        name = route.result_set_name
        headers = tuple(route.expected_columns)
        if (
            type(name) is not str
            or not name
            or name in result
            or len(headers) > MAX_RESULT_HEADERS
            or any(
                type(header) is not str or not header or header.strip() != header
                for header in headers
            )
            or len(set(headers)) != len(headers)
        ):
            raise _fail("pinned stats result inventory is invalid")
        result[name] = headers
    if not result or len(result) > MAX_RESULT_ROUTES:
        raise _fail("pinned stats result inventory is absent or unbounded")
    return result


def _route_headers(headers_by_name: Mapping[str, tuple[str, ...]], name: str) -> tuple[str, ...]:
    headers = headers_by_name.get(name)
    if headers is None:
        raise _fail("custom stats parser requested an undeclared result route")
    return headers


def _require_header_prefix(headers: tuple[str, ...], prefix: tuple[str, ...]) -> tuple[str, ...]:
    if headers[: len(prefix)] != prefix:
        raise _fail("pinned custom stats header prefix is unsupported")
    return headers[len(prefix) :]


def _append_row(
    rows: list[tuple[object, ...]],
    values: Sequence[object],
    *,
    headers: tuple[str, ...],
    budget: _OutputBudget,
) -> None:
    rows.append(budget.add_row(values, width=len(headers)))


def _decode_generic_boxscore(
    *,
    endpoint_id: str,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[_RawResult, ...]:
    root_name = _GENERIC_BOXSCORE_ROOTS[endpoint_id]
    boxscore = _required_object(payload, root_name, label=f"{endpoint_id} root")
    player_headers = _route_headers(headers_by_name, "PlayerStats")
    team_headers = _route_headers(headers_by_name, "TeamStats")
    player_stat_fields = _require_header_prefix(
        player_headers, ("gameId",) + _TEAM_FIELDS + _PLAYER_FIELDS
    )
    team_stat_fields = _require_header_prefix(team_headers, ("gameId",) + _TEAM_FIELDS)
    game_id = boxscore.get("gameId")

    teams = {
        name: _required_object(boxscore, name, label=f"{endpoint_id} {name}")
        for name in ("homeTeam", "awayTeam")
    }
    team_rows: list[tuple[object, ...]] = []
    for team_name in ("homeTeam", "awayTeam"):
        team = teams[team_name]
        statistics = _optional_object(
            team, "statistics", label=f"{endpoint_id} {team_name} statistics"
        )
        _append_row(
            team_rows,
            (game_id,) + _values(team, _TEAM_FIELDS) + _values(statistics, team_stat_fields),
            headers=team_headers,
            budget=budget,
        )

    player_rows: list[tuple[object, ...]] = []
    for team_name in ("awayTeam", "homeTeam"):
        team = teams[team_name]
        players = _optional_array(team, "players", label=f"{endpoint_id} {team_name} players")
        for player_index, value in enumerate(players):
            player = _object(value, label=f"{endpoint_id} player {player_index}")
            statistics = _optional_object(
                player,
                "statistics",
                label=f"{endpoint_id} player {player_index} statistics",
            )
            _append_row(
                player_rows,
                (game_id,)
                + _values(team, _TEAM_FIELDS)
                + _values(player, _PLAYER_FIELDS)
                + _values(statistics, player_stat_fields),
                headers=player_headers,
                budget=budget,
            )
    return (
        _RawResult("PlayerStats", player_headers, tuple(player_rows)),
        _RawResult("TeamStats", team_headers, tuple(team_rows)),
    )


def _decode_traditional_boxscore(
    *,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[_RawResult, ...]:
    boxscore = _required_object(payload, "boxScoreTraditional", label="BoxScoreTraditionalV3 root")
    player_headers = _route_headers(headers_by_name, "PlayerStats")
    starter_headers = _route_headers(headers_by_name, "TeamStarterBenchStats")
    team_headers = _route_headers(headers_by_name, "TeamStats")
    player_stat_fields = _require_header_prefix(
        player_headers, ("gameId",) + _TEAM_FIELDS + _PLAYER_FIELDS
    )
    team_stat_fields = _require_header_prefix(team_headers, ("gameId",) + _TEAM_FIELDS)
    starter_tail = _require_header_prefix(starter_headers, ("gameId",) + _TEAM_FIELDS)
    if not starter_tail or starter_tail[-1] != "startersBench":
        raise _fail("pinned traditional starter/bench headers are unsupported")
    starter_stat_fields = starter_tail[:-1]
    game_id = boxscore.get("gameId")
    teams = {
        name: _required_object(boxscore, name, label=f"traditional {name}")
        for name in ("homeTeam", "awayTeam")
    }

    player_rows: list[tuple[object, ...]] = []
    team_rows: list[tuple[object, ...]] = []
    starter_rows: list[tuple[object, ...]] = []
    for team_name in ("homeTeam", "awayTeam"):
        team = teams[team_name]
        statistics = _optional_object(
            team, "statistics", label=f"traditional {team_name} statistics"
        )
        _append_row(
            team_rows,
            (game_id,) + _values(team, _TEAM_FIELDS) + _values(statistics, team_stat_fields),
            headers=team_headers,
            budget=budget,
        )
        players = _optional_array(team, "players", label=f"traditional {team_name} players")
        for player_index, value in enumerate(players):
            player = _object(value, label=f"traditional player {player_index}")
            player_statistics = _optional_object(
                player,
                "statistics",
                label=f"traditional player {player_index} statistics",
            )
            _append_row(
                player_rows,
                (game_id,)
                + _values(team, _TEAM_FIELDS)
                + _values(player, _PLAYER_FIELDS)
                + _values(player_statistics, player_stat_fields),
                headers=player_headers,
                budget=budget,
            )
        for source_name, label in (("starters", "Starters"), ("bench", "Bench")):
            source = team.get(source_name)
            if source is None:
                statistic_values: tuple[object, ...] = (None,) * len(starter_stat_fields)
            else:
                statistic_values = _values(
                    _object(source, label=f"traditional {team_name} {source_name}"),
                    starter_stat_fields,
                )
            _append_row(
                starter_rows,
                (game_id,) + _values(team, _TEAM_FIELDS) + statistic_values + (label,),
                headers=starter_headers,
                budget=budget,
            )
    return (
        _RawResult("PlayerStats", player_headers, tuple(player_rows)),
        _RawResult("TeamStarterBenchStats", starter_headers, tuple(starter_rows)),
        _RawResult("TeamStats", team_headers, tuple(team_rows)),
    )


def _filtered_keys(record: Mapping[str, object], excluded: frozenset[str]) -> tuple[str, ...]:
    return tuple(key for key in record if key not in excluded)


def _assert_exact_key_order(
    record: Mapping[str, object], expected: tuple[str, ...], *, excluded: frozenset[str], label: str
) -> None:
    if _filtered_keys(record, excluded) != expected:
        raise _fail(f"{label} key order differs from the pinned custom parser contract")


def _decode_matchups(
    *,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
    allow_header_drift: bool = False,
) -> tuple[_RawResult, ...]:
    top_level_keys = tuple(payload)
    if (
        "boxScoreMatchups" not in payload
        or len(top_level_keys) < 2
        or top_level_keys[1] != "boxScoreMatchups"
    ):
        raise _fail("matchups response does not bind its exact second-key root")
    root = _required_object(payload, "boxScoreMatchups", label="matchups root")
    if "gameId" not in root:
        raise _fail("matchups root omitted gameId")
    pinned_headers = _route_headers(headers_by_name, "PlayerStats")
    home = _required_object(root, "homeTeam", label="matchups homeTeam")
    away = _required_object(root, "awayTeam", label="matchups awayTeam")
    home_players = _array(home.get("players"), label="matchups homeTeam players")
    if not home_players:
        raise _fail("matchups header authority has no home player exemplar")
    first_player = _object(home_players[0], label="matchups first home player")
    first_matchups = _array(first_player.get("matchups"), label="matchups first player rows")
    if not first_matchups:
        raise _fail("matchups header authority has no matchup exemplar")
    first_matchup = _object(first_matchups[0], label="matchups first matchup")
    first_statistics = _required_object(
        first_matchup, "statistics", label="matchups first statistics"
    )

    team_keys = _filtered_keys(home, frozenset({"players", "statistics"}))
    player_keys = _filtered_keys(first_player, frozenset({"matchups"}))
    matchup_keys = _filtered_keys(first_matchup, frozenset({"statistics"}))
    statistics_keys = tuple(first_statistics)
    observed_headers = (
        ("gameId",)
        + team_keys
        + tuple(f"{name}Off" for name in player_keys)
        + tuple(f"{name}Def" for name in matchup_keys)
        + statistics_keys
    )
    if observed_headers != pinned_headers and not allow_header_drift:
        raise _fail("matchups dynamic header order differs from the pinned result route")
    headers = observed_headers if allow_header_drift else pinned_headers

    rows: list[tuple[object, ...]] = []
    for team_name, team in (("homeTeam", home), ("awayTeam", away)):
        _assert_exact_key_order(
            team,
            team_keys,
            excluded=frozenset({"players", "statistics"}),
            label=f"matchups {team_name}",
        )
        if "statistics" in team:
            raise _fail("matchups team statistics would drift row width from its headers")
        players = _array(team.get("players"), label=f"matchups {team_name} players")
        for player_index, value in enumerate(players):
            player = _object(value, label=f"matchups {team_name} player {player_index}")
            _assert_exact_key_order(
                player,
                player_keys,
                excluded=frozenset({"matchups"}),
                label=f"matchups {team_name} player {player_index}",
            )
            matchups = _array(player.get("matchups"), label=f"matchups {team_name} player matchups")
            for matchup_index, matchup_value in enumerate(matchups):
                matchup = _object(
                    matchup_value,
                    label=f"matchups {team_name} matchup {matchup_index}",
                )
                _assert_exact_key_order(
                    matchup,
                    matchup_keys,
                    excluded=frozenset({"statistics"}),
                    label=f"matchups {team_name} matchup {matchup_index}",
                )
                statistics = _required_object(
                    matchup,
                    "statistics",
                    label=f"matchups {team_name} matchup statistics",
                )
                if tuple(statistics) != statistics_keys:
                    raise _fail("matchups statistics order differs across rows")
                row = (
                    (root["gameId"],)
                    + tuple(team[key] for key in team_keys)
                    + tuple(player[key] for key in player_keys)
                    + tuple(matchup[key] for key in matchup_keys)
                    + tuple(statistics[key] for key in statistics_keys)
                )
                _append_row(rows, row, headers=headers, budget=budget)
    return (_RawResult("PlayerStats", headers, tuple(rows)),)


def _decode_summary(
    *,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[_RawResult, ...]:
    summary = _required_object(payload, "boxScoreSummary", label="box-score summary root")
    game_id = summary.get("gameId")
    results: list[_RawResult] = []

    game_summary_headers = _route_headers(headers_by_name, "GameSummary")
    game_summary_rows: list[tuple[object, ...]] = []
    _append_row(
        game_summary_rows,
        _values(summary, game_summary_headers),
        headers=game_summary_headers,
        budget=budget,
    )
    results.append(_RawResult("GameSummary", game_summary_headers, tuple(game_summary_rows)))

    game_info_headers = _route_headers(headers_by_name, "GameInfo")
    if game_info_headers != ("gameId", "gameDate", "attendance", "gameDuration"):
        raise _fail("pinned summary game-info headers are unsupported")
    game_info_rows: list[tuple[object, ...]] = []
    _append_row(
        game_info_rows,
        (game_id, summary.get("gameEt"), summary.get("attendance"), summary.get("duration")),
        headers=game_info_headers,
        budget=budget,
    )
    results.append(_RawResult("GameInfo", game_info_headers, tuple(game_info_rows)))

    arena_headers = _route_headers(headers_by_name, "ArenaInfo")
    if not arena_headers or arena_headers[0] != "gameId":
        raise _fail("pinned summary arena headers are unsupported")
    arena = _optional_object(summary, "arena", label="summary arena")
    arena_rows: list[tuple[object, ...]] = []
    _append_row(
        arena_rows,
        (game_id,) + _values(arena, arena_headers[1:]),
        headers=arena_headers,
        budget=budget,
    )
    results.append(_RawResult("ArenaInfo", arena_headers, tuple(arena_rows)))

    official_headers = _route_headers(headers_by_name, "Officials")
    if not official_headers or official_headers[0] != "gameId":
        raise _fail("pinned summary official headers are unsupported")
    official_rows: list[tuple[object, ...]] = []
    for index, value in enumerate(_optional_array(summary, "officials", label="summary officials")):
        official = _object(value, label=f"summary official {index}")
        _append_row(
            official_rows,
            (game_id,) + _values(official, official_headers[1:]),
            headers=official_headers,
            budget=budget,
        )
    results.append(_RawResult("Officials", official_headers, tuple(official_rows)))

    line_headers = _route_headers(headers_by_name, "LineScore")
    if line_headers[:1] != ("gameId",):
        raise _fail("pinned summary line-score headers are unsupported")
    line_rows: list[tuple[object, ...]] = []
    for team_name in ("homeTeam", "awayTeam"):
        team = _optional_object(summary, team_name, label=f"summary {team_name}")
        period_scores: list[object] = [None, None, None, None]
        for period_index, value in enumerate(
            _optional_array(team, "periods", label=f"summary {team_name} periods")
        ):
            period = _object(value, label=f"summary {team_name} period {period_index}")
            number = period.get("period", 0)
            if type(number) is not int:
                raise _fail("summary period number must be an exact integer")
            if 1 <= number <= 4:
                period_scores[number - 1] = period.get("score")
        row = (
            game_id,
            team.get("teamId"),
            team.get("teamCity"),
            team.get("teamName"),
            team.get("teamTricode"),
            team.get("teamSlug"),
            team.get("teamWins"),
            team.get("teamLosses"),
            *period_scores,
            team.get("score"),
        )
        _append_row(line_rows, row, headers=line_headers, budget=budget)
    results.append(_RawResult("LineScore", line_headers, tuple(line_rows)))

    inactive_headers = _route_headers(headers_by_name, "InactivePlayers")
    if inactive_headers[:2] != ("gameId", "teamId"):
        raise _fail("pinned summary inactive-player headers are unsupported")
    inactive_rows: list[tuple[object, ...]] = []
    for team_name in ("homeTeam", "awayTeam"):
        team = _optional_object(summary, team_name, label=f"summary {team_name}")
        for index, value in enumerate(
            _optional_array(team, "inactives", label=f"summary {team_name} inactives")
        ):
            inactive = _object(value, label=f"summary inactive player {index}")
            _append_row(
                inactive_rows,
                (game_id, team.get("teamId")) + _values(inactive, inactive_headers[2:]),
                headers=inactive_headers,
                budget=budget,
            )
    results.append(_RawResult("InactivePlayers", inactive_headers, tuple(inactive_rows)))

    meeting_headers = _route_headers(headers_by_name, "LastFiveMeetings")
    expected_meeting_headers = (
        "recencyOrder",
        "gameId",
        "gameTimeUTC",
        "gameEt",
        "gameStatus",
        "gameStatusText",
        "awayTeamId",
        "awayTeamCity",
        "awayTeamName",
        "awayTeamTricode",
        "awayTeamScore",
        "awayTeamWins",
        "awayTeamLosses",
        "homeTeamId",
        "homeTeamCity",
        "homeTeamName",
        "homeTeamTricode",
        "homeTeamScore",
        "homeTeamWins",
        "homeTeamLosses",
    )
    if meeting_headers != expected_meeting_headers:
        raise _fail("pinned summary meeting headers are unsupported")
    meetings_parent = _optional_object(
        summary, "lastFiveMeetings", label="summary last-five meetings"
    )
    meeting_rows: list[tuple[object, ...]] = []
    for index, value in enumerate(
        _optional_array(meetings_parent, "meetings", label="summary meetings")
    ):
        meeting = _object(value, label=f"summary meeting {index}")
        away_team = _optional_object(meeting, "awayTeam", label="summary meeting awayTeam")
        home_team = _optional_object(meeting, "homeTeam", label="summary meeting homeTeam")
        row = (
            meeting.get("recencyOrder"),
            meeting.get("gameId"),
            meeting.get("gameTimeUTC"),
            meeting.get("gameEt"),
            meeting.get("gameStatus"),
            meeting.get("gameStatusText"),
            away_team.get("teamId"),
            away_team.get("teamCity"),
            away_team.get("teamName"),
            away_team.get("teamTricode"),
            away_team.get("score"),
            away_team.get("wins"),
            away_team.get("losses"),
            home_team.get("teamId"),
            home_team.get("teamCity"),
            home_team.get("teamName"),
            home_team.get("teamTricode"),
            home_team.get("score"),
            home_team.get("wins"),
            home_team.get("losses"),
        )
        _append_row(meeting_rows, row, headers=meeting_headers, budget=budget)
    results.append(_RawResult("LastFiveMeetings", meeting_headers, tuple(meeting_rows)))

    other_headers = _route_headers(headers_by_name, "OtherStats")
    if other_headers[:5] != ("gameId", "teamId", "teamCity", "teamName", "teamTricode"):
        raise _fail("pinned summary other-stats headers are unsupported")
    postgame = _optional_object(summary, "postgameCharts", label="summary postgame charts")
    other_rows: list[tuple[object, ...]] = []
    for team_name in ("homeTeam", "awayTeam"):
        team = _optional_object(postgame, team_name, label=f"summary postgame {team_name}")
        statistics = _optional_object(
            team, "statistics", label=f"summary postgame {team_name} statistics"
        )
        row = (
            game_id,
            team.get("teamId"),
            team.get("teamCity"),
            team.get("teamName"),
            team.get("teamTricode"),
        ) + _values(statistics, other_headers[5:])
        _append_row(other_rows, row, headers=other_headers, budget=budget)
    results.append(_RawResult("OtherStats", other_headers, tuple(other_rows)))

    video_headers = _route_headers(headers_by_name, "AvailableVideo")
    if not video_headers or video_headers[0] != "gameId":
        raise _fail("pinned summary video headers are unsupported")
    video_rows: list[tuple[object, ...]] = []
    _append_row(
        video_rows,
        (game_id,) + _values(summary, video_headers[1:]),
        headers=video_headers,
        budget=budget,
    )
    results.append(_RawResult("AvailableVideo", video_headers, tuple(video_rows)))
    return tuple(results)


def _decode_play_by_play(
    *,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[_RawResult, ...]:
    game = _required_object(payload, "game", label="play-by-play game root")
    play_headers = _route_headers(headers_by_name, "PlayByPlay")
    if not play_headers or play_headers[0] != "gameId":
        raise _fail("pinned play-by-play headers are unsupported")
    rows: list[tuple[object, ...]] = []
    for index, value in enumerate(_optional_array(game, "actions", label="play-by-play actions")):
        action = _object(value, label=f"play-by-play action {index}")
        _append_row(
            rows,
            (game.get("gameId"),) + _values(action, play_headers[1:]),
            headers=play_headers,
            budget=budget,
        )
    video_headers = _route_headers(headers_by_name, "AvailableVideo")
    if video_headers != ("videoAvailable",):
        raise _fail("pinned play-by-play video headers are unsupported")
    video_rows: list[tuple[object, ...]] = []
    _append_row(
        video_rows,
        (game.get("videoAvailable", 0),),
        headers=video_headers,
        budget=budget,
    )
    # This is the provider parser's insertion order.  The pinned endpoint
    # contract intentionally assigns the reverse canonical ordinal.
    return (
        _RawResult("PlayByPlay", play_headers, tuple(rows)),
        _RawResult("AvailableVideo", video_headers, tuple(video_rows)),
    )


def _decode_gravity_leaders(
    *,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[_RawResult, ...]:
    if "leaders" not in payload:
        raise _fail("gravity-leaders response omitted its result root")
    headers = _route_headers(headers_by_name, "leaders")
    rows: list[tuple[object, ...]] = []
    for index, value in enumerate(_array(payload["leaders"], label="gravity leaders")):
        leader = _object(value, label=f"gravity leader {index}")
        _append_row(rows, _values(leader, headers), headers=headers, budget=budget)
    return (_RawResult("leaders", headers, tuple(rows)),)


def _decode_ist_standings(
    *,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
    allow_header_drift: bool = False,
) -> tuple[_RawResult, ...]:
    for required in ("leagueId", "seasonYear", "teams"):
        if required not in payload:
            raise _fail("IST standings response omitted a required root field")
    teams = _array(payload["teams"], label="IST standings teams")
    if not teams:
        raise _fail("IST standings has no team exemplar for dynamic headers")
    first_team = _object(teams[0], label="IST standings first team")
    if "games" not in first_team:
        raise _fail("IST standings first team omitted games")
    team_keys = _filtered_keys(first_team, frozenset({"games"}))
    first_games = _array(first_team["games"], label="IST standings first-team games")
    game_headers: list[str] = []
    expected_game_shapes: list[tuple[int, tuple[str, ...]]] = []
    for game_index, value in enumerate(first_games):
        game = _object(value, label=f"IST standings first-team game {game_index}")
        number = game.get("gameNumber")
        if type(number) is not int or number < 1 or number > MAX_RESULT_HEADERS:
            raise _fail("IST standings game number is invalid")
        keys = _filtered_keys(game, frozenset({"gameNumber"}))
        expected_game_shapes.append((number, keys))
        game_headers.extend(f"{key}{number}" for key in keys)
    observed_headers = ("leagueId", "seasonYear") + team_keys + tuple(game_headers)
    pinned_headers = _route_headers(headers_by_name, "Standings")
    if observed_headers != pinned_headers and not allow_header_drift:
        raise _fail("IST standings dynamic header order differs from the pinned route")
    headers = observed_headers if allow_header_drift else pinned_headers

    rows: list[tuple[object, ...]] = []
    for team_index, value in enumerate(teams):
        team = _object(value, label=f"IST standings team {team_index}")
        _assert_exact_key_order(
            team,
            team_keys,
            excluded=frozenset({"games"}),
            label=f"IST standings team {team_index}",
        )
        if "games" not in team:
            raise _fail("IST standings team omitted games")
        games = _array(team["games"], label=f"IST standings team {team_index} games")
        if len(games) != len(expected_game_shapes):
            raise _fail("IST standings game denominator differs across teams")
        game_values: list[object] = []
        for game_index, (game_value, (number, keys)) in enumerate(
            zip(games, expected_game_shapes, strict=True)
        ):
            game = _object(game_value, label=f"IST standings team {team_index} game {game_index}")
            if game.get("gameNumber") != number:
                raise _fail("IST standings game numbering differs across teams")
            _assert_exact_key_order(
                game,
                keys,
                excluded=frozenset({"gameNumber"}),
                label=f"IST standings team {team_index} game {game_index}",
            )
            game_values.extend(game[key] for key in keys)
        row = (
            payload["leagueId"],
            payload["seasonYear"],
            *(team[key] for key in team_keys),
            *game_values,
        )
        _append_row(rows, row, headers=headers, budget=budget)
    return (_RawResult("Standings", headers, tuple(rows)),)


_SCHEDULE_NESTED_GAME_KEYS: Final = frozenset(
    {"broadcasters", "awayTeam", "homeTeam", "pointsLeaders"}
)


def _schedule_root(payload: dict[str, object]) -> dict[str, object]:
    keys = tuple(payload)
    if "leagueSchedule" not in payload or len(keys) < 2 or keys[1] != "leagueSchedule":
        raise _fail("schedule response does not bind its exact second-key root")
    root = _required_object(payload, "leagueSchedule", label="schedule root")
    for required in ("leagueId", "seasonYear", "gameDates", "weeks"):
        if required not in root:
            raise _fail("schedule response omitted a required root field")
    return root


def _schedule_games(
    root: Mapping[str, object],
) -> list[tuple[dict[str, object], dict[str, object]]]:
    flattened: list[tuple[dict[str, object], dict[str, object]]] = []
    for date_index, value in enumerate(_array(root["gameDates"], label="schedule gameDates")):
        game_date = _object(value, label=f"schedule game date {date_index}")
        if "gameDate" not in game_date or "games" not in game_date:
            raise _fail("schedule game-date entry is incomplete")
        for game_index, game_value in enumerate(
            _array(game_date["games"], label=f"schedule game date {date_index} games")
        ):
            flattened.append(
                (
                    game_date,
                    _object(game_value, label=f"schedule game {date_index}:{game_index}"),
                )
            )
            if len(flattened) > MAX_RESULT_ROWS:
                raise _fail("schedule game denominator exceeds its row bound")
    return flattened


def _first_schedule_broadcaster_keys(
    games: Sequence[tuple[dict[str, object], dict[str, object]]],
    broadcaster_types: tuple[str, ...],
) -> tuple[str, ...]:
    for _date, game in games:
        broadcasters = _required_object(game, "broadcasters", label="schedule broadcasters")
        for broadcaster_type in broadcaster_types:
            values = _array(
                broadcasters.get(broadcaster_type),
                label=f"schedule {broadcaster_type}",
            )
            for value in values:
                return tuple(_object(value, label="schedule broadcaster exemplar"))
    return ()


def _first_schedule_leader_keys(
    games: Sequence[tuple[dict[str, object], dict[str, object]]],
) -> tuple[str, ...]:
    for _date, game in games:
        leaders = _array(game.get("pointsLeaders"), label="schedule points leaders")
        for value in leaders:
            return tuple(_object(value, label="schedule points-leader exemplar"))
    return ()


def _decode_schedule(
    *,
    endpoint_id: str,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
    allow_header_drift: bool = False,
) -> tuple[_RawResult, ...]:
    root = _schedule_root(payload)
    games = _schedule_games(root)
    if not games:
        raise _fail("schedule has no game exemplar for dynamic headers")
    first_game = games[0][1]
    for required in ("homeTeam", "awayTeam", "pointsLeaders", "broadcasters"):
        if required not in first_game:
            raise _fail("schedule first game omitted a nested parser field")

    scalar_game_keys = _filtered_keys(first_game, _SCHEDULE_NESTED_GAME_KEYS)
    first_home = _required_object(first_game, "homeTeam", label="schedule first homeTeam")
    team_keys = tuple(first_home)
    first_broadcasters = _required_object(
        first_game, "broadcasters", label="schedule first broadcasters"
    )
    broadcaster_types = tuple(first_broadcasters)
    broadcaster_keys = _first_schedule_broadcaster_keys(games, broadcaster_types)
    leader_keys = _first_schedule_leader_keys(games)

    max_leaders = 0
    max_broadcasters: dict[str, int] = {name: 0 for name in broadcaster_types}
    for _date, game in games:
        leaders = _array(game.get("pointsLeaders"), label="schedule points leaders")
        max_leaders = max(max_leaders, len(leaders))
        broadcasters = _required_object(game, "broadcasters", label="schedule broadcasters")
        if tuple(broadcasters) != broadcaster_types:
            raise _fail("schedule broadcaster type order differs across games")
        for broadcaster_type in broadcaster_types:
            values = _array(
                broadcasters[broadcaster_type],
                label=f"schedule {broadcaster_type}",
            )
            max_broadcasters[broadcaster_type] = max(
                max_broadcasters[broadcaster_type], len(values)
            )

    generated_headers: list[str] = ["leagueId", "seasonYear", "gameDate"]
    generated_headers.extend(scalar_game_keys)
    generated_headers.extend(f"homeTeam_{key}" for key in team_keys)
    generated_headers.extend(f"awayTeam_{key}" for key in team_keys)
    for index in range(max_leaders):
        suffix = f"_{index}" if max_leaders > 1 else ""
        generated_headers.extend(f"pointsLeaders{suffix}_{key}" for key in leader_keys)
    for broadcaster_type in broadcaster_types:
        maximum = max_broadcasters[broadcaster_type]
        for index in range(maximum):
            suffix = f"_{index}" if maximum > 1 else ""
            generated_headers.extend(
                f"{broadcaster_type}{suffix}_{key}" for key in broadcaster_keys
            )

    observed_game_headers = tuple(generated_headers)
    pinned_game_headers = _route_headers(headers_by_name, "SeasonGames")
    if observed_game_headers != pinned_game_headers and not allow_header_drift:
        raise _fail("schedule dynamic game headers differ from the pinned result route")
    game_headers = observed_game_headers if allow_header_drift else pinned_game_headers
    game_rows: list[tuple[object, ...]] = []
    for game_index, (game_date, game) in enumerate(games):
        _assert_exact_key_order(
            game,
            scalar_game_keys,
            excluded=_SCHEDULE_NESTED_GAME_KEYS,
            label=f"schedule game {game_index}",
        )
        home = _required_object(game, "homeTeam", label=f"schedule game {game_index} home")
        away = _required_object(game, "awayTeam", label=f"schedule game {game_index} away")
        if tuple(home) != team_keys or tuple(away) != team_keys:
            raise _fail("schedule team field order differs across games")
        leaders = _array(game["pointsLeaders"], label=f"schedule game {game_index} leaders")
        leader_values: list[object] = []
        for value in leaders:
            leader = _object(value, label=f"schedule game {game_index} leader")
            if tuple(leader) != leader_keys:
                raise _fail("schedule points-leader field order differs across games")
            leader_values.extend(leader[key] for key in leader_keys)
        for _padding in range(max_leaders - len(leaders)):
            leader_values.extend(None for _key in leader_keys)

        broadcaster_values: list[object] = []
        broadcasters = _required_object(
            game, "broadcasters", label=f"schedule game {game_index} broadcasters"
        )
        for broadcaster_type in broadcaster_types:
            values = _array(
                broadcasters[broadcaster_type],
                label=f"schedule game {game_index} {broadcaster_type}",
            )
            for value in values:
                broadcaster = _object(value, label=f"schedule game {game_index} broadcaster")
                if tuple(broadcaster) != broadcaster_keys:
                    raise _fail("schedule broadcaster field order differs across games")
                broadcaster_values.extend(broadcaster[key] for key in broadcaster_keys)
            for _padding in range(max_broadcasters[broadcaster_type] - len(values)):
                broadcaster_values.extend(None for _key in broadcaster_keys)

        row = (
            root["leagueId"],
            root["seasonYear"],
            game_date["gameDate"],
            *(game[key] for key in scalar_game_keys),
            *(home[key] for key in team_keys),
            *(away[key] for key in team_keys),
            *leader_values,
            *broadcaster_values,
        )
        _append_row(game_rows, row, headers=game_headers, budget=budget)

    pinned_week_headers = _route_headers(headers_by_name, "SeasonWeeks")
    weeks = _array(root["weeks"], label="schedule weeks")
    if weeks:
        first_week = _object(weeks[0], label="schedule first week")
        week_keys = tuple(first_week)
        observed_week_headers = ("leagueId", "seasonYear") + week_keys
    else:
        week_keys = pinned_week_headers[2:]
        observed_week_headers = (
            "leagueId",
            "seasonYear",
            "weekNumber",
            "weekName",
            "startDate",
            "endDate",
        )
    if observed_week_headers != pinned_week_headers and not allow_header_drift:
        raise _fail("schedule dynamic week headers differ from the pinned result route")
    week_headers = observed_week_headers if allow_header_drift else pinned_week_headers
    week_rows: list[tuple[object, ...]] = []
    for index, value in enumerate(weeks):
        week = _object(value, label=f"schedule week {index}")
        if tuple(week) != week_keys:
            raise _fail("schedule week field order differs across rows")
        _append_row(
            week_rows,
            (root["leagueId"], root["seasonYear"], *(week[key] for key in week_keys)),
            headers=week_headers,
            budget=budget,
        )

    results: list[_RawResult] = [
        _RawResult("SeasonGames", game_headers, tuple(game_rows)),
        _RawResult("SeasonWeeks", week_headers, tuple(week_rows)),
    ]
    if endpoint_id == "ScheduleLeagueV2Int":
        if "broadcasterList" not in root:
            raise _fail("international schedule omitted broadcasterList")
        broadcaster_list = _array(root["broadcasterList"], label="schedule broadcasterList")
        if not broadcaster_list:
            raise _fail("international schedule has no broadcaster-list header exemplar")
        first = _object(broadcaster_list[0], label="schedule first broadcaster-list row")
        keys = tuple(first)
        observed_headers = ("leagueId", "seasonYear") + keys
        pinned_headers = _route_headers(headers_by_name, "BroadcasterList")
        if observed_headers != pinned_headers and not allow_header_drift:
            raise _fail("schedule broadcaster-list headers differ from the pinned route")
        headers = observed_headers if allow_header_drift else pinned_headers
        rows: list[tuple[object, ...]] = []
        for index, value in enumerate(broadcaster_list):
            record = _object(value, label=f"schedule broadcaster-list row {index}")
            if tuple(record) != keys:
                raise _fail("schedule broadcaster-list field order differs across rows")
            _append_row(
                rows,
                (root["leagueId"], root["seasonYear"], *(record[key] for key in keys)),
                headers=headers,
                budget=budget,
            )
        results.append(_RawResult("BroadcasterList", headers, tuple(rows)))
    return tuple(results)


_SCOREBOARD_BROADCASTER_TYPES: Final = (
    ("nationalBroadcasters", "nationalTv"),
    ("nationalRadioBroadcasters", "nationalRadio"),
    ("nationalOttBroadcasters", "nationalOtt"),
    ("homeTvBroadcasters", "homeTv"),
    ("homeRadioBroadcasters", "homeRadio"),
    ("homeOttBroadcasters", "homeOtt"),
    ("awayTvBroadcasters", "awayTv"),
    ("awayRadioBroadcasters", "awayRadio"),
    ("awayOttBroadcasters", "awayOtt"),
)


def _decode_scoreboard(
    *,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[_RawResult, ...]:
    scoreboard = _required_object(payload, "scoreboard", label="scoreboard root")
    games = _optional_array(scoreboard, "games", label="scoreboard games")

    info_headers = _route_headers(headers_by_name, "ScoreboardInfo")
    info_rows: list[tuple[object, ...]] = []
    _append_row(
        info_rows,
        _values(scoreboard, info_headers),
        headers=info_headers,
        budget=budget,
    )

    game_headers = _route_headers(headers_by_name, "GameHeader")
    game_rows: list[tuple[object, ...]] = []
    line_headers = _route_headers(headers_by_name, "LineScore")
    if line_headers[:1] != ("gameId",):
        raise _fail("pinned scoreboard line-score headers are unsupported")
    line_rows: list[tuple[object, ...]] = []
    game_leader_headers = _route_headers(headers_by_name, "GameLeaders")
    team_leader_headers = _route_headers(headers_by_name, "TeamLeaders")
    if game_leader_headers[:3] != ("gameId", "teamId", "leaderType") or (
        team_leader_headers[:3] != ("gameId", "teamId", "leaderType")
        or team_leader_headers[-1:] != ("seasonLeadersFlag",)
    ):
        raise _fail("pinned scoreboard leader headers are unsupported")
    game_leader_rows: list[tuple[object, ...]] = []
    team_leader_rows: list[tuple[object, ...]] = []
    broadcaster_headers = _route_headers(headers_by_name, "Broadcasters")
    if broadcaster_headers[:2] != ("gameId", "broadcasterType"):
        raise _fail("pinned scoreboard broadcaster headers are unsupported")
    broadcaster_rows: list[tuple[object, ...]] = []

    for game_index, value in enumerate(games):
        game = _object(value, label=f"scoreboard game {game_index}")
        game_id = game.get("gameId")
        _append_row(
            game_rows,
            _values(game, game_headers),
            headers=game_headers,
            budget=budget,
        )
        teams = {
            side: _optional_object(game, f"{side}Team", label=f"scoreboard {side}Team")
            for side in ("home", "away")
        }
        for side in ("home", "away"):
            team = teams[side]
            _append_row(
                line_rows,
                (game_id,) + _values(team, line_headers[1:]),
                headers=line_headers,
                budget=budget,
            )

        game_leaders = _optional_object(game, "gameLeaders", label="scoreboard game leaders")
        for side, source_name in (("home", "homeLeaders"), ("away", "awayLeaders")):
            leader = _optional_object(
                game_leaders, source_name, label=f"scoreboard {side} game leader"
            )
            if leader:
                _append_row(
                    game_leader_rows,
                    (game_id, teams[side].get("teamId"), side)
                    + _values(leader, game_leader_headers[3:]),
                    headers=game_leader_headers,
                    budget=budget,
                )

        team_leaders = _optional_object(game, "teamLeaders", label="scoreboard team leaders")
        for side, source_name in (("home", "homeLeaders"), ("away", "awayLeaders")):
            leader = _optional_object(
                team_leaders, source_name, label=f"scoreboard {side} team leader"
            )
            if leader:
                _append_row(
                    team_leader_rows,
                    (game_id, teams[side].get("teamId"), side)
                    + _values(leader, team_leader_headers[3:-1])
                    + (team_leaders.get("seasonLeadersFlag"),),
                    headers=team_leader_headers,
                    budget=budget,
                )

        broadcasters = _optional_object(game, "broadcasters", label="scoreboard broadcasters")
        for source_name, label in _SCOREBOARD_BROADCASTER_TYPES:
            for broadcaster_index, broadcaster_value in enumerate(
                _optional_array(
                    broadcasters,
                    source_name,
                    label=f"scoreboard {source_name}",
                )
            ):
                broadcaster = _object(
                    broadcaster_value,
                    label=f"scoreboard {source_name} {broadcaster_index}",
                )
                _append_row(
                    broadcaster_rows,
                    (game_id, label) + _values(broadcaster, broadcaster_headers[2:]),
                    headers=broadcaster_headers,
                    budget=budget,
                )

    return (
        _RawResult("ScoreboardInfo", info_headers, tuple(info_rows)),
        _RawResult("GameHeader", game_headers, tuple(game_rows)),
        _RawResult("LineScore", line_headers, tuple(line_rows)),
        _RawResult("GameLeaders", game_leader_headers, tuple(game_leader_rows)),
        _RawResult("TeamLeaders", team_leader_headers, tuple(team_leader_rows)),
        _RawResult("Broadcasters", broadcaster_headers, tuple(broadcaster_rows)),
    )


def _normalized_metadata_key(value: str) -> str:
    return _METADATA_KEY_RE.sub("_", value.strip().lower()).strip("_")


def _identifier(value: str) -> str:
    return _IDENTIFIER_RE.sub("_", value).strip("_").lower()


def _deduplicate_headers(headers: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    counts: dict[str, int] = {}
    for raw_header in headers:
        header = raw_header.strip()
        if not header:
            continue
        count = counts.get(header, 0) + 1
        counts[header] = count
        result.append(header if count == 1 else f"{header}_{count}")
    return tuple(result)


def _structured_legacy_headers(raw_headers: list[object]) -> tuple[str, ...]:
    records = [_object(value, label="legacy structured header") for value in raw_headers]
    columns_record: dict[str, object] | None = None
    for record in records:
        name = record.get("name")
        if type(name) is str and _normalized_metadata_key(name) == "columns":
            if columns_record is not None:
                raise _fail("legacy structured headers contain duplicate columns metadata")
            columns_record = record
    if columns_record is None:
        raise _fail("legacy structured headers omitted columns metadata")
    column_names = _array(columns_record.get("columnNames"), label="legacy structured column names")
    if any(type(name) is not str or not name.strip() for name in column_names):
        raise _fail("legacy structured headers contain an invalid column name")
    base_columns = [cast("str", name) for name in column_names]
    if not base_columns:
        raise _fail("legacy structured headers contain no columns")

    grouping_records: list[dict[str, object]] = []
    for record in records:
        name = record.get("name")
        if type(name) is str and _normalized_metadata_key(name) == "columns":
            continue
        labels = record.get("columnNames")
        span = record.get("columnSpan")
        if type(labels) is list and type(span) is int and span > 0:
            grouping_records.append(record)
    if not grouping_records:
        return _deduplicate_headers(base_columns)

    primary = grouping_records[0]
    skip_value = primary.get("columnsToSkip", 0)
    span_value = primary["columnSpan"]
    if (
        type(skip_value) is not int
        or skip_value < 0
        or type(span_value) is not int
        or span_value < 1
    ):
        raise _fail("legacy structured header grouping ordinals are invalid")
    labels = _array(primary["columnNames"], label="legacy structured grouping labels")
    if any(type(label) is not str for label in labels):
        raise _fail("legacy structured grouping label is invalid")
    output = [column for column in base_columns[:skip_value] if column.strip()]
    metrics = base_columns[skip_value:]
    cursor = 0
    for raw_label in labels:
        label = _identifier(cast("str", raw_label))
        if not label:
            continue
        for _offset in range(span_value):
            if cursor >= len(metrics):
                break
            metric = _identifier(metrics[cursor])
            cursor += 1
            if metric:
                output.append(f"{label}_{metric}")
    output.extend(metrics[cursor:])
    return _deduplicate_headers(output)


def _legacy_headers(
    value: object,
    *,
    expected_headers: tuple[str, ...],
) -> tuple[str, ...]:
    raw_headers = _array(value, label="legacy result headers")
    if not raw_headers:
        if expected_headers:
            raise _fail("legacy result headers are empty")
        return ()
    if all(type(header) is str for header in raw_headers):
        headers = tuple(cast("str", header) for header in raw_headers)
    elif all(type(header) is dict for header in raw_headers):
        headers = _structured_legacy_headers(raw_headers)
    else:
        raise _fail("legacy result headers have a mixed or unsupported shape")
    if (
        not headers
        or len(headers) > MAX_RESULT_HEADERS
        or any(not header or header.strip() != header for header in headers)
        or len(set(headers)) != len(headers)
    ):
        raise _fail("legacy result headers are invalid or duplicated")
    return headers


def _observed_legacy_header_details(
    value: object,
) -> tuple[tuple[str | None, ...], tuple[object, ...]]:
    """Reproduce production effective names and emitted header values exactly."""

    if type(value) is not list:
        return (), ()
    raw_headers = cast("list[object]", value)
    if len(raw_headers) > MAX_RESULT_HEADERS:
        raise _fail("observed legacy result headers exceed their bound")
    if all(type(header) is str for header in raw_headers):
        names = tuple(cast("str", header) for header in raw_headers)
        return names, names
    if raw_headers and all(type(header) is dict for header in raw_headers):
        try:
            headers = _structured_legacy_headers(raw_headers)
        except IndependentStatsValueDecoderError:
            headers = ()
        if headers:
            return headers, headers
    return (
        tuple(header if type(header) is str else None for header in raw_headers),
        tuple(raw_headers),
    )


def _observed_legacy_header_names(value: object) -> tuple[str | None, ...]:
    """Return production effective header names for any JSON header container."""

    names, _values = _observed_legacy_header_details(value)
    return names


def _json_value_kind(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if type(value) is str:
        return "string"
    if type(value) is list:
        return "array"
    if type(value) is dict:
        return "object"
    raise _fail("observed stats row contains a non-JSON value")


def _observed_per_set_anomalies(
    *,
    expected_headers: tuple[str, ...] | None,
    raw_headers: object,
    observed_header_names: tuple[str | None, ...],
    raw_rows: object,
    compare_expected_headers: bool = True,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if type(raw_headers) is not list:
        reasons.add("unsupported_header_shape")
    if any(name is None for name in observed_header_names):
        reasons.add("unsupported_header_shape")
    observed_headers = tuple(name for name in observed_header_names if name is not None)
    if len(set(observed_headers)) != len(observed_headers):
        reasons.add("duplicate_header")
    if compare_expected_headers and expected_headers is not None:
        expected_counter = Counter(expected_headers)
        observed_counter = Counter(observed_headers)
        if observed_counter - expected_counter:
            reasons.add("additive_header")
        if expected_counter - observed_counter:
            reasons.add("removed_header")
        if expected_counter == observed_counter and expected_headers != observed_headers:
            reasons.add("reordered_header")

    if type(raw_rows) is not list:
        reasons.add("unsupported_row_container")
        return tuple(sorted(reasons))

    widths: set[int] = set()
    kinds_by_ordinal: dict[int, set[str]] = {}
    for raw_row in cast("list[object]", raw_rows):
        if type(raw_row) is not list:
            reasons.add("non_sequence_row")
            continue
        row = cast("list[object]", raw_row)
        widths.add(len(row))
        if len(row) != len(observed_header_names):
            reasons.add("ragged_row")
        for ordinal, value in enumerate(row):
            kind = _json_value_kind(value)
            if kind != "null":
                kinds_by_ordinal.setdefault(ordinal, set()).add(kind)
    if len(widths) > 1:
        reasons.add("ragged_row")
    if any(len(kinds) > 1 for kinds in kinds_by_ordinal.values()):
        reasons.add("heterogeneous_column")
    return tuple(sorted(reasons))


def _decode_observed_legacy_results(
    *,
    payload: dict[str, object],
    contract: NbaApiEndpointContract,
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[DecodedObservedStatsResultV1, ...]:
    roots = tuple(name for name in ("resultSets", "resultSet") if name in payload)
    if len(roots) != 1:
        raise _fail("observed legacy stats response must contain exactly one result envelope")
    raw_container = payload[roots[0]]
    if type(raw_container) is dict:
        entries: list[object] = [raw_container]
    else:
        entries = _array(raw_container, label="observed legacy result-set envelope")
    if len(entries) > MAX_RESULT_ROUTES:
        raise _fail("observed legacy result-set denominator is unbounded")

    expected_by_name: dict[str, tuple[int, tuple[str, ...]]] = {}
    expected_names: list[str] = []
    for canonical_ordinal, route in enumerate(contract.result_sets):
        name = route.result_set_name
        if type(name) is not str or _RESULT_NAME_RE.fullmatch(name) is None:
            raise _fail("pinned stats contract contains an invalid result name")
        if name in expected_by_name:
            raise _fail("pinned stats contract contains a duplicate result name")
        expected_headers = headers_by_name[name]
        expected_by_name[name] = (canonical_ordinal, expected_headers)
        expected_names.append(name)

    provider_sets: list[tuple[str, object, tuple[str | None, ...], tuple[str, ...], object]] = []
    for provider_ordinal, value in enumerate(entries):
        result = _object(value, label=f"observed legacy result set {provider_ordinal}")
        if not {"name", "headers", "rowSet"} <= set(result):
            raise _fail("observed legacy result set omitted name, headers, or rows")
        name = result["name"]
        if type(name) is not str or _RESULT_NAME_RE.fullmatch(name) is None:
            raise _fail("observed legacy result-set name is invalid")
        raw_headers = result["headers"]
        raw_rows = result["rowSet"]
        effective_header_names, _header_values = _observed_legacy_header_details(raw_headers)
        ordered_headers = tuple(header for header in effective_header_names if header is not None)
        budget.add_observed_result(raw_headers=raw_headers, raw_rows=raw_rows)
        provider_sets.append((name, raw_headers, effective_header_names, ordered_headers, raw_rows))

    provider_names = [
        name for name, _raw_headers, _effective_headers, _ordered_headers, _rows in provider_sets
    ]
    provider_name_counts = Counter(provider_names)
    global_reasons: set[str] = set()
    if provider_name_counts - Counter(expected_names):
        global_reasons.add("additive_result_set")
    if Counter(expected_names) - provider_name_counts:
        global_reasons.add("missing_result_set")
    if any(count > 1 for count in provider_name_counts.values()):
        global_reasons.add("duplicate_result_set_name")

    per_set_anomalies: list[tuple[str, ...]] = []
    for (
        name,
        _raw_headers,
        effective_header_names,
        _ordered_headers,
        raw_rows,
    ) in provider_sets:
        expected = expected_by_name.get(name)
        anomalies = _observed_per_set_anomalies(
            expected_headers=None if expected is None else expected[1],
            raw_headers=_raw_headers,
            observed_header_names=effective_header_names,
            raw_rows=raw_rows,
        )
        per_set_anomalies.append(anomalies)
        global_reasons.update(anomalies)

    missing_names = [name for name in expected_names if provider_name_counts[name] == 0]
    if len(provider_sets) + len(missing_names) > MAX_RESULT_ROUTES:
        raise _fail("observed stats result denominator exceeds its bound")

    occurrences: Counter[str] = Counter()
    decoded: list[DecodedObservedStatsResultV1] = []
    for provider_ordinal, (
        name,
        raw_headers,
        effective_header_names,
        ordered_headers,
        raw_rows,
    ) in enumerate(provider_sets):
        duplicate_name_ordinal = occurrences[name]
        occurrences[name] += 1
        expected = expected_by_name.get(name)
        canonical_ordinal = (
            expected[0] if expected is not None and provider_name_counts[name] == 1 else None
        )
        decoded.append(
            DecodedObservedStatsResultV1._from_present(
                provider_ordinal=provider_ordinal,
                canonical_ordinal=canonical_ordinal,
                duplicate_name_ordinal=duplicate_name_ordinal,
                result_name=name,
                response_mode="declared_result_sets",
                raw_headers=raw_headers,
                ordered_headers=ordered_headers,
                effective_header_names=effective_header_names,
                raw_rows=raw_rows,
                anomaly_codes=per_set_anomalies[provider_ordinal],
            )
        )
    for name in missing_names:
        canonical_ordinal, expected_headers = expected_by_name[name]
        decoded.append(
            DecodedObservedStatsResultV1._from_missing(
                canonical_ordinal=canonical_ordinal,
                result_name=name,
                ordered_headers=expected_headers,
            )
        )
    return tuple(decoded)


def _decode_observed_unknown_legacy_results(
    *,
    payload: dict[str, object],
    budget: _OutputBudget,
) -> tuple[DecodedObservedStatsResultV1, ...]:
    """Decode only the exact legacy envelope admitted by an unknown-mode pin."""

    roots = tuple(name for name in ("resultSets", "resultSet") if name in payload)
    if len(roots) != 1:
        raise _fail("observed unknown-dynamic response must contain exactly one legacy envelope")
    raw_container = payload[roots[0]]
    if type(raw_container) is dict:
        entries: list[object] = [raw_container]
    elif type(raw_container) is list:
        entries = cast("list[object]", raw_container)
    else:
        raise _fail("observed unknown-dynamic legacy envelope must be an object or array")
    if len(entries) > MAX_RESULT_ROUTES:
        raise _fail("observed unknown-dynamic result denominator is unbounded")

    occurrences: Counter[str] = Counter()
    decoded: list[DecodedObservedStatsResultV1] = []
    for provider_ordinal, value in enumerate(entries):
        result = _object(value, label=f"observed unknown result set {provider_ordinal}")
        if not {"name", "headers", "rowSet"} <= set(result):
            raise _fail("observed unknown result set omitted name, headers, or rows")
        name = result["name"]
        raw_headers = result["headers"]
        raw_rows = result["rowSet"]
        if (
            type(name) is not str
            or not name
            or name.strip() != name
            or _RESULT_NAME_RE.fullmatch(name) is None
        ):
            raise _fail("observed unknown result-set name is invalid")
        if (
            type(raw_headers) is not list
            or len(raw_headers) > MAX_RESULT_HEADERS
            or any(
                type(header) is not str or not header or header.strip() != header
                for header in cast("list[object]", raw_headers)
            )
        ):
            raise _fail("observed unknown result-set headers are invalid")
        if type(raw_rows) is not list or len(raw_rows) > MAX_RESULT_ROWS:
            raise _fail("observed unknown result-set rows are invalid")
        headers = cast("list[str]", raw_headers)
        rows = cast("list[object]", raw_rows)
        if any(
            type(row) is not list or len(cast("list[object]", row)) != len(headers) for row in rows
        ):
            raise _fail("observed unknown result row width differs from its headers")
        budget.add_observed_result(raw_headers=raw_headers, raw_rows=raw_rows)
        duplicate_name_ordinal = occurrences[name]
        occurrences[name] += 1
        decoded.append(
            DecodedObservedStatsResultV1._from_present(
                provider_ordinal=provider_ordinal,
                canonical_ordinal=None,
                duplicate_name_ordinal=duplicate_name_ordinal,
                result_name=name,
                response_mode="unknown_dynamic_response",
                raw_headers=raw_headers,
                ordered_headers=tuple(headers),
                effective_header_names=tuple(headers),
                raw_rows=raw_rows,
                anomaly_codes=(),
            )
        )
    return tuple(decoded)


def _decode_legacy_results(
    *,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[_RawResult, ...]:
    roots = tuple(name for name in ("resultSets", "resultSet") if name in payload)
    if len(roots) != 1:
        raise _fail("legacy stats response must contain exactly one result envelope")
    raw_container = payload[roots[0]]
    if type(raw_container) is dict:
        entries: list[object] = [raw_container]
    else:
        entries = _array(raw_container, label="legacy result-set envelope")
    if not entries or len(entries) > MAX_RESULT_ROUTES:
        raise _fail("legacy result-set denominator is absent or unbounded")
    results: list[_RawResult] = []
    names: set[str] = set()
    for provider_ordinal, value in enumerate(entries):
        result = _object(value, label=f"legacy result set {provider_ordinal}")
        if not {"name", "headers", "rowSet"} <= set(result):
            raise _fail("legacy result set omitted name, headers, or rows")
        name = result["name"]
        if type(name) is not str or not name or name.strip() != name:
            raise _fail("legacy result-set name is invalid")
        if name in names:
            raise _fail("legacy response contains a duplicate result-set name")
        names.add(name)
        expected_headers = _route_headers(headers_by_name, name)
        headers = _legacy_headers(
            result["headers"],
            expected_headers=expected_headers,
        )
        rows: list[tuple[object, ...]] = []
        for row_index, raw_row in enumerate(
            _array(result["rowSet"], label=f"legacy result {name} rows")
        ):
            row = _array(raw_row, label=f"legacy result {name} row {row_index}")
            _append_row(rows, row, headers=headers, budget=budget)
        results.append(_RawResult(name, headers, tuple(rows)))
    return tuple(results)


def _decode_custom_results(
    *,
    endpoint_id: str,
    payload: dict[str, object],
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
    allow_header_drift: bool = False,
) -> tuple[_RawResult, ...]:
    if "resultSets" in payload or "resultSet" in payload:
        raise _fail("custom stats response contains an ambiguous legacy result envelope")
    if endpoint_id in _GENERIC_BOXSCORE_ROOTS:
        return _decode_generic_boxscore(
            endpoint_id=endpoint_id,
            payload=payload,
            headers_by_name=headers_by_name,
            budget=budget,
        )
    if endpoint_id == "BoxScoreTraditionalV3":
        return _decode_traditional_boxscore(
            payload=payload, headers_by_name=headers_by_name, budget=budget
        )
    if endpoint_id == "BoxScoreMatchupsV3":
        return _decode_matchups(
            payload=payload,
            headers_by_name=headers_by_name,
            budget=budget,
            allow_header_drift=allow_header_drift,
        )
    if endpoint_id == "BoxScoreSummaryV3":
        return _decode_summary(payload=payload, headers_by_name=headers_by_name, budget=budget)
    if endpoint_id == "GravityLeaders":
        return _decode_gravity_leaders(
            payload=payload, headers_by_name=headers_by_name, budget=budget
        )
    if endpoint_id == "ISTStandings":
        return _decode_ist_standings(
            payload=payload,
            headers_by_name=headers_by_name,
            budget=budget,
            allow_header_drift=allow_header_drift,
        )
    if endpoint_id == "PlayByPlayV3":
        return _decode_play_by_play(payload=payload, headers_by_name=headers_by_name, budget=budget)
    if endpoint_id in {"ScheduleLeagueV2", "ScheduleLeagueV2Int"}:
        return _decode_schedule(
            endpoint_id=endpoint_id,
            payload=payload,
            headers_by_name=headers_by_name,
            budget=budget,
            allow_header_drift=allow_header_drift,
        )
    if endpoint_id == "ScoreboardV3":
        return _decode_scoreboard(payload=payload, headers_by_name=headers_by_name, budget=budget)
    raise _fail("pinned custom stats endpoint has no independent decoder")


def _decode_observed_custom_results(
    *,
    endpoint_id: str,
    payload: dict[str, object],
    contract: NbaApiEndpointContract,
    headers_by_name: Mapping[str, tuple[str, ...]],
    budget: _OutputBudget,
) -> tuple[DecodedObservedStatsResultV1, ...]:
    raw_results = _decode_custom_results(
        endpoint_id=endpoint_id,
        payload=payload,
        headers_by_name=headers_by_name,
        budget=budget,
        allow_header_drift=True,
    )
    if not raw_results or len(raw_results) > MAX_RESULT_ROUTES:
        raise _fail("observed custom stats result denominator is absent or unbounded")

    expected_by_name: dict[str, tuple[int, tuple[str, ...]]] = {}
    expected_names: list[str] = []
    for canonical_ordinal, route in enumerate(contract.result_sets):
        name = route.result_set_name
        if type(name) is not str or _RESULT_NAME_RE.fullmatch(name) is None:
            raise _fail("pinned custom stats contract contains an invalid result name")
        if name in expected_by_name:
            raise _fail("pinned custom stats contract contains a duplicate result name")
        expected_headers = headers_by_name[name]
        expected_by_name[name] = (canonical_ordinal, expected_headers)
        expected_names.append(name)

    provider_names = [result.name for result in raw_results]
    provider_name_counts = Counter(provider_names)
    global_reasons: set[str] = set()
    if provider_name_counts - Counter(expected_names):
        global_reasons.add("additive_result_set")
    if Counter(expected_names) - provider_name_counts:
        global_reasons.add("missing_result_set")
    if any(count > 1 for count in provider_name_counts.values()):
        global_reasons.add("duplicate_result_set_name")

    per_set_anomalies: list[tuple[str, ...]] = []
    for result in raw_results:
        expected = expected_by_name.get(result.name)
        anomalies = _observed_per_set_anomalies(
            expected_headers=None if expected is None else expected[1],
            raw_headers=list(result.headers),
            observed_header_names=result.headers,
            raw_rows=[list(row) for row in result.rows],
        )
        per_set_anomalies.append(anomalies)
        global_reasons.update(anomalies)
    missing_names = [name for name in expected_names if provider_name_counts[name] == 0]
    if len(raw_results) + len(missing_names) > MAX_RESULT_ROUTES:
        raise _fail("observed custom stats result denominator exceeds its bound")

    occurrences: Counter[str] = Counter()
    decoded: list[DecodedObservedStatsResultV1] = []
    for provider_ordinal, result in enumerate(raw_results):
        duplicate_name_ordinal = occurrences[result.name]
        occurrences[result.name] += 1
        expected = expected_by_name.get(result.name)
        canonical_ordinal = (
            expected[0] if expected is not None and provider_name_counts[result.name] == 1 else None
        )
        decoded.append(
            DecodedObservedStatsResultV1._from_present(
                provider_ordinal=provider_ordinal,
                canonical_ordinal=canonical_ordinal,
                duplicate_name_ordinal=duplicate_name_ordinal,
                result_name=result.name,
                response_mode="declared_result_sets",
                raw_headers=list(result.headers),
                ordered_headers=result.headers,
                effective_header_names=result.headers,
                raw_rows=[list(row) for row in result.rows],
                anomaly_codes=per_set_anomalies[provider_ordinal],
            )
        )
    for name in missing_names:
        canonical_ordinal, expected_headers = expected_by_name[name]
        decoded.append(
            DecodedObservedStatsResultV1._from_missing(
                canonical_ordinal=canonical_ordinal,
                result_name=name,
                ordered_headers=expected_headers,
            )
        )
    return tuple(decoded)


def _reject_error_envelope(payload: Mapping[str, object]) -> None:
    if (
        "resultSets" not in payload
        and "resultSet" not in payload
        and any(key in payload for key in ("Message", "message", "error"))
    ):
        raise _fail("stats parser input is an upstream error envelope")
    meta = payload.get("meta")
    meta_code = meta.get("code") if type(meta) is dict else None
    for candidate in (
        payload.get("statusCode"),
        payload.get("status"),
        payload.get("code"),
        meta_code,
    ):
        if type(candidate) is int and candidate >= 400:
            raise _fail("stats parser input is an upstream error envelope")


def _assert_custom_census(contracts: Mapping[str, NbaApiEndpointContract]) -> None:
    custom = {
        endpoint_id: contract
        for endpoint_id, contract in contracts.items()
        if contract.parser_kind == "custom_nested"
    }
    if frozenset(custom) != CUSTOM_NESTED_ENDPOINT_IDS:
        raise _fail("pinned custom stats endpoint census differs from decoder support")
    if sum(len(contract.result_sets) for contract in custom.values()) != (
        CUSTOM_NESTED_RESULT_ROUTE_COUNT
    ):
        raise _fail("pinned custom stats route census differs from decoder support")


def _validate_results(
    *,
    raw_results: tuple[_RawResult, ...],
    contract: NbaApiEndpointContract,
) -> tuple[DecodedStatsResultV1, ...]:
    if not raw_results or len(raw_results) > MAX_RESULT_ROUTES:
        raise _fail("decoded stats result denominator is absent or unbounded")
    expected: dict[str, tuple[int, tuple[str, ...]]] = {}
    for canonical_ordinal, route in enumerate(contract.result_sets):
        name = route.result_set_name
        if type(name) is not str or not name or name in expected:
            raise _fail("pinned stats contract contains an invalid result name")
        expected[name] = (canonical_ordinal, tuple(route.expected_columns))
    observed_names = tuple(result.name for result in raw_results)
    if len(set(observed_names)) != len(observed_names):
        raise _fail("decoded stats results contain a duplicate name")
    if set(observed_names) != set(expected) or len(raw_results) != len(expected):
        raise _fail("decoded stats result inventory differs from the pinned contract")

    decoded: list[DecodedStatsResultV1] = []
    for provider_ordinal, raw_result in enumerate(raw_results):
        canonical_ordinal, expected_headers = expected[raw_result.name]
        if raw_result.headers != expected_headers:
            raise _fail("decoded stats header order differs from the pinned result route")
        if any(len(row) != len(expected_headers) for row in raw_result.rows):
            raise _fail("decoded stats row width differs from the pinned result route")
        anomalies = _observed_per_set_anomalies(
            expected_headers=expected_headers,
            raw_headers=list(raw_result.headers),
            observed_header_names=raw_result.headers,
            raw_rows=[list(row) for row in raw_result.rows],
        )
        if anomalies:
            raise _fail("decoded stats values require the lossless fallback contract")
        if contract.parser_kind == "legacy_result_sets" and expected_headers and raw_result.rows:
            try:
                pl.DataFrame(
                    [list(row) for row in raw_result.rows],
                    schema=list(expected_headers),
                    orient="row",
                    infer_schema_length=None,
                )
            except (TypeError, ValueError, pl.exceptions.PolarsError) as exc:
                raise _fail("decoded stats values require the lossless fallback contract") from exc
        decoded.append(
            DecodedStatsResultV1._from_rows(
                provider_ordinal=provider_ordinal,
                canonical_ordinal=canonical_ordinal,
                result_name=raw_result.name,
                ordered_headers=expected_headers,
                rows=raw_result.rows,
            )
        )
    return tuple(decoded)


def _admitted_contract(
    *,
    endpoint_id: str,
    endpoint_contract_sha256_value: str,
    provider_authority_sha256: str,
) -> NbaApiEndpointContract:
    if (
        type(endpoint_id) is not str
        or not endpoint_id
        or endpoint_id.strip() != endpoint_id
        or type(endpoint_contract_sha256_value) is not str
        or type(provider_authority_sha256) is not str
    ):
        raise _fail("stats decoder authority inputs have foreign types")
    contracts = pinned_runtime_contracts()
    _assert_custom_census(contracts)
    contract = contracts.get(endpoint_id)
    if contract is None:
        raise _fail("stats endpoint is absent from the exact pinned registry")
    expected_provider = expected_nba_api_provider_authority().get("authority_sha256")
    if (
        type(expected_provider) is not str
        or provider_authority_sha256 != expected_provider
        or endpoint_contract_sha256_value != _endpoint_contract_sha256_for(contract)
    ):
        raise _fail("stats decoder authority pin differs from the exact runtime contract")
    return contract


def decode_stats_value_rows(
    *,
    endpoint_id: str,
    endpoint_contract_sha256: str,
    provider_authority_sha256: str,
    parser_input: bytes,
) -> tuple[DecodedStatsResultV1, ...]:
    """Decode exact provider-ordered stats results from immutable raw bytes.

    Every authority argument must match the generated exact-pin registry.  A
    foreign pin, changed custom-parser census, malformed body, or any result
    inventory/header/row drift fails before a DTO is returned.
    """

    contract = _admitted_contract(
        endpoint_id=endpoint_id,
        endpoint_contract_sha256_value=endpoint_contract_sha256,
        provider_authority_sha256=provider_authority_sha256,
    )
    value = _decode_json_bytes(parser_input, require_object=True)
    payload = cast("dict[str, object]", value)
    _reject_error_envelope(payload)
    headers_by_name = _headers_by_name(contract)
    budget = _OutputBudget()
    if contract.parser_kind == "legacy_result_sets":
        raw_results = _decode_legacy_results(
            payload=payload,
            headers_by_name=headers_by_name,
            budget=budget,
        )
    elif contract.parser_kind == "custom_nested":
        if endpoint_id not in CUSTOM_NESTED_ENDPOINT_IDS:
            raise _fail("custom stats endpoint is unsupported by the independent decoder")
        raw_results = _decode_custom_results(
            endpoint_id=endpoint_id,
            payload=payload,
            headers_by_name=headers_by_name,
            budget=budget,
        )
    else:  # pragma: no cover - generated contract parser kind is closed
        raise _fail("stats endpoint has an unsupported parser kind")
    return _validate_results(raw_results=raw_results, contract=contract)


def decode_observed_lossless_stats_response(
    *,
    endpoint_id: str,
    endpoint_contract_sha256: str,
    provider_authority_sha256: str,
    parser_input: bytes,
) -> DecodedObservedStatsResponseV1:
    """Decode and seal one exact whole-response lossless fallback independently.

    Unlike :func:`decode_stats_value_rows`, this path preserves provider drift:
    additive, missing, reordered, and duplicate headers/results remain visible
    with exact ordinals and rows. Custom-nested endpoints use this module's
    independent pinned flatteners and never execute the production adapter or
    provider parser modules.
    """

    contract = _admitted_contract(
        endpoint_id=endpoint_id,
        endpoint_contract_sha256_value=endpoint_contract_sha256,
        provider_authority_sha256=provider_authority_sha256,
    )
    value = _decode_json_bytes(parser_input, require_object=True)
    payload = cast("dict[str, object]", value)
    _reject_error_envelope(payload)
    budget = _OutputBudget()
    response_mode = contract.response_mode
    if response_mode == "unknown_dynamic_response":
        if contract.parser_kind != "legacy_result_sets" or contract.result_sets:
            raise _fail("unknown-dynamic stats contract parser identity drifted")
        headers_by_name: dict[str, tuple[str, ...]] = {}
        results = _decode_observed_unknown_legacy_results(
            payload=payload,
            budget=budget,
        )
    elif contract.parser_kind == "legacy_result_sets":
        headers_by_name = _headers_by_name(contract)
        results = _decode_observed_legacy_results(
            payload=payload,
            contract=contract,
            headers_by_name=headers_by_name,
            budget=budget,
        )
    elif contract.parser_kind == "custom_nested":
        headers_by_name = _headers_by_name(contract)
        if endpoint_id not in CUSTOM_NESTED_ENDPOINT_IDS:
            raise _fail("custom stats endpoint is unsupported by the independent decoder")
        results = _decode_observed_custom_results(
            endpoint_id=endpoint_id,
            payload=payload,
            contract=contract,
            headers_by_name=headers_by_name,
            budget=budget,
        )
    else:
        raise _fail("stats endpoint has an unsupported parser kind")
    endpoint_slug = contract.endpoint_slug
    if type(endpoint_slug) is not str or not endpoint_slug:
        raise _fail("stats endpoint lacks an exact pinned slug")
    expected_routes = tuple(
        (route.result_set_name, tuple(route.expected_columns)) for route in contract.result_sets
    )
    if any(type(name) is not str for name, _headers in expected_routes):
        raise _fail("stats endpoint lacks an exact pinned result name")
    return DecodedObservedStatsResponseV1._build(
        endpoint_id=endpoint_id,
        endpoint_slug=endpoint_slug,
        response_mode=response_mode,
        expected_headers_by_name={cast("str", name): headers for name, headers in expected_routes},
        results=results,
    )


def decode_observed_lossless_stats_value_rows(
    *,
    endpoint_id: str,
    endpoint_contract_sha256: str,
    provider_authority_sha256: str,
    parser_input: bytes,
) -> tuple[DecodedObservedStatsResultV1, ...]:
    """Return the result projection of whole-response observed fallback evidence."""

    return decode_observed_lossless_stats_response(
        endpoint_id=endpoint_id,
        endpoint_contract_sha256=endpoint_contract_sha256,
        provider_authority_sha256=provider_authority_sha256,
        parser_input=parser_input,
    ).results


def _endpoint_contract_sha256_for(contract: NbaApiEndpointContract) -> str:
    """Return the exact digest while keeping call-site names unambiguous."""

    return endpoint_contract_sha256(contract)
