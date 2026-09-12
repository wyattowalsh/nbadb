"""Independent verifier for non-admitted star-semantic authoring candidates.

This module intentionally imports neither ``star_semantic_authoring`` nor any
of its helpers.  It strict-parses canonical authority, decision, and observed
generation bytes; independently re-derives every candidate, blocker, digest,
and evidence-closure row; and then requires exact structural equality.

The proof remains source-relative and non-admitted.  It cannot prove that the
caller supplied the complete frozen authority, that a reviewer accepted the
semantics, or that the public model is green.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "IndependentStarSemanticAuthoringError",
    "StarSemanticAuthoringIndependentProofV1",
    "verify_star_semantic_authoring_generation_independently",
]

_SCHEMA_VERSION = 1
_DECISION_KIND = "nbadb_star_table_semantic_decision"
_CANDIDATE_KIND = "nbadb_star_table_semantic_authoring_candidate"
_GENERATION_KIND = "nbadb_star_semantic_authoring_generation"
_AUTHORITY_INPUT_KIND = "nbadb_star_semantic_authority_input"
_DECISION_INPUT_KIND = "nbadb_star_semantic_decision_input"
_EVIDENCE_CLOSURE_KIND = "nbadb_star_semantic_review_input_closure"
_PROOF_KIND = "nbadb_star_semantic_authoring_independent_proof"
_SEMANTIC_KIND = "nbadb_star_table_semantic_contract"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_MAX_AUTHORITIES = 10_000
_MAX_DECISIONS = 10_000
_MAX_COLUMNS = 100_000
_MAX_TOTAL_RELATIONSHIPS = 100_000
_MAX_GENERATION_BLOCKERS = 2 + _MAX_DECISIONS + (_MAX_AUTHORITIES * 5) + _MAX_TOTAL_RELATIONSHIPS
_MAX_CANONICAL_BYTES = 128 * 1024 * 1024

_FAMILY_PREFIXES = {
    "dimension": "dim_",
    "fact": "fact_",
    "bridge": "bridge_",
    "aggregate": "agg_",
    "analytics": "analytics_",
}
_STABILITIES = frozenset({"stable", "experimental", "withheld", "rejected"})
_KEY_MODES = frozenset({"keyed", "reviewed_bag"})
_KEY_KINDS = frozenset({"natural", "candidate", "surrogate"})
_NULL_POLICIES = frozenset({"forbidden", "allowed_distinct", "allowed_equal"})
_CARDINALITIES = frozenset({"one_to_one", "many_to_one", "one_to_many", "many_to_many"})
_ORPHAN_POLICIES = frozenset({"reject", "allow", "typed_unavailable"})
_RELATIONSHIP_TIMINGS = frozenset({"current", "as_of", "event_time", "not_applicable"})
_LINEAGE_SOURCE_KINDS = frozenset(
    {"provider_occurrence", "storage_occurrence", "star_column", "literal", "audit", "expression"}
)
_LINEAGE_TRANSFORM_KINDS = frozenset(
    {"copy", "rename", "cast", "expression", "aggregate", "window", "union"}
)
_ROW_MODES = frozenset({"entity", "event", "snapshot", "aggregate", "bridge"})
_FILTER_POLICIES = frozenset({"preserve", "reviewed_filter"})
_DEDUP_POLICIES = frozenset({"none", "exact", "latest_by_key", "source_precedence"})
_UNION_POLICIES = frozenset({"none", "multiset", "set", "source_precedence"})
_AGGREGATION_POLICIES = frozenset({"none", "grouped", "windowed"})
_ADDITIVITY = frozenset({"not_applicable", "additive", "semi_additive", "non_additive"})
_CORRECTION_POLICIES = frozenset({"append_only", "replace_scope", "scd", "latest_truth"})
_TRUTH_MODES = frozenset({"event_truth", "as_observed", "current_truth", "bitemporal"})
_SCD_POLICIES = frozenset({"not_applicable", "type1", "type2"})
_COVERAGE_POLICIES = frozenset({"complete_scope", "declared_partial", "snapshot"})
_INCOMPLETE_POLICIES = frozenset({"reject", "typed_incomplete"})
_EMPTY_POLICIES = frozenset({"materialize_typed_empty", "reject_empty"})
_UNAVAILABLE_POLICIES = frozenset({"typed_unavailable", "contract_blocked", "not_applicable"})
_CARDINALITY_EFFECTS = frozenset({"row_preserving", "expanding", "reducing"})
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


class IndependentStarSemanticAuthoringError(ValueError):
    """Raised when independent reconstruction fails or observed bytes differ."""


class _SemanticDecisionError(ValueError):
    """Internal signal for a well-formed decision with invalid joined semantics."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise IndependentStarSemanticAuthoringError(
            "independent star semantic value is not canonical JSON"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise IndependentStarSemanticAuthoringError(f"{label} must be an exact string-keyed object")
    return cast("dict[str, object]", value)


def _array(value: object, *, label: str, maximum: int = _MAX_COLUMNS) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise IndependentStarSemanticAuthoringError(f"{label} must be an exact bounded array")
    return cast("list[object]", value)


def _exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if frozenset(payload) != expected:
        raise IndependentStarSemanticAuthoringError(f"{label} has missing or unexpected fields")


def _decode_canonical_mapping(raw: bytes, *, label: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise IndependentStarSemanticAuthoringError(f"{label} canonical byte length is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise IndependentStarSemanticAuthoringError(
                    f"{label} canonical JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                IndependentStarSemanticAuthoringError(
                    f"{label} contains non-finite JSON constant {value}"
                )
            ),
        )
    except IndependentStarSemanticAuthoringError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise IndependentStarSemanticAuthoringError(f"{label} is invalid JSON") from exc
    payload = _mapping(decoded, label=label)
    if _canonical_bytes(payload) != raw:
        raise IndependentStarSemanticAuthoringError(f"{label} is not exact canonical JSON")
    return payload


