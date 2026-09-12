from __future__ import annotations

import ast
import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from nbadb.contracts import rebind_star_semantic_decision_corpora as rebind
from nbadb.contracts import star_semantic_decision_corpus as corpus_contract
from nbadb.contracts.star_semantic_authoring import (
    StarTableSemanticDecisionV1,
    canonical_star_semantic_authoring_json_bytes,
    canonical_star_semantic_authoring_sha256,
)
from nbadb.contracts.star_semantic_decision_corpus import (
    StarSemanticDecisionCorpusError,
    parse_star_semantic_decision_corpus,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module")
def fresh_rebinds() -> tuple[
    rebind.StarSemanticCorpusRebindV1,
    rebind.StarSemanticCorpusRebindV1,
]:
    return (
        rebind.build_rebound_star_semantic_decision_corpora(),
        rebind.build_rebound_star_semantic_decision_corpora(),
    )


def _repacked(payload: dict[str, object]) -> bytes:
    content = {key: value for key, value in payload.items() if key != "corpus_sha256"}
    payload["corpus_sha256"] = canonical_star_semantic_authoring_sha256(content)
    return canonical_star_semantic_authoring_json_bytes(payload) + b"\n"


def _fixture_payload(name: str) -> dict[str, object]:
    raw = rebind._old_fixture_path(name).read_bytes()  # noqa: SLF001
    value = json.loads(raw[:-1])
    assert type(value) is dict
    return value


def test_two_fresh_rebinds_are_byte_identical_and_replay_exact_roots(
    fresh_rebinds: tuple[
        rebind.StarSemanticCorpusRebindV1,
        rebind.StarSemanticCorpusRebindV1,
    ],
) -> None:
    first, second = fresh_rebinds

    assert first.main_corpus_bytes == second.main_corpus_bytes
    assert first.dimension_corpus_bytes == second.dimension_corpus_bytes
    assert first.old_candidate.candidate_sha256 == rebind._OLD_CANDIDATE_SHA256  # noqa: SLF001
    assert (
        first.old_disposition.semantic_sha256 == rebind._OLD_DISPOSITION_SEMANTIC_SHA256  # noqa: SLF001
    )
    assert first.old_authority.authority_sha256 == rebind._OLD_AUTHORITY_SHA256  # noqa: SLF001
    assert first.old_decision.decision_sha256 == rebind._OLD_DECISION_SHA256  # noqa: SLF001
    assert (
        first.current_candidate.candidate_sha256 == rebind._CURRENT_CANDIDATE_SHA256  # noqa: SLF001
    )
    assert (
        first.current_disposition.semantic_sha256 == rebind._CURRENT_DISPOSITION_SEMANTIC_SHA256  # noqa: SLF001
    )
    assert (
        first.current_authority.authority_sha256 == rebind._CURRENT_AUTHORITY_SHA256  # noqa: SLF001
    )
    assert len(first.current_authorities) == 261
    assert len(first.current_dimension_authorities) == 18
    assert first.authority_admitted is False
    assert first.model_green is False


def test_rebind_changes_only_the_explicit_authority_bound_digest_paths(
    fresh_rebinds: tuple[
        rebind.StarSemanticCorpusRebindV1,
        rebind.StarSemanticCorpusRebindV1,
    ],
) -> None:
    rebound = fresh_rebinds[0]
    changed = rebind._diff_paths(  # noqa: SLF001
        rebound.old_decision.to_dict(),
        rebound.rebound_decision.to_dict(),
    )

    assert changed == rebind._AUTHORITY_BOUND_DECISION_PATHS  # noqa: SLF001
    assert rebound.authority_bound_changed_paths == tuple(sorted(changed))
    assert len(changed) == 16
    assert all(
        path == "authority_sha256"
        or path == "decision_sha256"
        or "evidence_sha256" in path
        or "witness_sha256s" in path
        or "expression_sha256" in path
        for path in changed
    )


def test_rebound_corpora_have_exact_red_denominators_and_identical_decision(
    fresh_rebinds: tuple[
        rebind.StarSemanticCorpusRebindV1,
        rebind.StarSemanticCorpusRebindV1,
    ],
) -> None:
    rebound = fresh_rebinds[0]
    main = parse_star_semantic_decision_corpus(
        rebound.main_corpus_bytes,
        authorities=rebound.current_authorities,
    )
    dimensions = parse_star_semantic_decision_corpus(
        rebound.dimension_corpus_bytes,
        authorities=rebound.current_dimension_authorities,
    )

    assert len(main.authorities) == 261
    assert len(main.decisions) == 1
    assert len(main.unreviewed_table_ids) == len(main.blockers) == 260
    assert len(dimensions.authorities) == 18
    assert len(dimensions.decisions) == 1
    assert len(dimensions.unreviewed_table_ids) == len(dimensions.blockers) == 17
    assert main.decisions == dimensions.decisions == (rebound.rebound_decision,)
    assert main.admitted is dimensions.admitted is False
    assert main.model_green is dimensions.model_green is False
    assert b"review_receipt" not in rebound.main_corpus_bytes
    assert b"review_receipt" not in rebound.dimension_corpus_bytes


@pytest.mark.parametrize("scope", ("main", "dimensions"))
def test_current_corpora_reject_self_resealed_adjacent_blocker_order(
    fresh_rebinds: tuple[
        rebind.StarSemanticCorpusRebindV1,
        rebind.StarSemanticCorpusRebindV1,
    ],
    scope: str,
) -> None:
    rebound = fresh_rebinds[0]
    if scope == "main":
        raw = rebound.main_corpus_bytes
        authorities = rebound.current_authorities
    else:
        raw = rebound.dimension_corpus_bytes
        authorities = rebound.current_dimension_authorities
    payload = json.loads(raw[:-1])
    assert type(payload) is dict
    blockers = payload["blockers"]
    assert type(blockers) is list and len(blockers) >= 2
    blockers[0], blockers[1] = blockers[1], blockers[0]

    with pytest.raises(StarSemanticDecisionCorpusError, match="blockers"):
        parse_star_semantic_decision_corpus(
            _repacked(payload),
            authorities=authorities,
        )


@pytest.mark.parametrize("scope", ("main", "dimensions"))
def test_current_corpora_reject_self_resealed_adjacent_authority_order(
    fresh_rebinds: tuple[
        rebind.StarSemanticCorpusRebindV1,
        rebind.StarSemanticCorpusRebindV1,
    ],
    scope: str,
) -> None:
    rebound = fresh_rebinds[0]
    if scope == "main":
        raw = rebound.main_corpus_bytes
        authorities = list(rebound.current_authorities)
    else:
        raw = rebound.dimension_corpus_bytes
        authorities = list(rebound.current_dimension_authorities)
    payload = json.loads(raw[:-1])
    assert type(payload) is dict and len(authorities) >= 2
    authorities[0], authorities[1] = authorities[1], authorities[0]
    reordered = tuple(authorities)
    payload["authority_inventory_sha256"] = corpus_contract._authority_inventory_sha256(  # noqa: SLF001
        reordered
    )

    with pytest.raises(StarSemanticDecisionCorpusError, match="sorted"):
        parse_star_semantic_decision_corpus(
            _repacked(payload),
            authorities=reordered,
        )


def test_old_fixtures_are_exact_canonical_pinned_inputs() -> None:
    fixture_rows = (
        (
            rebind._OLD_MAIN_FIXTURE_NAME,  # noqa: SLF001
            rebind._OLD_MAIN_BYTE_COUNT,  # noqa: SLF001
            rebind._OLD_MAIN_BYTES_SHA256,  # noqa: SLF001
        ),
        (
            rebind._OLD_DIMENSION_FIXTURE_NAME,  # noqa: SLF001
            rebind._OLD_DIMENSION_BYTE_COUNT,  # noqa: SLF001
            rebind._OLD_DIMENSION_BYTES_SHA256,  # noqa: SLF001
        ),
    )
    decisions: list[object] = []
    for name, expected_size, expected_sha256 in fixture_rows:
        raw = rebind._old_fixture_path(name).read_bytes()  # noqa: SLF001
        payload = rebind._strict_canonical_payload(raw, label=name)  # noqa: SLF001
        assert len(raw) == expected_size
        assert hashlib.sha256(raw).hexdigest() == expected_sha256
        decision_rows = payload["decisions"]
        assert type(decision_rows) is list and len(decision_rows) == 1
        decisions.append(decision_rows[0])
    assert decisions[0] == decisions[1]
    assert canonical_star_semantic_authoring_json_bytes(
        decisions[0]
    ) == canonical_star_semantic_authoring_json_bytes(decisions[1])


def test_old_fixture_root_and_strict_json_mutations_fail_closed(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload(rebind._OLD_MAIN_FIXTURE_NAME)  # noqa: SLF001
    payload["structural_inventory_sha256"] = "f" * 64
    mutated = _repacked(payload)
    path = tmp_path / rebind._OLD_MAIN_FIXTURE_NAME  # noqa: SLF001
    path.write_bytes(mutated)

    original_path = rebind._old_fixture_path  # noqa: SLF001
    try:
        rebind._old_fixture_path = lambda _name: path  # type: ignore[assignment]  # noqa: SLF001
        with pytest.raises(rebind.StarSemanticCorpusRebindError, match="structural"):
            rebind._load_pinned_old_fixture(  # noqa: SLF001
                name=rebind._OLD_MAIN_FIXTURE_NAME,  # noqa: SLF001
                expected_byte_count=len(mutated),
                expected_bytes_sha256=hashlib.sha256(mutated).hexdigest(),
                expected_authority_inventory_sha256=(
                    rebind._OLD_MAIN_AUTHORITY_INVENTORY_SHA256  # noqa: SLF001
                ),
                expected_corpus_sha256=cast_str(payload["corpus_sha256"]),
            )
    finally:
        rebind._old_fixture_path = original_path  # type: ignore[assignment]  # noqa: SLF001

    canonical = rebind._old_fixture_path(  # noqa: SLF001
        rebind._OLD_MAIN_FIXTURE_NAME  # noqa: SLF001
    ).read_bytes()
    with pytest.raises(rebind.StarSemanticCorpusRebindError, match="canonical"):
        rebind._strict_canonical_payload(  # noqa: SLF001
            canonical[:-1] + b" \n", label="noncanonical"
        )
    duplicate = b'{"schema_version":1,"schema_version":1}\n'
    with pytest.raises(rebind.StarSemanticCorpusRebindError, match="duplicate"):
        rebind._strict_canonical_payload(duplicate, label="duplicate")  # noqa: SLF001


def cast_str(value: object) -> str:
    assert type(value) is str
    return value


@pytest.mark.parametrize("mutation", ("extra_decision", "blocker_drift"))
def test_old_denominator_mutations_fail_closed(mutation: str) -> None:
    payload = _fixture_payload(rebind._OLD_MAIN_FIXTURE_NAME)  # noqa: SLF001
    decisions = payload["decisions"]
    blockers = payload["blockers"]
    assert type(decisions) is list
    assert type(blockers) is list
    if mutation == "extra_decision":
        decisions.append(deepcopy(decisions[0]))
    else:
        blocker = blockers[0]
        assert type(blocker) is dict
        blocker["blocker_codes"] = ["semantic_decision_not_authored"]
    names = tuple(
        item["table_name"]
        for item in blockers
        if type(item) is dict and type(item.get("table_name")) is str
    )
    expected_names = tuple(sorted(("dim_season_phase", *names)))
    with pytest.raises(rebind.StarSemanticCorpusRebindError):
        rebind._validate_old_payload_denominator(  # noqa: SLF001
            payload,
            expected_names=expected_names,
        )


def test_semantic_literal_and_witness_mutations_are_not_rebindable(
    fresh_rebinds: tuple[
        rebind.StarSemanticCorpusRebindV1,
        rebind.StarSemanticCorpusRebindV1,
    ],
) -> None:
    rebound = fresh_rebinds[0]
    old_payload = rebound.old_decision.to_dict()
    semantic_mutation = deepcopy(old_payload)
    semantic_mutation["algorithm_version"] = "v2"
    witness_mutation = deepcopy(old_payload)
    witness_mutation["positive_witness_sha256s"] = ["f" * 64]

    for payload in (semantic_mutation, witness_mutation):
        with pytest.raises(Exception, match="digest"):
            StarTableSemanticDecisionV1.from_dict(payload)
        assert (
            rebind._diff_paths(old_payload, payload)  # noqa: SLF001
            != rebind._AUTHORITY_BOUND_DECISION_PATHS  # noqa: SLF001
        )


@pytest.mark.parametrize(
    "drift",
    ("candidate", "schema", "transform_dependencies", "disposition"),
)
def test_table_local_candidate_and_disposition_drift_fail_theorem(
    fresh_rebinds: tuple[
        rebind.StarSemanticCorpusRebindV1,
        rebind.StarSemanticCorpusRebindV1,
    ],
    drift: str,
) -> None:
    rebound = fresh_rebinds[0]
    current_candidate = rebound.current_candidate
    current_disposition = rebound.current_disposition
    current_authority = rebound.current_authority
    if drift == "candidate":
        current_candidate = replace(current_candidate, dependency_ids=("star:dim_team",))
    elif drift == "schema":
        current_authority = replace(current_authority, schema_sha256="f" * 64)
    elif drift == "transform_dependencies":
        current_authority = replace(
            current_authority,
            transformer_dependencies=("stg_foreign",),
        )
    else:
        current_disposition = replace(
            current_disposition,
            reason_code="requirement:mutated",
        )
    with pytest.raises(rebind.StarSemanticCorpusRebindError, match="drift"):
        rebind._assert_model_invariants(  # noqa: SLF001
            old_candidate=rebound.old_candidate,
            current_candidate=current_candidate,
            old_disposition=rebound.old_disposition,
            current_disposition=current_disposition,
            old_authority=rebound.old_authority,
            current_authority=current_authority,
        )


def test_source_mutation_changes_evidence_but_not_semantic_claims(
    fresh_rebinds: tuple[
        rebind.StarSemanticCorpusRebindV1,
        rebind.StarSemanticCorpusRebindV1,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rebound = fresh_rebinds[0]
    monkeypatch.setattr(rebind, "_source_sha256", lambda _value: "f" * 64)
    mutated = rebind._build_season_phase_decision(rebound.old_authority)  # noqa: SLF001

    assert mutated != rebound.old_decision
    changed = rebind._diff_paths(  # noqa: SLF001
        rebound.old_decision.to_dict(), mutated.to_dict()
    )
    assert changed == rebind._AUTHORITY_BOUND_DECISION_PATHS - {"authority_sha256"}


def test_module_has_no_generic_cli_subprocess_receipt_or_green_path() -> None:
    source = inspect.getsource(rebind)
    tree = ast.parse(source)
    forbidden_names = {
        "ReviewReceiptV1",
        "argparse",
        "click",
        "requests",
        "subprocess",
        "typer",
        "urllib",
    }
    loaded_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }

    assert loaded_names.isdisjoint(forbidden_names)
    assert "authority_admitted: Literal[False]" in source
    assert "model_green: Literal[False]" in source
    assert "def main(" not in source
    assert "def build_rebound_star_semantic_decision_corpora()" in source
    assert "ReviewReceiptV1" not in source
    assert source.count("review_receipts=()") == 1
