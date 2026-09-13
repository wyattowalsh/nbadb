"""Authority-preserving rebind for the sole authored star semantic decision.

This module is intentionally table-specific and red-only.  It replays the
historical ``dim_season_phase`` authority from immutable corpus fixtures,
derives the complete current structural/stable authority denominator, proves
that every non-generation-bound semantic input is unchanged, and then
recomputes only the explicitly enumerated authority-bound evidence digests.

It neither authors another decision nor issues review/admission evidence.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from nbadb.contracts.model_candidate_census import (
    canonical_analytical_needs_authority_v1,
    compile_current_model_candidate_census,
)
from nbadb.contracts.stable_model_disposition import (
    StableModelCandidateV1,
    StableModelDispositionV1,
    compile_stable_model_disposition_inventory,
    draft_required_model_dispositions,
)
from nbadb.contracts.star_semantic_authoring import (
    StarTableSemanticDecisionV1,
    canonical_star_semantic_authoring_json_bytes,
    canonical_star_semantic_authoring_sha256,
)
from nbadb.contracts.star_semantic_contract import (
    ColumnLineageEdgeV1,
    FunctionalDependencyV1,
    KeyGroupV1,
    RowPolicyV1,
    TemporalPolicyV1,
)
from nbadb.contracts.star_semantic_decision_corpus import (
    compile_star_semantic_decision_corpus_bytes,
    parse_star_semantic_decision_corpus,
    star_semantic_decision_corpus_path,
)
from nbadb.contracts.star_semantic_inventory import (
    StarTableSemanticAuthorityV1,
    derive_star_semantic_authorities,
)
from nbadb.contracts.star_table_contract import compile_star_table_contracts
from nbadb.schemas.star.dim_season_phase import DimSeasonPhaseSchema
from nbadb.transform.dimensions.dim_season_phase import DimSeasonPhaseTransformer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "StarSemanticCorpusRebindError",
    "StarSemanticCorpusRebindV1",
    "build_rebound_star_semantic_decision_corpora",
    "write_rebound_star_semantic_decision_corpora",
]

_TABLE_NAME = "dim_season_phase"
_OLD_STRUCTURAL_SHA256 = "05159cb4feffed20649cbb9b4a602019ee2929278099261e7ed512d4a9191e5b"
_OLD_STABLE_SHA256 = "70e306bc7eac6d4127e8eafb7aedd08896431f2e34813eab9cda87b3cd192a12"
_OLD_CANDIDATE_SOURCE_SHA256 = "55195f220b00b71c7828f9308f9697dd6e1ce0ed59c63b49b685a936fc30b95c"
_OLD_CANDIDATE_SHA256 = "dd162405a1381fd948cbbf649124570104e527fad93171766b0869ad05326ee5"
_OLD_DISPOSITION_SEMANTIC_SHA256 = (
    "31f97cc23ccbf0998f4340d1304363bb4c6c942adaebc26a3e357a04db6ff06b"
)
_OLD_AUTHORITY_SHA256 = "854d929fab0206d9ffa4eecdfcf53cd1d26bb9ccf109601851be17fe5b71506c"
_OLD_DECISION_SHA256 = "306674d25e0b38a489fde10ba97dce54d221b882e10eccf598574e2ff7207f98"
_CURRENT_STRUCTURAL_SHA256 = "c76385e19091181d1870912ccff607fde75361f66692e20659ae9434ea24d827"
_CURRENT_CENSUS_SHA256 = "245283ba808444ff5605baf2120959339b1d32fedbbad7408237204b81856263"
_CURRENT_CANDIDATE_SOURCE_SHA256 = (
    "cc8077be7ca9a0bcdcd6ea09305659aead3eae2992a0254f3225354892937372"
)
_CURRENT_STABLE_SHA256 = "1d6ab5555eb840f857bb460ec3dc79e0e9e79059b4686123297c3c2f905e5656"
_CURRENT_CANDIDATE_SHA256 = "ab0b79e1f334548e1e2d1db97ac8236fd89de8b8a92cd53b61ed7f8270cde5c5"
_CURRENT_DISPOSITION_SEMANTIC_SHA256 = (
    "722f0be46d39654619a178894cb6bed827a39a81b9330b6237899fcac4b7edef"
)
_CURRENT_AUTHORITY_SHA256 = "9977db4c03337d5783ebd5eab295c296c39e6bb8ada4100ff15dadb40a774d32"

_OLD_MAIN_FIXTURE_NAME = f"star-semantic-decisions-{_OLD_STRUCTURAL_SHA256}-main-v1.json"
_OLD_DIMENSION_FIXTURE_NAME = f"star-semantic-decisions-{_OLD_STRUCTURAL_SHA256}-dimensions-v1.json"
_OLD_MAIN_BYTES_SHA256 = "c0d3b11907774f10ca6401c0aaf431ed937cface4c129010f17acd00851d0e6a"
_OLD_DIMENSION_BYTES_SHA256 = "b1a2dd821593ee337bd06f61dcfb7e113d07fb77b7d7ec209c3e36109469dcc0"
_OLD_MAIN_BYTE_COUNT = 69_260
_OLD_DIMENSION_BYTE_COUNT = 7_927
_OLD_MAIN_AUTHORITY_INVENTORY_SHA256 = (
    "e0de5d48c0001b99c2424fb55658cd447e873945a1e9f03f4b8067dd1028e4a2"
)
_OLD_DIMENSION_AUTHORITY_INVENTORY_SHA256 = (
    "68899884826327993f40f0ef68f144984904ca397ad7d222d1a1fedab4ecc68a"
)
_OLD_MAIN_CORPUS_SHA256 = "b0f07afd6a60f424f7ca99631c17e281277b10e767f38546a54a7662d08966ac"
_OLD_DIMENSION_CORPUS_SHA256 = "4186703599ef5c786bfe859f072e896c45b09fb086b10b860a3932462b1a96b6"

_EXPECTED_ROWS: tuple[tuple[int, str, int], ...] = (
    (1, "Preseason", 1),
    (2, "Regular", 2),
    (3, "Play-In", 3),
    (4, "Playoffs R1", 4),
    (5, "Playoffs R2", 5),
    (6, "Conference Finals", 6),
    (7, "Finals", 7),
    (8, "All-Star", 8),
)
_BLOCKER_CODES = (
    "semantic_decision_not_authored",
    "table_specific_semantic_evidence_unreviewed",
)
_REVALIDATION_TRIGGERS = (
    "authority_inventory_changed",
    "decision_shard_extended",
    "stable_disposition_inventory_changed",
    "structural_inventory_changed",
)
_CORPUS_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "corpus_mode",
        "structural_inventory_sha256",
        "stable_inventory_sha256",
        "authority_inventory_sha256",
        "denominator_count",
        "decisions",
        "unreviewed_table_ids",
        "blocker_codes",
        "blockers",
        "revalidation_triggers",
        "corpus_sha256",
    }
)
_AUTHORITY_BOUND_DECISION_PATHS = frozenset(
    {
        "authority_sha256",
        "purpose_evidence_sha256",
        "key_groups[0].evidence_sha256",
        "functional_dependencies[0].evidence_sha256",
        "row_policy.evidence_sha256",
        "temporal_policy.evidence_sha256",
        "lineage_edges[0].expression_sha256",
        "lineage_edges[0].evidence_sha256",
        "lineage_edges[1].expression_sha256",
        "lineage_edges[1].evidence_sha256",
        "lineage_edges[2].expression_sha256",
        "lineage_edges[2].evidence_sha256",
        "positive_witness_sha256s[0]",
        "negative_witness_sha256s[0]",
        "mutation_witness_sha256s[0]",
        "decision_sha256",
    }
)


class StarSemanticCorpusRebindError(ValueError):
    """The historical replay or current authority rebind failed closed."""


@dataclass(frozen=True, slots=True)
class StarSemanticCorpusRebindV1:
    """Deterministic, non-admitted output of the table-specific rebind."""

    old_candidate: StableModelCandidateV1
    current_candidate: StableModelCandidateV1
    old_disposition: StableModelDispositionV1
    current_disposition: StableModelDispositionV1
    old_authority: StarTableSemanticAuthorityV1
    current_authority: StarTableSemanticAuthorityV1
    old_decision: StarTableSemanticDecisionV1
    rebound_decision: StarTableSemanticDecisionV1
    current_authorities: tuple[StarTableSemanticAuthorityV1, ...]
    current_dimension_authorities: tuple[StarTableSemanticAuthorityV1, ...]
    main_corpus_bytes: bytes
    dimension_corpus_bytes: bytes
    authority_bound_changed_paths: tuple[str, ...]
    authority_admitted: Literal[False] = False
    model_green: Literal[False] = False


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _old_fixture_path(name: str) -> Path:
    return _project_root() / "tests" / "unit" / "contracts" / "fixtures" / name


def _strict_canonical_payload(raw: bytes, *, label: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise StarSemanticCorpusRebindError(f"{label} must use canonical JSON plus one LF")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise StarSemanticCorpusRebindError(f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw[:-1].decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                StarSemanticCorpusRebindError(f"{label} contains non-finite JSON constant {value}")
            ),
        )
    except StarSemanticCorpusRebindError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarSemanticCorpusRebindError(f"{label} is invalid JSON") from exc
    if type(decoded) is not dict or any(type(key) is not str for key in decoded):
        raise StarSemanticCorpusRebindError(f"{label} must be an exact JSON object")
    payload = cast("dict[str, object]", decoded)
    if canonical_star_semantic_authoring_json_bytes(payload) + b"\n" != raw:
        raise StarSemanticCorpusRebindError(f"{label} is not canonical")
    if frozenset(payload) != _CORPUS_KEYS:
        raise StarSemanticCorpusRebindError(f"{label} fields differ from schema v1")
    content = {key: value for key, value in payload.items() if key != "corpus_sha256"}
    if payload["corpus_sha256"] != canonical_star_semantic_authoring_sha256(content):
        raise StarSemanticCorpusRebindError(f"{label} corpus digest is invalid")
    return payload


def _load_pinned_old_fixture(
    *,
    name: str,
    expected_byte_count: int,
    expected_bytes_sha256: str,
    expected_authority_inventory_sha256: str,
    expected_corpus_sha256: str,
) -> dict[str, object]:
    path = _old_fixture_path(name)
    if not path.is_file() or path.is_symlink():
        raise StarSemanticCorpusRebindError("old corpus fixture must be a regular file")
    raw = path.read_bytes()
    if len(raw) != expected_byte_count:
        raise StarSemanticCorpusRebindError("old corpus fixture byte count drifted")
    if hashlib.sha256(raw).hexdigest() != expected_bytes_sha256:
        raise StarSemanticCorpusRebindError("old corpus fixture bytes drifted")
    payload = _strict_canonical_payload(raw, label=name)
    expected_roots = {
        "structural_inventory_sha256": _OLD_STRUCTURAL_SHA256,
        "stable_inventory_sha256": _OLD_STABLE_SHA256,
        "authority_inventory_sha256": expected_authority_inventory_sha256,
        "corpus_sha256": expected_corpus_sha256,
    }
    for field, expected in expected_roots.items():
        if payload[field] != expected:
            raise StarSemanticCorpusRebindError(f"old corpus fixture {field} drifted")
    return payload


def _exact_array(payload: Mapping[str, object], field: str) -> list[object]:
    value = payload[field]
    if type(value) is not list:
        raise StarSemanticCorpusRebindError(f"old corpus {field} must be an exact array")
    return cast("list[object]", value)


def _validate_old_payload_denominator(
    payload: Mapping[str, object],
    *,
    expected_names: tuple[str, ...],
) -> dict[str, object]:
    if (
        payload["schema_version"] != 1
        or payload["kind"] != "nbadb_star_semantic_decision_corpus_shard_manifest"
        or payload["corpus_mode"] != "exact_denominator_shard_manifest"
        or payload["denominator_count"] != len(expected_names)
    ):
        raise StarSemanticCorpusRebindError("old corpus identity or denominator drifted")
    decisions = _exact_array(payload, "decisions")
    if len(decisions) != 1 or type(decisions[0]) is not dict:
        raise StarSemanticCorpusRebindError("old corpus must contain exactly one decision")
    decision_payload = cast("dict[str, object]", decisions[0])
    if decision_payload.get("table_name") != _TABLE_NAME:
        raise StarSemanticCorpusRebindError("old corpus decision identity drifted")
    unreviewed = tuple(_exact_array(payload, "unreviewed_table_ids"))
    expected_unreviewed = tuple(name for name in expected_names if name != _TABLE_NAME)
    if unreviewed != expected_unreviewed:
        raise StarSemanticCorpusRebindError("old corpus unreviewed denominator drifted")
    if tuple(_exact_array(payload, "blocker_codes")) != _BLOCKER_CODES:
        raise StarSemanticCorpusRebindError("old corpus blocker codes drifted")
    if tuple(_exact_array(payload, "revalidation_triggers")) != _REVALIDATION_TRIGGERS:
        raise StarSemanticCorpusRebindError("old corpus revalidation policy drifted")
    blockers = _exact_array(payload, "blockers")
    if len(blockers) != len(expected_unreviewed):
        raise StarSemanticCorpusRebindError("old corpus blocker count drifted")
    for blocker, table_name in zip(blockers, expected_unreviewed, strict=True):
        if type(blocker) is not dict:
            raise StarSemanticCorpusRebindError("old corpus blocker row is not an object")
        blocker_payload = cast("dict[str, object]", blocker)
        if blocker_payload != {
            "table_name": table_name,
            "authority_sha256": blocker_payload.get("authority_sha256"),
            "blocker_codes": list(_BLOCKER_CODES),
        }:
            raise StarSemanticCorpusRebindError("old corpus blocker row drifted")
        authority_sha256 = blocker_payload["authority_sha256"]
        if (
            type(authority_sha256) is not str
            or len(authority_sha256) != 64
            or any(char not in "0123456789abcdef" for char in authority_sha256)
        ):
            raise StarSemanticCorpusRebindError("old blocker authority digest is invalid")
    return decision_payload


def _source_sha256(value: type[object]) -> str:
    source = inspect.getsourcefile(value)
    if source is None:
        raise StarSemanticCorpusRebindError("season-phase source location is unavailable")
    path = Path(source)
    if not path.is_file() or path.is_symlink():
        raise StarSemanticCorpusRebindError("season-phase source must be a regular file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_sha256(*, authority_sha256: str, evidence_class: str, claim: object) -> str:
    return canonical_star_semantic_authoring_sha256(
        {
            "schema_version": 1,
            "kind": "nbadb_star_semantic_dimension_evidence",
            "table_name": _TABLE_NAME,
            "evidence_class": evidence_class,
            "claim": claim,
            "schema_source_sha256": _source_sha256(DimSeasonPhaseSchema),
            "transform_source_sha256": _source_sha256(DimSeasonPhaseTransformer),
            "authority_sha256": authority_sha256,
        }
    )


def _rows_payload() -> list[list[object]]:
    return [list(row) for row in _EXPECTED_ROWS]


def _build_season_phase_decision(
    authority: StarTableSemanticAuthorityV1,
) -> StarTableSemanticDecisionV1:
    if authority.output_name != _TABLE_NAME:
        raise StarSemanticCorpusRebindError("season-phase decision received a foreign authority")
    rows = _rows_payload()
    lineage_edges = tuple(
        ColumnLineageEdgeV1(
            edge_id=f"lineage:{column}",
            target_column=column,
            source_kind="literal",
            source_ids=(f"literal:{_TABLE_NAME}:{column}",),
            source_dependency_ids=(),
            transform_kind="expression",
            expression_sha256=_evidence_sha256(
                authority_sha256=authority.authority_sha256,
                evidence_class=f"expression:{column}",
                claim={"enumeration_rows": rows, "target_column": column},
            ),
            evidence_sha256=_evidence_sha256(
                authority_sha256=authority.authority_sha256,
                evidence_class=f"lineage:{column}",
                claim={"enumeration_rows": rows, "target_column": column},
            ),
        )
        for column in ("phase_id", "phase_name", "phase_order")
    )
    return StarTableSemanticDecisionV1(
        table_name=_TABLE_NAME,
        authority_sha256=authority.authority_sha256,
        purpose_code="season_phase_reference_lookup",
        purpose_evidence_sha256=_evidence_sha256(
            authority_sha256=authority.authority_sha256,
            evidence_class="purpose",
            claim={
                "consumer_role": "standalone_reference_dimension",
                "enumeration_rows": rows,
            },
        ),
        grain_dimensions=("phase_id",),
        observation_identity=("phase_id",),
        key_mode="keyed",
        key_groups=(
            KeyGroupV1(
                key_id="phase_id",
                key_kind="natural",
                columns=("phase_id",),
                null_policy="forbidden",
                evidence_sha256=_evidence_sha256(
                    authority_sha256=authority.authority_sha256,
                    evidence_class="key",
                    claim={
                        "column": "phase_id",
                        "expected_unique_values": list(range(1, 9)),
                    },
                ),
            ),
        ),
        functional_dependencies=(
            FunctionalDependencyV1(
                dependency_id="phase_lookup_values",
                determinants=("phase_id",),
                dependents=("phase_name", "phase_order"),
                evidence_sha256=_evidence_sha256(
                    authority_sha256=authority.authority_sha256,
                    evidence_class="functional_dependency",
                    claim={
                        "dependency_id": "phase_lookup_values",
                        "dependents": ["phase_name", "phase_order"],
                        "determinants": ["phase_id"],
                        "enumeration_rows": rows,
                    },
                ),
            ),
        ),
        relationships=(),
        lineage_edges=lineage_edges,
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
            evidence_sha256=_evidence_sha256(
                authority_sha256=authority.authority_sha256,
                evidence_class="row_policy",
                claim={"expected_row_count": 8, "enumeration_rows": rows},
            ),
        ),
        temporal_policy=TemporalPolicyV1(
            event_columns=(),
            observation_columns=(),
            load_columns=(),
            version_columns=(),
            feature_cutoff_columns=(),
            correction_policy="latest_truth",
            truth_mode="current_truth",
            evidence_sha256=_evidence_sha256(
                authority_sha256=authority.authority_sha256,
                evidence_class="temporal_policy",
                claim={"fixed_reference_enumeration": True, "temporal_columns": []},
            ),
        ),
        scd_policy="type1",
        algorithm_id="season-phase-enumeration",
        algorithm_version="v1",
        coverage_policy="complete_scope",
        incomplete_policy="reject",
        empty_policy="reject_empty",
        unavailable_policy="not_applicable",
        dependency_cardinalities=(),
        positive_witness_sha256s=(
            _evidence_sha256(
                authority_sha256=authority.authority_sha256,
                evidence_class="positive_validation",
                claim={"expected_rows": rows, "schema_validation": "pass"},
            ),
        ),
        negative_witness_sha256s=(
            _evidence_sha256(
                authority_sha256=authority.authority_sha256,
                evidence_class="negative_validation",
                claim={
                    "case": "duplicate_phase_id",
                    "mutated_row": [1, "Duplicate", 9],
                },
            ),
        ),
        mutation_witness_sha256s=(
            _evidence_sha256(
                authority_sha256=authority.authority_sha256,
                evidence_class="mutation_validation",
                claim={
                    "case": "phase_name_changed",
                    "mutated_row": [8, "Changed", 8],
                },
            ),
        ),
    )


def _diff_paths(old: object, new: object, *, path: str = "") -> set[str]:
    if type(old) is not type(new):
        return {path or "<root>"}
    if type(old) is dict:
        old_mapping = cast("dict[str, object]", old)
        new_mapping = cast("dict[str, object]", new)
        if old_mapping.keys() != new_mapping.keys():
            return {path or "<root>"}
        changed: set[str] = set()
        for key in old_mapping:
            child = f"{path}.{key}" if path else key
            changed.update(_diff_paths(old_mapping[key], new_mapping[key], path=child))
        return changed
    if type(old) is list:
        old_list = cast("list[object]", old)
        new_list = cast("list[object]", new)
        if len(old_list) != len(new_list):
            return {path or "<root>"}
        changed = set()
        for index, (old_item, new_item) in enumerate(zip(old_list, new_list, strict=True)):
            changed.update(_diff_paths(old_item, new_item, path=f"{path}[{index}]"))
        return changed
    return set() if old == new else {path or "<root>"}


def _replay_old_model_authority(
    *, current_candidate: StableModelCandidateV1, current_authority: StarTableSemanticAuthorityV1
) -> tuple[StableModelCandidateV1, StableModelDispositionV1, StarTableSemanticAuthorityV1]:
    if set(current_candidate.evidence_sha256s) != {
        _CURRENT_STRUCTURAL_SHA256,
        current_authority.structural_table_sha256,
        current_authority.schema_sha256,
        current_authority.transform_sha256,
    }:
        raise StarSemanticCorpusRebindError("current candidate evidence closure drifted")
    old_candidate = replace(
        current_candidate,
        evidence_sha256s=tuple(
            sorted(
                _OLD_STRUCTURAL_SHA256 if value == _CURRENT_STRUCTURAL_SHA256 else value
                for value in current_candidate.evidence_sha256s
            )
        ),
    )
    if old_candidate.candidate_sha256 != _OLD_CANDIDATE_SHA256:
        raise StarSemanticCorpusRebindError("old candidate typed replay drifted")
    old_disposition = draft_required_model_dispositions(
        candidate_source_authority_sha256=_OLD_CANDIDATE_SOURCE_SHA256,
        candidates=(old_candidate,),
    )[0]
    if old_disposition.semantic_sha256 != _OLD_DISPOSITION_SEMANTIC_SHA256:
        raise StarSemanticCorpusRebindError("old disposition typed replay drifted")
    old_authority = replace(
        current_authority,
        structural_inventory_sha256=_OLD_STRUCTURAL_SHA256,
        stable_inventory_sha256=_OLD_STABLE_SHA256,
        candidate_sha256=old_candidate.candidate_sha256,
        disposition_semantic_sha256=old_disposition.semantic_sha256,
    )
    if old_authority.authority_sha256 != _OLD_AUTHORITY_SHA256:
        raise StarSemanticCorpusRebindError("old semantic authority typed replay drifted")
    return old_candidate, old_disposition, old_authority


def _assert_model_invariants(
    *,
    old_candidate: StableModelCandidateV1,
    current_candidate: StableModelCandidateV1,
    old_disposition: StableModelDispositionV1,
    current_disposition: StableModelDispositionV1,
    old_authority: StarTableSemanticAuthorityV1,
    current_authority: StarTableSemanticAuthorityV1,
) -> None:
    candidate_fields = (
        "candidate_id",
        "candidate_kind",
        "gate_requirement",
        "structural_sha256",
        "dependency_ids",
        "implementation_status",
        "implementation_sha256",
    )
    if any(
        getattr(old_candidate, field) != getattr(current_candidate, field)
        for field in candidate_fields
    ):
        raise StarSemanticCorpusRebindError("candidate invariant fields drifted")
    if set(old_candidate.evidence_sha256s) ^ set(current_candidate.evidence_sha256s) != {
        _OLD_STRUCTURAL_SHA256,
        _CURRENT_STRUCTURAL_SHA256,
    }:
        raise StarSemanticCorpusRebindError("candidate evidence changed beyond generation root")
    disposition_fields = (
        "candidate_id",
        "candidate_structural_sha256",
        "disposition",
        "reason_code",
        "revalidation_owner",
        "revalidation_trigger",
    )
    if any(
        getattr(old_disposition, field) != getattr(current_disposition, field)
        for field in disposition_fields
    ):
        raise StarSemanticCorpusRebindError("disposition invariant fields drifted")
    if set(old_disposition.reason_evidence_sha256s) ^ set(
        current_disposition.reason_evidence_sha256s
    ) != {
        _OLD_STRUCTURAL_SHA256,
        _CURRENT_STRUCTURAL_SHA256,
        _OLD_CANDIDATE_SOURCE_SHA256,
        _CURRENT_CANDIDATE_SOURCE_SHA256,
    }:
        raise StarSemanticCorpusRebindError("disposition evidence changed beyond authority roots")
    authority_exclusions = {
        "structural_inventory_sha256",
        "stable_inventory_sha256",
        "candidate_sha256",
        "disposition_semantic_sha256",
        "authority_sha256",
    }
    old_authority_payload = old_authority.to_dict()
    current_authority_payload = current_authority.to_dict()
    if {
        key: value
        for key, value in old_authority_payload.items()
        if key not in authority_exclusions
    } != {
        key: value
        for key, value in current_authority_payload.items()
        if key not in authority_exclusions
    }:
        raise StarSemanticCorpusRebindError("semantic authority table-local fields drifted")


def _compile_current_authorities() -> tuple[
    tuple[StarTableSemanticAuthorityV1, ...],
    StableModelCandidateV1,
    StableModelDispositionV1,
    StarTableSemanticAuthorityV1,
]:
    analytical_needs = canonical_analytical_needs_authority_v1()
    census = compile_current_model_candidate_census(analytical_needs=analytical_needs)
    structural = compile_star_table_contracts()
    candidates = census.to_stable_candidates()
    dispositions = draft_required_model_dispositions(
        candidate_source_authority_sha256=census.candidate_source_authority_sha256,
        candidates=candidates,
    )
    stable = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=census.candidate_source_authority_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=(),
    )
    pins = {
        "structural": (structural.contract_sha256, _CURRENT_STRUCTURAL_SHA256),
        "census": (census.census_sha256, _CURRENT_CENSUS_SHA256),
        "candidate source": (
            census.candidate_source_authority_sha256,
            _CURRENT_CANDIDATE_SOURCE_SHA256,
        ),
        "stable": (stable.inventory_sha256, _CURRENT_STABLE_SHA256),
    }
    for label, (actual, expected) in pins.items():
        if actual != expected:
            raise StarSemanticCorpusRebindError(f"current {label} authority drifted")
    if census.star_model_contract_sha256 != structural.contract_sha256:
        raise StarSemanticCorpusRebindError("current census structural parent drifted")
    authorities = derive_star_semantic_authorities(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
    )
    candidates_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    dispositions_by_id = {disposition.candidate_id: disposition for disposition in dispositions}
    authorities_by_name = {authority.output_name: authority for authority in authorities}
    try:
        candidate = candidates_by_id[f"star:{_TABLE_NAME}"]
        disposition = dispositions_by_id[f"star:{_TABLE_NAME}"]
        authority = authorities_by_name[_TABLE_NAME]
    except KeyError as exc:
        raise StarSemanticCorpusRebindError("current season-phase authority is missing") from exc
    if candidate.candidate_sha256 != _CURRENT_CANDIDATE_SHA256:
        raise StarSemanticCorpusRebindError("current season-phase candidate drifted")
    if disposition.semantic_sha256 != _CURRENT_DISPOSITION_SEMANTIC_SHA256:
        raise StarSemanticCorpusRebindError("current season-phase disposition drifted")
    if authority.authority_sha256 != _CURRENT_AUTHORITY_SHA256:
        raise StarSemanticCorpusRebindError("current season-phase authority drifted")
    return authorities, candidate, disposition, authority


def _validate_old_fixtures(
    *, current_authorities: Sequence[StarTableSemanticAuthorityV1]
) -> dict[str, object]:
    names = tuple(authority.output_name for authority in current_authorities)
    dimension_names = tuple(name for name in names if name.startswith("dim_"))
    main = _load_pinned_old_fixture(
        name=_OLD_MAIN_FIXTURE_NAME,
        expected_byte_count=_OLD_MAIN_BYTE_COUNT,
        expected_bytes_sha256=_OLD_MAIN_BYTES_SHA256,
        expected_authority_inventory_sha256=_OLD_MAIN_AUTHORITY_INVENTORY_SHA256,
        expected_corpus_sha256=_OLD_MAIN_CORPUS_SHA256,
    )
    dimensions = _load_pinned_old_fixture(
        name=_OLD_DIMENSION_FIXTURE_NAME,
        expected_byte_count=_OLD_DIMENSION_BYTE_COUNT,
        expected_bytes_sha256=_OLD_DIMENSION_BYTES_SHA256,
        expected_authority_inventory_sha256=_OLD_DIMENSION_AUTHORITY_INVENTORY_SHA256,
        expected_corpus_sha256=_OLD_DIMENSION_CORPUS_SHA256,
    )
    main_decision = _validate_old_payload_denominator(main, expected_names=names)
    dimension_decision = _validate_old_payload_denominator(
        dimensions, expected_names=dimension_names
    )
    if main_decision != dimension_decision or (
        canonical_star_semantic_authoring_json_bytes(main_decision)
        != canonical_star_semantic_authoring_json_bytes(dimension_decision)
    ):
        raise StarSemanticCorpusRebindError("old corpus decision copies differ")
    return main_decision


def build_rebound_star_semantic_decision_corpora() -> StarSemanticCorpusRebindV1:
    """Build both current corpora after an exact historical equivalence proof."""

    (
        current_authorities,
        current_candidate,
        current_disposition,
        current_authority,
    ) = _compile_current_authorities()
    old_decision_payload = _validate_old_fixtures(current_authorities=current_authorities)
    old_candidate, old_disposition, old_authority = _replay_old_model_authority(
        current_candidate=current_candidate,
        current_authority=current_authority,
    )
    _assert_model_invariants(
        old_candidate=old_candidate,
        current_candidate=current_candidate,
        old_disposition=old_disposition,
        current_disposition=current_disposition,
        old_authority=old_authority,
        current_authority=current_authority,
    )
    expected_old_decision = _build_season_phase_decision(old_authority)
    old_decision = StarTableSemanticDecisionV1.from_dict(old_decision_payload)
    if (
        old_decision != expected_old_decision
        or old_decision.decision_sha256 != _OLD_DECISION_SHA256
    ):
        raise StarSemanticCorpusRebindError(
            "old decision literals or authority-bound evidence drifted"
        )
    rebound_decision = _build_season_phase_decision(current_authority)
    changed_paths = _diff_paths(old_decision.to_dict(), rebound_decision.to_dict())
    if changed_paths != _AUTHORITY_BOUND_DECISION_PATHS:
        raise StarSemanticCorpusRebindError(
            "decision changed outside the explicit authority-bound evidence allowlist"
        )
    current_dimension_authorities = tuple(
        authority for authority in current_authorities if authority.output_name.startswith("dim_")
    )
    if len(current_authorities) != 261 or len(current_dimension_authorities) != 18:
        raise StarSemanticCorpusRebindError("current authority denominator count drifted")
    main_bytes = compile_star_semantic_decision_corpus_bytes(
        authorities=current_authorities,
        decision_shards=(rebound_decision,),
    )
    dimension_bytes = compile_star_semantic_decision_corpus_bytes(
        authorities=current_dimension_authorities,
        decision_shards=(rebound_decision,),
    )
    if main_bytes != compile_star_semantic_decision_corpus_bytes(
        authorities=current_authorities,
        decision_shards=(rebound_decision,),
    ) or dimension_bytes != compile_star_semantic_decision_corpus_bytes(
        authorities=current_dimension_authorities,
        decision_shards=(rebound_decision,),
    ):
        raise StarSemanticCorpusRebindError("fresh corpus builds are nondeterministic")
    main = parse_star_semantic_decision_corpus(
        main_bytes,
        authorities=current_authorities,
    )
    dimensions = parse_star_semantic_decision_corpus(
        dimension_bytes,
        authorities=current_dimension_authorities,
    )
    if (
        len(main.decisions) != 1
        or len(main.blockers) != 260
        or len(dimensions.decisions) != 1
        or len(dimensions.blockers) != 17
        or main.decisions[0] != dimensions.decisions[0]
        or main.admitted
        or main.model_green
        or dimensions.admitted
        or dimensions.model_green
    ):
        raise StarSemanticCorpusRebindError("rebound corpus red-boundary counts drifted")
    return StarSemanticCorpusRebindV1(
        old_candidate=old_candidate,
        current_candidate=current_candidate,
        old_disposition=old_disposition,
        current_disposition=current_disposition,
        old_authority=old_authority,
        current_authority=current_authority,
        old_decision=old_decision,
        rebound_decision=rebound_decision,
        current_authorities=current_authorities,
        current_dimension_authorities=current_dimension_authorities,
        main_corpus_bytes=main_bytes,
        dimension_corpus_bytes=dimension_bytes,
        authority_bound_changed_paths=tuple(sorted(changed_paths)),
    )


def write_rebound_star_semantic_decision_corpora() -> tuple[Path, Path]:
    """Write the two fixed canonical resources after the full proof succeeds."""

    rebound = build_rebound_star_semantic_decision_corpora()
    main_path = star_semantic_decision_corpus_path()
    dimension_path = main_path.with_name("star-semantic-decisions-dimensions-v1.json")
    main_path.write_bytes(rebound.main_corpus_bytes)
    dimension_path.write_bytes(rebound.dimension_corpus_bytes)
    return main_path, dimension_path
