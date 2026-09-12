from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from nbadb.contracts.actions_artifact import ArtifactMemberIdentityV1
    from nbadb.contracts.publication_recovery import (
        PendingTakeoverReceiptV1,
        PendingTakeoverStatusReceiptV1,
    )

GITHUB_API_VERSION = "2026-03-10"
PUBLICATION_DEPLOYMENT_TASK = "nbadb:kaggle-publication"
_INTENT_KIND = "nbadb_kaggle_publication_intent"
_HEX_20_RE = re.compile(r"[0-9a-f]{20}")
_HEX_32_RE = re.compile(r"[0-9a-f]{32}")
_HEX_40_RE = re.compile(r"[0-9a-f]{40}")
_HEX_64_RE = re.compile(r"[0-9a-f]{64}")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_JOB_RE = re.compile(r"[A-Za-z0-9_.-]+")
_POSITIVE_INTEGER_RE = re.compile(r"[1-9][0-9]*")
_TAKEOVER_DESCRIPTION_RE = re.compile(r"nbadb takeover t=([A-Za-z0-9_-]{43}) job=([A-Za-z0-9_.-]+)")
_IN_PROGRESS_DESCRIPTION_RE = re.compile(
    r"nbadb ip intent=([0-9a-f]{64}) nonce=([0-9a-f]{32}) job=([A-Za-z0-9_.-]+)"
)
_SUCCESS_DESCRIPTION_RE = re.compile(
    r"nbadb ok v=([1-9][0-9]*) c=([A-Za-z0-9_-]{43}) "
    r"r=([A-Za-z0-9_-]{43}) j=([A-Za-z0-9_.-]+)"
)
_GITHUB_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_UNRESOLVED_STATES = frozenset({"pending", "in_progress"})
_ACTIVE_RUN_STATES = frozenset({"in_progress", "pending"})
_ACTIVE_JOB_STATES = frozenset({"in_progress", "pending", "queued", "requested", "waiting"})
_HEAD_DEPLOYMENT_LIMIT = 2
_STATUS_RECEIPT_LIMIT = 4
_WORKFLOW_CONTENT_MAX_BYTES = 2 * 1024 * 1024
_WORKFLOW_JOB_INVENTORY_LIMIT = 1_000
_PUBLICATION_MUTEX_GROUP = "nbadb-kaggle-publish"
_DEPLOYMENT_HEAD_QUERY = """\
query NbadbKagglePublicationHead(
  $owner: String!
  $repository: String!
  $environment: String!
) {
  repository(owner: $owner, name: $repository) {
    deployments(
      first: 2
      environments: [$environment]
      orderBy: {field: CREATED_AT, direction: DESC}
    ) {
      nodes {
        databaseId
        createdAt
      }
    }
  }
}
"""
_COMPLETED_CONCLUSIONS = frozenset(
    {
        "action_required",
        "cancelled",
        "failure",
        "neutral",
        "skipped",
        "stale",
        "startup_failure",
        "success",
        "timed_out",
    }
)


class PublicationLedgerError(RuntimeError):
    """A durable publication ledger operation failed closed."""


class PublicationLedgerPendingError(PublicationLedgerError):
    """A durable intent exists but cannot safely enter the Kaggle upload call."""


@dataclass(frozen=True, slots=True)
class GitHubResponse:
    status_code: int
    payload: Any


class GitHubTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        timeout_seconds: float,
    ) -> GitHubResponse: ...


