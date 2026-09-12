from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from nbadb.orchestrate.request_universe_generation_contract import (
    ExplicitTemporalScopeValueV1,
    FieldOccurrenceInputV1,
    LogicalRequestCallV1,
    RequestUniverseCandidateSourceV1,
    RouteRequestMemberV1,
    TemporalScopeKind,
    compile_request_universe_candidate_generation_v1,
)
from nbadb.orchestrate.request_universe_generation_verifier import (
    verify_request_universe_candidate_independently,
)
from nbadb.orchestrate.temporal_field_evidence_contract import (
    FieldEvidenceStateV1,
    FieldObservationBindingV1,
    TemporalFieldEvidenceCandidateV1,
    TemporalFieldEvidenceContractError,
    canonical_temporal_field_evidence_sha256,
    compile_temporal_field_evidence_candidate_v1,
)

_AUTHORITY = "a" * 64
_FIELD_FATE = "b" * 64
_TEMPORAL = "c" * 64


def _parent() -> tuple[object, object]:
    call = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="video_details",
        canonical_endpoint_name="video_details",
        physical_endpoint_name="video_details",
        parameters={"GameID": "0022300001", "Season": "2023-24"},
    )
    route = RouteRequestMemberV1.build(
        call=call,
        route_id="video_details:stg_video_details:0",
        result_name="VideoDetails",
        result_ordinal=0,
    )
    fields = tuple(
        FieldOccurrenceInputV1(
            authority_generation_sha256=_AUTHORITY,
            occurrence_id=f"video_details:stg_video_details:0#field:{ordinal}",
            route_id=route.route_id,
            endpoint_name=route.endpoint_name,
            result_name=route.result_name,
            result_ordinal=route.result_ordinal,
            nested_path=route.nested_path,
            provider_field="GAME_ID",
            field_occurrence_ordinal=ordinal,
            field_fate_contract_sha256=_FIELD_FATE,
        )
        for ordinal in range(2)
    )
    period = ExplicitTemporalScopeValueV1(
        authority_generation_sha256=_AUTHORITY,
        physical_call_id=route.physical_call_id,
        route_request_member_id=route.route_request_member_id,
        route_id=route.route_id,
        endpoint_name=route.endpoint_name,
        request_scope_sha256=route.request_scope_sha256,
        temporal_contract_sha256=_TEMPORAL,
        temporal_scope_kind=TemporalScopeKind.SEASON,
        temporal_scope_value="2023-24",
    )
    source = RequestUniverseCandidateSourceV1(
        authority_generation_sha256=_AUTHORITY,
        field_fate_contract_sha256=_FIELD_FATE,
        temporal_contract_sha256=_TEMPORAL,
        logical_calls=(call,),
        route_members=(route,),
        field_occurrences=tuple(sorted(fields, key=lambda item: item.identity_sha256)),
        explicit_temporal_scopes=(period,),
        unintegrated_cume_values=(),
    )
    candidate = compile_request_universe_candidate_generation_v1(source)
    proof = verify_request_universe_candidate_independently(
        source_payload=source.to_dict(),
        candidate_payload=candidate.to_dict(),
    )
    return candidate, proof


def _observation(
    candidate: object,
    *,
    index: int = 0,
    state: FieldEvidenceStateV1 = FieldEvidenceStateV1.POPULATED,
    seed: int = 1,
) -> FieldObservationBindingV1:
    cell = candidate.field_period_cells[index]
    digests = tuple(f"{value:x}" * 64 for value in range(1, 10))
    typed = f"{seed:x}" * 64
    reconstructed = f"{seed + 1:x}" * 64
    return FieldObservationBindingV1.build(
        parent_candidate_sha256=candidate.identity_sha256,
        cell=cell,
        state=state,
        raw_authority_bundle_sha256=digests[0],
        request_observation_sha256=digests[1],
        provider_call_sha256=digests[2],
        provider_request_sha256=digests[3],
        result_occurrence_sha256=digests[4],
        logical_result_receipt_sha256=digests[5],
        route_receipt_sha256=digests[6],
        typed_value_receipt_sha256=typed,
        reconstruction_receipt_sha256=reconstructed,
    )


def _reseal_observation(payload: dict[str, object]) -> FieldObservationBindingV1:
    identity = copy.deepcopy(payload)
    identity.pop("observation_id")
    payload["observation_id"] = (
        f"field-observation-v1:{canonical_temporal_field_evidence_sha256(identity)}"
    )
    return FieldObservationBindingV1.from_dict(payload)


