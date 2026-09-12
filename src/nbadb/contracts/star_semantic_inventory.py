"""Inventory-level authority and fail-closed join for public star semantics.

The structural star compiler and stable-model disposition inventory are the
parents of this contract.  Their exact table, schema, transform, candidate,
and disposition identities are projected into immutable per-table authority
rows before semantic authoring begins.  Missing authored contracts and review
receipts remain canonical blockers; they are never inferred from structure.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from nbadb.contracts.review_evidence import ReviewReceiptV1
from nbadb.contracts.stable_model_disposition import (
    StableModelDispositionInventoryV1,
)
from nbadb.contracts.star_semantic_contract import StarTableSemanticContractV1
from nbadb.contracts.star_table_contract import (
    ConsumerMetadataContract,
    ForeignKeyContract,
    GrainContract,
    KeyPolicyContract,
    ModelBlockerSummary,
    SemanticPolicyContract,
    StarColumnContract,
    StarFamilyCounts,
    StarModelContractInventory,
    StarTableContract,
    TransformContract,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "STAR_SEMANTIC_INVENTORY_KIND",
    "STAR_SEMANTIC_INVENTORY_SCHEMA_VERSION",
    "StarSemanticInventoryBlockerV1",
    "StarSemanticInventoryError",
    "StarSemanticInventoryV1",
    "StarTableSemanticAuthorityV1",
    "compile_star_semantic_inventory",
    "derive_star_semantic_authorities",
]

STAR_SEMANTIC_INVENTORY_SCHEMA_VERSION = 1
STAR_SEMANTIC_INVENTORY_KIND = "nbadb_star_semantic_inventory"

type SemanticTableFamily = Literal["dimension", "fact", "bridge", "aggregate", "analytics"]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_STRUCTURAL_TO_SEMANTIC_FAMILY: dict[str, SemanticTableFamily] = {
    "dim": "dimension",
    "fact": "fact",
    "bridge": "bridge",
    "agg": "aggregate",
    "analytics": "analytics",
}
_FAMILY_PREFIXES = (
    ("fact_", "fact", "fact"),
    ("dim_", "dim", "dimension"),
    ("bridge_", "bridge", "bridge"),
    ("agg_", "agg", "aggregate"),
    ("analytics_", "analytics", "analytics"),
)


class StarSemanticInventoryError(ValueError):
    """A structural authority, semantic join, or serialized inventory is invalid."""


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
        raise StarSemanticInventoryError("star semantic inventory is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise StarSemanticInventoryError(f"{field} must be a lowercase SHA-256")
    return value


def _require_optional_sha256(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_sha256(value, field=field)


def _require_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise StarSemanticInventoryError(f"{field} must be a safe nonempty identifier")
    return value


def _require_optional_id(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_id(value, field=field)


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise StarSemanticInventoryError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    if any(not isinstance(key, str) for key in payload):
        raise StarSemanticInventoryError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = ",".join(sorted(expected - actual))
    unexpected = ",".join(sorted(actual - expected))
    raise StarSemanticInventoryError(
        f"{label} fields differ (missing={missing}; unexpected={unexpected})"
    )


def _decode_canonical_bytes(raw: bytes) -> Mapping[str, object]:
    if not isinstance(raw, bytes) or not raw:
        raise StarSemanticInventoryError("star semantic inventory bytes must be nonempty")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise StarSemanticInventoryError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise StarSemanticInventoryError(f"non-finite JSON constant: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarSemanticInventoryError("star semantic inventory bytes are invalid JSON") from exc
    payload = _require_mapping(value, label="star semantic inventory")
    if _canonical_bytes(payload) != raw:
        raise StarSemanticInventoryError("star semantic inventory bytes are not canonical")
    return payload


def _decode_canonical_json_text(raw: object, *, field: str) -> object:
    if not isinstance(raw, str) or not raw:
        raise StarSemanticInventoryError(f"{field} must be nonempty canonical JSON")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StarSemanticInventoryError(f"{field} is invalid JSON") from exc
    if _canonical_bytes(decoded).decode("utf-8") != raw:
        raise StarSemanticInventoryError(f"{field} is not canonical JSON")
    return decoded


def _family_for_output(output_name: str) -> tuple[str, SemanticTableFamily]:
    for prefix, structural_family, semantic_family in _FAMILY_PREFIXES:
        if output_name.startswith(prefix):
            return structural_family, semantic_family
    raise StarSemanticInventoryError(
        f"public output has no recognized family prefix: {output_name}"
    )


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
        "metadata": _decode_canonical_json_text(
            column.metadata_json,
            field=f"column {column.name} metadata_json",
        ),
    }


def _validate_structural_table(table: StarTableContract) -> None:
    if type(table) is not StarTableContract:
        raise StarSemanticInventoryError("structural tables contain an invalid row")
    _require_id(table.output_name, field="structural output_name")
    expected_family, _semantic_family = _family_for_output(table.output_name)
    if table.family != expected_family:
        raise StarSemanticInventoryError(f"structural table family drifted: {table.output_name}")
    if table.purpose is not None and not isinstance(table.purpose, str):
        raise StarSemanticInventoryError("structural table purpose must be null or a string")
    _require_id(table.schema_class, field="structural schema_class")
    _require_id(table.schema_module, field="structural schema_module")
    if type(table.columns) is not tuple or any(
        type(column) is not StarColumnContract for column in table.columns
    ):
        raise StarSemanticInventoryError("structural columns must be an exact typed tuple")
    if tuple(column.ordinal for column in table.columns) != tuple(range(len(table.columns))):
        raise StarSemanticInventoryError(
            "structural column ordinals must be contiguous and ordered"
        )
    if len({column.name for column in table.columns}) != len(table.columns):
        raise StarSemanticInventoryError("structural column names must be unique")
    for column in table.columns:
        _require_id(column.name, field="structural column name")
        if not isinstance(column.data_type, str) or not column.data_type:
            raise StarSemanticInventoryError("structural column data_type must be nonempty")
        if any(
            type(value) is not bool for value in (column.nullable, column.unique, column.required)
        ):
            raise StarSemanticInventoryError("structural column flags must be exact booleans")
        if column.source is not None and (not isinstance(column.source, str) or not column.source):
            raise StarSemanticInventoryError(
                "structural column source must be null or a nonempty string"
            )
        if column.fk_ref is not None:
            _require_id(column.fk_ref, field="structural column fk_ref")
    _require_sha256(table.schema_sha256, field="structural schema_sha256")
    if table.schema_sha256 != _sha256([_column_payload(column) for column in table.columns]):
        raise StarSemanticInventoryError(f"structural schema digest drifted: {table.output_name}")
    if type(table.foreign_keys) is not tuple or any(
        type(item) is not ForeignKeyContract for item in table.foreign_keys
    ):
        raise StarSemanticInventoryError("structural foreign_keys must be an exact typed tuple")
    for relation in table.foreign_keys:
        for field, value in (
            ("foreign key column", relation.column),
            ("foreign key reference", relation.reference),
            ("foreign key target_table", relation.target_table),
            ("foreign key target_column", relation.target_column),
        ):
            _require_id(value, field=field)
        if type(relation.target_column_unique) is not bool or type(relation.reviewed) is not bool:
            raise StarSemanticInventoryError("structural foreign-key flags must be exact booleans")
        if relation.current_or_as_of is not None:
            _require_id(relation.current_or_as_of, field="foreign key current_or_as_of")
        if type(relation.blockers) is not tuple or any(
            not isinstance(item, str) or not item for item in relation.blockers
        ):
            raise StarSemanticInventoryError("structural foreign-key blockers are invalid")
    if type(table.transform) is not TransformContract:
        raise StarSemanticInventoryError("structural transform must be an exact TransformContract")
    transform = table.transform
    for field, value in (
        ("transform class_name", transform.class_name),
        ("transform qualname", transform.qualname),
        ("transform runtime_module", transform.runtime_module),
        ("transform binding_module", transform.binding_module),
        ("transform kind", transform.kind),
    ):
        _require_id(value, field=field)
    if type(transform.dependencies) is not tuple or len(set(transform.dependencies)) != len(
        transform.dependencies
    ):
        raise StarSemanticInventoryError(
            "transform dependencies must be an exact ordered unique tuple"
        )
    for dependency in transform.dependencies:
        _require_id(dependency, field="transform dependency")
    _require_sha256(transform.implementation_sha256, field="transform implementation_sha256")
    if table.consumer_metadata is not None:
        if type(table.consumer_metadata) is not ConsumerMetadataContract:
            raise StarSemanticInventoryError("consumer_metadata has an invalid type")
        consumer_value = _decode_canonical_json_text(
            table.consumer_metadata.canonical_json,
            field="consumer_metadata canonical_json",
        )
        if table.consumer_metadata.sha256 != _sha256(consumer_value):
            raise StarSemanticInventoryError("consumer_metadata digest drifted")
    if type(table.grain) is not GrainContract:
        raise StarSemanticInventoryError("structural grain has an invalid type")
    if type(table.key_policy) is not KeyPolicyContract:
        raise StarSemanticInventoryError("structural key policy has an invalid type")
    if type(table.semantic_policies) is not tuple or any(
        type(item) is not SemanticPolicyContract for item in table.semantic_policies
    ):
        raise StarSemanticInventoryError("structural semantic policies are invalid")
    if type(table.blockers) is not tuple or any(
        not isinstance(item, str) or not item for item in table.blockers
    ):
        raise StarSemanticInventoryError("structural blockers must be an exact string tuple")
    if len(set(table.blockers)) != len(table.blockers):
        raise StarSemanticInventoryError("structural blockers must be unique")
    if type(table.model_green) is not bool:
        raise StarSemanticInventoryError("structural table model_green must be an exact boolean")
    if table.model_green is not (not table.blockers):
        raise StarSemanticInventoryError("structural table gate differs from its blockers")
    _require_sha256(table.contract_sha256, field="structural table contract_sha256")
    if table.contract_sha256 != _sha256(_structural_table_payload(table)):
        raise StarSemanticInventoryError(f"structural table digest drifted: {table.output_name}")


def _structural_table_payload(table: StarTableContract) -> dict[str, object]:
    return {
        "output_name": table.output_name,
        "family": table.family,
        "purpose": table.purpose,
        "schema_class": table.schema_class,
        "schema_module": table.schema_module,
        "columns": [_column_payload(column) for column in table.columns],
        "schema_sha256": table.schema_sha256,
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
            for relation in table.foreign_keys
        ],
        "transform": {
            "class_name": table.transform.class_name,
            "qualname": table.transform.qualname,
            "runtime_module": table.transform.runtime_module,
            "binding_module": table.transform.binding_module,
            "kind": table.transform.kind,
            "dependencies": list(table.transform.dependencies),
            "implementation_sha256": table.transform.implementation_sha256,
        },
        "consumer_metadata": (
            None
            if table.consumer_metadata is None
            else {
                "value": _decode_canonical_json_text(
                    table.consumer_metadata.canonical_json,
                    field="consumer_metadata canonical_json",
                ),
                "sha256": table.consumer_metadata.sha256,
            }
        ),
        "grain": {
            "label": table.grain.label,
            "columns": list(table.grain.columns),
            "evidence_kind": table.grain.evidence_kind,
            "reviewed": table.grain.reviewed,
        },
        "key_policy": {
            "kind": table.key_policy.kind,
            "columns": list(table.key_policy.columns),
            "reviewed": table.key_policy.reviewed,
            "evidence_kind": table.key_policy.evidence_kind,
        },
        "semantic_policies": [
            {
                "name": policy.name,
                "value": policy.value,
                "evidence_kind": policy.evidence_kind,
                "reviewed": policy.reviewed,
            }
            for policy in table.semantic_policies
        ],
        "blockers": list(table.blockers),
        "model_green": table.model_green,
    }


def _structural_blocker_summary(
    tables: Sequence[StarTableContract],
) -> tuple[ModelBlockerSummary, ...]:
    occurrences: Counter[str] = Counter()
    table_counts: Counter[str] = Counter()
    for table in tables:
        codes: set[str] = set()
        for blocker in table.blockers:
            code = blocker.partition(":")[0]
            occurrences[code] += 1
            codes.add(code)
        table_counts.update(codes)
    return tuple(
        ModelBlockerSummary(
            code=code,
            table_count=table_counts[code],
            occurrence_count=occurrences[code],
        )
        for code in sorted(occurrences)
    )


def _validate_structural_inventory(inventory: StarModelContractInventory) -> None:
    if type(inventory) is not StarModelContractInventory:
        raise StarSemanticInventoryError(
            "structural inventory must be an exact StarModelContractInventory"
        )
    if type(inventory.tables) is not tuple or any(
        type(table) is not StarTableContract for table in inventory.tables
    ):
        raise StarSemanticInventoryError("structural tables must be an exact typed tuple")
    if not inventory.tables:
        raise StarSemanticInventoryError("structural table inventory must be nonempty")
    names = tuple(table.output_name for table in inventory.tables)
    if names != tuple(sorted(set(names))):
        raise StarSemanticInventoryError("structural tables must be sorted with unique names")
    for table in inventory.tables:
        _validate_structural_table(table)
    if type(inventory.family_counts) is not StarFamilyCounts:
        raise StarSemanticInventoryError("structural family_counts has an invalid type")
    counts = Counter(table.family for table in inventory.tables)
    expected_counts = StarFamilyCounts(
        fact=counts["fact"],
        dim=counts["dim"],
        bridge=counts["bridge"],
        agg=counts["agg"],
        analytics=counts["analytics"],
    )
    if inventory.family_counts != expected_counts:
        raise StarSemanticInventoryError("structural family counts drifted")
    if type(inventory.blocker_summary) is not tuple or any(
        type(item) is not ModelBlockerSummary for item in inventory.blocker_summary
    ):
        raise StarSemanticInventoryError("structural blocker_summary has an invalid type")
    expected_summary = _structural_blocker_summary(inventory.tables)
    if inventory.blocker_summary != expected_summary:
        raise StarSemanticInventoryError("structural blocker summary drifted")
    if type(inventory.model_green) is not bool:
        raise StarSemanticInventoryError("structural model_green must be an exact boolean")
    expected_green = not expected_summary and all(table.model_green for table in inventory.tables)
    if inventory.model_green is not expected_green:
        raise StarSemanticInventoryError("structural inventory gate drifted")
    _require_sha256(inventory.contract_sha256, field="structural inventory contract_sha256")
    payload = {
        "tables": [
            {"output_name": table.output_name, "contract_sha256": table.contract_sha256}
            for table in inventory.tables
        ],
        "family_counts": {
            "fact": expected_counts.fact,
            "dim": expected_counts.dim,
            "bridge": expected_counts.bridge,
            "agg": expected_counts.agg,
            "analytics": expected_counts.analytics,
        },
        "blocker_summary": [
            {
                "code": blocker.code,
                "table_count": blocker.table_count,
                "occurrence_count": blocker.occurrence_count,
            }
            for blocker in expected_summary
        ],
        "model_green": expected_green,
    }
    if inventory.contract_sha256 != _sha256(payload):
        raise StarSemanticInventoryError("structural inventory digest drifted")


@dataclass(frozen=True, slots=True, order=True)
class StarTableSemanticAuthorityV1:
    """Immutable structural and stable-disposition parent row for one table."""

    output_name: str
    table_family: SemanticTableFamily
    structural_inventory_sha256: str
    stable_inventory_sha256: str
    structural_table_sha256: str
    schema_sha256: str
    transform_sha256: str
    ordered_columns: tuple[str, ...]
    transformer_dependencies: tuple[str, ...]
    expected_candidate_id: str
    candidate_sha256: str | None
    candidate_kind: str | None
    candidate_gate_requirement: str | None
    candidate_structural_sha256: str | None
    candidate_implementation_status: str | None
    candidate_implementation_sha256: str | None
    disposition_semantic_sha256: str | None
    disposition_status: str | None

    def __post_init__(self) -> None:
        _require_id(self.output_name, field="authority output_name")
        _structural_family, expected_family = _family_for_output(self.output_name)
        if self.table_family != expected_family:
            raise StarSemanticInventoryError(
                f"semantic authority family drifted: {self.output_name}"
            )
        for field, digest in (
            ("structural_inventory_sha256", self.structural_inventory_sha256),
            ("stable_inventory_sha256", self.stable_inventory_sha256),
            ("structural_table_sha256", self.structural_table_sha256),
            ("schema_sha256", self.schema_sha256),
            ("transform_sha256", self.transform_sha256),
        ):
            _require_sha256(digest, field=field)
        for field, values, allow_empty in (
            ("ordered_columns", self.ordered_columns, True),
            ("transformer_dependencies", self.transformer_dependencies, True),
        ):
            if type(values) is not tuple or (not allow_empty and not values):
                raise StarSemanticInventoryError(f"{field} must be an exact tuple")
            if len(set(values)) != len(values):
                raise StarSemanticInventoryError(f"{field} must be unique and ordered")
            for value in values:
                _require_id(value, field=field)
        if self.expected_candidate_id != f"star:{self.output_name}":
            raise StarSemanticInventoryError("expected candidate identity drifted")
        candidate_identity_values = (
            self.candidate_sha256,
            self.candidate_kind,
            self.candidate_gate_requirement,
            self.candidate_structural_sha256,
            self.candidate_implementation_status,
        )
        if any(value is None for value in candidate_identity_values) and any(
            value is not None for value in candidate_identity_values
        ):
            raise StarSemanticInventoryError("candidate authority fields must co-occur")
        if self.candidate_sha256 is not None:
            _require_sha256(self.candidate_sha256, field="candidate_sha256")
            if self.candidate_kind not in {self.table_family, "live"}:
                raise StarSemanticInventoryError("candidate kind differs from table authority")
            if self.candidate_gate_requirement != "stable_required":
                raise StarSemanticInventoryError("public star candidate must be stable_required")
            _require_sha256(
                self.candidate_structural_sha256,
                field="candidate_structural_sha256",
            )
            if self.candidate_implementation_status == "implemented":
                _require_sha256(
                    self.candidate_implementation_sha256,
                    field="candidate_implementation_sha256",
                )
            elif (
                self.candidate_implementation_status == "missing"
                and self.candidate_implementation_sha256 is not None
            ):
                raise StarSemanticInventoryError(
                    "missing candidate cannot carry an implementation digest"
                )
            elif self.candidate_implementation_status not in {"implemented", "missing"}:
                raise StarSemanticInventoryError(
                    "public star candidate implementation status is invalid"
                )
        elif self.candidate_implementation_sha256 is not None:
            raise StarSemanticInventoryError(
                "candidate implementation digest requires a candidate authority"
            )
        disposition_values = (self.disposition_semantic_sha256, self.disposition_status)
        if (disposition_values[0] is None) != (disposition_values[1] is None):
            raise StarSemanticInventoryError("disposition authority fields must co-occur")
        if self.disposition_semantic_sha256 is not None:
            if self.candidate_sha256 is None:
                raise StarSemanticInventoryError("disposition authority requires a candidate")
            _require_sha256(
                self.disposition_semantic_sha256,
                field="disposition_semantic_sha256",
            )
            if self.disposition_status not in {"stable", "experimental", "withheld", "rejected"}:
                raise StarSemanticInventoryError("disposition status is invalid")

    def _content_dict(self) -> dict[str, object]:
        return {
            "output_name": self.output_name,
            "table_family": self.table_family,
            "structural_inventory_sha256": self.structural_inventory_sha256,
            "stable_inventory_sha256": self.stable_inventory_sha256,
            "structural_table_sha256": self.structural_table_sha256,
            "schema_sha256": self.schema_sha256,
            "transform_sha256": self.transform_sha256,
            "ordered_columns": list(self.ordered_columns),
            "transformer_dependencies": list(self.transformer_dependencies),
            "expected_candidate_id": self.expected_candidate_id,
            "candidate_sha256": self.candidate_sha256,
            "candidate_kind": self.candidate_kind,
            "candidate_gate_requirement": self.candidate_gate_requirement,
            "candidate_structural_sha256": self.candidate_structural_sha256,
            "candidate_implementation_status": self.candidate_implementation_status,
            "candidate_implementation_sha256": self.candidate_implementation_sha256,
            "disposition_semantic_sha256": self.disposition_semantic_sha256,
            "disposition_status": self.disposition_status,
        }

    @property
    def authority_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "authority_sha256": self.authority_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="star table semantic authority")
        _require_exact_keys(
            payload,
            frozenset(
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
            ),
            label="star table semantic authority",
        )
        ordered_columns = payload["ordered_columns"]
        dependencies = payload["transformer_dependencies"]
        if type(ordered_columns) is not list or type(dependencies) is not list:
            raise StarSemanticInventoryError("authority columns and dependencies must be arrays")
        authority = cls(
            output_name=cast("str", payload["output_name"]),
            table_family=cast("SemanticTableFamily", payload["table_family"]),
            structural_inventory_sha256=cast("str", payload["structural_inventory_sha256"]),
            stable_inventory_sha256=cast("str", payload["stable_inventory_sha256"]),
            structural_table_sha256=cast("str", payload["structural_table_sha256"]),
            schema_sha256=cast("str", payload["schema_sha256"]),
            transform_sha256=cast("str", payload["transform_sha256"]),
            ordered_columns=tuple(
                _require_id(item, field="ordered_columns") for item in ordered_columns
            ),
            transformer_dependencies=tuple(
                _require_id(item, field="transformer_dependencies") for item in dependencies
            ),
            expected_candidate_id=cast("str", payload["expected_candidate_id"]),
            candidate_sha256=_require_optional_sha256(
                payload["candidate_sha256"], field="candidate_sha256"
            ),
            candidate_kind=_require_optional_id(payload["candidate_kind"], field="candidate_kind"),
            candidate_gate_requirement=_require_optional_id(
                payload["candidate_gate_requirement"],
                field="candidate_gate_requirement",
            ),
            candidate_structural_sha256=_require_optional_sha256(
                payload["candidate_structural_sha256"],
                field="candidate_structural_sha256",
            ),
            candidate_implementation_status=_require_optional_id(
                payload["candidate_implementation_status"],
                field="candidate_implementation_status",
            ),
            candidate_implementation_sha256=_require_optional_sha256(
                payload["candidate_implementation_sha256"],
                field="candidate_implementation_sha256",
            ),
            disposition_semantic_sha256=_require_optional_sha256(
                payload["disposition_semantic_sha256"],
                field="disposition_semantic_sha256",
            ),
            disposition_status=_require_optional_id(
                payload["disposition_status"], field="disposition_status"
            ),
        )
        if payload["authority_sha256"] != authority.authority_sha256:
            raise StarSemanticInventoryError("star table authority digest is invalid")
        return authority


@dataclass(frozen=True, slots=True, order=True)
class StarSemanticInventoryBlockerV1:
    """One exact table-scoped or inventory-scoped release blocker."""

    scope_id: str
    code: str

    def __post_init__(self) -> None:
        _require_id(self.scope_id, field="blocker scope_id")
        _require_id(self.code, field="blocker code")

    def to_dict(self) -> dict[str, str]:
        return {"scope_id": self.scope_id, "code": self.code}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="star semantic inventory blocker")
        _require_exact_keys(
            payload,
            frozenset({"scope_id", "code"}),
            label="star semantic inventory blocker",
        )
        return cls(
            scope_id=cast("str", payload["scope_id"]),
            code=cast("str", payload["code"]),
        )


def derive_star_semantic_authorities(
    *,
    structural_inventory: StarModelContractInventory,
    stable_disposition_inventory: StableModelDispositionInventoryV1,
) -> tuple[StarTableSemanticAuthorityV1, ...]:
    """Derive the exact current structural/stable parent row for every public table."""

    _validate_structural_inventory(structural_inventory)
    if type(stable_disposition_inventory) is not StableModelDispositionInventoryV1:
        raise StarSemanticInventoryError(
            "stable inventory must be an exact StableModelDispositionInventoryV1"
        )
    if (
        StableModelDispositionInventoryV1.from_canonical_bytes(
            stable_disposition_inventory.canonical_bytes
        )
        != stable_disposition_inventory
    ):
        raise StarSemanticInventoryError("stable disposition inventory failed exact readback")

    candidates_by_id = {
        candidate.candidate_id: candidate for candidate in stable_disposition_inventory.candidates
    }
    dispositions_by_id = {
        disposition.candidate_id: disposition
        for disposition in stable_disposition_inventory.dispositions
    }
    authorities: list[StarTableSemanticAuthorityV1] = []
    for table in structural_inventory.tables:
        candidate_id = f"star:{table.output_name}"
        candidate = candidates_by_id.get(candidate_id)
        _structural_family, semantic_family = _family_for_output(table.output_name)
        if candidate is not None:
            expected_candidate_kind = (
                "live"
                if table.transform.binding_module.startswith("nbadb.transform.live.")
                else semantic_family
            )
            if candidate.candidate_kind != expected_candidate_kind:
                raise StarSemanticInventoryError(f"stable candidate kind drifted: {candidate_id}")
            if candidate.gate_requirement != "stable_required":
                raise StarSemanticInventoryError(
                    f"stable candidate gate requirement drifted: {candidate_id}"
                )
            expected_evidence = {
                structural_inventory.contract_sha256,
                table.contract_sha256,
                table.schema_sha256,
                table.transform.implementation_sha256,
            }
            if set(candidate.evidence_sha256s) != expected_evidence:
                raise StarSemanticInventoryError(
                    f"stable candidate evidence authority drifted: {candidate_id}"
                )
            structural_blocked = any(
                blocker == "schema_empty" or blocker.startswith("schema_")
                for blocker in table.blockers
            )
            if structural_blocked and candidate.implementation_status != "missing":
                raise StarSemanticInventoryError(
                    f"stable candidate structural blocker drifted: {candidate_id}"
                )
        disposition = dispositions_by_id.get(candidate_id)
        authorities.append(
            StarTableSemanticAuthorityV1(
                output_name=table.output_name,
                table_family=semantic_family,
                structural_inventory_sha256=structural_inventory.contract_sha256,
                stable_inventory_sha256=stable_disposition_inventory.inventory_sha256,
                structural_table_sha256=table.contract_sha256,
                schema_sha256=table.schema_sha256,
                transform_sha256=table.transform.implementation_sha256,
                ordered_columns=tuple(column.name for column in table.columns),
                transformer_dependencies=table.transform.dependencies,
                expected_candidate_id=candidate_id,
                candidate_sha256=(None if candidate is None else candidate.candidate_sha256),
                candidate_kind=(None if candidate is None else candidate.candidate_kind),
                candidate_gate_requirement=(
                    None if candidate is None else candidate.gate_requirement
                ),
                candidate_structural_sha256=(
                    None if candidate is None else candidate.structural_sha256
                ),
                candidate_implementation_status=(
                    None if candidate is None else candidate.implementation_status
                ),
                candidate_implementation_sha256=(
                    None if candidate is None else candidate.implementation_sha256
                ),
                disposition_semantic_sha256=(
                    None if disposition is None else disposition.semantic_sha256
                ),
                disposition_status=(None if disposition is None else disposition.disposition),
            )
        )
    return tuple(authorities)


def _validate_contract_against_authority(
    contract: StarTableSemanticContractV1,
    authority: StarTableSemanticAuthorityV1,
    *,
    authorities_by_name: Mapping[str, StarTableSemanticAuthorityV1],
) -> None:
    if contract.table_family != authority.table_family:
        raise StarSemanticInventoryError(f"semantic contract family drifted: {contract.table_name}")
    for field, actual, expected in (
        (
            "structural table",
            contract.structural_table_sha256,
            authority.structural_table_sha256,
        ),
        ("schema", contract.schema_sha256, authority.schema_sha256),
        ("transform", contract.transform_sha256, authority.transform_sha256),
    ):
        if actual != expected:
            raise StarSemanticInventoryError(
                f"semantic contract {field} parent drifted: {contract.table_name}"
            )
    if contract.ordered_columns != authority.ordered_columns:
        raise StarSemanticInventoryError(
            f"semantic contract ordered columns drifted: {contract.table_name}"
        )
    if contract.source_precedence != authority.transformer_dependencies:
        raise StarSemanticInventoryError(
            f"semantic contract source precedence drifted: {contract.table_name}"
        )
    if authority.disposition_semantic_sha256 is not None:
        if contract.stable_disposition_sha256 != authority.disposition_semantic_sha256:
            raise StarSemanticInventoryError(
                f"semantic contract disposition parent drifted: {contract.table_name}"
            )
        if contract.stability != authority.disposition_status:
            raise StarSemanticInventoryError(
                f"semantic contract stability drifted: {contract.table_name}"
            )
    for relationship in contract.relationships:
        target = authorities_by_name.get(relationship.target_table)
        if target is None:
            raise StarSemanticInventoryError(
                f"semantic relationship targets a foreign table: {contract.table_name}"
            )
        unknown = tuple(
            column for column in relationship.target_columns if column not in target.ordered_columns
        )
        if unknown:
            raise StarSemanticInventoryError(
                f"semantic relationship targets unknown columns: {contract.table_name}:"
                + ",".join(unknown)
            )


def _validate_review_binding(
    *,
    contract: StarTableSemanticContractV1,
    authority: StarTableSemanticAuthorityV1,
    receipt: ReviewReceiptV1,
) -> None:
    if receipt.receipt_sha256 != contract.review_receipt_sha256:
        raise StarSemanticInventoryError("semantic review receipt digest differs")
    if (
        receipt.subject_kind != "star_table_semantic_contract"
        or receipt.subject_semantic_sha256 != contract.semantic_sha256
    ):
        raise StarSemanticInventoryError(
            f"semantic review is rebound to foreign semantics: {contract.table_name}"
        )
    required_inputs = {
        contract.semantic_sha256,
        contract.structural_table_sha256,
        contract.schema_sha256,
        contract.transform_sha256,
        contract.stable_disposition_sha256,
        authority.authority_sha256,
        authority.structural_inventory_sha256,
        authority.stable_inventory_sha256,
    }
    if not required_inputs.issubset(receipt.accepted_input_sha256s):
        raise StarSemanticInventoryError(
            f"semantic review omits exact authority inputs: {contract.table_name}"
        )


def _validate_and_compute_join_blockers(
    *,
    structural_inventory_sha256: str,
    stable_inventory_sha256: str,
    stable_inventory_release_gate_green: bool,
    authorities: Sequence[StarTableSemanticAuthorityV1],
    semantic_contracts: Sequence[StarTableSemanticContractV1],
    review_receipts: Sequence[ReviewReceiptV1],
) -> tuple[StarSemanticInventoryBlockerV1, ...]:
    _require_sha256(structural_inventory_sha256, field="structural_inventory_sha256")
    _require_sha256(stable_inventory_sha256, field="stable_inventory_sha256")
    if type(stable_inventory_release_gate_green) is not bool:
        raise StarSemanticInventoryError(
            "stable_inventory_release_gate_green must be an exact boolean"
        )
    if not authorities:
        raise StarSemanticInventoryError("semantic authority inventory must be nonempty")
    if any(type(item) is not StarTableSemanticAuthorityV1 for item in authorities):
        raise StarSemanticInventoryError("semantic authorities contain an invalid row")
    if any(type(item) is not StarTableSemanticContractV1 for item in semantic_contracts):
        raise StarSemanticInventoryError("semantic contracts contain an invalid row")
    if any(type(item) is not ReviewReceiptV1 for item in review_receipts):
        raise StarSemanticInventoryError("semantic review receipts contain an invalid row")
    if len({item.output_name for item in authorities}) != len(authorities):
        raise StarSemanticInventoryError("semantic authority table names must be unique")
    if len({item.table_name for item in semantic_contracts}) != len(semantic_contracts):
        raise StarSemanticInventoryError("semantic contract table names must be unique")
    if len({item.receipt_sha256 for item in review_receipts}) != len(review_receipts):
        raise StarSemanticInventoryError("semantic review receipt identities must be unique")
    for authority in authorities:
        if (
            authority.structural_inventory_sha256 != structural_inventory_sha256
            or authority.stable_inventory_sha256 != stable_inventory_sha256
        ):
            raise StarSemanticInventoryError(
                f"semantic authority parent inventory drifted: {authority.output_name}"
            )

    authorities_by_name = {item.output_name: item for item in authorities}
    contracts_by_name = {item.table_name: item for item in semantic_contracts}
    foreign_contracts = sorted(set(contracts_by_name) - set(authorities_by_name))
    if foreign_contracts:
        raise StarSemanticInventoryError(
            "semantic contracts reference foreign tables: " + ",".join(foreign_contracts)
        )
    referenced_review_digests = {contract.review_receipt_sha256 for contract in semantic_contracts}
    extra_reviews = sorted(
        {receipt.receipt_sha256 for receipt in review_receipts} - referenced_review_digests
    )
    if extra_reviews:
        raise StarSemanticInventoryError("semantic review inventory contains a foreign receipt")
    reviews_by_digest = {item.receipt_sha256: item for item in review_receipts}

    blockers: list[StarSemanticInventoryBlockerV1] = []
    if not stable_inventory_release_gate_green:
        blockers.append(
            StarSemanticInventoryBlockerV1(
                scope_id="inventory",
                code="stable_disposition_inventory_not_green",
            )
        )
    for authority in sorted(authorities):
        if authority.candidate_sha256 is None:
            blockers.append(
                StarSemanticInventoryBlockerV1(
                    scope_id=authority.output_name,
                    code="stable_candidate_missing",
                )
            )
        if authority.disposition_semantic_sha256 is None:
            blockers.append(
                StarSemanticInventoryBlockerV1(
                    scope_id=authority.output_name,
                    code="stable_disposition_missing",
                )
            )
        elif authority.disposition_status != "stable":
            blockers.append(
                StarSemanticInventoryBlockerV1(
                    scope_id=authority.output_name,
                    code="registered_public_table_not_stable",
                )
            )
        contract = contracts_by_name.get(authority.output_name)
        if contract is None:
            blockers.extend(
                (
                    StarSemanticInventoryBlockerV1(
                        scope_id=authority.output_name,
                        code="semantic_contract_missing",
                    ),
                    StarSemanticInventoryBlockerV1(
                        scope_id=authority.output_name,
                        code="semantic_review_missing",
                    ),
                )
            )
            continue
        _validate_contract_against_authority(
            contract,
            authority,
            authorities_by_name=authorities_by_name,
        )
        if contract.stability != "stable" or contract.public_disposition != "published":
            blockers.append(
                StarSemanticInventoryBlockerV1(
                    scope_id=authority.output_name,
                    code="semantic_contract_not_stable_published",
                )
            )
        receipt = reviews_by_digest.get(contract.review_receipt_sha256)
        if receipt is None:
            blockers.append(
                StarSemanticInventoryBlockerV1(
                    scope_id=authority.output_name,
                    code="semantic_review_missing",
                )
            )
            continue
        _validate_review_binding(contract=contract, authority=authority, receipt=receipt)
        if receipt.disposition != "accepted":
            blockers.append(
                StarSemanticInventoryBlockerV1(
                    scope_id=authority.output_name,
                    code="semantic_review_changes_required",
                )
            )
    return tuple(sorted(set(blockers)))


@dataclass(frozen=True, slots=True)
class StarSemanticInventoryV1:
    """Exact public-table semantic authority, authored contracts, and review join."""

    structural_inventory_sha256: str
    stable_inventory_sha256: str
    stable_inventory_release_gate_green: bool
    authorities: tuple[StarTableSemanticAuthorityV1, ...]
    semantic_contracts: tuple[StarTableSemanticContractV1, ...]
    review_receipts: tuple[ReviewReceiptV1, ...]
    blockers: tuple[StarSemanticInventoryBlockerV1, ...]
    model_green: bool

    schema_version: ClassVar[int] = STAR_SEMANTIC_INVENTORY_SCHEMA_VERSION
    kind: ClassVar[str] = STAR_SEMANTIC_INVENTORY_KIND

    def __post_init__(self) -> None:
        for label, rows, row_type, identity in (
            (
                "authorities",
                self.authorities,
                StarTableSemanticAuthorityV1,
                "output_name",
            ),
            (
                "semantic_contracts",
                self.semantic_contracts,
                StarTableSemanticContractV1,
                "table_name",
            ),
            (
                "review_receipts",
                self.review_receipts,
                ReviewReceiptV1,
                "receipt_sha256",
            ),
            (
                "blockers",
                self.blockers,
                StarSemanticInventoryBlockerV1,
                "scope_id",
            ),
        ):
            if type(rows) is not tuple or any(type(row) is not row_type for row in rows):
                raise StarSemanticInventoryError(f"{label} must be an exact typed tuple")
            expected_order = (
                tuple(sorted(rows))
                if label == "blockers"
                else tuple(sorted(rows, key=lambda row: getattr(row, identity)))
            )
            if rows != expected_order:
                raise StarSemanticInventoryError(f"{label} must be sorted")
        if len({item.output_name for item in self.authorities}) != len(self.authorities):
            raise StarSemanticInventoryError("semantic authority table names must be unique")
        if len({item.table_name for item in self.semantic_contracts}) != len(
            self.semantic_contracts
        ):
            raise StarSemanticInventoryError("semantic contract table names must be unique")
        if len({item.receipt_sha256 for item in self.review_receipts}) != len(self.review_receipts):
            raise StarSemanticInventoryError("semantic review receipt identities must be unique")
        if len({(item.scope_id, item.code) for item in self.blockers}) != len(self.blockers):
            raise StarSemanticInventoryError("semantic blocker identities must be unique")
        expected_blockers = _validate_and_compute_join_blockers(
            structural_inventory_sha256=self.structural_inventory_sha256,
            stable_inventory_sha256=self.stable_inventory_sha256,
            stable_inventory_release_gate_green=self.stable_inventory_release_gate_green,
            authorities=self.authorities,
            semantic_contracts=self.semantic_contracts,
            review_receipts=self.review_receipts,
        )
        if self.blockers != expected_blockers:
            raise StarSemanticInventoryError(
                "blocker inventory differs from the exact star semantic join"
            )
        if type(self.model_green) is not bool:
            raise StarSemanticInventoryError("model_green must be an exact boolean")
        expected_green = self.stable_inventory_release_gate_green and not self.blockers
        if self.model_green is not expected_green:
            raise StarSemanticInventoryError("model_green differs from the exact semantic join")

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "structural_inventory_sha256": self.structural_inventory_sha256,
            "stable_inventory_sha256": self.stable_inventory_sha256,
            "stable_inventory_release_gate_green": (self.stable_inventory_release_gate_green),
            "authorities": [item.to_dict() for item in self.authorities],
            "semantic_contracts": [item.to_dict() for item in self.semantic_contracts],
            "review_receipts": [item.to_dict() for item in self.review_receipts],
            "blockers": [item.to_dict() for item in self.blockers],
            "model_green": self.model_green,
        }

    @property
    def inventory_sha256(self) -> str:
        return _sha256(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "inventory_sha256": self.inventory_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="star semantic inventory")
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "structural_inventory_sha256",
                    "stable_inventory_sha256",
                    "stable_inventory_release_gate_green",
                    "authorities",
                    "semantic_contracts",
                    "review_receipts",
                    "blockers",
                    "model_green",
                    "inventory_sha256",
                }
            ),
            label="star semantic inventory",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise StarSemanticInventoryError("star semantic inventory identity is invalid")
        for field in ("stable_inventory_release_gate_green", "model_green"):
            if type(payload[field]) is not bool:
                raise StarSemanticInventoryError(f"{field} must be an exact boolean")
        arrays = {
            field: payload[field]
            for field in (
                "authorities",
                "semantic_contracts",
                "review_receipts",
                "blockers",
            )
        }
        if any(type(value) is not list for value in arrays.values()):
            raise StarSemanticInventoryError("star semantic inventories must be arrays")
        inventory = cls(
            structural_inventory_sha256=cast("str", payload["structural_inventory_sha256"]),
            stable_inventory_sha256=cast("str", payload["stable_inventory_sha256"]),
            stable_inventory_release_gate_green=cast(
                "bool", payload["stable_inventory_release_gate_green"]
            ),
            authorities=tuple(
                StarTableSemanticAuthorityV1.from_dict(item)
                for item in cast("list[object]", arrays["authorities"])
            ),
            semantic_contracts=tuple(
                StarTableSemanticContractV1.from_dict(item)
                for item in cast("list[object]", arrays["semantic_contracts"])
            ),
            review_receipts=tuple(
                ReviewReceiptV1.from_dict(item)
                for item in cast("list[object]", arrays["review_receipts"])
            ),
            blockers=tuple(
                StarSemanticInventoryBlockerV1.from_dict(item)
                for item in cast("list[object]", arrays["blockers"])
            ),
            model_green=cast("bool", payload["model_green"]),
        )
        if payload["inventory_sha256"] != inventory.inventory_sha256:
            raise StarSemanticInventoryError("star semantic inventory digest is invalid")
        return inventory

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_bytes(raw))


def compile_star_semantic_inventory(
    *,
    structural_inventory: StarModelContractInventory,
    stable_disposition_inventory: StableModelDispositionInventoryV1,
    semantic_contracts: Sequence[StarTableSemanticContractV1],
    review_receipts: Sequence[ReviewReceiptV1],
) -> StarSemanticInventoryV1:
    """Compile the exact current public-table semantic join without inference."""

    contract_rows = tuple(semantic_contracts)
    review_rows = tuple(review_receipts)
    if any(type(item) is not StarTableSemanticContractV1 for item in contract_rows):
        raise StarSemanticInventoryError("semantic contracts contain an invalid row")
    if any(type(item) is not ReviewReceiptV1 for item in review_rows):
        raise StarSemanticInventoryError("semantic review receipts contain an invalid row")
    authorities = derive_star_semantic_authorities(
        structural_inventory=structural_inventory,
        stable_disposition_inventory=stable_disposition_inventory,
    )
    sorted_contracts = tuple(sorted(contract_rows, key=lambda item: item.table_name))
    sorted_reviews = tuple(sorted(review_rows, key=lambda item: item.receipt_sha256))
    blockers = _validate_and_compute_join_blockers(
        structural_inventory_sha256=structural_inventory.contract_sha256,
        stable_inventory_sha256=stable_disposition_inventory.inventory_sha256,
        stable_inventory_release_gate_green=(stable_disposition_inventory.release_gate_green),
        authorities=authorities,
        semantic_contracts=sorted_contracts,
        review_receipts=sorted_reviews,
    )
    return StarSemanticInventoryV1(
        structural_inventory_sha256=structural_inventory.contract_sha256,
        stable_inventory_sha256=stable_disposition_inventory.inventory_sha256,
        stable_inventory_release_gate_green=(stable_disposition_inventory.release_gate_green),
        authorities=authorities,
        semantic_contracts=sorted_contracts,
        review_receipts=sorted_reviews,
        blockers=blockers,
        model_green=(stable_disposition_inventory.release_gate_green and not blockers),
    )
