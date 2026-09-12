"""Exact structural provider-field, route-binding, and storage-sink inventories.

This layer owns only structure.  It starts from the independently reconstructed
installed ``nba_api`` package surface, preserves every provider occurrence by source
ordinal, and then records executable route expansion and storage targets separately.
It deliberately has no star-schema, semantic-review, model, metric, or DATA-GREEN
dependency.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast

import polars as pl
import pyarrow as pa

from nbadb.contracts.request_scope_storage_contract import (
    EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT,
    RequestScopeStorageFieldV1,
    request_scope_arrow_type,
)
from nbadb.contracts.staging_route_contract import (
    KnownConditionalStagingRouteAdmission,
    StagingRouteContract,
    admit_known_conditional_staging_route,
    conditional_staging_key_from_route_id,
    staging_route_contract_bundle,
    validate_staging_route_contract_bundle,
)
from nbadb.core.nba_api_provenance import verify_nba_api_provider
from nbadb.core.nba_api_request_surface_verifier import (
    IndependentPackageInventory,
    build_independent_package_inventory,
    build_independent_surface_atoms,
)
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    load_pinned_runtime_contract_payload,
    owned_contract_sha256,
    pinned_live_contracts,
    pinned_runtime_contracts,
    pinned_static_contracts,
)
from nbadb.schemas.registry import get_input_schema

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nbadb.contracts.raw_request_authority import (
        RawRequestAuthorityBundleV2,
        RequestObservationV2,
        ResultOccurrenceV2,
    )
    from nbadb.orchestrate.staging_batches import CommittedStagingFrameReadbackV2

__all__ = [
    "EXPECTED_BOUND_STORAGE_SINK_COUNT",
    "EXPECTED_EXPANDED_SOURCE_OCCURRENCE_COUNT",
    "EXPECTED_LIVE_SOURCE_OCCURRENCE_COUNT",
    "EXPECTED_PROVIDER_SOURCE_OCCURRENCE_COUNT",
    "EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT",
    "EXPECTED_ROUTED_SOURCE_OCCURRENCE_COUNT",
    "EXPECTED_ROUTE_FIELD_BINDING_COUNT",
    "EXPECTED_SINGLE_ROUTE_SOURCE_OCCURRENCE_COUNT",
    "EXPECTED_STATIC_SOURCE_OCCURRENCE_COUNT",
    "EXPECTED_STATS_SOURCE_OCCURRENCE_COUNT",
    "EXPECTED_STORAGE_SINK_COUNT",
    "EXPECTED_STORAGE_ONLY_SINK_COUNT",
    "EXPECTED_UNROUTED_SOURCE_OCCURRENCE_COUNT",
    "FieldFateStructureError",
    "FieldFateStructureBlockerV1",
    "FieldFateStructureV1",
    "ConditionalRouteOccurrenceAuthorityV1",
    "LosslessFieldBindingV1",
    "ProviderFieldSourceInventoryV1",
    "ProviderFieldSourceOccurrenceV1",
    "RouteFieldBindingInventoryV1",
    "RouteFieldBindingV1",
    "RouteLandingFieldJoinV1",
    "SourceRouteExpansionV1",
    "StorageSinkInventoryV1",
    "StorageSinkV1",
    "StatsLosslessFieldBindingV1",
    "canonical_json_bytes",
    "canonical_sha256",
    "compile_field_fate_structure",
    "compile_provider_field_source_inventory",
    "compile_route_field_binding_inventory",
    "compile_storage_sink_inventory",
    "derive_conditional_route_occurrence_authority",
    "validate_conditional_route_occurrence_authority",
    "validate_field_fate_structure",
]

EXPECTED_STATS_SOURCE_OCCURRENCE_COUNT: Final = 9_513
EXPECTED_LIVE_SOURCE_OCCURRENCE_COUNT: Final = 431
EXPECTED_STATIC_SOURCE_OCCURRENCE_COUNT: Final = 26
EXPECTED_PROVIDER_SOURCE_OCCURRENCE_COUNT: Final = 9_970
EXPECTED_ROUTE_FIELD_BINDING_COUNT: Final = 11_323
EXPECTED_ROUTED_SOURCE_OCCURRENCE_COUNT: Final = 9_694
EXPECTED_UNROUTED_SOURCE_OCCURRENCE_COUNT: Final = 276
EXPECTED_SINGLE_ROUTE_SOURCE_OCCURRENCE_COUNT: Final = 8_475
EXPECTED_EXPANDED_SOURCE_OCCURRENCE_COUNT: Final = 1_219
EXPECTED_STORAGE_SINK_COUNT: Final = 13_260
EXPECTED_BOUND_STORAGE_SINK_COUNT: Final = 11_207
EXPECTED_STORAGE_ONLY_SINK_COUNT: Final = 2_053

_EXPECTED_DIRECT_LIVE_SOURCE_OCCURRENCE_COUNT: Final = 409
_EXPECTED_ROUTE_COUNT: Final = 438
_EXPECTED_ROUTE_BINDING_FAMILY_COUNTS: Final = {
    "live": 155,
    "static": 26,
    "stats": 11_142,
}
_EXPECTED_MAPPING_TRANSFORM_COUNTS: Final = {
    "identity": 144,
    "list_to_canonical_json": 2,
    "nested_projection": 2,
    "payload_json_record": 126,
    "rename": 11_049,
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,511}")

type SourceFamily = Literal["stats", "live", "static"]
type SourceProvenanceKind = Literal[
    "installed_stats_header_atom",
    "installed_live_source_field_atom",
    "upstream_live_docs_field",
    "unverified_live_docs_field",
    "installed_live_nested_scalar_projection",
    "installed_static_field_projection",
]
type ExpansionStatus = Literal["unrouted", "single_route", "expanded_routes"]
type StorageSinkStatus = Literal["provider_bound", "storage_only"]
type StructuralBlockerKind = Literal[
    "source_authority_unavailable",
    "lossless_storage_binding_unresolved",
]
type LosslessBindingStrategy = Literal[
    "object_contract_field",
    "scalar_result_set_item",
]
type ConditionalRouteSourceShape = Literal[
    "live_lossless_bound",
    "selected_result_bound",
    "body_node_bound",
    "hybrid_result_body_bound",
]
type StatsLosslessBindingKind = Literal[
    "selected_result_bound",
    "body_node_bound",
]
type RouteLandingFieldOrigin = Literal[
    "provider_bound",
    "provider_multi_bound",
    "lossless_bound",
    "storage_only",
]

_LIVE_DOCS_FIELD_COUNT: Final = 21
_LIVE_NESTED_SCALAR_FIELD_COUNT: Final = 1
_EXPECTED_LOSSLESS_FIELD_BINDING_COUNT: Final = 276
_UPSTREAM_ROOT_ENV: Final = "NBADB_NBA_API_DOCS_ROOT"
_LIVE_LOSSLESS_STAGING_KEY: Final = "stg_nba_api_live_lossless_nodes"
_LOSSLESS_BINDING_REQUIREMENT: Final = (
    "add an exact transactional raw structured-storage route and receipt for this provider "
    "field without collapsing its source occurrence"
)
_SOURCE_AUTHORITY_REQUIREMENT: Final = (
    "supply the verified exact nba_api checkout so the pinned live documentation bytes can "
    "be read and authenticated"
)


class FieldFateStructureError(RuntimeError):
    """Raised when the structural field denominator or a join is not exact."""


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FieldFateStructureError("structural value is not canonical JSON") from exc


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise FieldFateStructureError(f"{field_name} must be a lowercase SHA-256")
    return value


def _token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SOURCE_TOKEN_RE.fullmatch(value) is None:
        raise FieldFateStructureError(f"{field_name} must be an exact safe token")
    return value


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise FieldFateStructureError(f"{field_name} must be a nonempty exact string")
    return value


def _nonnegative(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise FieldFateStructureError(f"{field_name} must be a nonnegative integer")
    return value


def _source_occurrence_id(
    source_family: SourceFamily,
    endpoint_id: str,
    result_set_ordinal: int,
    field_ordinal: int,
) -> str:
    return (
        f"source_field:{source_family}:{endpoint_id}:{result_set_ordinal:04d}:{field_ordinal:04d}"
    )


def _route_binding_id(route_id: str, mapping_ordinal: int) -> str:
    return f"route_binding:{route_id}:{mapping_ordinal:04d}"


def _storage_sink_id(route_id: str, storage_ordinal: int) -> str:
    return f"storage_sink:{route_id}:{storage_ordinal:04d}"


@dataclass(frozen=True, slots=True)
class ProviderFieldSourceOccurrenceV1:
    """One exact provider field occurrence before executable-route expansion."""

    occurrence_id: str
    source_family: SourceFamily
    endpoint_id: str
    result_set_name: str
    result_set_ordinal: int
    field_ordinal: int
    provider_field_name: str
    source_path: str
    authority_atom_id: str
    authority_atom_sha256: str
    endpoint_contract_sha256: str
    provenance_kind: SourceProvenanceKind
    direct_source_field: bool

    def __post_init__(self) -> None:
        if self.source_family not in {"stats", "live", "static"}:
            raise FieldFateStructureError("source_family is unsupported")
        _token(self.endpoint_id, field_name="endpoint_id")
        _text(self.result_set_name, field_name="result_set_name")
        _nonnegative(self.result_set_ordinal, field_name="result_set_ordinal")
        _nonnegative(self.field_ordinal, field_name="field_ordinal")
        _text(self.provider_field_name, field_name="provider_field_name")
        _text(self.source_path, field_name="source_path")
        _text(self.authority_atom_id, field_name="authority_atom_id")
        _sha256(self.authority_atom_sha256, field_name="authority_atom_sha256")
        _sha256(self.endpoint_contract_sha256, field_name="endpoint_contract_sha256")
        if self.provenance_kind not in {
            "installed_stats_header_atom",
            "installed_live_source_field_atom",
            "upstream_live_docs_field",
            "unverified_live_docs_field",
            "installed_live_nested_scalar_projection",
            "installed_static_field_projection",
        }:
            raise FieldFateStructureError("source provenance kind is unsupported")
        if type(self.direct_source_field) is not bool:
            raise FieldFateStructureError("direct_source_field must be a boolean")
        expected_id = _source_occurrence_id(
            self.source_family,
            self.endpoint_id,
            self.result_set_ordinal,
            self.field_ordinal,
        )
        if self.occurrence_id != expected_id:
            raise FieldFateStructureError("source occurrence ID differs from its exact ordinals")

    @property
    def occurrence_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "occurrence_id": self.occurrence_id,
            "source_family": self.source_family,
            "endpoint_id": self.endpoint_id,
            "result_set_name": self.result_set_name,
            "result_set_ordinal": self.result_set_ordinal,
            "field_ordinal": self.field_ordinal,
            "provider_field_name": self.provider_field_name,
            "source_path": self.source_path,
            "authority_atom_id": self.authority_atom_id,
            "authority_atom_sha256": self.authority_atom_sha256,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provenance_kind": self.provenance_kind,
            "direct_source_field": self.direct_source_field,
        }


@dataclass(frozen=True, slots=True)
class FieldFateStructureBlockerV1:
    """One open, field-level blocker outside structural route/sink coverage."""

    blocker_id: str
    blocker_kind: StructuralBlockerKind
    source_occurrence_id: str
    source_occurrence_sha256: str
    evidence_sha256: str
    resolution_requirement: str
    status: Literal["open"] = "open"

    def __post_init__(self) -> None:
        if self.blocker_kind not in {
            "source_authority_unavailable",
            "lossless_storage_binding_unresolved",
        }:
            raise FieldFateStructureError("structural blocker kind is unsupported")
        _text(self.source_occurrence_id, field_name="source_occurrence_id")
        _sha256(self.source_occurrence_sha256, field_name="source_occurrence_sha256")
        _sha256(self.evidence_sha256, field_name="evidence_sha256")
        _text(self.resolution_requirement, field_name="resolution_requirement")
        expected_id = f"field_fate_blocker:{self.blocker_kind}:{self.source_occurrence_id}"
        if self.blocker_id != expected_id:
            raise FieldFateStructureError("structural blocker ID differs from its exact source")
        if self.status != "open":
            raise FieldFateStructureError("structural blockers cannot claim resolution")

    @property
    def blocker_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "blocker_id": self.blocker_id,
            "blocker_kind": self.blocker_kind,
            "source_occurrence_id": self.source_occurrence_id,
            "source_occurrence_sha256": self.source_occurrence_sha256,
            "evidence_sha256": self.evidence_sha256,
            "resolution_requirement": self.resolution_requirement,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class LosslessFieldBindingV1:
    """Exact binding from one wide-unrouted live field to the receipt-bound node sink."""

    binding_id: str
    source_occurrence_id: str
    source_occurrence_sha256: str
    staging_key: str
    endpoint_id: str
    result_set_name: str
    result_set_ordinal: int
    field_ordinal: int
    provider_field_name: str
    contract_result_set_json_path: str
    contract_field_json_path: str
    binding_strategy: LosslessBindingStrategy
    selector_columns: tuple[str, ...]
    sink_authority_sha256: str
    binding_evidence_sha256: str

    def __post_init__(self) -> None:
        expected_id = f"lossless_field_binding:{self.source_occurrence_id}"
        if self.binding_id != expected_id:
            raise FieldFateStructureError("lossless field binding ID differs from its source")
        _text(self.source_occurrence_id, field_name="source_occurrence_id")
        _sha256(self.source_occurrence_sha256, field_name="source_occurrence_sha256")
        if self.staging_key != _LIVE_LOSSLESS_STAGING_KEY:
            raise FieldFateStructureError("lossless field binding names a foreign sink")
        _token(self.endpoint_id, field_name="endpoint_id")
        _text(self.result_set_name, field_name="result_set_name")
        _nonnegative(self.result_set_ordinal, field_name="result_set_ordinal")
        _nonnegative(self.field_ordinal, field_name="field_ordinal")
        _text(self.provider_field_name, field_name="provider_field_name")
        _text(self.contract_result_set_json_path, field_name="contract_result_set_json_path")
        _text(self.contract_field_json_path, field_name="contract_field_json_path")
        if self.binding_strategy not in {
            "object_contract_field",
            "scalar_result_set_item",
        }:
            raise FieldFateStructureError("lossless field binding strategy is unsupported")
        if type(self.selector_columns) is not tuple or self.selector_columns != tuple(
            sorted(set(self.selector_columns))
        ):
            raise FieldFateStructureError("lossless selector columns must be canonical and unique")
        required_common = {
            "contract_json_path",
            "endpoint_contract_sha256",
            "endpoint_id",
            "provider_authority_sha256",
            "request_parameters_json",
            "response_receipt_sha256",
            "result_set_ordinal",
            "snapshot_at",
        }
        required_strategy = (
            {
                "canonical_json",
                "contract_field_ordinal",
                "object_key",
                "presence_kind",
                "value_kind",
            }
            if self.binding_strategy == "object_contract_field"
            else {"array_ordinal", "canonical_json", "presence_kind", "value_kind"}
        )
        if set(self.selector_columns) != required_common | required_strategy:
            raise FieldFateStructureError("lossless field selector is not exact")
        _sha256(self.sink_authority_sha256, field_name="sink_authority_sha256")
        _sha256(self.binding_evidence_sha256, field_name="binding_evidence_sha256")

    @property
    def binding_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "source_occurrence_id": self.source_occurrence_id,
            "source_occurrence_sha256": self.source_occurrence_sha256,
            "staging_key": self.staging_key,
            "endpoint_id": self.endpoint_id,
            "result_set_name": self.result_set_name,
            "result_set_ordinal": self.result_set_ordinal,
            "field_ordinal": self.field_ordinal,
            "provider_field_name": self.provider_field_name,
            "contract_result_set_json_path": self.contract_result_set_json_path,
            "contract_field_json_path": self.contract_field_json_path,
            "binding_strategy": self.binding_strategy,
            "selector_columns": list(self.selector_columns),
            "sink_authority_sha256": self.sink_authority_sha256,
            "binding_evidence_sha256": self.binding_evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class StatsLosslessFieldBindingV1:
    """One occurrence-local stats fallback row without invented provider identity."""

    binding_id: str
    binding_kind: StatsLosslessBindingKind
    route_id: str
    staging_key: str
    staging_row_ordinal: int
    observation_record_sha256: str
    observation_sha256: str
    source_occurrence_sha256: str | None
    body_object_sha256: str | None
    response_receipt_sha256: str
    record_kind: str
    result_set_name: str | None
    result_set_occurrence: int | None
    provider_index: int | None
    canonical_index: int | None
    header_name: str | None
    header_ordinal: int | None
    row_ordinal: int | None
    node_ordinal: int | None
    parent_node_ordinal: int | None
    json_path: str | None
    parent_json_path: str | None
    depth: int | None
    object_key: str | None
    object_key_ordinal: int | None
    array_ordinal: int | None
    selector_columns: tuple[str, ...]
    row_identity_json: str
    row_identity_sha256: str
    binding_evidence_sha256: str

    def __post_init__(self) -> None:
        _text(self.binding_id, field_name="stats lossless binding_id")
        if self.binding_kind not in {"selected_result_bound", "body_node_bound"}:
            raise FieldFateStructureError("stats lossless binding kind is unsupported")
        _token(self.route_id, field_name="stats lossless route_id")
        if self.staging_key != "stg_nba_api_lossless_result_cells":
            raise FieldFateStructureError("stats lossless binding names a foreign staging key")
        _nonnegative(self.staging_row_ordinal, field_name="stats lossless row ordinal")
        _sha256(self.observation_record_sha256, field_name="observation_record_sha256")
        _sha256(self.observation_sha256, field_name="observation_sha256")
        _sha256(self.response_receipt_sha256, field_name="response_receipt_sha256")
        _text(self.record_kind, field_name="record_kind")
        if self.binding_kind == "selected_result_bound":
            if self.source_occurrence_sha256 is None or self.body_object_sha256 is not None:
                raise FieldFateStructureError(
                    "selected stats binding must name exactly one result occurrence"
                )
            _sha256(self.source_occurrence_sha256, field_name="source_occurrence_sha256")
        else:
            if self.source_occurrence_sha256 is not None or self.body_object_sha256 is None:
                raise FieldFateStructureError(
                    "body-node binding cannot promote a provider result occurrence"
                )
            _sha256(self.body_object_sha256, field_name="body_object_sha256")
        for field_name in (
            "result_set_occurrence",
            "provider_index",
            "canonical_index",
            "header_ordinal",
            "row_ordinal",
            "node_ordinal",
            "parent_node_ordinal",
            "depth",
            "object_key_ordinal",
            "array_ordinal",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _nonnegative(value, field_name=field_name)
        for field_name in (
            "result_set_name",
            "header_name",
            "json_path",
            "parent_json_path",
            "object_key",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _text(value, field_name=field_name)
        if type(self.selector_columns) is not tuple or self.selector_columns != tuple(
            sorted(set(self.selector_columns))
        ):
            raise FieldFateStructureError(
                "stats lossless selector columns must be canonical and unique"
            )
        try:
            decoded = json.loads(self.row_identity_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FieldFateStructureError("stats lossless row identity is invalid JSON") from exc
        if not isinstance(decoded, dict) or canonical_json_bytes(decoded).decode() != (
            self.row_identity_json
        ):
            raise FieldFateStructureError("stats lossless row identity is not canonical")
        if self.row_identity_sha256 != canonical_sha256(decoded):
            raise FieldFateStructureError("stats lossless row identity digest drifted")
        _sha256(self.binding_evidence_sha256, field_name="binding_evidence_sha256")

    @property
    def binding_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "binding_kind": self.binding_kind,
            "route_id": self.route_id,
            "staging_key": self.staging_key,
            "staging_row_ordinal": self.staging_row_ordinal,
            "observation_record_sha256": self.observation_record_sha256,
            "observation_sha256": self.observation_sha256,
            "source_occurrence_sha256": self.source_occurrence_sha256,
            "body_object_sha256": self.body_object_sha256,
            "response_receipt_sha256": self.response_receipt_sha256,
            "record_kind": self.record_kind,
            "result_set_name": self.result_set_name,
            "result_set_occurrence": self.result_set_occurrence,
            "provider_index": self.provider_index,
            "canonical_index": self.canonical_index,
            "header_name": self.header_name,
            "header_ordinal": self.header_ordinal,
            "row_ordinal": self.row_ordinal,
            "node_ordinal": self.node_ordinal,
            "parent_node_ordinal": self.parent_node_ordinal,
            "json_path": self.json_path,
            "parent_json_path": self.parent_json_path,
            "depth": self.depth,
            "object_key": self.object_key,
            "object_key_ordinal": self.object_key_ordinal,
            "array_ordinal": self.array_ordinal,
            "selector_columns": list(self.selector_columns),
            "row_identity_json": self.row_identity_json,
            "row_identity_sha256": self.row_identity_sha256,
            "binding_evidence_sha256": self.binding_evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class ProviderFieldSourceInventoryV1:
    """Exact installed-source field denominator with no route expansion."""

    occurrences: tuple[ProviderFieldSourceOccurrenceV1, ...]
    independent_package_inventory_sha256: str
    independent_source_atoms_sha256: str
    pinned_runtime_contract_payload_sha256: str
    live_docs_field_evidence_sha256: str
    live_nested_scalar_evidence_sha256: str
    static_field_evidence_sha256: str
    _by_occurrence_id: Mapping[str, ProviderFieldSourceOccurrenceV1] = field(
        init=False,
        repr=False,
        compare=False,
    )

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "field_fate_provider_source_inventory"

    def __post_init__(self) -> None:
        if type(self.occurrences) is not tuple or any(
            not isinstance(item, ProviderFieldSourceOccurrenceV1) for item in self.occurrences
        ):
            raise FieldFateStructureError("source occurrences must be an immutable typed tuple")
        if len(self.occurrences) != EXPECTED_PROVIDER_SOURCE_OCCURRENCE_COUNT:
            raise FieldFateStructureError("provider source denominator differs from the exact pin")
        expected_order = tuple(sorted(self.occurrences, key=lambda item: item.occurrence_id))
        if self.occurrences != expected_order:
            raise FieldFateStructureError("source occurrences are not in canonical order")
        ids = tuple(item.occurrence_id for item in self.occurrences)
        hashes = tuple(item.occurrence_sha256 for item in self.occurrences)
        if len(ids) != len(set(ids)) or len(hashes) != len(set(hashes)):
            raise FieldFateStructureError("source occurrences overlap or collapse")
        counts = Counter(item.source_family for item in self.occurrences)
        if counts != {
            "stats": EXPECTED_STATS_SOURCE_OCCURRENCE_COUNT,
            "live": EXPECTED_LIVE_SOURCE_OCCURRENCE_COUNT,
            "static": EXPECTED_STATIC_SOURCE_OCCURRENCE_COUNT,
        }:
            raise FieldFateStructureError("source-family denominator differs from the exact pin")
        if (
            sum(
                item.provenance_kind == "installed_live_source_field_atom"
                for item in self.occurrences
            )
            != _EXPECTED_DIRECT_LIVE_SOURCE_OCCURRENCE_COUNT
        ):
            raise FieldFateStructureError("direct live source-field denominator drifted")
        provenance_counts = Counter(item.provenance_kind for item in self.occurrences)
        if (
            provenance_counts["upstream_live_docs_field"]
            + provenance_counts["unverified_live_docs_field"]
            != _LIVE_DOCS_FIELD_COUNT
            or provenance_counts["installed_live_nested_scalar_projection"]
            != _LIVE_NESTED_SCALAR_FIELD_COUNT
            or provenance_counts["installed_static_field_projection"]
            != EXPECTED_STATIC_SOURCE_OCCURRENCE_COUNT
            or (
                provenance_counts["upstream_live_docs_field"]
                and provenance_counts["unverified_live_docs_field"]
            )
        ):
            raise FieldFateStructureError("independent non-atom source authorities drifted")
        for field_name in (
            "independent_package_inventory_sha256",
            "independent_source_atoms_sha256",
            "pinned_runtime_contract_payload_sha256",
            "live_docs_field_evidence_sha256",
            "live_nested_scalar_evidence_sha256",
            "static_field_evidence_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "_by_occurrence_id",
            MappingProxyType({item.occurrence_id: item for item in self.occurrences}),
        )

    @property
    def by_occurrence_id(self) -> Mapping[str, ProviderFieldSourceOccurrenceV1]:
        return self._by_occurrence_id

    @property
    def occurrences_sha256(self) -> str:
        return canonical_sha256([item.to_dict() for item in self.occurrences])

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "independent_package_inventory_sha256": self.independent_package_inventory_sha256,
            "independent_source_atoms_sha256": self.independent_source_atoms_sha256,
            "pinned_runtime_contract_payload_sha256": (self.pinned_runtime_contract_payload_sha256),
            "live_docs_field_evidence_sha256": self.live_docs_field_evidence_sha256,
            "live_nested_scalar_evidence_sha256": self.live_nested_scalar_evidence_sha256,
            "static_field_evidence_sha256": self.static_field_evidence_sha256,
            "occurrences_sha256": self.occurrences_sha256,
            "summary": {
                "provider_source_occurrence_count": len(self.occurrences),
                "source_family_counts": dict(
                    sorted(Counter(item.source_family for item in self.occurrences).items())
                ),
                "provenance_kind_counts": dict(
                    sorted(Counter(item.provenance_kind for item in self.occurrences).items())
                ),
            },
            "occurrences": [item.to_dict() for item in self.occurrences],
        }


@dataclass(frozen=True, slots=True)
class RouteFieldBindingV1:
    """One exact executable route mapping bound to one source occurrence."""

    binding_id: str
    route_id: str
    route_ordinal: int
    mapping_ordinal: int
    source_family: SourceFamily
    source_occurrence_id: str
    source_occurrence_sha256: str
    route_contract_sha256: str
    endpoint_role: str
    endpoint_alias_target: str | None
    storage_role: str
    storage_role_target: str | None
    provider_column: str
    canonical_column: str
    mapping_transform: str
    storage_sink_id: str
    storage_column: str

    def __post_init__(self) -> None:
        _text(self.route_id, field_name="route_id")
        _nonnegative(self.route_ordinal, field_name="route_ordinal")
        _nonnegative(self.mapping_ordinal, field_name="mapping_ordinal")
        if self.binding_id != _route_binding_id(self.route_id, self.mapping_ordinal):
            raise FieldFateStructureError("route binding ID differs from route/mapping ordinals")
        if self.source_family not in {"stats", "live", "static"}:
            raise FieldFateStructureError("route binding source family is unsupported")
        _text(self.source_occurrence_id, field_name="source_occurrence_id")
        _sha256(self.source_occurrence_sha256, field_name="source_occurrence_sha256")
        _sha256(self.route_contract_sha256, field_name="route_contract_sha256")
        for field_name in (
            "endpoint_role",
            "storage_role",
            "provider_column",
            "canonical_column",
            "mapping_transform",
            "storage_sink_id",
            "storage_column",
        ):
            _text(getattr(self, field_name), field_name=field_name)
        for field_name in ("endpoint_alias_target", "storage_role_target"):
            value = getattr(self, field_name)
            if value is not None:
                _text(value, field_name=field_name)

    @property
    def binding_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "route_id": self.route_id,
            "route_ordinal": self.route_ordinal,
            "mapping_ordinal": self.mapping_ordinal,
            "source_family": self.source_family,
            "source_occurrence_id": self.source_occurrence_id,
            "source_occurrence_sha256": self.source_occurrence_sha256,
            "route_contract_sha256": self.route_contract_sha256,
            "endpoint_role": self.endpoint_role,
            "endpoint_alias_target": self.endpoint_alias_target,
            "storage_role": self.storage_role,
            "storage_role_target": self.storage_role_target,
            "provider_column": self.provider_column,
            "canonical_column": self.canonical_column,
            "mapping_transform": self.mapping_transform,
            "storage_sink_id": self.storage_sink_id,
            "storage_column": self.storage_column,
        }


@dataclass(frozen=True, slots=True)
class SourceRouteExpansionV1:
    """All route bindings for one source occurrence, including the unrouted case."""

    source_occurrence_id: str
    source_occurrence_sha256: str
    binding_ids: tuple[str, ...]
    alias_binding_ids: tuple[str, ...]
    copy_binding_ids: tuple[str, ...]
    status: ExpansionStatus

    def __post_init__(self) -> None:
        _text(self.source_occurrence_id, field_name="source_occurrence_id")
        _sha256(self.source_occurrence_sha256, field_name="source_occurrence_sha256")
        for field_name in ("binding_ids", "alias_binding_ids", "copy_binding_ids"):
            values = getattr(self, field_name)
            if type(values) is not tuple or values != tuple(sorted(set(values))):
                raise FieldFateStructureError(f"{field_name} must be canonical and unique")
            for value in values:
                _text(value, field_name=field_name)
        if not set(self.alias_binding_ids) <= set(self.binding_ids) or not set(
            self.copy_binding_ids
        ) <= set(self.binding_ids):
            raise FieldFateStructureError("alias/copy expansion is outside its binding inventory")
        expected_status: ExpansionStatus = (
            "unrouted"
            if not self.binding_ids
            else "single_route"
            if len(self.binding_ids) == 1
            else "expanded_routes"
        )
        if self.status != expected_status:
            raise FieldFateStructureError("source route-expansion status is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_occurrence_id": self.source_occurrence_id,
            "source_occurrence_sha256": self.source_occurrence_sha256,
            "binding_ids": list(self.binding_ids),
            "alias_binding_ids": list(self.alias_binding_ids),
            "copy_binding_ids": list(self.copy_binding_ids),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class RouteFieldBindingInventoryV1:
    """Route-local expansion of source occurrences, separate from source identity."""

    bindings: tuple[RouteFieldBindingV1, ...]
    source_expansions: tuple[SourceRouteExpansionV1, ...]
    provider_source_inventory_sha256: str
    staging_route_contract_sha256: str
    _by_binding_id: Mapping[str, RouteFieldBindingV1] = field(
        init=False,
        repr=False,
        compare=False,
    )

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "field_fate_route_binding_inventory"

    def __post_init__(self) -> None:
        if type(self.bindings) is not tuple or any(
            not isinstance(item, RouteFieldBindingV1) for item in self.bindings
        ):
            raise FieldFateStructureError("route bindings must be an immutable typed tuple")
        if len(self.bindings) != EXPECTED_ROUTE_FIELD_BINDING_COUNT:
            raise FieldFateStructureError("route binding denominator differs from exact routes")
        expected_binding_order = tuple(
            sorted(self.bindings, key=lambda item: (item.route_ordinal, item.mapping_ordinal))
        )
        if self.bindings != expected_binding_order:
            raise FieldFateStructureError("route bindings are not in executable route order")
        binding_ids = tuple(item.binding_id for item in self.bindings)
        if len(binding_ids) != len(set(binding_ids)):
            raise FieldFateStructureError("route binding IDs overlap")
        if (
            Counter(item.source_family for item in self.bindings)
            != _EXPECTED_ROUTE_BINDING_FAMILY_COUNTS
        ):
            raise FieldFateStructureError("route binding source-family counts drifted")
        if (
            Counter(item.mapping_transform for item in self.bindings)
            != _EXPECTED_MAPPING_TRANSFORM_COUNTS
        ):
            raise FieldFateStructureError("route binding transform counts drifted")

        if type(self.source_expansions) is not tuple or any(
            not isinstance(item, SourceRouteExpansionV1) for item in self.source_expansions
        ):
            raise FieldFateStructureError("source expansions must be an immutable typed tuple")
        if len(self.source_expansions) != EXPECTED_PROVIDER_SOURCE_OCCURRENCE_COUNT:
            raise FieldFateStructureError("source expansion inventory omits provider occurrences")
        expansion_ids = tuple(item.source_occurrence_id for item in self.source_expansions)
        if expansion_ids != tuple(sorted(set(expansion_ids))):
            raise FieldFateStructureError("source expansions overlap or are not canonical")
        expanded_binding_ids = tuple(
            binding_id for item in self.source_expansions for binding_id in item.binding_ids
        )
        if len(expanded_binding_ids) != len(set(expanded_binding_ids)) or set(
            expanded_binding_ids
        ) != set(binding_ids):
            raise FieldFateStructureError("source expansions omit or overlap route bindings")
        statuses = Counter(item.status for item in self.source_expansions)
        if statuses != {
            "unrouted": EXPECTED_UNROUTED_SOURCE_OCCURRENCE_COUNT,
            "single_route": EXPECTED_SINGLE_ROUTE_SOURCE_OCCURRENCE_COUNT,
            "expanded_routes": EXPECTED_EXPANDED_SOURCE_OCCURRENCE_COUNT,
        }:
            raise FieldFateStructureError("source expansion status counts drifted")
        for field_name in (
            "provider_source_inventory_sha256",
            "staging_route_contract_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "_by_binding_id",
            MappingProxyType({item.binding_id: item for item in self.bindings}),
        )

    @property
    def by_binding_id(self) -> Mapping[str, RouteFieldBindingV1]:
        return self._by_binding_id

    @property
    def bindings_sha256(self) -> str:
        return canonical_sha256([item.to_dict() for item in self.bindings])

    @property
    def expansions_sha256(self) -> str:
        return canonical_sha256([item.to_dict() for item in self.source_expansions])

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "provider_source_inventory_sha256": self.provider_source_inventory_sha256,
            "staging_route_contract_sha256": self.staging_route_contract_sha256,
            "bindings_sha256": self.bindings_sha256,
            "expansions_sha256": self.expansions_sha256,
            "summary": {
                "route_binding_count": len(self.bindings),
                "routed_source_occurrence_count": sum(
                    item.status != "unrouted" for item in self.source_expansions
                ),
                "unrouted_source_occurrence_count": sum(
                    item.status == "unrouted" for item in self.source_expansions
                ),
                "source_family_counts": dict(
                    sorted(Counter(item.source_family for item in self.bindings).items())
                ),
                "mapping_transform_counts": dict(
                    sorted(Counter(item.mapping_transform for item in self.bindings).items())
                ),
                "expansion_status_counts": dict(
                    sorted(Counter(item.status for item in self.source_expansions).items())
                ),
            },
            "bindings": [item.to_dict() for item in self.bindings],
            "source_expansions": [item.to_dict() for item in self.source_expansions],
        }


@dataclass(frozen=True, slots=True)
class StorageSinkV1:
    """One route-local schema column, whether provider-bound or storage-only."""

    sink_id: str
    route_id: str
    route_ordinal: int
    storage_ordinal: int
    staging_key: str
    schema_tier: str
    schema_table: str
    schema_class: str
    storage_role: str
    storage_role_target: str | None
    storage_column: str
    route_contract_sha256: str
    binding_ids: tuple[str, ...]
    status: StorageSinkStatus

    def __post_init__(self) -> None:
        _text(self.route_id, field_name="route_id")
        _nonnegative(self.route_ordinal, field_name="route_ordinal")
        _nonnegative(self.storage_ordinal, field_name="storage_ordinal")
        if self.sink_id != _storage_sink_id(self.route_id, self.storage_ordinal):
            raise FieldFateStructureError("storage sink ID differs from route/storage ordinals")
        for field_name in (
            "staging_key",
            "schema_tier",
            "schema_table",
            "schema_class",
            "storage_role",
            "storage_column",
        ):
            _text(getattr(self, field_name), field_name=field_name)
        if self.storage_role_target is not None:
            _text(self.storage_role_target, field_name="storage_role_target")
        _sha256(self.route_contract_sha256, field_name="route_contract_sha256")
        if type(self.binding_ids) is not tuple or self.binding_ids != tuple(
            sorted(set(self.binding_ids))
        ):
            raise FieldFateStructureError("storage sink binding IDs must be canonical and unique")
        expected_status: StorageSinkStatus = (
            "provider_bound" if self.binding_ids else "storage_only"
        )
        if self.status != expected_status:
            raise FieldFateStructureError("storage sink status differs from its bindings")

    @property
    def sink_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "sink_id": self.sink_id,
            "route_id": self.route_id,
            "route_ordinal": self.route_ordinal,
            "storage_ordinal": self.storage_ordinal,
            "staging_key": self.staging_key,
            "schema_tier": self.schema_tier,
            "schema_table": self.schema_table,
            "schema_class": self.schema_class,
            "storage_role": self.storage_role,
            "storage_role_target": self.storage_role_target,
            "storage_column": self.storage_column,
            "route_contract_sha256": self.route_contract_sha256,
            "binding_ids": list(self.binding_ids),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ConditionalRouteOccurrenceAuthorityV1:
    """Exact occurrence-local authority for one observed conditional route."""

    route_id: str
    route_local_ordinal: int
    endpoint_name: str
    source_family: Literal["stats", "live"]
    source_shape: ConditionalRouteSourceShape
    staging_key: str
    schema_tier: Literal["staging"]
    schema_table: str
    schema_class: str
    storage_role: Literal["conditional_lossless"]
    route_admission_sha256: str
    field_fate_structure_sha256: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    committed_logical_parameters_sha256: str
    source_parameters_sha256s: tuple[str, ...]
    staging_parameters_sha256: str | None
    raw_bundle_sha256: str
    readback_receipt_sha256: str
    committed_receipt_root_sha256: str
    response_receipt_sha256: str
    observation_record_sha256s: tuple[str, ...]
    result_occurrence_sha256s: tuple[str, ...]
    body_object_sha256s: tuple[str, ...]
    stats_bindings: tuple[StatsLosslessFieldBindingV1, ...]
    live_binding_ids: tuple[str, ...]
    sinks: tuple[StorageSinkV1, ...]
    authority_sha256: str
    raw_bundle: RawRequestAuthorityBundleV2 = field(repr=False, compare=False)
    readback: CommittedStagingFrameReadbackV2 = field(repr=False, compare=False)

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "conditional_route_occurrence_authority"

    def __post_init__(self) -> None:
        _token(self.route_id, field_name="conditional route_id")
        _nonnegative(self.route_local_ordinal, field_name="conditional route-local ordinal")
        _token(self.endpoint_name, field_name="conditional endpoint_name")
        if self.source_family not in {"stats", "live"}:
            raise FieldFateStructureError("conditional route source family is unsupported")
        expected_shapes = (
            {
                "selected_result_bound",
                "body_node_bound",
                "hybrid_result_body_bound",
            }
            if self.source_family == "stats"
            else {"live_lossless_bound"}
        )
        if self.source_shape not in expected_shapes:
            raise FieldFateStructureError("conditional route source shape differs from its family")
        if conditional_staging_key_from_route_id(self.route_id) != self.staging_key:
            raise FieldFateStructureError("conditional route ID differs from its staging key")
        for field_name in ("schema_table", "schema_class"):
            _text(getattr(self, field_name), field_name=field_name)
        if (
            self.schema_tier != "staging"
            or self.schema_table != self.staging_key
            or self.storage_role != "conditional_lossless"
        ):
            raise FieldFateStructureError("conditional route storage contract is not exact")
        for field_name in (
            "route_admission_sha256",
            "field_fate_structure_sha256",
            "provider_authority_sha256",
            "endpoint_contract_sha256",
            "committed_logical_parameters_sha256",
            "raw_bundle_sha256",
            "readback_receipt_sha256",
            "committed_receipt_root_sha256",
            "response_receipt_sha256",
            "authority_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        if type(self.source_parameters_sha256s) is not tuple or (
            not self.source_parameters_sha256s
            or self.source_parameters_sha256s != tuple(sorted(set(self.source_parameters_sha256s)))
        ):
            raise FieldFateStructureError(
                "conditional source parameter hashes must be canonical and unique"
            )
        for digest in self.source_parameters_sha256s:
            _sha256(digest, field_name="source_parameters_sha256")
        if self.staging_parameters_sha256 is not None:
            _sha256(
                self.staging_parameters_sha256,
                field_name="staging_parameters_sha256",
            )
        for field_name in (
            "observation_record_sha256s",
            "result_occurrence_sha256s",
            "body_object_sha256s",
            "live_binding_ids",
        ):
            values = getattr(self, field_name)
            if type(values) is not tuple or values != tuple(sorted(set(values))):
                raise FieldFateStructureError(
                    f"conditional {field_name} must be canonical and unique"
                )
        for digest in (
            *self.observation_record_sha256s,
            *self.result_occurrence_sha256s,
            *self.body_object_sha256s,
        ):
            _sha256(digest, field_name="conditional occurrence digest")
        if type(self.stats_bindings) is not tuple or any(
            type(item) is not StatsLosslessFieldBindingV1 for item in self.stats_bindings
        ):
            raise FieldFateStructureError("conditional stats bindings are not an exact tuple")
        if self.stats_bindings != tuple(
            sorted(self.stats_bindings, key=lambda item: item.binding_id)
        ):
            raise FieldFateStructureError("conditional stats bindings are not canonical")
        if self.source_family == "stats":
            if self.live_binding_ids or not self.stats_bindings:
                raise FieldFateStructureError("stats conditional authority has foreign bindings")
        elif self.stats_bindings or not self.live_binding_ids:
            raise FieldFateStructureError("live conditional authority has foreign bindings")
        if self.source_shape == "body_node_bound":
            if self.result_occurrence_sha256s or not self.body_object_sha256s:
                raise FieldFateStructureError(
                    "body-node authority cannot promote a result occurrence"
                )
        elif self.source_shape == "hybrid_result_body_bound":
            if not self.result_occurrence_sha256s or not self.body_object_sha256s:
                raise FieldFateStructureError(
                    "hybrid stats authority requires result and body-node roots"
                )
        elif not self.result_occurrence_sha256s:
            raise FieldFateStructureError("selected conditional authority has no result occurrence")
        if type(self.sinks) is not tuple or any(
            type(item) is not StorageSinkV1 for item in self.sinks
        ):
            raise FieldFateStructureError("conditional route sinks are not an exact tuple")
        if tuple(item.storage_ordinal for item in self.sinks) != tuple(range(len(self.sinks))):
            raise FieldFateStructureError("conditional route sink ordinals are not contiguous")
        if any(
            item.route_id != self.route_id
            or item.route_ordinal != self.route_local_ordinal
            or item.staging_key != self.staging_key
            or item.schema_tier != self.schema_tier
            or item.schema_table != self.schema_table
            or item.schema_class != self.schema_class
            or item.storage_role != self.storage_role
            or item.storage_role_target is not None
            or item.route_contract_sha256 != self.route_admission_sha256
            for item in self.sinks
        ):
            raise FieldFateStructureError("conditional route sink differs from its authority")
        if self.authority_sha256 != canonical_sha256(self.identity_payload()):
            raise FieldFateStructureError("conditional route authority digest drifted")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "route_id": self.route_id,
            "route_local_ordinal": self.route_local_ordinal,
            "endpoint_name": self.endpoint_name,
            "source_family": self.source_family,
            "source_shape": self.source_shape,
            "staging_key": self.staging_key,
            "schema_tier": self.schema_tier,
            "schema_table": self.schema_table,
            "schema_class": self.schema_class,
            "storage_role": self.storage_role,
            "route_admission_sha256": self.route_admission_sha256,
            "field_fate_structure_sha256": self.field_fate_structure_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "committed_logical_parameters_sha256": (self.committed_logical_parameters_sha256),
            "source_parameters_sha256s": list(self.source_parameters_sha256s),
            "staging_parameters_sha256": self.staging_parameters_sha256,
            "raw_bundle_sha256": self.raw_bundle_sha256,
            "readback_receipt_sha256": self.readback_receipt_sha256,
            "committed_receipt_root_sha256": self.committed_receipt_root_sha256,
            "response_receipt_sha256": self.response_receipt_sha256,
            "observation_record_sha256s": list(self.observation_record_sha256s),
            "result_occurrence_sha256s": list(self.result_occurrence_sha256s),
            "body_object_sha256s": list(self.body_object_sha256s),
            "stats_bindings": [item.to_dict() for item in self.stats_bindings],
            "live_binding_ids": list(self.live_binding_ids),
            "sinks": [item.to_dict() for item in self.sinks],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "authority_sha256": self.authority_sha256}


@dataclass(frozen=True, slots=True)
class RouteLandingFieldJoinV1:
    """One exact route-local storage field joined back to provider authority."""

    sink: StorageSinkV1
    route_bindings: tuple[RouteFieldBindingV1, ...]
    provider_sources: tuple[ProviderFieldSourceOccurrenceV1, ...]
    lossless_bindings: tuple[LosslessFieldBindingV1 | StatsLosslessFieldBindingV1, ...]
    origin: RouteLandingFieldOrigin

    def __post_init__(self) -> None:
        if type(self.sink) is not StorageSinkV1:
            raise FieldFateStructureError("route landing field has a foreign storage sink")
        if type(self.route_bindings) is not tuple or any(
            type(item) is not RouteFieldBindingV1 for item in self.route_bindings
        ):
            raise FieldFateStructureError("route landing bindings must be an exact typed tuple")
        if type(self.provider_sources) is not tuple or any(
            type(item) is not ProviderFieldSourceOccurrenceV1 for item in self.provider_sources
        ):
            raise FieldFateStructureError("route landing sources must be an exact typed tuple")
        if type(self.lossless_bindings) is not tuple or any(
            type(item) not in {LosslessFieldBindingV1, StatsLosslessFieldBindingV1}
            for item in self.lossless_bindings
        ):
            raise FieldFateStructureError(
                "route landing lossless bindings must be an exact typed tuple"
            )

        if self.lossless_bindings:
            if self.origin != "lossless_bound":
                raise FieldFateStructureError(
                    "lossless route landing authority has the wrong origin"
                )
            if self.route_bindings or self.sink.status != "provider_bound":
                raise FieldFateStructureError(
                    "lossless route landing authority cannot invent wide bindings"
                )
            lossless_binding_ids = tuple(binding.binding_id for binding in self.lossless_bindings)
            if lossless_binding_ids != tuple(sorted(set(lossless_binding_ids))):
                raise FieldFateStructureError(
                    "lossless route landing bindings are not canonical and unique"
                )
            if lossless_binding_ids != self.sink.binding_ids:
                raise FieldFateStructureError(
                    "lossless route landing binding multiplicity differs from its sink"
                )
            if all(type(binding) is LosslessFieldBindingV1 for binding in self.lossless_bindings):
                if len(self.lossless_bindings) != len(self.provider_sources):
                    raise FieldFateStructureError(
                        "live lossless bindings and sources differ in multiplicity"
                    )
                for binding, source in zip(
                    self.lossless_bindings,
                    self.provider_sources,
                    strict=True,
                ):
                    if type(binding) is not LosslessFieldBindingV1 or (
                        binding.staging_key != self.sink.staging_key
                        or self.sink.storage_column not in binding.selector_columns
                        or binding.source_occurrence_id != source.occurrence_id
                        or binding.source_occurrence_sha256 != source.occurrence_sha256
                        or source.source_family != "live"
                        or binding.endpoint_id != source.endpoint_id
                        or binding.result_set_name != source.result_set_name
                        or binding.result_set_ordinal != source.result_set_ordinal
                        or binding.field_ordinal != source.field_ordinal
                        or binding.provider_field_name != source.provider_field_name
                        or binding.contract_field_json_path != source.source_path
                    ):
                        raise FieldFateStructureError(
                            "lossless route landing binding/source join differs from its sink"
                        )
            elif self.provider_sources or any(
                type(binding) is not StatsLosslessFieldBindingV1
                or binding.staging_key != self.sink.staging_key
                or self.sink.storage_column not in binding.selector_columns
                for binding in self.lossless_bindings
            ):
                raise FieldFateStructureError(
                    "stats lossless route landing invented provider result authority"
                )
            return

        binding_ids = tuple(item.binding_id for item in self.route_bindings)
        if binding_ids != self.sink.binding_ids:
            raise FieldFateStructureError(
                "route landing binding multiplicity differs from its storage sink"
            )

        if len(self.route_bindings) != len(self.provider_sources):
            raise FieldFateStructureError(
                "route landing provider bindings and sources differ in multiplicity"
            )
        for binding, source in zip(
            self.route_bindings,
            self.provider_sources,
            strict=True,
        ):
            if (
                binding.storage_sink_id != self.sink.sink_id
                or binding.storage_column != self.sink.storage_column
                or binding.source_occurrence_id != source.occurrence_id
                or binding.source_occurrence_sha256 != source.occurrence_sha256
            ):
                raise FieldFateStructureError(
                    "route landing binding/source join differs from its exact sink"
                )

        expected_origin: RouteLandingFieldOrigin
        if not self.route_bindings:
            expected_origin = "storage_only"
        elif len(self.route_bindings) == 1:
            expected_origin = "provider_bound"
        else:
            expected_origin = "provider_multi_bound"
        if self.origin != expected_origin:
            raise FieldFateStructureError(
                "route landing origin differs from its exact binding multiplicity"
            )
        if (expected_origin == "storage_only") != (self.sink.status == "storage_only"):
            raise FieldFateStructureError(
                "route landing storage-only status differs from its exact sink"
            )


@dataclass(frozen=True, slots=True)
class StorageSinkInventoryV1:
    """Complete route-local storage-column inventory and binding partition."""

    sinks: tuple[StorageSinkV1, ...]
    route_binding_inventory_sha256: str
    staging_route_contract_sha256: str
    _by_sink_id: Mapping[str, StorageSinkV1] = field(
        init=False,
        repr=False,
        compare=False,
    )

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "field_fate_storage_sink_inventory"

    def __post_init__(self) -> None:
        if type(self.sinks) is not tuple or any(
            not isinstance(item, StorageSinkV1) for item in self.sinks
        ):
            raise FieldFateStructureError("storage sinks must be an immutable typed tuple")
        if len(self.sinks) != EXPECTED_STORAGE_SINK_COUNT:
            raise FieldFateStructureError("storage sink denominator differs from exact schemas")
        expected_order = tuple(
            sorted(self.sinks, key=lambda item: (item.route_ordinal, item.storage_ordinal))
        )
        if self.sinks != expected_order:
            raise FieldFateStructureError("storage sinks are not in route/schema order")
        sink_ids = tuple(item.sink_id for item in self.sinks)
        if len(sink_ids) != len(set(sink_ids)):
            raise FieldFateStructureError("storage sink IDs overlap")
        statuses = Counter(item.status for item in self.sinks)
        if statuses != {
            "provider_bound": EXPECTED_BOUND_STORAGE_SINK_COUNT,
            "storage_only": EXPECTED_STORAGE_ONLY_SINK_COUNT,
        }:
            raise FieldFateStructureError("storage sink status counts drifted")
        all_binding_ids = tuple(
            binding_id for item in self.sinks for binding_id in item.binding_ids
        )
        if len(all_binding_ids) != EXPECTED_ROUTE_FIELD_BINDING_COUNT or len(
            all_binding_ids
        ) != len(set(all_binding_ids)):
            raise FieldFateStructureError("storage sinks omit or overlap route bindings")
        for field_name in (
            "route_binding_inventory_sha256",
            "staging_route_contract_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "_by_sink_id",
            MappingProxyType({item.sink_id: item for item in self.sinks}),
        )

    @property
    def by_sink_id(self) -> Mapping[str, StorageSinkV1]:
        return self._by_sink_id

    @property
    def sinks_sha256(self) -> str:
        return canonical_sha256([item.to_dict() for item in self.sinks])

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "route_binding_inventory_sha256": self.route_binding_inventory_sha256,
            "staging_route_contract_sha256": self.staging_route_contract_sha256,
            "sinks_sha256": self.sinks_sha256,
            "summary": {
                "storage_sink_count": len(self.sinks),
                "status_counts": dict(sorted(Counter(item.status for item in self.sinks).items())),
                "schema_tier_counts": dict(
                    sorted(Counter(item.schema_tier for item in self.sinks).items())
                ),
                "storage_role_counts": dict(
                    sorted(Counter(item.storage_role for item in self.sinks).items())
                ),
            },
            "sinks": [item.to_dict() for item in self.sinks],
        }


def _validate_route_landing_arrow_schema(
    route: StagingRouteContract,
    arrow_schema: pa.Schema,
) -> tuple[RequestScopeStorageFieldV1, ...]:
    if type(arrow_schema) is not pa.Schema:
        raise FieldFateStructureError("route landing schema must be an exact Arrow schema")
    if arrow_schema.metadata is not None:
        raise FieldFateStructureError("route landing Arrow schema metadata is not canonical")
    if len(arrow_schema.names) != len(set(arrow_schema.names)):
        raise FieldFateStructureError("route landing Arrow schema has duplicate fields")
    declared_width = len(route.storage_columns)
    if tuple(arrow_schema.names[:declared_width]) != route.storage_columns:
        raise FieldFateStructureError(
            "route landing Arrow fields differ from exact storage schema order"
        )

    schema_cls = get_input_schema(route.staging_key)
    if schema_cls is None or schema_cls.__name__ != route.resolved_schema_class:
        raise FieldFateStructureError(
            "route landing schema class differs from its exact route contract"
        )
    declared_schema = schema_cls.to_schema()
    if tuple(declared_schema.columns) != route.storage_columns:
        raise FieldFateStructureError(
            "route landing declared schema differs from exact storage columns"
        )

    arrow_fields = tuple(arrow_schema)
    for arrow_field, (column_name, column) in zip(
        arrow_fields[:declared_width],
        declared_schema.columns.items(),
        strict=True,
    ):
        if arrow_field.name != column_name:
            raise FieldFateStructureError(
                "route landing Arrow field differs from exact storage ordinal"
            )
        if arrow_field.metadata is not None or not arrow_field.nullable:
            raise FieldFateStructureError(
                "route landing Arrow field metadata/nullability is not canonical"
            )
        if column.dtype is None:
            continue
        try:
            expected_type = (
                pl.Series(
                    column_name,
                    [],
                    dtype=column.dtype.type,
                )
                .to_arrow()
                .type
            )
        except Exception as exc:  # pragma: no cover - guarded by schema test census
            raise FieldFateStructureError(
                "route landing declared dtype has no exact Arrow representation"
            ) from exc
        if not arrow_field.type.equals(expected_type):
            raise FieldFateStructureError(
                "route landing Arrow logical type differs from its declared schema"
            )

    possible_scope_fields = route.request_scope_storage_fields
    scope_by_name = {item.storage_column: item for item in possible_scope_fields}
    selected_scope_fields: list[RequestScopeStorageFieldV1] = []
    previous_ordinal = -1
    for arrow_field in arrow_fields[declared_width:]:
        scope_field = scope_by_name.get(arrow_field.name)
        if scope_field is None:
            raise FieldFateStructureError(
                "route landing Arrow suffix invents a request-scope storage field"
            )
        if scope_field.field_ordinal <= previous_ordinal:
            raise FieldFateStructureError(
                "route landing request-scope storage fields are reordered"
            )
        if arrow_field.metadata is not None or not arrow_field.nullable:
            raise FieldFateStructureError(
                "route landing request-scope Arrow metadata/nullability is not canonical"
            )
        try:
            expected_type = request_scope_arrow_type(scope_field.logical_type)
        except (TypeError, ValueError) as exc:  # pragma: no cover - typed policy construction
            raise FieldFateStructureError(
                "route landing request-scope logical type authority is invalid"
            ) from exc
        if not arrow_field.type.equals(expected_type):
            raise FieldFateStructureError(
                "route landing request-scope Arrow logical type differs from authority"
            )
        selected_scope_fields.append(scope_field)
        previous_ordinal = scope_field.field_ordinal
    return tuple(selected_scope_fields)


def _validate_conditional_arrow_schema(
    authority: ConditionalRouteOccurrenceAuthorityV1,
    arrow_schema: pa.Schema,
) -> None:
    if type(arrow_schema) is not pa.Schema or arrow_schema.metadata is not None:
        raise FieldFateStructureError(
            "conditional route landing requires an exact metadata-free Arrow schema"
        )
    if tuple(arrow_schema.names) != tuple(item.storage_column for item in authority.sinks):
        raise FieldFateStructureError(
            "conditional route landing Arrow fields differ from route-local sink order"
        )
    schema_cls = get_input_schema(authority.staging_key)
    if schema_cls is None or schema_cls.__name__ != authority.schema_class:
        raise FieldFateStructureError("conditional route landing schema class drifted")
    declared = schema_cls.to_schema()
    if tuple(declared.columns) != tuple(arrow_schema.names):
        raise FieldFateStructureError("conditional route landing declared schema drifted")
    for arrow_field, (column_name, column) in zip(
        arrow_schema,
        declared.columns.items(),
        strict=True,
    ):
        if arrow_field.metadata is not None or not arrow_field.nullable:
            raise FieldFateStructureError(
                "conditional Arrow field metadata/nullability is not canonical"
            )
        if column.dtype is None:
            continue
        expected_type = pl.Series(column_name, [], dtype=column.dtype.type).to_arrow().type
        if arrow_field.name != column_name or not arrow_field.type.equals(expected_type):
            raise FieldFateStructureError(
                "conditional Arrow field differs from its declared logical type"
            )


def _decode_committed_readback(
    value: CommittedStagingFrameReadbackV2,
) -> tuple[CommittedStagingFrameReadbackV2, pl.DataFrame]:
    from nbadb.orchestrate.staging_batches import CommittedStagingFrameReadbackV2

    if type(value) is not CommittedStagingFrameReadbackV2:
        raise FieldFateStructureError("conditional authority requires the exact readback type")
    validated = CommittedStagingFrameReadbackV2(
        committed_receipt=value.committed_receipt,
        canonical_frame_format=value.canonical_frame_format,
        frame_content_hash_contract=value.frame_content_hash_contract,
        frame_schema_hash_contract=value.frame_schema_hash_contract,
        canonical_frame_bytes=value.canonical_frame_bytes,
        canonical_frame_sha256=value.canonical_frame_sha256,
        canonical_frame_size_bytes=value.canonical_frame_size_bytes,
        recomputed_frame_schema_sha256=value.recomputed_frame_schema_sha256,
        recomputed_frame_content_hash=value.recomputed_frame_content_hash,
        recomputed_persisted_content_sha256=value.recomputed_persisted_content_sha256,
        row_count=value.row_count,
        readback_receipt_sha256=value.readback_receipt_sha256,
    )
    try:
        with pa.ipc.open_stream(io.BytesIO(validated.canonical_frame_bytes)) as reader:
            frame = pl.from_arrow(reader.read_all(), rechunk=True)
    except Exception as exc:
        raise FieldFateStructureError("conditional readback Arrow bytes cannot be decoded") from exc
    if not isinstance(frame, pl.DataFrame):  # pragma: no cover - PyArrow table contract
        raise FieldFateStructureError("conditional readback did not decode to a frame")
    return validated, frame


def _stats_binding(
    *,
    route_id: str,
    staging_row_ordinal: int,
    row: dict[str, object],
    binding_kind: StatsLosslessBindingKind,
    observation_record_sha256: str,
    observation_sha256: str,
    source_occurrence_sha256: str | None,
    body_object_sha256: str | None,
) -> StatsLosslessFieldBindingV1:
    row_identity_json = canonical_json_bytes(row).decode("utf-8")
    binding_id = f"conditional_lossless_binding:{route_id}:{staging_row_ordinal:08d}:{binding_kind}"
    response_receipt_sha256 = row["response_receipt_sha256"]
    record_kind = row["record_kind"]
    if not isinstance(response_receipt_sha256, str) or not isinstance(record_kind, str):
        raise FieldFateStructureError("stats lossless row lacks exact required identity")

    def optional_text(field_name: str) -> str | None:
        value = row[field_name]
        if value is not None and not isinstance(value, str):
            raise FieldFateStructureError(f"stats lossless {field_name} has a foreign type")
        return value

    def optional_int(field_name: str) -> int | None:
        value = row[field_name]
        if value is not None and type(value) is not int:
            raise FieldFateStructureError(f"stats lossless {field_name} has a foreign type")
        return value

    selector_columns = tuple(sorted(key for key, item in row.items() if item is not None))
    evidence_values: dict[str, object] = {
        "binding_id": binding_id,
        "binding_kind": binding_kind,
        "route_id": route_id,
        "staging_key": "stg_nba_api_lossless_result_cells",
        "staging_row_ordinal": staging_row_ordinal,
        "observation_record_sha256": observation_record_sha256,
        "observation_sha256": observation_sha256,
        "source_occurrence_sha256": source_occurrence_sha256,
        "body_object_sha256": body_object_sha256,
        "response_receipt_sha256": response_receipt_sha256,
        "record_kind": record_kind,
        "result_set_name": optional_text("result_set_name"),
        "result_set_occurrence": optional_int("result_set_occurrence"),
        "provider_index": optional_int("provider_index"),
        "canonical_index": optional_int("canonical_index"),
        "header_name": optional_text("header_name"),
        "header_ordinal": optional_int("header_ordinal"),
        "row_ordinal": optional_int("row_ordinal"),
        "node_ordinal": optional_int("node_ordinal"),
        "parent_node_ordinal": optional_int("parent_node_ordinal"),
        "json_path": optional_text("json_path"),
        "parent_json_path": optional_text("parent_json_path"),
        "depth": optional_int("depth"),
        "object_key": optional_text("object_key"),
        "object_key_ordinal": optional_int("object_key_ordinal"),
        "array_ordinal": optional_int("array_ordinal"),
        "selector_columns": list(selector_columns),
        "row_identity_json": row_identity_json,
        "row_identity_sha256": canonical_sha256(row),
    }
    evidence = canonical_sha256(evidence_values)
    return StatsLosslessFieldBindingV1(
        binding_id=binding_id,
        binding_kind=binding_kind,
        route_id=route_id,
        staging_key="stg_nba_api_lossless_result_cells",
        staging_row_ordinal=staging_row_ordinal,
        observation_record_sha256=observation_record_sha256,
        observation_sha256=observation_sha256,
        source_occurrence_sha256=source_occurrence_sha256,
        body_object_sha256=body_object_sha256,
        response_receipt_sha256=response_receipt_sha256,
        record_kind=record_kind,
        result_set_name=optional_text("result_set_name"),
        result_set_occurrence=optional_int("result_set_occurrence"),
        provider_index=optional_int("provider_index"),
        canonical_index=optional_int("canonical_index"),
        header_name=optional_text("header_name"),
        header_ordinal=optional_int("header_ordinal"),
        row_ordinal=optional_int("row_ordinal"),
        node_ordinal=optional_int("node_ordinal"),
        parent_node_ordinal=optional_int("parent_node_ordinal"),
        json_path=optional_text("json_path"),
        parent_json_path=optional_text("parent_json_path"),
        depth=optional_int("depth"),
        object_key=optional_text("object_key"),
        object_key_ordinal=optional_int("object_key_ordinal"),
        array_ordinal=optional_int("array_ordinal"),
        selector_columns=selector_columns,
        row_identity_json=row_identity_json,
        row_identity_sha256=canonical_sha256(row),
        binding_evidence_sha256=evidence,
    )


def _selected_stats_binding_for_row(
    *,
    route_id: str,
    staging_row_ordinal: int,
    row: dict[str, object],
    selected: tuple[tuple[RequestObservationV2, ResultOccurrenceV2], ...],
    declared_result_indexes: Mapping[tuple[str, int], int],
) -> StatsLosslessFieldBindingV1:
    candidates: list[tuple[RequestObservationV2, ResultOccurrenceV2]] = []
    for observation, occurrence in selected:
        provider_index = row["provider_index"]
        canonical_index = row["canonical_index"]
        if provider_index is not None and occurrence.provider_result_ordinal != provider_index:
            continue
        if provider_index is None:
            result_name = row["result_set_name"]
            duplicate_ordinal = row["result_set_occurrence"]
            declared_index = (
                declared_result_indexes.get((result_name, duplicate_ordinal))
                if isinstance(result_name, str) and type(duplicate_ordinal) is int
                else None
            )
            if (
                row["record_kind"] != "missing_expected"
                or type(canonical_index) is not int
                or declared_index != canonical_index
                or occurrence.provider_result_ordinal is not None
                or occurrence.canonical_result_ordinal is not None
                or occurrence.presence != "missing"
            ):
                continue
        if row["result_set_name"] is not None and occurrence.result_name != row["result_set_name"]:
            continue
        if (
            row["result_set_occurrence"] is not None
            and occurrence.duplicate_name_ordinal != row["result_set_occurrence"]
        ):
            continue
        candidates.append((observation, occurrence))
    if len(candidates) != 1:
        raise FieldFateStructureError(
            "stats lossless staging row has ambiguous or missing result occurrence authority"
        )
    observation, occurrence = candidates[0]
    headers = occurrence.ordered_headers()
    header_ordinal = row["header_ordinal"]
    row_ordinal = row["row_ordinal"]
    if header_ordinal is not None:
        if type(header_ordinal) is not int or header_ordinal < 0:
            raise FieldFateStructureError("stats lossless header ordinal is invalid")
        if headers and (
            header_ordinal >= len(headers) or headers[header_ordinal] != row["header_name"]
        ):
            raise FieldFateStructureError("stats lossless header differs from raw authority")
    if row_ordinal is not None and (
        type(row_ordinal) is not int or row_ordinal >= occurrence.row_count
    ):
        raise FieldFateStructureError("stats lossless row ordinal exceeds raw authority")
    return _stats_binding(
        route_id=route_id,
        staging_row_ordinal=staging_row_ordinal,
        row=row,
        binding_kind="selected_result_bound",
        observation_record_sha256=observation.observation_record_sha256,
        observation_sha256=observation.attempt.observation_sha256,
        source_occurrence_sha256=occurrence.occurrence_sha256,
        body_object_sha256=None,
    )


def _declared_stats_result_indexes(endpoint_id: str) -> dict[tuple[str, int], int]:
    """Bind declared result identity without rewriting observed raw ordinals."""

    contract = pinned_runtime_contracts().get(endpoint_id)
    if contract is None:
        raise FieldFateStructureError(
            "stats lossless endpoint lacks its pinned result-set contract"
        )
    result_sets = tuple(sorted(contract.result_sets, key=lambda item: item.result_set_index))
    if tuple(item.result_set_index for item in result_sets) != tuple(range(len(result_sets))):
        raise FieldFateStructureError(
            "stats lossless pinned result-set ordinals are not contiguous"
        )
    name_occurrences: Counter[str] = Counter()
    declared: dict[tuple[str, int], int] = {}
    for result_set in result_sets:
        name = result_set.result_set_name
        if name is None:
            raise FieldFateStructureError("stats lossless pinned result-set name is absent")
        duplicate_ordinal = name_occurrences[name]
        name_occurrences[name] += 1
        key = (name, duplicate_ordinal)
        if key in declared:
            raise FieldFateStructureError("stats lossless pinned result-set identity is ambiguous")
        declared[key] = result_set.result_set_index
    return declared


def _validate_selected_stats_frame_values(
    *,
    frame: pl.DataFrame,
    bundle: RawRequestAuthorityBundleV2,
    selected: tuple[tuple[RequestObservationV2, ResultOccurrenceV2], ...],
    response_receipt_sha256: str,
) -> None:
    from nbadb.contracts.raw_request_authority import decode_parser_input_object
    from nbadb.extract.nba_api_adapter import (
        ResponseContractError,
        rederive_raw_authority_stats_fallback,
        rederive_raw_authority_unknown_stats_response,
    )
    from nbadb.extract.stats_lossless import build_unknown_stats_lossless_fallback

    observations = {
        observation.attempt.observation_sha256: observation for observation, _item in selected
    }
    if len(observations) != 1:
        raise FieldFateStructureError(
            "stats lossless frame spans multiple selected raw observations"
        )
    observation = next(iter(observations.values()))
    body = next(
        (item for item in bundle.objects if item.object_sha256 == observation.body_object_sha256),
        None,
    )
    if body is None:
        raise FieldFateStructureError("selected stats observation lacks parser-input authority")
    try:
        contract = pinned_runtime_contracts()[observation.attempt.endpoint_id]
        if contract.response_mode == "unknown_dynamic_response":
            unknown = rederive_raw_authority_unknown_stats_response(
                endpoint_id=observation.attempt.endpoint_id,
                parser_input=decode_parser_input_object(body),
                safe_parameters_json=observation.attempt.safe_parameters_json,
                provider_authority_sha256=observation.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=(observation.attempt.endpoint_contract_sha256),
            ).bind_response_receipt(response_receipt_sha256)
            expected = build_unknown_stats_lossless_fallback(
                unknown,
                expected_response_receipt_sha256=response_receipt_sha256,
                expected_parameters_sha256=unknown.parameters_sha256,
                expected_parser_input_sha256=body.response_sha256,
            )
            if expected is None:
                raise ResponseContractError(
                    "selected unknown stats response has no observed lossless drift"
                )
        else:
            expected = rederive_raw_authority_stats_fallback(
                endpoint_id=observation.attempt.endpoint_id,
                parser_input=decode_parser_input_object(body),
                provider_authority_sha256=observation.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=(observation.attempt.endpoint_contract_sha256),
            ).bind_response_receipt(response_receipt_sha256)
    except (ResponseContractError, TypeError, ValueError) as exc:
        raise FieldFateStructureError(
            "selected stats parser input cannot rederive its exact fallback frame"
        ) from exc
    expected_frame = expected.frame
    if (
        frame.columns != expected_frame.columns
        or dict(frame.schema) != dict(expected_frame.schema)
        or not frame.equals(expected_frame)
    ):
        raise FieldFateStructureError(
            "stats lossless committed frame differs from exact raw fallback replay"
        )


def _validate_selected_result_raw_values(
    *,
    bundle: RawRequestAuthorityBundleV2,
    selected: tuple[tuple[RequestObservationV2, ResultOccurrenceV2], ...],
) -> None:
    """Reparse exact stats/live bodies and bind every declared result denominator."""

    from nbadb.contracts.raw_request_authority import decode_parser_input_object
    from nbadb.extract.nba_api_adapter import (
        ResponseContractError,
        rederive_raw_authority_result_sets,
        rederive_raw_authority_unknown_stats_response,
    )

    objects_by_sha = {item.object_sha256: item for item in bundle.objects}
    observations = {
        observation.attempt.observation_sha256: observation for observation, _item in selected
    }
    for observation_sha256, observation in observations.items():
        body = (
            objects_by_sha.get(observation.body_object_sha256)
            if observation.body_object_sha256 is not None
            else None
        )
        if body is None:
            raise FieldFateStructureError(
                "selected result observation lacks parser-input authority"
            )
        try:
            contract = pinned_runtime_contracts().get(observation.attempt.endpoint_id)
            if (
                observation.attempt.source_family == "stats"
                and contract is not None
                and contract.response_mode == "unknown_dynamic_response"
            ):
                unknown = rederive_raw_authority_unknown_stats_response(
                    endpoint_id=observation.attempt.endpoint_id,
                    parser_input=decode_parser_input_object(body),
                    safe_parameters_json=observation.attempt.safe_parameters_json,
                    provider_authority_sha256=(observation.attempt.provider_authority_sha256),
                    endpoint_contract_sha256_value=(observation.attempt.endpoint_contract_sha256),
                )
                duplicate_names: Counter[str] = Counter()
                unknown_derivations = []
                for item in unknown.occurrences:
                    duplicate_ordinal = duplicate_names[item.name]
                    duplicate_names[item.name] += 1
                    unknown_derivations.append((item.receipt, item.headers, duplicate_ordinal))
                derivations = tuple(unknown_derivations)
            else:
                declared_derivations = rederive_raw_authority_result_sets(
                    source_family=observation.attempt.source_family,
                    endpoint_id=observation.attempt.endpoint_id,
                    parser_input=decode_parser_input_object(body),
                    provider_authority_sha256=(observation.attempt.provider_authority_sha256),
                    endpoint_contract_sha256_value=(observation.attempt.endpoint_contract_sha256),
                )
                derivations = tuple(
                    (
                        item.result_set,
                        item.ordered_headers,
                        item.duplicate_name_ordinal,
                    )
                    for item in declared_derivations
                )
        except (ResponseContractError, TypeError, ValueError) as exc:
            raise FieldFateStructureError(
                "selected result parser input cannot rederive result authority"
            ) from exc
        declared = tuple(
            sorted(
                (
                    item
                    for item in bundle.occurrences
                    if item.observation_sha256 == observation_sha256
                ),
                key=lambda item: item.occurrence_ordinal,
            )
        )
        if len(declared) != len(derivations) or tuple(
            item.occurrence_ordinal for item in declared
        ) != tuple(range(len(derivations))):
            raise FieldFateStructureError("selected result denominator differs from parser input")
        for occurrence, (result, ordered_headers, duplicate_name_ordinal) in zip(
            declared,
            derivations,
            strict=True,
        ):
            present_containers = result.container_count
            missing_count = result.missing_count
            null_count = result.null_count
            if present_containers == 0:
                if result.parent_observation_count == 0:
                    expected_presence = "not_observed_parent_empty"
                    expected_headers = ordered_headers
                    expected_row_count = expected_cell_count = expected_node_count = 0
                    expected_container_count = expected_missing_count = expected_null_count = 0
                elif missing_count > 0 and null_count == 0:
                    expected_presence = "missing"
                    expected_headers = ()
                    expected_row_count = expected_cell_count = expected_node_count = 0
                    expected_container_count = 0
                    expected_missing_count = missing_count
                    expected_null_count = 0
                elif null_count > 0 and missing_count == 0:
                    expected_presence = "null"
                    expected_headers = ()
                    expected_row_count = expected_cell_count = 0
                    expected_node_count = expected_container_count = null_count
                    expected_missing_count = 0
                    expected_null_count = null_count
                elif missing_count > 0 and null_count > 0:
                    expected_presence = "mixed_absent"
                    expected_headers = ()
                    expected_row_count = expected_cell_count = 0
                    expected_node_count = expected_container_count = null_count
                    expected_missing_count = missing_count
                    expected_null_count = null_count
                else:
                    raise FieldFateStructureError(
                        "selected result has no unique rederived absence state"
                    )
            elif result.row_count > 0:
                expected_presence = "present"
                expected_headers = ordered_headers
                expected_row_count = result.row_count
                expected_cell_count = result.row_count * len(expected_headers)
                expected_node_count = (
                    0 if result.container_kind == "nba_api_result_set" else result.row_count
                )
                expected_container_count = present_containers + null_count
                expected_missing_count = missing_count
                expected_null_count = null_count
            elif result.container_kind == "nba_api_result_set":
                expected_presence = "present_empty"
                expected_headers = ordered_headers
                expected_row_count = expected_cell_count = expected_node_count = 0
                expected_container_count = present_containers + null_count
                expected_missing_count = missing_count
                expected_null_count = null_count
            elif (
                result.container_kind in {"nba_api_live_json_array", "nba_api_static_records"}
                and present_containers == 1
                and missing_count == 0
                and null_count == 0
            ):
                expected_presence = "empty_array"
                expected_headers = ()
                expected_row_count = expected_cell_count = 0
                expected_node_count = expected_container_count = 1
                expected_missing_count = expected_null_count = 0
            else:
                expected_presence = "present"
                expected_headers = ordered_headers
                expected_row_count = expected_cell_count = 0
                expected_node_count = present_containers
                expected_container_count = present_containers + null_count
                expected_missing_count = missing_count
                expected_null_count = null_count
            if (
                result.name != occurrence.result_name
                or duplicate_name_ordinal != occurrence.duplicate_name_ordinal
                or result.provider_index != occurrence.provider_result_ordinal
                or result.canonical_index != occurrence.canonical_result_ordinal
                or result.json_path != occurrence.json_path
                or result.container_kind != occurrence.container_kind
                or expected_presence != occurrence.presence
                or expected_headers != occurrence.ordered_headers()
                or expected_row_count != occurrence.row_count
                or expected_cell_count != occurrence.cell_count
                or expected_node_count != occurrence.node_count
                or expected_container_count != occurrence.container_count
                or expected_missing_count != occurrence.missing_count
                or expected_null_count != occurrence.null_count
                or result.parent_occurrence_states_sha256 != occurrence.parent_state_sha256
                or result.normalized_output_sha256 != occurrence.output_sha256
            ):
                raise FieldFateStructureError(
                    "selected result authority differs from exact parser input"
                )


def _authority_identity_payload(values: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "conditional_route_occurrence_authority",
        "route_id": values["route_id"],
        "route_local_ordinal": values["route_local_ordinal"],
        "endpoint_name": values["endpoint_name"],
        "source_family": values["source_family"],
        "source_shape": values["source_shape"],
        "staging_key": values["staging_key"],
        "schema_tier": values["schema_tier"],
        "schema_table": values["schema_table"],
        "schema_class": values["schema_class"],
        "storage_role": values["storage_role"],
        "route_admission_sha256": values["route_admission_sha256"],
        "field_fate_structure_sha256": values["field_fate_structure_sha256"],
        "provider_authority_sha256": values["provider_authority_sha256"],
        "endpoint_contract_sha256": values["endpoint_contract_sha256"],
        "committed_logical_parameters_sha256": values["committed_logical_parameters_sha256"],
        "source_parameters_sha256s": list(
            cast("tuple[str, ...]", values["source_parameters_sha256s"])
        ),
        "staging_parameters_sha256": values["staging_parameters_sha256"],
        "raw_bundle_sha256": values["raw_bundle_sha256"],
        "readback_receipt_sha256": values["readback_receipt_sha256"],
        "committed_receipt_root_sha256": values["committed_receipt_root_sha256"],
        "response_receipt_sha256": values["response_receipt_sha256"],
        "observation_record_sha256s": list(
            cast("tuple[str, ...]", values["observation_record_sha256s"])
        ),
        "result_occurrence_sha256s": list(
            cast("tuple[str, ...]", values["result_occurrence_sha256s"])
        ),
        "body_object_sha256s": list(cast("tuple[str, ...]", values["body_object_sha256s"])),
        "stats_bindings": [
            item.to_dict()
            for item in cast("tuple[StatsLosslessFieldBindingV1, ...]", values["stats_bindings"])
        ],
        "live_binding_ids": list(cast("tuple[str, ...]", values["live_binding_ids"])),
        "sinks": [item.to_dict() for item in cast("tuple[StorageSinkV1, ...]", values["sinks"])],
    }


def derive_conditional_route_occurrence_authority(
    *,
    structure: FieldFateStructureV1,
    route_id: str,
    raw_bundle: RawRequestAuthorityBundleV2,
    readback: CommittedStagingFrameReadbackV2,
) -> ConditionalRouteOccurrenceAuthorityV1:
    """Derive one conditional route solely from exact raw and committed authorities."""

    from nbadb.contracts.raw_request_authority import (
        BODYLESS_RESULT_OCCURRENCES_SHA256,
        RawRequestAuthorityError,
        decode_parser_input_object,
        validate_raw_request_authority_bundle,
    )
    from nbadb.extract.live_lossless import (
        reconstruct_live_payload,
        validate_live_lossless_frame,
    )
    from nbadb.extract.nba_api_adapter import (
        ResponseContractError,
        rederive_raw_authority_unknown_stats_response,
        validate_lossless_fallback_frame,
    )
    from nbadb.extract.stats_lossless import (
        build_unknown_stats_lossless_fallback,
        validate_unknown_stats_lossless_frame,
    )

    if not isinstance(structure, FieldFateStructureV1):
        raise FieldFateStructureError("conditional authority has a foreign field-fate root")
    if structure is not compile_field_fate_structure():
        validate_field_fate_structure(structure)
    _token(route_id, field_name="conditional route_id")
    staging_key = conditional_staging_key_from_route_id(route_id)
    if staging_key is None:
        raise FieldFateStructureError("conditional authority route is not a known conditional")
    try:
        bundle = validate_raw_request_authority_bundle(raw_bundle)
        validated_readback, frame = _decode_committed_readback(readback)
    except Exception as exc:
        raise FieldFateStructureError(
            "conditional source authority failed strict validation"
        ) from exc
    receipt = validated_readback.committed_receipt
    if receipt.result_route_id != route_id or receipt.staging_key != staging_key:
        raise FieldFateStructureError("conditional readback names a foreign route")
    if frame.height <= 0 or frame.height != receipt.persisted_row_count:
        raise FieldFateStructureError("conditional readback lacks an observed staging row")
    observed_response_receipts = frame.get_column("response_receipt_sha256").to_list()
    if any(not isinstance(item, str) for item in observed_response_receipts):
        raise FieldFateStructureError("conditional frame lacks an exact response receipt")
    response_receipts = tuple(sorted(set(observed_response_receipts)))
    if len(response_receipts) != 1:
        raise FieldFateStructureError("conditional frame mixes response receipts")
    response_receipt_sha256 = _sha256(
        response_receipts[0], field_name="conditional response receipt"
    )

    routes = staging_route_contract_bundle()
    endpoint_name = route_id.rsplit(":", 2)[0]
    try:
        selected = bundle.selected_terminal_occurrences_for_route(
            route_id,
            receipt.receipt_root_sha256,
        )
    except RawRequestAuthorityError as exc:
        raise FieldFateStructureError("conditional selected route authority is invalid") from exc
    registry_static_route_ids = tuple(
        route.route_id
        for route in routes.routes
        if route.endpoint_name == endpoint_name
        and route.source_family == "stats"
        and route.staging_key != staging_key
    )
    registry_endpoint_ids = {
        routes.by_route_id[item].provider_endpoint_id for item in registry_static_route_ids
    }
    unknown_stats_response = False
    if len(registry_endpoint_ids) == 1:
        registry_contract = pinned_runtime_contracts().get(next(iter(registry_endpoint_ids)))
        unknown_stats_response = (
            registry_contract is not None
            and registry_contract.response_mode == "unknown_dynamic_response"
        )
    if selected and unknown_stats_response:
        for _observation, occurrence in selected:
            try:
                occurrence_route_ids = occurrence.canonical_route_ids()
                occurrence_receipts = occurrence.committed_staging_receipts_by_route()
            except RawRequestAuthorityError as exc:
                raise FieldFateStructureError(
                    "unknown stats occurrence route authority is invalid"
                ) from exc
            if (
                occurrence_route_ids != (route_id,)
                or tuple(occurrence_receipts) != (route_id,)
                or occurrence_receipts[route_id] != receipt.receipt_root_sha256
                or occurrence.landing_disposition != "lossless_only"
            ):
                raise FieldFateStructureError(
                    "unknown stats occurrence route membership differs from response-level policy"
                )
        static_route_ids = registry_static_route_ids
    elif selected:
        static_route_ids = tuple(
            sorted(
                {
                    candidate
                    for _observation, occurrence in selected
                    for candidate in occurrence.canonical_route_ids()
                    if candidate != route_id and candidate in routes.by_route_id
                }
            )
        )
    else:
        static_route_ids = ()
    if not static_route_ids:
        static_route_ids = registry_static_route_ids
    if not static_route_ids:
        raise FieldFateStructureError("conditional route lacks exact static route authority")
    try:
        admission: KnownConditionalStagingRouteAdmission = admit_known_conditional_staging_route(
            endpoint_name=endpoint_name,
            static_route_ids=static_route_ids,
            conditional_route_ids=(route_id,),
            provider_authority_sha256=receipt.provider_authority_sha256,
        )
    except ValueError as exc:
        raise FieldFateStructureError(
            "conditional route admission cannot be reconstructed"
        ) from exc
    if tuple(frame.columns) != admission.storage_columns:
        raise FieldFateStructureError("conditional readback columns differ from admission")
    schema_cls = get_input_schema(staging_key)
    if schema_cls is None:
        raise FieldFateStructureError("conditional route schema is unavailable")
    try:
        checked = schema_cls.validate(frame)
    except Exception as exc:
        raise FieldFateStructureError("conditional frame fails its staging schema") from exc
    if (
        not isinstance(checked, pl.DataFrame)
        or checked.columns != frame.columns
        or dict(checked.schema) != dict(frame.schema)
    ):
        raise FieldFateStructureError("conditional schema validation changed the frame")
    staging_parameters_sha256: str | None = None
    if "parameters_sha256" in frame.columns:
        staging_parameter_values = {
            item for item in frame.get_column("parameters_sha256").to_list() if item is not None
        }
        if len(staging_parameter_values) > 1 or any(
            not isinstance(item, str) for item in staging_parameter_values
        ):
            raise FieldFateStructureError("conditional frame mixes staging parameter identities")
        if staging_parameter_values:
            staging_parameters_sha256 = _sha256(
                next(iter(staging_parameter_values)),
                field_name="staging_parameters_sha256",
            )

    static_routes = tuple(routes.by_route_id[item] for item in static_route_ids)
    endpoint_ids = {item.provider_endpoint_id for item in static_routes}
    if len(endpoint_ids) != 1:
        raise FieldFateStructureError("conditional static routes span endpoint identities")
    endpoint_id = next(iter(endpoint_ids))
    stats_bindings: tuple[StatsLosslessFieldBindingV1, ...] = ()
    live_binding_ids: tuple[str, ...] = ()
    body_objects: tuple[str, ...] = ()
    observation_records: tuple[str, ...]
    occurrence_hashes: tuple[str, ...]
    if selected:
        selected_observations = {item[0].attempt.observation_sha256: item[0] for item in selected}
        if any(
            observation.attempt.endpoint_id != endpoint_id
            or observation.attempt.source_family != static_routes[0].source_family
            or observation.attempt.provider_authority_sha256 != receipt.provider_authority_sha256
            or observation.attempt.endpoint_contract_sha256
            != static_routes[0].endpoint_contract_sha256
            or observation.logical_receipt_sha256 != receipt.logical_call_receipt_sha256
            for observation in selected_observations.values()
        ):
            raise FieldFateStructureError("conditional selection differs from committed receipt")
        if any(
            observation.capture_response_receipt_sha256 != response_receipt_sha256
            for observation in selected_observations.values()
        ):
            raise FieldFateStructureError(
                "conditional selected response receipt differs from raw capture"
            )
        observation_records = tuple(
            sorted(item.observation_record_sha256 for item in selected_observations.values())
        )
        occurrence_hashes = tuple(sorted(item[1].occurrence_sha256 for item in selected))
        source_parameters_sha256s = tuple(
            sorted(
                {
                    observation.attempt.safe_parameters_sha256
                    for observation in selected_observations.values()
                }
            )
        )
        if staging_key == "stg_nba_api_lossless_result_cells":
            declared_result_indexes = _declared_stats_result_indexes(endpoint_id)
            validate_lossless_fallback_frame(
                frame,
                expected_response_receipt_sha256=response_receipt_sha256,
            )
            _validate_selected_result_raw_values(bundle=bundle, selected=selected)
            _validate_selected_stats_frame_values(
                frame=frame,
                bundle=bundle,
                selected=selected,
                response_receipt_sha256=response_receipt_sha256,
            )
            stats_contract = pinned_runtime_contracts()[endpoint_id]
            if stats_contract.response_mode == "unknown_dynamic_response":
                if len(selected_observations) != 1:
                    raise FieldFateStructureError(
                        "unknown stats conditional frame spans multiple observations"
                    )
                selected_observation = next(iter(selected_observations.values()))
                body = next(
                    (
                        item
                        for item in bundle.objects
                        if item.object_sha256 == selected_observation.body_object_sha256
                    ),
                    None,
                )
                if body is None:
                    raise FieldFateStructureError(
                        "unknown stats conditional selection lacks its exact body"
                    )
                body_objects = (body.object_sha256,)
                hybrid_bindings: list[StatsLosslessFieldBindingV1] = []
                for ordinal, row in enumerate(frame.to_dicts()):
                    if row["record_kind"] in {"response", "json_node"}:
                        hybrid_bindings.append(
                            _stats_binding(
                                route_id=route_id,
                                staging_row_ordinal=ordinal,
                                row=row,
                                binding_kind="body_node_bound",
                                observation_record_sha256=(
                                    selected_observation.observation_record_sha256
                                ),
                                observation_sha256=(
                                    selected_observation.attempt.observation_sha256
                                ),
                                source_occurrence_sha256=None,
                                body_object_sha256=body.object_sha256,
                            )
                        )
                    else:
                        hybrid_bindings.append(
                            _selected_stats_binding_for_row(
                                route_id=route_id,
                                staging_row_ordinal=ordinal,
                                row=row,
                                selected=selected,
                                declared_result_indexes=declared_result_indexes,
                            )
                        )
                stats_bindings = tuple(sorted(hybrid_bindings, key=lambda item: item.binding_id))
                source_shape: ConditionalRouteSourceShape = "hybrid_result_body_bound"
            else:
                stats_bindings = tuple(
                    sorted(
                        (
                            _selected_stats_binding_for_row(
                                route_id=route_id,
                                staging_row_ordinal=ordinal,
                                row=row,
                                selected=selected,
                                declared_result_indexes=declared_result_indexes,
                            )
                            for ordinal, row in enumerate(frame.to_dicts())
                        ),
                        key=lambda item: item.binding_id,
                    )
                )
                source_shape = "selected_result_bound"
            source_family: Literal["stats", "live"] = "stats"
        else:
            from nbadb.contracts.staging_route_contract import (
                ConditionalLiveStagingRouteAdmission,
            )

            if not isinstance(admission, ConditionalLiveStagingRouteAdmission):
                raise FieldFateStructureError("live conditional admission has a foreign type")
            if len(selected_observations) != 1:
                raise FieldFateStructureError(
                    "live conditional frame has ambiguous result observation multiplicity"
                )
            live_observation = next(iter(selected_observations.values()))
            selected_route_landings = tuple(
                landing
                for landing in bundle.landings
                if landing.observation_sha256 == live_observation.attempt.observation_sha256
                and landing.route_id == route_id
                and landing.receipt_root_sha256 == receipt.receipt_root_sha256
                and landing.landing_semantic == "conditional_lossless"
            )
            if len(selected_route_landings) != 1:
                raise FieldFateStructureError(
                    "live conditional route lacks one exact selected landing"
                )
            selected_route_landing = selected_route_landings[0]
            snapshot_values = frame.get_column("snapshot_at").unique().to_list()
            if len(snapshot_values) != 1 or snapshot_values[0] is None:
                raise FieldFateStructureError("live conditional frame has ambiguous snapshot")
            frame_snapshot_at = snapshot_values[0]
            landing_snapshot_at = selected_route_landing.live_snapshot_at
            if (
                not isinstance(frame_snapshot_at, datetime)
                or frame_snapshot_at.tzinfo is None
                or frame_snapshot_at.utcoffset() != UTC.utcoffset(frame_snapshot_at)
                or landing_snapshot_at is None
                or landing_snapshot_at.tzinfo is None
                or landing_snapshot_at.utcoffset() != UTC.utcoffset(landing_snapshot_at)
                or frame_snapshot_at != landing_snapshot_at
            ):
                raise FieldFateStructureError(
                    "live conditional frame snapshot differs from selected route landing"
                )
            validate_live_lossless_frame(
                frame,
                expected_response_receipt_sha256=response_receipt_sha256,
                expected_result_set_count=admission.result_set_index,
                expected_snapshot_at=frame_snapshot_at,
                expected_endpoint_id=endpoint_id,
                expected_endpoint_slug=admission.provider_endpoint_slug,
            )
            request_parameter_values = (
                frame.get_column("request_parameters_json").unique().to_list()
            )
            if (
                len(request_parameter_values) != 1
                or not isinstance(request_parameter_values[0], str)
                or admission.logical_parameters_sha256(request_parameter_values[0])
                != receipt.logical_parameters_sha256
            ):
                raise FieldFateStructureError(
                    "live conditional frame differs from committed logical parameters"
                )
            _validate_selected_result_raw_values(bundle=bundle, selected=selected)
            live_body = next(
                (
                    item
                    for item in bundle.objects
                    if item.object_sha256 == live_observation.body_object_sha256
                ),
                None,
            )
            if live_body is None:
                raise FieldFateStructureError("live conditional selection lacks its exact body")
            try:
                raw_payload = json.loads(decode_parser_input_object(live_body))
            except Exception as exc:
                raise FieldFateStructureError(
                    "live conditional raw body cannot be reconstructed"
                ) from exc
            if raw_payload != reconstruct_live_payload(frame):
                raise FieldFateStructureError(
                    "live conditional node frame differs from its raw body"
                )
            selected_result_keys = {
                (item[1].result_name, item[1].provider_result_ordinal) for item in selected
            } | {(item[1].result_name, item[1].canonical_result_ordinal) for item in selected}
            applicable = tuple(
                item
                for item in structure.lossless_bindings
                if item.endpoint_id == endpoint_id
                and (item.result_set_name, item.result_set_ordinal) in selected_result_keys
            )
            if not applicable:
                raise FieldFateStructureError("live conditional route has no exact field bindings")
            live_binding_ids = tuple(sorted(item.binding_id for item in applicable))
            source_family = "live"
            source_shape = "live_lossless_bound"
    else:
        if staging_key != "stg_nba_api_lossless_result_cells":
            raise FieldFateStructureError("live conditional route lacks terminal selection")
        validate_unknown_stats_lossless_frame(
            frame,
            expected_response_receipt_sha256=response_receipt_sha256,
        )
        parser_sha_values = frame.get_column("parser_input_sha256").unique().to_list()
        if len(parser_sha_values) != 1 or not isinstance(parser_sha_values[0], str):
            raise FieldFateStructureError("body-node frame lacks one parser-input identity")
        parser_sha256 = _sha256(parser_sha_values[0], field_name="parser_input_sha256")
        route_landings = tuple(
            landing
            for landing in bundle.landings
            if landing.route_id == route_id
            and landing.receipt_root_sha256 == receipt.receipt_root_sha256
            and landing.landing_semantic == "conditional_lossless"
            and landing.source_occurrence_count == 0
            and landing.source_occurrences_sha256 == BODYLESS_RESULT_OCCURRENCES_SHA256
        )
        if len(route_landings) != 1:
            raise FieldFateStructureError("conditional body-node route lacks one terminal landing")
        route_landing = route_landings[0]
        observations_by_sha = {
            item.attempt.observation_sha256: item for item in bundle.observations
        }
        observation = observations_by_sha.get(route_landing.observation_sha256)
        objects_by_sha = {item.object_sha256: item for item in bundle.objects}
        body = (
            objects_by_sha.get(observation.body_object_sha256)
            if observation is not None and observation.body_object_sha256 is not None
            else None
        )
        if (
            observation is None
            or observation.lifecycle != "selected_terminal"
            or observation.attempt.source_family != "stats"
            or observation.attempt.endpoint_id != endpoint_id
            or observation.attempt.provider_authority_sha256 != receipt.provider_authority_sha256
            or observation.attempt.endpoint_contract_sha256
            != static_routes[0].endpoint_contract_sha256
            or body is None
            or body.response_sha256 != parser_sha256
        ):
            raise FieldFateStructureError(
                "conditional body-node route has ambiguous or missing raw observation"
            )
        if (
            observation.result_occurrence_count != 0
            or observation.result_occurrences_sha256 != BODYLESS_RESULT_OCCURRENCES_SHA256
            or any(
                occurrence.observation_sha256 == observation.attempt.observation_sha256
                for occurrence in bundle.occurrences
            )
        ):
            raise FieldFateStructureError(
                "conditional body-node raw observation cannot carry result occurrence authority"
            )
        if observation.capture_response_receipt_sha256 != response_receipt_sha256:
            raise FieldFateStructureError(
                "conditional body-node response receipt differs from raw capture"
            )
        if (
            observation.logical_receipt_sha256 != receipt.logical_call_receipt_sha256
            or observation.attempt.safe_parameters_sha256 != receipt.logical_parameters_sha256
        ):
            raise FieldFateStructureError(
                "conditional body-node observation differs from committed logical authority"
            )
        try:
            parser_input = decode_parser_input_object(body)
            unknown = rederive_raw_authority_unknown_stats_response(
                endpoint_id=observation.attempt.endpoint_id,
                parser_input=parser_input,
                safe_parameters_json=observation.attempt.safe_parameters_json,
                provider_authority_sha256=observation.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=(observation.attempt.endpoint_contract_sha256),
            )
            if staging_parameters_sha256 != unknown.parameters_sha256:
                raise FieldFateStructureError(
                    "conditional body-node parameters differ from raw request authority"
                )
            if unknown.occurrences:
                raise FieldFateStructureError(
                    "conditional body-node raw observation hides named result occurrences"
                )
            expected = build_unknown_stats_lossless_fallback(
                unknown.bind_response_receipt(response_receipt_sha256),
                expected_response_receipt_sha256=response_receipt_sha256,
                expected_parameters_sha256=unknown.parameters_sha256,
                expected_parser_input_sha256=body.response_sha256,
            )
            if expected is None:
                raise ResponseContractError(
                    "conditional body-node raw response has no lossless projection"
                )
        except FieldFateStructureError:
            raise
        except (ResponseContractError, TypeError, ValueError) as exc:
            raise FieldFateStructureError(
                "conditional body-node raw response cannot be exactly reconstructed"
            ) from exc
        expected_frame = expected.frame
        if (
            frame.columns != expected_frame.columns
            or dict(frame.schema) != dict(expected_frame.schema)
            or not frame.equals(expected_frame)
        ):
            raise FieldFateStructureError(
                "conditional body-node frame differs from exact raw fallback replay"
            )
        observation_records = (observation.observation_record_sha256,)
        occurrence_hashes = ()
        body_objects = (body.object_sha256,)
        stats_bindings = tuple(
            _stats_binding(
                route_id=route_id,
                staging_row_ordinal=ordinal,
                row=row,
                binding_kind="body_node_bound",
                observation_record_sha256=observation.observation_record_sha256,
                observation_sha256=observation.attempt.observation_sha256,
                source_occurrence_sha256=None,
                body_object_sha256=body.object_sha256,
            )
            for ordinal, row in enumerate(frame.to_dicts())
        )
        source_family = "stats"
        source_shape = "body_node_bound"
        source_parameters_sha256s = (observation.attempt.safe_parameters_sha256,)

    bindings_by_column: defaultdict[str, list[str]] = defaultdict(list)
    if source_family == "stats":
        for binding in stats_bindings:
            for column_name in binding.selector_columns:
                bindings_by_column[column_name].append(binding.binding_id)
    else:
        binding_by_id = {item.binding_id: item for item in structure.lossless_bindings}
        for binding_id in live_binding_ids:
            binding = binding_by_id[binding_id]
            for column_name in binding.selector_columns:
                bindings_by_column[column_name].append(binding_id)
    sinks = tuple(
        StorageSinkV1(
            sink_id=_storage_sink_id(route_id, ordinal),
            route_id=route_id,
            route_ordinal=admission.result_set_index,
            storage_ordinal=ordinal,
            staging_key=staging_key,
            schema_tier="staging",
            schema_table=staging_key,
            schema_class=schema_cls.__name__,
            storage_role="conditional_lossless",
            storage_role_target=None,
            storage_column=column_name,
            route_contract_sha256=admission.contract_sha256,
            binding_ids=tuple(sorted(set(bindings_by_column[column_name]))),
            status=("provider_bound" if bindings_by_column[column_name] else "storage_only"),
        )
        for ordinal, column_name in enumerate(admission.storage_columns)
    )
    values: dict[str, object] = {
        "route_id": route_id,
        "route_local_ordinal": admission.result_set_index,
        "endpoint_name": endpoint_name,
        "source_family": source_family,
        "source_shape": source_shape,
        "staging_key": staging_key,
        "schema_tier": "staging",
        "schema_table": staging_key,
        "schema_class": schema_cls.__name__,
        "storage_role": "conditional_lossless",
        "route_admission_sha256": admission.contract_sha256,
        "field_fate_structure_sha256": structure.identity_sha256,
        "provider_authority_sha256": receipt.provider_authority_sha256,
        "endpoint_contract_sha256": admission.endpoint_contract_sha256,
        "committed_logical_parameters_sha256": receipt.logical_parameters_sha256,
        "source_parameters_sha256s": source_parameters_sha256s,
        "staging_parameters_sha256": staging_parameters_sha256,
        "raw_bundle_sha256": bundle.bundle_sha256,
        "readback_receipt_sha256": validated_readback.readback_receipt_sha256,
        "committed_receipt_root_sha256": receipt.receipt_root_sha256,
        "response_receipt_sha256": response_receipt_sha256,
        "observation_record_sha256s": tuple(sorted(observation_records)),
        "result_occurrence_sha256s": tuple(sorted(occurrence_hashes)),
        "body_object_sha256s": tuple(sorted(body_objects)),
        "stats_bindings": stats_bindings,
        "live_binding_ids": live_binding_ids,
        "sinks": sinks,
    }
    return ConditionalRouteOccurrenceAuthorityV1(
        **values,  # type: ignore[arg-type]
        authority_sha256=canonical_sha256(_authority_identity_payload(values)),
        raw_bundle=bundle,
        readback=validated_readback,
    )


def validate_conditional_route_occurrence_authority(
    value: object,
    *,
    structure: FieldFateStructureV1,
) -> ConditionalRouteOccurrenceAuthorityV1:
    """Strictly rebuild a conditional authority from its embedded exact roots."""

    if type(value) is not ConditionalRouteOccurrenceAuthorityV1:
        raise FieldFateStructureError("conditional route authority has a foreign type")
    expected = derive_conditional_route_occurrence_authority(
        structure=structure,
        route_id=value.route_id,
        raw_bundle=value.raw_bundle,
        readback=value.readback,
    )
    if value.to_dict() != expected.to_dict():
        raise FieldFateStructureError("conditional route authority differs from exact sources")
    return value


def _conditional_route_landing_fields(
    structure: FieldFateStructureV1,
    *,
    route_id: str,
    arrow_schema: pa.Schema,
    authority: ConditionalRouteOccurrenceAuthorityV1,
) -> tuple[RouteLandingFieldJoinV1, ...]:
    validated = validate_conditional_route_occurrence_authority(
        authority,
        structure=structure,
    )
    if validated.route_id != route_id:
        raise FieldFateStructureError("conditional route authority names a foreign route")
    _validate_conditional_arrow_schema(validated, arrow_schema)
    stats_by_id = {item.binding_id: item for item in validated.stats_bindings}
    live_by_id = {item.binding_id: item for item in structure.lossless_bindings}
    source_by_id = structure.provider_sources.by_occurrence_id
    joined: list[RouteLandingFieldJoinV1] = []
    for storage_ordinal, (sink, arrow_field) in enumerate(
        zip(validated.sinks, arrow_schema, strict=True)
    ):
        if (
            sink.route_id != route_id
            or sink.route_ordinal != validated.route_local_ordinal
            or sink.storage_ordinal != storage_ordinal
            or sink.storage_column != arrow_field.name
            or sink.route_contract_sha256 != validated.route_admission_sha256
        ):
            raise FieldFateStructureError(
                "conditional route-local sink differs from exact field ordinal"
            )
        if validated.source_family == "stats":
            bindings: tuple[LosslessFieldBindingV1 | StatsLosslessFieldBindingV1, ...] = tuple(
                stats_by_id[item] for item in sink.binding_ids
            )
            sources: tuple[ProviderFieldSourceOccurrenceV1, ...] = ()
        else:
            bindings = tuple(live_by_id[item] for item in sink.binding_ids)
            sources = tuple(source_by_id[item.source_occurrence_id] for item in bindings)
        if not bindings:
            if sink.status != "storage_only" or sink.binding_ids:
                raise FieldFateStructureError(
                    "conditional storage-only sink invents binding membership"
                )
            origin: RouteLandingFieldOrigin = "storage_only"
        else:
            if (
                sink.status != "provider_bound"
                or tuple(item.binding_id for item in bindings) != sink.binding_ids
            ):
                raise FieldFateStructureError(
                    "conditional lossless sink drops or invents binding membership"
                )
            origin = "lossless_bound"
        joined.append(
            RouteLandingFieldJoinV1(
                sink=sink,
                route_bindings=(),
                provider_sources=sources,
                lossless_bindings=bindings,
                origin=origin,
            )
        )
    return tuple(joined)


@dataclass(frozen=True, slots=True)
class FieldFateStructureV1:
    """Joined structural authority; never a semantic or MODEL-GREEN receipt."""

    provider_sources: ProviderFieldSourceInventoryV1
    route_bindings: RouteFieldBindingInventoryV1
    storage_sinks: StorageSinkInventoryV1
    lossless_bindings: tuple[LosslessFieldBindingV1, ...]
    blockers: tuple[FieldFateStructureBlockerV1, ...]

    schema_version: ClassVar[int] = 3
    kind: ClassVar[str] = "field_fate_structure"

    def __post_init__(self) -> None:
        if not isinstance(self.provider_sources, ProviderFieldSourceInventoryV1):
            raise FieldFateStructureError("provider_sources has a foreign concrete type")
        if not isinstance(self.route_bindings, RouteFieldBindingInventoryV1):
            raise FieldFateStructureError("route_bindings has a foreign concrete type")
        if not isinstance(self.storage_sinks, StorageSinkInventoryV1):
            raise FieldFateStructureError("storage_sinks has a foreign concrete type")
        if (
            self.route_bindings.provider_source_inventory_sha256
            != self.provider_sources.identity_sha256
            or self.storage_sinks.route_binding_inventory_sha256
            != self.route_bindings.identity_sha256
            or self.storage_sinks.staging_route_contract_sha256
            != self.route_bindings.staging_route_contract_sha256
        ):
            raise FieldFateStructureError("structural child authority digest drifted")

        source_by_id = self.provider_sources.by_occurrence_id
        expansion_ids = {
            item.source_occurrence_id for item in self.route_bindings.source_expansions
        }
        if expansion_ids != set(source_by_id):
            raise FieldFateStructureError("source expansion inventory omits source occurrences")
        for expansion in self.route_bindings.source_expansions:
            if (
                expansion.source_occurrence_sha256
                != source_by_id[expansion.source_occurrence_id].occurrence_sha256
            ):
                raise FieldFateStructureError("source expansion authority digest drifted")
        for binding in self.route_bindings.bindings:
            source = source_by_id.get(binding.source_occurrence_id)
            if source is None or source.occurrence_sha256 != binding.source_occurrence_sha256:
                raise FieldFateStructureError("route binding names a missing or stale source")
        sink_binding_ids = {
            binding_id for sink in self.storage_sinks.sinks for binding_id in sink.binding_ids
        }
        if sink_binding_ids != set(self.route_bindings.by_binding_id):
            raise FieldFateStructureError("storage sink partition differs from route bindings")
        for binding in self.route_bindings.bindings:
            sink = self.storage_sinks.by_sink_id.get(binding.storage_sink_id)
            if sink is None or binding.binding_id not in sink.binding_ids:
                raise FieldFateStructureError("route binding names a missing storage sink")

        if type(self.lossless_bindings) is not tuple or any(
            not isinstance(item, LosslessFieldBindingV1) for item in self.lossless_bindings
        ):
            raise FieldFateStructureError(
                "lossless field bindings must be an immutable typed tuple"
            )
        if self.lossless_bindings != tuple(
            sorted(self.lossless_bindings, key=lambda item: item.binding_id)
        ):
            raise FieldFateStructureError("lossless field bindings are not canonical")
        lossless_binding_ids = tuple(item.binding_id for item in self.lossless_bindings)
        if len(lossless_binding_ids) != len(set(lossless_binding_ids)):
            raise FieldFateStructureError("lossless field binding identities overlap")
        for binding in self.lossless_bindings:
            source = source_by_id.get(binding.source_occurrence_id)
            if (
                source is None
                or source.occurrence_sha256 != binding.source_occurrence_sha256
                or source.source_family != "live"
                or source.endpoint_id != binding.endpoint_id
                or source.result_set_name != binding.result_set_name
                or source.result_set_ordinal != binding.result_set_ordinal
                or source.field_ordinal != binding.field_ordinal
                or source.provider_field_name != binding.provider_field_name
                or source.source_path != binding.contract_field_json_path
            ):
                raise FieldFateStructureError(
                    "lossless field binding differs from its exact live source"
                )

        if type(self.blockers) is not tuple or any(
            not isinstance(item, FieldFateStructureBlockerV1) for item in self.blockers
        ):
            raise FieldFateStructureError("structural blockers must be an immutable typed tuple")
        if self.blockers != tuple(sorted(self.blockers, key=lambda item: item.blocker_id)):
            raise FieldFateStructureError("structural blockers are not in canonical order")
        blocker_ids = tuple(item.blocker_id for item in self.blockers)
        if len(blocker_ids) != len(set(blocker_ids)):
            raise FieldFateStructureError("structural blocker identities overlap")
        for blocker in self.blockers:
            source = source_by_id.get(blocker.source_occurrence_id)
            if source is None or source.occurrence_sha256 != blocker.source_occurrence_sha256:
                raise FieldFateStructureError("structural blocker names a missing or stale source")

        lossless_blockers = {
            item.source_occurrence_id
            for item in self.blockers
            if item.blocker_kind == "lossless_storage_binding_unresolved"
        }
        unrouted_sources = {
            item.source_occurrence_id
            for item in self.route_bindings.source_expansions
            if item.status == "unrouted"
        }
        lossless_bound_sources = {item.source_occurrence_id for item in self.lossless_bindings}
        if lossless_bound_sources | lossless_blockers != unrouted_sources or (
            lossless_bound_sources & lossless_blockers
        ):
            raise FieldFateStructureError(
                "lossless bindings/blockers do not partition wide-unrouted sources"
            )
        if len(lossless_bound_sources) != _EXPECTED_LOSSLESS_FIELD_BINDING_COUNT:
            raise FieldFateStructureError("lossless field binding denominator drifted")
        source_authority_blockers = {
            item.source_occurrence_id
            for item in self.blockers
            if item.blocker_kind == "source_authority_unavailable"
        }
        unverified_sources = {
            item.occurrence_id
            for item in self.provider_sources.occurrences
            if item.provenance_kind == "unverified_live_docs_field"
        }
        if source_authority_blockers != unverified_sources:
            raise FieldFateStructureError(
                "source-authority blockers differ from unverified live-docs fields"
            )

    def route_landing_fields(
        self,
        route_id: str,
        arrow_schema: pa.Schema,
        *,
        conditional_authority: ConditionalRouteOccurrenceAuthorityV1 | None = None,
    ) -> tuple[RouteLandingFieldJoinV1, ...]:
        """Join one represented route's exact Arrow fields to structural authority."""

        _token(route_id, field_name="route_id")
        if self is not compile_field_fate_structure():
            validate_field_fate_structure(self)
        routes = staging_route_contract_bundle()
        validate_staging_route_contract_bundle(routes)
        route = routes.by_route_id.get(route_id)
        if route is None:
            if conditional_staging_key_from_route_id(route_id) is not None:
                if conditional_authority is None:
                    raise FieldFateStructureError(
                        "conditional lossless route requires exact occurrence authority"
                    )
                return _conditional_route_landing_fields(
                    self,
                    route_id=route_id,
                    arrow_schema=arrow_schema,
                    authority=conditional_authority,
                )
            raise FieldFateStructureError("route landing field route is absent from authority")
        if conditional_authority is not None:
            raise FieldFateStructureError(
                "static route landing rejects foreign conditional authority"
            )
        landed_scope_fields = _validate_route_landing_arrow_schema(route, arrow_schema)

        possible_sinks = tuple(
            item for item in self.storage_sinks.sinks if item.route_id == route.route_id
        )
        if (
            len(possible_sinks) != len(route.possible_storage_columns)
            or tuple(item.storage_ordinal for item in possible_sinks)
            != tuple(range(len(possible_sinks)))
            or tuple(item.storage_column for item in possible_sinks)
            != route.possible_storage_columns
        ):
            raise FieldFateStructureError(
                "route landing storage sink inventory differs from its exact possible schema"
            )
        declared_sinks = possible_sinks[: len(route.storage_columns)]
        possible_scope_sinks = {
            item.storage_column: item for item in possible_sinks[len(route.storage_columns) :]
        }
        scope_sinks: list[StorageSinkV1] = []
        for ordinal, scope_field in enumerate(landed_scope_fields):
            actual_ordinal = len(declared_sinks) + ordinal
            authority_sink = possible_scope_sinks[scope_field.storage_column]
            scope_sinks.append(
                authority_sink
                if authority_sink.storage_ordinal == actual_ordinal
                else StorageSinkV1(
                    sink_id=_storage_sink_id(route.route_id, actual_ordinal),
                    route_id=route.route_id,
                    route_ordinal=route.ordinal,
                    storage_ordinal=actual_ordinal,
                    staging_key=route.staging_key,
                    schema_tier=route.resolved_schema_tier,
                    schema_table=route.resolved_schema_table,
                    schema_class=route.resolved_schema_class,
                    storage_role=route.storage_role,
                    storage_role_target=route.storage_role_target,
                    storage_column=scope_field.storage_column,
                    route_contract_sha256=route.contract_sha256,
                    binding_ids=(),
                    status="storage_only",
                )
            )
        sinks = declared_sinks + tuple(scope_sinks)

        bindings_by_sink: defaultdict[str, list[RouteFieldBindingV1]] = defaultdict(list)
        sink_ids = {item.sink_id for item in sinks}
        for binding in self.route_bindings.bindings:
            if binding.route_id == route.route_id:
                bindings_by_sink[binding.storage_sink_id].append(binding)
            elif binding.storage_sink_id in sink_ids:
                raise FieldFateStructureError(
                    "route landing storage sink contains a foreign route binding"
                )
        if not set(bindings_by_sink) <= sink_ids:
            raise FieldFateStructureError(
                "route landing route binding names a foreign storage sink"
            )
        source_by_id = self.provider_sources.by_occurrence_id
        sources_by_ordinal = _source_occurrence_index(self.provider_sources)
        live_by_path = _live_path_index(self.provider_sources)
        joined: list[RouteLandingFieldJoinV1] = []
        for storage_ordinal, (sink, arrow_field) in enumerate(
            zip(sinks, arrow_schema, strict=True)
        ):
            if (
                sink.route_id != route.route_id
                or sink.route_ordinal != route.ordinal
                or sink.storage_ordinal != storage_ordinal
                or sink.staging_key != route.staging_key
                or sink.schema_tier != route.resolved_schema_tier
                or sink.schema_table != route.resolved_schema_table
                or sink.schema_class != route.resolved_schema_class
                or sink.storage_role != route.storage_role
                or sink.storage_role_target != route.storage_role_target
                or sink.storage_column != arrow_field.name
                or sink.route_contract_sha256 != route.contract_sha256
            ):
                raise FieldFateStructureError(
                    "route landing storage sink differs from its exact route contract"
                )

            bindings = tuple(
                sorted(
                    bindings_by_sink.get(sink.sink_id, ()),
                    key=lambda item: item.mapping_ordinal,
                )
            )
            if tuple(item.binding_id for item in bindings) != sink.binding_ids:
                raise FieldFateStructureError(
                    "route landing storage sink drops or invents binding membership"
                )
            sources: list[ProviderFieldSourceOccurrenceV1] = []
            for binding in bindings:
                if binding.mapping_ordinal >= len(route.column_mappings):
                    raise FieldFateStructureError(
                        "route landing binding has a foreign mapping ordinal"
                    )
                mapping = route.column_mappings[binding.mapping_ordinal]
                if (
                    binding.route_id != route.route_id
                    or binding.route_ordinal != route.ordinal
                    or binding.route_contract_sha256 != route.contract_sha256
                    or binding.endpoint_role != route.endpoint_role
                    or binding.endpoint_alias_target != route.endpoint_alias_target
                    or binding.storage_role != route.storage_role
                    or binding.storage_role_target != route.storage_role_target
                    or binding.provider_column != mapping.provider_column
                    or binding.canonical_column != mapping.canonical_column
                    or binding.mapping_transform != mapping.transform
                    or binding.storage_sink_id != sink.sink_id
                    or binding.storage_column != sink.storage_column
                    or mapping.storage_column != sink.storage_column
                ):
                    raise FieldFateStructureError(
                        "route landing binding differs from its exact route mapping"
                    )
                source = source_by_id.get(binding.source_occurrence_id)
                expected_source = _resolve_route_source(
                    route,
                    binding.mapping_ordinal,
                    sources_by_ordinal,
                    live_by_path,
                )
                if (
                    source is None
                    or source != expected_source
                    or binding.source_family != source.source_family
                    or binding.source_occurrence_sha256 != source.occurrence_sha256
                    or source.source_family != route.source_family
                    or source.endpoint_id != route.provider_endpoint_id
                    or source.endpoint_contract_sha256 != route.endpoint_contract_sha256
                    or source.provider_field_name != binding.provider_column.split(".")[-1]
                ):
                    raise FieldFateStructureError(
                        "route landing source differs from exact provider field authority"
                    )
                sources.append(source)

            origin: RouteLandingFieldOrigin = (
                "storage_only"
                if not bindings
                else "provider_bound"
                if len(bindings) == 1
                else "provider_multi_bound"
            )
            joined.append(
                RouteLandingFieldJoinV1(
                    sink=sink,
                    route_bindings=bindings,
                    provider_sources=tuple(sources),
                    lossless_bindings=(),
                    origin=origin,
                )
            )
        return tuple(joined)

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "provider_sources_sha256": self.provider_sources.identity_sha256,
            "route_bindings_sha256": self.route_bindings.identity_sha256,
            "storage_sinks_sha256": self.storage_sinks.identity_sha256,
            "lossless_bindings_sha256": canonical_sha256(
                [item.to_dict() for item in self.lossless_bindings]
            ),
            "blockers_sha256": canonical_sha256([item.to_dict() for item in self.blockers]),
            "summary": {
                "provider_source_occurrence_count": len(self.provider_sources.occurrences),
                "route_binding_count": len(self.route_bindings.bindings),
                "storage_sink_count": len(self.storage_sinks.sinks),
                "wide_unrouted_source_occurrence_count": sum(
                    item.status == "unrouted" for item in self.route_bindings.source_expansions
                ),
                "lossless_field_binding_count": len(self.lossless_bindings),
                "open_blocker_count": len(self.blockers),
                "source_authority_blocker_count": sum(
                    item.blocker_kind == "source_authority_unavailable" for item in self.blockers
                ),
                "unresolved_lossless_binding_count": sum(
                    item.blocker_kind == "lossless_storage_binding_unresolved"
                    for item in self.blockers
                ),
                "lossless_field_binding_complete": not any(
                    item.blocker_kind == "lossless_storage_binding_unresolved"
                    for item in self.blockers
                ),
                "model_green": "not_evaluated_by_structural_layer",
            },
            "provider_sources": self.provider_sources.to_dict(),
            "route_bindings": self.route_bindings.to_dict(),
            "storage_sinks": self.storage_sinks.to_dict(),
            "lossless_bindings": [item.to_dict() for item in self.lossless_bindings],
            "blockers": [item.to_dict() for item in self.blockers],
        }


