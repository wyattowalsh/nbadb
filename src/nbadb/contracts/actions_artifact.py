"""Exact GitHub Actions artifact and member identities.

Every receipt that binds a workflow artifact must carry one of these
identities.  A verifier re-reads the artifact through the GitHub API and
compares repository, owner run, owner run attempt, artifact id, name, digest,
and size before trusting it.  Run attempt is never inferred from an artifact
name: it must be supplied by the producer that created the artifact and is
checked against the API's run-attempt record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Never, Self

from nbadb.contracts.receipt_digest import canonical_receipt_bytes

__all__ = [
    "ARTIFACT_DIGEST_PATTERN",
    "ACTIONS_ARTIFACT_SCHEMA_VERSION",
    "ActionsArtifactError",
    "ActionsArtifactIdentityV1",
    "ArtifactMemberIdentityV1",
    "parse_run_attempt_from_artifact_name",
]

#: Schema version for serialized artifact identities.
ACTIONS_ARTIFACT_SCHEMA_VERSION: Final = 1

#: Exact artifact digest form: ``sha256:`` plus 64 lowercase hex characters.
ARTIFACT_DIGEST_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}\Z", flags=re.ASCII)

#: Exact member/object digest form: 64 lowercase hex characters.
_MEMBER_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)

#: Canonical relative POSIX member path: no drive, no backslash, no traversal.
_MEMBER_PATH_PATTERN: Final = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]*\Z", flags=re.ASCII)

_IDENTITY_KEYS: Final = (
    "repository",
    "run_id",
    "run_attempt",
    "artifact_id",
    "artifact_name",
    "artifact_digest",
    "artifact_size_bytes",
)
_MEMBER_KEYS: Final = (
    "artifact",
    "member_path",
    "member_sha256",
    "member_size_bytes",
)


class ActionsArtifactError(ValueError):
    """An Actions artifact or member identity is malformed or unverified."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ActionsArtifactError(f"{field} must be a non-empty string")
    return value


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ActionsArtifactError(f"{field} must be a positive integer")
    return value


def _require_repository(value: object) -> str:
    text = _require_text(value, "repository")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text):
        raise ActionsArtifactError(f"repository must be 'owner/name', got {text!r}")
    return text


def _require_artifact_digest(value: object) -> str:
    text = _require_text(value, "artifact_digest")
    if not ARTIFACT_DIGEST_PATTERN.fullmatch(text):
        raise ActionsArtifactError(
            "artifact_digest must be 'sha256:' plus 64 lowercase hex characters"
        )
    return text


def _require_member_path(value: object) -> str:
    text = _require_text(value, "member_path")
    if not _MEMBER_PATH_PATTERN.fullmatch(text):
        raise ActionsArtifactError(
            f"member_path must be a canonical relative POSIX path, got {text!r}"
        )
    if text.startswith("/") or "\\" in text or text.split("/")[0] in {"", ".", ".."}:
        raise ActionsArtifactError(f"member_path must not be absolute or traversing, got {text!r}")
    segments = text.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ActionsArtifactError(
            f"member_path must not contain empty, '.', or '..' segments, got {text!r}"
        )
    if len(set(segments)) != len(segments):
        raise ActionsArtifactError(f"member_path must not repeat path segments, got {text!r}")
    return text


