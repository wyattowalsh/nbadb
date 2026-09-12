from __future__ import annotations

import hashlib
import json
import pickle
from collections import Counter
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.contracts.staging_route_contract import (
    StagingRouteContract,
    staging_route_contract_bundle,
)
from nbadb.core.nba_api_competition_identity import (
    COMPETITION_IDENTITY_RESOURCE,
    CompetitionIdentityAuthority,
    CompetitionIdentityRequirement,
    CompetitionQualifiedDiscoveryGeneration,
    CompetitionQualifiedEntityIdentity,
    CompetitionQualifiedPaginationPage,
    CompetitionQualifiedPaginationSeries,
    CompetitionQualifiedRequest,
    CompetitionQualifiedStagingOccurrence,
    CompetitionQualifiedTerminalObservation,
    CompetitionQualifiedUnavailableEvidence,
    CompetitionRoleBinding,
    NbaApiCompetitionIdentityError,
    bind_explicit_competition_request,
    bind_receipt_root_competition_request,
    bind_static_competition_source,
    build_competition_identity_authority,
    build_competition_terminal_request_binding,
    build_pinned_competition_identity_payload,
    compile_competition_identity_requirements,
    load_pinned_competition_identity_payload,
    qualify_discovery_generation,
    qualify_entity_identity,
    qualify_pagination_page,
    qualify_pagination_series,
    qualify_staging_occurrence,
    qualify_terminal_observation,
    qualify_unavailable_evidence,
    write_pinned_competition_identity,
)
from nbadb.core.nba_api_implicit_competition import (
    ReceiptBoundCompetitionRoot,
    pinned_implicit_competition_authority,
)
from nbadb.core.nba_api_request_surface import (
    CanonicalProviderRequest,
    RequestClosureIteration,
    RequestClosureReceipt,
    RequestExpansionEvidence,
    RequestScopeDimension,
    RequestScopeManifest,
    RequestTerminalEvidence,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_terminal_state import (
    TerminalRequestBinding,
    TypedUpstreamUnavailableEvidence,
    UpstreamUnavailableSupportAuthority,
    build_typed_upstream_unavailable_evidence,
)
from nbadb.extract.bronze import LogicalCallReceiptBinding, canonical_parameters_sha256
from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointTransaction,
    CheckpointW2AuthorityIdentity,
)
from nbadb.orchestrate.dependent_workload_contract import (
    FoundationAuthority,
    FoundationAuthorityKind,
    FoundationInputReceipt,
)
from nbadb.orchestrate.extractor_runner import (
    RequestClosureCompetitionAuthority,
    RequestClosureExecutionAuthority,
    RequestClosureLogicalCallBinding,
    RequestClosureStagingRouteAlias,
)
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.request_closure_runtime import (
    PersistedStagingReceipt,
    RequestObservation,
    ResultSetReceipt,
    RouteRequestSpecInput,
    build_authoritative_route_manifest,
)
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
)
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

if TYPE_CHECKING:
    from collections.abc import Mapping


_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_D = "d" * 64
_E = "e" * 64
_F = "f" * 64
_SOURCE_SHA = "a" * 40
_EXPECTED_PROVIDER = "e5981c0223c99ecd4a483606781d1433cc23f22b26ec71c41a3b12b9ad827085"
_LEAGUES = ("00", "01", "10", "15", "20")
_RESOURCE_PATH = (
    Path(__file__).parents[3] / "src" / "nbadb" / "contracts" / COMPETITION_IDENTITY_RESOURCE
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _checkpoint_w2_authority() -> CheckpointW2AuthorityIdentity:
    relation_counts = tuple(
        sorted(
            (table_name, 0)
            for table_name in (*PUBLIC_VALUE_AUTHORITY_TABLES, RAW_NBA_API_W2_OPERATION_TABLE)
        )
    )
    database_authority = W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=0,
        w2_source_call_admission_inventory_sha256=_A,
        raw_authority_v2_bundle_count=0,
        raw_authority_v2_bundle_inventory_sha256=_B,
        raw_authority_v2_persistence_receipt_inventory_sha256=_C,
        w2_publication_receipt_count=0,
        w2_publication_receipt_inventory_sha256=_D,
        w2_exact_six_schema_inventory_sha256=_E,
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=0,
        w2_relation_inventory_sha256=_F,
    )
    return CheckpointW2AuthorityIdentity(
        database_authority=database_authority,
        database_authority_sha256=database_authority.receipt_sha256,
        expected_call_count=0,
        expected_call_inventory_sha256="0" * 64,
        database_authority_closed=True,
    )


def _requirements() -> tuple[CompetitionIdentityRequirement, ...]:
    return compile_competition_identity_requirements()


def _requirement(
    repo_endpoint_name: str,
    league_id: str = "00",
    *,
    strategy: str | None = None,
    constructor_name: str | None = None,
) -> CompetitionIdentityRequirement:
    matches = [
        item
        for item in _requirements()
        if item.repo_endpoint_name == repo_endpoint_name
        and item.league_id == league_id
        and (strategy is None or item.role_binding.binding_strategy == strategy)
        and (constructor_name is None or item.role_binding.constructor_name == constructor_name)
    ]
    assert len(matches) == 1
    return matches[0]


def _provider_request(
    requirement: CompetitionIdentityRequirement,
    *,
    parameters: Mapping[str, object] | None = None,
) -> CanonicalProviderRequest:
    authority = pinned_request_surface_authority()
    endpoint = authority.endpoint(
        requirement.source_family,  # type: ignore[arg-type]
        requirement.provider_endpoint_id,
    )
    supplied = dict(parameters or {})
    constructor = requirement.role_binding.constructor_name
    if constructor is not None:
        supplied[constructor] = requirement.league_id
    return materialize_provider_request(
        endpoint,
        supplied,
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )


def _league_game_log_request(
    league_id: str = "00",
    *,
    counter: str | int | float = 0,
    extra: Mapping[str, object] | None = None,
) -> tuple[CompetitionIdentityRequirement, CanonicalProviderRequest, CompetitionQualifiedRequest]:
    requirement = _requirement("league_game_log", league_id)
    parameters: dict[str, object] = {
        "season": "2024-25",
        "season_type_all_star": "Regular Season",
        "counter": counter,
    }
    parameters.update(extra or {})
    provider = _provider_request(requirement, parameters=parameters)
    return requirement, provider, bind_explicit_competition_request(requirement, provider)


def _non_cursor_scope(request: CanonicalProviderRequest, cursor_name: str = "counter") -> str:
    return _digest(
        {
            "request_surface_sha256": request.request_surface_sha256,
            "source_family": request.source_family,
            "provider_endpoint_id": request.endpoint_id,
            "materialized_parameters": [
                [name, value]
                for name, value in request.materialized_parameters
                if name != cursor_name
            ],
        }
    )


def _pagination(
    request: CompetitionQualifiedRequest,
    provider: CanonicalProviderRequest,
) -> CompetitionQualifiedPaginationSeries:
    endpoint = pinned_request_surface_authority().endpoint(
        provider.source_family,
        provider.endpoint_id,
    )
    cursor = next(item for item in endpoint.parameters if item.semantic_role == "pagination_cursor")
    return qualify_pagination_series(
        request,
        provider.endpoint_id,
        cursor.occurrence_id,
        _non_cursor_scope(provider, cursor.name),
    )


