"""Strict public schema for normalized stats/static result-cell authority."""

from __future__ import annotations

import json
import math
import re
from typing import cast

import pandera.polars as pa
import polars as pl

from nbadb.contracts.raw_request_authority import (
    MAX_JSON_NODES,
    MAX_PARSER_INPUT_BYTES,
    canonical_json_bytes,
)
from nbadb.schemas.base import BaseSchema

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_MAX_PUBLIC_JSON_DEPTH = 64
_MAX_INTEGER_ABS = (1 << 63) - 1
_MAX_NUMBER_TOKEN_BYTES = 128
_AUTHORIZATION_HEADER_SECRET_RE = re.compile(
    r"authorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}",
    flags=re.ASCII | re.IGNORECASE,
)
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])", flags=re.ASCII)
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])", flags=re.ASCII)
_KEY_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+", flags=re.ASCII)
_SENSITIVE_OBJECT_KEY_RE = re.compile(
    r"(?:authorization|cookie|set_cookie|credential|client_secret|access_token|"
    r"refresh_token|api_key|password|proxy_url|proxy_host|vpn_server|vpn_ip|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|private_key|secret_key|personal_access_token|ssh_private_key)\Z",
    flags=re.ASCII,
)
_GENERIC_SENSITIVE_KEY_COMPONENTS = frozenset({"auth", "session", "secret", "token"})
_LOCAL_PATH_VALUE_RE = re.compile(
    r"(?:/Users/[^/\x00\s]+(?=/|\s|\Z)|/home/[^/\x00\s]+(?=/|\s|\Z)|"
    r"/private/var(?![A-Za-z0-9_])|[A-Za-z]:\\Users\\)"
)
_BEARER_SECRET_RE = re.compile(
    r"bearer\s+[A-Za-z0-9._~+/=-]{20,}(?![A-Za-z0-9._~+/=-])",
    flags=re.ASCII | re.IGNORECASE,
)
_BASIC_SECRET_RE = re.compile(
    r"basic\s+[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=])",
    flags=re.ASCII | re.IGNORECASE,
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


def _normalized_public_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _is_secret_shaped_public_text(value: str) -> bool:
    stripped = value.strip()
    return (
        _AUTHORIZATION_HEADER_SECRET_RE.search(stripped) is not None
        or _BEARER_SECRET_RE.search(stripped) is not None
        or _BASIC_SECRET_RE.search(stripped) is not None
        or _LOCAL_PATH_VALUE_RE.search(value) is not None
        or any(pattern.search(value) is not None for pattern in _EMBEDDED_SECRET_RES)
    )


def _is_public_safe_header(value: object) -> bool:
    if type(value) is not str:
        return False
    normalized = _normalized_public_key(value)
    return not (
        _SENSITIVE_OBJECT_KEY_RE.fullmatch(normalized) is not None
        or any(
            component in _GENERIC_SENSITIVE_KEY_COMPONENTS for component in normalized.split("_")
        )
        or _is_secret_shaped_public_text(value)
    )


def _reject_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _preflight_canonical_json_bytes(raw: bytes) -> bool:
    depth = 0
    maximum_depth = 0
    nodes = 1
    in_string = False
    escaped = False
    index = 0
    while index < len(raw):
        byte = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            index += 1
            continue
        if byte == 0x22:
            in_string = True
            index += 1
            continue
        if byte in (0x7B, 0x5B):
            depth += 1
            maximum_depth = max(maximum_depth, depth)
            nodes += 1
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                return False
        elif byte in (0x2C, 0x3A):
            nodes += 1
        elif byte == 0x2D or 0x30 <= byte <= 0x39:
            end = index + 1
            while end < len(raw) and raw[end] not in b" \t\r\n,]}":
                end += 1
            if end - index > _MAX_NUMBER_TOKEN_BYTES:
                return False
            index = end
            if maximum_depth > _MAX_PUBLIC_JSON_DEPTH or nodes > MAX_JSON_NODES:
                return False
            continue
        if maximum_depth > _MAX_PUBLIC_JSON_DEPTH or nodes > MAX_JSON_NODES:
            return False
        index += 1
    return not in_string and not escaped and depth == 0


def _bounded_integer_token(token: str) -> int:
    if len(token) > _MAX_NUMBER_TOKEN_BYTES:
        raise ValueError("invalid number")
    value = int(token)
    if abs(value) > _MAX_INTEGER_ABS:
        raise ValueError("invalid number")
    return value


def _bounded_float_token(token: str) -> float:
    if len(token) > _MAX_NUMBER_TOKEN_BYTES:
        raise ValueError("invalid number")
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("invalid number")
    return value


def _reject_nonfinite_constant(_token: str) -> object:
    raise ValueError("invalid number")


def _is_public_safe_canonical_json(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    if not raw or len(raw) > MAX_PARSER_INPUT_BYTES or not _preflight_canonical_json_bytes(raw):
        return False
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_object,
            parse_constant=_reject_nonfinite_constant,
            parse_float=_bounded_float_token,
            parse_int=_bounded_integer_token,
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False
    nodes = 0
    stack: list[tuple[object, int]] = [(decoded, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > _MAX_PUBLIC_JSON_DEPTH:
            return False
        if type(item) is dict:
            mapping = cast("dict[str, object]", item)
            for key, child in mapping.items():
                if not _is_public_safe_header(key):
                    return False
                stack.append((child, depth + 1))
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in cast("list[object]", item))
        elif (
            (type(item) is str and _is_secret_shaped_public_text(item))
            or (type(item) is int and abs(item) > _MAX_INTEGER_ABS)
            or (
                type(item) is float
                and (not math.isfinite(item) or (item == 0.0 and math.copysign(1.0, item) < 0))
            )
        ):
            return False
    try:
        return canonical_json_bytes(decoded, maximum_bytes=MAX_PARSER_INPUT_BYTES) == raw
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False


def _column_values(data: pa.PolarsData, column: str) -> list[object]:
    return cast(
        "list[object]",
        data.lazyframe.select(pl.col(column)).collect().get_column(column).to_list(),
    )


class RawNbaApiResultCellSchema(BaseSchema):
    """One exact provider value under a Raw Authority V2 result occurrence."""

    schema_version: int = pa.Field(eq=2)
    cell_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    occurrence_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    cell_ordinal: int = pa.Field(ge=0, le=2**63 - 1)
    row_ordinal: int = pa.Field(ge=0, le=2**63 - 1)
    header_ordinal: int = pa.Field(ge=0, le=2**63 - 1)
    header_name: str = pa.Field(str_length=(1, 256))
    presence_kind: str = pa.Field(isin=["present", "null", "empty_object", "empty_array"])
    value_kind: str = pa.Field(
        isin=["null", "boolean", "integer", "number", "string", "array", "object"]
    )
    canonical_json: str = pa.Field(str_length=(1, MAX_PARSER_INPUT_BYTES))
    canonical_json_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)

    @pa.dataframe_check
    @classmethod
    def canonical_json_utf8_bytes_are_bounded(cls, data: pa.PolarsData) -> bool:
        """Enforce the persistence byte contract, not Unicode code-point length."""

        return bool(
            data.lazyframe.select(
                pl.col("canonical_json").str.len_bytes().is_between(1, MAX_PARSER_INPUT_BYTES).all()
            )
            .collect()
            .item()
        )

    @pa.dataframe_check
    @classmethod
    def header_names_are_public_safe(cls, data: pa.PolarsData) -> bool:
        """Reject sensitive-key and credential-shaped headers without echoing them."""

        return all(_is_public_safe_header(value) for value in _column_values(data, "header_name"))

    @pa.dataframe_check
    @classmethod
    def canonical_json_is_public_safe(cls, data: pa.PolarsData) -> bool:
        """Reject nested credential-shaped public values without echoing them."""

        return all(
            _is_public_safe_canonical_json(value)
            for value in _column_values(data, "canonical_json")
        )

    class Config:
        coerce = False
        strict = True
        ordered = True


__all__ = ["RawNbaApiResultCellSchema"]