def _compile(*observations: FieldObservationBindingV1) -> TemporalFieldEvidenceCandidateV1:
    candidate, proof = _parent()
    return compile_temporal_field_evidence_candidate_v1(
        parent_candidate=candidate,
        parent_proof=proof,
        observations=observations,
    )


def test_zero_evidence_conserves_every_parent_cell_as_unresolved() -> None:
    parent, proof = _parent()
    result = compile_temporal_field_evidence_candidate_v1(
        parent_candidate=parent,
        parent_proof=proof,
    )

    assert result.denominator_count == len(parent.field_period_cells) == 2
    assert result.denominator_inventory_sha256 == parent.field_period_inventory_sha256
    assert [cell.to_parent_cell_dict() for cell in result.evidence_cells] == [
        cell.to_dict() for cell in parent.field_period_cells
    ]
    assert result.evidenced_cell_ids == ()
    assert result.conflict_cell_ids == ()
    assert result.unresolved_cell_ids == tuple(cell.cell_id for cell in parent.field_period_cells)
    assert {cell.state for cell in result.evidence_cells} == {"evidence_insufficient"}
    assert result.parent_blockers == parent.blockers
    assert result.denominator_admitted is False
    assert result.terminal is False
    assert result.release_eligible is False


def test_duplicate_field_names_and_zero_width_assertions_remain_distinct_unresolved() -> None:
    parent, proof = _parent()
    empty = _observation(
        parent,
        index=0,
        state=FieldEvidenceStateV1.PRESENT_EMPTY,
        seed=1,
    )
    populated = _observation(parent, index=1, seed=3)
    result = compile_temporal_field_evidence_candidate_v1(
        parent_candidate=parent,
        parent_proof=proof,
        observations=(populated, empty),
    )

    assert result.evidenced_cell_ids == ()
    assert len(result.unresolved_cell_ids) == 2
    assert {
        (
            cell.provider_field,
            cell.field_occurrence_ordinal,
            cell.state,
            cell.observed_states,
        )
        for cell in result.evidence_cells
    } == {
        ("GAME_ID", 0, "evidence_insufficient", ("present_empty",)),
        ("GAME_ID", 1, "evidence_insufficient", ("populated",)),
    }
    assert result.joined_observations == tuple(
        sorted((empty, populated), key=lambda item: item.observation_id)
    )


def test_repeated_equal_assertions_are_unresolved_but_distinct_states_conflict() -> None:
    parent, proof = _parent()
    first = _observation(parent, state=FieldEvidenceStateV1.NULL, seed=1)
    second = _observation(parent, state=FieldEvidenceStateV1.NULL, seed=3)
    equal = compile_temporal_field_evidence_candidate_v1(
        parent_candidate=parent,
        parent_proof=proof,
        observations=(first, second),
    )
    cell = next(item for item in equal.evidence_cells if item.cell_id == first.cell_id)
    assert cell.state == "evidence_insufficient"
    assert cell.disposition.value == "unresolved"
    assert cell.observed_states == ("null",)
    assert equal.evidenced_cell_ids == ()

    different = _observation(parent, state=FieldEvidenceStateV1.POPULATED, seed=5)
    conflict = compile_temporal_field_evidence_candidate_v1(
        parent_candidate=parent,
        parent_proof=proof,
        observations=(first, different),
    )
    conflicted = next(item for item in conflict.evidence_cells if item.cell_id == first.cell_id)
    assert conflicted.state == "evidence_insufficient"
    assert conflicted.disposition.value == "conflict"
    assert conflicted.observed_states == ("null", "populated")
    assert conflict.conflict_cell_ids == (first.cell_id,)


@pytest.mark.parametrize(
    "state",
    [FieldEvidenceStateV1.UNKNOWN, FieldEvidenceStateV1.TRANSIENT],
)
def test_unknown_and_transient_evidence_remain_unresolved(
    state: FieldEvidenceStateV1,
) -> None:
    parent, proof = _parent()
    observation = _observation(parent, state=state)
    result = compile_temporal_field_evidence_candidate_v1(
        parent_candidate=parent,
        parent_proof=proof,
        observations=(observation,),
    )

    cell = next(item for item in result.evidence_cells if item.cell_id == observation.cell_id)
    assert cell.state == "evidence_insufficient"
    assert cell.disposition.value == "unresolved"
    assert cell.observed_states == (state.value,)
    assert "upstream_unavailable" not in result.canonical_bytes.decode()


