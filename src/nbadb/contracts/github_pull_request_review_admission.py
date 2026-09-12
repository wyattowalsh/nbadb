"""Red-only, caller-claimed observations of GitHub pull-request reviews.

This module closes one deliberately narrow gap between a stable-model review
work packet and a later, repository-pinned trust stage.  It authenticates an
exact point-in-time GitHub readback against a caller-supplied identity policy,
but that policy is explicitly untrusted.  This module never issues a review
receipt, admits a protected identity, or turns a review gate green.  A future
stage must resolve a trust root outside every caller and pull-request input,
then perform its own current direct readback before making any such decision.

The only network primitive is private and fixed to ``api.github.com``.  Public
callers provide commitments, identifiers, and their untrusted policy bytes;
never response JSON, transport objects, base URLs, trusted digests, resolvers,
or pre-computed verification booleans.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import socket
import ssl
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast
from urllib.parse import urlsplit

from nbadb.contracts.stable_model_review_packet import (
    StableModelReviewChallengeV1,
    StableModelReviewResultSlotV1,
    StableModelReviewShardV1,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "GITHUB_PULL_REQUEST_REVIEW_ADMISSION_SCHEMA_VERSION",
    "CallerClaimedGitHubRepositoryV1",
    "CallerClaimedGitHubReviewPolicyV1",
    "CallerClaimedGitHubReviewerV1",
    "ExternalReviewResultBundleEntryV1",
    "ExternalReviewResultBundleV1",
    "GitHubApiReadReceiptV1",
    "GitHubPullRequestReviewAdmissionError",
    "UntrustedGitHubPullRequestReviewObservationV1",
    "build_caller_claimed_review_submission_body",
    "build_external_review_result_bundle",
    "observe_github_pull_request_review_untrusted",
]

GITHUB_PULL_REQUEST_REVIEW_ADMISSION_SCHEMA_VERSION = 1

_GITHUB_API_HOST = "api.github.com"
_GITHUB_API_VERSION = "2026-03-10"
_GITHUB_ACCEPT = "application/vnd.github+json"
_USER_AGENT = "nbadb-pr-review-observer/1"
_HTTPS_TIMEOUT_SECONDS = 30.0

_MAX_CALLER_POLICY_BYTES = 64 * 1024
_MAX_RESULT_BUNDLE_BYTES = 4 * 1024 * 1024
_MAX_OBSERVATION_BYTES = 512 * 1024
_MAX_PULL_REQUEST_BYTES = 2 * 1024 * 1024
_MAX_REVIEW_BYTES = 1 * 1024 * 1024
_MAX_JSON_DEPTH = 48
_MAX_JSON_NODES = 100_000
_MAX_PAYLOAD_NODES = 20_000

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
_OWNER_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?\Z", flags=re.ASCII)
_REPOSITORY_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,98}[a-z0-9])?\Z", flags=re.ASCII)
_LOGIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?\Z", flags=re.ASCII)
_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}\Z", flags=re.ASCII)
_NODE_ID_RE = re.compile(r"[A-Za-z0-9_=-]{1,256}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_ETAG_RE = re.compile(r"[\x21-\x7e]{1,512}\Z", flags=re.ASCII)
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9:_-]{1,256}\Z", flags=re.ASCII)
_RFC3339_UTC_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z\Z",
    flags=re.ASCII,
)
_ALLOWED_REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED"})
_READ_SEQUENCE: tuple[tuple[int, str], ...] = (
    (1, "PR_A"),
    (2, "review_A"),
    (3, "PR_B"),
    (4, "review_B"),
    (5, "PR_C"),
)
_READ_INVENTORY_DOMAIN = "nbadb:github-pr-review-untrusted-read-inventory:v1"

type ReviewerUserType = Literal["User", "Bot"]
type ReviewerRole = Literal["owner", "maintainer", "member"]
type ReviewerBotPolicy = Literal["human_only", "allow_bot"]


class GitHubPullRequestReviewAdmissionError(ValueError):
    """A caller policy, result commitment, or GitHub observation failed closed."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError, MemoryError) as exc:
        raise GitHubPullRequestReviewAdmissionError("value is not canonical JSON") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise GitHubPullRequestReviewAdmissionError(
            f"{field_name} must be an exact lowercase SHA-256"
        )
    return value


def _require_git_sha(value: object, *, field_name: str) -> str:
    if type(value) is not str or _GIT_SHA_RE.fullmatch(value) is None:
        raise GitHubPullRequestReviewAdmissionError(
            f"{field_name} must be an exact lowercase 40-character Git SHA"
        )
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0 or value > 2**63 - 1:
        raise GitHubPullRequestReviewAdmissionError(
            f"{field_name} must be a positive bounded integer"
        )
    return value


def _require_bounded_int(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GitHubPullRequestReviewAdmissionError(f"{field_name} is outside its exact bounds")
    return value


def _require_ascii_match(value: object, *, field_name: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise GitHubPullRequestReviewAdmissionError(
            f"{field_name} is not an exact canonical ASCII value"
        )
    return value


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise GitHubPullRequestReviewAdmissionError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _require_exact_keys(
    value: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if any(type(key) is not str for key in value):
        raise GitHubPullRequestReviewAdmissionError(f"{label} keys must be strings")
    actual = frozenset(value)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        extra = ",".join(sorted(actual - expected))
        raise GitHubPullRequestReviewAdmissionError(
            f"{label} fields differ (missing={missing}; unexpected={extra})"
        )


def _require_field(value: Mapping[str, object], field_name: str, *, label: str) -> object:
    if field_name not in value:
        raise GitHubPullRequestReviewAdmissionError(f"{label} omits {field_name}")
    return value[field_name]


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GitHubPullRequestReviewAdmissionError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _parse_finite_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise GitHubPullRequestReviewAdmissionError("JSON contains a non-finite number")
    return value


def _reject_nonfinite(_value: str) -> object:
    raise GitHubPullRequestReviewAdmissionError("JSON contains a non-finite number")


def _guard_json_shape(raw: bytes, *, label: str) -> None:
    """Bound allocation depth/node shape before materializing JSON."""

    stack: list[int] = []
    nodes = 0
    index = 0
    in_string = False
    escaping = False
    scalar = False
    while index < len(raw):
        token = raw[index]
        if in_string:
            if escaping:
                escaping = False
            elif token == 0x5C:
                escaping = True
            elif token == 0x22:
                in_string = False
            index += 1
            continue
        if token == 0x22:
            nodes += 1
            in_string = True
            scalar = False
        elif token in {0x7B, 0x5B}:
            nodes += 1
            if len(stack) >= _MAX_JSON_DEPTH:
                raise GitHubPullRequestReviewAdmissionError(
                    f"{label} exceeds its JSON depth budget"
                )
            stack.append(token)
            scalar = False
        elif token in {0x7D, 0x5D}:
            if not stack:
                raise GitHubPullRequestReviewAdmissionError(
                    f"{label} contains unmatched JSON delimiters"
                )
            expected = 0x7B if token == 0x7D else 0x5B
            if stack.pop() != expected:
                raise GitHubPullRequestReviewAdmissionError(
                    f"{label} contains mismatched JSON delimiters"
                )
            scalar = False
        elif token in {0x09, 0x0A, 0x0D, 0x20, 0x2C, 0x3A}:
            scalar = False
        elif not scalar:
            nodes += 1
            scalar = True
        if nodes > _MAX_JSON_NODES:
            raise GitHubPullRequestReviewAdmissionError(f"{label} exceeds its JSON node budget")
        index += 1
    if in_string or stack:
        raise GitHubPullRequestReviewAdmissionError(f"{label} contains incomplete JSON")


def _validate_json_tree(value: object, *, label: str, maximum_nodes: int) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > maximum_nodes:
            raise GitHubPullRequestReviewAdmissionError(f"{label} exceeds its JSON node budget")
        if depth > _MAX_JSON_DEPTH:
            raise GitHubPullRequestReviewAdmissionError(f"{label} exceeds its JSON depth budget")
        if type(current) is dict:
            mapping = cast("dict[object, object]", current)
            if any(type(key) is not str for key in mapping):
                raise GitHubPullRequestReviewAdmissionError(
                    f"{label} contains a non-string JSON key"
                )
            stack.extend((item, depth + 1) for item in mapping.values())
        elif type(current) is list:
            stack.extend((item, depth + 1) for item in cast("list[object]", current))
        elif type(current) is float:
            if not math.isfinite(current):
                raise GitHubPullRequestReviewAdmissionError(f"{label} contains a non-finite number")
        elif current is None or type(current) in {str, int, bool}:
            continue
        else:
            raise GitHubPullRequestReviewAdmissionError(f"{label} contains a non-JSON value")


def _decode_json(
    raw: bytes,
    *,
    label: str,
    maximum_bytes: int,
    require_canonical: bool,
) -> object:
    if type(raw) is not bytes or not raw or len(raw) > maximum_bytes:
        raise GitHubPullRequestReviewAdmissionError(f"{label} size is outside its exact bounds")
    _guard_json_shape(raw, label=label)
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
            parse_float=_parse_finite_float,
        )
    except GitHubPullRequestReviewAdmissionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError, MemoryError):
        raise GitHubPullRequestReviewAdmissionError(f"{label} is invalid JSON") from None
    _validate_json_tree(value, label=label, maximum_nodes=_MAX_JSON_NODES)
    if require_canonical and _canonical_bytes(value) != raw:
        raise GitHubPullRequestReviewAdmissionError(f"{label} is not canonical JSON")
    return value


def _require_rfc3339_utc(value: object, *, field_name: str) -> str:
    if type(value) is not str or _RFC3339_UTC_RE.fullmatch(value) is None:
        raise GitHubPullRequestReviewAdmissionError(f"{field_name} must be strict UTC RFC3339")
    base = value[:-1]
    if "." in base:
        whole, fraction = base.split(".", maxsplit=1)
        parse_value = f"{whole}.{fraction[:6].ljust(6, '0')}"
        parse_format = "%Y-%m-%dT%H:%M:%S.%f"
    else:
        parse_value = base
        parse_format = "%Y-%m-%dT%H:%M:%S"
    try:
        datetime.strptime(parse_value, parse_format).replace(tzinfo=UTC)
    except ValueError:
        raise GitHubPullRequestReviewAdmissionError(
            f"{field_name} must be strict UTC RFC3339"
        ) from None
    return value


def _rfc3339_order_key(value: object, *, field_name: str) -> tuple[datetime, str]:
    checked = _require_rfc3339_utc(value, field_name=field_name)
    base = checked[:-1]
    if "." in base:
        whole, fraction = base.split(".", maxsplit=1)
    else:
        whole, fraction = base, ""
    instant = datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return instant, fraction.ljust(9, "0")


def _now_rfc3339() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CallerClaimedGitHubRepositoryV1:
    """Caller-claimed canonical identity for one GitHub repository/base."""

    repository_id: int
    repository_node_id: str
    owner_id: int
    owner_node_id: str
    owner_login: str
    name: str
    full_name: str
    base_ref: str

    def __post_init__(self) -> None:
        _require_positive_int(self.repository_id, field_name="repository_id")
        _require_ascii_match(
            self.repository_node_id,
            field_name="repository_node_id",
            pattern=_NODE_ID_RE,
        )
        _require_positive_int(self.owner_id, field_name="owner_id")
        _require_ascii_match(self.owner_node_id, field_name="owner_node_id", pattern=_NODE_ID_RE)
        owner = _require_ascii_match(self.owner_login, field_name="owner_login", pattern=_OWNER_RE)
        name = _require_ascii_match(self.name, field_name="repository name", pattern=_REPOSITORY_RE)
        if self.full_name != f"{owner}/{name}":
            raise GitHubPullRequestReviewAdmissionError(
                "repository full_name differs from canonical owner/name"
            )
        _require_ascii_match(self.base_ref, field_name="base_ref", pattern=_REF_RE)

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_id": self.repository_id,
            "repository_node_id": self.repository_node_id,
            "owner_id": self.owner_id,
            "owner_node_id": self.owner_node_id,
            "owner_login": self.owner_login,
            "name": self.name,
            "full_name": self.full_name,
            "base_ref": self.base_ref,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="caller-claimed repository policy")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "repository_id",
                    "repository_node_id",
                    "owner_id",
                    "owner_node_id",
                    "owner_login",
                    "name",
                    "full_name",
                    "base_ref",
                }
            ),
            label="caller-claimed repository policy",
        )
        return cls(
            repository_id=cast("int", payload["repository_id"]),
            repository_node_id=cast("str", payload["repository_node_id"]),
            owner_id=cast("int", payload["owner_id"]),
            owner_node_id=cast("str", payload["owner_node_id"]),
            owner_login=cast("str", payload["owner_login"]),
            name=cast("str", payload["name"]),
            full_name=cast("str", payload["full_name"]),
            base_ref=cast("str", payload["base_ref"]),
        )


