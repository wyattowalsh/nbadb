"""Exact continuation-source authority for full-extraction ``continue`` dispatches.

A continuation never guesses its source.  The dispatch supplies exactly five
identity fields (source run id, source run attempt, manifest artifact name,
manifest artifact id, manifest artifact digest); this module re-reads the
exact artifact through the GitHub Actions API, proves it belongs to the named
source run and attempt, hashes the expected member, and parses one committed
schema-v3 checkpoint transaction whose chain, source SHA, generation, and
artifact-name encoding all agree.  The attempt is never inferred from the
artifact name or any ``latest``-style lookup.
"""

from __future__ import annotations

import hashlib
import io
import re
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from nbadb.contracts.actions_artifact import (
    ActionsArtifactIdentityV1,
    ArtifactMemberIdentityV1,
)
from nbadb.orchestrate.checkpoint_contract import (
    CheckpointState,
    CheckpointTransaction,
)

__all__ = [
    "CONTINUATION_SOURCE_SCHEMA_VERSION",
    "ArtifactApiTransport",
    "ContinuationDispatchInputs",
    "ContinuationSourceError",
    "VerifiedContinuationSource",
    "continuation_inputs_from_env",
    "verify_continuation_source",
]

CONTINUATION_SOURCE_SCHEMA_VERSION: Final = 1

_REPOSITORY: Final = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_ARTIFACT_NAME_ITERATION: Final = re.compile(r"^(?P<prefix>.+)-iter-(?P<generation>[1-9][0-9]*)\Z")
_SAFE_MEMBER_SUFFIXES: Final = (".json",)


class ContinuationSourceError(ValueError):
    """A continuation source identity or its evidence is invalid."""


class ArtifactApiTransport(Protocol):
    """Read-only GitHub Actions API seam; tests inject deterministic fakes."""

    def artifact(self, repository: str, artifact_id: int) -> Mapping[str, Any]:
        """Return the exact artifact JSON for one artifact id."""

    def workflow_run(self, repository: str, run_id: int) -> Mapping[str, Any]:
        """Return the exact owner workflow-run JSON for one run id."""

    def download(self, repository: str, artifact_id: int) -> bytes:
        """Return the raw artifact archive bytes for one artifact id."""