def _atom_sha256(atom: Mapping[str, object]) -> str:
    return canonical_sha256(dict(atom))


def _authority_atoms() -> tuple[
    IndependentPackageInventory,
    tuple[dict[str, object], ...],
    Mapping[str, dict[str, object]],
]:
    inventory = build_independent_package_inventory()
    atoms = build_independent_surface_atoms()
    if canonical_sha256(list(atoms)) != inventory.source_atoms_sha256:
        raise FieldFateStructureError("independent source-atom digest differs from its inventory")
    atom_by_id = {cast("str", atom["atom_id"]): atom for atom in atoms}
    if len(atom_by_id) != len(atoms):
        raise FieldFateStructureError("independent source-atom identities overlap")
    return inventory, atoms, MappingProxyType(atom_by_id)


def _upstream_root_key(upstream_root: Path | str | None) -> str | None:
    raw = upstream_root if upstream_root is not None else os.getenv(_UPSTREAM_ROOT_ENV)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        resolved = Path(raw).expanduser().resolve(strict=True)
    except OSError as exc:
        raise FieldFateStructureError("exact nba_api checkout path is unreadable") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise FieldFateStructureError("exact nba_api checkout path is not a regular directory")
    return str(resolved)


@lru_cache(maxsize=4)
def _verified_upstream_root(root_key: str) -> Path:
    root = Path(root_key)
    evidence = verify_nba_api_provider(
        root,
        project_root=Path(__file__).resolve().parents[3],
    )
    if evidence.get("verified") is not True:
        reasons = evidence.get("errors")
        rendered = (
            ",".join(str(item) for item in reasons) if isinstance(reasons, list) else "unknown"
        )
        raise FieldFateStructureError(
            f"exact nba_api checkout failed provider verification: {rendered}"
        )
    return root


