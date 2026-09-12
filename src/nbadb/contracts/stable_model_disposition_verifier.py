"""Independent verifier for the reviewed stable-model disposition inventory.

The verifier intentionally imports neither ``stable_model_disposition`` nor
``review_evidence``.  It strict-parses exact canonical row bytes, independently
re-derives candidate and review identities, validates the dependency graph and
review join, derives every blocker, and byte-compares the observed inventory.

This proves equality to the supplied candidate authority.  It does not prove
that the caller supplied the complete repository model census; admission binds
this proof to the independently regenerated census and packaged resources.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "IndependentStableModelDispositionError",
    "StableModelDispositionIndependentProofV1",
    "verify_stable_model_disposition_inventory_independently",
]

_SCHEMA_VERSION = 1
_INVENTORY_KIND = "nbadb_stable_model_disposition_inventory"
_REVIEW_KIND = "nbadb_model_review_receipt"
_PROOF_KIND = "nbadb_stable_model_disposition_independent_proof"
_MAX_ROWS = 10_000
_MAX_ROW_BYTES = 16 * 1024 * 1024
_MAX_INVENTORY_BYTES = 128 * 1024 * 1024
_MAX_AGGREGATE_INPUT_BYTES = 256 * 1024 * 1024
_MAX_EVIDENCE = 65_536
_MAX_JSON_NUMBER_CHARS = 256
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
_GATE_REQUIREMENTS = frozenset(
    {"lossless_required", "stable_required", "optional_candidate", "experimental_only"}
)
_IMPLEMENTATION_STATUSES = frozenset({"implemented", "missing", "not_applicable"})
_DISPOSITIONS = frozenset({"stable", "experimental", "withheld", "rejected"})
_LAYERS = {
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
_REVIEW_DISPOSITIONS = frozenset({"accepted", "changes_required"})
_INDEPENDENCE_KINDS = frozenset(
    {
        "independent_agent_review",
        "maintainer_review",
        "protected_environment_approval",
        "qualified_external_review",
    }
)
_FINDING_SEVERITIES = frozenset({"blocker", "major", "minor", "note"})
_FINDING_STATUSES = frozenset({"open", "resolved"})
_VALIDATION_CLASSES = frozenset({"positive", "negative", "mutation"})


class IndependentStableModelDispositionError(ValueError):
    """The independent disposition reconstruction or comparison failed."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise IndependentStableModelDispositionError(
            "independent disposition value is not canonical JSON"
        ) from exc


def _sha256_value(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise IndependentStableModelDispositionError(f"{label} must be an exact object")
    return cast("dict[str, object]", value)


def _array(value: object, *, label: str, maximum: int = _MAX_EVIDENCE) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise IndependentStableModelDispositionError(f"{label} must be a bounded exact array")
    return cast("list[object]", value)


def _exact_keys(payload: Mapping[str, object], *, expected: frozenset[str], label: str) -> None:
    if frozenset(payload) != expected:
        raise IndependentStableModelDispositionError(f"{label} has missing or unexpected fields")


def _decode(raw: bytes, *, label: str, maximum: int) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise IndependentStableModelDispositionError(f"{label} bytes must be nonempty and bounded")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise IndependentStableModelDispositionError(
                    f"{label} contains duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise IndependentStableModelDispositionError(
            f"{label} contains non-finite JSON constant: {value}"
        )

    def _integer(value: str) -> int:
        if len(value) > _MAX_JSON_NUMBER_CHARS:
            raise IndependentStableModelDispositionError(
                f"{label} contains an oversized JSON integer"
            )
        try:
            return int(value)
        except ValueError as exc:
            raise IndependentStableModelDispositionError(
                f"{label} contains an invalid JSON integer"
            ) from exc

    def _float(value: str) -> float:
        if len(value) > _MAX_JSON_NUMBER_CHARS:
            raise IndependentStableModelDispositionError(
                f"{label} contains an oversized JSON float"
            )
        try:
            result = float(value)
        except (OverflowError, ValueError) as exc:
            raise IndependentStableModelDispositionError(
                f"{label} contains an invalid JSON float"
            ) from exc
        if not math.isfinite(result):
            raise IndependentStableModelDispositionError(
                f"{label} contains a non-finite JSON float"
            )
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
            parse_int=_integer,
        )
    except IndependentStableModelDispositionError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        OverflowError,
        RecursionError,
        ValueError,
    ) as exc:
        raise IndependentStableModelDispositionError(f"{label} is invalid JSON") from exc
    payload = _mapping(value, label=label)
    if _canonical_bytes(payload) != raw:
        raise IndependentStableModelDispositionError(f"{label} is not exact canonical JSON")
    return payload