@dataclass(frozen=True, slots=True)
class ActionsArtifactIdentityV1:
    """Exact identity of one immutable GitHub Actions artifact."""

    repository: str
    run_id: int
    run_attempt: int
    artifact_id: int
    artifact_name: str
    artifact_digest: str
    artifact_size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", _require_repository(self.repository))
        object.__setattr__(self, "run_id", _require_positive_int(self.run_id, "run_id"))
        object.__setattr__(
            self, "run_attempt", _require_positive_int(self.run_attempt, "run_attempt")
        )
        object.__setattr__(
            self, "artifact_id", _require_positive_int(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "artifact_name", _require_text(self.artifact_name, "artifact_name")
        )
        object.__setattr__(self, "artifact_digest", _require_artifact_digest(self.artifact_digest))
        object.__setattr__(
            self,
            "artifact_size_bytes",
            _require_positive_int(self.artifact_size_bytes, "artifact_size_bytes"),
        )

    def to_payload(self) -> dict[str, object]:
        """Serialize to an exact-key mapping."""
        return {
            "schema_version": ACTIONS_ARTIFACT_SCHEMA_VERSION,
            "repository": self.repository,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "artifact_digest": self.artifact_digest,
            "artifact_size_bytes": self.artifact_size_bytes,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Parse an exact-key mapping; missing or extra keys fail."""
        if not isinstance(payload, dict):
            raise ActionsArtifactError("artifact identity payload must be a mapping")
        keys = set(payload)
        expected = {*_IDENTITY_KEYS, "schema_version"}
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise ActionsArtifactError(
                f"artifact identity keys mismatch: missing={missing} extra={extra}"
            )
        schema_version = payload.get("schema_version")
        if schema_version != ACTIONS_ARTIFACT_SCHEMA_VERSION:
            raise ActionsArtifactError(
                f"unsupported artifact identity schema version {schema_version!r}"
            )
        repository = _require_text(payload.get("repository"), "repository")
        run_id = _require_positive_int(payload.get("run_id"), "run_id")
        run_attempt = _require_positive_int(payload.get("run_attempt"), "run_attempt")
        artifact_id = _require_positive_int(payload.get("artifact_id"), "artifact_id")
        artifact_name = _require_text(payload.get("artifact_name"), "artifact_name")
        artifact_digest = _require_artifact_digest(payload.get("artifact_digest"))
        artifact_size = _require_positive_int(
            payload.get("artifact_size_bytes"), "artifact_size_bytes"
        )
        return cls(
            repository=repository,
            run_id=run_id,
            run_attempt=run_attempt,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            artifact_digest=artifact_digest,
            artifact_size_bytes=artifact_size,
        )

    def canonical_bytes(self) -> bytes:
        """Deterministic canonical bytes for digest binding."""
        return canonical_receipt_bytes(self.to_payload())

    def require_attempt(self, *, run_id: int, run_attempt: int) -> None:
        """Fail unless this identity is owned by exactly this run and attempt.

        The attempt must come from the API's run-attempt record or the
        producing workflow's runtime context — never from the artifact name.
        """
        if self.run_id != run_id or self.run_attempt != run_attempt:
            raise ActionsArtifactError(
                "artifact owner mismatch: identity names run "
                f"{self.run_id}/attempt {self.run_attempt}, verifier observed "
                f"run {run_id}/attempt {run_attempt}"
            )


@dataclass(frozen=True, slots=True)
class ArtifactMemberIdentityV1:
    """Exact identity of one regular member inside an immutable artifact."""

    artifact: ActionsArtifactIdentityV1
    member_path: str
    member_sha256: str
    member_size_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ActionsArtifactIdentityV1):
            raise ActionsArtifactError("artifact must be an ActionsArtifactIdentityV1")
        object.__setattr__(self, "member_path", _require_member_path(self.member_path))
        sha = _require_text(self.member_sha256, "member_sha256")
        if not _MEMBER_SHA256_PATTERN.fullmatch(sha):
            raise ActionsArtifactError("member_sha256 must be 64 lowercase hex characters")
        object.__setattr__(self, "member_sha256", sha)
        object.__setattr__(
            self,
            "member_size_bytes",
            _require_positive_int(self.member_size_bytes, "member_size_bytes"),
        )

    def to_payload(self) -> dict[str, object]:
        """Serialize to an exact-key mapping."""
        return {
            "schema_version": ACTIONS_ARTIFACT_SCHEMA_VERSION,
            "artifact": self.artifact.to_payload(),
            "member_path": self.member_path,
            "member_sha256": self.member_sha256,
            "member_size_bytes": self.member_size_bytes,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Parse an exact-key mapping; missing or extra keys fail."""
        if not isinstance(payload, dict):
            raise ActionsArtifactError("artifact member payload must be a mapping")
        keys = set(payload)
        expected = {*_MEMBER_KEYS, "schema_version"}
        if keys != expected:
            missing = sorted(expected - keys)
            extra = sorted(keys - expected)
            raise ActionsArtifactError(
                f"artifact member keys mismatch: missing={missing} extra={extra}"
            )
        schema_version = payload.get("schema_version")
        if schema_version != ACTIONS_ARTIFACT_SCHEMA_VERSION:
            raise ActionsArtifactError(
                f"unsupported artifact member schema version {schema_version!r}"
            )
        artifact = ActionsArtifactIdentityV1.from_payload(payload.get("artifact"))
        member_path = _require_member_path(payload.get("member_path"))
        member_sha256 = _require_text(payload.get("member_sha256"), "member_sha256")
        if not _MEMBER_SHA256_PATTERN.fullmatch(member_sha256):
            raise ActionsArtifactError("member_sha256 must be 64 lowercase hex characters")
        member_size_bytes = _require_positive_int(
            payload.get("member_size_bytes"), "member_size_bytes"
        )
        return cls(
            artifact=artifact,
            member_path=member_path,
            member_sha256=member_sha256,
            member_size_bytes=member_size_bytes,
        )

    def canonical_bytes(self) -> bytes:
        """Deterministic canonical bytes for digest binding."""
        return canonical_receipt_bytes(self.to_payload())


def parse_run_attempt_from_artifact_name(artifact_name: str) -> Never:
    """Deliberately unimplemented: attempt must never be inferred from names.

    Exists only so call sites attempting the inference fail loudly and tests
    can prove the inference is rejected by design.
    """
    raise ActionsArtifactError(
        f"run attempt must never be inferred from an artifact name: {artifact_name!r}"
    )
