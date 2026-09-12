"""Exact, immutable provider-to-silver contracts for every staging route.

The compiler deliberately resolves provider identities from the concrete
extractor classes and exact pinned contracts.  Endpoint aliases, schema
copies, and provider packets without static columns must all be declared by
existing repository policy; no cross-route name matching is used to make a
route resolved.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from nbadb.contracts.request_scope_storage_contract import (
    EXPECTED_REQUEST_SCOPE_STORAGE_COLUMN_COUNTS,
    EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT,
    EXPECTED_REQUEST_SCOPE_STORAGE_ROUTE_COUNT,
    RequestScopeStorageFieldV1,
    derive_request_scope_storage_fields,
    request_scope_storage_inventory_sha256,
    validate_production_request_scope_injection_policy,
)
from nbadb.core.endpoint_coverage import (
    _CLASSIFIED_NONBLOCKING_CONTRACT_UNKNOWN_RESULT_SETS,
    _ENDPOINT_ALIASES,
    _RUNTIME_CLASS_ALIASES,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    load_pinned_runtime_contract_payload,
    owned_contract_sha256,
    pinned_endpoint_contract,
    pinned_live_endpoint_contract,
    pinned_static_dataset_contract,
)
from nbadb.extract.base import _canonicalize_endpoint_column_name, _to_snake_case
from nbadb.extract.live.endpoints import LIVE_PACKET_CONTRACTS
from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.extract.registry import registry
from nbadb.orchestrate.staging_map import (
    CONDITIONAL_STAGING_KEYS,
    LOSSLESS_FALLBACK_STAGING_KEY,
    STAGING_MAP,
)
from nbadb.schemas.registry import (
    _INPUT_SCHEMA_ALIASES,
    _raw_schema_registry,
    _staging_schema_registry,
    get_input_schema,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nbadb.extract.base import BaseExtractor
    from nbadb.orchestrate.staging_map import StagingEntry
    from nbadb.schemas.base import BaseSchema

SourceFamily = Literal["stats", "live", "static"]
RouteStatus = Literal[
    "bound_provider_packet",
    "classified_provider_packet_absent",
    "classified_provider_columns_absent",
]
EndpointRole = Literal["canonical", "intentional_alias"]
StorageRole = Literal["direct", "intentional_copy", "intentional_schema_alias"]
PresencePolicy = Literal["required", "optional"]
MissingPolicy = Literal["fail_closed", "materialize_empty"]
PresentEmptyPolicy = Literal["allowed", "forbidden_by_pinned_snapshot"]
StorageMappingStatus = Literal[
    "complete",
    "lossless_payload_json",
    "declared_storage_subset",
    "provider_columns_absent",
]

# The executable route registry is the authority.  Keeping a second literal
# count here made a valid additive static-dataset route fail compilation before
# its identity and schema could be audited.
EXPECTED_STAGING_ROUTE_COUNT = len(STAGING_MAP)
_PROVIDER_RUNTIME_PREFIXES = (
    "nba_api.stats.endpoints.",
    "nba_api.live.nba.endpoints.",
)
_STATIC_COLUMN_TRANSFORMS: Mapping[tuple[str, str], tuple[str, str]] = MappingProxyType(
    {
        ("static_teams", "championship_year"): (
            "championship_years_json",
            "list_to_canonical_json",
        ),
        ("static_wnba_teams", "championship_year"): (
            "championship_years_json",
            "list_to_canonical_json",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class RouteColumnMapping:
    """One explicit provider-field to canonical/storage-field decision."""

    provider_column: str
    canonical_column: str
    storage_column: str | None
    transform: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_column": self.provider_column,
            "canonical_column": self.canonical_column,
            "storage_column": self.storage_column,
            "transform": self.transform,
        }


@dataclass(frozen=True, slots=True)
class StagingRouteContract:
    """One immutable contract in exact ``STAGING_MAP`` order."""

    route_id: str
    ordinal: int
    endpoint_name: str
    canonical_endpoint_name: str
    endpoint_role: EndpointRole
    endpoint_alias_target: str | None
    staging_key: str
    param_pattern: str
    source_family: SourceFamily
    provider_endpoint_id: str
    canonical_provider_endpoint_id: str
    provider_runtime_class: str
    canonical_runtime_class: str
    provider_runtime_module: str
    provider_endpoint_slug: str
    provider_result_set_name: str | None
    provider_result_set_ordinal: int | None
    canonical_result_set_name: str | None
    canonical_result_set_ordinal: int
    declared_result_set_index: int
    use_multi: bool
    provider_columns: tuple[str, ...]
    canonical_columns: tuple[str, ...]
    storage_columns: tuple[str, ...]
    request_scope_storage_fields: tuple[RequestScopeStorageFieldV1, ...]
    column_mappings: tuple[RouteColumnMapping, ...]
    canonical_columns_without_storage: tuple[str, ...]
    storage_columns_without_provider: tuple[str, ...]
    storage_mapping_status: StorageMappingStatus
    resolved_schema_tier: str
    resolved_schema_table: str
    resolved_schema_class: str
    storage_role: StorageRole
    storage_role_target: str | None
    provider_authority_sha256: str
    source_contract_bundle_sha256: str
    endpoint_contract_sha256: str
    provider_required_parameters: tuple[str, ...]
    provider_optional_parameters: tuple[str, ...]
    presence_policy: PresencePolicy
    missing_result_set_policy: MissingPolicy
    present_empty_policy: PresentEmptyPolicy
    classified_status: RouteStatus
    disposition_reason: str | None
    allow_missing_result_set: bool
    deprecated_after: str | None
    min_season: int | None
    season_type_capability: str
    supported_season_types: tuple[str, ...]

    @property
    def route_status(self) -> RouteStatus:
        """Compatibility name consumed by schema annotation audit rows."""

        return self.classified_status

    @property
    def possible_storage_columns(self) -> tuple[str, ...]:
        """Declared schema columns plus every possible request-derived suffix."""

        return self.storage_columns + tuple(
            item.storage_column for item in self.request_scope_storage_fields
        )

    @property
    def contract_sha256(self) -> str:
        """Return the canonical digest of this exact route-local contract."""

        return _canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "ordinal": self.ordinal,
            "endpoint_name": self.endpoint_name,
            "canonical_endpoint_name": self.canonical_endpoint_name,
            "endpoint_role": self.endpoint_role,
            "endpoint_alias_target": self.endpoint_alias_target,
            "staging_key": self.staging_key,
            "param_pattern": self.param_pattern,
            "source_family": self.source_family,
            "provider_endpoint_id": self.provider_endpoint_id,
            "canonical_provider_endpoint_id": self.canonical_provider_endpoint_id,
            "provider_runtime_class": self.provider_runtime_class,
            "canonical_runtime_class": self.canonical_runtime_class,
            "provider_runtime_module": self.provider_runtime_module,
            "provider_endpoint_slug": self.provider_endpoint_slug,
            "provider_result_set_name": self.provider_result_set_name,
            "provider_result_set_ordinal": self.provider_result_set_ordinal,
            "canonical_result_set_name": self.canonical_result_set_name,
            "canonical_result_set_ordinal": self.canonical_result_set_ordinal,
            "result_set_index": self.declared_result_set_index,
            "use_multi": self.use_multi,
            "provider_columns": list(self.provider_columns),
            "canonical_columns": list(self.canonical_columns),
            "storage_columns": list(self.storage_columns),
            "request_scope_storage_fields": [
                item.to_dict() for item in self.request_scope_storage_fields
            ],
            "possible_storage_columns": list(self.possible_storage_columns),
            "rename_mapping": [item.to_dict() for item in self.column_mappings],
            "canonical_columns_without_storage": list(self.canonical_columns_without_storage),
            "storage_columns_without_provider": list(self.storage_columns_without_provider),
            "storage_mapping_status": self.storage_mapping_status,
            "resolved_schema_tier": self.resolved_schema_tier,
            "resolved_schema_table": self.resolved_schema_table,
            "resolved_schema_class": self.resolved_schema_class,
            "storage_role": self.storage_role,
            "storage_role_target": self.storage_role_target,
            "provider_authority_sha256": self.provider_authority_sha256,
            "source_contract_bundle_sha256": self.source_contract_bundle_sha256,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_required_parameters": list(self.provider_required_parameters),
            "provider_optional_parameters": list(self.provider_optional_parameters),
            "presence_policy": self.presence_policy,
            "missing_result_set_policy": self.missing_result_set_policy,
            "present_empty_policy": self.present_empty_policy,
            "classified_status": self.classified_status,
            "route_status": self.route_status,
            "disposition_reason": self.disposition_reason,
            "allow_missing_result_set": self.allow_missing_result_set,
            "deprecated_after": self.deprecated_after,
            "min_season": self.min_season,
            "season_type_capability": self.season_type_capability,
            "supported_season_types": list(self.supported_season_types),
            "column_count": len(self.storage_columns),
            "possible_column_count": len(self.possible_storage_columns),
        }


@dataclass(frozen=True, slots=True)
class StagingRouteContractBundle:
    """Immutable route sequence plus its exact-source identity."""

    routes: tuple[StagingRouteContract, ...]
    digest: str
    provider_authority_sha256: str
    pinned_contract_payload_sha256: str
    source_family_counts: tuple[tuple[str, int], ...]
    status_counts: tuple[tuple[str, int], ...]
    endpoint_role_counts: tuple[tuple[str, int], ...]
    storage_role_counts: tuple[tuple[str, int], ...]
    storage_mapping_status_counts: tuple[tuple[str, int], ...]
    request_scope_storage_sha256: str
    request_scope_storage_field_count: int
    request_scope_storage_route_count: int
    request_scope_storage_column_counts: tuple[tuple[str, int], ...]
    _by_route_id: Mapping[str, StagingRouteContract]

    @property
    def by_route_id(self) -> Mapping[str, StagingRouteContract]:
        return self._by_route_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "nbadb_staging_route_contract_bundle",
            "digest": self.digest,
            "provider_authority_sha256": self.provider_authority_sha256,
            "pinned_contract_payload_sha256": self.pinned_contract_payload_sha256,
            "summary": {
                "route_count": len(self.routes),
                "source_family_counts": dict(self.source_family_counts),
                "status_counts": dict(self.status_counts),
                "endpoint_role_counts": dict(self.endpoint_role_counts),
                "storage_role_counts": dict(self.storage_role_counts),
                "storage_mapping_status_counts": dict(self.storage_mapping_status_counts),
                "request_scope_storage_field_count": self.request_scope_storage_field_count,
                "request_scope_storage_route_count": self.request_scope_storage_route_count,
                "request_scope_storage_column_counts": dict(
                    self.request_scope_storage_column_counts
                ),
            },
            "request_scope_storage_sha256": self.request_scope_storage_sha256,
            "routes": [route.to_dict() for route in self.routes],
        }


@dataclass(frozen=True, slots=True)
class ConditionalStagingRouteAdmission:
    """One response-conditional route admitted after a captured provider response."""

    route_id: str
    endpoint_name: str
    staging_key: str
    result_set_index: int
    provider_endpoint_slug: str
    endpoint_contract_sha256: str
    provider_authority_sha256: str
    static_route_ids: tuple[str, ...]
    storage_columns: tuple[str, ...]

    @property
    def contract_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "nbadb_conditional_staging_route_admission",
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "staging_key": self.staging_key,
            "result_set_index": self.result_set_index,
            "provider_endpoint_slug": self.provider_endpoint_slug,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "static_route_ids": list(self.static_route_ids),
            "storage_columns": list(self.storage_columns),
        }


@dataclass(frozen=True, slots=True)
class ConditionalLiveStagingRouteAdmission:
    """One complete live-node route admitted after a captured live response."""

    route_id: str
    endpoint_name: str
    staging_key: str
    result_set_index: int
    provider_endpoint_id: str
    provider_endpoint_slug: str
    endpoint_contract_sha256: str
    provider_authority_sha256: str
    static_route_ids: tuple[str, ...]
    storage_columns: tuple[str, ...]
    request_parameter_mapping: tuple[tuple[str, str], ...]

    @property
    def expected_result_set_count(self) -> int:
        return self.result_set_index

    @property
    def contract_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    def logical_parameters_sha256(self, request_parameters_json: str) -> str:
        """Map exact provider query names back to the logical request scope."""

        from nbadb.extract.bronze import canonical_parameters_sha256

        try:
            provider_parameters = json.loads(request_parameters_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("live conditional request parameters are invalid JSON") from exc
        by_query_name = {
            query_name: logical_name for logical_name, query_name in self.request_parameter_mapping
        }
        if (
            not isinstance(provider_parameters, dict)
            or any(not isinstance(key, str) for key in provider_parameters)
            or set(provider_parameters) != set(by_query_name)
        ):
            raise ValueError("live conditional request parameters differ from its contract")
        return canonical_parameters_sha256(
            {by_query_name[query_name]: value for query_name, value in provider_parameters.items()}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "nbadb_conditional_live_staging_route_admission",
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "staging_key": self.staging_key,
            "result_set_index": self.result_set_index,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_endpoint_slug": self.provider_endpoint_slug,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "static_route_ids": list(self.static_route_ids),
            "storage_columns": list(self.storage_columns),
            "request_parameter_mapping": [list(item) for item in self.request_parameter_mapping],
        }


type KnownConditionalStagingRouteAdmission = (
    ConditionalStagingRouteAdmission | ConditionalLiveStagingRouteAdmission
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_class_for_extractor(extractor_cls: type[BaseExtractor]) -> type:
    """Resolve the exact provider class referenced by one concrete extractor."""

    module = importlib.import_module(extractor_cls.__module__)
    candidates: dict[tuple[str, str], type] = {}
    for value in extractor_cls.__dict__.values():
        function = value.__func__ if isinstance(value, (classmethod, staticmethod)) else value
        code = getattr(function, "__code__", None)
        if code is None:
            continue
        for name in code.co_names:
            candidate = getattr(module, name, None)
            if not isinstance(candidate, type) or not candidate.__module__.startswith(
                _PROVIDER_RUNTIME_PREFIXES
            ):
                continue
            candidates[(candidate.__module__, candidate.__name__)] = candidate
    if len(candidates) != 1:
        identities = ", ".join(f"{module}.{name}" for module, name in sorted(candidates))
        raise ValueError(
            f"{extractor_cls.endpoint_name} must reference exactly one provider runtime class; "
            f"found [{identities}]"
        )
    return next(iter(candidates.values()))


def _resolved_schema(
    entry: StagingEntry,
) -> tuple[type[BaseSchema], str, str, StorageRole, str | None]:
    schema_cls = get_input_schema(entry.staging_key)
    if schema_cls is None:
        raise ValueError(f"{entry.staging_key} has no exact input schema")

    tier: str | None = None
    table: str | None = None
    for candidate_table, candidate_cls in _staging_schema_registry().items():
        if candidate_cls is schema_cls:
            tier, table = "staging", candidate_table
            break
    if table is None:
        for candidate_table, candidate_cls in _raw_schema_registry().items():
            if candidate_cls is schema_cls:
                tier, table = "raw", candidate_table
                break
    if tier is None or table is None:
        raise ValueError(f"{entry.staging_key} resolved outside the schema registries")

    target = _INPUT_SCHEMA_ALIASES.get(entry.staging_key)
    if table == entry.staging_key:
        if target is None:
            return schema_cls, tier, table, "direct", None
        # Some copy-family routes now have their own concrete schema while the
        # explicit historical copy target is intentionally retained.  Preserve
        # that provenance instead of allowing direct registry precedence to
        # erase the declared relationship.
        staging_keys = {item.staging_key for item in STAGING_MAP}
        role: StorageRole = (
            "intentional_copy" if target in staging_keys else "intentional_schema_alias"
        )
        return schema_cls, tier, table, role, target
    if target is None:
        raise ValueError(f"{entry.staging_key} uses an undeclared schema alias")
    if target != table:
        raise ValueError(f"{entry.staging_key} schema alias target drifted from its registry")
    staging_keys = {item.staging_key for item in STAGING_MAP}
    role: StorageRole = "intentional_copy" if target in staging_keys else "intentional_schema_alias"
    return schema_cls, tier, table, role, target


def _column_mapping(
    provider_columns: Sequence[str],
    canonical_columns: Sequence[str],
    storage_columns: tuple[str, ...],
    *,
    transforms: Mapping[str, str] | None = None,
) -> tuple[RouteColumnMapping, ...]:
    if len(provider_columns) != len(canonical_columns):
        raise ValueError("provider and canonical column orders differ in width")
    storage = set(storage_columns)
    mappings: list[RouteColumnMapping] = []
    for provider, canonical in zip(provider_columns, canonical_columns, strict=True):
        mappings.append(
            RouteColumnMapping(
                provider_column=provider,
                canonical_column=canonical,
                storage_column=canonical if canonical in storage else None,
                transform=(transforms or {}).get(
                    provider,
                    "identity" if provider == canonical else "rename",
                ),
            )
        )
    return tuple(mappings)


def _route_columns(
    *,
    source_family: SourceFamily,
    endpoint_name: str,
    runtime_class_name: str,
    result_set_index: int,
    provider_columns: tuple[str, ...],
    storage_columns: tuple[str, ...],
    live_projections: tuple[tuple[str, str], ...] = (),
) -> tuple[tuple[str, ...], tuple[RouteColumnMapping, ...]]:
    if source_family == "stats":
        canonical = tuple(
            _canonicalize_endpoint_column_name(
                runtime_class_name,
                result_set_index,
                column,
            )
            for column in provider_columns
        )
        return canonical, _column_mapping(provider_columns, canonical, storage_columns)

    if source_family == "live":
        canonical_list = [_to_snake_case(column) for column in provider_columns]
        mappings = list(_column_mapping(provider_columns, canonical_list, storage_columns))
        if "payload_json" in storage_columns:
            mappings = [
                RouteColumnMapping(
                    provider_column=mapping.provider_column,
                    canonical_column=mapping.canonical_column,
                    storage_column="payload_json",
                    transform="payload_json_record",
                )
                if mapping.storage_column is None
                else mapping
                for mapping in mappings
            ]
        for source_path, target_column in live_projections:
            if target_column not in canonical_list:
                canonical_list.append(target_column)
            mappings.append(
                RouteColumnMapping(
                    provider_column=source_path,
                    canonical_column=target_column,
                    storage_column=(
                        target_column if target_column in set(storage_columns) else None
                    ),
                    transform="nested_projection",
                )
            )
        return tuple(canonical_list), tuple(mappings)

    transform_targets = {
        provider: target
        for (dataset_id, provider), (target, _kind) in _STATIC_COLUMN_TRANSFORMS.items()
        if dataset_id == endpoint_name
    }
    transforms = {
        provider: kind
        for (dataset_id, provider), (_target, kind) in _STATIC_COLUMN_TRANSFORMS.items()
        if dataset_id == endpoint_name
    }
    canonical = tuple(transform_targets.get(column, column) for column in provider_columns)
    return canonical, _column_mapping(
        provider_columns,
        canonical,
        storage_columns,
        transforms=transforms,
    )


def _stats_route_source(
    entry: StagingEntry,
    runtime_cls: type,
) -> dict[str, Any]:
    contract = pinned_endpoint_contract(runtime_cls)
    result_index = entry.result_set_index if entry.use_multi else 0
    result_set = next(
        (item for item in contract.result_sets if item.result_set_index == result_index),
        None,
    )
    optional = tuple(
        parameter
        for parameter in contract.parameters
        if parameter not in contract.required_parameters
    )
    return {
        "source_family": "stats",
        "provider_endpoint_id": contract.runtime_class_name,
        "provider_runtime_class": contract.runtime_class_name,
        "provider_runtime_module": contract.module_name,
        "provider_endpoint_slug": contract.endpoint_slug,
        "provider_result_set_name": result_set.result_set_name if result_set else None,
        "provider_result_set_ordinal": result_set.result_set_index if result_set else None,
        "canonical_result_set_name": result_set.result_set_name if result_set else None,
        "provider_columns": result_set.expected_columns if result_set else (),
        "endpoint_contract_sha256": endpoint_contract_sha256(contract),
        "provider_required_parameters": contract.required_parameters,
        "provider_optional_parameters": optional,
        "live_projections": (),
    }


def _live_route_source(entry: StagingEntry, runtime_cls: type) -> dict[str, Any]:
    contract = pinned_live_endpoint_contract(runtime_cls)
    packets = tuple(
        packet for packet in LIVE_PACKET_CONTRACTS if packet.staging_key == entry.staging_key
    )
    if len(packets) != 1:
        raise ValueError(f"{entry.staging_key} must have exactly one live packet contract")
    packet = packets[0]
    if packet.upstream_endpoint != contract.endpoint_id:
        raise ValueError(f"{entry.staging_key} live endpoint identity drifted")
    result_set = packet.provider_result_set
    required = tuple(parameter.name for parameter in contract.parameters if parameter.required)
    optional = tuple(parameter.name for parameter in contract.parameters if not parameter.required)
    return {
        "source_family": "live",
        "provider_endpoint_id": contract.endpoint_id,
        "provider_runtime_class": contract.endpoint_id,
        "provider_runtime_module": contract.runtime_module,
        "provider_endpoint_slug": contract.endpoint_slug,
        "provider_result_set_name": result_set.name,
        "provider_result_set_ordinal": result_set.ordinal,
        "canonical_result_set_name": packet.source_endpoint,
        "provider_columns": tuple(field.name for field in result_set.fields),
        "endpoint_contract_sha256": owned_contract_sha256(contract),
        "provider_required_parameters": required,
        "provider_optional_parameters": optional,
        "live_projections": packet.typed_projections,
    }


def _static_route_source(entry: StagingEntry) -> dict[str, Any]:
    contract = pinned_static_dataset_contract(entry.endpoint_name)
    return {
        "source_family": "static",
        "provider_endpoint_id": contract.dataset_id,
        "provider_runtime_class": contract.getter_name,
        "provider_runtime_module": contract.provider_module,
        "provider_endpoint_slug": contract.source_symbol,
        "provider_result_set_name": f"{contract.source_symbol}_shape_1",
        "provider_result_set_ordinal": 0,
        "canonical_result_set_name": f"{contract.source_symbol}_shape_1",
        "provider_columns": tuple(field.name for field in contract.raw_fields),
        "endpoint_contract_sha256": owned_contract_sha256(contract),
        "provider_required_parameters": (),
        "provider_optional_parameters": (),
        "live_projections": (),
    }


def _classified_status(
    entry: StagingEntry,
    provider_result_set_name: str | None,
    provider_columns: tuple[str, ...],
) -> tuple[RouteStatus, str | None]:
    if provider_result_set_name is not None and provider_columns:
        return "bound_provider_packet", None
    key = (entry.endpoint_name, entry.staging_key, entry.result_set_index)
    reason = _CLASSIFIED_NONBLOCKING_CONTRACT_UNKNOWN_RESULT_SETS.get(key)
    if reason is None:
        raise ValueError(f"{entry.endpoint_name}:{entry.staging_key} lacks provider packet policy")
    status: RouteStatus = (
        "classified_provider_packet_absent"
        if provider_result_set_name is None
        else "classified_provider_columns_absent"
    )
    return status, reason


def _bundle_digest_payload(
    routes: Sequence[StagingRouteContract],
    *,
    provider_authority_sha256: str,
    pinned_contract_payload_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "nbadb_staging_route_contract_bundle",
        "provider_authority_sha256": provider_authority_sha256,
        "pinned_contract_payload_sha256": pinned_contract_payload_sha256,
        "routes": [route.to_dict() for route in routes],
    }


def _make_bundle(routes: Sequence[StagingRouteContract]) -> StagingRouteContractBundle:
    route_tuple = tuple(routes)
    authority = expected_nba_api_provider_authority()["authority_sha256"]
    payload_digest = load_pinned_runtime_contract_payload()["payload_sha256"]
    digest = _canonical_sha256(
        _bundle_digest_payload(
            route_tuple,
            provider_authority_sha256=authority,
            pinned_contract_payload_sha256=payload_digest,
        )
    )
    request_scope_route_fields = tuple(
        (route.route_id, route.request_scope_storage_fields) for route in route_tuple
    )
    request_scope_fields = tuple(
        item for route in route_tuple for item in route.request_scope_storage_fields
    )
    return StagingRouteContractBundle(
        routes=route_tuple,
        digest=digest,
        provider_authority_sha256=authority,
        pinned_contract_payload_sha256=payload_digest,
        source_family_counts=tuple(
            sorted(Counter(route.source_family for route in route_tuple).items())
        ),
        status_counts=tuple(
            sorted(Counter(route.classified_status for route in route_tuple).items())
        ),
        endpoint_role_counts=tuple(
            sorted(Counter(route.endpoint_role for route in route_tuple).items())
        ),
        storage_role_counts=tuple(
            sorted(Counter(route.storage_role for route in route_tuple).items())
        ),
        storage_mapping_status_counts=tuple(
            sorted(Counter(route.storage_mapping_status for route in route_tuple).items())
        ),
        request_scope_storage_sha256=request_scope_storage_inventory_sha256(
            request_scope_route_fields
        ),
        request_scope_storage_field_count=len(request_scope_fields),
        request_scope_storage_route_count=sum(
            bool(route.request_scope_storage_fields) for route in route_tuple
        ),
        request_scope_storage_column_counts=tuple(
            sorted(Counter(item.storage_column for item in request_scope_fields).items())
        ),
        _by_route_id=MappingProxyType({route.route_id: route for route in route_tuple}),
    )


def _compile_staging_route_contract_bundle() -> StagingRouteContractBundle:
    validate_production_request_scope_injection_policy()
    registry.discover()
    pinned_payload = load_pinned_runtime_contract_payload()
    family_bundle_digests = {
        "stats": pinned_payload["contracts_sha256"],
        "live": pinned_payload["live_contracts_sha256"],
        "static": pinned_payload["static_contracts_sha256"],
    }
    authority_digest = expected_nba_api_provider_authority()["authority_sha256"]
    routes: list[StagingRouteContract] = []

    for ordinal, entry in enumerate(STAGING_MAP):
        extractor_cls = registry.get(entry.endpoint_name)
        if extractor_cls.category == "static":
            source = _static_route_source(entry)
        else:
            runtime_cls = _runtime_class_for_extractor(extractor_cls)
            source = (
                _live_route_source(entry, runtime_cls)
                if extractor_cls.category == "live"
                else _stats_route_source(entry, runtime_cls)
            )
        runtime_class_name = str(source["provider_runtime_class"])

        schema_cls, schema_tier, schema_table, storage_role, storage_target = _resolved_schema(
            entry
        )
        storage_columns = tuple(schema_cls.to_schema().columns)
        provider_columns = tuple(source["provider_columns"])
        canonical_columns, column_mappings = _route_columns(
            source_family=source["source_family"],
            endpoint_name=entry.endpoint_name,
            runtime_class_name=runtime_class_name,
            result_set_index=entry.result_set_index if entry.use_multi else 0,
            provider_columns=provider_columns,
            storage_columns=storage_columns,
            live_projections=tuple(source["live_projections"]),
        )
        route_id = f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
        request_scope_storage_fields = derive_request_scope_storage_fields(
            route_id=route_id,
            source_family=source["source_family"],
            provider_required_parameters=tuple(source["provider_required_parameters"]),
            provider_optional_parameters=tuple(source["provider_optional_parameters"]),
            canonical_columns=canonical_columns,
            declared_storage_columns=storage_columns,
        )
        mapped_storage = {
            mapping.storage_column
            for mapping in column_mappings
            if mapping.storage_column is not None
        }
        canonical_columns_without_storage = tuple(
            mapping.canonical_column
            for mapping in column_mappings
            if mapping.storage_column is None
        )
        if not provider_columns:
            storage_mapping_status: StorageMappingStatus = "provider_columns_absent"
        elif canonical_columns_without_storage:
            storage_mapping_status = "declared_storage_subset"
        elif any(mapping.transform == "payload_json_record" for mapping in column_mappings):
            storage_mapping_status = "lossless_payload_json"
        else:
            storage_mapping_status = "complete"
        status, disposition_reason = _classified_status(
            entry,
            source["provider_result_set_name"],
            provider_columns,
        )
        endpoint_target = _ENDPOINT_ALIASES.get(entry.endpoint_name)
        endpoint_role: EndpointRole = (
            "intentional_alias" if endpoint_target is not None else "canonical"
        )
        canonical_endpoint_name = endpoint_target or entry.endpoint_name
        canonical_runtime_class = _RUNTIME_CLASS_ALIASES.get(
            runtime_class_name,
            runtime_class_name,
        )
        canonical_provider_endpoint_id = _RUNTIME_CLASS_ALIASES.get(
            str(source["provider_endpoint_id"]),
            str(source["provider_endpoint_id"]),
        )
        presence_policy: PresencePolicy = (
            "optional" if entry.allow_missing_result_set else "required"
        )
        season_type_capability = entry.season_type_capability
        if season_type_capability is None:
            raise ValueError(f"{entry.staging_key} has no season-type capability")

        routes.append(
            StagingRouteContract(
                route_id=route_id,
                ordinal=ordinal,
                endpoint_name=entry.endpoint_name,
                canonical_endpoint_name=canonical_endpoint_name,
                endpoint_role=endpoint_role,
                endpoint_alias_target=endpoint_target,
                staging_key=entry.staging_key,
                param_pattern=entry.param_pattern,
                source_family=source["source_family"],
                provider_endpoint_id=source["provider_endpoint_id"],
                canonical_provider_endpoint_id=canonical_provider_endpoint_id,
                provider_runtime_class=runtime_class_name,
                canonical_runtime_class=canonical_runtime_class,
                provider_runtime_module=source["provider_runtime_module"],
                provider_endpoint_slug=source["provider_endpoint_slug"],
                provider_result_set_name=source["provider_result_set_name"],
                provider_result_set_ordinal=source["provider_result_set_ordinal"],
                canonical_result_set_name=source["canonical_result_set_name"],
                canonical_result_set_ordinal=(entry.result_set_index if entry.use_multi else 0),
                declared_result_set_index=entry.result_set_index,
                use_multi=entry.use_multi,
                provider_columns=provider_columns,
                canonical_columns=canonical_columns,
                storage_columns=storage_columns,
                request_scope_storage_fields=request_scope_storage_fields,
                column_mappings=column_mappings,
                canonical_columns_without_storage=canonical_columns_without_storage,
                storage_columns_without_provider=tuple(
                    column for column in storage_columns if column not in mapped_storage
                ),
                storage_mapping_status=storage_mapping_status,
                resolved_schema_tier=schema_tier,
                resolved_schema_table=schema_table,
                resolved_schema_class=schema_cls.__name__,
                storage_role=storage_role,
                storage_role_target=storage_target,
                provider_authority_sha256=authority_digest,
                source_contract_bundle_sha256=family_bundle_digests[source["source_family"]],
                endpoint_contract_sha256=source["endpoint_contract_sha256"],
                provider_required_parameters=tuple(source["provider_required_parameters"]),
                provider_optional_parameters=tuple(source["provider_optional_parameters"]),
                presence_policy=presence_policy,
                missing_result_set_policy=(
                    "materialize_empty" if entry.allow_missing_result_set else "fail_closed"
                ),
                present_empty_policy=(
                    "forbidden_by_pinned_snapshot"
                    if source["source_family"] == "static"
                    else "allowed"
                ),
                classified_status=status,
                disposition_reason=disposition_reason,
                allow_missing_result_set=entry.allow_missing_result_set,
                deprecated_after=entry.deprecated_after,
                min_season=entry.min_season,
                season_type_capability=season_type_capability,
                supported_season_types=tuple(entry.supported_season_types or ()),
            )
        )

    bundle = _make_bundle(routes)
    _validate_bundle_structure(bundle)
    return bundle


def _validate_bundle_structure(bundle: StagingRouteContractBundle) -> None:
    if len(bundle.routes) != EXPECTED_STAGING_ROUTE_COUNT:
        raise ValueError("staging route contract differs from the exact executable route registry")
    if tuple(route.ordinal for route in bundle.routes) != tuple(
        range(EXPECTED_STAGING_ROUTE_COUNT)
    ):
        raise ValueError("staging route ordinals are not exact and contiguous")
    route_ids = tuple(route.route_id for route in bundle.routes)
    if len(set(route_ids)) != EXPECTED_STAGING_ROUTE_COUNT:
        raise ValueError("staging route IDs are not unique")
    if len({route.staging_key for route in bundle.routes}) != EXPECTED_STAGING_ROUTE_COUNT:
        raise ValueError("staging route keys are not unique")
    endpoint_names = {route.endpoint_name for route in bundle.routes}
    staging_keys = {route.staging_key for route in bundle.routes}
    for route in bundle.routes:
        expected_id = f"{route.endpoint_name}:{route.staging_key}:{route.declared_result_set_index}"
        if route.route_id != expected_id:
            raise ValueError("staging route ID differs from its immutable identity")
        if not route.resolved_schema_table or not route.resolved_schema_class:
            raise ValueError("staging route contains an unresolved schema")
        if route.endpoint_role == "intentional_alias" and not route.endpoint_alias_target:
            raise ValueError("intentional endpoint alias omitted its target")
        if route.endpoint_role == "canonical" and route.endpoint_alias_target is not None:
            raise ValueError("canonical endpoint unexpectedly declares an alias target")
        if (
            route.endpoint_alias_target is not None
            and route.endpoint_alias_target not in endpoint_names
        ):
            raise ValueError("intentional endpoint alias target is not a staging endpoint")
        if route.storage_role != "direct" and not route.storage_role_target:
            raise ValueError("intentional storage alias/copy omitted its target")
        if route.storage_role == "direct" and route.storage_role_target is not None:
            raise ValueError("direct storage route unexpectedly declares a target")
        if (
            route.storage_role == "intentional_copy"
            and route.storage_role_target not in staging_keys
        ):
            raise ValueError("intentional storage copy target is not a staging route")
        if route.presence_policy == "optional" and not route.allow_missing_result_set:
            raise ValueError("optional route policy disagrees with STAGING_MAP")
        if route.presence_policy == "required" and route.allow_missing_result_set:
            raise ValueError("required route policy disagrees with STAGING_MAP")
        expected_scope_fields = derive_request_scope_storage_fields(
            route_id=route.route_id,
            source_family=route.source_family,
            provider_required_parameters=route.provider_required_parameters,
            provider_optional_parameters=route.provider_optional_parameters,
            canonical_columns=route.canonical_columns,
            declared_storage_columns=route.storage_columns,
        )
        if route.request_scope_storage_fields != expected_scope_fields:
            raise ValueError("staging route request-scope storage authority drifted")
        scope_columns = tuple(item.storage_column for item in route.request_scope_storage_fields)
        if (
            len(scope_columns) != len(set(scope_columns))
            or set(scope_columns) & set(route.storage_columns)
            or route.possible_storage_columns != route.storage_columns + scope_columns
        ):
            raise ValueError("staging route request-scope storage fields overlap or reorder")
    if dict(bundle.by_route_id) != {route.route_id: route for route in bundle.routes}:
        raise ValueError("immutable route index differs from route inventory")
    expected_family_counts = tuple(
        sorted(Counter(route.source_family for route in bundle.routes).items())
    )
    expected_status_counts = tuple(
        sorted(Counter(route.classified_status for route in bundle.routes).items())
    )
    expected_endpoint_role_counts = tuple(
        sorted(Counter(route.endpoint_role for route in bundle.routes).items())
    )
    expected_storage_role_counts = tuple(
        sorted(Counter(route.storage_role for route in bundle.routes).items())
    )
    expected_storage_mapping_status_counts = tuple(
        sorted(Counter(route.storage_mapping_status for route in bundle.routes).items())
    )
    if bundle.source_family_counts != expected_family_counts:
        raise ValueError("staging route source-family counts are invalid")
    if bundle.status_counts != expected_status_counts:
        raise ValueError("staging route status counts are invalid")
    if bundle.endpoint_role_counts != expected_endpoint_role_counts:
        raise ValueError("staging route endpoint-role counts are invalid")
    if bundle.storage_role_counts != expected_storage_role_counts:
        raise ValueError("staging route storage-role counts are invalid")
    if bundle.storage_mapping_status_counts != expected_storage_mapping_status_counts:
        raise ValueError("staging route storage-mapping-status counts are invalid")
    request_scope_fields = tuple(
        item for route in bundle.routes for item in route.request_scope_storage_fields
    )
    expected_request_scope_sha256 = request_scope_storage_inventory_sha256(
        tuple((route.route_id, route.request_scope_storage_fields) for route in bundle.routes)
    )
    if (
        bundle.request_scope_storage_sha256 != expected_request_scope_sha256
        or bundle.request_scope_storage_field_count != len(request_scope_fields)
        or len(request_scope_fields) != EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT
        or bundle.request_scope_storage_route_count
        != sum(bool(route.request_scope_storage_fields) for route in bundle.routes)
        or bundle.request_scope_storage_route_count != EXPECTED_REQUEST_SCOPE_STORAGE_ROUTE_COUNT
        or bundle.request_scope_storage_column_counts
        != tuple(sorted(Counter(item.storage_column for item in request_scope_fields).items()))
        or bundle.request_scope_storage_column_counts
        != tuple(sorted(EXPECTED_REQUEST_SCOPE_STORAGE_COLUMN_COUNTS.items()))
    ):
        raise ValueError("staging route request-scope storage census drifted")
    expected_digest = _canonical_sha256(
        _bundle_digest_payload(
            bundle.routes,
            provider_authority_sha256=bundle.provider_authority_sha256,
            pinned_contract_payload_sha256=bundle.pinned_contract_payload_sha256,
        )
    )
    if bundle.digest != expected_digest:
        raise ValueError("staging route contract digest is invalid")


@lru_cache(maxsize=1)
def staging_route_contract_bundle() -> StagingRouteContractBundle:
    """Return the exact immutable executable-route silver contract."""

    return _compile_staging_route_contract_bundle()


def admit_conditional_lossless_route(
    *,
    endpoint_name: str,
    static_route_ids: tuple[str, ...],
    conditional_route_ids: tuple[str, ...],
    provider_authority_sha256: str,
) -> ConditionalStagingRouteAdmission:
    """Admit the sole fixed fallback route for one already-observed stats response.

    The caller remains responsible for invoking this only after the runner has
    verified the fallback frame's response receipt. This contract deliberately
    stays outside the immutable pre-provider route inventory.
    """

    if not isinstance(endpoint_name, str) or not endpoint_name or ":" in endpoint_name:
        raise ValueError("conditional staging endpoint name is invalid")
    if (
        type(static_route_ids) is not tuple
        or not static_route_ids
        or len(static_route_ids) != len(set(static_route_ids))
        or any(not isinstance(route_id, str) or not route_id for route_id in static_route_ids)
    ):
        raise ValueError("conditional staging admission requires unique static routes")
    if type(conditional_route_ids) is not tuple or len(conditional_route_ids) != 1:
        raise ValueError("conditional staging admission requires exactly one fallback route")
    if (
        not isinstance(provider_authority_sha256, str)
        or len(provider_authority_sha256) != 64
        or any(character not in "0123456789abcdef" for character in provider_authority_sha256)
    ):
        raise ValueError("conditional staging provider authority is invalid")

    bundle = staging_route_contract_bundle()
    if provider_authority_sha256 != bundle.provider_authority_sha256:
        raise ValueError("conditional staging provider authority differs")
    static_routes = tuple(bundle.by_route_id.get(route_id) for route_id in static_route_ids)
    if any(route is None for route in static_routes):
        raise ValueError("conditional staging static route is absent from current authority")
    resolved_static_routes = tuple(route for route in static_routes if route is not None)
    if any(
        route.endpoint_name != endpoint_name or route.source_family != "stats"
        for route in resolved_static_routes
    ):
        raise ValueError("conditional staging static route differs from its stats endpoint")

    runtime_identities = {
        (route.provider_runtime_module, route.provider_runtime_class)
        for route in resolved_static_routes
    }
    endpoint_contract_digests = {route.endpoint_contract_sha256 for route in resolved_static_routes}
    endpoint_slugs = {route.provider_endpoint_slug for route in resolved_static_routes}
    if (
        len(runtime_identities) != 1
        or len(endpoint_contract_digests) != 1
        or len(endpoint_slugs) != 1
    ):
        raise ValueError("conditional staging static routes span provider contracts")
    runtime_module, runtime_class_name = next(iter(runtime_identities))
    try:
        runtime_class = getattr(importlib.import_module(runtime_module), runtime_class_name)
        endpoint_contract = pinned_endpoint_contract(runtime_class)
    except (AttributeError, ImportError, ValueError) as exc:
        raise ValueError("conditional staging provider contract cannot be resolved") from exc
    expected_result_set_index = len(endpoint_contract.result_sets)
    expected_route_id = (
        f"{endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:{expected_result_set_index}"
    )
    conditional_route_id = conditional_route_ids[0]
    if conditional_route_id in static_route_ids or conditional_route_id != expected_route_id:
        raise ValueError("conditional staging route differs from the fixed fallback identity")

    schema_cls = get_input_schema(LOSSLESS_FALLBACK_STAGING_KEY)
    if schema_cls is None:
        raise ValueError("conditional staging fallback schema is unavailable")
    storage_columns = tuple(schema_cls.to_schema().columns)
    return ConditionalStagingRouteAdmission(
        route_id=conditional_route_id,
        endpoint_name=endpoint_name,
        staging_key=LOSSLESS_FALLBACK_STAGING_KEY,
        result_set_index=expected_result_set_index,
        provider_endpoint_slug=next(iter(endpoint_slugs)),
        endpoint_contract_sha256=next(iter(endpoint_contract_digests)),
        provider_authority_sha256=provider_authority_sha256,
        static_route_ids=static_route_ids,
        storage_columns=storage_columns,
    )


def conditional_staging_key_from_route_id(route_id: object) -> str | None:
    """Return a known conditional key only for its canonical route-ID shape."""

    if not isinstance(route_id, str):
        return None
    try:
        endpoint_name, staging_key, raw_index = route_id.rsplit(":", 2)
        result_set_index = int(raw_index)
    except (TypeError, ValueError):
        return None
    if (
        not endpoint_name
        or ":" in endpoint_name
        or staging_key not in CONDITIONAL_STAGING_KEYS
        or result_set_index < 0
        or raw_index != str(result_set_index)
    ):
        return None
    return staging_key


def admit_conditional_live_lossless_route(
    *,
    endpoint_name: str,
    static_route_ids: tuple[str, ...],
    conditional_route_ids: tuple[str, ...],
    provider_authority_sha256: str,
) -> ConditionalLiveStagingRouteAdmission:
    """Admit the fixed live-node route for one already-captured live response."""

    if not isinstance(endpoint_name, str) or not endpoint_name or ":" in endpoint_name:
        raise ValueError("conditional live staging endpoint name is invalid")
    if (
        type(static_route_ids) is not tuple
        or not static_route_ids
        or len(static_route_ids) != len(set(static_route_ids))
        or any(not isinstance(route_id, str) or not route_id for route_id in static_route_ids)
    ):
        raise ValueError("conditional live staging admission requires unique static routes")
    if type(conditional_route_ids) is not tuple or len(conditional_route_ids) != 1:
        raise ValueError("conditional live staging admission requires exactly one node route")
    if (
        not isinstance(provider_authority_sha256, str)
        or len(provider_authority_sha256) != 64
        or any(character not in "0123456789abcdef" for character in provider_authority_sha256)
    ):
        raise ValueError("conditional live staging provider authority is invalid")

    bundle = staging_route_contract_bundle()
    if provider_authority_sha256 != bundle.provider_authority_sha256:
        raise ValueError("conditional live staging provider authority differs")
    static_routes = tuple(bundle.by_route_id.get(route_id) for route_id in static_route_ids)
    if any(route is None for route in static_routes):
        raise ValueError("conditional live staging static route is absent from current authority")
    resolved_static_routes = tuple(route for route in static_routes if route is not None)
    if any(
        route.endpoint_name != endpoint_name or route.source_family != "live"
        for route in resolved_static_routes
    ):
        raise ValueError("conditional live staging route differs from its live endpoint")

    runtime_identities = {
        (route.provider_runtime_module, route.provider_runtime_class)
        for route in resolved_static_routes
    }
    endpoint_contract_digests = {route.endpoint_contract_sha256 for route in resolved_static_routes}
    endpoint_ids = {route.provider_endpoint_id for route in resolved_static_routes}
    endpoint_slugs = {route.provider_endpoint_slug for route in resolved_static_routes}
    if (
        len(runtime_identities) != 1
        or len(endpoint_contract_digests) != 1
        or len(endpoint_ids) != 1
        or len(endpoint_slugs) != 1
    ):
        raise ValueError("conditional live staging routes span provider contracts")
    runtime_module, runtime_class_name = next(iter(runtime_identities))
    try:
        runtime_class = getattr(importlib.import_module(runtime_module), runtime_class_name)
        endpoint_contract = pinned_live_endpoint_contract(runtime_class)
    except (AttributeError, ImportError, ValueError) as exc:
        raise ValueError("conditional live staging provider contract cannot be resolved") from exc
    endpoint_contract_digest = owned_contract_sha256(endpoint_contract)
    if endpoint_contract_digests != {endpoint_contract_digest}:
        raise ValueError("conditional live staging endpoint contract differs")
    expected_result_set_index = len(endpoint_contract.result_sets)
    expected_route_id = f"{endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:{expected_result_set_index}"
    conditional_route_id = conditional_route_ids[0]
    if conditional_route_id in static_route_ids or conditional_route_id != expected_route_id:
        raise ValueError("conditional live staging route differs from the fixed node identity")

    schema_cls = get_input_schema(LIVE_LOSSLESS_STAGING_KEY)
    if schema_cls is None:
        raise ValueError("conditional live staging schema is unavailable")
    return ConditionalLiveStagingRouteAdmission(
        route_id=conditional_route_id,
        endpoint_name=endpoint_name,
        staging_key=LIVE_LOSSLESS_STAGING_KEY,
        result_set_index=expected_result_set_index,
        provider_endpoint_id=next(iter(endpoint_ids)),
        provider_endpoint_slug=next(iter(endpoint_slugs)),
        endpoint_contract_sha256=endpoint_contract_digest,
        provider_authority_sha256=provider_authority_sha256,
        static_route_ids=static_route_ids,
        storage_columns=tuple(schema_cls.to_schema().columns),
        request_parameter_mapping=tuple(
            (parameter.name, parameter.query_name) for parameter in endpoint_contract.parameters
        ),
    )


def admit_known_conditional_staging_route(
    *,
    endpoint_name: str,
    static_route_ids: tuple[str, ...],
    conditional_route_ids: tuple[str, ...],
    provider_authority_sha256: str,
) -> KnownConditionalStagingRouteAdmission:
    """Dispatch one canonical conditional route to its typed authority."""

    if type(conditional_route_ids) is not tuple or len(conditional_route_ids) != 1:
        raise ValueError("known conditional admission requires exactly one route")
    staging_key = conditional_staging_key_from_route_id(conditional_route_ids[0])
    if staging_key == LOSSLESS_FALLBACK_STAGING_KEY:
        return admit_conditional_lossless_route(
            endpoint_name=endpoint_name,
            static_route_ids=static_route_ids,
            conditional_route_ids=conditional_route_ids,
            provider_authority_sha256=provider_authority_sha256,
        )
    if staging_key == LIVE_LOSSLESS_STAGING_KEY:
        return admit_conditional_live_lossless_route(
            endpoint_name=endpoint_name,
            static_route_ids=static_route_ids,
            conditional_route_ids=conditional_route_ids,
            provider_authority_sha256=provider_authority_sha256,
        )
    raise ValueError("route is not a typed known conditional staging route")


def validate_staging_route_contract_bundle(bundle: StagingRouteContractBundle) -> None:
    """Validate structure, digest, and exact equality to live pinned sources."""

    _validate_bundle_structure(bundle)
    expected = staging_route_contract_bundle()
    if bundle == expected:
        return
    for observed, current in zip(bundle.routes, expected.routes, strict=True):
        if observed.route_id != current.route_id:
            raise ValueError("staging route ID differs from the exact source")
        if observed.provider_columns != current.provider_columns:
            raise ValueError("provider column order differs from the exact source")
        if (
            observed.endpoint_role,
            observed.endpoint_alias_target,
            observed.storage_role,
            observed.storage_role_target,
        ) != (
            current.endpoint_role,
            current.endpoint_alias_target,
            current.storage_role,
            current.storage_role_target,
        ):
            raise ValueError("staging route alias/copy policy differs from the exact source")
        if (
            observed.presence_policy,
            observed.missing_result_set_policy,
            observed.present_empty_policy,
        ) != (
            current.presence_policy,
            current.missing_result_set_policy,
            current.present_empty_policy,
        ):
            raise ValueError("staging route optional/empty policy differs from the exact source")
        if observed != current:
            raise ValueError("staging route contract differs from the exact source")
    raise ValueError("staging route bundle metadata differs from the exact source")


__all__ = [
    "ConditionalLiveStagingRouteAdmission",
    "ConditionalStagingRouteAdmission",
    "EXPECTED_STAGING_ROUTE_COUNT",
    "RouteColumnMapping",
    "StagingRouteContract",
    "StagingRouteContractBundle",
    "admit_conditional_live_lossless_route",
    "admit_conditional_lossless_route",
    "admit_known_conditional_staging_route",
    "conditional_staging_key_from_route_id",
    "staging_route_contract_bundle",
    "validate_staging_route_contract_bundle",
]
