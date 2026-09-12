"""Reviewed disposition authority for the complete stable-model candidate census.

Candidate discovery is intentionally external to this module.  The compiler
accepts a digest-bound candidate inventory and authored decisions, preserves
missing decisions and reviews as blockers, and refuses stale or foreign rows.
Runtime model registration is therefore evidence, never the expected set.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from nbadb.contracts.review_evidence import ReviewReceiptV1

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "STABLE_MODEL_DISPOSITION_KIND",
    "STABLE_MODEL_DISPOSITION_SCHEMA_VERSION",
    "ImplementationStatus",
    "ModelGateRequirement",
    "ModelCandidateKind",
    "ModelDisposition",
    "ModelDispositionBlockerV1",
    "StableModelCandidateV1",
    "StableModelDispositionError",
    "StableModelDispositionInventoryV1",
    "StableModelDispositionV1",
    "compile_stable_model_disposition_inventory",
    "draft_required_model_dispositions",
]

STABLE_MODEL_DISPOSITION_SCHEMA_VERSION = 1
STABLE_MODEL_DISPOSITION_KIND = "nbadb_stable_model_disposition_inventory"

type ModelCandidateKind = Literal[
    "source",
    "staging",
    "dimension",
    "fact",
    "bridge",
    "aggregate",
    "analytics",
    "live",
    "experimental_model",
]
type ModelDisposition = Literal["stable", "experimental", "withheld", "rejected"]
type ImplementationStatus = Literal["implemented", "missing", "not_applicable"]
type ModelGateRequirement = Literal[
    "lossless_required",
    "stable_required",
    "optional_candidate",
    "experimental_only",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_CANDIDATE_KINDS = frozenset(
    {
        "source",
        "staging",
        "dimension",
        "fact",
        "bridge",
        "aggregate",
        "analytics",
        "live",
        "experimental_model",
    }
)
_PUBLIC_STABLE_KINDS = _CANDIDATE_KINDS - {"experimental_model"}
_DISPOSITIONS = frozenset({"stable", "experimental", "withheld", "rejected"})
_IMPLEMENTATION_STATUSES = frozenset({"implemented", "missing", "not_applicable"})
_GATE_REQUIREMENTS = frozenset(
    {"lossless_required", "stable_required", "optional_candidate", "experimental_only"}
)
_CANDIDATE_KIND_LAYER = {
    "source": 0,
    "staging": 1,
    "dimension": 2,
    "fact": 2,
    "bridge": 2,
    "live": 2,
    "aggregate": 3,
    "analytics": 4,
    "experimental_model": 5,
}


class StableModelDispositionError(ValueError):
    """A model candidate, reviewed decision, or inventory is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StableModelDispositionError("model disposition is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise StableModelDispositionError(f"{field} must be a lowercase SHA-256")
    return value


def _require_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise StableModelDispositionError(f"{field} must be a safe nonempty identifier")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    if any(not isinstance(key, str) for key in payload):
        raise StableModelDispositionError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = ",".join(sorted(expected - actual))
    unexpected = ",".join(sorted(actual - expected))
    raise StableModelDispositionError(
        f"{label} fields differ (missing={missing}; unexpected={unexpected})"
    )


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise StableModelDispositionError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _tuple_ids(value: object, *, field: str, allow_empty: bool = True) -> tuple[str, ...]:
    if type(value) is not list:
        raise StableModelDispositionError(f"{field} must be an array")
    values = tuple(_require_id(item, field=field) for item in cast("Sequence[object]", value))
    if (not values and not allow_empty) or values != tuple(sorted(set(values))):
        raise StableModelDispositionError(f"{field} must be sorted and unique")
    return values


def _tuple_sha256s(value: object, *, field: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise StableModelDispositionError(f"{field} must be an array")
    values = tuple(_require_sha256(item, field=field) for item in cast("Sequence[object]", value))
    if not values or values != tuple(sorted(set(values))):
        raise StableModelDispositionError(f"{field} must be nonempty, sorted, and unique")
    return values


def _decode_canonical_bytes(raw: bytes) -> Mapping[str, object]:
    if not isinstance(raw, bytes) or not raw:
        raise StableModelDispositionError("model disposition bytes must be nonempty")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise StableModelDispositionError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise StableModelDispositionError(f"non-finite JSON constant: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StableModelDispositionError("model disposition bytes are invalid JSON") from exc
    payload = _require_mapping(value, label="model disposition inventory")
    if _canonical_bytes(payload) != raw:
        raise StableModelDispositionError("model disposition bytes are not canonical")
    return payload


@dataclass(frozen=True, slots=True, order=True)
class StableModelCandidateV1:
    """One independently discovered source, table, composition, or model candidate."""

    candidate_id: str
    candidate_kind: ModelCandidateKind
    gate_requirement: ModelGateRequirement
    structural_sha256: str
    dependency_ids: tuple[str, ...]
    evidence_sha256s: tuple[str, ...]
    implementation_status: ImplementationStatus
    implementation_sha256: str | None

    def __post_init__(self) -> None:
        _require_id(self.candidate_id, field="candidate_id")
        if self.candidate_kind not in _CANDIDATE_KINDS:
            raise StableModelDispositionError("candidate_kind is invalid")
        if self.gate_requirement not in _GATE_REQUIREMENTS:
            raise StableModelDispositionError("gate_requirement is invalid")
        if self.candidate_kind in {"source", "staging"} and self.gate_requirement != (
            "lossless_required"
        ):
            raise StableModelDispositionError(
                "source and staging candidates must be lossless_required"
            )
        if self.candidate_kind == "experimental_model" and self.gate_requirement != (
            "experimental_only"
        ):
            raise StableModelDispositionError(
                "experimental_model candidates must be experimental_only"
            )
        if self.candidate_kind != "experimental_model" and self.gate_requirement == (
            "experimental_only"
        ):
            raise StableModelDispositionError(
                "experimental_only candidates must use experimental_model kind"
            )
        _require_sha256(self.structural_sha256, field="candidate structural_sha256")
        if self.dependency_ids != tuple(sorted(set(self.dependency_ids))):
            raise StableModelDispositionError("dependency_ids must be sorted and unique")
        for dependency_id in self.dependency_ids:
            _require_id(dependency_id, field="dependency_ids")
        if self.candidate_id in self.dependency_ids:
            raise StableModelDispositionError("candidate cannot depend on itself")
        if not self.evidence_sha256s or self.evidence_sha256s != tuple(
            sorted(set(self.evidence_sha256s))
        ):
            raise StableModelDispositionError(
                "candidate evidence_sha256s must be nonempty, sorted, and unique"
            )
        for digest in self.evidence_sha256s:
            _require_sha256(digest, field="candidate evidence_sha256s")
        if self.implementation_status not in _IMPLEMENTATION_STATUSES:
            raise StableModelDispositionError("implementation_status is invalid")
        if self.implementation_status == "implemented":
            _require_sha256(self.implementation_sha256, field="implementation_sha256")
        elif self.implementation_sha256 is not None:
            raise StableModelDispositionError(
                "nonimplemented candidate cannot carry implementation_sha256"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_kind": self.candidate_kind,
            "gate_requirement": self.gate_requirement,
            "structural_sha256": self.structural_sha256,
            "dependency_ids": list(self.dependency_ids),
            "evidence_sha256s": list(self.evidence_sha256s),
            "implementation_status": self.implementation_status,
            "implementation_sha256": self.implementation_sha256,
        }

    @property
    def candidate_sha256(self) -> str:
        return _sha256(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="stable model candidate")
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "candidate_id",
                    "candidate_kind",
                    "gate_requirement",
                    "structural_sha256",
                    "dependency_ids",
                    "evidence_sha256s",
                    "implementation_status",
                    "implementation_sha256",
                }
            ),
            label="stable model candidate",
        )
        implementation_sha256 = payload["implementation_sha256"]
        if implementation_sha256 is not None and not isinstance(implementation_sha256, str):
            raise StableModelDispositionError("implementation_sha256 must be null or a string")
        return cls(
            candidate_id=cast("str", payload["candidate_id"]),
            candidate_kind=cast("ModelCandidateKind", payload["candidate_kind"]),
            gate_requirement=cast("ModelGateRequirement", payload["gate_requirement"]),
            structural_sha256=cast("str", payload["structural_sha256"]),
            dependency_ids=_tuple_ids(payload["dependency_ids"], field="dependency_ids"),
            evidence_sha256s=_tuple_sha256s(
                payload["evidence_sha256s"], field="candidate evidence_sha256s"
            ),
            implementation_status=cast("ImplementationStatus", payload["implementation_status"]),
            implementation_sha256=implementation_sha256,
        )