@dataclass(frozen=True, slots=True)
class CallerClaimedGitHubReviewerV1:
    """Caller-claimed canonical identity and policy for one reviewer."""

    reviewer_id: int
    reviewer_node_id: str
    login: str
    user_type: ReviewerUserType
    role: ReviewerRole
    bot_policy: ReviewerBotPolicy = "human_only"

    def __post_init__(self) -> None:
        _require_positive_int(self.reviewer_id, field_name="reviewer_id")
        _require_ascii_match(
            self.reviewer_node_id,
            field_name="reviewer_node_id",
            pattern=_NODE_ID_RE,
        )
        _require_ascii_match(self.login, field_name="reviewer login", pattern=_LOGIN_RE)
        if type(self.user_type) is not str or self.user_type not in {"User", "Bot"}:
            raise GitHubPullRequestReviewAdmissionError("reviewer user_type is unsupported")
        if type(self.role) is not str or self.role not in {"owner", "maintainer", "member"}:
            raise GitHubPullRequestReviewAdmissionError("reviewer role is unsupported")
        if type(self.bot_policy) is not str or self.bot_policy not in {"human_only", "allow_bot"}:
            raise GitHubPullRequestReviewAdmissionError("reviewer bot policy is unsupported")
        if self.user_type == "Bot" and self.bot_policy != "allow_bot":
            raise GitHubPullRequestReviewAdmissionError(
                "caller-claimed reviewer bot identity is forbidden by policy"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "reviewer_id": self.reviewer_id,
            "reviewer_node_id": self.reviewer_node_id,
            "login": self.login,
            "user_type": self.user_type,
            "role": self.role,
            "bot_policy": self.bot_policy,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="caller-claimed reviewer policy")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "reviewer_id",
                    "reviewer_node_id",
                    "login",
                    "user_type",
                    "role",
                    "bot_policy",
                }
            ),
            label="caller-claimed reviewer policy",
        )
        return cls(
            reviewer_id=cast("int", payload["reviewer_id"]),
            reviewer_node_id=cast("str", payload["reviewer_node_id"]),
            login=cast("str", payload["login"]),
            user_type=cast("ReviewerUserType", payload["user_type"]),
            role=cast("ReviewerRole", payload["role"]),
            bot_policy=cast("ReviewerBotPolicy", payload["bot_policy"]),
        )


@dataclass(frozen=True, slots=True)
class CallerClaimedGitHubReviewPolicyV1:
    """Canonical caller claim; never a protected or independent trust root."""

    repository: CallerClaimedGitHubRepositoryV1
    reviewer: CallerClaimedGitHubReviewerV1

    schema_version: ClassVar[int] = GITHUB_PULL_REQUEST_REVIEW_ADMISSION_SCHEMA_VERSION
    kind: ClassVar[str] = "caller_claimed_github_review_policy_v1"
    trust_class: ClassVar[str] = "caller_supplied_untrusted"

    def __post_init__(self) -> None:
        if type(self.repository) is not CallerClaimedGitHubRepositoryV1:
            raise GitHubPullRequestReviewAdmissionError("caller-claimed repository is foreign")
        if type(self.reviewer) is not CallerClaimedGitHubReviewerV1:
            raise GitHubPullRequestReviewAdmissionError("caller-claimed reviewer is foreign")

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "trust_class": self.trust_class,
            "repository": self.repository.to_dict(),
            "reviewer": self.reviewer.to_dict(),
        }

    @property
    def claimed_policy_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "claimed_policy_sha256": _sha256(content)}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        payload = _require_mapping(
            _decode_json(
                raw,
                label="caller-claimed GitHub review policy",
                maximum_bytes=_MAX_CALLER_POLICY_BYTES,
                require_canonical=True,
            ),
            label="caller-claimed GitHub review policy",
        )
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "trust_class",
                    "repository",
                    "reviewer",
                    "claimed_policy_sha256",
                }
            ),
            label="caller-claimed GitHub review policy",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or payload["trust_class"] != cls.trust_class
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "caller-claimed GitHub review policy schema is unsupported"
            )
        result = cls(
            repository=CallerClaimedGitHubRepositoryV1.from_dict(payload["repository"]),
            reviewer=CallerClaimedGitHubReviewerV1.from_dict(payload["reviewer"]),
        )
        if payload != result.to_dict():
            raise GitHubPullRequestReviewAdmissionError(
                "caller-claimed GitHub review policy differs from exact reconstruction"
            )
        return result


