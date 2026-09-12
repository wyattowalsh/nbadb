"""Generated runtime contract authority for the exact pinned nba_api release."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urljoin

from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library import parameters as provider_parameters
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.core.nba_api_contract import (
    NbaApiEndpointContract,
    _discover_live_runtime_endpoint_classes,
    _live_runtime_metadata_from_class,
    _parse_live_endpoint_metadata,
    contract_from_json,
    contract_to_json,
    discover_runtime_endpoint_contracts,
)
from nbadb.core.nba_api_provenance import (
    NBA_API_INVENTORY_FILE_COUNT,
    NBA_API_LICENSE_IDENTIFIER,
    NBA_API_LICENSE_SHA256,
    NBA_API_LIVE_COLUMN_CONTRACT_COUNT,
    NBA_API_LIVE_CONTRACT_SHA256,
    NBA_API_LIVE_ENDPOINT_CONTRACT_COUNT,
    NBA_API_LIVE_PARSED_COLUMN_CONTRACT_COUNT,
    NBA_API_LIVE_RESULT_SET_CONTRACT_COUNT,
    NBA_API_RUNTIME_CONTRACT_COUNT,
    NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256,
    NBA_API_RUNTIME_CONTRACT_SHA256,
    NBA_API_STATIC_CONTRACT_SHA256,
    NBA_API_STATIC_DATASET_CONTRACT_COUNT,
    NBA_API_STATIC_MODELED_FIELD_CONTRACT_COUNT,
    NBA_API_TREE_INVENTORY_SHA256,
    NBA_API_UPSTREAM_COMMIT,
    NBA_API_UPSTREAM_TAG,
    NBA_API_UPSTREAM_TREE,
    NBA_API_VERSION,
    verify_nba_api_provider,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

RUNTIME_CONTRACT_SCHEMA_VERSION = 4
RUNTIME_CONTRACT_RESOURCE = "nba_api_runtime_contract_v1_11_4.json"

_STATIC_DATASETS = (
    ("static_players", "players", "players.py", "_get_player_dict", "get_players"),
    ("static_teams", "teams", "teams.py", "_get_team_dict", "get_teams"),
    (
        "static_wnba_players",
        "wnba_players",
        "players.py",
        "_get_player_dict",
        "get_wnba_players",
    ),
    (
        "static_wnba_teams",
        "wnba_teams",
        "teams.py",
        "_get_team_dict",
        "get_wnba_teams",
    ),
)
_IMPLEMENTED_STATIC_OMISSIONS = {
    "static_teams": frozenset({"championship_year"}),
    "static_wnba_teams": frozenset({"championship_year"}),
}
_LIVE_AUXILIARY_PARAMETERS = frozenset({"proxy", "headers", "timeout", "get_request"})
_PATH_PARAMETER_RE = re.compile(r"\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")
_UPDATE_MARKER_RE = re.compile(r"^#\s*Data last updated:\s*(?P<value>.+?)\s*$", re.MULTILINE)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_JSON_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})

_LIVE_ENDPOINT_FIELDS = frozenset(
    {
        "base_url",
        "base_url_provenance",
        "contract_sha256",
        "disposition_reason",
        "docs_source_path",
        "docs_source_sha256",
        "documented_url",
        "documented_url_drift",
        "endpoint_id",
        "endpoint_slug",
        "endpoint_url_template",
        "envelope_root_order",
        "evidence",
        "full_url_template",
        "gate_effects",
        "model_disposition",
        "ordered_header_names",
        "ordered_headers_provenance",
        "ordered_headers_sha256",
        "owner",
        "parameters",
        "request_method",
        "request_method_provenance",
        "result_sets",
        "revalidation_path",
        "runtime_module",
        "skipped_shapes",
        "source_family",
        "source_path",
        "source_sha256",
    }
)


def stats_endpoint_url_template(endpoint_slug: str) -> str:
    """Return the exact installed-provider URL for one stats endpoint slug.

    Provider transport internals remain behind this runtime-contract boundary;
    request planners consume only the resulting nbadb-owned string authority.
    """

    if not endpoint_slug or endpoint_slug.strip() != endpoint_slug:
        raise ValueError("stats endpoint slug must be a nonempty canonical string")
    return str(NBAStatsHTTP.base_url).format(endpoint=endpoint_slug)


def stats_parameter_finite_values(parameter_name: str) -> tuple[object, ...]:
    """Project scalar constants from one exact-pin provider parameter class.

    The returned values are plain Python scalars, never upstream classes or
    response objects.  Canonical ordering and domain validation remain owned by
    the request-surface contract.
    """

    if not parameter_name or parameter_name.strip() != parameter_name:
        raise ValueError("stats parameter name must be a nonempty canonical string")
    class_name = "".join(part[:1].upper() + part[1:] for part in parameter_name.split("_") if part)
    parameter_class = getattr(provider_parameters, class_name, None)
    if not inspect.isclass(parameter_class):
        return ()
    values: list[object] = []
    for attribute in dir(parameter_class):
        if attribute.startswith("_") or attribute in {"default", "current_datetime"}:
            continue
        try:
            value = getattr(parameter_class, attribute)
        except Exception:
            continue
        if value is None or type(value) in {str, bool, int, float}:
            values.append(value)
    return tuple(values)


_LIVE_PARAMETER_FIELDS = frozenset(
    {
        "confidence",
        "default",
        "has_default",
        "location",
        "name",
        "nullable",
        "ordinal",
        "pattern",
        "provenance_source",
        "query_name",
        "required",
    }
)
_LIVE_RESULT_SET_FIELDS = frozenset(
    {
        "container_kind",
        "fields",
        "fields_sha256",
        "json_path",
        "name",
        "ordinal",
        "parent_field_name",
        "parent_result_set_name",
        "traversal_path",
    }
)
_LIVE_FIELD_FIELDS = frozenset(
    {
        "confidence",
        "documented_type",
        "drift_status",
        "json_path",
        "key_presence",
        "name",
        "nested_result_set_name",
        "nullable",
        "ordinal",
        "provenance_source",
        "runtime_sample_type",
        "sample_type",
        "source_field",
    }
)
_STATIC_DATASET_FIELDS = frozenset(
    {
        "contract_sha256",
        "data_source_path",
        "data_source_sha256",
        "dataset_id",
        "declared_update_marker",
        "disposition_reason",
        "evidence",
        "extraction_coverage_effect",
        "gate_effects",
        "getter_name",
        "implementation_status",
        "model_disposition",
        "owner",
        "projected_fields",
        "projected_records_sha256",
        "provider_module",
        "provider_source_path",
        "provider_source_sha256",
        "raw_fields",
        "raw_records_sha256",
        "revalidation_path",
        "row_count",
        "source_family",
        "source_rows_sha256",
        "source_symbol",
        "unique_id_count",
    }
)
_STATIC_FIELD_FIELDS = frozenset(
    {
        "disposition_reason",
        "extraction_coverage_effect",
        "model_disposition",
        "name",
        "ordinal",
        "owner",
        "provider_projection_disposition",
        "revalidation_path",
        "sample_type",
    }
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _exact_object(value: object, fields: frozenset[str], kind: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{kind} fields do not match the exact schema")
    return cast("dict[str, Any]", value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _sha256_string(value: object, field: str) -> str:
    text = _string(value, field)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{field} must be a canonical SHA-256")
    return text


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer greater than or equal to {minimum}")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _string_tuple(
    value: object,
    field: str,
    *,
    allow_duplicates: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an ordered string array")
    result = tuple(_string(item, field) for item in value)
    if not allow_duplicates and len(set(result)) != len(result):
        raise ValueError(f"{field} must not contain duplicates")
    return result


def _type_union(value: object, field: str, *, optional: bool) -> tuple[str, ...] | None:
    if value is None:
        if optional:
            return None
        raise ValueError(f"{field} must declare a JSON value type")
    raw = value if isinstance(value, list) else [value]
    if not raw:
        raise ValueError(f"{field} must not be empty")
    result = tuple(_string(item, field) for item in raw)
    if len(set(result)) != len(result) or any(item not in _JSON_TYPES for item in result):
        raise ValueError(f"{field} contains an invalid JSON value type")
    return result


def _type_union_json(value: tuple[str, ...] | None) -> str | list[str] | None:
    if value is None:
        return None
    return value[0] if len(value) == 1 else list(value)


@dataclass(frozen=True, slots=True)
class GateEffects:
    model_green: str
    data_green: str
    publication: str

    @classmethod
    def from_json(cls, raw: object) -> GateEffects:
        value = _exact_object(
            raw, frozenset({"model_green", "data_green", "publication"}), "gate effects"
        )
        return cls(
            model_green=_string(value["model_green"], "model_green"),
            data_green=_string(value["data_green"], "data_green"),
            publication=_string(value["publication"], "publication"),
        )

    def to_json(self) -> dict[str, str]:
        return {
            "model_green": self.model_green,
            "data_green": self.data_green,
            "publication": self.publication,
        }


@dataclass(frozen=True, slots=True)
class LiveParameterContract:
    name: str
    ordinal: int
    query_name: str
    location: str
    required: bool
    has_default: bool
    default: str | int | float | bool | None
    nullable: bool
    pattern: str | None
    provenance_source: str
    confidence: str

    @classmethod
    def from_json(cls, raw: object) -> LiveParameterContract:
        value = _exact_object(raw, _LIVE_PARAMETER_FIELDS, "live parameter contract")
        default = value["default"]
        if default is not None and not isinstance(default, str | int | float | bool):
            raise ValueError("live parameter default is not a JSON scalar")
        contract = cls(
            name=_string(value["name"], "live parameter name"),
            ordinal=_integer(value["ordinal"], "live parameter ordinal"),
            query_name=_string(value["query_name"], "live parameter query name"),
            location=_string(value["location"], "live parameter location"),
            required=_boolean(value["required"], "live parameter required"),
            has_default=_boolean(value["has_default"], "live parameter has_default"),
            default=cast("str | int | float | bool | None", default),
            nullable=_boolean(value["nullable"], "live parameter nullable"),
            pattern=_optional_string(value["pattern"], "live parameter pattern"),
            provenance_source=_string(
                value["provenance_source"], "live parameter provenance source"
            ),
            confidence=_string(value["confidence"], "live parameter confidence"),
        )
        if contract.location not in {"path", "query"}:
            raise ValueError("live parameter location is invalid")
        if contract.required == contract.has_default:
            raise ValueError("live parameter required/default contract is inconsistent")
        if not contract.has_default and contract.default is not None:
            raise ValueError("required live parameter cannot carry a default")
        if contract.nullable and not contract.has_default:
            raise ValueError("required live parameter cannot be nullable")
        return contract

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ordinal": self.ordinal,
            "query_name": self.query_name,
            "location": self.location,
            "required": self.required,
            "has_default": self.has_default,
            "default": self.default,
            "nullable": self.nullable,
            "pattern": self.pattern,
            "provenance_source": self.provenance_source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class LiveFieldContract:
    name: str
    ordinal: int
    json_path: str
    sample_types: tuple[str, ...]
    runtime_sample_type: str | None
    documented_types: tuple[str, ...] | None
    source_field: bool
    key_presence: str
    nested_result_set_name: str | None
    nullable: bool
    provenance_source: str
    confidence: str
    drift_status: str

    @classmethod
    def from_json(cls, raw: object) -> LiveFieldContract:
        value = _exact_object(raw, _LIVE_FIELD_FIELDS, "live field contract")
        runtime_type = _optional_string(
            value["runtime_sample_type"], "live field runtime sample type"
        )
        if runtime_type is not None and runtime_type not in _JSON_TYPES:
            raise ValueError("live field runtime sample type is invalid")
        return cls(
            name=_string(value["name"], "live field name"),
            ordinal=_integer(value["ordinal"], "live field ordinal"),
            json_path=_string(value["json_path"], "live field JSON path"),
            sample_types=cast(
                "tuple[str, ...]",
                _type_union(value["sample_type"], "live field sample type", optional=False),
            ),
            runtime_sample_type=runtime_type,
            documented_types=_type_union(
                value["documented_type"], "live field documented type", optional=True
            ),
            source_field=_boolean(value["source_field"], "live field source_field"),
            key_presence=_string(value["key_presence"], "live field key presence"),
            nested_result_set_name=_optional_string(
                value["nested_result_set_name"], "live field nested result set"
            ),
            nullable=_boolean(value["nullable"], "live field nullable"),
            provenance_source=_string(value["provenance_source"], "live field provenance source"),
            confidence=_string(value["confidence"], "live field confidence"),
            drift_status=_string(value["drift_status"], "live field drift status"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ordinal": self.ordinal,
            "json_path": self.json_path,
            "sample_type": _type_union_json(self.sample_types),
            "runtime_sample_type": self.runtime_sample_type,
            "documented_type": _type_union_json(self.documented_types),
            "source_field": self.source_field,
            "key_presence": self.key_presence,
            "nested_result_set_name": self.nested_result_set_name,
            "nullable": self.nullable,
            "provenance_source": self.provenance_source,
            "confidence": self.confidence,
            "drift_status": self.drift_status,
        }


@dataclass(frozen=True, slots=True)
class LiveResultSetContract:
    name: str
    ordinal: int
    json_path: str
    traversal_path: tuple[str, ...]
    container_kind: str
    parent_result_set_name: str | None
    parent_field_name: str | None
    fields: tuple[LiveFieldContract, ...]
    fields_sha256: str

    @classmethod
    def from_json(cls, raw: object) -> LiveResultSetContract:
        value = _exact_object(raw, _LIVE_RESULT_SET_FIELDS, "live result-set contract")
        raw_fields = value["fields"]
        if not isinstance(raw_fields, list):
            raise ValueError("live result-set fields must be an array")
        fields = tuple(LiveFieldContract.from_json(field) for field in raw_fields)
        if [field.ordinal for field in fields] != list(range(len(fields))):
            raise ValueError("live result-set field ordinals are not contiguous")
        if len({field.name for field in fields}) != len(fields):
            raise ValueError("live result-set field names are not unique")
        digest = _sha256_string(value["fields_sha256"], "live fields digest")
        if digest != _sha256([field.to_json() for field in fields]):
            raise ValueError("live result-set fields digest is invalid")
        return cls(
            name=_string(value["name"], "live result-set name"),
            ordinal=_integer(value["ordinal"], "live result-set ordinal"),
            json_path=_string(value["json_path"], "live result-set JSON path"),
            traversal_path=_string_tuple(
                value["traversal_path"],
                "live result-set traversal path",
                allow_duplicates=True,
            ),
            container_kind=_string(value["container_kind"], "live result-set container kind"),
            parent_result_set_name=_optional_string(
                value["parent_result_set_name"], "live parent result-set name"
            ),
            parent_field_name=_optional_string(
                value["parent_field_name"], "live parent field name"
            ),
            fields=fields,
            fields_sha256=digest,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ordinal": self.ordinal,
            "json_path": self.json_path,
            "traversal_path": list(self.traversal_path),
            "container_kind": self.container_kind,
            "parent_result_set_name": self.parent_result_set_name,
            "parent_field_name": self.parent_field_name,
            "fields": [field.to_json() for field in self.fields],
            "fields_sha256": self.fields_sha256,
        }


@dataclass(frozen=True, slots=True)
class LiveEndpointContract:
    endpoint_id: str
    runtime_module: str
    source_family: str
    endpoint_slug: str
    request_method: str
    request_method_provenance: str
    base_url: str
    base_url_provenance: str
    endpoint_url_template: str
    full_url_template: str
    documented_url: str
    documented_url_drift: str
    parameters: tuple[LiveParameterContract, ...]
    ordered_header_names: tuple[str, ...]
    ordered_headers_sha256: str
    ordered_headers_provenance: str
    envelope_root_order: tuple[str, ...]
    result_sets: tuple[LiveResultSetContract, ...]
    skipped_shapes: tuple[str, ...]
    source_path: str
    source_sha256: str
    docs_source_path: str
    docs_source_sha256: str
    model_disposition: str
    disposition_reason: str
    owner: str
    revalidation_path: str
    evidence: tuple[tuple[str, str], ...]
    gate_effects: GateEffects
    contract_sha256: str

    @classmethod
    def from_json(cls, raw: object) -> LiveEndpointContract:
        value = _exact_object(raw, _LIVE_ENDPOINT_FIELDS, "live endpoint contract")
        raw_parameters = value["parameters"]
        raw_result_sets = value["result_sets"]
        if not isinstance(raw_parameters, list) or not isinstance(raw_result_sets, list):
            raise ValueError("live endpoint contract inventories must be arrays")
        parameters = tuple(LiveParameterContract.from_json(item) for item in raw_parameters)
        result_sets = tuple(LiveResultSetContract.from_json(item) for item in raw_result_sets)
        if [item.ordinal for item in parameters] != list(range(len(parameters))):
            raise ValueError("live parameter ordinals are not contiguous")
        if [item.ordinal for item in result_sets] != list(range(len(result_sets))):
            raise ValueError("live result-set ordinals are not contiguous")
        if len({item.name for item in parameters}) != len(parameters):
            raise ValueError("live parameter names are not unique")
        if len({item.name for item in result_sets}) != len(result_sets):
            raise ValueError("live result-set names are not unique")
        raw_evidence = _exact_object(
            value["evidence"],
            frozenset({"docs_source_sha256", "runtime_source_sha256"}),
            "live endpoint evidence",
        )
        evidence = tuple(
            (key, _sha256_string(raw_evidence[key], f"live evidence {key}"))
            for key in sorted(raw_evidence)
        )
        contract = cls(
            endpoint_id=_string(value["endpoint_id"], "live endpoint id"),
            runtime_module=_string(value["runtime_module"], "live runtime module"),
            source_family=_string(value["source_family"], "live source family"),
            endpoint_slug=_string(value["endpoint_slug"], "live endpoint slug"),
            request_method=_string(value["request_method"], "live request method"),
            request_method_provenance=_string(
                value["request_method_provenance"], "live request method provenance"
            ),
            base_url=_string(value["base_url"], "live base URL"),
            base_url_provenance=_string(value["base_url_provenance"], "live base URL provenance"),
            endpoint_url_template=_string(
                value["endpoint_url_template"], "live endpoint URL template"
            ),
            full_url_template=_string(value["full_url_template"], "live full URL template"),
            documented_url=_string(value["documented_url"], "live documented URL"),
            documented_url_drift=_string(
                value["documented_url_drift"], "live documented URL drift"
            ),
            parameters=parameters,
            ordered_header_names=_string_tuple(
                value["ordered_header_names"], "live ordered header names"
            ),
            ordered_headers_sha256=_sha256_string(
                value["ordered_headers_sha256"], "live ordered headers digest"
            ),
            ordered_headers_provenance=_string(
                value["ordered_headers_provenance"], "live ordered headers provenance"
            ),
            envelope_root_order=_string_tuple(
                value["envelope_root_order"], "live envelope root order"
            ),
            result_sets=result_sets,
            skipped_shapes=_string_tuple(value["skipped_shapes"], "live skipped shapes"),
            source_path=_string(value["source_path"], "live source path"),
            source_sha256=_sha256_string(value["source_sha256"], "live source digest"),
            docs_source_path=_string(value["docs_source_path"], "live docs source path"),
            docs_source_sha256=_sha256_string(
                value["docs_source_sha256"], "live docs source digest"
            ),
            model_disposition=_string(value["model_disposition"], "live model disposition"),
            disposition_reason=_string(value["disposition_reason"], "live disposition reason"),
            owner=_string(value["owner"], "live contract owner"),
            revalidation_path=_string(value["revalidation_path"], "live revalidation path"),
            evidence=evidence,
            gate_effects=GateEffects.from_json(value["gate_effects"]),
            contract_sha256=_sha256_string(
                value["contract_sha256"], "live endpoint contract digest"
            ),
        )
        contract._validate_semantics()
        body = contract.to_json()
        body.pop("contract_sha256")
        if contract.contract_sha256 != _sha256(body):
            raise ValueError("live endpoint contract digest is invalid")
        return contract

    def _validate_semantics(self) -> None:
        if self.source_family != "live" or self.request_method != "GET":
            raise ValueError("live endpoint request identity is invalid")
        placeholders = set(_PATH_PARAMETER_RE.findall(self.endpoint_url_template))
        path_parameters = {item.name for item in self.parameters if item.location == "path"}
        if placeholders != path_parameters:
            raise ValueError("live endpoint path parameters differ from its URL template")
        try:
            expected_full_url = self.base_url.format(endpoint=self.endpoint_url_template)
        except (KeyError, ValueError) as exc:
            raise ValueError("live endpoint base URL template is invalid") from exc
        if self.full_url_template != expected_full_url:
            raise ValueError("live endpoint full URL differs from its fixed base URL")
        by_name = {item.name: item for item in self.result_sets}
        by_path = {
            tuple(item.json_path.removeprefix("$.").split(".")): item for item in self.result_sets
        }
        if tuple(item.name for item in self.result_sets if item.parent_result_set_name is None) != (
            self.envelope_root_order
        ):
            raise ValueError("live envelope root order differs from root result sets")
        for result_set in self.result_sets:
            own_path = tuple(result_set.json_path.removeprefix("$.").split("."))
            if not result_set.json_path.startswith("$.") or not all(own_path):
                raise ValueError("live result-set JSON path is invalid")
            traversal: list[str] = []
            for index, segment in enumerate(own_path):
                traversal.append(segment)
                parent = by_path.get(own_path[: index + 1])
                if (
                    parent is not None
                    and parent.container_kind == "nba_api_live_json_array"
                    and index + 1 < len(own_path)
                ):
                    traversal.append("*")
            if tuple(traversal) != result_set.traversal_path:
                raise ValueError("live result-set traversal path is not derivable")
            parent_candidates = [
                candidate
                for candidate in self.result_sets
                if candidate.name != result_set.name
                and own_path[: len(candidate.json_path.removeprefix("$.").split("."))]
                == tuple(candidate.json_path.removeprefix("$.").split("."))
                and len(candidate.json_path) < len(result_set.json_path)
            ]
            parent = max(parent_candidates, key=lambda item: len(item.json_path), default=None)
            if (parent.name if parent is not None else None) != result_set.parent_result_set_name:
                raise ValueError("live result-set parent identity is invalid")
            if result_set.parent_result_set_name is None:
                if result_set.parent_field_name is not None:
                    raise ValueError("root live result set cannot have a parent field")
            else:
                parent_contract = by_name[result_set.parent_result_set_name]
                parent_field = next(
                    (
                        field
                        for field in parent_contract.fields
                        if field.name == result_set.parent_field_name
                    ),
                    None,
                )
                if parent_field is None:
                    raise ValueError("live nested result set omitted its structural parent field")
                if parent_field.nested_result_set_name != result_set.name:
                    raise ValueError("live nested result-set reference is invalid")
            for field in result_set.fields:
                if field.json_path != f"{result_set.json_path}.{field.name}":
                    raise ValueError("live field JSON path is invalid")
                if field.nested_result_set_name is not None:
                    child = by_name.get(field.nested_result_set_name)
                    if (
                        child is None
                        or child.parent_result_set_name != result_set.name
                        or child.parent_field_name != field.name
                    ):
                        raise ValueError("live field nested result-set reference is invalid")

    def to_json(self) -> dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "runtime_module": self.runtime_module,
            "source_family": self.source_family,
            "endpoint_slug": self.endpoint_slug,
            "request_method": self.request_method,
            "request_method_provenance": self.request_method_provenance,
            "base_url": self.base_url,
            "base_url_provenance": self.base_url_provenance,
            "endpoint_url_template": self.endpoint_url_template,
            "full_url_template": self.full_url_template,
            "documented_url": self.documented_url,
            "documented_url_drift": self.documented_url_drift,
            "parameters": [item.to_json() for item in self.parameters],
            "ordered_header_names": list(self.ordered_header_names),
            "ordered_headers_sha256": self.ordered_headers_sha256,
            "ordered_headers_provenance": self.ordered_headers_provenance,
            "envelope_root_order": list(self.envelope_root_order),
            "result_sets": [item.to_json() for item in self.result_sets],
            "skipped_shapes": list(self.skipped_shapes),
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "docs_source_path": self.docs_source_path,
            "docs_source_sha256": self.docs_source_sha256,
            "model_disposition": self.model_disposition,
            "disposition_reason": self.disposition_reason,
            "owner": self.owner,
            "revalidation_path": self.revalidation_path,
            "evidence": dict(self.evidence),
            "gate_effects": self.gate_effects.to_json(),
            "contract_sha256": self.contract_sha256,
        }


@dataclass(frozen=True, slots=True)
class StaticFieldContract:
    name: str
    ordinal: int
    sample_type: str
    provider_projection_disposition: str
    model_disposition: str
    disposition_reason: str
    owner: str
    extraction_coverage_effect: str
    revalidation_path: str

    @classmethod
    def from_json(cls, raw: object) -> StaticFieldContract:
        value = _exact_object(raw, _STATIC_FIELD_FIELDS, "static field contract")
        return cls(
            name=_string(value["name"], "static field name"),
            ordinal=_integer(value["ordinal"], "static field ordinal"),
            sample_type=_string(value["sample_type"], "static field sample type"),
            provider_projection_disposition=_string(
                value["provider_projection_disposition"],
                "static field provider projection disposition",
            ),
            model_disposition=_string(value["model_disposition"], "static field model disposition"),
            disposition_reason=_string(
                value["disposition_reason"], "static field disposition reason"
            ),
            owner=_string(value["owner"], "static field owner"),
            extraction_coverage_effect=_string(
                value["extraction_coverage_effect"], "static field extraction coverage effect"
            ),
            revalidation_path=_string(value["revalidation_path"], "static field revalidation path"),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ordinal": self.ordinal,
            "sample_type": self.sample_type,
            "provider_projection_disposition": self.provider_projection_disposition,
            "model_disposition": self.model_disposition,
            "disposition_reason": self.disposition_reason,
            "owner": self.owner,
            "extraction_coverage_effect": self.extraction_coverage_effect,
            "revalidation_path": self.revalidation_path,
        }


@dataclass(frozen=True, slots=True)
class StaticDatasetContract:
    dataset_id: str
    source_family: str
    provider_module: str
    getter_name: str
    source_symbol: str
    provider_source_path: str
    provider_source_sha256: str
    data_source_path: str
    data_source_sha256: str
    declared_update_marker: str
    raw_fields: tuple[StaticFieldContract, ...]
    projected_fields: tuple[str, ...]
    row_count: int
    unique_id_count: int
    source_rows_sha256: str
    raw_records_sha256: str
    projected_records_sha256: str
    model_disposition: str
    implementation_status: str
    disposition_reason: str
    owner: str
    extraction_coverage_effect: str
    revalidation_path: str
    evidence: tuple[tuple[str, str], ...]
    gate_effects: GateEffects
    contract_sha256: str

    @classmethod
    def from_json(cls, raw: object) -> StaticDatasetContract:
        value = _exact_object(raw, _STATIC_DATASET_FIELDS, "static dataset contract")
        raw_fields = value["raw_fields"]
        if not isinstance(raw_fields, list):
            raise ValueError("static raw field inventory must be an array")
        fields = tuple(StaticFieldContract.from_json(item) for item in raw_fields)
        if [item.ordinal for item in fields] != list(range(len(fields))):
            raise ValueError("static field ordinals are not contiguous")
        if len({item.name for item in fields}) != len(fields):
            raise ValueError("static field names are not unique")
        raw_evidence = _exact_object(
            value["evidence"],
            frozenset(
                {
                    "data_source_sha256",
                    "getter_name",
                    "provider_source_sha256",
                    "scope_evidence_kind",
                    "source_symbol",
                }
            ),
            "static dataset evidence",
        )
        evidence = tuple(
            (
                key,
                (
                    _sha256_string(raw_evidence[key], f"static evidence {key}")
                    if key.endswith("sha256")
                    else _string(raw_evidence[key], f"static evidence {key}")
                ),
            )
            for key in sorted(raw_evidence)
        )
        contract = cls(
            dataset_id=_string(value["dataset_id"], "static dataset id"),
            source_family=_string(value["source_family"], "static source family"),
            provider_module=_string(value["provider_module"], "static provider module"),
            getter_name=_string(value["getter_name"], "static getter name"),
            source_symbol=_string(value["source_symbol"], "static source symbol"),
            provider_source_path=_string(
                value["provider_source_path"], "static provider source path"
            ),
            provider_source_sha256=_sha256_string(
                value["provider_source_sha256"], "static provider source digest"
            ),
            data_source_path=_string(value["data_source_path"], "static data source path"),
            data_source_sha256=_sha256_string(
                value["data_source_sha256"], "static data source digest"
            ),
            declared_update_marker=_string(value["declared_update_marker"], "static update marker"),
            raw_fields=fields,
            projected_fields=_string_tuple(value["projected_fields"], "static projected fields"),
            row_count=_integer(value["row_count"], "static row count", minimum=1),
            unique_id_count=_integer(value["unique_id_count"], "static unique id count", minimum=1),
            source_rows_sha256=_sha256_string(
                value["source_rows_sha256"], "static source rows digest"
            ),
            raw_records_sha256=_sha256_string(
                value["raw_records_sha256"], "static raw records digest"
            ),
            projected_records_sha256=_sha256_string(
                value["projected_records_sha256"], "static projected records digest"
            ),
            model_disposition=_string(value["model_disposition"], "static model disposition"),
            implementation_status=_string(
                value["implementation_status"], "static implementation status"
            ),
            disposition_reason=_string(value["disposition_reason"], "static disposition reason"),
            owner=_string(value["owner"], "static contract owner"),
            extraction_coverage_effect=_string(
                value["extraction_coverage_effect"], "static extraction coverage effect"
            ),
            revalidation_path=_string(value["revalidation_path"], "static revalidation path"),
            evidence=evidence,
            gate_effects=GateEffects.from_json(value["gate_effects"]),
            contract_sha256=_sha256_string(
                value["contract_sha256"], "static dataset contract digest"
            ),
        )
        contract._validate_semantics()
        body = contract.to_json()
        body.pop("contract_sha256")
        if contract.contract_sha256 != _sha256(body):
            raise ValueError("static dataset contract digest is invalid")
        return contract

    def _validate_semantics(self) -> None:
        if self.source_family != "static" or self.row_count != self.unique_id_count:
            raise ValueError("static dataset source/grain contract is invalid")
        raw_names = tuple(item.name for item in self.raw_fields)
        if any(name not in raw_names for name in self.projected_fields):
            raise ValueError("static provider projection is not a subset of raw fields")
        projected = set(self.projected_fields)
        for field in self.raw_fields:
            expected_projection = (
                "projected_by_provider"
                if field.name in projected
                else "omitted_by_provider_projection"
            )
            if field.provider_projection_disposition != expected_projection:
                raise ValueError("static field projection disposition is inconsistent")
        blocked = any(field.model_disposition == "contract_blocked" for field in self.raw_fields)
        if blocked != (self.implementation_status == "contract_blocked"):
            raise ValueError("static implementation status disagrees with field dispositions")

    def to_json(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "source_family": self.source_family,
            "provider_module": self.provider_module,
            "getter_name": self.getter_name,
            "source_symbol": self.source_symbol,
            "provider_source_path": self.provider_source_path,
            "provider_source_sha256": self.provider_source_sha256,
            "data_source_path": self.data_source_path,
            "data_source_sha256": self.data_source_sha256,
            "declared_update_marker": self.declared_update_marker,
            "raw_fields": [field.to_json() for field in self.raw_fields],
            "projected_fields": list(self.projected_fields),
            "row_count": self.row_count,
            "unique_id_count": self.unique_id_count,
            "source_rows_sha256": self.source_rows_sha256,
            "raw_records_sha256": self.raw_records_sha256,
            "projected_records_sha256": self.projected_records_sha256,
            "model_disposition": self.model_disposition,
            "implementation_status": self.implementation_status,
            "disposition_reason": self.disposition_reason,
            "owner": self.owner,
            "extraction_coverage_effect": self.extraction_coverage_effect,
            "revalidation_path": self.revalidation_path,
            "evidence": dict(self.evidence),
            "gate_effects": self.gate_effects.to_json(),
            "contract_sha256": self.contract_sha256,
        }


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider_payload() -> dict[str, Any]:
    return {
        "version": NBA_API_VERSION,
        "tag": NBA_API_UPSTREAM_TAG,
        "commit_sha": NBA_API_UPSTREAM_COMMIT,
        "tree_sha": NBA_API_UPSTREAM_TREE,
        "source_inventory_file_count": NBA_API_INVENTORY_FILE_COUNT,
        "source_inventory_sha256": NBA_API_TREE_INVENTORY_SHA256,
        "license_identifier": NBA_API_LICENSE_IDENTIFIER,
        "license_sha256": NBA_API_LICENSE_SHA256,
    }


def _exact_package_root(upstream_root: Path) -> Path:
    candidates = (upstream_root / "src" / "nba_api", upstream_root / "nba_api")
    package_root = next((candidate for candidate in candidates if candidate.is_dir()), None)
    if package_root is None:
        raise ValueError("exact nba_api checkout omitted its package root")
    return package_root


def _verify_generation_source(upstream_root: Path) -> Path:
    project_root = Path(__file__).resolve().parents[3]
    evidence = verify_nba_api_provider(upstream_root, project_root=project_root)
    if evidence["verified"] is not True:
        reasons = ",".join(str(reason) for reason in evidence["errors"])
        raise ValueError(f"exact nba_api generation source is invalid: {reasons}")
    return _exact_package_root(upstream_root)


def _live_docs_supplements(upstream_root: Path) -> dict[str, dict[str, Any]]:
    docs_dir = upstream_root / "docs" / "nba_api" / "live" / "endpoints"
    if not docs_dir.is_dir():
        raise ValueError("exact nba_api checkout omitted live endpoint docs")
    supplements: dict[str, dict[str, Any]] = {}
    for path in sorted(docs_dir.glob("*.md")):
        supplement = _parse_live_endpoint_metadata(
            upstream_root,
            path,
            path.read_text(encoding="utf-8"),
        )
        if supplement is None:
            raise ValueError(f"live endpoint docs could not be parsed: {path.name}")
        supplements[path.stem] = supplement
    return supplements


def _json_default(value: object) -> object:
    if value is inspect.Parameter.empty:
        return None
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ValueError("live endpoint default is not canonical JSON")


def _live_parameter_contracts(
    runtime_cls: type,
    metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    docs_parameters = {
        str(row.get("python_parameter_variable")): row
        for row in metadata.get("docs_supplement", {}).get("parameters", [])
        if isinstance(row, dict) and row.get("python_parameter_variable")
    }
    path_parameters = set(_PATH_PARAMETER_RE.findall(str(getattr(runtime_cls, "endpoint_url", ""))))
    contracts: list[dict[str, Any]] = []
    for parameter in inspect.signature(runtime_cls).parameters.values():
        if parameter.name in _LIVE_AUXILIARY_PARAMETERS:
            continue
        docs = docs_parameters.get(parameter.name, {})
        has_default = parameter.default is not inspect.Parameter.empty
        contracts.append(
            {
                "name": parameter.name,
                "ordinal": len(contracts),
                "query_name": docs.get("api_parameter_name") or parameter.name,
                "location": "path" if parameter.name in path_parameters else "query",
                "required": not has_default,
                "has_default": has_default,
                "default": _json_default(parameter.default),
                "nullable": has_default and parameter.default is None,
                "pattern": docs.get("pattern"),
                "provenance_source": (
                    "runtime_signature+live_docs" if docs else "runtime_signature"
                ),
                "confidence": "high",
            }
        )
    if path_parameters != {
        contract["name"] for contract in contracts if contract["location"] == "path"
    }:
        raise ValueError("live endpoint URL placeholders do not match domain parameters")
    return contracts


def _build_live_contracts(
    upstream_root: Path,
    package_root: Path,
) -> dict[str, dict[str, Any]]:
    supplements = _live_docs_supplements(upstream_root)
    runtime_classes = _discover_live_runtime_endpoint_classes()
    expected_names = {"BoxScore", "Odds", "PlayByPlay", "ScoreBoard"}
    if set(runtime_classes) != expected_names:
        raise ValueError("live endpoint class inventory differs from the exact pinned release")
    ordered_headers = [[key, value] for key, value in NBALiveHTTP.headers.items()]
    headers_sha256 = _sha256(ordered_headers)
    contracts: dict[str, dict[str, Any]] = {}
    for name, runtime_cls in sorted(runtime_classes.items()):
        slug = runtime_cls.__module__.rsplit(".", 1)[-1]
        supplement = supplements.get(slug)
        if supplement is None:
            raise ValueError(f"live endpoint docs omitted {slug}")
        metadata = _live_runtime_metadata_from_class(runtime_cls, supplement)
        source_relative = Path(*runtime_cls.__module__.split(".")).with_suffix(".py")
        source_path = package_root.parent / source_relative
        if not source_path.is_file():
            raise ValueError(f"live endpoint source omitted {source_relative.as_posix()}")
        data_sets = metadata["data_sets"]
        paths_by_name = {
            data_set["result_set_name"]: str(data_set["json_path"]).removeprefix("$.").split(".")
            for data_set in data_sets
        }
        kinds_by_name = {
            data_set["result_set_name"]: data_set["data_grain"] for data_set in data_sets
        }
        result_sets: list[dict[str, Any]] = []
        for index, data_set in enumerate(data_sets):
            fields = [
                {
                    "name": field["key"],
                    "ordinal": field["ordinal"],
                    "json_path": field["json_path"],
                    "sample_type": field["sample_type"],
                    "runtime_sample_type": field.get("runtime_sample_type"),
                    "documented_type": field.get("documented_type"),
                    "source_field": field.get("source_field", True),
                    "key_presence": field.get("key_presence"),
                    "nested_result_set_name": field.get("nested_result_set_name"),
                    "nullable": field["nullable"],
                    "provenance_source": field["source"],
                    "confidence": field["confidence"],
                    "drift_status": field["drift_status"],
                }
                for field in data_set["fields"]
            ]
            own_path = paths_by_name[data_set["result_set_name"]]
            parent_candidates = [
                (candidate_name, candidate_path)
                for candidate_name, candidate_path in paths_by_name.items()
                if len(candidate_path) < len(own_path)
                and own_path[: len(candidate_path)] == candidate_path
            ]
            parent_name, parent_path = max(
                parent_candidates,
                key=lambda item: len(item[1]),
                default=(None, []),
            )
            traversal_path: list[str] = []
            for segment_index, segment in enumerate(own_path):
                traversal_path.append(segment)
                prefix = own_path[: segment_index + 1]
                matching_name = next(
                    (
                        candidate_name
                        for candidate_name, candidate_path in paths_by_name.items()
                        if candidate_path == prefix
                    ),
                    None,
                )
                if (
                    matching_name is not None
                    and kinds_by_name[matching_name] == "nba_api_live_json_array"
                    and segment_index + 1 < len(own_path)
                ):
                    traversal_path.append("*")
            result_sets.append(
                {
                    "name": data_set["result_set_name"],
                    "ordinal": index,
                    "json_path": data_set["json_path"],
                    "traversal_path": traversal_path,
                    "parent_result_set_name": parent_name,
                    "parent_field_name": (
                        own_path[len(parent_path)] if parent_name is not None else None
                    ),
                    "container_kind": data_set["data_grain"],
                    "fields": fields,
                    "fields_sha256": _sha256(fields),
                }
            )
        endpoint_url_template = str(cast("Any", runtime_cls).endpoint_url)
        canonical_full_url = urljoin(
            "https://cdn.nba.com/static/json/liveData/",
            endpoint_url_template,
        )
        documented_url = supplement.get("endpoint_url")
        contract: dict[str, Any] = {
            "endpoint_id": name,
            "runtime_module": runtime_cls.__module__,
            "endpoint_slug": slug,
            "source_family": "live",
            "request_method": "GET",
            "request_method_provenance": "nba_api.library.http.NBAHTTP.send_api_request",
            "base_url": NBALiveHTTP.base_url,
            "base_url_provenance": "nba_api.live.nba.library.http.NBALiveHTTP",
            "endpoint_url_template": endpoint_url_template,
            "full_url_template": canonical_full_url,
            "documented_url": documented_url,
            "documented_url_drift": (
                "docs_matches_canonical"
                if documented_url == canonical_full_url
                else "docs_relative_runtime_canonicalized"
            ),
            "parameters": _live_parameter_contracts(runtime_cls, metadata),
            "ordered_header_names": list(NBALiveHTTP.headers),
            "ordered_headers_sha256": headers_sha256,
            "ordered_headers_provenance": "nba_api.live.nba.library.http.NBALiveHTTP.headers",
            "envelope_root_order": list(getattr(runtime_cls, "expected_data", {})),
            "result_sets": result_sets,
            "skipped_shapes": metadata["skipped_shapes"],
            "source_path": source_relative.as_posix(),
            "source_sha256": _file_sha256(source_path),
            "docs_source_path": supplement["source_path"],
            "docs_source_sha256": supplement["source_sha256"],
            "model_disposition": "defined_and_implemented",
            "disposition_reason": "owned live snapshot contract for the pinned provider",
            "evidence": {
                "runtime_source_sha256": _file_sha256(source_path),
                "docs_source_sha256": supplement["source_sha256"],
            },
            "owner": "nbadb_data_model",
            "revalidation_path": "regenerate_from_exact_pinned_nba_api_source",
            "gate_effects": {
                "model_green": "blocks_on_drift",
                "data_green": "requires_observed_snapshot_receipts",
                "publication": "none",
            },
        }
        contract["contract_sha256"] = _sha256(contract)
        contracts[name] = contract
    return contracts


def _literal_assignments(path: Path, names: Sequence[str]) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = set(names)
    values: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted:
            values[target.id] = ast.literal_eval(node.value)
    if set(values) != wanted:
        raise ValueError("static source omitted a required literal assignment")
    return values


def _indexed_field_names(path: Path, prefix: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    indexes: dict[int, str] = {}
    marker = f"{prefix}_index_"
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.startswith(marker):
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("static field index is invalid")
        indexes[value] = target.id.removeprefix(marker)
    if set(indexes) != set(range(len(indexes))):
        raise ValueError("static field indexes are not contiguous")
    return [indexes[index] for index in range(len(indexes))]


def _projection_keys(path: Path, function_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ),
        None,
    )
    if function is None:
        raise ValueError("static provider omitted its projection function")
    returned = next(
        (
            node.value
            for node in ast.walk(function)
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
        ),
        None,
    )
    if returned is None:
        raise ValueError("static provider projection is not a dictionary")
    if any(key is None for key in returned.keys):
        raise ValueError("static provider projection contains a dictionary expansion")
    keys = [ast.literal_eval(cast("ast.expr", key)) for key in returned.keys]
    if not all(isinstance(key, str) for key in keys):
        raise ValueError("static provider projection contains a non-string key")
    return cast("list[str]", keys)


def _records_for_fields(
    records: Sequence[Sequence[Any]],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    return [dict(zip(fields, record, strict=True)) for record in records]


def _build_static_contracts(package_root: Path) -> dict[str, dict[str, Any]]:
    data_path = package_root / "stats" / "library" / "data.py"
    static_root = package_root / "stats" / "static"
    if not data_path.is_file() or not static_root.is_dir():
        raise ValueError("exact nba_api checkout omitted static source files")
    symbols = [spec[1] for spec in _STATIC_DATASETS]
    records_by_symbol = _literal_assignments(data_path, symbols)
    data_source = data_path.read_text(encoding="utf-8")
    update_match = _UPDATE_MARKER_RE.search(data_source)
    if update_match is None:
        raise ValueError("static source omitted its declared update marker")
    fields_by_kind = {
        "players": _indexed_field_names(data_path, "player"),
        "teams": _indexed_field_names(data_path, "team"),
    }
    contracts: dict[str, dict[str, Any]] = {}
    for dataset_id, symbol, module_name, projector_name, getter_name in _STATIC_DATASETS:
        kind = "players" if "players" in symbol else "teams"
        fields = fields_by_kind[kind]
        provider_path = static_root / module_name
        projected_fields = _projection_keys(provider_path, projector_name)
        records = records_by_symbol[symbol]
        raw_records = _records_for_fields(records, fields)
        projected_records = [
            {field: record[field] for field in projected_fields} for record in raw_records
        ]
        ids = [record["id"] for record in raw_records]
        implemented_omissions = _IMPLEMENTED_STATIC_OMISSIONS.get(dataset_id, frozenset())
        contract: dict[str, Any] = {
            "dataset_id": dataset_id,
            "source_family": "static",
            "provider_module": f"nba_api.stats.static.{Path(module_name).stem}",
            "getter_name": getter_name,
            "source_symbol": symbol,
            "raw_fields": [
                {
                    "name": field,
                    "ordinal": index,
                    "sample_type": type(raw_records[0][field]).__name__,
                    "provider_projection_disposition": (
                        "projected_by_provider"
                        if field in projected_fields
                        else "omitted_by_provider_projection"
                    ),
                    "model_disposition": (
                        "defined_and_implemented"
                        if field in projected_fields or field in implemented_omissions
                        else "contract_blocked"
                    ),
                    "disposition_reason": (
                        "field is present in the provider projection"
                        if field in projected_fields
                        else (
                            "nbadb captures the raw provider field before projection and "
                            "promotes it as compact championship_years_json"
                            if field in implemented_omissions
                            else "source field requires pre-projection bronze preservation"
                        )
                    ),
                    "owner": "nbadb_data_model",
                    "extraction_coverage_effect": (
                        "blocks_model_green"
                        if field not in projected_fields and field not in implemented_omissions
                        else "none"
                    ),
                    "revalidation_path": "regenerate_from_exact_pinned_nba_api_source",
                }
                for index, field in enumerate(fields)
            ],
            "projected_fields": projected_fields,
            "row_count": len(raw_records),
            "unique_id_count": len(set(ids)),
            "source_rows_sha256": _sha256(records),
            "raw_records_sha256": _sha256(raw_records),
            "projected_records_sha256": _sha256(projected_records),
            "data_source_path": "nba_api/stats/library/data.py",
            "data_source_sha256": _file_sha256(data_path),
            "provider_source_path": f"nba_api/stats/static/{module_name}",
            "provider_source_sha256": _file_sha256(provider_path),
            "declared_update_marker": update_match.group("value"),
            "model_disposition": "defined_and_implemented",
            "implementation_status": (
                "contract_blocked"
                if set(fields) - set(projected_fields) - set(implemented_omissions)
                else "complete"
            ),
            "disposition_reason": "nbadb owns the embedded league static reference snapshot",
            "extraction_coverage_effect": "reference_snapshot",
            "evidence": {
                "data_source_sha256": _file_sha256(data_path),
                "provider_source_sha256": _file_sha256(provider_path),
                "source_symbol": symbol,
                "getter_name": getter_name,
                "scope_evidence_kind": "declared_nbadb_nba_and_wnba_product_scope",
            },
            "owner": "nbadb_data_model",
            "revalidation_path": "regenerate_from_exact_pinned_nba_api_source",
            "gate_effects": {
                "model_green": "blocks_on_unresolved_in_scope_fields",
                "data_green": "requires_snapshot_reconciliation",
                "publication": "none",
            },
        }
        if len(ids) != len(set(ids)) or any(
            isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0
            for identifier in ids
        ):
            raise ValueError(f"static dataset {dataset_id} has invalid identifiers")
        contract["contract_sha256"] = _sha256(contract)
        contracts[dataset_id] = contract
    return contracts


def build_pinned_runtime_contract_payload(upstream_root: Path | str) -> dict[str, Any]:
    """Build the canonical registry from one verified exact-source checkout."""

    root = Path(upstream_root).resolve()
    package_root = _verify_generation_source(root)
    stats_contracts = {
        name: contract_to_json(contract)
        for name, contract in sorted(discover_runtime_endpoint_contracts().items())
    }
    live_contracts = _build_live_contracts(root, package_root)
    static_contracts = _build_static_contracts(package_root)
    stats_result_set_count = sum(
        len(contract["result_sets"]) for contract in stats_contracts.values()
    )
    stats_column_count = sum(
        len(result_set["expected_columns"])
        for contract in stats_contracts.values()
        for result_set in contract["result_sets"]
    )
    live_result_set_count = sum(
        len(contract["result_sets"]) for contract in live_contracts.values()
    )
    live_column_count = sum(
        len(result_set["fields"])
        for contract in live_contracts.values()
        for result_set in contract["result_sets"]
    )
    live_source_field_count = sum(
        1
        for contract in live_contracts.values()
        for result_set in contract["result_sets"]
        for field in result_set["fields"]
        if field["source_field"]
    )
    in_scope_static = [
        contract
        for contract in static_contracts.values()
        if contract["model_disposition"] == "defined_and_implemented"
    ]
    payload: dict[str, Any] = {
        "schema_version": RUNTIME_CONTRACT_SCHEMA_VERSION,
        "kind": "nbadb_pinned_nba_api_runtime_contract",
        "provider": _provider_payload(),
        "summary": {
            "endpoint_contract_count": len(stats_contracts),
            "result_set_contract_count": stats_result_set_count,
            "column_contract_count": stats_column_count,
            "live_endpoint_contract_count": len(live_contracts),
            "live_result_set_contract_count": live_result_set_count,
            "live_column_contract_count": live_source_field_count,
            "live_parsed_column_contract_count": live_column_count,
            "static_dataset_contract_count": len(static_contracts),
            "static_modeled_dataset_contract_count": len(in_scope_static),
            "static_modeled_field_contract_count": sum(
                len(contract["raw_fields"]) for contract in in_scope_static
            ),
            "static_out_of_scope_dataset_contract_count": (
                len(static_contracts) - len(in_scope_static)
            ),
        },
        "contracts_sha256": _sha256(stats_contracts),
        "live_contracts_sha256": _sha256(live_contracts),
        "static_contracts_sha256": _sha256(static_contracts),
        "contracts": stats_contracts,
        "live_contracts": live_contracts,
        "static_contracts": static_contracts,
    }
    payload["payload_sha256"] = _sha256(payload)
    return payload


def _validate_owned_contracts(
    contracts: object,
    *,
    id_field: str,
    digest_field: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(contracts, dict):
        raise ValueError("pinned owned contract inventory is invalid")
    owned = cast("dict[str, dict[str, Any]]", contracts)
    for name, contract in owned.items():
        if not isinstance(name, str) or not isinstance(contract, dict):
            raise ValueError("pinned owned contract entry is invalid")
        if contract.get(id_field) != name:
            raise ValueError("pinned owned contract identity is invalid")
        body = dict(contract)
        digest = body.pop(digest_field, None)
        if not isinstance(digest, str) or digest != _sha256(body):
            raise ValueError("pinned owned contract digest is invalid")
    return owned


def _validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("pinned nba_api runtime contract must be an object")
    value = cast("dict[str, Any]", payload)
    if set(value) != {
        "schema_version",
        "kind",
        "provider",
        "summary",
        "contracts_sha256",
        "live_contracts_sha256",
        "static_contracts_sha256",
        "contracts",
        "live_contracts",
        "static_contracts",
        "payload_sha256",
    }:
        raise ValueError("pinned nba_api runtime contract fields do not match the schema")
    if (
        value["schema_version"] != RUNTIME_CONTRACT_SCHEMA_VERSION
        or value["kind"] != "nbadb_pinned_nba_api_runtime_contract"
    ):
        raise ValueError("pinned nba_api runtime contract identity is invalid")
    body = dict(value)
    payload_sha256 = body.pop("payload_sha256")
    if not isinstance(payload_sha256, str) or _sha256(body) != payload_sha256:
        raise ValueError("pinned nba_api runtime contract payload digest is invalid")
    if payload_sha256 != NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256:
        raise ValueError("pinned nba_api runtime contract payload disagrees with authority")
    if value["provider"] != _provider_payload():
        raise ValueError("pinned nba_api runtime contract provider identity drifted")

    stats = value["contracts"]
    if not isinstance(stats, dict) or _sha256(stats) != value["contracts_sha256"]:
        raise ValueError("pinned nba_api stats contract digest is invalid")
    if value["contracts_sha256"] != NBA_API_RUNTIME_CONTRACT_SHA256:
        raise ValueError("pinned nba_api stats contract disagrees with provider authority")
    loaded_stats = {
        name: contract_from_json(contract)
        for name, contract in sorted(stats.items())
        if isinstance(name, str)
    }
    if len(loaded_stats) != len(stats):
        raise ValueError("pinned nba_api stats contract contains an invalid endpoint name")

    live = _validate_owned_contracts(
        value["live_contracts"], id_field="endpoint_id", digest_field="contract_sha256"
    )
    static = _validate_owned_contracts(
        value["static_contracts"], id_field="dataset_id", digest_field="contract_sha256"
    )
    if _sha256(live) != value["live_contracts_sha256"]:
        raise ValueError("pinned nba_api live contract digest is invalid")
    if value["live_contracts_sha256"] != NBA_API_LIVE_CONTRACT_SHA256:
        raise ValueError("pinned nba_api live contract disagrees with provider authority")
    if _sha256(static) != value["static_contracts_sha256"]:
        raise ValueError("pinned nba_api static contract digest is invalid")
    if value["static_contracts_sha256"] != NBA_API_STATIC_CONTRACT_SHA256:
        raise ValueError("pinned nba_api static contract disagrees with provider authority")

    live_owned = {
        name: LiveEndpointContract.from_json(contract) for name, contract in sorted(live.items())
    }
    static_owned = {
        name: StaticDatasetContract.from_json(contract) for name, contract in sorted(static.items())
    }

    in_scope_static = [
        contract
        for contract in static_owned.values()
        if contract.model_disposition == "defined_and_implemented"
    ]
    expected_summary = {
        "endpoint_contract_count": len(loaded_stats),
        "result_set_contract_count": sum(
            len(contract.result_sets) for contract in loaded_stats.values()
        ),
        "column_contract_count": sum(
            len(result_set.expected_columns)
            for contract in loaded_stats.values()
            for result_set in contract.result_sets
        ),
        "live_endpoint_contract_count": len(live),
        "live_result_set_contract_count": sum(
            len(contract.result_sets) for contract in live_owned.values()
        ),
        "live_column_contract_count": sum(
            1
            for contract in live_owned.values()
            for result_set in contract.result_sets
            for field in result_set.fields
            if field.source_field
        ),
        "live_parsed_column_contract_count": sum(
            len(result_set.fields)
            for contract in live_owned.values()
            for result_set in contract.result_sets
        ),
        "static_dataset_contract_count": len(static),
        "static_modeled_dataset_contract_count": len(in_scope_static),
        "static_modeled_field_contract_count": sum(
            len(contract.raw_fields) for contract in in_scope_static
        ),
        "static_out_of_scope_dataset_contract_count": len(static) - len(in_scope_static),
    }
    if value["summary"] != expected_summary:
        raise ValueError("pinned nba_api runtime contract summary is invalid")
    if expected_summary["endpoint_contract_count"] != NBA_API_RUNTIME_CONTRACT_COUNT:
        raise ValueError("pinned nba_api stats contract count disagrees with authority")
    authoritative_counts = {
        "live_endpoint_contract_count": NBA_API_LIVE_ENDPOINT_CONTRACT_COUNT,
        "live_result_set_contract_count": NBA_API_LIVE_RESULT_SET_CONTRACT_COUNT,
        "live_column_contract_count": NBA_API_LIVE_COLUMN_CONTRACT_COUNT,
        "live_parsed_column_contract_count": NBA_API_LIVE_PARSED_COLUMN_CONTRACT_COUNT,
        "static_dataset_contract_count": NBA_API_STATIC_DATASET_CONTRACT_COUNT,
        "static_modeled_field_contract_count": NBA_API_STATIC_MODELED_FIELD_CONTRACT_COUNT,
    }
    for field, expected_count in authoritative_counts.items():
        if expected_summary[field] != expected_count:
            raise ValueError(f"pinned nba_api runtime contract {field} disagrees with authority")
    return value


def load_pinned_runtime_contract_payload(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the generated registry without consulting declarations."""

    if path is None:
        resource = resources.files("nbadb.contracts").joinpath(RUNTIME_CONTRACT_RESOURCE)
        raw = resource.read_bytes()
    else:
        raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("pinned nba_api runtime contract cannot be decoded") from exc
    return _validate_payload(payload)


