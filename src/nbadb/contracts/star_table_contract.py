"""Fail-closed compiled contracts for the public star-table universe.

The compiler in this module deliberately distinguishes structural facts from
reviewed semantic evidence.  Runtime schemas and transformers can prove the
ordered physical surface, but names, SQL text, and consumer hints do not prove
grain, keys, relationship timing, or row semantics.  Missing review evidence
therefore remains visible as a blocker instead of being promoted to a model
claim.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import sys
import textwrap
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from types import ModuleType


class StarTableContractCompilationError(RuntimeError):
    """The exact public-table contract inventory could not be proven."""


@dataclass(frozen=True, slots=True)
class StarFamilyCounts:
    """Exact public output counts by documented table family."""

    fact: int
    dim: int
    bridge: int
    agg: int
    analytics: int

    @property
    def total(self) -> int:
        return self.fact + self.dim + self.bridge + self.agg + self.analytics


@dataclass(frozen=True, slots=True)
class StarColumnContract:
    """One ordered Pandera output-column contract."""

    ordinal: int
    name: str
    data_type: str
    nullable: bool
    unique: bool
    required: bool
    source: str | None
    fk_ref: str | None
    metadata_json: str


@dataclass(frozen=True, slots=True)
class ForeignKeyContract:
    """A declared FK target plus the still-required relationship semantics."""

    column: str
    reference: str
    target_table: str
    target_column: str
    target_column_unique: bool
    current_or_as_of: str | None
    reviewed: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsumerMetadataContract:
    """Exact schema-owned consumer metadata, without inferred additions."""

    canonical_json: str
    sha256: str


@dataclass(frozen=True, slots=True)
class GrainContract:
    """A consumer grain label that never substitutes for reviewed columns."""

    label: str | None
    columns: tuple[str, ...]
    evidence_kind: str
    reviewed: bool


@dataclass(frozen=True, slots=True)
class KeyPolicyContract:
    """A reviewed key or an explicit fail-closed unreviewed bag state."""

    kind: str
    columns: tuple[str, ...]
    reviewed: bool
    evidence_kind: str


@dataclass(frozen=True, slots=True)
class SemanticPolicyContract:
    """One reviewed semantic policy or its explicit missing-evidence state."""

    name: str
    value: str | None
    evidence_kind: str
    reviewed: bool


@dataclass(frozen=True, slots=True)
class TransformContract:
    """Exact runtime transformer identity and normalized implementation hash."""

    class_name: str
    qualname: str
    runtime_module: str
    binding_module: str
    kind: str
    dependencies: tuple[str, ...]
    implementation_sha256: str


@dataclass(frozen=True, slots=True)
class StarTableContract:
    """Immutable structural and semantic evidence for one public output."""

    output_name: str
    family: str
    purpose: str | None
    schema_class: str
    schema_module: str
    columns: tuple[StarColumnContract, ...]
    schema_sha256: str
    foreign_keys: tuple[ForeignKeyContract, ...]
    transform: TransformContract
    consumer_metadata: ConsumerMetadataContract | None
    grain: GrainContract
    key_policy: KeyPolicyContract
    semantic_policies: tuple[SemanticPolicyContract, ...]
    blockers: tuple[str, ...]
    model_green: bool
    contract_sha256: str


@dataclass(frozen=True, slots=True)
class ModelBlockerSummary:
    """Stable aggregate of one blocker category across the inventory."""

    code: str
    table_count: int
    occurrence_count: int


@dataclass(frozen=True, slots=True)
class StarModelContractInventory:
    """The exact immutable public-table contract generation."""

    tables: tuple[StarTableContract, ...]
    family_counts: StarFamilyCounts
    blocker_summary: tuple[ModelBlockerSummary, ...]
    model_green: bool
    contract_sha256: str

    def table(self, output_name: str) -> StarTableContract:
        """Return one exact output contract or fail closed."""
        for contract in self.tables:
            if contract.output_name == output_name:
                return contract
        raise KeyError(output_name)


_FAMILY_PREFIXES: Final = (
    ("fact_", "fact"),
    ("dim_", "dim"),
    ("bridge_", "bridge"),
    ("agg_", "agg"),
    ("analytics_", "analytics"),
)
_SEMANTIC_POLICY_NAMES: Final = (
    "row",
    "filter",
    "dedup",
    "union",
    "aggregate",
    "temporal",
    "scd",
)


def _normalize_json_value(value: object, *, context: str) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise StarTableContractCompilationError(f"{context} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise StarTableContractCompilationError(
                    f"{context} contains a non-string mapping key"
                )
            normalized[key] = _normalize_json_value(
                item,
                context=f"{context}.{key}",
            )
        return normalized
    if isinstance(value, list | tuple):
        return [
            _normalize_json_value(item, context=f"{context}[{index}]")
            for index, item in enumerate(value)
        ]
    raise StarTableContractCompilationError(
        f"{context} contains unsupported value type {type(value).__name__}"
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_text(_canonical_json(value))


def _column_payload(column: StarColumnContract) -> dict[str, object]:
    return {
        "ordinal": column.ordinal,
        "name": column.name,
        "data_type": column.data_type,
        "nullable": column.nullable,
        "unique": column.unique,
        "required": column.required,
        "source": column.source,
        "fk_ref": column.fk_ref,
        "metadata": json.loads(column.metadata_json),
    }


def schema_contract_sha256(columns: Sequence[StarColumnContract]) -> str:
    """Return the order-sensitive digest for an ordered column sequence."""
    return _sha256_json([_column_payload(column) for column in columns])


def _family(output_name: str) -> str:
    for prefix, family in _FAMILY_PREFIXES:
        if output_name.startswith(prefix):
            return family
    raise StarTableContractCompilationError(
        f"public output has no recognized family prefix: {output_name}"
    )


def _family_counts(names: Sequence[str]) -> StarFamilyCounts:
    counts = Counter(_family(name) for name in names)
    return StarFamilyCounts(
        fact=counts["fact"],
        dim=counts["dim"],
        bridge=counts["bridge"],
        agg=counts["agg"],
        analytics=counts["analytics"],
    )


def _schema_backed_star_table_contract() -> tuple[tuple[str, ...], StarFamilyCounts]:
    """Return the deterministic schema-backed public-output universe."""
    from nbadb.orchestrate.transformers import expected_transform_output_tables

    names = tuple(sorted(expected_transform_output_tables(include_live=True)))
    return names, _family_counts(names)


_EXPECTED_STAR_TABLE_NAMES, EXPECTED_STAR_TABLE_COUNTS = _schema_backed_star_table_contract()
EXPECTED_STAR_TABLE_TOTAL: Final = len(_EXPECTED_STAR_TABLE_NAMES)


def _schema_columns(
    output_name: str,
    schema_cls: type[Any],
) -> tuple[StarColumnContract, ...]:
    try:
        schema = schema_cls.to_schema()
    except Exception as exc:
        raise StarTableContractCompilationError(
            f"cannot compile Pandera schema for {output_name}: {type(exc).__name__}: {exc}"
        ) from exc

    columns: list[StarColumnContract] = []
    for ordinal, (column_name, column) in enumerate(schema.columns.items()):
        if not isinstance(column_name, str) or not column_name:
            raise StarTableContractCompilationError(
                f"{output_name} has an invalid Pandera column name at ordinal {ordinal}"
            )
        metadata = dict(getattr(column, "metadata", {}) or {})
        normalized_metadata = _normalize_json_value(
            metadata,
            context=f"{output_name}.{column_name}.metadata",
        )
        source = metadata.get("source")
        if source is not None and (not isinstance(source, str) or not source):
            raise StarTableContractCompilationError(
                f"{output_name}.{column_name} has invalid source metadata"
            )
        fk_ref = metadata.get("fk_ref")
        if fk_ref is not None and (not isinstance(fk_ref, str) or not fk_ref):
            raise StarTableContractCompilationError(
                f"{output_name}.{column_name} has invalid fk_ref metadata"
            )
        data_type = str(getattr(column, "dtype", ""))
        if not data_type:
            raise StarTableContractCompilationError(
                f"{output_name}.{column_name} has no stable Pandera dtype"
            )
        columns.append(
            StarColumnContract(
                ordinal=ordinal,
                name=column_name,
                data_type=data_type,
                nullable=bool(getattr(column, "nullable", False)),
                unique=bool(getattr(column, "unique", False)),
                required=bool(getattr(column, "required", True)),
                source=source,
                fk_ref=fk_ref,
                metadata_json=_canonical_json(normalized_metadata),
            )
        )
    return tuple(columns)


def _direct_purpose(schema_cls: type[Any]) -> str | None:
    value = schema_cls.__dict__.get("__doc__")
    if value is None:
        return None
    if not isinstance(value, str):
        raise StarTableContractCompilationError(
            f"{schema_cls.__module__}.{schema_cls.__qualname__} has a non-string docstring"
        )
    normalized = inspect.cleandoc(value).strip()
    return normalized or None


def _consumer_metadata(
    output_name: str,
    schema_cls: type[Any],
) -> tuple[ConsumerMetadataContract | None, GrainContract]:
    from nbadb.schemas.consumer_metadata import infer_consumer_metadata

    raw = schema_cls.__dict__.get("__consumer_metadata__")
    explicit: Mapping[str, object] | None
    if raw is None:
        explicit = None
    elif isinstance(raw, Mapping):
        explicit = raw
    else:
        raise StarTableContractCompilationError(
            f"{output_name} has non-mapping __consumer_metadata__"
        )

    metadata_contract: ConsumerMetadataContract | None = None
    explicit_grain: object = None
    if explicit is not None:
        normalized = _normalize_json_value(
            explicit,
            context=f"{output_name}.__consumer_metadata__",
        )
        canonical = _canonical_json(normalized)
        metadata_contract = ConsumerMetadataContract(
            canonical_json=canonical,
            sha256=_sha256_text(canonical),
        )
        explicit_grain = explicit.get("grain")
        if explicit_grain is not None and (
            not isinstance(explicit_grain, str) or not explicit_grain
        ):
            raise StarTableContractCompilationError(
                f"{output_name} has invalid explicit consumer grain"
            )

    if isinstance(explicit_grain, str):
        grain = GrainContract(
            label=explicit_grain,
            columns=(),
            evidence_kind="explicit_consumer_metadata_unreviewed",
            reviewed=False,
        )
    else:
        inferred = infer_consumer_metadata(output_name, schema_doc="").get("grain")
        if inferred is not None and (not isinstance(inferred, str) or not inferred):
            raise StarTableContractCompilationError(
                f"{output_name} has invalid inferred consumer grain"
            )
        grain = GrainContract(
            label=inferred if isinstance(inferred, str) else None,
            columns=(),
            evidence_kind=("inferred_consumer_metadata_unreviewed" if inferred else "missing"),
            reviewed=False,
        )
    return metadata_contract, grain


def _normalized_python_ast(value: Any, *, context: str) -> str:
    try:
        source = inspect.getsource(value)
    except (OSError, TypeError) as exc:
        raise StarTableContractCompilationError(
            f"cannot inspect {context}: {type(exc).__name__}: {exc}"
        ) from exc
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError as exc:
        raise StarTableContractCompilationError(
            f"cannot parse {context}: {type(exc).__name__}: {exc}"
        ) from exc
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def _normalized_binding_ast(
    module: ModuleType,
    *,
    binding_name: str,
    output_name: str,
) -> str:
    try:
        source = inspect.getsource(module)
    except (OSError, TypeError) as exc:
        raise StarTableContractCompilationError(
            f"cannot inspect {output_name}.binding_module: {type(exc).__name__}: {exc}"
        ) from exc
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise StarTableContractCompilationError(
            f"cannot parse {output_name}.binding_module: {type(exc).__name__}: {exc}"
        ) from exc

    matches: list[ast.stmt] = []
    for node in tree.body:
        class_binding = isinstance(node, ast.ClassDef) and node.name == binding_name
        assignment_binding = isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == binding_name for target in node.targets
        )
        annotated_binding = (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == binding_name
        )
        if class_binding or assignment_binding or annotated_binding:
            matches.append(node)
    if len(matches) != 1:
        raise StarTableContractCompilationError(
            f"{output_name} has {len(matches)} normalized binding definitions; expected one"
        )
    return ast.dump(matches[0], annotate_fields=True, include_attributes=False)


def _normalized_sql(value: object, *, output_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StarTableContractCompilationError(
            f"SQL transformer {output_name} has no non-empty _SQL implementation"
        )
    normalized = textwrap.dedent(value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.strip().splitlines())


def _binding_module(transformer_cls: type[Any]) -> tuple[str, ModuleType]:
    matches: list[tuple[str, ModuleType]] = []
    for module_name, module in sorted(sys.modules.items()):
        if not module_name.startswith("nbadb.transform.") or module is None:
            continue
        if vars(module).get(transformer_cls.__name__) is transformer_cls:
            matches.append((module_name, module))
    if len(matches) != 1:
        modules = ", ".join(name for name, _ in matches) or "none"
        raise StarTableContractCompilationError(
            f"transformer {transformer_cls.__name__} has ambiguous binding modules: {modules}"
        )
    return matches[0]


def _runtime_class_constants(
    transformer_cls: type[Any],
    *,
    output_name: str,
) -> dict[str, object]:
    constants: dict[str, object] = {}
    for name, value in sorted(transformer_cls.__dict__.items()):
        if name.startswith("__") or name in {"_abc_impl", "_SQL"}:
            continue
        if inspect.isroutine(value) or isinstance(value, classmethod | staticmethod | property):
            continue
        constants[name] = _normalize_json_value(
            value,
            context=f"{output_name}.transform_class.{name}",
        )
    return constants


def _transform_contract(output_name: str, transformer: object) -> TransformContract:
    from nbadb.transform.base import SqlTransformer

    transformer_cls = type(transformer)
    class_name = transformer_cls.__name__
    if not class_name or not isinstance(class_name, str):
        raise StarTableContractCompilationError(
            f"{output_name} transformer has no stable class name"
        )
    binding_module, binding_module_object = _binding_module(transformer_cls)
    dependencies_value = getattr(transformer, "depends_on", None)
    if not isinstance(dependencies_value, list) or any(
        not isinstance(item, str) or not item for item in dependencies_value
    ):
        raise StarTableContractCompilationError(
            f"{output_name} transformer has invalid ordered dependencies"
        )
    dependencies = tuple(dependencies_value)
    if len(dependencies) != len(set(dependencies)):
        raise StarTableContractCompilationError(
            f"{output_name} transformer has duplicate ordered dependencies"
        )

    is_sql = isinstance(transformer, SqlTransformer)
    kind = "sql" if is_sql else "python"
    transform_method = getattr(transformer_cls, "transform", None)
    if not callable(transform_method):
        raise StarTableContractCompilationError(
            f"{output_name} transformer has no callable transform implementation"
        )
    implementation: dict[str, object] = {
        "class_name": class_name,
        "qualname": transformer_cls.__qualname__,
        "runtime_module": transformer_cls.__module__,
        "binding_module": binding_module,
        "kind": kind,
        "output_name": output_name,
        "dependencies": list(dependencies),
        "mro": [f"{member.__module__}.{member.__qualname__}" for member in transformer_cls.__mro__],
        "runtime_class_constants": _runtime_class_constants(
            transformer_cls,
            output_name=output_name,
        ),
        "binding_ast": _normalized_binding_ast(
            binding_module_object,
            binding_name=class_name,
            output_name=output_name,
        ),
        "effective_transform_ast": _normalized_python_ast(
            transform_method,
            context=f"{output_name}.transform",
        ),
    }
    if is_sql:
        implementation["normalized_sql"] = _normalized_sql(
            getattr(transformer, "_SQL", None),
            output_name=output_name,
        )
    else:
        implementation["class_ast"] = _normalized_python_ast(
            transformer_cls,
            context=f"{output_name}.transformer_class",
        )
    return TransformContract(
        class_name=class_name,
        qualname=transformer_cls.__qualname__,
        runtime_module=transformer_cls.__module__,
        binding_module=binding_module,
        kind=kind,
        dependencies=dependencies,
        implementation_sha256=_sha256_json(implementation),
    )


def _foreign_keys(
    output_name: str,
    columns: tuple[StarColumnContract, ...],
    columns_by_table: Mapping[str, tuple[StarColumnContract, ...]],
) -> tuple[ForeignKeyContract, ...]:
    target_columns = {
        table_name: {column.name: column for column in table_columns}
        for table_name, table_columns in columns_by_table.items()
    }
    contracts: list[ForeignKeyContract] = []
    for column in columns:
        if column.fk_ref is None:
            continue
        if column.fk_ref.count(".") != 1:
            raise StarTableContractCompilationError(
                f"{output_name}.{column.name} has malformed fk_ref {column.fk_ref!r}"
            )
        target_table, target_column = column.fk_ref.split(".")
        target = target_columns.get(target_table, {}).get(target_column)
        if target is None:
            raise StarTableContractCompilationError(
                f"{output_name}.{column.name} has unresolved fk_ref {column.fk_ref!r}"
            )
        contracts.append(
            ForeignKeyContract(
                column=column.name,
                reference=column.fk_ref,
                target_table=target_table,
                target_column=target_column,
                target_column_unique=target.unique,
                current_or_as_of=None,
                reviewed=False,
                blockers=("fk_relationship_semantics_unreviewed",),
            )
        )
    return tuple(contracts)


def _table_payload(
    *,
    output_name: str,
    family: str,
    purpose: str | None,
    schema_class: str,
    schema_module: str,
    columns: tuple[StarColumnContract, ...],
    schema_sha256: str,
    foreign_keys: tuple[ForeignKeyContract, ...],
    transform: TransformContract,
    consumer_metadata: ConsumerMetadataContract | None,
    grain: GrainContract,
    key_policy: KeyPolicyContract,
    semantic_policies: tuple[SemanticPolicyContract, ...],
    blockers: tuple[str, ...],
    model_green: bool,
) -> dict[str, object]:
    return {
        "output_name": output_name,
        "family": family,
        "purpose": purpose,
        "schema_class": schema_class,
        "schema_module": schema_module,
        "columns": [_column_payload(column) for column in columns],
        "schema_sha256": schema_sha256,
        "foreign_keys": [
            {
                "column": relation.column,
                "reference": relation.reference,
                "target_table": relation.target_table,
                "target_column": relation.target_column,
                "target_column_unique": relation.target_column_unique,
                "current_or_as_of": relation.current_or_as_of,
                "reviewed": relation.reviewed,
                "blockers": list(relation.blockers),
            }
            for relation in foreign_keys
        ],
        "transform": {
            "class_name": transform.class_name,
            "qualname": transform.qualname,
            "runtime_module": transform.runtime_module,
            "binding_module": transform.binding_module,
            "kind": transform.kind,
            "dependencies": list(transform.dependencies),
            "implementation_sha256": transform.implementation_sha256,
        },
        "consumer_metadata": (
            None
            if consumer_metadata is None
            else {
                "value": json.loads(consumer_metadata.canonical_json),
                "sha256": consumer_metadata.sha256,
            }
        ),
        "grain": {
            "label": grain.label,
            "columns": list(grain.columns),
            "evidence_kind": grain.evidence_kind,
            "reviewed": grain.reviewed,
        },
        "key_policy": {
            "kind": key_policy.kind,
            "columns": list(key_policy.columns),
            "reviewed": key_policy.reviewed,
            "evidence_kind": key_policy.evidence_kind,
        },
        "semantic_policies": [
            {
                "name": policy.name,
                "value": policy.value,
                "evidence_kind": policy.evidence_kind,
                "reviewed": policy.reviewed,
            }
            for policy in semantic_policies
        ],
        "blockers": list(blockers),
        "model_green": model_green,
    }


def _compile_table(
    *,
    output_name: str,
    schema_cls: type[Any],
    columns: tuple[StarColumnContract, ...],
    columns_by_table: Mapping[str, tuple[StarColumnContract, ...]],
    transformer: object,
) -> StarTableContract:
    purpose = _direct_purpose(schema_cls)
    consumer_metadata, grain = _consumer_metadata(output_name, schema_cls)
    foreign_keys = _foreign_keys(output_name, columns, columns_by_table)
    transform = _transform_contract(output_name, transformer)
    schema_sha256 = schema_contract_sha256(columns)

    key_policy = KeyPolicyContract(
        kind="unreviewed_bag",
        columns=(),
        reviewed=False,
        evidence_kind="no_explicit_reviewed_key_or_bag_policy",
    )
    semantic_policies = tuple(
        SemanticPolicyContract(
            name=name,
            value=None,
            evidence_kind="missing_explicit_reviewed_contract",
            reviewed=False,
        )
        for name in _SEMANTIC_POLICY_NAMES
    )

    blockers: list[str] = []
    if not columns:
        blockers.append("schema_empty")
    if purpose is None:
        blockers.append("purpose_missing")
    blockers.append("grain_columns_unreviewed")
    if grain.evidence_kind == "inferred_consumer_metadata_unreviewed":
        blockers.append("grain_inferred_unreviewed")
    elif grain.evidence_kind == "missing":
        blockers.append("grain_missing")
    else:
        blockers.append("grain_label_explicit_but_unreviewed")
    blockers.append("key_policy_unreviewed_bag")
    for column in columns:
        if column.source is None and column.fk_ref is None:
            blockers.append(f"column_source_missing:{column.name}")
        if column.fk_ref is None and (column.name == "id" or column.name.endswith(("_id", "_sk"))):
            blockers.append(f"identifier_relationship_disposition_unreviewed:{column.name}")
    blockers.extend(
        f"fk_relationship_semantics_unreviewed:{relation.column}" for relation in foreign_keys
    )
    blockers.extend(f"{policy.name}_semantics_unreviewed" for policy in semantic_policies)
    blockers_tuple = tuple(dict.fromkeys(blockers))
    model_green = not blockers_tuple
    payload = _table_payload(
        output_name=output_name,
        family=_family(output_name),
        purpose=purpose,
        schema_class=schema_cls.__name__,
        schema_module=schema_cls.__module__,
        columns=columns,
        schema_sha256=schema_sha256,
        foreign_keys=foreign_keys,
        transform=transform,
        consumer_metadata=consumer_metadata,
        grain=grain,
        key_policy=key_policy,
        semantic_policies=semantic_policies,
        blockers=blockers_tuple,
        model_green=model_green,
    )
    return StarTableContract(
        output_name=output_name,
        family=_family(output_name),
        purpose=purpose,
        schema_class=schema_cls.__name__,
        schema_module=schema_cls.__module__,
        columns=columns,
        schema_sha256=schema_sha256,
        foreign_keys=foreign_keys,
        transform=transform,
        consumer_metadata=consumer_metadata,
        grain=grain,
        key_policy=key_policy,
        semantic_policies=semantic_policies,
        blockers=blockers_tuple,
        model_green=model_green,
        contract_sha256=_sha256_json(payload),
    )


def _blocker_summary(
    tables: tuple[StarTableContract, ...],
) -> tuple[ModelBlockerSummary, ...]:
    occurrences: Counter[str] = Counter()
    table_counts: Counter[str] = Counter()
    for table in tables:
        table_codes: set[str] = set()
        for blocker in table.blockers:
            code = blocker.partition(":")[0]
            occurrences[code] += 1
            table_codes.add(code)
        table_counts.update(table_codes)
    return tuple(
        ModelBlockerSummary(
            code=code,
            table_count=table_counts[code],
            occurrence_count=occurrences[code],
        )
        for code in sorted(occurrences)
    )


def compile_star_table_contracts() -> StarModelContractInventory:
    """Compile the exact schema-backed runtime inventory or fail closed.

    Structural registry drift is an exception.  Missing reviewed semantic
    evidence is represented by immutable blockers and keeps ``model_green``
    false without dropping the affected table.
    """
    try:
        from nbadb.orchestrate.transformers import discover_all_transformers
        from nbadb.schemas.registry import _star_schema_registry

        schemas = _star_schema_registry()
        transformers = discover_all_transformers(include_live=True)
    except Exception as exc:
        if isinstance(exc, StarTableContractCompilationError):
            raise
        raise StarTableContractCompilationError(
            f"cannot load the runtime star-table universe: {type(exc).__name__}: {exc}"
        ) from exc

    schema_names = set(schemas)
    transformer_names = [getattr(transformer, "output_table", None) for transformer in transformers]
    if any(not isinstance(name, str) or not name for name in transformer_names):
        raise StarTableContractCompilationError(
            "runtime transformer discovery returned an invalid output name"
        )
    typed_transformer_names = [str(name) for name in transformer_names]
    duplicates = sorted(
        name for name, count in Counter(typed_transformer_names).items() if count > 1
    )
    transformers_by_name = dict(zip(typed_transformer_names, transformers, strict=True))
    missing = sorted(schema_names - set(transformers_by_name))
    extra = sorted(set(transformers_by_name) - schema_names)
    if duplicates or missing or extra:
        raise StarTableContractCompilationError(
            "star schema/transform universe mismatch: "
            f"duplicates={duplicates}; missing={missing}; extra={extra}"
        )

    ordered_names = tuple(sorted(schema_names))
    counts = _family_counts(ordered_names)
    if ordered_names != _EXPECTED_STAR_TABLE_NAMES or counts != EXPECTED_STAR_TABLE_COUNTS:
        raise StarTableContractCompilationError(
            "unexpected public star-table universe: "
            f"actual={ordered_names}; expected={_EXPECTED_STAR_TABLE_NAMES}; "
            f"counts={counts!r}; expected_counts={EXPECTED_STAR_TABLE_COUNTS!r}"
        )

    columns_by_table = {
        output_name: _schema_columns(output_name, schemas[output_name])
        for output_name in ordered_names
    }
    tables = tuple(
        _compile_table(
            output_name=output_name,
            schema_cls=schemas[output_name],
            columns=columns_by_table[output_name],
            columns_by_table=columns_by_table,
            transformer=transformers_by_name[output_name],
        )
        for output_name in ordered_names
    )
    if tuple(table.output_name for table in tables) != _EXPECTED_STAR_TABLE_NAMES:
        raise StarTableContractCompilationError(
            "compiled star contracts differ from the schema-backed output universe"
        )

    summary = _blocker_summary(tables)
    model_green = not summary and all(table.model_green for table in tables)
    inventory_payload = {
        "tables": [
            {"output_name": table.output_name, "contract_sha256": table.contract_sha256}
            for table in tables
        ],
        "family_counts": {
            "fact": counts.fact,
            "dim": counts.dim,
            "bridge": counts.bridge,
            "agg": counts.agg,
            "analytics": counts.analytics,
        },
        "blocker_summary": [
            {
                "code": blocker.code,
                "table_count": blocker.table_count,
                "occurrence_count": blocker.occurrence_count,
            }
            for blocker in summary
        ],
        "model_green": model_green,
    }
    return StarModelContractInventory(
        tables=tables,
        family_counts=counts,
        blocker_summary=summary,
        model_green=model_green,
        contract_sha256=_sha256_json(inventory_payload),
    )


__all__ = [
    "EXPECTED_STAR_TABLE_COUNTS",
    "EXPECTED_STAR_TABLE_TOTAL",
    "ConsumerMetadataContract",
    "ForeignKeyContract",
    "GrainContract",
    "KeyPolicyContract",
    "ModelBlockerSummary",
    "SemanticPolicyContract",
    "StarColumnContract",
    "StarFamilyCounts",
    "StarModelContractInventory",
    "StarTableContract",
    "StarTableContractCompilationError",
    "TransformContract",
    "compile_star_table_contracts",
    "schema_contract_sha256",
]