@dataclass(frozen=True, slots=True)
class ExternalReviewResultBundleEntryV1:
    """One external result payload bound to one exact red W0 result slot."""

    candidate_id: str
    topological_depth: int
    result_slot_sha256: str
    candidate_sha256: str
    candidate_structural_sha256: str
    draft_semantic_sha256: str
    pending_review_identity_sha256: str
    review_input_sha256: str
    required_review_input_sha256s: tuple[str, ...]
    payload: Mapping[str, object]
    payload_sha256: str

    schema_version: ClassVar[int] = GITHUB_PULL_REQUEST_REVIEW_ADMISSION_SCHEMA_VERSION
    kind: ClassVar[str] = "external_review_result_bundle_entry_v1"

    def __post_init__(self) -> None:
        _require_ascii_match(self.candidate_id, field_name="candidate_id", pattern=_SAFE_ID_RE)
        _require_bounded_int(
            self.topological_depth,
            field_name="topological_depth",
            minimum=0,
            maximum=1024,
        )
        for field_name in (
            "result_slot_sha256",
            "candidate_sha256",
            "candidate_structural_sha256",
            "draft_semantic_sha256",
            "pending_review_identity_sha256",
            "review_input_sha256",
            "payload_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if (
            type(self.required_review_input_sha256s) is not tuple
            or not self.required_review_input_sha256s
            or self.required_review_input_sha256s
            != tuple(sorted(set(self.required_review_input_sha256s)))
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "required review inputs must be nonempty, sorted, and unique"
            )
        for digest in self.required_review_input_sha256s:
            _require_sha256(digest, field_name="required_review_input_sha256s")
        if type(self.payload) is not dict:
            raise GitHubPullRequestReviewAdmissionError("external result payload must be an object")
        _validate_json_tree(
            self.payload,
            label="external result payload",
            maximum_nodes=_MAX_PAYLOAD_NODES,
        )
        if _sha256(self.payload) != self.payload_sha256:
            raise GitHubPullRequestReviewAdmissionError(
                "external result payload differs from its digest"
            )

    @classmethod
    def for_slot(
        cls,
        *,
        slot: StableModelReviewResultSlotV1,
        payload: Mapping[str, object],
    ) -> Self:
        if type(slot) is not StableModelReviewResultSlotV1:
            raise GitHubPullRequestReviewAdmissionError("external result slot is foreign")
        if type(payload) is not dict:
            raise GitHubPullRequestReviewAdmissionError("external result payload must be an object")
        return cls(
            candidate_id=slot.candidate_id,
            topological_depth=slot.topological_depth,
            result_slot_sha256=slot.result_slot_sha256,
            candidate_sha256=slot.candidate_sha256,
            candidate_structural_sha256=slot.candidate_structural_sha256,
            draft_semantic_sha256=slot.draft_semantic_sha256,
            pending_review_identity_sha256=slot.pending_review_identity_sha256,
            review_input_sha256=slot.review_input_sha256,
            required_review_input_sha256s=slot.required_review_input_sha256s,
            payload=dict(payload),
            payload_sha256=_sha256(payload),
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "candidate_id": self.candidate_id,
            "topological_depth": self.topological_depth,
            "result_slot_sha256": self.result_slot_sha256,
            "candidate_sha256": self.candidate_sha256,
            "candidate_structural_sha256": self.candidate_structural_sha256,
            "draft_semantic_sha256": self.draft_semantic_sha256,
            "pending_review_identity_sha256": self.pending_review_identity_sha256,
            "review_input_sha256": self.review_input_sha256,
            "required_review_input_sha256s": list(self.required_review_input_sha256s),
            "payload": dict(self.payload),
            "payload_sha256": self.payload_sha256,
        }

    @property
    def entry_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "entry_sha256": _sha256(content)}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="external result entry")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "candidate_id",
                    "topological_depth",
                    "result_slot_sha256",
                    "candidate_sha256",
                    "candidate_structural_sha256",
                    "draft_semantic_sha256",
                    "pending_review_identity_sha256",
                    "review_input_sha256",
                    "required_review_input_sha256s",
                    "payload",
                    "payload_sha256",
                    "entry_sha256",
                }
            ),
            label="external result entry",
        )
        required = payload["required_review_input_sha256s"]
        if (
            payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(required) is not list
        ):
            raise GitHubPullRequestReviewAdmissionError("external result entry schema is invalid")
        result = cls(
            candidate_id=cast("str", payload["candidate_id"]),
            topological_depth=cast("int", payload["topological_depth"]),
            result_slot_sha256=cast("str", payload["result_slot_sha256"]),
            candidate_sha256=cast("str", payload["candidate_sha256"]),
            candidate_structural_sha256=cast("str", payload["candidate_structural_sha256"]),
            draft_semantic_sha256=cast("str", payload["draft_semantic_sha256"]),
            pending_review_identity_sha256=cast("str", payload["pending_review_identity_sha256"]),
            review_input_sha256=cast("str", payload["review_input_sha256"]),
            required_review_input_sha256s=tuple(cast("list[str]", required)),
            payload=_require_mapping(payload["payload"], label="external result payload"),
            payload_sha256=cast("str", payload["payload_sha256"]),
        )
        if payload != result.to_dict():
            raise GitHubPullRequestReviewAdmissionError(
                "external result entry differs from exact reconstruction"
            )
        return result


@dataclass(frozen=True, slots=True)
class ExternalReviewResultBundleV1:
    """Canonical exact-union commitment for all result slots in one W0 shard."""

    source_sha: str
    work_packet_sha256: str
    challenge_sha256: str
    shard_id: str
    shard_sha256: str
    candidate_id_inventory_sha256: str
    result_slot_inventory_sha256: str
    entries: tuple[ExternalReviewResultBundleEntryV1, ...]

    schema_version: ClassVar[int] = GITHUB_PULL_REQUEST_REVIEW_ADMISSION_SCHEMA_VERSION
    kind: ClassVar[str] = "external_review_result_bundle_v1"

    def __post_init__(self) -> None:
        _require_git_sha(self.source_sha, field_name="result bundle source_sha")
        for field_name in (
            "work_packet_sha256",
            "challenge_sha256",
            "shard_sha256",
            "candidate_id_inventory_sha256",
            "result_slot_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_ascii_match(self.shard_id, field_name="shard_id", pattern=_SAFE_ID_RE)
        if (
            type(self.entries) is not tuple
            or not self.entries
            or any(type(item) is not ExternalReviewResultBundleEntryV1 for item in self.entries)
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "result bundle entries are empty or foreign"
            )
        if self.entries != tuple(sorted(self.entries, key=lambda item: item.candidate_id)):
            raise GitHubPullRequestReviewAdmissionError("result bundle entries are not sorted")
        if len({item.candidate_id for item in self.entries}) != len(self.entries):
            raise GitHubPullRequestReviewAdmissionError("result bundle entries are duplicated")

    @property
    def entry_inventory_sha256(self) -> str:
        return _sha256([item.to_dict() for item in self.entries])

    @property
    def payload_inventory_sha256(self) -> str:
        return _sha256(
            [
                {"candidate_id": item.candidate_id, "payload_sha256": item.payload_sha256}
                for item in self.entries
            ]
        )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "work_packet_sha256": self.work_packet_sha256,
            "challenge_sha256": self.challenge_sha256,
            "shard_id": self.shard_id,
            "shard_sha256": self.shard_sha256,
            "candidate_count": len(self.entries),
            "candidate_id_inventory_sha256": self.candidate_id_inventory_sha256,
            "result_slot_inventory_sha256": self.result_slot_inventory_sha256,
            "entry_inventory_sha256": self.entry_inventory_sha256,
            "payload_inventory_sha256": self.payload_inventory_sha256,
            "entries": [item.to_dict() for item in self.entries],
        }

    @property
    def result_bundle_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "result_bundle_sha256": _sha256(content)}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def bind_to_w0(
        self,
        *,
        shard: StableModelReviewShardV1,
        challenge: StableModelReviewChallengeV1,
    ) -> None:
        _bind_shard_and_challenge(shard=shard, challenge=challenge)
        exact_bundle = (
            self.source_sha == shard.source_sha == challenge.source_sha
            and self.work_packet_sha256 == challenge.work_packet_sha256
            and self.challenge_sha256 == challenge.challenge_sha256
            and self.shard_id == shard.shard_id == challenge.shard_id
            and self.shard_sha256 == shard.shard_sha256 == challenge.shard_sha256
            and self.candidate_id_inventory_sha256
            == shard.candidate_id_inventory_sha256
            == challenge.candidate_id_inventory_sha256
            and self.result_slot_inventory_sha256
            == shard.result_slot_inventory_sha256
            == challenge.result_slot_inventory_sha256
            and len(self.entries) == len(shard.result_slots) == challenge.candidate_count
        )
        if not exact_bundle:
            raise GitHubPullRequestReviewAdmissionError(
                "external result bundle differs from the exact W0 shard/challenge"
            )
        if tuple(item.candidate_id for item in self.entries) != shard.candidate_ids:
            raise GitHubPullRequestReviewAdmissionError(
                "external result bundle candidate union differs from W0"
            )
        for entry, slot in zip(self.entries, shard.result_slots, strict=True):
            if _sha256(entry.payload) != entry.payload_sha256:
                raise GitHubPullRequestReviewAdmissionError(
                    "external result payload changed after commitment"
                )
            if not _entry_matches_slot(entry, slot):
                raise GitHubPullRequestReviewAdmissionError(
                    "external result entry differs from its exact W0 slot"
                )

    @classmethod
    def from_canonical_bytes(
        cls,
        raw: bytes,
        *,
        shard: StableModelReviewShardV1,
        challenge: StableModelReviewChallengeV1,
    ) -> Self:
        payload = _require_mapping(
            _decode_json(
                raw,
                label="external result bundle",
                maximum_bytes=_MAX_RESULT_BUNDLE_BYTES,
                require_canonical=True,
            ),
            label="external result bundle",
        )
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "source_sha",
                    "work_packet_sha256",
                    "challenge_sha256",
                    "shard_id",
                    "shard_sha256",
                    "candidate_count",
                    "candidate_id_inventory_sha256",
                    "result_slot_inventory_sha256",
                    "entry_inventory_sha256",
                    "payload_inventory_sha256",
                    "entries",
                    "result_bundle_sha256",
                }
            ),
            label="external result bundle",
        )
        entries = payload["entries"]
        if (
            payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(entries) is not list
            or type(payload["candidate_count"]) is not int
        ):
            raise GitHubPullRequestReviewAdmissionError("external result bundle schema is invalid")
        result = cls(
            source_sha=cast("str", payload["source_sha"]),
            work_packet_sha256=cast("str", payload["work_packet_sha256"]),
            challenge_sha256=cast("str", payload["challenge_sha256"]),
            shard_id=cast("str", payload["shard_id"]),
            shard_sha256=cast("str", payload["shard_sha256"]),
            candidate_id_inventory_sha256=cast("str", payload["candidate_id_inventory_sha256"]),
            result_slot_inventory_sha256=cast("str", payload["result_slot_inventory_sha256"]),
            entries=tuple(
                ExternalReviewResultBundleEntryV1.from_dict(item)
                for item in cast("list[object]", entries)
            ),
        )
        if payload != result.to_dict():
            raise GitHubPullRequestReviewAdmissionError(
                "external result bundle differs from exact reconstruction"
            )
        result.bind_to_w0(shard=shard, challenge=challenge)
        return result


