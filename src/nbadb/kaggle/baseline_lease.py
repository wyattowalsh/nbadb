"""Durable, fenced baseline-build lease backed by GitHub Deployments.

This module owns the storage/state-machine primitive only.  Workflow admission,
secret access, tunnel control, and publication integration deliberately remain in
their callers.  All decisions use GitHub's response ``Date`` and persisted
timestamps; a runner's local clock is never lease authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

GITHUB_API_VERSION = "2026-03-10"
BASELINE_LEASE_DEPLOYMENT_TASK = "nbadb:baseline-build-lease"
_LEASE_KIND = "nbadb_baseline_build_lease"
_LEASE_SCHEMA_VERSION = 1
_LEASE_DESCRIPTION_PREFIX = "nbadb baseline lease key="
_TRANSITION_PREFIX = "nbadb-bl1"
_HEAD_WINDOW = 2
_DEPLOYMENT_PAGE_SIZE = 100
_MAX_DEPLOYMENT_INVENTORY = 10_000
_STATUS_PAGE_SIZE = 100
_MAX_STATUS_INVENTORY = 10_000
_STATUS_RETENTION_SECONDS = 90 * 24 * 60 * 60
_MAX_TTL_SECONDS = 86_400
_MAX_DESCRIPTION_BYTES = 140
_HEX_32_RE = re.compile(r"[0-9a-f]{32}")
_HEX_40_RE = re.compile(r"[0-9a-f]{40}")
_HEX_64_RE = re.compile(r"[0-9a-f]{64}")
_BASE36_RE = re.compile(r"0|[1-9a-z][0-9a-z]*")
_LEASE_KEY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_BASE_URL_SCHEMES = frozenset({"http", "https"})
_LEASE_HEAD_QUERY = """\
query NbadbBaselineLeaseHead(
  $owner: String!
  $repository: String!
  $environment: String!
  $pageSize: Int!
  $cursor: String
) {
  repository(owner: $owner, name: $repository) {
    deployments(
      first: $pageSize
      after: $cursor
      environments: [$environment]
      orderBy: {field: CREATED_AT, direction: DESC}
    ) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        databaseId
        createdAt
      }
    }
  }
}
"""


class BaselineLeaseError(RuntimeError):
    """The durable lease evidence is malformed or cannot be trusted."""


class BaselineLeaseHeldError(BaselineLeaseError):
    """Another unexpired owner currently holds the baseline lease."""


class BaselineLeasePendingError(BaselineLeaseError):
    """A write outcome is ambiguous and must be reconciled by exact nonce."""

    def __init__(self, message: str, *, nonce: str) -> None:
        super().__init__(message)
        self.nonce = nonce


class BaselineLeaseStaleError(BaselineLeaseError):
    """A receipt lost its fence, revision, owner, or expiry authority."""


class _BaselineLeaseAmbiguousResponseError(BaselineLeaseError):
    """An HTTP response is unusable as exact receipt evidence."""


class LeaseState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    RELEASED = "released"


class LeaseOperation(StrEnum):
    ACQUIRE = "acquire"
    HEARTBEAT = "heartbeat"
    TRANSFER = "transfer"
    RECOVER = "recover"
    RELEASE = "release"


class ScheduledLeaseAction(StrEnum):
    NOOP_HELD = "noop_held"
    ACQUIRE_REQUIRED = "acquire_required"


_OPERATION_CODE = {
    LeaseOperation.ACQUIRE: "a",
    LeaseOperation.HEARTBEAT: "h",
    LeaseOperation.TRANSFER: "t",
    LeaseOperation.RECOVER: "c",
    LeaseOperation.RELEASE: "r",
}
_CODE_OPERATION = {value: key for key, value in _OPERATION_CODE.items()}
_TRANSITION_RE = re.compile(
    rf"{re.escape(_TRANSITION_PREFIX)}\.([ahctr])\."
    r"(0|[1-9a-z][0-9a-z]*)\."
    r"(0|[1-9a-z][0-9a-z]*)\."
    r"(0|[1-9a-z][0-9a-z]*)\."
    r"(0|[1-9a-z][0-9a-z]*)\."
    r"([A-Za-z0-9_-]{43})\.([0-9a-f]{32})"
)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_lease_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _LEASE_KEY_RE.fullmatch(value) is None
    ):
        raise ValueError("Baseline lease key must be an owner/dataset identifier")
    return value.casefold()


def _validated_base_url(value: str, *, field: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in _BASE_URL_SCHEMES
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Baseline lease {field} is invalid")
    return value.rstrip("/")


def _require_positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise BaselineLeaseError(f"Baseline lease {field} must be a positive integer")
    return value


def _require_hex(value: object, *, field: str, length: int) -> str:
    pattern = _HEX_40_RE if length == 40 else _HEX_64_RE
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"Baseline lease {field} must be {length} lowercase hex characters")
    return value


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None
    ):
        raise BaselineLeaseError(f"Baseline lease {field} is invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise BaselineLeaseError(f"Baseline lease {field} is invalid") from exc


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encode_base36(value: int) -> str:
    if value < 0:
        raise ValueError("Base36 values must be nonnegative")
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    parts: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        parts.append(alphabet[remainder])
    return "".join(reversed(parts))


def _decode_base36(value: str, *, field: str) -> int:
    if _BASE36_RE.fullmatch(value) is None:
        raise BaselineLeaseError(f"Baseline lease {field} is not canonical base36")
    decoded = int(value, 36)
    if _encode_base36(decoded) != value:
        raise BaselineLeaseError(f"Baseline lease {field} is not canonical base36")
    return decoded


def _digest_token(value: str) -> str:
    return base64.urlsafe_b64encode(bytes.fromhex(value)).decode("ascii").rstrip("=")


def _parse_digest_token(value: str, *, field: str) -> str:
    try:
        decoded = base64.b64decode(f"{value}=", altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BaselineLeaseError(f"Baseline lease {field} token is invalid") from exc
    if (
        len(decoded) != hashlib.sha256().digest_size
        or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value
    ):
        raise BaselineLeaseError(f"Baseline lease {field} token is invalid")
    return decoded.hex()


def baseline_concurrency_group(lease_key: str) -> str:
    """Return the one lower-case supplemental Actions queue for a lease key."""

    canonical = _canonical_lease_key(lease_key)
    digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()[:16]
    return f"nbadb-baseline-build-{digest}"


@dataclass(frozen=True, slots=True)
class BaselineConcurrencyPolicy:
    group: str
    queue: str
    cancel_in_progress: bool
    fencing_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.group, str) or self.group != self.group.casefold():
            raise BaselineLeaseError("Baseline lease concurrency group is not normalized")
        if self.queue != "max":
            raise BaselineLeaseError("Baseline lease concurrency queue must be unbounded max")
        if type(self.cancel_in_progress) is not bool or self.cancel_in_progress:
            raise BaselineLeaseError("Baseline lease concurrency must be non-cancelling")
        if type(self.fencing_authority) is not bool or self.fencing_authority:
            raise BaselineLeaseError("GitHub concurrency is not baseline fencing authority")

    @classmethod
    def validate(
        cls,
        lease_key: str,
        *,
        group: str,
        queue: str,
        cancel_in_progress: bool,
    ) -> BaselineConcurrencyPolicy:
        expected = baseline_concurrency_group(lease_key)
        if group != group.casefold() or group != expected:
            raise BaselineLeaseError("Baseline lease concurrency group is not exact and normalized")
        if queue != "max":
            raise BaselineLeaseError("Baseline lease concurrency queue must be unbounded max")
        if type(cancel_in_progress) is not bool or cancel_in_progress:
            raise BaselineLeaseError("Baseline lease concurrency must be non-cancelling")
        return cls(group=group, queue=queue, cancel_in_progress=cancel_in_progress)


@dataclass(frozen=True, slots=True)
class BaselineLeaseOwner:
    repository: str
    run_id: int
    run_attempt: int
    source_sha: str
    workflow_sha256: str

    def __post_init__(self) -> None:
        repository = _canonical_lease_key(self.repository)
        object.__setattr__(self, "repository", repository)
        if type(self.run_id) is not int or self.run_id <= 0:
            raise ValueError("Baseline lease owner run_id must be positive")
        if type(self.run_attempt) is not int or self.run_attempt != 1:
            raise ValueError("Baseline lease owner must be from workflow run attempt one")
        _require_hex(self.source_sha, field="owner source_sha", length=40)
        _require_hex(self.workflow_sha256, field="owner workflow_sha256", length=64)

    def to_payload(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "source_sha": self.source_sha,
            "workflow_sha256": self.workflow_sha256,
        }

    @classmethod
    def from_payload(cls, value: object) -> BaselineLeaseOwner:
        expected = {"repository", "run_id", "run_attempt", "source_sha", "workflow_sha256"}
        if not isinstance(value, dict) or set(value) != expected:
            raise BaselineLeaseError("Baseline lease owner payload schema is invalid")
        payload = cast("dict[str, Any]", value)
        try:
            return cls(
                repository=cast("str", payload["repository"]),
                run_id=cast("int", payload["run_id"]),
                run_attempt=cast("int", payload["run_attempt"]),
                source_sha=cast("str", payload["source_sha"]),
                workflow_sha256=cast("str", payload["workflow_sha256"]),
            )
        except (TypeError, ValueError) as exc:
            raise BaselineLeaseError("Baseline lease owner payload is invalid") from exc

    @property
    def digest(self) -> str:
        return _canonical_sha256({"schema_version": 1, **self.to_payload()})


@dataclass(frozen=True, slots=True)
class BaselineLeaseReceipt:
    lease_key: str
    environment: str
    fence: int
    revision: int
    owner: BaselineLeaseOwner
    state: LeaseState
    operation: LeaseOperation
    transition_nonce: str
    predecessor_revision: int | None
    transition_authority_sha256: str | None
    deployment_created_at: str
    heartbeat_at: str
    expires_at: str
    deployment_url: str
    status_url: str | None

    def __post_init__(self) -> None:
        if self.lease_key != _canonical_lease_key(self.lease_key):
            raise ValueError("Baseline lease receipt key is not canonical")
        if self.environment != GitHubDeploymentBaselineLease.environment_for(self.lease_key):
            raise ValueError("Baseline lease receipt environment is invalid")
        if type(self.fence) is not int or self.fence <= 0:
            raise ValueError("Baseline lease receipt fence must be positive")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("Baseline lease receipt revision must be nonnegative")
        if not isinstance(self.owner, BaselineLeaseOwner):
            raise ValueError("Baseline lease receipt owner is invalid")
        if not isinstance(self.state, LeaseState) or not isinstance(self.operation, LeaseOperation):
            raise ValueError("Baseline lease receipt state is invalid")
        if (
            not isinstance(self.transition_nonce, str)
            or _HEX_32_RE.fullmatch(self.transition_nonce) is None
        ):
            raise ValueError("Baseline lease receipt nonce is invalid")
        created = _parse_timestamp(self.deployment_created_at, field="deployment created_at")
        heartbeat = _parse_timestamp(self.heartbeat_at, field="heartbeat_at")
        expiry = _parse_timestamp(self.expires_at, field="expires_at")
        if heartbeat < created or expiry < heartbeat:
            raise ValueError("Baseline lease receipt timestamps are invalid")
        if self.state is LeaseState.PENDING:
            if (
                self.revision != 0
                or self.status_url is not None
                or self.operation is not LeaseOperation.ACQUIRE
                or self.predecessor_revision is not None
                or self.transition_authority_sha256 is not None
            ):
                raise ValueError("Baseline pending lease receipt is invalid")
        elif (
            self.revision <= 0
            or self.status_url is None
            or type(self.predecessor_revision) is not int
            or self.predecessor_revision < 0
            or self.predecessor_revision >= self.revision
            or not isinstance(self.transition_authority_sha256, str)
            or _HEX_64_RE.fullmatch(self.transition_authority_sha256) is None
        ):
            raise ValueError("Baseline persisted lease receipt is invalid")
        if self.state is LeaseState.RELEASED and self.operation is not LeaseOperation.RELEASE:
            raise ValueError("Baseline released receipt operation is invalid")
        if self.state is LeaseState.ACTIVE and self.operation not in {
            LeaseOperation.ACQUIRE,
            LeaseOperation.HEARTBEAT,
            LeaseOperation.TRANSFER,
            LeaseOperation.RECOVER,
        }:
            raise ValueError("Baseline active receipt operation is invalid")

    @property
    def receipt_digest(self) -> str:
        return _canonical_sha256(
            {
                "schema_version": 1,
                "lease_key": self.lease_key,
                "environment": self.environment,
                "fence": self.fence,
                "revision": self.revision,
                "owner": self.owner.to_payload(),
                "state": self.state.value,
                "operation": self.operation.value,
                "transition_nonce": self.transition_nonce,
                "predecessor_revision": self.predecessor_revision,
                "transition_authority_sha256": self.transition_authority_sha256,
                "deployment_created_at": self.deployment_created_at,
                "heartbeat_at": self.heartbeat_at,
                "expires_at": self.expires_at,
                "deployment_url": self.deployment_url,
                "status_url": self.status_url,
            }
        )

    def is_expired_at(self, server_time: datetime) -> bool:
        if server_time.tzinfo is None:
            raise ValueError("Baseline lease server_time must be timezone-aware")
        return server_time.astimezone(UTC) >= _parse_timestamp(
            self.expires_at,
            field="expires_at",
        )


@dataclass(frozen=True, slots=True)
class BaselineLeaseInspection:
    lease_key: str
    server_time: datetime
    current: BaselineLeaseReceipt | None
    head_fence: int | None
    inventory_count: int
    status_inventory_count: int
    retention_truncated: bool
    retained_head_revision: int | None
    retained_head_state: LeaseState | None
    retained_head_expires_at: str | None
    retained_head_status_url: str | None

    @property
    def held(self) -> bool:
        if self.current is not None:
            return self.current.state in {
                LeaseState.PENDING,
                LeaseState.ACTIVE,
            } and not self.current.is_expired_at(self.server_time)
        if (
            self.retention_truncated
            and self.retained_head_state is LeaseState.ACTIVE
            and self.retained_head_expires_at is not None
        ):
            return self.server_time < _parse_timestamp(
                self.retained_head_expires_at,
                field="retained head expires_at",
            )
        return False


@dataclass(frozen=True, slots=True)
class ScheduledLeaseAdmission:
    action: ScheduledLeaseAction
    server_time: datetime
    fence: int | None
    receipt_digest: str | None
    expires_at: str | None


@dataclass(frozen=True, slots=True)
class BaselineGitHubResponse:
    status_code: int
    payload: Any
    headers: tuple[tuple[str, str], ...]


class BaselineGitHubTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        timeout_seconds: float,
    ) -> BaselineGitHubResponse: ...


class UrllibBaselineGitHubTransport:
    """Injectable stdlib transport; tests use an in-memory fake service."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json_body: Mapping[str, Any] | None = None,
        timeout_seconds: float,
    ) -> BaselineGitHubResponse:
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
        response_headers: Sequence[tuple[str, str]]
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status_code = response.status
                response_body = response.read()
                response_headers = tuple(response.headers.items())
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            response_body = exc.read()
            response_headers = tuple(exc.headers.items())
        try:
            payload = json.loads(response_body) if response_body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            # Preserve the HTTP status so the state-machine layer can distinguish
            # a definitive mutation 4xx from an ambiguous post-mutation reread.
            # The untrusted response body is never authority and is not retained.
            payload = None
        return BaselineGitHubResponse(
            status_code=status_code,
            payload=payload,
            headers=tuple(response_headers),
        )


