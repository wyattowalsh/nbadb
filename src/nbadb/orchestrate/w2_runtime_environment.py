"""Fail-closed admission for production W2 preparation runtime resources.

The boundary accepts only an already validated Raw Authority V2 execution and
assurance authority.  Its two filesystem authorities are explicit, run-owned
environment roots; no settings, data directory, secret, or local-development
fallback participates in admission.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Never, cast

from nbadb.contracts.assurance import FIELD_FATE_STRUCTURE_NAME
from nbadb.contracts.field_fate_structure import (
    FieldFateStructureV1,
    compile_field_fate_structure,
    validate_field_fate_structure,
)
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.declared_bodyless_packet_store import (
    DeclaredBodylessPacketStore,
)
from nbadb.orchestrate.raw_request_assurance import (
    RawRequestAssuranceAuthorityV2,
    validate_raw_request_assurance_authority,
)
from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
from nbadb.orchestrate.w2_source_call_preparation import (
    W2SourceCallPreparationRuntime,
)

W2_BODY_BLOB_ROOT_ENV: Final = "NBADB_W2_BODY_BLOB_ROOT"
W2_DECLARED_BODYLESS_PACKET_ROOT_ENV: Final = "NBADB_W2_DECLARED_BODYLESS_PACKET_ROOT"

_ROOT_ENV_NAMES: Final = (
    W2_BODY_BLOB_ROOT_ENV,
    W2_DECLARED_BODYLESS_PACKET_ROOT_ENV,
)
_MAX_ROOT_UTF8_BYTES: Final = 4096
_DIRECTORY_MODE: Final = 0o700
_ASSURANCE_TEXT_FIELDS: Final = (
    "source_sha",
    "assurance_admission_sha256",
    "assurance_manifest_sha256",
    "generation_semantic_sha256",
    "generation_index_sha256",
    "provider_evidence_sha256",
    "provider_authority_sha256",
    "field_authority_sha256",
    "model_authority_sha256",
    "validation_provenance_sha256",
)

_BODY_BLOB_STORE_TYPE: Final = BodyBlobStore
_DECLARED_BODYLESS_PACKET_STORE_TYPE: Final = DeclaredBodylessPacketStore
_FIELD_FATE_STRUCTURE_TYPE: Final = FieldFateStructureV1
_RUNTIME_TYPE: Final = W2SourceCallPreparationRuntime


class W2RuntimeEnvironmentError(ValueError):
    """The active execution cannot admit exact production W2 resources."""


def _fail(message: str) -> Never:
    raise W2RuntimeEnvironmentError(message) from None


@dataclass(frozen=True, slots=True)
class _PinnedRoot:
    path: Path
    identity: tuple[int, int, int, int, int]


def _replay_execution_identity(value: object) -> RawRequestExecutionIdentityV1:
    if type(value) is not RawRequestExecutionIdentityV1:
        _fail("W2 runtime requires an exact active execution identity")
    execution = value
    try:
        exact = RawRequestExecutionIdentityV1(
            source_sha=execution.source_sha,
            run_id=execution.run_id,
            run_attempt=execution.run_attempt,
            chain_id=execution.chain_id,
            lane_id=execution.lane_id,
        )
    except Exception:
        _fail("W2 runtime execution identity failed exact replay")
    if exact != execution or exact is execution:
        _fail("W2 runtime execution identity differs from exact replay")
    return exact


def _exact_child_identities(
    value: object,
    *,
    label: str,
) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple:
        _fail(f"W2 runtime assurance {label} has a foreign exact type")
    identities = value
    if any(
        type(item) is not tuple
        or len(item) != 2
        or type(item[0]) is not str
        or type(item[1]) is not str
        for item in identities
    ):
        _fail(f"W2 runtime assurance {label} has a foreign child identity")
    return cast("tuple[tuple[str, str], ...]", identities)


def _replay_assurance_authority(value: object) -> RawRequestAssuranceAuthorityV2:
    if type(value) is not RawRequestAssuranceAuthorityV2:
        _fail("W2 runtime requires an exact Raw Authority V2 assurance authority")
    authority = value
    try:
        validated = validate_raw_request_assurance_authority(authority)
    except Exception:
        _fail("W2 runtime assurance authority failed independent validation")
    if type(validated) is not RawRequestAssuranceAuthorityV2 or validated is not authority:
        _fail("W2 runtime assurance validation returned foreign authority")
    try:
        text_values = tuple(getattr(authority, name) for name in _ASSURANCE_TEXT_FIELDS)
        field_children = _exact_child_identities(
            authority.field_children,
            label="field children",
        )
        model_children = _exact_child_identities(
            authority.model_children,
            label="model children",
        )
    except W2RuntimeEnvironmentError:
        raise
    except Exception:
        _fail("W2 runtime assurance authority failed exact preflight")
    if any(type(item) is not str for item in text_values):
        _fail("W2 runtime assurance authority has a foreign scalar type")
    try:
        exact = RawRequestAssuranceAuthorityV2(
            source_sha=authority.source_sha,
            assurance_admission_sha256=authority.assurance_admission_sha256,
            assurance_manifest_sha256=authority.assurance_manifest_sha256,
            generation_semantic_sha256=authority.generation_semantic_sha256,
            generation_index_sha256=authority.generation_index_sha256,
            provider_evidence_sha256=authority.provider_evidence_sha256,
            provider_authority_sha256=authority.provider_authority_sha256,
            field_children=field_children,
            model_children=model_children,
            field_authority_sha256=authority.field_authority_sha256,
            model_authority_sha256=authority.model_authority_sha256,
            validation_provenance_sha256=authority.validation_provenance_sha256,
        )
    except Exception:
        _fail("W2 runtime assurance authority failed exact replay")
    if exact != authority or exact is authority:
        _fail("W2 runtime assurance authority differs from exact replay")
    try:
        replayed = validate_raw_request_assurance_authority(exact)
    except Exception:
        _fail("W2 runtime replayed assurance failed independent validation")
    if type(replayed) is not RawRequestAssuranceAuthorityV2 or replayed is not exact:
        _fail("W2 runtime replay validation returned foreign authority")
    return exact


def _read_root_values(environ: Mapping[str, str] | None) -> tuple[str, str]:
    if environ is not None and not isinstance(environ, Mapping):
        _fail("W2 runtime environment must be one mapping authority")
    source = os.environ if environ is None else environ
    try:
        values = tuple(source.get(name) for name in _ROOT_ENV_NAMES)
    except Exception:
        _fail("W2 runtime root environment is unreadable")
    body_root, packet_root = values
    if type(body_root) is not str or type(packet_root) is not str:
        _fail("W2 runtime root environment is incomplete")
    return body_root, packet_root


def _canonical_root(raw: str, *, label: str) -> Path:
    if type(raw) is not str:
        _fail(f"W2 runtime {label} root has a foreign exact type")
    try:
        encoded = raw.encode("utf-8", errors="strict")
        path = Path(raw)
    except (TypeError, UnicodeError, ValueError):
        _fail(f"W2 runtime {label} root is not an exact POSIX path")
    if (
        not encoded
        or len(encoded) > _MAX_ROOT_UTF8_BYTES
        or b"\x00" in encoded
        or os.name != "posix"
        or not path.is_absolute()
        or path.anchor != os.sep
        or path == Path("/")
        or raw != str(path)
        or any(part in {"", ".", ".."} for part in path.parts[1:])
    ):
        _fail(f"W2 runtime {label} root is not one canonical bounded absolute path")
    return path


def _root_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    try:
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    except Exception:
        _fail("W2 runtime root metadata is malformed")


def _pin_root(path: Path, *, label: str) -> _PinnedRoot:
    current = Path(path.anchor)
    root_info: os.stat_result | None = None
    try:
        for component in path.parts[1:]:
            current /= component
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                _fail(f"W2 runtime {label} root traverses a non-directory authority")
            root_info = info
    except W2RuntimeEnvironmentError:
        raise
    except Exception:
        _fail(f"W2 runtime {label} root is unavailable")
    if root_info is None:
        _fail(f"W2 runtime {label} root is unavailable")
    try:
        effective_uid = os.geteuid()
    except Exception:
        _fail("W2 runtime cannot establish POSIX owner authority")
    if root_info.st_uid != effective_uid or stat.S_IMODE(root_info.st_mode) != _DIRECTORY_MODE:
        _fail(f"W2 runtime {label} root lacks exact owner-only 0700 authority")
    return _PinnedRoot(path=path, identity=_root_identity(root_info))


def _require_disjoint_roots(body: _PinnedRoot, packet: _PinnedRoot) -> None:
    if (
        body.identity[:2] == packet.identity[:2]
        or body.path == packet.path
        or body.path in packet.path.parents
        or packet.path in body.path.parents
    ):
        _fail("W2 runtime roots overlap or alias")


def _require_root_unchanged(root: _PinnedRoot, *, label: str) -> None:
    current = _pin_root(root.path, label=label)
    if current != root:
        _fail(f"W2 runtime {label} root changed after admission")


def _compile_current_field_fate() -> FieldFateStructureV1:
    # An explicit empty upstream root selects the installed pinned authority and
    # prevents this boundary from consulting NBADB_NBA_API_DOCS_ROOT.
    return compile_field_fate_structure(upstream_root="")


def _replay_current_field_fate() -> FieldFateStructureV1:
    try:
        current = _compile_current_field_fate()
    except Exception:
        _fail("W2 runtime current field-fate authority could not be compiled")
    if type(current) is not _FIELD_FATE_STRUCTURE_TYPE:
        _fail("W2 runtime field-fate compiler returned a foreign authority")
    try:
        exact = _FIELD_FATE_STRUCTURE_TYPE(
            provider_sources=current.provider_sources,
            route_bindings=current.route_bindings,
            storage_sinks=current.storage_sinks,
            lossless_bindings=current.lossless_bindings,
            blockers=current.blockers,
        )
        validate_field_fate_structure(exact, upstream_root="")
    except Exception:
        _fail("W2 runtime current field-fate authority failed exact replay")
    if exact != current or exact is current:
        _fail("W2 runtime current field-fate authority differs from exact replay")
    return exact


def _require_field_fate_child(
    assurance: RawRequestAssuranceAuthorityV2,
    field_fate: FieldFateStructureV1,
) -> None:
    matches = tuple(
        digest for name, digest in assurance.field_children if name == FIELD_FATE_STRUCTURE_NAME
    )
    if len(matches) != 1 or matches[0] != field_fate.identity_sha256:
        _fail("W2 runtime field-fate authority differs from assurance child identity")


def _construct_body_blob_store(
    root: Path,
    execution: RawRequestExecutionIdentityV1,
) -> BodyBlobStore:
    return _BODY_BLOB_STORE_TYPE(
        root,
        source_sha=execution.source_sha,
        run_id=execution.run_id,
        run_attempt=execution.run_attempt,
        chain_id=execution.chain_id,
        lane_id=execution.lane_id,
    )


def _construct_declared_bodyless_packet_store(
    root: Path,
    execution: RawRequestExecutionIdentityV1,
) -> DeclaredBodylessPacketStore:
    return _DECLARED_BODYLESS_PACKET_STORE_TYPE(
        root,
        source_sha=execution.source_sha,
        run_id=execution.run_id,
        run_attempt=execution.run_attempt,
        chain_id=execution.chain_id,
        lane_id=execution.lane_id,
    )


def _construct_runtime(
    body_store: BodyBlobStore,
    packet_store: DeclaredBodylessPacketStore,
    field_fate: FieldFateStructureV1,
) -> W2SourceCallPreparationRuntime:
    return _RUNTIME_TYPE(
        body_blob_store=body_store,
        declared_bodyless_packet_store=packet_store,
        field_fate=field_fate,
        known_secrets=(),
    )


def w2_source_call_preparation_runtime_from_env(
    execution_identity: RawRequestExecutionIdentityV1 | None,
    assurance_authority: RawRequestAssuranceAuthorityV2 | None,
    environ: Mapping[str, str] | None = None,
) -> W2SourceCallPreparationRuntime | None:
    """Admit the exact run-owned resources for one active W2 execution.

    ``None`` is returned only for a genuinely inactive execution.  Once an
    execution identity exists, every missing, foreign, mutable, or mismatched
    authority fails closed.
    """

    if execution_identity is None:
        return None
    execution = _replay_execution_identity(execution_identity)
    assurance = _replay_assurance_authority(assurance_authority)
    if assurance.source_sha != execution.source_sha:
        _fail("W2 runtime assurance source differs from active execution")

    body_raw, packet_raw = _read_root_values(environ)
    body_root = _pin_root(_canonical_root(body_raw, label="body-blob"), label="body-blob")
    packet_root = _pin_root(
        _canonical_root(packet_raw, label="declared-bodyless packet"),
        label="declared-bodyless packet",
    )
    _require_disjoint_roots(body_root, packet_root)

    field_fate = _replay_current_field_fate()
    _require_field_fate_child(assurance, field_fate)

    try:
        body_store = _construct_body_blob_store(body_root.path, execution)
    except Exception:
        _fail("W2 runtime body-blob store construction failed")
    if type(body_store) is not _BODY_BLOB_STORE_TYPE:
        _fail("W2 runtime body-blob store construction returned a foreign type")
    try:
        packet_store = _construct_declared_bodyless_packet_store(packet_root.path, execution)
    except Exception:
        _fail("W2 runtime declared-bodyless store construction failed")
    if type(packet_store) is not _DECLARED_BODYLESS_PACKET_STORE_TYPE:
        _fail("W2 runtime declared-bodyless store construction returned a foreign type")

    _require_root_unchanged(body_root, label="body-blob")
    _require_root_unchanged(packet_root, label="declared-bodyless packet")
    try:
        runtime = _construct_runtime(body_store, packet_store, field_fate)
    except Exception:
        _fail("W2 source-call preparation runtime construction failed")
    if (
        type(runtime) is not _RUNTIME_TYPE
        or runtime.body_blob_store is not body_store
        or runtime.declared_bodyless_packet_store is not packet_store
        or runtime.field_fate is not field_fate
        or type(runtime.known_secrets) is not tuple
        or runtime.known_secrets
    ):
        _fail("W2 source-call preparation runtime returned foreign authority")
    _require_root_unchanged(body_root, label="body-blob")
    _require_root_unchanged(packet_root, label="declared-bodyless packet")
    return runtime


__all__ = [
    "W2_BODY_BLOB_ROOT_ENV",
    "W2_DECLARED_BODYLESS_PACKET_ROOT_ENV",
    "W2RuntimeEnvironmentError",
    "w2_source_call_preparation_runtime_from_env",
]