def _dynamic_receipt(
    requirement: CompetitionIdentityRequirement,
    provider: CanonicalProviderRequest,
) -> ReceiptBoundCompetitionRoot:
    authority = pinned_implicit_competition_authority()
    binding = next(
        item
        for item in authority.endpoint_bindings
        if item.binding_sha256 == requirement.role_binding.root_binding_sha256
    )
    root = binding.root_requirement
    assert root.root_mode == "request_parameter"
    occurrence = next(
        item
        for item in pinned_request_surface_authority()
        .endpoint(provider.source_family, provider.endpoint_id)
        .parameters
        if item.occurrence_id == root.provider_occurrence_id
    )
    root_value = dict(provider.materialized_parameters)[occurrence.name]
    source_scope_sha256 = _digest(
        {
            "league_id": requirement.league_id,
            "physical_endpoint_key": requirement.physical_endpoint_key,
            "scope": "competition-identity-offline-test",
        }
    )
    producer_artifact_sha256 = _digest(
        {"artifact": requirement.physical_endpoint_key, "league_id": requirement.league_id}
    )
    producer_payload_sha256 = _digest(
        {"payload": provider.provider_request_sha256, "root_value": root_value}
    )
    producer_body: dict[str, object] = {
        "artifact_sha256": producer_artifact_sha256,
        "payload_sha256": producer_payload_sha256,
        "schema": "OfflineProducerReceiptV1",
        "source_request_identity_sha256": provider.provider_request_sha256,
        "source_scope_sha256": source_scope_sha256,
        "task_id": "competition-identity-offline-test",
    }
    source_request_receipt_sha256 = _digest(producer_body)
    producer_receipt = {
        **producer_body,
        "receipt_sha256": source_request_receipt_sha256,
    }
    common: dict[str, object] = {
        "competition_authority_sha256": authority.competition_authority_sha256,
        "league_id": requirement.league_id,
        "root_binding_sha256": binding.binding_sha256,
        "root_generation_sha256": source_scope_sha256,
        "root_kind": root.root_kind,
        "root_mode": root.root_mode,
        "root_value": root_value,
        "source_endpoint_id": binding.provider_endpoint_id,
        "source_request_identity_sha256": provider.provider_request_sha256,
        "source_request_receipt_sha256": source_request_receipt_sha256,
    }
    variant = {
        **common,
        "producer_artifact_sha256": producer_artifact_sha256,
        "producer_payload_sha256": producer_payload_sha256,
        "producer_receipt_sha256": source_request_receipt_sha256,
        "producer_schema": "OfflineProducerReceiptV1",
        "producer_task_id": "competition-identity-offline-test",
        "source_scope_sha256": source_scope_sha256,
        "provider_occurrence_id": root.provider_occurrence_id,
        "root_value_type": "int" if type(root_value) is int else "str",
        "source_signature_sha256": root.source_signature_sha256,
        "typed_domain_sha256": root.typed_domain_sha256,
    }
    observation = {
        **common,
        "schema": "ReceiptBoundCompetitionRootV1",
        "variant_evidence_sha256": _digest(variant),
    }
    body = {**observation, "root_observation_sha256": _digest(observation)}
    return ReceiptBoundCompetitionRoot(
        **body,
        receipt_sha256=_digest(body),
        variant_evidence=variant,
        producer_receipt=producer_receipt,
    )


def _checkpoint_transaction() -> CheckpointTransaction:
    candidate = CheckpointTransaction.candidate(
        chain_id="competition-identity-test",
        source_sha=_SOURCE_SHA,
        generation=2,
        artifact_name="full-extraction-checkpoint-competition-identity-test-iter-2",
        lane_contracts=[{"lane_id": "foundation", "coverage_units_hash": _A}],
        coverage_fingerprint=_B,
    )
    built = candidate.mark_built(
        database_sha256=_C,
        report_sha256=_D,
        w2_authority=_checkpoint_w2_authority(),
    )
    assert built.build is not None
    receipt = CheckpointArtifactReceipt(
        artifact_id=101,
        artifact_run_id=202,
        artifact_run_attempt=1,
        artifact_name=built.artifact_name,
        artifact_digest="sha256:" + _E,
        artifact_size_bytes=4096,
        database_sha256=_C,
        report_sha256=_D,
        chain_id="competition-identity-test",
        source_sha=_SOURCE_SHA,
        generation=2,
        coverage_fingerprint=_B,
        lane_inventory_sha256=built.identity.coverage.lane_inventory_sha256,
        w2_authority_identity_sha256=built.build.w2_authority.identity_sha256,
    )
    return built.mark_uploaded_verified(receipt).commit()


def _discovery_authority() -> tuple[FoundationAuthority, FoundationInputReceipt]:
    logical_parameters = {"season": "2024-25", "season_type": "Regular Season"}
    discovery = FoundationInputReceipt(
        authority_kind=FoundationAuthorityKind.DISCOVERY_GENERATION,
        table_name="stg_league_game_log",
        chunk_id=_A,
        endpoint_name="league_game_log",
        logical_call_receipt_sha256=None,
        discovery_manifest_sha256=_B,
        logical_parameters=tuple(logical_parameters.items()),
        logical_parameters_sha256=canonical_parameters_sha256(logical_parameters),
        provider_authority_sha256=_EXPECTED_PROVIDER,
        result_route_id="league_game_log:stg_league_game_log:0",
        persisted_content_sha256=_A,
        persisted_schema_sha256=_C,
        persisted_row_count=2,
    )
    authority = FoundationAuthority(
        checkpoint_transaction=_checkpoint_transaction(),
        checkpoint_report_sha256=_D,
        checkpoint_database_sha256=_C,
        discovery_artifact_id=303,
        discovery_artifact_run_id=202,
        discovery_artifact_name="full-extraction-discovery-artifacts-competition-identity-test",
        discovery_artifact_digest=_E,
        provider_authority_sha256=_EXPECTED_PROVIDER,
        source_sha=_SOURCE_SHA,
        compiler_implementation_sha256=_F,
        query_plan_sha256=_A,
        input_receipts=(discovery,),
    )
    return authority, discovery


def _league_game_log_route() -> StagingRouteContract:
    return next(
        route
        for route in staging_route_contract_bundle().routes
        if route.route_id == "league_game_log:stg_league_game_log:0"
    )


def _terminal_request_binding(
    request: CompetitionQualifiedRequest,
    provider: CanonicalProviderRequest,
    execution: RequestClosureExecutionAuthority,
) -> TerminalRequestBinding:
    assert request.provider_request_sha256 == provider.provider_request_sha256
    return execution.request_binding_for(provider.provider_request_sha256)


def _typed_unavailable_evidence(
    request_binding: TerminalRequestBinding,
) -> TypedUpstreamUnavailableEvidence:
    support_body: dict[str, object] = {
        "authority_kind": "endpoint_support_evidence",
        "authority_version": 1,
        "support_authority_sha256": _A,
        "support_cell_id": "competition_identity_support_cell",
        "support_cell_sha256": _B,
        "provider_authority_sha256": request_binding.provider_authority_sha256,
        "request_surface_sha256": request_binding.request_surface_sha256,
        "source_family": request_binding.source_family,
        "endpoint_id": request_binding.endpoint_id,
        "scope_sha256": request_binding.scope_sha256,
        "competition_scope_sha256": request_binding.competition_scope_sha256,
        "source_request_sha256": request_binding.source_request_sha256,
        "provider_request_sha256": request_binding.provider_request_sha256,
        "status": "upstream_unavailable",
        "reason_code": "declared_provider_unavailable",
        "independent_verifier_id": "competition_support_verifier_v1",
        "independent_verifier_sha256": _C,
    }
    support_body["support_binding_sha256"] = _digest(
        {
            "domain": "nbadb.nba-api.upstream-unavailable-support.v1",
            "payload": support_body,
        }
    )
    support = UpstreamUnavailableSupportAuthority(
        **support_body  # type: ignore[arg-type]
    )
    return build_typed_upstream_unavailable_evidence(request_binding, support)


