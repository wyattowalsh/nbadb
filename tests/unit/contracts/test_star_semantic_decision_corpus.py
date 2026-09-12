from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.contracts.star_semantic_authoring import (
    StarTableSemanticDecisionV1,
    canonical_star_semantic_authoring_json_bytes,
    canonical_star_semantic_authoring_sha256,
)
from nbadb.contracts.star_semantic_contract import (
    ColumnLineageEdgeV1,
    KeyGroupV1,
    RowPolicyV1,
    TemporalPolicyV1,
)
from nbadb.contracts.star_semantic_decision_corpus import (
    StarSemanticDecisionCorpusError,
    compile_star_semantic_decision_corpus_bytes,
    load_star_semantic_decision_corpus,
    parse_star_semantic_decision_corpus,
    star_semantic_decision_corpus_path,
)
from nbadb.contracts.star_semantic_inventory import StarTableSemanticAuthorityV1
from nbadb.contracts.star_table_contract import compile_star_table_contracts

if TYPE_CHECKING:
    from pathlib import Path


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _authority(output_name: str) -> StarTableSemanticAuthorityV1:
    return StarTableSemanticAuthorityV1(
        output_name=output_name,
        table_family="dimension",
        structural_inventory_sha256=_digest("structural-inventory"),
        stable_inventory_sha256=_digest("stable-inventory"),
        structural_table_sha256=_digest(f"structural-table:{output_name}"),
        schema_sha256=_digest(f"schema:{output_name}"),
        transform_sha256=_digest(f"transform:{output_name}"),
        ordered_columns=("entity_id",),
        transformer_dependencies=(),
        expected_candidate_id=f"star:{output_name}",
        candidate_sha256=_digest(f"candidate:{output_name}"),
        candidate_kind="dimension",
        candidate_gate_requirement="stable_required",
        candidate_structural_sha256=_digest(f"candidate-structure:{output_name}"),
        candidate_implementation_status="implemented",
        candidate_implementation_sha256=_digest(f"candidate-implementation:{output_name}"),
        disposition_semantic_sha256=_digest(f"disposition:{output_name}"),
        disposition_status="stable",
    )


def _authorities() -> tuple[StarTableSemanticAuthorityV1, ...]:
    return tuple(sorted((_authority("dim_alpha"), _authority("dim_beta"))))


def _decision(authority: StarTableSemanticAuthorityV1) -> StarTableSemanticDecisionV1:
    return StarTableSemanticDecisionV1(
        table_name=authority.output_name,
        authority_sha256=authority.authority_sha256,
        purpose_code=f"purpose:{authority.output_name}",
        purpose_evidence_sha256=_digest(f"purpose:{authority.output_name}"),
        grain_dimensions=("entity_id",),
        observation_identity=("entity_id",),
        key_mode="keyed",
        key_groups=(
            KeyGroupV1(
                key_id="natural",
                key_kind="natural",
                columns=("entity_id",),
                null_policy="forbidden",
                evidence_sha256=_digest(f"key:{authority.output_name}"),
            ),
        ),
        functional_dependencies=(),
        relationships=(),
        lineage_edges=(
            ColumnLineageEdgeV1(
                edge_id="lineage:entity_id",
                target_column="entity_id",
                source_kind="literal",
                source_ids=(f"literal:{authority.output_name}:entity_id",),
                source_dependency_ids=(),
                transform_kind="expression",
                expression_sha256=_digest(f"expression:{authority.output_name}"),
                evidence_sha256=_digest(f"lineage:{authority.output_name}"),
            ),
        ),
        competition_discriminators=(),
        request_discriminators=(),
        source_mode="reviewed_source_free",
        row_policy=RowPolicyV1(
            row_mode="entity",
            filter_policy="preserve",
            dedup_policy="none",
            union_policy="none",
            aggregation_policy="none",
            additivity="not_applicable",
            evidence_sha256=_digest(f"row:{authority.output_name}"),
        ),
        temporal_policy=TemporalPolicyV1(
            event_columns=(),
            observation_columns=(),
            load_columns=(),
            version_columns=(),
            feature_cutoff_columns=(),
            correction_policy="latest_truth",
            truth_mode="current_truth",
            evidence_sha256=_digest(f"temporal:{authority.output_name}"),
        ),
        scd_policy="type1",
        algorithm_id=f"algorithm:{authority.output_name}",
        algorithm_version="v1",
        coverage_policy="complete_scope",
        incomplete_policy="reject",
        empty_policy="materialize_typed_empty",
        unavailable_policy="typed_unavailable",
        dependency_cardinalities=(),
        positive_witness_sha256s=(_digest(f"positive:{authority.output_name}"),),
        negative_witness_sha256s=(_digest(f"negative:{authority.output_name}"),),
        mutation_witness_sha256s=(_digest(f"mutation:{authority.output_name}"),),
    )