def _installed_nba_api_bytes(relative_path: str) -> bytes:
    if not relative_path.startswith("nba_api/") or ".." in Path(relative_path).parts:
        raise FieldFateStructureError("installed nba_api authority path is invalid")
    try:
        return (
            resources.files("nba_api")
            .joinpath(*relative_path.removeprefix("nba_api/").split("/"))
            .read_bytes()
        )
    except (FileNotFoundError, OSError) as exc:
        raise FieldFateStructureError("installed nba_api authority source is unreadable") from exc


def _assignment_node(tree: ast.Module, name: str) -> ast.AST:
    matches = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    ]
    if len(matches) != 1:
        raise FieldFateStructureError(f"installed authority lacks one assignment for {name}")
    return matches[0]


def _live_docs_field_authorities(
    root_key: str | None,
) -> Mapping[tuple[str, str], tuple[str, str, SourceProvenanceKind]]:
    contracts = pinned_live_contracts()
    result: dict[tuple[str, str], tuple[str, str, SourceProvenanceKind]] = {}
    verified_root = _verified_upstream_root(root_key) if root_key is not None else None
    for endpoint_id, contract in sorted(contracts.items()):
        documented_fields = tuple(
            field
            for result_set in contract.result_sets
            for field in result_set.fields
            if field.provenance_source == "live_docs_about_fields"
        )
        if not documented_fields:
            continue
        if verified_root is None:
            for live_field in documented_fields:
                evidence = {
                    "schema_version": 1,
                    "kind": "unavailable_checked_upstream_live_docs_field",
                    "endpoint_id": endpoint_id,
                    "source_path": live_field.json_path,
                    "field_name": live_field.name,
                    "docs_source_path": contract.docs_source_path,
                    "expected_docs_source_sha256": contract.docs_source_sha256,
                    "reason": "exact_upstream_checkout_not_supplied",
                }
                result[(endpoint_id, live_field.json_path)] = (
                    f"unverified_live_docs_field:{endpoint_id}:{live_field.json_path}",
                    canonical_sha256(evidence),
                    "unverified_live_docs_field",
                )
            continue

        docs_path = verified_root / contract.docs_source_path
        try:
            raw = docs_path.read_bytes()
            text = raw.decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            raise FieldFateStructureError("checked upstream live docs are unreadable") from exc
        raw_sha256 = hashlib.sha256(raw).hexdigest()
        if raw_sha256 != contract.docs_source_sha256:
            raise FieldFateStructureError("checked upstream live-docs bytes differ from the pin")
        rows: dict[str, tuple[int, str]] = {}
        for line_ordinal, line in enumerate(text.splitlines()):
            match = re.match(r"^\s*`([^`]+)`\|", line)
            if match is None:
                continue
            field_name = match.group(1)
            if field_name in rows:
                raise FieldFateStructureError("checked upstream live-docs fields overlap")
            rows[field_name] = (line_ordinal, hashlib.sha256(line.encode("utf-8")).hexdigest())
        for live_field in documented_fields:
            line_authority = rows.get(live_field.name)
            if line_authority is None:
                raise FieldFateStructureError("checked upstream live docs omit a pinned field")
            evidence = {
                "schema_version": 1,
                "kind": "checked_upstream_live_docs_field",
                "endpoint_id": endpoint_id,
                "source_path": live_field.json_path,
                "field_name": live_field.name,
                "docs_source_path": contract.docs_source_path,
                "docs_source_sha256": raw_sha256,
                "line_ordinal": line_authority[0],
                "line_sha256": line_authority[1],
            }
            result[(endpoint_id, live_field.json_path)] = (
                f"upstream_live_docs_field:{endpoint_id}:{live_field.json_path}",
                canonical_sha256(evidence),
                "upstream_live_docs_field",
            )
    if len(result) != _LIVE_DOCS_FIELD_COUNT:
        raise FieldFateStructureError("live docs field authority denominator drifted")
    return MappingProxyType(result)