def _runtime_evidence(
    request: CompetitionQualifiedRequest,
    provider: CanonicalProviderRequest,
    *,
    state: str = "success_nonempty",
) -> tuple[
    RequestObservation,
    RequestClosureExecutionAuthority,
    LogicalCallReceiptBinding,
    StagingRouteContract,
    CommittedStagingChunkReceiptV2,
]:
    manifest_route_id = "competition_identity_league_game_log"
    logical_parameters = {"season": "2024-25", "season_type": "Regular Season"}
    provider_parameters = {
        name: value
        for name, value in provider.materialized_parameters
        if name in {"season", "season_type_all_star"}
    }
    manifest = build_authoritative_route_manifest(
        (
            RouteRequestSpecInput(
                route_id=manifest_route_id,
                source_family="stats",
                endpoint_id="LeagueGameLog",
                parameters=tuple(sorted(provider_parameters.items())),
                pagination_series_id="competition_identity_series",
                pagination_ordinal=0,
                pagination_terminal=True,
            ),
        )
    )
    surface = pinned_request_surface_authority()
    endpoint = surface.endpoint("stats", "LeagueGameLog")
    materialized_parameters = dict(provider.materialized_parameters)
    values_by_dependency: dict[str, dict[bytes, object]] = {}
    for parameter in endpoint.parameters:
        value = materialized_parameters[parameter.name]
        canonical_value = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        for dependency_id in parameter.dependencies:
            values_by_dependency.setdefault(dependency_id, {})[canonical_value] = value
    dimensions = tuple(
        sorted(
            (
                RequestScopeDimension(
                    dependency_id=dependency_id,
                    source_kind="competition_identity_test",
                    source_authority_sha256=_A,
                    values=tuple(values[key] for key in sorted(values)),
                )
                for dependency_id, values in values_by_dependency.items()
            ),
            key=lambda item: item.dimension_sha256,
        )
    )
    scope = RequestScopeManifest(
        request_surface_sha256=surface.surface_sha256,
        scope_id="competition_identity_test",
        seed_route_ids=(manifest_route_id,),
        dimensions=dimensions,
    )
    route = _league_game_log_route()
    logical_sha256 = canonical_parameters_sha256(logical_parameters)
    request_binding = build_competition_terminal_request_binding(
        request,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        route_ids=(manifest_route_id,),
    )
    execution = RequestClosureExecutionAuthority(
        route_manifest=manifest,
        scope=scope,
        staging_route_aliases=(RequestClosureStagingRouteAlias(manifest_route_id, route.route_id),),
        logical_calls=(
            RequestClosureLogicalCallBinding(
                endpoint_name="league_game_log",
                logical_parameters_sha256=logical_sha256,
                provider_request_sha256=provider.provider_request_sha256,
                route_ids=(manifest_route_id,),
            ),
        ),
        competition_authorities=(RequestClosureCompetitionAuthority(request, request_binding),),
    )
    logical_receipt = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=_B,
        endpoint_name="league_game_log",
        logical_parameters_sha256=logical_sha256,
        provider_authority_sha256=_EXPECTED_PROVIDER,
        result_route_ids=(route.route_id,),
    )
    result_row_count = 0 if state == "success_empty" else 2
    result_occurrence_state = "present_empty" if result_row_count == 0 else "present_nonempty"
    committed = CommittedStagingChunkReceiptV2(
        chunk_id="competition-identity-chunk",
        staging_key=route.staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=_C,
        persisted_row_count=result_row_count,
        persisted_content_sha256=_D,
        persisted_schema_sha256=_E,
        logical_call_receipt_sha256=logical_receipt.logical_call_receipt_sha256,
        provider_authority_sha256=_EXPECTED_PROVIDER,
        logical_parameters_sha256=logical_sha256,
        result_route_id=route.route_id,
    )
    result = ResultSetReceipt(
        ordinal=0,
        result_set_name="LeagueGameLog",
        occurrence_state=result_occurrence_state,
        row_count=result_row_count,
        ordered_columns_sha256=_A,
        result_set_payload_sha256=_F,
    )
    persisted = PersistedStagingReceipt(
        result_set_ordinal=0,
        result_set_name="LeagueGameLog",
        staging_key=route.staging_key,
        row_count=result_row_count,
        result_set_payload_sha256=_F,
        staging_receipt_root_sha256=committed.receipt_root_sha256,
    )
    success = state in {"success_nonempty", "success_empty"}
    has_body = success or state == "response_contract_failed"
    request_binding = _terminal_request_binding(request, provider, execution)
    typed_unavailable = (
        _typed_unavailable_evidence(request_binding) if state == "upstream_unavailable" else None
    )
    observation = RequestObservation(
        request_surface_sha256=surface.surface_sha256,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=provider.provider_request_sha256,
        source_family="stats",
        endpoint_id="LeagueGameLog",
        route_ids=(manifest_route_id,),
        request_binding=request_binding,
        state=state,
        attempt_count=(
            0 if state in {"upstream_unavailable", "contract_blocked", "unattempted"} else 1
        ),
        http_status=200 if has_body else None,
        response_body_sha256=_D if has_body else None,
        response_body_bytes=128 if has_body else None,
        parser_input_sha256=_E if has_body else None,
        pagination_termination_reason="declared_total",
        result_sets=(result,) if success else (),
        staging_receipts=(persisted,) if success else (),
        upstream_unavailable_evidence=typed_unavailable,
        reason_code=(
            "not_scheduled"
            if state == "unattempted"
            else "contract_not_modeled"
            if state == "contract_blocked"
            else None
        ),
        contract_evidence_sha256=_B if state == "contract_blocked" else None,
        failure_class=(
            "invalid_response_shape"
            if state == "response_contract_failed"
            else "transport_timeout"
            if state == "transient_failed"
            else None
        ),
        classification_input_sha256=_F if state == "unclassified" else None,
    )
    return observation, execution, logical_receipt, route, committed


def _terminal_closure(
    request: CompetitionQualifiedRequest,
    provider: CanonicalProviderRequest,
    *,
    state: str = "success_nonempty",
) -> tuple[RequestTerminalEvidence, RequestClosureReceipt]:
    observation, execution, _logical, _route, _committed = _runtime_evidence(
        request,
        provider,
        state=state,
    )
    scope = execution.scope
    surface = pinned_request_surface_authority()
    terminal = observation.to_terminal_evidence(
        pagination=(0, True, observation.pagination_termination_reason),
    )
    unit = provider.provider_request_sha256
    seed = RequestExpansionEvidence(
        evidence_id="competition_identity_seed",
        evidence_kind="seed",
        request_surface_sha256=surface.surface_sha256,
        scope_sha256=scope.scope_sha256,
        input_units=(),
        discovered_units=(unit,),
        source_values=(scope.seed_route_ids[0],),
        complete=True,
    )
    fixed = RequestExpansionEvidence(
        evidence_id="competition_identity_fixed_point",
        evidence_kind="fixed_point",
        request_surface_sha256=surface.surface_sha256,
        scope_sha256=scope.scope_sha256,
        input_units=(unit,),
        discovered_units=(),
        source_values=(),
        complete=True,
    )
    iterations = (
        RequestClosureIteration(
            iteration=0,
            request_surface_sha256=surface.surface_sha256,
            scope_sha256=scope.scope_sha256,
            input_units=(),
            new_units=(unit,),
            output_units=(unit,),
            evidence=(seed,),
        ),
        RequestClosureIteration(
            iteration=1,
            request_surface_sha256=surface.surface_sha256,
            scope_sha256=scope.scope_sha256,
            input_units=(unit,),
            new_units=(),
            output_units=(unit,),
            evidence=(fixed,),
        ),
    )
    closure = RequestClosureReceipt(
        request_surface_sha256=surface.surface_sha256,
        scope=scope,
        route_manifest=execution.route_manifest,
        bindings=execution.bindings,
        iterations=iterations,
        terminal_evidence=(terminal,),
    )
    return terminal, closure


def _qualified_values() -> tuple[object, ...]:
    requirement, provider, request = _league_game_log_request()
    series = _pagination(request, provider)
    page = qualify_pagination_page(series, request, 0, 0, _A)
    foundation, discovery_receipt = _discovery_authority()
    discovery = qualify_discovery_generation(request, foundation, discovery_receipt)
    observation, execution, logical, route, committed = _runtime_evidence(request, provider)
    terminal_evidence, terminal_closure = _terminal_closure(request, provider)
    terminal = qualify_terminal_observation(request, terminal_evidence, terminal_closure)
    unavailable_evidence, unavailable_closure = _terminal_closure(
        request,
        provider,
        state="upstream_unavailable",
    )
    unavailable = qualify_unavailable_evidence(
        request,
        unavailable_evidence,
        unavailable_closure,
    )
    staging = qualify_staging_occurrence(
        request,
        observation,
        execution,
        logical,
        route,
        committed,
    )
    entity = qualify_entity_identity(requirement, "team", "provider_integer", 1610612737)
    return (
        requirement.role_binding,
        requirement,
        request,
        series,
        page,
        discovery,
        terminal,
        unavailable,
        staging,
        entity,
        build_competition_identity_authority(),
    )


def _fresh_init_evidence(value: object) -> dict[str, object]:
    if type(value) is CompetitionQualifiedRequest:
        return {
            "requirement_evidence": value._requirement_evidence,
            "provider_request_evidence": value._provider_request_evidence,
            "root_receipt_evidence": value._root_receipt_evidence,
        }
    if type(value) is CompetitionQualifiedPaginationSeries:
        return {"request_evidence": value._request_evidence}
    if type(value) is CompetitionQualifiedPaginationPage:
        return {
            "series_evidence": value._series_evidence,
            "request_evidence": value._request_evidence,
        }
    if type(value) is CompetitionQualifiedDiscoveryGeneration:
        return {
            "request_evidence": value._request_evidence,
            "foundation_authority_evidence": value._foundation_authority_evidence,
            "discovery_receipt_evidence": value._discovery_receipt_evidence,
        }
    if type(value) is CompetitionQualifiedTerminalObservation:
        return {
            "request_evidence": value._request_evidence,
            "terminal_evidence": value._terminal_evidence,
            "closure_receipt": value._closure_receipt,
        }
    if type(value) is CompetitionQualifiedUnavailableEvidence:
        return {
            "request_evidence": value._request_evidence,
            "terminal_evidence": value._terminal_evidence,
            "closure_receipt": value._closure_receipt,
        }
    if type(value) is CompetitionQualifiedStagingOccurrence:
        return {
            "request_evidence": value._request_evidence,
            "observation_evidence": value._observation_evidence,
            "execution_authority_evidence": value._execution_authority_evidence,
            "logical_call_receipt_binding_evidence": (value._logical_call_receipt_binding_evidence),
            "route_evidence": value._route_evidence,
            "committed_receipt_evidence": value._committed_receipt_evidence,
        }
    if type(value) is CompetitionQualifiedEntityIdentity:
        return {"requirement_evidence": value._requirement_evidence}
    return {}