def _decoded(raw: bytes) -> dict[str, object]:
    value = json.loads(raw[:-1])
    assert type(value) is dict
    return value


def _repacked(payload: dict[str, object], *, update_digest: bool = True) -> bytes:
    if update_digest:
        content = {key: value for key, value in payload.items() if key != "corpus_sha256"}
        payload["corpus_sha256"] = canonical_star_semantic_authoring_sha256(content)
    return canonical_star_semantic_authoring_json_bytes(payload) + b"\n"


def test_checked_corpus_freezes_exact_current_261_table_denominator() -> None:
    raw = star_semantic_decision_corpus_path().read_bytes()
    payload = _decoded(raw)
    dimension_payload = _decoded(
        star_semantic_decision_corpus_path()
        .with_name("star-semantic-decisions-dimensions-v1.json")
        .read_bytes()
    )
    structural = compile_star_table_contracts()
    table_names = tuple(table.output_name for table in structural.tables)
    unreviewed_table_names = tuple(
        table_name for table_name in table_names if table_name != "dim_season_phase"
    )
    decisions = payload["decisions"]
    dimension_decisions = dimension_payload["decisions"]
    assert type(decisions) is list and len(decisions) == 1
    assert type(dimension_decisions) is list and len(dimension_decisions) == 1

    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    assert canonical_star_semantic_authoring_json_bytes(payload) + b"\n" == raw
    assert payload["structural_inventory_sha256"] == structural.contract_sha256
    assert payload["denominator_count"] == len(table_names) == 261
    assert tuple(item["table_name"] for item in decisions) == ("dim_season_phase",)
    assert decisions[0] == dimension_decisions[0]
    assert canonical_star_semantic_authoring_json_bytes(
        decisions[0]
    ) == canonical_star_semantic_authoring_json_bytes(dimension_decisions[0])
    assert tuple(payload["unreviewed_table_ids"]) == unreviewed_table_names
    blockers = payload["blockers"]
    assert type(blockers) is list
    assert len(blockers) == 260
    assert tuple(item["table_name"] for item in blockers) == unreviewed_table_names
    assert len({item["authority_sha256"] for item in blockers}) == 260
    assert b"review_receipt" not in raw
    assert payload["corpus_sha256"] == canonical_star_semantic_authoring_sha256(
        {key: value for key, value in payload.items() if key != "corpus_sha256"}
    )


def test_empty_shard_is_exactly_blocked_and_never_admitted() -> None:
    authorities = _authorities()
    raw = compile_star_semantic_decision_corpus_bytes(
        authorities=authorities,
        decision_shards=(),
    )
    corpus = parse_star_semantic_decision_corpus(raw, authorities=authorities)

    assert corpus.decisions == ()
    assert corpus.unreviewed_table_ids == ("dim_alpha", "dim_beta")
    assert len(corpus.blockers) == 2
    assert all(
        blocker.codes
        == (
            "semantic_decision_not_authored",
            "table_specific_semantic_evidence_unreviewed",
        )
        for blocker in corpus.blockers
    )
    assert corpus.admitted is False
    assert corpus.model_green is False
    generation = corpus.authoring_generation()
    assert generation.candidates == ()
    assert {blocker.code for blocker in generation.blockers} >= {
        "frozen_authority_completeness_unproven",
        "semantic_decision_missing",
    }


def test_independently_authored_shard_merges_only_by_exact_table_id() -> None:
    authorities = _authorities()
    decision = _decision(authorities[1])
    raw = compile_star_semantic_decision_corpus_bytes(
        authorities=authorities,
        decision_shards=(decision,),
    )
    corpus = parse_star_semantic_decision_corpus(raw, authorities=authorities)

    assert tuple(corpus.by_table_name) == ("dim_beta",)
    assert corpus.by_table_name["dim_beta"] == decision
    assert corpus.unreviewed_table_ids == ("dim_alpha",)
    assert tuple(blocker.table_name for blocker in corpus.blockers) == ("dim_alpha",)
    assert len(corpus.authoring_generation().candidates) == 1
    assert corpus.admitted is False
    assert corpus.model_green is False
    with pytest.raises(TypeError):
        corpus.by_table_name["dim_alpha"] = decision  # type: ignore[index]


