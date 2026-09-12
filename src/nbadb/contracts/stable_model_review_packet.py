"""Canonical red-only work packets for stable-model disposition review.

The packet compiler freezes the exact structural candidate census and the
requirement-preserving disposition drafts into bounded, content-addressed
review work.  It deliberately has no authority-admission surface: it does not
call GitHub, construct :class:`ReviewReceiptV1`, or make a model-green claim.
Every emitted result slot remains pending until a later, externally
authenticated review-admission stage replaces this work packet with separate
authority evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from nbadb.contracts.model_candidate_census import (
    ModelCandidateCensusEvidenceV1,
    ModelCandidateCensusV1,
    canonical_analytical_needs_authority_v1,
    compile_current_model_candidate_census,
)
from nbadb.contracts.stable_model_disposition import (
    StableModelCandidateV1,
    StableModelDispositionV1,
    draft_required_model_dispositions,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND",
    "STABLE_MODEL_REVIEW_CANDIDATE_COUNT",
    "STABLE_MODEL_REVIEW_MAX_SHARD_SIZE",
    "STABLE_MODEL_REVIEW_PACKET_KIND",
    "STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION",
    "STABLE_MODEL_REVIEW_SHARD_COUNT",
    "StableModelReviewChallengeV1",
    "StableModelReviewContentV1",
    "StableModelReviewPacketError",
    "StableModelReviewPacketV1",
    "StableModelReviewResultSlotV1",
    "StableModelReviewShardV1",
    "compile_current_stable_model_review_packet",
    "compile_stable_model_review_packet",
]

STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION = 1
STABLE_MODEL_REVIEW_PACKET_KIND = "nbadb_stable_model_review_work_packet"
GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND = "github_pull_request_review_v1"

STABLE_MODEL_REVIEW_CANDIDATE_COUNT = 1_128
STABLE_MODEL_REVIEW_MAX_SHARD_SIZE = 64
STABLE_MODEL_REVIEW_SHARD_COUNT = 22

_EXPECTED_DEPTH_COUNTS = (431, 439, 219, 17, 11, 8, 3)
_EXPECTED_SHARD_COUNTS = (7, 7, 4, 1, 1, 1, 1)
_REQUIRED_VALIDATION_CLASSES = ("mutation", "negative", "positive")
_PENDING_REVIEW_STATE = "pending_external_review"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)

_MAX_CENSUS_BYTES = 64 * 1024 * 1024
_MAX_REVIEW_INPUT_BYTES = 2 * 1024 * 1024
_MAX_RESULT_SLOT_BYTES = 1 * 1024 * 1024
_MAX_SHARD_BYTES = 16 * 1024 * 1024
_MAX_PACKET_BYTES = 128 * 1024 * 1024
_MAX_CHALLENGE_BYTES = 1 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 2_000_000

type ReviewContentKind = Literal["candidate_census", "candidate_review_input"]
type ReviewWorkState = Literal["pending_external_review"]
type ReviewChallengeState = Literal["awaiting_github_pull_request_review"]


class StableModelReviewPacketError(ValueError):
    """The stable-model review work packet is malformed or stale."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, MemoryError) as exc:
        raise StableModelReviewPacketError("review packet value is not canonical JSON") from exc


def _canonical_text(value: object) -> str:
    return _canonical_bytes(value).decode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise StableModelReviewPacketError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_git_sha(value: object, *, field_name: str = "source_sha") -> str:
    if type(value) is not str or _GIT_SHA_RE.fullmatch(value) is None:
        raise StableModelReviewPacketError(f"{field_name} must be a lowercase 40-character Git SHA")
    return value


def _require_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise StableModelReviewPacketError(f"{field_name} must be a safe nonempty identifier")
    return value