@lru_cache(maxsize=1)
def pinned_runtime_contracts() -> Mapping[str, NbaApiEndpointContract]:
    payload = load_pinned_runtime_contract_payload()
    return MappingProxyType(
        {
            name: contract_from_json(contract)
            for name, contract in sorted(payload["contracts"].items())
        }
    )


@lru_cache(maxsize=1)
def pinned_live_contracts() -> Mapping[str, LiveEndpointContract]:
    payload = load_pinned_runtime_contract_payload()["live_contracts"]
    return MappingProxyType(
        {
            name: LiveEndpointContract.from_json(contract)
            for name, contract in sorted(payload.items())
        }
    )


@lru_cache(maxsize=1)
def pinned_static_contracts() -> Mapping[str, StaticDatasetContract]:
    payload = load_pinned_runtime_contract_payload()["static_contracts"]
    return MappingProxyType(
        {
            name: StaticDatasetContract.from_json(contract)
            for name, contract in sorted(payload.items())
        }
    )


def endpoint_contract_sha256(contract: NbaApiEndpointContract) -> str:
    """Return the stable digest carried by response and staging receipts."""

    return _sha256(contract_to_json(contract))


def pinned_endpoint_contract(runtime_cls: type) -> NbaApiEndpointContract:
    """Resolve one stats runtime class against the generated registry."""

    contract = pinned_runtime_contracts().get(runtime_cls.__name__)
    if contract is None:
        raise ValueError("runtime endpoint is absent from the pinned nbadb contract")
    endpoint_slug = getattr(runtime_cls, "endpoint", None)
    if contract.module_name != runtime_cls.__module__ or contract.endpoint_slug != endpoint_slug:
        raise ValueError("runtime endpoint identity drifted from the pinned nbadb contract")
    return contract