def _nested_scalar_field_authorities() -> Mapping[
    tuple[str, str], tuple[str, str, SourceProvenanceKind]
]:
    result: dict[tuple[str, str], tuple[str, str, SourceProvenanceKind]] = {}
    parser_path = Path(__file__).resolve().parents[1] / "core" / "nba_api_contract.py"
    parser_raw = parser_path.read_bytes()
    parser_tree = ast.parse(parser_raw.decode("utf-8", errors="strict"), filename=str(parser_path))
    projection_function = next(
        (
            node
            for node in parser_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_flatten_live_expected_data_node"
        ),
        None,
    )
    if projection_function is None:
        raise FieldFateStructureError("nested scalar projection parser is absent")
    rule_matches = 0
    for node in ast.walk(projection_function):
        if not isinstance(node, ast.Dict):
            continue
        constants = {
            key.value: value
            for key, value in zip(node.keys, node.values, strict=True)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        source = constants.get("source")
        source_field = constants.get("source_field")
        has_value_shape = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "_live_shape_field"
            and child.args
            and isinstance(child.args[0], ast.Constant)
            and child.args[0].value == "value"
            for child in ast.walk(node)
        )
        if (
            isinstance(source, ast.Constant)
            and source.value == "nbadb_nested_scalar_projection"
            and isinstance(source_field, ast.Constant)
            and source_field.value is False
            and has_value_shape
        ):
            rule_matches += 1
    if rule_matches != 1:
        raise FieldFateStructureError("nested scalar projection rule is absent or ambiguous")

    for endpoint_id, contract in sorted(pinned_live_contracts().items()):
        raw = _installed_nba_api_bytes(contract.source_path)
        if hashlib.sha256(raw).hexdigest() != contract.source_sha256:
            raise FieldFateStructureError("installed live source differs from its exact digest")
        tree = ast.parse(raw.decode("utf-8", errors="strict"), filename=contract.source_path)
        class_nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == endpoint_id
        ]
        if len(class_nodes) != 1:
            raise FieldFateStructureError("installed live endpoint class is absent or ambiguous")
        expected_data = ast.literal_eval(
            _assignment_node(
                ast.Module(body=class_nodes[0].body, type_ignores=[]),
                "expected_data",
            )
        )
        for result_set in contract.result_sets:
            for live_field in result_set.fields:
                if live_field.provenance_source != "nbadb_nested_scalar_projection":
                    continue
                segments = live_field.json_path.removeprefix("$.").split(".")
                if len(segments) < 2 or segments[-1] != "value":
                    raise FieldFateStructureError("nested scalar field path is unsupported")
                cursor: object = expected_data
                for segment in segments[:-2]:
                    if not isinstance(cursor, dict) or segment not in cursor:
                        raise FieldFateStructureError("nested scalar source path is absent")
                    cursor = cast("dict[str, object]", cursor)[segment]
                    if isinstance(cursor, list):
                        if not cursor:
                            raise FieldFateStructureError("nested scalar source list is empty")
                        cursor = cursor[0]
                parent_name = segments[-2]
                if not isinstance(cursor, dict) or parent_name not in cursor:
                    raise FieldFateStructureError("nested scalar parent source is absent")
                parent = cast("dict[str, object]", cursor)[parent_name]
                if (
                    not isinstance(parent, list)
                    or not parent
                    or any(isinstance(item, dict | list) for item in parent)
                ):
                    raise FieldFateStructureError("nested scalar parent is not a scalar list")
                evidence = {
                    "schema_version": 1,
                    "kind": "installed_live_nested_scalar_projection",
                    "endpoint_id": endpoint_id,
                    "source_path": live_field.json_path,
                    "field_name": live_field.name,
                    "runtime_source_path": contract.source_path,
                    "runtime_source_sha256": contract.source_sha256,
                    "parser_source_path": "src/nbadb/core/nba_api_contract.py",
                    "parser_source_sha256": hashlib.sha256(parser_raw).hexdigest(),
                    "projection_rule": "nonempty_scalar_list_item_to_value_field_v1",
                    "observed_scalar_type_names": sorted({type(item).__name__ for item in parent}),
                }
                result[(endpoint_id, live_field.json_path)] = (
                    f"installed_live_nested_scalar_projection:{endpoint_id}:{live_field.json_path}",
                    canonical_sha256(evidence),
                    "installed_live_nested_scalar_projection",
                )
    if len(result) != _LIVE_NESTED_SCALAR_FIELD_COUNT:
        raise FieldFateStructureError("nested scalar field authority denominator drifted")
    return MappingProxyType(result)