@dataclass(frozen=True, slots=True)
class ContinuationDispatchInputs:
    """The exact five-field continuation dispatch contract."""

    repository: str
    source_run_id: int
    source_run_attempt: int
    manifest_artifact_name: str
    manifest_artifact_id: int
    manifest_artifact_digest: str
    chain_id: str
    source_sha: str
    expected_member_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or not _REPOSITORY.fullmatch(self.repository):
            raise ContinuationSourceError("repository must be 'owner/name'")
        for field in ("source_run_id", "source_run_attempt", "manifest_artifact_id"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ContinuationSourceError(f"{field} must be a positive integer")
        if not isinstance(self.manifest_artifact_name, str) or not self.manifest_artifact_name:
            raise ContinuationSourceError("manifest_artifact_name must be a non-empty string")
        digest = self.manifest_artifact_digest
        if not isinstance(digest, str):
            raise ContinuationSourceError("manifest_artifact_digest must be 'sha256:<64 hex>'")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise ContinuationSourceError("manifest_artifact_digest must be 'sha256:<64 hex>'")
        if not isinstance(self.chain_id, str) or not self.chain_id:
            raise ContinuationSourceError("chain_id must be a non-empty string")
        if not isinstance(self.source_sha, str) or not re.fullmatch(
            r"[0-9a-f]{40}", self.source_sha
        ):
            raise ContinuationSourceError("source_sha must be a 40 hex character git sha")
        if not isinstance(self.expected_member_path, str) or not self.expected_member_path.endswith(
            _SAFE_MEMBER_SUFFIXES
        ):
            raise ContinuationSourceError("expected_member_path must name a JSON member")
        if self.expected_member_path.startswith(("/", "\\")) or ".." in self.expected_member_path:
            raise ContinuationSourceError("expected_member_path must be a safe relative path")


@dataclass(frozen=True, slots=True)
class VerifiedContinuationSource:
    """The exact evidence a continuation dispatch is allowed to consume."""

    schema_version: int
    member: ArtifactMemberIdentityV1
    transaction: CheckpointTransaction
    member_payload_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != CONTINUATION_SOURCE_SCHEMA_VERSION:
            raise ContinuationSourceError("unsupported verified-source schema version")
        if not isinstance(self.member, ArtifactMemberIdentityV1):
            raise ContinuationSourceError("member must be an ArtifactMemberIdentityV1")
        if not isinstance(self.transaction, CheckpointTransaction):
            raise ContinuationSourceError("transaction must be a CheckpointTransaction")
        if self.transaction.state is not CheckpointState.COMMITTED:
            raise ContinuationSourceError(
                "continuation requires a committed checkpoint transaction"
            )
        if self.transaction.receipt is None:
            raise ContinuationSourceError(
                "committed continuation source lacks its artifact receipt"
            )


def _safe_member_bytes(archive_bytes: bytes, expected_path: str) -> bytes:
    """Extract exactly one expected regular member; every unsafe shape fails."""

    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ContinuationSourceError("manifest artifact is not a readable archive") from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ContinuationSourceError("manifest artifact contains duplicate members")
        if names.count(expected_path) != 1:
            raise ContinuationSourceError(
                f"manifest artifact must contain exactly one {expected_path!r} member"
            )

        normalized_names: set[str] = set()
        for info in infos:
            name = info.filename
            segments = name.split("/")
            if (
                name.startswith(("/", "\\"))
                or "\\" in name
                or not name
                or any(segment in {"", ".", ".."} for segment in segments)
            ):
                raise ContinuationSourceError(f"archive member path is unsafe: {name!r}")
            if name in normalized_names:
                raise ContinuationSourceError("manifest artifact contains destination collisions")
            normalized_names.add(name)
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if info.is_dir() or file_type not in {0, stat.S_IFREG}:
                raise ContinuationSourceError(f"archive member must be a regular file: {name!r}")
            if info.file_size > 8 * 1024 * 1024:
                raise ContinuationSourceError(
                    f"archive member exceeds the 8 MiB evidence bound: {name!r}"
                )

        for name in normalized_names:
            segments = name.split("/")
            for boundary in range(1, len(segments)):
                if "/".join(segments[:boundary]) in normalized_names:
                    raise ContinuationSourceError("archive has a file/dir parent collision")

        try:
            return archive.read(expected_path)
        except (KeyError, RuntimeError, OSError) as exc:
            raise ContinuationSourceError("expected member could not be read") from exc


def verify_continuation_source(
    inputs: ContinuationDispatchInputs,
    transport: ArtifactApiTransport,
    *,
    current_run_id: int,
) -> VerifiedContinuationSource:
    """Re-read and verify one exact continuation source before any effect."""

    if (
        isinstance(current_run_id, bool)
        or not isinstance(current_run_id, int)
        or current_run_id < 1
    ):
        raise ContinuationSourceError("current_run_id must be a positive integer")
    if inputs.source_run_id == current_run_id:
        raise ContinuationSourceError(
            "a continuation source must name a different run than the current run"
        )

    artifact_json = transport.artifact(inputs.repository, inputs.manifest_artifact_id)
    if not isinstance(artifact_json, Mapping):
        raise ContinuationSourceError("artifact API response must be an object")
    api_id = artifact_json.get("id")
    api_name = artifact_json.get("name")
    api_workflow_run = artifact_json.get("workflow_run")
    if not isinstance(api_workflow_run, Mapping):
        raise ContinuationSourceError("artifact API owner run is missing or malformed")
    api_run_id = api_workflow_run.get("id")
    api_digest = artifact_json.get("digest")
    api_size = artifact_json.get("size_in_bytes")
    api_expired = artifact_json.get("expired")
    if api_id != inputs.manifest_artifact_id:
        raise ContinuationSourceError("artifact API returned a different artifact id")
    if api_name != inputs.manifest_artifact_name:
        raise ContinuationSourceError("artifact API returned a different artifact name")
    if api_run_id != inputs.source_run_id:
        raise ContinuationSourceError("artifact is not owned by the named source run")
    if not isinstance(api_digest, str) or not api_digest.startswith("sha256:"):
        raise ContinuationSourceError("artifact API digest is missing or malformed")
    if api_digest != inputs.manifest_artifact_digest:
        raise ContinuationSourceError("artifact digest drifted from the dispatch input")
    if api_expired is True:
        raise ContinuationSourceError("continuation source artifact has expired")
    if isinstance(api_size, bool) or not isinstance(api_size, int) or api_size < 1:
        raise ContinuationSourceError("artifact API size is missing or malformed")

    run_json = transport.workflow_run(inputs.repository, inputs.source_run_id)
    if not isinstance(run_json, Mapping):
        raise ContinuationSourceError("owner workflow-run API response must be an object")
    if run_json.get("id") != inputs.source_run_id:
        raise ContinuationSourceError("workflow-run API returned a different source run")
    if run_json.get("run_attempt") != inputs.source_run_attempt:
        raise ContinuationSourceError(
            "source run attempt differs from the exact continuation dispatch input"
        )
    if run_json.get("event") != "workflow_dispatch":
        raise ContinuationSourceError("source run was not produced by workflow_dispatch")
    if run_json.get("head_sha") != inputs.source_sha:
        raise ContinuationSourceError("source run head SHA differs from the dispatch source SHA")

    identity = ActionsArtifactIdentityV1(
        repository=inputs.repository,
        run_id=inputs.source_run_id,
        run_attempt=inputs.source_run_attempt,
        artifact_id=inputs.manifest_artifact_id,
        artifact_name=inputs.manifest_artifact_name,
        artifact_digest=inputs.manifest_artifact_digest,
        artifact_size_bytes=api_size,
    )

    archive_bytes = transport.download(inputs.repository, inputs.manifest_artifact_id)
    if len(archive_bytes) != identity.artifact_size_bytes:
        raise ContinuationSourceError("downloaded artifact size does not match the API identity")
    archive_digest = f"sha256:{hashlib.sha256(archive_bytes).hexdigest()}"
    if archive_digest != inputs.manifest_artifact_digest:
        raise ContinuationSourceError("downloaded artifact bytes do not match the dispatch digest")
    member_bytes = _safe_member_bytes(archive_bytes, inputs.expected_member_path)
    member = ArtifactMemberIdentityV1(
        artifact=identity,
        member_path=inputs.expected_member_path,
        member_sha256=hashlib.sha256(member_bytes).hexdigest(),
        member_size_bytes=len(member_bytes),
    )

    import json

    try:
        payload = json.loads(member_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContinuationSourceError("continuation manifest member is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ContinuationSourceError("continuation manifest member must be an object")
    try:
        transaction = CheckpointTransaction.from_dict(dict(payload))
    except Exception as exc:  # noqa: BLE001 - re-raised as the module's contract error
        raise ContinuationSourceError(
            f"continuation checkpoint transaction rejected: {exc}"
        ) from exc

    name_match = _ARTIFACT_NAME_ITERATION.match(inputs.manifest_artifact_name)
    if name_match is None:
        raise ContinuationSourceError(
            "manifest artifact name must encode chain and iteration generation"
        )
    if int(name_match.group("generation")) != transaction.identity.generation:
        raise ContinuationSourceError("artifact-name generation does not match the transaction")
    if transaction.identity.chain_id != inputs.chain_id:
        raise ContinuationSourceError("transaction chain does not match the dispatch chain")
    if transaction.identity.source_sha != inputs.source_sha:
        raise ContinuationSourceError("transaction source SHA does not match the dispatch input")

    return VerifiedContinuationSource(
        schema_version=CONTINUATION_SOURCE_SCHEMA_VERSION,
        member=member,
        transaction=transaction,
        member_payload_sha256=member.member_sha256,
    )


def continuation_inputs_from_env(
    env: Mapping[str, str],
    *,
    repository: str,
    chain_id: str,
    source_sha: str,
    expected_member_path: str = "manifests/next.json",
) -> ContinuationDispatchInputs:
    """Build the exact five-field inputs from validated dispatch environment."""

    def _required(name: str) -> str:
        value = (env.get(name) or "").strip()
        if not value:
            raise ContinuationSourceError(f"{name} is required for a continuation dispatch")
        return value

    def _positive(name: str) -> int:
        raw = _required(name)
        if not re.fullmatch(r"[1-9][0-9]*", raw):
            raise ContinuationSourceError(f"{name} must be a positive integer")
        return int(raw)

    return ContinuationDispatchInputs(
        repository=repository,
        source_run_id=_positive("FULL_EXTRACTION_RESUME_SOURCE_RUN_ID"),
        source_run_attempt=_positive("FULL_EXTRACTION_RESUME_SOURCE_RUN_ATTEMPT"),
        manifest_artifact_name=_required("FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_NAME"),
        manifest_artifact_id=_positive("FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_ID"),
        manifest_artifact_digest=_required(
            "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_DIGEST"
        ),
        chain_id=chain_id,
        source_sha=source_sha,
        expected_member_path=expected_member_path,
    )
