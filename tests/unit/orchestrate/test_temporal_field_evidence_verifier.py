from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json

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
    compile_temporal_field_evidence_candidate_v1,
)
from nbadb.orchestrate.temporal_field_evidence_verifier import (
    IndependentTemporalFieldEvidenceError,
    TemporalFieldEvidenceIndependentProofV1,
    verify_temporal_field_evidence_candidate_independently,
)

_AUTHORITY = "a" * 64
_FIELD_FATE = "b" * 64
_TEMPORAL = "c" * 64


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _case(
    *, asserted_receipt_sha256: str | None = None
) -> tuple[
    dict[str, object],
    dict[str, object],
    tuple[dict[str, object], ...],
    dict[str, object],
]:
    call = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="video_events_asset",
        canonical_endpoint_name="video_events_asset",
        physical_endpoint_name="video_events_asset",
        parameters={"GameID": "0022300001", "Season": "2023-24"},
    )
    route = RouteRequestMemberV1.build(
        call=call,
        route_id="video_events_asset:stg_video_events_asset:0",
        result_name="VideoEventsAsset",
        result_ordinal=0,
        nested_path=("assets",),
    )
    fields = tuple(
        FieldOccurrenceInputV1(
            authority_generation_sha256=_AUTHORITY,
            occurrence_id=f"video_events_asset:stg_video_events_asset:0#field:{ordinal}",
            route_id=route.route_id,
            endpoint_name=route.endpoint_name,
            result_name=route.result_name,
            result_ordinal=route.result_ordinal,
            nested_path=route.nested_path,
            provider_field="ASSET_URL",
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
        temporal_scope_kind=TemporalScopeKind.GAME_ID,
        temporal_scope_value="0022300001",
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
    parent = compile_request_universe_candidate_generation_v1(source)
    parent_proof = verify_request_universe_candidate_independently(
        source_payload=source.to_dict(),
        candidate_payload=parent.to_dict(),
    )
    receipt = asserted_receipt_sha256
    observation = FieldObservationBindingV1.build(
        parent_candidate_sha256=parent.identity_sha256,
        cell=parent.field_period_cells[0],
        state=FieldEvidenceStateV1.PRESENT_EMPTY,
        raw_authority_bundle_sha256=receipt or "1" * 64,
        request_observation_sha256=receipt or "2" * 64,
        provider_call_sha256=receipt or "3" * 64,
        provider_request_sha256=receipt or "4" * 64,
        result_occurrence_sha256=receipt or "5" * 64,
        logical_result_receipt_sha256=receipt or "6" * 64,
        route_receipt_sha256=receipt or "7" * 64,
        typed_value_receipt_sha256=receipt or "8" * 64,
        reconstruction_receipt_sha256=receipt or "9" * 64,
    )
    evidence = compile_temporal_field_evidence_candidate_v1(
        parent_candidate=parent,
        parent_proof=parent_proof,
        observations=(observation,),
    )
    return (
        parent.to_dict(),
        parent_proof.to_dict(),
        (observation.to_dict(),),
        evidence.to_dict(),
    )


def _verify(
    parent: dict[str, object],
    parent_proof: dict[str, object],
    observations: tuple[dict[str, object], ...],
    evidence: dict[str, object],
) -> TemporalFieldEvidenceIndependentProofV1:
    return verify_temporal_field_evidence_candidate_independently(
        parent_candidate_bytes=_canonical(parent),
        parent_proof_bytes=_canonical(parent_proof),
        evidence_bytes=tuple(_canonical(item) for item in observations),
        candidate_bytes=_canonical(evidence),
    )


def test_independent_verifier_rederives_exact_nonterminal_partition() -> None:
    parent, parent_proof, observations, evidence = _case()
    proof = _verify(parent, parent_proof, observations, evidence)

    assert proof.parent_candidate_sha256 == _digest(parent)
    assert proof.parent_proof_sha256 == _digest(parent_proof)
    assert proof.evidence_candidate_sha256 == _digest(evidence)
    assert proof.denominator_count == 2
    assert proof.evidenced_cell_count == 0
    assert proof.unresolved_cell_count == 2
    assert proof.conflict_cell_count == 0
    assert proof.unjoinable_observation_count == 0
    assert proof.exact_partition_equal is True
    assert proof.candidate_only is True
    assert proof.denominator_admitted is False
    assert proof.terminal is False
    assert proof.release_eligible is False


def test_verifier_has_no_primary_or_nbadb_helper_imports() -> None:
    module = inspect.getmodule(verify_temporal_field_evidence_candidate_independently)
    assert module is not None
    tree = ast.parse(inspect.getsource(module))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(
        not (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("nbadb")
        )
        and not (
            isinstance(node, ast.Import)
            and any(alias.name.startswith("nbadb") for alias in node.names)
        )
        for node in imports
    )


def test_resealed_observation_request_route_field_and_authority_rebinding_rejects() -> None:
    parent, parent_proof, observations, evidence = _case()
    for field_name, value in (
        ("request_scope_sha256", "f" * 64),
        ("route_id", "video_events_asset:stg_video_events_asset:999"),
        ("provider_field", "OPAQUE_REBOUND"),
        ("authority_generation_sha256", "e" * 64),
        ("parent_candidate_sha256", "d" * 64),
    ):
        rebound = copy.deepcopy(observations[0])
        rebound[field_name] = value
        identity = copy.deepcopy(rebound)
        identity.pop("observation_id")
        rebound["observation_id"] = f"field-observation-v1:{_digest(identity)}"
        with pytest.raises(IndependentTemporalFieldEvidenceError, match="differs"):
            _verify(parent, parent_proof, (rebound,), evidence)


def test_missing_receipt_false_proof_and_forbidden_state_reject_before_compare() -> None:
    parent, parent_proof, observations, evidence = _case()
    missing = copy.deepcopy(observations[0])
    missing.pop("typed_value_receipt_sha256")
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="missing or unexpected"):
        _verify(parent, parent_proof, (missing,), evidence)

    false_proof = copy.deepcopy(observations[0])
    false_proof["proofs_equal"] = False
    identity = copy.deepcopy(false_proof)
    identity.pop("observation_id")
    false_proof["observation_id"] = f"field-observation-v1:{_digest(identity)}"
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="equal proof"):
        _verify(parent, parent_proof, (false_proof,), evidence)

    unavailable = copy.deepcopy(observations[0])
    unavailable["state"] = "upstream_unavailable"
    identity = copy.deepcopy(unavailable)
    identity.pop("observation_id")
    unavailable["observation_id"] = f"field-observation-v1:{_digest(identity)}"
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="state is invalid"):
        _verify(parent, parent_proof, (unavailable,), evidence)