@dataclass(frozen=True, slots=True, order=True)
class StableModelDispositionV1:
    """One authored stable/experimental/withheld/rejected decision."""

    candidate_id: str
    candidate_sha256: str
    candidate_structural_sha256: str
    disposition: ModelDisposition
    reason_code: str
    reason_evidence_sha256s: tuple[str, ...]
    revalidation_owner: str
    revalidation_trigger: str
    review_receipt_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.candidate_id, field="disposition candidate_id")
        _require_sha256(self.candidate_sha256, field="candidate_sha256")
        _require_sha256(
            self.candidate_structural_sha256,
            field="candidate_structural_sha256",
        )
        if self.disposition not in _DISPOSITIONS:
            raise StableModelDispositionError("model disposition is invalid")
        _require_id(self.reason_code, field="reason_code")
        if not self.reason_evidence_sha256s or self.reason_evidence_sha256s != tuple(
            sorted(set(self.reason_evidence_sha256s))
        ):
            raise StableModelDispositionError(
                "reason_evidence_sha256s must be nonempty, sorted, and unique"
            )
        for digest in self.reason_evidence_sha256s:
            _require_sha256(digest, field="reason_evidence_sha256s")
        _require_id(self.revalidation_owner, field="revalidation_owner")
        _require_id(self.revalidation_trigger, field="revalidation_trigger")
        _require_sha256(self.review_receipt_sha256, field="review_receipt_sha256")

    def _semantic_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_sha256": self.candidate_sha256,
            "candidate_structural_sha256": self.candidate_structural_sha256,
            "disposition": self.disposition,
            "reason_code": self.reason_code,
            "reason_evidence_sha256s": list(self.reason_evidence_sha256s),
            "revalidation_owner": self.revalidation_owner,
            "revalidation_trigger": self.revalidation_trigger,
        }

    @property
    def semantic_sha256(self) -> str:
        return _sha256(self._semantic_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self._semantic_dict(),
            "semantic_sha256": self.semantic_sha256,
            "review_receipt_sha256": self.review_receipt_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="stable model disposition")
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "candidate_id",
                    "candidate_sha256",
                    "candidate_structural_sha256",
                    "disposition",
                    "reason_code",
                    "reason_evidence_sha256s",
                    "revalidation_owner",
                    "revalidation_trigger",
                    "semantic_sha256",
                    "review_receipt_sha256",
                }
            ),
            label="stable model disposition",
        )
        decision = cls(
            candidate_id=cast("str", payload["candidate_id"]),
            candidate_sha256=cast("str", payload["candidate_sha256"]),
            candidate_structural_sha256=cast("str", payload["candidate_structural_sha256"]),
            disposition=cast("ModelDisposition", payload["disposition"]),
            reason_code=cast("str", payload["reason_code"]),
            reason_evidence_sha256s=_tuple_sha256s(
                payload["reason_evidence_sha256s"],
                field="reason_evidence_sha256s",
            ),
            revalidation_owner=cast("str", payload["revalidation_owner"]),
            revalidation_trigger=cast("str", payload["revalidation_trigger"]),
            review_receipt_sha256=cast("str", payload["review_receipt_sha256"]),
        )
        if payload["semantic_sha256"] != decision.semantic_sha256:
            raise StableModelDispositionError("disposition semantic digest is invalid")
        return decision


