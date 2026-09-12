"""Typed semantic authority for one schema-backed public star output.

The existing star-table compiler proves structural schemas and transform
identities.  This module captures the reviewed meanings that structure alone
cannot prove: grain, keys, relationships, lineage, temporal truth, row
semantics, coverage, and dependency cardinality.  It never infers those fields
from names, SQL text, or consumer hints.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from nbadb.contracts.review_evidence import ReviewReceiptV1

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "STAR_TABLE_SEMANTIC_CONTRACT_KIND",
    "STAR_TABLE_SEMANTIC_CONTRACT_SCHEMA_VERSION",
    "ColumnLineageEdgeV1",
    "DependencyCardinalityV1",
    "FunctionalDependencyV1",
    "KeyGroupV1",
    "RelationshipV1",
    "RowPolicyV1",
    "StarSemanticContractError",
    "StarTableSemanticContractV1",
    "TemporalPolicyV1",
]

STAR_TABLE_SEMANTIC_CONTRACT_SCHEMA_VERSION = 1
STAR_TABLE_SEMANTIC_CONTRACT_KIND = "nbadb_star_table_semantic_contract"

type TableFamily = Literal["dimension", "fact", "bridge", "aggregate", "analytics"]
type Stability = Literal["stable", "experimental", "withheld", "rejected"]
type PublicDisposition = Literal["published", "unpublished"]
type KeyMode = Literal["keyed", "reviewed_bag"]
type KeyKind = Literal["natural", "candidate", "surrogate"]
type NullKeyPolicy = Literal["forbidden", "allowed_distinct", "allowed_equal"]
type JoinCardinality = Literal["one_to_one", "many_to_one", "one_to_many", "many_to_many"]
type OrphanPolicy = Literal["reject", "allow", "typed_unavailable"]
type RelationshipTiming = Literal["current", "as_of", "event_time", "not_applicable"]
type LineageSourceKind = Literal[
    "provider_occurrence",
    "storage_occurrence",
    "star_column",
    "literal",
    "audit",
    "expression",
]
type LineageTransformKind = Literal[
    "copy",
    "rename",
    "cast",
    "expression",
    "aggregate",
    "window",
    "union",
]
type CardinalityEffect = Literal["row_preserving", "expanding", "reducing"]
type SourceMode = Literal["dependency_backed", "reviewed_source_free"]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_TABLE_FAMILIES = frozenset({"dimension", "fact", "bridge", "aggregate", "analytics"})
_STABILITIES = frozenset({"stable", "experimental", "withheld", "rejected"})
_PUBLIC_DISPOSITIONS = frozenset({"published", "unpublished"})
_KEY_MODES = frozenset({"keyed", "reviewed_bag"})
_KEY_KINDS = frozenset({"natural", "candidate", "surrogate"})
_NULL_KEY_POLICIES = frozenset({"forbidden", "allowed_distinct", "allowed_equal"})
_JOIN_CARDINALITIES = frozenset({"one_to_one", "many_to_one", "one_to_many", "many_to_many"})
_ORPHAN_POLICIES = frozenset({"reject", "allow", "typed_unavailable"})
_RELATIONSHIP_TIMINGS = frozenset({"current", "as_of", "event_time", "not_applicable"})
_LINEAGE_SOURCE_KINDS = frozenset(
    {
        "provider_occurrence",
        "storage_occurrence",
        "star_column",
        "literal",
        "audit",
        "expression",
    }
)
_LINEAGE_TRANSFORM_KINDS = frozenset(
    {"copy", "rename", "cast", "expression", "aggregate", "window", "union"}
)
_CARDINALITY_EFFECTS = frozenset({"row_preserving", "expanding", "reducing"})
_SOURCE_MODES = frozenset({"dependency_backed", "reviewed_source_free"})
_FAMILY_PREFIX = {
    "dimension": "dim_",
    "fact": "fact_",
    "bridge": "bridge_",
    "aggregate": "agg_",
    "analytics": "analytics_",
}


class StarSemanticContractError(ValueError):
    """A typed star-table semantic contract or its review binding is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StarSemanticContractError("star semantic contract is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise StarSemanticContractError(f"{field} must be a lowercase SHA-256")
    return value


def _require_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise StarSemanticContractError(f"{field} must be a safe nonempty identifier")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    if any(not isinstance(key, str) for key in payload):
        raise StarSemanticContractError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = ",".join(sorted(expected - actual))
    unexpected = ",".join(sorted(actual - expected))
    raise StarSemanticContractError(
        f"{label} fields differ (missing={missing}; unexpected={unexpected})"
    )


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise StarSemanticContractError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _ordered_ids(value: object, *, field: str, allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not list:
        raise StarSemanticContractError(f"{field} must be an array")
    values = tuple(_require_id(item, field=field) for item in cast("Sequence[object]", value))
    if (not values and not allow_empty) or len(set(values)) != len(values):
        raise StarSemanticContractError(f"{field} must be unique and ordered")
    return values


def _sorted_ids(value: object, *, field: str, allow_empty: bool = True) -> tuple[str, ...]:
    values = _ordered_ids(value, field=field, allow_empty=allow_empty)
    if values != tuple(sorted(values)):
        raise StarSemanticContractError(f"{field} must be sorted")
    return values


def _sorted_sha256s(value: object, *, field: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise StarSemanticContractError(f"{field} must be an array")
    values = tuple(_require_sha256(item, field=field) for item in cast("Sequence[object]", value))
    if not values or values != tuple(sorted(set(values))):
        raise StarSemanticContractError(f"{field} must be nonempty, sorted, and unique")
    return values


def _decode_canonical_bytes(raw: bytes) -> Mapping[str, object]:
    if not isinstance(raw, bytes) or not raw:
        raise StarSemanticContractError("star semantic contract bytes must be nonempty")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise StarSemanticContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise StarSemanticContractError(f"non-finite JSON constant: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarSemanticContractError("star semantic contract bytes are invalid JSON") from exc
    payload = _require_mapping(value, label="star semantic contract")
    if _canonical_bytes(payload) != raw:
        raise StarSemanticContractError("star semantic contract bytes are not canonical")
    return payload


def _require_columns_subset(
    values: tuple[str, ...],
    columns: frozenset[str],
    *,
    field: str,
) -> None:
    unknown = sorted(set(values) - columns)
    if unknown:
        raise StarSemanticContractError(f"{field} references unknown columns: {','.join(unknown)}")


@dataclass(frozen=True, slots=True, order=True)
class KeyGroupV1:
    key_id: str
    key_kind: KeyKind
    columns: tuple[str, ...]
    null_policy: NullKeyPolicy
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.key_id, field="key_id")
        if self.key_kind not in _KEY_KINDS:
            raise StarSemanticContractError("key_kind is invalid")
        if type(self.columns) is not tuple:
            raise StarSemanticContractError("key columns must be an exact tuple")
        if not self.columns or len(set(self.columns)) != len(self.columns):
            raise StarSemanticContractError("key columns must be nonempty, unique, and ordered")
        for column in self.columns:
            _require_id(column, field="key columns")
        if self.null_policy not in _NULL_KEY_POLICIES:
            raise StarSemanticContractError("key null_policy is invalid")
        _require_sha256(self.evidence_sha256, field="key evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "key_id": self.key_id,
            "key_kind": self.key_kind,
            "columns": list(self.columns),
            "null_policy": self.null_policy,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="key group")
        _require_exact_keys(
            payload,
            frozenset({"key_id", "key_kind", "columns", "null_policy", "evidence_sha256"}),
            label="key group",
        )
        return cls(
            key_id=cast("str", payload["key_id"]),
            key_kind=cast("KeyKind", payload["key_kind"]),
            columns=_ordered_ids(payload["columns"], field="key columns"),
            null_policy=cast("NullKeyPolicy", payload["null_policy"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True, order=True)
class FunctionalDependencyV1:
    dependency_id: str
    determinants: tuple[str, ...]
    dependents: tuple[str, ...]
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.dependency_id, field="functional dependency_id")
        for field, values in (
            ("functional determinants", self.determinants),
            ("functional dependents", self.dependents),
        ):
            if type(values) is not tuple:
                raise StarSemanticContractError(f"{field} must be an exact tuple")
            if not values or values != tuple(sorted(set(values))):
                raise StarSemanticContractError(f"{field} must be nonempty, sorted, and unique")
            for value in values:
                _require_id(value, field=field)
        if set(self.determinants) & set(self.dependents):
            raise StarSemanticContractError("functional dependency sides must be disjoint")
        _require_sha256(self.evidence_sha256, field="functional dependency evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "dependency_id": self.dependency_id,
            "determinants": list(self.determinants),
            "dependents": list(self.dependents),
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="functional dependency")
        _require_exact_keys(
            payload,
            frozenset({"dependency_id", "determinants", "dependents", "evidence_sha256"}),
            label="functional dependency",
        )
        return cls(
            dependency_id=cast("str", payload["dependency_id"]),
            determinants=_sorted_ids(
                payload["determinants"], field="functional determinants", allow_empty=False
            ),
            dependents=_sorted_ids(
                payload["dependents"], field="functional dependents", allow_empty=False
            ),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True, order=True)
class RelationshipV1:
    relationship_id: str
    local_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]
    cardinality: JoinCardinality
    orphan_policy: OrphanPolicy
    timing: RelationshipTiming
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.relationship_id, field="relationship_id")
        _require_id(self.target_table, field="relationship target_table")
        for field, values in (
            ("relationship local_columns", self.local_columns),
            ("relationship target_columns", self.target_columns),
        ):
            if type(values) is not tuple:
                raise StarSemanticContractError(f"{field} must be an exact tuple")
            if not values or len(set(values)) != len(values):
                raise StarSemanticContractError(f"{field} must be nonempty, unique, and ordered")
            for value in values:
                _require_id(value, field=field)
        if len(self.local_columns) != len(self.target_columns):
            raise StarSemanticContractError("relationship column arity differs")
        if self.cardinality not in _JOIN_CARDINALITIES:
            raise StarSemanticContractError("relationship cardinality is invalid")
        if self.orphan_policy not in _ORPHAN_POLICIES:
            raise StarSemanticContractError("relationship orphan_policy is invalid")
        if self.timing not in _RELATIONSHIP_TIMINGS:
            raise StarSemanticContractError("relationship timing is invalid")
        _require_sha256(self.evidence_sha256, field="relationship evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "relationship_id": self.relationship_id,
            "local_columns": list(self.local_columns),
            "target_table": self.target_table,
            "target_columns": list(self.target_columns),
            "cardinality": self.cardinality,
            "orphan_policy": self.orphan_policy,
            "timing": self.timing,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="relationship")
        _require_exact_keys(
            payload,
            frozenset(
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
        return cls(
            relationship_id=cast("str", payload["relationship_id"]),
            local_columns=_ordered_ids(
                payload["local_columns"], field="relationship local_columns"
            ),
            target_table=cast("str", payload["target_table"]),
            target_columns=_ordered_ids(
                payload["target_columns"], field="relationship target_columns"
            ),
            cardinality=cast("JoinCardinality", payload["cardinality"]),
            orphan_policy=cast("OrphanPolicy", payload["orphan_policy"]),
            timing=cast("RelationshipTiming", payload["timing"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True, order=True)
class ColumnLineageEdgeV1:
    edge_id: str
    target_column: str
    source_kind: LineageSourceKind
    source_ids: tuple[str, ...]
    source_dependency_ids: tuple[str, ...]
    transform_kind: LineageTransformKind
    expression_sha256: str | None
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.edge_id, field="lineage edge_id")
        _require_id(self.target_column, field="lineage target_column")
        if self.source_kind not in _LINEAGE_SOURCE_KINDS:
            raise StarSemanticContractError("lineage source_kind is invalid")
        if type(self.source_ids) is not tuple:
            raise StarSemanticContractError("lineage source_ids must be an exact tuple")
        if not self.source_ids or self.source_ids != tuple(sorted(set(self.source_ids))):
            raise StarSemanticContractError("lineage source_ids must be nonempty, sorted, unique")
        for source_id in self.source_ids:
            _require_id(source_id, field="lineage source_ids")
        if type(self.source_dependency_ids) is not tuple:
            raise StarSemanticContractError("lineage source_dependency_ids must be an exact tuple")
        if self.source_dependency_ids != tuple(sorted(set(self.source_dependency_ids))):
            raise StarSemanticContractError(
                "lineage source_dependency_ids must be sorted and unique"
            )
        for dependency_id in self.source_dependency_ids:
            _require_id(dependency_id, field="lineage source_dependency_ids")
        dependency_required = self.source_kind not in {"literal", "audit"}
        if dependency_required is not bool(self.source_dependency_ids):
            raise StarSemanticContractError(
                "lineage source dependency membership disagrees with source_kind"
            )
        if self.transform_kind not in _LINEAGE_TRANSFORM_KINDS:
            raise StarSemanticContractError("lineage transform_kind is invalid")
        if self.transform_kind in {"copy", "rename", "cast"} and len(self.source_ids) != 1:
            raise StarSemanticContractError(
                f"{self.transform_kind} lineage requires exactly one source"
            )
        if self.transform_kind == "union" and len(self.source_ids) < 2:
            raise StarSemanticContractError("union lineage requires at least two sources")
        expression_required = self.transform_kind in {
            "cast",
            "expression",
            "aggregate",
            "window",
            "union",
        }
        if expression_required:
            _require_sha256(self.expression_sha256, field="lineage expression_sha256")
        elif self.expression_sha256 is not None:
            raise StarSemanticContractError("copy or rename lineage cannot carry expression_sha256")
        _require_sha256(self.evidence_sha256, field="lineage evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "target_column": self.target_column,
            "source_kind": self.source_kind,
            "source_ids": list(self.source_ids),
            "source_dependency_ids": list(self.source_dependency_ids),
            "transform_kind": self.transform_kind,
            "expression_sha256": self.expression_sha256,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="column lineage edge")
        _require_exact_keys(
            payload,
            frozenset(
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
            label="column lineage edge",
        )
        expression_sha256 = payload["expression_sha256"]
        if expression_sha256 is not None and not isinstance(expression_sha256, str):
            raise StarSemanticContractError("lineage expression_sha256 must be null or a string")
        return cls(
            edge_id=cast("str", payload["edge_id"]),
            target_column=cast("str", payload["target_column"]),
            source_kind=cast("LineageSourceKind", payload["source_kind"]),
            source_ids=_sorted_ids(
                payload["source_ids"], field="lineage source_ids", allow_empty=False
            ),
            source_dependency_ids=_sorted_ids(
                payload["source_dependency_ids"],
                field="lineage source_dependency_ids",
                allow_empty=True,
            ),
            transform_kind=cast("LineageTransformKind", payload["transform_kind"]),
            expression_sha256=expression_sha256,
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class RowPolicyV1:
    row_mode: Literal["entity", "event", "snapshot", "aggregate", "bridge"]
    filter_policy: Literal["preserve", "reviewed_filter"]
    dedup_policy: Literal["none", "exact", "latest_by_key", "source_precedence"]
    union_policy: Literal["none", "multiset", "set", "source_precedence"]
    aggregation_policy: Literal["none", "grouped", "windowed"]
    additivity: Literal["not_applicable", "additive", "semi_additive", "non_additive"]
    evidence_sha256: str

    def __post_init__(self) -> None:
        if self.row_mode not in {"entity", "event", "snapshot", "aggregate", "bridge"}:
            raise StarSemanticContractError("row_mode is invalid")
        if self.filter_policy not in {"preserve", "reviewed_filter"}:
            raise StarSemanticContractError("filter_policy is invalid")
        if self.dedup_policy not in {"none", "exact", "latest_by_key", "source_precedence"}:
            raise StarSemanticContractError("dedup_policy is invalid")
        if self.union_policy not in {"none", "multiset", "set", "source_precedence"}:
            raise StarSemanticContractError("union_policy is invalid")
        if self.aggregation_policy not in {"none", "grouped", "windowed"}:
            raise StarSemanticContractError("aggregation_policy is invalid")
        if self.additivity not in {
            "not_applicable",
            "additive",
            "semi_additive",
            "non_additive",
        }:
            raise StarSemanticContractError("additivity is invalid")
        _require_sha256(self.evidence_sha256, field="row policy evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "row_mode": self.row_mode,
            "filter_policy": self.filter_policy,
            "dedup_policy": self.dedup_policy,
            "union_policy": self.union_policy,
            "aggregation_policy": self.aggregation_policy,
            "additivity": self.additivity,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="row policy")
        _require_exact_keys(
            payload,
            frozenset(
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
        return cls(
            row_mode=cast(
                "Literal['entity', 'event', 'snapshot', 'aggregate', 'bridge']", payload["row_mode"]
            ),
            filter_policy=cast("Literal['preserve', 'reviewed_filter']", payload["filter_policy"]),
            dedup_policy=cast(
                "Literal['none', 'exact', 'latest_by_key', 'source_precedence']",
                payload["dedup_policy"],
            ),
            union_policy=cast(
                "Literal['none', 'multiset', 'set', 'source_precedence']",
                payload["union_policy"],
            ),
            aggregation_policy=cast(
                "Literal['none', 'grouped', 'windowed']",
                payload["aggregation_policy"],
            ),
            additivity=cast(
                "Literal['not_applicable', 'additive', 'semi_additive', 'non_additive']",
                payload["additivity"],
            ),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class TemporalPolicyV1:
    event_columns: tuple[str, ...]
    observation_columns: tuple[str, ...]
    load_columns: tuple[str, ...]
    version_columns: tuple[str, ...]
    feature_cutoff_columns: tuple[str, ...]
    correction_policy: Literal["append_only", "replace_scope", "scd", "latest_truth"]
    truth_mode: Literal["event_truth", "as_observed", "current_truth", "bitemporal"]
    evidence_sha256: str

    def __post_init__(self) -> None:
        for field, values in (
            ("event_columns", self.event_columns),
            ("observation_columns", self.observation_columns),
            ("load_columns", self.load_columns),
            ("version_columns", self.version_columns),
            ("feature_cutoff_columns", self.feature_cutoff_columns),
        ):
            if type(values) is not tuple:
                raise StarSemanticContractError(f"temporal {field} must be an exact tuple")
            if values != tuple(sorted(set(values))):
                raise StarSemanticContractError(f"temporal {field} must be sorted and unique")
            for value in values:
                _require_id(value, field=f"temporal {field}")
        if self.correction_policy not in {"append_only", "replace_scope", "scd", "latest_truth"}:
            raise StarSemanticContractError("correction_policy is invalid")
        if self.truth_mode not in {"event_truth", "as_observed", "current_truth", "bitemporal"}:
            raise StarSemanticContractError("truth_mode is invalid")
        _require_sha256(self.evidence_sha256, field="temporal policy evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_columns": list(self.event_columns),
            "observation_columns": list(self.observation_columns),
            "load_columns": list(self.load_columns),
            "version_columns": list(self.version_columns),
            "feature_cutoff_columns": list(self.feature_cutoff_columns),
            "correction_policy": self.correction_policy,
            "truth_mode": self.truth_mode,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="temporal policy")
        _require_exact_keys(
            payload,
            frozenset(
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
        return cls(
            event_columns=_sorted_ids(payload["event_columns"], field="event_columns"),
            observation_columns=_sorted_ids(
                payload["observation_columns"], field="observation_columns"
            ),
            load_columns=_sorted_ids(payload["load_columns"], field="load_columns"),
            version_columns=_sorted_ids(payload["version_columns"], field="version_columns"),
            feature_cutoff_columns=_sorted_ids(
                payload["feature_cutoff_columns"], field="feature_cutoff_columns"
            ),
            correction_policy=cast(
                "Literal['append_only', 'replace_scope', 'scd', 'latest_truth']",
                payload["correction_policy"],
            ),
            truth_mode=cast(
                "Literal['event_truth', 'as_observed', 'current_truth', 'bitemporal']",
                payload["truth_mode"],
            ),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True, order=True)
class DependencyCardinalityV1:
    dependency_id: str
    effect: CardinalityEffect
    equation_code: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.dependency_id, field="dependency cardinality dependency_id")
        if self.effect not in _CARDINALITY_EFFECTS:
            raise StarSemanticContractError("dependency cardinality effect is invalid")
        _require_id(self.equation_code, field="dependency cardinality equation_code")
        _require_sha256(self.evidence_sha256, field="dependency cardinality evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "dependency_id": self.dependency_id,
            "effect": self.effect,
            "equation_code": self.equation_code,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="dependency cardinality")
        _require_exact_keys(
            payload,
            frozenset({"dependency_id", "effect", "equation_code", "evidence_sha256"}),
            label="dependency cardinality",
        )
        return cls(
            dependency_id=cast("str", payload["dependency_id"]),
            effect=cast("CardinalityEffect", payload["effect"]),
            equation_code=cast("str", payload["equation_code"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class StarTableSemanticContractV1:
    """One complete typed semantic decision for a structural public output."""

    table_name: str
    table_family: TableFamily
    structural_table_sha256: str
    schema_sha256: str
    transform_sha256: str
    stable_disposition_sha256: str
    stability: Stability
    public_disposition: PublicDisposition
    purpose_code: str
    purpose_evidence_sha256: str
    ordered_columns: tuple[str, ...]
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
    source_precedence: tuple[str, ...]
    row_policy: RowPolicyV1
    temporal_policy: TemporalPolicyV1
    scd_policy: Literal["not_applicable", "type1", "type2"]
    algorithm_id: str | None
    algorithm_version: str | None
    coverage_policy: Literal["complete_scope", "declared_partial", "snapshot"]
    incomplete_policy: Literal["reject", "typed_incomplete"]
    empty_policy: Literal["materialize_typed_empty", "reject_empty"]
    unavailable_policy: Literal["typed_unavailable", "contract_blocked", "not_applicable"]
    dependency_cardinalities: tuple[DependencyCardinalityV1, ...]
    positive_witness_sha256s: tuple[str, ...]
    negative_witness_sha256s: tuple[str, ...]
    mutation_witness_sha256s: tuple[str, ...]
    review_receipt_sha256: str

    schema_version: ClassVar[int] = STAR_TABLE_SEMANTIC_CONTRACT_SCHEMA_VERSION
    kind: ClassVar[str] = STAR_TABLE_SEMANTIC_CONTRACT_KIND

    def __post_init__(self) -> None:
        _require_id(self.table_name, field="table_name")
        if self.table_family not in _TABLE_FAMILIES:
            raise StarSemanticContractError("table_family is invalid")
        if not self.table_name.startswith(_FAMILY_PREFIX[self.table_family]):
            raise StarSemanticContractError("table_name and table_family disagree")
        for field, digest in (
            ("structural_table_sha256", self.structural_table_sha256),
            ("schema_sha256", self.schema_sha256),
            ("transform_sha256", self.transform_sha256),
            ("stable_disposition_sha256", self.stable_disposition_sha256),
            ("purpose_evidence_sha256", self.purpose_evidence_sha256),
            ("review_receipt_sha256", self.review_receipt_sha256),
        ):
            _require_sha256(digest, field=field)
        if self.stability not in _STABILITIES:
            raise StarSemanticContractError("stability is invalid")
        if self.public_disposition not in _PUBLIC_DISPOSITIONS:
            raise StarSemanticContractError("public_disposition is invalid")
        if self.stability == "stable" and self.public_disposition != "published":
            raise StarSemanticContractError("stable star table must be published")
        if self.stability in {"withheld", "rejected"} and self.public_disposition != "unpublished":
            raise StarSemanticContractError("withheld or rejected star table must be unpublished")
        _require_id(self.purpose_code, field="purpose_code")
        if type(self.row_policy) is not RowPolicyV1:
            raise StarSemanticContractError("row_policy must be an exact RowPolicyV1")
        if type(self.temporal_policy) is not TemporalPolicyV1:
            raise StarSemanticContractError("temporal_policy must be an exact TemporalPolicyV1")
        if type(self.ordered_columns) is not tuple:
            raise StarSemanticContractError("ordered_columns must be an exact tuple")
        if not self.ordered_columns or len(set(self.ordered_columns)) != len(self.ordered_columns):
            raise StarSemanticContractError("ordered_columns must be nonempty and unique")
        for column in self.ordered_columns:
            _require_id(column, field="ordered_columns")
        columns = frozenset(self.ordered_columns)
        for field, values, allow_empty in (
            ("grain_dimensions", self.grain_dimensions, False),
            ("observation_identity", self.observation_identity, False),
            ("competition_discriminators", self.competition_discriminators, True),
            ("request_discriminators", self.request_discriminators, True),
        ):
            if type(values) is not tuple:
                raise StarSemanticContractError(f"{field} must be an exact tuple")
            if (not values and not allow_empty) or len(set(values)) != len(values):
                raise StarSemanticContractError(f"{field} must be unique and ordered")
            for value in values:
                _require_id(value, field=field)
            _require_columns_subset(values, columns, field=field)
        expected_observation_identity = (
            set(self.grain_dimensions)
            | set(self.competition_discriminators)
            | set(self.request_discriminators)
        )
        if set(self.observation_identity) != expected_observation_identity:
            raise StarSemanticContractError(
                "observation_identity must exactly cover grain and discriminators"
            )
        if self.key_mode not in _KEY_MODES:
            raise StarSemanticContractError("key_mode is invalid")
        if type(self.key_groups) is not tuple or any(
            type(key_group) is not KeyGroupV1 for key_group in self.key_groups
        ):
            raise StarSemanticContractError("key_groups must be an exact typed tuple")
        if self.key_groups != tuple(sorted(self.key_groups)) or len(
            {item.key_id for item in self.key_groups}
        ) != len(self.key_groups):
            raise StarSemanticContractError("key_groups must be sorted with unique identities")
        if len({item.columns for item in self.key_groups}) != len(self.key_groups):
            raise StarSemanticContractError("key-group column sets must be semantically unique")
        if self.key_mode == "keyed" and not self.key_groups:
            raise StarSemanticContractError("keyed table requires at least one key group")
        if self.key_mode == "reviewed_bag" and self.key_groups:
            raise StarSemanticContractError("reviewed bag cannot carry key groups")
        for key_group in self.key_groups:
            _require_columns_subset(key_group.columns, columns, field="key group")
        semantic_key_groups = tuple(
            key_group for key_group in self.key_groups if key_group.key_kind != "surrogate"
        )
        observation_identity = set(self.observation_identity)
        if self.key_mode == "keyed" and not semantic_key_groups:
            raise StarSemanticContractError(
                "keyed table requires a natural or candidate semantic key"
            )
        if any(
            not set(key_group.columns).issubset(observation_identity)
            for key_group in semantic_key_groups
        ):
            raise StarSemanticContractError(
                "semantic key columns must be part of observation_identity"
            )
        for label, rows, row_type, identity in (
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
            if type(rows) is not tuple or any(type(row) is not row_type for row in rows):
                raise StarSemanticContractError(f"{label} must be an exact typed tuple")
            if rows != tuple(sorted(rows)) or len({getattr(row, identity) for row in rows}) != len(
                rows
            ):
                raise StarSemanticContractError(f"{label} must be sorted with unique identities")
        for dependency in self.functional_dependencies:
            _require_columns_subset(dependency.determinants, columns, field="functional dependency")
            _require_columns_subset(dependency.dependents, columns, field="functional dependency")
        for relationship in self.relationships:
            _require_columns_subset(relationship.local_columns, columns, field="relationship")
        relationship_semantic_ids = tuple(
            (
                relationship.local_columns,
                relationship.target_table,
                relationship.target_columns,
                relationship.timing,
            )
            for relationship in self.relationships
        )
        if len(set(relationship_semantic_ids)) != len(relationship_semantic_ids):
            raise StarSemanticContractError("relationship semantic identities must be unique")
        for edge in self.lineage_edges:
            _require_columns_subset((edge.target_column,), columns, field="lineage edge")
        lineage_targets = {edge.target_column for edge in self.lineage_edges}
        if len(lineage_targets) != len(self.lineage_edges):
            raise StarSemanticContractError(
                "lineage must contain exactly one edge per target column"
            )
        if lineage_targets != columns:
            missing = sorted(columns - lineage_targets)
            extra = sorted(lineage_targets - columns)
            raise StarSemanticContractError(
                f"lineage target coverage differs (missing={missing}; extra={extra})"
            )
        if self.source_mode not in _SOURCE_MODES:
            raise StarSemanticContractError("source_mode is invalid")
        if type(self.source_precedence) is not tuple:
            raise StarSemanticContractError("source_precedence must be an exact tuple")
        if self.source_precedence != tuple(dict.fromkeys(self.source_precedence)):
            raise StarSemanticContractError("source_precedence must be unique and ordered")
        for source in self.source_precedence:
            _require_id(source, field="source_precedence")
        lineage_dependency_ids = {
            dependency_id
            for edge in self.lineage_edges
            for dependency_id in edge.source_dependency_ids
        }
        if self.source_mode == "dependency_backed":
            if not self.source_precedence:
                raise StarSemanticContractError(
                    "dependency-backed semantics require nonempty source_precedence"
                )
            if lineage_dependency_ids != set(self.source_precedence):
                raise StarSemanticContractError(
                    "lineage dependencies must exactly cover source_precedence"
                )
        else:
            if self.source_precedence:
                raise StarSemanticContractError(
                    "reviewed source-free semantics require empty source_precedence"
                )
            if lineage_dependency_ids or any(
                edge.source_dependency_ids for edge in self.lineage_edges
            ):
                raise StarSemanticContractError(
                    "reviewed source-free lineage cannot carry dependency identities"
                )
            if any(edge.source_kind not in {"literal", "audit"} for edge in self.lineage_edges):
                raise StarSemanticContractError(
                    "reviewed source-free lineage must use only literal or audit sources"
                )
        temporal_columns = (
            *self.temporal_policy.event_columns,
            *self.temporal_policy.observation_columns,
            *self.temporal_policy.load_columns,
            *self.temporal_policy.version_columns,
            *self.temporal_policy.feature_cutoff_columns,
        )
        _require_columns_subset(temporal_columns, columns, field="temporal policy")
        if self.scd_policy not in {"not_applicable", "type1", "type2"}:
            raise StarSemanticContractError("scd_policy is invalid")
        if self.scd_policy == "type2":
            if self.temporal_policy.correction_policy != "scd":
                raise StarSemanticContractError("type2 SCD requires correction_policy=scd")
            if not self.temporal_policy.version_columns:
                raise StarSemanticContractError("type2 SCD requires version columns")
            if not set(self.temporal_policy.version_columns).issubset(observation_identity):
                raise StarSemanticContractError(
                    "type2 version columns must be part of observation_identity"
                )
        elif self.scd_policy == "type1":
            if self.temporal_policy.version_columns:
                raise StarSemanticContractError("type1 SCD cannot carry version columns")
            if self.temporal_policy.correction_policy not in {
                "replace_scope",
                "latest_truth",
            }:
                raise StarSemanticContractError(
                    "type1 SCD requires replacement or latest-truth correction"
                )
        elif self.temporal_policy.correction_policy == "scd":
            raise StarSemanticContractError("correction_policy=scd requires type2 SCD")
        if (
            self.temporal_policy.truth_mode == "event_truth"
            and not self.temporal_policy.event_columns
        ):
            raise StarSemanticContractError("event_truth requires event columns")
        if (
            self.temporal_policy.truth_mode == "as_observed"
            and not self.temporal_policy.observation_columns
        ):
            raise StarSemanticContractError("as_observed requires observation columns")
        if self.temporal_policy.truth_mode == "bitemporal" and (
            not self.temporal_policy.event_columns or not self.temporal_policy.observation_columns
        ):
            raise StarSemanticContractError(
                "bitemporal truth requires event and observation columns"
            )
        if (self.algorithm_id is None) != (self.algorithm_version is None):
            raise StarSemanticContractError("algorithm_id and algorithm_version must co-occur")
        if self.algorithm_id is not None:
            _require_id(self.algorithm_id, field="algorithm_id")
            _require_id(self.algorithm_version, field="algorithm_version")
        source_free_algorithm_derived = self.source_mode == "reviewed_source_free" and any(
            edge.source_kind == "audit"
            or edge.transform_kind in {"cast", "expression", "aggregate", "window", "union"}
            for edge in self.lineage_edges
        )
        if source_free_algorithm_derived and self.algorithm_id is None:
            raise StarSemanticContractError(
                "algorithm-derived source-free semantics require algorithm identity"
            )
        if self.coverage_policy not in {"complete_scope", "declared_partial", "snapshot"}:
            raise StarSemanticContractError("coverage_policy is invalid")
        if self.incomplete_policy not in {"reject", "typed_incomplete"}:
            raise StarSemanticContractError("incomplete_policy is invalid")
        if self.empty_policy not in {"materialize_typed_empty", "reject_empty"}:
            raise StarSemanticContractError("empty_policy is invalid")
        if self.unavailable_policy not in {
            "typed_unavailable",
            "contract_blocked",
            "not_applicable",
        }:
            raise StarSemanticContractError("unavailable_policy is invalid")
        if self.table_family == "aggregate" and (
            self.row_policy.row_mode != "aggregate" or self.row_policy.aggregation_policy == "none"
        ):
            raise StarSemanticContractError(
                "aggregate table requires aggregate row and aggregation semantics"
            )
        if self.table_family == "bridge" and self.row_policy.row_mode != "bridge":
            raise StarSemanticContractError("bridge table requires bridge row semantics")
        dependency_ids = tuple(item.dependency_id for item in self.dependency_cardinalities)
        if set(dependency_ids) != set(self.source_precedence):
            raise StarSemanticContractError(
                "dependency cardinalities must exactly cover source_precedence"
            )
        if self.source_mode == "reviewed_source_free" and self.dependency_cardinalities:
            raise StarSemanticContractError(
                "reviewed source-free semantics cannot carry dependency cardinalities"
            )
        for field, values in (
            ("positive_witness_sha256s", self.positive_witness_sha256s),
            ("negative_witness_sha256s", self.negative_witness_sha256s),
            ("mutation_witness_sha256s", self.mutation_witness_sha256s),
        ):
            if type(values) is not tuple:
                raise StarSemanticContractError(f"{field} must be an exact tuple")
            if not values or values != tuple(sorted(set(values))):
                raise StarSemanticContractError(f"{field} must be nonempty, sorted, and unique")
            for digest in values:
                _require_sha256(digest, field=field)

    def _semantic_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "table_name": self.table_name,
            "table_family": self.table_family,
            "structural_table_sha256": self.structural_table_sha256,
            "schema_sha256": self.schema_sha256,
            "transform_sha256": self.transform_sha256,
            "stable_disposition_sha256": self.stable_disposition_sha256,
            "stability": self.stability,
            "public_disposition": self.public_disposition,
            "purpose_code": self.purpose_code,
            "purpose_evidence_sha256": self.purpose_evidence_sha256,
            "ordered_columns": list(self.ordered_columns),
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
            "source_precedence": list(self.source_precedence),
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
    def semantic_sha256(self) -> str:
        return _sha256(self._semantic_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self._semantic_dict(),
            "semantic_sha256": self.semantic_sha256,
            "review_receipt_sha256": self.review_receipt_sha256,
        }

    def validate_review_receipt(self, receipt: ReviewReceiptV1) -> None:
        """Validate exact semantic, structural, and accepted-review binding."""

        if type(receipt) is not ReviewReceiptV1:
            raise StarSemanticContractError("review receipt has an invalid type")
        if receipt.receipt_sha256 != self.review_receipt_sha256:
            raise StarSemanticContractError("review receipt digest differs")
        if (
            receipt.subject_kind != "star_table_semantic_contract"
            or receipt.subject_semantic_sha256 != self.semantic_sha256
        ):
            raise StarSemanticContractError("review receipt is rebound to foreign semantics")
        required_inputs = {
            self.semantic_sha256,
            self.structural_table_sha256,
            self.schema_sha256,
            self.transform_sha256,
            self.stable_disposition_sha256,
        }
        if not required_inputs.issubset(receipt.accepted_input_sha256s):
            raise StarSemanticContractError("review receipt omits required structural inputs")
        if receipt.disposition != "accepted":
            raise StarSemanticContractError("star semantic review requires accepted disposition")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="star table semantic contract")
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "table_name",
                "table_family",
                "structural_table_sha256",
                "schema_sha256",
                "transform_sha256",
                "stable_disposition_sha256",
                "stability",
                "public_disposition",
                "purpose_code",
                "purpose_evidence_sha256",
                "ordered_columns",
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
                "source_precedence",
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
                "semantic_sha256",
                "review_receipt_sha256",
            }
        )
        _require_exact_keys(payload, expected, label="star table semantic contract")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise StarSemanticContractError("star table semantic contract identity is invalid")
        arrays = {
            name: payload[name]
            for name in (
                "key_groups",
                "functional_dependencies",
                "relationships",
                "lineage_edges",
                "dependency_cardinalities",
            )
        }
        if any(type(value) is not list for value in arrays.values()):
            raise StarSemanticContractError("star semantic nested inventories must be arrays")
        algorithm_id = payload["algorithm_id"]
        algorithm_version = payload["algorithm_version"]
        if algorithm_id is not None and not isinstance(algorithm_id, str):
            raise StarSemanticContractError("algorithm_id must be null or a string")
        if algorithm_version is not None and not isinstance(algorithm_version, str):
            raise StarSemanticContractError("algorithm_version must be null or a string")
        contract = cls(
            table_name=cast("str", payload["table_name"]),
            table_family=cast("TableFamily", payload["table_family"]),
            structural_table_sha256=cast("str", payload["structural_table_sha256"]),
            schema_sha256=cast("str", payload["schema_sha256"]),
            transform_sha256=cast("str", payload["transform_sha256"]),
            stable_disposition_sha256=cast("str", payload["stable_disposition_sha256"]),
            stability=cast("Stability", payload["stability"]),
            public_disposition=cast("PublicDisposition", payload["public_disposition"]),
            purpose_code=cast("str", payload["purpose_code"]),
            purpose_evidence_sha256=cast("str", payload["purpose_evidence_sha256"]),
            ordered_columns=_ordered_ids(payload["ordered_columns"], field="ordered_columns"),
            grain_dimensions=_ordered_ids(payload["grain_dimensions"], field="grain_dimensions"),
            observation_identity=_ordered_ids(
                payload["observation_identity"], field="observation_identity"
            ),
            key_mode=cast("KeyMode", payload["key_mode"]),
            key_groups=tuple(
                KeyGroupV1.from_dict(item) for item in cast("list[object]", arrays["key_groups"])
            ),
            functional_dependencies=tuple(
                FunctionalDependencyV1.from_dict(item)
                for item in cast("list[object]", arrays["functional_dependencies"])
            ),
            relationships=tuple(
                RelationshipV1.from_dict(item)
                for item in cast("list[object]", arrays["relationships"])
            ),
            lineage_edges=tuple(
                ColumnLineageEdgeV1.from_dict(item)
                for item in cast("list[object]", arrays["lineage_edges"])
            ),
            competition_discriminators=_ordered_ids(
                payload["competition_discriminators"],
                field="competition_discriminators",
                allow_empty=True,
            ),
            request_discriminators=_ordered_ids(
                payload["request_discriminators"],
                field="request_discriminators",
                allow_empty=True,
            ),
            source_mode=cast("SourceMode", payload["source_mode"]),
            source_precedence=_ordered_ids(
                payload["source_precedence"],
                field="source_precedence",
                allow_empty=True,
            ),
            row_policy=RowPolicyV1.from_dict(payload["row_policy"]),
            temporal_policy=TemporalPolicyV1.from_dict(payload["temporal_policy"]),
            scd_policy=cast("Literal['not_applicable', 'type1', 'type2']", payload["scd_policy"]),
            algorithm_id=algorithm_id,
            algorithm_version=algorithm_version,
            coverage_policy=cast(
                "Literal['complete_scope', 'declared_partial', 'snapshot']",
                payload["coverage_policy"],
            ),
            incomplete_policy=cast(
                "Literal['reject', 'typed_incomplete']", payload["incomplete_policy"]
            ),
            empty_policy=cast(
                "Literal['materialize_typed_empty', 'reject_empty']",
                payload["empty_policy"],
            ),
            unavailable_policy=cast(
                "Literal['typed_unavailable', 'contract_blocked', 'not_applicable']",
                payload["unavailable_policy"],
            ),
            dependency_cardinalities=tuple(
                DependencyCardinalityV1.from_dict(item)
                for item in cast("list[object]", arrays["dependency_cardinalities"])
            ),
            positive_witness_sha256s=_sorted_sha256s(
                payload["positive_witness_sha256s"], field="positive_witness_sha256s"
            ),
            negative_witness_sha256s=_sorted_sha256s(
                payload["negative_witness_sha256s"], field="negative_witness_sha256s"
            ),
            mutation_witness_sha256s=_sorted_sha256s(
                payload["mutation_witness_sha256s"], field="mutation_witness_sha256s"
            ),
            review_receipt_sha256=cast("str", payload["review_receipt_sha256"]),
        )
        if payload["semantic_sha256"] != contract.semantic_sha256:
            raise StarSemanticContractError("star semantic contract digest is invalid")
        return contract

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_bytes(raw))
