"""Finite structural registry for public numeric columns and metric candidates.

The registry proves two finite surfaces without inferring semantics:

* every numeric column in the schema-backed public transform universe; and
* every computed numeric SQL alias in the 33 aggregate/analytics transforms.

Numeric identifiers and calendar keys are not automatically measures.  Any
numeric column that is not an exact computed SQL alias therefore remains an
unclassified public numeric candidate until reviewed evidence says whether it
is a sourced measure or a nonsemantic key.  Every unreviewed semantic candidate
remains quarantined and blocks the stable model release gate.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

import sqlglot
from sqlglot import exp

from nbadb.contracts.star_table_contract import (
    StarColumnContract,
    StarModelContractInventory,
    StarTableContract,
    compile_star_table_contracts,
)
from nbadb.orchestrate.transformers import discover_all_transformers

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

MetricKind = Literal[
    "explicit_structural_nonmetric",
    "unreviewed_numeric_candidate",
]
ExpressionKind = Literal["computed_numeric_alias", "no_computed_expression_evidence"]
RegistryStatus = Literal[
    "blocked_pending_semantic_review",
    "blocked_pending_measure_classification",
    "explicit_nonsemantic_disposition",
]
ConsumerAdmission = Literal["quarantined"]

# Current-census regression evidence.  Compilation and validation bind to the
# live schema/transform registries rather than using these values as authority.
EXPECTED_PUBLIC_NUMERIC_COLUMN_COUNT = 4_651
EXPECTED_COMPUTED_NUMERIC_ALIAS_COUNT = 190
EXPECTED_EXPLICIT_STRUCTURAL_NONMETRIC_COUNT = 346
EXPECTED_AGGREGATE_ANALYTICS_TABLE_COUNT = 33


class MetricUseCaseContractCompilationError(RuntimeError):
    """The exact metric/use-case structural inventory could not be compiled."""


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _is_numeric(column: StarColumnContract) -> bool:
    return column.data_type in {"Float64", "Int64"}


def _is_typed_null_placeholder(expression: exp.Expression) -> bool:
    """Return whether an alias only fills a UNION branch with typed NULL."""

    current = expression
    while isinstance(current, (exp.Cast, exp.TryCast, exp.Paren)):
        current = current.this
    return isinstance(current, exp.Null)


def _iter_output_projection_aliases(parsed: exp.Expression) -> Iterator[exp.Alias]:
    """Yield only the aliases that define one table's exported output columns.

    The exported meaning of a transformer is its outermost projection: the
    final ``SELECT`` list, plus every arm of a top-level ``UNION``/``UNION
    ALL``.  Aliases inside CTE bodies and subqueries are internal plumbing --
    for example per-source fail-closed guards that legitimately reuse one
    column name with different error literals -- and never reach the output
    as separate meanings, so they are excluded from the ambiguity contract.
    """

    root = parsed
    while isinstance(root, exp.Paren):
        root = root.this
    projections: list[exp.Expression] = []
    if isinstance(root, exp.Union):
        for arm in root.find_all(exp.Select):
            if arm.parent is not None and not isinstance(arm.parent, (exp.Union, exp.Subquery)):
                continue
            projections.append(arm)
    elif isinstance(root, exp.Select):
        projections.append(root)
    for projection in projections:
        for item in projection.expressions:
            if isinstance(item, exp.Alias):
                yield item


@dataclass(frozen=True, slots=True)
class MetricSemanticField:
    """One required semantic field and its explicit review state."""

    name: str
    value: str | None
    reviewed: bool
    evidence: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "reviewed": self.reviewed,
            "evidence": self.evidence,
        }


_REQUIRED_SEMANTIC_FIELDS = (
    "formula",
    "inputs",
    "grain",
    "unit_scale",
    "weighting",
    "null_zero_policy",
    "aggregation",
    "eligibility",
    "tie_window_policy",
    "season_era_applicability",
    "reviewed_lineage",
    "evidence",
    "use_cases",
    "misuse_risks",
)


@dataclass(frozen=True, slots=True)
class PublicMetricContract:
    """One public numeric column bound to exact structural evidence."""

    metric_id: str
    ordinal: int
    table_name: str
    column_name: str
    column_ordinal: int
    data_type: str
    metric_kind: MetricKind
    expression_kind: ExpressionKind
    declared_source: str | None
    schema_sha256: str
    transform_sha256: str
    expression_sql: str | None
    expression_sha256: str
    semantic_fields: tuple[MetricSemanticField, ...]
    status: RegistryStatus
    consumer_admission: ConsumerAdmission
    blockers: tuple[str, ...]
    contract_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_fields", tuple(self.semantic_fields))
        object.__setattr__(self, "blockers", tuple(self.blockers))

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "ordinal": self.ordinal,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "column_ordinal": self.column_ordinal,
            "data_type": self.data_type,
            "metric_kind": self.metric_kind,
            "expression_kind": self.expression_kind,
            "declared_source": self.declared_source,
            "schema_sha256": self.schema_sha256,
            "transform_sha256": self.transform_sha256,
            "expression_sql": self.expression_sql,
            "expression_sha256": self.expression_sha256,
            "semantic_fields": [field.to_dict() for field in self.semantic_fields],
            "status": self.status,
            "consumer_admission": self.consumer_admission,
            "blockers": list(self.blockers),
            "contract_sha256": self.contract_sha256,
        }


@dataclass(frozen=True, slots=True)
class MetricUseCaseRegistry:
    """Exact numeric-column inventory with conservative consumer admission."""

    metrics: tuple[PublicMetricContract, ...]
    digest: str
    star_contract_sha256: str
    kind_counts: tuple[tuple[str, int], ...]
    expression_counts: tuple[tuple[str, int], ...]
    semantic_gap_counts: tuple[tuple[str, int], ...]
    blocker_counts: tuple[tuple[str, int], ...]
    _by_metric_id: Mapping[str, PublicMetricContract]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", tuple(self.metrics))
        object.__setattr__(self, "kind_counts", tuple(tuple(row) for row in self.kind_counts))
        object.__setattr__(
            self,
            "expression_counts",
            tuple(tuple(row) for row in self.expression_counts),
        )
        object.__setattr__(
            self,
            "blocker_counts",
            tuple(tuple(row) for row in self.blocker_counts),
        )
        object.__setattr__(
            self,
            "semantic_gap_counts",
            tuple(tuple(row) for row in self.semantic_gap_counts),
        )
        object.__setattr__(self, "_by_metric_id", MappingProxyType(dict(self._by_metric_id)))

    @property
    def by_metric_id(self) -> Mapping[str, PublicMetricContract]:
        return self._by_metric_id

    @property
    def model_green(self) -> bool:
        return self.release_gate_green and self.experimental_semantics_green

    @property
    def release_gate_green(self) -> bool:
        """Whether the stable structural metric registry has release blockers."""

        return not self.blocker_counts

    @property
    def experimental_semantics_green(self) -> bool:
        """Whether every quarantined semantic candidate has been reviewed."""

        return not self.semantic_gap_counts

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "nbadb_metric_use_case_registry",
            "digest": self.digest,
            "star_contract_sha256": self.star_contract_sha256,
            "model_green": self.model_green,
            "summary": {
                "numeric_column_count": len(self.metrics),
                "release_gate_green": self.release_gate_green,
                "experimental_semantics_green": self.experimental_semantics_green,
                "kind_counts": dict(self.kind_counts),
                "expression_counts": dict(self.expression_counts),
                "semantic_gap_counts": dict(self.semantic_gap_counts),
                "blocker_counts": dict(self.blocker_counts),
                "quarantined_count": sum(
                    metric.consumer_admission == "quarantined" for metric in self.metrics
                ),
            },
            "metrics": [metric.to_dict() for metric in self.metrics],
        }


def _computed_alias_expressions(
    star: StarModelContractInventory,
) -> Mapping[tuple[str, str], str]:
    """Return exact normalized SQL expressions for all computed numeric aliases."""

    tables = {
        table.output_name: table for table in star.tables if table.family in {"agg", "analytics"}
    }
    if len(tables) != star.family_counts.agg + star.family_counts.analytics:
        raise MetricUseCaseContractCompilationError("aggregate/analytics table universe drifted")
    transformers = {
        transformer.output_table: transformer
        for transformer in discover_all_transformers(include_live=True)
        if transformer.output_table in tables
    }
    if set(transformers) != set(tables):
        raise MetricUseCaseContractCompilationError(
            "aggregate/analytics transformer universe differs from star contracts"
        )

    computed: dict[tuple[str, str], str] = {}
    for table_name in sorted(tables):
        table = tables[table_name]
        transformer = transformers[table_name]
        sql = getattr(transformer, "_SQL", None)
        if not isinstance(sql, str) or not sql.strip():
            raise MetricUseCaseContractCompilationError(
                f"{table_name} has no exact SQL expression source"
            )
        try:
            parsed = sqlglot.parse_one(sql, read="duckdb")
        except Exception as exc:
            raise MetricUseCaseContractCompilationError(
                f"cannot parse {table_name} SQL: {type(exc).__name__}"
            ) from exc
        numeric_names = {column.name for column in table.columns if _is_numeric(column)}
        for alias in _iter_output_projection_aliases(parsed):
            alias_name = alias.alias
            if (
                alias_name not in numeric_names
                or isinstance(alias.this, exp.Column)
                or _is_typed_null_placeholder(alias.this)
            ):
                continue
            normalized = alias.this.sql(dialect="duckdb", pretty=False)
            identity = (table_name, alias_name)
            previous = computed.get(identity)
            if previous is not None and previous != normalized:
                raise MetricUseCaseContractCompilationError(
                    f"{table_name}.{alias_name} has ambiguous computed SQL expressions"
                )
            computed[identity] = normalized

    return MappingProxyType(computed)


def _semantic_fields(
    *,
    expression_sql: str | None,
) -> tuple[MetricSemanticField, ...]:
    fields: list[MetricSemanticField] = []
    for name in _REQUIRED_SEMANTIC_FIELDS:
        if name == "formula" and expression_sql is not None:
            fields.append(
                MetricSemanticField(
                    name=name,
                    value=expression_sql,
                    reviewed=True,
                    evidence="exact_normalized_duckdb_sql_expression",
                )
            )
        else:
            fields.append(
                MetricSemanticField(
                    name=name,
                    value=None,
                    reviewed=False,
                    evidence="missing_reviewed_metric_semantics",
                )
            )
    return tuple(fields)


def _expression_evidence(
    *,
    table_name: str,
    column_name: str,
    column_ordinal: int,
    declared_source: str | None,
    transform_sha256: str,
    expression_sql: str | None,
    metric_kind: MetricKind,
) -> dict[str, object]:
    if expression_sql is not None:
        evidence: dict[str, object] = {
            "kind": "exact_computed_numeric_alias",
            "dialect": "duckdb",
            "normalized_expression": expression_sql,
        }
    else:
        evidence = {
            "kind": "public_numeric_column",
            "declared_source": declared_source,
            "column_ordinal": column_ordinal,
            "metric_kind": metric_kind,
        }
    evidence.update(
        {
            "table_name": table_name,
            "column_name": column_name,
            "transform_sha256": transform_sha256,
        }
    )
    return evidence


def _expression_sha256(
    *,
    table: StarTableContract,
    column: StarColumnContract,
    expression_sql: str | None,
    metric_kind: MetricKind,
) -> str:
    return _canonical_sha256(
        _expression_evidence(
            table_name=table.output_name,
            column_name=column.name,
            column_ordinal=column.ordinal,
            declared_source=column.source,
            transform_sha256=table.transform.implementation_sha256,
            expression_sql=expression_sql,
            metric_kind=metric_kind,
        )
    )


def _bundle_digest_payload(
    *,
    star_contract_sha256: str,
    metrics: Sequence[PublicMetricContract],
    kind_counts: Sequence[tuple[str, int]],
    expression_counts: Sequence[tuple[str, int]],
    blocker_counts: Sequence[tuple[str, int]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nbadb_metric_use_case_registry",
        "star_contract_sha256": star_contract_sha256,
        "kind_counts": list(kind_counts),
        "expression_counts": list(expression_counts),
        "blocker_counts": list(blocker_counts),
        "metrics": [
            {"metric_id": metric.metric_id, "contract_sha256": metric.contract_sha256}
            for metric in metrics
        ],
    }


def _metric_payload(
    *,
    ordinal: int,
    table: StarTableContract,
    column: StarColumnContract,
    metric_kind: MetricKind,
    expression_kind: ExpressionKind,
    expression_sql: str | None,
    expression_sha256: str,
    semantic_fields: Sequence[MetricSemanticField],
    status: RegistryStatus,
    blockers: Sequence[str],
) -> dict[str, object]:
    return {
        "metric_id": f"{table.output_name}.{column.name}",
        "ordinal": ordinal,
        "table_name": table.output_name,
        "column_name": column.name,
        "column_ordinal": column.ordinal,
        "data_type": column.data_type,
        "metric_kind": metric_kind,
        "expression_kind": expression_kind,
        "declared_source": column.source,
        "schema_sha256": table.schema_sha256,
        "transform_sha256": table.transform.implementation_sha256,
        "expression_sql": expression_sql,
        "expression_sha256": expression_sha256,
        "semantic_fields": [field.to_dict() for field in semantic_fields],
        "status": status,
        "consumer_admission": "quarantined",
        "blockers": list(blockers),
    }


def _compile_metric_use_case_registry() -> MetricUseCaseRegistry:
    star = compile_star_table_contracts()
    computed_aliases = _computed_alias_expressions(star)
    metrics: list[PublicMetricContract] = []
    for table in star.tables:
        for column in table.columns:
            if not _is_numeric(column):
                continue
            ordinal = len(metrics)
            expression_sql = computed_aliases.get((table.output_name, column.name))
            structural_nonmetric = column.fk_ref is not None or column.unique
            if structural_nonmetric:
                metric_kind: MetricKind = "explicit_structural_nonmetric"
                status: RegistryStatus = "explicit_nonsemantic_disposition"
            else:
                metric_kind = "unreviewed_numeric_candidate"
                status = (
                    "blocked_pending_semantic_review"
                    if expression_sql is not None
                    else "blocked_pending_measure_classification"
                )
            expression_kind: ExpressionKind = (
                "computed_numeric_alias"
                if expression_sql is not None
                else "no_computed_expression_evidence"
            )
            semantic_fields = _semantic_fields(expression_sql=expression_sql)
            if structural_nonmetric:
                blockers = ("nonsemantic_numeric_column_excluded_from_metric_consumers",)
            else:
                blockers = tuple(
                    ["numeric_column_measure_classification_unreviewed"]
                    if expression_sql is None
                    else []
                ) + tuple(
                    f"metric_semantics_unreviewed:{field.name}"
                    for field in semantic_fields
                    if not field.reviewed
                )
            expression_sha256 = _expression_sha256(
                table=table,
                column=column,
                expression_sql=expression_sql,
                metric_kind=metric_kind,
            )
            payload = _metric_payload(
                ordinal=ordinal,
                table=table,
                column=column,
                metric_kind=metric_kind,
                expression_kind=expression_kind,
                expression_sql=expression_sql,
                expression_sha256=expression_sha256,
                semantic_fields=semantic_fields,
                status=status,
                blockers=blockers,
            )
            metrics.append(
                PublicMetricContract(
                    metric_id=f"{table.output_name}.{column.name}",
                    ordinal=ordinal,
                    table_name=table.output_name,
                    column_name=column.name,
                    column_ordinal=column.ordinal,
                    data_type=column.data_type,
                    metric_kind=metric_kind,
                    expression_kind=expression_kind,
                    declared_source=column.source,
                    schema_sha256=table.schema_sha256,
                    transform_sha256=table.transform.implementation_sha256,
                    expression_sql=expression_sql,
                    expression_sha256=expression_sha256,
                    semantic_fields=semantic_fields,
                    status=status,
                    consumer_admission="quarantined",
                    blockers=blockers,
                    contract_sha256=_canonical_sha256(payload),
                )
            )

    metric_tuple = tuple(metrics)
    kind_counts = tuple(sorted(Counter(metric.metric_kind for metric in metric_tuple).items()))
    expression_counts = tuple(
        sorted(Counter(metric.expression_kind for metric in metric_tuple).items())
    )
    semantic_gap_counts = tuple(
        sorted(
            Counter(
                code
                for metric in metric_tuple
                if metric.metric_kind != "explicit_structural_nonmetric"
                for code in metric.blockers
            ).items()
        )
    )
    # Compilation errors (missing tables, schemas, SQL, ambiguous expressions,
    # or binding drift) fail before a registry exists.  Remaining semantic
    # review gaps are also stable model blockers; quarantine alone is not a
    # reviewed metric or nonmetric disposition.
    blocker_counts = semantic_gap_counts
    digest_payload = _bundle_digest_payload(
        star_contract_sha256=star.contract_sha256,
        metrics=metric_tuple,
        kind_counts=kind_counts,
        expression_counts=expression_counts,
        blocker_counts=blocker_counts,
    )
    bundle = MetricUseCaseRegistry(
        metrics=metric_tuple,
        digest=_canonical_sha256(digest_payload),
        star_contract_sha256=star.contract_sha256,
        kind_counts=kind_counts,
        expression_counts=expression_counts,
        semantic_gap_counts=semantic_gap_counts,
        blocker_counts=blocker_counts,
        _by_metric_id=MappingProxyType({metric.metric_id: metric for metric in metric_tuple}),
    )
    _validate_registry(bundle, star=star, computed_aliases=computed_aliases)
    return bundle


def _validate_metric(metric: PublicMetricContract) -> None:
    if metric.metric_id != f"{metric.table_name}.{metric.column_name}":
        raise ValueError("metric registry identity is invalid")
    if not all(
        _is_sha256(value)
        for value in (
            metric.schema_sha256,
            metric.transform_sha256,
            metric.expression_sha256,
            metric.contract_sha256,
        )
    ):
        raise ValueError("metric registry contains an invalid digest")
    if tuple(field.name for field in metric.semantic_fields) != _REQUIRED_SEMANTIC_FIELDS:
        raise ValueError("metric registry semantic-field inventory is invalid")
    expected_expression_sha256 = _canonical_sha256(
        _expression_evidence(
            table_name=metric.table_name,
            column_name=metric.column_name,
            column_ordinal=metric.column_ordinal,
            declared_source=metric.declared_source,
            transform_sha256=metric.transform_sha256,
            expression_sql=metric.expression_sql,
            metric_kind=metric.metric_kind,
        )
    )
    if metric.expression_sha256 != expected_expression_sha256:
        raise ValueError("metric registry expression digest is invalid")

    if metric.metric_kind == "explicit_structural_nonmetric":
        if metric.status != "explicit_nonsemantic_disposition" or metric.blockers != (
            "nonsemantic_numeric_column_excluded_from_metric_consumers",
        ):
            raise ValueError("metric registry lost an explicit nonsemantic disposition")
        expected_blockers = metric.blockers
    elif metric.expression_kind == "computed_numeric_alias":
        formula = metric.semantic_fields[0]
        if (
            not metric.expression_sql
            or metric.status != "blocked_pending_semantic_review"
            or not formula.reviewed
            or formula.value != metric.expression_sql
            or any(field.reviewed for field in metric.semantic_fields[1:])
        ):
            raise ValueError("metric registry invented reviewed computed semantics")
        expected_blockers = tuple(
            f"metric_semantics_unreviewed:{field.name}" for field in metric.semantic_fields[1:]
        )
    else:
        if (
            metric.expression_sql is not None
            or metric.status != "blocked_pending_measure_classification"
            or any(field.reviewed for field in metric.semantic_fields)
        ):
            raise ValueError("metric registry invented numeric-column measure semantics")
        expected_blockers = (
            "numeric_column_measure_classification_unreviewed",
            *(f"metric_semantics_unreviewed:{field.name}" for field in metric.semantic_fields),
        )
    if metric.consumer_admission != "quarantined" or metric.blockers != expected_blockers:
        raise ValueError("metric registry invented consumer admission or blocker state")

    payload = {key: value for key, value in metric.to_dict().items() if key != "contract_sha256"}
    if metric.contract_sha256 != _canonical_sha256(payload):
        raise ValueError("metric registry metric contract digest is invalid")


def _validate_registry(
    registry: MetricUseCaseRegistry,
    *,
    star: StarModelContractInventory | None = None,
    computed_aliases: Mapping[tuple[str, str], str] | None = None,
) -> None:
    if tuple(metric.ordinal for metric in registry.metrics) != tuple(range(len(registry.metrics))):
        raise ValueError("metric registry ordinals are not exact and contiguous")
    if len({metric.metric_id for metric in registry.metrics}) != len(registry.metrics):
        raise ValueError("metric registry contains duplicate identities")
    for metric in registry.metrics:
        _validate_metric(metric)
    expected_kind_counts = tuple(
        sorted(Counter(metric.metric_kind for metric in registry.metrics).items())
    )
    if registry.kind_counts != expected_kind_counts:
        raise ValueError("metric registry kind counts are invalid")
    expected_expression_counts = tuple(
        sorted(Counter(metric.expression_kind for metric in registry.metrics).items())
    )
    if registry.expression_counts != expected_expression_counts:
        raise ValueError("metric registry expression counts are invalid")
    expected_semantic_gap_counts = tuple(
        sorted(
            Counter(
                code
                for metric in registry.metrics
                if metric.metric_kind != "explicit_structural_nonmetric"
                for code in metric.blockers
            ).items()
        )
    )
    if registry.semantic_gap_counts != expected_semantic_gap_counts:
        raise ValueError("metric registry semantic-gap counts are invalid")
    if registry.blocker_counts != expected_semantic_gap_counts:
        raise ValueError("metric registry blocker counts are invalid")
    if dict(registry.by_metric_id) != {metric.metric_id: metric for metric in registry.metrics}:
        raise ValueError("metric registry immutable index differs from its inventory")
    expected = _canonical_sha256(
        _bundle_digest_payload(
            star_contract_sha256=registry.star_contract_sha256,
            metrics=registry.metrics,
            kind_counts=registry.kind_counts,
            expression_counts=registry.expression_counts,
            blocker_counts=registry.blocker_counts,
        )
    )
    if registry.digest != expected:
        raise ValueError("metric registry digest is invalid")
    if star is None:
        return
    if registry.star_contract_sha256 != star.contract_sha256:
        raise ValueError("metric registry parent star digest is invalid")
    expected_columns = [
        (table, column) for table in star.tables for column in table.columns if _is_numeric(column)
    ]
    if len(expected_columns) != len(registry.metrics):
        raise ValueError("metric registry differs from the live numeric-column universe")
    exact_aliases = computed_aliases or _computed_alias_expressions(star)
    for metric, (table, column) in zip(registry.metrics, expected_columns, strict=True):
        expected_kind: MetricKind = (
            "explicit_structural_nonmetric"
            if column.fk_ref is not None or column.unique
            else "unreviewed_numeric_candidate"
        )
        expected_expression = exact_aliases.get((table.output_name, column.name))
        expected_binding = (
            f"{table.output_name}.{column.name}",
            table.output_name,
            column.name,
            column.ordinal,
            column.data_type,
            expected_kind,
            column.source,
            table.schema_sha256,
            table.transform.implementation_sha256,
            expected_expression,
        )
        actual_binding = (
            metric.metric_id,
            metric.table_name,
            metric.column_name,
            metric.column_ordinal,
            metric.data_type,
            metric.metric_kind,
            metric.declared_source,
            metric.schema_sha256,
            metric.transform_sha256,
            metric.expression_sql,
        )
        if actual_binding != expected_binding:
            raise ValueError(f"metric registry live binding drifted: {metric.metric_id}")


@lru_cache(maxsize=1)
def metric_use_case_registry() -> MetricUseCaseRegistry:
    """Return the exact finite public numeric-column registry."""

    return _compile_metric_use_case_registry()


def validate_metric_use_case_registry(registry: MetricUseCaseRegistry) -> None:
    """Validate structure, digest, and equality to the exact live public model."""

    star = compile_star_table_contracts()
    _validate_registry(
        registry,
        star=star,
        computed_aliases=_computed_alias_expressions(star),
    )
    if registry != metric_use_case_registry():
        raise ValueError("metric registry differs from the exact live sources")


__all__ = [
    "EXPECTED_AGGREGATE_ANALYTICS_TABLE_COUNT",
    "EXPECTED_COMPUTED_NUMERIC_ALIAS_COUNT",
    "EXPECTED_EXPLICIT_STRUCTURAL_NONMETRIC_COUNT",
    "EXPECTED_PUBLIC_NUMERIC_COLUMN_COUNT",
    "ExpressionKind",
    "MetricSemanticField",
    "MetricUseCaseContractCompilationError",
    "MetricUseCaseRegistry",
    "PublicMetricContract",
    "metric_use_case_registry",
    "validate_metric_use_case_registry",
]