@dataclass(frozen=True, slots=True, order=True)
class ModelDispositionBlockerV1:
    """One exact release blocker in the disposition join."""

    candidate_id: str
    code: str

    def __post_init__(self) -> None:
        _require_id(self.candidate_id, field="blocker candidate_id")
        _require_id(self.code, field="blocker code")

    def to_dict(self) -> dict[str, str]:
        return {"candidate_id": self.candidate_id, "code": self.code}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="model disposition blocker")
        _require_exact_keys(
            payload,
            frozenset({"candidate_id", "code"}),
            label="model disposition blocker",
        )
        return cls(
            candidate_id=cast("str", payload["candidate_id"]),
            code=cast("str", payload["code"]),
        )


@dataclass(frozen=True, slots=True)
class StableModelDispositionInventoryV1:
    """Complete candidate/disposition/review join with fail-closed blockers."""

    candidate_source_authority_sha256: str
    candidates: tuple[StableModelCandidateV1, ...]
    dispositions: tuple[StableModelDispositionV1, ...]
    review_receipts: tuple[ReviewReceiptV1, ...]
    blockers: tuple[ModelDispositionBlockerV1, ...]
    release_gate_green: bool

    schema_version: ClassVar[int] = STABLE_MODEL_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = STABLE_MODEL_DISPOSITION_KIND

    def __post_init__(self) -> None:
        _require_sha256(
            self.candidate_source_authority_sha256,
            field="candidate_source_authority_sha256",
        )
        for label, values, row_type, identity in (
            ("candidates", self.candidates, StableModelCandidateV1, "candidate_id"),
            ("dispositions", self.dispositions, StableModelDispositionV1, "candidate_id"),
            ("review_receipts", self.review_receipts, ReviewReceiptV1, "receipt_sha256"),
            ("blockers", self.blockers, ModelDispositionBlockerV1, "candidate_id"),
        ):
            if type(values) is not tuple or any(type(item) is not row_type for item in values):
                raise StableModelDispositionError(f"{label} must be an exact typed tuple")
            expected_order = (
                tuple(sorted(values))
                if label == "blockers"
                else tuple(sorted(values, key=lambda item: getattr(item, identity)))
            )
            if values != expected_order:
                raise StableModelDispositionError(f"{label} must be sorted")
        if len({item.candidate_id for item in self.candidates}) != len(self.candidates):
            raise StableModelDispositionError("candidate identities must be unique")
        if len({item.candidate_id for item in self.dispositions}) != len(self.dispositions):
            raise StableModelDispositionError("disposition candidate identities must be unique")
        if len({item.receipt_sha256 for item in self.review_receipts}) != len(self.review_receipts):
            raise StableModelDispositionError("review receipt identities must be unique")
        if len({(item.candidate_id, item.code) for item in self.blockers}) != len(self.blockers):
            raise StableModelDispositionError("blocker identities must be unique")
        expected_blockers = _validate_and_compute_join_blockers(
            candidate_source_authority_sha256=self.candidate_source_authority_sha256,
            candidates=self.candidates,
            dispositions=self.dispositions,
            review_receipts=self.review_receipts,
        )
        if self.blockers != expected_blockers:
            raise StableModelDispositionError(
                "blocker inventory differs from the exact candidate/disposition/review join"
            )
        if type(self.release_gate_green) is not bool:
            raise StableModelDispositionError("release_gate_green must be an exact boolean")
        if self.release_gate_green is not (not self.blockers):
            raise StableModelDispositionError("release gate differs from blocker inventory")

    @property
    def candidate_inventory_sha256(self) -> str:
        return _sha256([item.to_dict() for item in self.candidates])

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "candidate_source_authority_sha256": self.candidate_source_authority_sha256,
            "candidate_inventory_sha256": self.candidate_inventory_sha256,
            "candidates": [item.to_dict() for item in self.candidates],
            "dispositions": [item.to_dict() for item in self.dispositions],
            "review_receipts": [item.to_dict() for item in self.review_receipts],
            "blockers": [item.to_dict() for item in self.blockers],
            "release_gate_green": self.release_gate_green,
        }

    @property
    def inventory_sha256(self) -> str:
        return _sha256(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "inventory_sha256": self.inventory_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="stable model disposition inventory")
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "candidate_source_authority_sha256",
                    "candidate_inventory_sha256",
                    "candidates",
                    "dispositions",
                    "review_receipts",
                    "blockers",
                    "release_gate_green",
                    "inventory_sha256",
                }
            ),
            label="stable model disposition inventory",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise StableModelDispositionError("model disposition inventory identity is invalid")
        if type(payload["release_gate_green"]) is not bool:
            raise StableModelDispositionError("release_gate_green must be an exact boolean")
        candidates = payload["candidates"]
        dispositions = payload["dispositions"]
        reviews = payload["review_receipts"]
        if (
            type(candidates) is not list
            or type(dispositions) is not list
            or type(reviews) is not list
        ):
            raise StableModelDispositionError("model disposition inventories must be arrays")
        rebuilt = compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256=cast(
                "str", payload["candidate_source_authority_sha256"]
            ),
            candidates=tuple(StableModelCandidateV1.from_dict(item) for item in candidates),
            dispositions=tuple(StableModelDispositionV1.from_dict(item) for item in dispositions),
            review_receipts=tuple(ReviewReceiptV1.from_dict(item) for item in reviews),
        )
        if payload != rebuilt.to_dict():
            raise StableModelDispositionError(
                "model disposition inventory differs from the exact recomputed join"
            )
        return cast("Self", rebuilt)

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_bytes(raw))