def _sha(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise IndependentStarSemanticAuthoringError(f"{label} must be an exact lowercase SHA-256")
    return value


def _optional_sha(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _sha(value, label=label)


def _safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise IndependentStarSemanticAuthoringError(
            f"{label} must be an exact bounded safe identifier"
        )
    return value


def _optional_id(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _safe_id(value, label=label)


def _schema(payload: Mapping[str, object], *, kind: str, label: str) -> None:
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != _SCHEMA_VERSION
        or type(payload.get("kind")) is not str
        or payload.get("kind") != kind
    ):
        raise IndependentStarSemanticAuthoringError(f"{label} schema identity is invalid")


def _id_array(
    value: object,
    *,
    label: str,
    allow_empty: bool,
    sorted_values: bool,
) -> list[str]:
    raw = _array(value, label=label)
    values = [_safe_id(item, label=label) for item in raw]
    if (not allow_empty and not values) or len(values) != len(set(values)):
        raise IndependentStarSemanticAuthoringError(f"{label} cardinality or uniqueness is invalid")
    if sorted_values and values != sorted(values):
        raise IndependentStarSemanticAuthoringError(f"{label} must be sorted")
    return values


def _sha_array(value: object, *, label: str, allow_empty: bool) -> list[str]:
    raw = _array(value, label=label)
    values = [_sha(item, label=label) for item in raw]
    if (not allow_empty and not values) or values != sorted(set(values)):
        raise IndependentStarSemanticAuthoringError(
            f"{label} must be canonical sorted unique SHA-256 values"
        )
    return values


def _literal(value: object, *, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        raise IndependentStarSemanticAuthoringError(f"{label} literal is invalid")
    return value


def _validate_authority(value: object) -> dict[str, object]:
    payload = _mapping(value, label="semantic authority")
    fields = frozenset(
        {
            "output_name",
            "table_family",
            "structural_inventory_sha256",
            "stable_inventory_sha256",
            "structural_table_sha256",
            "schema_sha256",
            "transform_sha256",
            "ordered_columns",
            "transformer_dependencies",
            "expected_candidate_id",
            "candidate_sha256",
            "candidate_kind",
            "candidate_gate_requirement",
            "candidate_structural_sha256",
            "candidate_implementation_status",
            "candidate_implementation_sha256",
            "disposition_semantic_sha256",
            "disposition_status",
            "authority_sha256",
        }
    )
    _exact_keys(payload, expected=fields, label="semantic authority")
    output_name = _safe_id(payload["output_name"], label="authority output_name")
    family = _literal(
        payload["table_family"],
        allowed=frozenset(_FAMILY_PREFIXES),
        label="authority table_family",
    )
    if not output_name.startswith(_FAMILY_PREFIXES[family]):
        raise IndependentStarSemanticAuthoringError("authority table family and name disagree")
    for field in (
        "structural_inventory_sha256",
        "stable_inventory_sha256",
        "structural_table_sha256",
        "schema_sha256",
        "transform_sha256",
        "authority_sha256",
    ):
        _sha(payload[field], label=f"authority {field}")
    ordered_columns = _id_array(
        payload["ordered_columns"],
        label="authority ordered_columns",
        allow_empty=True,
        sorted_values=False,
    )
    dependencies = _id_array(
        payload["transformer_dependencies"],
        label="authority transformer_dependencies",
        allow_empty=True,
        sorted_values=False,
    )
    del ordered_columns, dependencies
    if payload["expected_candidate_id"] != f"star:{output_name}":
        raise IndependentStarSemanticAuthoringError("authority expected candidate id drifted")
    candidate_sha = _optional_sha(payload["candidate_sha256"], label="candidate_sha256")
    candidate_kind = _optional_id(payload["candidate_kind"], label="candidate_kind")
    candidate_gate = _optional_id(
        payload["candidate_gate_requirement"], label="candidate_gate_requirement"
    )
    candidate_structural = _optional_sha(
        payload["candidate_structural_sha256"], label="candidate_structural_sha256"
    )
    candidate_status = _optional_id(
        payload["candidate_implementation_status"], label="candidate_implementation_status"
    )
    candidate_implementation = _optional_sha(
        payload["candidate_implementation_sha256"], label="candidate_implementation_sha256"
    )
    identity_values = (
        candidate_sha,
        candidate_kind,
        candidate_gate,
        candidate_structural,
        candidate_status,
    )
    if any(item is None for item in identity_values) and any(
        item is not None for item in identity_values
    ):
        raise IndependentStarSemanticAuthoringError("candidate authority fields do not co-occur")
    if candidate_sha is not None:
        if candidate_kind not in {family, "live"} or candidate_gate != "stable_required":
            raise IndependentStarSemanticAuthoringError("candidate authority identity is invalid")
        if candidate_status == "implemented" and candidate_implementation is None:
            raise IndependentStarSemanticAuthoringError(
                "implemented candidate lacks implementation digest"
            )
        if candidate_status == "missing" and candidate_implementation is not None:
            raise IndependentStarSemanticAuthoringError(
                "missing candidate carries implementation digest"
            )
        if candidate_status not in {"implemented", "missing"}:
            raise IndependentStarSemanticAuthoringError("candidate status is invalid")
    elif candidate_implementation is not None:
        raise IndependentStarSemanticAuthoringError(
            "implementation digest lacks candidate authority"
        )
    disposition_sha = _optional_sha(
        payload["disposition_semantic_sha256"], label="disposition_semantic_sha256"
    )
    disposition_status = _optional_id(payload["disposition_status"], label="disposition_status")
    if (disposition_sha is None) != (disposition_status is None):
        raise IndependentStarSemanticAuthoringError("disposition fields do not co-occur")
    if disposition_sha is not None and (
        candidate_sha is None or disposition_status not in _STABILITIES
    ):
        raise IndependentStarSemanticAuthoringError("disposition authority is invalid")
    content = {key: payload[key] for key in payload if key != "authority_sha256"}
    if payload["authority_sha256"] != _sha256(content):
        raise IndependentStarSemanticAuthoringError("authority digest is invalid")
    return payload


def _validate_key_group(value: object) -> dict[str, object]:
    payload = _mapping(value, label="key group")
    _exact_keys(
        payload,
        expected=frozenset({"key_id", "key_kind", "columns", "null_policy", "evidence_sha256"}),
        label="key group",
    )
    _safe_id(payload["key_id"], label="key group id")
    _literal(payload["key_kind"], allowed=_KEY_KINDS, label="key kind")
    _id_array(payload["columns"], label="key columns", allow_empty=False, sorted_values=False)
    _literal(payload["null_policy"], allowed=_NULL_POLICIES, label="key null policy")
    _sha(payload["evidence_sha256"], label="key evidence")
    return payload


def _validate_functional_dependency(value: object) -> dict[str, object]:
    payload = _mapping(value, label="functional dependency")
    _exact_keys(
        payload,
        expected=frozenset({"dependency_id", "determinants", "dependents", "evidence_sha256"}),
        label="functional dependency",
    )
    _safe_id(payload["dependency_id"], label="functional dependency id")
    determinants = _id_array(
        payload["determinants"],
        label="functional determinants",
        allow_empty=False,
        sorted_values=True,
    )
    dependents = _id_array(
        payload["dependents"],
        label="functional dependents",
        allow_empty=False,
        sorted_values=True,
    )
    if set(determinants) & set(dependents):
        raise IndependentStarSemanticAuthoringError("functional dependency sides overlap")
    _sha(payload["evidence_sha256"], label="functional dependency evidence")
    return payload


def _validate_relationship(value: object) -> dict[str, object]:
    payload = _mapping(value, label="relationship")
    _exact_keys(
        payload,
        expected=frozenset(
            {
                "relationship_id",
                "local_columns",
                "target_table",
                "target_columns",
                "cardinality",
                "orphan_policy",
                "timing",
                "evidence_sha256",
            }
        ),
        label="relationship",
    )
    _safe_id(payload["relationship_id"], label="relationship id")
    local = _id_array(
        payload["local_columns"],
        label="relationship local columns",
        allow_empty=False,
        sorted_values=False,
    )
    _safe_id(payload["target_table"], label="relationship target table")
    target = _id_array(
        payload["target_columns"],
        label="relationship target columns",
        allow_empty=False,
        sorted_values=False,
    )
    if len(local) != len(target):
        raise IndependentStarSemanticAuthoringError("relationship arity differs")
    _literal(payload["cardinality"], allowed=_CARDINALITIES, label="relationship cardinality")
    _literal(payload["orphan_policy"], allowed=_ORPHAN_POLICIES, label="orphan policy")
    _literal(payload["timing"], allowed=_RELATIONSHIP_TIMINGS, label="relationship timing")
    _sha(payload["evidence_sha256"], label="relationship evidence")
    return payload


def _validate_lineage(value: object) -> dict[str, object]:
    payload = _mapping(value, label="lineage edge")
    _exact_keys(
        payload,
        expected=frozenset(
            {
                "edge_id",
                "target_column",
                "source_kind",
                "source_ids",
                "source_dependency_ids",
                "transform_kind",
                "expression_sha256",
                "evidence_sha256",
            }
        ),
        label="lineage edge",
    )
    _safe_id(payload["edge_id"], label="lineage edge id")
    _safe_id(payload["target_column"], label="lineage target column")
    source_kind = _literal(
        payload["source_kind"], allowed=_LINEAGE_SOURCE_KINDS, label="lineage source kind"
    )
    source_ids = _id_array(
        payload["source_ids"],
        label="lineage source ids",
        allow_empty=False,
        sorted_values=True,
    )
    source_dependencies = _id_array(
        payload["source_dependency_ids"],
        label="lineage source dependencies",
        allow_empty=True,
        sorted_values=True,
    )
    if (source_kind not in {"literal", "audit"}) != bool(source_dependencies):
        raise IndependentStarSemanticAuthoringError(
            "lineage dependency membership disagrees with source kind"
        )
    transform_kind = _literal(
        payload["transform_kind"],
        allowed=_LINEAGE_TRANSFORM_KINDS,
        label="lineage transform kind",
    )
    if transform_kind in {"copy", "rename", "cast"} and len(source_ids) != 1:
        raise IndependentStarSemanticAuthoringError("unary lineage has invalid source arity")
    if transform_kind == "union" and len(source_ids) < 2:
        raise IndependentStarSemanticAuthoringError("union lineage has invalid source arity")
    expression_required = transform_kind in {"cast", "expression", "aggregate", "window", "union"}
    expression_sha = payload["expression_sha256"]
    if expression_required:
        _sha(expression_sha, label="lineage expression")
    elif expression_sha is not None:
        raise IndependentStarSemanticAuthoringError("copy/rename lineage carries expression")
    _sha(payload["evidence_sha256"], label="lineage evidence")
    return payload


def _validate_row_policy(value: object) -> dict[str, object]:
    payload = _mapping(value, label="row policy")
    _exact_keys(
        payload,
        expected=frozenset(
            {
                "row_mode",
                "filter_policy",
                "dedup_policy",
                "union_policy",
                "aggregation_policy",
                "additivity",
                "evidence_sha256",
            }
        ),
        label="row policy",
    )
    _literal(payload["row_mode"], allowed=_ROW_MODES, label="row mode")
    _literal(payload["filter_policy"], allowed=_FILTER_POLICIES, label="filter policy")
    _literal(payload["dedup_policy"], allowed=_DEDUP_POLICIES, label="dedup policy")
    _literal(payload["union_policy"], allowed=_UNION_POLICIES, label="union policy")
    _literal(
        payload["aggregation_policy"],
        allowed=_AGGREGATION_POLICIES,
        label="aggregation policy",
    )
    _literal(payload["additivity"], allowed=_ADDITIVITY, label="additivity")
    _sha(payload["evidence_sha256"], label="row policy evidence")
    return payload


def _validate_temporal_policy(value: object) -> dict[str, object]:
    payload = _mapping(value, label="temporal policy")
    _exact_keys(
        payload,
        expected=frozenset(
            {
                "event_columns",
                "observation_columns",
                "load_columns",
                "version_columns",
                "feature_cutoff_columns",
                "correction_policy",
                "truth_mode",
                "evidence_sha256",
            }
        ),
        label="temporal policy",
    )
    for field in (
        "event_columns",
        "observation_columns",
        "load_columns",
        "version_columns",
        "feature_cutoff_columns",
    ):
        _id_array(
            payload[field],
            label=f"temporal {field}",
            allow_empty=True,
            sorted_values=True,
        )
    _literal(
        payload["correction_policy"],
        allowed=_CORRECTION_POLICIES,
        label="correction policy",
    )
    _literal(payload["truth_mode"], allowed=_TRUTH_MODES, label="truth mode")
    _sha(payload["evidence_sha256"], label="temporal evidence")
    return payload


def _validate_dependency_cardinality(value: object) -> dict[str, object]:
    payload = _mapping(value, label="dependency cardinality")
    _exact_keys(
        payload,
        expected=frozenset({"dependency_id", "effect", "equation_code", "evidence_sha256"}),
        label="dependency cardinality",
    )
    _safe_id(payload["dependency_id"], label="dependency cardinality id")
    _literal(payload["effect"], allowed=_CARDINALITY_EFFECTS, label="cardinality effect")
    _safe_id(payload["equation_code"], label="cardinality equation")
    _sha(payload["evidence_sha256"], label="cardinality evidence")
    return payload


_DECISION_FIELDS = frozenset(
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
)


def _validate_sorted_identity_rows(
    rows: list[dict[str, object]],
    *,
    identity: str,
    label: str,
) -> None:
    identities = [_safe_id(row[identity], label=f"{label} identity") for row in rows]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise IndependentStarSemanticAuthoringError(
            f"{label} must be sorted with unique identities"
        )


def _validate_decision(value: object) -> dict[str, object]:
    payload = _mapping(value, label="semantic decision")
    _exact_keys(payload, expected=_DECISION_FIELDS, label="semantic decision")
    _schema(payload, kind=_DECISION_KIND, label="semantic decision")
    _safe_id(payload["table_name"], label="decision table name")
    _sha(payload["authority_sha256"], label="decision authority")
    _safe_id(payload["purpose_code"], label="purpose code")
    _sha(payload["purpose_evidence_sha256"], label="purpose evidence")
    for field, allow_empty in (
        ("grain_dimensions", False),
        ("observation_identity", False),
        ("competition_discriminators", True),
        ("request_discriminators", True),
    ):
        _id_array(
            payload[field],
            label=f"decision {field}",
            allow_empty=allow_empty,
            sorted_values=False,
        )
    _literal(payload["key_mode"], allowed=_KEY_MODES, label="key mode")
    keys = [
        _validate_key_group(item)
        for item in _array(payload["key_groups"], label="decision key groups")
    ]
    dependencies = [
        _validate_functional_dependency(item)
        for item in _array(
            payload["functional_dependencies"], label="decision functional dependencies"
        )
    ]
    relationships = [
        _validate_relationship(item)
        for item in _array(
            payload["relationships"],
            label="decision relationships",
            maximum=_MAX_TOTAL_RELATIONSHIPS,
        )
    ]
    lineage = [
        _validate_lineage(item)
        for item in _array(payload["lineage_edges"], label="decision lineage")
    ]
    cardinalities = [
        _validate_dependency_cardinality(item)
        for item in _array(
            payload["dependency_cardinalities"], label="decision dependency cardinalities"
        )
    ]
    for rows, identity, label in (
        (keys, "key_id", "key groups"),
        (dependencies, "dependency_id", "functional dependencies"),
        (relationships, "relationship_id", "relationships"),
        (lineage, "edge_id", "lineage"),
        (cardinalities, "dependency_id", "dependency cardinalities"),
    ):
        _validate_sorted_identity_rows(rows, identity=identity, label=label)
    _validate_row_policy(payload["row_policy"])
    _validate_temporal_policy(payload["temporal_policy"])
    _literal(payload["source_mode"], allowed=_SOURCE_MODES, label="source mode")
    _literal(payload["scd_policy"], allowed=_SCD_POLICIES, label="SCD policy")
    algorithm_id = payload["algorithm_id"]
    algorithm_version = payload["algorithm_version"]
    if (algorithm_id is None) != (algorithm_version is None):
        raise IndependentStarSemanticAuthoringError("algorithm identity does not co-occur")
    if algorithm_id is not None:
        _safe_id(algorithm_id, label="algorithm id")
        _safe_id(algorithm_version, label="algorithm version")
    _literal(payload["coverage_policy"], allowed=_COVERAGE_POLICIES, label="coverage policy")
    _literal(payload["incomplete_policy"], allowed=_INCOMPLETE_POLICIES, label="incomplete policy")
    _literal(payload["empty_policy"], allowed=_EMPTY_POLICIES, label="empty policy")
    _literal(
        payload["unavailable_policy"],
        allowed=_UNAVAILABLE_POLICIES,
        label="unavailable policy",
    )
    for field in (
        "positive_witness_sha256s",
        "negative_witness_sha256s",
        "mutation_witness_sha256s",
    ):
        _sha_array(payload[field], label=f"decision {field}", allow_empty=False)
    content = {key: payload[key] for key in payload if key != "decision_sha256"}
    if payload["decision_sha256"] != _sha256(content):
        raise IndependentStarSemanticAuthoringError("decision digest is invalid")
    return payload


def _require_subset(values: Sequence[str], columns: set[str], *, label: str) -> None:
    if any(value not in columns for value in values):
        raise _SemanticDecisionError(f"{label} contains foreign columns")


def _semantic_payload(
    authority: Mapping[str, object],
    decision: Mapping[str, object],
) -> dict[str, object]:
    columns_list = cast("list[str]", authority["ordered_columns"])
    dependencies_list = cast("list[str]", authority["transformer_dependencies"])
    if not columns_list:
        raise _SemanticDecisionError("authority cannot form a final semantic contract")
    columns = set(columns_list)
    grain = cast("list[str]", decision["grain_dimensions"])
    observation = cast("list[str]", decision["observation_identity"])
    competition = cast("list[str]", decision["competition_discriminators"])
    request = cast("list[str]", decision["request_discriminators"])
    for label, values in (
        ("grain", grain),
        ("observation", observation),
        ("competition", competition),
        ("request", request),
    ):
        _require_subset(values, columns, label=label)
    if set(observation) != set(grain) | set(competition) | set(request):
        raise _SemanticDecisionError("observation identity differs from grain/discriminators")

    key_mode = cast("str", decision["key_mode"])
    key_groups = cast("list[dict[str, object]]", decision["key_groups"])
    if key_mode == "keyed" and not key_groups:
        raise _SemanticDecisionError("keyed decision lacks keys")
    if key_mode == "reviewed_bag" and key_groups:
        raise _SemanticDecisionError("reviewed bag carries keys")
    key_column_sets: set[tuple[str, ...]] = set()
    semantic_key_count = 0
    for key in key_groups:
        key_columns = cast("list[str]", key["columns"])
        _require_subset(key_columns, columns, label="key")
        identity = tuple(key_columns)
        if identity in key_column_sets:
            raise _SemanticDecisionError("duplicate semantic key column set")
        key_column_sets.add(identity)
        if key["key_kind"] != "surrogate":
            semantic_key_count += 1
            if not set(key_columns).issubset(observation):
                raise _SemanticDecisionError("semantic key falls outside observation identity")
    if key_mode == "keyed" and semantic_key_count == 0:
        raise _SemanticDecisionError("keyed decision lacks semantic key")

    for dependency in cast("list[dict[str, object]]", decision["functional_dependencies"]):
        _require_subset(
            cast("list[str]", dependency["determinants"]),
            columns,
            label="functional determinants",
        )
        _require_subset(
            cast("list[str]", dependency["dependents"]),
            columns,
            label="functional dependents",
        )
    relationship_semantics: set[tuple[object, ...]] = set()
    for relationship in cast("list[dict[str, object]]", decision["relationships"]):
        local = cast("list[str]", relationship["local_columns"])
        _require_subset(local, columns, label="relationship")
        semantic_identity = (
            tuple(local),
            relationship["target_table"],
            tuple(cast("list[str]", relationship["target_columns"])),
            relationship["timing"],
        )
        if semantic_identity in relationship_semantics:
            raise _SemanticDecisionError("duplicate relationship semantic identity")
        relationship_semantics.add(semantic_identity)

    lineage = cast("list[dict[str, object]]", decision["lineage_edges"])
    lineage_targets = [cast("str", edge["target_column"]) for edge in lineage]
    if len(lineage_targets) != len(set(lineage_targets)) or set(lineage_targets) != columns:
        raise _SemanticDecisionError("lineage does not exactly cover target columns")
    lineage_dependencies = {
        dependency_id
        for edge in lineage
        for dependency_id in cast("list[str]", edge["source_dependency_ids"])
    }
    source_mode = cast("str", decision["source_mode"])
    if source_mode == "dependency_backed":
        if not dependencies_list:
            raise _SemanticDecisionError("dependency-backed semantics lack dependencies")
        if lineage_dependencies != set(dependencies_list):
            raise _SemanticDecisionError("lineage dependency coverage differs")
    else:
        if dependencies_list:
            raise _SemanticDecisionError("source-free semantics carry dependencies")
        if lineage_dependencies or any(
            cast("list[str]", edge["source_dependency_ids"]) for edge in lineage
        ):
            raise _SemanticDecisionError("source-free lineage carries dependency identities")
        if any(edge["source_kind"] not in {"literal", "audit"} for edge in lineage):
            raise _SemanticDecisionError("source-free lineage is not literal or audit")

    temporal = cast("dict[str, object]", decision["temporal_policy"])
    temporal_columns = [
        column
        for field in (
            "event_columns",
            "observation_columns",
            "load_columns",
            "version_columns",
            "feature_cutoff_columns",
        )
        for column in cast("list[str]", temporal[field])
    ]
    _require_subset(temporal_columns, columns, label="temporal policy")
    scd_policy = decision["scd_policy"]
    version_columns = cast("list[str]", temporal["version_columns"])
    if scd_policy == "type2":
        if temporal["correction_policy"] != "scd" or not version_columns:
            raise _SemanticDecisionError("type2 SCD policy is incomplete")
        if not set(version_columns).issubset(observation):
            raise _SemanticDecisionError("type2 version columns leave observation identity")
    elif scd_policy == "type1":
        if version_columns or temporal["correction_policy"] not in {
            "replace_scope",
            "latest_truth",
        }:
            raise _SemanticDecisionError("type1 SCD policy is inconsistent")
    elif temporal["correction_policy"] == "scd":
        raise _SemanticDecisionError("SCD correction lacks type2 policy")
    if temporal["truth_mode"] == "event_truth" and not temporal["event_columns"]:
        raise _SemanticDecisionError("event truth lacks event columns")
    if temporal["truth_mode"] == "as_observed" and not temporal["observation_columns"]:
        raise _SemanticDecisionError("observed truth lacks observation columns")
    if temporal["truth_mode"] == "bitemporal" and (
        not temporal["event_columns"] or not temporal["observation_columns"]
    ):
        raise _SemanticDecisionError("bitemporal truth lacks both timelines")

    row_policy = cast("dict[str, object]", decision["row_policy"])
    family = authority["table_family"]
    if family == "aggregate" and (
        row_policy["row_mode"] != "aggregate" or row_policy["aggregation_policy"] == "none"
    ):
        raise _SemanticDecisionError("aggregate family row policy is invalid")
    if family == "bridge" and row_policy["row_mode"] != "bridge":
        raise _SemanticDecisionError("bridge family row policy is invalid")
    cardinality_ids = {
        cast("str", item["dependency_id"])
        for item in cast("list[dict[str, object]]", decision["dependency_cardinalities"])
    }
    if cardinality_ids != set(dependencies_list):
        raise _SemanticDecisionError("dependency cardinality coverage differs")
    if source_mode == "reviewed_source_free" and cardinality_ids:
        raise _SemanticDecisionError("source-free semantics carry dependency cardinalities")
    source_free_algorithm_derived = source_mode == "reviewed_source_free" and any(
        edge["source_kind"] == "audit"
        or edge["transform_kind"] in {"cast", "expression", "aggregate", "window", "union"}
        for edge in lineage
    )
    if source_free_algorithm_derived and decision["algorithm_id"] is None:
        raise _SemanticDecisionError("algorithm-derived source-free semantics lack identity")

    disposition = authority["disposition_status"]
    if disposition == "stable":
        public_disposition = "published"
    elif disposition in {"withheld", "rejected"}:
        public_disposition = "unpublished"
    else:
        raise _SemanticDecisionError("disposition cannot bind public status")
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": _SEMANTIC_KIND,
        "table_name": authority["output_name"],
        "table_family": authority["table_family"],
        "structural_table_sha256": authority["structural_table_sha256"],
        "schema_sha256": authority["schema_sha256"],
        "transform_sha256": authority["transform_sha256"],
        "stable_disposition_sha256": authority["disposition_semantic_sha256"],
        "stability": disposition,
        "public_disposition": public_disposition,
        "purpose_code": decision["purpose_code"],
        "purpose_evidence_sha256": decision["purpose_evidence_sha256"],
        "ordered_columns": columns_list,
        "grain_dimensions": grain,
        "observation_identity": observation,
        "key_mode": key_mode,
        "key_groups": decision["key_groups"],
        "functional_dependencies": decision["functional_dependencies"],
        "relationships": decision["relationships"],
        "lineage_edges": decision["lineage_edges"],
        "competition_discriminators": competition,
        "request_discriminators": request,
        "source_mode": source_mode,
        "source_precedence": dependencies_list,
        "row_policy": row_policy,
        "temporal_policy": temporal,
        "scd_policy": scd_policy,
        "algorithm_id": decision["algorithm_id"],
        "algorithm_version": decision["algorithm_version"],
        "coverage_policy": decision["coverage_policy"],
        "incomplete_policy": decision["incomplete_policy"],
        "empty_policy": decision["empty_policy"],
        "unavailable_policy": decision["unavailable_policy"],
        "dependency_cardinalities": decision["dependency_cardinalities"],
        "positive_witness_sha256s": decision["positive_witness_sha256s"],
        "negative_witness_sha256s": decision["negative_witness_sha256s"],
        "mutation_witness_sha256s": decision["mutation_witness_sha256s"],
    }


def _evidence_inputs(
    *,
    authority_inventory_sha256: str,
    authority: Mapping[str, object],
    decision: Mapping[str, object],
    target_hashes: Sequence[str],
    semantic_sha256: str,
) -> list[str]:
    inputs = {
        authority_inventory_sha256,
        cast("str", authority["authority_sha256"]),
        cast("str", authority["structural_inventory_sha256"]),
        cast("str", authority["stable_inventory_sha256"]),
        cast("str", authority["structural_table_sha256"]),
        cast("str", authority["schema_sha256"]),
        cast("str", authority["transform_sha256"]),
        cast("str", decision["decision_sha256"]),
        cast("str", decision["purpose_evidence_sha256"]),
        semantic_sha256,
        *target_hashes,
        *cast("list[str]", decision["positive_witness_sha256s"]),
        *cast("list[str]", decision["negative_witness_sha256s"]),
        *cast("list[str]", decision["mutation_witness_sha256s"]),
    }
    for field in (
        "candidate_sha256",
        "candidate_structural_sha256",
        "candidate_implementation_sha256",
        "disposition_semantic_sha256",
    ):
        value = authority[field]
        if value is not None:
            inputs.add(cast("str", value))
    for field in (
        "key_groups",
        "functional_dependencies",
        "relationships",
        "lineage_edges",
        "dependency_cardinalities",
    ):
        for row in cast("list[dict[str, object]]", decision[field]):
            inputs.add(cast("str", row["evidence_sha256"]))
            expression = row.get("expression_sha256")
            if expression is not None:
                inputs.add(cast("str", expression))
    inputs.add(cast("str", cast("dict[str, object]", decision["row_policy"])["evidence_sha256"]))
    inputs.add(
        cast("str", cast("dict[str, object]", decision["temporal_policy"])["evidence_sha256"])
    )
    return sorted(inputs)


def _blocker(*, scope_id: str, code: str, evidence: Sequence[str]) -> dict[str, object]:
    return {
        "scope_id": scope_id,
        "code": code,
        "evidence_sha256s": sorted(set(evidence)),
    }


def _blocker_sort_key(value: Mapping[str, object]) -> tuple[object, ...]:
    return (
        value["scope_id"],
        value["code"],
        tuple(cast("list[str]", value["evidence_sha256s"])),
    )


def _derive_generation(
    authorities: list[dict[str, object]],
    decisions: list[dict[str, object]],
) -> dict[str, object]:
    authority_names = [cast("str", item["output_name"]) for item in authorities]
    decision_names = [cast("str", item["table_name"]) for item in decisions]
    if authority_names != sorted(authority_names) or len(authority_names) != len(
        set(authority_names)
    ):
        raise IndependentStarSemanticAuthoringError(
            "authority inputs must be sorted with unique table identities"
        )
    if decision_names != sorted(decision_names) or len(decision_names) != len(set(decision_names)):
        raise IndependentStarSemanticAuthoringError(
            "decision inputs must be sorted with unique table identities"
        )
    structural_generations = {
        cast("str", item["structural_inventory_sha256"]) for item in authorities
    }
    stable_generations = {cast("str", item["stable_inventory_sha256"]) for item in authorities}
    if len(structural_generations) > 1 or len(stable_generations) > 1:
        raise IndependentStarSemanticAuthoringError("mixed authority generations are forbidden")
    authority_inventory_sha = _sha256(
        {
            "schema_version": _SCHEMA_VERSION,
            "kind": _AUTHORITY_INPUT_KIND,
            "authorities": authorities,
        }
    )
    decision_inventory_sha = _sha256(
        {
            "schema_version": _SCHEMA_VERSION,
            "kind": _DECISION_INPUT_KIND,
            "decisions": decisions,
        }
    )
    authorities_by_name = {cast("str", item["output_name"]): item for item in authorities}
    decisions_by_name = {cast("str", item["table_name"]): item for item in decisions}
    blockers = [
        _blocker(
            scope_id="star_semantic_authoring",
            code="frozen_authority_completeness_unproven",
            evidence=(authority_inventory_sha,),
        )
    ]
    if not authorities:
        blockers.append(
            _blocker(
                scope_id="star_semantic_authoring",
                code="authority_inventory_empty",
                evidence=(authority_inventory_sha,),
            )
        )
    for decision in decisions:
        table_name = cast("str", decision["table_name"])
        if table_name not in authorities_by_name:
            blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="semantic_decision_without_authority",
                    evidence=(cast("str", decision["decision_sha256"]),),
                )
            )

    candidates: list[dict[str, object]] = []
    for authority in authorities:
        table_name = cast("str", authority["output_name"])
        authority_sha = cast("str", authority["authority_sha256"])
        decision = decisions_by_name.get(table_name)
        authority_blockers: list[dict[str, object]] = []
        if not authority["ordered_columns"]:
            authority_blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="authority_ordered_columns_empty",
                    evidence=(authority_sha, cast("str", authority["schema_sha256"])),
                )
            )
        if authority["candidate_sha256"] is None:
            authority_blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="authority_candidate_missing",
                    evidence=(authority_sha,),
                )
            )
        elif authority["candidate_implementation_status"] != "implemented":
            authority_blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="authority_candidate_implementation_missing",
                    evidence=(authority_sha, cast("str", authority["candidate_sha256"])),
                )
            )
        if authority["disposition_semantic_sha256"] is None:
            authority_blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="authority_disposition_missing",
                    evidence=(authority_sha,),
                )
            )
        elif authority["disposition_status"] != "stable":
            authority_blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="authority_not_stable",
                    evidence=(
                        authority_sha,
                        cast("str", authority["disposition_semantic_sha256"]),
                    ),
                )
            )
        if decision is None:
            blockers.extend(authority_blockers)
            blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="semantic_decision_missing",
                    evidence=(authority_sha,),
                )
            )
            continue
        table_blockers = authority_blockers
        decision_sha = cast("str", decision["decision_sha256"])
        if decision["authority_sha256"] != authority_sha:
            table_blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="semantic_decision_authority_mismatch",
                    evidence=(authority_sha, decision_sha),
                )
            )
        target_hashes: list[str] = []
        for relationship in cast("list[dict[str, object]]", decision["relationships"]):
            target = authorities_by_name.get(cast("str", relationship["target_table"]))
            if target is None or any(
                column not in cast("list[str]", target["ordered_columns"])
                for column in cast("list[str]", relationship["target_columns"])
            ):
                table_blockers.append(
                    _blocker(
                        scope_id=table_name,
                        code="semantic_relationship_target_invalid",
                        evidence=(
                            authority_sha,
                            decision_sha,
                            cast("str", relationship["evidence_sha256"]),
                        ),
                    )
                )
            else:
                target_hashes.append(cast("str", target["authority_sha256"]))
        if table_blockers:
            blockers.extend(table_blockers)
            continue
        try:
            semantic = _semantic_payload(authority, decision)
        except _SemanticDecisionError:
            blockers.append(
                _blocker(
                    scope_id=table_name,
                    code="semantic_decision_invalid",
                    evidence=(authority_sha, decision_sha),
                )
            )
            continue
        semantic_sha = _sha256(semantic)
        target_hashes = sorted(set(target_hashes))
        evidence_inputs = _evidence_inputs(
            authority_inventory_sha256=authority_inventory_sha,
            authority=authority,
            decision=decision,
            target_hashes=target_hashes,
            semantic_sha256=semantic_sha,
        )
        evidence_closure_sha = _sha256(
            {
                "schema_version": _SCHEMA_VERSION,
                "kind": _EVIDENCE_CLOSURE_KIND,
                "required_review_input_sha256s": evidence_inputs,
            }
        )
        candidate_content = {
            "schema_version": _SCHEMA_VERSION,
            "kind": _CANDIDATE_KIND,
            "authority_inventory_sha256": authority_inventory_sha,
            "authority": authority,
            "decision": decision,
            "relationship_target_authority_sha256s": target_hashes,
            "semantic_sha256": semantic_sha,
            "required_review_input_sha256s": evidence_inputs,
            "evidence_closure_sha256": evidence_closure_sha,
            "admitted": False,
            "model_green": False,
        }
        candidates.append({**candidate_content, "candidate_sha256": _sha256(candidate_content)})
    candidates.sort(
        key=lambda item: cast("str", cast("dict[str, object]", item["authority"])["output_name"])
    )
    unique_blockers = {
        (
            cast("str", item["scope_id"]),
            cast("str", item["code"]),
            tuple(cast("list[str]", item["evidence_sha256s"])),
        ): item
        for item in blockers
    }
    blockers = sorted(unique_blockers.values(), key=_blocker_sort_key)
    content = {
        "schema_version": _SCHEMA_VERSION,
        "kind": _GENERATION_KIND,
        "structural_inventory_sha256": (
            None if not authorities else authorities[0]["structural_inventory_sha256"]
        ),
        "stable_inventory_sha256": (
            None if not authorities else authorities[0]["stable_inventory_sha256"]
        ),
        "authority_inventory_sha256": authority_inventory_sha,
        "decision_inventory_sha256": decision_inventory_sha,
        "candidates": candidates,
        "blockers": blockers,
        "complete": False,
        "admitted": False,
        "model_green": False,
    }
    return {**content, "generation_sha256": _sha256(content)}


