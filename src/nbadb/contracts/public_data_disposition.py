"""Exact public data disposition contracts for sanitized publication candidates.

A :class:`PublicDataDispositionV1` is the sole allowlist authority for every
public database table, export resource, report, and metadata file that may
leave the private extraction tree.  Candidates are built from this positive
allowlist; they are never produced by copying a private checkpoint and deleting
known files.

The four body-bearing raw authority relations are private-only.  They appear
here only as a rejection set: any disposition that carries them as a relation,
as a resource's relation name, or referenced from a resource path is invalid
regardless of any other field.

Every digest is recomputed at construction and parse time; a stored literal
never confers authority.  Schema or disposition drift fails closed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self

if TYPE_CHECKING:
    from collections.abc import Callable

from nbadb.contracts.receipt_digest import canonical_receipt_bytes

__all__ = [
    "PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION",
    "PRIVATE_RAW_AUTHORITY_RELATIONS",
    "RESERVED_ENVELOPE_PATHS",
    "PublicDataDispositionError",
    "PublicDataDispositionV1",
    "PublicRelationDispositionV1",
    "PublicResourceDispositionV1",
]

#: Schema version for serialized dispositions.
PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION: Final = 1

#: The exact-four body-bearing raw authority relations; private-only, never
#: publishable in any public database, export, report, or metadata form.
PRIVATE_RAW_AUTHORITY_RELATIONS: Final = (
    "raw_nba_api_parser_input_object",
    "raw_nba_api_request_observation",
    "raw_nba_api_result_occurrence",
    "raw_nba_api_observation_route_landing",
)

#: The fixed staged publication envelope: candidate resources plus exactly
#: these reserved files.  Candidate resources may never claim these names.
RESERVED_ENVELOPE_PATHS: Final = (
    "public-data-disposition.json",
    "dataset-metadata.json",
    "publication-marker.json",
)

#: Canonical relative POSIX resource path: no drive, no backslash, no
#: traversal, no trailing slash (files only).
_RESOURCE_PATH_PATTERN: Final = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]*\Z", flags=re.ASCII)

#: Lowercase snake_case relation/table names keep ordering deterministic.
_TABLE_NAME_PATTERN: Final = re.compile(r"[a-z_][a-z0-9_]*\Z", flags=re.ASCII)

_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)

_MEDIA_TYPE_PATTERN: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\Z",
    flags=re.ASCII,
)

#: Physical types that can carry raw bytes; public relations never use them.
_BINARY_PHYSICAL_TYPES: Final = frozenset(
    {"binary", "bytes", "blob", "bytea", "varbinary", "large_binary"}
)

_RELATION_KEYS: Final = (
    "table_name",
    "category",
    "ordered_columns",
    "physical_types",
    "schema_sha256",
)
_RESOURCE_KEYS: Final = ("path", "size_bytes", "sha256", "media_type", "relation_name")
_DISPOSITION_KEYS: Final = (
    "candidate_tree_sha256",
    "candidate_inventory_sha256",
    "relation_entries",
    "resource_entries",
    "reserved_envelope_paths",
    "disposition_sha256",
)


class PublicDataDispositionError(ValueError):
    """A public data disposition is malformed, unsafe, or drifted."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PublicDataDispositionError(f"{field} must be a non-empty string")
    return value


def _require_sha256(value: object, field: str) -> str:
    text = _require_text(value, field)
    if not _SHA256_PATTERN.fullmatch(text):
        raise PublicDataDispositionError(f"{field} must be 64 lowercase hex characters")
    return text


def _require_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PublicDataDispositionError(f"{field} must be a non-negative integer")
    return value