def _validate_dependency_graph(candidates: Sequence[StableModelCandidateV1]) -> None:
    by_id = {item.candidate_id: item for item in candidates}
    for candidate in candidates:
        unknown = sorted(set(candidate.dependency_ids) - set(by_id))
        if unknown:
            raise StableModelDispositionError(
                f"candidate {candidate.candidate_id} has unknown dependencies: {','.join(unknown)}"
            )
        if candidate.candidate_kind == "source" and candidate.dependency_ids:
            raise StableModelDispositionError("source candidates must be dependency leaves")
        candidate_layer = _CANDIDATE_KIND_LAYER[candidate.candidate_kind]
        inverted = tuple(
            dependency_id
            for dependency_id in candidate.dependency_ids
            if _CANDIDATE_KIND_LAYER[by_id[dependency_id].candidate_kind] > candidate_layer
        )
        if inverted:
            raise StableModelDispositionError(
                f"candidate {candidate.candidate_id} has dependency-layer inversions: "
                + ",".join(inverted)
            )

    state: dict[str, int] = {}

    def visit(candidate_id: str) -> None:
        status = state.get(candidate_id, 0)
        if status == 1:
            raise StableModelDispositionError("candidate dependency graph contains a cycle")
        if status == 2:
            return
        state[candidate_id] = 1
        for dependency_id in by_id[candidate_id].dependency_ids:
            visit(dependency_id)
        state[candidate_id] = 2

    for candidate_id in sorted(by_id):
        visit(candidate_id)


