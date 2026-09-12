from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from functools import lru_cache

import pytest

from nbadb.contracts.field_fate_contract import compile_field_fate_contracts
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.contracts.temporal_availability_contract import (
    temporal_availability_contract_bundle,
)
from nbadb.core.nba_api_request_surface import (
    RequestScopeDimension,
    RequestScopeManifest,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_terminal_state import build_terminal_request_binding
from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointTransaction,
    CheckpointW2AuthorityIdentity,
)
from nbadb.orchestrate.public_value_authority_store import (
    PUBLIC_VALUE_AUTHORITY_TABLES,
)
from nbadb.orchestrate.request_closure_runtime import (
    PersistedStagingReceipt,
    RequestClosureAdapterInput,
    RequestObservation,
    ResultSetReceipt,
    RouteRequestSpecInput,
    build_authoritative_route_manifest,
    build_request_closure_runtime_receipt,
)
from nbadb.orchestrate.request_universe_generation_contract import (
    CommittedObservationGenerationV1,
    ExplicitTemporalScopeValueV1,
    FieldOccurrenceInputV1,
    LogicalRequestCallV1,
    RequestUniverseCandidateSourceV1,
    RequestUniverseFinalizationSourceV1,
    RequestUniverseShardV1,
    RouteRequestMemberV1,
    TemporalScopeKind,
    TerminalRequestClassificationV1,
    TerminalRequestDisposition,
    TerminalRequestEvidenceV1,
    compile_request_universe_candidate_generation_v1,
    compile_request_universe_v1,
)
from nbadb.orchestrate.request_universe_generation_verifier import (
    verify_request_universe_candidate_independently,
    verify_request_universe_v1_independently,
)
from nbadb.orchestrate.request_universe_source_admission import (
    RequestUniverseFinalAuthorityV1,
    RequestUniverseSourceAdmissionError,
    RequestUniverseSourceAdmissionV1,
    RequestUniverseTemporalFieldDenominatorV1,
    compile_request_universe_final_authority_v1,
    compile_request_universe_source_admission_v1,
    validate_request_universe_final_authority_v1,
    validate_request_universe_source_admission_v1,
)
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

_AUTHORITY_GENERATION = "a" * 64


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _reseal(payload: dict[str, object]) -> dict[str, object]:
    body = dict(payload)
    body.pop("admission_sha256", None)
    payload["admission_sha256"] = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    return payload


@lru_cache(maxsize=1)
def _current_source() -> RequestUniverseCandidateSourceV1:
    routes = staging_route_contract_bundle()
    fields = compile_field_fate_contracts()
    temporal = temporal_availability_contract_bundle()
    route = routes.by_route_id["league_game_log:stg_league_game_log:0"]
    route_scope = temporal.by_route_id[route.route_id]
    call = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        source_family=route.source_family,
        endpoint_name=route.endpoint_name,
        canonical_endpoint_name=route.canonical_endpoint_name,
        physical_endpoint_name=route.endpoint_name,
        parameters={"season": "2023-24"},
    )
    member = RouteRequestMemberV1.build(
        call=call,
        route_id=route.route_id,
        result_name=route.provider_result_set_name,
        result_ordinal=route.provider_result_set_ordinal,
    )
    field_occurrences = tuple(
        sorted(
            (
                FieldOccurrenceInputV1.from_current_contract(
                    authority_generation_sha256=_AUTHORITY_GENERATION,
                    field_fate_contract_sha256=fields.digest,
                    field_fate=field,
                )
                for field in fields.fields
                if field.route_id == route.route_id
            ),
            key=lambda item: item.identity_sha256,
        )
    )
    period = ExplicitTemporalScopeValueV1.from_current_contract(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        temporal_contract_sha256=temporal.digest,
        route_member=member,
        route_scope=route_scope,
        temporal_scope_kind=TemporalScopeKind.SEASON,
        temporal_scope_value="2023-24",
    )
    return RequestUniverseCandidateSourceV1(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        field_fate_contract_sha256=fields.digest,
        temporal_contract_sha256=temporal.digest,
        logical_calls=(call,),
        route_members=(member,),
        field_occurrences=field_occurrences,
        explicit_temporal_scopes=(period,),
    )


