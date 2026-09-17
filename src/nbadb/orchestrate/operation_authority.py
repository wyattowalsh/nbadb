from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any, ClassVar, Self, cast

from nbadb.contracts.actions_artifact import (
    ActionsArtifactIdentityV1,
    ArtifactMemberIdentityV1,
)

__all__ = [
    "ACTION_DISPATCH_EVENT",
    "DIRECT_PARALLELISM_LIMIT",
    "ExactArtifactMemberV1",
    "NetworkMode",
    "OPERATION_AUTHORITY_SCHEMA_VERSION",
    "OperationAuthorityError",
    "OperationAuthorityV1",
    "OperationKind",
    "VPN_PARALLELISM_DEFAULT",
    "VPN_PARALLELISM_LIMIT",
]

OPERATION_AUTHORITY_SCHEMA_VERSION = 1

ACTION_DISPATCH_EVENT = "workflow_dispatch"

VPN_PARALLELISM_DEFAULT = 2
VPN_PARALLELISM_LIMIT = 6
DIRECT_PARALLELISM_LIMIT = 6


class OperationAuthorityError(ValueError):
    """Raised when operation authority identities or invariants are violated."""


class OperationKind(StrEnum):
    """Exact operation classes an Actions authority receipt can represent."""

    TARGETED_SMOKE = "targeted_smoke"
    EXTRACT = "extract"
    CONTINUE = "continue"
    PUBLISH = "publish"
    RECONCILE = "reconcile"
    DAILY_BUILD = "daily_build"
    MONTHLY_BUILD = "monthly_build"
    DATA_GREEN_CLOSEOUT = "data_green_closeout"


class NetworkMode(StrEnum):
    """Requested network routing for provider-facing operations."""

    VPN = "vpn"
    AUTO = "auto"
    DIRECT = "direct"


def _require_exact_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise OperationAuthorityError(f"{field_name} must be a nonempty exact string")
    return value


def _require_sha256(value: object, *, field_name: str, prefixed: bool = False) -> str:
    raw = _require_exact_text(value, field_name=field_name)
    expected_length = 71 if prefixed else 64
    if len(raw) != expected_length:
        raise OperationAuthorityError(f"{field_name} must be a lowercase SHA-256")
    if prefixed:
        if not raw.startswith("sha256:"):
            raise OperationAuthorityError(f"{field_name} must be a lowercase SHA-256")
        raw_hex = raw.removeprefix("sha256:")
    else:
        raw_hex = raw
    if any(character not in "0123456789abcdef" for character in raw_hex):
        raise OperationAuthorityError(f"{field_name} must be a lowercase SHA-256")
    return raw