def _validate_and_compute_join_blockers(
    *,
    candidate_source_authority_sha256: str,
    candidates: Sequence[StableModelCandidateV1],
    dispositions: Sequence[StableModelDispositionV1],
    review_receipts: Sequence[ReviewReceiptV1],
) -> tuple[ModelDispositionBlockerV1, ...]:
    """Validate the complete join and deterministically derive its blockers."""

    _require_sha256(
        candidate_source_authority_sha256,
        field="candidate_source_authority_sha256",
    )
    if any(type(item) is not StableModelCandidateV1 for item in candidates):
        raise StableModelDispositionError("candidates contain an invalid row")
    if any(type(item) is not StableModelDispositionV1 for item in dispositions):
        raise StableModelDispositionError("dispositions contain an invalid row")
    if any(type(item) is not ReviewReceiptV1 for item in review_receipts):
        raise StableModelDispositionError("review_receipts contain an invalid row")
    if not candidates:
        raise StableModelDispositionError("candidate inventory must be nonempty")
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise StableModelDispositionError("candidate identities must be unique")
    if len({item.candidate_id for item in dispositions}) != len(dispositions):
        raise StableModelDispositionError("disposition candidate identities must be unique")
    if len({item.receipt_sha256 for item in review_receipts}) != len(review_receipts):
        raise StableModelDispositionError("review receipt identities must be unique")
    _validate_dependency_graph(candidates)

    candidates_by_id = {item.candidate_id: item for item in candidates}
    decisions_by_id = {item.candidate_id: item for item in dispositions}
    foreign_decisions = sorted(set(decisions_by_id) - set(candidates_by_id))
    if foreign_decisions:
        raise StableModelDispositionError(
            "dispositions reference foreign candidates: " + ",".join(foreign_decisions)
        )
    referenced_review_digests = {item.review_receipt_sha256 for item in dispositions}
    extra_review_digests = sorted(
        {item.receipt_sha256 for item in review_receipts} - referenced_review_digests
    )
    if extra_review_digests:
        raise StableModelDispositionError("review receipt inventory contains a foreign receipt")
    reviews_by_digest = {item.receipt_sha256: item for item in review_receipts}

    blockers: list[ModelDispositionBlockerV1] = []
    for candidate in sorted(candidates, key=lambda item: item.candidate_id):
        decision = decisions_by_id.get(candidate.candidate_id)
        if decision is None:
            blockers.append(
                ModelDispositionBlockerV1(
                    candidate_id=candidate.candidate_id,
                    code="candidate_disposition_missing",
                )
            )
            continue
        if decision.candidate_structural_sha256 != candidate.structural_sha256:
            raise StableModelDispositionError(
                f"disposition structural authority drifted: {candidate.candidate_id}"
            )
        if decision.candidate_sha256 != candidate.candidate_sha256:
            raise StableModelDispositionError(
                f"disposition candidate authority drifted: {candidate.candidate_id}"
            )
        review = reviews_by_digest.get(decision.review_receipt_sha256)
        if review is None:
            blockers.append(
                ModelDispositionBlockerV1(
                    candidate_id=candidate.candidate_id,
                    code="independent_review_receipt_missing",
                )
            )
        else:
            if (
                review.subject_kind != "stable_model_disposition"
                or review.subject_semantic_sha256 != decision.semantic_sha256
                or candidate.candidate_sha256 not in review.accepted_input_sha256s
                or candidate.structural_sha256 not in review.accepted_input_sha256s
                or candidate_source_authority_sha256 not in review.accepted_input_sha256s
            ):
                raise StableModelDispositionError(
                    f"review receipt is rebound to foreign evidence: {candidate.candidate_id}"
                )
            if review.disposition != "accepted":
                blockers.append(
                    ModelDispositionBlockerV1(
                        candidate_id=candidate.candidate_id,
                        code="independent_review_changes_required",
                    )
                )
        if decision.disposition == "stable" and candidate.implementation_status != "implemented":
            blockers.append(
                ModelDispositionBlockerV1(
                    candidate_id=candidate.candidate_id,
                    code="stable_implementation_missing",
                )
            )
        if (
            candidate.gate_requirement in {"lossless_required", "stable_required"}
            and decision.disposition != "stable"
        ):
            blockers.append(
                ModelDispositionBlockerV1(
                    candidate_id=candidate.candidate_id,
                    code="required_candidate_not_stable",
                )
            )
        if candidate.gate_requirement == "experimental_only" and decision.disposition == "stable":
            blockers.append(
                ModelDispositionBlockerV1(
                    candidate_id=candidate.candidate_id,
                    code="experimental_candidate_promoted_without_kind_change",
                )
            )
        if (
            decision.disposition == "experimental"
            and candidate.candidate_kind in _PUBLIC_STABLE_KINDS
        ):
            blockers.append(
                ModelDispositionBlockerV1(
                    candidate_id=candidate.candidate_id,
                    code="stable_surface_deferred_as_experimental",
                )
            )
        if decision.disposition == "stable":
            for dependency_id in candidate.dependency_ids:
                dependency_decision = decisions_by_id.get(dependency_id)
                if dependency_decision is None or dependency_decision.disposition != "stable":
                    blockers.append(
                        ModelDispositionBlockerV1(
                            candidate_id=candidate.candidate_id,
                            code=f"nonstable_dependency:{dependency_id}",
                        )
                    )

    return tuple(sorted(set(blockers)))


