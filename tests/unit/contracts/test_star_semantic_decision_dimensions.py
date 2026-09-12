from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import cast

import pandera.errors
import polars as pl
import pytest

from nbadb.contracts.star_semantic_authoring import (
    StarSemanticAuthoringContractError,
    StarTableSemanticDecisionV1,
    canonical_star_semantic_authoring_json_bytes,
    canonical_star_semantic_authoring_sha256,
)
from nbadb.contracts.star_semantic_decision_corpus import (
    StarSemanticDecisionCorpusError,
    compile_star_semantic_decision_corpus_bytes,
    parse_star_semantic_decision_corpus,
    star_semantic_decision_corpus_path,
)
from nbadb.contracts.star_semantic_inventory import StarTableSemanticAuthorityV1
from nbadb.contracts.star_table_contract import compile_star_table_contracts
from nbadb.schemas.star.dim_season_phase import DimSeasonPhaseSchema
from nbadb.transform.dimensions.dim_season_phase import DimSeasonPhaseTransformer

_RESOURCE_NAME = "star-semantic-decisions-dimensions-v1.json"
_EXPECTED_ROWS = [
    [1, "Preseason", 1],
    [2, "Regular", 2],
    [3, "Play-In", 3],
    [4, "Playoffs R1", 4],
    [5, "Playoffs R2", 5],
    [6, "Conference Finals", 6],
    [7, "Finals", 7],
    [8, "All-Star", 8],
]
_UNREVIEWED_DIMENSIONS = (
    "dim_all_players",
    "dim_arena",
    "dim_coach",
    "dim_college",
    "dim_date",
    "dim_defunct_team",
    "dim_game",
    "dim_official",
    "dim_play_event_type",
    "dim_player",
    "dim_schedule_int",
    "dim_season",
    "dim_season_week",
    "dim_shot_zone",
    "dim_team",
    "dim_team_extended",
    "dim_team_history",
)


def _resource_path() -> Path:
    return star_semantic_decision_corpus_path().with_name(_RESOURCE_NAME)


def _payload() -> dict[str, object]:
    raw = _resource_path().read_bytes()
    value = json.loads(raw[:-1])
    assert type(value) is dict
    return value


def _decision_payload() -> dict[str, object]:
    decisions = _payload()["decisions"]
    assert type(decisions) is list and len(decisions) == 1
    decision = decisions[0]
    assert type(decision) is dict
    return cast("dict[str, object]", decision)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _source_sha256(obj: object) -> str:
    source = inspect.getsourcefile(obj)
    assert source is not None
    return hashlib.sha256(Path(source).read_bytes()).hexdigest()


def _evidence(
    *,
    authority_sha256: str,
    evidence_class: str,
    claim: object,
) -> str:
    return canonical_star_semantic_authoring_sha256(
        {
            "schema_version": 1,
            "kind": "nbadb_star_semantic_dimension_evidence",
            "table_name": "dim_season_phase",
            "evidence_class": evidence_class,
            "claim": claim,
            "schema_source_sha256": _source_sha256(DimSeasonPhaseSchema),
            "transform_source_sha256": _source_sha256(DimSeasonPhaseTransformer),
            "authority_sha256": authority_sha256,
        }
    )


def _micro_authority(output_name: str) -> StarTableSemanticAuthorityV1:
    return StarTableSemanticAuthorityV1(
        output_name=output_name,
        table_family="dimension",
        structural_inventory_sha256=_digest("micro-structural-inventory"),
        stable_inventory_sha256=_digest("micro-stable-inventory"),
        structural_table_sha256=_digest(f"micro-structural-table:{output_name}"),
        schema_sha256=_digest(f"micro-schema:{output_name}"),
        transform_sha256=_digest(f"micro-transform:{output_name}"),
        ordered_columns=("entity_id",),
        transformer_dependencies=(),
        expected_candidate_id=f"star:{output_name}",
        candidate_sha256=_digest(f"micro-candidate:{output_name}"),
        candidate_kind="dimension",
        candidate_gate_requirement="stable_required",
        candidate_structural_sha256=_digest(f"micro-candidate-structure:{output_name}"),
        candidate_implementation_status="implemented",
        candidate_implementation_sha256=_digest(f"micro-candidate-implementation:{output_name}"),
        disposition_semantic_sha256=_digest(f"micro-disposition:{output_name}"),
        disposition_status="stable",
    )


