from __future__ import annotations

import calendar
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, NoReturn, Self, cast
from urllib.parse import urlsplit

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver
from yaml.tokens import AliasToken, AnchorToken, TagToken

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "ARTIFACT_PACKAGES_FREE_FLOOR_BYTES",
    "CACHE_FREE_FLOOR_BYTES",
    "FREE_EXECUTION_ADMISSION_SCHEMA_VERSION",
    "FREE_EXECUTION_COST_READBACK_SCHEMA_VERSION",
    "FREE_EXECUTION_POINT_OF_USE_SCHEMA_VERSION",
    "ActualJobCostReadbackV1",
    "ArtifactCostReadbackV1",
    "CostReadbackAuthorityBundleV1",
    "ExactHttpResponseV1",
    "ExecutionIntentV1",
    "ExternalServiceCostEvidenceV1",
    "ExternalServiceCostReadbackV1",
    "ExternalServiceKind",
    "FreeExecutionAdmissionError",
    "FreeExecutionAdmissionStatus",
    "FreeExecutionAdmissionV1",
    "FreeExecutionAuthorityBundleV1",
    "FreeExecutionCostReadbackStatus",
    "FreeExecutionCostReadbackV1",
    "FreeExecutionMode",
    "FreeExecutionPointOfUseV1",
    "JobGraphEvidenceV1",
    "PagedInventoryAuthorityV1",
    "PointOfUseAuthorityBundleV1",
    "ProviderOperationV1",
    "RepositoryPricingEvidenceV1",
    "StorageCostEvidenceV1",
    "WorkflowJobRequirementV1",
    "canonical_json_bytes",
]

FREE_EXECUTION_ADMISSION_SCHEMA_VERSION = 1
FREE_EXECUTION_POINT_OF_USE_SCHEMA_VERSION = 1
FREE_EXECUTION_COST_READBACK_SCHEMA_VERSION = 1

ARTIFACT_PACKAGES_FREE_FLOOR_BYTES = 500 * 1024 * 1024
CACHE_FREE_FLOOR_BYTES = 10 * 1024 * 1024 * 1024