def _identity_field(value: object) -> str:
    return {
        CompetitionRoleBinding: "role_binding_sha256",
        CompetitionIdentityRequirement: "requirement_sha256",
        CompetitionQualifiedRequest: "source_request_sha256",
        CompetitionQualifiedPaginationSeries: "pagination_series_sha256",
        CompetitionQualifiedPaginationPage: "pagination_page_sha256",
        CompetitionQualifiedDiscoveryGeneration: "discovery_generation_sha256",
        CompetitionQualifiedTerminalObservation: "terminal_observation_sha256",
        CompetitionQualifiedUnavailableEvidence: "unavailable_evidence_sha256",
        CompetitionQualifiedStagingOccurrence: "staging_occurrence_sha256",
        CompetitionQualifiedEntityIdentity: "entity_identity_sha256",
        CompetitionIdentityAuthority: "authority_sha256",
    }[type(value)]


def test_competition_identity_authority_covers_exact_c_plus_d_denominators() -> None:
    requirements = _requirements()
    authority = build_competition_identity_authority()
    counts = Counter(item.role_binding.binding_strategy for item in requirements)

    assert len(requirements) == 815
    assert sum(item.executable for item in requirements) == 799
    assert tuple(item.requirement_id for item in requirements) == tuple(
        sorted(item.requirement_id for item in requirements)
    )
    assert len({item.requirement_id for item in requirements}) == 815
    assert counts == {
        "explicit_applicability_cell": 635,
        "receipt_bound_dynamic_root": 160,
        "fixed_static_root": 4,
        "root_not_exposed": 16,
    }
    assert authority.identity_requirements == requirements
    assert dict(authority.binding_strategy_counts) == counts
    assert all(
        item.role_binding.source_authority_sha256
        == authority.competition_applicability_authority_sha256
        for item in requirements
        if item.role_binding.binding_strategy == "explicit_applicability_cell"
    )
    assert all(
        item.role_binding.source_cell_id.startswith("alias-role:")
        for item in requirements
        if item.role_binding.binding_strategy == "explicit_applicability_cell"
    )


def test_explicit_implicit_and_static_sources_compile_typed_distinct_identities() -> None:
    explicit_requirement, explicit_provider, explicit = _league_game_log_request()
    dynamic_requirement = _requirement("live_box_score", strategy="receipt_bound_dynamic_root")
    dynamic_provider = _provider_request(
        dynamic_requirement,
        parameters={"game_id": "0022400001"},
    )
    dynamic_receipt = _dynamic_receipt(dynamic_requirement, dynamic_provider)
    dynamic = bind_receipt_root_competition_request(
        dynamic_requirement,
        dynamic_receipt,
        dynamic_provider,
    )
    static_requirement = _requirement("static_players", strategy="fixed_static_root")
    static = bind_static_competition_source(static_requirement)

    assert type(explicit_provider) is CanonicalProviderRequest
    assert explicit.provider_request_sha256 == explicit_provider.provider_request_sha256
    assert dynamic.provider_request_sha256 == dynamic_provider.provider_request_sha256
    assert dynamic.source_evidence_sha256 == dynamic_receipt.receipt_sha256
    assert static.provider_request_sha256 is None
    assert static.request_kind == "static_source"
    assert explicit_requirement.role_binding.source_cell_sha256 == explicit.source_evidence_sha256
    assert (
        len(
            {
                explicit.source_request_sha256,
                dynamic.source_request_sha256,
                static.source_request_sha256,
            }
        )
        == 3
    )


def test_unexposed_static_roots_are_non_executable_and_availability_stays_unknown() -> None:
    unexposed = [
        item for item in _requirements() if item.role_binding.binding_strategy == "root_not_exposed"
    ]
    assert len(unexposed) == 16
    assert all(not item.executable for item in unexposed)
    assert all(item.provider_availability_status == "unknown" for item in _requirements())
    assert all(item.request_terminal_state == "not_asserted" for item in _requirements())
    with pytest.raises(NbaApiCompetitionIdentityError):
        bind_static_competition_source(unexposed[0])


