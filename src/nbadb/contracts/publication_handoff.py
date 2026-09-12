"""Immutable terminal publication handoff contract.

``TerminalPublicationHandoffV1`` is the sole input a publication or
reconciliation dispatch accepts.  A producer (full extraction or a recurring
successor build) uploads the checkpoint, next manifest, private evidence, and
sanitized candidate artifacts first, re-reads each exact identity through the
GitHub API, and only then seals this handoff binding all of them.  The digest
is the SHA-256 of the canonical bytes of every other field, so any
substitution -- a swapped candidate digest, a different run attempt, a
noncommitted checkpoint -- breaks the seal and fails verification.

Successor-produced handoffs additionally bind an exact private-baseline
artifact member owned by the *parent* run; that member intentionally names a
different run than the producer and is the only artifact allowed to do so.
"""

from __future__ import annotations

import re
import types
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, ClassVar, Final, Protocol, Self, cast, get_args, get_origin, get_type_hints

from nbadb.contracts.actions_artifact import (
    ActionsArtifactIdentityV1,
    ArtifactMemberIdentityV1,
)
from nbadb.contracts.receipt_digest import (
    CanonicalReceiptError,
    canonical_receipt_digest,
    verify_receipt_digest,
)

__all__ = [
    "PUBLICATION_HANDOFF_SCHEMA_VERSION",
    "CHECKPOINT_STATES",
    "CHECKPOINT_STATE_COMMITTED",
    "PublicationHandoffError",
    "CheckpointBindingV1",
    "TerminalPublicationHandoffV1",
]

#: Schema version for serialized handoffs.
PUBLICATION_HANDOFF_SCHEMA_VERSION: Final = 1

#: The only checkpoint state a terminal handoff may bind.
CHECKPOINT_STATE_COMMITTED: Final = "committed"

#: Known checkpoint lifecycle states; only ``committed`` seals a handoff.
CHECKPOINT_STATES: Final = frozenset({"candidate", "built", "uploaded_verified", "committed"})

_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_GIT_SHA: Final = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
_REPOSITORY: Final = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z", flags=re.ASCII)

#: Mutable-looking artifact names never identify an immutable artifact.
_MUTABLE_NAME_TOKEN: Final = re.compile(
    r"(?:^|[^a-z0-9])(?:latest|current|newest|head|tip)(?:[^a-z0-9]|$)", flags=re.IGNORECASE
)


class PublicationHandoffError(ValueError):
    """A terminal publication handoff is malformed, tampered, or incomplete."""


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PublicationHandoffError(f"{field} must be a non-empty string")
    return value


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise PublicationHandoffError(f"{field} must be 64 lowercase hex characters")
    return value


def _require_git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
        raise PublicationHandoffError(f"{field} must be a 40 hex character git sha")
    return value


