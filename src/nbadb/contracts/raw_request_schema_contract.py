"""Deterministic schema artifact for the public raw-request authority surface.

The runtime models, fixed DuckDB/Parquet table schemas, and CSV/SQLite scalar
projection are separate implementation surfaces.  This module joins them into
one canonical, replayable contract so pre-extraction admission can bind the
actual public schema instead of relying on a code-presence assertion.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Self, cast

import polars as pl

from nbadb.contracts.raw_request_authority import (
    DETERMINISTIC_GZIP_CODEC,
    DETERMINISTIC_GZIP_CONTRACT_SHA256,
    MAX_AUTHORITY_ROWS,
    MAX_PARSER_INPUT_BYTES,
    MAX_PARSER_INPUT_STORED_BYTES,
    PUBLIC_PARSER_INPUT_REPRESENTATION,
    RAW_REQUEST_AUTHORITY_BUNDLE_ADAPTER,
    RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
)
from nbadb.kaggle.raw_value_codec import (
    RAW_VALUE_CODEC_SCHEMA_VERSION,
    RAW_VALUE_CODEC_TAG,
)
from nbadb.schemas.raw.nba_api_authority import (
    RawNbaApiObservationRouteLandingSchema,
    RawNbaApiParserInputObjectSchema,
    RawNbaApiRequestObservationSchema,
    RawNbaApiResultOccurrenceSchema,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pandera.api.checks import Check

__all__ = [
    "RAW_REQUEST_SCHEMA_CONTRACT_KIND",
    "RAW_REQUEST_SCHEMA_CONTRACT_SCHEMA_VERSION",
    "RawRequestSchemaColumnV2",
    "RawRequestSchemaContractError",
    "RawRequestSchemaContractV2",
    "RawRequestSchemaTableV2",
    "compile_raw_request_schema_contract",
    "parse_raw_request_schema_contract",
]

RAW_REQUEST_SCHEMA_CONTRACT_SCHEMA_VERSION = 2
RAW_REQUEST_SCHEMA_CONTRACT_KIND = "nbadb_public_raw_request_schema_contract_v2"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,255}\Z", flags=re.ASCII)
_PRIMARY_KEYS = {
    "raw_nba_api_parser_input_object": "object_sha256",
    "raw_nba_api_request_observation": "observation_sha256",
    "raw_nba_api_result_occurrence": "occurrence_sha256",
    "raw_nba_api_observation_route_landing": "landing_sha256",
}

_PUBLIC_TABLES = (
    (
        "raw_nba_api_parser_input_object",
        RawNbaApiParserInputObjectSchema,
        "Exact parser-consumed public response bytes with deterministic compression.",
    ),
    (
        "raw_nba_api_request_observation",
        RawNbaApiRequestObservationSchema,
        "One exact allocated or completed provider request observation.",
    ),
    (
        "raw_nba_api_result_occurrence",
        RawNbaApiResultOccurrenceSchema,
        "Ordered result occurrences with exact route and receipt evidence.",
    ),
    (
        "raw_nba_api_observation_route_landing",
        RawNbaApiObservationRouteLandingSchema,
        "Response-level route landings with exact committed receipt authority.",
    ),
)


class RawRequestSchemaContractError(ValueError):
    """The public raw-request schema artifact is invalid or has drifted."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RawRequestSchemaContractError(
            "raw-request schema contract is not canonical JSON"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RawRequestSchemaContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_name(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_NAME_RE.fullmatch(value) is None:
        raise RawRequestSchemaContractError(f"{field_name} must be a safe identifier")
    return value


def _require_exact_int(value: object, *, field_name: str) -> int:
    if type(value) is not int:
        raise RawRequestSchemaContractError(f"{field_name} must be an exact integer")
    return value


def _exact_mapping(
    value: object,
    keys: frozenset[str],
    *,
    label: str,
) -> Mapping[str, object]:
    if type(value) is not dict:
        raise RawRequestSchemaContractError(f"{label} must be an exact object")
    payload = cast("Mapping[str, object]", value)
    if frozenset(payload) != keys or any(type(key) is not str for key in payload):
        raise RawRequestSchemaContractError(f"{label} schema is not exact")
    return payload


def _decode_canonical_object(raw: bytes) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw:
        raise RawRequestSchemaContractError("raw-request schema bytes must be nonempty")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RawRequestSchemaContractError(
                    f"raw-request schema contains a duplicate key: {key}"
                )
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise RawRequestSchemaContractError(
            f"raw-request schema contains a non-finite value: {value}"
        )

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
    except RawRequestSchemaContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RawRequestSchemaContractError("raw-request schema bytes are invalid JSON") from exc
    payload = _exact_mapping(
        value,
        frozenset(
            {
                "schema_version",
                "kind",
                "authority_schema_version",
                "public_parser_input_representation",
                "parser_input_codec",
                "parser_input_codec_contract_sha256",
                "max_parser_input_bytes",
                "max_parser_input_stored_bytes",
                "max_authority_rows",
                "convenience_scalar_codec_schema_version",
                "convenience_scalar_codec_tag",
                "bundle_json_schema_json",
                "bundle_json_schema_sha256",
                "table_inventory_sha256",
                "tables",
                "contract_sha256",
            }
        ),
        label="raw-request schema contract",
    )
    if _canonical_bytes(payload) != raw:
        raise RawRequestSchemaContractError("raw-request schema bytes are not canonical")
    return payload


def _json_statistics(check: Check) -> str:
    statistics = dict(check.statistics or {})
    encoded = _canonical_bytes(statistics).decode("utf-8")
    if (
        json.dumps(
            json.loads(encoded),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        != encoded
    ):
        raise RawRequestSchemaContractError("raw-request schema check statistics drifted")
    return encoded


def _logical_type(dtype: object) -> str:
    if dtype == pl.Int64:
        return "int64"
    if dtype == pl.String:
        return "string"
    if dtype == pl.Binary:
        return "binary"
    if dtype == pl.Boolean:
        return "boolean"
    if isinstance(dtype, pl.Datetime):
        if dtype.time_unit != "us" or dtype.time_zone != "UTC":
            raise RawRequestSchemaContractError(
                "raw-request datetime columns must be UTC microseconds"
            )
        return "datetime[us,UTC]"
    raise RawRequestSchemaContractError(f"unsupported raw-request logical type: {dtype!r}")


@dataclass(frozen=True, slots=True, order=True)
class RawRequestSchemaColumnV2:
    """One ordered public table column and all declared scalar checks."""

    ordinal: int
    name: str
    logical_type: str
    nullable: bool
    unique: bool
    checks: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise RawRequestSchemaContractError("raw-request column ordinal is invalid")
        _require_name(self.name, field_name="raw-request column name")
        if self.logical_type not in {
            "int64",
            "string",
            "binary",
            "boolean",
            "datetime[us,UTC]",
        }:
            raise RawRequestSchemaContractError("raw-request column logical type is invalid")
        if type(self.nullable) is not bool or type(self.unique) is not bool:
            raise RawRequestSchemaContractError("raw-request column flags must be exact booleans")
        if type(self.checks) is not tuple or self.checks != tuple(sorted(set(self.checks))):
            raise RawRequestSchemaContractError(
                "raw-request column checks must be sorted and unique"
            )
        for name, statistics_json in self.checks:
            _require_name(name, field_name="raw-request check name")
            try:
                statistics = json.loads(statistics_json)
            except json.JSONDecodeError as exc:
                raise RawRequestSchemaContractError(
                    "raw-request check statistics are invalid JSON"
                ) from exc
            if (
                type(statistics) is not dict
                or _canonical_bytes(statistics).decode() != statistics_json
            ):
                raise RawRequestSchemaContractError(
                    "raw-request check statistics are not canonical"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "name": self.name,
            "logical_type": self.logical_type,
            "nullable": self.nullable,
            "unique": self.unique,
            "checks": [
                {"name": name, "statistics_json": statistics_json}
                for name, statistics_json in self.checks
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _exact_mapping(
            value,
            frozenset({"ordinal", "name", "logical_type", "nullable", "unique", "checks"}),
            label="raw-request schema column",
        )
        checks = payload["checks"]
        if type(checks) is not list:
            raise RawRequestSchemaContractError("raw-request column checks must be an array")
        parsed_checks: list[tuple[str, str]] = []
        for item in checks:
            check = _exact_mapping(
                item,
                frozenset({"name", "statistics_json"}),
                label="raw-request schema check",
            )
            if type(check["name"]) is not str or type(check["statistics_json"]) is not str:
                raise RawRequestSchemaContractError("raw-request schema check fields are invalid")
            parsed_checks.append((check["name"], check["statistics_json"]))
        return cls(
            ordinal=cast("int", payload["ordinal"]),
            name=cast("str", payload["name"]),
            logical_type=cast("str", payload["logical_type"]),
            nullable=cast("bool", payload["nullable"]),
            unique=cast("bool", payload["unique"]),
            checks=tuple(parsed_checks),
        )


@dataclass(frozen=True, slots=True, order=True)
class RawRequestSchemaTableV2:
    """One fixed public raw table with its complete ordered column schema."""

    table_name: str
    primary_key: str
    description: str
    strict: bool
    coerce: bool
    ordered: bool
    dataframe_checks: tuple[tuple[str, str], ...]
    columns: tuple[RawRequestSchemaColumnV2, ...]

    def __post_init__(self) -> None:
        _require_name(self.table_name, field_name="raw-request table name")
        _require_name(self.primary_key, field_name="raw-request primary key")
        if type(self.description) is not str or not self.description.strip():
            raise RawRequestSchemaContractError("raw-request table description is empty")
        if any(type(value) is not bool for value in (self.strict, self.coerce, self.ordered)):
            raise RawRequestSchemaContractError("raw-request table flags must be exact booleans")
        if (self.strict, self.coerce, self.ordered) != (True, False, True):
            raise RawRequestSchemaContractError("raw-request table policy is not fail-closed")
        if self.dataframe_checks != tuple(sorted(set(self.dataframe_checks))):
            raise RawRequestSchemaContractError(
                "raw-request dataframe checks must be sorted and unique"
            )
        if type(self.columns) is not tuple or not self.columns:
            raise RawRequestSchemaContractError("raw-request table columns must be nonempty")
        if tuple(column.ordinal for column in self.columns) != tuple(range(len(self.columns))):
            raise RawRequestSchemaContractError(
                "raw-request table column ordinals are not contiguous"
            )
        if len({column.name for column in self.columns}) != len(self.columns):
            raise RawRequestSchemaContractError("raw-request table columns overlap")
        if self.primary_key not in {column.name for column in self.columns}:
            raise RawRequestSchemaContractError("raw-request primary key is not a table column")

    @property
    def schema_sha256(self) -> str:
        return _sha256(self._semantic_dict())

    def _semantic_dict(self) -> dict[str, object]:
        return {
            "table_name": self.table_name,
            "primary_key": self.primary_key,
            "description": self.description,
            "strict": self.strict,
            "coerce": self.coerce,
            "ordered": self.ordered,
            "dataframe_checks": [
                {"name": name, "statistics_json": statistics_json}
                for name, statistics_json in self.dataframe_checks
            ],
            "columns": [column.to_dict() for column in self.columns],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._semantic_dict(), "schema_sha256": self.schema_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _exact_mapping(
            value,
            frozenset(
                {
                    "table_name",
                    "primary_key",
                    "description",
                    "strict",
                    "coerce",
                    "ordered",
                    "dataframe_checks",
                    "columns",
                    "schema_sha256",
                }
            ),
            label="raw-request schema table",
        )
        raw_checks = payload["dataframe_checks"]
        raw_columns = payload["columns"]
        if type(raw_checks) is not list or type(raw_columns) is not list:
            raise RawRequestSchemaContractError("raw-request table arrays are invalid")
        checks: list[tuple[str, str]] = []
        for item in raw_checks:
            check = _exact_mapping(
                item,
                frozenset({"name", "statistics_json"}),
                label="raw-request dataframe check",
            )
            if type(check["name"]) is not str or type(check["statistics_json"]) is not str:
                raise RawRequestSchemaContractError("raw-request dataframe check is invalid")
            checks.append((check["name"], check["statistics_json"]))
        table = cls(
            table_name=cast("str", payload["table_name"]),
            primary_key=cast("str", payload["primary_key"]),
            description=cast("str", payload["description"]),
            strict=cast("bool", payload["strict"]),
            coerce=cast("bool", payload["coerce"]),
            ordered=cast("bool", payload["ordered"]),
            dataframe_checks=tuple(checks),
            columns=tuple(RawRequestSchemaColumnV2.from_dict(item) for item in raw_columns),
        )
        if payload["schema_sha256"] != table.schema_sha256:
            raise RawRequestSchemaContractError("raw-request table schema digest is stale")
        return table


def _compile_current_table_rows() -> tuple[RawRequestSchemaTableV2, ...]:
    """Compile the current Pandera tables without trusting serialized rows."""

    table_rows: list[RawRequestSchemaTableV2] = []
    for table_name, schema_type, description in _PUBLIC_TABLES:
        schema = schema_type.to_schema()
        columns = tuple(
            RawRequestSchemaColumnV2(
                ordinal=ordinal,
                name=name,
                logical_type=_logical_type(column.dtype.type),
                nullable=bool(column.nullable),
                unique=bool(column.unique),
                checks=tuple(
                    sorted((check.name, _json_statistics(check)) for check in column.checks)
                ),
            )
            for ordinal, (name, column) in enumerate(schema.columns.items())
        )
        dataframe_checks = tuple(
            sorted((check.name, _json_statistics(check)) for check in (schema.checks or []))
        )
        try:
            primary_key = _PRIMARY_KEYS[table_name]
        except KeyError as exc:
            raise RawRequestSchemaContractError(
                "raw-request publication inventory contains a foreign table"
            ) from exc
        table_rows.append(
            RawRequestSchemaTableV2(
                table_name=table_name,
                primary_key=primary_key,
                description=description,
                strict=bool(schema.strict),
                coerce=bool(schema.coerce),
                ordered=bool(schema.ordered),
                dataframe_checks=dataframe_checks,
                columns=columns,
            )
        )
    return tuple(sorted(table_rows, key=lambda table: table.table_name))


def _compile_current_bundle_json_schema() -> str:
    """Compile the exact current V2 bundle schema independently of input bytes."""

    return _canonical_bytes(RAW_REQUEST_AUTHORITY_BUNDLE_ADAPTER.json_schema()).decode("utf-8")


@dataclass(frozen=True, slots=True)
class RawRequestSchemaContractV2:
    """Canonical static schema authority for all public raw-request artifacts."""

    authority_schema_version: int
    public_parser_input_representation: str
    parser_input_codec: str
    parser_input_codec_contract_sha256: str
    max_parser_input_bytes: int
    max_parser_input_stored_bytes: int
    max_authority_rows: int
    convenience_scalar_codec_schema_version: int
    convenience_scalar_codec_tag: str
    bundle_json_schema_json: str
    tables: tuple[RawRequestSchemaTableV2, ...]

    schema_version: ClassVar[int] = RAW_REQUEST_SCHEMA_CONTRACT_SCHEMA_VERSION
    kind: ClassVar[str] = RAW_REQUEST_SCHEMA_CONTRACT_KIND

    def __post_init__(self) -> None:
        _require_exact_int(
            self.authority_schema_version,
            field_name="authority_schema_version",
        )
        if self.authority_schema_version != RAW_REQUEST_AUTHORITY_SCHEMA_VERSION:
            raise RawRequestSchemaContractError("raw-request authority schema version drifted")
        if self.public_parser_input_representation != PUBLIC_PARSER_INPUT_REPRESENTATION:
            raise RawRequestSchemaContractError("raw-request representation drifted")
        if self.parser_input_codec != DETERMINISTIC_GZIP_CODEC:
            raise RawRequestSchemaContractError("raw-request parser-input codec drifted")
        _require_sha256(
            self.parser_input_codec_contract_sha256,
            field_name="parser_input_codec_contract_sha256",
        )
        if self.parser_input_codec_contract_sha256 != DETERMINISTIC_GZIP_CONTRACT_SHA256:
            raise RawRequestSchemaContractError("raw-request parser-input codec contract drifted")
        _require_exact_int(
            self.max_parser_input_bytes,
            field_name="max_parser_input_bytes",
        )
        _require_exact_int(
            self.max_parser_input_stored_bytes,
            field_name="max_parser_input_stored_bytes",
        )
        _require_exact_int(
            self.max_authority_rows,
            field_name="max_authority_rows",
        )
        if (
            self.max_parser_input_bytes != MAX_PARSER_INPUT_BYTES
            or self.max_parser_input_stored_bytes != MAX_PARSER_INPUT_STORED_BYTES
            or self.max_authority_rows != MAX_AUTHORITY_ROWS
        ):
            raise RawRequestSchemaContractError("raw-request schema bounds drifted")
        _require_exact_int(
            self.convenience_scalar_codec_schema_version,
            field_name="convenience_scalar_codec_schema_version",
        )
        if (
            self.convenience_scalar_codec_schema_version != RAW_VALUE_CODEC_SCHEMA_VERSION
            or self.convenience_scalar_codec_tag != RAW_VALUE_CODEC_TAG
        ):
            raise RawRequestSchemaContractError("raw-request convenience codec drifted")
        try:
            bundle_schema = json.loads(self.bundle_json_schema_json)
        except json.JSONDecodeError as exc:
            raise RawRequestSchemaContractError(
                "raw-request bundle JSON schema is invalid"
            ) from exc
        if (
            type(bundle_schema) is not dict
            or _canonical_bytes(bundle_schema).decode() != self.bundle_json_schema_json
        ):
            raise RawRequestSchemaContractError("raw-request bundle JSON schema is not canonical")
        if type(self.tables) is not tuple or self.tables != tuple(
            sorted(self.tables, key=lambda table: table.table_name)
        ):
            raise RawRequestSchemaContractError("raw-request tables must be sorted")
        if {table.table_name for table in self.tables} != set(_PRIMARY_KEYS):
            raise RawRequestSchemaContractError("raw-request table inventory is incomplete")
        if any(_PRIMARY_KEYS[table.table_name] != table.primary_key for table in self.tables):
            raise RawRequestSchemaContractError("raw-request primary-key authority drifted")
        if self.bundle_json_schema_json != _compile_current_bundle_json_schema():
            raise RawRequestSchemaContractError(
                "raw-request bundle JSON schema differs from current runtime authority"
            )
        if self.tables != _compile_current_table_rows():
            raise RawRequestSchemaContractError(
                "raw-request table schema differs from current Pandera authority"
            )

    @property
    def bundle_json_schema_sha256(self) -> str:
        return hashlib.sha256(self.bundle_json_schema_json.encode("utf-8")).hexdigest()

    @property
    def table_inventory_sha256(self) -> str:
        return _sha256([table.to_dict() for table in self.tables])

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_schema_version": self.authority_schema_version,
            "public_parser_input_representation": self.public_parser_input_representation,
            "parser_input_codec": self.parser_input_codec,
            "parser_input_codec_contract_sha256": self.parser_input_codec_contract_sha256,
            "max_parser_input_bytes": self.max_parser_input_bytes,
            "max_parser_input_stored_bytes": self.max_parser_input_stored_bytes,
            "max_authority_rows": self.max_authority_rows,
            "convenience_scalar_codec_schema_version": (
                self.convenience_scalar_codec_schema_version
            ),
            "convenience_scalar_codec_tag": self.convenience_scalar_codec_tag,
            "bundle_json_schema_json": self.bundle_json_schema_json,
            "bundle_json_schema_sha256": self.bundle_json_schema_sha256,
            "table_inventory_sha256": self.table_inventory_sha256,
            "tables": [table.to_dict() for table in self.tables],
        }

    @property
    def contract_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "contract_sha256": self.contract_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _exact_mapping(
            value,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "authority_schema_version",
                    "public_parser_input_representation",
                    "parser_input_codec",
                    "parser_input_codec_contract_sha256",
                    "max_parser_input_bytes",
                    "max_parser_input_stored_bytes",
                    "max_authority_rows",
                    "convenience_scalar_codec_schema_version",
                    "convenience_scalar_codec_tag",
                    "bundle_json_schema_json",
                    "bundle_json_schema_sha256",
                    "table_inventory_sha256",
                    "tables",
                    "contract_sha256",
                }
            ),
            label="raw-request schema contract",
        )
        tables = payload["tables"]
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(tables) is not list
        ):
            raise RawRequestSchemaContractError("raw-request schema identity is invalid")
        authority_schema_version = _require_exact_int(
            payload["authority_schema_version"],
            field_name="authority_schema_version",
        )
        convenience_scalar_codec_schema_version = _require_exact_int(
            payload["convenience_scalar_codec_schema_version"],
            field_name="convenience_scalar_codec_schema_version",
        )
        max_parser_input_bytes = _require_exact_int(
            payload["max_parser_input_bytes"],
            field_name="max_parser_input_bytes",
        )
        max_parser_input_stored_bytes = _require_exact_int(
            payload["max_parser_input_stored_bytes"],
            field_name="max_parser_input_stored_bytes",
        )
        max_authority_rows = _require_exact_int(
            payload["max_authority_rows"],
            field_name="max_authority_rows",
        )
        contract = cls(
            authority_schema_version=authority_schema_version,
            public_parser_input_representation=cast(
                "str", payload["public_parser_input_representation"]
            ),
            parser_input_codec=cast("str", payload["parser_input_codec"]),
            parser_input_codec_contract_sha256=cast(
                "str", payload["parser_input_codec_contract_sha256"]
            ),
            max_parser_input_bytes=max_parser_input_bytes,
            max_parser_input_stored_bytes=max_parser_input_stored_bytes,
            max_authority_rows=max_authority_rows,
            convenience_scalar_codec_schema_version=(convenience_scalar_codec_schema_version),
            convenience_scalar_codec_tag=cast("str", payload["convenience_scalar_codec_tag"]),
            bundle_json_schema_json=cast("str", payload["bundle_json_schema_json"]),
            tables=tuple(RawRequestSchemaTableV2.from_dict(item) for item in tables),
        )
        if (
            payload["bundle_json_schema_sha256"] != contract.bundle_json_schema_sha256
            or payload["table_inventory_sha256"] != contract.table_inventory_sha256
            or payload["contract_sha256"] != contract.contract_sha256
        ):
            raise RawRequestSchemaContractError("raw-request schema digest is stale")
        return contract

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_object(raw))