def _static_field_authorities() -> Mapping[tuple[str, int], tuple[str, str, SourceProvenanceKind]]:
    contracts = pinned_static_contracts()
    result: dict[tuple[str, int], tuple[str, str, SourceProvenanceKind]] = {}
    for dataset_id, contract in sorted(contracts.items()):
        provider_raw = _installed_nba_api_bytes(contract.provider_source_path)
        data_raw = _installed_nba_api_bytes(contract.data_source_path)
        if (
            hashlib.sha256(provider_raw).hexdigest() != contract.provider_source_sha256
            or hashlib.sha256(data_raw).hexdigest() != contract.data_source_sha256
        ):
            raise FieldFateStructureError("installed static authority bytes differ from the pin")
        provider_tree = ast.parse(
            provider_raw.decode("utf-8", errors="strict"), filename=contract.provider_source_path
        )
        data_tree = ast.parse(
            data_raw.decode("utf-8", errors="strict"), filename=contract.data_source_path
        )
        prefix = "player_index_" if "players" in dataset_id else "team_index_"
        index_constants: dict[str, int] = {}
        for node in data_tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not target.id.startswith(prefix):
                continue
            value = ast.literal_eval(node.value)
            if type(value) is not int or value < 0:
                raise FieldFateStructureError("installed static data index is invalid")
            index_constants[target.id] = value
        if len(index_constants) != len(contract.raw_fields):
            raise FieldFateStructureError("installed static data-index denominator drifted")

        projection_functions: list[tuple[str, dict[str, str]]] = []
        for node in provider_tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            returns = [child for child in ast.walk(node) if isinstance(child, ast.Return)]
            if len(returns) != 1 or not isinstance(returns[0].value, ast.Dict):
                continue
            projection: dict[str, str] = {}
            valid = True
            for key_node, value_node in zip(
                returns[0].value.keys, returns[0].value.values, strict=True
            ):
                if (
                    not isinstance(key_node, ast.Constant)
                    or not isinstance(key_node.value, str)
                    or not isinstance(value_node, ast.Subscript)
                    or not isinstance(value_node.slice, ast.Name)
                ):
                    valid = False
                    break
                projection[key_node.value] = value_node.slice.id
            if valid and projection:
                projection_functions.append((node.name, projection))
        if len(projection_functions) != 1:
            raise FieldFateStructureError("installed static getter projection is ambiguous")
        projection_function, projected_by_name = projection_functions[0]
        projected_by_index = {index_name: name for name, index_name in projected_by_name.items()}
        if len(projected_by_index) != len(projected_by_name):
            raise FieldFateStructureError("installed static getter projection collapses fields")

        rows_node = _assignment_node(data_tree, contract.source_symbol)
        if not isinstance(rows_node, ast.List) or not rows_node.elts:
            raise FieldFateStructureError("installed static dataset rows are absent")
        row_widths = {
            len(row.elts) for row in rows_node.elts if isinstance(row, ast.List | ast.Tuple)
        }
        if len(row_widths) != 1 or len(rows_node.elts) != contract.row_count:
            raise FieldFateStructureError("installed static dataset row shape drifted")
        (row_width,) = tuple(row_widths)
        if row_width != len(contract.raw_fields):
            raise FieldFateStructureError("installed static row width differs from raw fields")

        names_by_ordinal: dict[int, tuple[str, str, bool]] = {}
        for index_name, ordinal in index_constants.items():
            fallback_name = index_name.removeprefix(prefix)
            projected_name = projected_by_index.get(index_name)
            field_name = projected_name if projected_name is not None else fallback_name
            if ordinal in names_by_ordinal:
                raise FieldFateStructureError("installed static data ordinals overlap")
            names_by_ordinal[ordinal] = (field_name, index_name, projected_name is not None)
        expected_fields = tuple((field.ordinal, field.name) for field in contract.raw_fields)
        derived_fields = tuple(
            (ordinal, names_by_ordinal[ordinal][0]) for ordinal in sorted(names_by_ordinal)
        )
        if derived_fields != expected_fields:
            raise FieldFateStructureError("installed static field names/ordinals differ from pin")
        for static_field in contract.raw_fields:
            field_name, index_name, getter_projected = names_by_ordinal[static_field.ordinal]
            expected_projected = (
                static_field.provider_projection_disposition == "projected_by_provider"
            )
            if field_name != static_field.name or getter_projected != expected_projected:
                raise FieldFateStructureError("installed static getter disposition drifted")
            evidence = {
                "schema_version": 1,
                "kind": "installed_static_field_projection",
                "dataset_id": dataset_id,
                "source_symbol": contract.source_symbol,
                "field_name": field_name,
                "field_ordinal": static_field.ordinal,
                "data_index_constant": index_name,
                "getter_projection_function": projection_function,
                "getter_projected": getter_projected,
                "provider_source_path": contract.provider_source_path,
                "provider_source_sha256": contract.provider_source_sha256,
                "data_source_path": contract.data_source_path,
                "data_source_sha256": contract.data_source_sha256,
                "source_row_count": len(rows_node.elts),
                "source_row_width": row_width,
            }
            result[(dataset_id, static_field.ordinal)] = (
                f"installed_static_field_projection:{dataset_id}:{static_field.ordinal:04d}",
                canonical_sha256(evidence),
                "installed_static_field_projection",
            )
    if len(result) != EXPECTED_STATIC_SOURCE_OCCURRENCE_COUNT:
        raise FieldFateStructureError("static field authority denominator drifted")
    return MappingProxyType(result)