def _require_int(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise StableModelReviewPacketError(f"{field_name} is outside its exact integer bounds")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if any(type(key) is not str for key in payload):
        raise StableModelReviewPacketError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = ",".join(sorted(expected - actual))
    unexpected = ",".join(sorted(actual - expected))
    raise StableModelReviewPacketError(
        f"{label} fields differ (missing={missing}; unexpected={unexpected})"
    )


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise StableModelReviewPacketError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _validate_json_tree(value: object, *, label: str) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise StableModelReviewPacketError(f"{label} exceeds its JSON node budget")
        if depth > _MAX_JSON_DEPTH:
            raise StableModelReviewPacketError(f"{label} exceeds its JSON depth budget")
        if type(current) is dict:
            mapping = cast("dict[object, object]", current)
            if any(type(key) is not str for key in mapping):
                raise StableModelReviewPacketError(f"{label} contains a non-string JSON key")
            stack.extend((item, depth + 1) for item in mapping.values())
        elif type(current) is list:
            stack.extend((item, depth + 1) for item in cast("list[object]", current))
        elif current is None or type(current) in {str, int, float, bool}:
            continue
        else:
            raise StableModelReviewPacketError(f"{label} contains a non-JSON value")


def _guard_json_lexical_structure(raw: bytes, *, label: str) -> None:
    """Bound JSON allocation shape before the materializing decoder runs.

    The scanner is deliberately iterative and allocation-constant apart from a
    depth-bounded delimiter stack.  It treats quoted strings, including escaped
    quotes and structural characters, as opaque tokens.  Object-key strings are
    counted too because they allocate Python objects even though the later
    semantic tree walk counts only values.
    """

    stack: list[int] = []
    node_count = 0
    index = 0
    raw_length = len(raw)
    whitespace = frozenset({0x09, 0x0A, 0x0D, 0x20})
    scalar_delimiters = frozenset(
        {
            0x09,
            0x0A,
            0x0D,
            0x20,
            0x22,
            0x2C,
            0x3A,
            0x5B,
            0x5D,
            0x7B,
            0x7D,
        }
    )

    while index < raw_length:
        token = raw[index]
        if token in whitespace:
            index += 1
            continue
        if token in {0x2C, 0x3A}:  # comma or colon
            index += 1
            continue
        if token in {0x7B, 0x5B}:  # object or array open
            node_count += 1
            if node_count > _MAX_JSON_NODES:
                raise StableModelReviewPacketError(f"{label} exceeds its JSON node budget")
            if len(stack) >= _MAX_JSON_DEPTH:
                raise StableModelReviewPacketError(f"{label} exceeds its JSON depth budget")
            stack.append(token)
            index += 1
            continue
        if token in {0x7D, 0x5D}:  # object or array close
            if not stack:
                raise StableModelReviewPacketError(
                    f"{label} contains an unmatched JSON closing delimiter"
                )
            expected_open = 0x7B if token == 0x7D else 0x5B
            if stack.pop() != expected_open:
                raise StableModelReviewPacketError(f"{label} contains mismatched JSON delimiters")
            index += 1
            continue
        if token == 0x22:  # quoted string, including object keys
            node_count += 1
            if node_count > _MAX_JSON_NODES:
                raise StableModelReviewPacketError(f"{label} exceeds its JSON node budget")
            index += 1
            while index < raw_length:
                string_byte = raw[index]
                if string_byte == 0x22:
                    index += 1
                    break
                if string_byte == 0x5C:  # escape: next byte stays inside the string
                    index += 2
                    if index > raw_length:
                        raise StableModelReviewPacketError(
                            f"{label} contains a truncated JSON string escape"
                        )
                    continue
                if string_byte < 0x20:
                    raise StableModelReviewPacketError(
                        f"{label} contains an unescaped JSON control byte"
                    )
                index += 1
            else:
                raise StableModelReviewPacketError(f"{label} contains an unterminated JSON string")
            continue

        # A number, true/false/null, non-finite constant, or invalid bare token
        # still represents at least one decoder allocation attempt.  Count it
        # now; json.loads remains the grammar authority below.
        node_count += 1
        if node_count > _MAX_JSON_NODES:
            raise StableModelReviewPacketError(f"{label} exceeds its JSON node budget")
        index += 1
        while index < raw_length and raw[index] not in scalar_delimiters:
            index += 1

    if stack:
        raise StableModelReviewPacketError(f"{label} contains unclosed JSON delimiters")


def _decode_json(
    raw: bytes,
    *,
    label: str,
    maximum_bytes: int,
    require_canonical: bool,
) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > maximum_bytes:
        raise StableModelReviewPacketError(f"{label} bytes are empty or exceed their bound")

    try:
        _guard_json_lexical_structure(raw, label=label)
    except StableModelReviewPacketError:
        raise
    except (RecursionError, MemoryError) as exc:
        raise StableModelReviewPacketError(
            f"{label} exceeded resource bounds before JSON decoding"
        ) from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise StableModelReviewPacketError(f"{label} contains duplicate key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise StableModelReviewPacketError(f"{label} contains non-finite constant: {value}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, MemoryError) as exc:
        raise StableModelReviewPacketError(
            f"{label} bytes are invalid JSON or exceeded decoder resource bounds"
        ) from exc
    try:
        _validate_json_tree(value, label=label)
    except StableModelReviewPacketError:
        raise
    except (RecursionError, MemoryError) as exc:
        raise StableModelReviewPacketError(
            f"{label} exceeded resource bounds during JSON validation"
        ) from exc
    payload = _require_mapping(value, label=label)
    if require_canonical and _canonical_bytes(payload) != raw:
        raise StableModelReviewPacketError(f"{label} bytes are not canonical")
    return payload


def _decode_canonical_text(
    value: object,
    *,
    label: str,
    maximum_bytes: int,
) -> Mapping[str, object]:
    if type(value) is not str:
        raise StableModelReviewPacketError(f"{label} canonical JSON must be a string")
    return _decode_json(
        value.encode("utf-8"),
        label=label,
        maximum_bytes=maximum_bytes,
        require_canonical=True,
    )


def _sha_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise StableModelReviewPacketError(f"{field_name} must be an array")
    values = tuple(
        _require_sha256(item, field_name=field_name) for item in cast("list[object]", value)
    )
    if not values or values != tuple(sorted(set(values))):
        raise StableModelReviewPacketError(f"{field_name} must be nonempty, sorted, and unique")
    return values


def _id_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise StableModelReviewPacketError(f"{field_name} must be an array")
    values = tuple(_require_id(item, field_name=field_name) for item in value)
    if not values or values != tuple(sorted(set(values))):
        raise StableModelReviewPacketError(f"{field_name} must be nonempty, sorted, and unique")
    return values


def _compute_topological_depths(
    candidates: Sequence[StableModelCandidateV1],
) -> dict[str, int]:
    by_id = {item.candidate_id: item for item in candidates}
    if len(by_id) != len(candidates):
        raise StableModelReviewPacketError("candidate identities overlap")
    pending = set(by_id)
    depths: dict[str, int] = {}
    while pending:
        progress = False
        for candidate_id in sorted(tuple(pending)):
            dependencies = by_id[candidate_id].dependency_ids
            if any(dependency_id not in by_id for dependency_id in dependencies):
                raise StableModelReviewPacketError(
                    f"candidate has a foreign dependency: {candidate_id}"
                )
            if all(dependency_id in depths for dependency_id in dependencies):
                depths[candidate_id] = (
                    0
                    if not dependencies
                    else 1 + max(depths[dependency_id] for dependency_id in dependencies)
                )
                pending.remove(candidate_id)
                progress = True
        if not progress:
            raise StableModelReviewPacketError("candidate dependency graph is cyclic")
    return depths


@dataclass(frozen=True, slots=True)
class StableModelReviewContentV1:
    """One canonical content-addressed input embedded in the review packet."""

    content_kind: ReviewContentKind
    subject_id: str
    canonical_json: str
    content_sha256: str = ""

    schema_version: ClassVar[int] = STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION
    kind: ClassVar[str] = "stable_model_review_content_v1"

    def __post_init__(self) -> None:
        if self.content_kind not in {"candidate_census", "candidate_review_input"}:
            raise StableModelReviewPacketError("review content kind is unsupported")
        _require_id(self.subject_id, field_name="review content subject_id")
        maximum = (
            _MAX_CENSUS_BYTES
            if self.content_kind == "candidate_census"
            else _MAX_REVIEW_INPUT_BYTES
        )
        raw = self.canonical_json.encode("utf-8")
        _decode_json(
            raw,
            label=f"{self.content_kind} content",
            maximum_bytes=maximum,
            require_canonical=True,
        )
        expected = _sha256_bytes(raw)
        if self.content_sha256 and self.content_sha256 != expected:
            raise StableModelReviewPacketError("review content digest differs from its bytes")
        object.__setattr__(self, "content_sha256", expected)

    @property
    def content(self) -> Mapping[str, object]:
        # Construction already performed duplicate, non-finite, size, depth,
        # node, and canonical-byte validation.  Replays can therefore decode
        # without redundantly repeating those bounded checks.
        return cast("Mapping[str, object]", json.loads(self.canonical_json))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "content_kind": self.content_kind,
            "subject_id": self.subject_id,
            "content": dict(self.content),
            "content_sha256": self.content_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="review content")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "content_kind",
                    "subject_id",
                    "content",
                    "content_sha256",
                }
            ),
            label="review content",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise StableModelReviewPacketError("review content schema identity is invalid")
        result = cls(
            content_kind=cast("ReviewContentKind", payload["content_kind"]),
            subject_id=cast("str", payload["subject_id"]),
            canonical_json=_canonical_text(payload["content"]),
            content_sha256=cast("str", payload["content_sha256"]),
        )
        if payload != result.to_dict():
            raise StableModelReviewPacketError("review content differs from exact reconstruction")
        return result


