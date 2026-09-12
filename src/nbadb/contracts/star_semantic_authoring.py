"""Pure, non-admitted authoring candidates for reviewed star semantics.

The structural/star-disposition authority and the authored semantic decision
are both explicit inputs.  This module never reads registries, source files,
SQL, docstrings, consumer hints, the filesystem, the clock, or the environment.
It binds only exact fields already present in ``StarTableSemanticAuthorityV1``
and never infers a semantic decision from a table or column name.

Every generation remains deliberately non-admitted and non-green.  A separate
frozen-authority admission step and an independent human/process review are
required before any ``StarTableSemanticContractV1`` may be materialized.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast

from nbadb.contracts.review_evidence import ReviewEvidenceError, ReviewReceiptV1
from nbadb.contracts.star_semantic_contract import (
    ColumnLineageEdgeV1,
    DependencyCardinalityV1,
    FunctionalDependencyV1,
    KeyGroupV1,
    RelationshipV1,
    RowPolicyV1,
    StarSemanticContractError,
    StarTableSemanticContractV1,
    TemporalPolicyV1,
)
from nbadb.contracts.star_semantic_inventory import StarTableSemanticAuthorityV1

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "STAR_SEMANTIC_AUTHORING_SCHEMA_VERSION",
    "StarSemanticAuthoringBlockerV1",
    "StarSemanticAuthoringContractError",
    "StarSemanticAuthoringGenerationV1",
    "StarTableSemanticCandidateV1",
    "StarTableSemanticDecisionV1",
    "canonical_star_semantic_authoring_json_bytes",
    "canonical_star_semantic_authoring_sha256",
    "compile_star_semantic_authoring_generation_v1",
    "materialize_reviewed_star_semantic_candidate_v1",
]

STAR_SEMANTIC_AUTHORING_SCHEMA_VERSION = 1

_DECISION_KIND = "nbadb_star_table_semantic_decision"
_CANDIDATE_KIND = "nbadb_star_table_semantic_authoring_candidate"
_GENERATION_KIND = "nbadb_star_semantic_authoring_generation"
_AUTHORITY_INPUT_KIND = "nbadb_star_semantic_authority_input"
_DECISION_INPUT_KIND = "nbadb_star_semantic_decision_input"
_EVIDENCE_CLOSURE_KIND = "nbadb_star_semantic_review_input_closure"
_NON_ADMITTED_REVIEW_SHA256 = hashlib.sha256(
    b"nbadb-star-semantic-authoring-non-admitted-review-placeholder-v1"
).hexdigest()

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_MAX_AUTHORITIES = 10_000
_MAX_DECISIONS = 10_000
_MAX_COLUMNS = 100_000
_MAX_TOTAL_RELATIONSHIPS = 100_000
_MAX_GENERATION_BLOCKERS = 2 + _MAX_DECISIONS + (_MAX_AUTHORITIES * 5) + _MAX_TOTAL_RELATIONSHIPS
_MAX_CANONICAL_BYTES = 128 * 1024 * 1024

_KEY_MODES = frozenset({"keyed", "reviewed_bag"})
_SCD_POLICIES = frozenset({"not_applicable", "type1", "type2"})
_COVERAGE_POLICIES = frozenset({"complete_scope", "declared_partial", "snapshot"})
_INCOMPLETE_POLICIES = frozenset({"reject", "typed_incomplete"})
_EMPTY_POLICIES = frozenset({"materialize_typed_empty", "reject_empty"})
_UNAVAILABLE_POLICIES = frozenset({"typed_unavailable", "contract_blocked", "not_applicable"})
_SOURCE_MODES = frozenset({"dependency_backed", "reviewed_source_free"})
_BLOCKER_CODES = frozenset(
    {
        "authority_candidate_implementation_missing",
        "authority_candidate_missing",
        "authority_disposition_missing",
        "authority_inventory_empty",
        "authority_not_stable",
        "authority_ordered_columns_empty",
        "frozen_authority_completeness_unproven",
        "semantic_decision_authority_mismatch",
        "semantic_decision_invalid",
        "semantic_decision_missing",
        "semantic_decision_without_authority",
        "semantic_relationship_target_invalid",
    }
)

type KeyMode = Literal["keyed", "reviewed_bag"]
type ScdPolicy = Literal["not_applicable", "type1", "type2"]
type CoveragePolicy = Literal["complete_scope", "declared_partial", "snapshot"]
type IncompletePolicy = Literal["reject", "typed_incomplete"]
type EmptyPolicy = Literal["materialize_typed_empty", "reject_empty"]
type UnavailablePolicy = Literal["typed_unavailable", "contract_blocked", "not_applicable"]
type SourceMode = Literal["dependency_backed", "reviewed_source_free"]


class StarSemanticAuthoringContractError(ValueError):
    """Raised when explicit authoring input is ambiguous, lossy, or fabricated."""


def canonical_star_semantic_authoring_json_bytes(payload: object) -> bytes:
    """Return the sole canonical JSON representation for this candidate layer."""

    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise StarSemanticAuthoringContractError(
            "star semantic authoring value is not canonical JSON"
        ) from exc


def canonical_star_semantic_authoring_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_star_semantic_authoring_json_bytes(payload)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise StarSemanticAuthoringContractError(f"{field_name} must be an exact lowercase SHA-256")
    return value


def _require_safe_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise StarSemanticAuthoringContractError(
            f"{field_name} must be an exact bounded safe identifier"
        )
    return value


def _require_exact_tuple(value: object, *, field_name: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise StarSemanticAuthoringContractError(f"{field_name} must be an exact tuple")
    return cast("tuple[Any, ...]", value)


def _require_ordered_unique_ids(
    value: object,
    *,
    field_name: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    values = _require_exact_tuple(value, field_name=field_name)
    if (not allow_empty and not values) or len(values) > _MAX_COLUMNS:
        raise StarSemanticAuthoringContractError(f"{field_name} has an invalid bounded cardinality")
    if len(set(values)) != len(values):
        raise StarSemanticAuthoringContractError(f"{field_name} must be unique and ordered")
    return tuple(_require_safe_id(item, field_name=field_name) for item in values)


def _require_sorted_unique_sha256s(
    value: object,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    values = _require_exact_tuple(value, field_name=field_name)
    typed = tuple(_require_sha256(item, field_name=field_name) for item in values)
    if (not allow_empty and not typed) or typed != tuple(sorted(set(typed))):
        raise StarSemanticAuthoringContractError(
            f"{field_name} must be canonical sorted unique SHA-256 values"
        )
    return typed


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if type(payload) is not dict or frozenset(payload) != expected:
        raise StarSemanticAuthoringContractError(f"{label} has missing or unexpected fields")


def _mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise StarSemanticAuthoringContractError(
            f"{field_name} must be an exact string-keyed object"
        )
    return cast("Mapping[str, object]", value)


def _list(value: object, *, field_name: str, maximum: int = _MAX_COLUMNS) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise StarSemanticAuthoringContractError(f"{field_name} must be an exact bounded array")
    return cast("list[object]", value)


def _decode_canonical_mapping(raw: bytes, *, label: str) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise StarSemanticAuthoringContractError(f"{label} canonical byte length is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise StarSemanticAuthoringContractError(
                    f"{label} canonical JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                StarSemanticAuthoringContractError(
                    f"{label} contains non-finite JSON constant {value}"
                )
            ),
        )
    except StarSemanticAuthoringContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise StarSemanticAuthoringContractError(f"{label} is invalid JSON") from exc
    payload = _mapping(decoded, field_name=label)
    if canonical_star_semantic_authoring_json_bytes(payload) != raw:
        raise StarSemanticAuthoringContractError(f"{label} is not exact canonical JSON")
    return payload


def _array_to_ids(value: object, *, field_name: str, allow_empty: bool) -> tuple[str, ...]:
    values = _list(value, field_name=field_name)
    return _require_ordered_unique_ids(
        tuple(values), field_name=field_name, allow_empty=allow_empty
    )


def _array_to_sha256s(value: object, *, field_name: str) -> tuple[str, ...]:
    values = _list(value, field_name=field_name)
    return _require_sorted_unique_sha256s(tuple(values), field_name=field_name)


@dataclass(frozen=True, slots=True)
class StarTableSemanticDecisionV1:
    """One literal human-authored semantic decision, before authority binding."""

    table_name: str
    authority_sha256: str
    purpose_code: str
    purpose_evidence_sha256: str
    grain_dimensions: tuple[str, ...]
    observation_identity: tuple[str, ...]
    key_mode: KeyMode
    key_groups: tuple[KeyGroupV1, ...]
    functional_dependencies: tuple[FunctionalDependencyV1, ...]
    relationships: tuple[RelationshipV1, ...]
    lineage_edges: tuple[ColumnLineageEdgeV1, ...]
    competition_discriminators: tuple[str, ...]
    request_discriminators: tuple[str, ...]
    source_mode: SourceMode
    row_policy: RowPolicyV1
    temporal_policy: TemporalPolicyV1
    scd_policy: ScdPolicy
    algorithm_id: str | None
    algorithm_version: str | None
    coverage_policy: CoveragePolicy
    incomplete_policy: IncompletePolicy
    empty_policy: EmptyPolicy
    unavailable_policy: UnavailablePolicy
    dependency_cardinalities: tuple[DependencyCardinalityV1, ...]
    positive_witness_sha256s: tuple[str, ...]
    negative_witness_sha256s: tuple[str, ...]
    mutation_witness_sha256s: tuple[str, ...]

    schema_version: ClassVar[int] = STAR_SEMANTIC_AUTHORING_SCHEMA_VERSION
    kind: ClassVar[str] = _DECISION_KIND

    def __post_init__(self) -> None:
        _require_safe_id(self.table_name, field_name="decision table_name")
        _require_sha256(self.authority_sha256, field_name="decision authority_sha256")
        _require_safe_id(self.purpose_code, field_name="decision purpose_code")
        _require_sha256(
            self.purpose_evidence_sha256,
            field_name="decision purpose_evidence_sha256",
        )
        for field_name, values, allow_empty in (
            ("grain_dimensions", self.grain_dimensions, False),
            ("observation_identity", self.observation_identity, False),
            ("competition_discriminators", self.competition_discriminators, True),
            ("request_discriminators", self.request_discriminators, True),
        ):
            _require_ordered_unique_ids(
                values,
                field_name=f"decision {field_name}",
                allow_empty=allow_empty,
            )
        if self.key_mode not in _KEY_MODES:
            raise StarSemanticAuthoringContractError("decision key_mode is invalid")
        if self.source_mode not in _SOURCE_MODES:
            raise StarSemanticAuthoringContractError("decision source_mode is invalid")
        for field_name, values, row_type, identity in (
            ("key_groups", self.key_groups, KeyGroupV1, "key_id"),
            (
                "functional_dependencies",
                self.functional_dependencies,
                FunctionalDependencyV1,
                "dependency_id",
            ),
            ("relationships", self.relationships, RelationshipV1, "relationship_id"),
            ("lineage_edges", self.lineage_edges, ColumnLineageEdgeV1, "edge_id"),
            (
                "dependency_cardinalities",
                self.dependency_cardinalities,
                DependencyCardinalityV1,
                "dependency_id",
            ),
        ):
            rows = _require_exact_tuple(values, field_name=f"decision {field_name}")
            if field_name == "relationships" and len(rows) > _MAX_TOTAL_RELATIONSHIPS:
                raise StarSemanticAuthoringContractError(
                    "decision relationships exceed the bounded aggregate relationship budget"
                )
            if any(type(row) is not row_type for row in rows):
                raise StarSemanticAuthoringContractError(
                    f"decision {field_name} must be an exact typed tuple"
                )
            identities = tuple(getattr(row, identity) for row in rows)
            if rows != tuple(sorted(rows)) or len(identities) != len(set(identities)):
                raise StarSemanticAuthoringContractError(
                    f"decision {field_name} must be sorted with unique identities"
                )
        if type(self.row_policy) is not RowPolicyV1:
            raise StarSemanticAuthoringContractError("decision row_policy type is invalid")
        if type(self.temporal_policy) is not TemporalPolicyV1:
            raise StarSemanticAuthoringContractError("decision temporal_policy type is invalid")
        if self.scd_policy not in _SCD_POLICIES:
            raise StarSemanticAuthoringContractError("decision scd_policy is invalid")
        if (self.algorithm_id is None) != (self.algorithm_version is None):
            raise StarSemanticAuthoringContractError(
                "decision algorithm identity and version must co-occur"
            )
        if self.algorithm_id is not None:
            _require_safe_id(self.algorithm_id, field_name="decision algorithm_id")
            _require_safe_id(self.algorithm_version, field_name="decision algorithm_version")
        if self.coverage_policy not in _COVERAGE_POLICIES:
            raise StarSemanticAuthoringContractError("decision coverage_policy is invalid")
        if self.incomplete_policy not in _INCOMPLETE_POLICIES:
            raise StarSemanticAuthoringContractError("decision incomplete_policy is invalid")
        if self.empty_policy not in _EMPTY_POLICIES:
            raise StarSemanticAuthoringContractError("decision empty_policy is invalid")
        if self.unavailable_policy not in _UNAVAILABLE_POLICIES:
            raise StarSemanticAuthoringContractError("decision unavailable_policy is invalid")
        for field_name, values in (
            ("positive_witness_sha256s", self.positive_witness_sha256s),
            ("negative_witness_sha256s", self.negative_witness_sha256s),
            ("mutation_witness_sha256s", self.mutation_witness_sha256s),
        ):
            _require_sorted_unique_sha256s(
                values,
                field_name=f"decision {field_name}",
            )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "table_name": self.table_name,
            "authority_sha256": self.authority_sha256,
            "purpose_code": self.purpose_code,
            "purpose_evidence_sha256": self.purpose_evidence_sha256,
            "grain_dimensions": list(self.grain_dimensions),
            "observation_identity": list(self.observation_identity),
            "key_mode": self.key_mode,
            "key_groups": [item.to_dict() for item in self.key_groups],
            "functional_dependencies": [item.to_dict() for item in self.functional_dependencies],
            "relationships": [item.to_dict() for item in self.relationships],
            "lineage_edges": [item.to_dict() for item in self.lineage_edges],
            "competition_discriminators": list(self.competition_discriminators),
            "request_discriminators": list(self.request_discriminators),
            "source_mode": self.source_mode,
            "row_policy": self.row_policy.to_dict(),
            "temporal_policy": self.temporal_policy.to_dict(),
            "scd_policy": self.scd_policy,
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "coverage_policy": self.coverage_policy,
            "incomplete_policy": self.incomplete_policy,
            "empty_policy": self.empty_policy,
            "unavailable_policy": self.unavailable_policy,
            "dependency_cardinalities": [item.to_dict() for item in self.dependency_cardinalities],
            "positive_witness_sha256s": list(self.positive_witness_sha256s),
            "negative_witness_sha256s": list(self.negative_witness_sha256s),
            "mutation_witness_sha256s": list(self.mutation_witness_sha256s),
        }

    @property
    def decision_sha256(self) -> str:
        return canonical_star_semantic_authoring_sha256(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_star_semantic_authoring_json_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "decision_sha256": self.decision_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _mapping(value, field_name="star semantic decision")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "table_name",
                    "authority_sha256",
                    "purpose_code",
                    "purpose_evidence_sha256",
                    "grain_dimensions",
                    "observation_identity",
                    "key_mode",
                    "key_groups",
                    "functional_dependencies",
                    "relationships",
                    "lineage_edges",
                    "competition_discriminators",
                    "request_discriminators",
                    "source_mode",
                    "row_policy",
                    "temporal_policy",
                    "scd_policy",
                    "algorithm_id",
                    "algorithm_version",
                    "coverage_policy",
                    "incomplete_policy",
                    "empty_policy",
                    "unavailable_policy",
                    "dependency_cardinalities",
                    "positive_witness_sha256s",
                    "negative_witness_sha256s",
                    "mutation_witness_sha256s",
                    "decision_sha256",
                }
            ),
            label="star semantic decision",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or type(payload["kind"]) is not str
            or payload["kind"] != cls.kind
        ):
            raise StarSemanticAuthoringContractError("decision schema identity is invalid")
        algorithm_id = payload["algorithm_id"]
        algorithm_version = payload["algorithm_version"]
        if algorithm_id is not None and type(algorithm_id) is not str:
            raise StarSemanticAuthoringContractError("decision algorithm_id type is invalid")
        if algorithm_version is not None and type(algorithm_version) is not str:
            raise StarSemanticAuthoringContractError("decision algorithm_version type is invalid")
        decision = cls(
            table_name=cast("str", payload["table_name"]),
            authority_sha256=cast("str", payload["authority_sha256"]),
            purpose_code=cast("str", payload["purpose_code"]),
            purpose_evidence_sha256=cast("str", payload["purpose_evidence_sha256"]),
            grain_dimensions=_array_to_ids(
                payload["grain_dimensions"],
                field_name="decision grain_dimensions",
                allow_empty=False,
            ),
            observation_identity=_array_to_ids(
                payload["observation_identity"],
                field_name="decision observation_identity",
                allow_empty=False,
            ),
            key_mode=cast("KeyMode", payload["key_mode"]),
            key_groups=tuple(
                KeyGroupV1.from_dict(item)
                for item in _list(payload["key_groups"], field_name="decision key_groups")
            ),
            functional_dependencies=tuple(
                FunctionalDependencyV1.from_dict(item)
                for item in _list(
                    payload["functional_dependencies"],
                    field_name="decision functional_dependencies",
                )
            ),
            relationships=tuple(
                RelationshipV1.from_dict(item)
                for item in _list(payload["relationships"], field_name="decision relationships")
            ),
            lineage_edges=tuple(
                ColumnLineageEdgeV1.from_dict(item)
                for item in _list(payload["lineage_edges"], field_name="decision lineage_edges")
            ),
            competition_discriminators=_array_to_ids(
                payload["competition_discriminators"],
                field_name="decision competition_discriminators",
                allow_empty=True,
            ),
            request_discriminators=_array_to_ids(
                payload["request_discriminators"],
                field_name="decision request_discriminators",
                allow_empty=True,
            ),
            source_mode=cast("SourceMode", payload["source_mode"]),
            row_policy=RowPolicyV1.from_dict(payload["row_policy"]),
            temporal_policy=TemporalPolicyV1.from_dict(payload["temporal_policy"]),
            scd_policy=cast("ScdPolicy", payload["scd_policy"]),
            algorithm_id=algorithm_id,
            algorithm_version=algorithm_version,
            coverage_policy=cast("CoveragePolicy", payload["coverage_policy"]),
            incomplete_policy=cast("IncompletePolicy", payload["incomplete_policy"]),
            empty_policy=cast("EmptyPolicy", payload["empty_policy"]),
            unavailable_policy=cast("UnavailablePolicy", payload["unavailable_policy"]),
            dependency_cardinalities=tuple(
                DependencyCardinalityV1.from_dict(item)
                for item in _list(
                    payload["dependency_cardinalities"],
                    field_name="decision dependency_cardinalities",
                )
            ),
            positive_witness_sha256s=_array_to_sha256s(
                payload["positive_witness_sha256s"],
                field_name="decision positive_witness_sha256s",
            ),
            negative_witness_sha256s=_array_to_sha256s(
                payload["negative_witness_sha256s"],
                field_name="decision negative_witness_sha256s",
            ),
            mutation_witness_sha256s=_array_to_sha256s(
                payload["mutation_witness_sha256s"],
                field_name="decision mutation_witness_sha256s",
            ),
        )
        if type(payload["decision_sha256"]) is not str or (
            payload["decision_sha256"] != decision.decision_sha256
        ):
            raise StarSemanticAuthoringContractError("decision digest is invalid")
        return decision

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_mapping(raw, label="star semantic decision"))


def _semantic_contract_for(
    authority: StarTableSemanticAuthorityV1,
    decision: StarTableSemanticDecisionV1,
) -> StarTableSemanticContractV1:
    if authority.disposition_status == "stable":
        public_disposition: Literal["published", "unpublished"] = "published"
    elif authority.disposition_status in {"withheld", "rejected"}:
        public_disposition = "unpublished"
    else:
        raise StarSemanticAuthoringContractError(
            "only an exact stable, withheld, or rejected disposition can bind public status"
        )
    return StarTableSemanticContractV1(
        table_name=authority.output_name,
        table_family=authority.table_family,
        structural_table_sha256=authority.structural_table_sha256,
        schema_sha256=authority.schema_sha256,
        transform_sha256=authority.transform_sha256,
        stable_disposition_sha256=cast("str", authority.disposition_semantic_sha256),
        stability=cast("Any", authority.disposition_status),
        public_disposition=public_disposition,
        purpose_code=decision.purpose_code,
        purpose_evidence_sha256=decision.purpose_evidence_sha256,
        ordered_columns=authority.ordered_columns,
        grain_dimensions=decision.grain_dimensions,
        observation_identity=decision.observation_identity,
        key_mode=decision.key_mode,
        key_groups=decision.key_groups,
        functional_dependencies=decision.functional_dependencies,
        relationships=decision.relationships,
        lineage_edges=decision.lineage_edges,
        competition_discriminators=decision.competition_discriminators,
        request_discriminators=decision.request_discriminators,
        source_mode=decision.source_mode,
        source_precedence=authority.transformer_dependencies,
        row_policy=decision.row_policy,
        temporal_policy=decision.temporal_policy,
        scd_policy=decision.scd_policy,
        algorithm_id=decision.algorithm_id,
        algorithm_version=decision.algorithm_version,
        coverage_policy=decision.coverage_policy,
        incomplete_policy=decision.incomplete_policy,
        empty_policy=decision.empty_policy,
        unavailable_policy=decision.unavailable_policy,
        dependency_cardinalities=decision.dependency_cardinalities,
        positive_witness_sha256s=decision.positive_witness_sha256s,
        negative_witness_sha256s=decision.negative_witness_sha256s,
        mutation_witness_sha256s=decision.mutation_witness_sha256s,
        review_receipt_sha256=_NON_ADMITTED_REVIEW_SHA256,
    )


def materialize_reviewed_star_semantic_candidate_v1(
    *,
    candidate: StarTableSemanticCandidateV1,
    review_receipt: ReviewReceiptV1,
) -> StarTableSemanticContractV1:
    """Materialize one candidate only after exact independent review closure.

    This is deliberately a table-local bridge.  It does not prove that the
    caller supplied the complete frozen table universe and it does not make a
    generation green.  The final inventory join remains responsible for those
    global properties.
    """

    if type(candidate) is not StarTableSemanticCandidateV1:
        raise StarSemanticAuthoringContractError(
            "reviewed materialization requires an exact semantic candidate"
        )
    if type(review_receipt) is not ReviewReceiptV1:
        raise StarSemanticAuthoringContractError(
            "reviewed materialization requires an exact review receipt"
        )

    try:
        checked_candidate = StarTableSemanticCandidateV1.from_dict(candidate.to_dict())
        checked_review = ReviewReceiptV1.from_dict(review_receipt.to_dict())
    except (StarSemanticAuthoringContractError, ReviewEvidenceError) as exc:
        raise StarSemanticAuthoringContractError(
            "reviewed materialization input failed exact typed reconstruction"
        ) from exc
    if checked_candidate != candidate or checked_review != review_receipt:
        raise StarSemanticAuthoringContractError(
            "reviewed materialization input differs after exact reconstruction"
        )
    candidate = checked_candidate
    review_receipt = checked_review

    provisional = _semantic_contract_for(candidate.authority, candidate.decision)
    if provisional.semantic_sha256 != candidate.semantic_sha256:
        raise StarSemanticAuthoringContractError(
            "reviewed materialization candidate semantics drifted"
        )
    if (
        review_receipt.subject_kind != "star_table_semantic_contract"
        or review_receipt.subject_semantic_sha256 != candidate.semantic_sha256
        or review_receipt.disposition != "accepted"
    ):
        raise StarSemanticAuthoringContractError(
            "review receipt does not accept the exact candidate semantics"
        )
    required_inputs = {
        candidate.candidate_sha256,
        candidate.evidence_closure_sha256,
        *candidate.required_review_input_sha256s,
    }
    if not required_inputs.issubset(review_receipt.accepted_input_sha256s):
        raise StarSemanticAuthoringContractError(
            "review receipt omits the exact candidate evidence closure"
        )

    reviewed = replace(
        provisional,
        review_receipt_sha256=review_receipt.receipt_sha256,
    )
    reviewed.validate_review_receipt(review_receipt)
    return reviewed


def _evidence_inputs(
    *,
    authority_inventory_sha256: str,
    authority: StarTableSemanticAuthorityV1,
    decision: StarTableSemanticDecisionV1,
    relationship_target_authority_sha256s: tuple[str, ...],
    semantic_sha256: str,
) -> tuple[str, ...]:
    inputs = {
        authority_inventory_sha256,
        authority.authority_sha256,
        authority.structural_inventory_sha256,
        authority.stable_inventory_sha256,
        authority.structural_table_sha256,
        authority.schema_sha256,
        authority.transform_sha256,
        decision.decision_sha256,
        decision.purpose_evidence_sha256,
        semantic_sha256,
        *relationship_target_authority_sha256s,
        *decision.positive_witness_sha256s,
        *decision.negative_witness_sha256s,
        *decision.mutation_witness_sha256s,
    }
    for optional_digest in (
        authority.candidate_sha256,
        authority.candidate_structural_sha256,
        authority.candidate_implementation_sha256,
        authority.disposition_semantic_sha256,
    ):
        if optional_digest is not None:
            inputs.add(optional_digest)
    inputs.update(item.evidence_sha256 for item in decision.key_groups)
    inputs.update(item.evidence_sha256 for item in decision.functional_dependencies)
    inputs.update(item.evidence_sha256 for item in decision.relationships)
    inputs.update(item.evidence_sha256 for item in decision.lineage_edges)
    inputs.update(
        item.expression_sha256
        for item in decision.lineage_edges
        if item.expression_sha256 is not None
    )
    inputs.add(decision.row_policy.evidence_sha256)
    inputs.add(decision.temporal_policy.evidence_sha256)
    inputs.update(item.evidence_sha256 for item in decision.dependency_cardinalities)
    return tuple(sorted(inputs))


@dataclass(frozen=True, slots=True)
class StarTableSemanticCandidateV1:
    """Exact authority-bound semantic payload awaiting independent review.

    Target digests are a hash-only closure here, so this primary non-admitted
    DTO can prove their canonical cardinality but cannot bind each digest to a
    relationship table identity.  The joined independent verifier supplies
    that authority binding before any later admission step.
    """

    authority_inventory_sha256: str
    authority: StarTableSemanticAuthorityV1
    decision: StarTableSemanticDecisionV1
    relationship_target_authority_sha256s: tuple[str, ...]
    semantic_sha256: str
    required_review_input_sha256s: tuple[str, ...]
    evidence_closure_sha256: str
    admitted: Literal[False] = False
    model_green: Literal[False] = False

    schema_version: ClassVar[int] = STAR_SEMANTIC_AUTHORING_SCHEMA_VERSION
    kind: ClassVar[str] = _CANDIDATE_KIND

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_inventory_sha256,
            field_name="candidate authority_inventory_sha256",
        )
        if type(self.authority) is not StarTableSemanticAuthorityV1:
            raise StarSemanticAuthoringContractError("candidate authority type is invalid")
        if type(self.decision) is not StarTableSemanticDecisionV1:
            raise StarSemanticAuthoringContractError("candidate decision type is invalid")
        if (
            self.decision.table_name != self.authority.output_name
            or self.decision.authority_sha256 != self.authority.authority_sha256
        ):
            raise StarSemanticAuthoringContractError(
                "candidate decision is rebound to a foreign authority"
            )
        if (
            not self.authority.ordered_columns
            or self.authority.candidate_sha256 is None
            or self.authority.candidate_implementation_status != "implemented"
            or self.authority.candidate_implementation_sha256 is None
            or self.authority.disposition_semantic_sha256 is None
            or self.authority.disposition_status != "stable"
        ):
            raise StarSemanticAuthoringContractError(
                "candidate authority retains an unresolved structural or disposition blocker"
            )
        target_hashes = _require_sorted_unique_sha256s(
            self.relationship_target_authority_sha256s,
            field_name="candidate relationship_target_authority_sha256s",
            allow_empty=True,
        )
        expected_target_count = len(
            {relationship.target_table for relationship in self.decision.relationships}
        )
        if len(target_hashes) != expected_target_count:
            raise StarSemanticAuthoringContractError(
                "candidate relationship authority inventory has invalid cardinality"
            )
        semantic_contract = _semantic_contract_for(self.authority, self.decision)
        if self.semantic_sha256 != semantic_contract.semantic_sha256:
            raise StarSemanticAuthoringContractError("candidate semantic digest is invalid")
        expected_inputs = _evidence_inputs(
            authority_inventory_sha256=self.authority_inventory_sha256,
            authority=self.authority,
            decision=self.decision,
            relationship_target_authority_sha256s=target_hashes,
            semantic_sha256=self.semantic_sha256,
        )
        if self.required_review_input_sha256s != expected_inputs:
            raise StarSemanticAuthoringContractError(
                "candidate review input closure is incomplete or fabricated"
            )
        expected_closure = canonical_star_semantic_authoring_sha256(
            {
                "schema_version": self.schema_version,
                "kind": _EVIDENCE_CLOSURE_KIND,
                "required_review_input_sha256s": list(expected_inputs),
            }
        )
        if self.evidence_closure_sha256 != expected_closure:
            raise StarSemanticAuthoringContractError("candidate evidence closure digest is invalid")
        if type(self.admitted) is not bool or self.admitted:
            raise StarSemanticAuthoringContractError("candidate admitted must be exact false")
        if type(self.model_green) is not bool or self.model_green:
            raise StarSemanticAuthoringContractError("candidate model_green must be exact false")

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_inventory_sha256": self.authority_inventory_sha256,
            "authority": self.authority.to_dict(),
            "decision": self.decision.to_dict(),
            "relationship_target_authority_sha256s": list(
                self.relationship_target_authority_sha256s
            ),
            "semantic_sha256": self.semantic_sha256,
            "required_review_input_sha256s": list(self.required_review_input_sha256s),
            "evidence_closure_sha256": self.evidence_closure_sha256,
            "admitted": self.admitted,
            "model_green": self.model_green,
        }

    @property
    def candidate_sha256(self) -> str:
        return canonical_star_semantic_authoring_sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "candidate_sha256": self.candidate_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _mapping(value, field_name="star semantic candidate")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "authority_inventory_sha256",
                    "authority",
                    "decision",
                    "relationship_target_authority_sha256s",
                    "semantic_sha256",
                    "required_review_input_sha256s",
                    "evidence_closure_sha256",
                    "admitted",
                    "model_green",
                    "candidate_sha256",
                }
            ),
            label="star semantic candidate",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or type(payload["kind"]) is not str
            or payload["kind"] != cls.kind
        ):
            raise StarSemanticAuthoringContractError("candidate schema identity is invalid")
        if type(payload["admitted"]) is not bool or type(payload["model_green"]) is not bool:
            raise StarSemanticAuthoringContractError("candidate booleans have invalid types")
        candidate = cls(
            authority_inventory_sha256=cast("str", payload["authority_inventory_sha256"]),
            authority=StarTableSemanticAuthorityV1.from_dict(payload["authority"]),
            decision=StarTableSemanticDecisionV1.from_dict(payload["decision"]),
            relationship_target_authority_sha256s=_array_to_sha256s_allow_empty(
                payload["relationship_target_authority_sha256s"],
                field_name="candidate relationship_target_authority_sha256s",
            ),
            semantic_sha256=cast("str", payload["semantic_sha256"]),
            required_review_input_sha256s=_array_to_sha256s(
                payload["required_review_input_sha256s"],
                field_name="candidate required_review_input_sha256s",
            ),
            evidence_closure_sha256=cast("str", payload["evidence_closure_sha256"]),
            admitted=cast("Literal[False]", payload["admitted"]),
            model_green=cast("Literal[False]", payload["model_green"]),
        )
        if type(payload["candidate_sha256"]) is not str or (
            payload["candidate_sha256"] != candidate.candidate_sha256
        ):
            raise StarSemanticAuthoringContractError("candidate digest is invalid")
        return candidate


def _array_to_sha256s_allow_empty(value: object, *, field_name: str) -> tuple[str, ...]:
    values = _list(value, field_name=field_name)
    return _require_sorted_unique_sha256s(tuple(values), field_name=field_name, allow_empty=True)


@dataclass(frozen=True, slots=True, order=True)
class StarSemanticAuthoringBlockerV1:
    """One canonical reason this source-relative generation cannot be admitted."""

    scope_id: str
    code: str
    evidence_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_safe_id(self.scope_id, field_name="blocker scope_id")
        if self.code not in _BLOCKER_CODES:
            raise StarSemanticAuthoringContractError("blocker code is invalid")
        _require_sorted_unique_sha256s(
            self.evidence_sha256s,
            field_name="blocker evidence_sha256s",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "scope_id": self.scope_id,
            "code": self.code,
            "evidence_sha256s": list(self.evidence_sha256s),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _mapping(value, field_name="star semantic authoring blocker")
        _require_exact_keys(
            payload,
            expected=frozenset({"scope_id", "code", "evidence_sha256s"}),
            label="star semantic authoring blocker",
        )
        return cls(
            scope_id=cast("str", payload["scope_id"]),
            code=cast("str", payload["code"]),
            evidence_sha256s=_array_to_sha256s(
                payload["evidence_sha256s"],
                field_name="blocker evidence_sha256s",
            ),
        )


@dataclass(frozen=True, slots=True)
class StarSemanticAuthoringGenerationV1:
    """Source-relative candidate generation that is structurally never admitted."""

    structural_inventory_sha256: str | None
    stable_inventory_sha256: str | None
    authority_inventory_sha256: str
    decision_inventory_sha256: str
    candidates: tuple[StarTableSemanticCandidateV1, ...]
    blockers: tuple[StarSemanticAuthoringBlockerV1, ...]
    complete: Literal[False] = False
    admitted: Literal[False] = False
    model_green: Literal[False] = False

    schema_version: ClassVar[int] = STAR_SEMANTIC_AUTHORING_SCHEMA_VERSION
    kind: ClassVar[str] = _GENERATION_KIND

    def __post_init__(self) -> None:
        if (self.structural_inventory_sha256 is None) != (self.stable_inventory_sha256 is None):
            raise StarSemanticAuthoringContractError(
                "generation parent inventory identities must co-occur"
            )
        if self.structural_inventory_sha256 is not None:
            _require_sha256(
                self.structural_inventory_sha256,
                field_name="generation structural_inventory_sha256",
            )
            _require_sha256(
                self.stable_inventory_sha256,
                field_name="generation stable_inventory_sha256",
            )
        _require_sha256(
            self.authority_inventory_sha256,
            field_name="generation authority_inventory_sha256",
        )
        _require_sha256(
            self.decision_inventory_sha256,
            field_name="generation decision_inventory_sha256",
        )
        candidates = _require_exact_tuple(self.candidates, field_name="generation candidates")
        if len(candidates) > _MAX_AUTHORITIES:
            raise StarSemanticAuthoringContractError(
                "generation candidates exceed the bounded authority inventory"
            )
        if any(type(item) is not StarTableSemanticCandidateV1 for item in candidates):
            raise StarSemanticAuthoringContractError(
                "generation candidates must be an exact typed tuple"
            )
        if candidates != tuple(sorted(candidates, key=lambda item: item.authority.output_name)):
            raise StarSemanticAuthoringContractError(
                "generation candidates must be sorted by table identity"
            )
        if len({item.authority.output_name for item in candidates}) != len(candidates):
            raise StarSemanticAuthoringContractError("generation candidate identities repeat")
        if any(
            item.authority_inventory_sha256 != self.authority_inventory_sha256
            for item in candidates
        ):
            raise StarSemanticAuthoringContractError(
                "generation candidate authority inventory is rebound"
            )
        blockers = _require_exact_tuple(self.blockers, field_name="generation blockers")
        if len(blockers) > _MAX_GENERATION_BLOCKERS:
            raise StarSemanticAuthoringContractError(
                "generation blockers exceed the bounded derivation maximum"
            )
        if any(type(item) is not StarSemanticAuthoringBlockerV1 for item in blockers):
            raise StarSemanticAuthoringContractError(
                "generation blockers must be an exact typed tuple"
            )
        expected_blockers = tuple(
            sorted(blockers, key=lambda item: (item.scope_id, item.code, item.evidence_sha256s))
        )
        if blockers != expected_blockers or len(set(blockers)) != len(blockers):
            raise StarSemanticAuthoringContractError(
                "generation blockers must be canonical sorted unique rows"
            )
        if not any(
            blocker.code == "frozen_authority_completeness_unproven" for blocker in blockers
        ):
            raise StarSemanticAuthoringContractError(
                "generation must retain the external frozen-authority admission blocker"
            )
        for field_name, value in (
            ("complete", self.complete),
            ("admitted", self.admitted),
            ("model_green", self.model_green),
        ):
            if type(value) is not bool or value:
                raise StarSemanticAuthoringContractError(
                    f"generation {field_name} must be exact false"
                )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "structural_inventory_sha256": self.structural_inventory_sha256,
            "stable_inventory_sha256": self.stable_inventory_sha256,
            "authority_inventory_sha256": self.authority_inventory_sha256,
            "decision_inventory_sha256": self.decision_inventory_sha256,
            "candidates": [item.to_dict() for item in self.candidates],
            "blockers": [item.to_dict() for item in self.blockers],
            "complete": self.complete,
            "admitted": self.admitted,
            "model_green": self.model_green,
        }

    @property
    def generation_sha256(self) -> str:
        return canonical_star_semantic_authoring_sha256(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_star_semantic_authoring_json_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "generation_sha256": self.generation_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _mapping(value, field_name="star semantic authoring generation")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "structural_inventory_sha256",
                    "stable_inventory_sha256",
                    "authority_inventory_sha256",
                    "decision_inventory_sha256",
                    "candidates",
                    "blockers",
                    "complete",
                    "admitted",
                    "model_green",
                    "generation_sha256",
                }
            ),
            label="star semantic authoring generation",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or type(payload["kind"]) is not str
            or payload["kind"] != cls.kind
        ):
            raise StarSemanticAuthoringContractError("generation schema identity is invalid")
        for field_name in ("complete", "admitted", "model_green"):
            if type(payload[field_name]) is not bool:
                raise StarSemanticAuthoringContractError(
                    f"generation {field_name} has an invalid type"
                )
        structural_inventory_sha256 = payload["structural_inventory_sha256"]
        stable_inventory_sha256 = payload["stable_inventory_sha256"]
        if structural_inventory_sha256 is not None and type(structural_inventory_sha256) is not str:
            raise StarSemanticAuthoringContractError(
                "generation structural inventory type is invalid"
            )
        if stable_inventory_sha256 is not None and type(stable_inventory_sha256) is not str:
            raise StarSemanticAuthoringContractError("generation stable inventory type is invalid")
        generation = cls(
            structural_inventory_sha256=structural_inventory_sha256,
            stable_inventory_sha256=stable_inventory_sha256,
            authority_inventory_sha256=cast("str", payload["authority_inventory_sha256"]),
            decision_inventory_sha256=cast("str", payload["decision_inventory_sha256"]),
            candidates=tuple(
                StarTableSemanticCandidateV1.from_dict(item)
                for item in _list(
                    payload["candidates"],
                    field_name="generation candidates",
                    maximum=_MAX_AUTHORITIES,
                )
            ),
            blockers=tuple(
                StarSemanticAuthoringBlockerV1.from_dict(item)
                for item in _list(
                    payload["blockers"],
                    field_name="generation blockers",
                    maximum=_MAX_GENERATION_BLOCKERS,
                )
            ),
            complete=cast("Literal[False]", payload["complete"]),
            admitted=cast("Literal[False]", payload["admitted"]),
            model_green=cast("Literal[False]", payload["model_green"]),
        )
        if type(payload["generation_sha256"]) is not str or (
            payload["generation_sha256"] != generation.generation_sha256
        ):
            raise StarSemanticAuthoringContractError("generation digest is invalid")
        return generation

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(
            _decode_canonical_mapping(raw, label="star semantic authoring generation")
        )


def _authority_inventory_sha256(
    authorities: Sequence[StarTableSemanticAuthorityV1],
) -> str:
    return canonical_star_semantic_authoring_sha256(
        {
            "schema_version": STAR_SEMANTIC_AUTHORING_SCHEMA_VERSION,
            "kind": _AUTHORITY_INPUT_KIND,
            "authorities": [authority.to_dict() for authority in authorities],
        }
    )


def _decision_inventory_sha256(decisions: Sequence[StarTableSemanticDecisionV1]) -> str:
    return canonical_star_semantic_authoring_sha256(
        {
            "schema_version": STAR_SEMANTIC_AUTHORING_SCHEMA_VERSION,
            "kind": _DECISION_INPUT_KIND,
            "decisions": [decision.to_dict() for decision in decisions],
        }
    )


def _blocker(
    *,
    scope_id: str,
    code: str,
    evidence_sha256s: Sequence[str],
) -> StarSemanticAuthoringBlockerV1:
    return StarSemanticAuthoringBlockerV1(
        scope_id=scope_id,
        code=code,
        evidence_sha256s=tuple(sorted(set(evidence_sha256s))),
    )


def compile_star_semantic_authoring_generation_v1(
    *,
    authorities: tuple[StarTableSemanticAuthorityV1, ...],
    decisions: tuple[StarTableSemanticDecisionV1, ...],
) -> StarSemanticAuthoringGenerationV1:
    """Compile only reviewable candidates from exact caller-supplied inputs.

    The unconditional frozen-authority blocker records that this source-relative
    compiler cannot prove that the caller supplied the complete external
    authority.  Consequently even a locally complete candidate set remains
    non-admitted and non-green.
    """

    if type(authorities) is not tuple or len(authorities) > _MAX_AUTHORITIES:
        raise StarSemanticAuthoringContractError("authorities must be an exact bounded tuple")
    if type(decisions) is not tuple or len(decisions) > _MAX_DECISIONS:
        raise StarSemanticAuthoringContractError("decisions must be an exact bounded tuple")
    if any(type(item) is not StarTableSemanticAuthorityV1 for item in authorities):
        raise StarSemanticAuthoringContractError(
            "authorities must contain exact StarTableSemanticAuthorityV1 rows"
        )
    if any(type(item) is not StarTableSemanticDecisionV1 for item in decisions):
        raise StarSemanticAuthoringContractError(
            "decisions must contain exact StarTableSemanticDecisionV1 rows"
        )
    if authorities != tuple(sorted(authorities, key=lambda item: item.output_name)) or len(
        {item.output_name for item in authorities}
    ) != len(authorities):
        raise StarSemanticAuthoringContractError(
            "authorities must be sorted with unique table identities"
        )
    if decisions != tuple(sorted(decisions, key=lambda item: item.table_name)) or len(
        {item.table_name for item in decisions}
    ) != len(decisions):
        raise StarSemanticAuthoringContractError(
            "decisions must be sorted with unique table identities"
        )
    if sum(len(item.relationships) for item in decisions) > _MAX_TOTAL_RELATIONSHIPS:
        raise StarSemanticAuthoringContractError(
            "decisions exceed the bounded aggregate relationship budget"
        )
    structural_generations = {item.structural_inventory_sha256 for item in authorities}
    stable_generations = {item.stable_inventory_sha256 for item in authorities}
    if len(structural_generations) > 1 or len(stable_generations) > 1:
        raise StarSemanticAuthoringContractError("mixed authority generations are forbidden")

    authority_inventory_sha256 = _authority_inventory_sha256(authorities)
    decision_inventory_sha256 = _decision_inventory_sha256(decisions)
    structural_inventory_sha256 = (
        None if not authorities else authorities[0].structural_inventory_sha256
    )
    stable_inventory_sha256 = None if not authorities else authorities[0].stable_inventory_sha256
    authorities_by_name = {item.output_name: item for item in authorities}
    decisions_by_name = {item.table_name: item for item in decisions}
    blockers: list[StarSemanticAuthoringBlockerV1] = [
        _blocker(
            scope_id="star_semantic_authoring",
            code="frozen_authority_completeness_unproven",
            evidence_sha256s=(authority_inventory_sha256,),
        )
    ]
    if not authorities:
        blockers.append(
            _blocker(
                scope_id="star_semantic_authoring",
                code="authority_inventory_empty",
                evidence_sha256s=(authority_inventory_sha256,),
            )
        )
    for decision in decisions:
        if decision.table_name not in authorities_by_name:
            blockers.append(
                _blocker(
                    scope_id=decision.table_name,
                    code="semantic_decision_without_authority",
                    evidence_sha256s=(decision.decision_sha256,),
                )
            )

    candidates: list[StarTableSemanticCandidateV1] = []
    for authority in authorities:
        decision = decisions_by_name.get(authority.output_name)
        authority_blockers: list[StarSemanticAuthoringBlockerV1] = []
        if not authority.ordered_columns:
            authority_blockers.append(
                _blocker(
                    scope_id=authority.output_name,
                    code="authority_ordered_columns_empty",
                    evidence_sha256s=(authority.authority_sha256, authority.schema_sha256),
                )
            )
        if authority.candidate_sha256 is None:
            authority_blockers.append(
                _blocker(
                    scope_id=authority.output_name,
                    code="authority_candidate_missing",
                    evidence_sha256s=(authority.authority_sha256,),
                )
            )
        elif authority.candidate_implementation_status != "implemented":
            authority_blockers.append(
                _blocker(
                    scope_id=authority.output_name,
                    code="authority_candidate_implementation_missing",
                    evidence_sha256s=(authority.authority_sha256, authority.candidate_sha256),
                )
            )
        if authority.disposition_semantic_sha256 is None:
            authority_blockers.append(
                _blocker(
                    scope_id=authority.output_name,
                    code="authority_disposition_missing",
                    evidence_sha256s=(authority.authority_sha256,),
                )
            )
        elif authority.disposition_status != "stable":
            authority_blockers.append(
                _blocker(
                    scope_id=authority.output_name,
                    code="authority_not_stable",
                    evidence_sha256s=(
                        authority.authority_sha256,
                        authority.disposition_semantic_sha256,
                    ),
                )
            )
        if decision is None:
            blockers.extend(authority_blockers)
            blockers.append(
                _blocker(
                    scope_id=authority.output_name,
                    code="semantic_decision_missing",
                    evidence_sha256s=(authority.authority_sha256,),
                )
            )
            continue
        table_blockers = authority_blockers
        if decision.authority_sha256 != authority.authority_sha256:
            table_blockers.append(
                _blocker(
                    scope_id=authority.output_name,
                    code="semantic_decision_authority_mismatch",
                    evidence_sha256s=(authority.authority_sha256, decision.decision_sha256),
                )
            )
        target_authorities: list[StarTableSemanticAuthorityV1] = []
        for relationship in decision.relationships:
            target = authorities_by_name.get(relationship.target_table)
            if target is None or any(
                column not in target.ordered_columns for column in relationship.target_columns
            ):
                table_blockers.append(
                    _blocker(
                        scope_id=authority.output_name,
                        code="semantic_relationship_target_invalid",
                        evidence_sha256s=(
                            authority.authority_sha256,
                            decision.decision_sha256,
                            relationship.evidence_sha256,
                        ),
                    )
                )
            else:
                target_authorities.append(target)
        if table_blockers:
            blockers.extend(table_blockers)
            continue
        try:
            semantic_contract = _semantic_contract_for(authority, decision)
        except (StarSemanticContractError, StarSemanticAuthoringContractError):
            blockers.append(
                _blocker(
                    scope_id=authority.output_name,
                    code="semantic_decision_invalid",
                    evidence_sha256s=(authority.authority_sha256, decision.decision_sha256),
                )
            )
            continue
        target_hashes = tuple(sorted({target.authority_sha256 for target in target_authorities}))
        evidence_inputs = _evidence_inputs(
            authority_inventory_sha256=authority_inventory_sha256,
            authority=authority,
            decision=decision,
            relationship_target_authority_sha256s=target_hashes,
            semantic_sha256=semantic_contract.semantic_sha256,
        )
        evidence_closure_sha256 = canonical_star_semantic_authoring_sha256(
            {
                "schema_version": STAR_SEMANTIC_AUTHORING_SCHEMA_VERSION,
                "kind": _EVIDENCE_CLOSURE_KIND,
                "required_review_input_sha256s": list(evidence_inputs),
            }
        )
        candidates.append(
            StarTableSemanticCandidateV1(
                authority_inventory_sha256=authority_inventory_sha256,
                authority=authority,
                decision=decision,
                relationship_target_authority_sha256s=target_hashes,
                semantic_sha256=semantic_contract.semantic_sha256,
                required_review_input_sha256s=evidence_inputs,
                evidence_closure_sha256=evidence_closure_sha256,
            )
        )

    return StarSemanticAuthoringGenerationV1(
        structural_inventory_sha256=structural_inventory_sha256,
        stable_inventory_sha256=stable_inventory_sha256,
        authority_inventory_sha256=authority_inventory_sha256,
        decision_inventory_sha256=decision_inventory_sha256,
        candidates=tuple(sorted(candidates, key=lambda item: item.authority.output_name)),
        blockers=tuple(
            sorted(
                set(blockers),
                key=lambda item: (item.scope_id, item.code, item.evidence_sha256s),
            )
        ),
    )