def _micro_authorities() -> tuple[StarTableSemanticAuthorityV1, ...]:
    return tuple(sorted((_micro_authority("dim_alpha"), _micro_authority("dim_beta"))))


def _decoded(raw: bytes) -> dict[str, object]:
    value = json.loads(raw[:-1])
    assert type(value) is dict
    return value


def _repacked(payload: dict[str, object]) -> bytes:
    content = {key: value for key, value in payload.items() if key != "corpus_sha256"}
    payload["corpus_sha256"] = canonical_star_semantic_authoring_sha256(content)
    return canonical_star_semantic_authoring_json_bytes(payload) + b"\n"


def test_dimension_resource_freezes_exact_current_scope_without_blanket_decisions() -> None:
    raw = _resource_path().read_bytes()
    payload = _payload()
    structural = compile_star_table_contracts()
    dimensions = tuple(
        table.output_name for table in structural.tables if table.output_name.startswith("dim_")
    )
    decisions = payload["decisions"]
    blockers = payload["blockers"]
    assert type(decisions) is list
    assert type(blockers) is list

    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert canonical_star_semantic_authoring_json_bytes(payload) + b"\n" == raw
    assert payload["structural_inventory_sha256"] == structural.contract_sha256
    assert payload["stable_inventory_sha256"] == (
        "02840ce9ce15492d11a23ee27bc2020543bc9d07a41de9bbea44296a7b397ddc"
    )
    assert payload["authority_inventory_sha256"] == (
        "974664b40aa8cd07ca2cff94c891e79f56fdba129afdc4922a65a995f79c905f"
    )
    assert payload["denominator_count"] == len(dimensions) == 18
    assert tuple(item["table_name"] for item in decisions) == ("dim_season_phase",)
    assert tuple(payload["unreviewed_table_ids"]) == _UNREVIEWED_DIMENSIONS
    assert tuple(item["table_name"] for item in blockers) == _UNREVIEWED_DIMENSIONS
    assert set(dimensions) == {"dim_season_phase", *_UNREVIEWED_DIMENSIONS}
    assert len({item["authority_sha256"] for item in blockers}) == 17
    assert b"review_receipt" not in raw
    assert payload["corpus_sha256"] == canonical_star_semantic_authoring_sha256(
        {key: value for key, value in payload.items() if key != "corpus_sha256"}
    )


