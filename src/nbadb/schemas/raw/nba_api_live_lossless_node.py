"""Strict schema for the sole mandatory live-lossless public relation."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any

import pandera.polars as pa
import polars as pl

from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_COLUMNS,
    LIVE_LOSSLESS_REPRESENTATION_KIND,
    LIVE_LOSSLESS_SOURCE_INPUT_KIND,
    LIVE_LOSSLESS_TEXT_COLUMNS,
    LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND,
    MAX_LIVE_LOSSLESS_ANOMALY_BYTES,
    MAX_LIVE_LOSSLESS_CANONICAL_BYTES,
    MAX_LIVE_LOSSLESS_DEPTH,
    MAX_LIVE_LOSSLESS_HEADER_COUNT,
    MAX_LIVE_LOSSLESS_JSON_NODES,
    MAX_LIVE_LOSSLESS_JSON_PATH_BYTES,
    MAX_LIVE_LOSSLESS_NODES,
    MAX_LIVE_LOSSLESS_OBSERVATIONS,
    MAX_LIVE_LOSSLESS_RECORDS,
    MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
    MAX_LIVE_LOSSLESS_RESULTS,
    MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    LiveLosslessNodeRecordV1,
    LiveLosslessValueAuthorityError,
    canonical_ordered_root_sha256,
)
from nbadb.contracts.public_value_types import MAX_PUBLIC_VALUE_EXPECTED_UNITS
from nbadb.schemas.base import BaseSchema

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
_RECORD_KINDS = ["result_declaration", "result_occurrence", "node", "field_cell"]
_PRESENCE_KINDS = [
    "present",
    "null",
    "empty_object",
    "empty_array",
    "missing",
    "mixed_absent",
    "not_observed_parent_empty",
]
_VALUE_KINDS = [
    "object",
    "array",
    "null",
    "boolean",
    "integer",
    "number",
    "string",
    "missing",
]
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z", flags=re.ASCII)
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])", flags=re.ASCII)
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])", flags=re.ASCII)
_KEY_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+", flags=re.ASCII)
_SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|proxy_authorization|authentication|cookie|set_cookie|credential|"
    r"secret|token|client_secret|client_key|access_token|refresh_token|id_token|api_key|"
    r"apikey|password|passwd|proxy_url|proxy_host|vpn_server|vpn_ip|vpn_password|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|gh_token|pat|private_key|secret_key|personal_access_token|"
    r"ssh_private_key)\Z",
    flags=re.ASCII,
)
_GENERIC_SENSITIVE_KEY_COMPONENTS = frozenset({"auth", "session", "secret", "token"})
_AUTHORIZATION_HEADER_SECRET_RE = re.compile(
    r"authorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}",
    flags=re.ASCII | re.IGNORECASE,
)
_BEARER_SECRET_RE = re.compile(
    r"bearer\s+[A-Za-z0-9._~+/=-]{20,}(?![A-Za-z0-9._~+/=-])",
    flags=re.ASCII | re.IGNORECASE,
)
_BASIC_SECRET_RE = re.compile(
    r"basic\s+[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=])",
    flags=re.ASCII | re.IGNORECASE,
)
_LOCAL_PATH_VALUE_RE = re.compile(
    r"(?:/Users/[^/\x00\s]+(?=/|\s|\Z)|/home/[^/\x00\s]+(?=/|\s|\Z)|"
    r"/private/var(?![A-Za-z0-9_])|[A-Za-z]:\\Users\\)"
)
_EMBEDDED_SECRET_RES = (
    re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b", flags=re.ASCII),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b", flags=re.ASCII),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", flags=re.ASCII),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b", flags=re.ASCII),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
        flags=re.ASCII,
    ),
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----", flags=re.ASCII),
    re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", flags=re.ASCII | re.IGNORECASE),
)
_ANOMALY_CODES = frozenset({"additive_envelope_root", "reordered_envelope_root", "additive_field"})
_INVALID_CANONICAL_JSON = object()


def _normalized_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _safe_text(value: str, *, key: bool = False) -> bool:
    normalized = _normalized_key(value)
    if key and (
        _SENSITIVE_KEY_RE.fullmatch(normalized) is not None
        or any(
            component in _GENERIC_SENSITIVE_KEY_COMPONENTS for component in normalized.split("_")
        )
    ):
        return False
    stripped = value.strip()
    return not (
        _AUTHORIZATION_HEADER_SECRET_RE.search(stripped) is not None
        or _BEARER_SECRET_RE.search(stripped) is not None
        or _BASIC_SECRET_RE.search(stripped) is not None
        or _LOCAL_PATH_VALUE_RE.search(value) is not None
        or any(pattern.search(value) is not None for pattern in _EMBEDDED_SECRET_RES)
    )


def _decode_safe_canonical_json(value: object, *, require: type | None = None) -> object:
    if type(value) is not str:
        return _INVALID_CANONICAL_JSON
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return _INVALID_CANONICAL_JSON
    if not raw or len(raw) > MAX_LIVE_LOSSLESS_CANONICAL_BYTES:
        return _INVALID_CANONICAL_JSON

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, item in items:
            if key in output:
                raise ValueError
            output[key] = item
        return output

    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _token: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return _INVALID_CANONICAL_JSON
    if require is not None and type(decoded) is not require:
        return _INVALID_CANONICAL_JSON
    stack: list[tuple[object, int]] = [(decoded, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_LIVE_LOSSLESS_JSON_NODES or depth > MAX_LIVE_LOSSLESS_DEPTH:
            return _INVALID_CANONICAL_JSON
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if abs(item) > (1 << 63) - 1:
                return _INVALID_CANONICAL_JSON
        elif type(item) is float:
            if not math.isfinite(item):
                return _INVALID_CANONICAL_JSON
        elif type(item) is str:
            if not _safe_text(item):
                return _INVALID_CANONICAL_JSON
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is dict:
            for key, child in item.items():
                if type(key) is not str or not _safe_text(key, key=True):
                    return _INVALID_CANONICAL_JSON
                stack.append((child, depth + 1))
        else:
            return _INVALID_CANONICAL_JSON
    try:
        canonical = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        return _INVALID_CANONICAL_JSON
    return decoded if canonical == raw else _INVALID_CANONICAL_JSON


def _canonical_timestamp(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is UTC and value == parsed.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


class RawNbaApiLiveLosslessNodeSchema(BaseSchema):
    """One declaration, occurrence, node, or field-cell public record."""

    schema_version: int = pa.Field(eq=PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION)
    record_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    source_input_kind: str = pa.Field(eq=LIVE_LOSSLESS_SOURCE_INPUT_KIND)
    representation_kind: str = pa.Field(
        isin=[
            LIVE_LOSSLESS_REPRESENTATION_KIND,
            LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND,
        ]
    )
    representation_assignment_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    expected_unit_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    expected_unit_ordinal: int = pa.Field(ge=0, lt=MAX_PUBLIC_VALUE_EXPECTED_UNITS)
    ownership_kind: str = pa.Field(isin=["result_occurrence", "response_residual"])
    ownership_occurrence_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
    )
    response_residual_record_count: int = pa.Field(ge=0, le=MAX_LIVE_LOSSLESS_RECORDS)
    response_residual_record_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    raw_authority_bundle_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    observation_record_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    attempt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    semantic_request_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    logical_invocation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_call_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    request_surface_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    runtime_contract_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    endpoint_contract_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    parser_input_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    parser_input_length: int = pa.Field(gt=0, le=MAX_LIVE_LOSSLESS_CANONICAL_BYTES)
    decoder_anomaly_codes_json: str = pa.Field(str_length=(2, MAX_LIVE_LOSSLESS_ANOMALY_BYTES))
    decoder_anomaly_codes_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    decoder_response_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    capture_response_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_landings_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    raw_result_occurrences_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    source_sha: str = pa.Field(str_matches=_GIT_SHA_PATTERN)
    run_id: int = pa.Field(gt=0, le=2**63 - 1)
    run_attempt: int = pa.Field(gt=0, le=2**31 - 1)
    chain_id: str = pa.Field(str_length=(1, 512))
    lane_id: str = pa.Field(str_length=(1, 512))
    endpoint_id: str = pa.Field(str_length=(1, 512))
    endpoint_slug: str = pa.Field(str_length=(1, 512))
    live_snapshot_at: str = pa.Field(str_length=(27, 27))
    provider_call_ordinal: int = pa.Field(ge=0, le=2**63 - 1)
    page_ordinal: int | None = pa.Field(nullable=True, ge=0, le=2**63 - 1)
    provider_call_role: str = pa.Field(str_length=(1, 512))
    retry_ordinal: int = pa.Field(ge=0, le=2**31 - 1)
    request_ordinal: int = pa.Field(ge=0, le=2**63 - 1)
    observation_ordinal: int = pa.Field(ge=0, lt=MAX_LIVE_LOSSLESS_OBSERVATIONS)
    global_record_ordinal: int = pa.Field(ge=0, lt=MAX_LIVE_LOSSLESS_RECORDS)
    observation_record_ordinal: int = pa.Field(ge=0, lt=MAX_LIVE_LOSSLESS_RECORDS)
    record_kind: str = pa.Field(isin=_RECORD_KINDS)
    raw_occurrence_sha256: str | None = pa.Field(nullable=True, str_matches=_SHA256_PATTERN)
    result_set_name: str | None = pa.Field(nullable=True, str_length=(1, 512))
    result_set_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_LIVE_LOSSLESS_RESULTS,
    )
    result_set_occurrence: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
    )
    node_ordinal: int | None = pa.Field(nullable=True, ge=0, lt=MAX_LIVE_LOSSLESS_NODES)
    parent_node_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_LIVE_LOSSLESS_NODES,
    )
    field_name: str | None = pa.Field(nullable=True, str_length=(1, 512))
    field_ordinal: int | None = pa.Field(nullable=True, ge=0, lt=MAX_LIVE_LOSSLESS_HEADER_COUNT)
    row_ordinal: int | None = pa.Field(nullable=True, ge=0, lt=MAX_LIVE_LOSSLESS_NODES)
    json_path: str | None = pa.Field(nullable=True, str_length=(1, 4_096))
    presence_kind: str | None = pa.Field(nullable=True, isin=_PRESENCE_KINDS)
    value_kind: str | None = pa.Field(nullable=True, isin=_VALUE_KINDS)
    canonical_json: str | None = pa.Field(
        nullable=True,
        str_length=(1, MAX_LIVE_LOSSLESS_CANONICAL_BYTES),
    )
    canonical_json_sha256: str | None = pa.Field(nullable=True, str_matches=_SHA256_PATTERN)
    value_sha256: str | None = pa.Field(nullable=True, str_matches=_SHA256_PATTERN)
    source_item_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    payload_json: str = pa.Field(str_length=(2, MAX_LIVE_LOSSLESS_CANONICAL_BYTES))
    payload_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)

    @classmethod
    def validate(cls, data: Any, *args: Any, **kwargs: Any) -> Any:
        """Type exact all-null columns without coercing any observed value."""

        if isinstance(data, (pl.DataFrame, pl.LazyFrame)):
            schema = data.schema if isinstance(data, pl.DataFrame) else data.collect_schema()
            replacements = [
                pl.col(column).cast(pl.String if column in LIVE_LOSSLESS_TEXT_COLUMNS else pl.Int64)
                for column in LIVE_LOSSLESS_NODE_COLUMNS
                if column in schema and schema[column] == pl.Null
            ]
            if replacements:
                data = data.with_columns(replacements)
        return super().validate(data, *args, **kwargs)

    @pa.dataframe_check
    @classmethod
    def canonical_utf8_bytes_are_bounded(cls, data: pa.PolarsData) -> bool:
        return bool(
            data.lazyframe.select(
                pl.col("canonical_json")
                .is_null()
                .or_(
                    pl.col("canonical_json")
                    .str.len_bytes()
                    .is_between(1, MAX_LIVE_LOSSLESS_CANONICAL_BYTES)
                )
                .all()
                .alias("canonical"),
                pl.col("payload_json")
                .str.len_bytes()
                .is_between(2, MAX_LIVE_LOSSLESS_CANONICAL_BYTES)
                .all()
                .alias("payload"),
                pl.sum_horizontal(
                    [
                        pl.col(column).fill_null("").str.len_bytes()
                        for column in LIVE_LOSSLESS_TEXT_COLUMNS
                    ]
                )
                .sum()
                .le(MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES)
                .alias("total"),
            )
            .collect()
            .row(0)
            == (True, True, True)
        )

    @pa.dataframe_check
    @classmethod
    def public_text_is_not_secret_shaped(cls, data: pa.PolarsData) -> bool:
        for row in data.lazyframe.collect().to_dicts():
            for column in LIVE_LOSSLESS_TEXT_COLUMNS:
                value = row[column]
                if value is not None and (
                    type(value) is not str or not _safe_text(value, key=column == "field_name")
                ):
                    return False
        return True

    @pa.dataframe_check
    @classmethod
    def canonical_and_nested_semantics_are_safe(cls, data: pa.PolarsData) -> bool:
        rows = data.lazyframe.collect().to_dicts()
        if len(rows) > MAX_LIVE_LOSSLESS_RECORDS:
            return False
        for row in rows:
            if not _canonical_timestamp(row["live_snapshot_at"]):
                return False
            for name in (
                "chain_id",
                "lane_id",
                "endpoint_id",
                "endpoint_slug",
                "provider_call_role",
            ):
                value = row[name]
                if (
                    type(value) is not str
                    or _SAFE_ID_RE.fullmatch(value) is None
                    or not _safe_text(value)
                ):
                    return False
            for name in ("result_set_name", "field_name"):
                value = row[name]
                if value is not None and (
                    type(value) is not str
                    or _SAFE_ID_RE.fullmatch(value) is None
                    or not _safe_text(value, key=name == "field_name")
                ):
                    return False
            path = row["json_path"]
            if path is not None and (
                type(path) is not str
                or not path.startswith("$")
                or len(path.encode("utf-8")) > MAX_LIVE_LOSSLESS_JSON_PATH_BYTES
                or not _safe_text(path)
            ):
                return False
            anomaly = _decode_safe_canonical_json(row["decoder_anomaly_codes_json"], require=list)
            if (
                type(anomaly) is not list
                or len(row["decoder_anomaly_codes_json"].encode("utf-8"))
                > MAX_LIVE_LOSSLESS_ANOMALY_BYTES
                or anomaly != sorted(set(anomaly))
                or any(type(item) is not str or item not in _ANOMALY_CODES for item in anomaly)
            ):
                return False
            if (
                _decode_safe_canonical_json(row["payload_json"], require=dict)
                is _INVALID_CANONICAL_JSON
            ):
                return False
            canonical = row["canonical_json"]
            if (
                canonical is not None
                and _decode_safe_canonical_json(canonical) is _INVALID_CANONICAL_JSON
            ):
                return False
        return True

    @pa.dataframe_check
    @classmethod
    def bundle_observation_and_record_coordinates_are_exact(
        cls,
        data: pa.PolarsData,
    ) -> bool:
        rows = data.lazyframe.collect().to_dicts()
        bundle_groups: dict[str, list[dict[str, object]]] = {}
        try:
            for row in rows:
                LiveLosslessNodeRecordV1.from_row(row)
                bundle_sha256 = row["raw_authority_bundle_sha256"]
                if type(bundle_sha256) is not str:
                    return False
                bundle_groups.setdefault(bundle_sha256, []).append(row)
        except (
            LiveLosslessValueAuthorityError,
            TypeError,
            ValueError,
            UnicodeError,
            RecursionError,
        ):
            raise ValueError(
                "live-lossless public record failed exact DTO reconstruction"
            ) from None

        for bundle_rows in bundle_groups.values():
            if tuple(row["global_record_ordinal"] for row in bundle_rows) != tuple(
                range(len(bundle_rows))
            ):
                return False

            observation_groups: dict[int, list[dict[str, object]]] = {}
            active_observation_ordinal: int | None = None
            units_by_ordinal: dict[int, tuple[object, ...]] = {}
            ordinals_by_unit_sha256: dict[str, int] = {}
            for row in bundle_rows:
                observation_ordinal = row["observation_ordinal"]
                expected_unit_ordinal = row["expected_unit_ordinal"]
                expected_unit_sha256 = row["expected_unit_sha256"]
                if (
                    type(observation_ordinal) is not int
                    or type(expected_unit_ordinal) is not int
                    or type(expected_unit_sha256) is not str
                ):
                    return False
                if observation_ordinal != active_observation_ordinal:
                    if observation_ordinal in observation_groups:
                        return False
                    if observation_ordinal != len(observation_groups):
                        return False
                    observation_groups[observation_ordinal] = []
                    active_observation_ordinal = observation_ordinal
                observation_groups[observation_ordinal].append(row)

                binding = (
                    expected_unit_sha256,
                    row["representation_assignment_sha256"],
                    observation_ordinal,
                    row["ownership_kind"],
                    row["raw_occurrence_sha256"],
                    row["ownership_occurrence_ordinal"],
                )
                existing_binding = units_by_ordinal.setdefault(
                    expected_unit_ordinal,
                    binding,
                )
                if existing_binding != binding:
                    return False
                existing_ordinal = ordinals_by_unit_sha256.setdefault(
                    expected_unit_sha256,
                    expected_unit_ordinal,
                )
                if existing_ordinal != expected_unit_ordinal:
                    return False

            if tuple(units_by_ordinal) != tuple(range(len(units_by_ordinal))):
                return False
            for observation_rows in observation_groups.values():
                if tuple(row["observation_record_ordinal"] for row in observation_rows) != tuple(
                    range(len(observation_rows))
                ):
                    return False
                first = observation_rows[0]
                common = (
                    first["raw_authority_bundle_sha256"],
                    first["observation_ordinal"],
                    first["observation_record_sha256"],
                    first["observation_sha256"],
                    first["attempt_sha256"],
                )
                if any(
                    (
                        row["raw_authority_bundle_sha256"],
                        row["observation_ordinal"],
                        row["observation_record_sha256"],
                        row["observation_sha256"],
                        row["attempt_sha256"],
                    )
                    != common
                    for row in observation_rows[1:]
                ):
                    return False
        return True

    @pa.dataframe_check
    @classmethod
    def ownership_partition_is_explicit_and_exact(cls, data: pa.PolarsData) -> bool:
        rows = data.lazyframe.collect().to_dicts()
        empty_residual_root = canonical_ordered_root_sha256(
            kind="live_lossless_response_residual_source_items_v1",
            count=0,
            item_sha256s=(),
        )
        groups: dict[tuple[str, int], list[dict[str, object]]] = {}
        for row in rows:
            occurrence_owned = row["ownership_kind"] == "result_occurrence"
            if occurrence_owned:
                if (
                    row["raw_occurrence_sha256"] is None
                    or row["ownership_occurrence_ordinal"] is None
                    or row["representation_kind"] != LIVE_LOSSLESS_REPRESENTATION_KIND
                ):
                    return False
            elif (
                row["ownership_kind"] != "response_residual"
                or row["raw_occurrence_sha256"] is not None
                or row["ownership_occurrence_ordinal"] is not None
                or row["representation_kind"] != LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND
                or row["record_kind"] != "node"
                or row["response_residual_record_count"] == 0
            ):
                return False
            if (row["response_residual_record_count"] == 0) != (
                row["response_residual_record_root_sha256"] == empty_residual_root
            ):
                return False
            raw_authority_bundle_sha256 = row["raw_authority_bundle_sha256"]
            observation_ordinal = row["observation_ordinal"]
            if type(raw_authority_bundle_sha256) is not str or type(observation_ordinal) is not int:
                return False
            groups.setdefault(
                (raw_authority_bundle_sha256, observation_ordinal),
                [],
            ).append(row)
        for group in groups.values():
            residual_source_items = tuple(
                str(row["source_item_sha256"])
                for row in group
                if row["ownership_kind"] == "response_residual"
            )
            residual_root = canonical_ordered_root_sha256(
                kind="live_lossless_response_residual_source_items_v1",
                count=len(residual_source_items),
                item_sha256s=residual_source_items,
            )
            if any(
                row["response_residual_record_count"] != len(residual_source_items)
                or row["response_residual_record_root_sha256"] != residual_root
                for row in group
            ):
                return False
        return True

    class Config:
        coerce = False
        strict = True
        ordered = True


__all__ = ["RawNbaApiLiveLosslessNodeSchema"]
