"""Value-free row contract for Public Value Authority route-field landings.

The rows bind one exact Raw Authority V2 route landing, one expected value
unit/representation assignment, and either one ordered landing field or the
explicit zero-field sentinel.  They deliberately carry no provider values,
receipt identity JSON, or embedded typed-value DTOs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import ClassVar, Final, Never, Self, cast

from nbadb.contracts.public_value_types import (
    EXPECTED_VALUE_UNIT_KINDS_V1,
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    PUBLIC_VALUE_REPRESENTATION_KINDS_V1,
    PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1,
    ExpectedValueUnitKindV1,
    PublicValueRepresentationKindV1,
    PublicValueSourceInputKindV1,
    PublicValueTypesError,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.typed_field_value_receipt import MAX_ROUTE_FIELDS

__all__ = [
    "RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS",
    "MAX_ROUTE_FIELD_LANDING_ROWS",
    "RawNbaApiRouteFieldLandingV1",
    "RouteFieldLandingAuthorityError",
]


MAX_ROUTE_FIELD_LANDING_ROWS: Final = 10_000_000
MAX_ROUTE_FIELD_LANDING_FIELDS: Final = MAX_ROUTE_FIELDS
MAX_ROUTE_FIELD_LANDING_RECEIPTS: Final = 1_000_000

RouteFieldLandingRowKindV1 = str
RouteFieldOriginV1 = str

_ROW_KINDS: Final = frozenset({"field_binding", "route_only"})
_FIELD_ORIGINS: Final = frozenset(
    {"provider_bound", "provider_multi_bound", "lossless_bound", "storage_only"}
)
_UNIT_KINDS = frozenset(EXPECTED_VALUE_UNIT_KINDS_V1)
_SOURCE_INPUT_KINDS = frozenset(PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1)
_REPRESENTATION_KINDS = frozenset(PUBLIC_VALUE_REPRESENTATION_KINDS_V1)
_RESULT_REPRESENTATIONS = frozenset(
    {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
    }
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z", flags=re.ASCII)
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])", flags=re.ASCII)
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])", flags=re.ASCII)
_KEY_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+", flags=re.ASCII)
_SENSITIVE_FIELD_KEY_RE = re.compile(
    r"(?:authorization|proxy_authorization|authentication|cookie|set_cookie|credential|"
    r"secret|token|client_secret|client_key|access_token|refresh_token|id_token|api_key|"
    r"apikey|password|passwd|proxy_url|proxy_host|vpn_server|vpn_ip|vpn_password|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|gh_token|pat|private_key|secret_key|personal_access_token|"
    r"ssh_private_key)\Z",
    flags=re.ASCII,
)
_GENERIC_SENSITIVE_FIELD_COMPONENTS = frozenset({"auth", "session", "secret", "token"})
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
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
        flags=re.ASCII,
    ),
)

RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS: Final = (
    "schema_version",
    "landing_field_sha256",
    "landing_field_ordinal",
    "route_receipt_ordinal",
    "raw_authority_bundle_sha256",
    "route_landing_receipt_sha256",
    "raw_route_landing_sha256",
    "observation_sha256",
    "route_ordinal",
    "route_id",
    "staging_key",
    "unit_sha256",
    "unit_ordinal",
    "unit_kind",
    "occurrence_sha256",
    "occurrence_ordinal",
    "assignment_sha256",
    "source_input_kind",
    "representation_kind",
    "row_kind",
    "field_ordinal",
    "field_name",
    "field_authority_sha256",
    "field_origin",
    "logical_type_sha256",
)

_ROW_IDENTITY_KIND: Final = "raw_nba_api_route_field_landing_v1"


class RouteFieldLandingAuthorityError(ValueError):
    """One value-free route-field landing row is unsafe or inconsistent."""


def _fail(message: str) -> Never:
    raise RouteFieldLandingAuthorityError(message)


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _ordinal(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value >= maximum:
        _fail(f"{label} must be one bounded nonnegative exact integer")
    return value


def _safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact public-safe identifier")
    return value


def _safe_field_name(value: object) -> str:
    if type(value) is not str or not value or len(value) > 1_024:
        _fail("route-field landing field name is absent or over bound")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("route-field landing field name contains invalid Unicode")
    stripped = value.strip()
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    normalized = _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()
    if (
        not encoded
        or len(encoded) > 8_192
        or any(ord(character) < 0x20 for character in value)
        or _AUTHORIZATION_HEADER_SECRET_RE.search(stripped) is not None
        or _BEARER_SECRET_RE.search(stripped) is not None
        or _BASIC_SECRET_RE.search(stripped) is not None
        or _LOCAL_PATH_VALUE_RE.search(value) is not None
        or _SENSITIVE_FIELD_KEY_RE.fullmatch(normalized) is not None
        or any(
            component in _GENERIC_SENSITIVE_FIELD_COMPONENTS for component in normalized.split("_")
        )
        or any(pattern.search(value) is not None for pattern in _EMBEDDED_SECRET_RES)
    ):
        _fail("route-field landing field name is not public-safe")
    return value


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("route-field landing identity is not canonical JSON")
    if not encoded or len(encoded) > 64 * 1024:
        _fail("route-field landing identity exceeds its byte bound")
    return hashlib.sha256(encoded).hexdigest()


def _strict_row(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _fail("route-field landing row lacks its exact ordered columns")
    mapping = cast("dict[object, object]", value)
    if any(type(key) is not str for key in mapping) or tuple(mapping) != (
        RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS
    ):
        _fail("route-field landing row lacks its exact ordered columns")
    return cast("dict[str, object]", value)


def _identity_payload(values: dict[str, object]) -> dict[str, object]:
    return {
        "kind": _ROW_IDENTITY_KIND,
        **{
            column: values[column]
            for column in RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS
            if column != "landing_field_sha256"
        },
    }


@dataclass(frozen=True, slots=True)
class RawNbaApiRouteFieldLandingV1:
    """One exact unit × route-field binding, without provider values."""

    landing_field_sha256: str
    landing_field_ordinal: int
    route_receipt_ordinal: int
    raw_authority_bundle_sha256: str
    route_landing_receipt_sha256: str
    raw_route_landing_sha256: str
    observation_sha256: str
    route_ordinal: int
    route_id: str
    staging_key: str
    unit_sha256: str
    unit_ordinal: int
    unit_kind: ExpectedValueUnitKindV1
    occurrence_sha256: str | None
    occurrence_ordinal: int | None
    assignment_sha256: str
    source_input_kind: PublicValueSourceInputKindV1
    representation_kind: PublicValueRepresentationKindV1
    row_kind: RouteFieldLandingRowKindV1
    field_ordinal: int | None
    field_name: str | None
    field_authority_sha256: str | None
    field_origin: RouteFieldOriginV1 | None
    logical_type_sha256: str | None

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for label, value in (
            ("landing-field identity", self.landing_field_sha256),
            ("raw authority bundle", self.raw_authority_bundle_sha256),
            ("route landing receipt", self.route_landing_receipt_sha256),
            ("raw route landing", self.raw_route_landing_sha256),
            ("observation", self.observation_sha256),
            ("expected unit", self.unit_sha256),
            ("representation assignment", self.assignment_sha256),
        ):
            _sha256(value, label=label)
        _ordinal(
            self.landing_field_ordinal,
            label="landing-field ordinal",
            maximum=MAX_ROUTE_FIELD_LANDING_ROWS,
        )
        _ordinal(
            self.route_receipt_ordinal,
            label="route-receipt ordinal",
            maximum=MAX_ROUTE_FIELD_LANDING_RECEIPTS,
        )
        _ordinal(
            self.route_ordinal, label="route ordinal", maximum=MAX_ROUTE_FIELD_LANDING_RECEIPTS
        )
        _ordinal(
            self.unit_ordinal,
            label="expected-unit ordinal",
            maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS,
        )
        _safe_id(self.route_id, label="route identity")
        _safe_id(self.staging_key, label="staging identity")
        if type(self.unit_kind) is not str or self.unit_kind not in _UNIT_KINDS:
            _fail("route-field landing unit kind is outside the closed V1 domain")
        if type(self.source_input_kind) is not str or self.source_input_kind not in (
            _SOURCE_INPUT_KINDS
        ):
            _fail("route-field landing source-input kind is outside the closed V1 domain")
        if type(self.representation_kind) is not str or self.representation_kind not in (
            _REPRESENTATION_KINDS
        ):
            _fail("route-field landing representation is outside the closed V1 domain")
        if self.unit_kind == "result_occurrence":
            _sha256(self.occurrence_sha256, label="route-field landing occurrence")
            _ordinal(
                self.occurrence_ordinal,
                label="route-field landing occurrence ordinal",
                maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS,
            )
            if self.representation_kind not in _RESULT_REPRESENTATIONS:
                _fail("result-occurrence landing uses a response-level representation")
        else:
            if self.occurrence_sha256 is not None or self.occurrence_ordinal is not None:
                _fail("response route-field landing invents occurrence identity")
            expected_representation = (
                "response_lossless_records_v1"
                if self.unit_kind == "response_residual"
                else "response_fixed_zero_v1"
            )
            if self.representation_kind != expected_representation:
                _fail("response route-field landing has the wrong representation")
        try:
            ValueRepresentationAssignmentV1(
                assignment_sha256=self.assignment_sha256,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                unit_sha256=self.unit_sha256,
                unit_ordinal=self.unit_ordinal,
                source_input_kind=self.source_input_kind,
                representation_kind=self.representation_kind,
            )
        except PublicValueTypesError:
            _fail("route-field landing assignment binding is invalid")
        if type(self.row_kind) is not str or self.row_kind not in _ROW_KINDS:
            _fail("route-field landing row kind is outside the closed V1 domain")
        field_values = (
            self.field_ordinal,
            self.field_name,
            self.field_authority_sha256,
            self.field_origin,
            self.logical_type_sha256,
        )
        if self.row_kind == "route_only":
            if any(value is not None for value in field_values):
                _fail("route-only landing fabricates field authority")
        else:
            if any(value is None for value in field_values):
                _fail("field-binding landing omits field authority")
            _ordinal(
                self.field_ordinal,
                label="route-field field ordinal",
                maximum=MAX_ROUTE_FIELD_LANDING_FIELDS,
            )
            _safe_field_name(self.field_name)
            _sha256(self.field_authority_sha256, label="route-field field authority")
            if type(self.field_origin) is not str or self.field_origin not in _FIELD_ORIGINS:
                _fail("route-field field origin is outside the closed domain")
            _sha256(self.logical_type_sha256, label="route-field logical type")
        if self.landing_field_sha256 != _canonical_sha256(_identity_payload(self.to_row())):
            _fail("route-field landing digest differs from its exact row identity")

    @classmethod
    def build(
        cls,
        *,
        landing_field_ordinal: int,
        route_receipt_ordinal: int,
        raw_authority_bundle_sha256: str,
        route_landing_receipt_sha256: str,
        raw_route_landing_sha256: str,
        observation_sha256: str,
        route_ordinal: int,
        route_id: str,
        staging_key: str,
        unit_sha256: str,
        unit_ordinal: int,
        unit_kind: ExpectedValueUnitKindV1,
        occurrence_sha256: str | None,
        occurrence_ordinal: int | None,
        assignment_sha256: str,
        source_input_kind: PublicValueSourceInputKindV1,
        representation_kind: PublicValueRepresentationKindV1,
        row_kind: RouteFieldLandingRowKindV1,
        field_ordinal: int | None,
        field_name: str | None,
        field_authority_sha256: str | None,
        field_origin: RouteFieldOriginV1 | None,
        logical_type_sha256: str | None,
    ) -> Self:
        values: dict[str, object] = {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "landing_field_sha256": "0" * 64,
            "landing_field_ordinal": landing_field_ordinal,
            "route_receipt_ordinal": route_receipt_ordinal,
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "route_landing_receipt_sha256": route_landing_receipt_sha256,
            "raw_route_landing_sha256": raw_route_landing_sha256,
            "observation_sha256": observation_sha256,
            "route_ordinal": route_ordinal,
            "route_id": route_id,
            "staging_key": staging_key,
            "unit_sha256": unit_sha256,
            "unit_ordinal": unit_ordinal,
            "unit_kind": unit_kind,
            "occurrence_sha256": occurrence_sha256,
            "occurrence_ordinal": occurrence_ordinal,
            "assignment_sha256": assignment_sha256,
            "source_input_kind": source_input_kind,
            "representation_kind": representation_kind,
            "row_kind": row_kind,
            "field_ordinal": field_ordinal,
            "field_name": field_name,
            "field_authority_sha256": field_authority_sha256,
            "field_origin": field_origin,
            "logical_type_sha256": logical_type_sha256,
        }
        values["landing_field_sha256"] = _canonical_sha256(_identity_payload(values))
        return cls.from_row(values)

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "landing_field_sha256": self.landing_field_sha256,
            "landing_field_ordinal": self.landing_field_ordinal,
            "route_receipt_ordinal": self.route_receipt_ordinal,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "route_landing_receipt_sha256": self.route_landing_receipt_sha256,
            "raw_route_landing_sha256": self.raw_route_landing_sha256,
            "observation_sha256": self.observation_sha256,
            "route_ordinal": self.route_ordinal,
            "route_id": self.route_id,
            "staging_key": self.staging_key,
            "unit_sha256": self.unit_sha256,
            "unit_ordinal": self.unit_ordinal,
            "unit_kind": self.unit_kind,
            "occurrence_sha256": self.occurrence_sha256,
            "occurrence_ordinal": self.occurrence_ordinal,
            "assignment_sha256": self.assignment_sha256,
            "source_input_kind": self.source_input_kind,
            "representation_kind": self.representation_kind,
            "row_kind": self.row_kind,
            "field_ordinal": self.field_ordinal,
            "field_name": self.field_name,
            "field_authority_sha256": self.field_authority_sha256,
            "field_origin": self.field_origin,
            "logical_type_sha256": self.logical_type_sha256,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_row(value)
        if type(row["schema_version"]) is not int or row["schema_version"] != (
            PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
        ):
            _fail("route-field landing schema version is invalid")
        try:
            return cls(
                landing_field_sha256=cast("str", row["landing_field_sha256"]),
                landing_field_ordinal=cast("int", row["landing_field_ordinal"]),
                route_receipt_ordinal=cast("int", row["route_receipt_ordinal"]),
                raw_authority_bundle_sha256=cast("str", row["raw_authority_bundle_sha256"]),
                route_landing_receipt_sha256=cast("str", row["route_landing_receipt_sha256"]),
                raw_route_landing_sha256=cast("str", row["raw_route_landing_sha256"]),
                observation_sha256=cast("str", row["observation_sha256"]),
                route_ordinal=cast("int", row["route_ordinal"]),
                route_id=cast("str", row["route_id"]),
                staging_key=cast("str", row["staging_key"]),
                unit_sha256=cast("str", row["unit_sha256"]),
                unit_ordinal=cast("int", row["unit_ordinal"]),
                unit_kind=cast("ExpectedValueUnitKindV1", row["unit_kind"]),
                occurrence_sha256=cast("str | None", row["occurrence_sha256"]),
                occurrence_ordinal=cast("int | None", row["occurrence_ordinal"]),
                assignment_sha256=cast("str", row["assignment_sha256"]),
                source_input_kind=cast("PublicValueSourceInputKindV1", row["source_input_kind"]),
                representation_kind=cast(
                    "PublicValueRepresentationKindV1", row["representation_kind"]
                ),
                row_kind=cast("str", row["row_kind"]),
                field_ordinal=cast("int | None", row["field_ordinal"]),
                field_name=cast("str | None", row["field_name"]),
                field_authority_sha256=cast("str | None", row["field_authority_sha256"]),
                field_origin=cast("str | None", row["field_origin"]),
                logical_type_sha256=cast("str | None", row["logical_type_sha256"]),
            )
        except (TypeError, ValueError) as exc:
            raise RouteFieldLandingAuthorityError(
                "route-field landing row failed exact semantic replay"
            ) from exc

    def canonical_bytes(self) -> bytes:
        try:
            return json.dumps(
                self.to_row(),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8", errors="strict")
        except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
            _fail("route-field landing row cannot be encoded canonically")