def _entry_matches_slot(
    entry: ExternalReviewResultBundleEntryV1,
    slot: StableModelReviewResultSlotV1,
) -> bool:
    return (
        entry.candidate_id == slot.candidate_id
        and entry.topological_depth == slot.topological_depth
        and entry.result_slot_sha256 == slot.result_slot_sha256
        and entry.candidate_sha256 == slot.candidate_sha256
        and entry.candidate_structural_sha256 == slot.candidate_structural_sha256
        and entry.draft_semantic_sha256 == slot.draft_semantic_sha256
        and entry.pending_review_identity_sha256 == slot.pending_review_identity_sha256
        and entry.review_input_sha256 == slot.review_input_sha256
        and entry.required_review_input_sha256s == slot.required_review_input_sha256s
    )


def _bind_shard_and_challenge(
    *,
    shard: StableModelReviewShardV1,
    challenge: StableModelReviewChallengeV1,
) -> None:
    if (
        type(shard) is not StableModelReviewShardV1
        or type(challenge) is not StableModelReviewChallengeV1
    ):
        raise GitHubPullRequestReviewAdmissionError("W0 shard or challenge is foreign")
    if (
        challenge.source_sha != shard.source_sha
        or challenge.shard_id != shard.shard_id
        or challenge.shard_sha256 != shard.shard_sha256
        or challenge.candidate_id_inventory_sha256 != shard.candidate_id_inventory_sha256
        or challenge.result_slot_inventory_sha256 != shard.result_slot_inventory_sha256
        or challenge.candidate_count != len(shard.result_slots)
        or challenge.authority_admitted is not False
    ):
        raise GitHubPullRequestReviewAdmissionError("W0 shard/challenge join is inconsistent")


def build_external_review_result_bundle(
    *,
    shard: StableModelReviewShardV1,
    challenge: StableModelReviewChallengeV1,
    payloads_by_candidate_id: Mapping[str, Mapping[str, object]],
) -> ExternalReviewResultBundleV1:
    """Build one canonical bundle from an exact-once external payload union."""

    _bind_shard_and_challenge(shard=shard, challenge=challenge)
    if type(payloads_by_candidate_id) is not dict:
        raise GitHubPullRequestReviewAdmissionError("result payload map must be an exact object")
    if any(
        type(key) is not str or type(value) is not dict
        for key, value in payloads_by_candidate_id.items()
    ):
        raise GitHubPullRequestReviewAdmissionError("result payload map contains foreign entries")
    if frozenset(payloads_by_candidate_id) != frozenset(shard.candidate_ids):
        raise GitHubPullRequestReviewAdmissionError(
            "result payload map differs from the exact W0 candidate union"
        )
    result = ExternalReviewResultBundleV1(
        source_sha=shard.source_sha,
        work_packet_sha256=challenge.work_packet_sha256,
        challenge_sha256=challenge.challenge_sha256,
        shard_id=shard.shard_id,
        shard_sha256=shard.shard_sha256,
        candidate_id_inventory_sha256=shard.candidate_id_inventory_sha256,
        result_slot_inventory_sha256=shard.result_slot_inventory_sha256,
        entries=tuple(
            ExternalReviewResultBundleEntryV1.for_slot(
                slot=slot,
                payload=payloads_by_candidate_id[slot.candidate_id],
            )
            for slot in shard.result_slots
        ),
    )
    result.bind_to_w0(shard=shard, challenge=challenge)
    return result


def build_caller_claimed_review_submission_body(
    *,
    policy: CallerClaimedGitHubReviewPolicyV1,
    pull_number: int,
    shard: StableModelReviewShardV1,
    challenge: StableModelReviewChallengeV1,
    result_bundle: ExternalReviewResultBundleV1,
) -> str:
    """Build the exact ASCII body for one caller-claimed review policy."""

    if type(policy) is not CallerClaimedGitHubReviewPolicyV1:
        raise GitHubPullRequestReviewAdmissionError("caller-claimed review policy is foreign")
    pull = _require_positive_int(pull_number, field_name="pull_number")
    result_bundle.bind_to_w0(shard=shard, challenge=challenge)
    repo = policy.repository
    reviewer = policy.reviewer
    lines = (
        "NBADB-STABLE-MODEL-REVIEW-V1",
        f"trust_class:{policy.trust_class}",
        f"claimed_policy_sha256:{policy.claimed_policy_sha256}",
        f"repository_id:{repo.repository_id}",
        f"repository_node_id:{repo.repository_node_id}",
        f"repository_full_name:{repo.full_name}",
        f"repository_base_ref:{repo.base_ref}",
        f"pull_number:{pull}",
        f"source_sha:{shard.source_sha}",
        f"reviewer_id:{reviewer.reviewer_id}",
        f"reviewer_node_id:{reviewer.reviewer_node_id}",
        f"reviewer_login:{reviewer.login}",
        f"reviewer_type:{reviewer.user_type}",
        f"reviewer_role:{reviewer.role}",
        f"reviewer_bot_policy:{reviewer.bot_policy}",
        f"work_packet_sha256:{challenge.work_packet_sha256}",
        f"challenge_sha256:{challenge.challenge_sha256}",
        f"shard_id:{shard.shard_id}",
        f"shard_sha256:{shard.shard_sha256}",
        f"result_bundle_sha256:{result_bundle.result_bundle_sha256}",
        f"candidate_count:{len(result_bundle.entries)}",
        f"candidate_id_inventory_sha256:{shard.candidate_id_inventory_sha256}",
        f"result_slot_inventory_sha256:{shard.result_slot_inventory_sha256}",
        f"result_entry_inventory_sha256:{result_bundle.entry_inventory_sha256}",
        f"result_payload_inventory_sha256:{result_bundle.payload_inventory_sha256}",
    )
    body = "\n".join(lines)
    try:
        encoded = body.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise GitHubPullRequestReviewAdmissionError(
            "review submission body contains non-ASCII data"
        ) from None
    if encoded.decode("ascii") != body or "```" in body or body.endswith((" ", "\n")):
        raise GitHubPullRequestReviewAdmissionError(
            "review submission body is not exact canonical ASCII"
        )
    return body


@dataclass(frozen=True, slots=True)
class _RawGitHubRead:
    requested_url: str
    final_url: str
    status_code: int
    raw_body: bytes
    etag: str | None
    request_id: str | None
    observed_at: str


def _validate_exact_github_url(url: str, *, expected_url: str) -> None:
    if type(url) is not str or url != expected_url:
        raise GitHubPullRequestReviewAdmissionError("GitHub response URL differs from request")
    try:
        split = urlsplit(url)
        explicit_port = split.port
    except ValueError:
        raise GitHubPullRequestReviewAdmissionError(
            "GitHub URL is not exact fixed-host HTTPS"
        ) from None
    if (
        split.scheme != "https"
        or split.netloc != _GITHUB_API_HOST
        or split.hostname != _GITHUB_API_HOST
        or explicit_port is not None
        or split.username is not None
        or split.password is not None
        or split.query
        or split.fragment
        or not split.path.startswith("/repos/")
    ):
        raise GitHubPullRequestReviewAdmissionError("GitHub URL is not exact fixed-host HTTPS")


def _https_get(url: str, *, token: str, maximum_bytes: int) -> _RawGitHubRead:
    """Private fixed-host HTTPS GET.  It never follows redirects or consults proxies."""

    _validate_exact_github_url(url, expected_url=url)
    if (
        type(token) is not str
        or not 1 <= len(token) <= 4096
        or token.strip() != token
        or any(character in token for character in "\r\n\0")
    ):
        raise GitHubPullRequestReviewAdmissionError("GitHub bearer token is invalid")
    if type(maximum_bytes) is not int or maximum_bytes <= 0:
        raise GitHubPullRequestReviewAdmissionError("GitHub response size bound is invalid")
    path = urlsplit(url).path
    context = ssl.create_default_context()
    connection: http.client.HTTPSConnection | None = None
    try:
        connection = http.client.HTTPSConnection(
            _GITHUB_API_HOST,
            port=443,
            timeout=_HTTPS_TIMEOUT_SECONDS,
            context=context,
        )
        connection.request(
            "GET",
            path,
            headers={
                "Accept": _GITHUB_ACCEPT,
                "X-GitHub-Api-Version": _GITHUB_API_VERSION,
                "Accept-Encoding": "identity",
                "User-Agent": _USER_AGENT,
                "Authorization": f"Bearer {token}",
            },
        )
        response = connection.getresponse()
        status = response.status
        if status != 200:
            raise GitHubPullRequestReviewAdmissionError("GitHub returned a non-200 response")
        content_encoding = response.getheader("Content-Encoding")
        if content_encoding not in {None, "", "identity"}:
            raise GitHubPullRequestReviewAdmissionError(
                "GitHub response used an unsupported content encoding"
            )
        raw = response.read(maximum_bytes + 1)
        if not raw or len(raw) > maximum_bytes:
            raise GitHubPullRequestReviewAdmissionError(
                "GitHub response size is outside its exact bounds"
            )
        return _RawGitHubRead(
            requested_url=url,
            final_url=url,
            status_code=status,
            raw_body=raw,
            etag=response.getheader("ETag"),
            request_id=response.getheader("X-GitHub-Request-Id"),
            observed_at=_now_rfc3339(),
        )
    except GitHubPullRequestReviewAdmissionError:
        raise
    except (TimeoutError, ssl.SSLError, socket.gaierror, OSError, http.client.HTTPException):
        raise GitHubPullRequestReviewAdmissionError(
            "GitHub transport failed before an authenticated observation"
        ) from None
    finally:
        if connection is not None:
            with suppress(OSError):
                connection.close()


