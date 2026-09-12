"""Canonical packaged-resource authority for reviewed model decisions.

This module authenticates a caller-selected, repository-owned resource root.
It deliberately does not interpret model dispositions, semantic decisions, or
review evidence.  Those higher-level admissions consume the exact bytes and
evidence-resolution map returned here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import ClassVar, Self, cast

__all__ = [
    "AUTHORITY_RESOURCE_MANIFEST_KIND",
    "AUTHORITY_RESOURCE_MANIFEST_SCHEMA_VERSION",
    "AuthorityResourceError",
    "AuthorityResourceManifestV1",
    "AuthorityResourceRecordV1",
    "LoadedAuthorityResourcesV1",
    "load_authority_resource_manifest",
]

AUTHORITY_RESOURCE_MANIFEST_SCHEMA_VERSION = 1
AUTHORITY_RESOURCE_MANIFEST_KIND = "nbadb_model_authority_resource_manifest"

_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_RESOURCE_BYTES = 16 * 1024 * 1024
_MAX_AGGREGATE_BYTES = 64 * 1024 * 1024
_MAX_RESOURCES = 4096
_MAX_PARENT_SHA256S = 4096
_MAX_EVIDENCE_DIGESTS = 65_536
_MAX_JSON_DEPTH = 128
_MAX_JSON_NODES = 1_000_000
_MAX_JSON_NUMBER_CHARS = 256
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_HAS_DESCRIPTOR_RELATIVE_OPEN = os.open in os.supports_dir_fd
_HAS_DESCRIPTOR_SCANDIR = os.scandir in os.supports_fd


class AuthorityResourceError(ValueError):
    """A resource manifest or its exact packaged members are invalid."""


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
        raise AuthorityResourceError("authority resource value is not canonical JSON") from exc


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise AuthorityResourceError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise AuthorityResourceError(f"{field_name} must be a safe nonempty identifier")
    return value


def _require_exact_int(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise AuthorityResourceError(f"{field_name} must be an integer in [{minimum}, {maximum}]")
    return value


def _require_exact_keys(
    payload: dict[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if any(type(key) is not str for key in payload):
        raise AuthorityResourceError(f"{label} fields must use exact string keys")
    actual = frozenset(payload)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        unexpected = ",".join(sorted(actual - expected))
        raise AuthorityResourceError(
            f"{label} fields differ (missing={missing}; unexpected={unexpected})"
        )


def _decode_canonical_object(
    raw: bytes,
    *,
    label: str,
    maximum_bytes: int,
) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > maximum_bytes:
        raise AuthorityResourceError(f"{label} bytes are empty, foreign, or oversized")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise AuthorityResourceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise AuthorityResourceError(f"non-finite JSON constant: {value}")

    def _integer(value: str) -> int:
        if len(value) > _MAX_JSON_NUMBER_CHARS:
            raise AuthorityResourceError(f"{label} integer token exceeds its bound")
        try:
            return int(value)
        except ValueError as exc:
            raise AuthorityResourceError(f"{label} integer token is invalid") from exc

    def _floating(value: str) -> float:
        if len(value) > _MAX_JSON_NUMBER_CHARS:
            raise AuthorityResourceError(f"{label} number token exceeds its bound")
        try:
            result = float(value)
        except ValueError as exc:
            raise AuthorityResourceError(f"{label} number token is invalid") from exc
        if result != result or result in {float("inf"), float("-inf")}:
            raise AuthorityResourceError(f"{label} number token is non-finite")
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_int=_integer,
            parse_float=_floating,
        )
    except AuthorityResourceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise AuthorityResourceError(f"{label} bytes are invalid JSON") from exc
    if type(value) is not dict:
        raise AuthorityResourceError(f"{label} root must be an object")
    payload = cast("dict[str, object]", value)
    stack: list[tuple[object, int]] = [(payload, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise AuthorityResourceError(f"{label} exceeds its JSON structure budget")
        if type(node) is dict:
            stack.extend((item, depth + 1) for item in cast("dict[str, object]", node).values())
        elif type(node) is list:
            stack.extend((item, depth + 1) for item in cast("list[object]", node))
    if _canonical_bytes(payload) != raw:
        raise AuthorityResourceError(f"{label} bytes are not canonical")
    return payload


def _safe_relative_path(value: object, *, field_name: str) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise AuthorityResourceError(f"{field_name} must be a safe relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise AuthorityResourceError(f"{field_name} must be a safe relative POSIX path")
    if len(path.parts) > 32 or len(value.encode("utf-8")) > 1024:
        raise AuthorityResourceError(f"{field_name} exceeds its path bound")
    return value


def _tuple_sha256s(
    value: object,
    *,
    field_name: str,
    maximum: int = _MAX_EVIDENCE_DIGESTS,
) -> tuple[str, ...]:
    if type(value) is not list:
        raise AuthorityResourceError(f"{field_name} must be an array")
    values = tuple(_require_sha256(item, field_name=field_name) for item in value)
    if values != tuple(sorted(set(values))) or len(values) > maximum:
        raise AuthorityResourceError(f"{field_name} must be bounded, sorted, and unique")
    return values


@dataclass(frozen=True, slots=True, order=True)
class AuthorityResourceRecordV1:
    """One exact non-manifest file in a packaged model-authority root."""

    resource_id: str
    relative_path: str
    resource_role: str
    content_sha256: str
    size_bytes: int
    evidence_sha256s: tuple[str, ...]

    schema_version: ClassVar[int] = AUTHORITY_RESOURCE_MANIFEST_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_model_authority_resource_record"

    def __post_init__(self) -> None:
        _require_id(self.resource_id, field_name="resource_id")
        _safe_relative_path(self.relative_path, field_name="relative_path")
        _require_id(self.resource_role, field_name="resource_role")
        _require_sha256(self.content_sha256, field_name="content_sha256")
        _require_exact_int(
            self.size_bytes,
            field_name="size_bytes",
            minimum=2,
            maximum=_MAX_RESOURCE_BYTES,
        )
        if type(self.evidence_sha256s) is not tuple:
            raise AuthorityResourceError("evidence_sha256s must be an exact tuple")
        if (
            self.evidence_sha256s != tuple(sorted(set(self.evidence_sha256s)))
            or not self.evidence_sha256s
            or len(self.evidence_sha256s) > _MAX_EVIDENCE_DIGESTS
        ):
            raise AuthorityResourceError(
                "evidence_sha256s must be nonempty, bounded, sorted, and unique"
            )
        for digest in self.evidence_sha256s:
            _require_sha256(digest, field_name="evidence_sha256s")
        if self.content_sha256 not in self.evidence_sha256s:
            raise AuthorityResourceError(
                "evidence_sha256s must include the exact resource content digest"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "resource_id": self.resource_id,
            "relative_path": self.relative_path,
            "resource_role": self.resource_role,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "evidence_sha256s": list(self.evidence_sha256s),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthorityResourceError("authority resource record must be an object")
        payload = cast("dict[str, object]", value)
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "resource_id",
                    "relative_path",
                    "resource_role",
                    "content_sha256",
                    "size_bytes",
                    "evidence_sha256s",
                }
            ),
            label="authority resource record",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or type(payload["kind"]) is not str
            or payload["kind"] != cls.kind
        ):
            raise AuthorityResourceError("authority resource record schema is invalid")
        return cls(
            resource_id=cast("str", payload["resource_id"]),
            relative_path=cast("str", payload["relative_path"]),
            resource_role=cast("str", payload["resource_role"]),
            content_sha256=cast("str", payload["content_sha256"]),
            size_bytes=cast("int", payload["size_bytes"]),
            evidence_sha256s=_tuple_sha256s(
                payload["evidence_sha256s"], field_name="evidence_sha256s"
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorityResourceManifestV1:
    """Exact complete membership for one packaged model-authority root."""

    authority_id: str
    parent_sha256s: tuple[str, ...]
    resources: tuple[AuthorityResourceRecordV1, ...]

    schema_version: ClassVar[int] = AUTHORITY_RESOURCE_MANIFEST_SCHEMA_VERSION
    kind: ClassVar[str] = AUTHORITY_RESOURCE_MANIFEST_KIND

    def __post_init__(self) -> None:
        _require_id(self.authority_id, field_name="authority_id")
        if (
            type(self.parent_sha256s) is not tuple
            or not self.parent_sha256s
            or len(self.parent_sha256s) > _MAX_PARENT_SHA256S
            or self.parent_sha256s != tuple(sorted(set(self.parent_sha256s)))
        ):
            raise AuthorityResourceError(
                "parent_sha256s must be nonempty, bounded, sorted, and unique"
            )
        for digest in self.parent_sha256s:
            _require_sha256(digest, field_name="parent_sha256s")
        if (
            type(self.resources) is not tuple
            or not self.resources
            or len(self.resources) > _MAX_RESOURCES
            or any(type(item) is not AuthorityResourceRecordV1 for item in self.resources)
        ):
            raise AuthorityResourceError("resources must be a nonempty exact bounded tuple")
        if self.resources != tuple(sorted(self.resources, key=lambda item: item.resource_id)):
            raise AuthorityResourceError("resources must be sorted by resource_id")
        for field_name, values in (
            ("resource IDs", [item.resource_id for item in self.resources]),
            ("resource paths", [item.relative_path for item in self.resources]),
            ("resource content digests", [item.content_sha256 for item in self.resources]),
        ):
            if len(values) != len(set(values)):
                raise AuthorityResourceError(f"{field_name} must be unique")
        evidence = [digest for item in self.resources for digest in item.evidence_sha256s]
        if len(evidence) > _MAX_EVIDENCE_DIGESTS or len(evidence) != len(set(evidence)):
            raise AuthorityResourceError(
                "evidence digests must be bounded and resolve to exactly one resource"
            )
        aggregate_size = sum(item.size_bytes for item in self.resources)
        if aggregate_size > _MAX_AGGREGATE_BYTES:
            raise AuthorityResourceError("resource aggregate size exceeds its bound")
        placeholder = {**self._content_dict(), "manifest_sha256": "0" * 64}
        if len(_canonical_bytes(placeholder)) > _MAX_MANIFEST_BYTES:
            raise AuthorityResourceError("authority resource manifest exceeds its byte bound")

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_id": self.authority_id,
            "parent_sha256s": list(self.parent_sha256s),
            "resources": [item.to_dict() for item in self.resources],
        }

    @property
    def manifest_sha256(self) -> str:
        return _sha256_bytes(_canonical_bytes(self._content_dict()))

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "manifest_sha256": self.manifest_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthorityResourceError("authority resource manifest must be an object")
        payload = cast("dict[str, object]", value)
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "authority_id",
                    "parent_sha256s",
                    "resources",
                    "manifest_sha256",
                }
            ),
            label="authority resource manifest",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or type(payload["kind"]) is not str
            or payload["kind"] != cls.kind
        ):
            raise AuthorityResourceError("authority resource manifest schema is invalid")
        resources = payload["resources"]
        if type(resources) is not list:
            raise AuthorityResourceError("manifest resources must be an array")
        manifest = cls(
            authority_id=cast("str", payload["authority_id"]),
            parent_sha256s=_tuple_sha256s(
                payload["parent_sha256s"],
                field_name="parent_sha256s",
                maximum=_MAX_PARENT_SHA256S,
            ),
            resources=tuple(AuthorityResourceRecordV1.from_dict(item) for item in resources),
        )
        if (
            _require_sha256(payload["manifest_sha256"], field_name="manifest_sha256")
            != manifest.manifest_sha256
        ):
            raise AuthorityResourceError("authority resource manifest digest is invalid")
        return manifest

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(
            _decode_canonical_object(
                raw,
                label="authority resource manifest",
                maximum_bytes=_MAX_MANIFEST_BYTES,
            )
        )


@dataclass(frozen=True, slots=True, init=False)
class LoadedAuthorityResourcesV1:
    """Validated in-memory readback of one complete packaged authority root."""

    manifest_relative_path: str
    manifest: AuthorityResourceManifestV1
    expected_manifest_sha256: str
    _resources_by_id: MappingProxyType[str, bytes] = field(repr=False)
    _resource_ids_by_evidence_sha256: MappingProxyType[str, str] = field(repr=False)

    def __init__(self) -> None:
        raise AuthorityResourceError(
            "loaded authority resources are created only by the pinned filesystem loader"
        )

    @classmethod
    def _from_validated(
        cls,
        *,
        manifest_relative_path: str,
        manifest: AuthorityResourceManifestV1,
        expected_manifest_sha256: str,
        resources_by_id: dict[str, bytes],
    ) -> Self:
        instance = object.__new__(cls)
        object.__setattr__(instance, "manifest_relative_path", manifest_relative_path)
        object.__setattr__(instance, "manifest", manifest)
        object.__setattr__(
            instance,
            "expected_manifest_sha256",
            expected_manifest_sha256,
        )
        object.__setattr__(
            instance,
            "_resources_by_id",
            MappingProxyType(dict(resources_by_id)),
        )
        evidence_index = {
            digest: record.resource_id
            for record in manifest.resources
            for digest in record.evidence_sha256s
        }
        object.__setattr__(
            instance,
            "_resource_ids_by_evidence_sha256",
            MappingProxyType(evidence_index),
        )
        instance._validated_snapshot(expected_manifest_sha256=expected_manifest_sha256)
        return instance

    def _validated_snapshot(
        self,
        *,
        expected_manifest_sha256: str,
    ) -> tuple[
        AuthorityResourceManifestV1,
        dict[str, bytes],
        dict[str, str],
    ]:
        if type(self) is not LoadedAuthorityResourcesV1:
            raise AuthorityResourceError("loaded authority resource type is foreign")
        try:
            manifest_relative_path = self.manifest_relative_path
            supplied_manifest = self.manifest
            supplied_pin = self.expected_manifest_sha256
            supplied_resources = self._resources_by_id
            supplied_evidence = self._resource_ids_by_evidence_sha256
        except AttributeError as exc:
            raise AuthorityResourceError("loaded authority resource object is incomplete") from exc
        manifest_path = _safe_relative_path(
            manifest_relative_path,
            field_name="manifest_relative_path",
        )
        if not manifest_path:
            raise AuthorityResourceError("manifest path is invalid")
        if type(supplied_manifest) is not AuthorityResourceManifestV1:
            raise AuthorityResourceError("loaded authority manifest type is foreign")
        manifest = AuthorityResourceManifestV1.from_dict(supplied_manifest.to_dict())
        external_pin = _require_sha256(
            expected_manifest_sha256,
            field_name="expected_manifest_sha256",
        )
        stored_pin = _require_sha256(
            supplied_pin,
            field_name="stored expected_manifest_sha256",
        )
        if external_pin != stored_pin or manifest.manifest_sha256 != external_pin:
            raise AuthorityResourceError("loaded authority manifest differs from its trust pin")
        try:
            resource_snapshot = dict(supplied_resources)
            evidence_snapshot = dict(supplied_evidence)
        except (TypeError, ValueError) as exc:
            raise AuthorityResourceError("loaded authority indexes are foreign") from exc
        records_by_id = {record.resource_id: record for record in manifest.resources}
        if set(resource_snapshot) != set(records_by_id):
            raise AuthorityResourceError("loaded authority resource index is incomplete")
        for resource_id, raw in resource_snapshot.items():
            if type(resource_id) is not str or type(raw) is not bytes:
                raise AuthorityResourceError("loaded authority resource index is untyped")
            record = records_by_id[resource_id]
            if len(raw) != record.size_bytes or _sha256_bytes(raw) != record.content_sha256:
                raise AuthorityResourceError("loaded authority resource bytes differ from receipt")
            _decode_canonical_object(
                raw,
                label=f"loaded authority resource {resource_id}",
                maximum_bytes=_MAX_RESOURCE_BYTES,
            )
        expected_evidence = {
            digest: record.resource_id
            for record in manifest.resources
            for digest in record.evidence_sha256s
        }
        if evidence_snapshot != expected_evidence:
            raise AuthorityResourceError("loaded authority evidence index is fabricated")
        return manifest, resource_snapshot, expected_evidence

    def resource_bytes(
        self,
        resource_id: str,
        *,
        expected_manifest_sha256: str,
    ) -> bytes:
        _require_id(resource_id, field_name="resource_id")
        _manifest, resources, _evidence = self._validated_snapshot(
            expected_manifest_sha256=expected_manifest_sha256
        )
        try:
            return resources[resource_id]
        except KeyError as exc:
            raise AuthorityResourceError("authority resource ID is not declared") from exc

    def resolve_evidence(
        self,
        evidence_sha256: str,
        *,
        expected_manifest_sha256: str,
    ) -> tuple[AuthorityResourceRecordV1, bytes]:
        digest = _require_sha256(evidence_sha256, field_name="evidence_sha256")
        manifest, resources, evidence_index = self._validated_snapshot(
            expected_manifest_sha256=expected_manifest_sha256
        )
        try:
            resource_id = evidence_index[digest]
        except KeyError as exc:
            raise AuthorityResourceError("evidence digest is not declared") from exc
        records = {item.resource_id: item for item in manifest.resources}
        record = records[resource_id]
        if digest not in record.evidence_sha256s:
            raise AuthorityResourceError("evidence digest is rebound to a foreign resource")
        return record, resources[resource_id]


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_descriptor_relative_io() -> None:
    if (
        not _HAS_DESCRIPTOR_RELATIVE_OPEN
        or not _HAS_DESCRIPTOR_SCANDIR
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_NONBLOCK")
    ):
        raise AuthorityResourceError(
            "authority resources require descriptor-relative no-follow filesystem support"
        )


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | cast("int", getattr(os, "O_CLOEXEC", 0))


def _file_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | cast("int", getattr(os, "O_CLOEXEC", 0))


def _open_root_directory(root_path: Path) -> tuple[int, os.stat_result]:
    _require_descriptor_relative_io()
    try:
        before = root_path.lstat()
        resolved_root = root_path.resolve(strict=True)
    except OSError as exc:
        raise AuthorityResourceError("authority resource root cannot be inspected") from exc
    if stat.S_IFMT(before.st_mode) != stat.S_IFDIR or root_path.is_symlink():
        raise AuthorityResourceError("authority resource root must be a non-symlink directory")
    if resolved_root != root_path.absolute():
        raise AuthorityResourceError("authority resource root must already be an exact path")
    try:
        descriptor = os.open(root_path, _directory_flags())
        opened = os.fstat(descriptor)
        after = root_path.lstat()
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise AuthorityResourceError("authority resource root cannot be opened safely") from exc
    if not (
        _stat_identity(before) == _stat_identity(opened) == _stat_identity(after)
        and stat.S_IFMT(opened.st_mode) == stat.S_IFDIR
    ):
        os.close(descriptor)
        raise AuthorityResourceError("authority resource root changed while it was opened")
    return descriptor, opened


def _open_relative_parent(root_descriptor: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(root_descriptor)
    try:
        for part in parts:
            next_descriptor: int | None = None
            try:
                next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
                opened = os.fstat(next_descriptor)
                if stat.S_IFMT(opened.st_mode) != stat.S_IFDIR:
                    raise AuthorityResourceError("authority resource parent is not a directory")
            except (OSError, AuthorityResourceError):
                if next_descriptor is not None:
                    os.close(next_descriptor)
                raise
            previous_descriptor = descriptor
            descriptor = next_descriptor
            next_descriptor = None
            os.close(previous_descriptor)
        return descriptor
    except (OSError, AuthorityResourceError) as exc:
        os.close(descriptor)
        if isinstance(exc, AuthorityResourceError):
            raise
        raise AuthorityResourceError(
            "authority resource parent cannot be opened without following links"
        ) from exc


def _read_descriptor_relative_file(
    root_descriptor: int,
    relative_path: str,
    *,
    maximum_bytes: int,
    label: str,
) -> bytes:
    parts = PurePosixPath(relative_path).parts
    parent_descriptor = _open_relative_parent(root_descriptor, parts[:-1])
    descriptor: int | None = None
    try:
        descriptor = os.open(parts[-1], _file_flags(), dir_fd=parent_descriptor)
        before = os.fstat(descriptor)
        if stat.S_IFMT(before.st_mode) != stat.S_IFREG:
            raise AuthorityResourceError(f"{label} must be a non-symlink regular file")
        if not 1 <= before.st_size <= maximum_bytes:
            raise AuthorityResourceError(f"{label} size exceeds its bound")
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - observed))
            if not chunk:
                break
            chunks.append(chunk)
            observed += len(chunk)
            if observed > maximum_bytes:
                raise AuthorityResourceError(f"{label} size exceeds its bound")
        after = os.fstat(descriptor)
    except OSError as exc:
        raise AuthorityResourceError(f"{label} cannot be read safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)
    raw = b"".join(chunks)
    if _stat_identity(before) != _stat_identity(after) or len(raw) != before.st_size:
        raise AuthorityResourceError(f"{label} changed while it was read")
    return raw


def _scan_descriptor_tree(
    directory_descriptor: int,
    *,
    prefix: tuple[str, ...] = (),
) -> tuple[set[str], tuple[tuple[str, tuple[int, int, int, int, int, int]], ...]]:
    if len(prefix) > 32:
        raise AuthorityResourceError("authority resource directory depth exceeds its bound")
    files: set[str] = set()
    directories: list[tuple[str, tuple[int, int, int, int, int, int]]] = []
    scan_descriptor = os.dup(directory_descriptor)
    try:
        with os.scandir(scan_descriptor) as entries:
            ordered = sorted(
                (
                    entry.name,
                    entry.stat(follow_symlinks=False),
                    entry.is_symlink(),
                )
                for entry in entries
            )
    except (OSError, TypeError, NotImplementedError) as exc:
        raise AuthorityResourceError("authority resource membership cannot be scanned") from exc
    finally:
        with suppress(OSError):
            os.close(scan_descriptor)
    for name, observed, is_symlink in ordered:
        if type(name) is not str or not name or "/" in name or "\\" in name:
            raise AuthorityResourceError("authority resource member name is invalid")
        relative_parts = (*prefix, name)
        relative = PurePosixPath(*relative_parts).as_posix()
        mode = stat.S_IFMT(observed.st_mode)
        if mode == stat.S_IFDIR and not is_symlink:
            child_descriptor: int | None = None
            try:
                child_descriptor = os.open(name, _directory_flags(), dir_fd=directory_descriptor)
                opened = os.fstat(child_descriptor)
            except OSError as exc:
                if child_descriptor is not None:
                    os.close(child_descriptor)
                raise AuthorityResourceError(
                    "authority resource directory cannot be opened safely"
                ) from exc
            if _stat_identity(observed) != _stat_identity(opened):
                os.close(child_descriptor)
                raise AuthorityResourceError("authority resource directory changed during scan")
            directories.append((relative, _stat_identity(opened)))
            try:
                child_files, child_directories = _scan_descriptor_tree(
                    child_descriptor,
                    prefix=relative_parts,
                )
            finally:
                os.close(child_descriptor)
            files.update(child_files)
            directories.extend(child_directories)
        elif mode == stat.S_IFREG and not is_symlink:
            files.add(relative)
        else:
            raise AuthorityResourceError("authority root contains a symlink or special member")
    return files, tuple(directories)


def load_authority_resource_manifest(
    root: Path | str,
    *,
    expected_manifest_sha256: str,
    manifest_relative_path: str = "current-manifest.json",
) -> LoadedAuthorityResourcesV1:
    """Read one externally pinned exact resource root via held descriptors."""

    manifest_path_value = _safe_relative_path(
        manifest_relative_path,
        field_name="manifest_relative_path",
    )
    manifest_pin = _require_sha256(
        expected_manifest_sha256,
        field_name="expected_manifest_sha256",
    )
    root_path = Path(root)
    root_descriptor, root_opened = _open_root_directory(root_path)
    try:
        membership_before = _scan_descriptor_tree(root_descriptor)
        manifest_raw = _read_descriptor_relative_file(
            root_descriptor,
            manifest_path_value,
            maximum_bytes=_MAX_MANIFEST_BYTES,
            label="authority resource manifest",
        )
        manifest = AuthorityResourceManifestV1.from_canonical_bytes(manifest_raw)
        if manifest.manifest_sha256 != manifest_pin:
            raise AuthorityResourceError("authority resource manifest differs from its pin")

        expected_paths = {
            manifest_path_value,
            *(item.relative_path for item in manifest.resources),
        }
        expected_directories = {
            PurePosixPath(*parts[:depth]).as_posix()
            for relative_path in expected_paths
            for parts in (PurePosixPath(relative_path).parts[:-1],)
            for depth in range(1, len(parts) + 1)
        }
        observed_directories = {relative for relative, _identity in membership_before[1]}
        if membership_before[0] != expected_paths or observed_directories != expected_directories:
            raise AuthorityResourceError("authority resource membership differs from its manifest")

        resources_by_id: dict[str, bytes] = {}
        for record in manifest.resources:
            raw = _read_descriptor_relative_file(
                root_descriptor,
                record.relative_path,
                maximum_bytes=_MAX_RESOURCE_BYTES,
                label=f"authority resource {record.resource_id}",
            )
            if len(raw) != record.size_bytes or _sha256_bytes(raw) != record.content_sha256:
                raise AuthorityResourceError(
                    f"authority resource {record.resource_id} differs from its receipt"
                )
            _decode_canonical_object(
                raw,
                label=f"authority resource {record.resource_id}",
                maximum_bytes=_MAX_RESOURCE_BYTES,
            )
            resources_by_id[record.resource_id] = raw

        manifest_readback = _read_descriptor_relative_file(
            root_descriptor,
            manifest_path_value,
            maximum_bytes=_MAX_MANIFEST_BYTES,
            label="authority resource manifest readback",
        )
        membership_after = _scan_descriptor_tree(root_descriptor)
        root_after = os.fstat(root_descriptor)
        try:
            path_after = root_path.lstat()
        except OSError as exc:
            raise AuthorityResourceError(
                "authority resource root disappeared during readback"
            ) from exc
        if (
            manifest_readback != manifest_raw
            or membership_after != membership_before
            or _stat_identity(root_after) != _stat_identity(root_opened)
            or _stat_identity(path_after) != _stat_identity(root_opened)
        ):
            raise AuthorityResourceError(
                "authority resource root changed during authenticated readback"
            )
    finally:
        os.close(root_descriptor)

    return LoadedAuthorityResourcesV1._from_validated(
        manifest_relative_path=manifest_path_value,
        manifest=manifest,
        expected_manifest_sha256=manifest_pin,
        resources_by_id=resources_by_id,
    )