def _require_commit_sha(value: object, *, field_name: str) -> str:
    raw = _require_exact_text(value, field_name=field_name)
    if len(raw) != 40 or any(character not in "0123456789abcdef" for character in raw):
        raise OperationAuthorityError(f"{field_name} must be a 40-character lowercase commit SHA")
    return raw


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise OperationAuthorityError(f"{field_name} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise OperationAuthorityError(f"{field_name} must be a nonnegative integer")
    return value


def _require_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise OperationAuthorityError(f"{field_name} must be an exact boolean")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if unexpected:
        details.append("unexpected=" + ",".join(unexpected))
    raise OperationAuthorityError(f"{label} fields are invalid: {'; '.join(details)}")


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ExactArtifactMemberV1:
    """Exact artifact/member identity bound into an operation authority.

    Run attempt is an explicit field and is never inferred from the artifact
    name. This local value mirrors the shared ``ArtifactMemberIdentityV1``
    shape without importing the parallel contract module.
    """

    repository: str
    run_id: int
    run_attempt: int
    artifact_id: int
    artifact_name: str
    artifact_digest: str
    artifact_size_bytes: int
    member_path: str
    member_sha256: str
    member_size_bytes: int

    def __post_init__(self) -> None:
        _require_repository(self.repository)
        _require_positive_int(self.run_id, field_name="run_id")
        _require_positive_int(self.run_attempt, field_name="run_attempt")
        _require_positive_int(self.artifact_id, field_name="artifact_id")
        _require_exact_text(self.artifact_name, field_name="artifact_name")
        _require_sha256(self.artifact_digest, field_name="artifact_digest", prefixed=True)
        _require_nonnegative_int(self.artifact_size_bytes, field_name="artifact_size_bytes")
        _require_relative_member_path(self.member_path)
        _require_sha256(self.member_sha256, field_name="member_sha256")
        _require_nonnegative_int(self.member_size_bytes, field_name="member_size_bytes")

    def to_shared_member(self) -> ArtifactMemberIdentityV1:
        """Convert to the shared nested ``ArtifactMemberIdentityV1`` exactly."""

        return ArtifactMemberIdentityV1(
            artifact=ActionsArtifactIdentityV1(
                repository=self.repository,
                run_id=self.run_id,
                run_attempt=self.run_attempt,
                artifact_id=self.artifact_id,
                artifact_name=self.artifact_name,
                artifact_digest=self.artifact_digest,
                artifact_size_bytes=self.artifact_size_bytes,
            ),
            member_path=self.member_path,
            member_sha256=self.member_sha256,
            member_size_bytes=self.member_size_bytes,
        )

    @classmethod
    def from_shared_member(cls, member: ArtifactMemberIdentityV1) -> ExactArtifactMemberV1:
        """Build from the shared nested ``ArtifactMemberIdentityV1`` exactly."""

        artifact = member.artifact
        return cls(
            repository=artifact.repository,
            run_id=artifact.run_id,
            run_attempt=artifact.run_attempt,
            artifact_id=artifact.artifact_id,
            artifact_name=artifact.artifact_name,
            artifact_digest=artifact.artifact_digest,
            artifact_size_bytes=artifact.artifact_size_bytes,
            member_path=member.member_path,
            member_sha256=member.member_sha256,
            member_size_bytes=member.member_size_bytes,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "repository": self.repository,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "artifact_digest": self.artifact_digest,
            "artifact_size_bytes": self.artifact_size_bytes,
            "member_path": self.member_path,
            "member_sha256": self.member_sha256,
            "member_size_bytes": self.member_size_bytes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "repository",
                    "run_id",
                    "run_attempt",
                    "artifact_id",
                    "artifact_name",
                    "artifact_digest",
                    "artifact_size_bytes",
                    "member_path",
                    "member_sha256",
                    "member_size_bytes",
                }
            ),
            label="exact artifact member",
        )
        return cls(
            repository=_require_repository(payload["repository"]),
            run_id=_require_positive_int(payload["run_id"], field_name="run_id"),
            run_attempt=_require_positive_int(payload["run_attempt"], field_name="run_attempt"),
            artifact_id=_require_positive_int(payload["artifact_id"], field_name="artifact_id"),
            artifact_name=_require_exact_text(payload["artifact_name"], field_name="artifact_name"),
            artifact_digest=_require_sha256(
                payload["artifact_digest"], field_name="artifact_digest", prefixed=True
            ),
            artifact_size_bytes=_require_nonnegative_int(
                payload["artifact_size_bytes"], field_name="artifact_size_bytes"
            ),
            member_path=_require_relative_member_path(payload["member_path"]),
            member_sha256=_require_sha256(payload["member_sha256"], field_name="member_sha256"),
            member_size_bytes=_require_nonnegative_int(
                payload["member_size_bytes"], field_name="member_size_bytes"
            ),
        )


def _require_repository(value: object, *, field_name: str = "repository") -> str:
    raw = _require_exact_text(value, field_name=field_name)
    if raw.count("/") != 1:
        raise OperationAuthorityError(f"{field_name} must be an owner/name repository identity")
    owner, name = raw.split("/", 1)
    if not owner or not name:
        raise OperationAuthorityError(f"{field_name} must be an owner/name repository identity")
    return raw


def _require_workflow_path(value: object, *, field_name: str = "workflow_path") -> str:
    raw = _require_exact_text(value, field_name=field_name)
    if not raw.startswith(".github/workflows/") or not raw.endswith((".yml", ".yaml")):
        raise OperationAuthorityError(f"{field_name} must be a repository workflow file path")
    if raw.endswith("/") or ".." in raw or "\\" in raw:
        raise OperationAuthorityError(f"{field_name} must be a repository workflow file path")
    return raw


