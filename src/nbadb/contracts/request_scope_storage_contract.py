"""Canonical storage authority for request-scope columns added after decoding.

Stats result packets frequently omit the season, season type, or league that
selected them.  :mod:`nbadb.extract.base` retains those request dimensions as
columns after provider-field canonicalization.  They are not provider response
fields, so this module models them as a separate, code-owned storage authority
derived from the exact pinned parameter names accepted by each route.

The logical types below are semantic policy, not observations of a returned
Arrow frame.  A landing frame is admitted only when its optional suffix is an
ordered subset of these independently declared fields and every present field
has the exact declared Arrow type.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar, Final, Literal, cast

import pyarrow as pa

type RequestScopeLogicalType = Literal["int64", "large_string"]

REQUEST_SCOPE_STORAGE_SCHEMA_VERSION: Final = 1
EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT: Final = 608
EXPECTED_REQUEST_SCOPE_STORAGE_ROUTE_COUNT: Final = 313
EXPECTED_REQUEST_SCOPE_STORAGE_COLUMN_COUNTS: Final = MappingProxyType(
    {
        "league_id": 309,
        "season_type": 127,
        "season_year": 172,
    }
)


class RequestScopeStorageContractError(ValueError):
    """Raised when request-derived storage authority is missing or ambiguous."""


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RequestScopeStorageContractError(
            "request-scope storage authority is not canonical JSON"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _exact_text_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or any(type(item) is not str or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise RequestScopeStorageContractError(
            f"{field_name} must be an exact unique nonempty string tuple"
        )
    return cast("tuple[str, ...]", value)


@dataclass(frozen=True, slots=True)
class RequestScopeParameterPolicyV1:
    """One exact input alias and the logical type it produces in storage."""

    parameter_name: str
    logical_type: RequestScopeLogicalType

    def __post_init__(self) -> None:
        if type(self.parameter_name) is not str or not self.parameter_name:
            raise RequestScopeStorageContractError("scope parameter name is invalid")
        if self.logical_type not in {"int64", "large_string"}:
            raise RequestScopeStorageContractError("scope parameter logical type is unsupported")

    def to_dict(self) -> dict[str, str]:
        return {
            "parameter_name": self.parameter_name,
            "logical_type": self.logical_type,
        }


@dataclass(frozen=True, slots=True)
class RequestScopeColumnPolicyV1:
    """Code-owned output order and alias precedence for one scope dimension."""

    storage_column: str
    parameter_policies: tuple[RequestScopeParameterPolicyV1, ...]

    def __post_init__(self) -> None:
        if type(self.storage_column) is not str or not self.storage_column:
            raise RequestScopeStorageContractError("scope storage column is invalid")
        if (
            type(self.parameter_policies) is not tuple
            or not self.parameter_policies
            or any(
                type(item) is not RequestScopeParameterPolicyV1 for item in self.parameter_policies
            )
        ):
            raise RequestScopeStorageContractError("scope parameter policies are invalid")
        names = tuple(item.parameter_name for item in self.parameter_policies)
        if len(names) != len(set(names)):
            raise RequestScopeStorageContractError("scope parameter aliases overlap")

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(item.parameter_name for item in self.parameter_policies)

    def to_dict(self) -> dict[str, object]:
        return {
            "storage_column": self.storage_column,
            "parameter_policies": [item.to_dict() for item in self.parameter_policies],
        }


# This is deliberately independent of the private extractor constants.  The
# compiler verifies parity with the production injection function before using
# this policy, so mutating either side fails rather than silently redefining it.
REQUEST_SCOPE_COLUMN_POLICIES: Final = (
    RequestScopeColumnPolicyV1(
        storage_column="season_year",
        parameter_policies=(
            RequestScopeParameterPolicyV1("season", "large_string"),
            RequestScopeParameterPolicyV1("season_nullable", "large_string"),
            RequestScopeParameterPolicyV1("season_year", "int64"),
        ),
    ),
    RequestScopeColumnPolicyV1(
        storage_column="season_type",
        parameter_policies=(
            RequestScopeParameterPolicyV1("season_type_all_star", "large_string"),
            RequestScopeParameterPolicyV1("season_type_playoffs", "large_string"),
            RequestScopeParameterPolicyV1("season_type", "large_string"),
            RequestScopeParameterPolicyV1("season_type_nullable", "large_string"),
            RequestScopeParameterPolicyV1(
                "season_type_all_star_nullable",
                "large_string",
            ),
        ),
    ),
    RequestScopeColumnPolicyV1(
        storage_column="league_id",
        parameter_policies=(
            RequestScopeParameterPolicyV1("league_id", "large_string"),
            RequestScopeParameterPolicyV1("league_id_nullable", "large_string"),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class RequestScopeStorageFieldV1:
    """One route-local request dimension that may be appended to its frame."""

    route_id: str
    field_ordinal: int
    storage_column: str
    source_parameter_names: tuple[str, ...]
    required_parameter_names: tuple[str, ...]
    optional_parameter_names: tuple[str, ...]
    logical_type: RequestScopeLogicalType
    field_sha256: str

    schema_version: ClassVar[int] = REQUEST_SCOPE_STORAGE_SCHEMA_VERSION
    kind: ClassVar[str] = "request_scope_storage_field_v1"

    def __post_init__(self) -> None:
        if type(self.route_id) is not str or not self.route_id:
            raise RequestScopeStorageContractError("scope field route identity is invalid")
        if type(self.field_ordinal) is not int or self.field_ordinal < 0:
            raise RequestScopeStorageContractError("scope field ordinal is invalid")
        if type(self.storage_column) is not str or not self.storage_column:
            raise RequestScopeStorageContractError("scope field storage column is invalid")
        sources = _exact_text_tuple(
            self.source_parameter_names,
            field_name="source_parameter_names",
        )
        required = (
            _exact_text_tuple(
                self.required_parameter_names,
                field_name="required_parameter_names",
            )
            if self.required_parameter_names
            else ()
        )
        optional = (
            _exact_text_tuple(
                self.optional_parameter_names,
                field_name="optional_parameter_names",
            )
            if self.optional_parameter_names
            else ()
        )
        if set(required) & set(optional) or set(required) | set(optional) != set(sources):
            raise RequestScopeStorageContractError(
                "scope field required/optional aliases do not partition its sources"
            )
        if self.logical_type not in {"int64", "large_string"}:
            raise RequestScopeStorageContractError("scope field logical type is unsupported")
        if (
            type(self.field_sha256) is not str
            or len(self.field_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.field_sha256)
            or self.field_sha256 != _canonical_sha256(self.identity_payload())
        ):
            raise RequestScopeStorageContractError("scope field digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "route_id": self.route_id,
            "field_ordinal": self.field_ordinal,
            "storage_column": self.storage_column,
            "source_parameter_names": list(self.source_parameter_names),
            "required_parameter_names": list(self.required_parameter_names),
            "optional_parameter_names": list(self.optional_parameter_names),
            "logical_type": self.logical_type,
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_payload() | {"field_sha256": self.field_sha256}


def _field(
    *,
    route_id: str,
    field_ordinal: int,
    storage_column: str,
    source_parameter_names: tuple[str, ...],
    required_parameter_names: tuple[str, ...],
    optional_parameter_names: tuple[str, ...],
    logical_type: RequestScopeLogicalType,
) -> RequestScopeStorageFieldV1:
    values: dict[str, object] = {
        "schema_version": REQUEST_SCOPE_STORAGE_SCHEMA_VERSION,
        "kind": RequestScopeStorageFieldV1.kind,
        "route_id": route_id,
        "field_ordinal": field_ordinal,
        "storage_column": storage_column,
        "source_parameter_names": list(source_parameter_names),
        "required_parameter_names": list(required_parameter_names),
        "optional_parameter_names": list(optional_parameter_names),
        "logical_type": logical_type,
    }
    return RequestScopeStorageFieldV1(
        route_id=route_id,
        field_ordinal=field_ordinal,
        storage_column=storage_column,
        source_parameter_names=source_parameter_names,
        required_parameter_names=required_parameter_names,
        optional_parameter_names=optional_parameter_names,
        logical_type=logical_type,
        field_sha256=_canonical_sha256(values),
    )


def derive_request_scope_storage_fields(
    *,
    route_id: str,
    source_family: str,
    provider_required_parameters: tuple[str, ...],
    provider_optional_parameters: tuple[str, ...],
    canonical_columns: tuple[str, ...],
    declared_storage_columns: tuple[str, ...],
) -> tuple[RequestScopeStorageFieldV1, ...]:
    """Derive every possible appended field from exact route authorities."""

    if type(route_id) is not str or not route_id:
        raise RequestScopeStorageContractError("scope route identity is invalid")
    required = (
        _exact_text_tuple(
            provider_required_parameters,
            field_name="provider_required_parameters",
        )
        if provider_required_parameters
        else ()
    )
    optional = (
        _exact_text_tuple(
            provider_optional_parameters,
            field_name="provider_optional_parameters",
        )
        if provider_optional_parameters
        else ()
    )
    canonical = (
        _exact_text_tuple(
            canonical_columns,
            field_name="canonical_columns",
        )
        if canonical_columns
        else ()
    )
    storage = (
        _exact_text_tuple(
            declared_storage_columns,
            field_name="declared_storage_columns",
        )
        if declared_storage_columns
        else ()
    )
    if set(required) & set(optional):
        raise RequestScopeStorageContractError(
            "scope route required and optional parameter authorities overlap"
        )
    if source_family != "stats":
        return ()

    accepted = set(required) | set(optional)
    fields: list[RequestScopeStorageFieldV1] = []
    for policy in REQUEST_SCOPE_COLUMN_POLICIES:
        # The production injection runs after provider-field canonicalization
        # and never overwrites an existing provider/storage representation.
        if policy.storage_column in canonical or policy.storage_column in storage:
            continue
        aliases = tuple(name for name in policy.parameter_names if name in accepted)
        if not aliases:
            continue
        logical_types = {
            item.logical_type
            for item in policy.parameter_policies
            if item.parameter_name in aliases
        }
        if len(logical_types) != 1:
            raise RequestScopeStorageContractError(
                "scope aliases have ambiguous storage logical types"
            )
        fields.append(
            _field(
                route_id=route_id,
                field_ordinal=len(fields),
                storage_column=policy.storage_column,
                source_parameter_names=aliases,
                required_parameter_names=tuple(name for name in aliases if name in required),
                optional_parameter_names=tuple(name for name in aliases if name in optional),
                logical_type=next(iter(logical_types)),
            )
        )
    return tuple(fields)


def request_scope_arrow_type(logical_type: RequestScopeLogicalType) -> pa.DataType:
    """Return the exact Arrow type declared by the independent scope policy."""

    if logical_type == "large_string":
        return pa.large_string()
    if logical_type == "int64":
        return pa.int64()
    raise RequestScopeStorageContractError("scope Arrow logical type is unsupported")


def selected_request_scope_storage_fields(
    fields: tuple[RequestScopeStorageFieldV1, ...],
    request_parameters: object,
) -> tuple[RequestScopeStorageFieldV1, ...]:
    """Select the exact present field subset using production alias precedence."""

    if type(fields) is not tuple or any(
        type(item) is not RequestScopeStorageFieldV1 for item in fields
    ):
        raise RequestScopeStorageContractError("scope field inventory is invalid")
    if type(request_parameters) is not dict or any(
        type(name) is not str for name in request_parameters
    ):
        raise RequestScopeStorageContractError("scope request parameters are invalid")
    selected: list[RequestScopeStorageFieldV1] = []
    for field in fields:
        value: object | None = None
        selected_name: str | None = None
        for name in field.source_parameter_names:
            candidate = request_parameters.get(name)
            if candidate is not None and candidate != "":
                value = candidate
                selected_name = name
                break
        if selected_name is None:
            if field.required_parameter_names:
                raise RequestScopeStorageContractError(
                    "required request-scope storage value is absent"
                )
            continue
        if field.logical_type == "large_string":
            if type(value) is not str:
                raise RequestScopeStorageContractError(
                    "request-scope text value differs from its exact logical type"
                )
        elif type(value) is not int:
            raise RequestScopeStorageContractError(
                "request-scope integer value differs from its exact logical type"
            )
        selected.append(field)
    return tuple(selected)


def request_scope_storage_inventory_sha256(
    route_fields: tuple[tuple[str, tuple[RequestScopeStorageFieldV1, ...]], ...],
) -> str:
    """Hash an exact route-ordered inventory without trusting caller dictionaries."""

    if type(route_fields) is not tuple:
        raise RequestScopeStorageContractError("scope route inventory is mutable")
    route_ids: list[str] = []
    payload: list[dict[str, object]] = []
    for route_id, fields in route_fields:
        if type(route_id) is not str or not route_id or type(fields) is not tuple:
            raise RequestScopeStorageContractError("scope route inventory is invalid")
        if any(type(item) is not RequestScopeStorageFieldV1 for item in fields):
            raise RequestScopeStorageContractError("scope route fields have foreign types")
        if tuple(item.field_ordinal for item in fields) != tuple(range(len(fields))):
            raise RequestScopeStorageContractError("scope route fields are reordered")
        route_ids.append(route_id)
        payload.append(
            {
                "route_id": route_id,
                "fields": [item.to_dict() for item in fields],
            }
        )
    if len(route_ids) != len(set(route_ids)):
        raise RequestScopeStorageContractError("scope route inventory overlaps")
    return _canonical_sha256(
        {
            "schema_version": REQUEST_SCOPE_STORAGE_SCHEMA_VERSION,
            "kind": "request_scope_storage_inventory_v1",
            "routes": payload,
        }
    )


def validate_production_request_scope_injection_policy() -> None:
    """Prove the private production injection keys/order still match this authority."""

    from nbadb.extract import base

    expected_columns = tuple(item.storage_column for item in REQUEST_SCOPE_COLUMN_POLICIES)
    expected_aliases = {
        item.storage_column: item.parameter_names for item in REQUEST_SCOPE_COLUMN_POLICIES
    }
    actual_aliases = {
        "season_year": base._SEASON_YEAR_KEYS,
        "season_type": base._SEASON_TYPE_KEYS,
        "league_id": base._LEAGUE_ID_KEYS,
    }
    if tuple(actual_aliases) != expected_columns or actual_aliases != expected_aliases:
        raise RequestScopeStorageContractError(
            "production request-scope injection keys/order differ from storage authority"
        )


__all__ = [
    "EXPECTED_REQUEST_SCOPE_STORAGE_COLUMN_COUNTS",
    "EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT",
    "EXPECTED_REQUEST_SCOPE_STORAGE_ROUTE_COUNT",
    "REQUEST_SCOPE_COLUMN_POLICIES",
    "REQUEST_SCOPE_STORAGE_SCHEMA_VERSION",
    "RequestScopeColumnPolicyV1",
    "RequestScopeLogicalType",
    "RequestScopeParameterPolicyV1",
    "RequestScopeStorageContractError",
    "RequestScopeStorageFieldV1",
    "derive_request_scope_storage_fields",
    "request_scope_arrow_type",
    "request_scope_storage_inventory_sha256",
    "selected_request_scope_storage_fields",
    "validate_production_request_scope_injection_policy",
]