class UrllibGitHubTransport:
    """Small stdlib transport so ledger behavior is independently injectable."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        timeout_seconds: float,
    ) -> GitHubResponse:
        body = (
            json.dumps(json_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if json_body is not None
            else None
        )
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status_code = response.status
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            response_body = exc.read()
        try:
            payload = json.loads(response_body) if response_body else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = f"GitHub publication ledger returned non-JSON HTTP {status_code}"
            raise PublicationLedgerError(msg) from exc
        return GitHubResponse(status_code=status_code, payload=payload)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolution_digest(
    *,
    intent_id: str,
    resolved_version: int,
    publication_marker_sha256: str,
    readback_fingerprint: str,
    claim_digest: str,
    resolver_admission_digest: str,
) -> str:
    return _canonical_sha256(
        {
            "intent_id": intent_id,
            "resolved_version": resolved_version,
            "publication_marker_sha256": publication_marker_sha256,
            "readback_fingerprint": readback_fingerprint,
            "claim_digest": claim_digest,
            "resolver_admission_digest": resolver_admission_digest,
        }
    )


def _parse_github_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or _GITHUB_TIMESTAMP_RE.fullmatch(value) is None:
        raise PublicationLedgerError(f"GitHub publication ledger {field} is invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise PublicationLedgerError(f"GitHub publication ledger {field} is invalid") from exc
    return parsed


def _digest_token(value: str) -> str:
    _require_digest(value, field="digest token")
    return base64.urlsafe_b64encode(bytes.fromhex(value)).decode("ascii").rstrip("=")


def _parse_digest_token(value: str, *, field: str) -> str:
    try:
        decoded = base64.b64decode(f"{value}=", altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PublicationLedgerError(f"GitHub publication ledger {field} token is invalid") from exc
    if (
        len(decoded) != hashlib.sha256().digest_size
        or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value
    ):
        raise PublicationLedgerError(f"GitHub publication ledger {field} token is invalid")
    return decoded.hex()


def _require_digest(value: str | None, *, field: str, length: int = 64) -> None:
    pattern = {20: _HEX_20_RE, 40: _HEX_40_RE, 64: _HEX_64_RE}[length]
    if value is None or pattern.fullmatch(value) is None:
        msg = f"Kaggle publication intent {field} must be {length} lowercase hex characters"
        raise ValueError(msg)


def _validated_base_url(value: str, *, field: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        msg = f"GitHub publication ledger {field} is invalid"
        raise ValueError(msg)
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class PublicationIntent:
    dataset: str
    source_sha: str
    publish_key: str
    bundle_fingerprint: str
    data_tree_fingerprint: str
    staged_tree_fingerprint: str
    publication_marker_sha256: str
    metadata_sha256: str
    resource_count: int
    resource_bytes: int
    verify_remote: bool
    full_publication: bool
    chain_id: str | None = None
    coverage_fingerprint: str | None = None
    assured_data_tree_fingerprint: str | None = None
    assured_manifest_sha256: str | None = None
    terminal_assurance_report_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.dataset.strip() or "/" not in self.dataset:
            raise ValueError("Kaggle publication intent dataset is invalid")
        _require_digest(self.source_sha, field="source_sha", length=40)
        _require_digest(self.publish_key, field="publish_key", length=20)
        for field in (
            "bundle_fingerprint",
            "data_tree_fingerprint",
            "staged_tree_fingerprint",
            "publication_marker_sha256",
            "metadata_sha256",
        ):
            _require_digest(cast("str", getattr(self, field)), field=field)
        if type(self.resource_count) is not int or self.resource_count <= 0:
            raise ValueError("Kaggle publication intent resource_count must be positive")
        if type(self.resource_bytes) is not int or self.resource_bytes < 0:
            raise ValueError("Kaggle publication intent resource_bytes must be nonnegative")
        if self.verify_remote is not True:
            raise ValueError("Durable Kaggle publication intent requires exact remote verification")

        provenance_values = (
            self.chain_id,
            self.coverage_fingerprint,
            self.assured_data_tree_fingerprint,
        )
        if any(value is not None for value in provenance_values):
            if not isinstance(self.chain_id, str) or not self.chain_id.strip():
                raise ValueError("Kaggle publication intent chain_id is invalid")
            _require_digest(self.coverage_fingerprint, field="coverage_fingerprint")
            _require_digest(
                self.assured_data_tree_fingerprint,
                field="assured_data_tree_fingerprint",
            )
        if self.assured_manifest_sha256 is not None:
            _require_digest(self.assured_manifest_sha256, field="assured_manifest_sha256")
        if self.terminal_assurance_report_sha256 is not None:
            _require_digest(
                self.terminal_assurance_report_sha256,
                field="terminal_assurance_report_sha256",
            )
        if self.full_publication and (
            self.chain_id is None
            or self.assured_manifest_sha256 is None
            or self.terminal_assurance_report_sha256 is None
        ):
            raise ValueError(
                "Full Kaggle publication intent requires assured and terminal provenance"
            )

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "dataset": self.dataset,
            "source_sha": self.source_sha,
            "publish_key": self.publish_key,
            "bundle_fingerprint": self.bundle_fingerprint,
            "data_tree_fingerprint": self.data_tree_fingerprint,
            "staged_tree_fingerprint": self.staged_tree_fingerprint,
            "publication_marker_sha256": self.publication_marker_sha256,
            "metadata_sha256": self.metadata_sha256,
            "resource_count": self.resource_count,
            "resource_bytes": self.resource_bytes,
            "verify_remote": self.verify_remote,
            "full_publication": self.full_publication,
            "chain_id": self.chain_id,
            "coverage_fingerprint": self.coverage_fingerprint,
            "assured_data_tree_fingerprint": self.assured_data_tree_fingerprint,
            "assured_manifest_sha256": self.assured_manifest_sha256,
            "terminal_assurance_report_sha256": self.terminal_assurance_report_sha256,
        }

    @property
    def intent_id(self) -> str:
        return _canonical_sha256(self.semantic_payload())

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> PublicationIntent:
        expected_fields = {
            "schema_version",
            "dataset",
            "source_sha",
            "publish_key",
            "bundle_fingerprint",
            "data_tree_fingerprint",
            "staged_tree_fingerprint",
            "publication_marker_sha256",
            "metadata_sha256",
            "resource_count",
            "resource_bytes",
            "verify_remote",
            "full_publication",
            "chain_id",
            "coverage_fingerprint",
            "assured_data_tree_fingerprint",
            "assured_manifest_sha256",
            "terminal_assurance_report_sha256",
        }
        if set(payload) != expected_fields or payload.get("schema_version") != 1:
            raise PublicationLedgerError("GitHub publication intent payload schema is invalid")
        try:
            return cls(
                dataset=cast("str", payload["dataset"]),
                source_sha=cast("str", payload["source_sha"]),
                publish_key=cast("str", payload["publish_key"]),
                bundle_fingerprint=cast("str", payload["bundle_fingerprint"]),
                data_tree_fingerprint=cast("str", payload["data_tree_fingerprint"]),
                staged_tree_fingerprint=cast("str", payload["staged_tree_fingerprint"]),
                publication_marker_sha256=cast("str", payload["publication_marker_sha256"]),
                metadata_sha256=cast("str", payload["metadata_sha256"]),
                resource_count=cast("int", payload["resource_count"]),
                resource_bytes=cast("int", payload["resource_bytes"]),
                verify_remote=cast("bool", payload["verify_remote"]),
                full_publication=cast("bool", payload["full_publication"]),
                chain_id=cast("str | None", payload["chain_id"]),
                coverage_fingerprint=cast("str | None", payload["coverage_fingerprint"]),
                assured_data_tree_fingerprint=cast(
                    "str | None", payload["assured_data_tree_fingerprint"]
                ),
                assured_manifest_sha256=cast("str | None", payload["assured_manifest_sha256"]),
                terminal_assurance_report_sha256=cast(
                    "str | None", payload["terminal_assurance_report_sha256"]
                ),
            )
        except (TypeError, ValueError) as exc:
            raise PublicationLedgerError("GitHub publication intent payload is invalid") from exc


@dataclass(frozen=True, slots=True)
class PublicationAttempt:
    repository: str
    run_id: int
    run_attempt: int
    workflow: str
    workflow_ref: str
    job: str
    workflow_sha: str
    source_sha: str
    actor: str
    server_url: str
    api_url: str
    require_default_branch_head: bool = False
    expected_default_branch_sha: str | None = None

    def __post_init__(self) -> None:
        if _REPOSITORY_RE.fullmatch(self.repository) is None:
            raise ValueError("GitHub publication ledger repository is invalid")
        if type(self.run_id) is not int or self.run_id <= 0:
            raise ValueError("GitHub publication ledger run_id must be positive")
        if type(self.run_attempt) is not int or self.run_attempt <= 0:
            raise ValueError("GitHub publication ledger run_attempt must be positive")
        if (
            not self.workflow.strip()
            or not self.actor.strip()
            or _JOB_RE.fullmatch(self.job) is None
        ):
            raise ValueError("GitHub publication ledger workflow/actor is invalid")
        workflow_prefix = f"{self.repository}/"
        workflow_reference = self.workflow_ref.removeprefix(workflow_prefix)
        workflow_path, separator, workflow_ref = workflow_reference.rpartition("@")
        if (
            workflow_reference == self.workflow_ref
            or not separator
            or not workflow_ref.startswith("refs/")
            or not workflow_path.startswith(".github/workflows/")
            or not workflow_path.endswith((".yml", ".yaml"))
            or "\\" in workflow_path
            or ".." in workflow_path.split("/")
        ):
            raise ValueError("GitHub publication ledger workflow_ref is invalid")
        if type(self.require_default_branch_head) is not bool:
            raise ValueError(
                "GitHub publication ledger require_default_branch_head must be boolean"
            )
        _require_digest(self.workflow_sha, field="workflow_sha", length=40)
        _require_digest(self.source_sha, field="source_sha", length=40)
        if self.require_default_branch_head:
            expected_default_branch_sha = self.expected_default_branch_sha or self.source_sha
            _require_digest(
                expected_default_branch_sha,
                field="expected_default_branch_sha",
                length=40,
            )
            object.__setattr__(
                self,
                "expected_default_branch_sha",
                expected_default_branch_sha,
            )
        elif self.expected_default_branch_sha is not None:
            raise ValueError(
                "GitHub publication ledger expected_default_branch_sha requires "
                "default-branch enforcement"
            )
        object.__setattr__(
            self,
            "server_url",
            _validated_base_url(self.server_url, field="server_url"),
        )
        object.__setattr__(self, "api_url", _validated_base_url(self.api_url, field="api_url"))

    @classmethod
    def from_actions_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> PublicationAttempt:
        values = os.environ if env is None else env

        def required(name: str) -> str:
            value = values.get(name, "").strip()
            if not value:
                msg = f"Durable Kaggle publication requires {name}"
                raise PublicationLedgerError(msg)
            return value

        run_id = required("GITHUB_RUN_ID")
        run_attempt = required("GITHUB_RUN_ATTEMPT")
        require_default_branch_head = values.get(
            "NBADB_KAGGLE_REQUIRE_DEFAULT_HEAD",
            "false",
        ).strip()
        expected_default_branch_sha = values.get(
            "NBADB_KAGGLE_EXPECTED_DEFAULT_HEAD_SHA",
            "",
        ).strip()
        if require_default_branch_head not in {"false", "true"}:
            raise PublicationLedgerError("NBADB_KAGGLE_REQUIRE_DEFAULT_HEAD must be true or false")
        if _POSITIVE_INTEGER_RE.fullmatch(run_id) is None:
            raise PublicationLedgerError("GITHUB_RUN_ID must be a positive integer")
        if _POSITIVE_INTEGER_RE.fullmatch(run_attempt) is None:
            raise PublicationLedgerError("GITHUB_RUN_ATTEMPT must be a positive integer")
        try:
            return cls(
                repository=required("GITHUB_REPOSITORY"),
                run_id=int(run_id),
                run_attempt=int(run_attempt),
                workflow=required("GITHUB_WORKFLOW"),
                workflow_ref=required("GITHUB_WORKFLOW_REF"),
                job=required("GITHUB_JOB"),
                workflow_sha=required("GITHUB_SHA"),
                source_sha=required("NBADB_KAGGLE_PUBLICATION_SOURCE_SHA"),
                actor=required("GITHUB_ACTOR"),
                server_url=required("GITHUB_SERVER_URL"),
                api_url=required("GITHUB_API_URL"),
                require_default_branch_head=require_default_branch_head == "true",
                expected_default_branch_sha=expected_default_branch_sha or None,
            )
        except ValueError as exc:
            raise PublicationLedgerError(str(exc)) from exc

    @property
    def log_url(self) -> str:
        return (
            f"{self.server_url}/{self.repository}/actions/runs/{self.run_id}"
            f"/attempts/{self.run_attempt}"
        )

    @property
    def workflow_path(self) -> str:
        workflow_reference = self.workflow_ref.removeprefix(f"{self.repository}/")
        return workflow_reference.rpartition("@")[0]

    def payload(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "workflow": self.workflow,
            "workflow_ref": self.workflow_ref,
            "job": self.job,
            "workflow_sha": self.workflow_sha,
            "source_sha": self.source_sha,
            "actor": self.actor,
            "server_url": self.server_url,
            "api_url": self.api_url,
            "require_default_branch_head": self.require_default_branch_head,
            "expected_default_branch_sha": self.expected_default_branch_sha,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> PublicationAttempt:
        expected_fields = {
            "repository",
            "run_id",
            "run_attempt",
            "workflow",
            "workflow_ref",
            "job",
            "workflow_sha",
            "source_sha",
            "actor",
            "server_url",
            "api_url",
            "require_default_branch_head",
            "expected_default_branch_sha",
        }
        if set(payload) != expected_fields:
            raise PublicationLedgerError("GitHub publication attempt payload schema is invalid")
        try:
            return cls(
                repository=cast("str", payload["repository"]),
                run_id=cast("int", payload["run_id"]),
                run_attempt=cast("int", payload["run_attempt"]),
                workflow=cast("str", payload["workflow"]),
                workflow_ref=cast("str", payload["workflow_ref"]),
                job=cast("str", payload["job"]),
                workflow_sha=cast("str", payload["workflow_sha"]),
                source_sha=cast("str", payload["source_sha"]),
                actor=cast("str", payload["actor"]),
                server_url=cast("str", payload["server_url"]),
                api_url=cast("str", payload["api_url"]),
                require_default_branch_head=cast(
                    "bool",
                    payload["require_default_branch_head"],
                ),
                expected_default_branch_sha=cast(
                    "str | None",
                    payload["expected_default_branch_sha"],
                ),
            )
        except (TypeError, ValueError) as exc:
            raise PublicationLedgerError("GitHub publication attempt payload is invalid") from exc


@dataclass(frozen=True, slots=True)
class ExecutorReceipt:
    repository: str
    run_id: int
    run_attempt: int
    workflow_id: int
    workflow: str
    workflow_path: str
    workflow_sha: str
    job: str
    job_id: int
    job_url: str
    actor: str
    log_url: str
    workflow_content_sha256: str
    admission_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "workflow_id": self.workflow_id,
            "workflow": self.workflow,
            "workflow_path": self.workflow_path,
            "workflow_sha": self.workflow_sha,
            "job": self.job,
            "job_id": self.job_id,
            "job_url": self.job_url,
            "actor": self.actor,
            "log_url": self.log_url,
            "workflow_content_sha256": self.workflow_content_sha256,
            "admission_digest": self.admission_digest,
        }


@dataclass(frozen=True, slots=True)
class DeploymentStatusReceipt:
    status_id: int
    state: str
    created_at: str
    description: str
    log_url: str
    url: str
    executor: ExecutorReceipt
    creator_login: str
    creator_id: int
    nonce: str | None = None
    takeover_sha256: str | None = None
    bound_claim_digest: str | None = None
    resolved_version: int | None = None
    resolution_digest: str | None = None

    @property
    def claim_digest(self) -> str:
        if self.state == "in_progress" and self.nonce is not None:
            return _canonical_sha256(
                {
                    "status_id": self.status_id,
                    "created_at": self.created_at,
                    "nonce": self.nonce,
                    "executor_admission_digest": self.executor.admission_digest,
                }
            )
        if self.state == "success" and self.bound_claim_digest is not None:
            return self.bound_claim_digest
        raise PublicationLedgerError("GitHub publication status does not contain a claim digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_id": self.status_id,
            "state": self.state,
            "created_at": self.created_at,
            "description": self.description,
            "log_url": self.log_url,
            "url": self.url,
            "executor": self.executor.to_dict(),
            "creator_login": self.creator_login,
            "creator_id": self.creator_id,
            "nonce": self.nonce,
            "takeover_sha256": self.takeover_sha256,
            "bound_claim_digest": self.bound_claim_digest,
            "resolved_version": self.resolved_version,
            "resolution_digest": self.resolution_digest,
        }


@dataclass(frozen=True, slots=True)
class DeploymentReceipt:
    deployment_id: int
    created_at: str
    intent: PublicationIntent
    attempt: PublicationAttempt
    state: str
    url: str
    statuses_url: str
    latest_status: DeploymentStatusReceipt | None
    statuses: tuple[DeploymentStatusReceipt, ...]
    created_by_current: bool = False

    @property
    def intent_id(self) -> str:
        return self.intent.intent_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "created_at": self.created_at,
            "intent_id": self.intent_id,
            "state": self.state,
            "url": self.url,
            "statuses_url": self.statuses_url,
            "latest_status": (
                self.latest_status.to_dict() if self.latest_status is not None else None
            ),
            "created_by_current": self.created_by_current,
        }


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    deployment_id: int
    status_id: int
    intent_id: str
    dataset: str
    nonce: str
    claim_digest: str
    executor_admission_digest: str
    run_id: int
    run_attempt: int
    job: str
    url: str
    takeover_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "status_id": self.status_id,
            "intent_id": self.intent_id,
            "dataset": self.dataset,
            "nonce": self.nonce,
            "claim_digest": self.claim_digest,
            "executor_admission_digest": self.executor_admission_digest,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "job": self.job,
            "url": self.url,
            "takeover_sha256": self.takeover_sha256,
        }


@dataclass(frozen=True, slots=True)
class ResolutionReceipt:
    deployment_id: int
    status_id: int
    intent_id: str
    resolved_version: int
    publication_marker_sha256: str
    readback_fingerprint: str
    resolution_digest: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "status_id": self.status_id,
            "intent_id": self.intent_id,
            "resolved_version": self.resolved_version,
            "publication_marker_sha256": self.publication_marker_sha256,
            "readback_fingerprint": self.readback_fingerprint,
            "resolution_digest": self.resolution_digest,
            "url": self.url,
        }


@dataclass(frozen=True, slots=True)
class LedgerInventory:
    dataset: str
    records: tuple[DeploymentReceipt, ...]

    @property
    def unresolved(self) -> tuple[DeploymentReceipt, ...]:
        return tuple(record for record in self.records if record.state in _UNRESOLVED_STATES)

    @property
    def current(self) -> DeploymentReceipt | None:
        return self.records[-1] if self.records else None

    def exact(self, intent_id: str) -> tuple[DeploymentReceipt, ...]:
        return tuple(record for record in self.records if record.intent_id == intent_id)


class PublicationLedger(Protocol):
    @property
    def source_sha(self) -> str: ...

    def scan_dataset(self, dataset: str) -> LedgerInventory: ...

    def prepare(self, intent: PublicationIntent) -> DeploymentReceipt: ...

    def claim_pending(self, receipt: DeploymentReceipt) -> ExecutionReceipt: ...

    def record_pending_takeover(
        self,
        receipt: DeploymentReceipt,
        takeover: PendingTakeoverReceiptV1,
        takeover_member: ArtifactMemberIdentityV1,
    ) -> PendingTakeoverStatusReceiptV1: ...

    def claim_pending_takeover(
        self,
        receipt: DeploymentReceipt,
        takeover: PendingTakeoverReceiptV1,
        durable_status: PendingTakeoverStatusReceiptV1,
    ) -> ExecutionReceipt: ...

    def find_remote_match(
        self,
        marker: Mapping[str, Any],
        *,
        marker_sha256: str,
    ) -> DeploymentReceipt | None: ...

    def mark_reconciled(
        self,
        receipt: DeploymentReceipt,
        *,
        resolved_version: int,
        publication_marker_sha256: str,
        readback_fingerprint: str,
    ) -> ResolutionReceipt: ...

    def mark_resolved(
        self,
        execution: ExecutionReceipt,
        *,
        resolved_version: int,
        publication_marker_sha256: str,
        readback_fingerprint: str,
    ) -> ResolutionReceipt: ...


class GitHubDeploymentPublicationLedger:
    """Crash-durable write-ahead ledger backed by GitHub Deployments.

    The current Actions executor is admitted only after direct REST verification
    of its run attempt and immutable workflow content. That content must place the
    active job in the shared dataset-wide publisher concurrency group. GitHub then
    supplies the cross-host mutex; the bounded head protocol fails closed if remote
    chronology or state violates that serialized history.
    """

    def __init__(
        self,
        *,
        token: str,
        attempt: PublicationAttempt,
        transport: GitHubTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        nonce_factory: Callable[[], str] | None = None,
        request_timeout_seconds: float = 30.0,
        snapshot_delay_seconds: float = 1.0,
        recovery_delay_seconds: float = 2.0,
        recovery_attempts: int = 3,
    ) -> None:
        if not token.strip():
            raise PublicationLedgerError("Durable Kaggle publication requires GH_TOKEN")
        if request_timeout_seconds <= 0:
            raise ValueError("GitHub ledger request timeout must be positive")
        if snapshot_delay_seconds < 0 or recovery_delay_seconds < 0:
            raise ValueError("GitHub ledger observation delays must be nonnegative")
        if recovery_attempts <= 0:
            raise ValueError("GitHub ledger recovery_attempts must be positive")
        self._token = token
        self._attempt = attempt
        self._transport = transport or UrllibGitHubTransport()
        self._sleep = sleep
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
        self._request_timeout_seconds = request_timeout_seconds
        self._snapshot_delay_seconds = snapshot_delay_seconds
        self._recovery_delay_seconds = recovery_delay_seconds
        self._recovery_attempts = recovery_attempts
        self._executor_cache: dict[tuple[int, int, str], ExecutorReceipt] = {}

    @classmethod
    def from_actions_env(
        cls,
        env: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> GitHubDeploymentPublicationLedger:
        values = os.environ if env is None else env
        token = values.get("GH_TOKEN", "").strip()
        if not token:
            raise PublicationLedgerError("Durable Kaggle publication requires GH_TOKEN")
        return cls(
            token=token,
            attempt=PublicationAttempt.from_actions_env(values),
            **kwargs,
        )

    @property
    def source_sha(self) -> str:
        return self._attempt.source_sha

    def _require_originating_workflow_run(self, receipt: DeploymentReceipt) -> None:
        """Permit pending-intent recovery only within its original workflow run."""
        origin = receipt.attempt
        current = self._attempt
        if (
            origin.repository != current.repository
            or origin.run_id != current.run_id
            or origin.workflow_ref != current.workflow_ref
            or origin.workflow_sha != current.workflow_sha
            or origin.source_sha != current.source_sha
            or origin.job != current.job
        ):
            raise PublicationLedgerPendingError(
                "Kaggle publication intent is reconciliation-only in its original workflow run"
            )

    def _require_cross_run_origin_terminal(self, receipt: DeploymentReceipt) -> None:
        """Require a foreign claiming executor to be durably terminal."""

        origin = receipt.attempt
        current = self._attempt
        if (
            origin.repository == current.repository
            and origin.run_id == current.run_id
            and origin.run_attempt == current.run_attempt
            and origin.job == current.job
        ):
            return
        run_url = (
            f"{self._repository_api_url}/actions/runs/{origin.run_id}/attempts/{origin.run_attempt}"
        )
        run = self._require_object(
            self._request("GET", run_url),
            operation="reconciliation origin terminal receipt",
        )
        if run.get("status") != "completed" or run.get("conclusion") not in _COMPLETED_CONCLUSIONS:
            raise PublicationLedgerPendingError(
                "Kaggle publication origin publisher is not terminal"
            )

    @staticmethod
    def _require_execution_owner(
        execution: ExecutionReceipt,
        executor: ExecutorReceipt,
    ) -> None:
        """Require direct resolution to remain owned by its claiming executor."""
        if (
            execution.run_id != executor.run_id
            or execution.run_attempt != executor.run_attempt
            or execution.job != executor.job
            or execution.executor_admission_digest != executor.admission_digest
        ):
            raise PublicationLedgerPendingError(
                "GitHub publication execution is no longer owned by the current executor"
            )

    @staticmethod
    def environment_for_dataset(dataset: str) -> str:
        digest = hashlib.sha256(dataset.encode("utf-8")).hexdigest()[:16]
        return f"nbadb-kaggle-{digest}"

    @property
    def _repository_api_url(self) -> str:
        owner, repository = self._attempt.repository.split("/", 1)
        owner_path = urllib.parse.quote(owner, safe="")
        repository_path = urllib.parse.quote(repository, safe="")
        return f"{self._attempt.api_url}/repos/{owner_path}/{repository_path}"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "nbadb-kaggle-publication-ledger",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> GitHubResponse:
        return self._transport.request(
            method,
            url,
            headers=self._headers,
            json_body=json_body,
            timeout_seconds=self._request_timeout_seconds,
        )

    @staticmethod
    def _require_object(response: GitHubResponse, *, operation: str) -> dict[str, Any]:
        if response.status_code not in {200, 201} or not isinstance(response.payload, dict):
            msg = f"GitHub publication ledger {operation} failed with HTTP {response.status_code}"
            raise PublicationLedgerError(msg)
        return cast("dict[str, Any]", response.payload)

    @staticmethod
    def _require_list(response: GitHubResponse, *, operation: str) -> list[Any]:
        if response.status_code != 200 or not isinstance(response.payload, list):
            msg = f"GitHub publication ledger {operation} failed with HTTP {response.status_code}"
            raise PublicationLedgerError(msg)
        return cast("list[Any]", response.payload)

    @staticmethod
    def _positive_id(value: Any, *, field: str) -> int:
        if type(value) is not int or value <= 0:
            msg = f"GitHub publication ledger {field} must be a positive integer"
            raise PublicationLedgerError(msg)
        return value

    @staticmethod
    def _require_publication_mutex(workflow_content: str, *, job: str) -> None:
        lines = workflow_content.splitlines()
        try:
            jobs_index = lines.index("jobs:")
            job_index = lines.index(f"  {job}:", jobs_index + 1)
        except ValueError as exc:
            raise PublicationLedgerError(
                "GitHub publication workflow does not contain the active publisher job"
            ) from exc
        job_end = len(lines)
        for index in range(job_index + 1, len(lines)):
            line = lines[index]
            if re.fullmatch(r"  [A-Za-z0-9_.-]+:", line):
                job_end = index
                break
        job_lines = lines[job_index:job_end]
        required_lines = (
            "    concurrency:",
            f"      group: {_PUBLICATION_MUTEX_GROUP}",
            "      queue: max",
            "      cancel-in-progress: false",
        )
        positions: list[int] = []
        for required in required_lines:
            if job_lines.count(required) != 1:
                raise PublicationLedgerError(
                    "GitHub publication workflow does not prove the exact publisher mutex"
                )
            positions.append(job_lines.index(required))
        if positions != list(range(positions[0], positions[0] + len(required_lines))):
            raise PublicationLedgerError(
                "GitHub publication workflow publisher mutex is not structurally exact"
            )

    def _workflow_content(
        self,
        *,
        workflow_path: str,
        workflow_sha: str,
    ) -> tuple[str, str]:
        quoted_path = urllib.parse.quote(workflow_path, safe="/")
        quoted_ref = urllib.parse.quote(workflow_sha, safe="")
        contents_url = f"{self._repository_api_url}/contents/{quoted_path}?ref={quoted_ref}"
        raw = self._require_object(
            self._request("GET", contents_url),
            operation="workflow content receipt",
        )
        encoded = raw.get("content")
        if (
            raw.get("type") != "file"
            or raw.get("path") != workflow_path
            or raw.get("name") != workflow_path.rsplit("/", 1)[-1]
            or raw.get("encoding") != "base64"
            or not isinstance(encoded, str)
            or type(raw.get("size")) is not int
            or raw["size"] <= 0
            or raw["size"] > _WORKFLOW_CONTENT_MAX_BYTES
            or _HEX_40_RE.fullmatch(str(raw.get("sha") or "")) is None
        ):
            raise PublicationLedgerError("GitHub publication workflow content receipt is invalid")
        try:
            decoded = base64.b64decode("".join(encoded.split()), validate=True)
            content = decoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PublicationLedgerError(
                "GitHub publication workflow content is not canonical base64 UTF-8"
            ) from exc
        if len(decoded) != raw["size"]:
            raise PublicationLedgerError("GitHub publication workflow content size is inconsistent")
        return content, hashlib.sha256(decoded).hexdigest()

    def _verify_executor_job(
        self,
        *,
        run_id: int,
        run_attempt: int,
        run_name: str,
        workflow_sha: str,
        job: str,
        require_active: bool,
    ) -> tuple[int, str]:
        jobs_base_url = (
            f"{self._repository_api_url}/actions/runs/{run_id}/attempts/{run_attempt}/jobs"
        )

        def load_page(page: int) -> tuple[int, list[Any]]:
            inventory = self._require_object(
                self._request(
                    "GET",
                    f"{jobs_base_url}?per_page=100&page={page}",
                ),
                operation="workflow attempt job inventory",
            )
            total_count = inventory.get("total_count")
            jobs = inventory.get("jobs")
            if type(total_count) is not int or not isinstance(jobs, list):
                raise PublicationLedgerError(
                    "GitHub publication workflow attempt job inventory is invalid"
                )
            return total_count, jobs

        total_count, jobs = load_page(1)
        if (
            total_count <= 0
            or total_count > _WORKFLOW_JOB_INVENTORY_LIMIT
            or len(jobs) != min(total_count, 100)
        ):
            raise PublicationLedgerError(
                "GitHub publication workflow attempt job inventory is invalid"
            )
        for page in range(2, ((total_count + 99) // 100) + 1):
            page_total, page_jobs = load_page(page)
            expected_page_size = min(100, total_count - len(jobs))
            if page_total != total_count or len(page_jobs) != expected_page_size:
                raise PublicationLedgerError(
                    "GitHub publication workflow attempt job inventory changed"
                )
            jobs.extend(page_jobs)
        if len(jobs) != total_count:
            raise PublicationLedgerError(
                "GitHub publication workflow attempt job inventory is incomplete"
            )
        job_ids: set[int] = set()
        run_url = f"{self._repository_api_url}/actions/runs/{run_id}"
        for candidate in jobs:
            if not isinstance(candidate, dict):
                raise PublicationLedgerError(
                    "GitHub publication workflow attempt job inventory is malformed"
                )
            candidate_id = self._positive_id(candidate.get("id"), field="job id")
            candidate_status = candidate.get("status")
            candidate_conclusion = candidate.get("conclusion")
            if (
                candidate_id in job_ids
                or candidate.get("run_id") != run_id
                or candidate.get("run_attempt") != run_attempt
                or candidate.get("run_url") != run_url
                or candidate.get("head_sha") != workflow_sha
                or not isinstance(candidate.get("name"), str)
                or not candidate["name"].strip()
                or candidate.get("workflow_name") != run_name
                or candidate.get("url") != f"{self._repository_api_url}/actions/jobs/{candidate_id}"
                or not (
                    (candidate_status in _ACTIVE_JOB_STATES and candidate_conclusion is None)
                    or (
                        candidate_status == "completed"
                        and candidate_conclusion in _COMPLETED_CONCLUSIONS
                    )
                )
            ):
                raise PublicationLedgerError(
                    "GitHub publication workflow attempt job inventory is malformed"
                )
            job_ids.add(candidate_id)
        matches = [candidate for candidate in jobs if candidate.get("name") == job]
        if len(matches) != 1:
            raise PublicationLedgerError(
                "GitHub publication workflow does not have one exact publisher job"
            )
        summary = matches[0]
        job_id = self._positive_id(summary.get("id"), field="job id")
        job_url = f"{self._repository_api_url}/actions/jobs/{job_id}"
        direct = self._require_object(
            self._request("GET", job_url),
            operation="direct workflow job receipt",
        )
        receipt_fields = (
            "id",
            "run_id",
            "run_attempt",
            "run_url",
            "head_sha",
            "workflow_name",
            "name",
            "status",
            "conclusion",
            "url",
        )
        if any(summary.get(field) != direct.get(field) for field in receipt_fields):
            raise PublicationLedgerError(
                "GitHub publication direct workflow job receipt changed from inventory"
            )
        status = direct.get("status")
        conclusion = direct.get("conclusion")
        if (
            direct.get("id") != job_id
            or direct.get("run_id") != run_id
            or direct.get("run_attempt") != run_attempt
            or direct.get("run_url") != run_url
            or direct.get("head_sha") != workflow_sha
            or direct.get("workflow_name") != run_name
            or direct.get("name") != job
            or direct.get("url") != job_url
        ):
            raise PublicationLedgerError("GitHub publication workflow job provenance is invalid")
        if require_active:
            if status != "in_progress" or conclusion is not None:
                raise PublicationLedgerPendingError(
                    "GitHub publication executor job is not currently in progress"
                )
        elif not (
            (status == "in_progress" and conclusion is None)
            or (status == "completed" and conclusion in _COMPLETED_CONCLUSIONS)
        ):
            raise PublicationLedgerError("GitHub publication executor job state is invalid")
        return job_id, job_url

    def _verify_executor(
        self,
        *,
        run_id: int,
        run_attempt: int,
        job: str,
        require_active: bool,
    ) -> ExecutorReceipt:
        if run_id <= 0 or run_attempt <= 0 or _JOB_RE.fullmatch(job) is None:
            raise PublicationLedgerError("GitHub publication executor identity is invalid")
        cache_key = (run_id, run_attempt, job)
        cached = self._executor_cache.get(cache_key)
        if cached is not None and not require_active:
            return cached
        run_url = f"{self._repository_api_url}/actions/runs/{run_id}/attempts/{run_attempt}"
        run = self._require_object(
            self._request("GET", run_url),
            operation="workflow run-attempt receipt",
        )
        workflow_id = self._positive_id(run.get("workflow_id"), field="workflow id")
        workflow_sha = run.get("head_sha")
        workflow_path = run.get("path")
        run_name = run.get("name")
        actor = run.get("actor")
        repository = run.get("repository")
        head_repository = run.get("head_repository")
        status = run.get("status")
        conclusion = run.get("conclusion")
        if (
            run.get("id") != run_id
            or run.get("run_attempt") != run_attempt
            or _HEX_40_RE.fullmatch(str(workflow_sha or "")) is None
            or not isinstance(workflow_path, str)
            or not workflow_path.startswith(".github/workflows/")
            or not workflow_path.endswith((".yml", ".yaml"))
            or not isinstance(run_name, str)
            or not run_name.strip()
            or not isinstance(actor, dict)
            or not isinstance(actor.get("login"), str)
            or not actor["login"].strip()
            or not isinstance(repository, dict)
            or repository.get("full_name") != self._attempt.repository
            or not isinstance(head_repository, dict)
            or head_repository.get("full_name") != self._attempt.repository
            or run.get("event") not in {"schedule", "workflow_dispatch"}
        ):
            raise PublicationLedgerError(
                "GitHub publication workflow run-attempt provenance is invalid"
            )
        run_is_active = status in _ACTIVE_RUN_STATES and conclusion is None
        if require_active:
            if not run_is_active:
                raise PublicationLedgerPendingError(
                    "GitHub publication executor run is not currently active"
                )
        elif not (
            run_is_active or (status == "completed" and conclusion in _COMPLETED_CONCLUSIONS)
        ):
            raise PublicationLedgerError("GitHub publication executor state is invalid")

        job_id, job_url = self._verify_executor_job(
            run_id=run_id,
            run_attempt=run_attempt,
            run_name=run_name,
            workflow_sha=cast("str", workflow_sha),
            job=job,
            require_active=require_active,
        )
        if cached is not None:
            if (
                cached.workflow_id != workflow_id
                or cached.workflow_path != workflow_path
                or cached.workflow_sha != workflow_sha
                or cached.job_id != job_id
                or cached.job_url != job_url
                or cached.actor != actor["login"]
            ):
                raise PublicationLedgerError("GitHub publication executor receipt changed")
            return cached

        workflow_url = f"{self._repository_api_url}/actions/workflows/{workflow_id}"
        workflow = self._require_object(
            self._request("GET", workflow_url),
            operation="workflow definition receipt",
        )
        workflow_name = workflow.get("name")
        if (
            workflow.get("id") != workflow_id
            or not isinstance(workflow_name, str)
            or not workflow_name.strip()
            or workflow.get("path") != workflow_path
            or workflow.get("state") != "active"
            or workflow.get("url") != workflow_url
        ):
            raise PublicationLedgerError(
                "GitHub publication workflow definition identity is invalid"
            )
        workflow_content, content_sha256 = self._workflow_content(
            workflow_path=workflow_path,
            workflow_sha=cast("str", workflow_sha),
        )
        self._require_publication_mutex(workflow_content, job=job)
        stable_identity = {
            "repository": self._attempt.repository,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "workflow_id": workflow_id,
            "workflow": workflow_name,
            "workflow_path": workflow_path,
            "workflow_sha": workflow_sha,
            "job": job,
            "job_id": job_id,
            "job_url": job_url,
            "actor": actor["login"],
            "workflow_content_sha256": content_sha256,
            "mutex_group": _PUBLICATION_MUTEX_GROUP,
        }
        receipt = ExecutorReceipt(
            repository=self._attempt.repository,
            run_id=run_id,
            run_attempt=run_attempt,
            workflow_id=workflow_id,
            workflow=workflow_name,
            workflow_path=workflow_path,
            workflow_sha=cast("str", workflow_sha),
            job=job,
            job_id=job_id,
            job_url=job_url,
            actor=cast("str", actor["login"]),
            log_url=(
                f"{self._attempt.server_url}/{self._attempt.repository}"
                f"/actions/runs/{run_id}/attempts/{run_attempt}"
            ),
            workflow_content_sha256=content_sha256,
            admission_digest=_canonical_sha256(stable_identity),
        )
        self._executor_cache[cache_key] = receipt
        return receipt

    def _verify_default_branch_source(self) -> None:
        expected_default_branch_sha = self._attempt.expected_default_branch_sha
        if expected_default_branch_sha is None:
            raise PublicationLedgerError(
                "GitHub publication ledger expected default branch SHA is missing"
            )
        repository = self._require_object(
            self._request("GET", self._repository_api_url),
            operation="repository default-branch receipt",
        )
        default_branch = repository.get("default_branch")
        if (
            repository.get("full_name") != self._attempt.repository
            or not isinstance(default_branch, str)
            or not default_branch.strip()
        ):
            raise PublicationLedgerError("GitHub publication repository default branch is invalid")
        quoted_branch = urllib.parse.quote(default_branch, safe="")
        ref_request_url = f"{self._repository_api_url}/git/ref/heads/{quoted_branch}"
        ref_response_url = f"{self._repository_api_url}/git/refs/heads/{quoted_branch}"
        ref = self._require_object(
            self._request("GET", ref_request_url),
            operation="default-branch source receipt",
        )
        ref_object = ref.get("object")
        if (
            ref.get("ref") != f"refs/heads/{default_branch}"
            or ref.get("url") != ref_response_url
            or not isinstance(ref_object, dict)
            or ref_object.get("type") != "commit"
            or ref_object.get("sha") != expected_default_branch_sha
        ):
            raise PublicationLedgerPendingError(
                "GitHub default branch no longer equals the approved publication head"
            )

    def _verify_current_executor(self) -> ExecutorReceipt:
        executor = self._verify_executor(
            run_id=self._attempt.run_id,
            run_attempt=self._attempt.run_attempt,
            job=self._attempt.job,
            require_active=True,
        )
        if (
            executor.workflow != self._attempt.workflow
            or executor.workflow_path != self._attempt.workflow_path
            or executor.workflow_sha != self._attempt.workflow_sha
            or executor.actor != self._attempt.actor
            or executor.log_url != self._attempt.log_url
        ):
            raise PublicationLedgerError(
                "GitHub current publication executor does not match Actions context"
            )
        if self._attempt.require_default_branch_head:
            self._verify_default_branch_source()
        return executor

    def _deployment_payload(
        self,
        intent: PublicationIntent,
    ) -> dict[str, Any]:
        if intent.source_sha != self.source_sha:
            raise PublicationLedgerError(
                "Kaggle publication intent source SHA does not match trusted workflow source"
            )
        return {
            "schema_version": 1,
            "kind": _INTENT_KIND,
            "intent_id": intent.intent_id,
            "intent": intent.semantic_payload(),
            "attempt": self._attempt.payload(),
        }

    def _parse_deployment_payload(
        self,
        payload: Any,
    ) -> tuple[PublicationIntent, PublicationAttempt]:
        if not isinstance(payload, dict):
            raise PublicationLedgerError("GitHub publication deployment payload is not an object")
        payload = cast("dict[str, Any]", payload)
        if set(payload) != {
            "schema_version",
            "kind",
            "intent_id",
            "intent",
            "attempt",
        }:
            raise PublicationLedgerError("GitHub publication deployment payload schema is invalid")
        if payload.get("schema_version") != 1 or payload.get("kind") != _INTENT_KIND:
            raise PublicationLedgerError("GitHub publication deployment payload kind is invalid")
        if not isinstance(payload.get("intent"), dict) or not isinstance(
            payload.get("attempt"), dict
        ):
            raise PublicationLedgerError("GitHub publication deployment payload body is invalid")
        intent = PublicationIntent.from_payload(cast("dict[str, Any]", payload["intent"]))
        attempt = PublicationAttempt.from_payload(cast("dict[str, Any]", payload["attempt"]))
        if payload.get("intent_id") != intent.intent_id:
            raise PublicationLedgerError("GitHub publication deployment intent digest is invalid")
        if attempt.repository != self._attempt.repository:
            raise PublicationLedgerError("GitHub publication deployment repository is invalid")
        if attempt.source_sha != intent.source_sha:
            raise PublicationLedgerError("GitHub publication deployment source binding is invalid")
        return intent, attempt

    def _trusted_log_url(self, value: Any) -> tuple[str, int, int]:
        if not isinstance(value, str):
            raise PublicationLedgerError("GitHub publication deployment status log URL is invalid")
        prefix = f"{self._attempt.server_url}/{self._attempt.repository}/actions/runs/"
        suffix = value.removeprefix(prefix)
        match = re.fullmatch(r"([1-9][0-9]*)/attempts/([1-9][0-9]*)", suffix)
        if suffix == value or match is None:
            raise PublicationLedgerError(
                "GitHub publication deployment status log URL is untrusted"
            )
        return value, int(match.group(1)), int(match.group(2))

    def _parse_status(
        self,
        raw: Mapping[str, Any],
        *,
        deployment_id: int,
        environment: str,
        intent_id: str,
    ) -> DeploymentStatusReceipt:
        status_id = self._positive_id(raw.get("id"), field="status id")
        expected_url = (
            f"{self._repository_api_url}/deployments/{deployment_id}/statuses/{status_id}"
        )
        expected_deployment_url = f"{self._repository_api_url}/deployments/{deployment_id}"
        if (
            raw.get("url") != expected_url
            or raw.get("deployment_url") != expected_deployment_url
            or raw.get("repository_url") != self._repository_api_url
            or raw.get("environment") != environment
        ):
            raise PublicationLedgerError("GitHub publication deployment status identity is invalid")
        creator = raw.get("creator")
        if (
            not isinstance(creator, dict)
            or not isinstance(creator.get("login"), str)
            or not creator["login"].strip()
            or type(creator.get("id")) is not int
            or creator["id"] <= 0
        ):
            raise PublicationLedgerError("GitHub publication deployment status creator is invalid")
        state = raw.get("state")
        description = raw.get("description")
        if not isinstance(state, str) or not isinstance(description, str):
            raise PublicationLedgerError("GitHub publication deployment status body is invalid")
        created_at = raw.get("created_at")
        _parse_github_timestamp(created_at, field="status created_at")
        log_url, run_id, run_attempt = self._trusted_log_url(raw.get("log_url"))
        nonce: str | None = None
        takeover_sha256: str | None = None
        bound_claim_digest: str | None = None
        resolved_version: int | None = None
        resolution_digest: str | None = None
        job: str
        if state == "pending":
            match = _TAKEOVER_DESCRIPTION_RE.fullmatch(description)
            if match is None:
                raise PublicationLedgerError(
                    "GitHub publication takeover status description is invalid"
                )
            takeover_sha256 = _parse_digest_token(match.group(1), field="takeover digest")
            job = match.group(2)
        elif state == "in_progress":
            match = _IN_PROGRESS_DESCRIPTION_RE.fullmatch(description)
            if match is None or match.group(1) != intent_id:
                raise PublicationLedgerError(
                    "GitHub publication in-progress status description is invalid"
                )
            nonce = match.group(2)
            job = match.group(3)
        elif state == "success":
            match = _SUCCESS_DESCRIPTION_RE.fullmatch(description)
            if match is None:
                raise PublicationLedgerError(
                    "GitHub publication success status description is invalid"
                )
            resolved_version = int(match.group(1))
            bound_claim_digest = _parse_digest_token(
                match.group(2),
                field="claim digest",
            )
            resolution_digest = _parse_digest_token(
                match.group(3),
                field="resolution digest",
            )
            job = match.group(4)
        else:
            raise PublicationLedgerError(
                f"GitHub publication deployment status state is unsupported: {state!r}"
            )
        executor = self._verify_executor(
            run_id=run_id,
            run_attempt=run_attempt,
            job=job,
            require_active=False,
        )
        if executor.log_url != log_url:
            raise PublicationLedgerError(
                "GitHub publication status executor log URL is inconsistent"
            )
        return DeploymentStatusReceipt(
            status_id=status_id,
            state=state,
            created_at=cast("str", created_at),
            description=description,
            log_url=log_url,
            url=expected_url,
            executor=executor,
            creator_login=cast("str", creator["login"]),
            creator_id=cast("int", creator["id"]),
            nonce=nonce,
            takeover_sha256=takeover_sha256,
            bound_claim_digest=bound_claim_digest,
            resolved_version=resolved_version,
            resolution_digest=resolution_digest,
        )

    def _list_window(self, url: str, *, operation: str, limit: int) -> list[Any]:
        separator = "&" if "?" in url else "?"
        response = self._request(
            "GET",
            f"{url}{separator}per_page={limit}&page=1",
        )
        items = self._require_list(response, operation=operation)
        if len(items) > limit:
            raise PublicationLedgerError(
                f"GitHub publication ledger {operation} exceeded its bounded window"
            )
        return items

    def _load_statuses(
        self,
        *,
        deployment_id: int,
        statuses_url: str,
        environment: str,
        intent: PublicationIntent,
    ) -> tuple[DeploymentStatusReceipt, ...]:
        summaries = self._list_window(
            statuses_url,
            operation="status inventory",
            limit=_STATUS_RECEIPT_LIMIT,
        )
        if len(summaries) == _STATUS_RECEIPT_LIMIT:
            raise PublicationLedgerError(
                "GitHub publication deployment has more statuses than the protocol permits"
            )
        status_ids: set[int] = set()
        statuses: list[DeploymentStatusReceipt] = []
        summary_timestamps: list[datetime] = []
        for summary in summaries:
            if not isinstance(summary, dict):
                raise PublicationLedgerError(
                    "GitHub publication deployment status inventory is malformed"
                )
            status_id = self._positive_id(summary.get("id"), field="status id")
            if status_id in status_ids:
                raise PublicationLedgerError(
                    "GitHub publication deployment status inventory has duplicate ids"
                )
            status_ids.add(status_id)
            summary_created_at = summary.get("created_at")
            summary_timestamps.append(
                _parse_github_timestamp(
                    summary_created_at,
                    field="status inventory created_at",
                )
            )
            status_url = (
                f"{self._repository_api_url}/deployments/{deployment_id}/statuses/{status_id}"
            )
            direct = self._require_object(
                self._request("GET", status_url),
                operation="direct status receipt",
            )
            parsed = self._parse_status(
                direct,
                deployment_id=deployment_id,
                environment=environment,
                intent_id=intent.intent_id,
            )
            if parsed.created_at != summary_created_at:
                raise PublicationLedgerError(
                    "GitHub publication direct status receipt changed from inventory"
                )
            statuses.append(parsed)
        if len(set(summary_timestamps)) != len(summary_timestamps):
            raise PublicationLedgerError(
                "GitHub publication status inventory chronology is invalid"
            )
        statuses.sort(
            key=lambda status: _parse_github_timestamp(
                status.created_at,
                field="status created_at",
            )
        )
        state_sequence = tuple(status.state for status in statuses)
        allowed_sequences = {
            (),
            ("pending",),
            ("in_progress",),
            ("success",),
            ("pending", "in_progress"),
            ("in_progress", "success"),
            ("pending", "in_progress", "success"),
        }
        if state_sequence not in allowed_sequences:
            raise PublicationLedgerError(
                "GitHub publication status history is not terminally ordered"
            )
        claims = tuple(status for status in statuses if status.state == "in_progress")
        successes = tuple(status for status in statuses if status.state == "success")
        if successes:
            if len(successes) != 1:
                raise PublicationLedgerError(
                    "GitHub publication status history is not terminally ordered"
                )
            success = successes[0]
            if success.resolved_version is None:
                raise PublicationLedgerError(
                    "GitHub publication status history is not terminally ordered"
                )
            if state_sequence != ("success",) and (
                len(claims) != 1 or success.claim_digest != claims[0].claim_digest
            ):
                raise PublicationLedgerError(
                    "GitHub publication status history is not terminally ordered"
                )
        if statuses and statuses[-1].state == "success":
            success = statuses[-1]
            if success.resolved_version is None:
                raise PublicationLedgerError("GitHub publication success status is incomplete")
            expected_resolution_digest = _resolution_digest(
                intent_id=intent.intent_id,
                resolved_version=success.resolved_version,
                publication_marker_sha256=intent.publication_marker_sha256,
                readback_fingerprint=intent.staged_tree_fingerprint,
                claim_digest=success.claim_digest,
                resolver_admission_digest=success.executor.admission_digest,
            )
            if success.resolution_digest != expected_resolution_digest:
                raise PublicationLedgerError(
                    "GitHub publication success status receipt digest is invalid"
                )
        return tuple(statuses)

    def _parse_deployment(self, raw: Mapping[str, Any], *, dataset: str) -> DeploymentReceipt:
        deployment_id = self._positive_id(raw.get("id"), field="deployment id")
        expected_url = f"{self._repository_api_url}/deployments/{deployment_id}"
        expected_statuses_url = f"{expected_url}/statuses"
        environment = self.environment_for_dataset(dataset)
        created_at = raw.get("created_at")
        _parse_github_timestamp(created_at, field="deployment created_at")
        if (
            raw.get("url") != expected_url
            or raw.get("statuses_url") != expected_statuses_url
            or raw.get("repository_url") != self._repository_api_url
            or raw.get("task") != PUBLICATION_DEPLOYMENT_TASK
            or raw.get("environment") != environment
            or raw.get("transient_environment") is not False
            or raw.get("production_environment") is not True
        ):
            raise PublicationLedgerError("GitHub publication deployment identity is invalid")
        intent, attempt = self._parse_deployment_payload(raw.get("payload"))
        if (
            intent.dataset != dataset
            or raw.get("sha") != intent.source_sha
            or raw.get("ref") != intent.source_sha
            or raw.get("description") != f"nbadb pending intent={intent.intent_id}"
        ):
            raise PublicationLedgerError("GitHub publication deployment contract is invalid")
        creator = raw.get("creator")
        if (
            not isinstance(creator, dict)
            or not isinstance(creator.get("login"), str)
            or not creator["login"].strip()
            or type(creator.get("id")) is not int
            or creator["id"] <= 0
        ):
            raise PublicationLedgerError("GitHub publication deployment creator is invalid")
        statuses = self._load_statuses(
            deployment_id=deployment_id,
            statuses_url=expected_statuses_url,
            environment=environment,
            intent=intent,
        )
        latest_status = statuses[-1] if statuses else None
        state = latest_status.state if latest_status is not None else "pending"
        return DeploymentReceipt(
            deployment_id=deployment_id,
            created_at=cast("str", created_at),
            intent=intent,
            attempt=attempt,
            state=state,
            url=expected_url,
            statuses_url=expected_statuses_url,
            latest_status=latest_status,
            statuses=statuses,
        )

    def _snapshot_inventory(self, dataset: str) -> LedgerInventory:
        environment = self.environment_for_dataset(dataset)
        owner, repository = self._attempt.repository.split("/", 1)
        graphql = self._require_object(
            self._request(
                "POST",
                f"{self._attempt.api_url}/graphql",
                json_body={
                    "query": _DEPLOYMENT_HEAD_QUERY,
                    "variables": {
                        "owner": owner,
                        "repository": repository,
                        "environment": environment,
                    },
                },
            ),
            operation="ordered deployment head",
        )
        data = graphql.get("data")
        repository_payload = data.get("repository") if isinstance(data, dict) else None
        deployments_payload = (
            repository_payload.get("deployments") if isinstance(repository_payload, dict) else None
        )
        summaries = (
            deployments_payload.get("nodes") if isinstance(deployments_payload, dict) else None
        )
        if (
            graphql.get("errors") is not None
            or not isinstance(summaries, list)
            or len(summaries) > _HEAD_DEPLOYMENT_LIMIT
        ):
            raise PublicationLedgerError("GitHub publication ordered deployment head is malformed")
        deployment_ids: set[int] = set()
        records: list[DeploymentReceipt] = []
        summary_timestamps: list[datetime] = []
        for summary in summaries:
            if not isinstance(summary, dict):
                raise PublicationLedgerError("GitHub publication deployment inventory is malformed")
            deployment_id = self._positive_id(
                summary.get("databaseId"),
                field="deployment id",
            )
            if deployment_id in deployment_ids:
                raise PublicationLedgerError(
                    "GitHub publication deployment inventory has duplicate ids"
                )
            deployment_ids.add(deployment_id)
            summary_created_at = summary.get("createdAt")
            summary_timestamps.append(
                _parse_github_timestamp(
                    summary_created_at,
                    field="deployment inventory created_at",
                )
            )
            deployment_url = f"{self._repository_api_url}/deployments/{deployment_id}"
            direct = self._require_object(
                self._request("GET", deployment_url),
                operation="direct deployment receipt",
            )
            parsed = self._parse_deployment(direct, dataset=dataset)
            if parsed.created_at != summary_created_at:
                raise PublicationLedgerError(
                    "GitHub publication direct deployment receipt changed from inventory"
                )
            records.append(parsed)
        if any(
            current >= previous
            for previous, current in zip(
                summary_timestamps,
                summary_timestamps[1:],
                strict=False,
            )
        ):
            raise PublicationLedgerError(
                "GitHub publication deployment inventory chronology is invalid"
            )
        records.sort(
            key=lambda record: _parse_github_timestamp(
                record.created_at,
                field="deployment created_at",
            )
        )
        inventory = LedgerInventory(dataset=dataset, records=tuple(records))
        if len(inventory.unresolved) > 1:
            ids = ", ".join(str(record.deployment_id) for record in inventory.unresolved)
            raise PublicationLedgerError(
                f"GitHub publication ledger has multiple unresolved intents: {ids}"
            )
        if inventory.unresolved and inventory.current != inventory.unresolved[0]:
            raise PublicationLedgerError(
                "GitHub publication ledger has an unresolved intent behind its current head"
            )
        return inventory

    @staticmethod
    def _inventory_identity(inventory: LedgerInventory) -> str:
        payload = {
            "dataset": inventory.dataset,
            "records": [
                {
                    "deployment_id": record.deployment_id,
                    "created_at": record.created_at,
                    "intent_id": record.intent_id,
                    "state": record.state,
                    "latest_status": (
                        record.latest_status.to_dict() if record.latest_status is not None else None
                    ),
                    "status_ids": [status.status_id for status in record.statuses],
                }
                for record in inventory.records
            ],
        }
        return _canonical_sha256(payload)

    def scan_dataset(self, dataset: str) -> LedgerInventory:
        observations: list[tuple[str, LedgerInventory]] = []
        for index in range(3):
            if index:
                self._sleep(self._snapshot_delay_seconds)
            inventory = self._snapshot_inventory(dataset)
            observations.append((self._inventory_identity(inventory), inventory))
        if observations[-1][0] != observations[-2][0]:
            raise PublicationLedgerError("GitHub publication ledger inventory did not stabilize")
        return observations[-1][1]

    def _recover_write(
        self,
        dataset: str,
        predicate: Callable[[DeploymentReceipt], bool],
        *,
        operation: str,
    ) -> DeploymentReceipt:
        for attempt in range(self._recovery_attempts):
            if attempt:
                self._sleep(self._recovery_delay_seconds)
            inventory = self.scan_dataset(dataset)
            matches = tuple(record for record in inventory.records if predicate(record))
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise PublicationLedgerError(
                    f"GitHub publication ledger {operation} resolved ambiguously"
                )
        raise PublicationLedgerPendingError(
            f"GitHub publication ledger {operation} outcome is unresolved"
        )

    def prepare(self, intent: PublicationIntent) -> DeploymentReceipt:
        if intent.source_sha != self.source_sha:
            raise PublicationLedgerError(
                "Kaggle publication intent source SHA does not match trusted workflow source"
            )
        self._verify_current_executor()
        inventory = self.scan_dataset(intent.dataset)
        current = inventory.current
        if current is not None and current.state in _UNRESOLVED_STATES:
            if current.intent_id != intent.intent_id:
                raise PublicationLedgerPendingError(
                    "A different Kaggle publication intent remains unresolved"
                )
            if current.state != "pending":
                raise PublicationLedgerPendingError(
                    "The exact Kaggle publication intent is reconciliation-only"
                )
            self._require_originating_workflow_run(current)
            return current
        if current is not None and current.intent_id == intent.intent_id:
            raise PublicationLedgerPendingError(
                "The exact Kaggle publication intent was already resolved; "
                "remote reconciliation is required"
            )

        environment = self.environment_for_dataset(intent.dataset)
        body = {
            "ref": intent.source_sha,
            "task": PUBLICATION_DEPLOYMENT_TASK,
            "auto_merge": False,
            "required_contexts": [],
            "payload": self._deployment_payload(intent),
            "environment": environment,
            "description": f"nbadb pending intent={intent.intent_id}",
            "transient_environment": False,
            "production_environment": True,
        }
        try:
            response = self._request(
                "POST",
                f"{self._repository_api_url}/deployments",
                json_body=body,
            )
            created = self._require_object(response, operation="deployment creation")
            deployment_id = self._positive_id(created.get("id"), field="deployment id")
            direct = self._require_object(
                self._request(
                    "GET",
                    f"{self._repository_api_url}/deployments/{deployment_id}",
                ),
                operation="direct deployment receipt",
            )
            parsed = self._parse_deployment(direct, dataset=intent.dataset)
            if parsed.intent_id != intent.intent_id or parsed.state != "pending":
                raise PublicationLedgerError(
                    "GitHub publication deployment creation receipt is inconsistent"
                )
        except Exception:
            parsed = self._recover_write(
                intent.dataset,
                lambda record: record.intent_id == intent.intent_id and record.state == "pending",
                operation="deployment creation",
            )

        stable = self.scan_dataset(intent.dataset)
        stable_current = stable.current
        if (
            stable_current is None
            or stable_current.intent_id != intent.intent_id
            or stable_current.state != "pending"
        ):
            raise PublicationLedgerError(
                "GitHub publication deployment was not durably verified as pending"
            )
        return replace(stable_current, created_by_current=True)

    def _post_status(
        self,
        receipt: DeploymentReceipt,
        *,
        state: str,
        description: str,
    ) -> DeploymentStatusReceipt:
        body = {
            "state": state,
            "description": description,
            "environment": self.environment_for_dataset(receipt.intent.dataset),
            "log_url": self._attempt.log_url,
            "auto_inactive": False,
        }
        response = self._request("POST", receipt.statuses_url, json_body=body)
        raw = self._require_object(response, operation=f"{state} status creation")
        status_id = self._positive_id(raw.get("id"), field="status id")
        status_url = f"{receipt.statuses_url}/{status_id}"
        direct = self._require_object(
            self._request("GET", status_url),
            operation="direct status receipt",
        )
        return self._parse_status(
            direct,
            deployment_id=receipt.deployment_id,
            environment=self.environment_for_dataset(receipt.intent.dataset),
            intent_id=receipt.intent_id,
        )

    def _recover_status(
        self,
        receipt: DeploymentReceipt,
        *,
        state: str,
        nonce: str | None,
        takeover_sha256: str | None = None,
        resolved_version: int | None = None,
        resolution_digest: str | None = None,
    ) -> DeploymentStatusReceipt:
        recovered = self._recover_write(
            receipt.intent.dataset,
            lambda record: (
                record.deployment_id == receipt.deployment_id
                and any(
                    status.state == state
                    and status.nonce == nonce
                    and status.takeover_sha256 == takeover_sha256
                    and status.resolved_version == resolved_version
                    and status.resolution_digest == resolution_digest
                    for status in record.statuses
                )
            ),
            operation=f"{state} status creation",
        )
        matching = [
            status
            for status in recovered.statuses
            if status.state == state
            and status.nonce == nonce
            and status.takeover_sha256 == takeover_sha256
            and status.resolved_version == resolved_version
            and status.resolution_digest == resolution_digest
        ]
        if len(matching) != 1:
            raise PublicationLedgerPendingError(
                f"GitHub publication ledger {state} status is unresolved"
            )
        return matching[0]

    def record_pending_takeover(
        self,
        receipt: DeploymentReceipt,
        takeover: PendingTakeoverReceiptV1,
        takeover_member: ArtifactMemberIdentityV1,
    ) -> PendingTakeoverStatusReceiptV1:
        """Durably bind an uploaded takeover receipt before any recovery claim."""

        from nbadb.contracts.actions_artifact import ArtifactMemberIdentityV1
        from nbadb.contracts.publication_recovery import (
            PendingTakeoverReceiptV1,
            PendingTakeoverStatusReceiptV1,
        )

        if not isinstance(takeover, PendingTakeoverReceiptV1):
            raise PublicationLedgerError("pending takeover receipt is invalid")
        if not isinstance(takeover_member, ArtifactMemberIdentityV1):
            raise PublicationLedgerError("pending takeover artifact member is invalid")
        takeover.verify()
        executor = self._verify_current_executor()
        if takeover.recovery_executor != executor:
            raise PublicationLedgerPendingError(
                "pending takeover recovery executor is no longer current"
            )
        if (
            takeover.repository != self._attempt.repository
            or takeover.dataset != receipt.intent.dataset
            or takeover.intent_id != receipt.intent_id
            or takeover.deployment_id != receipt.deployment_id
            or takeover_member.artifact.repository != self._attempt.repository
            or takeover_member.artifact.run_id != executor.run_id
            or takeover_member.artifact.run_attempt != executor.run_attempt
            or takeover_member.member_sha256 != takeover.takeover_sha256
        ):
            raise PublicationLedgerError("pending takeover provenance is inconsistent")

        inventory = self.scan_dataset(receipt.intent.dataset)
        current = inventory.current
        if (
            current is None
            or current.intent_id != receipt.intent_id
            or current.deployment_id != receipt.deployment_id
            or current.state != "pending"
            or current.statuses
            or inventory.unresolved != (current,)
        ):
            raise PublicationLedgerPendingError(
                "Kaggle publication intent is no longer takeover-eligible"
            )
        inventory_sha256 = self._inventory_identity(inventory)
        stable = takeover.stable_inventory
        if (
            stable.repository != self._attempt.repository
            or stable.dataset != receipt.intent.dataset
            or stable.first_ledger_inventory_sha256 != inventory_sha256
            or stable.second_ledger_inventory_sha256 != inventory_sha256
        ):
            raise PublicationLedgerPendingError(
                "pending takeover stable ledger evidence differs from the current head"
            )

        original = self._verify_executor(
            run_id=current.attempt.run_id,
            run_attempt=current.attempt.run_attempt,
            job=current.attempt.job,
            require_active=False,
        )
        if original != takeover.original_executor:
            raise PublicationLedgerPendingError(
                "pending takeover original executor evidence differs"
            )
        origin_run = self._require_object(
            self._request(
                "GET",
                f"{self._repository_api_url}/actions/runs/{original.run_id}"
                f"/attempts/{original.run_attempt}",
            ),
            operation="takeover origin terminal receipt",
        )
        if (
            origin_run.get("status") != "completed"
            or origin_run.get("conclusion") != takeover.origin_terminal_conclusion
        ):
            raise PublicationLedgerPendingError("pending takeover origin publisher is not terminal")

        token = _digest_token(takeover.takeover_sha256)
        description = f"nbadb takeover t={token} job={executor.job}"
        try:
            pending = self._post_status(
                current,
                state="pending",
                description=description,
            )
        except Exception:
            pending = self._recover_status(
                current,
                state="pending",
                nonce=None,
                takeover_sha256=takeover.takeover_sha256,
            )
        stable_after = self.scan_dataset(receipt.intent.dataset)
        stable_current = stable_after.current
        if (
            stable_current is None
            or stable_current.deployment_id != receipt.deployment_id
            or stable_current.intent_id != receipt.intent_id
            or stable_current.state != "pending"
            or stable_current.latest_status != pending
            or pending.takeover_sha256 != takeover.takeover_sha256
            or pending.executor != executor
        ):
            raise PublicationLedgerPendingError("pending takeover status was not durably re-read")
        return PendingTakeoverStatusReceiptV1.build(
            deployment_id=receipt.deployment_id,
            status_id=pending.status_id,
            state="pending",
            creator_login=pending.creator_login,
            creator_id=pending.creator_id,
            description_token=token,
            takeover_member=takeover_member,
            takeover_sha256=takeover.takeover_sha256,
            recovery_executor=executor,
        )

    def claim_pending_takeover(
        self,
        receipt: DeploymentReceipt,
        takeover: PendingTakeoverReceiptV1,
        durable_status: PendingTakeoverStatusReceiptV1,
    ) -> ExecutionReceipt:
        """Claim a durably recorded pending takeover exactly once."""

        from nbadb.contracts.publication_recovery import (
            PendingTakeoverReceiptV1,
            PendingTakeoverStatusReceiptV1,
        )

        if not isinstance(takeover, PendingTakeoverReceiptV1) or not isinstance(
            durable_status, PendingTakeoverStatusReceiptV1
        ):
            raise PublicationLedgerError("pending takeover claim evidence is invalid")
        takeover.verify()
        durable_status.verify()
        executor = self._verify_current_executor()
        if takeover.recovery_executor != executor or durable_status.recovery_executor != executor:
            raise PublicationLedgerPendingError(
                "pending takeover recovery executor is no longer current"
            )
        if (
            takeover.deployment_id != receipt.deployment_id
            or takeover.intent_id != receipt.intent_id
            or durable_status.deployment_id != receipt.deployment_id
            or durable_status.takeover_sha256 != takeover.takeover_sha256
            or durable_status.takeover_member.member_sha256 != takeover.takeover_sha256
        ):
            raise PublicationLedgerError("pending takeover claim provenance is inconsistent")

        inventory = self.scan_dataset(receipt.intent.dataset)
        current = inventory.current
        latest = current.latest_status if current is not None else None
        if (
            current is None
            or current.deployment_id != receipt.deployment_id
            or current.intent_id != receipt.intent_id
            or current.state != "pending"
            or inventory.unresolved != (current,)
        ):
            raise PublicationLedgerPendingError(
                "Kaggle publication intent is no longer safely pending"
            )
        if (
            latest is None
            or latest.status_id != durable_status.status_id
            or latest.takeover_sha256 != takeover.takeover_sha256
            or latest.executor != executor
        ):
            raise PublicationLedgerPendingError(
                "pending takeover status is no longer the durable ledger head"
            )

        nonce = self._nonce_factory()
        if _HEX_32_RE.fullmatch(nonce) is None:
            raise PublicationLedgerError("GitHub publication claim nonce is invalid")
        description = f"nbadb ip intent={receipt.intent_id} nonce={nonce} job={executor.job}"
        try:
            in_progress = self._post_status(
                current,
                state="in_progress",
                description=description,
            )
        except Exception:
            in_progress = self._recover_status(
                current,
                state="in_progress",
                nonce=nonce,
            )
        stable_after = self.scan_dataset(receipt.intent.dataset)
        stable_current = stable_after.current
        if (
            stable_current is None
            or stable_current.deployment_id != receipt.deployment_id
            or stable_current.intent_id != receipt.intent_id
            or stable_current.state != "in_progress"
            or stable_current.latest_status != in_progress
            or in_progress.executor != executor
        ):
            raise PublicationLedgerPendingError(
                "pending takeover claim was not durably verified as in-progress"
            )
        return ExecutionReceipt(
            deployment_id=receipt.deployment_id,
            status_id=in_progress.status_id,
            intent_id=receipt.intent_id,
            dataset=receipt.intent.dataset,
            nonce=nonce,
            claim_digest=in_progress.claim_digest,
            executor_admission_digest=executor.admission_digest,
            run_id=executor.run_id,
            run_attempt=executor.run_attempt,
            job=executor.job,
            url=in_progress.url,
            takeover_sha256=takeover.takeover_sha256,
        )

    def claim_pending(self, receipt: DeploymentReceipt) -> ExecutionReceipt:
        executor = self._verify_current_executor()
        inventory = self.scan_dataset(receipt.intent.dataset)
        current = inventory.current
        if (
            current is None
            or current.intent_id != receipt.intent_id
            or current.deployment_id != receipt.deployment_id
            or current.state != "pending"
            or inventory.unresolved != (current,)
        ):
            raise PublicationLedgerPendingError(
                "Kaggle publication intent is no longer safely pending"
            )
        if current.latest_status is not None and current.latest_status.takeover_sha256 is not None:
            raise PublicationLedgerPendingError(
                "Kaggle publication intent has a durable takeover and requires takeover claim"
            )
        self._require_originating_workflow_run(receipt)
        self._require_originating_workflow_run(current)
        nonce = self._nonce_factory()
        if _HEX_32_RE.fullmatch(nonce) is None:
            raise PublicationLedgerError("GitHub publication claim nonce is invalid")

        in_progress_description = (
            f"nbadb ip intent={receipt.intent_id} nonce={nonce} job={self._attempt.job}"
        )
        try:
            in_progress = self._post_status(
                current,
                state="in_progress",
                description=in_progress_description,
            )
        except Exception:
            in_progress = self._recover_status(
                current,
                state="in_progress",
                nonce=nonce,
            )
        if in_progress.description != in_progress_description:
            raise PublicationLedgerError("GitHub publication in-progress receipt is inconsistent")
        stable = self.scan_dataset(receipt.intent.dataset)
        stable_current = stable.current
        if (
            stable_current is None
            or stable_current.intent_id != receipt.intent_id
            or stable_current.deployment_id != receipt.deployment_id
            or stable_current.state != "in_progress"
            or stable_current.latest_status != in_progress
        ):
            raise PublicationLedgerPendingError(
                "Kaggle publication intent was not durably verified as in-progress"
            )
        executor = self._verify_current_executor()
        if in_progress.executor != executor:
            raise PublicationLedgerPendingError(
                "Kaggle publication claim executor is no longer current"
            )
        return ExecutionReceipt(
            deployment_id=receipt.deployment_id,
            status_id=in_progress.status_id,
            intent_id=receipt.intent_id,
            dataset=receipt.intent.dataset,
            nonce=nonce,
            claim_digest=in_progress.claim_digest,
            executor_admission_digest=executor.admission_digest,
            run_id=executor.run_id,
            run_attempt=executor.run_attempt,
            job=executor.job,
            url=in_progress.url,
        )

    @staticmethod
    def _marker_matches_intent(
        marker: Mapping[str, Any],
        *,
        marker_sha256: str,
        intent: PublicationIntent,
    ) -> bool:
        provenance = marker.get("provenance")
        return (
            marker.get("dataset") == intent.dataset
            and marker.get("publish_key") == intent.publish_key
            and marker.get("bundle_fingerprint") == intent.bundle_fingerprint
            and marker.get("data_tree_fingerprint") == intent.data_tree_fingerprint
            and marker.get("metadata_sha256") == intent.metadata_sha256
            and marker_sha256 == intent.publication_marker_sha256
            and (
                intent.chain_id is None
                or (
                    isinstance(provenance, dict)
                    and provenance.get("chain_id") == intent.chain_id
                    and provenance.get("source_sha") == intent.source_sha
                    and provenance.get("coverage_fingerprint") == intent.coverage_fingerprint
                    and provenance.get("data_tree_fingerprint")
                    == intent.assured_data_tree_fingerprint
                )
            )
        )

    def find_remote_match(
        self,
        marker: Mapping[str, Any],
        *,
        marker_sha256: str,
    ) -> DeploymentReceipt | None:
        _require_digest(marker_sha256, field="publication_marker_sha256")
        dataset = marker.get("dataset")
        if not isinstance(dataset, str) or not dataset.strip():
            raise PublicationLedgerError("Kaggle remote marker dataset is invalid")
        inventory = self.scan_dataset(dataset)
        match = inventory.current
        if match is None or not self._marker_matches_intent(
            marker,
            marker_sha256=marker_sha256,
            intent=match.intent,
        ):
            return None
        if match.state == "pending":
            raise PublicationLedgerError(
                "Kaggle remote marker exists without a verified in-progress intent"
            )
        return match

    def _mark_success(
        self,
        receipt: DeploymentReceipt,
        *,
        resolved_version: int,
        publication_marker_sha256: str,
        readback_fingerprint: str,
        expected_executor: ExecutorReceipt | None = None,
    ) -> ResolutionReceipt:
        if type(resolved_version) is not int or resolved_version <= 0:
            raise ValueError("Kaggle resolved version must be positive")
        _require_digest(
            publication_marker_sha256,
            field="publication_marker_sha256",
        )
        _require_digest(readback_fingerprint, field="readback_fingerprint")
        if publication_marker_sha256 != receipt.intent.publication_marker_sha256:
            raise PublicationLedgerError(
                "Kaggle publication marker digest does not match the durable intent"
            )
        if readback_fingerprint != receipt.intent.staged_tree_fingerprint:
            raise PublicationLedgerError(
                "Kaggle publication readback fingerprint does not match the durable intent"
            )
        if not receipt.statuses:
            raise PublicationLedgerError(
                "GitHub publication resolution is missing its verified claim"
            )
        if receipt.state == "success":
            claim_source = receipt.latest_status
        else:
            claim_source = next(
                (status for status in receipt.statuses if status.state == "in_progress"),
                None,
            )
        if claim_source is None:
            raise PublicationLedgerError(
                "GitHub publication resolution is missing its verified claim"
            )
        claim_digest = claim_source.claim_digest
        current_executor = self._verify_current_executor()
        if expected_executor is not None and current_executor != expected_executor:
            raise PublicationLedgerPendingError(
                "GitHub publication execution executor changed before resolution"
            )
        resolver = (
            receipt.latest_status.executor
            if receipt.state == "success" and receipt.latest_status is not None
            else current_executor
        )
        resolution_digest = _resolution_digest(
            intent_id=receipt.intent_id,
            resolved_version=resolved_version,
            publication_marker_sha256=publication_marker_sha256,
            readback_fingerprint=readback_fingerprint,
            claim_digest=claim_digest,
            resolver_admission_digest=resolver.admission_digest,
        )
        if receipt.state == "success":
            latest = receipt.latest_status
            if (
                latest is None
                or latest.resolved_version != resolved_version
                or latest.resolution_digest != resolution_digest
            ):
                raise PublicationLedgerError("GitHub publication success receipt is inconsistent")
            return ResolutionReceipt(
                deployment_id=receipt.deployment_id,
                status_id=latest.status_id,
                intent_id=receipt.intent_id,
                resolved_version=resolved_version,
                publication_marker_sha256=publication_marker_sha256,
                readback_fingerprint=readback_fingerprint,
                resolution_digest=resolution_digest,
                url=latest.url,
            )
        if receipt.state != "in_progress":
            raise PublicationLedgerPendingError(
                "Only a verified in-progress intent can be resolved"
            )
        description = (
            f"nbadb ok v={resolved_version} c={_digest_token(claim_digest)} "
            f"r={_digest_token(resolution_digest)} j={self._attempt.job}"
        )
        if len(description) > 140:
            raise PublicationLedgerError(
                "GitHub publication success status description exceeds 140 characters"
            )
        try:
            stable_before_post = self.scan_dataset(receipt.intent.dataset)
        except PublicationLedgerError as exc:
            raise PublicationLedgerPendingError(
                "GitHub publication execution claim changed before success publication"
            ) from exc
        stable_current = stable_before_post.current
        if (
            stable_current != receipt
            or stable_current is None
            or stable_before_post.unresolved != (stable_current,)
        ):
            raise PublicationLedgerPendingError(
                "GitHub publication execution claim changed before success publication"
            )
        posting_executor = self._verify_current_executor()
        if posting_executor != current_executor or (
            expected_executor is not None and posting_executor != expected_executor
        ):
            raise PublicationLedgerPendingError(
                "GitHub publication execution executor changed before success publication"
            )
        # A competing status can be published while the final executor receipt
        # is being fetched. Re-read the exact bounded head once after that
        # executor check so such drift is still rejected before our POST. The
        # preceding three-observation scan established the stable baseline;
        # this adjacent snapshot proves it remained unchanged through the
        # executor check without widening the final mutation window.
        try:
            final_before_post = self._snapshot_inventory(receipt.intent.dataset)
        except PublicationLedgerError as exc:
            raise PublicationLedgerPendingError(
                "GitHub publication execution claim changed before success publication"
            ) from exc
        final_current = final_before_post.current
        if (
            final_current != stable_current
            or final_current is None
            or final_before_post.unresolved != (final_current,)
        ):
            raise PublicationLedgerPendingError(
                "GitHub publication execution claim changed before success publication"
            )
        try:
            final_executor = self._verify_current_executor()
        except PublicationLedgerPendingError as exc:
            raise PublicationLedgerPendingError(
                "GitHub publication execution executor changed before success publication"
            ) from exc
        if final_executor != posting_executor or (
            expected_executor is not None and final_executor != expected_executor
        ):
            raise PublicationLedgerPendingError(
                "GitHub publication execution executor changed before success publication"
            )
        try:
            success = self._post_status(
                receipt,
                state="success",
                description=description,
            )
        except Exception:
            success = self._recover_status(
                receipt,
                state="success",
                nonce=None,
                resolved_version=resolved_version,
                resolution_digest=resolution_digest,
            )
        if success.description != description:
            raise PublicationLedgerError("GitHub publication success receipt is inconsistent")
        stable = self.scan_dataset(receipt.intent.dataset)
        stable_current = stable.current
        if (
            stable_current is None
            or stable_current.intent_id != receipt.intent_id
            or stable_current.deployment_id != receipt.deployment_id
            or stable_current.state != "success"
            or stable_current.latest_status != success
        ):
            raise PublicationLedgerPendingError(
                "Kaggle publication success was not durably verified"
            )
        return ResolutionReceipt(
            deployment_id=receipt.deployment_id,
            status_id=success.status_id,
            intent_id=receipt.intent_id,
            resolved_version=resolved_version,
            publication_marker_sha256=publication_marker_sha256,
            readback_fingerprint=readback_fingerprint,
            resolution_digest=resolution_digest,
            url=success.url,
        )

    def mark_reconciled(
        self,
        receipt: DeploymentReceipt,
        *,
        resolved_version: int,
        publication_marker_sha256: str,
        readback_fingerprint: str,
    ) -> ResolutionReceipt:
        # Reconciliation is intentionally cross-run and readback-only: the
        # current resolver is directly verified, while the immutable intent,
        # marker digest, version, and readback fingerprint bind the result.
        self._verify_current_executor()
        inventory = self.scan_dataset(receipt.intent.dataset)
        current = inventory.current
        if (
            current is None
            or current.intent_id != receipt.intent_id
            or current.deployment_id != receipt.deployment_id
        ):
            raise PublicationLedgerError(
                "GitHub publication reconciliation receipt is no longer current"
            )
        self._require_cross_run_origin_terminal(current)
        return self._mark_success(
            current,
            resolved_version=resolved_version,
            publication_marker_sha256=publication_marker_sha256,
            readback_fingerprint=readback_fingerprint,
        )

    def mark_resolved(
        self,
        execution: ExecutionReceipt,
        *,
        resolved_version: int,
        publication_marker_sha256: str,
        readback_fingerprint: str,
    ) -> ResolutionReceipt:
        executor = self._verify_current_executor()
        self._require_execution_owner(execution, executor)
        inventory = self.scan_dataset(execution.dataset)
        receipt = inventory.current
        if receipt is None or receipt.intent_id != execution.intent_id:
            raise PublicationLedgerError(
                "GitHub publication execution intent did not resolve uniquely"
            )
        if execution.takeover_sha256 is None:
            self._require_originating_workflow_run(receipt)
        else:
            # A takeover execution resolves in a different run than the intent's
            # origin; the origin's terminal state was durably proven at takeover
            # record time and is re-verified live here before resolution.
            self._require_cross_run_origin_terminal(receipt)
        latest = receipt.latest_status
        if (
            receipt.deployment_id != execution.deployment_id
            or receipt.state != "in_progress"
            or latest is None
            or latest.state != "in_progress"
            or latest.status_id != execution.status_id
            or latest.nonce != execution.nonce
            or latest.claim_digest != execution.claim_digest
            or latest.url != execution.url
            or latest.executor != executor
            or latest.executor.admission_digest != execution.executor_admission_digest
            or latest.executor.run_id != execution.run_id
            or latest.executor.run_attempt != execution.run_attempt
            or latest.executor.job != execution.job
        ):
            raise PublicationLedgerPendingError(
                "GitHub publication execution receipt is no longer current"
            )
        return self._mark_success(
            receipt,
            resolved_version=resolved_version,
            publication_marker_sha256=publication_marker_sha256,
            readback_fingerprint=readback_fingerprint,
            expected_executor=executor,
        )