def test_self_consistently_omitted_or_reordered_denominator_cell_rejects() -> None:
    parent, parent_proof, observations, evidence = _case()
    dropped = copy.deepcopy(evidence)
    cells = dropped["evidence_cells"]
    assert isinstance(cells, list)
    dropped["evidence_cells"] = cells[:-1]
    dropped["evidence_cell_count"] = 1
    dropped["denominator_count"] = 1
    dropped["evidence_cell_inventory_sha256"] = _digest(dropped["evidence_cells"])
    unresolved = dropped["unresolved_cell_ids"]
    assert isinstance(unresolved, list)
    dropped["unresolved_cell_ids"] = []
    dropped["unresolved_cell_count"] = 0
    dropped["unresolved_partition_sha256"] = _digest([])
    dropped["denominator_inventory_sha256"] = _digest(
        [cells[0]["cell_id"]] if isinstance(cells[0], dict) else []
    )
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="differs"):
        _verify(parent, parent_proof, observations, dropped)

    reordered = copy.deepcopy(evidence)
    reordered_cells = reordered["evidence_cells"]
    assert isinstance(reordered_cells, list)
    reordered["evidence_cells"] = list(reversed(reordered_cells))
    reordered["evidence_cell_inventory_sha256"] = _digest(reordered["evidence_cells"])
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="differs"):
        _verify(parent, parent_proof, observations, reordered)


def test_resealed_cell_state_and_partition_mutation_rejects() -> None:
    parent, parent_proof, observations, evidence = _case()
    mutated = copy.deepcopy(evidence)
    cells = mutated["evidence_cells"]
    assert isinstance(cells, list) and isinstance(cells[0], dict)
    cells[0]["state"] = "null"
    cells[0]["observed_states"] = ["null"]
    mutated["evidence_cell_inventory_sha256"] = _digest(cells)
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="differs"):
        _verify(parent, parent_proof, observations, mutated)

    final = copy.deepcopy(evidence)
    final["denominator_admitted"] = True
    final["terminal"] = True
    final["release_eligible"] = True
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="differs"):
        _verify(parent, parent_proof, observations, final)