def compile_raw_request_schema_contract() -> RawRequestSchemaContractV2:
    """Compile the current fixed public schema and strict bundle model twice-readably."""

    return RawRequestSchemaContractV2(
        authority_schema_version=RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        public_parser_input_representation=PUBLIC_PARSER_INPUT_REPRESENTATION,
        parser_input_codec=DETERMINISTIC_GZIP_CODEC,
        parser_input_codec_contract_sha256=DETERMINISTIC_GZIP_CONTRACT_SHA256,
        max_parser_input_bytes=MAX_PARSER_INPUT_BYTES,
        max_parser_input_stored_bytes=MAX_PARSER_INPUT_STORED_BYTES,
        max_authority_rows=MAX_AUTHORITY_ROWS,
        convenience_scalar_codec_schema_version=RAW_VALUE_CODEC_SCHEMA_VERSION,
        convenience_scalar_codec_tag=RAW_VALUE_CODEC_TAG,
        bundle_json_schema_json=_compile_current_bundle_json_schema(),
        tables=_compile_current_table_rows(),
    )


def parse_raw_request_schema_contract(raw: bytes) -> RawRequestSchemaContractV2:
    """Parse only canonical duplicate-free bytes and revalidate every derived digest."""

    return RawRequestSchemaContractV2.from_canonical_bytes(raw)