@dataclass(frozen=True, slots=True)
class _GitHubUserProjectionV1:
    user_id: int
    node_id: str
    login: str
    user_type: str

    def to_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "node_id": self.node_id,
            "login": self.login,
            "user_type": self.user_type,
        }


@dataclass(frozen=True, slots=True)
class _GitHubRepositoryProjectionV1:
    repository_id: int
    node_id: str
    name: str
    full_name: str
    owner: _GitHubUserProjectionV1

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_id": self.repository_id,
            "node_id": self.node_id,
            "name": self.name,
            "full_name": self.full_name,
            "owner": self.owner.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _GitHubPullRequestProjectionV1:
    number: int
    node_id: str
    api_url: str
    html_url: str
    state: str
    merged: bool
    merged_at: str | None
    author: _GitHubUserProjectionV1
    base_ref: str
    base_repository: _GitHubRepositoryProjectionV1
    head_ref: str
    head_sha: str
    head_repository: _GitHubRepositoryProjectionV1

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "node_id": self.node_id,
            "api_url": self.api_url,
            "html_url": self.html_url,
            "state": self.state,
            "merged": self.merged,
            "merged_at": self.merged_at,
            "author": self.author.to_dict(),
            "base_ref": self.base_ref,
            "base_repository": self.base_repository.to_dict(),
            "head_ref": self.head_ref,
            "head_sha": self.head_sha,
            "head_repository": self.head_repository.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _GitHubReviewProjectionV1:
    review_id: int
    reviewer: _GitHubUserProjectionV1
    body: str
    state: str
    html_url: str
    pull_request_url: str
    submitted_at: str
    commit_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "reviewer": self.reviewer.to_dict(),
            "body": self.body,
            "state": self.state,
            "html_url": self.html_url,
            "pull_request_url": self.pull_request_url,
            "submitted_at": self.submitted_at,
            "commit_id": self.commit_id,
        }


def _parse_user(value: object, *, label: str) -> _GitHubUserProjectionV1:
    payload = _require_mapping(value, label=label)
    user_type = _require_field(payload, "type", label=label)
    if type(user_type) is not str or user_type not in {"User", "Bot"}:
        raise GitHubPullRequestReviewAdmissionError(f"{label} has an unsupported user type")
    return _GitHubUserProjectionV1(
        user_id=_require_positive_int(
            _require_field(payload, "id", label=label),
            field_name=f"{label} id",
        ),
        node_id=_require_ascii_match(
            _require_field(payload, "node_id", label=label),
            field_name=f"{label} node_id",
            pattern=_NODE_ID_RE,
        ),
        login=_require_ascii_match(
            _require_field(payload, "login", label=label),
            field_name=f"{label} login",
            pattern=_LOGIN_RE,
        ),
        user_type=user_type,
    )


def _parse_repository(value: object, *, label: str) -> _GitHubRepositoryProjectionV1:
    payload = _require_mapping(value, label=label)
    return _GitHubRepositoryProjectionV1(
        repository_id=_require_positive_int(
            _require_field(payload, "id", label=label), field_name=f"{label} id"
        ),
        node_id=_require_ascii_match(
            _require_field(payload, "node_id", label=label),
            field_name=f"{label} node_id",
            pattern=_NODE_ID_RE,
        ),
        name=_require_ascii_match(
            _require_field(payload, "name", label=label),
            field_name=f"{label} name",
            pattern=_REPOSITORY_RE,
        ),
        full_name=_require_ascii_match(
            _require_field(payload, "full_name", label=label),
            field_name=f"{label} full_name",
            pattern=re.compile(r"[a-z0-9-]{1,39}/[a-z0-9._-]{1,100}\Z", flags=re.ASCII),
        ),
        owner=_parse_user(_require_field(payload, "owner", label=label), label=f"{label} owner"),
    )


def _parse_pull_request(raw: bytes) -> _GitHubPullRequestProjectionV1:
    payload = _require_mapping(
        _decode_json(
            raw,
            label="GitHub pull request",
            maximum_bytes=_MAX_PULL_REQUEST_BYTES,
            require_canonical=False,
        ),
        label="GitHub pull request",
    )
    base = _require_mapping(
        _require_field(payload, "base", label="GitHub pull request"),
        label="pull request base",
    )
    head = _require_mapping(
        _require_field(payload, "head", label="GitHub pull request"),
        label="pull request head",
    )
    merged_at = _require_field(payload, "merged_at", label="GitHub pull request")
    if merged_at is not None and type(merged_at) is not str:
        raise GitHubPullRequestReviewAdmissionError("pull request merged_at has an invalid type")
    state = _require_field(payload, "state", label="GitHub pull request")
    merged = _require_field(payload, "merged", label="GitHub pull request")
    if type(state) is not str or type(merged) is not bool:
        raise GitHubPullRequestReviewAdmissionError("pull request state is invalid")
    return _GitHubPullRequestProjectionV1(
        number=_require_positive_int(
            _require_field(payload, "number", label="GitHub pull request"),
            field_name="pull request number",
        ),
        node_id=_require_ascii_match(
            _require_field(payload, "node_id", label="GitHub pull request"),
            field_name="pull request node_id",
            pattern=_NODE_ID_RE,
        ),
        api_url=cast("str", _require_field(payload, "url", label="GitHub pull request")),
        html_url=cast("str", _require_field(payload, "html_url", label="GitHub pull request")),
        state=state,
        merged=merged,
        merged_at=merged_at,
        author=_parse_user(
            _require_field(payload, "user", label="GitHub pull request"),
            label="pull request author",
        ),
        base_ref=_require_ascii_match(
            _require_field(base, "ref", label="pull request base"),
            field_name="pull request base ref",
            pattern=_REF_RE,
        ),
        base_repository=_parse_repository(
            _require_field(base, "repo", label="pull request base"),
            label="pull request base repository",
        ),
        head_ref=_require_ascii_match(
            _require_field(head, "ref", label="pull request head"),
            field_name="pull request head ref",
            pattern=_REF_RE,
        ),
        head_sha=_require_git_sha(
            _require_field(head, "sha", label="pull request head"),
            field_name="pull request head SHA",
        ),
        head_repository=_parse_repository(
            _require_field(head, "repo", label="pull request head"),
            label="pull request head repository",
        ),
    )


def _parse_review(raw: bytes) -> _GitHubReviewProjectionV1:
    payload = _require_mapping(
        _decode_json(
            raw,
            label="GitHub pull request review",
            maximum_bytes=_MAX_REVIEW_BYTES,
            require_canonical=False,
        ),
        label="GitHub pull request review",
    )
    body = _require_field(payload, "body", label="GitHub pull request review")
    state = _require_field(payload, "state", label="GitHub pull request review")
    html_url = _require_field(payload, "html_url", label="GitHub pull request review")
    pull_request_url = _require_field(
        payload, "pull_request_url", label="GitHub pull request review"
    )
    if any(type(item) is not str for item in (body, state, html_url, pull_request_url)):
        raise GitHubPullRequestReviewAdmissionError("GitHub review string projection is invalid")
    return _GitHubReviewProjectionV1(
        review_id=_require_positive_int(
            _require_field(payload, "id", label="GitHub pull request review"),
            field_name="review id",
        ),
        reviewer=_parse_user(
            _require_field(payload, "user", label="GitHub pull request review"),
            label="reviewer",
        ),
        body=cast("str", body),
        state=cast("str", state),
        html_url=cast("str", html_url),
        pull_request_url=cast("str", pull_request_url),
        submitted_at=_require_rfc3339_utc(
            _require_field(payload, "submitted_at", label="GitHub pull request review"),
            field_name="review submitted_at",
        ),
        commit_id=_require_git_sha(
            _require_field(payload, "commit_id", label="GitHub pull request review"),
            field_name="review commit_id",
        ),
    )


def _validate_repository_projection(
    projection: _GitHubRepositoryProjectionV1,
    *,
    policy: CallerClaimedGitHubRepositoryV1,
) -> None:
    if (
        projection.repository_id != policy.repository_id
        or projection.node_id != policy.repository_node_id
        or projection.name != policy.name
        or projection.full_name != policy.full_name
        or projection.owner.user_id != policy.owner_id
        or projection.owner.node_id != policy.owner_node_id
        or projection.owner.login != policy.owner_login
    ):
        raise GitHubPullRequestReviewAdmissionError(
            "GitHub repository projection differs from caller-claimed policy"
        )