def _candidate_and_proof(source: RequestUniverseCandidateSourceV1):
    candidate = compile_request_universe_candidate_generation_v1(source)
    proof = verify_request_universe_candidate_independently(
        source_payload=source.to_dict(),
        candidate_payload=candidate.to_dict(),
    )
    return candidate, proof


def _committed_checkpoint(candidate):
    relation_counts = tuple(
        sorted(
            (
                table_name,
                1 if table_name == RAW_NBA_API_W2_OPERATION_TABLE else 0,
            )
            for table_name in (
                *PUBLIC_VALUE_AUTHORITY_TABLES,
                RAW_NBA_API_W2_OPERATION_TABLE,
            )
        )
    )
    database_authority = W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=1,
        w2_source_call_admission_inventory_sha256=_sha256("w2-admissions"),
        raw_authority_v2_bundle_count=1,
        raw_authority_v2_bundle_inventory_sha256=_sha256("w2-bundles"),
        raw_authority_v2_persistence_receipt_inventory_sha256=_sha256("w2-persistence"),
        w2_publication_receipt_count=1,
        w2_publication_receipt_inventory_sha256=_sha256("w2-publications"),
        w2_exact_six_schema_inventory_sha256=_sha256("w2-schemas"),
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=1,
        w2_relation_inventory_sha256=_sha256("w2-relations"),
    )
    w2_authority = CheckpointW2AuthorityIdentity(
        database_authority=database_authority,
        database_authority_sha256=database_authority.receipt_sha256,
        expected_call_count=len(candidate.logical_calls),
        expected_call_inventory_sha256=candidate.logical_call_inventory_sha256,
        database_authority_closed=True,
    )
    transaction = CheckpointTransaction.candidate(
        chain_id="request-universe-final",
        source_sha="a" * 40,
        generation=1,
        artifact_name="request-universe-final-checkpoint-1",
        lane_contracts=(
            {
                "lane_id": "request-universe-lane-0",
                "coverage_units_hash": "e" * 64,
            },
        ),
        coverage_fingerprint="f" * 64,
    ).mark_built(
        database_sha256="b" * 64,
        report_sha256="c" * 64,
        w2_authority=w2_authority,
    )
    assert transaction.build is not None
    receipt = CheckpointArtifactReceipt(
        artifact_id=12345,
        artifact_run_id=67890,
        artifact_run_attempt=1,
        artifact_name=transaction.artifact_name,
        artifact_digest="sha256:" + "d" * 64,
        artifact_size_bytes=4096,
        database_sha256=transaction.build.database_sha256,
        report_sha256=transaction.build.report_sha256,
        chain_id=transaction.identity.chain_id,
        source_sha=transaction.identity.source_sha,
        generation=transaction.identity.generation,
        coverage_fingerprint=transaction.identity.coverage.coverage_fingerprint,
        lane_inventory_sha256=transaction.identity.coverage.lane_inventory_sha256,
        w2_authority_identity_sha256=w2_authority.identity_sha256,
    )
    return transaction.mark_uploaded_verified(receipt).commit()