def _validate_observed_candidate(value: object) -> dict[str, object]:
    payload = _mapping(value, label="observed candidate")
    _exact_keys(
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
        label="observed candidate",
    )
    _schema(payload, kind=_CANDIDATE_KIND, label="observed candidate")
    for field in (
        "authority_inventory_sha256",
        "semantic_sha256",
        "evidence_closure_sha256",
        "candidate_sha256",
    ):
        _sha(payload[field], label=f"observed candidate {field}")
    _validate_authority(payload["authority"])
    _validate_decision(payload["decision"])
    _sha_array(
        payload["relationship_target_authority_sha256s"],
        label="observed target authority hashes",
        allow_empty=True,
    )
    _sha_array(
        payload["required_review_input_sha256s"],
        label="observed review inputs",
        allow_empty=False,
    )
    for field in ("admitted", "model_green"):
        if type(payload[field]) is not bool or payload[field]:
            raise IndependentStarSemanticAuthoringError(
                f"observed candidate {field} must be exact false"
            )
    content = {key: payload[key] for key in payload if key != "candidate_sha256"}
    if payload["candidate_sha256"] != _sha256(content):
        raise IndependentStarSemanticAuthoringError("observed candidate digest is invalid")
    return payload


def _validate_observed_blocker(value: object) -> dict[str, object]:
    payload = _mapping(value, label="observed blocker")
    _exact_keys(
        payload,
        expected=frozenset({"scope_id", "code", "evidence_sha256s"}),
        label="observed blocker",
    )
    _safe_id(payload["scope_id"], label="observed blocker scope")
    if type(payload["code"]) is not str or payload["code"] not in _BLOCKER_CODES:
        raise IndependentStarSemanticAuthoringError("observed blocker code is invalid")
    _sha_array(payload["evidence_sha256s"], label="observed blocker evidence", allow_empty=False)
    return payload