@dataclass(frozen=True, slots=True, order=True)
class StableModelReviewResultSlotV1:
    """One deliberately empty result slot for a future external reviewer."""

    candidate_id: str
    topological_depth: int
    candidate_sha256: str
    candidate_structural_sha256: str
    draft_semantic_sha256: str
    pending_review_identity_sha256: str
    review_input_sha256: str
    required_review_input_sha256s: tuple[str, ...]
    required_validation_classes: tuple[str, ...] = _REQUIRED_VALIDATION_CLASSES
    work_state: ReviewWorkState = _PENDING_REVIEW_STATE
    review_receipt_sha256: None = None
    validation_receipt_sha256s: tuple[str, ...] = ()

    schema_version: ClassVar[int] = STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION
    kind: ClassVar[str] = "stable_model_review_result_slot_v1"

    def __post_init__(self) -> None:
        _require_id(self.candidate_id, field_name="result slot candidate_id")
        _require_int(
            self.topological_depth,
            field_name="result slot topological_depth",
            maximum=len(_EXPECTED_DEPTH_COUNTS) - 1,
        )
        for field_name in (
            "candidate_sha256",
            "candidate_structural_sha256",
            "draft_semantic_sha256",
            "pending_review_identity_sha256",
            "review_input_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if (
            type(self.required_review_input_sha256s) is not tuple
            or not self.required_review_input_sha256s
            or self.required_review_input_sha256s
            != tuple(sorted(set(self.required_review_input_sha256s)))
        ):
            raise StableModelReviewPacketError(
                "required review inputs must be a nonempty sorted unique tuple"
            )
        for digest in self.required_review_input_sha256s:
            _require_sha256(digest, field_name="required_review_input_sha256s")
        required_inputs = {
            self.candidate_sha256,
            self.candidate_structural_sha256,
            self.draft_semantic_sha256,
            self.pending_review_identity_sha256,
            self.review_input_sha256,
        }
        if not required_inputs.issubset(self.required_review_input_sha256s):
            raise StableModelReviewPacketError(
                "result slot required inputs omit candidate, draft, or content authority"
            )
        if self.required_validation_classes != _REQUIRED_VALIDATION_CLASSES:
            raise StableModelReviewPacketError(
                "result slot must require exact mutation, negative, and positive validation"
            )
        if self.work_state != _PENDING_REVIEW_STATE:
            raise StableModelReviewPacketError("result slot is not pending external review")
        if self.review_receipt_sha256 is not None or self.validation_receipt_sha256s != ():
            raise StableModelReviewPacketError(
                "red review work cannot contain review or validation receipts"
            )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "candidate_id": self.candidate_id,
            "topological_depth": self.topological_depth,
            "candidate_sha256": self.candidate_sha256,
            "candidate_structural_sha256": self.candidate_structural_sha256,
            "draft_semantic_sha256": self.draft_semantic_sha256,
            "pending_review_identity_sha256": self.pending_review_identity_sha256,
            "review_input_sha256": self.review_input_sha256,
            "required_review_input_sha256s": list(self.required_review_input_sha256s),
            "required_validation_classes": list(self.required_validation_classes),
            "work_state": self.work_state,
            "review_receipt_sha256": self.review_receipt_sha256,
            "validation_receipt_sha256s": list(self.validation_receipt_sha256s),
        }

    @property
    def result_slot_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "result_slot_sha256": _sha256(content)}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="review result slot")
        fields = frozenset(
            {
                "candidate_id",
                "topological_depth",
                "candidate_sha256",
                "candidate_structural_sha256",
                "draft_semantic_sha256",
                "pending_review_identity_sha256",
                "review_input_sha256",
                "required_review_input_sha256s",
                "required_validation_classes",
                "work_state",
                "review_receipt_sha256",
                "validation_receipt_sha256s",
                "result_slot_sha256",
            }
        )
        _require_exact_keys(
            payload,
            expected=frozenset({"schema_version", "kind", *fields}),
            label="review result slot",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(payload["required_validation_classes"]) is not list
            or type(payload["validation_receipt_sha256s"]) is not list
        ):
            raise StableModelReviewPacketError("review result slot schema is invalid")
        result = cls(
            candidate_id=cast("str", payload["candidate_id"]),
            topological_depth=_require_int(
                payload["topological_depth"],
                field_name="result slot topological_depth",
                maximum=len(_EXPECTED_DEPTH_COUNTS) - 1,
            ),
            candidate_sha256=cast("str", payload["candidate_sha256"]),
            candidate_structural_sha256=cast("str", payload["candidate_structural_sha256"]),
            draft_semantic_sha256=cast("str", payload["draft_semantic_sha256"]),
            pending_review_identity_sha256=cast("str", payload["pending_review_identity_sha256"]),
            review_input_sha256=cast("str", payload["review_input_sha256"]),
            required_review_input_sha256s=_sha_tuple(
                payload["required_review_input_sha256s"],
                field_name="required_review_input_sha256s",
            ),
            required_validation_classes=tuple(
                cast("list[str]", payload["required_validation_classes"])
            ),
            work_state=cast("ReviewWorkState", payload["work_state"]),
            review_receipt_sha256=cast("None", payload["review_receipt_sha256"]),
            validation_receipt_sha256s=tuple(
                cast("list[str]", payload["validation_receipt_sha256s"])
            ),
        )
        if payload != result.to_dict():
            raise StableModelReviewPacketError(
                "review result slot differs from exact red reconstruction"
            )
        return result

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(
            _decode_json(
                raw,
                label="review result slot",
                maximum_bytes=_MAX_RESULT_SLOT_BYTES,
                require_canonical=True,
            )
        )