def _request_closure(source: RequestUniverseCandidateSourceV1):
    route = staging_route_contract_bundle().by_route_id[source.route_members[0].route_id]
    authority = pinned_request_surface_authority()
    endpoint = authority.endpoint(route.source_family, route.provider_endpoint_id)
    parameters = dict(source.logical_calls[0].parameter_items)
    provider_request = materialize_provider_request(
        endpoint,
        parameters,
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    manifest = build_authoritative_route_manifest(
        (
            RouteRequestSpecInput(
                route_id=route.route_id,
                source_family=route.source_family,
                endpoint_id=route.provider_endpoint_id,
                parameters=tuple(sorted(parameters.items())),
                pagination_series_id="request_universe_league_game_log",
                pagination_ordinal=0,
                pagination_terminal=True,
            ),
        )
    )
    materialized = dict(provider_request.materialized_parameters)
    dimensions = []
    for dependency in sorted(
        {dependency for parameter in endpoint.parameters for dependency in parameter.dependencies}
    ):
        values = {
            materialized[parameter.name]
            for parameter in endpoint.parameters
            if dependency in parameter.dependencies
        }
        dimensions.append(
            RequestScopeDimension(
                dependency_id=dependency,
                source_kind="request_universe_final_test",
                source_authority_sha256="b" * 64,
                values=tuple(sorted(values, key=_canonical_bytes)),
            )
        )
    scope = RequestScopeManifest(
        request_surface_sha256=authority.surface_sha256,
        scope_id="request_universe_final_test",
        seed_route_ids=(route.route_id,),
        dimensions=tuple(sorted(dimensions, key=lambda item: item.dimension_sha256)),
    )
    request_binding = build_terminal_request_binding(
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        provider_authority_sha256="a" * 64,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=provider_request.provider_request_sha256,
        source_request_sha256="b" * 64,
        competition_authority_sha256="c" * 64,
        competition_scope_sha256="d" * 64,
        competition_requirement_sha256="e" * 64,
        role_binding_sha256="f" * 64,
        source_evidence_sha256="0" * 64,
        source_family=route.source_family,
        endpoint_id=route.provider_endpoint_id,
        route_ids=(route.route_id,),
    )
    result_set = ResultSetReceipt(
        ordinal=route.provider_result_set_ordinal,
        result_set_name=route.provider_result_set_name,
        occurrence_state="present_nonempty",
        row_count=1,
        ordered_columns_sha256="1" * 64,
        result_set_payload_sha256="2" * 64,
    )
    staging = PersistedStagingReceipt(
        result_set_ordinal=route.provider_result_set_ordinal,
        result_set_name=route.provider_result_set_name,
        staging_key=route.staging_key,
        row_count=1,
        result_set_payload_sha256="2" * 64,
        staging_receipt_root_sha256="3" * 64,
    )
    observation = RequestObservation(
        request_surface_sha256=authority.surface_sha256,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=provider_request.provider_request_sha256,
        source_family=route.source_family,
        endpoint_id=route.provider_endpoint_id,
        route_ids=(route.route_id,),
        request_binding=request_binding,
        state="success_nonempty",
        attempt_count=1,
        http_status=200,
        response_body_sha256="4" * 64,
        response_body_bytes=128,
        parser_input_sha256="5" * 64,
        result_sets=(result_set,),
        staging_receipts=(staging,),
        pagination_termination_reason="declared_total",
    )
    closure = build_request_closure_runtime_receipt(
        RequestClosureAdapterInput(manifest, scope, (observation,))
    )
    return closure, observation


def _replace_final_evidence(inputs: dict[str, object], evidence):
    source = inputs["source"]
    candidate = inputs["candidate"]
    candidate_proof = inputs["candidate_proof"]
    admission = inputs["admission"]
    checkpoint = inputs["checkpoint"]
    closure = inputs["closure"]
    temporal = inputs["temporal"]
    call = source.logical_calls[0]
    generation = CommittedObservationGenerationV1(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        checkpoint_identity_sha256=_sha256(checkpoint.identity.to_dict()),
        request_closure_receipt_sha256=closure.artifact_sha256,
        w2_authority_identity_sha256=checkpoint.build.w2_authority.identity_sha256,
        temporal_field_denominator_sha256=temporal.receipt_sha256,
        closure_fixed_point_provider_request_sha256s=tuple(
            closure.closure.iterations[-1].output_units
        ),
        terminal_evidence=(evidence,),
    )
    classification = TerminalRequestClassificationV1(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        committed_observation_generation_sha256=generation.generation_sha256,
        physical_call_id=call.physical_call_id,
        request_scope_sha256=call.request_scope_sha256,
        disposition=evidence.disposition,
        evidence=evidence,
    )
    finalization_source = RequestUniverseFinalizationSourceV1(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        checkpoint_identity_sha256=_sha256(checkpoint.identity.to_dict()),
        checkpoint_authority_generation_sha256=_AUTHORITY_GENERATION,
        request_closure_receipt_sha256=closure.artifact_sha256,
        request_closure_authority_generation_sha256=_AUTHORITY_GENERATION,
        w2_authority_identity_sha256=checkpoint.build.w2_authority.identity_sha256,
        w2_authority_generation_sha256=_AUTHORITY_GENERATION,
        temporal_field_denominator_sha256=temporal.receipt_sha256,
        temporal_field_authority_generation_sha256=_AUTHORITY_GENERATION,
        committed_observation_generation_sha256=generation.generation_sha256,
        committed_observation_authority_generation_sha256=_AUTHORITY_GENERATION,
        candidate_source_sha256=source.source_inputs_sha256,
        candidate_generation_sha256=candidate.identity_sha256,
        candidate_independent_proof_sha256=candidate_proof.identity_sha256,
        source_admission_sha256=admission.admission_sha256,
        committed_observation_generation=generation,
        logical_calls=candidate.logical_calls,
        terminal_classifications=(classification,),
        shards=(
            RequestUniverseShardV1(
                authority_generation_sha256=_AUTHORITY_GENERATION,
                shard_id="request-universe-shard-0",
                physical_call_ids=(call.physical_call_id,),
            ),
        ),
    )
    universe = compile_request_universe_v1(finalization_source)
    final_proof, independent_receipt = verify_request_universe_v1_independently(
        finalization_source_payload=finalization_source.to_dict(),
        request_universe_payload=universe.to_dict(),
        request_closure_payload=closure.to_dict(),
    )
    return finalization_source, universe, final_proof, independent_receipt


@lru_cache(maxsize=1)
def _final_authority_inputs() -> dict[str, object]:
    source = _current_source()
    candidate, candidate_proof = _candidate_and_proof(source)
    admission = compile_request_universe_source_admission_v1(
        source=source,
        candidate=candidate,
        independent_proof=candidate_proof,
    )
    checkpoint = _committed_checkpoint(candidate)
    assert checkpoint.build is not None
    closure, observation = _request_closure(source)
    checkpoint_identity_sha256 = _sha256(checkpoint.identity.to_dict())
    temporal = RequestUniverseTemporalFieldDenominatorV1.build(
        candidate=candidate,
        checkpoint_identity_sha256=checkpoint_identity_sha256,
        request_closure_receipt_sha256=closure.artifact_sha256,
        w2_authority_identity_sha256=checkpoint.build.w2_authority.identity_sha256,
    )
    generation_key_sha256 = _sha256(
        {
            "authority_generation_sha256": _AUTHORITY_GENERATION,
            "checkpoint_identity_sha256": checkpoint_identity_sha256,
            "request_closure_receipt_sha256": closure.artifact_sha256,
            "w2_authority_identity_sha256": checkpoint.build.w2_authority.identity_sha256,
            "temporal_field_denominator_sha256": temporal.receipt_sha256,
            "closure_fixed_point_provider_request_inventory_sha256": _sha256(
                list(closure.closure.iterations[-1].output_units)
            ),
            "parent_observation_generation_sha256": None,
            "generation_ordinal": 1,
        }
    )
    call = candidate.logical_calls[0]
    evidence = TerminalRequestEvidenceV1(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        checkpoint_identity_sha256=checkpoint_identity_sha256,
        request_closure_receipt_sha256=closure.artifact_sha256,
        w2_authority_identity_sha256=checkpoint.build.w2_authority.identity_sha256,
        temporal_field_denominator_sha256=temporal.receipt_sha256,
        observation_generation_key_sha256=generation_key_sha256,
        physical_call_id=call.physical_call_id,
        request_scope_sha256=call.request_scope_sha256,
        source_family=call.source_family,
        endpoint_name=call.endpoint_name,
        provider_request_sha256=observation.provider_request_sha256,
        request_observation_sha256=_sha256(observation.to_dict()),
        request_call=call,
        disposition=TerminalRequestDisposition.CAPTURED_NONEMPTY,
        captured_row_count=observation.total_result_rows,
        result_receipt_count=len(observation.result_sets),
        staging_receipt_count=len(observation.staging_receipts),
        result_receipt_inventory_sha256=_sha256(
            [item.to_dict() for item in observation.result_sets]
        ),
        staging_receipt_inventory_sha256=_sha256(
            [item.to_dict() for item in observation.staging_receipts]
        ),
    )
    preliminary = {
        "source": source,
        "candidate": candidate,
        "candidate_proof": candidate_proof,
        "admission": admission,
        "checkpoint": checkpoint,
        "closure": closure,
        "temporal": temporal,
    }
    finalization_source, universe, final_proof, independent_receipt = _replace_final_evidence(
        preliminary, evidence
    )
    authority = compile_request_universe_final_authority_v1(
        source=source,
        candidate=candidate,
        candidate_independent_proof=candidate_proof,
        source_admission=admission,
        checkpoint_transaction=checkpoint,
        request_closure_receipt=closure,
        temporal_field_denominator=temporal,
        finalization_source=finalization_source,
        request_universe=universe,
        final_independent_proof=final_proof,
        independent_empty_delta_receipt=independent_receipt,
    )
    return {
        **preliminary,
        "observation": observation,
        "evidence": evidence,
        "finalization_source": finalization_source,
        "universe": universe,
        "final_proof": final_proof,
        "independent_receipt": independent_receipt,
        "authority": authority,
    }


def test_current_source_admission_is_exactly_bound_but_never_terminal() -> None:
    source = _current_source()
    candidate, proof = _candidate_and_proof(source)

    admission = compile_request_universe_source_admission_v1(
        source=source,
        candidate=candidate,
        independent_proof=proof,
    )

    assert admission.supplied_member_bindings_validated is True
    assert admission.complete_denominator_admitted is False
    assert admission.least_fixed_point_proven is False
    assert admission.terminal is False
    assert admission.release_eligible is False
    assert admission.field_occurrence_count == len(source.field_occurrences)
    assert {
        "complete_parameter_domain_not_admitted",
        "complete_request_denominator_not_admitted",
        "least_fixed_point_not_proven",
        "source_relative_candidate_only",
        "temporal_observation_evidence_not_admitted",
    } <= set(admission.blocker_codes)
    assert (
        RequestUniverseSourceAdmissionV1.from_canonical_bytes(admission.canonical_bytes)
        == admission
    )
    assert (
        validate_request_universe_source_admission_v1(
            observed=admission.canonical_bytes,
            source=source,
            candidate=candidate,
            independent_proof=proof,
        )
        == admission
    )


def test_admission_rejects_self_consistent_field_omission() -> None:
    source = _current_source()
    omitted = replace(source, field_occurrences=source.field_occurrences[:-1])
    candidate, proof = _candidate_and_proof(omitted)

    with pytest.raises(
        RequestUniverseSourceAdmissionError,
        match="omits or mutates the current field denominator",
    ):
        compile_request_universe_source_admission_v1(
            source=omitted,
            candidate=candidate,
            independent_proof=proof,
        )


def test_admission_rejects_self_consistent_fabricated_nested_path() -> None:
    source = _current_source()
    call = source.logical_calls[0]
    current_member = source.route_members[0]
    fabricated_member = RouteRequestMemberV1.build(
        call=call,
        route_id=current_member.route_id,
        result_name=current_member.result_name,
        result_ordinal=current_member.result_ordinal,
        nested_path=("fabricated",),
    )
    forged_source = replace(
        source,
        route_members=tuple(
            sorted(
                (*source.route_members, fabricated_member),
                key=lambda item: item.route_request_member_id,
            )
        ),
    )
    candidate, proof = _candidate_and_proof(forged_source)

    with pytest.raises(
        RequestUniverseSourceAdmissionError,
        match="omit or invent a current result/nested-path member",
    ):
        compile_request_universe_source_admission_v1(
            source=forged_source,
            candidate=candidate,
            independent_proof=proof,
        )


def test_admission_rejects_self_consistent_fabricated_parameter() -> None:
    source = _current_source()
    routes = staging_route_contract_bundle()
    temporal = temporal_availability_contract_bundle()
    current_member = source.route_members[0]
    route = routes.by_route_id[current_member.route_id]
    route_scope = temporal.by_route_id[current_member.route_id]
    forged_call = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        source_family=route.source_family,
        endpoint_name=route.endpoint_name,
        canonical_endpoint_name=route.canonical_endpoint_name,
        physical_endpoint_name=route.endpoint_name,
        parameters={"fabricated": "value", "season": "2023-24"},
    )
    forged_member = RouteRequestMemberV1.build(
        call=forged_call,
        route_id=current_member.route_id,
        result_name=current_member.result_name,
        result_ordinal=current_member.result_ordinal,
    )
    forged_period = ExplicitTemporalScopeValueV1.from_current_contract(
        authority_generation_sha256=_AUTHORITY_GENERATION,
        temporal_contract_sha256=temporal.digest,
        route_member=forged_member,
        route_scope=route_scope,
        temporal_scope_kind=TemporalScopeKind.SEASON,
        temporal_scope_value="2023-24",
    )
    forged_source = replace(
        source,
        logical_calls=(forged_call,),
        route_members=(forged_member,),
        explicit_temporal_scopes=(forged_period,),
    )
    candidate, proof = _candidate_and_proof(forged_source)

    with pytest.raises(
        RequestUniverseSourceAdmissionError,
        match="parameters differ from the current provider request authority",
    ):
        compile_request_universe_source_admission_v1(
            source=forged_source,
            candidate=candidate,
            independent_proof=proof,
        )