def _require_str_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PublicDataDispositionError(f"{field} must be a sequence of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise PublicDataDispositionError(f"{field} entries must be non-empty strings")
        items.append(item)
    return tuple(items)


def _require_resource_path(value: object) -> str:
    text = _require_text(value, "path")
    if not _RESOURCE_PATH_PATTERN.fullmatch(text) or text.endswith("/"):
        raise PublicDataDispositionError(
            f"path must be a canonical relative POSIX file path, got {text!r}"
        )
    segments = text.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise PublicDataDispositionError(
            f"path must not contain empty, '.', or '..' segments, got {text!r}"
        )
    return text


def _reject_private_reference(*, where: str, value: str) -> None:
    for private in PRIVATE_RAW_AUTHORITY_RELATIONS:
        if private in value:
            raise PublicDataDispositionError(
                f"{where} references private raw authority relation {private!r}: {value!r}"
            )


@dataclass(frozen=True, slots=True)
class PublicRelationDispositionV1:
    """One declared public relation with its exact ordered schema."""

    table_name: str
    category: str
    ordered_columns: tuple[str, ...]
    physical_types: tuple[str, ...]
    schema_sha256: str

    def __post_init__(self) -> None:
        table = _require_text(self.table_name, "table_name")
        if not _TABLE_NAME_PATTERN.fullmatch(table):
            raise PublicDataDispositionError(
                f"table_name must be lowercase snake_case, got {table!r}"
            )
        object.__setattr__(self, "table_name", table)
        object.__setattr__(self, "category", _require_text(self.category, "category"))
        _reject_private_reference(where="relation table_name", value=table)
        columns = _require_str_tuple(self.ordered_columns, "ordered_columns")
        types = _require_str_tuple(self.physical_types, "physical_types")
        if len(columns) != len(types):
            raise PublicDataDispositionError(
                "ordered_columns and physical_types must have the same length: "
                f"{len(columns)} != {len(types)}"
            )
        if len(set(columns)) != len(columns):
            raise PublicDataDispositionError(
                f"ordered_columns must be duplicate-free for {table!r}"
            )
        if list(columns) != sorted(columns):
            raise PublicDataDispositionError(
                f"ordered_columns must be strictly ordered for {table!r}"
            )
        lowered = [physical.lower() for physical in types]
        for physical in lowered:
            if physical in _BINARY_PHYSICAL_TYPES:
                raise PublicDataDispositionError(
                    f"public relation {table!r} must not use binary physical type {physical!r}"
                )
        object.__setattr__(self, "ordered_columns", columns)
        object.__setattr__(self, "physical_types", types)
        schema_sha = _require_sha256(self.schema_sha256, "schema_sha256")
        if schema_sha != self.compute_schema_sha256():
            raise PublicDataDispositionError(
                "schema_sha256 does not match the declared table/category/columns/types; "
                "schema drift fails closed"
            )

    def digest_payload(self) -> dict[str, object]:
        """Exact-key mapping bound by :attr:`schema_sha256`."""
        return {
            "table_name": self.table_name,
            "category": self.category,
            "ordered_columns": list(self.ordered_columns),
            "physical_types": list(self.physical_types),
        }

    def compute_schema_sha256(self) -> str:
        """Digest over the declared relation schema."""
        return hashlib.sha256(canonical_receipt_bytes(self.digest_payload())).hexdigest()

    def to_payload(self) -> dict[str, object]:
        """Serialize to an exact-key mapping."""
        return {
            "schema_version": PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION,
            **self.digest_payload(),
            "schema_sha256": self.schema_sha256,
        }

    @classmethod
    def build(
        cls,
        *,
        table_name: str,
        category: str,
        ordered_columns: tuple[str, ...] | list[str],
        physical_types: tuple[str, ...] | list[str],
    ) -> Self:
        """Construct a relation entry, computing its schema digest."""
        return cls(
            table_name=table_name,
            category=category,
            ordered_columns=tuple(ordered_columns),
            physical_types=tuple(physical_types),
            schema_sha256=hashlib.sha256(
                canonical_receipt_bytes(
                    {
                        "table_name": table_name,
                        "category": category,
                        "ordered_columns": list(ordered_columns),
                        "physical_types": list(physical_types),
                    }
                )
            ).hexdigest(),
        )

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Parse an exact-key mapping; missing or extra keys fail."""
        if not isinstance(payload, dict):
            raise PublicDataDispositionError("relation payload must be a mapping")
        keys = set(payload)
        expected = {*_RELATION_KEYS, "schema_version"}
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise PublicDataDispositionError(
                f"relation keys mismatch: missing={missing} extra={extra}"
            )
        schema_version = payload.get("schema_version")
        if schema_version != PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION:
            raise PublicDataDispositionError(
                f"unsupported relation schema version {schema_version!r}"
            )
        table_name = _require_text(payload.get("table_name"), "table_name")
        category = _require_text(payload.get("category"), "category")
        return cls(
            table_name=table_name,
            category=category,
            ordered_columns=_require_str_tuple(payload.get("ordered_columns"), "ordered_columns"),
            physical_types=_require_str_tuple(payload.get("physical_types"), "physical_types"),
            schema_sha256=_require_sha256(payload.get("schema_sha256"), "schema_sha256"),
        )


@dataclass(frozen=True, slots=True)
class PublicResourceDispositionV1:
    """One declared public candidate resource file."""

    path: str
    size_bytes: int
    sha256: str
    media_type: str
    relation_name: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _require_resource_path(self.path))
        object.__setattr__(
            self, "size_bytes", _require_non_negative_int(self.size_bytes, "size_bytes")
        )
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        media_type = _require_text(self.media_type, "media_type")
        if not _MEDIA_TYPE_PATTERN.fullmatch(media_type):
            raise PublicDataDispositionError(
                f"media_type must be 'type/subtype', got {media_type!r}"
            )
        object.__setattr__(self, "media_type", media_type)
        if self.relation_name is not None:
            relation = _require_text(self.relation_name, "relation_name")
            if not _TABLE_NAME_PATTERN.fullmatch(relation):
                raise PublicDataDispositionError(
                    f"relation_name must be lowercase snake_case, got {relation!r}"
                )
            _reject_private_reference(where="resource relation_name", value=relation)
            object.__setattr__(self, "relation_name", relation)
        _reject_private_reference(where="resource path", value=self.path)

    def to_payload(self) -> dict[str, object]:
        """Serialize to an exact-key mapping."""
        return {
            "schema_version": PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "relation_name": self.relation_name,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Parse an exact-key mapping; missing or extra keys fail."""
        if not isinstance(payload, dict):
            raise PublicDataDispositionError("resource payload must be a mapping")
        keys = set(payload)
        expected = {*_RESOURCE_KEYS, "schema_version"}
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise PublicDataDispositionError(
                f"resource keys mismatch: missing={missing} extra={extra}"
            )
        schema_version = payload.get("schema_version")
        if schema_version != PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION:
            raise PublicDataDispositionError(
                f"unsupported resource schema version {schema_version!r}"
            )
        relation_name = payload.get("relation_name")
        if relation_name is not None:
            relation_name = _require_text(relation_name, "relation_name")
        return cls(
            path=_require_resource_path(payload.get("path")),
            size_bytes=_require_non_negative_int(payload.get("size_bytes"), "size_bytes"),
            sha256=_require_sha256(payload.get("sha256"), "sha256"),
            media_type=_require_text(payload.get("media_type"), "media_type"),
            relation_name=relation_name,
        )


@dataclass(frozen=True, slots=True)
class PublicDataDispositionV1:
    """The positive public allowlist binding one sanitized candidate tree."""

    candidate_tree_sha256: str
    candidate_inventory_sha256: str
    relation_entries: tuple[PublicRelationDispositionV1, ...]
    resource_entries: tuple[PublicResourceDispositionV1, ...]
    reserved_envelope_paths: tuple[str, ...]
    disposition_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_tree_sha256",
            _require_sha256(self.candidate_tree_sha256, "candidate_tree_sha256"),
        )
        object.__setattr__(
            self,
            "candidate_inventory_sha256",
            _require_sha256(self.candidate_inventory_sha256, "candidate_inventory_sha256"),
        )
        relations = self._require_entries(
            self.relation_entries,
            PublicRelationDispositionV1,
            "relation_entries",
            key=lambda entry: entry.table_name,
        )
        resources = self._require_entries(
            self.resource_entries,
            PublicResourceDispositionV1,
            "resource_entries",
            key=lambda entry: entry.path,
        )
        reserved = _require_str_tuple(self.reserved_envelope_paths, "reserved_envelope_paths")
        if tuple(reserved) != RESERVED_ENVELOPE_PATHS:
            raise PublicDataDispositionError(
                "reserved_envelope_paths must equal the fixed staged publication "
                f"envelope {list(RESERVED_ENVELOPE_PATHS)!r}, got {list(reserved)!r}"
            )
        object.__setattr__(self, "relation_entries", relations)
        object.__setattr__(self, "resource_entries", resources)
        object.__setattr__(self, "reserved_envelope_paths", reserved)
        self._require_disjoint_paths(resources)
        disposition_sha = _require_sha256(self.disposition_sha256, "disposition_sha256")
        if disposition_sha != self.compute_disposition_sha256():
            raise PublicDataDispositionError(
                "disposition_sha256 does not match the declared entries and candidate "
                "digests; disposition drift fails closed"
            )

    @staticmethod
    def _require_entries[E](
        value: object,
        entry_type: type[E],
        field: str,
        *,
        key: Callable[[E], str],
    ) -> tuple[E, ...]:
        if not isinstance(value, (list, tuple)):
            raise PublicDataDispositionError(f"{field} must be a sequence of entries")
        entries: list[E] = []
        for item in value:
            if not isinstance(item, entry_type):
                raise PublicDataDispositionError(
                    f"{field} entries must be {entry_type.__name__} instances"
                )
            entries.append(item)
        keys = [key(entry) for entry in entries]
        if len(set(keys)) != len(keys):
            raise PublicDataDispositionError(f"{field} must not contain duplicate entries")
        if keys != sorted(keys):
            raise PublicDataDispositionError(f"{field} must be strictly ordered")
        return tuple(entries)

    @staticmethod
    def _require_disjoint_paths(resources: tuple[PublicResourceDispositionV1, ...]) -> None:
        paths = [resource.path for resource in resources]
        for reserved in RESERVED_ENVELOPE_PATHS:
            if reserved in paths:
                raise PublicDataDispositionError(
                    f"reserved envelope path {reserved!r} must not be declared as a "
                    "candidate resource; the envelope is generated, not declared"
                )
        for path in paths:
            for other in paths:
                if path != other and other.startswith(path + "/"):
                    raise PublicDataDispositionError(
                        f"resource paths overlap: {path!r} is a file-parent of {other!r}"
                    )

    def digest_payload(self) -> dict[str, object]:
        """Exact-key mapping bound by :attr:`disposition_sha256`."""
        return {
            "schema_version": PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION,
            "candidate_tree_sha256": self.candidate_tree_sha256,
            "candidate_inventory_sha256": self.candidate_inventory_sha256,
            "relation_entries": [entry.to_payload() for entry in self.relation_entries],
            "resource_entries": [entry.to_payload() for entry in self.resource_entries],
            "reserved_envelope_paths": list(self.reserved_envelope_paths),
        }

    def compute_disposition_sha256(self) -> str:
        """Digest over the declared disposition excluding its own digest."""
        return hashlib.sha256(canonical_receipt_bytes(self.digest_payload())).hexdigest()

    def to_payload(self) -> dict[str, object]:
        """Serialize to an exact-key mapping."""
        return {
            **self.digest_payload(),
            "disposition_sha256": self.disposition_sha256,
        }

    @classmethod
    def build(
        cls,
        *,
        candidate_tree_sha256: str,
        candidate_inventory_sha256: str,
        relation_entries: tuple[PublicRelationDispositionV1, ...]
        | list[PublicRelationDispositionV1],
        resource_entries: tuple[PublicResourceDispositionV1, ...]
        | list[PublicResourceDispositionV1],
    ) -> Self:
        """Construct a disposition, computing its digest over the entries."""
        staged_payload = {
            "schema_version": PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION,
            "candidate_tree_sha256": candidate_tree_sha256,
            "candidate_inventory_sha256": candidate_inventory_sha256,
            "relation_entries": [entry.to_payload() for entry in relation_entries],
            "resource_entries": [entry.to_payload() for entry in resource_entries],
            "reserved_envelope_paths": list(RESERVED_ENVELOPE_PATHS),
        }
        disposition_sha256 = hashlib.sha256(canonical_receipt_bytes(staged_payload)).hexdigest()
        return cls(
            candidate_tree_sha256=candidate_tree_sha256,
            candidate_inventory_sha256=candidate_inventory_sha256,
            relation_entries=tuple(relation_entries),
            resource_entries=tuple(resource_entries),
            reserved_envelope_paths=RESERVED_ENVELOPE_PATHS,
            disposition_sha256=disposition_sha256,
        )

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Parse an exact-key mapping; drift and key mismatch fail closed."""
        if not isinstance(payload, dict):
            raise PublicDataDispositionError("disposition payload must be a mapping")
        keys = set(payload)
        expected = {*_DISPOSITION_KEYS, "schema_version"}
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise PublicDataDispositionError(
                f"disposition keys mismatch: missing={missing} extra={extra}"
            )
        schema_version = payload.get("schema_version")
        if schema_version != PUBLIC_DATA_DISPOSITION_SCHEMA_VERSION:
            raise PublicDataDispositionError(
                f"unsupported disposition schema version {schema_version!r}"
            )
        raw_relations = payload.get("relation_entries")
        raw_resources = payload.get("resource_entries")
        if not isinstance(raw_relations, list) or not isinstance(raw_resources, list):
            raise PublicDataDispositionError("entries must be lists in a payload")
        return cls(
            candidate_tree_sha256=_require_sha256(
                payload.get("candidate_tree_sha256"), "candidate_tree_sha256"
            ),
            candidate_inventory_sha256=_require_sha256(
                payload.get("candidate_inventory_sha256"), "candidate_inventory_sha256"
            ),
            relation_entries=tuple(
                PublicRelationDispositionV1.from_payload(entry) for entry in raw_relations
            ),
            resource_entries=tuple(
                PublicResourceDispositionV1.from_payload(entry) for entry in raw_resources
            ),
            reserved_envelope_paths=_require_str_tuple(
                payload.get("reserved_envelope_paths"), "reserved_envelope_paths"
            ),
            disposition_sha256=_require_sha256(
                payload.get("disposition_sha256"), "disposition_sha256"
            ),
        )