def test_parent_proof_rebinding_and_duplicate_observations_reject() -> None:
    parent, parent_proof, observations, evidence = _case()
    rebound = copy.deepcopy(parent_proof)
    rebound["candidate_generation_sha256"] = "f" * 64
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="differs"):
        _verify(parent, rebound, observations, evidence)
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="duplicate"):
        _verify(parent, parent_proof, (observations[0], observations[0]), evidence)


def test_exact_canonical_candidate_bytes_reject_type_confusion_and_noncanonical_forms() -> None:
    parent, parent_proof, observations, evidence = _case()
    shared = {
        "parent_candidate_bytes": _canonical(parent),
        "parent_proof_bytes": _canonical(parent_proof),
        "evidence_bytes": tuple(_canonical(item) for item in observations),
    }

    type_confused = copy.deepcopy(evidence)
    type_confused["joined_observation_count"] = True
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="differs"):
        verify_temporal_field_evidence_candidate_independently(
            **shared,
            candidate_bytes=_canonical(type_confused),
        )

    with pytest.raises(IndependentTemporalFieldEvidenceError, match="exact canonical"):
        verify_temporal_field_evidence_candidate_independently(
            **shared,
            candidate_bytes=_canonical(evidence) + b"\n",
        )

    duplicate = _canonical(evidence).replace(
        b'"terminal":false',
        b'"terminal":false,"terminal":false',
    )
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="duplicate keys"):
        verify_temporal_field_evidence_candidate_independently(
            **shared,
            candidate_bytes=duplicate,
        )


def test_parent_and_observation_bool_int_mutations_reject_before_partition_compare() -> None:
    parent, parent_proof, observations, evidence = _case()

    proof_count_bool = copy.deepcopy(parent_proof)
    proof_count_bool["logical_call_count"] = True
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="nonnegative integer"):
        _verify(parent, proof_count_bool, observations, evidence)

    parent_schema_bool = copy.deepcopy(parent)
    parent_schema_bool["schema_version"] = True
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="schema identity"):
        _verify(parent_schema_bool, parent_proof, observations, evidence)

    nested_call_bool = copy.deepcopy(parent)
    calls = nested_call_bool["logical_calls"]
    assert isinstance(calls, list) and isinstance(calls[0], dict)
    calls[0]["parameters_complete"] = 1
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="explicitly complete"):
        _verify(nested_call_bool, parent_proof, observations, evidence)

    observation_ordinal_bool = copy.deepcopy(observations[0])
    observation_ordinal_bool["field_occurrence_ordinal"] = True
    identity = copy.deepcopy(observation_ordinal_bool)
    identity.pop("observation_id")
    observation_ordinal_bool["observation_id"] = f"field-observation-v1:{_digest(identity)}"
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="nonnegative integer"):
        _verify(parent, parent_proof, (observation_ordinal_bool,), evidence)


def test_self_consistent_fabricated_receipt_assertions_remain_unresolved() -> None:
    parent, parent_proof, observations, evidence = _case(asserted_receipt_sha256="f" * 64)
    proof = _verify(parent, parent_proof, observations, evidence)

    cells = evidence["evidence_cells"]
    assert isinstance(cells, list) and isinstance(cells[0], dict)
    assert cells[0]["observed_states"] == ["present_empty"]
    assert cells[0]["state"] == "evidence_insufficient"
    assert cells[0]["disposition"] == "unresolved"
    assert evidence["evidenced_cell_ids"] == []
    assert proof.evidenced_cell_count == 0
    assert proof.unresolved_cell_count == proof.denominator_count
    assert proof.evidence_candidate_sha256 == hashlib.sha256(_canonical(evidence)).hexdigest()


def test_independent_proof_strict_roundtrip_and_false_authority_reject() -> None:
    parent, parent_proof, observations, evidence = _case()
    proof = _verify(parent, parent_proof, observations, evidence)
    assert (
        TemporalFieldEvidenceIndependentProofV1.from_canonical_bytes(proof.canonical_bytes) == proof
    )
    duplicate = proof.canonical_bytes.replace(
        b'"terminal":false',
        b'"terminal":false,"terminal":false',
    )
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="duplicate keys"):
        TemporalFieldEvidenceIndependentProofV1.from_canonical_bytes(duplicate)
    payload = proof.to_dict()
    payload["denominator_admitted"] = True
    with pytest.raises(IndependentTemporalFieldEvidenceError, match="cannot admit"):
        TemporalFieldEvidenceIndependentProofV1.from_dict(payload)