@dataclass(frozen=True, slots=True)
class StableModelReviewShardV1:
    """One exact topological review shard containing at most 64 result slots."""

    source_sha: str
    topological_depth: int
    shard_ordinal: int
    candidate_source_authority_sha256: str
    candidate_census_canonical_bytes_sha256: str
    candidate_inventory_sha256: str
    disposition_draft_inventory_sha256: str
    review_input_inventory_sha256: str
    result_slots: tuple[StableModelReviewResultSlotV1, ...]
    external_challenge_kind: str = GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND

    schema_version: ClassVar[int] = STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION
    kind: ClassVar[str] = "stable_model_review_shard_v1"

    def __post_init__(self) -> None:
        _require_git_sha(self.source_sha)
        _require_int(
            self.topological_depth,
            field_name="shard topological_depth",
            maximum=len(_EXPECTED_DEPTH_COUNTS) - 1,
        )
        _require_int(
            self.shard_ordinal,
            field_name="shard_ordinal",
            maximum=STABLE_MODEL_REVIEW_SHARD_COUNT - 1,
        )
        for field_name in (
            "candidate_source_authority_sha256",
            "candidate_census_canonical_bytes_sha256",
            "candidate_inventory_sha256",
            "disposition_draft_inventory_sha256",
            "review_input_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if self.external_challenge_kind != GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND:
            raise StableModelReviewPacketError("shard external challenge kind is unsupported")
        if (
            type(self.result_slots) is not tuple
            or not 1 <= len(self.result_slots) <= STABLE_MODEL_REVIEW_MAX_SHARD_SIZE
            or any(type(item) is not StableModelReviewResultSlotV1 for item in self.result_slots)
        ):
            raise StableModelReviewPacketError(
                "shard result slots are empty, oversized, or foreign"
            )
        if self.result_slots != tuple(
            sorted(self.result_slots, key=lambda item: item.candidate_id)
        ) or len({item.candidate_id for item in self.result_slots}) != len(self.result_slots):
            raise StableModelReviewPacketError("shard result slots are duplicated or unsorted")
        if any(item.topological_depth != self.topological_depth for item in self.result_slots):
            raise StableModelReviewPacketError("review shard crosses topological depths")

    @property
    def shard_id(self) -> str:
        return f"stable-model-review-depth-{self.topological_depth}-shard-{self.shard_ordinal:02d}"

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.result_slots)

    @property
    def candidate_id_inventory_sha256(self) -> str:
        return _sha256(list(self.candidate_ids))

    @property
    def result_slot_inventory_sha256(self) -> str:
        return _sha256([item.to_dict() for item in self.result_slots])

    def _content_dict(self) -> dict[str, object]:
        candidate_ids = list(self.candidate_ids)
        result_slots = [item.to_dict() for item in self.result_slots]
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "shard_id": self.shard_id,
            "topological_depth": self.topological_depth,
            "shard_ordinal": self.shard_ordinal,
            "candidate_source_authority_sha256": self.candidate_source_authority_sha256,
            "candidate_census_canonical_bytes_sha256": (
                self.candidate_census_canonical_bytes_sha256
            ),
            "candidate_inventory_sha256": self.candidate_inventory_sha256,
            "disposition_draft_inventory_sha256": (self.disposition_draft_inventory_sha256),
            "review_input_inventory_sha256": self.review_input_inventory_sha256,
            "external_challenge_kind": self.external_challenge_kind,
            "candidate_count": len(result_slots),
            "candidate_ids": candidate_ids,
            "candidate_id_inventory_sha256": _sha256(candidate_ids),
            "result_slot_inventory_sha256": _sha256(result_slots),
            "result_slots": result_slots,
        }

    @property
    def shard_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "shard_sha256": _sha256(content)}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="stable model review shard")
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "source_sha",
                "shard_id",
                "topological_depth",
                "shard_ordinal",
                "candidate_source_authority_sha256",
                "candidate_census_canonical_bytes_sha256",
                "candidate_inventory_sha256",
                "disposition_draft_inventory_sha256",
                "review_input_inventory_sha256",
                "external_challenge_kind",
                "candidate_count",
                "candidate_ids",
                "candidate_id_inventory_sha256",
                "result_slot_inventory_sha256",
                "result_slots",
                "shard_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="stable model review shard")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(payload["result_slots"]) is not list
            or type(payload["candidate_ids"]) is not list
            or type(payload["candidate_count"]) is not int
        ):
            raise StableModelReviewPacketError("stable model review shard schema is invalid")
        result = cls(
            source_sha=cast("str", payload["source_sha"]),
            topological_depth=cast("int", payload["topological_depth"]),
            shard_ordinal=cast("int", payload["shard_ordinal"]),
            candidate_source_authority_sha256=cast(
                "str", payload["candidate_source_authority_sha256"]
            ),
            candidate_census_canonical_bytes_sha256=cast(
                "str", payload["candidate_census_canonical_bytes_sha256"]
            ),
            candidate_inventory_sha256=cast("str", payload["candidate_inventory_sha256"]),
            disposition_draft_inventory_sha256=cast(
                "str", payload["disposition_draft_inventory_sha256"]
            ),
            review_input_inventory_sha256=cast("str", payload["review_input_inventory_sha256"]),
            result_slots=tuple(
                StableModelReviewResultSlotV1.from_dict(item)
                for item in cast("list[object]", payload["result_slots"])
            ),
            external_challenge_kind=cast("str", payload["external_challenge_kind"]),
        )
        if payload != result.to_dict():
            raise StableModelReviewPacketError(
                "stable model review shard differs from exact reconstruction"
            )
        return result

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(
            _decode_json(
                raw,
                label="stable model review shard",
                maximum_bytes=_MAX_SHARD_BYTES,
                require_canonical=True,
            )
        )


@dataclass(frozen=True, slots=True)
class StableModelReviewChallengeV1:
    """A hash-bound challenge for one later GitHub pull-request review."""

    source_sha: str
    work_packet_sha256: str
    shard_id: str
    shard_sha256: str
    candidate_id_inventory_sha256: str
    result_slot_inventory_sha256: str
    candidate_count: int
    challenge_state: ReviewChallengeState = "awaiting_github_pull_request_review"
    authority_admitted: Literal[False] = False

    schema_version: ClassVar[int] = STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION
    kind: ClassVar[str] = GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND

    def __post_init__(self) -> None:
        _require_git_sha(self.source_sha)
        _require_id(self.shard_id, field_name="challenge shard_id")
        for field_name in (
            "work_packet_sha256",
            "shard_sha256",
            "candidate_id_inventory_sha256",
            "result_slot_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_int(
            self.candidate_count,
            field_name="challenge candidate_count",
            minimum=1,
            maximum=STABLE_MODEL_REVIEW_MAX_SHARD_SIZE,
        )
        if self.challenge_state != "awaiting_github_pull_request_review":
            raise StableModelReviewPacketError("review challenge state is unsupported")
        if type(self.authority_admitted) is not bool or self.authority_admitted:
            raise StableModelReviewPacketError("review work challenge cannot admit authority")

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "work_packet_sha256": self.work_packet_sha256,
            "shard_id": self.shard_id,
            "shard_sha256": self.shard_sha256,
            "candidate_id_inventory_sha256": self.candidate_id_inventory_sha256,
            "result_slot_inventory_sha256": self.result_slot_inventory_sha256,
            "candidate_count": self.candidate_count,
            "challenge_state": self.challenge_state,
            "authority_admitted": self.authority_admitted,
        }

    @property
    def challenge_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "challenge_sha256": _sha256(content)}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="stable model review challenge")
        fields = frozenset(
            {
                "source_sha",
                "work_packet_sha256",
                "shard_id",
                "shard_sha256",
                "candidate_id_inventory_sha256",
                "result_slot_inventory_sha256",
                "candidate_count",
                "challenge_state",
                "authority_admitted",
                "challenge_sha256",
            }
        )
        _require_exact_keys(
            payload,
            expected=frozenset({"schema_version", "kind", *fields}),
            label="stable model review challenge",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(payload["candidate_count"]) is not int
            or type(payload["authority_admitted"]) is not bool
        ):
            raise StableModelReviewPacketError("stable model review challenge schema is invalid")
        result = cls(
            source_sha=cast("str", payload["source_sha"]),
            work_packet_sha256=cast("str", payload["work_packet_sha256"]),
            shard_id=cast("str", payload["shard_id"]),
            shard_sha256=cast("str", payload["shard_sha256"]),
            candidate_id_inventory_sha256=cast("str", payload["candidate_id_inventory_sha256"]),
            result_slot_inventory_sha256=cast("str", payload["result_slot_inventory_sha256"]),
            candidate_count=payload["candidate_count"],
            challenge_state=cast("ReviewChallengeState", payload["challenge_state"]),
            authority_admitted=cast("Literal[False]", payload["authority_admitted"]),
        )
        if payload != result.to_dict():
            raise StableModelReviewPacketError(
                "stable model review challenge differs from exact reconstruction"
            )
        return result

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(
            _decode_json(
                raw,
                label="stable model review challenge",
                maximum_bytes=_MAX_CHALLENGE_BYTES,
                require_canonical=True,
            )
        )