def test_strict_parser_and_recompiler_reject_type_confusion_and_resealing() -> None:
    source = _current_source()
    candidate, proof = _candidate_and_proof(source)
    admission = compile_request_universe_source_admission_v1(
        source=source,
        candidate=candidate,
        independent_proof=proof,
    )

    for field_name, value in (
        ("schema_version", True),
        ("logical_call_count", True),
        ("terminal", 0),
        ("supplied_member_bindings_validated", 1),
    ):
        malformed = _reseal({**admission.to_dict(), field_name: value})
        with pytest.raises(RequestUniverseSourceAdmissionError):
            RequestUniverseSourceAdmissionV1.from_dict(malformed)

    forged = _reseal({**admission.to_dict(), "provider_authority_sha256": "0" * 64})
    parsed_forgery = RequestUniverseSourceAdmissionV1.from_dict(forged)
    with pytest.raises(
        RequestUniverseSourceAdmissionError,
        match="differs from current authority recompilation",
    ):
        validate_request_universe_source_admission_v1(
            observed=parsed_forgery,
            source=source,
            candidate=candidate,
            independent_proof=proof,
        )

    with pytest.raises(RequestUniverseSourceAdmissionError, match="exact canonical JSON"):
        RequestUniverseSourceAdmissionV1.from_canonical_bytes(admission.canonical_bytes + b"\n")