def _validate_observed_generation(payload: Mapping[str, object]) -> dict[str, object]:
    observed = _mapping(payload, label="observed generation")
    _exact_keys(
        observed,
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
        label="observed generation",
    )
    _schema(observed, kind=_GENERATION_KIND, label="observed generation")
    for field in ("structural_inventory_sha256", "stable_inventory_sha256"):
        if observed[field] is not None:
            _sha(observed[field], label=f"observed generation {field}")
    if (observed["structural_inventory_sha256"] is None) != (
        observed["stable_inventory_sha256"] is None
    ):
        raise IndependentStarSemanticAuthoringError(
            "observed generation parent identities do not co-occur"
        )
    for field in (
        "authority_inventory_sha256",
        "decision_inventory_sha256",
        "generation_sha256",
    ):
        _sha(observed[field], label=f"observed generation {field}")
    candidates = [
        _validate_observed_candidate(item)
        for item in _array(
            observed["candidates"],
            label="observed candidates",
            maximum=_MAX_AUTHORITIES,
        )
    ]
    candidate_names = [
        cast("str", cast("dict[str, object]", item["authority"])["output_name"])
        for item in candidates
    ]
    if candidate_names != sorted(candidate_names) or len(candidate_names) != len(
        set(candidate_names)
    ):
        raise IndependentStarSemanticAuthoringError(
            "observed candidates are not canonical unique rows"
        )
    blockers = [
        _validate_observed_blocker(item)
        for item in _array(
            observed["blockers"],
            label="observed blockers",
            maximum=_MAX_GENERATION_BLOCKERS,
        )
    ]
    if blockers != sorted(blockers, key=_blocker_sort_key):
        raise IndependentStarSemanticAuthoringError("observed blockers are not sorted")
    blocker_identities = {
        (
            item["scope_id"],
            item["code"],
            tuple(cast("list[str]", item["evidence_sha256s"])),
        )
        for item in blockers
    }
    if len(blocker_identities) != len(blockers):
        raise IndependentStarSemanticAuthoringError("observed blockers repeat")
    for field in ("complete", "admitted", "model_green"):
        if type(observed[field]) is not bool or observed[field]:
            raise IndependentStarSemanticAuthoringError(
                f"observed generation {field} must be exact false"
            )
    content = {key: observed[key] for key in observed if key != "generation_sha256"}
    if observed["generation_sha256"] != _sha256(content):
        raise IndependentStarSemanticAuthoringError("observed generation digest is invalid")
    return observed