def _review_input_payload(
    *,
    candidate_source_authority_sha256: str,
    candidate: StableModelCandidateV1,
    evidence: ModelCandidateCensusEvidenceV1,
    draft: StableModelDispositionV1,
) -> dict[str, object]:
    return {
        "schema_version": STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION,
        "kind": "stable_model_candidate_review_input_v1",
        "candidate_source_authority_sha256": candidate_source_authority_sha256,
        "candidate": candidate.to_dict(),
        "evidence": evidence.to_dict(),
        "disposition_draft": draft.to_dict(),
    }


def _parse_review_input(
    value: StableModelReviewContentV1,
) -> tuple[
    StableModelCandidateV1,
    ModelCandidateCensusEvidenceV1,
    StableModelDispositionV1,
    str,
]:
    if value.content_kind != "candidate_review_input":
        raise StableModelReviewPacketError("candidate review input has a foreign content kind")
    payload = _require_mapping(value.content, label="candidate review input")
    _require_exact_keys(
        payload,
        expected=frozenset(
            {
                "schema_version",
                "kind",
                "candidate_source_authority_sha256",
                "candidate",
                "evidence",
                "disposition_draft",
            }
        ),
        label="candidate review input",
    )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION
        or payload["kind"] != "stable_model_candidate_review_input_v1"
    ):
        raise StableModelReviewPacketError("candidate review input schema is invalid")
    candidate = StableModelCandidateV1.from_dict(payload["candidate"])
    evidence = ModelCandidateCensusEvidenceV1.from_dict(payload["evidence"])
    draft = StableModelDispositionV1.from_dict(payload["disposition_draft"])
    if value.subject_id != candidate.candidate_id:
        raise StableModelReviewPacketError("candidate review input subject is rebound")
    if (
        evidence.candidate_id != candidate.candidate_id
        or draft.candidate_id != candidate.candidate_id
    ):
        raise StableModelReviewPacketError("candidate review input rows name different candidates")
    return (
        candidate,
        evidence,
        draft,
        _require_sha256(
            payload["candidate_source_authority_sha256"],
            field_name="candidate_source_authority_sha256",
        ),
    )