def _sha(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise IndependentStableModelDispositionError(f"{label} must be a lowercase SHA-256")
    return value


def _optional_sha(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _sha(value, label=label)


def _safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise IndependentStableModelDispositionError(
            f"{label} must be an exact bounded safe identifier"
        )
    return value


def _literal(value: object, *, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        raise IndependentStableModelDispositionError(f"{label} is invalid")
    return value


def _sorted_unique_ids(value: object, *, label: str, allow_empty: bool = True) -> list[str]:
    values = [_safe_id(item, label=label) for item in _array(value, label=label)]
    if (not values and not allow_empty) or values != sorted(set(values)):
        raise IndependentStableModelDispositionError(
            f"{label} must be canonical sorted unique identifiers"
        )
    return values


def _sorted_unique_shas(value: object, *, label: str, allow_empty: bool = False) -> list[str]:
    values = [_sha(item, label=label) for item in _array(value, label=label)]
    if (not values and not allow_empty) or values != sorted(set(values)):
        raise IndependentStableModelDispositionError(
            f"{label} must be canonical sorted unique SHA-256 values"
        )
    return values


def _validate_candidate(value: object) -> dict[str, object]:
    row = _mapping(value, label="candidate")
    _exact_keys(
        row,
        expected=frozenset(
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
        label="candidate",
    )
    candidate_id = _safe_id(row["candidate_id"], label="candidate_id")
    kind = _literal(row["candidate_kind"], allowed=_CANDIDATE_KINDS, label="candidate_kind")
    gate = _literal(row["gate_requirement"], allowed=_GATE_REQUIREMENTS, label="gate_requirement")
    if kind in {"source", "staging"} and gate != "lossless_required":
        raise IndependentStableModelDispositionError(
            "source and staging candidates must be lossless_required"
        )
    if kind == "experimental_model" and gate != "experimental_only":
        raise IndependentStableModelDispositionError(
            "experimental models must be experimental_only"
        )
    if kind != "experimental_model" and gate == "experimental_only":
        raise IndependentStableModelDispositionError(
            "experimental_only candidates must use experimental_model kind"
        )
    structural = _sha(row["structural_sha256"], label="candidate structural_sha256")
    dependencies = _sorted_unique_ids(row["dependency_ids"], label="dependency_ids")
    if candidate_id in dependencies:
        raise IndependentStableModelDispositionError("candidate cannot depend on itself")
    evidence = _sorted_unique_shas(row["evidence_sha256s"], label="candidate evidence")
    status = _literal(
        row["implementation_status"],
        allowed=_IMPLEMENTATION_STATUSES,
        label="implementation_status",
    )
    implementation = _optional_sha(row["implementation_sha256"], label="implementation_sha256")
    if (status == "implemented") != (implementation is not None):
        raise IndependentStableModelDispositionError("implementation status and digest disagree")
    return {
        "candidate_id": candidate_id,
        "candidate_kind": kind,
        "gate_requirement": gate,
        "structural_sha256": structural,
        "dependency_ids": dependencies,
        "evidence_sha256s": evidence,
        "implementation_status": status,
        "implementation_sha256": implementation,
    }


def _candidate_sha256(candidate: Mapping[str, object]) -> str:
    return _sha256_value(candidate)


def _validate_disposition(value: object) -> dict[str, object]:
    row = _mapping(value, label="disposition")
    _exact_keys(
        row,
        expected=frozenset(
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
        label="disposition",
    )
    semantic = {
        "candidate_id": _safe_id(row["candidate_id"], label="disposition candidate_id"),
        "candidate_sha256": _sha(row["candidate_sha256"], label="candidate_sha256"),
        "candidate_structural_sha256": _sha(
            row["candidate_structural_sha256"], label="candidate_structural_sha256"
        ),
        "disposition": _literal(
            row["disposition"], allowed=_DISPOSITIONS, label="model disposition"
        ),
        "reason_code": _safe_id(row["reason_code"], label="reason_code"),
        "reason_evidence_sha256s": _sorted_unique_shas(
            row["reason_evidence_sha256s"], label="reason evidence"
        ),
        "revalidation_owner": _safe_id(row["revalidation_owner"], label="revalidation_owner"),
        "revalidation_trigger": _safe_id(row["revalidation_trigger"], label="revalidation_trigger"),
    }
    semantic_sha256 = _sha(row["semantic_sha256"], label="semantic_sha256")
    if semantic_sha256 != _sha256_value(semantic):
        raise IndependentStableModelDispositionError("disposition semantic digest is invalid")
    return {
        **semantic,
        "semantic_sha256": semantic_sha256,
        "review_receipt_sha256": _sha(row["review_receipt_sha256"], label="review_receipt_sha256"),
    }


def _validate_finding(value: object) -> dict[str, object]:
    row = _mapping(value, label="review finding")
    _exact_keys(
        row,
        expected=frozenset({"finding_id", "severity", "status", "evidence_sha256"}),
        label="review finding",
    )
    return {
        "finding_id": _safe_id(row["finding_id"], label="finding_id"),
        "severity": _literal(
            row["severity"], allowed=_FINDING_SEVERITIES, label="finding severity"
        ),
        "status": _literal(row["status"], allowed=_FINDING_STATUSES, label="finding status"),
        "evidence_sha256": _sha(row["evidence_sha256"], label="finding evidence_sha256"),
    }


def _validate_validation(value: object) -> dict[str, object]:
    row = _mapping(value, label="review validation")
    _exact_keys(
        row,
        expected=frozenset(
            {"receipt_id", "validation_class", "command_sha256", "evidence_sha256", "passed"}
        ),
        label="review validation",
    )
    if type(row["passed"]) is not bool:
        raise IndependentStableModelDispositionError("review validation passed is not boolean")
    return {
        "receipt_id": _safe_id(row["receipt_id"], label="validation receipt_id"),
        "validation_class": _literal(
            row["validation_class"],
            allowed=_VALIDATION_CLASSES,
            label="validation_class",
        ),
        "command_sha256": _sha(row["command_sha256"], label="validation command_sha256"),
        "evidence_sha256": _sha(row["evidence_sha256"], label="validation evidence_sha256"),
        "passed": row["passed"],
    }


def _validate_review(value: object) -> dict[str, object]:
    row = _mapping(value, label="review receipt")
    _exact_keys(
        row,
        expected=frozenset(
            {
                "schema_version",
                "kind",
                "subject_kind",
                "subject_semantic_sha256",
                "author_task_id",
                "author_role",
                "reviewer_task_id",
                "reviewer_role",
                "independence_evidence_kind",
                "independence_evidence_sha256",
                "accepted_input_sha256s",
                "disposition",
                "findings",
                "validation_receipts",
                "receipt_sha256",
            }
        ),
        label="review receipt",
    )
    if type(row["schema_version"]) is not int or row["schema_version"] != _SCHEMA_VERSION:
        raise IndependentStableModelDispositionError("review receipt schema is invalid")
    if row["kind"] != _REVIEW_KIND:
        raise IndependentStableModelDispositionError("review receipt kind is invalid")
    author_task = _safe_id(row["author_task_id"], label="author_task_id")
    author_role = _safe_id(row["author_role"], label="author_role")
    reviewer_task = _safe_id(row["reviewer_task_id"], label="reviewer_task_id")
    reviewer_role = _safe_id(row["reviewer_role"], label="reviewer_role")
    if author_task == reviewer_task or author_role == reviewer_role:
        raise IndependentStableModelDispositionError("review author and reviewer are not distinct")
    subject_digest = _sha(row["subject_semantic_sha256"], label="review subject_semantic_sha256")
    accepted = _sorted_unique_shas(row["accepted_input_sha256s"], label="accepted inputs")
    if subject_digest not in accepted:
        raise IndependentStableModelDispositionError(
            "review accepted inputs omit its subject semantic digest"
        )
    findings = [_validate_finding(item) for item in _array(row["findings"], label="findings")]
    validations = [
        _validate_validation(item)
        for item in _array(row["validation_receipts"], label="validation receipts")
    ]
    if findings != sorted(findings, key=lambda item: tuple(item.values())) or len(
        {cast("str", item["finding_id"]) for item in findings}
    ) != len(findings):
        raise IndependentStableModelDispositionError("review findings are not sorted and unique")
    if validations != sorted(validations, key=lambda item: tuple(item.values())) or len(
        {cast("str", item["receipt_id"]) for item in validations}
    ) != len(validations):
        raise IndependentStableModelDispositionError("review validations are not sorted and unique")
    if {item["validation_class"] for item in validations} != _VALIDATION_CLASSES:
        raise IndependentStableModelDispositionError(
            "review lacks exact positive, negative, and mutation validations"
        )
    disposition = _literal(
        row["disposition"], allowed=_REVIEW_DISPOSITIONS, label="review disposition"
    )
    has_open = any(item["status"] == "open" for item in findings)
    has_failed = any(item["passed"] is False for item in validations)
    if disposition == "accepted" and (has_open or has_failed):
        raise IndependentStableModelDispositionError("accepted review retains failed evidence")
    if disposition == "changes_required" and not (has_open or has_failed):
        raise IndependentStableModelDispositionError("changes-required review has no failure")
    content = {
        "schema_version": _SCHEMA_VERSION,
        "kind": _REVIEW_KIND,
        "subject_kind": _safe_id(row["subject_kind"], label="subject_kind"),
        "subject_semantic_sha256": subject_digest,
        "author_task_id": author_task,
        "author_role": author_role,
        "reviewer_task_id": reviewer_task,
        "reviewer_role": reviewer_role,
        "independence_evidence_kind": _literal(
            row["independence_evidence_kind"],
            allowed=_INDEPENDENCE_KINDS,
            label="independence evidence kind",
        ),
        "independence_evidence_sha256": _sha(
            row["independence_evidence_sha256"], label="independence evidence digest"
        ),
        "accepted_input_sha256s": accepted,
        "disposition": disposition,
        "findings": findings,
        "validation_receipts": validations,
    }
    receipt_sha256 = _sha(row["receipt_sha256"], label="receipt_sha256")
    if receipt_sha256 != _sha256_value(content):
        raise IndependentStableModelDispositionError("review receipt digest is invalid")
    return {**content, "receipt_sha256": receipt_sha256}


def _validate_graph(candidates: Sequence[Mapping[str, object]]) -> None:
    by_id = {cast("str", item["candidate_id"]): item for item in candidates}
    for candidate_id, candidate in by_id.items():
        dependencies = cast("list[str]", candidate["dependency_ids"])
        unknown = sorted(set(dependencies) - set(by_id))
        if unknown:
            raise IndependentStableModelDispositionError(
                f"candidate {candidate_id} has unknown dependencies"
            )
        kind = cast("str", candidate["candidate_kind"])
        if kind == "source" and dependencies:
            raise IndependentStableModelDispositionError(
                "source candidates must be dependency leaves"
            )
        if any(
            _LAYERS[cast("str", by_id[dependency]["candidate_kind"])] > _LAYERS[kind]
            for dependency in dependencies
        ):
            raise IndependentStableModelDispositionError(
                f"candidate {candidate_id} has dependency-layer inversions"
            )

    indegree = {
        candidate_id: len(cast("list[str]", candidate["dependency_ids"]))
        for candidate_id, candidate in by_id.items()
    }
    dependents: dict[str, list[str]] = {candidate_id: [] for candidate_id in by_id}
    for candidate_id, candidate in by_id.items():
        for dependency in cast("list[str]", candidate["dependency_ids"]):
            dependents[dependency].append(candidate_id)
    ready = sorted(candidate_id for candidate_id, count in indegree.items() if count == 0)
    visited = 0
    while ready:
        candidate_id = ready.pop()
        visited += 1
        for dependent in dependents[candidate_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    if visited != len(by_id):
        raise IndependentStableModelDispositionError("candidate graph contains a cycle")


def _derive_inventory(
    *,
    candidate_source_authority_sha256: str,
    candidates: Sequence[dict[str, object]],
    dispositions: Sequence[dict[str, object]],
    reviews: Sequence[dict[str, object]],
) -> dict[str, object]:
    source_sha256 = _sha(
        candidate_source_authority_sha256, label="candidate_source_authority_sha256"
    )
    if not candidates:
        raise IndependentStableModelDispositionError("candidate inventory must be nonempty")
    candidates_sorted = sorted(candidates, key=lambda item: cast("str", item["candidate_id"]))
    dispositions_sorted = sorted(dispositions, key=lambda item: cast("str", item["candidate_id"]))
    reviews_sorted = sorted(reviews, key=lambda item: cast("str", item["receipt_sha256"]))
    for label, rows, identity in (
        ("candidate", candidates_sorted, "candidate_id"),
        ("disposition", dispositions_sorted, "candidate_id"),
        ("review", reviews_sorted, "receipt_sha256"),
    ):
        values = [cast("str", item[identity]) for item in rows]
        if len(values) != len(set(values)):
            raise IndependentStableModelDispositionError(f"{label} identities repeat")
    _validate_graph(candidates_sorted)
    candidates_by_id = {cast("str", item["candidate_id"]): item for item in candidates_sorted}
    decisions_by_id = {cast("str", item["candidate_id"]): item for item in dispositions_sorted}
    foreign = set(decisions_by_id) - set(candidates_by_id)
    if foreign:
        raise IndependentStableModelDispositionError("dispositions reference foreign candidates")
    referenced_reviews = {
        cast("str", item["review_receipt_sha256"]) for item in dispositions_sorted
    }
    if {cast("str", item["receipt_sha256"]) for item in reviews_sorted} - referenced_reviews:
        raise IndependentStableModelDispositionError("review inventory contains foreign receipts")
    reviews_by_digest = {cast("str", item["receipt_sha256"]): item for item in reviews_sorted}

    blockers: set[tuple[str, str]] = set()
    for candidate_id, candidate in candidates_by_id.items():
        decision = decisions_by_id.get(candidate_id)
        if decision is None:
            blockers.add((candidate_id, "candidate_disposition_missing"))
            continue
        candidate_sha256 = _candidate_sha256(candidate)
        if decision["candidate_structural_sha256"] != candidate["structural_sha256"]:
            raise IndependentStableModelDispositionError("disposition structural authority drifted")
        if decision["candidate_sha256"] != candidate_sha256:
            raise IndependentStableModelDispositionError("disposition candidate authority drifted")
        review = reviews_by_digest.get(cast("str", decision["review_receipt_sha256"]))
        if review is None:
            blockers.add((candidate_id, "independent_review_receipt_missing"))
        else:
            accepted = cast("list[str]", review["accepted_input_sha256s"])
            if (
                review["subject_kind"] != "stable_model_disposition"
                or review["subject_semantic_sha256"] != decision["semantic_sha256"]
                or candidate_sha256 not in accepted
                or candidate["structural_sha256"] not in accepted
                or source_sha256 not in accepted
            ):
                raise IndependentStableModelDispositionError(
                    "review receipt is rebound to foreign evidence"
                )
            if review["disposition"] != "accepted":
                blockers.add((candidate_id, "independent_review_changes_required"))
        decision_value = cast("str", decision["disposition"])
        gate = cast("str", candidate["gate_requirement"])
        if decision_value == "stable" and candidate["implementation_status"] != "implemented":
            blockers.add((candidate_id, "stable_implementation_missing"))
        if gate in {"lossless_required", "stable_required"} and decision_value != "stable":
            blockers.add((candidate_id, "required_candidate_not_stable"))
        if gate == "experimental_only" and decision_value == "stable":
            blockers.add((candidate_id, "experimental_candidate_promoted_without_kind_change"))
        if decision_value == "experimental" and candidate["candidate_kind"] in _PUBLIC_STABLE_KINDS:
            blockers.add((candidate_id, "stable_surface_deferred_as_experimental"))
        if decision_value == "stable":
            for dependency in cast("list[str]", candidate["dependency_ids"]):
                dependency_decision = decisions_by_id.get(dependency)
                if dependency_decision is None or dependency_decision["disposition"] != "stable":
                    blockers.add((candidate_id, f"nonstable_dependency:{dependency}"))

    blocker_rows = [
        {"candidate_id": candidate_id, "code": code} for candidate_id, code in sorted(blockers)
    ]
    candidate_inventory_sha256 = _sha256_value(candidates_sorted)
    content: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "kind": _INVENTORY_KIND,
        "candidate_source_authority_sha256": source_sha256,
        "candidate_inventory_sha256": candidate_inventory_sha256,
        "candidates": candidates_sorted,
        "dispositions": dispositions_sorted,
        "review_receipts": reviews_sorted,
        "blockers": blocker_rows,
        "release_gate_green": not blocker_rows,
    }
    return {**content, "inventory_sha256": _sha256_value(content)}


def _validate_observed_inventory(value: object) -> dict[str, object]:
    observed = _mapping(value, label="observed disposition inventory")
    _exact_keys(
        observed,
        expected=frozenset(
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
        label="observed disposition inventory",
    )
    if type(observed["schema_version"]) is not int or observed["schema_version"] != 1:
        raise IndependentStableModelDispositionError("observed inventory schema is invalid")
    if observed["kind"] != _INVENTORY_KIND:
        raise IndependentStableModelDispositionError("observed inventory kind is invalid")
    if type(observed["release_gate_green"]) is not bool:
        raise IndependentStableModelDispositionError(
            "observed release gate must be an exact boolean"
        )
    _sha(
        observed["candidate_source_authority_sha256"],
        label="observed candidate source authority",
    )
    _sha(observed["candidate_inventory_sha256"], label="observed candidate inventory")
    _sha(observed["inventory_sha256"], label="observed inventory")
    for field in ("candidates", "dispositions", "review_receipts", "blockers"):
        _array(observed[field], label=f"observed {field}", maximum=_MAX_ROWS)
    return observed


@dataclass(frozen=True, slots=True)
class StableModelDispositionIndependentProofV1:
    """Canonical independent equality proof for one disposition inventory."""

    candidate_source_authority_sha256: str
    candidate_inventory_sha256: str
    observed_inventory_bytes_sha256: str
    inventory_sha256: str
    candidate_count: int
    disposition_count: int
    review_receipt_count: int
    blocker_count: int
    release_gate_green: bool
    verified: Literal[True]

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = _PROOF_KIND

    def __post_init__(self) -> None:
        for label, value in (
            ("candidate source", self.candidate_source_authority_sha256),
            ("candidate inventory", self.candidate_inventory_sha256),
            ("observed bytes", self.observed_inventory_bytes_sha256),
            ("inventory", self.inventory_sha256),
        ):
            _sha(value, label=f"proof {label}")
        for label, value in (
            ("candidate_count", self.candidate_count),
            ("disposition_count", self.disposition_count),
            ("review_receipt_count", self.review_receipt_count),
            ("blocker_count", self.blocker_count),
        ):
            if type(value) is not int or not 0 <= value <= _MAX_ROWS:
                raise IndependentStableModelDispositionError(
                    f"proof {label} must be a bounded exact integer"
                )
        if type(self.release_gate_green) is not bool:
            raise IndependentStableModelDispositionError("proof release gate is not boolean")
        if type(self.verified) is not bool or not self.verified:
            raise IndependentStableModelDispositionError("proof verified must be exact true")
        if self.release_gate_green is not (self.blocker_count == 0):
            raise IndependentStableModelDispositionError(
                "proof release gate differs from blocker count"
            )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "candidate_source_authority_sha256": self.candidate_source_authority_sha256,
            "candidate_inventory_sha256": self.candidate_inventory_sha256,
            "observed_inventory_bytes_sha256": self.observed_inventory_bytes_sha256,
            "inventory_sha256": self.inventory_sha256,
            "candidate_count": self.candidate_count,
            "disposition_count": self.disposition_count,
            "review_receipt_count": self.review_receipt_count,
            "blocker_count": self.blocker_count,
            "release_gate_green": self.release_gate_green,
            "verified": self.verified,
        }

    @property
    def proof_sha256(self) -> str:
        return _sha256_value(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "proof_sha256": self.proof_sha256}

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        observed_inventory_canonical_bytes: bytes,
    ) -> Self:
        """Read a proof only with the exact observed inventory it summarizes."""

        payload = _mapping(value, label="independent disposition proof")
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "candidate_source_authority_sha256",
                    "candidate_inventory_sha256",
                    "observed_inventory_bytes_sha256",
                    "inventory_sha256",
                    "candidate_count",
                    "disposition_count",
                    "review_receipt_count",
                    "blocker_count",
                    "release_gate_green",
                    "verified",
                    "proof_sha256",
                }
            ),
            label="independent disposition proof",
        )
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise IndependentStableModelDispositionError("proof schema is invalid")
        if type(payload["kind"]) is not str or payload["kind"] != _PROOF_KIND:
            raise IndependentStableModelDispositionError("proof kind is invalid")
        for field in (
            "candidate_count",
            "disposition_count",
            "review_receipt_count",
            "blocker_count",
        ):
            if type(payload[field]) is not int:
                raise IndependentStableModelDispositionError(f"proof {field} type is invalid")
        for field in ("release_gate_green", "verified"):
            if type(payload[field]) is not bool:
                raise IndependentStableModelDispositionError(f"proof {field} type is invalid")
        proof = cls(
            candidate_source_authority_sha256=cast(
                "str", payload["candidate_source_authority_sha256"]
            ),
            candidate_inventory_sha256=cast("str", payload["candidate_inventory_sha256"]),
            observed_inventory_bytes_sha256=cast("str", payload["observed_inventory_bytes_sha256"]),
            inventory_sha256=cast("str", payload["inventory_sha256"]),
            candidate_count=cast("int", payload["candidate_count"]),
            disposition_count=cast("int", payload["disposition_count"]),
            review_receipt_count=cast("int", payload["review_receipt_count"]),
            blocker_count=cast("int", payload["blocker_count"]),
            release_gate_green=cast("bool", payload["release_gate_green"]),
            verified=cast("Literal[True]", payload["verified"]),
        )
        if _sha(payload["proof_sha256"], label="proof_sha256") != proof.proof_sha256:
            raise IndependentStableModelDispositionError("proof digest is invalid")
        observed = _validate_observed_inventory(
            _decode(
                observed_inventory_canonical_bytes,
                label="proof observed disposition inventory",
                maximum=_MAX_INVENTORY_BYTES,
            )
        )
        candidates = [
            _validate_candidate(item) for item in cast("list[object]", observed["candidates"])
        ]
        dispositions = [
            _validate_disposition(item) for item in cast("list[object]", observed["dispositions"])
        ]
        reviews = [
            _validate_review(item) for item in cast("list[object]", observed["review_receipts"])
        ]
        rebuilt = _derive_inventory(
            candidate_source_authority_sha256=cast(
                "str", observed["candidate_source_authority_sha256"]
            ),
            candidates=candidates,
            dispositions=dispositions,
            reviews=reviews,
        )
        if observed != rebuilt:
            raise IndependentStableModelDispositionError(
                "proof observed inventory differs from independent reconstruction"
            )
        expected_fields: dict[str, object] = {
            "candidate_source_authority_sha256": rebuilt["candidate_source_authority_sha256"],
            "candidate_inventory_sha256": rebuilt["candidate_inventory_sha256"],
            "observed_inventory_bytes_sha256": _sha256_bytes(observed_inventory_canonical_bytes),
            "inventory_sha256": rebuilt["inventory_sha256"],
            "candidate_count": len(candidates),
            "disposition_count": len(dispositions),
            "review_receipt_count": len(reviews),
            "blocker_count": len(cast("list[object]", rebuilt["blockers"])),
            "release_gate_green": rebuilt["release_gate_green"],
        }
        actual_fields = {field: getattr(proof, field) for field in expected_fields}
        if actual_fields != expected_fields:
            raise IndependentStableModelDispositionError(
                "independent proof summary differs from its observed inventory"
            )
        return proof

    @classmethod
    def from_canonical_bytes(
        cls,
        raw: bytes,
        *,
        observed_inventory_canonical_bytes: bytes,
    ) -> Self:
        """Read a proof only with the exact observed inventory it summarizes."""

        return cls.from_dict(
            _decode(raw, label="independent disposition proof", maximum=1_000_000),
            observed_inventory_canonical_bytes=observed_inventory_canonical_bytes,
        )


def verify_stable_model_disposition_inventory_independently(
    *,
    candidate_source_authority_sha256: str,
    candidate_canonical_bytes: tuple[bytes, ...],
    disposition_canonical_bytes: tuple[bytes, ...],
    review_receipt_canonical_bytes: tuple[bytes, ...],
    observed_inventory_canonical_bytes: bytes,
) -> StableModelDispositionIndependentProofV1:
    """Independently reconstruct and byte-compare one disposition inventory."""

    if (
        type(observed_inventory_canonical_bytes) is not bytes
        or not observed_inventory_canonical_bytes
        or len(observed_inventory_canonical_bytes) > _MAX_INVENTORY_BYTES
    ):
        raise IndependentStableModelDispositionError(
            "observed inventory bytes must be nonempty and bounded"
        )
    for label, values in (
        ("candidate", candidate_canonical_bytes),
        ("disposition", disposition_canonical_bytes),
        ("review receipt", review_receipt_canonical_bytes),
    ):
        if type(values) is not tuple or len(values) > _MAX_ROWS:
            raise IndependentStableModelDispositionError(
                f"{label} bytes must be an exact bounded tuple"
            )
        if any(type(raw) is not bytes for raw in values):
            raise IndependentStableModelDispositionError(f"{label} bytes contain a foreign value")
    aggregate_input_bytes = len(observed_inventory_canonical_bytes) + sum(
        len(raw)
        for values in (
            candidate_canonical_bytes,
            disposition_canonical_bytes,
            review_receipt_canonical_bytes,
        )
        for raw in values
    )
    if aggregate_input_bytes > _MAX_AGGREGATE_INPUT_BYTES:
        raise IndependentStableModelDispositionError(
            "disposition verification input exceeds its aggregate byte budget"
        )
    candidates = [
        _validate_candidate(_decode(raw, label=f"candidate {index}", maximum=_MAX_ROW_BYTES))
        for index, raw in enumerate(candidate_canonical_bytes)
    ]
    dispositions = [
        _validate_disposition(_decode(raw, label=f"disposition {index}", maximum=_MAX_ROW_BYTES))
        for index, raw in enumerate(disposition_canonical_bytes)
    ]
    reviews = [
        _validate_review(_decode(raw, label=f"review receipt {index}", maximum=_MAX_ROW_BYTES))
        for index, raw in enumerate(review_receipt_canonical_bytes)
    ]
    expected = _derive_inventory(
        candidate_source_authority_sha256=candidate_source_authority_sha256,
        candidates=candidates,
        dispositions=dispositions,
        reviews=reviews,
    )
    _validate_observed_inventory(
        _decode(
            observed_inventory_canonical_bytes,
            label="observed disposition inventory",
            maximum=_MAX_INVENTORY_BYTES,
        )
    )
    if observed_inventory_canonical_bytes != _canonical_bytes(expected):
        raise IndependentStableModelDispositionError(
            "observed inventory differs from independent reconstruction"
        )
    return StableModelDispositionIndependentProofV1(
        candidate_source_authority_sha256=cast(
            "str", expected["candidate_source_authority_sha256"]
        ),
        candidate_inventory_sha256=cast("str", expected["candidate_inventory_sha256"]),
        observed_inventory_bytes_sha256=_sha256_bytes(observed_inventory_canonical_bytes),
        inventory_sha256=cast("str", expected["inventory_sha256"]),
        candidate_count=len(candidates),
        disposition_count=len(dispositions),
        review_receipt_count=len(reviews),
        blocker_count=len(cast("list[object]", expected["blockers"])),
        release_gate_green=cast("bool", expected["release_gate_green"]),
        verified=True,
    )