def _require_relative_member_path(value: object, *, field_name: str = "member_path") -> str:
    raw = _require_exact_text(value, field_name=field_name)
    if raw.startswith("/") or raw.startswith("\\"):
        raise OperationAuthorityError(f"{field_name} must be a relative POSIX member path")
    if "\\" in raw or ".." in raw.split("/") or "./" in raw or raw.endswith("/"):
        raise OperationAuthorityError(f"{field_name} must be a relative POSIX member path")
    if any(not segment for segment in raw.split("/")):
        raise OperationAuthorityError(f"{field_name} must be a relative POSIX member path")
    return raw


@dataclass(frozen=True, slots=True)
class ActionsRuntimeView:
    """Read-only GitHub Actions runtime identities for independent revalidation."""

    repository: str
    run_id: int
    run_attempt: int
    event: str
    actor: str
    trusted_ref: str
    workflow_commit_sha: str
    source_sha: str
    workflow_content_sha256: str

    def __post_init__(self) -> None:
        _require_repository(self.repository)
        _require_positive_int(self.run_id, field_name="run_id")
        _require_positive_int(self.run_attempt, field_name="run_attempt")
        _require_exact_text(self.event, field_name="event")
        _require_exact_text(self.actor, field_name="actor")
        _require_exact_text(self.trusted_ref, field_name="trusted_ref")
        _require_commit_sha(self.workflow_commit_sha, field_name="workflow_commit_sha")
        _require_commit_sha(self.source_sha, field_name="source_sha")
        _require_sha256(self.workflow_content_sha256, field_name="workflow_content_sha256")