def compile_stable_model_disposition_inventory(
    *,
    candidate_source_authority_sha256: str,
    candidates: Sequence[StableModelCandidateV1],
    dispositions: Sequence[StableModelDispositionV1],
    review_receipts: Sequence[ReviewReceiptV1],
) -> StableModelDispositionInventoryV1:
    """Join an independently derived census to authored, separately reviewed decisions."""

    candidate_rows = tuple(candidates)
    disposition_rows = tuple(dispositions)
    review_rows = tuple(review_receipts)
    if any(type(item) is not StableModelCandidateV1 for item in candidate_rows):
        raise StableModelDispositionError("candidates contain an invalid row")
    if any(type(item) is not StableModelDispositionV1 for item in disposition_rows):
        raise StableModelDispositionError("dispositions contain an invalid row")
    if any(type(item) is not ReviewReceiptV1 for item in review_rows):
        raise StableModelDispositionError("review_receipts contain an invalid row")
    sorted_candidates = tuple(sorted(candidate_rows, key=lambda item: item.candidate_id))
    sorted_dispositions = tuple(sorted(disposition_rows, key=lambda item: item.candidate_id))
    sorted_reviews = tuple(sorted(review_rows, key=lambda item: item.receipt_sha256))
    sorted_blockers = _validate_and_compute_join_blockers(
        candidate_source_authority_sha256=candidate_source_authority_sha256,
        candidates=sorted_candidates,
        dispositions=sorted_dispositions,
        review_receipts=sorted_reviews,
    )
    return StableModelDispositionInventoryV1(
        candidate_source_authority_sha256=candidate_source_authority_sha256,
        candidates=sorted_candidates,
        dispositions=sorted_dispositions,
        review_receipts=sorted_reviews,
        blockers=sorted_blockers,
        release_gate_green=not sorted_blockers,
    )