def test_compiler_rejects_post_init_mutation_and_bool_int_equality() -> None:
    source = _current_source()
    candidate, proof = _candidate_and_proof(source)

    mutated_source = replace(source)
    object.__setattr__(mutated_source, "logical_calls", list(source.logical_calls))
    mutated_candidate = replace(candidate)
    object.__setattr__(mutated_candidate, "terminal", 0)
    mutated_proof = replace(proof)
    object.__setattr__(mutated_proof, "logical_call_count", True)

    for source_value, candidate_value, proof_value in (
        (mutated_source, candidate, proof),
        (source, mutated_candidate, proof),
        (source, candidate, mutated_proof),
    ):
        with pytest.raises(
            RequestUniverseSourceAdmissionError,
            match="strict DTO reconstruction",
        ):
            compile_request_universe_source_admission_v1(
                source=source_value,
                candidate=candidate_value,
                independent_proof=proof_value,
            )


def test_final_authority_joins_exact_typed_upstream_receipts() -> None:
    inputs = _final_authority_inputs()
    authority = inputs["authority"]

    assert type(authority) is RequestUniverseFinalAuthorityV1
    assert authority.request_universe_terminal is True
    assert authority.overall_release_eligible is False
    assert (
        RequestUniverseFinalAuthorityV1.from_canonical_bytes(authority.canonical_bytes) == authority
    )
    assert (
        validate_request_universe_final_authority_v1(
            observed=authority.canonical_bytes,
            source=inputs["source"],
            candidate=inputs["candidate"],
            candidate_independent_proof=inputs["candidate_proof"],
            source_admission=inputs["admission"],
            checkpoint_transaction=inputs["checkpoint"],
            request_closure_receipt=inputs["closure"],
            temporal_field_denominator=inputs["temporal"],
            finalization_source=inputs["finalization_source"],
            request_universe=inputs["universe"],
            final_independent_proof=inputs["final_proof"],
            independent_empty_delta_receipt=inputs["independent_receipt"],
        )
        == authority
    )