def test_checked_identity_resource_is_canonical_and_generated_without_drift(
    tmp_path: Path,
) -> None:
    payload = build_pinned_competition_identity_payload()
    assert len(payload) == 19
    assert payload["schema_version"] == 2
    assert payload["task_id"] == "A1.3a-repair-11"
    source_authorities = payload["source_authorities"]
    assert isinstance(source_authorities, dict)
    assert source_authorities == {
        "task_packet": {
            "path": (
                "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.3a-repair-11.json"
            ),
            "sha256": "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da",
        },
        "identity_contract": {
            "path": "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2e.json",
            "sha256": "d87507bb66d470dfec88626f8fc9c0b8484fa54dbb1244d564693414e18fc64c",
        },
        "terminal_state": {
            "path": "src/nbadb/contracts/nba_api_terminal_state_v1_11_4.json",
            "resource_sha256": ("9389644949a92046ce3e00491842c3786812cfe043d727dbbdc6b0c84d2ab867"),
            "payload_sha256": ("471f594174107ccb8f582a6ab0459a356acf9daebd75ac55464475b3df792f4d"),
            "terminal_policy_sha256": (
                "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
            ),
        },
        "request_surface": {
            "path": "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
            "resource_sha256": ("3082def2aa92b35d55107f5ce8eaf2ffa0532a0e649899d0f1180979f6144981"),
            "payload_sha256": ("b310313f41cf97cf1b8f55e01bbe95868532f3008527bf5265a985628eca9052"),
            "surface_sha256": ("ef6195829a9f1dad9f847094b79e88fae24dffc5c4df18e3d3e972f347f83733"),
            "runtime_contract_payload_sha256": (
                "7c9b59c475cff6b0b9d3619bdfe9a3849e11619980f6d15a1cafd5f269f61b3b"
            ),
            "terminal_policy_sha256": (
                "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
            ),
        },
        "competition": {
            "path": "src/nbadb/contracts/nba_api_competition_v1_11_4.json",
            "resource_sha256": ("cfb93458f5efb569995ddccaf33ae37c0c312e25e09d0649c307999ec0057c44"),
            "payload_sha256": ("1e79989c9d75d671520d868dfa4e63bc828ceb7844c64b28e7325dd11a6ce7e0"),
            "authority_sha256": (
                "61c9477221c08f4f36269c8c3050171e0ec472508a0a8ac72ddc6f42d865ef98"
            ),
        },
        "competition_applicability": {
            "path": ("src/nbadb/contracts/nba_api_competition_applicability_v1_11_4.json"),
            "resource_sha256": ("daf43b872bd301aa87f1a67b357d970b82e532890e09e7ce0e580545d09cb0aa"),
            "payload_sha256": ("c1b808dc593d5aa9aea90b02285c2cfb37dc60e60ecd988dcf944d4984a9907a"),
            "authority_sha256": (
                "867d64282d6da37b9289c191ec5396e34c2c2ca335ebc94d09329ad89619528f"
            ),
        },
        "implicit_competition": {
            "path": "src/nbadb/contracts/nba_api_implicit_competition_v1_11_4.json",
            "resource_sha256": ("ed75be5cf84df8975cc32d50b51215648896b618584ed5b3b3aedcb8b6dc2111"),
            "payload_sha256": ("9fddfad2276884b5d49dc71fca052d7285f73e046d5157427b7fb7b2fcd35ec1"),
            "authority_sha256": (
                "fe7fd7581532754b322155ad0a74fcbd4068e1ebc83fbd841fd3736e27616d97"
            ),
            "historical": True,
        },
        "implicit_supersession_proof": {
            "proof_sha256": ("72ef26235ab1ffbc3f3f339ef246151201dfa331f14444a88888eeddd94be7c5")
        },
    }
    qualified_surfaces = payload["qualified_surface_contracts"]
    assert isinstance(qualified_surfaces, list)
    assert len(qualified_surfaces) == 8
    assert payload["qualified_surface_contracts_sha256"] == (
        "d63d7842e2e68544afe6fa3eb36566f5b4f29138770fe20e76718bce9133c4b4"
    )
    raw = _RESOURCE_PATH.read_bytes()
    expected = (
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    assert raw == expected
    assert load_pinned_competition_identity_payload() == payload
    assert write_pinned_competition_identity(_RESOURCE_PATH, check=True) is True
    generated = tmp_path / COMPETITION_IDENTITY_RESOURCE
    assert write_pinned_competition_identity(generated) is False
    assert generated.read_bytes() == raw
    assert write_pinned_competition_identity(generated, check=True) is True

    for label in ("omission", "addition", "rebinding"):
        candidate = deepcopy(payload)
        candidate_authorities = candidate["source_authorities"]
        assert isinstance(candidate_authorities, dict)
        if label == "omission":
            candidate_authorities.pop("terminal_state")
        elif label == "addition":
            candidate_authorities["unexpected_authority"] = {"sha256": _A}
        else:
            terminal_authority = candidate_authorities["terminal_state"]
            assert isinstance(terminal_authority, dict)
            terminal_authority["payload_sha256"] = _A
        authority_body = dict(candidate)
        authority_body.pop("authority_sha256")
        authority_body.pop("payload_sha256")
        candidate["authority_sha256"] = _digest(authority_body)
        payload_body = dict(candidate)
        payload_body.pop("payload_sha256")
        candidate["payload_sha256"] = _digest(payload_body)
        mutated_path = tmp_path / f"source-authority-{label}.json"
        mutated_path.write_bytes(
            (
                json.dumps(
                    candidate,
                    sort_keys=True,
                    ensure_ascii=False,
                    allow_nan=False,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
        )
        with pytest.raises(NbaApiCompetitionIdentityError):
            load_pinned_competition_identity_payload(mutated_path)


def test_same_numeric_ids_stay_distinct_across_all_five_competitions() -> None:
    requirements = [_requirement("league_game_log", league) for league in _LEAGUES]
    identities = [
        qualify_entity_identity(item, "team", "provider_integer", 1610612737)
        for item in requirements
    ]
    assert {item.entity_value for item in identities} == {1610612737}
    assert len({item.competition_scope_sha256 for item in identities}) == 5
    assert len({item.entity_identity_sha256 for item in identities}) == 5
    assert len({item.requirement_sha256 for item in requirements}) == 5


def test_glalum_roles_remain_ordered_and_independent_without_cartesian_support() -> None:
    roles = [
        item
        for item in _requirements()
        if item.provider_endpoint_id == "GLAlumBoxScoreSimilarityScore"
    ]
    assert len(roles) == 10
    for league in _LEAGUES:
        league_roles = [item for item in roles if item.league_id == league]
        assert [item.role_binding.constructor_name for item in league_roles] == [
            "person1_league_id",
            "person2_league_id",
        ]
        assert league_roles[0].role_binding.temporal_companion_occurrence_ids != (
            league_roles[1].role_binding.temporal_companion_occurrence_ids
        )
        assert all(
            item.role_binding.participant_axis_binding == "same_person_temporal_companions"
            for item in league_roles
        )
        assert league_roles[0].requirement_sha256 != league_roles[1].requirement_sha256


def test_wire_provider_request_key_is_preserved_as_transport_evidence() -> None:
    requirement, provider, request = _league_game_log_request(
        extra={"direction": "DESC", "player_or_team_abbreviation": "P"}
    )
    assert dict(provider.materialized_parameters)["league_id"] == requirement.league_id
    assert "LeagueID=00" in provider.query_string
    assert request.provider_request_sha256 == provider.provider_request_sha256
    assert request.source_evidence_sha256 == requirement.role_binding.source_cell_sha256
    assert request.source_request_sha256 != provider.provider_request_sha256


def test_competition_propagates_through_every_qualified_surface() -> None:
    requirement, provider, request = _league_game_log_request()
    series = _pagination(request, provider)
    page = qualify_pagination_page(series, request, 0, 0, _A)
    foundation, discovery_receipt = _discovery_authority()
    discovery = qualify_discovery_generation(request, foundation, discovery_receipt)
    observation, execution, logical, route, committed = _runtime_evidence(request, provider)
    terminal_evidence, terminal_closure = _terminal_closure(request, provider)
    terminal = qualify_terminal_observation(request, terminal_evidence, terminal_closure)
    unavailable_evidence, unavailable_closure = _terminal_closure(
        request,
        provider,
        state="upstream_unavailable",
    )
    unavailable = qualify_unavailable_evidence(
        request,
        unavailable_evidence,
        unavailable_closure,
    )
    staging = qualify_staging_occurrence(
        request,
        observation,
        execution,
        logical,
        route,
        committed,
    )
    entity = qualify_entity_identity(requirement, "team", "provider_integer", 1610612737)

    assert series.competition_scope_sha256 == requirement.competition_scope_sha256
    assert page.source_request_sha256 == request.source_request_sha256
    assert discovery.competition_scope_sha256 == requirement.competition_scope_sha256
    assert terminal.source_request_sha256 == request.source_request_sha256
    assert unavailable.source_request_sha256 == request.source_request_sha256
    assert staging.source_request_sha256 == request.source_request_sha256
    assert entity.competition_scope_sha256 == requirement.competition_scope_sha256


def test_typed_runtime_receipts_derive_discovery_terminal_and_staging_identities() -> None:
    _requirement_value, provider, request = _league_game_log_request()
    foundation, discovery_receipt = _discovery_authority()
    discovery = qualify_discovery_generation(request, foundation, discovery_receipt)
    observation, execution, logical, route, committed = _runtime_evidence(request, provider)
    terminal_evidence, terminal_closure = _terminal_closure(request, provider)
    terminal = qualify_terminal_observation(request, terminal_evidence, terminal_closure)
    staging = qualify_staging_occurrence(
        request,
        observation,
        execution,
        logical,
        route,
        committed,
    )

    assert type(discovery) is CompetitionQualifiedDiscoveryGeneration
    assert discovery.native_period_scope_sha256 == discovery_receipt.logical_parameters_sha256
    assert discovery.row_count == discovery_receipt.persisted_row_count
    assert type(terminal) is CompetitionQualifiedTerminalObservation
    assert terminal.observation_sha256 == terminal_evidence.evidence_sha256
    assert type(staging) is CompetitionQualifiedStagingOccurrence
    assert staging.route_contract_sha256 == route.contract_sha256
    assert staging.result_ordinal == route.declared_result_set_index
    assert staging.logical_call_receipt_sha256 == logical.logical_call_receipt_sha256
    assert staging.committed_staging_receipt_sha256 == committed.receipt_root_sha256


@pytest.mark.parametrize(
    ("field_name", "hostile_value"),
    [
        ("canonical_frame_format", "arrow_ipc_stream_v1_polars"),
        ("frame_content_hash_contract", "nbadb_arrow_logical_table_sha256_v1"),
        ("frame_schema_hash_contract", "nbadb_arrow_schema_sha256_v1"),
        ("frame_schema_hash_contract", FRAME_CONTENT_HASH_CONTRACT),
    ],
    ids=["v1-format", "v1-content", "v1-schema", "foreign-schema-contract"],
)
def test_staging_occurrence_rejects_v1_or_mismatched_receipt_contract_ids(
    field_name: str,
    hostile_value: str,
) -> None:
    _requirement_value, provider, request = _league_game_log_request()
    observation, execution, logical, route, committed = _runtime_evidence(request, provider)
    hostile = copy(committed)
    object.__setattr__(hostile, field_name, hostile_value)

    with pytest.raises(
        NbaApiCompetitionIdentityError,
        match="full restart required",
    ):
        qualify_staging_occurrence(
            request,
            observation,
            execution,
            logical,
            route,
            hostile,
        )


@pytest.mark.parametrize(
    ("field_name", "delete_field"),
    [
        ("canonical_frame_format", False),
        ("frame_content_hash_contract", True),
        ("frame_schema_hash_contract", False),
    ],
    ids=["null-format", "missing-content", "null-schema"],
)
def test_staging_occurrence_rejects_missing_or_null_receipt_contract_ids(
    field_name: str,
    delete_field: bool,
) -> None:
    _requirement_value, provider, request = _league_game_log_request()
    observation, execution, logical, route, committed = _runtime_evidence(request, provider)
    hostile = copy(committed)
    if delete_field:
        object.__delattr__(hostile, field_name)
    else:
        object.__setattr__(hostile, field_name, None)

    with pytest.raises(
        NbaApiCompetitionIdentityError,
        match="scalar type drifted",
    ):
        qualify_staging_occurrence(
            request,
            observation,
            execution,
            logical,
            route,
            hostile,
        )


def test_competition_qualified_terminal_observation_binds_terminal_contract() -> None:
    _requirement_value, provider, request = _league_game_log_request()
    for state in ("success_nonempty", "success_empty"):
        evidence, closure = _terminal_closure(request, provider, state=state)
        qualified = qualify_terminal_observation(request, evidence, closure)
        assert qualified.to_dict() == {
            "source_request_sha256": request.source_request_sha256,
            "observation_sha256": evidence.evidence_sha256,
            "terminal_observation_sha256": qualified.terminal_observation_sha256,
        }
        assert closure.terminal_evidence == (evidence,)
        assert evidence.request_binding.source_request_sha256 == request.source_request_sha256

    unavailable_evidence, unavailable_closure = _terminal_closure(
        request,
        provider,
        state="upstream_unavailable",
    )
    unavailable = qualify_unavailable_evidence(
        request,
        unavailable_evidence,
        unavailable_closure,
    )
    typed = unavailable_evidence.upstream_unavailable_evidence
    assert typed is not None
    assert unavailable.to_dict() == {
        "source_request_sha256": request.source_request_sha256,
        "support_or_availability_authority_sha256": typed.unavailable_evidence_sha256,
        "unavailable_evidence_sha256": unavailable.unavailable_evidence_sha256,
    }


def test_authority_and_proof_contracts_use_exact_immutable_container_types() -> None:
    authority = build_competition_identity_authority()
    assert type(authority) is CompetitionIdentityAuthority
    assert type(authority.identity_requirements) is tuple
    assert type(authority.binding_strategy_counts) is tuple
    assert type(authority.collision_invariants) is tuple
    assert all(
        type(item) is CompetitionIdentityRequirement for item in authority.identity_requirements
    )
    assert all(
        type(item.role_binding) is CompetitionRoleBinding
        for item in authority.identity_requirements
    )
    assert [item.name for item in fields(authority)] == [
        "task_packet_sha256",
        "terminal_policy_sha256",
        "request_surface_sha256",
        "competition_authority_sha256",
        "competition_applicability_authority_sha256",
        "implicit_competition_authority_sha256",
        "implicit_supersession_proof_sha256",
        "source_inventory_inputs_sha256",
        "identity_requirements",
        "identity_requirements_sha256",
        "qualified_surface_contracts_sha256",
        "binding_strategy_counts",
        "collision_invariants",
        "authority_sha256",
    ]
    assert copy(authority) == authority
    assert deepcopy(authority) == authority
    assert pickle.loads(pickle.dumps(authority)) == authority
    with pytest.raises(FrozenInstanceError):
        authority.authority_sha256 = _A  # type: ignore[misc]

    from nbadb.core.nba_api_competition_identity_verifier import (
        IndependentCompetitionIdentityProof,
        verify_pinned_competition_identity_authority,
    )

    proof = verify_pinned_competition_identity_authority()
    assert type(proof) is IndependentCompetitionIdentityProof
    assert type(proof.findings) is tuple
    assert proof.findings == ()
    assert type(proof.finding_count) is int


def test_public_dto_constructors_copy_pickle_and_replace_paths_fail_closed() -> None:
    public_fields = {
        CompetitionRoleBinding: (
            "binding_strategy",
            "source_authority_kind",
            "source_authority_sha256",
            "source_cell_id",
            "source_cell_sha256",
            "constructor_name",
            "provider_occurrence_id",
            "wire_name",
            "temporal_companion_occurrence_ids",
            "participant_axis_binding",
            "root_binding_sha256",
            "root_kind",
            "root_mode",
            "root_state",
            "static_chain_sha256",
            "role_binding_sha256",
        ),
        CompetitionIdentityRequirement: (
            "requirement_id",
            "source_family",
            "physical_endpoint_key",
            "provider_endpoint_id",
            "repo_endpoint_name",
            "league_id",
            "symbol",
            "competition_scope_sha256",
            "role_binding",
            "executable",
            "provider_availability_status",
            "request_terminal_state",
            "requirement_sha256",
        ),
        CompetitionQualifiedRequest: (
            "competition_scope_sha256",
            "requirement_sha256",
            "role_binding_sha256",
            "request_kind",
            "source_evidence_sha256",
            "provider_request_sha256",
            "source_request_sha256",
        ),
        CompetitionQualifiedPaginationSeries: (
            "competition_scope_sha256",
            "provider_endpoint_id",
            "cursor_occurrence_id",
            "non_cursor_scope_sha256",
            "pagination_series_sha256",
        ),
        CompetitionQualifiedPaginationPage: (
            "pagination_series_sha256",
            "source_request_sha256",
            "cursor_value",
            "page_ordinal",
            "raw_wire_sha256",
            "pagination_page_sha256",
        ),
        CompetitionQualifiedDiscoveryGeneration: (
            "competition_scope_sha256",
            "native_period_scope_sha256",
            "producer_request_or_root_receipt_inventory_sha256",
            "schema_sha256",
            "row_count",
            "content_sha256",
            "discovery_generation_sha256",
        ),
        CompetitionQualifiedTerminalObservation: (
            "source_request_sha256",
            "observation_sha256",
            "terminal_observation_sha256",
        ),
        CompetitionQualifiedUnavailableEvidence: (
            "source_request_sha256",
            "support_or_availability_authority_sha256",
            "unavailable_evidence_sha256",
        ),
        CompetitionQualifiedStagingOccurrence: (
            "source_request_sha256",
            "route_contract_sha256",
            "result_ordinal",
            "logical_call_receipt_sha256",
            "committed_staging_receipt_sha256",
            "staging_occurrence_sha256",
        ),
        CompetitionQualifiedEntityIdentity: (
            "competition_scope_sha256",
            "entity_kind",
            "provider_encoding",
            "entity_value",
            "entity_identity_sha256",
        ),
        CompetitionIdentityAuthority: (
            "task_packet_sha256",
            "terminal_policy_sha256",
            "request_surface_sha256",
            "competition_authority_sha256",
            "competition_applicability_authority_sha256",
            "implicit_competition_authority_sha256",
            "implicit_supersession_proof_sha256",
            "source_inventory_inputs_sha256",
            "identity_requirements",
            "identity_requirements_sha256",
            "qualified_surface_contracts_sha256",
            "binding_strategy_counts",
            "collision_invariants",
            "authority_sha256",
        ),
    }
    for dto_type, expected_names in public_fields.items():
        assert tuple(item.name for item in fields(dto_type) if not item.name.startswith("_")) == (
            expected_names
        )

    requirement = _requirement("league_game_log")
    role = requirement.role_binding
    forged_role_body = role.to_dict()
    forged_role_body.pop("role_binding_sha256")
    forged_role_body["source_cell_id"] = (
        f"alias-role:not_a_registered_endpoint:{role.provider_occurrence_id}:"
        f"{requirement.league_id}"
    )
    with pytest.raises(NbaApiCompetitionIdentityError):
        replace(
            role,
            source_cell_id=forged_role_body["source_cell_id"],
            role_binding_sha256=_digest(forged_role_body),
        )

    forged_requirement_body = requirement.to_dict()
    forged_requirement_body.pop("requirement_sha256")
    forged_requirement_body["source_family"] = "live"
    forged_requirement_body["requirement_id"] = (
        f"competition-requirement:live:{requirement.repo_endpoint_name}:"
        f"{role.source_cell_id}:{requirement.league_id}"
    )
    with pytest.raises(NbaApiCompetitionIdentityError):
        replace(
            requirement,
            source_family="live",
            requirement_id=forged_requirement_body["requirement_id"],
            requirement_sha256=_digest(
                {
                    "domain_separator": "nbadb.nba-api.competition-scope.v1",
                    "requirement": forged_requirement_body,
                }
            ),
        )

    for value in _qualified_values():
        dto_type = type(value)
        evidence = _fresh_init_evidence(value)
        kwargs = {
            item.name: getattr(value, item.name)
            for item in fields(value)
            if item.init and not item.name.startswith("_")
        }
        rebuilt = dto_type(**kwargs, **evidence)
        assert rebuilt.to_dict() == value.to_dict()

        for transform in (copy, deepcopy, lambda item: pickle.loads(pickle.dumps(item))):
            cloned = transform(value)
            assert type(cloned) is dto_type
            assert cloned.to_dict() == value.to_dict()
            object.__setattr__(cloned, _identity_field(cloned), _A)
            with pytest.raises(NbaApiCompetitionIdentityError):
                cloned.to_dict()

        if evidence:
            with pytest.raises(ValueError):
                replace(value)
            assert replace(value, **evidence).to_dict() == value.to_dict()
        else:
            assert replace(value).to_dict() == value.to_dict()
        with pytest.raises(NbaApiCompetitionIdentityError):
            replace(value, **{_identity_field(value): _A}, **evidence)

        kwargs[_identity_field(value)] = _A
        with pytest.raises(NbaApiCompetitionIdentityError):
            dto_type(**kwargs, **evidence)


def test_self_resealed_and_private_evidence_forgeries_fail_at_consumption() -> None:
    values = _qualified_values()
    request = next(item for item in values if type(item) is CompetitionQualifiedRequest)
    series = next(item for item in values if type(item) is CompetitionQualifiedPaginationSeries)
    page = next(item for item in values if type(item) is CompetitionQualifiedPaginationPage)
    discovery = next(
        item for item in values if type(item) is CompetitionQualifiedDiscoveryGeneration
    )
    terminal = next(
        item for item in values if type(item) is CompetitionQualifiedTerminalObservation
    )
    unavailable = next(
        item for item in values if type(item) is CompetitionQualifiedUnavailableEvidence
    )
    staging = next(item for item in values if type(item) is CompetitionQualifiedStagingOccurrence)
    entity = next(item for item in values if type(item) is CompetitionQualifiedEntityIdentity)
    _foreign_requirement, _foreign_provider, foreign_request = _league_game_log_request("10")
    foreign_scope = foreign_request.competition_scope_sha256
    foreign_source_request = foreign_request.source_request_sha256

    resealed = copy(request)
    object.__setattr__(resealed, "competition_scope_sha256", foreign_scope)
    object.__setattr__(
        resealed,
        "source_request_sha256",
        _digest(
            {
                "domain_separator": "nbadb.nba-api.source-request.v1",
                "competition_scope_sha256": foreign_scope,
                "requirement_sha256": resealed.requirement_sha256,
                "role_binding_sha256": resealed.role_binding_sha256,
                "request_kind": resealed.request_kind,
                "source_evidence_sha256": resealed.source_evidence_sha256,
                "provider_request_sha256": resealed.provider_request_sha256,
            }
        ),
    )
    with pytest.raises(NbaApiCompetitionIdentityError):
        resealed.to_dict()

    resealed = copy(series)
    object.__setattr__(resealed, "competition_scope_sha256", foreign_scope)
    object.__setattr__(
        resealed,
        "pagination_series_sha256",
        _digest(
            {
                "domain_separator": "nbadb.nba-api.pagination-series.v1",
                "competition_scope_sha256": foreign_scope,
                "provider_endpoint_id": resealed.provider_endpoint_id,
                "cursor_occurrence_id": resealed.cursor_occurrence_id,
                "non_cursor_scope_sha256": resealed.non_cursor_scope_sha256,
            }
        ),
    )
    with pytest.raises(NbaApiCompetitionIdentityError):
        resealed.to_dict()

    reseal_vectors = (
        (
            page,
            "source_request_sha256",
            foreign_source_request,
            "pagination_page_sha256",
            "nbadb.nba-api.pagination-page.v1",
            (
                "pagination_series_sha256",
                "source_request_sha256",
                "cursor_value",
                "page_ordinal",
                "raw_wire_sha256",
            ),
        ),
        (
            discovery,
            "competition_scope_sha256",
            foreign_scope,
            "discovery_generation_sha256",
            "nbadb.nba-api.discovery-generation.v1",
            (
                "competition_scope_sha256",
                "native_period_scope_sha256",
                "producer_request_or_root_receipt_inventory_sha256",
                "schema_sha256",
                "row_count",
                "content_sha256",
            ),
        ),
        (
            terminal,
            "source_request_sha256",
            foreign_source_request,
            "terminal_observation_sha256",
            "nbadb.nba-api.terminal-observation.v1",
            ("source_request_sha256", "observation_sha256"),
        ),
        (
            unavailable,
            "source_request_sha256",
            foreign_source_request,
            "unavailable_evidence_sha256",
            "nbadb.nba-api.unavailable-evidence.v1",
            (
                "source_request_sha256",
                "support_or_availability_authority_sha256",
            ),
        ),
        (
            staging,
            "source_request_sha256",
            foreign_source_request,
            "staging_occurrence_sha256",
            "nbadb.nba-api.staging-occurrence.v1",
            (
                "source_request_sha256",
                "route_contract_sha256",
                "result_ordinal",
                "logical_call_receipt_sha256",
                "committed_staging_receipt_sha256",
            ),
        ),
        (
            entity,
            "competition_scope_sha256",
            foreign_scope,
            "entity_identity_sha256",
            "nbadb.nba-api.entity.v1",
            (
                "competition_scope_sha256",
                "entity_kind",
                "provider_encoding",
                "entity_value",
            ),
        ),
    )
    for value, parent_field, parent_value, digest_field, domain, body_fields in reseal_vectors:
        resealed = copy(value)
        object.__setattr__(resealed, parent_field, parent_value)
        body = {"domain_separator": domain}
        body.update({name: getattr(resealed, name) for name in body_fields})
        object.__setattr__(resealed, digest_field, _digest(body))
        with pytest.raises(NbaApiCompetitionIdentityError):
            resealed.to_dict()

    for value in values:
        private_fields = [item.name for item in fields(value) if item.name.startswith("_")]
        if not private_fields:
            continue
        forged = copy(value)
        object.__setattr__(forged, private_fields[0], object())
        with pytest.raises((NbaApiCompetitionIdentityError, AttributeError)):
            forged.to_dict()


def test_competition_identity_builder_never_sends_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("competition identity compiler attempted provider I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", network_forbidden)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", network_forbidden)
    assert len(compile_competition_identity_requirements()) == 815
    assert build_competition_identity_authority().identity_requirements_sha256
    assert build_pinned_competition_identity_payload()["payload_sha256"]


def test_qualified_children_reject_cross_endpoint_parent_and_receipt_rebinding() -> None:
    _requirement_value, provider, request = _league_game_log_request(counter=1)
    series = _pagination(request, provider)
    other_requirement, other_provider, other_request = _league_game_log_request("10", counter=1)
    assert other_requirement.competition_scope_sha256 != series.competition_scope_sha256
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_pagination_page(series, other_request, 1, 1, _A)

    foreign_requirement = _requirement("all_time_leaders_grids")
    foreign_provider = _provider_request(foreign_requirement)
    foreign_request = bind_explicit_competition_request(foreign_requirement, foreign_provider)
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_pagination_page(series, foreign_request, 1, 1, _A)

    encoded_pages: list[CompetitionQualifiedPaginationPage] = []
    for cursor in (1, 1.0, "1", "1.0"):
        _item_requirement, item_provider, item_request = _league_game_log_request(counter=cursor)
        item_series = _pagination(item_request, item_provider)
        encoded_pages.append(qualify_pagination_page(item_series, item_request, cursor, 1, _B))
    assert len({item.pagination_page_sha256 for item in encoded_pages}) == 4

    zero_pages: list[CompetitionQualifiedPaginationPage] = []
    for cursor in (0.0, -0.0):
        _item_requirement, item_provider, item_request = _league_game_log_request(counter=cursor)
        item_series = _pagination(item_request, item_provider)
        zero_pages.append(qualify_pagination_page(item_series, item_request, cursor, 0, _B))
    assert len({item.pagination_page_sha256 for item in zero_pages}) == 2

    for retained_cursor, substituted_cursor in ((0.0, -0.0), (-0.0, 0.0)):
        _item_requirement, item_provider, item_request = _league_game_log_request(
            counter=retained_cursor
        )
        item_series = _pagination(item_request, item_provider)
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_pagination_page(
                item_series,
                item_request,
                substituted_cursor,
                0,
                _B,
            )

    _string_requirement, string_provider, string_request = _league_game_log_request(counter="1")
    string_series = _pagination(string_request, string_provider)
    for coercively_equal in (1, 1.0, "1.0"):
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_pagination_page(string_series, string_request, coercively_equal, 1, _B)

    for cursor in (
        True,
        -1,
        1.5,
        float("inf"),
        float("nan"),
        "1.5",
        2_147_483_648,
        "2147483648",
        "not-a-number",
    ):
        with pytest.raises((NbaApiCompetitionIdentityError, ValueError)):
            _item_requirement, item_provider, item_request = _league_game_log_request(
                counter=cursor
            )
            item_series = _pagination(item_request, item_provider)
            qualify_pagination_page(item_series, item_request, cursor, 1, _B)

    dynamic_requirement = _requirement("live_box_score", strategy="receipt_bound_dynamic_root")
    dynamic_provider = _provider_request(
        dynamic_requirement,
        parameters={"game_id": "0022400001"},
    )
    dynamic_receipt = _dynamic_receipt(dynamic_requirement, dynamic_provider)
    dynamic_request = bind_receipt_root_competition_request(
        dynamic_requirement,
        dynamic_receipt,
        dynamic_provider,
    )
    for retained in (None, copy(dynamic_receipt), deepcopy(dynamic_receipt)):
        tampered = copy(dynamic_request)
        object.__setattr__(tampered, "_root_receipt_evidence", retained)
        if retained is not None:
            object.__setattr__(retained, "league_id", "10")
        with pytest.raises(NbaApiCompetitionIdentityError):
            tampered.to_dict()

    foreign_dynamic_requirement = _requirement(
        "live_box_score",
        "10",
        strategy="receipt_bound_dynamic_root",
    )
    foreign_dynamic_provider = _provider_request(
        foreign_dynamic_requirement,
        parameters={"game_id": "0022400001"},
    )
    foreign_dynamic_receipt = _dynamic_receipt(
        foreign_dynamic_requirement,
        foreign_dynamic_provider,
    )
    tampered = copy(dynamic_request)
    object.__setattr__(tampered, "_root_receipt_evidence", foreign_dynamic_receipt)
    with pytest.raises(NbaApiCompetitionIdentityError):
        tampered.to_dict()


def test_qualified_evidence_rejects_bare_digests_non_success_and_tampered_typed_inputs() -> None:
    _requirement_value, provider, request = _league_game_log_request()
    foundation, discovery_receipt = _discovery_authority()
    observation, execution, logical, route, committed = _runtime_evidence(request, provider)
    terminal_evidence, closure = _terminal_closure(request, provider)

    for unqualified in (_A, 0, {"legacy": "unqualified"}):
        for qualifier, args in (
            (qualify_discovery_generation, (unqualified, foundation, discovery_receipt)),
            (qualify_discovery_generation, (request, unqualified, discovery_receipt)),
            (qualify_discovery_generation, (request, foundation, unqualified)),
            (qualify_terminal_observation, (unqualified, terminal_evidence, closure)),
            (qualify_terminal_observation, (request, unqualified, closure)),
            (qualify_terminal_observation, (request, terminal_evidence, unqualified)),
            (qualify_unavailable_evidence, (unqualified, terminal_evidence, closure)),
            (qualify_unavailable_evidence, (request, unqualified, closure)),
            (qualify_unavailable_evidence, (request, terminal_evidence, unqualified)),
            (
                qualify_staging_occurrence,
                (unqualified, observation, execution, logical, route, committed),
            ),
            (
                qualify_staging_occurrence,
                (request, unqualified, execution, logical, route, committed),
            ),
            (
                qualify_staging_occurrence,
                (request, observation, unqualified, logical, route, committed),
            ),
            (
                qualify_staging_occurrence,
                (request, observation, execution, unqualified, route, committed),
            ),
            (
                qualify_staging_occurrence,
                (request, observation, execution, logical, unqualified, committed),
            ),
            (
                qualify_staging_occurrence,
                (request, observation, execution, logical, route, unqualified),
            ),
        ):
            with pytest.raises(NbaApiCompetitionIdentityError):
                qualifier(*args)

    for field_name, foreign_value in (
        ("request_surface_sha256", _A),
        ("route_manifest_sha256", _A),
        ("scope_sha256", _A),
        ("provider_request_sha256", _A),
        ("endpoint_id", "ForeignEndpoint"),
    ):
        foreign_observation = copy(observation)
        object.__setattr__(foreign_observation, field_name, foreign_value)
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_staging_occurrence(
                request,
                foreign_observation,
                execution,
                logical,
                route,
                committed,
            )

    for field_name, foreign_value in (
        ("request_surface_sha256", _A),
        ("route_manifest_sha256", _A),
        ("scope_sha256", _A),
        ("provider_request_sha256", _A),
        ("source_request_sha256", _A),
        ("endpoint_id", "ForeignEndpoint"),
    ):
        foreign_binding = copy(terminal_evidence.request_binding)
        object.__setattr__(foreign_binding, field_name, foreign_value)
        foreign_terminal = copy(terminal_evidence)
        object.__setattr__(foreign_terminal, "request_binding", foreign_binding)
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_terminal_observation(request, foreign_terminal, closure)

    for state in (
        "upstream_unavailable",
        "contract_blocked",
        "transient_failed",
        "response_contract_failed",
        "unattempted",
        "unclassified",
    ):
        failed_terminal, failed_closure = _terminal_closure(request, provider, state=state)
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_terminal_observation(request, failed_terminal, failed_closure)
        if state == "upstream_unavailable":
            assert (
                type(qualify_unavailable_evidence(request, failed_terminal, failed_closure))
                is CompetitionQualifiedUnavailableEvidence
            )
        else:
            with pytest.raises(NbaApiCompetitionIdentityError):
                qualify_unavailable_evidence(request, failed_terminal, failed_closure)
        failed, failed_execution, *_rest = _runtime_evidence(request, provider, state=state)
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_staging_occurrence(
                request,
                failed,
                failed_execution,
                logical,
                route,
                committed,
            )

    tampered_foundation = copy(foundation)
    object.__setattr__(tampered_foundation, "provider_authority_sha256", _A)
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_discovery_generation(request, tampered_foundation, discovery_receipt)

    foreign_discovery_receipt = replace(discovery_receipt, provider_authority_sha256=_A)
    foreign_foundation = replace(
        foundation,
        provider_authority_sha256=_A,
        input_receipts=(foreign_discovery_receipt,),
    )
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_discovery_generation(request, foreign_foundation, foreign_discovery_receipt)

    for league in ("01", "10", "15", "20"):
        _foreign_requirement, _foreign_provider, foreign_request = _league_game_log_request(league)
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_discovery_generation(foreign_request, foundation, discovery_receipt)

    for extra in (
        {"counter": 1},
        {"direction": "DESC"},
        {"player_or_team_abbreviation": "P"},
        {"sorter": "PTS"},
        {"date_from_nullable": "01/01/2025"},
        {"date_to_nullable": "01/02/2025"},
    ):
        _extra_requirement, _extra_provider, extra_request = _league_game_log_request(extra=extra)
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_discovery_generation(extra_request, foundation, discovery_receipt)

    foreign_execution_call = replace(execution.logical_calls[0], logical_parameters_sha256=_A)
    foreign_execution = replace(execution, logical_calls=(foreign_execution_call,))
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_staging_occurrence(
            request,
            observation,
            foreign_execution,
            logical,
            route,
            committed,
        )

    foreign_alias = RequestClosureStagingRouteAlias(
        observation.route_ids[0],
        "foreign_endpoint:stg_foreign:0",
    )
    foreign_execution = replace(execution, staging_route_aliases=(foreign_alias,))
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_staging_occurrence(
            request,
            observation,
            foreign_execution,
            logical,
            route,
            committed,
        )

    for foreign_logical in (
        replace(logical, logical_parameters_sha256=_A),
        replace(logical, provider_authority_sha256=_A),
        replace(logical, logical_call_receipt_sha256=_A),
    ):
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_staging_occurrence(
                request,
                observation,
                execution,
                foreign_logical,
                route,
                committed,
            )

    for foreign_committed in (
        replace(committed, logical_parameters_sha256=_A),
        replace(committed, provider_authority_sha256=_A),
        replace(committed, logical_call_receipt_sha256=_A),
        replace(committed, result_route_id="foreign_endpoint:stg_foreign:0"),
    ):
        with pytest.raises(NbaApiCompetitionIdentityError):
            qualify_staging_occurrence(
                request,
                observation,
                execution,
                logical,
                route,
                foreign_committed,
            )

    foreign_result = replace(observation.result_sets[0], result_set_name="ForeignResult")
    foreign_persisted = replace(observation.staging_receipts[0], result_set_name="ForeignResult")
    foreign_observation = replace(
        observation,
        result_sets=(foreign_result,),
        staging_receipts=(foreign_persisted,),
    )
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_staging_occurrence(
            request,
            foreign_observation,
            execution,
            logical,
            route,
            committed,
        )

    foreign_persisted = copy(observation.staging_receipts[0])
    object.__setattr__(foreign_persisted, "result_set_ordinal", 1)
    foreign_observation = copy(observation)
    object.__setattr__(foreign_observation, "staging_receipts", (foreign_persisted,))
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_staging_occurrence(
            request,
            foreign_observation,
            execution,
            logical,
            route,
            committed,
        )

    foreign_committed = replace(committed, persisted_row_count=3)
    foreign_persisted = replace(
        observation.staging_receipts[0],
        staging_receipt_root_sha256=foreign_committed.receipt_root_sha256,
    )
    foreign_observation = replace(observation, staging_receipts=(foreign_persisted,))
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_staging_occurrence(
            request,
            foreign_observation,
            execution,
            logical,
            route,
            foreign_committed,
        )

    foreign_persisted = replace(observation.staging_receipts[0], staging_receipt_root_sha256=_A)
    foreign_observation = replace(observation, staging_receipts=(foreign_persisted,))
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_staging_occurrence(
            request,
            foreign_observation,
            execution,
            logical,
            route,
            committed,
        )

    foreign_route = next(
        item for item in staging_route_contract_bundle().routes if item.route_id != route.route_id
    )
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_staging_occurrence(
            request,
            observation,
            execution,
            logical,
            foreign_route,
            committed,
        )

    tampered_request = copy(request)
    object.__setattr__(
        tampered_request,
        "_requirement_evidence",
        _requirement("league_game_log", "10"),
    )
    with pytest.raises(NbaApiCompetitionIdentityError):
        qualify_terminal_observation(tampered_request, terminal_evidence, closure)

    resealed = replace(
        request,
        source_request_sha256=_digest(
            {
                "domain_separator": "nbadb.nba-api.source-request.v1",
                "competition_scope_sha256": request.competition_scope_sha256,
                "requirement_sha256": request.requirement_sha256,
                "role_binding_sha256": request.role_binding_sha256,
                "request_kind": request.request_kind,
                "source_evidence_sha256": request.source_evidence_sha256,
                "provider_request_sha256": request.provider_request_sha256,
            }
        ),
        requirement_evidence=request._requirement_evidence,
        provider_request_evidence=request._provider_request_evidence,
        root_receipt_evidence=request._root_receipt_evidence,
    )
    assert resealed.to_dict() == request.to_dict()


@pytest.mark.parametrize(
    "transform",
    [copy, deepcopy, lambda value: pickle.loads(pickle.dumps(value))],
)
def test_copied_qualified_values_revalidate_private_evidence(
    transform: Any,
) -> None:
    _requirement_value, provider, request = _league_game_log_request()
    series = _pagination(request, provider)
    page = qualify_pagination_page(series, request, 0, 0, _A)
    for value in (request, series, page):
        cloned = transform(value)
        assert cloned.to_dict() == value.to_dict()
        private_name = next(
            name
            for name in (
                "_requirement_evidence",
                "_request_evidence",
                "_series_evidence",
            )
            if hasattr(cloned, name)
        )
        object.__setattr__(cloned, private_name, object())
        with pytest.raises((NbaApiCompetitionIdentityError, AttributeError)):
            cloned.to_dict()