def _validate_projections(
    *,
    pull: _GitHubPullRequestProjectionV1,
    review: _GitHubReviewProjectionV1,
    policy: CallerClaimedGitHubReviewPolicyV1,
    pull_number: int,
    review_id: int,
    expected_source_sha: str,
    expected_body: str,
) -> None:
    repo = policy.repository
    reviewer = policy.reviewer
    expected_pr_api = f"https://api.github.com/repos/{repo.full_name}/pulls/{pull_number}"
    expected_pr_html = f"https://github.com/{repo.full_name}/pull/{pull_number}"
    expected_review_html = f"{expected_pr_html}#pullrequestreview-{review_id}"
    if (
        pull.number != pull_number
        or pull.api_url != expected_pr_api
        or pull.html_url != expected_pr_html
    ):
        raise GitHubPullRequestReviewAdmissionError("pull request identity or URL is rebound")
    if pull.state != "open" or pull.merged or pull.merged_at is not None:
        raise GitHubPullRequestReviewAdmissionError("pull request is not open and unmerged")
    _validate_repository_projection(pull.base_repository, policy=repo)
    _validate_repository_projection(pull.head_repository, policy=repo)
    if pull.base_ref != repo.base_ref:
        raise GitHubPullRequestReviewAdmissionError(
            "pull request base ref differs from caller-claimed policy"
        )
    if pull.head_repository != pull.base_repository:
        raise GitHubPullRequestReviewAdmissionError("fork pull requests are not admissible")
    if pull.head_sha != expected_source_sha or review.commit_id != expected_source_sha:
        raise GitHubPullRequestReviewAdmissionError("pull/review source SHA differs from W0")
    if review.review_id != review_id:
        raise GitHubPullRequestReviewAdmissionError("GitHub review id is rebound")
    if review.pull_request_url != expected_pr_api or review.html_url != expected_review_html:
        raise GitHubPullRequestReviewAdmissionError("GitHub review URL is rebound")
    if (
        review.reviewer.user_id != reviewer.reviewer_id
        or review.reviewer.node_id != reviewer.reviewer_node_id
        or review.reviewer.login != reviewer.login
        or review.reviewer.user_type != reviewer.user_type
    ):
        raise GitHubPullRequestReviewAdmissionError(
            "GitHub reviewer differs from caller-claimed policy"
        )
    if (
        review.reviewer.user_id == pull.author.user_id
        or review.reviewer.node_id == pull.author.node_id
    ):
        raise GitHubPullRequestReviewAdmissionError("self-authored review is forbidden")
    if review.state not in _ALLOWED_REVIEW_STATES:
        raise GitHubPullRequestReviewAdmissionError("GitHub review state is not submitted")
    if review.body.encode("utf-8") != expected_body.encode("ascii"):
        raise GitHubPullRequestReviewAdmissionError(
            "GitHub review body differs from the local canonical commitment"
        )


@dataclass(frozen=True, slots=True)
class GitHubApiReadReceiptV1:
    """One typed, point-in-time API read in the fixed stabilization sequence."""

    read_ordinal: int
    read_label: str
    requested_url: str
    raw_sha256: str
    projection_sha256: str
    etag: str | None
    request_id: str | None
    observed_at: str

    schema_version: ClassVar[int] = GITHUB_PULL_REQUEST_REVIEW_ADMISSION_SCHEMA_VERSION
    kind: ClassVar[str] = "github_api_read_receipt_v1"

    def __post_init__(self) -> None:
        _require_bounded_int(
            self.read_ordinal,
            field_name="GitHub read ordinal",
            minimum=1,
            maximum=len(_READ_SEQUENCE),
        )
        if (self.read_ordinal, self.read_label) not in _READ_SEQUENCE:
            raise GitHubPullRequestReviewAdmissionError("GitHub read ordinal/label is unsupported")
        _validate_exact_github_url(self.requested_url, expected_url=self.requested_url)
        _require_sha256(self.raw_sha256, field_name="raw_sha256")
        _require_sha256(self.projection_sha256, field_name="projection_sha256")
        if self.etag is not None and (
            type(self.etag) is not str or _ETAG_RE.fullmatch(self.etag) is None
        ):
            raise GitHubPullRequestReviewAdmissionError("GitHub ETag is invalid")
        if self.request_id is not None and (
            type(self.request_id) is not str or _REQUEST_ID_RE.fullmatch(self.request_id) is None
        ):
            raise GitHubPullRequestReviewAdmissionError("GitHub request id is invalid")
        _require_rfc3339_utc(self.observed_at, field_name="GitHub read observed_at")

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "read_ordinal": self.read_ordinal,
            "read_label": self.read_label,
            "requested_url": self.requested_url,
            "raw_sha256": self.raw_sha256,
            "projection_sha256": self.projection_sha256,
            "etag": self.etag,
            "request_id": self.request_id,
            "observed_at": self.observed_at,
        }

    @property
    def receipt_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "receipt_sha256": _sha256(content)}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="GitHub API read receipt")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "read_ordinal",
                    "read_label",
                    "requested_url",
                    "raw_sha256",
                    "projection_sha256",
                    "etag",
                    "request_id",
                    "observed_at",
                    "receipt_sha256",
                }
            ),
            label="GitHub API read receipt",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "GitHub API read receipt schema is unsupported"
            )
        result = cls(
            read_ordinal=cast("int", payload["read_ordinal"]),
            read_label=cast("str", payload["read_label"]),
            requested_url=cast("str", payload["requested_url"]),
            raw_sha256=cast("str", payload["raw_sha256"]),
            projection_sha256=cast("str", payload["projection_sha256"]),
            etag=cast("str | None", payload["etag"]),
            request_id=cast("str | None", payload["request_id"]),
            observed_at=cast("str", payload["observed_at"]),
        )
        if payload != result.to_dict():
            raise GitHubPullRequestReviewAdmissionError(
                "GitHub API read receipt differs from exact reconstruction"
            )
        return result


def _read_inventory_sha256(reads: tuple[GitHubApiReadReceiptV1, ...]) -> str:
    return _sha256(
        {
            "domain": _READ_INVENTORY_DOMAIN,
            "reads": [item.to_dict() for item in reads],
        }
    )