def test_final_authority_rejects_foreign_checkpoint_and_temporal_receipts() -> None:
    inputs = _final_authority_inputs()
    checkpoint = inputs["checkpoint"]
    mutated_checkpoint = replace(checkpoint)
    object.__setattr__(
        mutated_checkpoint,
        "artifact_name",
        "foreign-request-universe-checkpoint",
    )

    with pytest.raises(
        RequestUniverseSourceAdmissionError,
        match="typed upstream authorities fail exact replay",
    ):
        compile_request_universe_final_authority_v1(
            source=inputs["source"],
            candidate=inputs["candidate"],
            candidate_independent_proof=inputs["candidate_proof"],
            source_admission=inputs["admission"],
            checkpoint_transaction=mutated_checkpoint,
            request_closure_receipt=inputs["closure"],
            temporal_field_denominator=inputs["temporal"],
            finalization_source=inputs["finalization_source"],
            request_universe=inputs["universe"],
            final_independent_proof=inputs["final_proof"],
            independent_empty_delta_receipt=inputs["independent_receipt"],
        )

    temporal_payload = inputs["temporal"].to_dict()
    temporal_payload["checkpoint_identity_sha256"] = "f" * 64
    temporal_body = dict(temporal_payload)
    temporal_body.pop("receipt_sha256")
    temporal_payload["receipt_sha256"] = _sha256(temporal_body)
    foreign_temporal = RequestUniverseTemporalFieldDenominatorV1.from_dict(temporal_payload)
    with pytest.raises(
        RequestUniverseSourceAdmissionError,
        match="differs from typed upstream authorities",
    ):
        compile_request_universe_final_authority_v1(
            source=inputs["source"],
            candidate=inputs["candidate"],
            candidate_independent_proof=inputs["candidate_proof"],
            source_admission=inputs["admission"],
            checkpoint_transaction=inputs["checkpoint"],
            request_closure_receipt=inputs["closure"],
            temporal_field_denominator=foreign_temporal,
            finalization_source=inputs["finalization_source"],
            request_universe=inputs["universe"],
            final_independent_proof=inputs["final_proof"],
            independent_empty_delta_receipt=inputs["independent_receipt"],
        )