def test_foreign_and_rebound_observations_are_retained_as_unjoinable() -> None:
    parent, proof = _parent()
    base = _observation(parent)
    variants: list[FieldObservationBindingV1] = []
    mutations: tuple[tuple[str, object], ...] = (
        ("parent_candidate_sha256", "d" * 64),
        ("authority_generation_sha256", "e" * 64),
        ("cell_id", "field-period-cell-v1:absent"),
        ("route_id", "video_details:stg_video_details:999"),
    )
    for field_name, value in mutations:
        payload = copy.deepcopy(base.to_dict())
        payload[field_name] = value
        variants.append(_reseal_observation(payload))
    result = compile_temporal_field_evidence_candidate_v1(
        parent_candidate=parent,
        parent_proof=proof,
        observations=tuple(variants),
    )

    assert result.joined_observations == ()
    assert {item.reason.value for item in result.unjoinable_observations} == {
        "parent_candidate_mismatch",
        "authority_mismatch",
        "cell_absent",
        "cell_identity_mismatch",
    }
    assert len(result.unjoinable_observations) == len(variants)
    assert len(result.unresolved_cell_ids) == result.denominator_count


def test_duplicate_observation_and_rebound_parent_proof_fail_closed() -> None:
    parent, proof = _parent()
    observation = _observation(parent)
    with pytest.raises(TemporalFieldEvidenceContractError, match="duplicate observation"):
        compile_temporal_field_evidence_candidate_v1(
            parent_candidate=parent,
            parent_proof=proof,
            observations=(observation, observation),
        )
    rebound = replace(proof, candidate_generation_sha256="f" * 64)
    with pytest.raises(TemporalFieldEvidenceContractError, match="not exactly bound"):
        compile_temporal_field_evidence_candidate_v1(
            parent_candidate=parent,
            parent_proof=rebound,
        )


def test_receipt_or_proof_rebinding_cannot_reuse_an_observation_id() -> None:
    parent, _proof = _parent()
    observation = _observation(parent)
    for field_name, value in (
        ("typed_value_receipt_sha256", "f" * 64),
        ("request_observation_sha256", "f" * 64),
        ("proofs_equal", False),
    ):
        payload = copy.deepcopy(observation.to_dict())
        payload[field_name] = value
        with pytest.raises(TemporalFieldEvidenceContractError):
            FieldObservationBindingV1.from_dict(payload)


def test_fabricated_resealed_receipt_assertions_never_promote_a_cell() -> None:
    parent, proof = _parent()
    payload = _observation(parent).to_dict()
    for ordinal, field_name in enumerate(
        (
            "raw_authority_bundle_sha256",
            "request_observation_sha256",
            "provider_call_sha256",
            "provider_request_sha256",
            "result_occurrence_sha256",
            "logical_result_receipt_sha256",
            "route_receipt_sha256",
            "typed_value_receipt_sha256",
            "reconstruction_receipt_sha256",
        ),
        start=1,
    ):
        payload[field_name] = f"{ordinal:x}" * 64
    observation = _reseal_observation(payload)

    result = compile_temporal_field_evidence_candidate_v1(
        parent_candidate=parent,
        parent_proof=proof,
        observations=(observation,),
    )

    cell = next(item for item in result.evidence_cells if item.cell_id == observation.cell_id)
    assert result.joined_observations == (observation,)
    assert result.evidenced_cell_ids == ()
    assert cell.state == "evidence_insufficient"
    assert cell.disposition.value == "unresolved"
    assert cell.observed_states == ("populated",)


def test_exact_scalar_and_enum_types_reject_bool_float_and_raw_string_confusions() -> None:
    parent, _proof = _parent()
    observation = _observation(parent)

    schema_bool = observation.to_dict()
    schema_bool["schema_version"] = True
    with pytest.raises(TemporalFieldEvidenceContractError, match="schema identity"):
        FieldObservationBindingV1.from_dict(schema_bool)

    ordinal_bool = observation.to_dict()
    ordinal_bool["field_occurrence_ordinal"] = True
    identity = copy.deepcopy(ordinal_bool)
    identity.pop("observation_id")
    ordinal_bool["observation_id"] = (
        f"field-observation-v1:{canonical_temporal_field_evidence_sha256(identity)}"
    )
    with pytest.raises(TemporalFieldEvidenceContractError, match="nonnegative integer"):
        FieldObservationBindingV1.from_dict(ordinal_bool)

    candidate_payload = _compile().to_dict()
    candidate_payload["evidence_cell_count"] = 2.0
    with pytest.raises(TemporalFieldEvidenceContractError, match="nonnegative integer"):
        TemporalFieldEvidenceCandidateV1.from_dict(candidate_payload)

    with pytest.raises(TemporalFieldEvidenceContractError, match="exact FieldEvidenceStateV1"):
        replace(observation, state="populated")
    with pytest.raises(
        TemporalFieldEvidenceContractError, match="exact FieldEvidenceDispositionV1"
    ):
        replace(_compile().evidence_cells[0], disposition="unresolved")