@dataclass(frozen=True, slots=True)
class StarSemanticAuthoringIndependentProofV1:
    """Canonical source-relative equality proof for one candidate generation."""

    authority_inventory_sha256: str
    decision_inventory_sha256: str
    observed_generation_bytes_sha256: str
    generation_sha256: str
    candidate_count: int
    blocker_count: int
    verified: Literal[True]
    admitted: Literal[False]
    model_green: Literal[False]

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = _PROOF_KIND

    def __post_init__(self) -> None:
        for field, value in (
            ("authority_inventory_sha256", self.authority_inventory_sha256),
            ("decision_inventory_sha256", self.decision_inventory_sha256),
            ("observed_generation_bytes_sha256", self.observed_generation_bytes_sha256),
            ("generation_sha256", self.generation_sha256),
        ):
            _sha(value, label=f"proof {field}")
        for field, value in (
            ("candidate_count", self.candidate_count),
            ("blocker_count", self.blocker_count),
        ):
            if type(value) is not int or value < 0:
                raise IndependentStarSemanticAuthoringError(
                    f"proof {field} must be a nonnegative integer"
                )
        if type(self.verified) is not bool or not self.verified:
            raise IndependentStarSemanticAuthoringError("proof verified must be exact true")
        if type(self.admitted) is not bool or self.admitted:
            raise IndependentStarSemanticAuthoringError("proof admitted must be exact false")
        if type(self.model_green) is not bool or self.model_green:
            raise IndependentStarSemanticAuthoringError("proof model_green must be exact false")

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_inventory_sha256": self.authority_inventory_sha256,
            "decision_inventory_sha256": self.decision_inventory_sha256,
            "observed_generation_bytes_sha256": self.observed_generation_bytes_sha256,
            "generation_sha256": self.generation_sha256,
            "candidate_count": self.candidate_count,
            "blocker_count": self.blocker_count,
            "verified": self.verified,
            "admitted": self.admitted,
            "model_green": self.model_green,
        }

    @property
    def proof_sha256(self) -> str:
        return _sha256(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "proof_sha256": self.proof_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _mapping(value, label="independent authoring proof")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "authority_inventory_sha256",
                    "decision_inventory_sha256",
                    "observed_generation_bytes_sha256",
                    "generation_sha256",
                    "candidate_count",
                    "blocker_count",
                    "verified",
                    "admitted",
                    "model_green",
                    "proof_sha256",
                }
            ),
            label="independent authoring proof",
        )
        _schema(payload, kind=_PROOF_KIND, label="independent authoring proof")
        for field in ("candidate_count", "blocker_count"):
            if type(payload[field]) is not int:
                raise IndependentStarSemanticAuthoringError(f"proof {field} has an invalid type")
        for field in ("verified", "admitted", "model_green"):
            if type(payload[field]) is not bool:
                raise IndependentStarSemanticAuthoringError(f"proof {field} has an invalid type")
        proof = cls(
            authority_inventory_sha256=cast("str", payload["authority_inventory_sha256"]),
            decision_inventory_sha256=cast("str", payload["decision_inventory_sha256"]),
            observed_generation_bytes_sha256=cast(
                "str", payload["observed_generation_bytes_sha256"]
            ),
            generation_sha256=cast("str", payload["generation_sha256"]),
            candidate_count=cast("int", payload["candidate_count"]),
            blocker_count=cast("int", payload["blocker_count"]),
            verified=cast("Literal[True]", payload["verified"]),
            admitted=cast("Literal[False]", payload["admitted"]),
            model_green=cast("Literal[False]", payload["model_green"]),
        )
        if type(payload["proof_sha256"]) is not str or (
            payload["proof_sha256"] != proof.proof_sha256
        ):
            raise IndependentStarSemanticAuthoringError("independent proof digest is invalid")
        return proof

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_mapping(raw, label="independent authoring proof"))