_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_PRIVATE_BODY_BYTES = 16 * 1024 * 1024
_MAX_WORKFLOW_BYTES = 2 * 1024 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 100_000
_MAX_TEXT_BYTES = 16_384
_MAX_SEQUENCE_ITEMS = 10_000
_MAX_PAGES = 1_000
_MAX_INT = (1 << 63) - 1
_MAX_EVIDENCE_TTL_SECONDS = 300
_MAX_POINT_OF_USE_TTL_SECONDS = 120
_MIN_STABILITY_SECONDS = 300
_STANDARD_RUNNER_LABEL = "ubuntu-latest"
_STANDARD_RUNNER_FAMILY = "github_hosted_standard"
_PRICING_RULE_ID = "public_standard_github_hosted_compute_free"
_PRICING_DOCUMENT_URL = "https://docs.github.com/en/billing/concepts/product-billing/github-actions"
_GITHUB_API_VERSION = "2026-03-10"
_SAFE_WORKFLOW_RUN_RE = re.compile(r"^echo [A-Za-z0-9_.:/ -]{1,512}$")
_SAFE_CHECKOUT_ACTION_RE = re.compile(r"^actions/checkout@[0-9a-f]{40}$")
_ALLOWED_TOP_LEVEL_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "repository",
        "source_sha",
        "workflow_path",
        "workflow_sha256",
        "publish",
        "active_lane_count",
        "matrix_lane_count",
        "deferred_lane_count",
        "lanes",
        "github_matrix",
        "resource_plan",
    }
)
_ALLOWED_LANE_FIELDS = frozenset(
    {"lane_id", "lane_index", "endpoint", "parameters", "operation_sha256s"}
)
_ALLOWED_MATRIX_FIELDS = _ALLOWED_LANE_FIELDS
_FORBIDDEN_KEY_FRAGMENTS = (
    "credential",
    "nord",
    "paid",
    "password",
    "proxy",
    "relay",
    "secret",
    "token",
    "vpn",
)
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"(?i)authorization\s*:\s*bearer\s+[^\s]+"),
)
_FORBIDDEN_VALUE_FRAGMENTS = (
    "credential",
    "nord",
    "paid",
    "password",
    "proxy",
    "relay",
    "secret",
    "token",
    "vpn",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CONCLUSIONS = frozenset(
    {"action_required", "cancelled", "failure", "neutral", "skipped", "success", "timed_out"}
)

_ADMISSION_INTEGRATION_BLOCKERS = (
    "free_execution_billing_authority_unavailable",
    "free_execution_http_collector_not_integrated",
    "free_execution_manifest_artifact_collector_not_integrated",
    "free_execution_nonce_issuer_not_integrated",
    "free_execution_operation_registry_not_integrated",
    "free_execution_plan_artifact_job_provenance_not_integrated",
    "free_execution_run_job_context_collector_not_integrated",
    "free_execution_storage_inventory_collector_not_integrated",
    "free_execution_workflow_content_collector_not_integrated",
)
_POINT_INTEGRATION_BLOCKERS = (
    "free_execution_point_predecessor_chain_collector_not_integrated",
    "free_execution_point_refresh_collector_not_integrated",
)
_COST_INTEGRATION_BLOCKERS = (
    "free_execution_artifact_cache_size_collector_not_integrated",
    "free_execution_billing_authority_unavailable",
    "free_execution_cost_collector_not_integrated",
    "free_execution_external_operation_inventory_not_integrated",
    "free_execution_future_billing_liability_collector_not_integrated",
)


class FreeExecutionAdmissionError(ValueError):
    """Raised when strictly-free execution authority is incomplete or inconsistent."""


def _raise_integration_blocked(*, stage: str, codes: tuple[str, ...]) -> NoReturn:
    """Make missing repository collectors an executable, non-DTO policy barrier."""
    normalized = tuple(sorted(set(codes)))
    if not normalized:
        raise FreeExecutionAdmissionError(f"{stage} has no trusted collector capability")
    raise FreeExecutionAdmissionError(f"{stage} is integration-blocked: {','.join(normalized)}")


class FreeExecutionAdmissionStatus(StrEnum):
    ADMITTED = "admitted"
    CAPACITY_BLOCKED = "capacity_blocked"


class FreeExecutionMode(StrEnum):
    INITIAL = "initial"
    TERMINAL_CATCHUP = "terminal_catchup"
    DAILY = "daily"
    MONTHLY = "monthly"
    OPPORTUNISTIC = "opportunistic"


class ExternalServiceKind(StrEnum):
    GITHUB_NETWORK_EGRESS = "github_network_egress"
    KAGGLE = "kaggle"
    NBA_API = "nba_api"


class FreeExecutionCostReadbackStatus(StrEnum):
    VERIFIED_ZERO = "verified_zero"
    PENDING = "pending"
    CHARGED = "charged"
    UNVERIFIABLE = "unverifiable"


def _json_int(value: str) -> int:
    digits = value.removeprefix("-")
    if not digits or len(digits) > 19:
        raise FreeExecutionAdmissionError("JSON integer is outside the bounded contract")
    parsed = int(value)
    if abs(parsed) > _MAX_INT:
        raise FreeExecutionAdmissionError("JSON integer is outside the bounded contract")
    return parsed


def _reject_constant(value: str) -> None:
    raise FreeExecutionAdmissionError(f"non-finite JSON number is forbidden: {value}")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise FreeExecutionAdmissionError("JSON object keys must be exact strings")
        if key in result:
            raise FreeExecutionAdmissionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_json_resources(value: object) -> None:
    nodes = 0
    active: set[int] = set()

    def visit(item: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise FreeExecutionAdmissionError("JSON exceeds the node budget")
        if depth > _MAX_JSON_DEPTH:
            raise FreeExecutionAdmissionError("JSON exceeds the depth budget")
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            if abs(cast("int", item)) > _MAX_INT:
                raise FreeExecutionAdmissionError("JSON integer is out of bounds")
            return
        if type(item) is float:
            if not math.isfinite(cast("float", item)):
                raise FreeExecutionAdmissionError("JSON contains a non-finite number")
            return
        if type(item) is str:
            if len(item.encode("utf-8")) > _MAX_TEXT_BYTES:
                raise FreeExecutionAdmissionError("JSON string exceeds the byte budget")
            return
        if type(item) in {list, tuple, dict}:
            identity = id(item)
            if identity in active:
                raise FreeExecutionAdmissionError("recursive JSON/YAML graphs are forbidden")
            active.add(identity)
            try:
                if type(item) is dict:
                    mapping = cast("dict[object, object]", item)
                    if len(mapping) > _MAX_SEQUENCE_ITEMS:
                        raise FreeExecutionAdmissionError("JSON object exceeds the item budget")
                    for key, child in mapping.items():
                        if type(key) is not str:
                            raise FreeExecutionAdmissionError("JSON keys must be exact strings")
                        visit(key, depth + 1)
                        visit(child, depth + 1)
                else:
                    sequence = cast("Sequence[object]", item)
                    if len(sequence) > _MAX_SEQUENCE_ITEMS:
                        raise FreeExecutionAdmissionError("JSON sequence exceeds the item budget")
                    for child in sequence:
                        visit(child, depth + 1)
            finally:
                active.remove(identity)
            return
        raise FreeExecutionAdmissionError("value is not bounded JSON")

    visit(value, 0)


def canonical_json_bytes(value: object) -> bytes:
    """Return the single bounded canonical JSON representation accepted here."""
    _validate_json_resources(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FreeExecutionAdmissionError("value is not canonical JSON") from exc
    if not encoded or len(encoded) > _MAX_JSON_BYTES:
        raise FreeExecutionAdmissionError("canonical JSON exceeds the byte budget")
    return encoded


def _decode_json_bytes(encoded: bytes, *, canonical: bool) -> object:
    if type(encoded) is not bytes or not encoded or len(encoded) > _MAX_PRIVATE_BODY_BYTES:
        raise FreeExecutionAdmissionError("JSON bytes are empty or exceed the byte budget")
    _reject_secret_material(encoded)
    try:
        value = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
            parse_int=_json_int,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise FreeExecutionAdmissionError("bytes are not strict UTF-8 JSON") from exc
    _validate_json_resources(value)
    _scan_secret_json_keys(value)
    if canonical and canonical_json_bytes(value) != encoded:
        raise FreeExecutionAdmissionError("receipt JSON is not canonically encoded")
    return value


def _decode_canonical_object(encoded: bytes) -> Mapping[str, object]:
    value = _decode_json_bytes(encoded, canonical=True)
    if type(value) is not dict:
        raise FreeExecutionAdmissionError("receipt JSON must be an object")
    return cast("Mapping[str, object]", value)


def _reject_secret_material(encoded: bytes) -> None:
    if any(pattern.search(encoded) for pattern in _SECRET_PATTERNS):
        raise FreeExecutionAdmissionError("private evidence contains secret material")


def _exact_text(value: object, *, field_name: str, maximum_bytes: int = 1024) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise FreeExecutionAdmissionError(f"{field_name} must be a bounded exact string")
    return value


def _uint(value: object, *, field_name: str, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or not minimum <= value <= _MAX_INT:
        raise FreeExecutionAdmissionError(f"{field_name} must be a bounded integer")
    return value


def _sha256(value: object, *, field_name: str, prefixed: bool = False) -> str:
    raw = _exact_text(value, field_name=field_name)
    prefix = "sha256:" if prefixed else ""
    if prefixed and not raw.startswith(prefix):
        raise FreeExecutionAdmissionError(f"{field_name} must be a lowercase SHA-256")
    digest = raw.removeprefix(prefix) if prefixed else raw
    if _SHA256_RE.fullmatch(digest) is None:
        raise FreeExecutionAdmissionError(f"{field_name} must be a lowercase SHA-256")
    return raw


def _source_sha(value: object, *, field_name: str = "source_sha") -> str:
    raw = _exact_text(value, field_name=field_name)
    if _SOURCE_SHA_RE.fullmatch(raw) is None:
        raise FreeExecutionAdmissionError(f"{field_name} must be a lowercase commit SHA")
    return raw


def _timestamp(value: object, *, field_name: str) -> datetime:
    raw = _exact_text(value, field_name=field_name)
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise FreeExecutionAdmissionError(
            f"{field_name} must be canonical UTC YYYY-MM-DDTHH:MM:SSZ"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != raw:
        raise FreeExecutionAdmissionError(f"{field_name} is not canonical UTC")
    return parsed


def _workflow_path(value: object) -> str:
    raw = _exact_text(value, field_name="workflow_path")
    path = PurePosixPath(raw)
    if (
        not raw.startswith(".github/workflows/")
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in raw
        or path.suffix not in {".yml", ".yaml"}
    ):
        raise FreeExecutionAdmissionError("workflow_path is invalid")
    return raw


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sealed_digest(supplied: str, *, identity: Mapping[str, object], field_name: str) -> str:
    expected = _canonical_sha256(dict(identity))
    if supplied and supplied != expected:
        raise FreeExecutionAdmissionError(f"{field_name} is invalid")
    return expected


def _require_exact_keys(
    payload: Mapping[str, object], *, expected: frozenset[str], label: str
) -> None:
    if type(payload) is not dict or frozenset(payload) != expected or len(payload) != len(expected):
        raise FreeExecutionAdmissionError(f"{label} fields are invalid")


def _mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise FreeExecutionAdmissionError(f"{field_name} must be an exact object")
    return cast("Mapping[str, object]", value)


def _tuple_text(value: object, *, field_name: str, sorted_unique: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > _MAX_SEQUENCE_ITEMS:
        raise FreeExecutionAdmissionError(f"{field_name} must be an immutable tuple")
    result = tuple(_exact_text(item, field_name=field_name) for item in value)
    if sorted_unique and result != tuple(sorted(set(result))):
        raise FreeExecutionAdmissionError(f"{field_name} must be sorted and unique")
    return result


def _checked_add(left: int, right: int, *, field_name: str) -> int:
    result = left + right
    if result > _MAX_INT:
        raise FreeExecutionAdmissionError(f"{field_name} overflows")
    return result


def _checked_multiply(left: int, right: int, *, field_name: str) -> int:
    if left and right > _MAX_INT // left:
        raise FreeExecutionAdmissionError(f"{field_name} overflows")
    return left * right


def _ceil_hours(start: datetime, end: datetime) -> int:
    if end <= start:
        return 0
    seconds = int((end - start).total_seconds())
    return (seconds + 3599) // 3600


def _billing_window(at: datetime) -> tuple[datetime, datetime, int, int]:
    start = datetime(at.year, at.month, 1, tzinfo=UTC)
    year = at.year + (1 if at.month == 12 else 0)
    month = 1 if at.month == 12 else at.month + 1
    end = datetime(year, month, 1, tzinfo=UTC)
    period_hours = int((end - start).total_seconds() // 3600)
    remaining_hours = _ceil_hours(at, end)
    expected = calendar.monthrange(at.year, at.month)[1] * 24
    if period_hours != expected:
        raise FreeExecutionAdmissionError("calendar billing-period derivation failed")
    return start, end, period_hours, remaining_hours


@dataclass(frozen=True, slots=True)
class ExactHttpResponseV1:
    """Private exact HTTP response authority; raw bytes are never serialized publicly."""

    method: str
    url: str
    api_version: str | None
    status_code: int
    response_date: str
    etag: str | None
    body: bytes = field(repr=False)
    body_sha256: str = ""
    receipt_sha256: str = ""

    def __post_init__(self) -> None:
        if self.method != "GET":
            raise FreeExecutionAdmissionError("authority HTTP method must be GET")
        url = _exact_text(self.url, field_name="url", maximum_bytes=4096)
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise FreeExecutionAdmissionError("authority URL must be exact HTTPS without userinfo")
        if self.api_version is not None:
            _exact_text(self.api_version, field_name="api_version")
        if _uint(self.status_code, field_name="status_code", positive=True) != 200:
            raise FreeExecutionAdmissionError("authority response must be HTTP 200")
        _timestamp(self.response_date, field_name="response_date")
        if self.etag is not None:
            _exact_text(self.etag, field_name="etag")
        if (
            type(self.body) is not bytes
            or not self.body
            or len(self.body) > _MAX_PRIVATE_BODY_BYTES
        ):
            raise FreeExecutionAdmissionError("private response body is empty or oversized")
        _reject_secret_material(self.body)
        digest = hashlib.sha256(self.body).hexdigest()
        if self.body_sha256 and self.body_sha256 != digest:
            raise FreeExecutionAdmissionError("private response body SHA-256 is invalid")
        object.__setattr__(self, "body_sha256", digest)
        object.__setattr__(
            self,
            "receipt_sha256",
            _sealed_digest(
                self.receipt_sha256,
                identity=self._public_identity_unchecked(),
                field_name="http_response.receipt_sha256",
            ),
        )

    @property
    def observed_at(self) -> datetime:
        return _timestamp(self.response_date, field_name="response_date")

    def json_value(self) -> object:
        self.validate_seal()
        return _decode_json_bytes(self.body, canonical=False)

    def json_object(self) -> Mapping[str, object]:
        value = self.json_value()
        if type(value) is not dict:
            raise FreeExecutionAdmissionError("authority response JSON must be an object")
        return cast("Mapping[str, object]", value)

    def public_identity(self) -> dict[str, object]:
        self.validate_seal()
        return self._public_identity_unchecked()

    def validate_seal(self) -> None:
        if (
            type(self.body) is not bytes
            or hashlib.sha256(self.body).hexdigest() != self.body_sha256
        ):
            raise FreeExecutionAdmissionError("private response body changed after sealing")
        expected = _canonical_sha256(self._public_identity_unchecked())
        if self.receipt_sha256 != expected:
            raise FreeExecutionAdmissionError("private response receipt changed after sealing")

    def _public_identity_unchecked(self) -> dict[str, object]:
        return {
            "method": self.method,
            "url": self.url,
            "api_version": self.api_version,
            "status_code": self.status_code,
            "response_date": self.response_date,
            "etag": self.etag,
            "body_sha256": self.body_sha256,
        }


def _scan_forbidden_keys(value: object, *, path: str = "$") -> None:
    if type(value) is dict:
        for raw_key, child in cast("dict[object, object]", value).items():
            if type(raw_key) is not str:
                raise FreeExecutionAdmissionError(f"{path} contains a non-string key")
            lowered = raw_key.casefold()
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise FreeExecutionAdmissionError(f"{path}.{raw_key} is forbidden")
            _scan_forbidden_keys(child, path=f"{path}.{raw_key}")
    elif type(value) in {list, tuple}:
        for index, child in enumerate(cast("Sequence[object]", value)):
            _scan_forbidden_keys(child, path=f"{path}[{index}]")
    elif type(value) is str:
        lowered = value.casefold()
        if any(marker in lowered for marker in _FORBIDDEN_VALUE_FRAGMENTS):
            raise FreeExecutionAdmissionError(f"{path} contains forbidden paid/routing material")


def _scan_secret_json_keys(value: object, *, path: str = "$") -> None:
    if type(value) is dict:
        for raw_key, child in cast("dict[object, object]", value).items():
            if type(raw_key) is not str:
                raise FreeExecutionAdmissionError(f"{path} contains a non-string key")
            lowered = raw_key.casefold()
            if any(
                fragment in lowered
                for fragment in ("authorization", "credential", "password", "secret", "token")
            ):
                raise FreeExecutionAdmissionError(f"{path}.{raw_key} contains secret material")
            _scan_secret_json_keys(child, path=f"{path}.{raw_key}")
    elif type(value) in {list, tuple}:
        for index, child in enumerate(cast("Sequence[object]", value)):
            _scan_secret_json_keys(child, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class ExecutionIntentV1:
    """Public digest summary independently derived from private canonical manifest bytes."""

    repository: str
    source_sha: str
    workflow_path: str
    workflow_sha256: str
    publish: bool
    active_lane_count: int
    matrix_lane_count: int
    deferred_lane_count: int
    lane_ids: tuple[str, ...]
    matrix_lane_ids: tuple[str, ...]
    lane_operation_sha256s: tuple[tuple[str, ...], ...]
    planned_artifact_max_bytes: int
    planned_artifact_retention_hours: int
    planned_cache_max_bytes: int
    required_external_services: tuple[ExternalServiceKind, ...]
    manifest_sha256: str
    intent_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        repository = _exact_text(self.repository, field_name="repository")
        if repository.count("/") != 1:
            raise FreeExecutionAdmissionError("repository must be owner/name")
        _source_sha(self.source_sha)
        _workflow_path(self.workflow_path)
        _sha256(self.workflow_sha256, field_name="workflow_sha256")
        if type(self.publish) is not bool:
            raise FreeExecutionAdmissionError("publish must be boolean")
        active = _uint(self.active_lane_count, field_name="active_lane_count")
        matrix = _uint(self.matrix_lane_count, field_name="matrix_lane_count")
        deferred = _uint(self.deferred_lane_count, field_name="deferred_lane_count")
        if active != matrix + deferred:
            raise FreeExecutionAdmissionError("manifest lane accounting is invalid")
        lanes = _tuple_text(self.lane_ids, field_name="lane_ids")
        matrix_lanes = _tuple_text(self.matrix_lane_ids, field_name="matrix_lane_ids")
        if lanes != tuple(dict.fromkeys(lanes)) or matrix_lanes != tuple(
            dict.fromkeys(matrix_lanes)
        ):
            raise FreeExecutionAdmissionError("manifest lane identities must be unique")
        if len(lanes) != active or len(matrix_lanes) != matrix:
            raise FreeExecutionAdmissionError("manifest lane denominator is incomplete")
        if any(lane not in set(lanes) for lane in matrix_lanes):
            raise FreeExecutionAdmissionError("matrix contains a foreign lane")
        if type(self.lane_operation_sha256s) is not tuple or len(
            self.lane_operation_sha256s
        ) != len(lanes):
            raise FreeExecutionAdmissionError("lane operation authority denominator is incomplete")
        normalized_operations: list[tuple[str, ...]] = []
        for index, raw_operations in enumerate(self.lane_operation_sha256s):
            if type(raw_operations) is not tuple or not raw_operations:
                raise FreeExecutionAdmissionError(
                    f"lane operation authority {index} must be a nonempty tuple"
                )
            operations = tuple(
                _sha256(item, field_name="lane_operation_sha256s") for item in raw_operations
            )
            if operations != tuple(sorted(set(operations))):
                raise FreeExecutionAdmissionError(
                    "lane operation authority digests must be sorted and unique"
                )
            normalized_operations.append(operations)
        object.__setattr__(self, "lane_operation_sha256s", tuple(normalized_operations))
        planned_bytes = _uint(
            self.planned_artifact_max_bytes,
            field_name="planned_artifact_max_bytes",
        )
        retention = _uint(
            self.planned_artifact_retention_hours,
            field_name="planned_artifact_retention_hours",
            positive=planned_bytes > 0,
        )
        if not planned_bytes and retention:
            raise FreeExecutionAdmissionError("zero planned artifacts require zero retention")
        _uint(self.planned_cache_max_bytes, field_name="planned_cache_max_bytes")
        required = (
            ExternalServiceKind.GITHUB_NETWORK_EGRESS,
            *((ExternalServiceKind.KAGGLE,) if self.publish else ()),
            ExternalServiceKind.NBA_API,
        )
        required = tuple(sorted(required, key=lambda item: item.value))
        if self.required_external_services != required:
            raise FreeExecutionAdmissionError(
                "required external services differ from publish intent"
            )
        _sha256(self.manifest_sha256, field_name="manifest_sha256")
        object.__setattr__(
            self,
            "intent_sha256",
            _sealed_digest(
                self.intent_sha256,
                identity=self._identity_dict(),
                field_name="intent_sha256",
            ),
        )

    @classmethod
    def from_manifest_bytes(cls, encoded: bytes) -> Self:
        payload = _decode_canonical_object(encoded)
        _require_exact_keys(
            payload,
            expected=_ALLOWED_TOP_LEVEL_MANIFEST_FIELDS,
            label="execution manifest",
        )
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("execution manifest schema version is unsupported")
        _scan_forbidden_keys(payload)
        lanes_raw = payload["lanes"]
        matrix_raw_value = payload["github_matrix"]
        resource_plan = _mapping(payload["resource_plan"], field_name="resource_plan")
        if type(lanes_raw) is not list or type(matrix_raw_value) is not dict:
            raise FreeExecutionAdmissionError("execution manifest lane inventories are invalid")
        matrix_raw = cast("Mapping[str, object]", matrix_raw_value)
        _require_exact_keys(matrix_raw, expected=frozenset({"include"}), label="github_matrix")
        include = matrix_raw["include"]
        if type(include) is not list:
            raise FreeExecutionAdmissionError("github_matrix.include must be an array")
        lane_ids: list[str] = []
        matrix_ids: list[str] = []
        lane_operation_sha256s: list[tuple[str, ...]] = []
        lane_rows_by_id: dict[str, Mapping[str, object]] = {}
        for index, raw_lane in enumerate(cast("list[object]", lanes_raw)):
            lane = _mapping(raw_lane, field_name=f"lanes[{index}]")
            _require_exact_keys(lane, expected=_ALLOWED_LANE_FIELDS, label="lane")
            lane_id = _exact_text(lane.get("lane_id"), field_name="lane_id")
            if _uint(lane.get("lane_index"), field_name="lane_index") != index:
                raise FreeExecutionAdmissionError("lane indices must be contiguous and ordered")
            _exact_text(lane.get("endpoint"), field_name="endpoint")
            _mapping(lane.get("parameters"), field_name="parameters")
            raw_operation_sha256s = lane.get("operation_sha256s")
            if type(raw_operation_sha256s) is not list or not raw_operation_sha256s:
                raise FreeExecutionAdmissionError(
                    "lane operation authority must be a nonempty array"
                )
            operation_sha256s = tuple(
                _sha256(item, field_name="operation_sha256s")
                for item in cast("list[object]", raw_operation_sha256s)
            )
            if operation_sha256s != tuple(sorted(set(operation_sha256s))):
                raise FreeExecutionAdmissionError(
                    "lane operation authority digests must be sorted and unique"
                )
            lane_ids.append(lane_id)
            lane_operation_sha256s.append(operation_sha256s)
            lane_rows_by_id[lane_id] = lane
        for index, raw_row in enumerate(cast("list[object]", include)):
            row = _mapping(raw_row, field_name=f"github_matrix.include[{index}]")
            _require_exact_keys(row, expected=_ALLOWED_MATRIX_FIELDS, label="matrix row")
            lane_id = _exact_text(row.get("lane_id"), field_name="lane_id")
            _uint(row.get("lane_index"), field_name="lane_index")
            _exact_text(row.get("endpoint"), field_name="endpoint")
            _mapping(row.get("parameters"), field_name="parameters")
            if lane_id not in lane_rows_by_id or row != lane_rows_by_id[lane_id]:
                raise FreeExecutionAdmissionError("matrix row differs from its exact lane")
            matrix_ids.append(lane_id)
        _require_exact_keys(
            resource_plan,
            expected=frozenset(
                {
                    "planned_artifact_max_bytes",
                    "planned_artifact_retention_hours",
                    "planned_cache_max_bytes",
                }
            ),
            label="resource_plan",
        )
        publish = payload["publish"]
        if type(publish) is not bool:
            raise FreeExecutionAdmissionError("publish must be boolean")
        required = [ExternalServiceKind.GITHUB_NETWORK_EGRESS, ExternalServiceKind.NBA_API]
        if publish:
            required.append(ExternalServiceKind.KAGGLE)
        return cls(
            repository=cast("str", payload["repository"]),
            source_sha=cast("str", payload["source_sha"]),
            workflow_path=cast("str", payload["workflow_path"]),
            workflow_sha256=cast("str", payload["workflow_sha256"]),
            publish=publish,
            active_lane_count=cast("int", payload["active_lane_count"]),
            matrix_lane_count=cast("int", payload["matrix_lane_count"]),
            deferred_lane_count=cast("int", payload["deferred_lane_count"]),
            lane_ids=tuple(lane_ids),
            matrix_lane_ids=tuple(matrix_ids),
            lane_operation_sha256s=tuple(lane_operation_sha256s),
            planned_artifact_max_bytes=cast("int", resource_plan["planned_artifact_max_bytes"]),
            planned_artifact_retention_hours=cast(
                "int", resource_plan["planned_artifact_retention_hours"]
            ),
            planned_cache_max_bytes=cast("int", resource_plan["planned_cache_max_bytes"]),
            required_external_services=tuple(sorted(required, key=lambda item: item.value)),
            manifest_sha256=hashlib.sha256(encoded).hexdigest(),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "workflow_path": self.workflow_path,
            "workflow_sha256": self.workflow_sha256,
            "publish": self.publish,
            "active_lane_count": self.active_lane_count,
            "matrix_lane_count": self.matrix_lane_count,
            "deferred_lane_count": self.deferred_lane_count,
            "lane_ids": list(self.lane_ids),
            "matrix_lane_ids": list(self.matrix_lane_ids),
            "lane_operation_sha256s": [list(item) for item in self.lane_operation_sha256s],
            "planned_artifact_max_bytes": self.planned_artifact_max_bytes,
            "planned_artifact_retention_hours": self.planned_artifact_retention_hours,
            "planned_cache_max_bytes": self.planned_cache_max_bytes,
            "required_external_services": [item.value for item in self.required_external_services],
            "manifest_sha256": self.manifest_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "intent_sha256": self.intent_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(cls._wire_fields())
        _require_exact_keys(payload, expected=expected, label="execution intent")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("execution intent schema is unsupported")
        lane_ids = payload["lane_ids"]
        matrix_ids = payload["matrix_lane_ids"]
        raw_lane_operations = payload["lane_operation_sha256s"]
        services = payload["required_external_services"]
        if (
            type(lane_ids) is not list
            or type(matrix_ids) is not list
            or type(raw_lane_operations) is not list
            or type(services) is not list
        ):
            raise FreeExecutionAdmissionError("execution intent arrays are invalid")
        try:
            service_values = tuple(
                ExternalServiceKind(_exact_text(item, field_name="required_external_services"))
                for item in services
            )
        except ValueError as exc:
            raise FreeExecutionAdmissionError("execution intent service is unsupported") from exc
        return cls(
            repository=cast("str", payload["repository"]),
            source_sha=cast("str", payload["source_sha"]),
            workflow_path=cast("str", payload["workflow_path"]),
            workflow_sha256=cast("str", payload["workflow_sha256"]),
            publish=cast("bool", payload["publish"]),
            active_lane_count=cast("int", payload["active_lane_count"]),
            matrix_lane_count=cast("int", payload["matrix_lane_count"]),
            deferred_lane_count=cast("int", payload["deferred_lane_count"]),
            lane_ids=tuple(_exact_text(item, field_name="lane_ids") for item in lane_ids),
            matrix_lane_ids=tuple(
                _exact_text(item, field_name="matrix_lane_ids") for item in matrix_ids
            ),
            lane_operation_sha256s=tuple(
                tuple(
                    _sha256(item, field_name="lane_operation_sha256s")
                    for item in cast("list[object]", row)
                )
                if type(row) is list
                else ()
                for row in cast("list[object]", raw_lane_operations)
            ),
            planned_artifact_max_bytes=cast("int", payload["planned_artifact_max_bytes"]),
            planned_artifact_retention_hours=cast(
                "int", payload["planned_artifact_retention_hours"]
            ),
            planned_cache_max_bytes=cast("int", payload["planned_cache_max_bytes"]),
            required_external_services=service_values,
            manifest_sha256=cast("str", payload["manifest_sha256"]),
            intent_sha256=cast("str", payload["intent_sha256"]),
        )

    @staticmethod
    def _wire_fields() -> tuple[str, ...]:
        return (
            "schema_version",
            "repository",
            "source_sha",
            "workflow_path",
            "workflow_sha256",
            "publish",
            "active_lane_count",
            "matrix_lane_count",
            "deferred_lane_count",
            "lane_ids",
            "matrix_lane_ids",
            "lane_operation_sha256s",
            "planned_artifact_max_bytes",
            "planned_artifact_retention_hours",
            "planned_cache_max_bytes",
            "required_external_services",
            "manifest_sha256",
            "intent_sha256",
        )

    def operation_sha256s_for_lane(self, lane_id: str) -> tuple[str, ...]:
        """Return the exact issued operation inventory for one manifest lane."""
        normalized = _exact_text(lane_id, field_name="lane_id")
        matches = tuple(
            operations
            for candidate, operations in zip(
                self.lane_ids,
                self.lane_operation_sha256s,
                strict=True,
            )
            if candidate == normalized
        )
        if len(matches) != 1:
            raise FreeExecutionAdmissionError("manifest lane operation authority is absent")
        return matches[0]


class _WorkflowLoader(yaml.SafeLoader):
    pass


_WorkflowLoader.yaml_implicit_resolvers = {
    key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for _resolver_key, _resolvers in tuple(_WorkflowLoader.yaml_implicit_resolvers.items()):
    _WorkflowLoader.yaml_implicit_resolvers[_resolver_key] = [
        item for item in _resolvers if item[0] != "tag:yaml.org,2002:bool"
    ]
_WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def _construct_unique_mapping(
    loader: _WorkflowLoader, node: MappingNode, deep: bool = False
) -> dict[object, object]:
    if not isinstance(node, MappingNode):
        raise ConstructorError(None, None, "expected a mapping node", node.start_mark)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise ConstructorError(
                None, None, "workflow key is unhashable", key_node.start_mark
            ) from exc
        if duplicate:
            raise ConstructorError(
                None, None, f"duplicate workflow key: {key}", key_node.start_mark
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_WorkflowLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_workflow(encoded: bytes) -> Mapping[str, object]:
    if type(encoded) is not bytes or not encoded or len(encoded) > _MAX_WORKFLOW_BYTES:
        raise FreeExecutionAdmissionError("workflow bytes are empty or oversized")
    _reject_secret_material(encoded)
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FreeExecutionAdmissionError("workflow bytes must be UTF-8") from exc
    try:
        for token in yaml.scan(text, Loader=_WorkflowLoader):
            if isinstance(token, (AnchorToken, AliasToken, TagToken)):
                raise FreeExecutionAdmissionError(
                    "workflow anchors, aliases, and custom tags are forbidden"
                )
        decoded = yaml.load(text, Loader=_WorkflowLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise FreeExecutionAdmissionError("workflow YAML is not strictly parseable") from exc
    if type(decoded) is not dict or any(type(key) is not str for key in decoded):
        raise FreeExecutionAdmissionError("workflow root must be an exact string-keyed object")
    _validate_json_resources(decoded)
    _scan_forbidden_keys(decoded, path="$.workflow")
    _scan_secret_json_keys(decoded, path="$.workflow")
    unsupported_root = frozenset(decoded) - {"jobs", "name", "on"}
    if unsupported_root:
        raise FreeExecutionAdmissionError("workflow root contains unsupported effect fields")
    if "on" not in decoded:
        raise FreeExecutionAdmissionError("workflow loader did not preserve the on key as text")
    trigger = decoded["on"]
    if trigger != "workflow_dispatch" and not (
        type(trigger) is dict
        and frozenset(trigger) == {"workflow_dispatch"}
        and trigger["workflow_dispatch"] in (None, {})
    ):
        raise FreeExecutionAdmissionError("workflow trigger is not exact workflow_dispatch")
    _validate_workflow_expressions(decoded)
    return cast("Mapping[str, object]", decoded)


def _validate_workflow_action_surface(
    workflow: Mapping[str, object],
    *,
    intent: ExecutionIntentV1,
) -> None:
    """Fail closed on workflow effects that lack an exact static cost derivation."""
    jobs = _mapping(workflow.get("jobs"), field_name="workflow.jobs")
    for raw_job_id, raw_job in jobs.items():
        job_id = _exact_text(raw_job_id, field_name="logical_job_id")
        job = _mapping(raw_job, field_name=f"workflow.jobs.{job_id}")
        unsupported_job = frozenset(job) - {
            "name",
            "needs",
            "runs-on",
            "steps",
            "strategy",
        }
        if unsupported_job:
            raise FreeExecutionAdmissionError("workflow job contains unsupported effect fields")
        if job.get("container") is not None or job.get("services") is not None:
            raise FreeExecutionAdmissionError(
                "workflow containers/services lack exact free-execution authority"
            )
        raw_steps = job.get("steps", [])
        if type(raw_steps) is not list:
            raise FreeExecutionAdmissionError("workflow job steps must be an exact array")
        for index, raw_step in enumerate(cast("list[object]", raw_steps)):
            step = _mapping(raw_step, field_name=f"workflow.jobs.{job_id}.steps[{index}]")
            if frozenset(step) - {"name", "run", "uses"}:
                raise FreeExecutionAdmissionError(
                    "workflow step contains unsupported effect fields"
                )
            uses = step.get("uses")
            run = step.get("run")
            if uses is not None and run is not None:
                raise FreeExecutionAdmissionError("workflow step cannot combine uses and run")
            if uses is not None:
                action = _exact_text(uses, field_name="workflow action")
                lowered = action.casefold()
                if "upload-artifact" in lowered or "/cache" in lowered:
                    raise FreeExecutionAdmissionError(
                        "workflow storage/cache liability lacks exact derivation"
                    )
                if _SAFE_CHECKOUT_ACTION_RE.fullmatch(action) is None:
                    raise FreeExecutionAdmissionError(
                        "workflow external action lacks reviewed free-execution authority"
                    )
                if step.get("with") not in (None, {}):
                    raise FreeExecutionAdmissionError(
                        "workflow action inputs lack exact free-execution derivation"
                    )
            elif run is not None:
                command = _exact_text(
                    run,
                    field_name="workflow run command",
                    maximum_bytes=_MAX_TEXT_BYTES,
                )
                if _SAFE_WORKFLOW_RUN_RE.fullmatch(command.strip()) is None:
                    raise FreeExecutionAdmissionError(
                        "workflow shell command lacks exact free-execution derivation"
                    )
            else:
                raise FreeExecutionAdmissionError("workflow step lacks an exact action or command")
    if (
        intent.planned_artifact_max_bytes != 0
        or intent.planned_artifact_retention_hours != 0
        or intent.planned_cache_max_bytes != 0
    ):
        raise FreeExecutionAdmissionError(
            "manifest resource plan differs from the exact zero-liability workflow surface"
        )


_WORKFLOW_EXPRESSION_RE = re.compile(r"\$\{\{.*?\}\}")
_SAFE_MATRIX_NAME_EXPRESSION_RE = re.compile(r"^\$\{\{\s*matrix\.[A-Za-z_][A-Za-z0-9_-]*\s*\}\}$")


def _validate_workflow_expressions(value: object) -> None:
    def visit(item: object) -> None:
        if type(item) is dict:
            for child in cast("dict[object, object]", item).values():
                visit(child)
            return
        if type(item) is list:
            for child in cast("list[object]", item):
                visit(child)
            return
        if type(item) is not str:
            return
        text = item
        matches = _WORKFLOW_EXPRESSION_RE.findall(text)
        if ("${{" in text or "}}" in text) and not matches:
            raise FreeExecutionAdmissionError("workflow contains an unbounded expression")
        for expression in matches:
            normalized = re.sub(r"\s+", "", expression).casefold()
            if normalized == "${{fromjson(needs.plan.outputs.github-matrix)}}":
                continue
            if _SAFE_MATRIX_NAME_EXPRESSION_RE.fullmatch(expression) is not None:
                continue
            raise FreeExecutionAdmissionError("workflow contains an unsupported expression")

    visit(value)


def _require_acyclic_jobs(jobs: tuple[WorkflowJobRequirementV1, ...]) -> None:
    dependencies = {job.logical_job_id: job.needs for job in jobs}
    visiting: set[str] = set()
    complete: set[str] = set()

    def visit(job_id: str) -> None:
        if job_id in complete:
            return
        if job_id in visiting:
            raise FreeExecutionAdmissionError("workflow job graph contains a dependency cycle")
        visiting.add(job_id)
        for dependency in dependencies[job_id]:
            visit(dependency)
        visiting.remove(job_id)
        complete.add(job_id)

    for job_id in dependencies:
        visit(job_id)


def _literal_matrix_instances(
    job_id: str,
    matrix: object,
    *,
    intent: ExecutionIntentV1,
) -> int:
    if type(matrix) is str:
        normalized = re.sub(r"\s+", "", matrix).casefold()
        if job_id == "extract" and normalized == "${{fromjson(needs.plan.outputs.github-matrix)}}":
            return intent.matrix_lane_count
        raise FreeExecutionAdmissionError("workflow has an unsupported dynamic matrix expression")
    if type(matrix) is not dict or not matrix:
        raise FreeExecutionAdmissionError("workflow matrix must be a nonempty literal object")
    mapping = cast("dict[object, object]", matrix)
    if any(type(key) is not str for key in mapping):
        raise FreeExecutionAdmissionError("workflow matrix keys must be strings")
    if set(mapping) == {"include"}:
        include = mapping["include"]
        if type(include) is not list:
            raise FreeExecutionAdmissionError("workflow matrix include must be an array")
        return len(include)
    if "include" in mapping or "exclude" in mapping:
        raise FreeExecutionAdmissionError("workflow mixed include/exclude matrices are unsupported")
    result = 1
    for key, values in mapping.items():
        if type(values) is not list or not values:
            raise FreeExecutionAdmissionError(f"workflow matrix {key} is not a nonempty array")
        result = _checked_multiply(result, len(values), field_name="workflow matrix instances")
    return result


@dataclass(frozen=True, slots=True)
class WorkflowJobRequirementV1:
    logical_job_id: str
    actual_name_prefix: str
    workflow_job_sha256: str
    runs_on_label: str
    runner_family: str
    needs: tuple[str, ...]
    maximum_instances: int
    provider_network_access: bool
    job_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        _exact_text(self.logical_job_id, field_name="logical_job_id")
        _exact_text(self.actual_name_prefix, field_name="actual_name_prefix")
        _sha256(self.workflow_job_sha256, field_name="workflow_job_sha256")
        if self.runs_on_label != _STANDARD_RUNNER_LABEL:
            raise FreeExecutionAdmissionError("workflow job runner is not literal ubuntu-latest")
        if self.runner_family != _STANDARD_RUNNER_FAMILY:
            raise FreeExecutionAdmissionError("workflow job runner family is unsupported")
        _tuple_text(self.needs, field_name="needs", sorted_unique=True)
        _uint(self.maximum_instances, field_name="maximum_instances")
        if self.provider_network_access is not True:
            raise FreeExecutionAdmissionError("job graph must conservatively mark network access")
        object.__setattr__(
            self,
            "job_sha256",
            _sealed_digest(
                self.job_sha256,
                identity=self._identity_dict(),
                field_name="workflow_job.job_sha256",
            ),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "logical_job_id": self.logical_job_id,
            "actual_name_prefix": self.actual_name_prefix,
            "workflow_job_sha256": self.workflow_job_sha256,
            "runs_on_label": self.runs_on_label,
            "runner_family": self.runner_family,
            "needs": list(self.needs),
            "maximum_instances": self.maximum_instances,
            "provider_network_access": self.provider_network_access,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "job_sha256": self.job_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "logical_job_id",
                "actual_name_prefix",
                "workflow_job_sha256",
                "runs_on_label",
                "runner_family",
                "needs",
                "maximum_instances",
                "provider_network_access",
                "job_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="workflow job")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("workflow job schema is unsupported")
        needs = payload["needs"]
        if type(needs) is not list:
            raise FreeExecutionAdmissionError("workflow job needs must be an array")
        return cls(
            logical_job_id=cast("str", payload["logical_job_id"]),
            actual_name_prefix=cast("str", payload["actual_name_prefix"]),
            workflow_job_sha256=cast("str", payload["workflow_job_sha256"]),
            runs_on_label=cast("str", payload["runs_on_label"]),
            runner_family=cast("str", payload["runner_family"]),
            needs=tuple(_exact_text(item, field_name="needs") for item in needs),
            maximum_instances=cast("int", payload["maximum_instances"]),
            provider_network_access=cast("bool", payload["provider_network_access"]),
            job_sha256=cast("str", payload["job_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class JobGraphEvidenceV1:
    source_sha: str
    workflow_path: str
    workflow_sha256: str
    intent_sha256: str
    jobs: tuple[WorkflowJobRequirementV1, ...]
    maximum_total_jobs: int
    maximum_concurrent_jobs: int
    evidence_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        _source_sha(self.source_sha)
        _workflow_path(self.workflow_path)
        _sha256(self.workflow_sha256, field_name="workflow_sha256")
        _sha256(self.intent_sha256, field_name="intent_sha256")
        if type(self.jobs) is not tuple or not self.jobs or len(self.jobs) > 1_000:
            raise FreeExecutionAdmissionError("job graph must be a bounded nonempty tuple")
        if any(type(item) is not WorkflowJobRequirementV1 for item in self.jobs):
            raise FreeExecutionAdmissionError("job graph contains foreign rows")
        jobs = tuple(WorkflowJobRequirementV1.from_dict(item.to_dict()) for item in self.jobs)
        object.__setattr__(self, "jobs", jobs)
        ids = tuple(item.logical_job_id for item in jobs)
        if ids != tuple(sorted(set(ids))):
            raise FreeExecutionAdmissionError("job graph identities must be sorted and unique")
        if any(dependency not in set(ids) for job in jobs for dependency in job.needs):
            raise FreeExecutionAdmissionError("job graph contains a foreign dependency")
        _require_acyclic_jobs(jobs)
        total = 0
        for job in jobs:
            total = _checked_add(total, job.maximum_instances, field_name="maximum_total_jobs")
        if self.maximum_total_jobs != total:
            raise FreeExecutionAdmissionError("maximum_total_jobs differs from the parsed graph")
        if self.maximum_concurrent_jobs != total:
            raise FreeExecutionAdmissionError(
                "maximum_concurrent_jobs must use the conservative complete bound"
            )
        object.__setattr__(
            self,
            "evidence_sha256",
            _sealed_digest(
                self.evidence_sha256,
                identity=self._identity_dict(),
                field_name="job_graph.evidence_sha256",
            ),
        )

    @classmethod
    def from_workflow_bytes(
        cls,
        workflow_bytes: bytes,
        *,
        intent: ExecutionIntentV1,
    ) -> Self:
        workflow_sha256 = hashlib.sha256(workflow_bytes).hexdigest()
        if workflow_sha256 != intent.workflow_sha256:
            raise FreeExecutionAdmissionError("workflow bytes differ from execution intent")
        workflow = _load_workflow(workflow_bytes)
        _validate_workflow_action_surface(workflow, intent=intent)
        raw_jobs = workflow.get("jobs")
        if type(raw_jobs) is not dict or not raw_jobs:
            raise FreeExecutionAdmissionError("workflow jobs must be a nonempty object")
        jobs: list[WorkflowJobRequirementV1] = []
        for raw_job_id, raw_job in cast("dict[object, object]", raw_jobs).items():
            job_id = _exact_text(raw_job_id, field_name="logical_job_id")
            job = _mapping(raw_job, field_name=f"jobs.{job_id}")
            if "uses" in job:
                raise FreeExecutionAdmissionError("reusable workflow jobs are unsupported")
            runs_on = job.get("runs-on")
            if type(runs_on) is not str or "${{" in runs_on:
                raise FreeExecutionAdmissionError(
                    "dynamic or nonliteral runner selectors are forbidden"
                )
            if runs_on != _STANDARD_RUNNER_LABEL:
                raise FreeExecutionAdmissionError("only literal ubuntu-latest jobs are supported")
            raw_name = job.get("name", job_id)
            if type(raw_name) is not str:
                raise FreeExecutionAdmissionError("workflow job name must be literal text")
            prefix = raw_name.split("${{", maxsplit=1)[0].strip()
            if not prefix:
                raise FreeExecutionAdmissionError("dynamic workflow job name lacks an exact prefix")
            raw_needs = job.get("needs", [])
            if type(raw_needs) is str:
                needs = (raw_needs,)
            elif type(raw_needs) is list and all(type(item) is str for item in raw_needs):
                needs = tuple(cast("list[str]", raw_needs))
            else:
                raise FreeExecutionAdmissionError("workflow job dependencies are not literal")
            if any("${{" in item for item in needs):
                raise FreeExecutionAdmissionError("dynamic workflow dependencies are forbidden")
            strategy = job.get("strategy")
            instances = 1
            if strategy is not None:
                strategy_mapping = _mapping(strategy, field_name=f"jobs.{job_id}.strategy")
                unsupported = frozenset(strategy_mapping) - {
                    "matrix",
                    "fail-fast",
                    "max-parallel",
                }
                if unsupported or "matrix" not in strategy_mapping:
                    raise FreeExecutionAdmissionError("workflow strategy is unsupported")
                if (
                    "max-parallel" in strategy_mapping
                    and type(strategy_mapping["max-parallel"]) is not int
                ):
                    raise FreeExecutionAdmissionError("dynamic max-parallel is unsupported")
                instances = _literal_matrix_instances(
                    job_id,
                    strategy_mapping["matrix"],
                    intent=intent,
                )
            jobs.append(
                WorkflowJobRequirementV1(
                    logical_job_id=job_id,
                    actual_name_prefix=prefix,
                    workflow_job_sha256=_canonical_sha256(dict(job)),
                    runs_on_label=runs_on,
                    runner_family=_STANDARD_RUNNER_FAMILY,
                    needs=tuple(sorted(set(needs))),
                    maximum_instances=instances,
                    provider_network_access=True,
                )
            )
        ordered = tuple(sorted(jobs, key=lambda item: item.logical_job_id))
        total = sum(item.maximum_instances for item in ordered)
        return cls(
            source_sha=intent.source_sha,
            workflow_path=intent.workflow_path,
            workflow_sha256=workflow_sha256,
            intent_sha256=intent.intent_sha256,
            jobs=ordered,
            maximum_total_jobs=total,
            maximum_concurrent_jobs=total,
        )

    def rederive(self, workflow_bytes: bytes, *, intent: ExecutionIntentV1) -> None:
        expected = type(self).from_workflow_bytes(workflow_bytes, intent=intent)
        if expected != self:
            raise FreeExecutionAdmissionError("job graph differs from exact workflow bytes")

    @property
    def provider_capacity(self) -> int:
        return sum(item.maximum_instances for item in self.jobs if item.provider_network_access)

    def job(self, logical_job_id: str) -> WorkflowJobRequirementV1:
        matches = tuple(item for item in self.jobs if item.logical_job_id == logical_job_id)
        if len(matches) != 1:
            raise FreeExecutionAdmissionError("logical job is absent or ambiguous")
        return matches[0]

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_sha": self.source_sha,
            "workflow_path": self.workflow_path,
            "workflow_sha256": self.workflow_sha256,
            "intent_sha256": self.intent_sha256,
            "jobs": [item.to_dict() for item in self.jobs],
            "maximum_total_jobs": self.maximum_total_jobs,
            "maximum_concurrent_jobs": self.maximum_concurrent_jobs,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "evidence_sha256": self.evidence_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "source_sha",
                "workflow_path",
                "workflow_sha256",
                "intent_sha256",
                "jobs",
                "maximum_total_jobs",
                "maximum_concurrent_jobs",
                "evidence_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="job graph")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("job graph schema is unsupported")
        raw_jobs = payload["jobs"]
        if type(raw_jobs) is not list:
            raise FreeExecutionAdmissionError("job graph jobs must be an array")
        return cls(
            source_sha=cast("str", payload["source_sha"]),
            workflow_path=cast("str", payload["workflow_path"]),
            workflow_sha256=cast("str", payload["workflow_sha256"]),
            intent_sha256=cast("str", payload["intent_sha256"]),
            jobs=tuple(
                WorkflowJobRequirementV1.from_dict(_mapping(item, field_name=f"jobs[{index}]"))
                for index, item in enumerate(cast("list[object]", raw_jobs))
            ),
            maximum_total_jobs=cast("int", payload["maximum_total_jobs"]),
            maximum_concurrent_jobs=cast("int", payload["maximum_concurrent_jobs"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


def _require_github_response(response: ExactHttpResponseV1, *, url: str) -> None:
    if type(response) is not ExactHttpResponseV1:
        raise FreeExecutionAdmissionError("GitHub response authority is foreign")
    response.validate_seal()
    if response.url != url:
        raise FreeExecutionAdmissionError("GitHub response URL is foreign")
    if response.api_version != _GITHUB_API_VERSION:
        raise FreeExecutionAdmissionError("GitHub API version is unsupported")
    if response.etag is None:
        raise FreeExecutionAdmissionError("GitHub response lacks an exact ETag")


def _owner_identity(owner: Mapping[str, object]) -> tuple[int, str, str, str]:
    _require_exact_keys(
        owner,
        expected=frozenset({"id", "login", "type"}),
        label="repository owner",
    )
    owner_id = _uint(owner["id"], field_name="owner.id", positive=True)
    login = _exact_text(owner["login"], field_name="owner.login")
    owner_type = _exact_text(owner["type"], field_name="owner.type")
    if owner_type not in {"Organization", "User"}:
        raise FreeExecutionAdmissionError("repository owner type is unsupported")
    identity = _canonical_sha256({"id": owner_id, "login": login, "type": owner_type})
    return owner_id, login, owner_type, identity


def _reviewed_zero_cost_policy(
    response: ExactHttpResponseV1,
    *,
    expected_url: str,
    expected_rule_id: str,
    expected_service_kind: str,
) -> Mapping[str, object]:
    """Parse one exact structured policy edition; free-text inference is forbidden."""
    if response.url != expected_url or response.api_version is not None or response.etag is None:
        raise FreeExecutionAdmissionError("reviewed zero-cost authority identity is foreign")
    response.validate_seal()
    payload = response.json_object()
    _require_exact_keys(
        payload,
        expected=frozenset(
            {
                "schema_version",
                "authority_kind",
                "service_kind",
                "authority_url",
                "authority_rule_id",
                "maximum_incremental_charge_microusd",
                "effective_at",
                "expires_at",
                "qualified_review_sha256",
            }
        ),
        label="reviewed zero-cost policy",
    )
    if (
        payload["schema_version"] != 1
        or type(payload["schema_version"]) is not int
        or payload["authority_kind"] != "reviewed_zero_incremental_charge_v1"
        or payload["service_kind"] != expected_service_kind
        or payload["authority_url"] != expected_url
        or payload["authority_rule_id"] != expected_rule_id
        or payload["maximum_incremental_charge_microusd"] != 0
    ):
        raise FreeExecutionAdmissionError("reviewed zero-cost policy fields are invalid")
    _sha256(payload["qualified_review_sha256"], field_name="qualified_review_sha256")
    effective = _timestamp(payload["effective_at"], field_name="policy.effective_at")
    expires = _timestamp(payload["expires_at"], field_name="policy.expires_at")
    if not effective <= response.observed_at < expires:
        raise FreeExecutionAdmissionError("reviewed zero-cost policy edition is stale")
    return payload


@dataclass(frozen=True, slots=True)
class RepositoryPricingEvidenceV1:
    repository_id: int
    repository: str
    owner_id: int
    owner_login: str
    owner_type: str
    owner_identity_sha256: str
    repository_response_sha256: str
    repository_etag: str
    pricing_document_sha256: str
    pricing_document_etag: str
    pricing_rule_id: str
    maximum_compute_charge_microusd: int
    readback_at: str
    expires_at: str
    evidence_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        _uint(self.repository_id, field_name="repository_id", positive=True)
        repository = _exact_text(self.repository, field_name="repository")
        if repository != f"{self.owner_login}/{repository.split('/', maxsplit=1)[-1]}":
            raise FreeExecutionAdmissionError("repository owner identity is inconsistent")
        _uint(self.owner_id, field_name="owner_id", positive=True)
        _exact_text(self.owner_login, field_name="owner_login")
        if self.owner_type not in {"Organization", "User"}:
            raise FreeExecutionAdmissionError("owner_type is unsupported")
        for name in (
            "owner_identity_sha256",
            "repository_response_sha256",
            "pricing_document_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        _exact_text(self.repository_etag, field_name="repository_etag")
        _exact_text(self.pricing_document_etag, field_name="pricing_document_etag")
        if self.pricing_rule_id != _PRICING_RULE_ID:
            raise FreeExecutionAdmissionError("pricing rule is unsupported")
        if _uint(
            self.maximum_compute_charge_microusd,
            field_name="maximum_compute_charge_microusd",
        ):
            raise FreeExecutionAdmissionError("repository pricing permits a charge")
        readback = _timestamp(self.readback_at, field_name="repository_pricing.readback_at")
        expires = _timestamp(self.expires_at, field_name="repository_pricing.expires_at")
        if (
            not readback < expires
            or (expires - readback).total_seconds() > _MAX_EVIDENCE_TTL_SECONDS
        ):
            raise FreeExecutionAdmissionError("repository pricing freshness is invalid")
        object.__setattr__(
            self,
            "evidence_sha256",
            _sealed_digest(
                self.evidence_sha256,
                identity=self._identity_dict(),
                field_name="repository_pricing.evidence_sha256",
            ),
        )

    @classmethod
    def from_authority(
        cls,
        *,
        repository: str,
        repository_response: ExactHttpResponseV1,
        pricing_response: ExactHttpResponseV1,
        expires_at: str,
    ) -> Self:
        _require_github_response(
            repository_response,
            url=f"https://api.github.com/repos/{repository}",
        )
        payload = repository_response.json_object()
        required = {
            "id",
            "full_name",
            "owner",
            "private",
            "visibility",
            "archived",
            "disabled",
        }
        if not required.issubset(payload):
            raise FreeExecutionAdmissionError("repository response omits required fields")
        if payload["full_name"] != repository:
            raise FreeExecutionAdmissionError("repository response identity is foreign")
        if (
            payload["private"] is not False
            or payload["visibility"] != "public"
            or payload["archived"] is not False
            or payload["disabled"] is not False
        ):
            raise FreeExecutionAdmissionError("repository is not an active exact public repository")
        owner_id, owner_login, owner_type, owner_sha = _owner_identity(
            _mapping(payload["owner"], field_name="owner")
        )
        if repository.split("/", maxsplit=1)[0] != owner_login:
            raise FreeExecutionAdmissionError("repository owner login is foreign")
        _reviewed_zero_cost_policy(
            pricing_response,
            expected_url=_PRICING_DOCUMENT_URL,
            expected_rule_id=_PRICING_RULE_ID,
            expected_service_kind="github_actions_compute",
        )
        readback = max(repository_response.observed_at, pricing_response.observed_at)
        expires = _timestamp(expires_at, field_name="repository_pricing.expires_at")
        if not readback < expires:
            raise FreeExecutionAdmissionError("repository pricing expiry precedes readback")
        return cls(
            repository_id=_uint(payload["id"], field_name="repository.id", positive=True),
            repository=repository,
            owner_id=owner_id,
            owner_login=owner_login,
            owner_type=owner_type,
            owner_identity_sha256=owner_sha,
            repository_response_sha256=repository_response.body_sha256,
            repository_etag=cast("str", repository_response.etag),
            pricing_document_sha256=pricing_response.body_sha256,
            pricing_document_etag=cast("str", pricing_response.etag),
            pricing_rule_id=_PRICING_RULE_ID,
            maximum_compute_charge_microusd=0,
            readback_at=readback.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_at=expires_at,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "repository_id": self.repository_id,
            "repository": self.repository,
            "owner_id": self.owner_id,
            "owner_login": self.owner_login,
            "owner_type": self.owner_type,
            "owner_identity_sha256": self.owner_identity_sha256,
            "repository_response_sha256": self.repository_response_sha256,
            "repository_etag": self.repository_etag,
            "pricing_document_sha256": self.pricing_document_sha256,
            "pricing_document_etag": self.pricing_document_etag,
            "pricing_rule_id": self.pricing_rule_id,
            "maximum_compute_charge_microusd": self.maximum_compute_charge_microusd,
            "readback_at": self.readback_at,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "evidence_sha256": self.evidence_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "repository_id",
                "repository",
                "owner_id",
                "owner_login",
                "owner_type",
                "owner_identity_sha256",
                "repository_response_sha256",
                "repository_etag",
                "pricing_document_sha256",
                "pricing_document_etag",
                "pricing_rule_id",
                "maximum_compute_charge_microusd",
                "readback_at",
                "expires_at",
                "evidence_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="repository pricing evidence")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("repository pricing schema is unsupported")
        return cls(
            repository_id=cast("int", payload["repository_id"]),
            repository=cast("str", payload["repository"]),
            owner_id=cast("int", payload["owner_id"]),
            owner_login=cast("str", payload["owner_login"]),
            owner_type=cast("str", payload["owner_type"]),
            owner_identity_sha256=cast("str", payload["owner_identity_sha256"]),
            repository_response_sha256=cast("str", payload["repository_response_sha256"]),
            repository_etag=cast("str", payload["repository_etag"]),
            pricing_document_sha256=cast("str", payload["pricing_document_sha256"]),
            pricing_document_etag=cast("str", payload["pricing_document_etag"]),
            pricing_rule_id=cast("str", payload["pricing_rule_id"]),
            maximum_compute_charge_microusd=cast("int", payload["maximum_compute_charge_microusd"]),
            readback_at=cast("str", payload["readback_at"]),
            expires_at=cast("str", payload["expires_at"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


def _account_url(owner_type: str, owner_login: str) -> str:
    namespace = "orgs" if owner_type == "Organization" else "users"
    return f"https://api.github.com/{namespace}/{owner_login}/settings/billing/usage"


def _parse_account(payload: Mapping[str, object]) -> tuple[int, str, str, str]:
    return _owner_identity(_mapping(payload.get("account"), field_name="account"))


def _storage_items(
    payload: Mapping[str, object],
    *,
    at: datetime,
    month_end: datetime,
) -> tuple[int, int, int, int]:
    section = _mapping(payload.get("artifact_packages"), field_name="artifact_packages")
    _require_exact_keys(
        section,
        expected=frozenset({"accrued_byte_hours", "items"}),
        label="artifact_packages",
    )
    items = section["items"]
    if type(items) is not list or len(items) > _MAX_SEQUENCE_ITEMS:
        raise FreeExecutionAdmissionError("artifact/Packages inventory must be an array")
    current_bytes = 0
    future = 0
    ids: set[tuple[str, int]] = set()
    for index, raw_item in enumerate(cast("list[object]", items)):
        item = _mapping(raw_item, field_name=f"artifact_packages.items[{index}]")
        _require_exact_keys(
            item,
            expected=frozenset({"id", "kind", "size_bytes", "expires_at"}),
            label="artifact/Packages item",
        )
        item_id = _uint(item["id"], field_name="item.id", positive=True)
        kind = _exact_text(item["kind"], field_name="item.kind")
        if kind not in {"artifact", "package"} or (kind, item_id) in ids:
            raise FreeExecutionAdmissionError("artifact/Packages identity is invalid or duplicated")
        ids.add((kind, item_id))
        size = _uint(item["size_bytes"], field_name="item.size_bytes")
        current_bytes = _checked_add(current_bytes, size, field_name="current storage bytes")
        raw_expiry = item["expires_at"]
        if raw_expiry is None:
            raise FreeExecutionAdmissionError(
                "artifact/Packages item has unresolved future retention liability"
            )
        expiry = _timestamp(raw_expiry, field_name="item.expires_at")
        if expiry > month_end:
            raise FreeExecutionAdmissionError(
                "artifact/Packages item crosses an unverified future billing period"
            )
        hours = _ceil_hours(at, expiry)
        future = _checked_add(
            future,
            _checked_multiply(size, hours, field_name="existing future byte-hours"),
            field_name="existing future byte-hours",
        )
    accrued = _uint(
        section["accrued_byte_hours"],
        field_name="artifact_packages.accrued_byte_hours",
    )
    return len(items), current_bytes, accrued, future


@dataclass(frozen=True, slots=True)
class StorageCostEvidenceV1:
    account_identity_sha256: str
    inventory_response_sha256: str
    cache_first_response_sha256: str
    cache_stable_response_sha256: str
    billing_response_sha256: str
    billing_period_start: str
    billing_period_end: str
    billing_period_hours: int
    billing_period_remaining_hours: int
    existing_item_count: int
    artifact_packages_current_bytes: int
    artifact_packages_accrued_byte_hours: int
    artifact_packages_existing_future_byte_hours: int
    planned_artifact_max_bytes: int
    planned_artifact_retention_hours: int
    planned_artifact_max_byte_hours: int
    artifact_packages_free_byte_hours: int
    cache_current_bytes: int
    planned_cache_max_bytes: int
    maximum_incremental_charge_microusd: int
    readback_at: str
    expires_at: str
    evidence_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        for name in (
            "account_identity_sha256",
            "inventory_response_sha256",
            "cache_first_response_sha256",
            "cache_stable_response_sha256",
            "billing_response_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        start = _timestamp(self.billing_period_start, field_name="billing_period_start")
        end = _timestamp(self.billing_period_end, field_name="billing_period_end")
        readback = _timestamp(self.readback_at, field_name="storage.readback_at")
        expires = _timestamp(self.expires_at, field_name="storage.expires_at")
        derived_start, derived_end, hours, remaining = _billing_window(readback)
        if (start, end, self.billing_period_hours, self.billing_period_remaining_hours) != (
            derived_start,
            derived_end,
            hours,
            remaining,
        ):
            raise FreeExecutionAdmissionError(
                "storage billing calendar is not independently derived"
            )
        item_count = _uint(self.existing_item_count, field_name="existing_item_count")
        del item_count
        current = _uint(
            self.artifact_packages_current_bytes,
            field_name="artifact_packages_current_bytes",
        )
        accrued = _uint(
            self.artifact_packages_accrued_byte_hours,
            field_name="artifact_packages_accrued_byte_hours",
        )
        existing_future = _uint(
            self.artifact_packages_existing_future_byte_hours,
            field_name="artifact_packages_existing_future_byte_hours",
        )
        planned = _uint(self.planned_artifact_max_bytes, field_name="planned_artifact_max_bytes")
        retention = _uint(
            self.planned_artifact_retention_hours,
            field_name="planned_artifact_retention_hours",
            positive=planned > 0,
        )
        if retention > remaining or (planned == 0 and retention != 0):
            raise FreeExecutionAdmissionError("planned artifact retention is invalid")
        planned_hours = _checked_multiply(planned, retention, field_name="planned byte-hours")
        if self.planned_artifact_max_byte_hours != planned_hours:
            raise FreeExecutionAdmissionError("planned artifact byte-hours are invalid")
        free_hours = _checked_multiply(
            ARTIFACT_PACKAGES_FREE_FLOOR_BYTES,
            hours,
            field_name="free byte-hours",
        )
        if self.artifact_packages_free_byte_hours != free_hours:
            raise FreeExecutionAdmissionError("free artifact/Packages byte-hours are invalid")
        if (
            _checked_add(current, planned, field_name="storage bytes")
            > ARTIFACT_PACKAGES_FREE_FLOOR_BYTES
        ):
            raise FreeExecutionAdmissionError("artifact/Packages current headroom is insufficient")
        total_liability = _checked_add(accrued, existing_future, field_name="storage liability")
        total_liability = _checked_add(
            total_liability, planned_hours, field_name="storage liability"
        )
        if total_liability > free_hours:
            raise FreeExecutionAdmissionError(
                "artifact/Packages calendar liability exceeds free usage"
            )
        cache = _uint(self.cache_current_bytes, field_name="cache_current_bytes")
        planned_cache = _uint(self.planned_cache_max_bytes, field_name="planned_cache_max_bytes")
        if _checked_add(cache, planned_cache, field_name="cache bytes") > CACHE_FREE_FLOOR_BYTES:
            raise FreeExecutionAdmissionError("cache headroom is insufficient")
        if _uint(
            self.maximum_incremental_charge_microusd,
            field_name="maximum_incremental_charge_microusd",
        ):
            raise FreeExecutionAdmissionError("storage authority permits a charge")
        if (
            not readback < expires
            or (expires - readback).total_seconds() > _MAX_EVIDENCE_TTL_SECONDS
        ):
            raise FreeExecutionAdmissionError("storage evidence freshness is invalid")
        object.__setattr__(
            self,
            "evidence_sha256",
            _sealed_digest(
                self.evidence_sha256,
                identity=self._identity_dict(),
                field_name="storage.evidence_sha256",
            ),
        )

    @classmethod
    def from_authority(
        cls,
        *,
        repository_pricing: RepositoryPricingEvidenceV1,
        intent: ExecutionIntentV1,
        inventory_response: ExactHttpResponseV1,
        cache_first_response: ExactHttpResponseV1,
        cache_stable_response: ExactHttpResponseV1,
        billing_response: ExactHttpResponseV1,
        expires_at: str,
    ) -> Self:
        account_url = _account_url(
            repository_pricing.owner_type,
            repository_pricing.owner_login,
        )
        _require_github_response(inventory_response, url=account_url)
        _require_github_response(billing_response, url=account_url)
        cache_url = (
            f"https://api.github.com/repos/{repository_pricing.repository}/actions/cache/usage"
        )
        _require_github_response(cache_first_response, url=cache_url)
        _require_github_response(cache_stable_response, url=cache_url)
        inventory = inventory_response.json_object()
        billing = billing_response.json_object()
        expected_owner = (
            repository_pricing.owner_id,
            repository_pricing.owner_login,
            repository_pricing.owner_type,
            repository_pricing.owner_identity_sha256,
        )
        if _parse_account(inventory) != expected_owner or _parse_account(billing) != expected_owner:
            raise FreeExecutionAdmissionError("storage account authority is foreign")
        _require_exact_keys(
            billing,
            expected=frozenset(
                {"account", "incremental_charge_microusd", "settled", "overlap_absent"}
            ),
            label="billing usage",
        )
        if (
            billing["incremental_charge_microusd"] != 0
            or billing["settled"] is not True
            or billing["overlap_absent"] is not True
        ):
            raise FreeExecutionAdmissionError("billing usage is charged, unsettled, or overlapping")
        first_cache = cache_first_response.json_object()
        stable_cache = cache_stable_response.json_object()
        cache_fields = frozenset({"active_caches_count", "active_caches_size_in_bytes"})
        _require_exact_keys(first_cache, expected=cache_fields, label="cache usage")
        _require_exact_keys(stable_cache, expected=cache_fields, label="cache usage")
        if first_cache != stable_cache:
            raise FreeExecutionAdmissionError("cache usage values did not stabilize")
        if (
            cache_stable_response.observed_at - cache_first_response.observed_at
        ).total_seconds() < _MIN_STABILITY_SECONDS:
            raise FreeExecutionAdmissionError("cache usage repeat window is too short")
        readback = max(
            inventory_response.observed_at,
            cache_stable_response.observed_at,
            billing_response.observed_at,
        )
        start, end, period_hours, remaining = _billing_window(readback)
        item_count, current, accrued, existing_future = _storage_items(
            inventory,
            at=readback,
            month_end=end,
        )
        planned_hours = _checked_multiply(
            intent.planned_artifact_max_bytes,
            intent.planned_artifact_retention_hours,
            field_name="planned byte-hours",
        )
        return cls(
            account_identity_sha256=repository_pricing.owner_identity_sha256,
            inventory_response_sha256=inventory_response.body_sha256,
            cache_first_response_sha256=cache_first_response.body_sha256,
            cache_stable_response_sha256=cache_stable_response.body_sha256,
            billing_response_sha256=billing_response.body_sha256,
            billing_period_start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            billing_period_end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            billing_period_hours=period_hours,
            billing_period_remaining_hours=remaining,
            existing_item_count=item_count,
            artifact_packages_current_bytes=current,
            artifact_packages_accrued_byte_hours=accrued,
            artifact_packages_existing_future_byte_hours=existing_future,
            planned_artifact_max_bytes=intent.planned_artifact_max_bytes,
            planned_artifact_retention_hours=intent.planned_artifact_retention_hours,
            planned_artifact_max_byte_hours=planned_hours,
            artifact_packages_free_byte_hours=_checked_multiply(
                ARTIFACT_PACKAGES_FREE_FLOOR_BYTES,
                period_hours,
                field_name="free byte-hours",
            ),
            cache_current_bytes=_uint(
                stable_cache["active_caches_size_in_bytes"],
                field_name="active_caches_size_in_bytes",
            ),
            planned_cache_max_bytes=intent.planned_cache_max_bytes,
            maximum_incremental_charge_microusd=0,
            readback_at=readback.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires_at=expires_at,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{
                name: getattr(self, name)
                for name in (
                    "account_identity_sha256",
                    "inventory_response_sha256",
                    "cache_first_response_sha256",
                    "cache_stable_response_sha256",
                    "billing_response_sha256",
                    "billing_period_start",
                    "billing_period_end",
                    "billing_period_hours",
                    "billing_period_remaining_hours",
                    "existing_item_count",
                    "artifact_packages_current_bytes",
                    "artifact_packages_accrued_byte_hours",
                    "artifact_packages_existing_future_byte_hours",
                    "planned_artifact_max_bytes",
                    "planned_artifact_retention_hours",
                    "planned_artifact_max_byte_hours",
                    "artifact_packages_free_byte_hours",
                    "cache_current_bytes",
                    "planned_cache_max_bytes",
                    "maximum_incremental_charge_microusd",
                    "readback_at",
                    "expires_at",
                )
            },
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "evidence_sha256": self.evidence_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        fields = frozenset(cls.__dataclass_fields__) - {"schema_version"}
        _require_exact_keys(payload, expected=fields | {"schema_version"}, label="storage evidence")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("storage evidence schema is unsupported")
        return cls(
            account_identity_sha256=cast("str", payload["account_identity_sha256"]),
            inventory_response_sha256=cast("str", payload["inventory_response_sha256"]),
            cache_first_response_sha256=cast("str", payload["cache_first_response_sha256"]),
            cache_stable_response_sha256=cast("str", payload["cache_stable_response_sha256"]),
            billing_response_sha256=cast("str", payload["billing_response_sha256"]),
            billing_period_start=cast("str", payload["billing_period_start"]),
            billing_period_end=cast("str", payload["billing_period_end"]),
            billing_period_hours=cast("int", payload["billing_period_hours"]),
            billing_period_remaining_hours=cast("int", payload["billing_period_remaining_hours"]),
            existing_item_count=cast("int", payload["existing_item_count"]),
            artifact_packages_current_bytes=cast("int", payload["artifact_packages_current_bytes"]),
            artifact_packages_accrued_byte_hours=cast(
                "int", payload["artifact_packages_accrued_byte_hours"]
            ),
            artifact_packages_existing_future_byte_hours=cast(
                "int", payload["artifact_packages_existing_future_byte_hours"]
            ),
            planned_artifact_max_bytes=cast("int", payload["planned_artifact_max_bytes"]),
            planned_artifact_retention_hours=cast(
                "int", payload["planned_artifact_retention_hours"]
            ),
            planned_artifact_max_byte_hours=cast("int", payload["planned_artifact_max_byte_hours"]),
            artifact_packages_free_byte_hours=cast(
                "int", payload["artifact_packages_free_byte_hours"]
            ),
            cache_current_bytes=cast("int", payload["cache_current_bytes"]),
            planned_cache_max_bytes=cast("int", payload["planned_cache_max_bytes"]),
            maximum_incremental_charge_microusd=cast(
                "int", payload["maximum_incremental_charge_microusd"]
            ),
            readback_at=cast("str", payload["readback_at"]),
            expires_at=cast("str", payload["expires_at"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


_EXTERNAL_AUTHORITY = {
    ExternalServiceKind.GITHUB_NETWORK_EGRESS: (
        _PRICING_DOCUMENT_URL,
        "github_public_network_egress_zero_incremental_charge_v1",
        "github_network_egress",
    ),
    ExternalServiceKind.NBA_API: (
        "https://www.nba.com/termsofuse",
        "nba_public_api_zero_incremental_charge_v1",
        "nba_api",
    ),
    ExternalServiceKind.KAGGLE: (
        "https://www.kaggle.com/docs/api",
        "kaggle_public_api_zero_incremental_charge_v1",
        "kaggle",
    ),
}


@dataclass(frozen=True, slots=True)
class ExternalServiceCostEvidenceV1:
    """Public summary derived from one exact private service-authority response."""

    service_kind: ExternalServiceKind
    authority_url: str
    authority_rule_id: str
    authority_response_sha256: str
    authority_etag: str
    maximum_incremental_charge_microusd: int
    readback_at: str
    expires_at: str
    evidence_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        if type(self.service_kind) is not ExternalServiceKind:
            raise FreeExecutionAdmissionError("external service kind is invalid")
        expected_url, expected_rule, _ = _EXTERNAL_AUTHORITY[self.service_kind]
        if self.authority_url != expected_url or self.authority_rule_id != expected_rule:
            raise FreeExecutionAdmissionError("external service authority identity is foreign")
        _sha256(self.authority_response_sha256, field_name="authority_response_sha256")
        _exact_text(self.authority_etag, field_name="authority_etag")
        if _uint(
            self.maximum_incremental_charge_microusd,
            field_name="maximum_incremental_charge_microusd",
        ):
            raise FreeExecutionAdmissionError("external authority permits an incremental charge")
        readback = _timestamp(self.readback_at, field_name="external.readback_at")
        expires = _timestamp(self.expires_at, field_name="external.expires_at")
        if (
            not readback < expires
            or (expires - readback).total_seconds() > _MAX_EVIDENCE_TTL_SECONDS
        ):
            raise FreeExecutionAdmissionError("external authority freshness is invalid")
        object.__setattr__(
            self,
            "evidence_sha256",
            _sealed_digest(
                self.evidence_sha256,
                identity=self._identity_dict(),
                field_name="external.evidence_sha256",
            ),
        )

    @classmethod
    def from_authority(
        cls,
        *,
        service_kind: ExternalServiceKind,
        response: ExactHttpResponseV1,
        expires_at: str,
    ) -> Self:
        if type(service_kind) is not ExternalServiceKind:
            raise FreeExecutionAdmissionError("external service kind is invalid")
        expected_url, rule, service_name = _EXTERNAL_AUTHORITY[service_kind]
        _reviewed_zero_cost_policy(
            response,
            expected_url=expected_url,
            expected_rule_id=rule,
            expected_service_kind=service_name,
        )
        return cls(
            service_kind=service_kind,
            authority_url=expected_url,
            authority_rule_id=rule,
            authority_response_sha256=response.body_sha256,
            authority_etag=cast("str", response.etag),
            maximum_incremental_charge_microusd=0,
            readback_at=response.response_date,
            expires_at=expires_at,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "service_kind": self.service_kind.value,
            "authority_url": self.authority_url,
            "authority_rule_id": self.authority_rule_id,
            "authority_response_sha256": self.authority_response_sha256,
            "authority_etag": self.authority_etag,
            "maximum_incremental_charge_microusd": (self.maximum_incremental_charge_microusd),
            "readback_at": self.readback_at,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "evidence_sha256": self.evidence_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "service_kind",
                "authority_url",
                "authority_rule_id",
                "authority_response_sha256",
                "authority_etag",
                "maximum_incremental_charge_microusd",
                "readback_at",
                "expires_at",
                "evidence_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="external service evidence")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("external evidence schema is unsupported")
        try:
            service_kind = ExternalServiceKind(
                _exact_text(payload["service_kind"], field_name="service_kind")
            )
        except ValueError as exc:
            raise FreeExecutionAdmissionError("external service kind is unsupported") from exc
        return cls(
            service_kind=service_kind,
            authority_url=cast("str", payload["authority_url"]),
            authority_rule_id=cast("str", payload["authority_rule_id"]),
            authority_response_sha256=cast("str", payload["authority_response_sha256"]),
            authority_etag=cast("str", payload["authority_etag"]),
            maximum_incremental_charge_microusd=cast(
                "int", payload["maximum_incremental_charge_microusd"]
            ),
            readback_at=cast("str", payload["readback_at"]),
            expires_at=cast("str", payload["expires_at"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class FreeExecutionAuthorityBundleV1:
    """Private raw authority required to construct or replay a positive admission."""

    workflow_bytes: bytes = field(repr=False)
    manifest_bytes: bytes = field(repr=False)
    execution_context_response: ExactHttpResponseV1 = field(repr=False)
    repository_response: ExactHttpResponseV1 = field(repr=False)
    pricing_response: ExactHttpResponseV1 = field(repr=False)
    storage_inventory_response: ExactHttpResponseV1 = field(repr=False)
    cache_first_response: ExactHttpResponseV1 = field(repr=False)
    cache_stable_response: ExactHttpResponseV1 = field(repr=False)
    billing_response: ExactHttpResponseV1 = field(repr=False)
    external_responses: tuple[tuple[ExternalServiceKind, ExactHttpResponseV1], ...] = field(
        repr=False
    )

    schema_version: ClassVar[int] = 1
    integration_blocker_codes: ClassVar[tuple[str, ...]] = _ADMISSION_INTEGRATION_BLOCKERS

    def __post_init__(self) -> None:
        if type(self.workflow_bytes) is not bytes or type(self.manifest_bytes) is not bytes:
            raise FreeExecutionAdmissionError("raw workflow and manifest authority must be bytes")
        if any(
            type(item) is not ExactHttpResponseV1
            for item in (
                self.repository_response,
                self.execution_context_response,
                self.pricing_response,
                self.storage_inventory_response,
                self.cache_first_response,
                self.cache_stable_response,
                self.billing_response,
            )
        ):
            raise FreeExecutionAdmissionError("free execution response authority is foreign")
        if type(self.external_responses) is not tuple:
            raise FreeExecutionAdmissionError("external response authority must be a tuple")
        if any(type(item) is not tuple or len(item) != 2 for item in self.external_responses):
            raise FreeExecutionAdmissionError("external response authority rows are invalid")
        kinds = tuple(item[0] for item in self.external_responses)
        if any(
            type(item[0]) is not ExternalServiceKind or type(item[1]) is not ExactHttpResponseV1
            for item in self.external_responses
        ) or kinds != tuple(sorted(set(kinds), key=lambda item: item.value)):
            raise FreeExecutionAdmissionError(
                "external response authorities must be sorted and unique"
            )

    def derive(
        self,
        *,
        repository: str,
        expires_at: str,
    ) -> tuple[
        ExecutionIntentV1,
        JobGraphEvidenceV1,
        RepositoryPricingEvidenceV1,
        StorageCostEvidenceV1,
        tuple[ExternalServiceCostEvidenceV1, ...],
    ]:
        intent = ExecutionIntentV1.from_manifest_bytes(self.manifest_bytes)
        if intent.repository != repository:
            raise FreeExecutionAdmissionError("execution manifest repository is foreign")
        graph = JobGraphEvidenceV1.from_workflow_bytes(self.workflow_bytes, intent=intent)
        pricing = RepositoryPricingEvidenceV1.from_authority(
            repository=repository,
            repository_response=self.repository_response,
            pricing_response=self.pricing_response,
            expires_at=expires_at,
        )
        storage = StorageCostEvidenceV1.from_authority(
            repository_pricing=pricing,
            intent=intent,
            inventory_response=self.storage_inventory_response,
            cache_first_response=self.cache_first_response,
            cache_stable_response=self.cache_stable_response,
            billing_response=self.billing_response,
            expires_at=expires_at,
        )
        responses = dict(self.external_responses)
        if set(responses) != set(intent.required_external_services):
            raise FreeExecutionAdmissionError(
                "external response denominator differs from manifest publish intent"
            )
        external = tuple(
            ExternalServiceCostEvidenceV1.from_authority(
                service_kind=kind,
                response=responses[kind],
                expires_at=expires_at,
            )
            for kind in intent.required_external_services
        )
        return intent, graph, pricing, storage, external

    def derive_execution_context(
        self,
        *,
        intent: ExecutionIntentV1,
    ) -> dict[str, object]:
        """Derive every execution-context field from one exact private receipt."""
        response = self.execution_context_response
        payload = response.json_object()
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "repository",
                    "source_sha",
                    "workflow_path",
                    "workflow_sha256",
                    "run_id",
                    "run_attempt",
                    "admission_job_id",
                    "mode",
                    "requested_capacity",
                    "admission_nonce",
                    "evaluated_at",
                    "expires_at",
                    "manifest_sha256",
                    "producer_job_receipt_sha256",
                }
            ),
            label="execution context authority",
        )
        run_id = _uint(payload["run_id"], field_name="run_id", positive=True)
        run_attempt = _uint(payload["run_attempt"], field_name="run_attempt", positive=True)
        _require_github_response(
            response,
            url=(
                f"https://api.github.com/repos/{intent.repository}/actions/runs/{run_id}/"
                f"attempts/{run_attempt}/free-execution-context"
            ),
        )
        try:
            mode = FreeExecutionMode(_exact_text(payload["mode"], field_name="mode"))
        except ValueError as exc:
            raise FreeExecutionAdmissionError("execution context mode is unsupported") from exc
        context: dict[str, object] = {
            "repository": _exact_text(payload["repository"], field_name="repository"),
            "source_sha": _source_sha(payload["source_sha"]),
            "workflow_path": _workflow_path(payload["workflow_path"]),
            "workflow_sha256": _sha256(payload["workflow_sha256"], field_name="workflow_sha256"),
            "run_id": run_id,
            "run_attempt": run_attempt,
            "admission_job_id": _exact_text(
                payload["admission_job_id"], field_name="admission_job_id"
            ),
            "mode": mode,
            "requested_capacity": _uint(
                payload["requested_capacity"],
                field_name="requested_capacity",
                positive=True,
            ),
            "admission_nonce": _exact_text(
                payload["admission_nonce"], field_name="admission_nonce"
            ),
            "evaluated_at": _exact_text(payload["evaluated_at"], field_name="evaluated_at"),
            "expires_at": _exact_text(payload["expires_at"], field_name="expires_at"),
        }
        if (
            payload["schema_version"] != 1
            or type(payload["schema_version"]) is not int
            or (
                context["repository"],
                context["source_sha"],
                context["workflow_path"],
                context["workflow_sha256"],
                payload["manifest_sha256"],
            )
            != (
                intent.repository,
                intent.source_sha,
                intent.workflow_path,
                intent.workflow_sha256,
                intent.manifest_sha256,
            )
        ):
            raise FreeExecutionAdmissionError("execution context is foreign to exact intent")
        _sha256(
            payload["producer_job_receipt_sha256"],
            field_name="producer_job_receipt_sha256",
        )
        evaluated = _timestamp(context["evaluated_at"], field_name="evaluated_at")
        expires = _timestamp(context["expires_at"], field_name="expires_at")
        if (
            not response.observed_at <= evaluated < expires
            or (expires - evaluated).total_seconds() > _MAX_EVIDENCE_TTL_SECONDS
        ):
            raise FreeExecutionAdmissionError("execution context freshness is invalid")
        if context["requested_capacity"] > intent.matrix_lane_count:
            raise FreeExecutionAdmissionError("execution context capacity exceeds exact lanes")
        return context

    def authority_sha256(self) -> str:
        return _canonical_sha256(
            {
                "schema_version": self.schema_version,
                "workflow_sha256": hashlib.sha256(self.workflow_bytes).hexdigest(),
                "manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest(),
                "execution_context_response": self.execution_context_response.public_identity(),
                "repository_response": self.repository_response.public_identity(),
                "pricing_response": self.pricing_response.public_identity(),
                "storage_inventory_response": (self.storage_inventory_response.public_identity()),
                "cache_first_response": self.cache_first_response.public_identity(),
                "cache_stable_response": self.cache_stable_response.public_identity(),
                "billing_response": self.billing_response.public_identity(),
                "external_responses": [
                    {
                        "service_kind": kind.value,
                        "response": response.public_identity(),
                    }
                    for kind, response in self.external_responses
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class FreeExecutionAdmissionV1:
    """Public receipt whose positive state remains bound to private raw authority."""

    repository: str
    source_sha: str
    workflow_path: str
    workflow_sha256: str
    run_id: int
    run_attempt: int
    admission_job_id: str
    mode: FreeExecutionMode
    requested_capacity: int
    admitted_capacity: int
    admission_nonce: str
    evaluated_at: str
    expires_at: str
    status: FreeExecutionAdmissionStatus
    blocker_codes: tuple[str, ...]
    intent: ExecutionIntentV1
    job_graph: JobGraphEvidenceV1 | None
    repository_pricing: RepositoryPricingEvidenceV1 | None
    storage_cost: StorageCostEvidenceV1 | None
    external_services: tuple[ExternalServiceCostEvidenceV1, ...]
    authority_sha256: str | None
    admission_sha256: str = ""

    schema_version: ClassVar[int] = FREE_EXECUTION_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        repository = _exact_text(self.repository, field_name="repository")
        if repository.count("/") != 1:
            raise FreeExecutionAdmissionError("repository must be owner/name")
        _source_sha(self.source_sha)
        _workflow_path(self.workflow_path)
        _sha256(self.workflow_sha256, field_name="workflow_sha256")
        _uint(self.run_id, field_name="run_id", positive=True)
        _uint(self.run_attempt, field_name="run_attempt", positive=True)
        _exact_text(self.admission_job_id, field_name="admission_job_id")
        if type(self.mode) is not FreeExecutionMode:
            raise FreeExecutionAdmissionError("free execution mode is invalid")
        requested = _uint(
            self.requested_capacity,
            field_name="requested_capacity",
            positive=True,
        )
        admitted = _uint(self.admitted_capacity, field_name="admitted_capacity")
        _exact_text(self.admission_nonce, field_name="admission_nonce")
        evaluated = _timestamp(self.evaluated_at, field_name="evaluated_at")
        expires = _timestamp(self.expires_at, field_name="expires_at")
        if (
            not evaluated < expires
            or (expires - evaluated).total_seconds() > _MAX_EVIDENCE_TTL_SECONDS
        ):
            raise FreeExecutionAdmissionError("admission freshness window is invalid")
        if type(self.status) is not FreeExecutionAdmissionStatus:
            raise FreeExecutionAdmissionError("admission status is invalid")
        blockers = _tuple_text(
            self.blocker_codes,
            field_name="blocker_codes",
            sorted_unique=True,
        )
        if type(self.intent) is not ExecutionIntentV1:
            raise FreeExecutionAdmissionError("admission intent is invalid")
        intent = ExecutionIntentV1.from_dict(self.intent.to_dict())
        object.__setattr__(self, "intent", intent)
        if (
            intent.repository,
            intent.source_sha,
            intent.workflow_path,
            intent.workflow_sha256,
        ) != (repository, self.source_sha, self.workflow_path, self.workflow_sha256):
            raise FreeExecutionAdmissionError("admission context differs from manifest intent")
        if type(self.external_services) is not tuple:
            raise FreeExecutionAdmissionError("external evidence must be a tuple")
        external: tuple[ExternalServiceCostEvidenceV1, ...] = tuple(
            ExternalServiceCostEvidenceV1.from_dict(item.to_dict())
            for item in self.external_services
            if type(item) is ExternalServiceCostEvidenceV1
        )
        if len(external) != len(self.external_services):
            raise FreeExecutionAdmissionError("external evidence contains a foreign row")
        kinds = tuple(item.service_kind for item in external)
        if kinds != tuple(sorted(set(kinds), key=lambda item: item.value)):
            raise FreeExecutionAdmissionError("external evidence identities are not sorted unique")
        object.__setattr__(self, "external_services", external)
        if self.status is FreeExecutionAdmissionStatus.ADMITTED:
            _raise_integration_blocked(
                stage="positive free-execution admission",
                codes=_ADMISSION_INTEGRATION_BLOCKERS,
            )
            if blockers or admitted != requested:
                raise FreeExecutionAdmissionError(
                    "positive admission capacity/blockers are invalid"
                )
            if (
                type(self.job_graph) is not JobGraphEvidenceV1
                or type(self.repository_pricing) is not RepositoryPricingEvidenceV1
                or type(self.storage_cost) is not StorageCostEvidenceV1
                or self.authority_sha256 is None
            ):
                raise FreeExecutionAdmissionError("positive admission omits required authority")
            graph = JobGraphEvidenceV1.from_dict(self.job_graph.to_dict())
            pricing = RepositoryPricingEvidenceV1.from_dict(self.repository_pricing.to_dict())
            storage = StorageCostEvidenceV1.from_dict(self.storage_cost.to_dict())
            if graph.provider_capacity < admitted:
                raise FreeExecutionAdmissionError("admitted capacity exceeds parsed job graph")
            if intent.matrix_lane_count == 0 or admitted > intent.matrix_lane_count:
                raise FreeExecutionAdmissionError(
                    "admitted capacity exceeds the exact executable lane denominator"
                )
            if graph.intent_sha256 != intent.intent_sha256:
                raise FreeExecutionAdmissionError("job graph is foreign to manifest intent")
            if pricing.repository != repository:
                raise FreeExecutionAdmissionError("repository pricing evidence is foreign")
            if kinds != intent.required_external_services:
                raise FreeExecutionAdmissionError("external evidence denominator is incomplete")
            _sha256(self.authority_sha256, field_name="authority_sha256")
            authority_readbacks = (
                _timestamp(pricing.readback_at, field_name="pricing.readback_at"),
                _timestamp(storage.readback_at, field_name="storage.readback_at"),
                *(
                    _timestamp(item.readback_at, field_name="external.readback_at")
                    for item in external
                ),
            )
            if max(authority_readbacks) > evaluated:
                raise FreeExecutionAdmissionError("admission predates its authority readback")
            object.__setattr__(self, "job_graph", graph)
            object.__setattr__(self, "repository_pricing", pricing)
            object.__setattr__(self, "storage_cost", storage)
        else:
            if admitted != 0 or not blockers:
                raise FreeExecutionAdmissionError("blocked admission capacity/blockers are invalid")
            if (
                any(
                    value is not None
                    for value in (
                        self.job_graph,
                        self.repository_pricing,
                        self.storage_cost,
                        self.authority_sha256,
                    )
                )
                or external
            ):
                raise FreeExecutionAdmissionError("blocked admission carries positive evidence")
        object.__setattr__(
            self,
            "admission_sha256",
            _sealed_digest(
                self.admission_sha256,
                identity=self._identity_dict(),
                field_name="admission_sha256",
            ),
        )

    @classmethod
    def admitted(
        cls,
        *,
        authority: FreeExecutionAuthorityBundleV1,
        repository: str,
        source_sha: str,
        workflow_path: str,
        workflow_sha256: str,
        run_id: int,
        run_attempt: int,
        admission_job_id: str,
        mode: FreeExecutionMode,
        requested_capacity: int,
        admission_nonce: str,
        evaluated_at: str,
        expires_at: str,
    ) -> Self:
        if type(authority) is not FreeExecutionAuthorityBundleV1:
            raise FreeExecutionAdmissionError("positive admission raw authority is foreign")
        intent = ExecutionIntentV1.from_manifest_bytes(authority.manifest_bytes)
        context = authority.derive_execution_context(intent=intent)
        supplied_context = (
            repository,
            source_sha,
            workflow_path,
            workflow_sha256,
            run_id,
            run_attempt,
            admission_job_id,
            mode,
            requested_capacity,
            admission_nonce,
            evaluated_at,
            expires_at,
        )
        derived_context = (
            context["repository"],
            context["source_sha"],
            context["workflow_path"],
            context["workflow_sha256"],
            context["run_id"],
            context["run_attempt"],
            context["admission_job_id"],
            context["mode"],
            context["requested_capacity"],
            context["admission_nonce"],
            context["evaluated_at"],
            context["expires_at"],
        )
        if supplied_context != derived_context:
            raise FreeExecutionAdmissionError(
                "admission execution context differs from exact collector receipt"
            )
        derived_intent, graph, pricing, storage, external = authority.derive(
            repository=cast("str", context["repository"]),
            expires_at=cast("str", context["expires_at"]),
        )
        if derived_intent != intent:
            raise FreeExecutionAdmissionError("admission intent derivation is unstable")
        _raise_integration_blocked(
            stage="positive free-execution admission",
            codes=_ADMISSION_INTEGRATION_BLOCKERS,
        )
        return cls(
            repository=cast("str", context["repository"]),
            source_sha=cast("str", context["source_sha"]),
            workflow_path=cast("str", context["workflow_path"]),
            workflow_sha256=cast("str", context["workflow_sha256"]),
            run_id=cast("int", context["run_id"]),
            run_attempt=cast("int", context["run_attempt"]),
            admission_job_id=cast("str", context["admission_job_id"]),
            mode=cast("FreeExecutionMode", context["mode"]),
            requested_capacity=cast("int", context["requested_capacity"]),
            admitted_capacity=cast("int", context["requested_capacity"]),
            admission_nonce=cast("str", context["admission_nonce"]),
            evaluated_at=cast("str", context["evaluated_at"]),
            expires_at=cast("str", context["expires_at"]),
            status=FreeExecutionAdmissionStatus.ADMITTED,
            blocker_codes=(),
            intent=intent,
            job_graph=graph,
            repository_pricing=pricing,
            storage_cost=storage,
            external_services=external,
            authority_sha256=authority.authority_sha256(),
        )

    @classmethod
    def capacity_blocked(
        cls,
        *,
        manifest_bytes: bytes,
        repository: str,
        source_sha: str,
        workflow_path: str,
        workflow_sha256: str,
        run_id: int,
        run_attempt: int,
        admission_job_id: str,
        mode: FreeExecutionMode,
        requested_capacity: int,
        admission_nonce: str,
        evaluated_at: str,
        expires_at: str,
        blocker_codes: tuple[str, ...],
    ) -> Self:
        intent = ExecutionIntentV1.from_manifest_bytes(manifest_bytes)
        if (
            repository,
            source_sha,
            workflow_path,
            workflow_sha256,
        ) != (
            intent.repository,
            intent.source_sha,
            intent.workflow_path,
            intent.workflow_sha256,
        ):
            raise FreeExecutionAdmissionError("blocked admission context is foreign to manifest")
        return cls(
            repository=repository,
            source_sha=source_sha,
            workflow_path=workflow_path,
            workflow_sha256=workflow_sha256,
            run_id=run_id,
            run_attempt=run_attempt,
            admission_job_id=admission_job_id,
            mode=mode,
            requested_capacity=requested_capacity,
            admitted_capacity=0,
            admission_nonce=admission_nonce,
            evaluated_at=evaluated_at,
            expires_at=expires_at,
            status=FreeExecutionAdmissionStatus.CAPACITY_BLOCKED,
            blocker_codes=blocker_codes,
            intent=intent,
            job_graph=None,
            repository_pricing=None,
            storage_cost=None,
            external_services=(),
            authority_sha256=None,
        )

    def validate_authority(self, authority: FreeExecutionAuthorityBundleV1) -> None:
        if self.status is not FreeExecutionAdmissionStatus.ADMITTED:
            raise FreeExecutionAdmissionError("blocked admission has no positive authority")
        _raise_integration_blocked(
            stage="positive free-execution admission",
            codes=_ADMISSION_INTEGRATION_BLOCKERS,
        )
        intent, graph, pricing, storage, external = authority.derive(
            repository=self.repository,
            expires_at=self.expires_at,
        )
        context = authority.derive_execution_context(intent=intent)
        if (
            intent != self.intent
            or graph != self.job_graph
            or pricing != self.repository_pricing
            or storage != self.storage_cost
            or external != self.external_services
            or authority.authority_sha256() != self.authority_sha256
            or (
                context["repository"],
                context["source_sha"],
                context["workflow_path"],
                context["workflow_sha256"],
                context["run_id"],
                context["run_attempt"],
                context["admission_job_id"],
                context["mode"],
                context["requested_capacity"],
                context["admission_nonce"],
                context["evaluated_at"],
                context["expires_at"],
            )
            != (
                self.repository,
                self.source_sha,
                self.workflow_path,
                self.workflow_sha256,
                self.run_id,
                self.run_attempt,
                self.admission_job_id,
                self.mode,
                self.requested_capacity,
                self.admission_nonce,
                self.evaluated_at,
                self.expires_at,
            )
        ):
            raise FreeExecutionAdmissionError("private raw authority differs from admission")

    def validate_manifest(self, manifest_bytes: bytes) -> None:
        if ExecutionIntentV1.from_manifest_bytes(manifest_bytes) != self.intent:
            raise FreeExecutionAdmissionError("private manifest differs from admission intent")

    def validate_context(
        self,
        *,
        repository: str,
        source_sha: str,
        workflow_path: str,
        workflow_sha256: str,
        run_id: int,
        run_attempt: int,
        admission_job_id: str,
        mode: FreeExecutionMode,
        checked_at: str,
    ) -> None:
        if (
            repository,
            source_sha,
            workflow_path,
            workflow_sha256,
            run_id,
            run_attempt,
            admission_job_id,
            mode,
        ) != (
            self.repository,
            self.source_sha,
            self.workflow_path,
            self.workflow_sha256,
            self.run_id,
            self.run_attempt,
            self.admission_job_id,
            self.mode,
        ):
            raise FreeExecutionAdmissionError("admission context is foreign")
        checked = _timestamp(checked_at, field_name="checked_at")
        evaluated = _timestamp(self.evaluated_at, field_name="evaluated_at")
        expires = _timestamp(self.expires_at, field_name="expires_at")
        if not evaluated <= checked < expires:
            raise FreeExecutionAdmissionError("admission is stale at point of use")

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "workflow_path": self.workflow_path,
            "workflow_sha256": self.workflow_sha256,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "admission_job_id": self.admission_job_id,
            "mode": self.mode.value,
            "requested_capacity": self.requested_capacity,
            "admitted_capacity": self.admitted_capacity,
            "admission_nonce": self.admission_nonce,
            "evaluated_at": self.evaluated_at,
            "expires_at": self.expires_at,
            "status": self.status.value,
            "blocker_codes": list(self.blocker_codes),
            "intent": self.intent.to_dict(),
            "job_graph": None if self.job_graph is None else self.job_graph.to_dict(),
            "repository_pricing": (
                None if self.repository_pricing is None else self.repository_pricing.to_dict()
            ),
            "storage_cost": None if self.storage_cost is None else self.storage_cost.to_dict(),
            "external_services": [item.to_dict() for item in self.external_services],
            "authority_sha256": self.authority_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "admission_sha256": self.admission_sha256}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(cls._identity_field_names()) | {"admission_sha256"}
        _require_exact_keys(payload, expected=expected, label="free execution admission")
        if (
            payload["schema_version"] != cls.schema_version
            or type(payload["schema_version"]) is not int
        ):
            raise FreeExecutionAdmissionError("admission schema is unsupported")
        blockers = payload["blocker_codes"]
        services = payload["external_services"]
        if type(blockers) is not list or type(services) is not list:
            raise FreeExecutionAdmissionError("admission arrays are invalid")
        try:
            mode = FreeExecutionMode(_exact_text(payload["mode"], field_name="mode"))
            status = FreeExecutionAdmissionStatus(
                _exact_text(payload["status"], field_name="status")
            )
        except ValueError as exc:
            raise FreeExecutionAdmissionError("admission enum is unsupported") from exc
        raw_graph = payload["job_graph"]
        raw_pricing = payload["repository_pricing"]
        raw_storage = payload["storage_cost"]
        return cls(
            repository=cast("str", payload["repository"]),
            source_sha=cast("str", payload["source_sha"]),
            workflow_path=cast("str", payload["workflow_path"]),
            workflow_sha256=cast("str", payload["workflow_sha256"]),
            run_id=cast("int", payload["run_id"]),
            run_attempt=cast("int", payload["run_attempt"]),
            admission_job_id=cast("str", payload["admission_job_id"]),
            mode=mode,
            requested_capacity=cast("int", payload["requested_capacity"]),
            admitted_capacity=cast("int", payload["admitted_capacity"]),
            admission_nonce=cast("str", payload["admission_nonce"]),
            evaluated_at=cast("str", payload["evaluated_at"]),
            expires_at=cast("str", payload["expires_at"]),
            status=status,
            blocker_codes=tuple(_exact_text(item, field_name="blocker_codes") for item in blockers),
            intent=ExecutionIntentV1.from_dict(_mapping(payload["intent"], field_name="intent")),
            job_graph=(
                None
                if raw_graph is None
                else JobGraphEvidenceV1.from_dict(_mapping(raw_graph, field_name="job_graph"))
            ),
            repository_pricing=(
                None
                if raw_pricing is None
                else RepositoryPricingEvidenceV1.from_dict(
                    _mapping(raw_pricing, field_name="repository_pricing")
                )
            ),
            storage_cost=(
                None
                if raw_storage is None
                else StorageCostEvidenceV1.from_dict(
                    _mapping(raw_storage, field_name="storage_cost")
                )
            ),
            external_services=tuple(
                ExternalServiceCostEvidenceV1.from_dict(
                    _mapping(item, field_name=f"external_services[{index}]")
                )
                for index, item in enumerate(cast("list[object]", services))
            ),
            authority_sha256=cast("str | None", payload["authority_sha256"]),
            admission_sha256=cast("str", payload["admission_sha256"]),
        )

    @classmethod
    def from_bytes(cls, encoded: bytes) -> Self:
        return cls.from_dict(_decode_canonical_object(encoded))

    @staticmethod
    def _identity_field_names() -> tuple[str, ...]:
        return (
            "schema_version",
            "repository",
            "source_sha",
            "workflow_path",
            "workflow_sha256",
            "run_id",
            "run_attempt",
            "admission_job_id",
            "mode",
            "requested_capacity",
            "admitted_capacity",
            "admission_nonce",
            "evaluated_at",
            "expires_at",
            "status",
            "blocker_codes",
            "intent",
            "job_graph",
            "repository_pricing",
            "storage_cost",
            "external_services",
            "authority_sha256",
        )


_SERVICE_HOSTS = {
    ExternalServiceKind.GITHUB_NETWORK_EGRESS: frozenset({"api.github.com", "github.com"}),
    ExternalServiceKind.KAGGLE: frozenset({"api.kaggle.com", "www.kaggle.com"}),
    ExternalServiceKind.NBA_API: frozenset(
        {"cdn.nba.com", "nba.com", "stats.nba.com", "www.nba.com"}
    ),
}


@dataclass(frozen=True, slots=True)
class ProviderOperationV1:
    """Exact provider operation authorized at one point of use."""

    service_kind: ExternalServiceKind
    lane_id: str
    operation_kind: str
    endpoint_id: str
    method: str
    request_url: str
    safe_parameters_json: str
    request_body_sha256: str | None
    operation_nonce: str
    operation_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        if type(self.service_kind) is not ExternalServiceKind:
            raise FreeExecutionAdmissionError("provider service kind is invalid")
        _exact_text(self.lane_id, field_name="lane_id")
        _exact_text(self.operation_kind, field_name="operation_kind")
        _exact_text(self.endpoint_id, field_name="endpoint_id")
        if self.method not in {"GET", "POST"}:
            raise FreeExecutionAdmissionError("provider operation method is unsupported")
        url = _exact_text(self.request_url, field_name="request_url", maximum_bytes=4096)
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise FreeExecutionAdmissionError("provider operation URL port is invalid") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _SERVICE_HOSTS[self.service_kind]
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or "//" in parsed.path
            or "%" in parsed.path
            or "\\" in parsed.path
        ):
            raise FreeExecutionAdmissionError("provider operation URL is foreign or ambiguous")
        raw_parameters = _exact_text(
            self.safe_parameters_json,
            field_name="safe_parameters_json",
            maximum_bytes=_MAX_TEXT_BYTES,
        ).encode("utf-8")
        parameters = _decode_canonical_object(raw_parameters)
        _scan_forbidden_keys(parameters, path="$.safe_parameters")
        if self.method == "GET":
            if self.request_body_sha256 is not None:
                raise FreeExecutionAdmissionError("GET provider operation cannot carry a body")
        elif self.request_body_sha256 is None:
            raise FreeExecutionAdmissionError("POST provider operation requires a body digest")
        if self.request_body_sha256 is not None:
            _sha256(self.request_body_sha256, field_name="request_body_sha256")
        _exact_text(self.operation_nonce, field_name="operation_nonce")
        object.__setattr__(
            self,
            "operation_sha256",
            _sealed_digest(
                self.operation_sha256,
                identity=self._identity_dict(),
                field_name="operation_sha256",
            ),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "service_kind": self.service_kind.value,
            "lane_id": self.lane_id,
            "operation_kind": self.operation_kind,
            "endpoint_id": self.endpoint_id,
            "method": self.method,
            "request_url": self.request_url,
            "safe_parameters_json": self.safe_parameters_json,
            "request_body_sha256": self.request_body_sha256,
            "operation_nonce": self.operation_nonce,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "operation_sha256": self.operation_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "service_kind",
                "lane_id",
                "operation_kind",
                "endpoint_id",
                "method",
                "request_url",
                "safe_parameters_json",
                "request_body_sha256",
                "operation_nonce",
                "operation_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="provider operation")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("provider operation schema is unsupported")
        try:
            service_kind = ExternalServiceKind(
                _exact_text(payload["service_kind"], field_name="service_kind")
            )
        except ValueError as exc:
            raise FreeExecutionAdmissionError("provider service kind is unsupported") from exc
        return cls(
            service_kind=service_kind,
            lane_id=cast("str", payload["lane_id"]),
            operation_kind=cast("str", payload["operation_kind"]),
            endpoint_id=cast("str", payload["endpoint_id"]),
            method=cast("str", payload["method"]),
            request_url=cast("str", payload["request_url"]),
            safe_parameters_json=cast("str", payload["safe_parameters_json"]),
            request_body_sha256=cast("str | None", payload["request_body_sha256"]),
            operation_nonce=cast("str", payload["operation_nonce"]),
            operation_sha256=cast("str", payload["operation_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class _ActualJobAuthorityV1:
    actual_job_id: int
    actual_job_name: str
    run_id: int
    run_attempt: int
    head_sha: str
    runner_id: int
    runner_name: str
    runner_labels: tuple[str, ...]
    response_sha256: str
    response_receipt_sha256: str
    observed_at: str


def _actual_job_authority(
    response: ExactHttpResponseV1,
    *,
    admission: FreeExecutionAdmissionV1,
    logical_job_id: str,
    lane_id: str,
) -> _ActualJobAuthorityV1:
    graph = admission.job_graph
    if graph is None:
        raise FreeExecutionAdmissionError("blocked admission has no job graph")
    requirement = graph.job(logical_job_id)
    payload = response.json_object()
    expected = frozenset(
        {
            "id",
            "name",
            "run_id",
            "run_attempt",
            "head_sha",
            "status",
            "conclusion",
            "runner_id",
            "runner_name",
            "runner_group_name",
            "labels",
            "environment",
            "os",
            "arch",
        }
    )
    _require_exact_keys(payload, expected=expected, label="actual job response")
    job_id = _uint(payload["id"], field_name="job.id", positive=True)
    _require_github_response(
        response,
        url=f"https://api.github.com/repos/{admission.repository}/actions/jobs/{job_id}",
    )
    lane = _exact_text(lane_id, field_name="lane_id")
    if lane not in admission.intent.matrix_lane_ids:
        raise FreeExecutionAdmissionError("actual job lane is foreign to exact manifest")
    name = _exact_text(payload["name"], field_name="job.name")
    prefix = requirement.actual_name_prefix
    if name != f"{prefix} {lane}":
        raise FreeExecutionAdmissionError("actual job name does not exactly bind its manifest lane")
    if _logical_job_for_name(graph, name).logical_job_id != logical_job_id:
        raise FreeExecutionAdmissionError("actual job name is ambiguous across logical jobs")
    if (
        payload["run_id"] != admission.run_id
        or payload["run_attempt"] != admission.run_attempt
        or payload["head_sha"] != admission.source_sha
    ):
        raise FreeExecutionAdmissionError("actual job run/source identity is foreign")
    if payload["status"] != "in_progress" or payload["conclusion"] is not None:
        raise FreeExecutionAdmissionError("actual job is not actively executing")
    if payload["runner_group_name"] is not None:
        raise FreeExecutionAdmissionError("actual job uses a runner group")
    labels = payload["labels"]
    if type(labels) is not list:
        raise FreeExecutionAdmissionError("actual job labels must be an array")
    label_tuple = tuple(
        _exact_text(item, field_name="job.labels") for item in cast("list[object]", labels)
    )
    if label_tuple != (_STANDARD_RUNNER_LABEL,):
        raise FreeExecutionAdmissionError("actual job labels are not exact ubuntu-latest")
    if (
        payload["environment"] != "github-hosted"
        or payload["os"] != "Linux"
        or payload["arch"] != "X64"
    ):
        raise FreeExecutionAdmissionError("actual job runner environment is unsupported")
    return _ActualJobAuthorityV1(
        actual_job_id=job_id,
        actual_job_name=name,
        run_id=cast("int", payload["run_id"]),
        run_attempt=cast("int", payload["run_attempt"]),
        head_sha=cast("str", payload["head_sha"]),
        runner_id=_uint(payload["runner_id"], field_name="runner_id", positive=True),
        runner_name=_exact_text(payload["runner_name"], field_name="runner_name"),
        runner_labels=label_tuple,
        response_sha256=response.body_sha256,
        response_receipt_sha256=response.receipt_sha256,
        observed_at=response.response_date,
    )


@dataclass(frozen=True, slots=True)
class PointOfUseAuthorityBundleV1:
    """Private fresh authority for one actual job point of use."""

    refreshed_free_authority: FreeExecutionAuthorityBundleV1 = field(repr=False)
    actual_job_response: ExactHttpResponseV1 = field(repr=False)

    integration_blocker_codes: ClassVar[tuple[str, ...]] = _POINT_INTEGRATION_BLOCKERS

    def __post_init__(self) -> None:
        if (
            type(self.refreshed_free_authority) is not FreeExecutionAuthorityBundleV1
            or type(self.actual_job_response) is not ExactHttpResponseV1
        ):
            raise FreeExecutionAdmissionError("point-of-use raw authority is foreign")

    def derive(
        self,
        *,
        admission: FreeExecutionAdmissionV1,
        logical_job_id: str,
        lane_id: str,
        expires_at: str,
    ) -> tuple[
        ExecutionIntentV1,
        JobGraphEvidenceV1,
        RepositoryPricingEvidenceV1,
        StorageCostEvidenceV1,
        tuple[ExternalServiceCostEvidenceV1, ...],
        _ActualJobAuthorityV1,
    ]:
        if admission.status is not FreeExecutionAdmissionStatus.ADMITTED:
            raise FreeExecutionAdmissionError("blocked admission cannot issue point authority")
        intent, graph, pricing, storage, external = self.refreshed_free_authority.derive(
            repository=admission.repository,
            expires_at=expires_at,
        )
        if intent != admission.intent or graph != admission.job_graph:
            raise FreeExecutionAdmissionError("refreshed source/workflow authority is foreign")
        original_pricing = admission.repository_pricing
        original_storage = admission.storage_cost
        if original_pricing is None or original_storage is None:
            raise FreeExecutionAdmissionError("admission omits positive cost authority")
        if (
            pricing.repository_id,
            pricing.owner_identity_sha256,
            pricing.pricing_rule_id,
            pricing.maximum_compute_charge_microusd,
        ) != (
            original_pricing.repository_id,
            original_pricing.owner_identity_sha256,
            original_pricing.pricing_rule_id,
            0,
        ):
            raise FreeExecutionAdmissionError("refreshed repository pricing identity drifted")
        if (
            storage.planned_artifact_max_bytes,
            storage.planned_artifact_retention_hours,
            storage.planned_cache_max_bytes,
            storage.maximum_incremental_charge_microusd,
        ) != (
            original_storage.planned_artifact_max_bytes,
            original_storage.planned_artifact_retention_hours,
            original_storage.planned_cache_max_bytes,
            0,
        ):
            raise FreeExecutionAdmissionError("refreshed storage plan/cost identity drifted")
        if (
            tuple(item.service_kind for item in external)
            != admission.intent.required_external_services
        ):
            raise FreeExecutionAdmissionError("refreshed external denominator drifted")
        job = _actual_job_authority(
            self.actual_job_response,
            admission=admission,
            logical_job_id=logical_job_id,
            lane_id=lane_id,
        )
        return intent, graph, pricing, storage, external, job

    def authority_sha256(self) -> str:
        return _canonical_sha256(
            {
                "schema_version": 1,
                "refreshed_free_authority_sha256": (
                    self.refreshed_free_authority.authority_sha256()
                ),
                "actual_job_response": self.actual_job_response.public_identity(),
            }
        )


@dataclass(frozen=True, slots=True)
class FreeExecutionPointOfUseV1:
    admission_sha256: str
    predecessor_sha256: str
    successor_sequence: int
    refreshed_authority_sha256: str
    repository: str
    source_sha: str
    run_id: int
    run_attempt: int
    logical_job_id: str
    lane_id: str
    job_requirement_sha256: str
    actual_job_id: int
    actual_job_name: str
    actual_job_response_sha256: str
    actual_job_response_receipt_sha256: str
    runner_id: int
    runner_name: str
    runner_labels: tuple[str, ...]
    checked_at: str
    expires_at: str
    point_of_use_sha256: str = ""

    schema_version: ClassVar[int] = FREE_EXECUTION_POINT_OF_USE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _raise_integration_blocked(
            stage="free-execution point of use",
            codes=_POINT_INTEGRATION_BLOCKERS,
        )
        for name in (
            "admission_sha256",
            "predecessor_sha256",
            "refreshed_authority_sha256",
            "job_requirement_sha256",
            "actual_job_response_sha256",
            "actual_job_response_receipt_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        _uint(self.successor_sequence, field_name="successor_sequence")
        repository = _exact_text(self.repository, field_name="repository")
        if repository.count("/") != 1:
            raise FreeExecutionAdmissionError("point repository must be owner/name")
        _source_sha(self.source_sha)
        _uint(self.run_id, field_name="run_id", positive=True)
        _uint(self.run_attempt, field_name="run_attempt", positive=True)
        _exact_text(self.logical_job_id, field_name="logical_job_id")
        _exact_text(self.lane_id, field_name="lane_id")
        _uint(self.actual_job_id, field_name="actual_job_id", positive=True)
        _exact_text(self.actual_job_name, field_name="actual_job_name")
        _uint(self.runner_id, field_name="runner_id", positive=True)
        _exact_text(self.runner_name, field_name="runner_name")
        if self.runner_labels != (_STANDARD_RUNNER_LABEL,):
            raise FreeExecutionAdmissionError("point runner labels are unsupported")
        checked = _timestamp(self.checked_at, field_name="checked_at")
        expires = _timestamp(self.expires_at, field_name="expires_at")
        if (
            not checked < expires
            or (expires - checked).total_seconds() > _MAX_POINT_OF_USE_TTL_SECONDS
        ):
            raise FreeExecutionAdmissionError("point-of-use freshness window is invalid")
        object.__setattr__(
            self,
            "point_of_use_sha256",
            _sealed_digest(
                self.point_of_use_sha256,
                identity=self._identity_dict(),
                field_name="point_of_use_sha256",
            ),
        )

    @classmethod
    def from_authority(
        cls,
        *,
        admission: FreeExecutionAdmissionV1,
        authority: PointOfUseAuthorityBundleV1,
        logical_job_id: str,
        lane_id: str,
        predecessor: FreeExecutionAdmissionV1 | FreeExecutionPointOfUseV1,
        checked_at: str,
        expires_at: str,
    ) -> Self:
        _raise_integration_blocked(
            stage="free-execution point of use",
            codes=_POINT_INTEGRATION_BLOCKERS,
        )
        _, graph, pricing, storage, external, job = authority.derive(
            admission=admission,
            logical_job_id=logical_job_id,
            lane_id=lane_id,
            expires_at=expires_at,
        )
        if type(predecessor) is FreeExecutionAdmissionV1:
            if predecessor.admission_sha256 != admission.admission_sha256:
                raise FreeExecutionAdmissionError("point predecessor admission is foreign")
            sequence = 0
            predecessor_sha = admission.admission_sha256
        elif type(predecessor) is FreeExecutionPointOfUseV1:
            if (
                predecessor.admission_sha256 != admission.admission_sha256
                or predecessor.repository != admission.repository
                or predecessor.source_sha != admission.source_sha
                or predecessor.run_id != admission.run_id
                or predecessor.run_attempt != admission.run_attempt
            ):
                raise FreeExecutionAdmissionError("point successor predecessor is foreign")
            if _timestamp(checked_at, field_name="checked_at") <= _timestamp(
                predecessor.checked_at,
                field_name="predecessor.checked_at",
            ):
                raise FreeExecutionAdmissionError(
                    "point successor does not advance predecessor time"
                )
            sequence = predecessor.successor_sequence + 1
            predecessor_sha = predecessor.point_of_use_sha256
        else:
            raise FreeExecutionAdmissionError("point predecessor type is unsupported")
        checked = _timestamp(checked_at, field_name="checked_at")
        if checked < _timestamp(admission.evaluated_at, field_name="admission.evaluated_at"):
            raise FreeExecutionAdmissionError("point check predates admission evaluation")
        latest_readback = max(
            _timestamp(pricing.readback_at, field_name="pricing.readback_at"),
            _timestamp(storage.readback_at, field_name="storage.readback_at"),
            _timestamp(job.observed_at, field_name="job.observed_at"),
            *(_timestamp(item.readback_at, field_name="external.readback_at") for item in external),
        )
        if (
            not latest_readback <= checked
            or (checked - latest_readback).total_seconds() > _MAX_EVIDENCE_TTL_SECONDS
        ):
            raise FreeExecutionAdmissionError("point check is not bound to fresh readback")
        requirement = graph.job(logical_job_id)
        return cls(
            admission_sha256=admission.admission_sha256,
            predecessor_sha256=predecessor_sha,
            successor_sequence=sequence,
            refreshed_authority_sha256=authority.authority_sha256(),
            repository=admission.repository,
            source_sha=admission.source_sha,
            run_id=admission.run_id,
            run_attempt=admission.run_attempt,
            logical_job_id=logical_job_id,
            lane_id=lane_id,
            job_requirement_sha256=requirement.job_sha256,
            actual_job_id=job.actual_job_id,
            actual_job_name=job.actual_job_name,
            actual_job_response_sha256=job.response_sha256,
            actual_job_response_receipt_sha256=job.response_receipt_sha256,
            runner_id=job.runner_id,
            runner_name=job.runner_name,
            runner_labels=job.runner_labels,
            checked_at=checked_at,
            expires_at=expires_at,
        )

    def validate_for(
        self,
        *,
        admission: FreeExecutionAdmissionV1,
        authority: PointOfUseAuthorityBundleV1,
        predecessor: FreeExecutionAdmissionV1 | FreeExecutionPointOfUseV1,
    ) -> None:
        expected = type(self).from_authority(
            admission=admission,
            authority=authority,
            logical_job_id=self.logical_job_id,
            lane_id=self.lane_id,
            predecessor=predecessor,
            checked_at=self.checked_at,
            expires_at=self.expires_at,
        )
        if expected != self:
            raise FreeExecutionAdmissionError("point-of-use receipt differs from raw authority")

    def validate_checked_at(self, checked_at: str) -> None:
        checked = _timestamp(checked_at, field_name="checked_at")
        if (
            not _timestamp(self.checked_at, field_name="point.checked_at")
            <= checked
            < _timestamp(
                self.expires_at,
                field_name="point.expires_at",
            )
        ):
            raise FreeExecutionAdmissionError("point-of-use receipt is stale")

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "admission_sha256": self.admission_sha256,
            "predecessor_sha256": self.predecessor_sha256,
            "successor_sequence": self.successor_sequence,
            "refreshed_authority_sha256": self.refreshed_authority_sha256,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "logical_job_id": self.logical_job_id,
            "lane_id": self.lane_id,
            "job_requirement_sha256": self.job_requirement_sha256,
            "actual_job_id": self.actual_job_id,
            "actual_job_name": self.actual_job_name,
            "actual_job_response_sha256": self.actual_job_response_sha256,
            "actual_job_response_receipt_sha256": (self.actual_job_response_receipt_sha256),
            "runner_id": self.runner_id,
            "runner_name": self.runner_name,
            "runner_labels": list(self.runner_labels),
            "checked_at": self.checked_at,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "point_of_use_sha256": self.point_of_use_sha256}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "admission_sha256",
                "predecessor_sha256",
                "successor_sequence",
                "refreshed_authority_sha256",
                "repository",
                "source_sha",
                "run_id",
                "run_attempt",
                "logical_job_id",
                "lane_id",
                "job_requirement_sha256",
                "actual_job_id",
                "actual_job_name",
                "actual_job_response_sha256",
                "actual_job_response_receipt_sha256",
                "runner_id",
                "runner_name",
                "runner_labels",
                "checked_at",
                "expires_at",
                "point_of_use_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="point-of-use receipt")
        if (
            payload["schema_version"] != cls.schema_version
            or type(payload["schema_version"]) is not int
        ):
            raise FreeExecutionAdmissionError("point-of-use schema is unsupported")
        labels = payload["runner_labels"]
        if type(labels) is not list:
            raise FreeExecutionAdmissionError("point runner labels must be an array")
        return cls(
            admission_sha256=cast("str", payload["admission_sha256"]),
            predecessor_sha256=cast("str", payload["predecessor_sha256"]),
            successor_sequence=cast("int", payload["successor_sequence"]),
            refreshed_authority_sha256=cast("str", payload["refreshed_authority_sha256"]),
            repository=cast("str", payload["repository"]),
            source_sha=cast("str", payload["source_sha"]),
            run_id=cast("int", payload["run_id"]),
            run_attempt=cast("int", payload["run_attempt"]),
            logical_job_id=cast("str", payload["logical_job_id"]),
            lane_id=cast("str", payload["lane_id"]),
            job_requirement_sha256=cast("str", payload["job_requirement_sha256"]),
            actual_job_id=cast("int", payload["actual_job_id"]),
            actual_job_name=cast("str", payload["actual_job_name"]),
            actual_job_response_sha256=cast("str", payload["actual_job_response_sha256"]),
            actual_job_response_receipt_sha256=cast(
                "str", payload["actual_job_response_receipt_sha256"]
            ),
            runner_id=cast("int", payload["runner_id"]),
            runner_name=cast("str", payload["runner_name"]),
            runner_labels=tuple(_exact_text(item, field_name="runner_labels") for item in labels),
            checked_at=cast("str", payload["checked_at"]),
            expires_at=cast("str", payload["expires_at"]),
            point_of_use_sha256=cast("str", payload["point_of_use_sha256"]),
        )

    @classmethod
    def from_bytes(cls, encoded: bytes) -> Self:
        return cls.from_dict(_decode_canonical_object(encoded))


@dataclass(frozen=True, slots=True)
class PagedInventoryAuthorityV1:
    """Private stable repeated list authority with complete page denominators."""

    inventory_kind: str
    base_url: str
    items_key: str
    first_pages: tuple[ExactHttpResponseV1, ...] = field(repr=False)
    stable_pages: tuple[ExactHttpResponseV1, ...] = field(repr=False)

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        if self.inventory_kind not in {"artifacts", "jobs"}:
            raise FreeExecutionAdmissionError("paged inventory kind is unsupported")
        expected_key = "artifacts" if self.inventory_kind == "artifacts" else "jobs"
        if self.items_key != expected_key:
            raise FreeExecutionAdmissionError("paged inventory item key is foreign")
        base = _exact_text(self.base_url, field_name="base_url", maximum_bytes=4096)
        parsed = urlsplit(base)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.github.com"
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise FreeExecutionAdmissionError("paged inventory base URL is invalid")
        if (
            type(self.first_pages) is not tuple
            or type(self.stable_pages) is not tuple
            or not self.first_pages
            or len(self.first_pages) > _MAX_PAGES
            or len(self.first_pages) != len(self.stable_pages)
            or any(type(item) is not ExactHttpResponseV1 for item in self.first_pages)
            or any(type(item) is not ExactHttpResponseV1 for item in self.stable_pages)
        ):
            raise FreeExecutionAdmissionError("paged inventory response sets are invalid")

    def derive(
        self,
    ) -> tuple[
        tuple[Mapping[str, object], ...],
        int,
        str,
        tuple[str, ...],
        tuple[str, ...],
        str,
    ]:
        first_items, first_total = self._derive_pages(self.first_pages)
        stable_items, stable_total = self._derive_pages(self.stable_pages)
        if first_total != stable_total or first_items != stable_items:
            raise FreeExecutionAdmissionError("paged inventory did not stabilize")
        latest_first = max(item.observed_at for item in self.first_pages)
        earliest_stable = min(item.observed_at for item in self.stable_pages)
        if (earliest_stable - latest_first).total_seconds() < _MIN_STABILITY_SECONDS:
            raise FreeExecutionAdmissionError("paged inventory repeat window is too short")
        inventory_sha = _canonical_sha256([dict(item) for item in stable_items])
        return (
            stable_items,
            stable_total,
            inventory_sha,
            tuple(item.receipt_sha256 for item in self.first_pages),
            tuple(item.receipt_sha256 for item in self.stable_pages),
            max(item.response_date for item in self.stable_pages),
        )

    def _derive_pages(
        self,
        pages: tuple[ExactHttpResponseV1, ...],
    ) -> tuple[tuple[Mapping[str, object], ...], int]:
        all_items: list[Mapping[str, object]] = []
        total: int | None = None
        for index, response in enumerate(pages, start=1):
            expected_url = f"{self.base_url}?per_page=100&page={index}"
            _require_github_response(response, url=expected_url)
            payload = response.json_object()
            _require_exact_keys(
                payload,
                expected=frozenset({"total_count", self.items_key}),
                label=f"{self.inventory_kind} page",
            )
            page_total = _uint(payload["total_count"], field_name="total_count")
            raw_items = payload[self.items_key]
            if type(raw_items) is not list or len(raw_items) > 100:
                raise FreeExecutionAdmissionError("paged inventory page is not a bounded array")
            if total is None:
                total = page_total
            elif total != page_total:
                raise FreeExecutionAdmissionError("paged inventory total_count changed by page")
            for item_index, raw_item in enumerate(cast("list[object]", raw_items)):
                all_items.append(
                    _mapping(
                        raw_item,
                        field_name=f"{self.inventory_kind}[{item_index}]",
                    )
                )
        assert total is not None
        expected_pages = max(1, (total + 99) // 100)
        if len(pages) != expected_pages or len(all_items) != total:
            raise FreeExecutionAdmissionError("paged inventory denominator is incomplete")
        if total:
            for page in pages[:-1]:
                page_items = page.json_object()[self.items_key]
                if type(page_items) is not list or len(page_items) != 100:
                    raise FreeExecutionAdmissionError("nonterminal inventory page is incomplete")
        identities: set[int] = set()
        for item in all_items:
            item_id = _uint(item.get("id"), field_name="inventory item id", positive=True)
            if item_id in identities:
                raise FreeExecutionAdmissionError("paged inventory contains a duplicate item")
            identities.add(item_id)
        return tuple(all_items), total


@dataclass(frozen=True, slots=True)
class ActualJobCostReadbackV1:
    job_id: int
    job_name: str
    logical_job_id: str
    conclusion: str
    billable_milliseconds: int
    incremental_charge_microusd: int
    direct_response_sha256: str
    direct_response_receipt_sha256: str
    readback_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        _uint(self.job_id, field_name="job_id", positive=True)
        _exact_text(self.job_name, field_name="job_name")
        _exact_text(self.logical_job_id, field_name="logical_job_id")
        if self.conclusion not in _CONCLUSIONS:
            raise FreeExecutionAdmissionError("job conclusion is unsupported")
        _uint(self.billable_milliseconds, field_name="billable_milliseconds")
        _uint(
            self.incremental_charge_microusd,
            field_name="incremental_charge_microusd",
        )
        _sha256(self.direct_response_sha256, field_name="direct_response_sha256")
        _sha256(
            self.direct_response_receipt_sha256,
            field_name="direct_response_receipt_sha256",
        )
        object.__setattr__(
            self,
            "readback_sha256",
            _sealed_digest(
                self.readback_sha256,
                identity=self._identity_dict(),
                field_name="job_readback.readback_sha256",
            ),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "logical_job_id": self.logical_job_id,
            "conclusion": self.conclusion,
            "billable_milliseconds": self.billable_milliseconds,
            "incremental_charge_microusd": self.incremental_charge_microusd,
            "direct_response_sha256": self.direct_response_sha256,
            "direct_response_receipt_sha256": self.direct_response_receipt_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "readback_sha256": self.readback_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(cls.__dataclass_fields__) | {"schema_version"}
        _require_exact_keys(payload, expected=expected, label="job cost readback")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("job readback schema is unsupported")
        return cls(
            job_id=cast("int", payload["job_id"]),
            job_name=cast("str", payload["job_name"]),
            logical_job_id=cast("str", payload["logical_job_id"]),
            conclusion=cast("str", payload["conclusion"]),
            billable_milliseconds=cast("int", payload["billable_milliseconds"]),
            incremental_charge_microusd=cast("int", payload["incremental_charge_microusd"]),
            direct_response_sha256=cast("str", payload["direct_response_sha256"]),
            direct_response_receipt_sha256=cast("str", payload["direct_response_receipt_sha256"]),
            readback_sha256=cast("str", payload["readback_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class ArtifactCostReadbackV1:
    artifact_id: int
    artifact_name: str
    size_bytes: int
    created_at: str
    expires_at: str
    retained_byte_hours: int
    incremental_charge_microusd: int
    direct_response_sha256: str
    direct_response_receipt_sha256: str
    readback_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        _uint(self.artifact_id, field_name="artifact_id", positive=True)
        _exact_text(self.artifact_name, field_name="artifact_name")
        size = _uint(self.size_bytes, field_name="size_bytes")
        created = _timestamp(self.created_at, field_name="created_at")
        expires = _timestamp(self.expires_at, field_name="expires_at")
        if not created < expires:
            raise FreeExecutionAdmissionError("artifact retention timestamps are invalid")
        expected_hours = _checked_multiply(
            size,
            _ceil_hours(created, expires),
            field_name="retained_byte_hours",
        )
        if self.retained_byte_hours != expected_hours:
            raise FreeExecutionAdmissionError("artifact retained byte-hours are invalid")
        _uint(
            self.incremental_charge_microusd,
            field_name="incremental_charge_microusd",
        )
        _sha256(self.direct_response_sha256, field_name="direct_response_sha256")
        _sha256(
            self.direct_response_receipt_sha256,
            field_name="direct_response_receipt_sha256",
        )
        object.__setattr__(
            self,
            "readback_sha256",
            _sealed_digest(
                self.readback_sha256,
                identity=self._identity_dict(),
                field_name="artifact_readback.readback_sha256",
            ),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "retained_byte_hours": self.retained_byte_hours,
            "incremental_charge_microusd": self.incremental_charge_microusd,
            "direct_response_sha256": self.direct_response_sha256,
            "direct_response_receipt_sha256": self.direct_response_receipt_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "readback_sha256": self.readback_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(cls.__dataclass_fields__) | {"schema_version"}
        _require_exact_keys(payload, expected=expected, label="artifact cost readback")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("artifact readback schema is unsupported")
        return cls(
            artifact_id=cast("int", payload["artifact_id"]),
            artifact_name=cast("str", payload["artifact_name"]),
            size_bytes=cast("int", payload["size_bytes"]),
            created_at=cast("str", payload["created_at"]),
            expires_at=cast("str", payload["expires_at"]),
            retained_byte_hours=cast("int", payload["retained_byte_hours"]),
            incremental_charge_microusd=cast("int", payload["incremental_charge_microusd"]),
            direct_response_sha256=cast("str", payload["direct_response_sha256"]),
            direct_response_receipt_sha256=cast("str", payload["direct_response_receipt_sha256"]),
            readback_sha256=cast("str", payload["readback_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class ExternalServiceCostReadbackV1:
    service_kind: ExternalServiceKind
    operation_count: int
    operation_inventory_sha256: str
    incremental_charge_microusd: int
    usage_response_sha256: str
    usage_response_receipt_sha256: str
    readback_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        if type(self.service_kind) is not ExternalServiceKind:
            raise FreeExecutionAdmissionError("external readback service kind is invalid")
        _uint(self.operation_count, field_name="operation_count")
        _sha256(self.operation_inventory_sha256, field_name="operation_inventory_sha256")
        _uint(
            self.incremental_charge_microusd,
            field_name="incremental_charge_microusd",
        )
        _sha256(self.usage_response_sha256, field_name="usage_response_sha256")
        _sha256(
            self.usage_response_receipt_sha256,
            field_name="usage_response_receipt_sha256",
        )
        object.__setattr__(
            self,
            "readback_sha256",
            _sealed_digest(
                self.readback_sha256,
                identity=self._identity_dict(),
                field_name="external_readback.readback_sha256",
            ),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "service_kind": self.service_kind.value,
            "operation_count": self.operation_count,
            "operation_inventory_sha256": self.operation_inventory_sha256,
            "incremental_charge_microusd": self.incremental_charge_microusd,
            "usage_response_sha256": self.usage_response_sha256,
            "usage_response_receipt_sha256": self.usage_response_receipt_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "readback_sha256": self.readback_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(cls.__dataclass_fields__) | {"schema_version"}
        _require_exact_keys(payload, expected=expected, label="external cost readback")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionAdmissionError("external readback schema is unsupported")
        try:
            kind = ExternalServiceKind(
                _exact_text(payload["service_kind"], field_name="service_kind")
            )
        except ValueError as exc:
            raise FreeExecutionAdmissionError("external readback service is unsupported") from exc
        return cls(
            service_kind=kind,
            operation_count=cast("int", payload["operation_count"]),
            operation_inventory_sha256=cast("str", payload["operation_inventory_sha256"]),
            incremental_charge_microusd=cast("int", payload["incremental_charge_microusd"]),
            usage_response_sha256=cast("str", payload["usage_response_sha256"]),
            usage_response_receipt_sha256=cast("str", payload["usage_response_receipt_sha256"]),
            readback_sha256=cast("str", payload["readback_sha256"]),
        )


def _logical_job_for_name(graph: JobGraphEvidenceV1, name: str) -> WorkflowJobRequirementV1:
    matches = tuple(
        item
        for item in graph.jobs
        if name == item.actual_name_prefix or name.startswith(f"{item.actual_name_prefix} ")
    )
    if len(matches) != 1:
        raise FreeExecutionAdmissionError("actual job name is absent or ambiguous in job graph")
    return matches[0]


def _derive_job_cost_readbacks(
    *,
    admission: FreeExecutionAdmissionV1,
    inventory: tuple[Mapping[str, object], ...],
    direct_responses: tuple[ExactHttpResponseV1, ...],
) -> tuple[ActualJobCostReadbackV1, ...]:
    graph = admission.job_graph
    if graph is None:
        raise FreeExecutionAdmissionError("blocked admission has no job graph")
    list_fields = frozenset(
        {"id", "name", "run_id", "run_attempt", "head_sha", "status", "conclusion"}
    )
    direct_fields = list_fields | {"billable_milliseconds", "incremental_charge_microusd"}
    inventory_by_id: dict[int, Mapping[str, object]] = {}
    for item in inventory:
        _require_exact_keys(item, expected=list_fields, label="job inventory item")
        item_id = _uint(item["id"], field_name="job.id", positive=True)
        inventory_by_id[item_id] = item
    responses_by_id: dict[int, ExactHttpResponseV1] = {}
    payloads_by_id: dict[int, Mapping[str, object]] = {}
    for response in direct_responses:
        payload = response.json_object()
        _require_exact_keys(payload, expected=direct_fields, label="direct job response")
        item_id = _uint(payload["id"], field_name="job.id", positive=True)
        if item_id in responses_by_id:
            raise FreeExecutionAdmissionError("direct job response is duplicated")
        _require_github_response(
            response,
            url=f"https://api.github.com/repos/{admission.repository}/actions/jobs/{item_id}",
        )
        responses_by_id[item_id] = response
        payloads_by_id[item_id] = payload
    if set(responses_by_id) != set(inventory_by_id):
        raise FreeExecutionAdmissionError("direct job response denominator is incomplete")
    results: list[ActualJobCostReadbackV1] = []
    counts: dict[str, int] = {}
    for item_id in sorted(inventory_by_id):
        listed = inventory_by_id[item_id]
        direct = payloads_by_id[item_id]
        if any(direct[field_name] != listed[field_name] for field_name in list_fields):
            raise FreeExecutionAdmissionError("direct job response differs from list inventory")
        if (
            direct["run_id"] != admission.run_id
            or direct["run_attempt"] != admission.run_attempt
            or direct["head_sha"] != admission.source_sha
            or direct["status"] != "completed"
            or direct["conclusion"] not in _CONCLUSIONS
        ):
            raise FreeExecutionAdmissionError("direct job completion identity is invalid")
        name = _exact_text(direct["name"], field_name="job.name")
        requirement = _logical_job_for_name(graph, name)
        counts[requirement.logical_job_id] = counts.get(requirement.logical_job_id, 0) + 1
        if counts[requirement.logical_job_id] > requirement.maximum_instances:
            raise FreeExecutionAdmissionError("actual job count exceeds workflow graph bound")
        response = responses_by_id[item_id]
        results.append(
            ActualJobCostReadbackV1(
                job_id=item_id,
                job_name=name,
                logical_job_id=requirement.logical_job_id,
                conclusion=cast("str", direct["conclusion"]),
                billable_milliseconds=_uint(
                    direct["billable_milliseconds"],
                    field_name="billable_milliseconds",
                ),
                incremental_charge_microusd=_uint(
                    direct["incremental_charge_microusd"],
                    field_name="incremental_charge_microusd",
                ),
                direct_response_sha256=response.body_sha256,
                direct_response_receipt_sha256=response.receipt_sha256,
            )
        )
    return tuple(results)


def _derive_artifact_cost_readbacks(
    *,
    admission: FreeExecutionAdmissionV1,
    inventory: tuple[Mapping[str, object], ...],
    direct_responses: tuple[ExactHttpResponseV1, ...],
) -> tuple[ArtifactCostReadbackV1, ...]:
    list_fields = frozenset(
        {
            "id",
            "name",
            "size_in_bytes",
            "expired",
            "created_at",
            "expires_at",
            "workflow_run_id",
            "head_sha",
        }
    )
    direct_fields = list_fields | {"incremental_charge_microusd"}
    inventory_by_id: dict[int, Mapping[str, object]] = {}
    for item in inventory:
        _require_exact_keys(item, expected=list_fields, label="artifact inventory item")
        item_id = _uint(item["id"], field_name="artifact.id", positive=True)
        inventory_by_id[item_id] = item
    responses_by_id: dict[int, ExactHttpResponseV1] = {}
    payloads_by_id: dict[int, Mapping[str, object]] = {}
    for response in direct_responses:
        payload = response.json_object()
        _require_exact_keys(payload, expected=direct_fields, label="direct artifact response")
        item_id = _uint(payload["id"], field_name="artifact.id", positive=True)
        if item_id in responses_by_id:
            raise FreeExecutionAdmissionError("direct artifact response is duplicated")
        _require_github_response(
            response,
            url=f"https://api.github.com/repos/{admission.repository}/actions/artifacts/{item_id}",
        )
        responses_by_id[item_id] = response
        payloads_by_id[item_id] = payload
    if set(responses_by_id) != set(inventory_by_id):
        raise FreeExecutionAdmissionError("direct artifact response denominator is incomplete")
    results: list[ArtifactCostReadbackV1] = []
    for item_id in sorted(inventory_by_id):
        listed = inventory_by_id[item_id]
        direct = payloads_by_id[item_id]
        if any(direct[field_name] != listed[field_name] for field_name in list_fields):
            raise FreeExecutionAdmissionError(
                "direct artifact response differs from list inventory"
            )
        if (
            direct["workflow_run_id"] != admission.run_id
            or direct["head_sha"] != admission.source_sha
            or direct["expired"] is not False
        ):
            raise FreeExecutionAdmissionError("direct artifact identity is foreign or expired")
        created = _timestamp(direct["created_at"], field_name="artifact.created_at")
        expires = _timestamp(direct["expires_at"], field_name="artifact.expires_at")
        size = _uint(direct["size_in_bytes"], field_name="artifact.size_in_bytes")
        response = responses_by_id[item_id]
        results.append(
            ArtifactCostReadbackV1(
                artifact_id=item_id,
                artifact_name=_exact_text(direct["name"], field_name="artifact.name"),
                size_bytes=size,
                created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                expires_at=expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
                retained_byte_hours=_checked_multiply(
                    size,
                    _ceil_hours(created, expires),
                    field_name="artifact retained byte-hours",
                ),
                incremental_charge_microusd=_uint(
                    direct["incremental_charge_microusd"],
                    field_name="incremental_charge_microusd",
                ),
                direct_response_sha256=response.body_sha256,
                direct_response_receipt_sha256=response.receipt_sha256,
            )
        )
    return tuple(results)


def _billing_payload(
    response: ExactHttpResponseV1,
    *,
    admission: FreeExecutionAdmissionV1,
) -> tuple[int, bool, bool]:
    pricing = admission.repository_pricing
    if pricing is None:
        raise FreeExecutionAdmissionError("blocked admission has no billing identity")
    _require_github_response(
        response,
        url=_account_url(pricing.owner_type, pricing.owner_login),
    )
    payload = response.json_object()
    _require_exact_keys(
        payload,
        expected=frozenset({"account", "incremental_charge_microusd", "settled", "overlap_absent"}),
        label="billing readback",
    )
    if _parse_account(payload)[3] != pricing.owner_identity_sha256:
        raise FreeExecutionAdmissionError("billing readback account is foreign")
    return (
        _uint(
            payload["incremental_charge_microusd"],
            field_name="incremental_charge_microusd",
        ),
        payload["settled"] is True,
        payload["overlap_absent"] is True,
    )


def _cost_storage_readback(
    response: ExactHttpResponseV1,
    *,
    admission: FreeExecutionAdmissionV1,
    artifacts: tuple[ArtifactCostReadbackV1, ...],
    readback: datetime,
) -> tuple[int, int, int, int]:
    pricing = admission.repository_pricing
    if pricing is None:
        raise FreeExecutionAdmissionError("blocked admission has no storage identity")
    _require_github_response(
        response,
        url=_account_url(pricing.owner_type, pricing.owner_login),
    )
    payload = response.json_object()
    _require_exact_keys(
        payload,
        expected=frozenset({"account", "artifact_packages"}),
        label="cost storage inventory",
    )
    if _parse_account(payload)[3] != pricing.owner_identity_sha256:
        raise FreeExecutionAdmissionError("cost storage inventory account is foreign")
    _, month_end, _, _ = _billing_window(readback)
    item_count, current, accrued, future = _storage_items(
        payload,
        at=readback,
        month_end=month_end,
    )
    section = _mapping(payload["artifact_packages"], field_name="artifact_packages")
    raw_items = section["items"]
    assert type(raw_items) is list
    item_index: dict[tuple[str, int], Mapping[str, object]] = {}
    for raw_item in cast("list[object]", raw_items):
        item = _mapping(raw_item, field_name="artifact_packages.item")
        item_index[
            (
                _exact_text(item["kind"], field_name="item.kind"),
                _uint(item["id"], field_name="item.id", positive=True),
            )
        ] = item
    for artifact in artifacts:
        item = item_index.get(("artifact", artifact.artifact_id))
        if (
            item is None
            or item["size_bytes"] != artifact.size_bytes
            or item["expires_at"] != artifact.expires_at
        ):
            raise FreeExecutionAdmissionError(
                "run artifact is absent or mismatched in complete storage inventory"
            )
    return item_count, current, accrued, future


def _external_usage_readbacks(
    *,
    admission: FreeExecutionAdmissionV1,
    responses: tuple[tuple[ExternalServiceKind, ExactHttpResponseV1], ...],
) -> tuple[ExternalServiceCostReadbackV1, ...]:
    kinds = tuple(item[0] for item in responses)
    if kinds != admission.intent.required_external_services:
        raise FreeExecutionAdmissionError("external usage denominator is incomplete")
    results: list[ExternalServiceCostReadbackV1] = []
    for kind, response in responses:
        expected_url = (
            f"https://api.github.com/repos/{admission.repository}/actions/runs/"
            f"{admission.run_id}/attempts/{admission.run_attempt}/"
            f"free-execution-usage/{kind.value}"
        )
        _require_github_response(response, url=expected_url)
        payload = response.json_object()
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "repository",
                    "source_sha",
                    "run_id",
                    "run_attempt",
                    "service_kind",
                    "operation_sha256s",
                    "incremental_charge_microusd",
                    "settled",
                }
            ),
            label="external usage response",
        )
        if (
            payload["repository"] != admission.repository
            or payload["source_sha"] != admission.source_sha
            or payload["run_id"] != admission.run_id
            or payload["run_attempt"] != admission.run_attempt
            or payload["service_kind"] != kind.value
            or payload["settled"] is not True
        ):
            raise FreeExecutionAdmissionError("external usage response identity is foreign")
        raw_operations = payload["operation_sha256s"]
        if type(raw_operations) is not list:
            raise FreeExecutionAdmissionError("external operation inventory must be an array")
        operations = tuple(
            _sha256(item, field_name="operation_sha256")
            for item in cast("list[object]", raw_operations)
        )
        if operations != tuple(sorted(set(operations))):
            raise FreeExecutionAdmissionError(
                "external operation inventory must be sorted and unique"
            )
        results.append(
            ExternalServiceCostReadbackV1(
                service_kind=kind,
                operation_count=len(operations),
                operation_inventory_sha256=_canonical_sha256(list(operations)),
                incremental_charge_microusd=_uint(
                    payload["incremental_charge_microusd"],
                    field_name="incremental_charge_microusd",
                ),
                usage_response_sha256=response.body_sha256,
                usage_response_receipt_sha256=response.receipt_sha256,
            )
        )
    expected_operations = tuple(
        sorted(
            operation_sha256
            for lane_operations in admission.intent.lane_operation_sha256s
            for operation_sha256 in lane_operations
        )
    )
    observed_operations = tuple(
        sorted(
            operation_sha256
            for _, response in responses
            for operation_sha256 in cast(
                "list[str]",
                response.json_object()["operation_sha256s"],
            )
        )
    )
    if observed_operations != expected_operations:
        raise FreeExecutionAdmissionError(
            "external operation inventory differs from exact issued manifest operations"
        )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class CostReadbackAuthorityBundleV1:
    """Private complete cost collector authority; no caller projections are accepted."""

    jobs_inventory: PagedInventoryAuthorityV1 = field(repr=False)
    artifacts_inventory: PagedInventoryAuthorityV1 = field(repr=False)
    direct_job_responses: tuple[ExactHttpResponseV1, ...] = field(repr=False)
    direct_artifact_responses: tuple[ExactHttpResponseV1, ...] = field(repr=False)
    storage_inventory_response: ExactHttpResponseV1 = field(repr=False)
    billing_baseline_response: ExactHttpResponseV1 = field(repr=False)
    billing_post_response: ExactHttpResponseV1 = field(repr=False)
    billing_stable_response: ExactHttpResponseV1 = field(repr=False)
    cache_first_response: ExactHttpResponseV1 = field(repr=False)
    cache_stable_response: ExactHttpResponseV1 = field(repr=False)
    external_usage_responses: tuple[tuple[ExternalServiceKind, ExactHttpResponseV1], ...] = field(
        repr=False
    )

    integration_blocker_codes: ClassVar[tuple[str, ...]] = _COST_INTEGRATION_BLOCKERS

    def __post_init__(self) -> None:
        if (
            type(self.jobs_inventory) is not PagedInventoryAuthorityV1
            or type(self.artifacts_inventory) is not PagedInventoryAuthorityV1
            or type(self.direct_job_responses) is not tuple
            or type(self.direct_artifact_responses) is not tuple
            or any(type(item) is not ExactHttpResponseV1 for item in self.direct_job_responses)
            or any(type(item) is not ExactHttpResponseV1 for item in self.direct_artifact_responses)
            or any(
                type(item) is not ExactHttpResponseV1
                for item in (
                    self.billing_baseline_response,
                    self.billing_post_response,
                    self.billing_stable_response,
                    self.storage_inventory_response,
                    self.cache_first_response,
                    self.cache_stable_response,
                )
            )
            or type(self.external_usage_responses) is not tuple
        ):
            raise FreeExecutionAdmissionError("cost readback raw authority is invalid")
        if any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not ExternalServiceKind
            or type(item[1]) is not ExactHttpResponseV1
            for item in self.external_usage_responses
        ):
            raise FreeExecutionAdmissionError("external usage response rows are invalid")
        kinds = tuple(item[0] for item in self.external_usage_responses)
        if kinds != tuple(sorted(set(kinds), key=lambda item: item.value)):
            raise FreeExecutionAdmissionError("external usage responses are not sorted unique")

    def authority_sha256(self) -> str:
        return _canonical_sha256(
            {
                "schema_version": 1,
                "jobs_first": [item.public_identity() for item in self.jobs_inventory.first_pages],
                "jobs_stable": [
                    item.public_identity() for item in self.jobs_inventory.stable_pages
                ],
                "artifacts_first": [
                    item.public_identity() for item in self.artifacts_inventory.first_pages
                ],
                "artifacts_stable": [
                    item.public_identity() for item in self.artifacts_inventory.stable_pages
                ],
                "direct_jobs": [item.public_identity() for item in self.direct_job_responses],
                "direct_artifacts": [
                    item.public_identity() for item in self.direct_artifact_responses
                ],
                "storage_inventory": self.storage_inventory_response.public_identity(),
                "billing_baseline": self.billing_baseline_response.public_identity(),
                "billing_post": self.billing_post_response.public_identity(),
                "billing_stable": self.billing_stable_response.public_identity(),
                "cache_first": self.cache_first_response.public_identity(),
                "cache_stable": self.cache_stable_response.public_identity(),
                "external_usage": [
                    {"service_kind": kind.value, "response": response.public_identity()}
                    for kind, response in self.external_usage_responses
                ],
            }
        )


@dataclass(frozen=True, slots=True)
class FreeExecutionCostReadbackV1:
    admission_sha256: str
    authority_sha256: str
    jobs_inventory_sha256: str
    artifacts_inventory_sha256: str
    jobs_total_count: int
    artifacts_total_count: int
    jobs: tuple[ActualJobCostReadbackV1, ...]
    artifacts: tuple[ArtifactCostReadbackV1, ...]
    external_services: tuple[ExternalServiceCostReadbackV1, ...]
    billing_period_start: str
    billing_period_end: str
    billing_period_hours: int
    storage_existing_item_count: int
    storage_current_bytes: int
    storage_accrued_byte_hours: int
    storage_existing_future_byte_hours: int
    storage_free_byte_hours: int
    cache_current_bytes: int
    billing_baseline_incremental_charge_microusd: int
    billing_incremental_charge_microusd: int
    maximum_incremental_charge_microusd: int
    readback_at: str
    status: FreeExecutionCostReadbackStatus
    readback_sha256: str = ""

    schema_version: ClassVar[int] = FREE_EXECUTION_COST_READBACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status is FreeExecutionCostReadbackStatus.VERIFIED_ZERO:
            _raise_integration_blocked(
                stage="verified-zero free-execution cost readback",
                codes=_COST_INTEGRATION_BLOCKERS,
            )
        _sha256(self.admission_sha256, field_name="admission_sha256")
        _sha256(self.authority_sha256, field_name="authority_sha256")
        _sha256(self.jobs_inventory_sha256, field_name="jobs_inventory_sha256")
        _sha256(self.artifacts_inventory_sha256, field_name="artifacts_inventory_sha256")
        jobs_count = _uint(self.jobs_total_count, field_name="jobs_total_count")
        artifacts_count = _uint(self.artifacts_total_count, field_name="artifacts_total_count")
        if (
            type(self.jobs) is not tuple
            or len(self.jobs) != jobs_count
            or any(type(item) is not ActualJobCostReadbackV1 for item in self.jobs)
        ):
            raise FreeExecutionAdmissionError("job readback denominator is invalid")
        if (
            type(self.artifacts) is not tuple
            or len(self.artifacts) != artifacts_count
            or any(type(item) is not ArtifactCostReadbackV1 for item in self.artifacts)
        ):
            raise FreeExecutionAdmissionError("artifact readback denominator is invalid")
        if type(self.external_services) is not tuple or any(
            type(item) is not ExternalServiceCostReadbackV1 for item in self.external_services
        ):
            raise FreeExecutionAdmissionError("external readback inventory is invalid")
        jobs = tuple(ActualJobCostReadbackV1.from_dict(item.to_dict()) for item in self.jobs)
        artifacts = tuple(
            ArtifactCostReadbackV1.from_dict(item.to_dict()) for item in self.artifacts
        )
        external = tuple(
            ExternalServiceCostReadbackV1.from_dict(item.to_dict())
            for item in self.external_services
        )
        if tuple(item.job_id for item in jobs) != tuple(sorted({item.job_id for item in jobs})):
            raise FreeExecutionAdmissionError("job readbacks are not sorted and unique")
        if tuple(item.artifact_id for item in artifacts) != tuple(
            sorted({item.artifact_id for item in artifacts})
        ):
            raise FreeExecutionAdmissionError("artifact readbacks are not sorted and unique")
        kinds = tuple(item.service_kind for item in external)
        if kinds != tuple(sorted(set(kinds), key=lambda item: item.value)):
            raise FreeExecutionAdmissionError("external readbacks are not sorted and unique")
        object.__setattr__(self, "jobs", jobs)
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "external_services", external)
        readback = _timestamp(self.readback_at, field_name="readback_at")
        period_start = _timestamp(self.billing_period_start, field_name="billing_period_start")
        period_end = _timestamp(self.billing_period_end, field_name="billing_period_end")
        expected_start, expected_end, expected_hours, _ = _billing_window(readback)
        if (
            period_start,
            period_end,
            self.billing_period_hours,
        ) != (expected_start, expected_end, expected_hours):
            raise FreeExecutionAdmissionError("cost readback billing calendar is invalid")
        _uint(self.storage_existing_item_count, field_name="storage_existing_item_count")
        current_storage = _uint(self.storage_current_bytes, field_name="storage_current_bytes")
        accrued_storage = _uint(
            self.storage_accrued_byte_hours,
            field_name="storage_accrued_byte_hours",
        )
        future_storage = _uint(
            self.storage_existing_future_byte_hours,
            field_name="storage_existing_future_byte_hours",
        )
        expected_free = _checked_multiply(
            ARTIFACT_PACKAGES_FREE_FLOOR_BYTES,
            expected_hours,
            field_name="storage_free_byte_hours",
        )
        if self.storage_free_byte_hours != expected_free:
            raise FreeExecutionAdmissionError("cost readback storage free floor is invalid")
        if (
            current_storage > ARTIFACT_PACKAGES_FREE_FLOOR_BYTES
            or _checked_add(
                accrued_storage,
                future_storage,
                field_name="storage liability",
            )
            > expected_free
        ):
            raise FreeExecutionAdmissionError("cost readback storage liability exceeds free usage")
        if (
            _uint(self.cache_current_bytes, field_name="cache_current_bytes")
            > CACHE_FREE_FLOOR_BYTES
        ):
            raise FreeExecutionAdmissionError("cost readback cache liability exceeds free usage")
        baseline_billing = _uint(
            self.billing_baseline_incremental_charge_microusd,
            field_name="billing_baseline_incremental_charge_microusd",
        )
        billing = _uint(
            self.billing_incremental_charge_microusd,
            field_name="billing_incremental_charge_microusd",
        )
        derived_maximum = max(baseline_billing, billing)
        for amount in (
            *(item.incremental_charge_microusd for item in jobs),
            *(item.incremental_charge_microusd for item in artifacts),
            *(item.incremental_charge_microusd for item in external),
        ):
            derived_maximum = max(derived_maximum, amount)
        if self.maximum_incremental_charge_microusd != derived_maximum:
            raise FreeExecutionAdmissionError("cost readback charge maximum is invalid")
        expected_status = (
            FreeExecutionCostReadbackStatus.VERIFIED_ZERO
            if derived_maximum == 0
            else FreeExecutionCostReadbackStatus.CHARGED
        )
        if self.status is not expected_status:
            raise FreeExecutionAdmissionError("cost readback status differs from exact charges")
        object.__setattr__(
            self,
            "readback_sha256",
            _sealed_digest(
                self.readback_sha256,
                identity=self._identity_dict(),
                field_name="cost_readback.readback_sha256",
            ),
        )

    @classmethod
    def from_authority(
        cls,
        *,
        admission: FreeExecutionAdmissionV1,
        authority: CostReadbackAuthorityBundleV1,
    ) -> Self:
        if admission.status is not FreeExecutionAdmissionStatus.ADMITTED:
            raise FreeExecutionAdmissionError("blocked admission cannot have positive readback")
        expected_jobs_url = (
            f"https://api.github.com/repos/{admission.repository}/actions/runs/"
            f"{admission.run_id}/attempts/{admission.run_attempt}/jobs"
        )
        expected_artifacts_url = (
            f"https://api.github.com/repos/{admission.repository}/actions/runs/"
            f"{admission.run_id}/artifacts"
        )
        if authority.jobs_inventory.base_url != expected_jobs_url:
            raise FreeExecutionAdmissionError("job inventory base URL is foreign")
        if authority.artifacts_inventory.base_url != expected_artifacts_url:
            raise FreeExecutionAdmissionError("artifact inventory base URL is foreign")
        jobs_inventory, jobs_total, jobs_sha, _, _, jobs_at = authority.jobs_inventory.derive()
        artifacts_inventory, artifacts_total, artifacts_sha, _, _, artifacts_at = (
            authority.artifacts_inventory.derive()
        )
        jobs = _derive_job_cost_readbacks(
            admission=admission,
            inventory=jobs_inventory,
            direct_responses=authority.direct_job_responses,
        )
        artifacts = _derive_artifact_cost_readbacks(
            admission=admission,
            inventory=artifacts_inventory,
            direct_responses=authority.direct_artifact_responses,
        )
        baseline = _billing_payload(authority.billing_baseline_response, admission=admission)
        post = _billing_payload(authority.billing_post_response, admission=admission)
        stable = _billing_payload(authority.billing_stable_response, admission=admission)
        if post != stable or not post[1] or not post[2]:
            raise FreeExecutionAdmissionError("billing readback is unsettled or unstable")
        if (
            authority.billing_post_response.observed_at
            < authority.billing_baseline_response.observed_at
        ):
            raise FreeExecutionAdmissionError("billing post-readback predates baseline")
        if (
            authority.billing_stable_response.observed_at
            - authority.billing_post_response.observed_at
        ).total_seconds() < _MIN_STABILITY_SECONDS:
            raise FreeExecutionAdmissionError("billing stable-readback window is too short")
        stable_billing_at = authority.billing_stable_response.observed_at
        if any(
            not _timestamp(jobs_at, field_name="jobs_inventory.readback_at")
            <= response.observed_at
            <= stable_billing_at
            for response in authority.direct_job_responses
        ) or any(
            not _timestamp(artifacts_at, field_name="artifacts_inventory.readback_at")
            <= response.observed_at
            <= stable_billing_at
            for response in authority.direct_artifact_responses
        ):
            raise FreeExecutionAdmissionError(
                "direct item receipts are not bracketed by stable inventory and billing"
            )
        if authority.storage_inventory_response.observed_at != (
            authority.billing_stable_response.observed_at
        ):
            raise FreeExecutionAdmissionError(
                "cost storage inventory is not co-timed with stable billing readback"
            )
        storage_item_count, storage_current, storage_accrued, storage_future = (
            _cost_storage_readback(
                authority.storage_inventory_response,
                admission=admission,
                artifacts=artifacts,
                readback=authority.storage_inventory_response.observed_at,
            )
        )
        cache_url = f"https://api.github.com/repos/{admission.repository}/actions/cache/usage"
        _require_github_response(authority.cache_first_response, url=cache_url)
        _require_github_response(authority.cache_stable_response, url=cache_url)
        cache_first = authority.cache_first_response.json_object()
        cache_stable = authority.cache_stable_response.json_object()
        cache_keys = frozenset({"active_caches_count", "active_caches_size_in_bytes"})
        _require_exact_keys(cache_first, expected=cache_keys, label="cache readback")
        _require_exact_keys(cache_stable, expected=cache_keys, label="cache readback")
        _uint(cache_stable["active_caches_count"], field_name="active_caches_count")
        cache_current = _uint(
            cache_stable["active_caches_size_in_bytes"],
            field_name="active_caches_size_in_bytes",
        )
        if (
            cache_first != cache_stable
            or (
                authority.cache_stable_response.observed_at
                - authority.cache_first_response.observed_at
            ).total_seconds()
            < _MIN_STABILITY_SECONDS
        ):
            raise FreeExecutionAdmissionError("cache readback is incomplete or unstable")
        if authority.cache_stable_response.observed_at != stable_billing_at:
            raise FreeExecutionAdmissionError(
                "cache usage is not co-timed with stable billing readback"
            )
        storage_plan = admission.storage_cost
        if storage_plan is None:
            raise FreeExecutionAdmissionError("positive admission omits its storage plan")
        actual_artifact_bytes = sum(item.size_bytes for item in artifacts)
        actual_artifact_byte_hours = sum(item.retained_byte_hours for item in artifacts)
        if (
            actual_artifact_bytes > storage_plan.planned_artifact_max_bytes
            or actual_artifact_byte_hours > storage_plan.planned_artifact_max_byte_hours
            or any(
                _ceil_hours(
                    _timestamp(item.created_at, field_name="artifact.created_at"),
                    _timestamp(item.expires_at, field_name="artifact.expires_at"),
                )
                > storage_plan.planned_artifact_retention_hours
                for item in artifacts
            )
        ):
            raise FreeExecutionAdmissionError(
                "actual artifact size/retention exceeds the exact admitted plan"
            )
        cache_growth = max(0, cache_current - storage_plan.cache_current_bytes)
        if cache_growth > storage_plan.planned_cache_max_bytes:
            raise FreeExecutionAdmissionError("actual cache growth exceeds the exact admitted plan")
        external = _external_usage_readbacks(
            admission=admission,
            responses=authority.external_usage_responses,
        )
        if any(
            response.observed_at != stable_billing_at
            for _, response in authority.external_usage_responses
        ):
            raise FreeExecutionAdmissionError(
                "external operation inventories are not co-timed with stable billing"
            )
        maximum_charge = max(
            baseline[0],
            post[0],
            *(item.incremental_charge_microusd for item in jobs),
            *(item.incremental_charge_microusd for item in artifacts),
            *(item.incremental_charge_microusd for item in external),
        )
        readback_at = max(
            jobs_at,
            artifacts_at,
            authority.billing_stable_response.response_date,
            authority.storage_inventory_response.response_date,
            authority.cache_stable_response.response_date,
            *(response.response_date for _, response in authority.external_usage_responses),
        )
        period_start, period_end, period_hours, _ = _billing_window(
            _timestamp(readback_at, field_name="readback_at")
        )
        free_storage_hours = _checked_multiply(
            ARTIFACT_PACKAGES_FREE_FLOOR_BYTES,
            period_hours,
            field_name="storage_free_byte_hours",
        )
        return cls(
            admission_sha256=admission.admission_sha256,
            authority_sha256=authority.authority_sha256(),
            jobs_inventory_sha256=jobs_sha,
            artifacts_inventory_sha256=artifacts_sha,
            jobs_total_count=jobs_total,
            artifacts_total_count=artifacts_total,
            jobs=jobs,
            artifacts=artifacts,
            external_services=external,
            billing_period_start=period_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            billing_period_end=period_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            billing_period_hours=period_hours,
            storage_existing_item_count=storage_item_count,
            storage_current_bytes=storage_current,
            storage_accrued_byte_hours=storage_accrued,
            storage_existing_future_byte_hours=storage_future,
            storage_free_byte_hours=free_storage_hours,
            cache_current_bytes=cache_current,
            billing_baseline_incremental_charge_microusd=baseline[0],
            billing_incremental_charge_microusd=post[0],
            maximum_incremental_charge_microusd=maximum_charge,
            readback_at=readback_at,
            status=(
                FreeExecutionCostReadbackStatus.VERIFIED_ZERO
                if maximum_charge == 0
                else FreeExecutionCostReadbackStatus.CHARGED
            ),
        )

    def validate_for(
        self,
        *,
        admission: FreeExecutionAdmissionV1,
        authority: CostReadbackAuthorityBundleV1,
    ) -> None:
        expected = type(self).from_authority(admission=admission, authority=authority)
        if expected != self:
            raise FreeExecutionAdmissionError("cost readback differs from raw authority")

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "admission_sha256": self.admission_sha256,
            "authority_sha256": self.authority_sha256,
            "jobs_inventory_sha256": self.jobs_inventory_sha256,
            "artifacts_inventory_sha256": self.artifacts_inventory_sha256,
            "jobs_total_count": self.jobs_total_count,
            "artifacts_total_count": self.artifacts_total_count,
            "jobs": [item.to_dict() for item in self.jobs],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "external_services": [item.to_dict() for item in self.external_services],
            "billing_period_start": self.billing_period_start,
            "billing_period_end": self.billing_period_end,
            "billing_period_hours": self.billing_period_hours,
            "storage_existing_item_count": self.storage_existing_item_count,
            "storage_current_bytes": self.storage_current_bytes,
            "storage_accrued_byte_hours": self.storage_accrued_byte_hours,
            "storage_existing_future_byte_hours": (self.storage_existing_future_byte_hours),
            "storage_free_byte_hours": self.storage_free_byte_hours,
            "cache_current_bytes": self.cache_current_bytes,
            "billing_baseline_incremental_charge_microusd": (
                self.billing_baseline_incremental_charge_microusd
            ),
            "billing_incremental_charge_microusd": (self.billing_incremental_charge_microusd),
            "maximum_incremental_charge_microusd": (self.maximum_incremental_charge_microusd),
            "readback_at": self.readback_at,
            "status": self.status.value,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "readback_sha256": self.readback_sha256}

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "admission_sha256",
                "authority_sha256",
                "jobs_inventory_sha256",
                "artifacts_inventory_sha256",
                "jobs_total_count",
                "artifacts_total_count",
                "jobs",
                "artifacts",
                "external_services",
                "billing_period_start",
                "billing_period_end",
                "billing_period_hours",
                "storage_existing_item_count",
                "storage_current_bytes",
                "storage_accrued_byte_hours",
                "storage_existing_future_byte_hours",
                "storage_free_byte_hours",
                "cache_current_bytes",
                "billing_baseline_incremental_charge_microusd",
                "billing_incremental_charge_microusd",
                "maximum_incremental_charge_microusd",
                "readback_at",
                "status",
                "readback_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="cost readback")
        if (
            payload["schema_version"] != cls.schema_version
            or type(payload["schema_version"]) is not int
        ):
            raise FreeExecutionAdmissionError("cost readback schema is unsupported")
        raw_jobs = payload["jobs"]
        raw_artifacts = payload["artifacts"]
        raw_external = payload["external_services"]
        if (
            type(raw_jobs) is not list
            or type(raw_artifacts) is not list
            or type(raw_external) is not list
        ):
            raise FreeExecutionAdmissionError("cost readback arrays are invalid")
        try:
            status = FreeExecutionCostReadbackStatus(
                _exact_text(payload["status"], field_name="status")
            )
        except ValueError as exc:
            raise FreeExecutionAdmissionError("cost readback status is unsupported") from exc
        return cls(
            admission_sha256=cast("str", payload["admission_sha256"]),
            authority_sha256=cast("str", payload["authority_sha256"]),
            jobs_inventory_sha256=cast("str", payload["jobs_inventory_sha256"]),
            artifacts_inventory_sha256=cast("str", payload["artifacts_inventory_sha256"]),
            jobs_total_count=cast("int", payload["jobs_total_count"]),
            artifacts_total_count=cast("int", payload["artifacts_total_count"]),
            jobs=tuple(
                ActualJobCostReadbackV1.from_dict(_mapping(item, field_name=f"jobs[{index}]"))
                for index, item in enumerate(cast("list[object]", raw_jobs))
            ),
            artifacts=tuple(
                ArtifactCostReadbackV1.from_dict(_mapping(item, field_name=f"artifacts[{index}]"))
                for index, item in enumerate(cast("list[object]", raw_artifacts))
            ),
            external_services=tuple(
                ExternalServiceCostReadbackV1.from_dict(
                    _mapping(item, field_name=f"external_services[{index}]")
                )
                for index, item in enumerate(cast("list[object]", raw_external))
            ),
            billing_period_start=cast("str", payload["billing_period_start"]),
            billing_period_end=cast("str", payload["billing_period_end"]),
            billing_period_hours=cast("int", payload["billing_period_hours"]),
            storage_existing_item_count=cast("int", payload["storage_existing_item_count"]),
            storage_current_bytes=cast("int", payload["storage_current_bytes"]),
            storage_accrued_byte_hours=cast("int", payload["storage_accrued_byte_hours"]),
            storage_existing_future_byte_hours=cast(
                "int", payload["storage_existing_future_byte_hours"]
            ),
            storage_free_byte_hours=cast("int", payload["storage_free_byte_hours"]),
            cache_current_bytes=cast("int", payload["cache_current_bytes"]),
            billing_baseline_incremental_charge_microusd=cast(
                "int", payload["billing_baseline_incremental_charge_microusd"]
            ),
            billing_incremental_charge_microusd=cast(
                "int", payload["billing_incremental_charge_microusd"]
            ),
            maximum_incremental_charge_microusd=cast(
                "int", payload["maximum_incremental_charge_microusd"]
            ),
            readback_at=cast("str", payload["readback_at"]),
            status=status,
            readback_sha256=cast("str", payload["readback_sha256"]),
        )

    @classmethod
    def from_bytes(cls, encoded: bytes) -> Self:
        return cls.from_dict(_decode_canonical_object(encoded))