def _field_authority_digest(
    occurrences: list[ProviderFieldSourceOccurrenceV1],
    provenance_kinds: set[SourceProvenanceKind],
) -> str:
    return canonical_sha256(
        [
            {
                "occurrence_id": item.occurrence_id,
                "authority_atom_id": item.authority_atom_id,
                "authority_atom_sha256": item.authority_atom_sha256,
                "provenance_kind": item.provenance_kind,
            }
            for item in sorted(occurrences, key=lambda row: row.occurrence_id)
            if item.provenance_kind in provenance_kinds
        ]
    )


@lru_cache(maxsize=4)
def _compile_provider_field_source_inventory(
    root_key: str | None,
) -> ProviderFieldSourceInventoryV1:
    """Compile the exact 9,970-occurrence provider-field denominator."""

    package_inventory, atoms, atom_by_id = _authority_atoms()
    stats_atoms = tuple(atom for atom in atoms if atom.get("kind") == "stats_result_header")
    live_atoms = tuple(atom for atom in atoms if atom.get("kind") == "live_source_field")
    static_atoms = tuple(atom for atom in atoms if atom.get("kind") == "static_dataset")
    if (
        len(stats_atoms) != EXPECTED_STATS_SOURCE_OCCURRENCE_COUNT
        or len(live_atoms) != _EXPECTED_DIRECT_LIVE_SOURCE_OCCURRENCE_COUNT
        or len(static_atoms) != 4
        or getattr(package_inventory, "header_occurrence_count", None)
        != EXPECTED_STATS_SOURCE_OCCURRENCE_COUNT + EXPECTED_LIVE_SOURCE_OCCURRENCE_COUNT
    ):
        raise FieldFateStructureError("independent provider-field denominator drifted")

    occurrences: list[ProviderFieldSourceOccurrenceV1] = []
    stats_contracts = pinned_runtime_contracts()
    stats_atom_ids: set[str] = set()
    for atom in stats_atoms:
        atom_id = cast("str", atom["atom_id"])
        endpoint_id = cast("str", atom["endpoint_id"])
        result_set_name = cast("str", atom["result_set_name"])
        result_set_ordinal = cast("int", atom["result_set_ordinal"])
        field_ordinal = cast("int", atom["header_ordinal"])
        header = cast("str", atom["header"])
        contract = stats_contracts.get(endpoint_id)
        if contract is None:
            raise FieldFateStructureError("stats source atom names an absent endpoint contract")
        result_sets = tuple(
            result_set
            for result_set in contract.result_sets
            if result_set.result_set_index == result_set_ordinal
        )
        if len(result_sets) != 1:
            raise FieldFateStructureError("stats source result-set ordinal is absent or ambiguous")
        result_set = result_sets[0]
        if (
            result_set.result_set_name != result_set_name
            or field_ordinal >= len(result_set.expected_columns)
            or result_set.expected_columns[field_ordinal] != header
        ):
            raise FieldFateStructureError("stats source header differs from its pinned contract")
        stats_atom_ids.add(atom_id)
        occurrences.append(
            ProviderFieldSourceOccurrenceV1(
                occurrence_id=_source_occurrence_id(
                    "stats", endpoint_id, result_set_ordinal, field_ordinal
                ),
                source_family="stats",
                endpoint_id=endpoint_id,
                result_set_name=result_set_name,
                result_set_ordinal=result_set_ordinal,
                field_ordinal=field_ordinal,
                provider_field_name=header,
                source_path=(
                    f"result_sets[{result_set_ordinal}].{result_set_name}.headers[{field_ordinal}]"
                ),
                authority_atom_id=atom_id,
                authority_atom_sha256=_atom_sha256(atom),
                endpoint_contract_sha256=endpoint_contract_sha256(contract),
                provenance_kind="installed_stats_header_atom",
                direct_source_field=True,
            )
        )
    if stats_atom_ids != {cast("str", atom["atom_id"]) for atom in stats_atoms}:
        raise FieldFateStructureError("stats source atoms were not consumed exactly once")

    live_contracts = pinned_live_contracts()
    live_docs_authorities = _live_docs_field_authorities(root_key)
    nested_scalar_authorities = _nested_scalar_field_authorities()
    expected_live_atom_ids: set[str] = set()
    for endpoint_id, contract in sorted(live_contracts.items()):
        endpoint_atom_id = f"endpoint:live:{endpoint_id}"
        endpoint_atom = atom_by_id.get(endpoint_atom_id)
        if endpoint_atom is None:
            raise FieldFateStructureError("live parser fields lack endpoint source authority")
        contract_digest = owned_contract_sha256(contract)
        for result_set in contract.result_sets:
            for live_field in result_set.fields:
                direct_atom_id = f"live_source_field:{endpoint_id}:{live_field.json_path}"
                direct_atom = atom_by_id.get(direct_atom_id)
                if direct_atom is not None:
                    if (
                        direct_atom.get("kind") != "live_source_field"
                        or direct_atom.get("endpoint_id") != endpoint_id
                        or direct_atom.get("json_path") != live_field.json_path
                    ):
                        raise FieldFateStructureError("live source atom is malformed")
                    authority_atom_id = direct_atom_id
                    authority_atom = direct_atom
                    provenance_kind: SourceProvenanceKind = "installed_live_source_field_atom"
                    expected_live_atom_ids.add(direct_atom_id)
                else:
                    independent_authority = live_docs_authorities.get(
                        (endpoint_id, live_field.json_path)
                    ) or nested_scalar_authorities.get((endpoint_id, live_field.json_path))
                    if independent_authority is None:
                        raise FieldFateStructureError(
                            "non-runtime live field lacks independent docs/parser authority"
                        )
                    authority_atom_id, authority_atom_sha256, provenance_kind = (
                        independent_authority
                    )
                occurrences.append(
                    ProviderFieldSourceOccurrenceV1(
                        occurrence_id=_source_occurrence_id(
                            "live", endpoint_id, result_set.ordinal, live_field.ordinal
                        ),
                        source_family="live",
                        endpoint_id=endpoint_id,
                        result_set_name=result_set.name,
                        result_set_ordinal=result_set.ordinal,
                        field_ordinal=live_field.ordinal,
                        provider_field_name=live_field.name,
                        source_path=live_field.json_path,
                        authority_atom_id=authority_atom_id,
                        authority_atom_sha256=(
                            _atom_sha256(authority_atom)
                            if direct_atom is not None
                            else authority_atom_sha256
                        ),
                        endpoint_contract_sha256=contract_digest,
                        provenance_kind=provenance_kind,
                        direct_source_field=live_field.source_field,
                    )
                )
    if expected_live_atom_ids != {cast("str", atom["atom_id"]) for atom in live_atoms}:
        raise FieldFateStructureError("installed live source paths were omitted or stale")

    static_contracts = pinned_static_contracts()
    static_field_authorities = _static_field_authorities()
    expected_static_ids = {cast("str", atom["dataset_id"]) for atom in static_atoms}
    if set(static_contracts) != expected_static_ids:
        raise FieldFateStructureError("static dataset authority and modeled contracts differ")
    for dataset_id, contract in sorted(static_contracts.items()):
        atom_id = f"static_dataset:{dataset_id}"
        atom = atom_by_id.get(atom_id)
        if atom is None or (
            atom.get("source_symbol") != contract.source_symbol
            or atom.get("row_width") != len(contract.raw_fields)
        ):
            raise FieldFateStructureError("static modeled fields lack exact dataset authority")
        for static_field in contract.raw_fields:
            field_authority = static_field_authorities.get((dataset_id, static_field.ordinal))
            if field_authority is None:
                raise FieldFateStructureError(
                    "static field lacks installed index/projection authority"
                )
            occurrences.append(
                ProviderFieldSourceOccurrenceV1(
                    occurrence_id=_source_occurrence_id(
                        "static", dataset_id, 0, static_field.ordinal
                    ),
                    source_family="static",
                    endpoint_id=dataset_id,
                    result_set_name=f"{contract.source_symbol}_shape_1",
                    result_set_ordinal=0,
                    field_ordinal=static_field.ordinal,
                    provider_field_name=static_field.name,
                    source_path=f"{contract.source_symbol}[*][{static_field.ordinal}]",
                    authority_atom_id=field_authority[0],
                    authority_atom_sha256=field_authority[1],
                    endpoint_contract_sha256=owned_contract_sha256(contract),
                    provenance_kind=field_authority[2],
                    direct_source_field=True,
                )
            )

    payload = load_pinned_runtime_contract_payload()
    payload_sha256 = payload.get("payload_sha256")
    if not isinstance(payload_sha256, str):
        raise FieldFateStructureError("pinned runtime payload lacks an exact digest")
    return ProviderFieldSourceInventoryV1(
        occurrences=tuple(sorted(occurrences, key=lambda item: item.occurrence_id)),
        independent_package_inventory_sha256=package_inventory.inventory_sha256,
        independent_source_atoms_sha256=package_inventory.source_atoms_sha256,
        pinned_runtime_contract_payload_sha256=payload_sha256,
        live_docs_field_evidence_sha256=_field_authority_digest(
            occurrences,
            {"upstream_live_docs_field", "unverified_live_docs_field"},
        ),
        live_nested_scalar_evidence_sha256=_field_authority_digest(
            occurrences,
            {"installed_live_nested_scalar_projection"},
        ),
        static_field_evidence_sha256=_field_authority_digest(
            occurrences,
            {"installed_static_field_projection"},
        ),
    )