def _require_int(value: object, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PublicationHandoffError(f"{field} must be an integer >= {minimum}")
    return value


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PublicationHandoffError(f"{field} must be a boolean")
    return value


def _require_repository(value: object, field: str) -> str:
    text = _require_str(value, field)
    if not _REPOSITORY.fullmatch(text):
        raise PublicationHandoffError(f"{field} must be 'owner/name', got {text!r}")
    return text


def _require_workflow_path(value: object) -> str:
    text = _require_str(value, "workflow_path")
    if not text.startswith(".github/workflows/") or not text.endswith(".yml"):
        raise PublicationHandoffError(
            f"workflow_path must name a workflow file under .github/workflows/, got {text!r}"
        )
    if text.split("/")[0] in {"", ".", ".."} or any(
        segment in {"", ".", ".."} for segment in text.split("/")
    ):
        raise PublicationHandoffError(f"workflow_path must not traverse, got {text!r}")
    return text


def _require_immutable_artifact_name(name: str, field: str) -> None:
    if _MUTABLE_NAME_TOKEN.search(name):
        raise PublicationHandoffError(
            f"{field} names a mutable artifact ({name!r}); mutable 'latest'-style "
            "names never identify an immutable artifact"
        )


class _PayloadCapable(Protocol):
    """Runtime shape of the exact-key payload dataclasses used here."""

    def to_payload(self) -> dict[str, object]: ...

    @classmethod
    def from_payload(cls, payload: object) -> Self: ...


def _to_shape(value: object) -> object:
    """Convert a handoff value into plain JSON shapes.

    Nested components that own an exact-key ``to_payload`` serialize through
    it so their payloads stay self-describing (including their own
    ``schema_version``) and decode through their own ``from_payload``.
    """
    if is_dataclass(value) and hasattr(type(value), "to_payload"):
        return _to_shape(cast("_PayloadCapable", value).to_payload())
    if is_dataclass(value):
        return {field.name: _to_shape(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_to_shape(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_shape(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise PublicationHandoffError(f"handoff values must be JSON shapes, got {type(value)!r}")


def _decode_value(annotation: object, value: object, field: str) -> object:
    """Decode a payload value against a field annotation."""
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is types.UnionType:
        dataclass_args = [arg for arg in args if is_dataclass(arg)]
        if value is None and type(None) in args:
            return None
        if len(dataclass_args) == 1 and isinstance(value, dict):
            capable = cast("type[_PayloadCapable]", dataclass_args[0])
            return capable.from_payload(value)
        return value
    if is_dataclass(annotation):
        if not isinstance(value, dict):
            raise PublicationHandoffError(f"{field} must serialize to a mapping")
        return cast("type[_PayloadCapable]", annotation).from_payload(value)
    if origin is tuple:
        if not isinstance(value, list):
            raise PublicationHandoffError(f"{field} must serialize to a list")
        item_annotation = args[0]
        decoded: list[object] = []
        for item in value:
            if is_dataclass(item_annotation):
                decoded.append(item_annotation.from_payload(item))  # type: ignore[attr-defined]
            else:
                decoded.append(item)
        return tuple(decoded)
    return value


class _HandoffPayloadMixin:
    """Exact-key payload support for handoff components."""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        raise NotImplementedError

    def to_payload(self) -> dict[str, object]:
        """Serialize to an exact-key mapping."""
        return {
            field.name: _to_shape(getattr(self, field.name)) for field in fields(cast("Any", self))
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Parse an exact-key mapping; missing or extra keys fail."""
        if not isinstance(payload, dict):
            raise PublicationHandoffError(f"{cls.__name__} payload must be a mapping")
        expected = {field.name for field in fields(cast("Any", cls))}
        if set(payload) != expected:
            missing = sorted(expected - set(payload))
            extra = sorted(set(payload) - expected)
            raise PublicationHandoffError(
                f"{cls.__name__} keys mismatch: missing={missing} extra={extra}"
            )
        hints = get_type_hints(cls)
        kwargs = {name: _decode_value(hints[name], payload.get(name), name) for name in expected}
        return cls(**kwargs)  # type: ignore[no-any-return]


class _SealedHandoffMixin(_HandoffPayloadMixin):
    """Exact-key payload plus self-digest sealing for the top-level handoff."""

    _DIGEST_FIELD: ClassVar[str]

    def __post_init__(self) -> None:
        # Integrity before interpretation: a sealed handoff parsed from an
        # untrusted payload must fail its digest seal before domain joins
        # run, so any substitution surfaces as a seal mismatch.
        try:
            verify_receipt_digest(self, digest_field=self._DIGEST_FIELD)
        except CanonicalReceiptError as exc:
            raise PublicationHandoffError(str(exc)) from exc
        self._validate()

    def to_payload(self) -> dict[str, object]:
        payload = super().to_payload()
        payload["schema_version"] = PUBLICATION_HANDOFF_SCHEMA_VERSION
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        if not isinstance(payload, dict):
            raise PublicationHandoffError(f"{cls.__name__} payload must be a mapping")
        expected = {field.name for field in fields(cast("Any", cls))} | {"schema_version"}
        if set(payload) != expected:
            missing = sorted(expected - set(payload))
            extra = sorted(set(payload) - expected)
            raise PublicationHandoffError(
                f"{cls.__name__} keys mismatch: missing={missing} extra={extra}"
            )
        schema_version = payload.get("schema_version")
        if schema_version != PUBLICATION_HANDOFF_SCHEMA_VERSION:
            raise PublicationHandoffError(
                f"unsupported {cls.__name__} schema version {schema_version!r}"
            )
        hints = get_type_hints(cls)
        kwargs = {
            name: _decode_value(hints[name], payload.get(name), name)
            for name in expected - {"schema_version"}
        }
        return cls(**kwargs)  # type: ignore[no-any-return]

    @classmethod
    def build(cls, **values: Any) -> Self:
        """Construct a handoff with its self digest computed from the evidence.

        ``values`` must provide every field except the digest field itself.
        Fields are validated before sealing so malformed values fail domain
        validation rather than the canonical encoder.
        """
        expected = {field.name for field in fields(cast("Any", cls))} - {cls._DIGEST_FIELD}
        if set(values) != expected:
            missing = sorted(expected - set(values))
            extra = sorted(set(values) - expected)
            raise PublicationHandoffError(
                f"{cls.__name__}.build keys mismatch: missing={missing} extra={extra}"
            )
        proto = object.__new__(cls)
        for name in expected:
            object.__setattr__(proto, name, values[name])
        object.__setattr__(proto, cls._DIGEST_FIELD, "0" * 64)
        proto._validate()
        digest = canonical_receipt_digest(proto, digest_field=cls._DIGEST_FIELD)
        return cls(**{**values, cls._DIGEST_FIELD: digest})  # type: ignore[no-any-return]

    def verify(self) -> None:
        """Re-run field validation and self-digest verification."""
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class CheckpointBindingV1(_HandoffPayloadMixin):
    """Exact committed-checkpoint binding carried by a terminal handoff."""

    state: str
    transaction_id: str
    transaction_sha256: str
    artifact: ActionsArtifactIdentityV1

    def _validate(self) -> None:
        state = _require_str(self.state, "checkpoint.state")
        if state not in CHECKPOINT_STATES:
            raise PublicationHandoffError(
                f"checkpoint.state must be one of {sorted(CHECKPOINT_STATES)}, got {state!r}"
            )
        _require_str(self.transaction_id, "checkpoint.transaction_id")
        _require_sha256(self.transaction_sha256, "checkpoint.transaction_sha256")
        if not isinstance(self.artifact, ActionsArtifactIdentityV1):
            raise PublicationHandoffError(
                "checkpoint.artifact must be an ActionsArtifactIdentityV1"
            )


@dataclass(frozen=True, slots=True)
class TerminalPublicationHandoffV1(_SealedHandoffMixin):
    """The sole immutable input accepted by publish and reconcile dispatches."""

    _DIGEST_FIELD: ClassVar[str] = "handoff_sha256"

    producer_repository: str
    workflow_path: str
    workflow_content_sha256: str
    workflow_sha: str
    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    terminal_iteration: int
    operation_authority_sha256: str
    next_manifest_member: ArtifactMemberIdentityV1
    checkpoint: CheckpointBindingV1
    candidate_artifact: ActionsArtifactIdentityV1
    candidate_inventory_sha256: str
    candidate_tree_sha256: str
    prepublication_admission_sha256: str
    public_disposition_sha256: str
    metadata_sha256: str
    private_capture_assurance_sha256: str
    successor: bool
    private_baseline_member: ArtifactMemberIdentityV1 | None
    handoff_sha256: str

    def _validate(self) -> None:
        repository = _require_repository(self.producer_repository, "producer_repository")
        _require_workflow_path(self.workflow_path)
        _require_sha256(self.workflow_content_sha256, "workflow_content_sha256")
        _require_git_sha(self.workflow_sha, "workflow_sha")
        _require_git_sha(self.source_sha, "source_sha")
        run_id = _require_int(self.run_id, "run_id", minimum=1)
        run_attempt = _require_int(self.run_attempt, "run_attempt", minimum=1)
        _require_str(self.chain_id, "chain_id")
        _require_int(self.terminal_iteration, "terminal_iteration", minimum=1)
        _require_sha256(self.operation_authority_sha256, "operation_authority_sha256")
        _require_sha256(self.candidate_inventory_sha256, "candidate_inventory_sha256")
        _require_sha256(self.candidate_tree_sha256, "candidate_tree_sha256")
        _require_sha256(self.prepublication_admission_sha256, "prepublication_admission_sha256")
        _require_sha256(self.public_disposition_sha256, "public_disposition_sha256")
        _require_sha256(self.metadata_sha256, "metadata_sha256")
        _require_sha256(self.private_capture_assurance_sha256, "private_capture_assurance_sha256")
        successor = _require_bool(self.successor, "successor")

        if not isinstance(self.next_manifest_member, ArtifactMemberIdentityV1):
            raise PublicationHandoffError(
                "next_manifest_member must be an ArtifactMemberIdentityV1"
            )
        if not isinstance(self.candidate_artifact, ActionsArtifactIdentityV1):
            raise PublicationHandoffError("candidate_artifact must be an ActionsArtifactIdentityV1")
        if not isinstance(self.checkpoint, CheckpointBindingV1):
            raise PublicationHandoffError("checkpoint must be a CheckpointBindingV1")
        if self.checkpoint.state != CHECKPOINT_STATE_COMMITTED:
            raise PublicationHandoffError(
                f"handoff requires a committed checkpoint; bound state is {self.checkpoint.state!r}"
            )

        self._require_owned(
            self.next_manifest_member.artifact,
            "next_manifest_member.artifact",
            repository,
            run_id,
            run_attempt,
        )
        self._require_owned(
            self.checkpoint.artifact,
            "checkpoint.artifact",
            repository,
            run_id,
            run_attempt,
        )
        self._require_owned(
            self.candidate_artifact,
            "candidate_artifact",
            repository,
            run_id,
            run_attempt,
        )

        if successor:
            if not isinstance(self.private_baseline_member, ArtifactMemberIdentityV1):
                raise PublicationHandoffError(
                    "successor handoffs must bind an exact private-baseline "
                    "artifact member from the parent run"
                )
            self._require_owned_repository(
                self.private_baseline_member.artifact,
                "private_baseline_member.artifact",
                repository,
            )
            _require_immutable_artifact_name(
                self.private_baseline_member.artifact.artifact_name,
                "private_baseline_member.artifact.artifact_name",
            )
        elif self.private_baseline_member is not None:
            raise PublicationHandoffError(
                "private_baseline_member is reserved for successor-produced handoffs; "
                "full-extraction handoffs must not bind one"
            )

    @staticmethod
    def _require_owned(
        artifact: ActionsArtifactIdentityV1,
        field: str,
        repository: str,
        run_id: int,
        run_attempt: int,
    ) -> None:
        """Require an artifact owned by the producing repository, run, attempt."""
        if artifact.repository != repository:
            raise PublicationHandoffError(
                f"{field} names repository {artifact.repository!r}; handoff producer "
                f"is {repository!r}"
            )
        if artifact.run_id != run_id or artifact.run_attempt != run_attempt:
            raise PublicationHandoffError(
                f"{field} names run {artifact.run_id}/attempt {artifact.run_attempt}; "
                f"handoff producer is run {run_id}/attempt {run_attempt}"
            )
        _require_immutable_artifact_name(artifact.artifact_name, f"{field}.artifact_name")

    @staticmethod
    def _require_owned_repository(
        artifact: ActionsArtifactIdentityV1, field: str, repository: str
    ) -> None:
        """Require repository agreement only (parent artifacts may name another run)."""
        if artifact.repository != repository:
            raise PublicationHandoffError(
                f"{field} names repository {artifact.repository!r}; handoff producer "
                f"is {repository!r}"
            )