@dataclass(frozen=True, slots=True)
class OperationAuthorityV1:
    """Neutral, exact GitHub Actions operation authority.

    This receipt is independent of free-execution admission: it never confers
    execution permission by itself, and its serialized ``authority_sha256`` is
    a derived digest. Authority exists only after
    ``require_current_actions_runtime`` independently revalidates the runtime
    identities against the live Actions context.
    """

    repository: str
    workflow_path: str
    workflow_content_sha256: str
    workflow_commit_sha: str
    source_sha: str
    trusted_ref: str
    run_id: int
    run_attempt: int
    event: str
    actor: str
    chain_id: str
    iteration: int
    operation: OperationKind
    requested_network_mode: NetworkMode | None
    requested_vpn_parallelism: int
    requested_direct_parallelism: int
    max_iterations: int
    retry_pipeline_failures: bool
    allow_re_extraction: bool
    manifest_lane_count: int
    continuation_source: ExactArtifactMemberV1 | None = None
    terminal_handoff: ExactArtifactMemberV1 | None = None
    parent_readback: ExactArtifactMemberV1 | None = None
    parent_private_capture: ExactArtifactMemberV1 | None = None
    parent_data_green: ExactArtifactMemberV1 | None = None
    remote_readback: ExactArtifactMemberV1 | None = None
    human_verification_receipt: ExactArtifactMemberV1 | None = None
    authority_sha256: str = ""

    _DIGEST_FIELD: ClassVar[str] = "authority_sha256"

    def __post_init__(self) -> None:
        _require_repository(self.repository)
        _require_workflow_path(self.workflow_path)
        _require_sha256(self.workflow_content_sha256, field_name="workflow_content_sha256")
        _require_commit_sha(self.workflow_commit_sha, field_name="workflow_commit_sha")
        _require_commit_sha(self.source_sha, field_name="source_sha")
        _require_exact_text(self.trusted_ref, field_name="trusted_ref")
        _require_positive_int(self.run_id, field_name="run_id")
        _require_positive_int(self.run_attempt, field_name="run_attempt")
        _require_exact_text(self.event, field_name="event")
        _require_exact_text(self.actor, field_name="actor")
        _require_exact_text(self.chain_id, field_name="chain_id")
        _require_positive_int(self.iteration, field_name="iteration")
        if not isinstance(self.operation, OperationKind):
            raise OperationAuthorityError("operation must be an OperationKind value")
        if self.requested_network_mode is not None and not isinstance(
            self.requested_network_mode, NetworkMode
        ):
            raise OperationAuthorityError(
                "requested_network_mode must be a NetworkMode value or None"
            )
        _require_nonnegative_int(
            self.requested_vpn_parallelism, field_name="requested_vpn_parallelism"
        )
        _require_nonnegative_int(
            self.requested_direct_parallelism, field_name="requested_direct_parallelism"
        )
        _require_positive_int(self.max_iterations, field_name="max_iterations")
        _require_bool(self.retry_pipeline_failures, field_name="retry_pipeline_failures")
        _require_bool(self.allow_re_extraction, field_name="allow_re_extraction")
        _require_positive_int(self.manifest_lane_count, field_name="manifest_lane_count")
        if self.event != ACTION_DISPATCH_EVENT:
            raise OperationAuthorityError(
                "operation authority requires an exact workflow_dispatch event"
            )
        self._validate_members()
        self._validate_operation_invariants()
        expected = _authority_digest(self.to_dict(exclude_digest=True))
        if not self.authority_sha256:
            object.__setattr__(self, "authority_sha256", expected)
        elif self.authority_sha256 != expected:
            raise OperationAuthorityError(
                "authority_sha256 does not match the recomputed canonical digest"
            )

    def _validate_members(self) -> None:
        for member in self._bound_members():
            if member.repository != self.repository:
                raise OperationAuthorityError(
                    "bound artifact members must belong to the authority repository"
                )

    def _bound_members(self) -> tuple[ExactArtifactMemberV1, ...]:
        return tuple(
            member
            for member in (
                self.continuation_source,
                self.terminal_handoff,
                self.parent_readback,
                self.parent_private_capture,
                self.parent_data_green,
                self.remote_readback,
                self.human_verification_receipt,
            )
            if member is not None
        )

    def _require_no_publication_inputs(self, *, context: str) -> None:
        if self.terminal_handoff is not None:
            raise OperationAuthorityError(f"{context} must not carry a terminal handoff member")
        if self.parent_readback is not None or self.parent_private_capture is not None:
            raise OperationAuthorityError(f"{context} must not carry successor parent members")
        if self.parent_data_green is not None:
            raise OperationAuthorityError(f"{context} must not carry successor parent members")
        if self.remote_readback is not None or self.human_verification_receipt is not None:
            raise OperationAuthorityError(f"{context} must not carry closeout members")

    def _validate_provider_network(self, *, context: str) -> None:
        if self.requested_network_mode is None:
            raise OperationAuthorityError(f"{context} requires an explicit network mode")
        if self.requested_network_mode is NetworkMode.DIRECT:
            if self.requested_vpn_parallelism != 0:
                raise OperationAuthorityError(
                    f"{context} with direct mode must not request VPN capacity"
                )
            if not 1 <= self.requested_direct_parallelism <= DIRECT_PARALLELISM_LIMIT:
                raise OperationAuthorityError(
                    f"{context} direct parallelism must be between 1 and {DIRECT_PARALLELISM_LIMIT}"
                )
            return
        if not 1 <= self.requested_vpn_parallelism <= VPN_PARALLELISM_LIMIT:
            raise OperationAuthorityError(
                f"{context} VPN parallelism must be between 1 and {VPN_PARALLELISM_LIMIT}"
            )
        if self.requested_network_mode is NetworkMode.VPN:
            if self.requested_direct_parallelism != 0:
                raise OperationAuthorityError(
                    f"{context} with VPN-only mode must not request direct capacity"
                )
            return
        if self.requested_network_mode is NetworkMode.AUTO:
            if self.requested_direct_parallelism > DIRECT_PARALLELISM_LIMIT:
                raise OperationAuthorityError(
                    f"{context} direct fallback parallelism must not exceed "
                    f"{DIRECT_PARALLELISM_LIMIT}"
                )
            return
        raise OperationAuthorityError(f"{context} requested an unsupported network mode")

    def _validate_no_provider_network(self, *, context: str) -> None:
        if self.requested_network_mode is not None:
            raise OperationAuthorityError(f"{context} must not request a provider network mode")
        if self.requested_vpn_parallelism != 0 or self.requested_direct_parallelism != 0:
            raise OperationAuthorityError(f"{context} must not request extraction parallelism")
        if self.max_iterations != 1:
            raise OperationAuthorityError(f"{context} must not request multiple iterations")
        if self.retry_pipeline_failures or self.allow_re_extraction:
            raise OperationAuthorityError(
                f"{context} must not request pipeline retry or re-extraction"
            )

    def _validate_operation_invariants(self) -> None:
        operation = self.operation
        if operation is OperationKind.TARGETED_SMOKE:
            if self.requested_network_mode is not NetworkMode.DIRECT:
                raise OperationAuthorityError(
                    "targeted_smoke is free/direct-only and may not request VPN capacity"
                )
            if self.requested_vpn_parallelism != 0:
                raise OperationAuthorityError("targeted_smoke authorizes zero VPN lanes")
            if self.requested_direct_parallelism != 1:
                raise OperationAuthorityError("targeted_smoke authorizes exactly one direct lane")
            if self.max_iterations != 1:
                raise OperationAuthorityError("targeted_smoke authorizes exactly one iteration")
            if self.retry_pipeline_failures:
                raise OperationAuthorityError("targeted_smoke may not retry pipeline failures")
            if self.allow_re_extraction:
                raise OperationAuthorityError("targeted_smoke may not re-extract")
            if self.manifest_lane_count != 1:
                raise OperationAuthorityError("targeted_smoke authorizes exactly one manifest lane")
            if self.continuation_source is not None:
                raise OperationAuthorityError(
                    "targeted_smoke must not carry a continuation source member"
                )
            self._require_no_publication_inputs(context="targeted_smoke")
            return

        if operation is OperationKind.EXTRACT:
            if self.continuation_source is not None:
                raise OperationAuthorityError(
                    "extract starts a fresh chain and must not carry a continuation source"
                )
            self._validate_provider_network(context="extract")
            self._require_no_publication_inputs(context="extract")
            return

        if operation is OperationKind.CONTINUE:
            if self.continuation_source is None:
                raise OperationAuthorityError("continue requires an exact continuation source")
            if self.continuation_source.run_id == self.run_id:
                raise OperationAuthorityError(
                    "continue must consume a source run distinct from the current run"
                )
            self._validate_provider_network(context="continue")
            self._require_no_publication_inputs(context="continue")
            return

        if operation in (OperationKind.PUBLISH, OperationKind.RECONCILE):
            if self.terminal_handoff is None:
                raise OperationAuthorityError(
                    f"{operation.value} requires an exact terminal handoff member"
                )
            if self.continuation_source is not None:
                raise OperationAuthorityError(
                    f"{operation.value} must not carry a continuation source member"
                )
            self._validate_no_provider_network(context=operation.value)
            if self.parent_readback is not None or self.parent_private_capture is not None:
                raise OperationAuthorityError(
                    f"{operation.value} must not carry successor parent members"
                )
            if self.parent_data_green is not None:
                raise OperationAuthorityError(
                    f"{operation.value} must not carry successor parent members"
                )
            if self.remote_readback is not None or self.human_verification_receipt is not None:
                raise OperationAuthorityError(f"{operation.value} must not carry closeout members")
            return

        if operation in (OperationKind.DAILY_BUILD, OperationKind.MONTHLY_BUILD):
            missing = [
                name
                for name, member in (
                    ("parent_readback", self.parent_readback),
                    ("parent_private_capture", self.parent_private_capture),
                    ("parent_data_green", self.parent_data_green),
                )
                if member is None
            ]
            if missing:
                raise OperationAuthorityError(
                    f"{operation.value} requires exact {'+'.join(missing)} members"
                )
            if self.continuation_source is not None:
                raise OperationAuthorityError(
                    f"{operation.value} must not carry a continuation source member"
                )
            if self.terminal_handoff is not None:
                raise OperationAuthorityError(
                    f"{operation.value} consumes parents and must not carry a handoff member"
                )
            self._validate_provider_network(context=operation.value)
            if self.remote_readback is not None or self.human_verification_receipt is not None:
                raise OperationAuthorityError(f"{operation.value} must not carry closeout members")
            return

        if operation is OperationKind.DATA_GREEN_CLOSEOUT:
            if self.remote_readback is None:
                raise OperationAuthorityError(
                    "data_green_closeout requires an exact remote readback member"
                )
            if self.human_verification_receipt is None:
                raise OperationAuthorityError(
                    "data_green_closeout requires a human verification receipt member"
                )
            if self.continuation_source is not None:
                raise OperationAuthorityError(
                    "data_green_closeout must not carry a continuation source member"
                )
            self._validate_no_provider_network(context="data_green_closeout")
            if self.terminal_handoff is not None:
                raise OperationAuthorityError("data_green_closeout must not carry a handoff member")
            if self.parent_readback is not None or self.parent_private_capture is not None:
                raise OperationAuthorityError(
                    "data_green_closeout must not carry successor parent members"
                )
            if self.parent_data_green is not None:
                raise OperationAuthorityError(
                    "data_green_closeout must not carry successor parent members"
                )
            return

        raise OperationAuthorityError("operation must be an OperationKind value")

    def to_dict(self, *, exclude_digest: bool = False) -> dict[str, object]:
        def member_dict(member: ExactArtifactMemberV1 | None) -> object | None:
            return member.to_dict() if member is not None else None

        payload: dict[str, object] = {
            "schema_version": OPERATION_AUTHORITY_SCHEMA_VERSION,
            "repository": self.repository,
            "workflow_path": self.workflow_path,
            "workflow_content_sha256": self.workflow_content_sha256,
            "workflow_commit_sha": self.workflow_commit_sha,
            "source_sha": self.source_sha,
            "trusted_ref": self.trusted_ref,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "event": self.event,
            "actor": self.actor,
            "chain_id": self.chain_id,
            "iteration": self.iteration,
            "operation": self.operation.value,
            "requested_network_mode": (
                self.requested_network_mode.value
                if self.requested_network_mode is not None
                else None
            ),
            "requested_vpn_parallelism": self.requested_vpn_parallelism,
            "requested_direct_parallelism": self.requested_direct_parallelism,
            "max_iterations": self.max_iterations,
            "retry_pipeline_failures": self.retry_pipeline_failures,
            "allow_re_extraction": self.allow_re_extraction,
            "manifest_lane_count": self.manifest_lane_count,
            "continuation_source": member_dict(self.continuation_source),
            "terminal_handoff": member_dict(self.terminal_handoff),
            "parent_readback": member_dict(self.parent_readback),
            "parent_private_capture": member_dict(self.parent_private_capture),
            "parent_data_green": member_dict(self.parent_data_green),
            "remote_readback": member_dict(self.remote_readback),
            "human_verification_receipt": member_dict(self.human_verification_receipt),
        }
        if not exclude_digest:
            payload[self._DIGEST_FIELD] = self.authority_sha256
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected_keys = frozenset({field.name for field in fields(cls)} | {"schema_version"}) - {
            "_DIGEST_FIELD"
        }
        _require_exact_keys(
            payload,
            expected=frozenset(expected_keys | {cls._DIGEST_FIELD}),
            label="operation authority",
        )
        if payload["schema_version"] != OPERATION_AUTHORITY_SCHEMA_VERSION:
            raise OperationAuthorityError("operation authority schema version is unsupported")

        def member(key: str) -> ExactArtifactMemberV1 | None:
            raw = payload[key]
            if raw is None:
                return None
            if not isinstance(raw, Mapping):
                raise OperationAuthorityError(f"{key} must be an object or null")
            return ExactArtifactMemberV1.from_dict(cast("Mapping[str, object]", raw))

        network_raw = payload["requested_network_mode"]
        if network_raw is None:
            network = None
        elif isinstance(network_raw, str):
            try:
                network = NetworkMode(network_raw)
            except ValueError as error:
                raise OperationAuthorityError(
                    "requested_network_mode must be a NetworkMode value or None"
                ) from error
        else:
            raise OperationAuthorityError(
                "requested_network_mode must be a NetworkMode value or None"
            )
        try:
            operation = OperationKind(cast("str", payload["operation"]))
        except ValueError as error:
            raise OperationAuthorityError("operation must be an OperationKind value") from error
        return cls(
            repository=_require_repository(payload["repository"]),
            workflow_path=_require_workflow_path(payload["workflow_path"]),
            workflow_content_sha256=_require_sha256(
                payload["workflow_content_sha256"], field_name="workflow_content_sha256"
            ),
            workflow_commit_sha=_require_commit_sha(
                payload["workflow_commit_sha"], field_name="workflow_commit_sha"
            ),
            source_sha=_require_commit_sha(payload["source_sha"], field_name="source_sha"),
            trusted_ref=_require_exact_text(payload["trusted_ref"], field_name="trusted_ref"),
            run_id=_require_positive_int(payload["run_id"], field_name="run_id"),
            run_attempt=_require_positive_int(payload["run_attempt"], field_name="run_attempt"),
            event=_require_exact_text(payload["event"], field_name="event"),
            actor=_require_exact_text(payload["actor"], field_name="actor"),
            chain_id=_require_exact_text(payload["chain_id"], field_name="chain_id"),
            iteration=_require_positive_int(payload["iteration"], field_name="iteration"),
            operation=operation,
            requested_network_mode=network,
            requested_vpn_parallelism=_require_nonnegative_int(
                payload["requested_vpn_parallelism"],
                field_name="requested_vpn_parallelism",
            ),
            requested_direct_parallelism=_require_nonnegative_int(
                payload["requested_direct_parallelism"],
                field_name="requested_direct_parallelism",
            ),
            max_iterations=_require_positive_int(
                payload["max_iterations"], field_name="max_iterations"
            ),
            retry_pipeline_failures=_require_bool(
                payload["retry_pipeline_failures"], field_name="retry_pipeline_failures"
            ),
            allow_re_extraction=_require_bool(
                payload["allow_re_extraction"], field_name="allow_re_extraction"
            ),
            manifest_lane_count=_require_positive_int(
                payload["manifest_lane_count"], field_name="manifest_lane_count"
            ),
            continuation_source=member("continuation_source"),
            terminal_handoff=member("terminal_handoff"),
            parent_readback=member("parent_readback"),
            parent_private_capture=member("parent_private_capture"),
            parent_data_green=member("parent_data_green"),
            remote_readback=member("remote_readback"),
            human_verification_receipt=member("human_verification_receipt"),
            authority_sha256=_require_sha256(
                payload[cls._DIGEST_FIELD], field_name=cls._DIGEST_FIELD
            ),
        )

    def require_current_actions_runtime(self, runtime: ActionsRuntimeView) -> Self:
        """Independently revalidate this authority against the live runtime.

        Authority is established only by this revalidation: the serialized
        digest alone never confers it. Any identity mismatch fails closed
        before an operation-specific effect can proceed.
        """
        mismatches: list[str] = []
        pairs: tuple[tuple[str, object, object], ...] = (
            ("repository", self.repository, runtime.repository),
            ("run_id", self.run_id, runtime.run_id),
            ("run_attempt", self.run_attempt, runtime.run_attempt),
            ("event", self.event, runtime.event),
            ("actor", self.actor, runtime.actor),
            ("trusted_ref", self.trusted_ref, runtime.trusted_ref),
            ("workflow_commit_sha", self.workflow_commit_sha, runtime.workflow_commit_sha),
            ("source_sha", self.source_sha, runtime.source_sha),
            (
                "workflow_content_sha256",
                self.workflow_content_sha256,
                runtime.workflow_content_sha256,
            ),
        )
        for name, recorded, observed in pairs:
            if recorded != observed:
                mismatches.append(name)
        if mismatches:
            raise OperationAuthorityError(
                "operation authority does not match the current Actions runtime: "
                + ",".join(mismatches)
            )
        if runtime.event != ACTION_DISPATCH_EVENT:
            raise OperationAuthorityError(
                "operation authority requires an exact workflow_dispatch event"
            )
        return self


def _authority_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def canonical_receipt_bytes(value: Any) -> bytes:  # pragma: no cover - narrow helper
    """Canonical encoding used for authority digests.

    Kept private to this module's digest rule; the shared contract codec is
    defined separately for the new receipt family.
    """
    return _canonical_bytes(value)