def draft_required_model_dispositions(
    *,
    candidate_source_authority_sha256: str,
    candidates: Sequence[StableModelCandidateV1],
) -> tuple[StableModelDispositionV1, ...]:
    """Draft the only requirement-preserving disposition for every candidate.

    This is deliberately not review evidence.  Required lossless/stable
    candidates remain ``stable`` even when their implementation is missing,
    while explicit analytical experiments remain ``experimental``.  Each
    draft points to a deterministic absent-review identity so the disposition
    join stays red until a real independent receipt replaces it.
    """

    authority_sha256 = _require_sha256(
        candidate_source_authority_sha256,
        field="candidate_source_authority_sha256",
    )
    candidate_rows = tuple(candidates)
    if not candidate_rows or any(
        type(item) is not StableModelCandidateV1 for item in candidate_rows
    ):
        raise StableModelDispositionError(
            "draft candidates must be a nonempty exact typed sequence"
        )
    if len({item.candidate_id for item in candidate_rows}) != len(candidate_rows):
        raise StableModelDispositionError("draft candidate identities must be unique")
    _validate_dependency_graph(candidate_rows)

    drafted: list[StableModelDispositionV1] = []
    for candidate in sorted(candidate_rows, key=lambda item: item.candidate_id):
        if candidate.gate_requirement == "experimental_only":
            disposition: ModelDisposition = "experimental"
            reason_code = "requirement:experimental_only"
        else:
            disposition = "stable"
            reason_code = f"requirement:{candidate.gate_requirement}"
        evidence_sha256s = tuple(sorted({authority_sha256, *candidate.evidence_sha256s}))
        provisional = StableModelDispositionV1(
            candidate_id=candidate.candidate_id,
            candidate_sha256=candidate.candidate_sha256,
            candidate_structural_sha256=candidate.structural_sha256,
            disposition=disposition,
            reason_code=reason_code,
            reason_evidence_sha256s=evidence_sha256s,
            revalidation_owner="owner:model-governance",
            revalidation_trigger="authority-or-implementation-change",
            review_receipt_sha256="0" * 64,
        )
        pending_review_sha256 = _sha256(
            {
                "schema_version": 1,
                "kind": "pending_independent_model_disposition_review",
                "candidate_source_authority_sha256": authority_sha256,
                "candidate_sha256": candidate.candidate_sha256,
                "disposition_semantic_sha256": provisional.semantic_sha256,
            }
        )
        drafted.append(
            StableModelDispositionV1(
                candidate_id=provisional.candidate_id,
                candidate_sha256=provisional.candidate_sha256,
                candidate_structural_sha256=(provisional.candidate_structural_sha256),
                disposition=provisional.disposition,
                reason_code=provisional.reason_code,
                reason_evidence_sha256s=provisional.reason_evidence_sha256s,
                revalidation_owner=provisional.revalidation_owner,
                revalidation_trigger=provisional.revalidation_trigger,
                review_receipt_sha256=pending_review_sha256,
            )
        )
    return tuple(drafted)