def compile_provider_field_source_inventory(
    upstream_root: Path | str | None = None,
) -> ProviderFieldSourceInventoryV1:
    """Compile provider occurrences, retaining source blockers when docs are absent."""

    return _compile_provider_field_source_inventory(_upstream_root_key(upstream_root))


def _source_key(
    family: SourceFamily,
    endpoint_id: str,
    result_set_ordinal: int,
    field_ordinal: int,
) -> tuple[SourceFamily, str, int, int]:
    return family, endpoint_id, result_set_ordinal, field_ordinal


def _source_occurrence_index(
    sources: ProviderFieldSourceInventoryV1,
) -> Mapping[tuple[SourceFamily, str, int, int], ProviderFieldSourceOccurrenceV1]:
    index = {
        _source_key(
            item.source_family,
            item.endpoint_id,
            item.result_set_ordinal,
            item.field_ordinal,
        ): item
        for item in sources.occurrences
    }
    if len(index) != len(sources.occurrences):
        raise FieldFateStructureError("source ordinal keys overlap")
    return MappingProxyType(index)


def _live_path_index(
    sources: ProviderFieldSourceInventoryV1,
) -> Mapping[tuple[str, str], ProviderFieldSourceOccurrenceV1]:
    live_sources = tuple(item for item in sources.occurrences if item.source_family == "live")
    index = {(item.endpoint_id, item.source_path): item for item in live_sources}
    if len(index) != len(live_sources):
        raise FieldFateStructureError("live endpoint/path source keys overlap")
    return MappingProxyType(index)


def _resolve_route_source(
    route: StagingRouteContract,
    mapping_ordinal: int,
    sources_by_ordinal: Mapping[
        tuple[SourceFamily, str, int, int], ProviderFieldSourceOccurrenceV1
    ],
    live_by_path: Mapping[tuple[str, str], ProviderFieldSourceOccurrenceV1],
) -> ProviderFieldSourceOccurrenceV1:
    mapping = route.column_mappings[mapping_ordinal]
    if route.source_family == "live" and mapping.transform == "nested_projection":
        live_contract = pinned_live_contracts().get(route.provider_endpoint_id)
        if live_contract is None or route.provider_result_set_ordinal is None:
            raise FieldFateStructureError("nested live route lacks an exact provider contract")
        base_sets = tuple(
            result_set
            for result_set in live_contract.result_sets
            if result_set.ordinal == route.provider_result_set_ordinal
        )
        if len(base_sets) != 1:
            raise FieldFateStructureError("nested live route result set is absent or ambiguous")
        source = live_by_path.get(
            (route.provider_endpoint_id, f"{base_sets[0].json_path}.{mapping.provider_column}")
        )
    else:
        if route.provider_result_set_ordinal is None:
            raise FieldFateStructureError("provider-bearing route lacks a result-set ordinal")
        if (
            mapping_ordinal >= len(route.provider_columns)
            or route.provider_columns[mapping_ordinal] != mapping.provider_column
        ):
            raise FieldFateStructureError("route mapping ordinal differs from provider columns")
        source = sources_by_ordinal.get(
            _source_key(
                route.source_family,
                route.provider_endpoint_id,
                route.provider_result_set_ordinal,
                mapping_ordinal,
            )
        )
    if source is None or source.provider_field_name != mapping.provider_column.split(".")[-1]:
        raise FieldFateStructureError("route mapping has no exact provider source occurrence")
    if source.endpoint_contract_sha256 != route.endpoint_contract_sha256:
        raise FieldFateStructureError("route and source endpoint contract digests differ")
    return source