def test_canonical_packer_is_order_independent_but_rejects_duplicate_shards() -> None:
    authorities = _authorities()
    decisions = tuple(_decision(authority) for authority in authorities)

    assert compile_star_semantic_decision_corpus_bytes(
        authorities=authorities,
        decision_shards=decisions,
    ) == compile_star_semantic_decision_corpus_bytes(
        authorities=authorities,
        decision_shards=tuple(reversed(decisions)),
    )
    with pytest.raises(StarSemanticDecisionCorpusError, match="duplicate table IDs"):
        compile_star_semantic_decision_corpus_bytes(
            authorities=authorities,
            decision_shards=(decisions[0], decisions[0]),
        )


def test_canonical_packer_rejects_foreign_and_stale_shards() -> None:
    authorities = _authorities()
    foreign = _decision(_authority("dim_foreign"))
    stale = replace(
        _decision(authorities[0]),
        authority_sha256=_digest("foreign-authority"),
    )

    with pytest.raises(StarSemanticDecisionCorpusError, match="foreign table ID"):
        compile_star_semantic_decision_corpus_bytes(
            authorities=authorities,
            decision_shards=(foreign,),
        )
    with pytest.raises(StarSemanticDecisionCorpusError, match="stale"):
        compile_star_semantic_decision_corpus_bytes(
            authorities=authorities,
            decision_shards=(stale,),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_blocker",
        "extra_blocker",
        "stale_blocker",
        "unreviewed_gap",
        "denominator_drift",
    ),
)
def test_parser_rejects_incomplete_or_foreign_blocker_denominators(
    mutation: str,
) -> None:
    authorities = _authorities()
    payload = _decoded(
        compile_star_semantic_decision_corpus_bytes(
            authorities=authorities,
            decision_shards=(),
        )
    )
    blockers = payload["blockers"]
    unreviewed = payload["unreviewed_table_ids"]
    assert type(blockers) is list
    assert type(unreviewed) is list
    if mutation == "missing_blocker":
        blockers.pop()
    elif mutation == "extra_blocker":
        blockers.append(dict(cast("dict[str, object]", blockers[0])))
    elif mutation == "stale_blocker":
        blockers[0]["authority_sha256"] = _digest("stale-blocker")
    elif mutation == "unreviewed_gap":
        unreviewed.pop()
    else:
        payload["denominator_count"] = 3

    with pytest.raises(StarSemanticDecisionCorpusError):
        parse_star_semantic_decision_corpus(
            _repacked(payload),
            authorities=authorities,
        )


def test_parser_rejects_digest_mutation_noncanonical_bytes_and_stale_authority() -> None:
    authorities = _authorities()
    raw = compile_star_semantic_decision_corpus_bytes(
        authorities=authorities,
        decision_shards=(),
    )
    payload = _decoded(raw)
    payload["denominator_count"] = 3

    with pytest.raises(StarSemanticDecisionCorpusError, match="digest"):
        parse_star_semantic_decision_corpus(
            _repacked(payload, update_digest=False),
            authorities=authorities,
        )
    with pytest.raises(StarSemanticDecisionCorpusError, match="canonical"):
        parse_star_semantic_decision_corpus(raw + b"\n", authorities=authorities)
    stale_authorities = (
        replace(authorities[0], schema_sha256=_digest("stale-schema")),
        authorities[1],
    )
    with pytest.raises(StarSemanticDecisionCorpusError, match="stale or foreign"):
        parse_star_semantic_decision_corpus(raw, authorities=stale_authorities)


def test_loader_rejects_missing_and_symlinked_resources(tmp_path: Path) -> None:
    authorities = _authorities()
    missing = tmp_path / "missing.json"
    target = tmp_path / "target.json"
    target.write_bytes(
        compile_star_semantic_decision_corpus_bytes(
            authorities=authorities,
            decision_shards=(),
        )
    )
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(StarSemanticDecisionCorpusError, match="regular non-symlink"):
        load_star_semantic_decision_corpus(authorities=authorities, path=missing)
    with pytest.raises(StarSemanticDecisionCorpusError, match="regular non-symlink"):
        load_star_semantic_decision_corpus(authorities=authorities, path=link)
