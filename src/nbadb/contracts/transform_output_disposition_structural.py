"""Exact structural denominator for transform-output disposition authority.

This module binds two independently exposed runtime views of the transform
output universe.  It deliberately carries no disposition state: structural
discovery remains complete even when no table has an authored disposition.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from nbadb.contracts.star_table_contract import (
    ModelBlockerSummary,
    StarFamilyCounts,
    StarModelContractInventory,
    StarTableContract,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "TRANSFORM_OUTPUT_STRUCTURAL_AUTHORITY_KIND",
    "TRANSFORM_OUTPUT_STRUCTURAL_AUTHORITY_SCHEMA_VERSION",
    "TransformOutputDispositionStructuralError",
    "TransformOutputStructuralAuthorityV1",
    "TransformOutputStructuralTableAuthorityV1",
    "compile_current_transform_output_structural_authority",
]

TRANSFORM_OUTPUT_STRUCTURAL_AUTHORITY_SCHEMA_VERSION = 1
TRANSFORM_OUTPUT_STRUCTURAL_AUTHORITY_KIND = (
    "nbadb_transform_output_disposition_structural_authority"
)
_TABLE_AUTHORITY_KIND = "nbadb_transform_output_disposition_structural_table"
_NAME_INVENTORY_KIND = "nbadb_transform_output_disposition_structural_names"
_TABLE_INVENTORY_KIND = "nbadb_transform_output_disposition_structural_tables"

type TransformOutputTableFamily = Literal[
    "fact",
    "dim",
    "bridge",
    "agg",
    "analytics",
]

_TABLE_FAMILIES = frozenset({"fact", "dim", "bridge", "agg", "analytics"})
_OUTPUT_NAME_RE = re.compile(
    r"(?:fact|dim|bridge|agg|analytics)_[a-z0-9]+(?:_[a-z0-9]+)*\Z",
    flags=re.ASCII,
)
_SQL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,255}\Z", flags=re.ASCII)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)

_MAX_CANONICAL_BYTES = 16 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 250_000
_MAX_COLLECTION_ITEMS = 8_192
_MAX_STRING_BYTES = 16 * 1024
_MAX_NUMBER_CHARS = 64


class TransformOutputDispositionStructuralError(ValueError):
    """The exact transform-output structural authority could not be proven."""


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
        raise TransformOutputDispositionStructuralError(
            "structural authority value is not canonical JSON"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise TransformOutputDispositionStructuralError(f"{field} must be a lowercase SHA-256")
    return value


def _require_output_name(value: object, *, field: str) -> str:
    if type(value) is not str or _OUTPUT_NAME_RE.fullmatch(value) is None:
        raise TransformOutputDispositionStructuralError(
            f"{field} must be an exact normalized transform output name"
        )
    return value


def _require_sql_name(value: object, *, field: str) -> str:
    if type(value) is not str or _SQL_NAME_RE.fullmatch(value) is None:
        raise TransformOutputDispositionStructuralError(f"{field} must be an exact SQL identifier")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    if any(type(key) is not str for key in payload):
        raise TransformOutputDispositionStructuralError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = ",".join(sorted(expected - actual))
    unexpected = ",".join(sorted(actual - expected))
    raise TransformOutputDispositionStructuralError(
        f"{label} fields differ (missing={missing}; unexpected={unexpected})"
    )


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise TransformOutputDispositionStructuralError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _require_string_array(
    value: object,
    *,
    field: str,
    output_names: bool = False,
) -> tuple[str, ...]:
    if type(value) is not list:
        raise TransformOutputDispositionStructuralError(f"{field} must be an array")
    validator = _require_output_name if output_names else _require_sql_name
    return tuple(validator(item, field=field) for item in cast("list[object]", value))


def _validate_json_tree(value: object, *, label: str) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    node_count = 0
    while stack:
        node, depth = stack.pop()
        node_count += 1
        if node_count > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise TransformOutputDispositionStructuralError(
                f"{label} exceeds its JSON structure budget"
            )
        if type(node) is dict:
            mapping = cast("dict[object, object]", node)
            if len(mapping) > _MAX_COLLECTION_ITEMS:
                raise TransformOutputDispositionStructuralError(
                    f"{label} contains an oversized object"
                )
            for key, item in mapping.items():
                if type(key) is not str or len(key.encode("utf-8")) > _MAX_STRING_BYTES:
                    raise TransformOutputDispositionStructuralError(
                        f"{label} contains an invalid object key"
                    )
                stack.append((item, depth + 1))
        elif type(node) is list:
            items = cast("list[object]", node)
            if len(items) > _MAX_COLLECTION_ITEMS:
                raise TransformOutputDispositionStructuralError(
                    f"{label} contains an oversized array"
                )
            stack.extend((item, depth + 1) for item in items)
        elif type(node) is str:
            if len(node.encode("utf-8")) > _MAX_STRING_BYTES:
                raise TransformOutputDispositionStructuralError(
                    f"{label} contains an oversized string"
                )
        elif node is None or type(node) in {bool, int}:
            continue
        else:
            raise TransformOutputDispositionStructuralError(
                f"{label} contains an unsupported JSON value"
            )


def _decode_canonical_object(raw: bytes) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise TransformOutputDispositionStructuralError(
            "structural authority bytes are empty, foreign, or oversized"
        )

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise TransformOutputDispositionStructuralError(
                    f"structural authority contains duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise TransformOutputDispositionStructuralError(
            f"structural authority contains non-finite JSON: {value}"
        )

    def _integer(value: str) -> int:
        if len(value) > _MAX_NUMBER_CHARS:
            raise TransformOutputDispositionStructuralError(
                "structural authority integer token exceeds its bound"
            )
        return int(value)

    def _floating(value: str) -> float:
        raise TransformOutputDispositionStructuralError(
            f"structural authority does not admit floating JSON values: {value}"
        )

    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_int=_integer,
            parse_float=_floating,
        )
    except TransformOutputDispositionStructuralError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise TransformOutputDispositionStructuralError(
            "structural authority bytes are invalid JSON"
        ) from exc
    payload = _require_mapping(decoded, label="structural authority")
    _validate_json_tree(payload, label="structural authority")
    if _canonical_bytes(payload) != raw:
        raise TransformOutputDispositionStructuralError(
            "structural authority bytes are not exact canonical JSON"
        )
    return payload


def _family_for_output(output_name: str) -> TransformOutputTableFamily:
    family = output_name.partition("_")[0]
    if family not in _TABLE_FAMILIES:
        raise TransformOutputDispositionStructuralError(
            f"transform output has an unsupported table family: {output_name}"
        )
    return cast("TransformOutputTableFamily", family)


@dataclass(frozen=True, slots=True, order=True)
class TransformOutputStructuralTableAuthorityV1:
    """One table-local structural identity with no disposition state."""

    output_name: str
    table_family: TransformOutputTableFamily
    table_contract_sha256: str
    schema_sha256: str
    transform_sha256: str
    ordered_columns: tuple[str, ...]
    dependencies: tuple[str, ...]

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_STRUCTURAL_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = _TABLE_AUTHORITY_KIND

    def __post_init__(self) -> None:
        _require_output_name(self.output_name, field="table output_name")
        if self.table_family != _family_for_output(self.output_name):
            raise TransformOutputDispositionStructuralError(
                f"table family differs from output name: {self.output_name}"
            )
        for field, value in (
            ("table_contract_sha256", self.table_contract_sha256),
            ("schema_sha256", self.schema_sha256),
            ("transform_sha256", self.transform_sha256),
        ):
            _require_sha256(value, field=field)
        for field, values in (
            ("ordered_columns", self.ordered_columns),
            ("dependencies", self.dependencies),
        ):
            if type(values) is not tuple:
                raise TransformOutputDispositionStructuralError(f"{field} must be an exact tuple")
            if len(values) != len(set(values)):
                raise TransformOutputDispositionStructuralError(f"{field} must be unique")
            for value in values:
                _require_sql_name(value, field=field)

    @property
    def ordered_column_inventory_sha256(self) -> str:
        return _sha256(
            {
                "schema_version": self.schema_version,
                "kind": "nbadb_transform_output_ordered_columns",
                "output_name": self.output_name,
                "ordered_columns": list(self.ordered_columns),
            }
        )

    @property
    def dependency_inventory_sha256(self) -> str:
        return _sha256(
            {
                "schema_version": self.schema_version,
                "kind": "nbadb_transform_output_ordered_dependencies",
                "output_name": self.output_name,
                "dependencies": list(self.dependencies),
            }
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "output_name": self.output_name,
            "table_family": self.table_family,
            "table_contract_sha256": self.table_contract_sha256,
            "schema_sha256": self.schema_sha256,
            "transform_sha256": self.transform_sha256,
            "ordered_columns": list(self.ordered_columns),
            "ordered_column_inventory_sha256": self.ordered_column_inventory_sha256,
            "dependencies": list(self.dependencies),
            "dependency_inventory_sha256": self.dependency_inventory_sha256,
        }

    @property
    def table_authority_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "table_authority_sha256": self.table_authority_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="structural table authority")
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "output_name",
                    "table_family",
                    "table_contract_sha256",
                    "schema_sha256",
                    "transform_sha256",
                    "ordered_columns",
                    "ordered_column_inventory_sha256",
                    "dependencies",
                    "dependency_inventory_sha256",
                    "table_authority_sha256",
                }
            ),
            label="structural table authority",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise TransformOutputDispositionStructuralError(
                "structural table authority schema identity is invalid"
            )
        table = cls(
            output_name=cast("str", payload["output_name"]),
            table_family=cast("TransformOutputTableFamily", payload["table_family"]),
            table_contract_sha256=cast("str", payload["table_contract_sha256"]),
            schema_sha256=cast("str", payload["schema_sha256"]),
            transform_sha256=cast("str", payload["transform_sha256"]),
            ordered_columns=_require_string_array(
                payload["ordered_columns"], field="ordered_columns"
            ),
            dependencies=_require_string_array(payload["dependencies"], field="dependencies"),
        )
        for field, expected in (
            ("ordered_column_inventory_sha256", table.ordered_column_inventory_sha256),
            ("dependency_inventory_sha256", table.dependency_inventory_sha256),
            ("table_authority_sha256", table.table_authority_sha256),
        ):
            if _require_sha256(payload[field], field=field) != expected:
                raise TransformOutputDispositionStructuralError(
                    f"structural table authority {field} is invalid"
                )
        return table


@dataclass(frozen=True, slots=True)
class TransformOutputStructuralAuthorityV1:
    """Complete exact transform-output structural denominator for one runtime."""

    output_names: tuple[str, ...]
    star_model_contract_sha256: str
    tables: tuple[TransformOutputStructuralTableAuthorityV1, ...]

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_STRUCTURAL_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = TRANSFORM_OUTPUT_STRUCTURAL_AUTHORITY_KIND

    def __post_init__(self) -> None:
        if type(self.output_names) is not tuple or not self.output_names:
            raise TransformOutputDispositionStructuralError(
                "output_names must be a nonempty exact tuple"
            )
        for output_name in self.output_names:
            _require_output_name(output_name, field="output_names")
        if self.output_names != tuple(sorted(set(self.output_names))):
            raise TransformOutputDispositionStructuralError(
                "output_names must be sorted and unique"
            )
        _require_sha256(
            self.star_model_contract_sha256,
            field="star_model_contract_sha256",
        )
        if (
            type(self.tables) is not tuple
            or not self.tables
            or any(
                type(item) is not TransformOutputStructuralTableAuthorityV1 for item in self.tables
            )
        ):
            raise TransformOutputDispositionStructuralError(
                "tables must be a nonempty exact typed tuple"
            )
        if self.tables != tuple(sorted(self.tables, key=lambda item: item.output_name)):
            raise TransformOutputDispositionStructuralError("tables must be sorted by output_name")
        table_names = tuple(item.output_name for item in self.tables)
        if table_names != self.output_names:
            raise TransformOutputDispositionStructuralError(
                "table identities differ from the exact output denominator"
            )
        if len({item.table_authority_sha256 for item in self.tables}) != len(self.tables):
            raise TransformOutputDispositionStructuralError(
                "table authority identities must be unique"
            )
        if len({item.table_contract_sha256 for item in self.tables}) != len(self.tables):
            raise TransformOutputDispositionStructuralError(
                "table contract identities must be unique"
            )

    @property
    def output_count(self) -> int:
        return len(self.output_names)

    @property
    def output_name_inventory_sha256(self) -> str:
        return _sha256(
            {
                "schema_version": self.schema_version,
                "kind": _NAME_INVENTORY_KIND,
                "output_names": list(self.output_names),
            }
        )

    @property
    def table_authority_inventory_sha256(self) -> str:
        return _sha256(
            {
                "schema_version": self.schema_version,
                "kind": _TABLE_INVENTORY_KIND,
                "tables": [
                    {
                        "output_name": table.output_name,
                        "table_authority_sha256": table.table_authority_sha256,
                    }
                    for table in self.tables
                ],
            }
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "output_count": self.output_count,
            "output_names": list(self.output_names),
            "output_name_inventory_sha256": self.output_name_inventory_sha256,
            "star_model_contract_sha256": self.star_model_contract_sha256,
            "table_authority_inventory_sha256": self.table_authority_inventory_sha256,
            "tables": [table.to_dict() for table in self.tables],
        }

    @property
    def authority_sha256(self) -> str:
        return _sha256(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "authority_sha256": self.authority_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="transform-output structural authority")
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "output_count",
                    "output_names",
                    "output_name_inventory_sha256",
                    "star_model_contract_sha256",
                    "table_authority_inventory_sha256",
                    "tables",
                    "authority_sha256",
                }
            ),
            label="transform-output structural authority",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise TransformOutputDispositionStructuralError(
                "transform-output structural authority schema identity is invalid"
            )
        table_values = payload["tables"]
        if type(table_values) is not list:
            raise TransformOutputDispositionStructuralError("tables must be an array")
        authority = cls(
            output_names=_require_string_array(
                payload["output_names"], field="output_names", output_names=True
            ),
            star_model_contract_sha256=cast("str", payload["star_model_contract_sha256"]),
            tables=tuple(
                TransformOutputStructuralTableAuthorityV1.from_dict(item)
                for item in cast("list[object]", table_values)
            ),
        )
        if type(payload["output_count"]) is not int or payload["output_count"] != (
            authority.output_count
        ):
            raise TransformOutputDispositionStructuralError(
                "structural authority output_count is invalid"
            )
        for field, expected in (
            ("output_name_inventory_sha256", authority.output_name_inventory_sha256),
            (
                "table_authority_inventory_sha256",
                authority.table_authority_inventory_sha256,
            ),
            ("authority_sha256", authority.authority_sha256),
        ):
            if _require_sha256(payload[field], field=field) != expected:
                raise TransformOutputDispositionStructuralError(
                    f"transform-output structural authority {field} is invalid"
                )
        return authority

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_object(raw))


def _expected_inventory_sha256(inventory: StarModelContractInventory) -> str:
    counts = inventory.family_counts
    if type(counts) is not StarFamilyCounts:
        raise TransformOutputDispositionStructuralError(
            "compiled star inventory family counts are untyped"
        )
    if type(inventory.blocker_summary) is not tuple or any(
        type(item) is not ModelBlockerSummary for item in inventory.blocker_summary
    ):
        raise TransformOutputDispositionStructuralError(
            "compiled star inventory blocker summary is untyped"
        )
    if type(inventory.model_green) is not bool:
        raise TransformOutputDispositionStructuralError(
            "compiled star inventory model_green is not an exact boolean"
        )
    return _sha256(
        {
            "tables": [
                {
                    "output_name": table.output_name,
                    "contract_sha256": table.contract_sha256,
                }
                for table in inventory.tables
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
                for blocker in inventory.blocker_summary
            ],
            "model_green": inventory.model_green,
        }
    )


def _validate_compiled_inventory(inventory: StarModelContractInventory) -> tuple[str, ...]:
    if type(inventory) is not StarModelContractInventory:
        raise TransformOutputDispositionStructuralError(
            "star contract compiler returned a foreign inventory type"
        )
    if (
        type(inventory.tables) is not tuple
        or not inventory.tables
        or any(type(item) is not StarTableContract for item in inventory.tables)
    ):
        raise TransformOutputDispositionStructuralError(
            "compiled star inventory tables are empty, foreign, or untyped"
        )
    names = tuple(table.output_name for table in inventory.tables)
    for name in names:
        _require_output_name(name, field="compiled output name")
    if names != tuple(sorted(set(names))):
        raise TransformOutputDispositionStructuralError(
            "compiled star inventory names must be sorted and unique"
        )
    actual_counts = Counter(_family_for_output(name) for name in names)
    derived_counts = StarFamilyCounts(
        fact=actual_counts["fact"],
        dim=actual_counts["dim"],
        bridge=actual_counts["bridge"],
        agg=actual_counts["agg"],
        analytics=actual_counts["analytics"],
    )
    if inventory.family_counts != derived_counts:
        raise TransformOutputDispositionStructuralError(
            "compiled star inventory family counts differ from its names"
        )
    _require_sha256(inventory.contract_sha256, field="compiled star inventory root")
    if inventory.contract_sha256 != _expected_inventory_sha256(inventory):
        raise TransformOutputDispositionStructuralError(
            "compiled star inventory root differs from its ordered table roots"
        )
    return names


def _table_authority(table: StarTableContract) -> TransformOutputStructuralTableAuthorityV1:
    return TransformOutputStructuralTableAuthorityV1(
        output_name=table.output_name,
        table_family=_family_for_output(table.output_name),
        table_contract_sha256=table.contract_sha256,
        schema_sha256=table.schema_sha256,
        transform_sha256=table.transform.implementation_sha256,
        ordered_columns=tuple(column.name for column in table.columns),
        dependencies=table.transform.dependencies,
    )


def compile_current_transform_output_structural_authority() -> TransformOutputStructuralAuthorityV1:
    """Fresh-compile both structural sources and require exact equality."""

    try:
        from nbadb.contracts.star_table_contract import compile_star_table_contracts
        from nbadb.orchestrate.transformers import expected_transform_output_tables

        discovered = expected_transform_output_tables(include_live=True)
        compiled = compile_star_table_contracts()
    except TransformOutputDispositionStructuralError:
        raise
    except Exception as exc:
        raise TransformOutputDispositionStructuralError(
            f"cannot fresh-compile the transform-output structural sources: {type(exc).__name__}"
        ) from exc

    if type(discovered) is not frozenset:
        raise TransformOutputDispositionStructuralError(
            "expected transform-output discovery returned a foreign collection type"
        )
    discovered_names = tuple(sorted(discovered))
    if not discovered_names:
        raise TransformOutputDispositionStructuralError(
            "expected transform-output discovery is empty"
        )
    for name in discovered_names:
        _require_output_name(name, field="discovered output name")
    compiled_names = _validate_compiled_inventory(compiled)
    if discovered_names != compiled_names:
        missing = ",".join(sorted(set(discovered_names) - set(compiled_names)))
        extra = ",".join(sorted(set(compiled_names) - set(discovered_names)))
        raise TransformOutputDispositionStructuralError(
            "transform-output structural sources differ "
            f"(missing_from_compiled={missing}; unexpected_in_compiled={extra}; "
            "ordered_sequences_equal=false)"
        )

    authority = TransformOutputStructuralAuthorityV1(
        output_names=discovered_names,
        star_model_contract_sha256=compiled.contract_sha256,
        tables=tuple(_table_authority(table) for table in compiled.tables),
    )
    replayed = TransformOutputStructuralAuthorityV1.from_canonical_bytes(authority.canonical_bytes)
    if replayed != authority:
        raise TransformOutputDispositionStructuralError(
            "fresh structural authority failed exact canonical replay"
        )
    return replayed