def verify_star_semantic_authoring_generation_independently(
    *,
    authority_canonical_bytes: tuple[bytes, ...],
    decision_canonical_bytes: tuple[bytes, ...],
    observed_generation_canonical_bytes: bytes,
) -> StarSemanticAuthoringIndependentProofV1:
    """Independently derive and byte-compare one non-admitted generation."""

    if (
        type(authority_canonical_bytes) is not tuple
        or len(authority_canonical_bytes) > _MAX_AUTHORITIES
    ):
        raise IndependentStarSemanticAuthoringError(
            "authority bytes must be an exact bounded tuple"
        )
    if (
        type(decision_canonical_bytes) is not tuple
        or len(decision_canonical_bytes) > _MAX_DECISIONS
    ):
        raise IndependentStarSemanticAuthoringError("decision bytes must be an exact bounded tuple")
    authorities = [
        _validate_authority(_decode_canonical_mapping(raw, label=f"authority input {index}"))
        for index, raw in enumerate(authority_canonical_bytes)
    ]
    decisions = [
        _validate_decision(_decode_canonical_mapping(raw, label=f"decision input {index}"))
        for index, raw in enumerate(decision_canonical_bytes)
    ]
    if sum(len(cast("list[object]", item["relationships"])) for item in decisions) > (
        _MAX_TOTAL_RELATIONSHIPS
    ):
        raise IndependentStarSemanticAuthoringError(
            "decisions exceed the bounded aggregate relationship budget"
        )
    expected = _derive_generation(authorities, decisions)
    observed = _validate_observed_generation(
        _decode_canonical_mapping(
            observed_generation_canonical_bytes,
            label="observed authoring generation",
        )
    )
    if observed != expected:
        raise IndependentStarSemanticAuthoringError(
            "observed generation differs from independent reconstruction"
        )
    return StarSemanticAuthoringIndependentProofV1(
        authority_inventory_sha256=cast("str", expected["authority_inventory_sha256"]),
        decision_inventory_sha256=cast("str", expected["decision_inventory_sha256"]),
        observed_generation_bytes_sha256=hashlib.sha256(
            observed_generation_canonical_bytes
        ).hexdigest(),
        generation_sha256=cast("str", expected["generation_sha256"]),
        candidate_count=len(cast("list[object]", expected["candidates"])),
        blocker_count=len(cast("list[object]", expected["blockers"])),
        verified=True,
        admitted=False,
        model_green=False,
    )