def pinned_live_endpoint_contract(runtime_cls: type) -> LiveEndpointContract:
    """Resolve one live runtime class against exact generated nested-shape authority."""

    contract = pinned_live_contracts().get(runtime_cls.__name__)
    if contract is None:
        raise ValueError("live endpoint is absent from the pinned nbadb contract")
    if (
        contract.runtime_module != runtime_cls.__module__
        or contract.endpoint_url_template != getattr(runtime_cls, "endpoint_url", None)
    ):
        raise ValueError("live endpoint identity drifted from the pinned nbadb contract")
    return contract


def pinned_static_dataset_contract(dataset_id: str) -> StaticDatasetContract:
    """Resolve one exact static dataset contract by canonical nbadb identity."""

    contract = pinned_static_contracts().get(dataset_id)
    if contract is None:
        raise ValueError("static dataset is absent from the pinned nbadb contract")
    return contract


def owned_contract_sha256(contract: LiveEndpointContract | StaticDatasetContract) -> str:
    """Return the embedded digest for a validated live or static contract."""

    return contract.contract_sha256


def write_pinned_runtime_contract(
    path: Path,
    *,
    upstream_root: Path | str,
    check: bool = False,
) -> bool:
    """Write or check the canonical exact-source generated resource."""

    encoded = _canonical_json_bytes(build_pinned_runtime_contract_payload(upstream_root)) + b"\n"
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise ValueError("pinned nba_api runtime contract has generated drift")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False