def test_season_phase_decision_binds_full_literal_semantics_and_evidence() -> None:
    decision = StarTableSemanticDecisionV1.from_dict(_decision_payload())
    authority_sha256 = decision.authority_sha256
    lineage = {edge.target_column: edge for edge in decision.lineage_edges}

    assert decision.table_name == "dim_season_phase"
    assert decision.purpose_code == "season_phase_reference_lookup"
    assert decision.purpose_evidence_sha256 == _evidence(
        authority_sha256=authority_sha256,
        evidence_class="purpose",
        claim={
            "consumer_role": "standalone_reference_dimension",
            "enumeration_rows": _EXPECTED_ROWS,
        },
    )
    assert decision.grain_dimensions == decision.observation_identity == ("phase_id",)
    assert decision.key_mode == "keyed"
    assert decision.key_groups[0].to_dict() == {
        "key_id": "phase_id",
        "key_kind": "natural",
        "columns": ["phase_id"],
        "null_policy": "forbidden",
        "evidence_sha256": _evidence(
            authority_sha256=authority_sha256,
            evidence_class="key",
            claim={
                "column": "phase_id",
                "expected_unique_values": [1, 2, 3, 4, 5, 6, 7, 8],
            },
        ),
    }
    assert decision.competition_discriminators == ()
    assert decision.request_discriminators == ()
    assert decision.source_mode == "reviewed_source_free"
    assert decision.relationships == decision.dependency_cardinalities == ()
    assert decision.functional_dependencies[0].to_dict() == {
        "dependency_id": "phase_lookup_values",
        "determinants": ["phase_id"],
        "dependents": ["phase_name", "phase_order"],
        "evidence_sha256": _evidence(
            authority_sha256=authority_sha256,
            evidence_class="functional_dependency",
            claim={
                "dependency_id": "phase_lookup_values",
                "dependents": ["phase_name", "phase_order"],
                "determinants": ["phase_id"],
                "enumeration_rows": _EXPECTED_ROWS,
            },
        ),
    }
    assert decision.row_policy.to_dict() == {
        "row_mode": "entity",
        "filter_policy": "preserve",
        "dedup_policy": "none",
        "union_policy": "none",
        "aggregation_policy": "none",
        "additivity": "not_applicable",
        "evidence_sha256": _evidence(
            authority_sha256=authority_sha256,
            evidence_class="row_policy",
            claim={"expected_row_count": 8, "enumeration_rows": _EXPECTED_ROWS},
        ),
    }
    assert decision.temporal_policy.evidence_sha256 == _evidence(
        authority_sha256=authority_sha256,
        evidence_class="temporal_policy",
        claim={"fixed_reference_enumeration": True, "temporal_columns": []},
    )
    assert decision.temporal_policy.event_columns == ()
    assert decision.temporal_policy.observation_columns == ()
    assert decision.temporal_policy.version_columns == ()
    assert decision.temporal_policy.correction_policy == "latest_truth"
    assert decision.temporal_policy.truth_mode == "current_truth"
    assert decision.scd_policy == "type1"
    assert decision.algorithm_id == "season-phase-enumeration"
    assert decision.algorithm_version == "v1"
    assert decision.coverage_policy == "complete_scope"
    assert decision.incomplete_policy == "reject"
    assert decision.empty_policy == "reject_empty"
    assert decision.unavailable_policy == "not_applicable"
    assert set(lineage) == {"phase_id", "phase_name", "phase_order"}
    for column, edge in lineage.items():
        claim = {"enumeration_rows": _EXPECTED_ROWS, "target_column": column}
        assert edge.source_kind == "literal"
        assert edge.source_ids == (f"literal:dim_season_phase:{column}",)
        assert edge.source_dependency_ids == ()
        assert edge.transform_kind == "expression"
        assert edge.expression_sha256 == _evidence(
            authority_sha256=authority_sha256,
            evidence_class=f"expression:{column}",
            claim=claim,
        )
        assert edge.evidence_sha256 == _evidence(
            authority_sha256=authority_sha256,
            evidence_class=f"lineage:{column}",
            claim=claim,
        )
    assert decision.positive_witness_sha256s == (
        _evidence(
            authority_sha256=authority_sha256,
            evidence_class="positive_validation",
            claim={"expected_rows": _EXPECTED_ROWS, "schema_validation": "pass"},
        ),
    )
    assert decision.negative_witness_sha256s == (
        _evidence(
            authority_sha256=authority_sha256,
            evidence_class="negative_validation",
            claim={
                "case": "duplicate_phase_id",
                "mutated_row": [1, "Duplicate", 9],
            },
        ),
    )
    assert decision.mutation_witness_sha256s == (
        _evidence(
            authority_sha256=authority_sha256,
            evidence_class="mutation_validation",
            claim={
                "case": "phase_name_changed",
                "mutated_row": [8, "Changed", 8],
            },
        ),
    )