def test_hostile_nested_dto_and_parent_proof_mutations_fail_before_join() -> None:
    parent, proof = _parent()
    observation = _observation(parent, index=1)
    object.__setattr__(observation, "field_occurrence_ordinal", True)
    with pytest.raises(TemporalFieldEvidenceContractError, match="strict nested reconstruction"):
        compile_temporal_field_evidence_candidate_v1(
            parent_candidate=parent,
            parent_proof=proof,
            observations=(observation,),
        )

    parent, proof = _parent()
    object.__setattr__(proof, "logical_call_count", True)
    with pytest.raises(TemporalFieldEvidenceContractError, match="strict nested reconstruction"):
        compile_temporal_field_evidence_candidate_v1(
            parent_candidate=parent,
            parent_proof=proof,
        )

    parent, proof = _parent()
    object.__setattr__(parent.field_period_cells[1], "field_occurrence_ordinal", True)
    with pytest.raises(TemporalFieldEvidenceContractError, match="strict nested reconstruction"):
        compile_temporal_field_evidence_candidate_v1(
            parent_candidate=parent,
            parent_proof=proof,
        )


def test_forbidden_unavailability_state_cannot_enter_observation_contract() -> None:
    parent, _proof = _parent()
    payload = _observation(parent).to_dict()
    payload["state"] = "upstream_unavailable"
    identity = copy.deepcopy(payload)
    identity.pop("observation_id")
    payload["observation_id"] = (
        f"field-observation-v1:{canonical_temporal_field_evidence_sha256(identity)}"
    )
    with pytest.raises(ValueError):
        FieldObservationBindingV1.from_dict(payload)


def test_self_consistent_cell_omission_and_reorder_are_rejected() -> None:
    result = _compile()
    dropped = copy.deepcopy(result.to_dict())
    cells = dropped["evidence_cells"]
    assert isinstance(cells, list)
    dropped["evidence_cells"] = cells[:-1]
    dropped["evidence_cell_count"] = 1
    dropped["denominator_count"] = 1
    dropped["evidence_cell_inventory_sha256"] = canonical_temporal_field_evidence_sha256(
        dropped["evidence_cells"]
    )
    unresolved = dropped["unresolved_cell_ids"]
    assert isinstance(unresolved, list)
    dropped["unresolved_cell_ids"] = unresolved[:-1]
    dropped["unresolved_cell_count"] = 1
    dropped["unresolved_partition_sha256"] = canonical_temporal_field_evidence_sha256(
        dropped["unresolved_cell_ids"]
    )
    with pytest.raises(TemporalFieldEvidenceContractError, match="denominator inventory"):
        TemporalFieldEvidenceCandidateV1.from_dict(dropped)

    reordered = copy.deepcopy(result.to_dict())
    reordered_cells = reordered["evidence_cells"]
    assert isinstance(reordered_cells, list)
    reordered["evidence_cells"] = list(reversed(reordered_cells))
    reordered["evidence_cell_inventory_sha256"] = canonical_temporal_field_evidence_sha256(
        reordered["evidence_cells"]
    )
    with pytest.raises(TemporalFieldEvidenceContractError, match="canonical sorted"):
        TemporalFieldEvidenceCandidateV1.from_dict(reordered)


def test_finality_flags_and_parent_blocker_loss_are_rejected() -> None:
    result = _compile()
    for field_name in ("denominator_admitted", "terminal", "release_eligible"):
        payload = copy.deepcopy(result.to_dict())
        payload[field_name] = True
        with pytest.raises(TemporalFieldEvidenceContractError, match="cannot admit"):
            TemporalFieldEvidenceCandidateV1.from_dict(payload)

    payload = copy.deepcopy(result.to_dict())
    payload["parent_blockers"] = []
    payload["parent_blocker_count"] = 0
    payload["parent_blocker_inventory_sha256_copy"] = canonical_temporal_field_evidence_sha256([])
    with pytest.raises(TemporalFieldEvidenceContractError, match="blockers were not conserved"):
        TemporalFieldEvidenceCandidateV1.from_dict(payload)


def test_candidate_canonical_roundtrip_rejects_duplicate_keys() -> None:
    result = _compile()
    assert TemporalFieldEvidenceCandidateV1.from_canonical_bytes(result.canonical_bytes) == result
    duplicate = result.canonical_bytes.replace(
        b'"terminal":false',
        b'"terminal":false,"terminal":false',
    )
    with pytest.raises(TemporalFieldEvidenceContractError, match="duplicate keys"):
        TemporalFieldEvidenceCandidateV1.from_canonical_bytes(duplicate)