@lru_cache(maxsize=4)
def _compile_route_field_binding_inventory(
    root_key: str | None,
) -> RouteFieldBindingInventoryV1:
    """Compile exact source-to-route expansion without changing the denominator."""

    sources = _compile_provider_field_source_inventory(root_key)
    routes = staging_route_contract_bundle()
    validate_staging_route_contract_bundle(routes)
    if len(routes.routes) != _EXPECTED_ROUTE_COUNT:
        raise FieldFateStructureError("staging route denominator differs from the exact pin")
    sources_by_ordinal = _source_occurrence_index(sources)
    live_by_path = _live_path_index(sources)
    bindings: list[RouteFieldBindingV1] = []
    bindings_by_source: dict[str, list[RouteFieldBindingV1]] = defaultdict(list)
    for route in routes.routes:
        for mapping_ordinal, mapping in enumerate(route.column_mappings):
            source = _resolve_route_source(
                route,
                mapping_ordinal,
                sources_by_ordinal,
                live_by_path,
            )
            if mapping.storage_column is None:
                raise FieldFateStructureError("route provider mapping lacks a storage sink")
            matching_storage_ordinals = tuple(
                ordinal
                for ordinal, column in enumerate(route.storage_columns)
                if column == mapping.storage_column
            )
            if len(matching_storage_ordinals) != 1:
                raise FieldFateStructureError("route storage sink is absent or ambiguous")
            binding = RouteFieldBindingV1(
                binding_id=_route_binding_id(route.route_id, mapping_ordinal),
                route_id=route.route_id,
                route_ordinal=route.ordinal,
                mapping_ordinal=mapping_ordinal,
                source_family=route.source_family,
                source_occurrence_id=source.occurrence_id,
                source_occurrence_sha256=source.occurrence_sha256,
                route_contract_sha256=route.contract_sha256,
                endpoint_role=route.endpoint_role,
                endpoint_alias_target=route.endpoint_alias_target,
                storage_role=route.storage_role,
                storage_role_target=route.storage_role_target,
                provider_column=mapping.provider_column,
                canonical_column=mapping.canonical_column,
                mapping_transform=mapping.transform,
                storage_sink_id=_storage_sink_id(route.route_id, matching_storage_ordinals[0]),
                storage_column=mapping.storage_column,
            )
            bindings.append(binding)
            bindings_by_source[source.occurrence_id].append(binding)

    expansions: list[SourceRouteExpansionV1] = []
    for source in sources.occurrences:
        source_bindings = bindings_by_source.get(source.occurrence_id, [])
        binding_ids = tuple(sorted(item.binding_id for item in source_bindings))
        status: ExpansionStatus = (
            "unrouted"
            if not binding_ids
            else "single_route"
            if len(binding_ids) == 1
            else "expanded_routes"
        )
        expansions.append(
            SourceRouteExpansionV1(
                source_occurrence_id=source.occurrence_id,
                source_occurrence_sha256=source.occurrence_sha256,
                binding_ids=binding_ids,
                alias_binding_ids=tuple(
                    sorted(
                        item.binding_id
                        for item in source_bindings
                        if item.endpoint_role != "canonical"
                    )
                ),
                copy_binding_ids=tuple(
                    sorted(
                        item.binding_id for item in source_bindings if item.storage_role != "direct"
                    )
                ),
                status=status,
            )
        )
    return RouteFieldBindingInventoryV1(
        bindings=tuple(bindings),
        source_expansions=tuple(expansions),
        provider_source_inventory_sha256=sources.identity_sha256,
        staging_route_contract_sha256=routes.digest,
    )


def compile_route_field_binding_inventory(
    upstream_root: Path | str | None = None,
) -> RouteFieldBindingInventoryV1:
    """Compile source-to-route expansion for the selected source authority."""

    return _compile_route_field_binding_inventory(_upstream_root_key(upstream_root))


@lru_cache(maxsize=4)
def _compile_storage_sink_inventory(root_key: str | None) -> StorageSinkInventoryV1:
    """Compile every route-local storage column and its exact binding partition."""

    route_bindings = _compile_route_field_binding_inventory(root_key)
    routes = staging_route_contract_bundle()
    bindings_by_sink: dict[str, list[str]] = defaultdict(list)
    for binding in route_bindings.bindings:
        bindings_by_sink[binding.storage_sink_id].append(binding.binding_id)
    sinks: list[StorageSinkV1] = []
    for route in routes.routes:
        for storage_ordinal, storage_column in enumerate(route.possible_storage_columns):
            sink_id = _storage_sink_id(route.route_id, storage_ordinal)
            binding_ids = tuple(sorted(bindings_by_sink.get(sink_id, ())))
            sinks.append(
                StorageSinkV1(
                    sink_id=sink_id,
                    route_id=route.route_id,
                    route_ordinal=route.ordinal,
                    storage_ordinal=storage_ordinal,
                    staging_key=route.staging_key,
                    schema_tier=route.resolved_schema_tier,
                    schema_table=route.resolved_schema_table,
                    schema_class=route.resolved_schema_class,
                    storage_role=route.storage_role,
                    storage_role_target=route.storage_role_target,
                    storage_column=storage_column,
                    route_contract_sha256=route.contract_sha256,
                    binding_ids=binding_ids,
                    status="provider_bound" if binding_ids else "storage_only",
                )
            )
    return StorageSinkInventoryV1(
        sinks=tuple(sinks),
        route_binding_inventory_sha256=route_bindings.identity_sha256,
        staging_route_contract_sha256=routes.digest,
    )


def compile_storage_sink_inventory(
    upstream_root: Path | str | None = None,
) -> StorageSinkInventoryV1:
    """Compile storage sinks for the selected source authority."""

    return _compile_storage_sink_inventory(_upstream_root_key(upstream_root))


@lru_cache(maxsize=1)
def _live_lossless_sink_authority() -> tuple[str, tuple[str, ...]]:
    root = Path(__file__).resolve().parents[3]
    relative_paths = (
        "src/nbadb/contracts/staging_route_contract.py",
        "src/nbadb/extract/live_lossless.py",
        "src/nbadb/extract/nba_api_adapter.py",
        "src/nbadb/orchestrate/extractor_runner.py",
        "src/nbadb/orchestrate/staging_batches.py",
        "src/nbadb/schemas/staging/nba_api_live_lossless.py",
    )
    sources: dict[str, tuple[bytes, ast.Module]] = {}
    for relative_path in relative_paths:
        path = root / relative_path
        raw = path.read_bytes()
        sources[relative_path] = (
            raw,
            ast.parse(raw.decode("utf-8", errors="strict"), filename=relative_path),
        )

    live_tree = sources["src/nbadb/extract/live_lossless.py"][1]
    schema_nodes = [
        node.value
        for node in live_tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "LIVE_LOSSLESS_SCHEMA"
    ]
    if len(schema_nodes) != 1 or not isinstance(schema_nodes[0], ast.Dict):
        raise FieldFateStructureError("live lossless sink schema authority is absent")
    schema_columns = tuple(
        key.value
        for key in schema_nodes[0].keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    )
    if len(schema_columns) != len(schema_nodes[0].keys) or len(schema_columns) != len(
        set(schema_columns)
    ):
        raise FieldFateStructureError("live lossless sink schema columns are ambiguous")
    required_columns = {
        "array_ordinal",
        "canonical_json",
        "contract_field_ordinal",
        "contract_json_path",
        "endpoint_contract_sha256",
        "endpoint_id",
        "object_key",
        "presence_kind",
        "provider_authority_sha256",
        "request_parameters_json",
        "response_receipt_sha256",
        "result_set_ordinal",
        "snapshot_at",
        "value_kind",
    }
    if not required_columns <= set(schema_columns):
        raise FieldFateStructureError("live lossless sink omits required field selectors")

    schema_tree = sources["src/nbadb/schemas/staging/nba_api_live_lossless.py"][1]
    schema_classes = [
        node
        for node in schema_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StagingNbaApiLiveLosslessNodesSchema"
    ]
    if len(schema_classes) != 1:
        raise FieldFateStructureError("live lossless staging schema class is ambiguous")
    declared_columns = tuple(
        node.target.id
        for node in schema_classes[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    )
    if declared_columns != schema_columns:
        raise FieldFateStructureError("live lossless frame/staging schema order differs")

    required_symbols = {
        "src/nbadb/contracts/staging_route_contract.py": {
            "admit_conditional_live_lossless_route",
        },
        "src/nbadb/extract/live_lossless.py": {
            "NbaApiLiveLosslessLanding",
            "build_live_lossless_landing",
            "reconstruct_live_payload",
            "validate_live_lossless_frame",
        },
        "src/nbadb/extract/nba_api_adapter.py": {
            "_parse_live_payloads",
            "fetch_live_payloads",
            "replay_live_payloads",
        },
        "src/nbadb/orchestrate/extractor_runner.py": {
            "ExtractorRunner",
        },
        "src/nbadb/orchestrate/staging_batches.py": {
            "_validate_persisted_live_lossless",
        },
    }
    for relative_path, expected_symbols in required_symbols.items():
        tree = sources[relative_path][1]
        observed = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        }
        if not expected_symbols <= observed:
            raise FieldFateStructureError(
                "live lossless admission/capture/persistence authority is incomplete"
            )

    runner_tree = sources["src/nbadb/orchestrate/extractor_runner.py"][1]
    runner_classes = [
        node
        for node in runner_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ExtractorRunner"
    ]
    if len(runner_classes) != 1:
        raise FieldFateStructureError("live lossless runner authority is ambiguous")
    runner_methods = {
        node.name: node
        for node in runner_classes[0].body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    required_runner_calls = {
        "_verified_live_lossless_landings": {"validate_live_lossless_frame"},
        "_verify_live_lossless_request_scope": {
            "admit_conditional_live_lossless_route",
            "logical_parameters_sha256",
        },
        "_admit_conditional_result_routes": {"_conditional_route_admission"},
        "_finalize_logical_call_receipt": {
            "LogicalCallReceiptBinding",
            "record_logical_call",
        },
    }
    for method_name, required_calls in required_runner_calls.items():
        method = runner_methods.get(method_name)
        if method is None:
            raise FieldFateStructureError("live lossless runner binding method is absent")
        observed_calls = {
            (
                call.func.id
                if isinstance(call.func, ast.Name)
                else call.func.attr
                if isinstance(call.func, ast.Attribute)
                else ""
            )
            for call in ast.walk(method)
            if isinstance(call, ast.Call)
        }
        if not required_calls <= observed_calls:
            raise FieldFateStructureError("live lossless runner binding calls are incomplete")

    staging_tree = sources["src/nbadb/orchestrate/staging_batches.py"][1]
    staging_classes = [
        node
        for node in staging_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StagingBatchStore"
    ]
    if len(staging_classes) != 1:
        raise FieldFateStructureError("live lossless staging store authority is ambiguous")
    persist_methods = [
        node
        for node in staging_classes[0].body
        if isinstance(node, ast.FunctionDef) and node.name == "persist_frame_batches"
    ]
    if len(persist_methods) != 1:
        raise FieldFateStructureError("live lossless staging persistence method is ambiguous")
    persist_calls = {
        (
            call.func.id
            if isinstance(call.func, ast.Name)
            else call.func.attr
            if isinstance(call.func, ast.Attribute)
            else ""
        )
        for call in ast.walk(persist_methods[0])
        if isinstance(call, ast.Call)
    }
    if not {"_validate_persisted_live_lossless", "_persist_frame_batch_list", "execute"} <= (
        persist_calls
    ):
        raise FieldFateStructureError(
            "live lossless transactional persistence calls are incomplete"
        )

    authority = {
        "schema_version": 1,
        "kind": "receipt_bound_live_lossless_sink_authority",
        "staging_key": _LIVE_LOSSLESS_STAGING_KEY,
        "schema_columns": list(schema_columns),
        "source_files": [
            {
                "path": relative_path,
                "sha256": hashlib.sha256(sources[relative_path][0]).hexdigest(),
            }
            for relative_path in relative_paths
        ],
        "guarantees": [
            "complete_decoded_payload_node_projection",
            "endpoint_contract_and_provider_authority_binding",
            "explicit_missing_null_empty_and_present_states",
            "logical_request_and_response_receipt_binding",
            "typed_conditional_route_admission",
            "typed_staging_persistence_and_replay_validation",
        ],
        "verified_call_edges": [
            "ExtractorRunner._admit_conditional_result_routes->_conditional_route_admission",
            "ExtractorRunner._finalize_logical_call_receipt->record_logical_call",
            "ExtractorRunner._verified_live_lossless_landings->validate_live_lossless_frame",
            "ExtractorRunner._verify_live_lossless_request_scope->admit_conditional_live_lossless_route",
            "StagingBatchStore.persist_frame_batches->_persist_frame_batch_list",
            "StagingBatchStore.persist_frame_batches->_validate_persisted_live_lossless",
        ],
    }
    return canonical_sha256(authority), schema_columns


def _compile_lossless_field_bindings(
    sources: ProviderFieldSourceInventoryV1,
    route_bindings: RouteFieldBindingInventoryV1,
) -> tuple[LosslessFieldBindingV1, ...]:
    sink_authority_sha256, _schema_columns = _live_lossless_sink_authority()
    source_by_id = sources.by_occurrence_id
    live_contracts = pinned_live_contracts()
    bindings: list[LosslessFieldBindingV1] = []
    for expansion in route_bindings.source_expansions:
        if expansion.status != "unrouted":
            continue
        source = source_by_id[expansion.source_occurrence_id]
        if source.source_family != "live":
            raise FieldFateStructureError("wide-unrouted non-live field lacks a lossless sink")
        contract = live_contracts.get(source.endpoint_id)
        result_sets = (
            ()
            if contract is None
            else tuple(
                result_set
                for result_set in contract.result_sets
                if result_set.ordinal == source.result_set_ordinal
            )
        )
        if len(result_sets) != 1:
            raise FieldFateStructureError("lossless field result-set authority is ambiguous")
        result_set = result_sets[0]
        fields = tuple(
            field for field in result_set.fields if field.ordinal == source.field_ordinal
        )
        if (
            len(fields) != 1
            or fields[0].name != source.provider_field_name
            or fields[0].json_path != source.source_path
        ):
            raise FieldFateStructureError("lossless field differs from typed live contract")
        strategy: LosslessBindingStrategy
        if source.direct_source_field:
            strategy = "object_contract_field"
            strategy_columns = {
                "canonical_json",
                "contract_field_ordinal",
                "object_key",
                "presence_kind",
                "value_kind",
            }
        else:
            if len(result_set.fields) != 1 or source.provider_field_name != "value":
                raise FieldFateStructureError(
                    "synthetic scalar lossless binding is not uniquely discriminated"
                )
            strategy = "scalar_result_set_item"
            strategy_columns = {
                "array_ordinal",
                "canonical_json",
                "presence_kind",
                "value_kind",
            }
        selector_columns = tuple(
            sorted(
                {
                    "contract_json_path",
                    "endpoint_contract_sha256",
                    "endpoint_id",
                    "provider_authority_sha256",
                    "request_parameters_json",
                    "response_receipt_sha256",
                    "result_set_ordinal",
                    "snapshot_at",
                    *strategy_columns,
                }
            )
        )
        binding_id = f"lossless_field_binding:{source.occurrence_id}"
        evidence = {
            "schema_version": 1,
            "kind": "receipt_bound_live_lossless_field_binding",
            "binding_id": binding_id,
            "source_occurrence_id": source.occurrence_id,
            "source_occurrence_sha256": source.occurrence_sha256,
            "staging_key": _LIVE_LOSSLESS_STAGING_KEY,
            "endpoint_id": source.endpoint_id,
            "result_set_name": source.result_set_name,
            "result_set_ordinal": source.result_set_ordinal,
            "field_ordinal": source.field_ordinal,
            "provider_field_name": source.provider_field_name,
            "contract_result_set_json_path": result_set.json_path,
            "contract_field_json_path": source.source_path,
            "binding_strategy": strategy,
            "selector_columns": list(selector_columns),
            "sink_authority_sha256": sink_authority_sha256,
        }
        bindings.append(
            LosslessFieldBindingV1(
                binding_id=binding_id,
                source_occurrence_id=source.occurrence_id,
                source_occurrence_sha256=source.occurrence_sha256,
                staging_key=_LIVE_LOSSLESS_STAGING_KEY,
                endpoint_id=source.endpoint_id,
                result_set_name=source.result_set_name,
                result_set_ordinal=source.result_set_ordinal,
                field_ordinal=source.field_ordinal,
                provider_field_name=source.provider_field_name,
                contract_result_set_json_path=result_set.json_path,
                contract_field_json_path=source.source_path,
                binding_strategy=strategy,
                selector_columns=selector_columns,
                sink_authority_sha256=sink_authority_sha256,
                binding_evidence_sha256=canonical_sha256(evidence),
            )
        )
    return tuple(sorted(bindings, key=lambda item: item.binding_id))


def _compile_structural_blockers(
    sources: ProviderFieldSourceInventoryV1,
    route_bindings: RouteFieldBindingInventoryV1,
    lossless_bindings: tuple[LosslessFieldBindingV1, ...],
) -> tuple[FieldFateStructureBlockerV1, ...]:
    source_by_id = sources.by_occurrence_id
    blockers: list[FieldFateStructureBlockerV1] = []
    for source in sources.occurrences:
        if source.provenance_kind != "unverified_live_docs_field":
            continue
        evidence_sha256 = canonical_sha256(
            {
                "schema_version": 1,
                "kind": "source_authority_unavailable",
                "source_occurrence_id": source.occurrence_id,
                "source_occurrence_sha256": source.occurrence_sha256,
                "expected_authority_atom_id": source.authority_atom_id,
                "expected_authority_atom_sha256": source.authority_atom_sha256,
            }
        )
        blockers.append(
            FieldFateStructureBlockerV1(
                blocker_id=(
                    f"field_fate_blocker:source_authority_unavailable:{source.occurrence_id}"
                ),
                blocker_kind="source_authority_unavailable",
                source_occurrence_id=source.occurrence_id,
                source_occurrence_sha256=source.occurrence_sha256,
                evidence_sha256=evidence_sha256,
                resolution_requirement=_SOURCE_AUTHORITY_REQUIREMENT,
            )
        )
    lossless_bound_sources = {item.source_occurrence_id for item in lossless_bindings}
    for expansion in route_bindings.source_expansions:
        if expansion.status != "unrouted":
            continue
        if expansion.source_occurrence_id in lossless_bound_sources:
            continue
        source = source_by_id[expansion.source_occurrence_id]
        evidence_sha256 = canonical_sha256(
            {
                "schema_version": 1,
                "kind": "lossless_storage_binding_unresolved",
                "source_occurrence_id": source.occurrence_id,
                "source_occurrence_sha256": source.occurrence_sha256,
                "source_route_expansion": expansion.to_dict(),
                "staging_route_contract_sha256": (route_bindings.staging_route_contract_sha256),
                "binding_state": "no_executable_route_or_storage_sink",
            }
        )
        blockers.append(
            FieldFateStructureBlockerV1(
                blocker_id=(
                    f"field_fate_blocker:lossless_storage_binding_unresolved:{source.occurrence_id}"
                ),
                blocker_kind="lossless_storage_binding_unresolved",
                source_occurrence_id=source.occurrence_id,
                source_occurrence_sha256=source.occurrence_sha256,
                evidence_sha256=evidence_sha256,
                resolution_requirement=_LOSSLESS_BINDING_REQUIREMENT,
            )
        )
    return tuple(sorted(blockers, key=lambda item: item.blocker_id))


@lru_cache(maxsize=4)
def _compile_field_fate_structure(root_key: str | None) -> FieldFateStructureV1:
    """Return the canonical joined structural contract."""

    provider_sources = _compile_provider_field_source_inventory(root_key)
    route_bindings = _compile_route_field_binding_inventory(root_key)
    storage_sinks = _compile_storage_sink_inventory(root_key)
    lossless_bindings = _compile_lossless_field_bindings(provider_sources, route_bindings)
    return FieldFateStructureV1(
        provider_sources=provider_sources,
        route_bindings=route_bindings,
        storage_sinks=storage_sinks,
        lossless_bindings=lossless_bindings,
        blockers=_compile_structural_blockers(
            provider_sources,
            route_bindings,
            lossless_bindings,
        ),
    )


def compile_field_fate_structure(
    upstream_root: Path | str | None = None,
) -> FieldFateStructureV1:
    """Return the canonical structural contract and all open field-level blockers."""

    return _compile_field_fate_structure(_upstream_root_key(upstream_root))


def validate_field_fate_structure(
    structure: FieldFateStructureV1,
    upstream_root: Path | str | None = None,
) -> None:
    """Fail closed unless ``structure`` equals the exact current structural contract."""

    if type(structure) is not FieldFateStructureV1:
        raise FieldFateStructureError("field-fate structure has a foreign concrete type")
    expected = compile_field_fate_structure(upstream_root)
    if structure.identity_sha256 != expected.identity_sha256 or structure != expected:
        raise FieldFateStructureError("field-fate structure differs from current authorities")