def test_final_authority_rejects_resealed_typed_terminal_evidence() -> None:
    inputs = _final_authority_inputs()
    evidence = replace(
        inputs["evidence"],
        request_observation_sha256="f" * 64,
        evidence_sha256="",
    )
    finalization_source, universe, final_proof, independent_receipt = _replace_final_evidence(
        inputs, evidence
    )

    with pytest.raises(
        RequestUniverseSourceAdmissionError,
        match="rebound from its request-closure observation",
    ):
        compile_request_universe_final_authority_v1(
            source=inputs["source"],
            candidate=inputs["candidate"],
            candidate_independent_proof=inputs["candidate_proof"],
            source_admission=inputs["admission"],
            checkpoint_transaction=inputs["checkpoint"],
            request_closure_receipt=inputs["closure"],
            temporal_field_denominator=inputs["temporal"],
            finalization_source=finalization_source,
            request_universe=universe,
            final_independent_proof=final_proof,
            independent_empty_delta_receipt=independent_receipt,
        )


def test_final_authority_recompiler_rejects_self_resealed_receipt() -> None:
    inputs = _final_authority_inputs()
    authority = inputs["authority"]
    payload = authority.to_dict()
    payload["checkpoint_identity_sha256"] = "f" * 64
    body = dict(payload)
    body.pop("authority_sha256")
    payload["authority_sha256"] = _sha256(body)
    forged = RequestUniverseFinalAuthorityV1.from_dict(payload)

    with pytest.raises(
        RequestUniverseSourceAdmissionError,
        match="differs from exact recompilation",
    ):
        validate_request_universe_final_authority_v1(
            observed=forged,
            source=inputs["source"],
            candidate=inputs["candidate"],
            candidate_independent_proof=inputs["candidate_proof"],
            source_admission=inputs["admission"],
            checkpoint_transaction=inputs["checkpoint"],
            request_closure_receipt=inputs["closure"],
            temporal_field_denominator=inputs["temporal"],
            finalization_source=inputs["finalization_source"],
            request_universe=inputs["universe"],
            final_independent_proof=inputs["final_proof"],
            independent_empty_delta_receipt=inputs["independent_receipt"],
        )