def _required_review_inputs(
    *,
    candidate_census_sha256: str,
    census_content_sha256: str,
    candidate_source_authority_sha256: str,
    candidate_inventory_sha256: str,
    candidate_sha256: str,
    candidate_structural_sha256: str,
    candidate_evidence_sha256s: tuple[str, ...],
    draft_semantic_sha256: str,
    pending_review_identity_sha256: str,
    draft_reason_evidence_sha256s: tuple[str, ...],
    review_input_sha256: str,
    disposition_draft_inventory_sha256: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                candidate_census_sha256,
                census_content_sha256,
                candidate_source_authority_sha256,
                candidate_inventory_sha256,
                disposition_draft_inventory_sha256,
                candidate_sha256,
                candidate_structural_sha256,
                draft_semantic_sha256,
                pending_review_identity_sha256,
                review_input_sha256,
                *candidate_evidence_sha256s,
                *draft_reason_evidence_sha256s,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class StableModelReviewPacketV1:
    """Exact 1,128-candidate, 22-shard red review work packet."""

    source_sha: str
    candidate_census_input: StableModelReviewContentV1
    review_inputs: tuple[StableModelReviewContentV1, ...]
    shards: tuple[StableModelReviewShardV1, ...]
    candidate_source_authority_sha256: str
    candidate_census_sha256: str
    candidate_census_canonical_bytes_sha256: str
    candidate_inventory_sha256: str
    disposition_draft_inventory_sha256: str
    review_input_inventory_sha256: str
    topological_depth_counts: tuple[int, ...] = _EXPECTED_DEPTH_COUNTS
    shard_depth_counts: tuple[int, ...] = _EXPECTED_SHARD_COUNTS
    max_shard_candidate_count: int = STABLE_MODEL_REVIEW_MAX_SHARD_SIZE
    external_challenge_kind: str = GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND
    work_state: ReviewWorkState = _PENDING_REVIEW_STATE
    authority_admitted: Literal[False] = False
    review_gate_green: Literal[False] = False

    schema_version: ClassVar[int] = STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION
    kind: ClassVar[str] = STABLE_MODEL_REVIEW_PACKET_KIND

    def __post_init__(self) -> None:
        _require_git_sha(self.source_sha)
        for field_name in (
            "candidate_source_authority_sha256",
            "candidate_census_sha256",
            "candidate_census_canonical_bytes_sha256",
            "candidate_inventory_sha256",
            "disposition_draft_inventory_sha256",
            "review_input_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if type(self.candidate_census_input) is not StableModelReviewContentV1:
            raise StableModelReviewPacketError("candidate census input has a foreign type")
        if (
            self.candidate_census_input.content_kind != "candidate_census"
            or self.candidate_census_input.subject_id != "census"
            or self.candidate_census_input.content_sha256
            != self.candidate_census_canonical_bytes_sha256
        ):
            raise StableModelReviewPacketError("candidate census content binding differs")
        census = ModelCandidateCensusV1.from_canonical_bytes(
            self.candidate_census_input.canonical_json.encode("utf-8")
        )
        if (
            census.census_sha256 != self.candidate_census_sha256
            or census.candidate_source_authority_sha256 != self.candidate_source_authority_sha256
            or census.candidate_inventory_sha256 != self.candidate_inventory_sha256
            or len(census.candidates) != STABLE_MODEL_REVIEW_CANDIDATE_COUNT
        ):
            raise StableModelReviewPacketError("candidate census authority is stale or incomplete")
        if type(self.review_inputs) is not tuple or any(
            type(item) is not StableModelReviewContentV1 for item in self.review_inputs
        ):
            raise StableModelReviewPacketError("review inputs must be an exact typed tuple")
        if len(self.review_inputs) != STABLE_MODEL_REVIEW_CANDIDATE_COUNT:
            raise StableModelReviewPacketError("review input denominator is not exactly 1,128")
        if self.review_inputs != tuple(
            sorted(self.review_inputs, key=lambda item: item.subject_id)
        ) or len({item.subject_id for item in self.review_inputs}) != len(self.review_inputs):
            raise StableModelReviewPacketError("review inputs are duplicated or unsorted")
        if any(item.content_kind != "candidate_review_input" for item in self.review_inputs):
            raise StableModelReviewPacketError("review input inventory contains a foreign kind")
        input_root = _sha256([item.to_dict() for item in self.review_inputs])
        if input_root != self.review_input_inventory_sha256:
            raise StableModelReviewPacketError("review input inventory digest differs")

        candidates_by_id = {item.candidate_id: item for item in census.candidates}
        evidence_by_id = {item.candidate_id: item for item in census.evidence}
        parsed_inputs: dict[
            str,
            tuple[
                StableModelCandidateV1,
                ModelCandidateCensusEvidenceV1,
                StableModelDispositionV1,
            ],
        ] = {}
        for content in self.review_inputs:
            candidate, evidence, draft, source_authority_sha256 = _parse_review_input(content)
            if (
                candidate != candidates_by_id.get(candidate.candidate_id)
                or evidence != evidence_by_id.get(candidate.candidate_id)
                or source_authority_sha256 != self.candidate_source_authority_sha256
            ):
                raise StableModelReviewPacketError(
                    "candidate review input is stale or foreign to the exact census"
                )
            parsed_inputs[candidate.candidate_id] = (candidate, evidence, draft)
        if set(parsed_inputs) != set(candidates_by_id):
            raise StableModelReviewPacketError("review input candidate union is incomplete")

        expected_drafts = draft_required_model_dispositions(
            candidate_source_authority_sha256=self.candidate_source_authority_sha256,
            candidates=census.candidates,
        )
        drafts = tuple(parsed_inputs[item.candidate_id][2] for item in census.candidates)
        if drafts != expected_drafts:
            raise StableModelReviewPacketError(
                "review packet dispositions differ from exact requirement-preserving drafts"
            )
        if _sha256([item.to_dict() for item in drafts]) != (
            self.disposition_draft_inventory_sha256
        ):
            raise StableModelReviewPacketError("disposition draft inventory digest differs")

        depths = _compute_topological_depths(census.candidates)
        depth_counts = tuple(
            Counter(depths.values()).get(depth, 0) for depth in range(len(_EXPECTED_DEPTH_COUNTS))
        )
        if (
            set(depths.values()) != set(range(len(_EXPECTED_DEPTH_COUNTS)))
            or depth_counts != _EXPECTED_DEPTH_COUNTS
            or self.topological_depth_counts != _EXPECTED_DEPTH_COUNTS
            or self.shard_depth_counts != _EXPECTED_SHARD_COUNTS
            or self.max_shard_candidate_count != STABLE_MODEL_REVIEW_MAX_SHARD_SIZE
        ):
            raise StableModelReviewPacketError(
                "review packet topological denominator differs from exact current census"
            )
        if self.external_challenge_kind != GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND:
            raise StableModelReviewPacketError("review packet external challenge kind is foreign")
        if self.work_state != _PENDING_REVIEW_STATE:
            raise StableModelReviewPacketError("review packet is not pending external review")
        if (
            type(self.authority_admitted) is not bool
            or self.authority_admitted
            or type(self.review_gate_green) is not bool
            or self.review_gate_green
        ):
            raise StableModelReviewPacketError("red review work cannot admit or green authority")

        if (
            type(self.shards) is not tuple
            or len(self.shards) != STABLE_MODEL_REVIEW_SHARD_COUNT
            or any(type(item) is not StableModelReviewShardV1 for item in self.shards)
        ):
            raise StableModelReviewPacketError("review shard inventory is not exactly 22")
        if self.shards != tuple(
            sorted(self.shards, key=lambda item: (item.topological_depth, item.shard_ordinal))
        ) or len({item.shard_id for item in self.shards}) != len(self.shards):
            raise StableModelReviewPacketError("review shards are duplicated or unsorted")
        roots = (
            self.source_sha,
            self.candidate_source_authority_sha256,
            self.candidate_census_canonical_bytes_sha256,
            self.candidate_inventory_sha256,
            self.disposition_draft_inventory_sha256,
            self.review_input_inventory_sha256,
        )
        if any(
            (
                shard.source_sha,
                shard.candidate_source_authority_sha256,
                shard.candidate_census_canonical_bytes_sha256,
                shard.candidate_inventory_sha256,
                shard.disposition_draft_inventory_sha256,
                shard.review_input_inventory_sha256,
            )
            != roots
            for shard in self.shards
        ):
            raise StableModelReviewPacketError("review shard is stale or foreign to the packet")

        slots_by_id: dict[str, StableModelReviewResultSlotV1] = {}
        shards_by_depth: dict[int, list[StableModelReviewShardV1]] = {}
        for shard in self.shards:
            shards_by_depth.setdefault(shard.topological_depth, []).append(shard)
            for slot in shard.result_slots:
                if slot.candidate_id in slots_by_id:
                    raise StableModelReviewPacketError(
                        "candidate appears in more than one review shard"
                    )
                slots_by_id[slot.candidate_id] = slot
        if set(slots_by_id) != set(candidates_by_id):
            raise StableModelReviewPacketError(
                "review shard union does not cover the exact 1,128 candidates"
            )

        inputs_by_id = {item.subject_id: item for item in self.review_inputs}
        drafts_by_id = {item.candidate_id: item for item in expected_drafts}
        candidate_census_sha256 = census.census_sha256
        for candidate_id, candidate in candidates_by_id.items():
            draft = drafts_by_id[candidate_id]
            review_input = inputs_by_id[candidate_id]
            expected_inputs = _required_review_inputs(
                candidate_census_sha256=candidate_census_sha256,
                census_content_sha256=self.candidate_census_canonical_bytes_sha256,
                candidate_source_authority_sha256=self.candidate_source_authority_sha256,
                candidate_inventory_sha256=self.candidate_inventory_sha256,
                candidate_sha256=candidate.candidate_sha256,
                candidate_structural_sha256=candidate.structural_sha256,
                candidate_evidence_sha256s=candidate.evidence_sha256s,
                draft_semantic_sha256=draft.semantic_sha256,
                pending_review_identity_sha256=draft.review_receipt_sha256,
                draft_reason_evidence_sha256s=draft.reason_evidence_sha256s,
                review_input_sha256=review_input.content_sha256,
                disposition_draft_inventory_sha256=(self.disposition_draft_inventory_sha256),
            )
            slot = slots_by_id[candidate_id]
            if (
                slot.topological_depth != depths[candidate_id]
                or slot.candidate_sha256 != candidate.candidate_sha256
                or slot.candidate_structural_sha256 != candidate.structural_sha256
                or slot.draft_semantic_sha256 != draft.semantic_sha256
                or slot.pending_review_identity_sha256 != draft.review_receipt_sha256
                or slot.review_input_sha256 != review_input.content_sha256
                or slot.required_review_input_sha256s != expected_inputs
            ):
                raise StableModelReviewPacketError(
                    f"review result slot is stale or foreign: {candidate_id}"
                )

        for depth, expected_shard_count in enumerate(_EXPECTED_SHARD_COUNTS):
            depth_ids = tuple(
                sorted(candidate_id for candidate_id, value in depths.items() if value == depth)
            )
            expected_chunks = tuple(
                depth_ids[index : index + STABLE_MODEL_REVIEW_MAX_SHARD_SIZE]
                for index in range(0, len(depth_ids), STABLE_MODEL_REVIEW_MAX_SHARD_SIZE)
            )
            observed_shards = tuple(shards_by_depth.get(depth, ()))
            if (
                len(observed_shards) != expected_shard_count
                or tuple(item.shard_ordinal for item in observed_shards)
                != tuple(range(expected_shard_count))
                or tuple(item.candidate_ids for item in observed_shards) != expected_chunks
            ):
                raise StableModelReviewPacketError(
                    f"review shards do not match exact deterministic depth partition: {depth}"
                )

    @property
    def candidate_count(self) -> int:
        return len(self.review_inputs)

    @property
    def shard_count(self) -> int:
        return len(self.shards)

    @property
    def review_result_slot_inventory_sha256(self) -> str:
        return _sha256([slot.to_dict() for shard in self.shards for slot in shard.result_slots])

    @property
    def shard_inventory_sha256(self) -> str:
        return _sha256([item.to_dict() for item in self.shards])

    def _content_dict(self) -> dict[str, object]:
        review_inputs = [item.to_dict() for item in self.review_inputs]
        shards = [item.to_dict() for item in self.shards]
        result_slots = [slot.to_dict() for shard in self.shards for slot in shard.result_slots]
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "candidate_source_authority_sha256": self.candidate_source_authority_sha256,
            "candidate_census_sha256": self.candidate_census_sha256,
            "candidate_census_canonical_bytes_sha256": (
                self.candidate_census_canonical_bytes_sha256
            ),
            "candidate_inventory_sha256": self.candidate_inventory_sha256,
            "disposition_draft_inventory_sha256": (self.disposition_draft_inventory_sha256),
            "review_input_inventory_sha256": self.review_input_inventory_sha256,
            "review_result_slot_inventory_sha256": _sha256(result_slots),
            "shard_inventory_sha256": _sha256(shards),
            "candidate_count": self.candidate_count,
            "review_input_count": len(self.review_inputs),
            "review_result_slot_count": sum(len(item.result_slots) for item in self.shards),
            "shard_count": self.shard_count,
            "topological_depth_counts": list(self.topological_depth_counts),
            "shard_depth_counts": list(self.shard_depth_counts),
            "max_shard_candidate_count": self.max_shard_candidate_count,
            "external_challenge_kind": self.external_challenge_kind,
            "work_state": self.work_state,
            "authority_admitted": self.authority_admitted,
            "review_gate_green": self.review_gate_green,
            "candidate_census_input": self.candidate_census_input.to_dict(),
            "review_inputs": review_inputs,
            "shards": shards,
        }

    @property
    def work_packet_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        content = self._content_dict()
        return {**content, "work_packet_sha256": _sha256(content)}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @property
    def challenges(self) -> tuple[StableModelReviewChallengeV1, ...]:
        """Derive one red-only external challenge per exact review shard."""

        work_packet_sha256 = self.work_packet_sha256
        challenges: list[StableModelReviewChallengeV1] = []
        for shard in self.shards:
            shard_content = shard._content_dict()
            challenges.append(
                StableModelReviewChallengeV1(
                    source_sha=self.source_sha,
                    work_packet_sha256=work_packet_sha256,
                    shard_id=shard.shard_id,
                    shard_sha256=_sha256(shard_content),
                    candidate_id_inventory_sha256=cast(
                        "str", shard_content["candidate_id_inventory_sha256"]
                    ),
                    result_slot_inventory_sha256=cast(
                        "str", shard_content["result_slot_inventory_sha256"]
                    ),
                    candidate_count=len(shard.result_slots),
                )
            )
        return tuple(challenges)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        raw = _canonical_bytes(value)
        if len(raw) > _MAX_PACKET_BYTES:
            raise StableModelReviewPacketError("stable model review packet exceeds byte bound")
        payload = _require_mapping(value, label="stable model review packet")
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "source_sha",
                "candidate_source_authority_sha256",
                "candidate_census_sha256",
                "candidate_census_canonical_bytes_sha256",
                "candidate_inventory_sha256",
                "disposition_draft_inventory_sha256",
                "review_input_inventory_sha256",
                "review_result_slot_inventory_sha256",
                "shard_inventory_sha256",
                "candidate_count",
                "review_input_count",
                "review_result_slot_count",
                "shard_count",
                "topological_depth_counts",
                "shard_depth_counts",
                "max_shard_candidate_count",
                "external_challenge_kind",
                "work_state",
                "authority_admitted",
                "review_gate_green",
                "candidate_census_input",
                "review_inputs",
                "shards",
                "work_packet_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="stable model review packet")
        array_fields = (
            "topological_depth_counts",
            "shard_depth_counts",
            "review_inputs",
            "shards",
        )
        integer_fields = (
            "candidate_count",
            "review_input_count",
            "review_result_slot_count",
            "shard_count",
            "max_shard_candidate_count",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or any(type(payload[field]) is not list for field in array_fields)
            or any(type(payload[field]) is not int for field in integer_fields)
            or type(payload["authority_admitted"]) is not bool
            or type(payload["review_gate_green"]) is not bool
        ):
            raise StableModelReviewPacketError("stable model review packet schema is invalid")
        result = cls(
            source_sha=cast("str", payload["source_sha"]),
            candidate_census_input=StableModelReviewContentV1.from_dict(
                payload["candidate_census_input"]
            ),
            review_inputs=tuple(
                StableModelReviewContentV1.from_dict(item)
                for item in cast("list[object]", payload["review_inputs"])
            ),
            shards=tuple(
                StableModelReviewShardV1.from_dict(item)
                for item in cast("list[object]", payload["shards"])
            ),
            candidate_source_authority_sha256=cast(
                "str", payload["candidate_source_authority_sha256"]
            ),
            candidate_census_sha256=cast("str", payload["candidate_census_sha256"]),
            candidate_census_canonical_bytes_sha256=cast(
                "str", payload["candidate_census_canonical_bytes_sha256"]
            ),
            candidate_inventory_sha256=cast("str", payload["candidate_inventory_sha256"]),
            disposition_draft_inventory_sha256=cast(
                "str", payload["disposition_draft_inventory_sha256"]
            ),
            review_input_inventory_sha256=cast("str", payload["review_input_inventory_sha256"]),
            topological_depth_counts=tuple(cast("list[int]", payload["topological_depth_counts"])),
            shard_depth_counts=tuple(cast("list[int]", payload["shard_depth_counts"])),
            max_shard_candidate_count=cast("int", payload["max_shard_candidate_count"]),
            external_challenge_kind=cast("str", payload["external_challenge_kind"]),
            work_state=cast("ReviewWorkState", payload["work_state"]),
            authority_admitted=cast("Literal[False]", payload["authority_admitted"]),
            review_gate_green=cast("Literal[False]", payload["review_gate_green"]),
        )
        if payload != result.to_dict():
            raise StableModelReviewPacketError(
                "stable model review packet differs from exact reconstruction"
            )
        return result

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(
            _decode_json(
                raw,
                label="stable model review packet",
                maximum_bytes=_MAX_PACKET_BYTES,
                require_canonical=True,
            )
        )


def compile_stable_model_review_packet(
    *,
    source_sha: str,
    census: ModelCandidateCensusV1,
    disposition_drafts: Sequence[StableModelDispositionV1],
) -> StableModelReviewPacketV1:
    """Compile exact red review work from one typed census and its exact drafts."""

    _require_git_sha(source_sha)
    if type(census) is not ModelCandidateCensusV1:
        raise StableModelReviewPacketError("review packet census has a foreign type")
    checked_census = ModelCandidateCensusV1.from_canonical_bytes(census.canonical_bytes)
    if checked_census != census:
        raise StableModelReviewPacketError("review packet census failed exact readback")
    drafts = tuple(disposition_drafts)
    if any(type(item) is not StableModelDispositionV1 for item in drafts):
        raise StableModelReviewPacketError("disposition drafts contain a foreign row")
    expected_drafts = draft_required_model_dispositions(
        candidate_source_authority_sha256=checked_census.candidate_source_authority_sha256,
        candidates=checked_census.candidates,
    )
    if drafts != expected_drafts:
        raise StableModelReviewPacketError(
            "disposition drafts differ from exact requirement-preserving compilation"
        )
    if len(checked_census.candidates) != STABLE_MODEL_REVIEW_CANDIDATE_COUNT:
        raise StableModelReviewPacketError("current review denominator is not exactly 1,128")

    census_content = StableModelReviewContentV1(
        content_kind="candidate_census",
        subject_id="census",
        canonical_json=checked_census.canonical_bytes.decode("utf-8"),
    )
    evidence_by_id = {item.candidate_id: item for item in checked_census.evidence}
    drafts_by_id = {item.candidate_id: item for item in drafts}
    review_inputs = tuple(
        StableModelReviewContentV1(
            content_kind="candidate_review_input",
            subject_id=candidate.candidate_id,
            canonical_json=_canonical_text(
                _review_input_payload(
                    candidate_source_authority_sha256=(
                        checked_census.candidate_source_authority_sha256
                    ),
                    candidate=candidate,
                    evidence=evidence_by_id[candidate.candidate_id],
                    draft=drafts_by_id[candidate.candidate_id],
                )
            ),
        )
        for candidate in checked_census.candidates
    )
    draft_root = _sha256([item.to_dict() for item in drafts])
    input_root = _sha256([item.to_dict() for item in review_inputs])
    depths = _compute_topological_depths(checked_census.candidates)
    inputs_by_id = {item.subject_id: item for item in review_inputs}
    candidate_census_sha256 = checked_census.census_sha256
    candidate_source_authority_sha256 = checked_census.candidate_source_authority_sha256
    candidate_inventory_sha256 = checked_census.candidate_inventory_sha256
    slots_by_id = {
        candidate.candidate_id: StableModelReviewResultSlotV1(
            candidate_id=candidate.candidate_id,
            topological_depth=depths[candidate.candidate_id],
            candidate_sha256=candidate.candidate_sha256,
            candidate_structural_sha256=candidate.structural_sha256,
            draft_semantic_sha256=drafts_by_id[candidate.candidate_id].semantic_sha256,
            pending_review_identity_sha256=(
                drafts_by_id[candidate.candidate_id].review_receipt_sha256
            ),
            review_input_sha256=inputs_by_id[candidate.candidate_id].content_sha256,
            required_review_input_sha256s=_required_review_inputs(
                candidate_census_sha256=candidate_census_sha256,
                census_content_sha256=census_content.content_sha256,
                candidate_source_authority_sha256=candidate_source_authority_sha256,
                candidate_inventory_sha256=candidate_inventory_sha256,
                candidate_sha256=candidate.candidate_sha256,
                candidate_structural_sha256=candidate.structural_sha256,
                candidate_evidence_sha256s=candidate.evidence_sha256s,
                draft_semantic_sha256=drafts_by_id[candidate.candidate_id].semantic_sha256,
                pending_review_identity_sha256=(
                    drafts_by_id[candidate.candidate_id].review_receipt_sha256
                ),
                draft_reason_evidence_sha256s=(
                    drafts_by_id[candidate.candidate_id].reason_evidence_sha256s
                ),
                review_input_sha256=inputs_by_id[candidate.candidate_id].content_sha256,
                disposition_draft_inventory_sha256=draft_root,
            ),
        )
        for candidate in checked_census.candidates
    }
    shards: list[StableModelReviewShardV1] = []
    for depth in range(len(_EXPECTED_DEPTH_COUNTS)):
        candidate_ids = tuple(
            sorted(candidate_id for candidate_id, value in depths.items() if value == depth)
        )
        for ordinal, start in enumerate(
            range(0, len(candidate_ids), STABLE_MODEL_REVIEW_MAX_SHARD_SIZE)
        ):
            shard_ids = candidate_ids[start : start + STABLE_MODEL_REVIEW_MAX_SHARD_SIZE]
            shards.append(
                StableModelReviewShardV1(
                    source_sha=source_sha,
                    topological_depth=depth,
                    shard_ordinal=ordinal,
                    candidate_source_authority_sha256=candidate_source_authority_sha256,
                    candidate_census_canonical_bytes_sha256=census_content.content_sha256,
                    candidate_inventory_sha256=candidate_inventory_sha256,
                    disposition_draft_inventory_sha256=draft_root,
                    review_input_inventory_sha256=input_root,
                    result_slots=tuple(slots_by_id[candidate_id] for candidate_id in shard_ids),
                )
            )
    return StableModelReviewPacketV1(
        source_sha=source_sha,
        candidate_census_input=census_content,
        review_inputs=review_inputs,
        shards=tuple(shards),
        candidate_source_authority_sha256=candidate_source_authority_sha256,
        candidate_census_sha256=candidate_census_sha256,
        candidate_census_canonical_bytes_sha256=census_content.content_sha256,
        candidate_inventory_sha256=candidate_inventory_sha256,
        disposition_draft_inventory_sha256=draft_root,
        review_input_inventory_sha256=input_root,
    )


def compile_current_stable_model_review_packet(
    *,
    source_sha: str,
    upstream_root: str | None = None,
) -> StableModelReviewPacketV1:
    """Recompute the exact current census and emit its red-only review packet."""

    census = compile_current_model_candidate_census(
        analytical_needs=canonical_analytical_needs_authority_v1(),
        upstream_root=upstream_root,
    )
    drafts = draft_required_model_dispositions(
        candidate_source_authority_sha256=census.candidate_source_authority_sha256,
        candidates=census.candidates,
    )
    return compile_stable_model_review_packet(
        source_sha=source_sha,
        census=census,
        disposition_drafts=drafts,
    )