def test_season_phase_positive_negative_and_mutation_witnesses_execute() -> None:
    result = DimSeasonPhaseTransformer().transform({})
    expected_dicts = [
        {"phase_id": row[0], "phase_name": row[1], "phase_order": row[2]} for row in _EXPECTED_ROWS
    ]

    assert result.to_dicts() == expected_dicts
    assert DimSeasonPhaseSchema.validate(result).to_dicts() == expected_dicts

    duplicate = pl.concat(
        [
            result,
            pl.DataFrame(
                {"phase_id": [1], "phase_name": ["Duplicate"], "phase_order": [9]},
                schema={"phase_id": pl.Int32, "phase_name": pl.String, "phase_order": pl.Int32},
            ),
        ]
    )
    with pytest.raises(pandera.errors.SchemaError):
        DimSeasonPhaseSchema.validate(duplicate)

    mutated = deepcopy(_decision_payload())
    mutated["purpose_code"] = "mutated_phase_semantics"
    with pytest.raises(StarSemanticAuthoringContractError, match="digest"):
        StarTableSemanticDecisionV1.from_dict(mutated)


@pytest.mark.parametrize(
    "mutation",
    ("missing", "extra", "duplicate", "stale"),
)
def test_strict_parser_rejects_blocker_denominator_mutations(mutation: str) -> None:
    authorities = _micro_authorities()
    raw = compile_star_semantic_decision_corpus_bytes(
        authorities=authorities,
        decision_shards=(),
    )
    payload = _decoded(raw)
    blockers = payload["blockers"]
    unreviewed = payload["unreviewed_table_ids"]
    assert type(blockers) is list and type(unreviewed) is list
    if mutation == "missing":
        blockers.pop()
    elif mutation == "extra":
        blockers.append(
            {
                "table_name": "dim_foreign",
                "authority_sha256": _digest("foreign"),
                "blocker_codes": list(payload["blocker_codes"]),
            }
        )
    elif mutation == "duplicate":
        blockers.append(dict(cast("dict[str, object]", blockers[0])))
    else:
        blockers[0]["authority_sha256"] = _digest("stale-blocker-authority")

    with pytest.raises(StarSemanticDecisionCorpusError):
        parse_star_semantic_decision_corpus(
            _repacked(payload),
            authorities=authorities,
        )


def test_strict_packer_rejects_duplicate_foreign_and_stale_decision_shards() -> None:
    authorities = _micro_authorities()
    decision = StarTableSemanticDecisionV1.from_dict(_decision_payload())

    with pytest.raises(StarSemanticDecisionCorpusError, match="duplicate table IDs"):
        compile_star_semantic_decision_corpus_bytes(
            authorities=authorities,
            decision_shards=(decision, decision),
        )
    with pytest.raises(StarSemanticDecisionCorpusError, match="foreign table ID"):
        compile_star_semantic_decision_corpus_bytes(
            authorities=authorities,
            decision_shards=(decision,),
        )
    stale = replace(
        decision,
        table_name="dim_alpha",
        authority_sha256=_digest("stale-decision-authority"),
    )
    with pytest.raises(StarSemanticDecisionCorpusError, match="stale"):
        compile_star_semantic_decision_corpus_bytes(
            authorities=authorities,
            decision_shards=(stale,),
        )


def test_parser_rejects_missing_extra_duplicate_and_stale_authority_rows() -> None:
    authorities = _micro_authorities()
    raw = compile_star_semantic_decision_corpus_bytes(
        authorities=authorities,
        decision_shards=(),
    )
    extra = tuple(sorted((*authorities, _micro_authority("dim_gamma"))))
    stale = (replace(authorities[0], schema_sha256=_digest("stale-schema")), authorities[1])

    for invalid in (
        authorities[:1],
        extra,
        (authorities[0], authorities[0]),
        stale,
    ):
        with pytest.raises(StarSemanticDecisionCorpusError):
            parse_star_semantic_decision_corpus(raw, authorities=invalid)
