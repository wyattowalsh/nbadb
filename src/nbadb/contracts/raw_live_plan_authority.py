"""Public, normalized live sealed-plan authority contracts.

These structures are persistence shapes, not self-authorizing capabilities.
The generation row stores exact canonical public plan bytes once, and the
observation binding projects one live request onto that generation.  Public
authority validators deliberately fail closed until a repo-pinned authenticated
collector supplies independently acquired trust; caller-provided digest strings
cannot authorize these structural records.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import ClassVar, Literal, Never, Self, cast

from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    validate_observation_route_landing,
    validate_raw_request_authority_bundle,
    validate_request_attempt_identity,
    validate_request_observation,
)
from nbadb.contracts.raw_request_reconstruction import (
    LiveSnapshotPlanAuthorityV2,
    RawRequestReconstructionError,
)

__all__ = [
    "GenerationKind",
    "LIVE_PLAN_KIND",
    "MAX_LIVE_PLAN_BYTES",
    "LivePlanCallAdmissionV2",
    "LivePlanItemV2",
    "LiveObservationPlanBindingV2",
    "LivePlanGenerationReceiptV2",
    "RawLivePlanAuthorityError",
    "validate_live_plan_authority_tables",
    "validate_live_observation_plan_authority",
]

GenerationKind = Literal[
    "full_root",
    "full_derived_game_fanout",
    "successor_wave_0",
    "successor_wave_1",
    "successor_update",
]

MAX_LIVE_PLAN_BYTES = 16 * 1024 * 1024
LIVE_PLAN_KIND = "nbadb_live_execution_plan_v2"
_MAX_PLAN_ITEMS = 1_000_000
_MAX_ROUTE_IDS = 4_096
_MAX_TEXT = 1_024
_MAX_LIVE_PLAN_TABLE_ROWS = 1_000_000
_MAX_LIVE_PLAN_TABLE_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z")
_SAFE_ARTIFACT_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z")
_FORBIDDEN_KEY_RE = re.compile(
    r"(?:api[._:-]?key|access[._:-]?key|authorization|cookie|credential|password|proxy|"
    r"secret|token|vpn|command|argument|environment|url|uri|"
    r"(?:^|[._:-])(?:local_path|filesystem_path|cache_path|proxy_host|proxy_ip|"
    r"vpn_host|vpn_ip|request_headers|response_headers)(?:$|[._:-]))",
    re.IGNORECASE,
)
_FORBIDDEN_VALUE_RE = re.compile(
    r"(?:\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\bgh[opurs]_[A-Za-z0-9]{20,}|"
    r"-----BEGIN [A-Z ]+ PRIVATE KEY-----)",
    re.IGNORECASE,
)
_GENERATION_KINDS = {
    "full_root",
    "full_derived_game_fanout",
    "successor_wave_0",
    "successor_wave_1",
    "successor_update",
}
_PLAN_ROOT_KEYS = frozenset({"items", "kind", "schema_version"})
_PLAN_ITEM_KEYS = frozenset(
    {
        "chain_id",
        "endpoint_contract_sha256",
        "endpoint_id",
        "lane_id",
        "logical_invocation_sha256",
        "plan_item_ordinal",
        "provider_authority_sha256",
        "provider_call_sha256",
        "route_ids",
        "run_attempt",
        "run_id",
        "safe_parameters_sha256",
        "scope_sha256",
        "semantic_request_sha256",
        "source_sha",
    }
)


class RawLivePlanAuthorityError(ValueError):
    """A public live-plan generation or observation binding is not exact."""


def _fail(message: str) -> Never:
    raise RawLivePlanAuthorityError(message)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError("live-plan value is not canonical JSON") from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be a lowercase SHA-256")
    return value


def _git_sha(value: object, *, field_name: str) -> str:
    if type(value) is not str or _GIT_SHA_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be a lowercase Git SHA")
    return value


def _safe_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be exact safe identity text")
    if _FORBIDDEN_KEY_RE.search(value):
        _fail(f"{field_name} contains a forbidden identity token")
    if _FORBIDDEN_VALUE_RE.search(value):
        _fail(f"{field_name} contains secret-shaped public text")
    return value


def _reject_secret_shaped_values(value: object) -> None:
    """Reject secret-shaped strings anywhere in one exact public JSON graph."""

    stack = [value]
    nodes = 0
    while stack:
        item = stack.pop()
        nodes += 1
        if nodes > _MAX_PLAN_ITEMS * len(_PLAN_ITEM_KEYS):
            _fail("sealed live plan exceeds its bounded public JSON graph")
        if type(item) is str:
            if _FORBIDDEN_VALUE_RE.search(item):
                _fail("sealed live plan contains secret-shaped public text")
        elif type(item) is list:
            stack.extend(cast("list[object]", item))
        elif type(item) is dict:
            stack.extend(cast("dict[object, object]", item).values())


def _positive(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1 or value > 2**63 - 1:
        _fail(f"{field_name} must be a positive bounded integer")
    return value


def _nonnegative(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        _fail(f"{field_name} must be a nonnegative bounded integer")
    return value


def _utc(value: object, *, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is not UTC or value.fold != 0:
        _fail(f"{field_name} must be an exact aware UTC datetime")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("sealed live plan contains duplicate JSON keys")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class LivePlanItemV2:
    """One typed, canonical provider-call member of a sealed live plan."""

    plan_item_ordinal: int
    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    semantic_request_sha256: str
    logical_invocation_sha256: str
    provider_call_sha256: str
    scope_sha256: str
    safe_parameters_sha256: str
    endpoint_id: str
    endpoint_contract_sha256: str
    provider_authority_sha256: str
    route_ids: tuple[str, ...]
    plan_item_sha256: str

    def __post_init__(self) -> None:
        _nonnegative(self.plan_item_ordinal, field_name="plan_item_ordinal")
        _git_sha(self.source_sha, field_name="plan item source_sha")
        _positive(self.run_id, field_name="plan item run_id")
        _positive(self.run_attempt, field_name="plan item run_attempt")
        _safe_id(self.chain_id, field_name="plan item chain_id")
        _safe_id(self.lane_id, field_name="plan item lane_id")
        _safe_id(self.endpoint_id, field_name="plan item endpoint_id")
        for field_name in (
            "semantic_request_sha256",
            "logical_invocation_sha256",
            "provider_call_sha256",
            "scope_sha256",
            "safe_parameters_sha256",
            "endpoint_contract_sha256",
            "provider_authority_sha256",
            "plan_item_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        _route_ids(self.route_ids)
        if self.plan_item_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("sealed live plan item digest differs from its exact typed projection")

    def identity_payload(self) -> dict[str, object]:
        return {
            "plan_item_ordinal": self.plan_item_ordinal,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "semantic_request_sha256": self.semantic_request_sha256,
            "logical_invocation_sha256": self.logical_invocation_sha256,
            "provider_call_sha256": self.provider_call_sha256,
            "scope_sha256": self.scope_sha256,
            "safe_parameters_sha256": self.safe_parameters_sha256,
            "endpoint_id": self.endpoint_id,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "route_ids": list(self.route_ids),
        }

    def semantic_identity_payload(self) -> dict[str, object]:
        """Return provider-call membership identity without its array coordinate."""

        payload = self.identity_payload()
        payload.pop("plan_item_ordinal")
        return payload


def _typed_plan_item(value: object, *, ordinal: int) -> LivePlanItemV2:
    if type(value) is not dict or set(cast("dict[str, object]", value)) != _PLAN_ITEM_KEYS:
        _fail("sealed live plan item does not have its exact typed key set")
    item = cast("dict[str, object]", value)
    item_ordinal = _nonnegative(item["plan_item_ordinal"], field_name="plan_item_ordinal")
    if item_ordinal != ordinal:
        _fail("sealed live plan item ordinal is not exact and contiguous")
    routes_value = item["route_ids"]
    if type(routes_value) is not list:
        _fail("sealed live plan item route inventory must be a JSON array")
    routes = _route_ids(tuple(cast("list[object]", routes_value)))
    payload = {
        "plan_item_ordinal": item_ordinal,
        "source_sha": _git_sha(item["source_sha"], field_name="plan item source_sha"),
        "run_id": _positive(item["run_id"], field_name="plan item run_id"),
        "run_attempt": _positive(item["run_attempt"], field_name="plan item run_attempt"),
        "chain_id": _safe_id(item["chain_id"], field_name="plan item chain_id"),
        "lane_id": _safe_id(item["lane_id"], field_name="plan item lane_id"),
        "semantic_request_sha256": _sha256(
            item["semantic_request_sha256"], field_name="plan item semantic request"
        ),
        "logical_invocation_sha256": _sha256(
            item["logical_invocation_sha256"], field_name="plan item logical invocation"
        ),
        "provider_call_sha256": _sha256(
            item["provider_call_sha256"], field_name="plan item provider call"
        ),
        "scope_sha256": _sha256(item["scope_sha256"], field_name="plan item scope"),
        "safe_parameters_sha256": _sha256(
            item["safe_parameters_sha256"], field_name="plan item parameters"
        ),
        "endpoint_id": _safe_id(item["endpoint_id"], field_name="plan item endpoint_id"),
        "endpoint_contract_sha256": _sha256(
            item["endpoint_contract_sha256"], field_name="plan item endpoint contract"
        ),
        "provider_authority_sha256": _sha256(
            item["provider_authority_sha256"], field_name="plan item provider authority"
        ),
        "route_ids": routes,
    }
    digest_payload = {**payload, "route_ids": list(routes)}
    return LivePlanItemV2(
        **payload,
        plan_item_sha256=_canonical_sha256(digest_payload),
    )


def _validate_public_plan_bytes(value: object) -> tuple[bytes, tuple[LivePlanItemV2, ...]]:
    if type(value) is not bytes or not value or len(value) > MAX_LIVE_PLAN_BYTES:
        _fail("sealed live plan bytes are absent or exceed their exact bound")
    try:
        text = value.decode("utf-8", errors="strict")
        decoded = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RawLivePlanAuthorityError("sealed live plan is not strict UTF-8 JSON") from exc
    if type(decoded) is not dict or _canonical_json_bytes(decoded) != value:
        _fail("sealed live plan is not one exact canonical JSON object")
    _reject_secret_shaped_values(decoded)
    root = cast("dict[str, object]", decoded)
    if set(root) != _PLAN_ROOT_KEYS:
        _fail("sealed live plan does not have its exact typed root key set")
    if root["schema_version"] != 2 or type(root["schema_version"]) is not int:
        _fail("sealed live plan schema version must be the exact integer 2")
    if root["kind"] != LIVE_PLAN_KIND or type(root["kind"]) is not str:
        _fail("sealed live plan kind is not the exact public contract kind")
    raw_items = root["items"]
    if type(raw_items) is not list or not raw_items or len(raw_items) > _MAX_PLAN_ITEMS:
        _fail("sealed live plan item inventory is absent or over bound")
    typed_items = tuple(
        _typed_plan_item(item, ordinal=ordinal)
        for ordinal, item in enumerate(cast("list[object]", raw_items))
    )
    if len({item.plan_item_sha256 for item in typed_items}) != len(typed_items):
        _fail("sealed live plan repeats an exact plan item")
    semantic_items = tuple(
        _canonical_sha256(item.semantic_identity_payload()) for item in typed_items
    )
    if len(set(semantic_items)) != len(semantic_items):
        _fail("sealed live plan repeats one semantic provider-call member")
    return value, typed_items


def _workflow_path(value: object) -> str:
    if (
        type(value) is not str
        or len(value) > _MAX_TEXT
        or not value.startswith(".github/workflows/")
        or not value.endswith((".yml", ".yaml"))
        or ".." in value.split("/")
        or value.startswith("/")
        or _FORBIDDEN_KEY_RE.search(value) is not None
        or _FORBIDDEN_VALUE_RE.search(value) is not None
    ):
        _fail("workflow_path is not an exact repository workflow path")
    return value


def _member_path(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_TEXT
        or value.startswith(("/", "\\"))
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or _FORBIDDEN_KEY_RE.search(value) is not None
        or _FORBIDDEN_VALUE_RE.search(value) is not None
    ):
        _fail("artifact member path is not one safe relative path")
    return value


def _route_ids(value: object) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or not value
        or len(value) > _MAX_ROUTE_IDS
        or len(value) != len(set(value))
    ):
        _fail("live-plan route inventory is absent, duplicate, or over bound")
    for route_id in value:
        _safe_id(route_id, field_name="live-plan route ID")
    return cast("tuple[str, ...]", value)


def _row_utc(value: object, *, field_name: str) -> datetime:
    """Normalize an exact UTC table value without trusting its tzinfo object."""

    if type(value) is not datetime or value.fold != 0:
        _fail(f"{field_name} table value must be an exact datetime")
    try:
        offset = value.utcoffset()
    except (AttributeError, OverflowError, ValueError) as exc:
        raise RawLivePlanAuthorityError(f"{field_name} table timezone is invalid") from exc
    if offset is None or offset.total_seconds() != 0:
        _fail(f"{field_name} table value must represent UTC exactly")
    return datetime(
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
        tzinfo=UTC,
        fold=0,
    )


def _exact_row(value: object, *, expected: frozenset[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(cast("dict[object, object]", value)) != expected:
        _fail(f"{label} table row does not have its exact column set")
    if any(type(key) is not str for key in cast("dict[object, object]", value)):
        _fail(f"{label} table row contains a non-text column name")
    row = cast("dict[str, object]", value)
    if row["schema_version"] != 2 or type(row["schema_version"]) is not int:
        _fail(f"{label} table row schema version is not the exact integer 2")
    return row


def _row_string_inventory(
    row: dict[str, object],
    *,
    json_field: str,
    digest_field: str,
    count_field: str,
    label: str,
    sha_values: bool,
) -> tuple[str, ...]:
    encoded = row[json_field]
    if type(encoded) is not str or not encoded:
        _fail(f"{label} JSON is absent")
    raw = encoded.encode("utf-8", errors="strict")
    try:
        value = json.loads(encoded, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RawLivePlanAuthorityError(f"{label} JSON is invalid") from exc
    if type(value) is not list or _canonical_json_bytes(value) != raw:
        _fail(f"{label} JSON is not one exact canonical array")
    items = tuple(cast("list[object]", value))
    if any(type(item) is not str for item in items) or len(items) != len(set(items)):
        _fail(f"{label} values are invalid or duplicated")
    if sha_values:
        for item in items:
            _sha256(item, field_name=label)
    else:
        _route_ids(items)
    if (
        row[digest_field] != _sha256_bytes(raw)
        or type(row[count_field]) is not int
        or row[count_field] != len(items)
    ):
        _fail(f"{label} count or digest differs from its exact JSON")
    return cast("tuple[str, ...]", items)


@dataclass(frozen=True, slots=True)
class LivePlanGenerationReceiptV2:
    """One externally receipted immutable live-plan byte generation."""

    generation_receipt_sha256: str
    generation_id: str
    generation_kind: GenerationKind
    parent_generation_receipt_sha256: str | None
    parent_capture_root_sha256: str | None
    sealed_plan_bytes: bytes
    sealed_plan_sha256: str
    sealed_plan_length: int
    plan_item_count: int
    plan_items_sha256: str
    source_sha: str
    producing_head_sha: str
    workflow_path: str
    workflow_content_sha256: str
    run_id: int
    run_attempt: int
    chain_id: str
    producer_job_id: int
    producer_job_name_sha256: str
    runner_identity_sha256: str
    matrix_lane_id: str
    operation: str
    nonce_sha256: str
    artifact_id: int
    artifact_name: str
    artifact_digest_sha256: str
    artifact_size: int
    artifact_archive_url_sha256: str
    artifact_expires_at: datetime
    member_path: str
    member_sha256: str
    member_length: int
    collector_receipt_sha256: str
    external_receipt_sha256: str
    live_snapshot_at: datetime
    generated_at: datetime

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "raw_nba_api_live_plan_generation_receipt_v2"

    def __post_init__(self) -> None:
        _sha256(self.generation_receipt_sha256, field_name="generation receipt")
        _safe_id(self.generation_id, field_name="generation_id")
        if type(self.generation_kind) is not str or self.generation_kind not in _GENERATION_KINDS:
            _fail("live-plan generation kind is unsupported")
        if self.parent_generation_receipt_sha256 is not None:
            _sha256(
                self.parent_generation_receipt_sha256,
                field_name="parent generation receipt",
            )
        if self.parent_capture_root_sha256 is not None:
            _sha256(self.parent_capture_root_sha256, field_name="parent capture root")
        if self.generation_kind == "full_root":
            if (
                self.parent_generation_receipt_sha256 is not None
                or self.parent_capture_root_sha256 is not None
            ):
                _fail("full-root plan generation cannot claim a parent")
        elif self.generation_kind == "successor_wave_0":
            if (
                self.parent_generation_receipt_sha256 is not None
                or self.parent_capture_root_sha256 is None
            ):
                _fail("successor wave-0 requires only its committed parent capture root")
        elif (
            self.parent_generation_receipt_sha256 is None or self.parent_capture_root_sha256 is None
        ):
            _fail("derived live-plan generation lacks its exact parent authorities")

        plan_bytes, plan_items = _validate_public_plan_bytes(self.sealed_plan_bytes)
        _sha256(self.sealed_plan_sha256, field_name="sealed plan")
        _sha256(self.plan_items_sha256, field_name="sealed plan item inventory")
        _positive(self.plan_item_count, field_name="sealed plan item count")
        if (
            type(self.sealed_plan_length) is not int
            or self.sealed_plan_length != len(plan_bytes)
            or self.sealed_plan_sha256 != _sha256_bytes(plan_bytes)
            or self.plan_item_count != len(plan_items)
            or self.plan_items_sha256
            != _canonical_sha256([item.plan_item_sha256 for item in plan_items])
        ):
            _fail("sealed plan bytes or item inventory differ from their exact authority")
        _git_sha(self.source_sha, field_name="semantic source")
        _git_sha(self.producing_head_sha, field_name="producing head")
        _workflow_path(self.workflow_path)
        for field_name in (
            "workflow_content_sha256",
            "producer_job_name_sha256",
            "runner_identity_sha256",
            "nonce_sha256",
            "artifact_digest_sha256",
            "artifact_archive_url_sha256",
            "member_sha256",
            "collector_receipt_sha256",
            "external_receipt_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        for field_name in ("run_id", "run_attempt", "producer_job_id", "artifact_id"):
            _positive(getattr(self, field_name), field_name=field_name)
        _safe_id(self.chain_id, field_name="chain_id")
        _safe_id(self.matrix_lane_id, field_name="matrix_lane_id")
        _safe_id(self.operation, field_name="operation")
        if (
            type(self.artifact_name) is not str
            or _SAFE_ARTIFACT_RE.fullmatch(self.artifact_name) is None
            or _FORBIDDEN_KEY_RE.search(self.artifact_name) is not None
            or _FORBIDDEN_VALUE_RE.search(self.artifact_name) is not None
        ):
            _fail("artifact_name is not exact safe artifact identity text")
        _positive(self.artifact_size, field_name="artifact_size")
        _member_path(self.member_path)
        _positive(self.member_length, field_name="member_length")
        if (
            self.member_sha256 != self.sealed_plan_sha256
            or self.member_length != self.sealed_plan_length
            or self.artifact_size < self.member_length
        ):
            _fail("artifact member does not equal the exact sealed live plan")
        expires_at = _utc(self.artifact_expires_at, field_name="artifact_expires_at")
        snapshot_at = _utc(self.live_snapshot_at, field_name="live_snapshot_at")
        generated_at = _utc(self.generated_at, field_name="generated_at")
        if expires_at <= generated_at:
            _fail("live-plan artifact is already expired at generation time")
        if snapshot_at > generated_at:
            _fail("live snapshot cutoff cannot be after its plan generation time")
        if self.generation_receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("generation receipt digest differs from its exact public projection")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "generation_id": self.generation_id,
            "generation_kind": self.generation_kind,
            "parent_generation_receipt_sha256": self.parent_generation_receipt_sha256,
            "parent_capture_root_sha256": self.parent_capture_root_sha256,
            "sealed_plan_json": self.sealed_plan_bytes.decode("utf-8"),
            "sealed_plan_sha256": self.sealed_plan_sha256,
            "sealed_plan_length": self.sealed_plan_length,
            "plan_item_count": self.plan_item_count,
            "plan_items_sha256": self.plan_items_sha256,
            "source_sha": self.source_sha,
            "producing_head_sha": self.producing_head_sha,
            "workflow_path": self.workflow_path,
            "workflow_content_sha256": self.workflow_content_sha256,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "producer_job_id": self.producer_job_id,
            "producer_job_name_sha256": self.producer_job_name_sha256,
            "runner_identity_sha256": self.runner_identity_sha256,
            "matrix_lane_id": self.matrix_lane_id,
            "operation": self.operation,
            "nonce_sha256": self.nonce_sha256,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "artifact_digest_sha256": self.artifact_digest_sha256,
            "artifact_size": self.artifact_size,
            "artifact_archive_url_sha256": self.artifact_archive_url_sha256,
            "artifact_expires_at": self.artifact_expires_at.isoformat().replace("+00:00", "Z"),
            "member_path": self.member_path,
            "member_sha256": self.member_sha256,
            "member_length": self.member_length,
            "collector_receipt_sha256": self.collector_receipt_sha256,
            "external_receipt_sha256": self.external_receipt_sha256,
            "live_snapshot_at": self.live_snapshot_at.isoformat().replace("+00:00", "Z"),
            "generated_at": self.generated_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def build(
        cls,
        *,
        generation_id: str,
        generation_kind: GenerationKind,
        parent_generation_receipt_sha256: str | None,
        parent_capture_root_sha256: str | None,
        sealed_plan_bytes: bytes,
        source_sha: str,
        producing_head_sha: str,
        workflow_path: str,
        workflow_content_sha256: str,
        run_id: int,
        run_attempt: int,
        chain_id: str,
        producer_job_id: int,
        producer_job_name_sha256: str,
        runner_identity_sha256: str,
        matrix_lane_id: str,
        operation: str,
        nonce_sha256: str,
        artifact_id: int,
        artifact_name: str,
        artifact_digest_sha256: str,
        artifact_size: int,
        artifact_archive_url_sha256: str,
        artifact_expires_at: datetime,
        member_path: str,
        member_sha256: str,
        member_length: int,
        collector_receipt_sha256: str,
        external_receipt_sha256: str,
        live_snapshot_at: datetime,
        generated_at: datetime,
    ) -> Self:
        plan_bytes, plan_items = _validate_public_plan_bytes(sealed_plan_bytes)
        sealed_plan_sha256 = _sha256_bytes(plan_bytes)
        sealed_plan_length = len(plan_bytes)
        plan_items_sha256 = _canonical_sha256([item.plan_item_sha256 for item in plan_items])
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "generation_id": generation_id,
            "generation_kind": generation_kind,
            "parent_generation_receipt_sha256": parent_generation_receipt_sha256,
            "parent_capture_root_sha256": parent_capture_root_sha256,
            "sealed_plan_json": plan_bytes.decode("utf-8"),
            "sealed_plan_sha256": sealed_plan_sha256,
            "sealed_plan_length": sealed_plan_length,
            "plan_item_count": len(plan_items),
            "plan_items_sha256": plan_items_sha256,
            "source_sha": source_sha,
            "producing_head_sha": producing_head_sha,
            "workflow_path": workflow_path,
            "workflow_content_sha256": workflow_content_sha256,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "chain_id": chain_id,
            "producer_job_id": producer_job_id,
            "producer_job_name_sha256": producer_job_name_sha256,
            "runner_identity_sha256": runner_identity_sha256,
            "matrix_lane_id": matrix_lane_id,
            "operation": operation,
            "nonce_sha256": nonce_sha256,
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "artifact_digest_sha256": artifact_digest_sha256,
            "artifact_size": artifact_size,
            "artifact_archive_url_sha256": artifact_archive_url_sha256,
            "artifact_expires_at": _utc(
                artifact_expires_at,
                field_name="artifact_expires_at",
            )
            .isoformat()
            .replace("+00:00", "Z"),
            "member_path": member_path,
            "member_sha256": member_sha256,
            "member_length": member_length,
            "collector_receipt_sha256": collector_receipt_sha256,
            "external_receipt_sha256": external_receipt_sha256,
            "live_snapshot_at": _utc(live_snapshot_at, field_name="live_snapshot_at")
            .isoformat()
            .replace("+00:00", "Z"),
            "generated_at": _utc(generated_at, field_name="generated_at")
            .isoformat()
            .replace("+00:00", "Z"),
        }
        return cls(
            generation_receipt_sha256=_canonical_sha256(payload),
            generation_id=generation_id,
            generation_kind=generation_kind,
            parent_generation_receipt_sha256=parent_generation_receipt_sha256,
            parent_capture_root_sha256=parent_capture_root_sha256,
            sealed_plan_bytes=plan_bytes,
            sealed_plan_sha256=sealed_plan_sha256,
            sealed_plan_length=sealed_plan_length,
            plan_item_count=len(plan_items),
            plan_items_sha256=plan_items_sha256,
            source_sha=source_sha,
            producing_head_sha=producing_head_sha,
            workflow_path=workflow_path,
            workflow_content_sha256=workflow_content_sha256,
            run_id=run_id,
            run_attempt=run_attempt,
            chain_id=chain_id,
            producer_job_id=producer_job_id,
            producer_job_name_sha256=producer_job_name_sha256,
            runner_identity_sha256=runner_identity_sha256,
            matrix_lane_id=matrix_lane_id,
            operation=operation,
            nonce_sha256=nonce_sha256,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            artifact_digest_sha256=artifact_digest_sha256,
            artifact_size=artifact_size,
            artifact_archive_url_sha256=artifact_archive_url_sha256,
            artifact_expires_at=artifact_expires_at,
            member_path=member_path,
            member_sha256=member_sha256,
            member_length=member_length,
            collector_receipt_sha256=collector_receipt_sha256,
            external_receipt_sha256=external_receipt_sha256,
            live_snapshot_at=live_snapshot_at,
            generated_at=generated_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "generation_receipt_sha256": self.generation_receipt_sha256,
        }

    def to_row(self) -> dict[str, object]:
        """Project the exact ordered public-table row for this generation."""

        return {
            "schema_version": self.schema_version,
            "generation_receipt_sha256": self.generation_receipt_sha256,
            "generation_id": self.generation_id,
            "generation_kind": self.generation_kind,
            "parent_generation_receipt_sha256": self.parent_generation_receipt_sha256,
            "parent_capture_root_sha256": self.parent_capture_root_sha256,
            "sealed_plan_bytes": self.sealed_plan_bytes,
            "sealed_plan_sha256": self.sealed_plan_sha256,
            "sealed_plan_length": self.sealed_plan_length,
            "plan_item_count": self.plan_item_count,
            "plan_items_sha256": self.plan_items_sha256,
            "source_sha": self.source_sha,
            "producing_head_sha": self.producing_head_sha,
            "workflow_path": self.workflow_path,
            "workflow_content_sha256": self.workflow_content_sha256,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "producer_job_id": self.producer_job_id,
            "producer_job_name_sha256": self.producer_job_name_sha256,
            "runner_identity_sha256": self.runner_identity_sha256,
            "matrix_lane_id": self.matrix_lane_id,
            "operation": self.operation,
            "nonce_sha256": self.nonce_sha256,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "artifact_digest_sha256": self.artifact_digest_sha256,
            "artifact_size": self.artifact_size,
            "artifact_archive_url_sha256": self.artifact_archive_url_sha256,
            "artifact_expires_at": self.artifact_expires_at,
            "member_path": self.member_path,
            "member_sha256": self.member_sha256,
            "member_length": self.member_length,
            "collector_receipt_sha256": self.collector_receipt_sha256,
            "external_receipt_sha256": self.external_receipt_sha256,
            "live_snapshot_at": self.live_snapshot_at,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        """Reconstruct and semantically validate one persisted generation row."""

        field_names = frozenset(field.name for field in fields(cls))
        row = _exact_row(
            value,
            expected=field_names | {"schema_version"},
            label="live-plan generation",
        )
        kwargs = {field_name: row[field_name] for field_name in field_names}
        for field_name in ("artifact_expires_at", "live_snapshot_at", "generated_at"):
            kwargs[field_name] = _row_utc(row[field_name], field_name=field_name)
        try:
            return cast("Self", _strict_generation(cls(**kwargs)))  # ty: ignore[invalid-argument-type]
        except (TypeError, ValueError) as exc:
            raise RawLivePlanAuthorityError(
                "live-plan generation table row failed semantic reconstruction"
            ) from exc


@dataclass(frozen=True, slots=True)
class LivePlanCallAdmissionV2:
    """Externally verified pre-call membership in one sealed plan generation."""

    admission_receipt_sha256: str
    plan_generation_receipt_sha256: str
    plan_item_ordinal: int
    plan_item_sha256: str
    observation_sha256: str
    semantic_request_sha256: str
    logical_invocation_sha256: str
    provider_call_sha256: str
    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    scope_sha256: str
    safe_parameters_sha256: str
    endpoint_id: str
    endpoint_contract_sha256: str
    provider_authority_sha256: str
    route_ids: tuple[str, ...]
    live_snapshot_at: datetime
    issued_at: datetime
    authorized_at: datetime
    expires_at: datetime
    authorization_collector_receipt_sha256: str
    authorization_receipt_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "raw_nba_api_live_plan_call_admission_v2"

    def __post_init__(self) -> None:
        for field_name in (
            "admission_receipt_sha256",
            "plan_generation_receipt_sha256",
            "plan_item_sha256",
            "observation_sha256",
            "semantic_request_sha256",
            "logical_invocation_sha256",
            "provider_call_sha256",
            "scope_sha256",
            "safe_parameters_sha256",
            "endpoint_contract_sha256",
            "provider_authority_sha256",
            "authorization_collector_receipt_sha256",
            "authorization_receipt_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        _nonnegative(self.plan_item_ordinal, field_name="plan_item_ordinal")
        _git_sha(self.source_sha, field_name="source_sha")
        _positive(self.run_id, field_name="run_id")
        _positive(self.run_attempt, field_name="run_attempt")
        _safe_id(self.chain_id, field_name="chain_id")
        _safe_id(self.lane_id, field_name="lane_id")
        _safe_id(self.endpoint_id, field_name="endpoint_id")
        _route_ids(self.route_ids)
        snapshot_at = _utc(self.live_snapshot_at, field_name="live_snapshot_at")
        issued_at = _utc(self.issued_at, field_name="issued_at")
        authorized_at = _utc(self.authorized_at, field_name="authorized_at")
        expires_at = _utc(self.expires_at, field_name="expires_at")
        if not snapshot_at <= issued_at <= authorized_at < expires_at:
            _fail("live-plan call admission time order is invalid")
        if self.admission_receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("live-plan call-admission digest differs from its exact projection")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "plan_generation_receipt_sha256": self.plan_generation_receipt_sha256,
            "plan_item_ordinal": self.plan_item_ordinal,
            "plan_item_sha256": self.plan_item_sha256,
            "observation_sha256": self.observation_sha256,
            "semantic_request_sha256": self.semantic_request_sha256,
            "logical_invocation_sha256": self.logical_invocation_sha256,
            "provider_call_sha256": self.provider_call_sha256,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "scope_sha256": self.scope_sha256,
            "safe_parameters_sha256": self.safe_parameters_sha256,
            "endpoint_id": self.endpoint_id,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "route_ids": list(self.route_ids),
            "live_snapshot_at": self.live_snapshot_at.isoformat().replace("+00:00", "Z"),
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "authorized_at": self.authorized_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "authorization_collector_receipt_sha256": (self.authorization_collector_receipt_sha256),
            "authorization_receipt_sha256": self.authorization_receipt_sha256,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        """Reconstruct one authenticated admission from its persisted row."""

        dataclass_names = frozenset(field.name for field in fields(cls))
        stored_names = (dataclass_names - {"route_ids"}) | {
            "schema_version",
            "route_ids_json",
            "route_ids_sha256",
            "route_count",
        }
        row = _exact_row(value, expected=stored_names, label="live-plan call admission")
        route_ids = _row_string_inventory(
            row,
            json_field="route_ids_json",
            digest_field="route_ids_sha256",
            count_field="route_count",
            label="live-plan call-admission routes",
            sha_values=False,
        )
        kwargs = {
            field_name: row[field_name]
            for field_name in dataclass_names
            if field_name != "route_ids"
        }
        kwargs["route_ids"] = route_ids
        for field_name in ("live_snapshot_at", "issued_at", "authorized_at", "expires_at"):
            kwargs[field_name] = _row_utc(row[field_name], field_name=field_name)
        try:
            return cast("Self", _strict_admission(cls(**kwargs)))  # ty: ignore[invalid-argument-type]
        except (TypeError, ValueError) as exc:
            raise RawLivePlanAuthorityError(
                "live-plan call-admission row failed semantic reconstruction"
            ) from exc

    @classmethod
    def build(
        cls,
        *,
        generation: LivePlanGenerationReceiptV2,
        attempt: RequestAttemptIdentityV2,
        plan_item_ordinal: int,
        issued_at: datetime,
        authorized_at: datetime,
        expires_at: datetime,
        authorization_collector_receipt_sha256: str,
        authorization_receipt_sha256: str,
    ) -> Self:
        exact_generation = _strict_generation(generation)
        exact_attempt = _strict_attempt(attempt)
        _nonnegative(plan_item_ordinal, field_name="plan_item_ordinal")
        _collector = _sha256(
            authorization_collector_receipt_sha256,
            field_name="authorization collector receipt",
        )
        _authorization = _sha256(
            authorization_receipt_sha256,
            field_name="external authorization receipt",
        )
        issued = _utc(issued_at, field_name="issued_at")
        authorized = _utc(authorized_at, field_name="authorized_at")
        expires = _utc(expires_at, field_name="expires_at")
        if exact_attempt.source_family != "live":
            _fail("live-plan call admission requires one live request attempt")
        if (
            exact_generation.source_sha != exact_attempt.source_sha
            or exact_generation.run_id != exact_attempt.run_id
            or exact_generation.run_attempt != exact_attempt.run_attempt
            or exact_generation.chain_id != exact_attempt.chain_id
            or exact_generation.matrix_lane_id != exact_attempt.lane_id
        ):
            _fail("live-plan call admission crosses its generation execution identity")
        _plan_bytes, plan_items = _validate_public_plan_bytes(exact_generation.sealed_plan_bytes)
        if plan_item_ordinal >= len(plan_items):
            _fail("live-plan call admission references a missing plan item")
        plan_item = plan_items[plan_item_ordinal]
        expected_item_identity = (
            exact_attempt.source_sha,
            exact_attempt.run_id,
            exact_attempt.run_attempt,
            exact_attempt.chain_id,
            exact_attempt.lane_id,
            exact_attempt.semantic_request_sha256,
            exact_attempt.logical_invocation_sha256,
            exact_attempt.provider_call_sha256,
            exact_attempt.scope_sha256,
            exact_attempt.safe_parameters_sha256,
            exact_attempt.endpoint_id,
            exact_attempt.endpoint_contract_sha256,
            exact_attempt.provider_authority_sha256,
        )
        actual_item_identity = (
            plan_item.source_sha,
            plan_item.run_id,
            plan_item.run_attempt,
            plan_item.chain_id,
            plan_item.lane_id,
            plan_item.semantic_request_sha256,
            plan_item.logical_invocation_sha256,
            plan_item.provider_call_sha256,
            plan_item.scope_sha256,
            plan_item.safe_parameters_sha256,
            plan_item.endpoint_id,
            plan_item.endpoint_contract_sha256,
            plan_item.provider_authority_sha256,
        )
        if actual_item_identity != expected_item_identity:
            _fail("live-plan call admission differs from its typed plan item")
        if not (
            exact_generation.generated_at <= issued <= authorized < expires
            and expires <= exact_generation.artifact_expires_at
        ):
            _fail("live-plan call admission is outside its generation validity window")
        exact_routes = plan_item.route_ids
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "plan_generation_receipt_sha256": exact_generation.generation_receipt_sha256,
            "plan_item_ordinal": plan_item_ordinal,
            "plan_item_sha256": plan_item.plan_item_sha256,
            "observation_sha256": exact_attempt.observation_sha256,
            "semantic_request_sha256": exact_attempt.semantic_request_sha256,
            "logical_invocation_sha256": exact_attempt.logical_invocation_sha256,
            "provider_call_sha256": exact_attempt.provider_call_sha256,
            "source_sha": exact_attempt.source_sha,
            "run_id": exact_attempt.run_id,
            "run_attempt": exact_attempt.run_attempt,
            "chain_id": exact_attempt.chain_id,
            "lane_id": exact_attempt.lane_id,
            "scope_sha256": exact_attempt.scope_sha256,
            "safe_parameters_sha256": exact_attempt.safe_parameters_sha256,
            "endpoint_id": exact_attempt.endpoint_id,
            "endpoint_contract_sha256": exact_attempt.endpoint_contract_sha256,
            "provider_authority_sha256": exact_attempt.provider_authority_sha256,
            "route_ids": list(exact_routes),
            "live_snapshot_at": exact_generation.live_snapshot_at.isoformat().replace(
                "+00:00", "Z"
            ),
            "issued_at": issued.isoformat().replace("+00:00", "Z"),
            "authorized_at": authorized.isoformat().replace("+00:00", "Z"),
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
            "authorization_collector_receipt_sha256": _collector,
            "authorization_receipt_sha256": _authorization,
        }
        return cls(
            admission_receipt_sha256=_canonical_sha256(payload),
            plan_generation_receipt_sha256=exact_generation.generation_receipt_sha256,
            plan_item_ordinal=plan_item_ordinal,
            plan_item_sha256=plan_item.plan_item_sha256,
            observation_sha256=exact_attempt.observation_sha256,
            semantic_request_sha256=exact_attempt.semantic_request_sha256,
            logical_invocation_sha256=exact_attempt.logical_invocation_sha256,
            provider_call_sha256=exact_attempt.provider_call_sha256,
            source_sha=exact_attempt.source_sha,
            run_id=exact_attempt.run_id,
            run_attempt=exact_attempt.run_attempt,
            chain_id=exact_attempt.chain_id,
            lane_id=exact_attempt.lane_id,
            scope_sha256=exact_attempt.scope_sha256,
            safe_parameters_sha256=exact_attempt.safe_parameters_sha256,
            endpoint_id=exact_attempt.endpoint_id,
            endpoint_contract_sha256=exact_attempt.endpoint_contract_sha256,
            provider_authority_sha256=exact_attempt.provider_authority_sha256,
            route_ids=exact_routes,
            live_snapshot_at=exact_generation.live_snapshot_at,
            issued_at=issued,
            authorized_at=authorized,
            expires_at=expires,
            authorization_collector_receipt_sha256=_collector,
            authorization_receipt_sha256=_authorization,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "admission_receipt_sha256": self.admission_receipt_sha256,
        }

    def to_row(self) -> dict[str, object]:
        route_ids_json = _canonical_json_bytes(list(self.route_ids)).decode("utf-8")
        return {
            "schema_version": self.schema_version,
            "admission_receipt_sha256": self.admission_receipt_sha256,
            "plan_generation_receipt_sha256": self.plan_generation_receipt_sha256,
            "plan_item_ordinal": self.plan_item_ordinal,
            "plan_item_sha256": self.plan_item_sha256,
            "observation_sha256": self.observation_sha256,
            "semantic_request_sha256": self.semantic_request_sha256,
            "logical_invocation_sha256": self.logical_invocation_sha256,
            "provider_call_sha256": self.provider_call_sha256,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "scope_sha256": self.scope_sha256,
            "safe_parameters_sha256": self.safe_parameters_sha256,
            "endpoint_id": self.endpoint_id,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "route_ids_json": route_ids_json,
            "route_ids_sha256": _sha256_bytes(route_ids_json.encode("utf-8")),
            "route_count": len(self.route_ids),
            "live_snapshot_at": self.live_snapshot_at,
            "issued_at": self.issued_at,
            "authorized_at": self.authorized_at,
            "expires_at": self.expires_at,
            "authorization_collector_receipt_sha256": (self.authorization_collector_receipt_sha256),
            "authorization_receipt_sha256": self.authorization_receipt_sha256,
        }


def _landing_authority_projection(
    landings: tuple[ObservationRouteLandingV2, ...],
) -> list[dict[str, object]]:
    return [
        {
            "landing_sha256": item.landing_sha256,
            "route_id": item.route_id,
            "staging_key": item.staging_key,
            "route_authority_sha256": item.route_authority_sha256,
            "source_occurrences_sha256": item.source_occurrences_sha256,
            "logical_receipt_sha256": item.logical_receipt_sha256,
            "provider_authority_sha256": item.provider_authority_sha256,
            "logical_parameters_sha256": item.logical_parameters_sha256,
            "content_hash": item.content_hash,
            "persisted_content_sha256": item.persisted_content_sha256,
            "persisted_schema_sha256": item.persisted_schema_sha256,
            "receipt_root_sha256": item.receipt_root_sha256,
        }
        for item in landings
    ]


def _live_observation_from_bundle(
    bundle: object,
    *,
    observation_sha256: str,
) -> tuple[
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    tuple[ObservationRouteLandingV2, ...],
]:
    try:
        exact_bundle = validate_raw_request_authority_bundle(bundle)
    except (TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError(
            "live plan received an invalid raw authority bundle"
        ) from exc
    observations = tuple(
        item
        for item in exact_bundle.observations
        if item.attempt.observation_sha256 == observation_sha256
    )
    if len(observations) != 1:
        _fail("live plan observation is absent or duplicated in its raw authority bundle")
    observation = observations[0]
    landings = tuple(
        item for item in exact_bundle.landings if item.observation_sha256 == observation_sha256
    )
    if not landings:
        _fail("live observation lacks its complete raw authority landing inventory")
    return exact_bundle, observation, landings


@dataclass(frozen=True, slots=True)
class LiveObservationPlanBindingV2:
    """Exact observation-to-plan projection for one selected live call."""

    binding_receipt_sha256: str
    observation_sha256: str
    observation_record_sha256: str
    plan_generation_receipt_sha256: str
    plan_admission_receipt_sha256: str
    live_plan_authority_sha256: str
    plan_item_ordinal: int
    plan_item_sha256: str
    semantic_request_sha256: str
    logical_invocation_sha256: str
    provider_call_sha256: str
    logical_receipt_sha256: str
    capture_response_receipt_sha256: str
    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    scope_sha256: str
    safe_parameters_sha256: str
    endpoint_id: str
    endpoint_contract_sha256: str
    provider_authority_sha256: str
    route_ids: tuple[str, ...]
    landing_sha256s: tuple[str, ...]
    landing_receipt_roots: tuple[str, ...]
    landing_authority_sha256: str
    live_snapshot_at: datetime

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "raw_nba_api_observation_live_plan_v2"

    def __post_init__(self) -> None:
        for field_name in (
            "binding_receipt_sha256",
            "observation_sha256",
            "observation_record_sha256",
            "plan_generation_receipt_sha256",
            "plan_admission_receipt_sha256",
            "live_plan_authority_sha256",
            "plan_item_sha256",
            "semantic_request_sha256",
            "logical_invocation_sha256",
            "provider_call_sha256",
            "logical_receipt_sha256",
            "capture_response_receipt_sha256",
            "scope_sha256",
            "safe_parameters_sha256",
            "endpoint_contract_sha256",
            "provider_authority_sha256",
            "landing_authority_sha256",
        ):
            _sha256(getattr(self, field_name), field_name=field_name)
        _nonnegative(self.plan_item_ordinal, field_name="plan_item_ordinal")
        _git_sha(self.source_sha, field_name="source_sha")
        _positive(self.run_id, field_name="run_id")
        _positive(self.run_attempt, field_name="run_attempt")
        _safe_id(self.chain_id, field_name="chain_id")
        _safe_id(self.lane_id, field_name="lane_id")
        _safe_id(self.endpoint_id, field_name="endpoint_id")
        _route_ids(self.route_ids)
        if (
            type(self.landing_sha256s) is not tuple
            or type(self.landing_receipt_roots) is not tuple
            or len(self.landing_sha256s) != len(self.route_ids)
            or len(self.landing_receipt_roots) != len(self.route_ids)
            or len(set(self.landing_sha256s)) != len(self.landing_sha256s)
        ):
            _fail("observation-plan landing authority inventory is invalid")
        for digest in (*self.landing_sha256s, *self.landing_receipt_roots):
            _sha256(digest, field_name="observation-plan landing authority")
        _utc(self.live_snapshot_at, field_name="live_snapshot_at")
        if self.binding_receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("observation-plan binding digest differs from its exact projection")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "observation_sha256": self.observation_sha256,
            "observation_record_sha256": self.observation_record_sha256,
            "plan_generation_receipt_sha256": self.plan_generation_receipt_sha256,
            "plan_admission_receipt_sha256": self.plan_admission_receipt_sha256,
            "live_plan_authority_sha256": self.live_plan_authority_sha256,
            "plan_item_ordinal": self.plan_item_ordinal,
            "plan_item_sha256": self.plan_item_sha256,
            "semantic_request_sha256": self.semantic_request_sha256,
            "logical_invocation_sha256": self.logical_invocation_sha256,
            "provider_call_sha256": self.provider_call_sha256,
            "logical_receipt_sha256": self.logical_receipt_sha256,
            "capture_response_receipt_sha256": self.capture_response_receipt_sha256,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "scope_sha256": self.scope_sha256,
            "safe_parameters_sha256": self.safe_parameters_sha256,
            "endpoint_id": self.endpoint_id,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "route_ids": list(self.route_ids),
            "landing_sha256s": list(self.landing_sha256s),
            "landing_receipt_roots": list(self.landing_receipt_roots),
            "landing_authority_sha256": self.landing_authority_sha256,
            "live_snapshot_at": self.live_snapshot_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def build(
        cls,
        *,
        generation: LivePlanGenerationReceiptV2,
        admission: LivePlanCallAdmissionV2,
        authority_bundle: RawRequestAuthorityBundleV2,
        observation_sha256: str,
    ) -> Self:
        exact_generation = _strict_generation(generation)
        exact_admission = _strict_admission(admission)
        _sha256(observation_sha256, field_name="live observation")
        _exact_bundle, exact_observation, exact_landings = _live_observation_from_bundle(
            authority_bundle,
            observation_sha256=observation_sha256,
        )
        attempt = exact_observation.attempt
        if (
            attempt.source_family != "live"
            or exact_observation.lifecycle != "selected_terminal"
            or exact_observation.capture_response_receipt_sha256 is None
            or exact_observation.logical_receipt_sha256 is None
        ):
            _fail("observation-plan binding requires one selected live observation")
        snapshot_values = {item.live_snapshot_at for item in exact_landings}
        if snapshot_values != {exact_generation.live_snapshot_at}:
            _fail("live landings differ from their plan-generation snapshot cutoff")
        if (
            exact_generation.source_sha != attempt.source_sha
            or exact_generation.run_id != attempt.run_id
            or exact_generation.run_attempt != attempt.run_attempt
            or exact_generation.chain_id != attempt.chain_id
            or exact_generation.matrix_lane_id != attempt.lane_id
        ):
            _fail("live observation crosses its plan-generation execution identity")
        if not (
            exact_generation.generated_at
            <= exact_admission.authorized_at
            <= exact_observation.started_at
            < exact_admission.expires_at
        ):
            _fail("live observation started outside its authenticated pre-call admission")
        route_ids = tuple(item.route_id for item in exact_landings)
        rebuilt_admission = LivePlanCallAdmissionV2.build(
            generation=exact_generation,
            attempt=attempt,
            plan_item_ordinal=exact_admission.plan_item_ordinal,
            issued_at=exact_admission.issued_at,
            authorized_at=exact_admission.authorized_at,
            expires_at=exact_admission.expires_at,
            authorization_collector_receipt_sha256=(
                exact_admission.authorization_collector_receipt_sha256
            ),
            authorization_receipt_sha256=exact_admission.authorization_receipt_sha256,
        )
        if rebuilt_admission != exact_admission:
            _fail("live observation differs from its exact call admission")
        if rebuilt_admission.route_ids != route_ids:
            _fail("live observation landing denominator differs from its typed plan item")
        try:
            authority = LiveSnapshotPlanAuthorityV2.build(
                sealed_plan_bytes=exact_generation.sealed_plan_bytes,
                attempt=attempt,
                route_ids=route_ids,
                live_snapshot_at=exact_generation.live_snapshot_at,
            )
        except (RawRequestReconstructionError, TypeError, ValueError) as exc:
            raise RawLivePlanAuthorityError(
                "live observation cannot project its exact sealed-plan authority"
            ) from exc
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "observation_sha256": attempt.observation_sha256,
            "observation_record_sha256": exact_observation.observation_record_sha256,
            "plan_generation_receipt_sha256": exact_generation.generation_receipt_sha256,
            "plan_admission_receipt_sha256": exact_admission.admission_receipt_sha256,
            "live_plan_authority_sha256": authority.authority_sha256,
            "plan_item_ordinal": exact_admission.plan_item_ordinal,
            "plan_item_sha256": exact_admission.plan_item_sha256,
            "semantic_request_sha256": attempt.semantic_request_sha256,
            "logical_invocation_sha256": attempt.logical_invocation_sha256,
            "provider_call_sha256": attempt.provider_call_sha256,
            "logical_receipt_sha256": exact_observation.logical_receipt_sha256,
            "capture_response_receipt_sha256": (exact_observation.capture_response_receipt_sha256),
            "source_sha": attempt.source_sha,
            "run_id": attempt.run_id,
            "run_attempt": attempt.run_attempt,
            "chain_id": attempt.chain_id,
            "lane_id": attempt.lane_id,
            "scope_sha256": attempt.scope_sha256,
            "safe_parameters_sha256": attempt.safe_parameters_sha256,
            "endpoint_id": attempt.endpoint_id,
            "endpoint_contract_sha256": attempt.endpoint_contract_sha256,
            "provider_authority_sha256": attempt.provider_authority_sha256,
            "route_ids": list(route_ids),
            "landing_sha256s": [item.landing_sha256 for item in exact_landings],
            "landing_receipt_roots": [item.receipt_root_sha256 for item in exact_landings],
            "landing_authority_sha256": _canonical_sha256(
                _landing_authority_projection(exact_landings)
            ),
            "live_snapshot_at": exact_generation.live_snapshot_at.isoformat().replace(
                "+00:00", "Z"
            ),
        }
        return cls(
            binding_receipt_sha256=_canonical_sha256(payload),
            observation_sha256=attempt.observation_sha256,
            observation_record_sha256=exact_observation.observation_record_sha256,
            plan_generation_receipt_sha256=exact_generation.generation_receipt_sha256,
            plan_admission_receipt_sha256=exact_admission.admission_receipt_sha256,
            live_plan_authority_sha256=authority.authority_sha256,
            plan_item_ordinal=exact_admission.plan_item_ordinal,
            plan_item_sha256=exact_admission.plan_item_sha256,
            semantic_request_sha256=attempt.semantic_request_sha256,
            logical_invocation_sha256=attempt.logical_invocation_sha256,
            provider_call_sha256=attempt.provider_call_sha256,
            logical_receipt_sha256=exact_observation.logical_receipt_sha256,
            capture_response_receipt_sha256=(exact_observation.capture_response_receipt_sha256),
            source_sha=attempt.source_sha,
            run_id=attempt.run_id,
            run_attempt=attempt.run_attempt,
            chain_id=attempt.chain_id,
            lane_id=attempt.lane_id,
            scope_sha256=attempt.scope_sha256,
            safe_parameters_sha256=attempt.safe_parameters_sha256,
            endpoint_id=attempt.endpoint_id,
            endpoint_contract_sha256=attempt.endpoint_contract_sha256,
            provider_authority_sha256=attempt.provider_authority_sha256,
            route_ids=route_ids,
            landing_sha256s=tuple(item.landing_sha256 for item in exact_landings),
            landing_receipt_roots=tuple(item.receipt_root_sha256 for item in exact_landings),
            landing_authority_sha256=_canonical_sha256(
                _landing_authority_projection(exact_landings)
            ),
            live_snapshot_at=exact_generation.live_snapshot_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "binding_receipt_sha256": self.binding_receipt_sha256,
        }

    def to_row(self) -> dict[str, object]:
        """Project the exact ordered public-table row for this observation."""

        route_ids_json = _canonical_json_bytes(list(self.route_ids)).decode("utf-8")
        landing_sha256s_json = _canonical_json_bytes(list(self.landing_sha256s)).decode("utf-8")
        landing_receipt_roots_json = _canonical_json_bytes(list(self.landing_receipt_roots)).decode(
            "utf-8"
        )
        return {
            "schema_version": self.schema_version,
            "binding_receipt_sha256": self.binding_receipt_sha256,
            "observation_sha256": self.observation_sha256,
            "observation_record_sha256": self.observation_record_sha256,
            "plan_generation_receipt_sha256": self.plan_generation_receipt_sha256,
            "plan_admission_receipt_sha256": self.plan_admission_receipt_sha256,
            "live_plan_authority_sha256": self.live_plan_authority_sha256,
            "plan_item_ordinal": self.plan_item_ordinal,
            "plan_item_sha256": self.plan_item_sha256,
            "semantic_request_sha256": self.semantic_request_sha256,
            "logical_invocation_sha256": self.logical_invocation_sha256,
            "provider_call_sha256": self.provider_call_sha256,
            "logical_receipt_sha256": self.logical_receipt_sha256,
            "capture_response_receipt_sha256": self.capture_response_receipt_sha256,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "scope_sha256": self.scope_sha256,
            "safe_parameters_sha256": self.safe_parameters_sha256,
            "endpoint_id": self.endpoint_id,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "route_ids_json": route_ids_json,
            "route_ids_sha256": _sha256_bytes(route_ids_json.encode("utf-8")),
            "route_count": len(self.route_ids),
            "landing_sha256s_json": landing_sha256s_json,
            "landing_sha256s_sha256": _sha256_bytes(landing_sha256s_json.encode("utf-8")),
            "landing_receipt_roots_json": landing_receipt_roots_json,
            "landing_receipt_roots_sha256": _sha256_bytes(
                landing_receipt_roots_json.encode("utf-8")
            ),
            "landing_count": len(self.landing_sha256s),
            "landing_authority_sha256": self.landing_authority_sha256,
            "live_snapshot_at": self.live_snapshot_at,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        """Reconstruct one observation binding from its normalized table row."""

        inventory_fields = {"route_ids", "landing_sha256s", "landing_receipt_roots"}
        dataclass_names = frozenset(field.name for field in fields(cls))
        stored_names = (dataclass_names - inventory_fields) | {
            "schema_version",
            "route_ids_json",
            "route_ids_sha256",
            "route_count",
            "landing_sha256s_json",
            "landing_sha256s_sha256",
            "landing_receipt_roots_json",
            "landing_receipt_roots_sha256",
            "landing_count",
        }
        row = _exact_row(value, expected=stored_names, label="observation-plan binding")
        route_ids = _row_string_inventory(
            row,
            json_field="route_ids_json",
            digest_field="route_ids_sha256",
            count_field="route_count",
            label="observation-plan routes",
            sha_values=False,
        )
        landing_sha256s = _row_string_inventory(
            row,
            json_field="landing_sha256s_json",
            digest_field="landing_sha256s_sha256",
            count_field="landing_count",
            label="observation-plan landing digests",
            sha_values=True,
        )
        landing_receipt_roots = _row_string_inventory(
            row,
            json_field="landing_receipt_roots_json",
            digest_field="landing_receipt_roots_sha256",
            count_field="landing_count",
            label="observation-plan landing receipt roots",
            sha_values=True,
        )
        kwargs = {
            field_name: row[field_name]
            for field_name in dataclass_names
            if field_name not in inventory_fields
        }
        kwargs.update(
            {
                "route_ids": route_ids,
                "landing_sha256s": landing_sha256s,
                "landing_receipt_roots": landing_receipt_roots,
                "live_snapshot_at": _row_utc(
                    row["live_snapshot_at"], field_name="live_snapshot_at"
                ),
            }
        )
        try:
            return cast("Self", _strict_binding(cls(**kwargs)))  # ty: ignore[invalid-argument-type]
        except (TypeError, ValueError) as exc:
            raise RawLivePlanAuthorityError(
                "observation-plan binding row failed semantic reconstruction"
            ) from exc


def _strict_generation(value: object) -> LivePlanGenerationReceiptV2:
    if type(value) is not LivePlanGenerationReceiptV2:
        _fail("live-plan generation does not have its exact contract type")
    try:
        rebuilt = LivePlanGenerationReceiptV2(
            **{
                field_name: getattr(value, field_name)
                for field_name in value.__dataclass_fields__
                if not field_name.startswith("_") and field_name not in {"schema_version", "kind"}
            }
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError(
            "live-plan generation failed strict reconstruction"
        ) from exc
    if rebuilt != value:
        _fail("live-plan generation changed during strict reconstruction")
    return rebuilt


def _strict_admission(value: object) -> LivePlanCallAdmissionV2:
    if type(value) is not LivePlanCallAdmissionV2:
        _fail("live-plan call admission does not have its exact contract type")
    try:
        rebuilt = LivePlanCallAdmissionV2(
            **{
                field_name: getattr(value, field_name)
                for field_name in value.__dataclass_fields__
                if not field_name.startswith("_") and field_name not in {"schema_version", "kind"}
            }
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError(
            "live-plan call admission failed strict reconstruction"
        ) from exc
    if rebuilt != value:
        _fail("live-plan call admission changed during strict reconstruction")
    return rebuilt


def _strict_binding(value: object) -> LiveObservationPlanBindingV2:
    if type(value) is not LiveObservationPlanBindingV2:
        _fail("observation-plan binding does not have its exact contract type")
    try:
        rebuilt = LiveObservationPlanBindingV2(
            **{
                field_name: getattr(value, field_name)
                for field_name in value.__dataclass_fields__
                if not field_name.startswith("_") and field_name not in {"schema_version", "kind"}
            }
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError(
            "observation-plan binding failed strict reconstruction"
        ) from exc
    if rebuilt != value:
        _fail("observation-plan binding changed during strict reconstruction")
    return rebuilt


def _strict_attempt(value: object) -> RequestAttemptIdentityV2:
    if type(value) is not RequestAttemptIdentityV2:
        _fail("live plan received a foreign request-attempt type")
    try:
        return validate_request_attempt_identity(value)
    except (TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError("live request attempt failed strict validation") from exc


def _strict_observation(value: object) -> RequestObservationV2:
    if type(value) is not RequestObservationV2:
        _fail("live plan received a foreign observation type")
    try:
        return validate_request_observation(value)
    except (TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError("live observation failed strict validation") from exc


def _strict_landings(
    value: object,
    observation_sha256: str,
) -> tuple[ObservationRouteLandingV2, ...]:
    if type(value) is not tuple or not value:
        _fail("live observation lacks an exact route-landing tuple")
    try:
        parsed = tuple(validate_observation_route_landing(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError("live route landing failed strict validation") from exc
    if any(item.observation_sha256 != observation_sha256 for item in parsed):
        _fail("live route landing crosses observation identity")
    if tuple(item.route_ordinal for item in parsed) != tuple(range(len(parsed))):
        _fail("live route landing order is not exact and contiguous")
    if len({item.route_id for item in parsed}) != len(parsed):
        _fail("live route landing repeats a route identity")
    return parsed


def _validate_live_observation_plan_structure(
    generation: LivePlanGenerationReceiptV2,
    admission: LivePlanCallAdmissionV2,
    binding: LiveObservationPlanBindingV2,
    authority_bundle: RawRequestAuthorityBundleV2,
) -> LiveSnapshotPlanAuthorityV2:
    """Reconstruct one structural projection without claiming external trust."""

    exact_generation = _strict_generation(generation)
    exact_admission = _strict_admission(admission)
    exact_binding = _strict_binding(binding)
    rebuilt_binding = LiveObservationPlanBindingV2.build(
        generation=exact_generation,
        admission=exact_admission,
        authority_bundle=authority_bundle,
        observation_sha256=exact_binding.observation_sha256,
    )
    if rebuilt_binding != exact_binding:
        _fail("observation-plan binding differs from exact public authorities")
    try:
        authority = LiveSnapshotPlanAuthorityV2(
            authority_sha256=exact_binding.live_plan_authority_sha256,
            sealed_plan_bytes=exact_generation.sealed_plan_bytes,
            sealed_plan_sha256=exact_generation.sealed_plan_sha256,
            sealed_plan_length=exact_generation.sealed_plan_length,
            source_sha=exact_binding.source_sha,
            run_id=exact_binding.run_id,
            run_attempt=exact_binding.run_attempt,
            chain_id=exact_binding.chain_id,
            lane_id=exact_binding.lane_id,
            observation_sha256=exact_binding.observation_sha256,
            scope_sha256=exact_binding.scope_sha256,
            safe_parameters_sha256=exact_binding.safe_parameters_sha256,
            endpoint_id=exact_binding.endpoint_id,
            endpoint_contract_sha256=exact_binding.endpoint_contract_sha256,
            provider_authority_sha256=exact_binding.provider_authority_sha256,
            route_ids=exact_binding.route_ids,
            live_snapshot_at=exact_binding.live_snapshot_at,
        )
    except (RawRequestReconstructionError, TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError(
            "live plan projection failed exact authority reconstruction"
        ) from exc
    return authority


def validate_live_observation_plan_authority(
    generation: LivePlanGenerationReceiptV2,
    admission: LivePlanCallAdmissionV2,
    binding: LiveObservationPlanBindingV2,
    authority_bundle: RawRequestAuthorityBundleV2,
) -> LiveSnapshotPlanAuthorityV2:
    """Fail closed until a repo-pinned authenticated collector is integrated."""

    _validate_live_observation_plan_structure(
        generation,
        admission,
        binding,
        authority_bundle,
    )
    _fail("authenticated live-plan external authority source is unavailable")


def _table_items(value: object, *, label: str) -> tuple[object, ...]:
    if type(value) not in {tuple, list}:
        _fail(f"{label} must be one exact row sequence")
    sequence = cast("list[object] | tuple[object, ...]", value)
    if len(sequence) > _MAX_LIVE_PLAN_TABLE_ROWS:
        _fail(f"{label} exceeds its exact row bound")
    return sequence if type(sequence) is tuple else tuple(sequence)


def _preflight_table_bytes(
    rows: tuple[object, ...],
    *,
    fields_by_type: dict[type[object], tuple[str, ...]],
    raw_fields: tuple[str, ...],
    label: str,
) -> None:
    """Bound aggregate public bytes before any restart JSON parser runs."""

    total = 0
    for item in rows:
        if type(item) is dict:
            values = cast("dict[object, object]", item)
            field_names = raw_fields
            getter = values.get
        else:
            field_names = fields_by_type.get(type(item), ())
            row_factory = getattr(item, "to_row", None)
            values = row_factory() if field_names and callable(row_factory) else {}
            getter = values.get
        for field_name in field_names:
            value = getter(field_name)
            if type(value) is bytes:
                total += len(value)
            elif type(value) is str:
                try:
                    total += len(value.encode("utf-8", errors="strict"))
                except UnicodeEncodeError as exc:
                    raise RawLivePlanAuthorityError(
                        f"{label} contains non-UTF-8 public text"
                    ) from exc
            elif value is not None:
                _fail(f"{label} public-byte field has a foreign exact type")
            if total > _MAX_LIVE_PLAN_TABLE_BYTES:
                _fail(f"{label} exceeds its aggregate public-byte bound")


def _validate_parent_graph(
    generations: tuple[LivePlanGenerationReceiptV2, ...],
    generation_by_receipt: dict[str, LivePlanGenerationReceiptV2],
) -> None:
    """Validate every parent chain in linear bounded work."""

    complete: set[str] = set()
    for generation in generations:
        if generation.generation_receipt_sha256 in complete:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        cursor = generation
        while cursor.generation_receipt_sha256 not in complete:
            receipt = cursor.generation_receipt_sha256
            if receipt in positions:
                _fail("live-plan generation parent graph contains a cycle")
            positions[receipt] = len(path)
            path.append(receipt)
            parent_receipt = cursor.parent_generation_receipt_sha256
            if parent_receipt is None:
                break
            parent = generation_by_receipt.get(parent_receipt)
            if parent is None:
                _fail("live-plan generation parent graph is incomplete")
            cursor = parent
        complete.update(path)


def validate_live_plan_authority_tables(
    generation_rows: object,
    admission_rows: object,
    binding_rows: object,
    authority_bundle: RawRequestAuthorityBundleV2,
) -> tuple[
    tuple[LivePlanGenerationReceiptV2, ...],
    tuple[LivePlanCallAdmissionV2, ...],
    tuple[LiveObservationPlanBindingV2, ...],
]:
    """Validate structure, then fail closed without authenticated external trust."""

    try:
        bundle = validate_raw_request_authority_bundle(authority_bundle)
    except (TypeError, ValueError) as exc:
        raise RawLivePlanAuthorityError(
            "live-plan table validation received an invalid raw authority bundle"
        ) from exc
    raw_generation_rows = _table_items(
        generation_rows,
        label="live-plan generation rows",
    )
    raw_admission_rows = _table_items(
        admission_rows,
        label="live-plan call-admission rows",
    )
    raw_binding_rows = _table_items(
        binding_rows,
        label="observation-plan binding rows",
    )
    _preflight_table_bytes(
        raw_generation_rows,
        fields_by_type={LivePlanGenerationReceiptV2: ("sealed_plan_bytes",)},
        raw_fields=("sealed_plan_bytes",),
        label="live-plan generation table",
    )
    _preflight_table_bytes(
        raw_admission_rows,
        fields_by_type={LivePlanCallAdmissionV2: ("route_ids_json",)},
        raw_fields=("route_ids_json",),
        label="live-plan call-admission table",
    )
    _preflight_table_bytes(
        raw_binding_rows,
        fields_by_type={
            LiveObservationPlanBindingV2: (
                "route_ids_json",
                "landing_sha256s_json",
                "landing_receipt_roots_json",
            )
        },
        raw_fields=(
            "route_ids_json",
            "landing_sha256s_json",
            "landing_receipt_roots_json",
        ),
        label="observation-plan binding table",
    )
    generations = tuple(
        _strict_generation(item)
        if type(item) is LivePlanGenerationReceiptV2
        else LivePlanGenerationReceiptV2.from_row(item)
        for item in raw_generation_rows
    )
    admissions = tuple(
        _strict_admission(item)
        if type(item) is LivePlanCallAdmissionV2
        else LivePlanCallAdmissionV2.from_row(item)
        for item in raw_admission_rows
    )
    bindings = tuple(
        _strict_binding(item)
        if type(item) is LiveObservationPlanBindingV2
        else LiveObservationPlanBindingV2.from_row(item)
        for item in raw_binding_rows
    )
    if not generations:
        _fail("live-plan generation table is empty")
    generation_by_receipt = {item.generation_receipt_sha256: item for item in generations}
    admission_by_observation = {item.observation_sha256: item for item in admissions}
    binding_by_observation = {item.observation_sha256: item for item in bindings}
    if (
        len(generation_by_receipt) != len(generations)
        or len({item.generation_id for item in generations}) != len(generations)
        or len(admission_by_observation) != len(admissions)
        or len({item.admission_receipt_sha256 for item in admissions}) != len(admissions)
        or len(binding_by_observation) != len(bindings)
        or len({item.binding_receipt_sha256 for item in bindings}) != len(bindings)
    ):
        _fail("live-plan table primary keys are duplicated")
    if generations != tuple(sorted(generations, key=lambda item: item.generation_receipt_sha256)):
        _fail("live-plan generation rows are not in canonical primary-key order")
    if admissions != tuple(sorted(admissions, key=lambda item: item.observation_sha256)):
        _fail("live-plan call-admission rows are not in canonical observation order")
    if bindings != tuple(sorted(bindings, key=lambda item: item.observation_sha256)):
        _fail("observation-plan binding rows are not in canonical observation order")

    for generation in generation_by_receipt.values():
        parent_sha256 = generation.parent_generation_receipt_sha256
        if parent_sha256 is None:
            continue
        parent = generation_by_receipt.get(parent_sha256)
        if parent is None:
            _fail("derived live-plan generation has an orphan parent")
        if (
            parent.source_sha != generation.source_sha
            or parent.chain_id != generation.chain_id
            or parent.generated_at > generation.generated_at
            or parent.live_snapshot_at > generation.live_snapshot_at
        ):
            _fail("derived live-plan generation crosses or precedes its parent authority")
    _validate_parent_graph(generations, generation_by_receipt)

    expected_plan_members: set[tuple[str, int]] = set()
    for generation in generations:
        _plan_bytes, plan_items = _validate_public_plan_bytes(generation.sealed_plan_bytes)
        expected_plan_members.update(
            (generation.generation_receipt_sha256, item.plan_item_ordinal) for item in plan_items
        )
        if len(expected_plan_members) > _MAX_PLAN_ITEMS:
            _fail("live-plan table exceeds its aggregate plan-member bound")

    observation_by_sha = {item.attempt.observation_sha256: item for item in bundle.observations}
    live_observation_ids = {
        key for key, item in observation_by_sha.items() if item.attempt.source_family == "live"
    }
    selected_live_ids = {
        key
        for key, item in observation_by_sha.items()
        if item.attempt.source_family == "live" and item.lifecycle == "selected_terminal"
    }
    if set(admission_by_observation) != live_observation_ids:
        _fail("live-plan call-admission table denominator differs from raw live observations")
    if set(binding_by_observation) != selected_live_ids:
        _fail("observation-plan binding denominator differs from selected raw live observations")
    admitted_plan_members: set[tuple[str, int]] = set()
    for observation_sha256, admission in admission_by_observation.items():
        observation = observation_by_sha[observation_sha256]
        generation = generation_by_receipt.get(admission.plan_generation_receipt_sha256)
        if generation is None:
            _fail("live-plan call admission references a missing generation")
        rebuilt = LivePlanCallAdmissionV2.build(
            generation=generation,
            attempt=observation.attempt,
            plan_item_ordinal=admission.plan_item_ordinal,
            issued_at=admission.issued_at,
            authorized_at=admission.authorized_at,
            expires_at=admission.expires_at,
            authorization_collector_receipt_sha256=(
                admission.authorization_collector_receipt_sha256
            ),
            authorization_receipt_sha256=admission.authorization_receipt_sha256,
        )
        if rebuilt != admission:
            _fail("persisted live-plan call admission differs from its typed plan authority")
        admitted_plan_members.add(
            (admission.plan_generation_receipt_sha256, admission.plan_item_ordinal)
        )
    if len(admitted_plan_members) != len(admissions):
        _fail("live-plan item disposition denominator contains duplicate admissions")
    if admitted_plan_members != expected_plan_members:
        _fail("live-plan item disposition denominator is incomplete or additive")

    for observation_sha256, binding in binding_by_observation.items():
        admission = admission_by_observation[observation_sha256]
        generation = generation_by_receipt.get(binding.plan_generation_receipt_sha256)
        if generation is None or binding.plan_admission_receipt_sha256 != (
            admission.admission_receipt_sha256
        ):
            _fail("observation-plan binding references missing or foreign plan authority")
        _validate_live_observation_plan_structure(
            generation,
            admission,
            binding,
            bundle,
        )
    _fail("authenticated live-plan external authority source is unavailable")
