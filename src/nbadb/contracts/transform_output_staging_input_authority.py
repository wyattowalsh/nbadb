"""Fresh registered authority for staging inputs consumed by transforms."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Self, cast

from nbadb.contracts.staging_route_contract import (
    staging_route_contract_bundle,
    validate_staging_route_contract_bundle,
)
from nbadb.contracts.star_table_contract import compile_star_table_contracts
from nbadb.contracts.transform_output_disposition_evidence import (
    canonical_json_bytes_v1,
    decode_canonical_json_bytes_v1,
)
from nbadb.schemas.registry import get_input_schema

__all__ = [
    "RegisteredStagingInputContractEntryV1",
    "RegisteredStagingInputContractInventoryV1",
    "StagingInputContractAuthorityError",
    "compile_registered_staging_input_contract_inventory",
]

_VERSION = 1
_ENTRY_KIND = "nbadb_registered_staging_input_contract"
_INVENTORY_KIND = "nbadb_registered_staging_input_contract_inventory"
_STRUCTURAL_OUTPUT_INVENTORY_KIND = "nbadb_registered_staging_input_structural_output_inventory"
_OUTPUT_NAME_RE = re.compile(
    r"(?:fact|dim|bridge|agg|analytics)_[a-z0-9]+(?:_[a-z0-9]+)*\Z",
    flags=re.ASCII,
)


class StagingInputContractAuthorityError(ValueError):
    """The current registered staging-input authority is not exact."""


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes_v1(value)).hexdigest()


def _schema_descriptor(dependency_id: str, schema_type: type[Any]) -> dict[str, object]:
    try:
        schema = schema_type.to_schema()
    except Exception as exc:
        raise StagingInputContractAuthorityError(
            f"cannot compile registered input schema: {dependency_id}"
        ) from exc
    columns = []
    for ordinal, (name, column) in enumerate(schema.columns.items()):
        if type(name) is not str or not name:
            raise StagingInputContractAuthorityError("registered schema column name is invalid")
        columns.append(
            {
                "ordinal": ordinal,
                "name": name,
                "dtype": str(column.dtype),
                "nullable": bool(column.nullable),
                "required": bool(column.required),
                "unique": bool(column.unique),
            }
        )
    return {
        "dependency_id": dependency_id,
        "schema_module": schema_type.__module__,
        "schema_class": schema_type.__name__,
        "strict": bool(getattr(schema, "strict", False)),
        "ordered": bool(getattr(schema, "ordered", False)),
        "columns": columns,
    }


@dataclass(frozen=True, slots=True, init=False)
class RegisteredStagingInputContractEntryV1:
    dependency_id: str
    classification: str
    route_ids: tuple[str, ...]
    route_contract_sha256s: tuple[str, ...]
    schema_module: str
    schema_class: str
    staging_schema_sha256: str
    input_contract_sha256: str
    contract_sha256: str

    schema_version: ClassVar[int] = _VERSION
    kind: ClassVar[str] = _ENTRY_KIND

    def __init__(self) -> None:
        raise TypeError("registered staging entries are compiler/parser owned")

    def _preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "dependency_id": self.dependency_id,
            "classification": self.classification,
            "route_ids": list(self.route_ids),
            "route_contract_sha256s": list(self.route_contract_sha256s),
            "schema_module": self.schema_module,
            "schema_class": self.schema_class,
            "staging_schema_sha256": self.staging_schema_sha256,
            "input_contract_sha256": self.input_contract_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._preimage(), "contract_sha256": self.contract_sha256}


@dataclass(frozen=True, slots=True, init=False)
class RegisteredStagingInputContractInventoryV1:
    structural_output_names: tuple[str, ...]
    structural_output_count: int
    structural_output_inventory_sha256: str
    star_model_contract_sha256: str
    entries: tuple[RegisteredStagingInputContractEntryV1, ...]
    entry_count: int
    entry_inventory_sha256: str
    contract_sha256: str

    schema_version: ClassVar[int] = _VERSION
    kind: ClassVar[str] = _INVENTORY_KIND

    def __init__(self) -> None:
        raise TypeError("registered staging inventory requires from_canonical_bytes")

    def _preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "structural_output_names": list(self.structural_output_names),
            "structural_output_count": self.structural_output_count,
            "structural_output_inventory_sha256": (self.structural_output_inventory_sha256),
            "star_model_contract_sha256": self.star_model_contract_sha256,
            "entries": [entry.to_dict() for entry in self.entries],
            "entry_count": self.entry_count,
            "entry_inventory_sha256": self.entry_inventory_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._preimage(), "contract_sha256": self.contract_sha256}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes_v1(self.to_dict())

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        """Replay one exact inventory and require equality to current authority."""

        inventory = cls.from_historical_canonical_bytes(raw)
        current = compile_registered_staging_input_contract_inventory()
        if current.canonical_bytes() != raw:
            raise StagingInputContractAuthorityError(
                "staging inventory differs from the fresh registered authority"
            )
        return inventory

    @classmethod
    def from_historical_canonical_bytes(cls, raw: bytes) -> Self:
        """Reconstruct the typed wire contract without consulting current registries."""

        decoded = decode_canonical_json_bytes_v1(raw)
        if type(decoded) is not dict:
            raise StagingInputContractAuthorityError("staging inventory must be an object")
        payload = cast("dict[str, object]", decoded)
        expected = {
            "schema_version",
            "kind",
            "structural_output_names",
            "structural_output_count",
            "structural_output_inventory_sha256",
            "star_model_contract_sha256",
            "entries",
            "entry_count",
            "entry_inventory_sha256",
            "contract_sha256",
        }
        if (
            set(payload) != expected
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or payload["kind"] != _INVENTORY_KIND
        ):
            raise StagingInputContractAuthorityError("staging inventory fields or identity differ")
        rows = payload["entries"]
        if type(rows) is not list:
            raise StagingInputContractAuthorityError("staging inventory entries must be an array")
        output_names = payload["structural_output_names"]
        if type(output_names) is not list or any(type(item) is not str for item in output_names):
            raise StagingInputContractAuthorityError(
                "staging inventory structural outputs must be an exact string array"
            )
        entries = tuple(_entry_from_dict(row) for row in rows)
        inventory = _build_inventory(
            entries,
            structural_output_names=tuple(cast("list[str]", output_names)),
            star_model_contract_sha256=cast("str", payload["star_model_contract_sha256"]),
        )
        if inventory.canonical_bytes() != raw:
            raise StagingInputContractAuthorityError(
                "staging inventory differs from reconstruction"
            )
        return cast("Self", inventory)


def _entry_from_dict(value: object) -> RegisteredStagingInputContractEntryV1:
    if type(value) is not dict:
        raise StagingInputContractAuthorityError("staging entry must be an object")
    row = cast("dict[str, object]", value)
    expected = {
        "schema_version",
        "kind",
        "dependency_id",
        "classification",
        "route_ids",
        "route_contract_sha256s",
        "schema_module",
        "schema_class",
        "staging_schema_sha256",
        "input_contract_sha256",
        "contract_sha256",
    }
    if (
        set(row) != expected
        or type(row["schema_version"]) is not int
        or row["schema_version"] != 1
        or row["kind"] != _ENTRY_KIND
    ):
        raise StagingInputContractAuthorityError("staging entry fields or identity differ")
    for name in (
        "dependency_id",
        "classification",
        "schema_module",
        "schema_class",
        "staging_schema_sha256",
        "input_contract_sha256",
        "contract_sha256",
    ):
        if type(row[name]) is not str:
            raise StagingInputContractAuthorityError(f"staging entry {name} has a foreign type")
    if type(row["route_ids"]) is not list or type(row["route_contract_sha256s"]) is not list:
        raise StagingInputContractAuthorityError("staging entry routes must be arrays")
    if any(type(item) is not str for item in row["route_ids"]):
        raise StagingInputContractAuthorityError("staging route identity has a foreign type")
    if any(type(item) is not str for item in row["route_contract_sha256s"]):
        raise StagingInputContractAuthorityError("staging route digest has a foreign type")
    entry = _build_entry(
        dependency_id=cast("str", row["dependency_id"]),
        route_ids=tuple(cast("list[str]", row["route_ids"])),
        route_contract_sha256s=tuple(cast("list[str]", row["route_contract_sha256s"])),
        schema_module=cast("str", row["schema_module"]),
        schema_class=cast("str", row["schema_class"]),
        staging_schema_sha256=cast("str", row["staging_schema_sha256"]),
    )
    if entry.to_dict() != row:
        raise StagingInputContractAuthorityError("staging entry contains substituted authority")
    return entry


def _build_entry(
    *,
    dependency_id: str,
    route_ids: tuple[str, ...],
    route_contract_sha256s: tuple[str, ...],
    schema_module: str,
    schema_class: str,
    staging_schema_sha256: str,
) -> RegisteredStagingInputContractEntryV1:
    if (
        type(dependency_id) is not str
        or not dependency_id.startswith("stg_")
        or type(schema_module) is not str
        or not schema_module
        or type(schema_class) is not str
        or not schema_class
        or type(staging_schema_sha256) is not str
        or len(staging_schema_sha256) != 64
        or any(character not in "0123456789abcdef" for character in staging_schema_sha256)
        or any(type(route_id) is not str or not route_id for route_id in route_ids)
        or any(
            type(route_sha256) is not str
            or len(route_sha256) != 64
            or any(character not in "0123456789abcdef" for character in route_sha256)
            for route_sha256 in route_contract_sha256s
        )
        or route_ids != tuple(sorted(set(route_ids)))
        or not route_ids
        or len(route_ids) != len(route_contract_sha256s)
    ):
        raise StagingInputContractAuthorityError("staging entry identity or routes are invalid")
    input_root = _digest(
        {
            "kind": "nbadb_registered_staging_input_preimage",
            "dependency_id": dependency_id,
            "route_ids": list(route_ids),
            "route_contract_sha256s": list(route_contract_sha256s),
            "staging_schema_sha256": staging_schema_sha256,
        }
    )
    instance = object.__new__(RegisteredStagingInputContractEntryV1)
    values = {
        "dependency_id": dependency_id,
        "classification": "staging",
        "route_ids": route_ids,
        "route_contract_sha256s": route_contract_sha256s,
        "schema_module": schema_module,
        "schema_class": schema_class,
        "staging_schema_sha256": staging_schema_sha256,
        "input_contract_sha256": input_root,
    }
    for name, item in values.items():
        object.__setattr__(instance, name, item)
    object.__setattr__(instance, "contract_sha256", _digest(instance._preimage()))
    return instance


def _build_inventory(
    entries: tuple[RegisteredStagingInputContractEntryV1, ...],
    *,
    structural_output_names: tuple[str, ...],
    star_model_contract_sha256: str,
) -> RegisteredStagingInputContractInventoryV1:
    if (
        type(structural_output_names) is not tuple
        or not structural_output_names
        or structural_output_names != tuple(sorted(set(structural_output_names)))
        or any(
            type(output_name) is not str or _OUTPUT_NAME_RE.fullmatch(output_name) is None
            for output_name in structural_output_names
        )
    ):
        raise StagingInputContractAuthorityError(
            "structural output names must be normalized, sorted, and unique"
        )
    if (
        type(star_model_contract_sha256) is not str
        or len(star_model_contract_sha256) != 64
        or any(character not in "0123456789abcdef" for character in star_model_contract_sha256)
    ):
        raise StagingInputContractAuthorityError(
            "star model contract identity must be one lowercase SHA-256"
        )
    names = tuple(entry.dependency_id for entry in entries)
    if names != tuple(sorted(set(names))):
        raise StagingInputContractAuthorityError("staging entries must be sorted and unique")
    instance = object.__new__(RegisteredStagingInputContractInventoryV1)
    structural_root = _digest(
        {
            "schema_version": _VERSION,
            "kind": _STRUCTURAL_OUTPUT_INVENTORY_KIND,
            "output_names": list(structural_output_names),
        }
    )
    object.__setattr__(instance, "structural_output_names", structural_output_names)
    object.__setattr__(instance, "structural_output_count", len(structural_output_names))
    object.__setattr__(
        instance,
        "structural_output_inventory_sha256",
        structural_root,
    )
    object.__setattr__(instance, "star_model_contract_sha256", star_model_contract_sha256)
    object.__setattr__(instance, "entries", entries)
    object.__setattr__(instance, "entry_count", len(entries))
    root = _digest(
        {
            "kind": "nbadb_registered_staging_entry_inventory",
            "rows": [[entry.dependency_id, entry.contract_sha256] for entry in entries],
        }
    )
    object.__setattr__(instance, "entry_inventory_sha256", root)
    object.__setattr__(instance, "contract_sha256", _digest(instance._preimage()))
    instance.canonical_bytes()
    return instance


def compile_registered_staging_input_contract_inventory() -> (
    RegisteredStagingInputContractInventoryV1
):
    from nbadb.orchestrate.transformers import expected_transform_output_tables

    star = compile_star_table_contracts()
    structural_output_names = tuple(sorted(expected_transform_output_tables(include_live=True)))
    star_output_names = tuple(table.output_name for table in star.tables)
    if structural_output_names != star_output_names:
        raise StagingInputContractAuthorityError(
            "structural and star output denominators differ before staging compilation"
        )
    dependency_ids = tuple(
        sorted(
            {
                dependency
                for table in star.tables
                for dependency in table.transform.dependencies
                if dependency.startswith("stg_")
            }
        )
    )
    routes = staging_route_contract_bundle()
    validate_staging_route_contract_bundle(routes)
    entries = []
    for dependency_id in dependency_ids:
        matched = tuple(route for route in routes.routes if route.staging_key == dependency_id)
        schema_type = get_input_schema(dependency_id)
        if not matched or schema_type is None:
            raise StagingInputContractAuthorityError(
                f"staging dependency lacks exact registered authority: {dependency_id}"
            )
        route_ids = tuple(sorted(route.route_id for route in matched))
        by_id = {route.route_id: route for route in matched}
        if len(by_id) != len(matched):
            raise StagingInputContractAuthorityError("staging dependency has ambiguous routes")
        schema_descriptor = _schema_descriptor(dependency_id, schema_type)
        entries.append(
            _build_entry(
                dependency_id=dependency_id,
                route_ids=route_ids,
                route_contract_sha256s=tuple(
                    by_id[route_id].contract_sha256 for route_id in route_ids
                ),
                schema_module=schema_type.__module__,
                schema_class=schema_type.__name__,
                staging_schema_sha256=_digest(schema_descriptor),
            )
        )
    return _build_inventory(
        tuple(entries),
        structural_output_names=structural_output_names,
        star_model_contract_sha256=star.contract_sha256,
    )