@dataclass(frozen=True, slots=True)
class _DeploymentRecord:
    deployment_id: int
    created_at: str
    lease_key: str
    environment: str
    initial_owner: BaselineLeaseOwner
    acquire_nonce: str
    requested_ttl_seconds: int
    url: str
    statuses_url: str


@dataclass(frozen=True, slots=True)
class _Transition:
    operation: LeaseOperation
    owner: BaselineLeaseOwner
    ttl_seconds: int
    predecessor_revision: int
    authority_sha256: str
    nonce: str


@dataclass(frozen=True, slots=True)
class _StatusInventory:
    current: BaselineLeaseReceipt | None
    retained_latest: BaselineLeaseReceipt | None
    retained_plausible_heads: tuple[BaselineLeaseReceipt, ...]
    retention_truncated: bool
    server_time: datetime
    inventory_digest: str
    count: int


class GitHubDeploymentBaselineLease:
    """Strict GitHub-Deployment state machine for one cooperative writer lease."""

    def __init__(
        self,
        *,
        token: str,
        repository: str,
        transport: BaselineGitHubTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        nonce_factory: Callable[[], str] | None = None,
        server_url: str = "https://github.com",
        api_url: str = "https://api.github.com",
        request_timeout_seconds: float = 30.0,
        snapshot_delay_seconds: float = 1.0,
        max_ttl_seconds: int = _MAX_TTL_SECONDS,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise BaselineLeaseError("Durable baseline lease requires a GitHub token")
        self._repository = _canonical_lease_key(repository)
        if request_timeout_seconds <= 0 or snapshot_delay_seconds < 0:
            raise ValueError("Baseline lease timing configuration is invalid")
        if (
            type(max_ttl_seconds) is not int
            or max_ttl_seconds <= 0
            or max_ttl_seconds > _MAX_TTL_SECONDS
        ):
            raise ValueError("Baseline lease max TTL is outside its fixed bounded contract")
        self._token = token
        self._transport = transport or UrllibBaselineGitHubTransport()
        self._sleep = sleep
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
        self._server_url = _validated_base_url(server_url, field="server_url")
        self._api_url = _validated_base_url(api_url, field="api_url")
        self._request_timeout_seconds = request_timeout_seconds
        self._snapshot_delay_seconds = snapshot_delay_seconds
        self._max_ttl_seconds = max_ttl_seconds
        self._last_server_time: datetime | None = None

    @staticmethod
    def environment_for(lease_key: str) -> str:
        canonical = _canonical_lease_key(lease_key)
        digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()[:16]
        return f"nbadb-baseline-{digest}"

    @property
    def _repository_api_url(self) -> str:
        owner, repository = self._repository.split("/", 1)
        return (
            f"{self._api_url}/repos/"
            f"{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repository, safe='')}"
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "nbadb-baseline-build-lease",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    @staticmethod
    def _server_date(headers: Sequence[tuple[str, str]]) -> datetime:
        values = [value for key, value in headers if key.casefold() == "date"]
        if len(values) != 1:
            raise BaselineLeaseError("GitHub baseline lease Date header is missing or ambiguous")
        try:
            parsed = parsedate_to_datetime(values[0])
        except (TypeError, ValueError) as exc:
            raise BaselineLeaseError("GitHub baseline lease Date header is invalid") from exc
        if parsed.tzinfo is None:
            raise BaselineLeaseError("GitHub baseline lease Date header is not timezone-aware")
        canonical = parsed.astimezone(UTC).replace(microsecond=0)
        if format_datetime(canonical, usegmt=True) != values[0]:
            raise BaselineLeaseError("GitHub baseline lease Date header is not canonical")
        return canonical

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Mapping[str, Any] | None = None,
    ) -> tuple[BaselineGitHubResponse, datetime]:
        response = self._transport.request(
            method,
            url,
            headers=self._headers,
            json_body=json_body,
            timeout_seconds=self._request_timeout_seconds,
        )
        server_time = self._server_date(response.headers)
        if self._last_server_time is not None and server_time < self._last_server_time:
            raise BaselineLeaseError("GitHub baseline lease server time moved backwards")
        self._last_server_time = server_time
        return response, server_time

    @staticmethod
    def _require_object(
        result: tuple[BaselineGitHubResponse, datetime],
        *,
        operation: str,
        statuses: frozenset[int] = frozenset({200}),
    ) -> tuple[dict[str, Any], datetime]:
        response, server_time = result
        if response.status_code not in statuses or not isinstance(response.payload, dict):
            raise _BaselineLeaseAmbiguousResponseError(
                f"GitHub baseline lease {operation} has no usable receipt at "
                f"HTTP {response.status_code}"
            )
        return cast("dict[str, Any]", response.payload), server_time

    @staticmethod
    def _require_list(
        result: tuple[BaselineGitHubResponse, datetime],
        *,
        operation: str,
    ) -> tuple[list[Any], datetime]:
        response, server_time = result
        if response.status_code != 200 or not isinstance(response.payload, list):
            raise _BaselineLeaseAmbiguousResponseError(
                f"GitHub baseline lease {operation} has no usable receipt at "
                f"HTTP {response.status_code}"
            )
        return cast("list[Any]", response.payload), server_time

    def _require_owner(self, owner: BaselineLeaseOwner) -> None:
        if not isinstance(owner, BaselineLeaseOwner) or owner.repository != self._repository:
            raise BaselineLeaseError("Baseline lease owner repository is foreign")

    def _require_ttl(self, ttl_seconds: int, *, allow_zero: bool = False) -> None:
        minimum = 0 if allow_zero else 1
        if (
            type(ttl_seconds) is not int
            or ttl_seconds < minimum
            or ttl_seconds > self._max_ttl_seconds
        ):
            raise ValueError("Baseline lease TTL is outside its bounded contract")

    def _new_nonce(self) -> str:
        nonce = self._nonce_factory()
        if not isinstance(nonce, str) or _HEX_32_RE.fullmatch(nonce) is None:
            raise BaselineLeaseError("Baseline lease nonce factory returned an invalid nonce")
        return nonce

    @staticmethod
    def _receipt_ttl_seconds(receipt: BaselineLeaseReceipt) -> int:
        heartbeat = _parse_timestamp(receipt.heartbeat_at, field="heartbeat_at")
        expires = _parse_timestamp(receipt.expires_at, field="expires_at")
        ttl_seconds = int((expires - heartbeat).total_seconds())
        if receipt.operation is LeaseOperation.RELEASE:
            if ttl_seconds != 0:
                raise BaselineLeaseError("Baseline lease release receipt TTL is invalid")
        elif ttl_seconds <= 0 or ttl_seconds > _MAX_TTL_SECONDS:
            raise BaselineLeaseError(
                "Baseline lease active receipt TTL is outside its bounded contract"
            )
        return ttl_seconds

    @staticmethod
    def _transition_authority_sha256(
        operation: LeaseOperation,
        owner: BaselineLeaseOwner,
        *,
        ttl_seconds: int,
        nonce: str,
        predecessor: BaselineLeaseReceipt,
    ) -> str:
        return _canonical_sha256(
            {
                "schema_version": 1,
                "operation": operation.value,
                "owner_digest": owner.digest,
                "ttl_seconds": ttl_seconds,
                "nonce": nonce,
                "predecessor_revision": predecessor.revision,
                "predecessor_receipt_digest": predecessor.receipt_digest,
                "predecessor_owner_digest": predecessor.owner.digest,
            }
        )

    @classmethod
    def _encode_transition(
        cls,
        operation: LeaseOperation,
        owner: BaselineLeaseOwner,
        *,
        ttl_seconds: int,
        nonce: str,
        predecessor: BaselineLeaseReceipt,
    ) -> str:
        authority_sha256 = cls._transition_authority_sha256(
            operation,
            owner,
            ttl_seconds=ttl_seconds,
            nonce=nonce,
            predecessor=predecessor,
        )
        description = ".".join(
            (
                _TRANSITION_PREFIX,
                _OPERATION_CODE[operation],
                _encode_base36(owner.run_id),
                _encode_base36(owner.run_attempt),
                _encode_base36(ttl_seconds),
                _encode_base36(predecessor.revision),
                _digest_token(authority_sha256),
                nonce,
            )
        )
        if len(description.encode("ascii")) > _MAX_DESCRIPTION_BYTES:
            raise BaselineLeaseError("Baseline lease transition description is too large")
        return description

    def _decode_transition(
        self,
        description: object,
        deployment: _DeploymentRecord,
    ) -> _Transition:
        if not isinstance(description, str):
            raise BaselineLeaseError("Baseline lease transition description is invalid")
        try:
            description_size = len(description.encode("ascii"))
        except UnicodeEncodeError as exc:
            raise BaselineLeaseError("Baseline lease transition description is invalid") from exc
        if description_size > _MAX_DESCRIPTION_BYTES:
            raise BaselineLeaseError("Baseline lease transition description is too large")
        match = _TRANSITION_RE.fullmatch(description)
        if match is None:
            raise BaselineLeaseError("Baseline lease transition description is invalid")
        operation = _CODE_OPERATION[match.group(1)]
        run_id = _decode_base36(match.group(2), field="owner run_id")
        run_attempt = _decode_base36(match.group(3), field="owner run_attempt")
        ttl_seconds = _decode_base36(match.group(4), field="transition TTL")
        predecessor_revision = _decode_base36(
            match.group(5),
            field="predecessor revision",
        )
        try:
            owner = BaselineLeaseOwner(
                repository=deployment.initial_owner.repository,
                run_id=run_id,
                run_attempt=run_attempt,
                source_sha=deployment.initial_owner.source_sha,
                workflow_sha256=deployment.initial_owner.workflow_sha256,
            )
        except (TypeError, ValueError) as exc:
            raise BaselineLeaseError(
                "Baseline lease persisted transition owner is invalid"
            ) from exc
        authority_sha256 = _parse_digest_token(
            match.group(6),
            field="receipt/owner authority",
        )
        nonce = match.group(7)
        if operation is LeaseOperation.RELEASE:
            if ttl_seconds != 0:
                raise BaselineLeaseError("Baseline lease release TTL is invalid")
        elif ttl_seconds <= 0 or ttl_seconds > self._max_ttl_seconds:
            raise BaselineLeaseError(
                "Baseline lease active transition TTL is outside its bounded contract"
            )
        return _Transition(
            operation=operation,
            owner=owner,
            ttl_seconds=ttl_seconds,
            predecessor_revision=predecessor_revision,
            authority_sha256=authority_sha256,
            nonce=nonce,
        )

    def _deployment_payload(
        self,
        *,
        lease_key: str,
        owner: BaselineLeaseOwner,
        ttl_seconds: int,
        nonce: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": _LEASE_SCHEMA_VERSION,
            "kind": _LEASE_KIND,
            "lease_key": lease_key,
            "initial_owner": owner.to_payload(),
            "acquire_nonce": nonce,
            "requested_ttl_seconds": ttl_seconds,
            "concurrency_group": baseline_concurrency_group(lease_key),
        }

    def _parse_deployment(
        self,
        raw: Mapping[str, Any],
        *,
        lease_key: str,
        observed_at: datetime,
    ) -> _DeploymentRecord:
        deployment_id = _require_positive_int(raw.get("id"), field="deployment id")
        environment = self.environment_for(lease_key)
        url = f"{self._repository_api_url}/deployments/{deployment_id}"
        statuses_url = f"{url}/statuses"
        created_at = raw.get("created_at")
        created = _parse_timestamp(created_at, field="deployment created_at")
        if created > observed_at:
            raise BaselineLeaseError("Baseline lease deployment timestamp is from the future")
        payload = raw.get("payload")
        expected_fields = {
            "schema_version",
            "kind",
            "lease_key",
            "initial_owner",
            "acquire_nonce",
            "requested_ttl_seconds",
            "concurrency_group",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise BaselineLeaseError("Baseline lease deployment payload schema is invalid")
        if (
            type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != _LEASE_SCHEMA_VERSION
            or payload.get("kind") != _LEASE_KIND
            or payload.get("lease_key") != lease_key
            or payload.get("concurrency_group") != baseline_concurrency_group(lease_key)
        ):
            raise BaselineLeaseError("Baseline lease deployment payload identity is invalid")
        owner = BaselineLeaseOwner.from_payload(payload.get("initial_owner"))
        self._require_owner(owner)
        nonce = payload.get("acquire_nonce")
        ttl_seconds = payload.get("requested_ttl_seconds")
        if not isinstance(nonce, str) or _HEX_32_RE.fullmatch(nonce) is None:
            raise BaselineLeaseError("Baseline lease deployment nonce is invalid")
        try:
            self._require_ttl(cast("int", ttl_seconds))
        except (TypeError, ValueError) as exc:
            raise BaselineLeaseError("Baseline lease deployment requested TTL is invalid") from exc
        description = (
            f"{_LEASE_DESCRIPTION_PREFIX}{hashlib.sha256(lease_key.encode()).hexdigest()[:20]}"
        )
        if (
            raw.get("url") != url
            or raw.get("statuses_url") != statuses_url
            or raw.get("repository_url") != self._repository_api_url
            or raw.get("sha") != owner.source_sha
            or raw.get("ref") != owner.source_sha
            or raw.get("task") != BASELINE_LEASE_DEPLOYMENT_TASK
            or raw.get("environment") != environment
            or raw.get("description") != description
            or raw.get("transient_environment") is not False
            or raw.get("production_environment") is not False
        ):
            raise BaselineLeaseError("Baseline lease deployment identity is invalid")
        creator = raw.get("creator")
        if (
            not isinstance(creator, dict)
            or not isinstance(creator.get("login"), str)
            or not creator["login"].strip()
            or type(creator.get("id")) is not int
            or creator["id"] <= 0
        ):
            raise BaselineLeaseError("Baseline lease deployment creator is invalid")
        return _DeploymentRecord(
            deployment_id=deployment_id,
            created_at=cast("str", created_at),
            lease_key=lease_key,
            environment=environment,
            initial_owner=owner,
            acquire_nonce=nonce,
            requested_ttl_seconds=cast("int", ttl_seconds),
            url=url,
            statuses_url=statuses_url,
        )

    def _parse_status(
        self,
        raw: Mapping[str, Any],
        *,
        deployment: _DeploymentRecord,
        observed_at: datetime,
    ) -> BaselineLeaseReceipt:
        status_id = _require_positive_int(raw.get("id"), field="status id")
        status_url = f"{deployment.statuses_url}/{status_id}"
        transition = self._decode_transition(raw.get("description"), deployment)
        if (
            transition.operation is LeaseOperation.ACQUIRE
            and transition.ttl_seconds != deployment.requested_ttl_seconds
        ):
            raise BaselineLeaseError(
                "Baseline lease acquire status TTL differs from its deployment request"
            )
        created_at = raw.get("created_at")
        created = _parse_timestamp(created_at, field="status created_at")
        deployment_created = _parse_timestamp(
            deployment.created_at,
            field="deployment created_at",
        )
        if created < deployment_created or created > observed_at:
            raise BaselineLeaseError("Baseline lease status timestamp is invalid")
        expected_state = (
            "inactive" if transition.operation is LeaseOperation.RELEASE else "in_progress"
        )
        expected_log_url = (
            f"{self._server_url}/{self._repository}/actions/runs/"
            f"{transition.owner.run_id}/attempts/{transition.owner.run_attempt}"
        )
        if (
            raw.get("url") != status_url
            or raw.get("deployment_url") != deployment.url
            or raw.get("repository_url") != self._repository_api_url
            or raw.get("environment") != deployment.environment
            or raw.get("state") != expected_state
            or raw.get("log_url") != expected_log_url
        ):
            raise BaselineLeaseError("Baseline lease deployment status identity is invalid")
        creator = raw.get("creator")
        if (
            not isinstance(creator, dict)
            or not isinstance(creator.get("login"), str)
            or not creator["login"].strip()
            or type(creator.get("id")) is not int
            or creator["id"] <= 0
        ):
            raise BaselineLeaseError("Baseline lease deployment status creator is invalid")
        state = (
            LeaseState.RELEASED
            if transition.operation is LeaseOperation.RELEASE
            else LeaseState.ACTIVE
        )
        expires = created + timedelta(seconds=transition.ttl_seconds)
        try:
            return BaselineLeaseReceipt(
                lease_key=deployment.lease_key,
                environment=deployment.environment,
                fence=deployment.deployment_id,
                revision=status_id,
                owner=transition.owner,
                state=state,
                operation=transition.operation,
                transition_nonce=transition.nonce,
                predecessor_revision=transition.predecessor_revision,
                transition_authority_sha256=transition.authority_sha256,
                deployment_created_at=deployment.created_at,
                heartbeat_at=cast("str", created_at),
                expires_at=_format_timestamp(expires),
                deployment_url=deployment.url,
                status_url=status_url,
            )
        except (TypeError, ValueError) as exc:
            raise BaselineLeaseError("Baseline lease persisted status receipt is invalid") from exc

    @staticmethod
    def _pending_receipt(deployment: _DeploymentRecord) -> BaselineLeaseReceipt:
        created = _parse_timestamp(deployment.created_at, field="deployment created_at")
        return BaselineLeaseReceipt(
            lease_key=deployment.lease_key,
            environment=deployment.environment,
            fence=deployment.deployment_id,
            revision=0,
            owner=deployment.initial_owner,
            state=LeaseState.PENDING,
            operation=LeaseOperation.ACQUIRE,
            transition_nonce=deployment.acquire_nonce,
            predecessor_revision=None,
            transition_authority_sha256=None,
            deployment_created_at=deployment.created_at,
            heartbeat_at=deployment.created_at,
            expires_at=_format_timestamp(
                created + timedelta(seconds=deployment.requested_ttl_seconds)
            ),
            deployment_url=deployment.url,
            status_url=None,
        )

    @classmethod
    def _validate_transition_authority(
        cls,
        current: BaselineLeaseReceipt,
        predecessor: BaselineLeaseReceipt,
    ) -> None:
        if current.fence != predecessor.fence or current.revision <= predecessor.revision:
            raise BaselineLeaseError("Baseline lease status revision is not monotonic")
        if current.predecessor_revision != predecessor.revision:
            raise BaselineLeaseError("Baseline lease predecessor revision is not exact")
        current_time = _parse_timestamp(current.heartbeat_at, field="status created_at")
        predecessor_time = _parse_timestamp(
            predecessor.heartbeat_at,
            field="status created_at",
        )
        if current_time < predecessor_time:
            raise BaselineLeaseError("Baseline lease status chronology is invalid")
        ttl_seconds = cls._receipt_ttl_seconds(current)
        expected_authority = cls._transition_authority_sha256(
            current.operation,
            current.owner,
            ttl_seconds=ttl_seconds,
            nonce=current.transition_nonce,
            predecessor=predecessor,
        )
        if current.transition_authority_sha256 != expected_authority:
            raise BaselineLeaseError("Baseline lease transition receipt/owner authority is invalid")

    @staticmethod
    def _validate_transition_semantics(
        current: BaselineLeaseReceipt,
        predecessor: BaselineLeaseReceipt,
    ) -> None:
        current_time = _parse_timestamp(current.heartbeat_at, field="status created_at")
        if predecessor.state is LeaseState.PENDING:
            if predecessor.revision != 0:
                raise BaselineLeaseError("Baseline lease pending predecessor is not the root")
            if current.operation is LeaseOperation.ACQUIRE:
                if (
                    current.owner != predecessor.owner
                    or current.transition_nonce != predecessor.transition_nonce
                    or predecessor.is_expired_at(current_time)
                ):
                    raise BaselineLeaseError("Baseline lease root acquisition authority is invalid")
            elif current.operation is LeaseOperation.RECOVER:
                if current.owner == predecessor.owner or not predecessor.is_expired_at(
                    current_time
                ):
                    raise BaselineLeaseError("Baseline lease root recovery authority is invalid")
            else:
                raise BaselineLeaseError(
                    "Baseline lease first status is not acquire or expired recovery"
                )
            return
        if predecessor.state is LeaseState.RELEASED:
            raise BaselineLeaseError("Baseline lease cannot transition after release")
        if predecessor.state is not LeaseState.ACTIVE:
            raise BaselineLeaseError("Baseline lease transition predecessor is not active")
        if current.operation is LeaseOperation.ACQUIRE:
            raise BaselineLeaseError("Baseline lease acquire is not a root transition")
        if current.operation in {LeaseOperation.HEARTBEAT, LeaseOperation.RELEASE}:
            if current.owner != predecessor.owner or predecessor.is_expired_at(current_time):
                raise BaselineLeaseError("Baseline lease owner renewed or released stale authority")
        elif current.operation is LeaseOperation.TRANSFER:
            if current.owner == predecessor.owner or predecessor.is_expired_at(current_time):
                raise BaselineLeaseError("Baseline lease transfer authority is invalid")
        elif current.operation is LeaseOperation.RECOVER and (
            current.owner == predecessor.owner or not predecessor.is_expired_at(current_time)
        ):
            raise BaselineLeaseError("Baseline lease recovery authority is invalid")

    @classmethod
    def _validate_transition_pair(
        cls,
        current: BaselineLeaseReceipt,
        predecessor: BaselineLeaseReceipt,
    ) -> None:
        cls._validate_transition_authority(current, predecessor)
        cls._validate_transition_semantics(current, predecessor)

    def _latest_receipt(
        self,
        deployment: _DeploymentRecord,
    ) -> _StatusInventory:
        summaries: list[Any] = []
        page = 1
        while True:
            page_rows, server_time = self._require_list(
                self._request(
                    "GET",
                    (f"{deployment.statuses_url}?per_page={_STATUS_PAGE_SIZE}&page={page}"),
                ),
                operation="status inventory",
            )
            if len(page_rows) > _STATUS_PAGE_SIZE:
                raise BaselineLeaseError("Baseline lease status inventory page exceeded its bound")
            if len(summaries) + len(page_rows) > _MAX_STATUS_INVENTORY:
                raise BaselineLeaseError(
                    "Baseline lease status inventory exceeded its bounded contract"
                )
            summaries.extend(page_rows)
            if len(page_rows) < _STATUS_PAGE_SIZE:
                break
            if len(summaries) == _MAX_STATUS_INVENTORY:
                overflow, server_time = self._require_list(
                    self._request(
                        "GET",
                        (f"{deployment.statuses_url}?per_page={_STATUS_PAGE_SIZE}&page={page + 1}"),
                    ),
                    operation="status inventory overflow check",
                )
                if overflow:
                    raise BaselineLeaseError(
                        "Baseline lease status inventory exceeded its bounded contract"
                    )
                break
            page += 1

        pending = self._pending_receipt(deployment)
        if not summaries:
            inventory_digest = _canonical_sha256(
                {
                    "schema_version": 1,
                    "deployment_id": deployment.deployment_id,
                    "statuses": [],
                }
            )
            return _StatusInventory(
                current=pending,
                retained_latest=None,
                retained_plausible_heads=(),
                retention_truncated=False,
                server_time=server_time,
                inventory_digest=inventory_digest,
                count=0,
            )

        receipts: list[BaselineLeaseReceipt] = []
        seen_status_ids: set[int] = set()
        for summary in summaries:
            if not isinstance(summary, dict):
                raise BaselineLeaseError("Baseline lease status inventory is malformed")
            status_id = _require_positive_int(summary.get("id"), field="status id")
            if status_id in seen_status_ids:
                raise BaselineLeaseError("Baseline lease status inventory repeats an ID")
            seen_status_ids.add(status_id)
            summary_created_at = summary.get("created_at")
            _parse_timestamp(summary_created_at, field="status created_at")
            direct, observed_at = self._require_object(
                self._request("GET", f"{deployment.statuses_url}/{status_id}"),
                operation="direct status receipt",
            )
            receipt = self._parse_status(
                direct,
                deployment=deployment,
                observed_at=observed_at,
            )
            expected_status_url = f"{deployment.statuses_url}/{status_id}"
            if (
                receipt.revision != status_id
                or receipt.status_url != expected_status_url
                or receipt.heartbeat_at != summary_created_at
            ):
                raise BaselineLeaseError(
                    "Baseline lease direct status receipt changed from inventory"
                )
            receipts.append(receipt)
            server_time = observed_at
        by_revision = {0: pending}
        children: dict[int, list[BaselineLeaseReceipt]] = {}
        retention_truncated = False
        for receipt in sorted(receipts, key=lambda item: item.revision):
            predecessor_revision = receipt.predecessor_revision
            assert predecessor_revision is not None
            if predecessor_revision >= receipt.revision:
                raise BaselineLeaseError("Baseline lease status revision is not monotonic")
            predecessor = by_revision.get(predecessor_revision)
            if predecessor is None:
                retention_truncated = True
            else:
                self._validate_transition_authority(receipt, predecessor)
            by_revision[receipt.revision] = receipt
            children.setdefault(predecessor_revision, []).append(receipt)

        current = pending
        while descendants := children.get(current.revision):
            selected: BaselineLeaseReceipt | None = None
            for descendant in sorted(descendants, key=lambda item: item.revision):
                try:
                    self._validate_transition_pair(descendant, current)
                except BaselineLeaseError:
                    continue
                selected = descendant
                break
            if selected is None:
                break
            current = selected
        inventory_digest = _canonical_sha256(
            {
                "schema_version": 1,
                "deployment_id": deployment.deployment_id,
                "statuses": [
                    {
                        "revision": receipt.revision,
                        "receipt_digest": receipt.receipt_digest,
                    }
                    for receipt in sorted(receipts, key=lambda item: item.revision)
                ],
            }
        )
        retained_latest = max(
            receipts,
            key=lambda item: (
                _parse_timestamp(item.heartbeat_at, field="status created_at"),
                item.revision,
            ),
        )
        if retention_truncated:
            deployment_created = _parse_timestamp(
                deployment.created_at,
                field="deployment created_at",
            )
            retention_cutoff = server_time - timedelta(seconds=_STATUS_RETENTION_SECONDS)
            if deployment_created > retention_cutoff:
                raise BaselineLeaseError(
                    "Baseline lease recent status predecessor receipt is missing"
                )
            retained_roots = [
                receipt for receipt in receipts if receipt.predecessor_revision not in by_revision
            ]
            plausible_heads: list[BaselineLeaseReceipt] = []
            for root in sorted(retained_roots, key=lambda item: item.revision):
                plausible = root
                while descendants := children.get(plausible.revision):
                    selected = None
                    for descendant in sorted(descendants, key=lambda item: item.revision):
                        try:
                            self._validate_transition_pair(descendant, plausible)
                        except BaselineLeaseError:
                            continue
                        selected = descendant
                        break
                    if selected is None:
                        break
                    plausible = selected
                plausible_heads.append(plausible)
            if not plausible_heads:
                raise BaselineLeaseError(
                    "Baseline lease retained status graph has no plausible head"
                )
            retained_latest = max(
                plausible_heads,
                key=lambda item: (
                    _parse_timestamp(item.heartbeat_at, field="status created_at"),
                    item.revision,
                ),
            )
            unexpired_active_heads = [
                head
                for head in plausible_heads
                if head.state is LeaseState.ACTIVE and not head.is_expired_at(server_time)
            ]
            if unexpired_active_heads:
                retained_latest = max(
                    unexpired_active_heads,
                    key=lambda item: (
                        _parse_timestamp(item.expires_at, field="expires_at"),
                        _parse_timestamp(item.heartbeat_at, field="status created_at"),
                        item.revision,
                    ),
                )
            current = None
            retained_plausible_heads = tuple(
                sorted(plausible_heads, key=lambda item: item.revision)
            )
        else:
            retained_plausible_heads = (current,)
        return _StatusInventory(
            current=current,
            retained_latest=retained_latest,
            retained_plausible_heads=retained_plausible_heads,
            retention_truncated=retention_truncated,
            server_time=server_time,
            inventory_digest=inventory_digest,
            count=len(summaries),
        )

    def _direct_deployment(
        self,
        deployment_id: int,
        *,
        lease_key: str,
    ) -> tuple[_DeploymentRecord, datetime]:
        expected_url = f"{self._repository_api_url}/deployments/{deployment_id}"
        raw, observed_at = self._require_object(
            self._request("GET", expected_url),
            operation="direct deployment receipt",
        )
        deployment = self._parse_deployment(
            raw,
            lease_key=lease_key,
            observed_at=observed_at,
        )
        if (
            deployment.deployment_id != deployment_id
            or deployment.url != expected_url
            or deployment.statuses_url != f"{expected_url}/statuses"
        ):
            raise BaselineLeaseError(
                "Baseline lease direct deployment receipt changed from requested ID"
            )
        return deployment, observed_at

    def _snapshot(self, lease_key: str) -> tuple[BaselineLeaseInspection, str]:
        environment = self.environment_for(lease_key)
        owner_name, repository_name = self._repository.split("/", 1)
        summaries: list[dict[str, Any]] = []
        total_count: int | None = None
        cursor: str | None = None
        seen_cursors: set[str] = set()
        last_summary_time: datetime | None = None
        while True:
            graphql, server_time = self._require_object(
                self._request(
                    "POST",
                    f"{self._api_url}/graphql",
                    json_body={
                        "query": _LEASE_HEAD_QUERY,
                        "variables": {
                            "owner": owner_name,
                            "repository": repository_name,
                            "environment": environment,
                            "pageSize": _DEPLOYMENT_PAGE_SIZE,
                            "cursor": cursor,
                        },
                    },
                ),
                operation="ordered deployment inventory",
            )
            data = graphql.get("data")
            repository = data.get("repository") if isinstance(data, dict) else None
            deployments = repository.get("deployments") if isinstance(repository, dict) else None
            page_rows = deployments.get("nodes") if isinstance(deployments, dict) else None
            page_total = deployments.get("totalCount") if isinstance(deployments, dict) else None
            page_info = deployments.get("pageInfo") if isinstance(deployments, dict) else None
            if (
                graphql.get("errors") is not None
                or type(page_total) is not int
                or page_total < 0
                or page_total > _MAX_DEPLOYMENT_INVENTORY
                or not isinstance(page_rows, list)
                or len(page_rows) > _DEPLOYMENT_PAGE_SIZE
                or not isinstance(page_info, dict)
                or set(page_info) != {"hasNextPage", "endCursor"}
                or type(page_info.get("hasNextPage")) is not bool
            ):
                raise BaselineLeaseError(
                    "Baseline lease deployment inventory exceeds its bounded contract"
                )
            if total_count is None:
                total_count = page_total
            elif page_total != total_count:
                raise BaselineLeaseError(
                    "Baseline lease deployment inventory count changed during pagination"
                )
            if len(summaries) + len(page_rows) > _MAX_DEPLOYMENT_INVENTORY:
                raise BaselineLeaseError(
                    "Baseline lease deployment inventory exceeds its bounded contract"
                )
            for summary in page_rows:
                if not isinstance(summary, dict) or set(summary) != {
                    "databaseId",
                    "createdAt",
                }:
                    raise BaselineLeaseError("Baseline lease deployment inventory is malformed")
                summary_time = _parse_timestamp(
                    summary.get("createdAt"),
                    field="deployment created_at",
                )
                if last_summary_time is not None and summary_time > last_summary_time:
                    raise BaselineLeaseError(
                        "Baseline lease deployment inventory timestamp order is invalid"
                    )
                last_summary_time = summary_time
                summaries.append(cast("dict[str, Any]", summary))
            has_next = cast("bool", page_info["hasNextPage"])
            end_cursor = page_info["endCursor"]
            if page_rows:
                if not isinstance(end_cursor, str) or not end_cursor:
                    raise BaselineLeaseError(
                        "Baseline lease deployment inventory cursor is invalid"
                    )
            elif end_cursor is not None:
                raise BaselineLeaseError("Baseline lease empty deployment page has a cursor")
            if not has_next:
                break
            if (
                not page_rows
                or not isinstance(end_cursor, str)
                or end_cursor in seen_cursors
                or end_cursor == cursor
            ):
                raise BaselineLeaseError(
                    "Baseline lease deployment inventory cursor did not advance"
                )
            seen_cursors.add(end_cursor)
            cursor = end_cursor

        assert total_count is not None
        if len(summaries) != total_count:
            raise BaselineLeaseError("Baseline lease deployment inventory is incomplete")
        seen_deployment_ids: set[int] = set()
        canonical_summaries: list[tuple[datetime, int, dict[str, Any]]] = []
        for summary in summaries:
            deployment_id = _require_positive_int(
                summary.get("databaseId"),
                field="deployment id",
            )
            if deployment_id in seen_deployment_ids:
                raise BaselineLeaseError("Baseline lease deployment inventory repeats an ID")
            seen_deployment_ids.add(deployment_id)
            created = _parse_timestamp(
                summary.get("createdAt"),
                field="deployment created_at",
            )
            canonical_summaries.append((created, deployment_id, summary))
        canonical_summaries.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if canonical_summaries and canonical_summaries[0][1] != max(
            deployment_id for _, deployment_id, _ in canonical_summaries
        ):
            raise BaselineLeaseError(
                "Baseline lease deployment head is not the global maximum fence"
            )
        deployment_inventory_digest = _canonical_sha256(
            {
                "schema_version": 1,
                "deployments": [
                    {
                        "deployment_id": deployment_id,
                        "created_at": cast("str", summary["createdAt"]),
                    }
                    for _, deployment_id, summary in canonical_summaries
                ],
            }
        )
        direct_deployments: list[_DeploymentRecord] = []
        for _, deployment_id, summary in canonical_summaries[:_HEAD_WINDOW]:
            summary_created_at = cast("str", summary["createdAt"])
            deployment, observed_at = self._direct_deployment(
                deployment_id,
                lease_key=lease_key,
            )
            if deployment.created_at != summary_created_at:
                raise BaselineLeaseError(
                    "Baseline lease direct deployment receipt changed from inventory"
                )
            direct_deployments.append(deployment)
            server_time = max(server_time, observed_at)
        if len(direct_deployments) == 2:
            current_deployment, previous_deployment = direct_deployments
            current_created = _parse_timestamp(
                current_deployment.created_at,
                field="deployment created_at",
            )
            previous_created = _parse_timestamp(
                previous_deployment.created_at,
                field="deployment created_at",
            )
            if (
                current_created < previous_created
                or current_deployment.deployment_id <= previous_deployment.deployment_id
            ):
                raise BaselineLeaseError("Baseline lease deployment fence is not monotonic")
        status_inventory = (
            self._latest_receipt(direct_deployments[0]) if direct_deployments else None
        )
        if status_inventory is not None:
            server_time = max(server_time, status_inventory.server_time)
        current_receipt = status_inventory.current if status_inventory is not None else None
        retained_latest = status_inventory.retained_latest if status_inventory is not None else None
        identity = _canonical_sha256(
            {
                "lease_key": lease_key,
                "inventory_count": total_count,
                "deployment_inventory_digest": deployment_inventory_digest,
                "direct_deployments": [
                    {
                        "deployment_id": deployment.deployment_id,
                        "created_at": deployment.created_at,
                        "initial_owner_digest": deployment.initial_owner.digest,
                        "acquire_nonce": deployment.acquire_nonce,
                        "requested_ttl_seconds": deployment.requested_ttl_seconds,
                        "url": deployment.url,
                        "statuses_url": deployment.statuses_url,
                    }
                    for deployment in direct_deployments
                ],
                "current_status_inventory_digest": (
                    status_inventory.inventory_digest if status_inventory is not None else None
                ),
                "retention_truncated": (
                    status_inventory.retention_truncated if status_inventory is not None else False
                ),
                "retained_head_receipt_digest": (
                    retained_latest.receipt_digest if retained_latest is not None else None
                ),
                "retained_plausible_head_receipt_digests": (
                    [
                        receipt.receipt_digest
                        for receipt in status_inventory.retained_plausible_heads
                    ]
                    if status_inventory is not None
                    else []
                ),
            }
        )
        return (
            BaselineLeaseInspection(
                lease_key=lease_key,
                server_time=server_time,
                current=current_receipt,
                head_fence=(direct_deployments[0].deployment_id if direct_deployments else None),
                inventory_count=total_count,
                status_inventory_count=(
                    status_inventory.count if status_inventory is not None else 0
                ),
                retention_truncated=(
                    status_inventory.retention_truncated if status_inventory is not None else False
                ),
                retained_head_revision=(
                    retained_latest.revision if retained_latest is not None else None
                ),
                retained_head_state=(
                    retained_latest.state if retained_latest is not None else None
                ),
                retained_head_expires_at=(
                    retained_latest.expires_at if retained_latest is not None else None
                ),
                retained_head_status_url=(
                    retained_latest.status_url if retained_latest is not None else None
                ),
            ),
            identity,
        )

    def inspect(self, lease_key: str) -> BaselineLeaseInspection:
        canonical = _canonical_lease_key(lease_key)
        observations: list[tuple[BaselineLeaseInspection, str]] = []
        for index in range(3):
            if index:
                self._sleep(self._snapshot_delay_seconds)
            observations.append(self._snapshot(canonical))
        if observations[-1][1] != observations[-2][1]:
            raise BaselineLeaseError("Baseline lease head inventory did not stabilize")
        return observations[-1][0]

    def scheduled_admission(self, lease_key: str) -> ScheduledLeaseAdmission:
        inspection = self.inspect(lease_key)
        current = inspection.current
        if inspection.held:
            return ScheduledLeaseAdmission(
                action=ScheduledLeaseAction.NOOP_HELD,
                server_time=inspection.server_time,
                fence=inspection.head_fence,
                receipt_digest=(current.receipt_digest if current is not None else None),
                expires_at=(
                    current.expires_at
                    if current is not None
                    else inspection.retained_head_expires_at
                ),
            )
        return ScheduledLeaseAdmission(
            action=ScheduledLeaseAction.ACQUIRE_REQUIRED,
            server_time=inspection.server_time,
            fence=inspection.head_fence,
            receipt_digest=current.receipt_digest if current is not None else None,
            expires_at=current.expires_at if current is not None else None,
        )

    def _require_exact_current(
        self,
        expected: BaselineLeaseReceipt,
        *,
        require_unexpired: bool,
        allow_pending: bool = False,
    ) -> BaselineLeaseInspection:
        inspection = self.inspect(expected.lease_key)
        current = inspection.current
        if current is None or current.receipt_digest != expected.receipt_digest:
            raise BaselineLeaseStaleError("Baseline lease receipt is no longer current")
        if current.state is not LeaseState.ACTIVE and not (
            allow_pending and current.state is LeaseState.PENDING
        ):
            raise BaselineLeaseStaleError("Baseline lease receipt is not active")
        if require_unexpired and current.is_expired_at(inspection.server_time):
            raise BaselineLeaseStaleError("Baseline lease receipt has expired")
        return inspection

    def assert_current(self, receipt: BaselineLeaseReceipt) -> BaselineLeaseReceipt:
        if not isinstance(receipt, BaselineLeaseReceipt):
            raise BaselineLeaseError("Baseline lease receipt is invalid")
        return cast(
            "BaselineLeaseReceipt",
            self._require_exact_current(receipt, require_unexpired=True).current,
        )

    @classmethod
    def _is_persisted_transition(
        cls,
        receipt: BaselineLeaseReceipt | None,
        *,
        expected: BaselineLeaseReceipt,
        operation: LeaseOperation,
        owner: BaselineLeaseOwner,
        ttl_seconds: int,
        nonce: str,
    ) -> bool:
        if receipt is None:
            return False
        target_state = (
            LeaseState.RELEASED if operation is LeaseOperation.RELEASE else LeaseState.ACTIVE
        )
        return (
            receipt.fence == expected.fence
            and receipt.revision > expected.revision
            and receipt.state is target_state
            and receipt.operation is operation
            and receipt.owner == owner
            and receipt.transition_nonce == nonce
            and receipt.predecessor_revision == expected.revision
            and receipt.transition_authority_sha256
            == cls._transition_authority_sha256(
                operation,
                owner,
                ttl_seconds=ttl_seconds,
                nonce=nonce,
                predecessor=expected,
            )
            and receipt.status_url == f"{expected.deployment_url}/statuses/{receipt.revision}"
        )

    def _reconcile_transition(
        self,
        expected: BaselineLeaseReceipt,
        *,
        operation: LeaseOperation,
        owner: BaselineLeaseOwner,
        ttl_seconds: int,
        nonce: str,
    ) -> BaselineLeaseReceipt | None:
        """Return only an exact, stable transition already persisted at the head."""
        try:
            inspection = self.inspect(expected.lease_key)
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                f"Baseline lease {operation.value} outcome requires exact nonce reconciliation",
                nonce=nonce,
            ) from exc
        current = inspection.current
        if not self._is_persisted_transition(
            current,
            expected=expected,
            operation=operation,
            owner=owner,
            ttl_seconds=ttl_seconds,
            nonce=nonce,
        ):
            return None
        assert current is not None
        try:
            reread = self.inspect(expected.lease_key).current
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                f"Baseline lease {operation.value} outcome requires exact nonce reconciliation",
                nonce=nonce,
            ) from exc
        if (
            reread is not None
            and reread.receipt_digest == current.receipt_digest
            and self._is_persisted_transition(
                reread,
                expected=expected,
                operation=operation,
                owner=owner,
                ttl_seconds=ttl_seconds,
                nonce=nonce,
            )
        ):
            return reread
        raise BaselineLeaseStaleError(
            "Baseline lease transition changed during final direct reread"
        )

    def _post_transition(
        self,
        expected: BaselineLeaseReceipt,
        *,
        operation: LeaseOperation,
        owner: BaselineLeaseOwner,
        ttl_seconds: int,
        nonce: str,
        require_unexpired: bool,
    ) -> BaselineLeaseReceipt:
        self._require_owner(owner)
        self._require_ttl(ttl_seconds, allow_zero=operation is LeaseOperation.RELEASE)
        if (
            (operation is LeaseOperation.RELEASE and ttl_seconds != 0)
            or (operation is not LeaseOperation.RELEASE and ttl_seconds <= 0)
            or not isinstance(nonce, str)
            or _HEX_32_RE.fullmatch(nonce) is None
        ):
            raise ValueError("Baseline lease transition parameters are invalid")
        try:
            current_inspection = self._require_exact_current(
                expected,
                require_unexpired=require_unexpired,
                allow_pending=operation in {LeaseOperation.ACQUIRE, LeaseOperation.RECOVER},
            )
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                f"Baseline lease {operation.value} outcome requires exact nonce reconciliation",
                nonce=nonce,
            ) from exc
        except BaselineLeaseStaleError:
            reconciled = self._reconcile_transition(
                expected,
                operation=operation,
                owner=owner,
                ttl_seconds=ttl_seconds,
                nonce=nonce,
            )
            if reconciled is not None:
                return reconciled
            raise
        if current_inspection.status_inventory_count >= _MAX_STATUS_INVENTORY:
            raise BaselineLeaseError(
                "Baseline lease status inventory has no reserved mutation capacity"
            )
        description = self._encode_transition(
            operation,
            owner,
            ttl_seconds=ttl_seconds,
            nonce=nonce,
            predecessor=expected,
        )
        body = {
            "state": "inactive" if operation is LeaseOperation.RELEASE else "in_progress",
            "description": description,
            "environment": expected.environment,
            "log_url": (
                f"{self._server_url}/{self._repository}/actions/runs/"
                f"{owner.run_id}/attempts/{owner.run_attempt}"
            ),
            "auto_inactive": False,
        }
        posted: BaselineLeaseReceipt | None = None
        ambiguous = False
        try:
            creation_result = self._request(
                "POST",
                f"{expected.deployment_url}/statuses",
                json_body=body,
            )
        except (TimeoutError, OSError, BaselineLeaseError):
            ambiguous = True
        else:
            creation_response, _server_time = creation_result
            if creation_response.status_code >= 500 or (
                creation_response.status_code == 201
                and not isinstance(creation_response.payload, dict)
            ):
                ambiguous = True
            elif creation_response.status_code != 201:
                raise BaselineLeaseError(
                    f"GitHub baseline lease {operation.value} status creation failed "
                    f"with HTTP {creation_response.status_code}"
                )
            else:
                created = cast("dict[str, Any]", creation_response.payload)
                try:
                    status_id = _require_positive_int(created.get("id"), field="status id")
                except BaselineLeaseError:
                    ambiguous = True
                else:
                    if status_id <= expected.revision:
                        raise BaselineLeaseError("Baseline lease status revision is not monotonic")
                    expected_status_url = f"{expected.deployment_url}/statuses/{status_id}"
                    try:
                        direct_result = self._request("GET", expected_status_url)
                    except (TimeoutError, OSError, BaselineLeaseError) as exc:
                        raise BaselineLeasePendingError(
                            f"Baseline lease {operation.value} outcome requires exact nonce "
                            "reconciliation",
                            nonce=nonce,
                        ) from exc
                    direct_response, observed_at = direct_result
                    if direct_response.status_code != 200 or not isinstance(
                        direct_response.payload,
                        dict,
                    ):
                        raise BaselineLeasePendingError(
                            f"Baseline lease {operation.value} outcome requires exact nonce "
                            "reconciliation",
                            nonce=nonce,
                        )
                    direct = cast("dict[str, Any]", direct_response.payload)
                    if direct.get("id") != status_id or direct.get("url") != expected_status_url:
                        raise BaselineLeaseError(
                            "Baseline lease transition receipt changed after creation"
                        )
                    expected_deployment_url = (
                        f"{self._repository_api_url}/deployments/{expected.fence}"
                    )
                    try:
                        deployment_result = self._request(
                            "GET",
                            expected_deployment_url,
                        )
                    except (TimeoutError, OSError, BaselineLeaseError) as exc:
                        raise BaselineLeasePendingError(
                            f"Baseline lease {operation.value} outcome requires exact nonce "
                            "reconciliation",
                            nonce=nonce,
                        ) from exc
                    deployment_response, deployment_observed_at = deployment_result
                    if deployment_response.status_code != 200 or not isinstance(
                        deployment_response.payload,
                        dict,
                    ):
                        raise BaselineLeasePendingError(
                            f"Baseline lease {operation.value} outcome requires exact nonce "
                            "reconciliation",
                            nonce=nonce,
                        )
                    deployment = self._parse_deployment(
                        cast(
                            "dict[str, Any]",
                            deployment_response.payload,
                        ),
                        lease_key=expected.lease_key,
                        observed_at=deployment_observed_at,
                    )
                    if (
                        deployment.deployment_id != expected.fence
                        or deployment.url != expected_deployment_url
                        or deployment.statuses_url != f"{expected_deployment_url}/statuses"
                    ):
                        raise BaselineLeaseError(
                            "Baseline lease direct deployment receipt changed from requested ID"
                        )
                    posted = self._parse_status(
                        direct,
                        deployment=deployment,
                        observed_at=observed_at,
                    )
                    if not self._is_persisted_transition(
                        posted,
                        expected=expected,
                        operation=operation,
                        owner=owner,
                        ttl_seconds=ttl_seconds,
                        nonce=nonce,
                    ):
                        raise BaselineLeaseError(
                            "Baseline lease transition receipt changed after creation"
                        )
        reconciled = self._reconcile_transition(
            expected,
            operation=operation,
            owner=owner,
            ttl_seconds=ttl_seconds,
            nonce=nonce,
        )
        if reconciled is not None:
            return reconciled
        if posted is not None or not ambiguous:
            raise BaselineLeaseStaleError("Baseline lease transition lost current authority")
        raise BaselineLeasePendingError(
            f"Baseline lease {operation.value} outcome requires exact nonce reconciliation",
            nonce=nonce,
        )

    def acquire(
        self,
        lease_key: str,
        owner: BaselineLeaseOwner,
        *,
        ttl_seconds: int,
        nonce: str | None = None,
    ) -> BaselineLeaseReceipt:
        canonical = _canonical_lease_key(lease_key)
        self._require_owner(owner)
        self._require_ttl(ttl_seconds)
        acquire_nonce = nonce if nonce is not None else self._new_nonce()
        if not isinstance(acquire_nonce, str) or _HEX_32_RE.fullmatch(acquire_nonce) is None:
            raise ValueError("Baseline lease acquisition nonce is invalid")
        before = self.inspect(canonical)
        if before.inventory_count >= _MAX_DEPLOYMENT_INVENTORY:
            raise BaselineLeaseError(
                "Baseline lease deployment inventory has no reserved mutation capacity"
            )
        if before.held:
            raise BaselineLeaseHeldError("Baseline lease is already held")
        previous_fence = before.head_fence or 0
        environment = self.environment_for(canonical)
        description = (
            f"{_LEASE_DESCRIPTION_PREFIX}{hashlib.sha256(canonical.encode()).hexdigest()[:20]}"
        )
        body = {
            "ref": owner.source_sha,
            "task": BASELINE_LEASE_DEPLOYMENT_TASK,
            "auto_merge": False,
            "required_contexts": [],
            "payload": self._deployment_payload(
                lease_key=canonical,
                owner=owner,
                ttl_seconds=ttl_seconds,
                nonce=acquire_nonce,
            ),
            "environment": environment,
            "description": description,
            "transient_environment": False,
            "production_environment": False,
        }
        try:
            creation_result = self._request(
                "POST",
                f"{self._repository_api_url}/deployments",
                json_body=body,
            )
        except (TimeoutError, OSError, BaselineLeaseError):
            return self.reconcile_acquire(
                canonical,
                owner,
                ttl_seconds=ttl_seconds,
                nonce=acquire_nonce,
            )
        creation_response, _server_time = creation_result
        if creation_response.status_code >= 500 or (
            creation_response.status_code == 201 and not isinstance(creation_response.payload, dict)
        ):
            return self.reconcile_acquire(
                canonical,
                owner,
                ttl_seconds=ttl_seconds,
                nonce=acquire_nonce,
            )
        if creation_response.status_code != 201:
            raise BaselineLeaseError(
                "GitHub baseline lease deployment creation failed "
                f"with HTTP {creation_response.status_code}"
            )
        created = cast("dict[str, Any]", creation_response.payload)
        try:
            deployment_id = _require_positive_int(created.get("id"), field="deployment id")
        except BaselineLeaseError:
            return self.reconcile_acquire(
                canonical,
                owner,
                ttl_seconds=ttl_seconds,
                nonce=acquire_nonce,
            )
        if deployment_id <= previous_fence:
            raise BaselineLeaseError("Baseline lease deployment fence is not monotonic")
        try:
            deployment, _ = self._direct_deployment(deployment_id, lease_key=canonical)
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                "Baseline lease deployment outcome requires exact nonce reconciliation",
                nonce=acquire_nonce,
            ) from exc
        if (
            deployment.acquire_nonce != acquire_nonce
            or deployment.initial_owner != owner
            or deployment.requested_ttl_seconds != ttl_seconds
        ):
            raise BaselineLeaseError("Baseline lease deployment creation receipt is inconsistent")
        try:
            pending = self.inspect(canonical)
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                "Baseline lease acquisition outcome requires exact nonce reconciliation",
                nonce=acquire_nonce,
            ) from exc
        if pending.current is None or pending.current.fence != deployment.deployment_id:
            raise BaselineLeaseStaleError("Baseline lease deployment did not retain the head fence")
        try:
            current_deployment, _ = self._direct_deployment(
                pending.current.fence,
                lease_key=canonical,
            )
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                "Baseline lease acquisition outcome requires exact nonce reconciliation",
                nonce=acquire_nonce,
            ) from exc
        if current_deployment.requested_ttl_seconds != ttl_seconds:
            raise BaselineLeaseError(
                "Baseline lease deployment request TTL changed before acquisition"
            )
        if pending.current.revision > 0:
            if (
                pending.current.operation is LeaseOperation.ACQUIRE
                and pending.current.owner == owner
                and pending.current.transition_nonce == acquire_nonce
            ):
                try:
                    active = self.assert_current(pending.current)
                    deployment_reread, _ = self._direct_deployment(
                        active.fence,
                        lease_key=canonical,
                    )
                except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
                    raise BaselineLeasePendingError(
                        "Baseline lease acquisition outcome requires exact nonce reconciliation",
                        nonce=acquire_nonce,
                    ) from exc
                if (
                    deployment_reread.requested_ttl_seconds != ttl_seconds
                    or self._receipt_ttl_seconds(active) != ttl_seconds
                ):
                    raise BaselineLeaseError(
                        "Baseline lease active acquisition TTL differs from its caller request"
                    )
                return active
            raise BaselineLeaseStaleError("Baseline lease deployment was concurrently mutated")
        return self._post_transition(
            pending.current,
            operation=LeaseOperation.ACQUIRE,
            owner=owner,
            ttl_seconds=ttl_seconds,
            nonce=acquire_nonce,
            require_unexpired=True,
        )

    def reconcile_acquire(
        self,
        lease_key: str,
        owner: BaselineLeaseOwner,
        *,
        ttl_seconds: int,
        nonce: str,
    ) -> BaselineLeaseReceipt:
        canonical = _canonical_lease_key(lease_key)
        self._require_owner(owner)
        self._require_ttl(ttl_seconds)
        if not isinstance(nonce, str) or _HEX_32_RE.fullmatch(nonce) is None:
            raise ValueError("Baseline lease acquisition nonce is invalid")
        try:
            inspection = self.inspect(canonical)
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                "Baseline lease acquisition outcome requires exact nonce reconciliation",
                nonce=nonce,
            ) from exc
        current = inspection.current
        if (
            current is None
            or current.owner != owner
            or current.transition_nonce != nonce
            or current.operation is not LeaseOperation.ACQUIRE
        ):
            raise BaselineLeasePendingError(
                "Baseline lease acquisition nonce is not the current deployment head",
                nonce=nonce,
            )
        try:
            deployment, _ = self._direct_deployment(current.fence, lease_key=canonical)
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                "Baseline lease acquisition outcome requires exact nonce reconciliation",
                nonce=nonce,
            ) from exc
        if deployment.requested_ttl_seconds != ttl_seconds:
            raise BaselineLeaseError(
                "Baseline lease reconciliation TTL differs from its deployment request"
            )
        if current.state is LeaseState.ACTIVE:
            try:
                return self.assert_current(current)
            except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
                raise BaselineLeasePendingError(
                    "Baseline lease acquisition outcome requires exact nonce reconciliation",
                    nonce=nonce,
                ) from exc
        if current.state is not LeaseState.PENDING or current.is_expired_at(inspection.server_time):
            raise BaselineLeaseStaleError("Baseline lease pending acquisition expired")
        return self._post_transition(
            current,
            operation=LeaseOperation.ACQUIRE,
            owner=owner,
            ttl_seconds=ttl_seconds,
            nonce=nonce,
            require_unexpired=False,
        )

    def heartbeat(
        self,
        receipt: BaselineLeaseReceipt,
        *,
        ttl_seconds: int,
        nonce: str | None = None,
    ) -> BaselineLeaseReceipt:
        return self._post_transition(
            receipt,
            operation=LeaseOperation.HEARTBEAT,
            owner=receipt.owner,
            ttl_seconds=ttl_seconds,
            nonce=nonce if nonce is not None else self._new_nonce(),
            require_unexpired=True,
        )

    def transfer(
        self,
        receipt: BaselineLeaseReceipt,
        next_owner: BaselineLeaseOwner,
        *,
        ttl_seconds: int,
        nonce: str | None = None,
    ) -> BaselineLeaseReceipt:
        self._require_owner(next_owner)
        if (
            next_owner == receipt.owner
            or next_owner.source_sha != receipt.owner.source_sha
            or next_owner.workflow_sha256 != receipt.owner.workflow_sha256
        ):
            raise BaselineLeaseError("Baseline lease transfer owner authority is foreign")
        return self._post_transition(
            receipt,
            operation=LeaseOperation.TRANSFER,
            owner=next_owner,
            ttl_seconds=ttl_seconds,
            nonce=nonce if nonce is not None else self._new_nonce(),
            require_unexpired=True,
        )

    def recover(
        self,
        expired_receipt: BaselineLeaseReceipt,
        next_owner: BaselineLeaseOwner,
        *,
        ttl_seconds: int,
        nonce: str | None = None,
    ) -> BaselineLeaseReceipt:
        self._require_owner(next_owner)
        if (
            next_owner == expired_receipt.owner
            or next_owner.source_sha != expired_receipt.owner.source_sha
            or next_owner.workflow_sha256 != expired_receipt.owner.workflow_sha256
        ):
            raise BaselineLeaseError("Baseline lease recovery owner authority is foreign")
        self._require_ttl(ttl_seconds)
        recovery_nonce = nonce if nonce is not None else self._new_nonce()
        if not isinstance(recovery_nonce, str) or _HEX_32_RE.fullmatch(recovery_nonce) is None:
            raise ValueError("Baseline lease transition parameters are invalid")
        try:
            inspection = self._require_exact_current(
                expired_receipt,
                require_unexpired=False,
                allow_pending=True,
            )
        except (TimeoutError, OSError, _BaselineLeaseAmbiguousResponseError) as exc:
            raise BaselineLeasePendingError(
                "Baseline lease recover outcome requires exact nonce reconciliation",
                nonce=recovery_nonce,
            ) from exc
        except BaselineLeaseStaleError:
            reconciled = self._reconcile_transition(
                expired_receipt,
                operation=LeaseOperation.RECOVER,
                owner=next_owner,
                ttl_seconds=ttl_seconds,
                nonce=recovery_nonce,
            )
            if reconciled is not None:
                return reconciled
            raise
        if not expired_receipt.is_expired_at(inspection.server_time):
            raise BaselineLeaseError("Baseline lease recovery requires exact expired authority")
        return self._post_transition(
            expired_receipt,
            operation=LeaseOperation.RECOVER,
            owner=next_owner,
            ttl_seconds=ttl_seconds,
            nonce=recovery_nonce,
            require_unexpired=False,
        )

    def release(
        self,
        receipt: BaselineLeaseReceipt,
        *,
        nonce: str | None = None,
    ) -> BaselineLeaseReceipt:
        return self._post_transition(
            receipt,
            operation=LeaseOperation.RELEASE,
            owner=receipt.owner,
            ttl_seconds=0,
            nonce=nonce if nonce is not None else self._new_nonce(),
            require_unexpired=True,
        )