@dataclass(frozen=True, slots=True)
class UntrustedGitHubPullRequestReviewObservationV1:
    """Durable caller-claimed readback; never protected or independent authority."""

    claimed_policy_sha256: str
    repository_id: int
    repository_node_id: str
    repository_full_name: str
    claimed_base_ref: str
    pull_number: int
    pull_request_node_id: str
    review_id: int
    source_sha: str
    work_packet_sha256: str
    challenge_sha256: str
    shard_id: str
    shard_sha256: str
    result_bundle_sha256: str
    candidate_count: int
    candidate_id_inventory_sha256: str
    result_slot_inventory_sha256: str
    result_entry_inventory_sha256: str
    result_payload_inventory_sha256: str
    review_submission_body_sha256: str
    review_state: str
    review_submitted_at: str
    pull_request_projection_sha256: str
    review_projection_sha256: str
    reads: tuple[GitHubApiReadReceiptV1, ...]
    read_inventory_sha256: str
    first_observed_at: str
    last_observed_at: str
    idempotency_tuple: tuple[str, ...]
    idempotency_sha256: str
    observation_id: str
    trust_class: Literal["caller_supplied_untrusted"] = "caller_supplied_untrusted"
    point_in_time_only: Literal[True] = True
    requires_protected_reverification: Literal[True] = True
    protected_identity_admitted: Literal[False] = False
    review_gate_green: Literal[False] = False

    schema_version: ClassVar[int] = GITHUB_PULL_REQUEST_REVIEW_ADMISSION_SCHEMA_VERSION
    kind: ClassVar[str] = "untrusted_github_pull_request_review_observation_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "claimed_policy_sha256",
            "work_packet_sha256",
            "challenge_sha256",
            "shard_sha256",
            "result_bundle_sha256",
            "candidate_id_inventory_sha256",
            "result_slot_inventory_sha256",
            "result_entry_inventory_sha256",
            "result_payload_inventory_sha256",
            "review_submission_body_sha256",
            "pull_request_projection_sha256",
            "review_projection_sha256",
            "read_inventory_sha256",
            "idempotency_sha256",
            "observation_id",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_git_sha(self.source_sha, field_name="observation source_sha")
        _require_positive_int(self.repository_id, field_name="repository_id")
        _require_positive_int(self.pull_number, field_name="pull_number")
        _require_positive_int(self.review_id, field_name="review_id")
        _require_ascii_match(
            self.repository_node_id,
            field_name="repository_node_id",
            pattern=_NODE_ID_RE,
        )
        _require_ascii_match(
            self.repository_full_name,
            field_name="repository_full_name",
            pattern=re.compile(
                r"[a-z0-9-]{1,39}/[a-z0-9._-]{1,100}\Z",
                flags=re.ASCII,
            ),
        )
        _require_ascii_match(
            self.claimed_base_ref,
            field_name="claimed_base_ref",
            pattern=_REF_RE,
        )
        _require_ascii_match(
            self.pull_request_node_id,
            field_name="pull_request_node_id",
            pattern=_NODE_ID_RE,
        )
        _require_ascii_match(self.shard_id, field_name="shard_id", pattern=_SAFE_ID_RE)
        _require_bounded_int(
            self.candidate_count,
            field_name="candidate_count",
            minimum=1,
            maximum=64,
        )
        if type(self.review_state) is not str or self.review_state not in _ALLOWED_REVIEW_STATES:
            raise GitHubPullRequestReviewAdmissionError("observation review state is unsupported")
        _require_rfc3339_utc(
            self.review_submitted_at,
            field_name="observation review_submitted_at",
        )
        if (
            type(self.reads) is not tuple
            or len(self.reads) != len(_READ_SEQUENCE)
            or any(type(item) is not GitHubApiReadReceiptV1 for item in self.reads)
            or tuple((item.read_ordinal, item.read_label) for item in self.reads) != _READ_SEQUENCE
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "observation must contain the exact five-read sequence"
            )
        pr_url = (
            f"https://api.github.com/repos/{self.repository_full_name}/pulls/{self.pull_number}"
        )
        review_url = f"{pr_url}/reviews/{self.review_id}"
        expected_joins = (
            (pr_url, self.pull_request_projection_sha256),
            (review_url, self.review_projection_sha256),
            (pr_url, self.pull_request_projection_sha256),
            (review_url, self.review_projection_sha256),
            (pr_url, self.pull_request_projection_sha256),
        )
        if any(
            receipt.requested_url != expected_url
            or receipt.projection_sha256 != expected_projection_sha256
            for receipt, (expected_url, expected_projection_sha256) in zip(
                self.reads, expected_joins, strict=True
            )
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "GitHub read receipts differ from their exact URL/projection joins"
            )
        observed_keys = tuple(
            _rfc3339_order_key(
                item.observed_at,
                field_name=f"{item.read_label} observed_at",
            )
            for item in self.reads
        )
        if any(
            later < earlier
            for earlier, later in zip(observed_keys, observed_keys[1:], strict=False)
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "GitHub read receipt timestamps are not nondecreasing"
            )
        if (
            self.first_observed_at != self.reads[0].observed_at
            or self.last_observed_at != self.reads[-1].observed_at
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "observation first/last timestamps differ from the read sequence"
            )
        if _read_inventory_sha256(self.reads) != self.read_inventory_sha256:
            raise GitHubPullRequestReviewAdmissionError(
                "GitHub read inventory root is inconsistent"
            )
        if (
            self.trust_class != "caller_supplied_untrusted"
            or self.point_in_time_only is not True
            or self.requires_protected_reverification is not True
            or self.protected_identity_admitted is not False
            or self.review_gate_green is not False
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "GitHub observation cannot claim protected identity or green review authority"
            )
        expected_idempotency_tuple = (
            str(self.repository_id),
            self.repository_node_id,
            self.repository_full_name,
            str(self.pull_number),
            str(self.review_id),
            self.source_sha,
            self.claimed_policy_sha256,
            self.work_packet_sha256,
            self.challenge_sha256,
            self.shard_id,
            self.shard_sha256,
            self.result_bundle_sha256,
        )
        if self.idempotency_tuple != expected_idempotency_tuple:
            raise GitHubPullRequestReviewAdmissionError("idempotency tuple is not exact")
        if _sha256(list(self.idempotency_tuple)) != self.idempotency_sha256:
            raise GitHubPullRequestReviewAdmissionError("idempotency tuple digest is inconsistent")
        expected_observation_id = _sha256(
            {
                "domain": "nbadb:github-pr-review-untrusted-observation-id:v1",
                "idempotency_sha256": self.idempotency_sha256,
                "pull_request_projection_sha256": self.pull_request_projection_sha256,
                "review_projection_sha256": self.review_projection_sha256,
                "read_inventory_sha256": self.read_inventory_sha256,
            }
        )
        if self.observation_id != expected_observation_id:
            raise GitHubPullRequestReviewAdmissionError("observation id is inconsistent")

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "claimed_policy_sha256": self.claimed_policy_sha256,
            "repository_id": self.repository_id,
            "repository_node_id": self.repository_node_id,
            "repository_full_name": self.repository_full_name,
            "claimed_base_ref": self.claimed_base_ref,
            "pull_number": self.pull_number,
            "pull_request_node_id": self.pull_request_node_id,
            "review_id": self.review_id,
            "source_sha": self.source_sha,
            "work_packet_sha256": self.work_packet_sha256,
            "challenge_sha256": self.challenge_sha256,
            "shard_id": self.shard_id,
            "shard_sha256": self.shard_sha256,
            "result_bundle_sha256": self.result_bundle_sha256,
            "candidate_count": self.candidate_count,
            "candidate_id_inventory_sha256": self.candidate_id_inventory_sha256,
            "result_slot_inventory_sha256": self.result_slot_inventory_sha256,
            "result_entry_inventory_sha256": self.result_entry_inventory_sha256,
            "result_payload_inventory_sha256": self.result_payload_inventory_sha256,
            "review_submission_body_sha256": self.review_submission_body_sha256,
            "review_state": self.review_state,
            "review_submitted_at": self.review_submitted_at,
            "pull_request_projection_sha256": self.pull_request_projection_sha256,
            "review_projection_sha256": self.review_projection_sha256,
            "reads": [item.to_dict() for item in self.reads],
            "read_inventory_sha256": self.read_inventory_sha256,
            "first_observed_at": self.first_observed_at,
            "last_observed_at": self.last_observed_at,
            "idempotency_tuple": list(self.idempotency_tuple),
            "idempotency_sha256": self.idempotency_sha256,
            "observation_id": self.observation_id,
            "trust_class": self.trust_class,
            "point_in_time_only": self.point_in_time_only,
            "requires_protected_reverification": self.requires_protected_reverification,
            "protected_identity_admitted": self.protected_identity_admitted,
            "review_gate_green": self.review_gate_green,
        }

    @property
    def observation_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "observation_sha256": _sha256(content)}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        payload = _require_mapping(
            _decode_json(
                raw,
                label="untrusted GitHub review observation",
                maximum_bytes=_MAX_OBSERVATION_BYTES,
                require_canonical=True,
            ),
            label="untrusted GitHub review observation",
        )
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "claimed_policy_sha256",
                    "repository_id",
                    "repository_node_id",
                    "repository_full_name",
                    "claimed_base_ref",
                    "pull_number",
                    "pull_request_node_id",
                    "review_id",
                    "source_sha",
                    "work_packet_sha256",
                    "challenge_sha256",
                    "shard_id",
                    "shard_sha256",
                    "result_bundle_sha256",
                    "candidate_count",
                    "candidate_id_inventory_sha256",
                    "result_slot_inventory_sha256",
                    "result_entry_inventory_sha256",
                    "result_payload_inventory_sha256",
                    "review_submission_body_sha256",
                    "review_state",
                    "review_submitted_at",
                    "pull_request_projection_sha256",
                    "review_projection_sha256",
                    "reads",
                    "read_inventory_sha256",
                    "first_observed_at",
                    "last_observed_at",
                    "idempotency_tuple",
                    "idempotency_sha256",
                    "observation_id",
                    "trust_class",
                    "point_in_time_only",
                    "requires_protected_reverification",
                    "protected_identity_admitted",
                    "review_gate_green",
                    "observation_sha256",
                }
            ),
            label="untrusted GitHub review observation",
        )
        reads = payload["reads"]
        idempotency_tuple = payload["idempotency_tuple"]
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(reads) is not list
            or type(idempotency_tuple) is not list
            or any(type(item) is not str for item in idempotency_tuple)
        ):
            raise GitHubPullRequestReviewAdmissionError(
                "untrusted GitHub review observation schema is unsupported"
            )
        result = cls(
            claimed_policy_sha256=cast("str", payload["claimed_policy_sha256"]),
            repository_id=cast("int", payload["repository_id"]),
            repository_node_id=cast("str", payload["repository_node_id"]),
            repository_full_name=cast("str", payload["repository_full_name"]),
            claimed_base_ref=cast("str", payload["claimed_base_ref"]),
            pull_number=cast("int", payload["pull_number"]),
            pull_request_node_id=cast("str", payload["pull_request_node_id"]),
            review_id=cast("int", payload["review_id"]),
            source_sha=cast("str", payload["source_sha"]),
            work_packet_sha256=cast("str", payload["work_packet_sha256"]),
            challenge_sha256=cast("str", payload["challenge_sha256"]),
            shard_id=cast("str", payload["shard_id"]),
            shard_sha256=cast("str", payload["shard_sha256"]),
            result_bundle_sha256=cast("str", payload["result_bundle_sha256"]),
            candidate_count=cast("int", payload["candidate_count"]),
            candidate_id_inventory_sha256=cast("str", payload["candidate_id_inventory_sha256"]),
            result_slot_inventory_sha256=cast("str", payload["result_slot_inventory_sha256"]),
            result_entry_inventory_sha256=cast("str", payload["result_entry_inventory_sha256"]),
            result_payload_inventory_sha256=cast("str", payload["result_payload_inventory_sha256"]),
            review_submission_body_sha256=cast("str", payload["review_submission_body_sha256"]),
            review_state=cast("str", payload["review_state"]),
            review_submitted_at=cast("str", payload["review_submitted_at"]),
            pull_request_projection_sha256=cast("str", payload["pull_request_projection_sha256"]),
            review_projection_sha256=cast("str", payload["review_projection_sha256"]),
            reads=tuple(GitHubApiReadReceiptV1.from_dict(item) for item in reads),
            read_inventory_sha256=cast("str", payload["read_inventory_sha256"]),
            first_observed_at=cast("str", payload["first_observed_at"]),
            last_observed_at=cast("str", payload["last_observed_at"]),
            idempotency_tuple=tuple(cast("list[str]", idempotency_tuple)),
            idempotency_sha256=cast("str", payload["idempotency_sha256"]),
            observation_id=cast("str", payload["observation_id"]),
            trust_class=cast("Literal['caller_supplied_untrusted']", payload["trust_class"]),
            point_in_time_only=cast("Literal[True]", payload["point_in_time_only"]),
            requires_protected_reverification=cast(
                "Literal[True]", payload["requires_protected_reverification"]
            ),
            protected_identity_admitted=cast(
                "Literal[False]", payload["protected_identity_admitted"]
            ),
            review_gate_green=cast("Literal[False]", payload["review_gate_green"]),
        )
        if payload != result.to_dict():
            raise GitHubPullRequestReviewAdmissionError(
                "untrusted GitHub review observation differs from exact reconstruction"
            )
        return result


def _validated_read(
    raw_read: _RawGitHubRead,
    *,
    label: str,
    expected_url: str,
    maximum_bytes: int,
) -> _RawGitHubRead:
    if type(raw_read) is not _RawGitHubRead:
        raise GitHubPullRequestReviewAdmissionError("GitHub read result is foreign")
    _validate_exact_github_url(raw_read.requested_url, expected_url=expected_url)
    _validate_exact_github_url(raw_read.final_url, expected_url=expected_url)
    if raw_read.status_code != 200:
        raise GitHubPullRequestReviewAdmissionError(f"{label} did not return exact status 200")
    if (
        type(raw_read.raw_body) is not bytes
        or not raw_read.raw_body
        or len(raw_read.raw_body) > maximum_bytes
    ):
        raise GitHubPullRequestReviewAdmissionError(f"{label} response size is outside bounds")
    if raw_read.etag is not None and (
        type(raw_read.etag) is not str or _ETAG_RE.fullmatch(raw_read.etag) is None
    ):
        raise GitHubPullRequestReviewAdmissionError(f"{label} ETag is invalid")
    if raw_read.request_id is not None and (
        type(raw_read.request_id) is not str
        or _REQUEST_ID_RE.fullmatch(raw_read.request_id) is None
    ):
        raise GitHubPullRequestReviewAdmissionError(f"{label} request id is invalid")
    _require_rfc3339_utc(raw_read.observed_at, field_name=f"{label} observed_at")
    return raw_read


def _read_evidence(
    *,
    ordinal: int,
    label: str,
    raw_read: _RawGitHubRead,
    projection: _GitHubPullRequestProjectionV1 | _GitHubReviewProjectionV1,
) -> GitHubApiReadReceiptV1:
    return GitHubApiReadReceiptV1(
        read_ordinal=ordinal,
        read_label=label,
        requested_url=raw_read.requested_url,
        raw_sha256=_sha256_bytes(raw_read.raw_body),
        projection_sha256=_sha256(projection.to_dict()),
        etag=raw_read.etag,
        request_id=raw_read.request_id,
        observed_at=raw_read.observed_at,
    )


def observe_github_pull_request_review_untrusted(
    *,
    caller_claimed_policy_canonical_bytes: bytes,
    shard: StableModelReviewShardV1,
    challenge: StableModelReviewChallengeV1,
    expected_source_sha: str,
    result_bundle_canonical_bytes: bytes,
    pull_number: int,
    review_id: int,
    github_token: str,
) -> UntrustedGitHubPullRequestReviewObservationV1:
    """Read one exact review against a caller policy and emit only red evidence."""

    source_sha = _require_git_sha(expected_source_sha, field_name="expected source SHA")
    pull = _require_positive_int(pull_number, field_name="pull_number")
    review_number = _require_positive_int(review_id, field_name="review_id")
    _bind_shard_and_challenge(shard=shard, challenge=challenge)
    if shard.source_sha != source_sha or challenge.source_sha != source_sha:
        raise GitHubPullRequestReviewAdmissionError("expected source SHA differs from W0")
    policy = CallerClaimedGitHubReviewPolicyV1.from_canonical_bytes(
        caller_claimed_policy_canonical_bytes,
    )
    result_bundle = ExternalReviewResultBundleV1.from_canonical_bytes(
        result_bundle_canonical_bytes,
        shard=shard,
        challenge=challenge,
    )
    expected_body = build_caller_claimed_review_submission_body(
        policy=policy,
        pull_number=pull,
        shard=shard,
        challenge=challenge,
        result_bundle=result_bundle,
    )
    full_name = policy.repository.full_name
    pr_url = f"https://api.github.com/repos/{full_name}/pulls/{pull}"
    review_url = f"{pr_url}/reviews/{review_number}"

    raw_pr_a = _validated_read(
        _https_get(pr_url, token=github_token, maximum_bytes=_MAX_PULL_REQUEST_BYTES),
        label="PR_A",
        expected_url=pr_url,
        maximum_bytes=_MAX_PULL_REQUEST_BYTES,
    )
    pr_a = _parse_pull_request(raw_pr_a.raw_body)
    raw_review_a = _validated_read(
        _https_get(review_url, token=github_token, maximum_bytes=_MAX_REVIEW_BYTES),
        label="review_A",
        expected_url=review_url,
        maximum_bytes=_MAX_REVIEW_BYTES,
    )
    review_a = _parse_review(raw_review_a.raw_body)
    raw_pr_b = _validated_read(
        _https_get(pr_url, token=github_token, maximum_bytes=_MAX_PULL_REQUEST_BYTES),
        label="PR_B",
        expected_url=pr_url,
        maximum_bytes=_MAX_PULL_REQUEST_BYTES,
    )
    pr_b = _parse_pull_request(raw_pr_b.raw_body)
    raw_review_b = _validated_read(
        _https_get(review_url, token=github_token, maximum_bytes=_MAX_REVIEW_BYTES),
        label="review_B",
        expected_url=review_url,
        maximum_bytes=_MAX_REVIEW_BYTES,
    )
    review_b = _parse_review(raw_review_b.raw_body)
    raw_pr_c = _validated_read(
        _https_get(pr_url, token=github_token, maximum_bytes=_MAX_PULL_REQUEST_BYTES),
        label="PR_C",
        expected_url=pr_url,
        maximum_bytes=_MAX_PULL_REQUEST_BYTES,
    )
    pr_c = _parse_pull_request(raw_pr_c.raw_body)

    if not (pr_a == pr_b == pr_c) or review_a != review_b:
        raise GitHubPullRequestReviewAdmissionError(
            "GitHub pull request/review projections did not stabilize across five reads"
        )
    _validate_projections(
        pull=pr_a,
        review=review_a,
        policy=policy,
        pull_number=pull,
        review_id=review_number,
        expected_source_sha=source_sha,
        expected_body=expected_body,
    )
    reads = (
        _read_evidence(ordinal=1, label="PR_A", raw_read=raw_pr_a, projection=pr_a),
        _read_evidence(ordinal=2, label="review_A", raw_read=raw_review_a, projection=review_a),
        _read_evidence(ordinal=3, label="PR_B", raw_read=raw_pr_b, projection=pr_b),
        _read_evidence(ordinal=4, label="review_B", raw_read=raw_review_b, projection=review_b),
        _read_evidence(ordinal=5, label="PR_C", raw_read=raw_pr_c, projection=pr_c),
    )
    read_inventory_sha256 = _read_inventory_sha256(reads)
    idempotency_tuple = (
        str(policy.repository.repository_id),
        policy.repository.repository_node_id,
        policy.repository.full_name,
        str(pull),
        str(review_number),
        source_sha,
        policy.claimed_policy_sha256,
        challenge.work_packet_sha256,
        challenge.challenge_sha256,
        shard.shard_id,
        shard.shard_sha256,
        result_bundle.result_bundle_sha256,
    )
    idempotency_sha256 = _sha256(list(idempotency_tuple))
    observation_id = _sha256(
        {
            "domain": "nbadb:github-pr-review-untrusted-observation-id:v1",
            "idempotency_sha256": idempotency_sha256,
            "pull_request_projection_sha256": _sha256(pr_a.to_dict()),
            "review_projection_sha256": _sha256(review_a.to_dict()),
            "read_inventory_sha256": read_inventory_sha256,
        }
    )
    return UntrustedGitHubPullRequestReviewObservationV1(
        claimed_policy_sha256=policy.claimed_policy_sha256,
        repository_id=policy.repository.repository_id,
        repository_node_id=policy.repository.repository_node_id,
        repository_full_name=policy.repository.full_name,
        claimed_base_ref=policy.repository.base_ref,
        pull_number=pull,
        pull_request_node_id=pr_a.node_id,
        review_id=review_number,
        source_sha=source_sha,
        work_packet_sha256=challenge.work_packet_sha256,
        challenge_sha256=challenge.challenge_sha256,
        shard_id=shard.shard_id,
        shard_sha256=shard.shard_sha256,
        result_bundle_sha256=result_bundle.result_bundle_sha256,
        candidate_count=len(result_bundle.entries),
        candidate_id_inventory_sha256=shard.candidate_id_inventory_sha256,
        result_slot_inventory_sha256=shard.result_slot_inventory_sha256,
        result_entry_inventory_sha256=result_bundle.entry_inventory_sha256,
        result_payload_inventory_sha256=result_bundle.payload_inventory_sha256,
        review_submission_body_sha256=_sha256_bytes(expected_body.encode("ascii")),
        review_state=review_a.state,
        review_submitted_at=review_a.submitted_at,
        pull_request_projection_sha256=_sha256(pr_a.to_dict()),
        review_projection_sha256=_sha256(review_a.to_dict()),
        reads=reads,
        read_inventory_sha256=read_inventory_sha256,
        first_observed_at=reads[0].observed_at,
        last_observed_at=reads[-1].observed_at,
        idempotency_tuple=idempotency_tuple,
        idempotency_sha256=idempotency_sha256,
        observation_id=observation_id,
    )
