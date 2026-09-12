"""Independent verification for authority semantic-diff receipts.

The primary module owns the typed decision object and builder. This module
first exact-parses and reconstructs canonical wire data with local primitive
validators. Only after those checks succeed does it instantiate the primary
DTO. Successful verification emits a separate proof; callers cannot mark a
primary decision as verified themselves.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Self, cast

from nbadb.contracts.authority_semantic_diff import (
    AUTHORITY_SEMANTIC_DIFF_KIND,
    AUTHORITY_SEMANTIC_DIFF_SCHEMA_VERSION,
    AuthoritySemanticDiffError,
    AuthoritySemanticDiffV1,
)

__all__ = [
    "AuthoritySemanticDiffVerificationProofV1",
    "VerifiedAuthoritySemanticDiffV1",
    "authority_semantic_diff_verifier_source_sha256",
    "build_verified_authority_semantic_diff",
    "verify_authority_semantic_diff_bytes_independently",
    "verify_verified_authority_semantic_diff_bytes",
]

_MAX_BYTES = 128 * 1024 * 1024
_PROOF_KIND = "nbadb_authority_semantic_diff_verification"
_ENVELOPE_KIND = "nbadb_verified_authority_semantic_diff"
_DELTA_MODES = frozenset({"since_last_observed", "recent_window", "targeted_backfill"})
_MODES = frozenset({"blocked", "full", *_DELTA_MODES})
_CATEGORIES = frozenset(
    {
        "provider_package",
        "request",
        "result",
        "header_occurrence",
        "field_occurrence",
        "temporal",
        "competition",
        "route",
        "model_disposition",
        "schema",
        "key_grain",
        "type",
        "meaning",
        "lineage",
        "reconstruction",
        "assurance_child",
    }
)
_CLASSIFICATIONS = frozenset({"additive", "bounded_compatible", "breaking", "ambiguous"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,511}\Z", flags=re.ASCII)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise AuthoritySemanticDiffError(
            "independent semantic diff payload is not canonical JSON"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def authority_semantic_diff_verifier_source_sha256() -> str:
    """Return the SHA-256 of this complete verifier module."""

    try:
        return _sha256_bytes(Path(__file__).read_bytes())
    except OSError as exc:
        raise AuthoritySemanticDiffError("cannot read independent verifier source") from exc


def _decode(raw: bytes, *, label: str = "independent semantic diff") -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
        raise AuthoritySemanticDiffError(f"{label} bytes are empty, foreign, or oversized")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise AuthoritySemanticDiffError(f"{label} contains duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                AuthoritySemanticDiffError(f"{label} contains non-finite JSON: {value}")
            ),
        )
    except AuthoritySemanticDiffError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AuthoritySemanticDiffError(f"{label} bytes are invalid JSON") from exc
    if type(decoded) is not dict:
        raise AuthoritySemanticDiffError(f"{label} root must be an object")
    payload = cast("dict[str, object]", decoded)
    if _canonical_bytes(payload) != raw:
        raise AuthoritySemanticDiffError(f"{label} bytes are not exact canonical JSON")
    return payload


def _object(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AuthoritySemanticDiffError(f"{label} must be an object")
    return cast("dict[str, object]", value)


def _array(value: object, *, label: str) -> list[object]:
    if type(value) is not list:
        raise AuthoritySemanticDiffError(f"{label} must be an array")
    return cast("list[object]", value)


def _exact_keys(payload: dict[str, object], expected: frozenset[str], *, label: str) -> None:
    if frozenset(payload) != expected:
        raise AuthoritySemanticDiffError(f"{label} fields differ from the independent contract")


def _string(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise AuthoritySemanticDiffError(f"{label} must be an exact string")
    return value


def _identifier(value: object, *, label: str) -> str:
    result = _string(value, label=label)
    if _SAFE_ID_RE.fullmatch(result) is None:
        raise AuthoritySemanticDiffError(f"{label} must be a safe nonempty identifier")
    return result


def _sha(value: object, *, label: str) -> str:
    result = _string(value, label=label)
    if _SHA256_RE.fullmatch(result) is None:
        raise AuthoritySemanticDiffError(f"{label} must be a lowercase SHA-256")
    return result


def _git_sha(value: object, *, label: str) -> str:
    result = _string(value, label=label)
    if _GIT_SHA_RE.fullmatch(result) is None:
        raise AuthoritySemanticDiffError(f"{label} must be a lowercase commit SHA")
    return result


def _bool(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        raise AuthoritySemanticDiffError(f"{label} must be an exact boolean")
    return value


def _ids(value: object, *, label: str, allow_empty: bool = False) -> list[str]:
    values = _array(value, label=label)
    result = [_identifier(item, label=label) for item in values]
    if (not allow_empty and not result) or result != sorted(set(result)):
        raise AuthoritySemanticDiffError(f"{label} must be sorted, unique, and complete")
    return result


def _validate_scope(value: object) -> dict[str, object]:
    scope = _object(value, label="independent affected scope")
    _exact_keys(
        scope,
        frozenset(
            {
                "scope_id",
                "scope_sha256",
                "route_ids",
                "bound_values_sha256",
                "exactly_enumerable",
            }
        ),
        label="independent affected scope",
    )
    _identifier(scope["scope_id"], label="scope_id")
    _sha(scope["scope_sha256"], label="scope_sha256")
    _ids(scope["route_ids"], label="route_ids")
    _sha(scope["bound_values_sha256"], label="bound_values_sha256")
    _bool(scope["exactly_enumerable"], label="exactly_enumerable")
    return scope


def _validate_atom(value: object) -> dict[str, object]:
    atom = _object(value, label="independent semantic atom")
    _exact_keys(
        atom,
        frozenset(
            {
                "atom_id",
                "child_id",
                "category",
                "semantic_sha256",
                "affected_scopes",
                "addition_classification",
                "mutation_classification",
                "evidence_sha256",
            }
        ),
        label="independent semantic atom",
    )
    _identifier(atom["atom_id"], label="atom_id")
    _identifier(atom["child_id"], label="atom child_id")
    if atom["category"] not in _CATEGORIES:
        raise AuthoritySemanticDiffError("independent semantic atom category is unsupported")
    _sha(atom["semantic_sha256"], label="atom semantic_sha256")
    scopes = [
        _validate_scope(item) for item in _array(atom["affected_scopes"], label="atom scopes")
    ]
    scope_ids = [cast("str", item["scope_id"]) for item in scopes]
    if scope_ids != sorted(set(scope_ids)):
        raise AuthoritySemanticDiffError("independent atom scopes are not sorted and unique")
    addition = atom["addition_classification"]
    mutation = atom["mutation_classification"]
    if addition not in {"additive", "breaking", "ambiguous"}:
        raise AuthoritySemanticDiffError("independent atom addition classification is unsupported")
    if mutation not in {"bounded_compatible", "breaking", "ambiguous"}:
        raise AuthoritySemanticDiffError("independent atom mutation classification is unsupported")
    if (addition == "additive" or mutation == "bounded_compatible") and not scopes:
        raise AuthoritySemanticDiffError("independent delta-compatible atom lacks exact scopes")
    _sha(atom["evidence_sha256"], label="atom evidence_sha256")
    return atom


def _validate_child(value: object, *, parent_sha256: str) -> dict[str, object]:
    child = _object(value, label="independent authority child")
    _exact_keys(
        child,
        frozenset(
            {
                "child_id",
                "child_sha256",
                "parent_authority_sha256",
                "semantic_atom_inventory_sha256",
                "semantic_atom_count",
            }
        ),
        label="independent authority child",
    )
    _identifier(child["child_id"], label="child_id")
    _sha(child["child_sha256"], label="child_sha256")
    if _sha(child["parent_authority_sha256"], label="parent_authority_sha256") != parent_sha256:
        raise AuthoritySemanticDiffError("independent authority child has a foreign parent")
    _sha(child["semantic_atom_inventory_sha256"], label="semantic_atom_inventory_sha256")
    count = child["semantic_atom_count"]
    if type(count) is not int or count < 0:
        raise AuthoritySemanticDiffError("independent semantic_atom_count is invalid")
    return child


def _validate_snapshot(value: object, *, label: str) -> dict[str, object]:
    snapshot = _object(value, label=label)
    _exact_keys(
        snapshot,
        frozenset(
            {
                "source_sha",
                "authority_sha256",
                "manifest_sha256",
                "generation_semantic_sha256",
                "mandatory_child_ids",
                "children",
                "semantic_atom_inventory_sha256",
                "semantic_atoms",
                "complete",
                "independent_verifier_sha256",
            }
        ),
        label=label,
    )
    _git_sha(snapshot["source_sha"], label=f"{label} source_sha")
    authority_sha = _sha(snapshot["authority_sha256"], label=f"{label} authority_sha256")
    _sha(snapshot["manifest_sha256"], label=f"{label} manifest_sha256")
    _sha(snapshot["generation_semantic_sha256"], label=f"{label} generation_semantic_sha256")
    mandatory = _ids(snapshot["mandatory_child_ids"], label=f"{label} mandatory_child_ids")
    children = [
        _validate_child(item, parent_sha256=authority_sha)
        for item in _array(snapshot["children"], label=f"{label} children")
    ]
    child_ids = [cast("str", item["child_id"]) for item in children]
    if child_ids != sorted(set(child_ids)):
        raise AuthoritySemanticDiffError(f"{label} children are not sorted and unique")
    atoms = [
        _validate_atom(item)
        for item in _array(snapshot["semantic_atoms"], label=f"{label} semantic_atoms")
    ]
    atom_ids = [cast("str", item["atom_id"]) for item in atoms]
    if atom_ids != sorted(set(atom_ids)):
        raise AuthoritySemanticDiffError(f"{label} semantic atoms are not sorted and unique")
    complete = _bool(snapshot["complete"], label=f"{label} complete")
    _sha(snapshot["independent_verifier_sha256"], label=f"{label} verifier SHA")
    if complete and child_ids != mandatory:
        raise AuthoritySemanticDiffError(f"{label} complete child closure differs")
    if not set(child_ids).issubset(mandatory):
        raise AuthoritySemanticDiffError(f"{label} contains an undeclared child")
    if not {cast("str", item["child_id"]) for item in atoms}.issubset(child_ids):
        raise AuthoritySemanticDiffError(f"{label} atom targets an undeclared child")
    if complete:
        child_by_id = {cast("str", item["child_id"]): item for item in children}
        for child_id in mandatory:
            roots = [item for item in atoms if item["atom_id"] == f"child:{child_id}"]
            if len(roots) != 1:
                raise AuthoritySemanticDiffError(f"{label} lacks one exact child root")
            root = roots[0]
            child = child_by_id[child_id]
            if (
                root["child_id"] != child_id
                or root["category"] != "assurance_child"
                or root["semantic_sha256"] != child["child_sha256"]
            ):
                raise AuthoritySemanticDiffError(f"{label} child root differs from identity")
            fine = [
                item
                for item in atoms
                if item["child_id"] == child_id and item["atom_id"] != f"child:{child_id}"
            ]
            if child["semantic_atom_count"] != len(fine) or child[
                "semantic_atom_inventory_sha256"
            ] != _sha256(fine):
                raise AuthoritySemanticDiffError(f"{label} child fine-atom inventory differs")
    if snapshot["semantic_atom_inventory_sha256"] != _sha256(atoms):
        raise AuthoritySemanticDiffError(f"{label} semantic atom inventory digest is invalid")
    return snapshot


def _validate_change(value: object) -> dict[str, object]:
    change = _object(value, label="independent semantic change")
    _exact_keys(
        change,
        frozenset(
            {
                "change_id",
                "category",
                "classification",
                "before_sha256",
                "after_sha256",
                "affected_scopes",
                "evidence_sha256",
                "reason_code",
            }
        ),
        label="independent semantic change",
    )
    _identifier(change["change_id"], label="change_id")
    if change["category"] not in _CATEGORIES or change["classification"] not in _CLASSIFICATIONS:
        raise AuthoritySemanticDiffError("independent change classification is unsupported")
    before = change["before_sha256"]
    after = change["after_sha256"]
    if before is not None:
        _sha(before, label="before_sha256")
    if after is not None:
        _sha(after, label="after_sha256")
    if before is None and after is None:
        raise AuthoritySemanticDiffError("independent change has no before or after identity")
    scopes = [
        _validate_scope(item) for item in _array(change["affected_scopes"], label="change scopes")
    ]
    scope_ids = [cast("str", item["scope_id"]) for item in scopes]
    if scope_ids != sorted(set(scope_ids)):
        raise AuthoritySemanticDiffError("independent change scopes are not sorted and unique")
    if change["classification"] in {"additive", "bounded_compatible"} and not scopes:
        raise AuthoritySemanticDiffError("independent compatible change lacks an exact scope")
    _sha(change["evidence_sha256"], label="change evidence_sha256")
    _identifier(change["reason_code"], label="reason_code")
    return change


def _validate_bounds(value: object) -> dict[str, object]:
    bounds = _object(value, label="independent delta bounds")
    _exact_keys(
        bounds,
        frozenset(
            {
                "since_watermark_sha256",
                "recent_window_start",
                "recent_window_end",
                "backfill_scope_ids",
            }
        ),
        label="independent delta bounds",
    )
    if bounds["since_watermark_sha256"] is not None:
        _sha(bounds["since_watermark_sha256"], label="since_watermark_sha256")
    start = bounds["recent_window_start"]
    end = bounds["recent_window_end"]
    if start is not None:
        _identifier(start, label="recent_window_start")
    if end is not None:
        _identifier(end, label="recent_window_end")
    if (start is None) != (end is None) or (
        isinstance(start, str) and isinstance(end, str) and start > end
    ):
        raise AuthoritySemanticDiffError("independent recent window bounds are invalid")
    _ids(bounds["backfill_scope_ids"], label="backfill_scope_ids", allow_empty=True)
    return bounds


def _validate_decision_payload(payload: dict[str, object]) -> dict[str, object]:
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "previous",
                "current",
                "changes",
                "first_extraction",
                "preferred_delta_mode",
                "delta_bounds",
                "selected_mode",
                "decision_reason",
                "receipt_sha256",
            }
        ),
        label="independent semantic diff",
    )
    if (
        payload["schema_version"] != AUTHORITY_SEMANTIC_DIFF_SCHEMA_VERSION
        or payload["kind"] != AUTHORITY_SEMANTIC_DIFF_KIND
    ):
        raise AuthoritySemanticDiffError("independent semantic diff schema identity is invalid")
    if payload["previous"] is not None:
        _validate_snapshot(payload["previous"], label="independent previous snapshot")
    _validate_snapshot(payload["current"], label="independent current snapshot")
    changes = [
        _validate_change(item)
        for item in _array(payload["changes"], label="independent semantic changes")
    ]
    change_ids = [cast("str", item["change_id"]) for item in changes]
    if change_ids != sorted(set(change_ids)):
        raise AuthoritySemanticDiffError("independent semantic changes are not sorted and unique")
    _bool(payload["first_extraction"], label="first_extraction")
    preferred = payload["preferred_delta_mode"]
    if preferred is not None and preferred not in _DELTA_MODES:
        raise AuthoritySemanticDiffError("independent delta preference is unsupported")
    _validate_bounds(payload["delta_bounds"])
    if payload["selected_mode"] not in _MODES:
        raise AuthoritySemanticDiffError("independent selected mode is unsupported")
    _identifier(payload["decision_reason"], label="decision_reason")
    _sha(payload["receipt_sha256"], label="receipt_sha256")
    return payload


def _derive_changes(
    previous: dict[str, object] | None,
    current: dict[str, object],
) -> tuple[dict[str, object], ...]:
    if previous is None:
        return ()
    before_atoms = cast("list[dict[str, object]]", previous["semantic_atoms"])
    after_atoms = cast("list[dict[str, object]]", current["semantic_atoms"])
    before_by_id = {cast("str", item["atom_id"]): item for item in before_atoms}
    after_by_id = {cast("str", item["atom_id"]): item for item in after_atoms}
    rows: list[dict[str, object]] = []
    for atom_id in sorted(set(before_by_id) | set(after_by_id)):
        before = before_by_id.get(atom_id)
        after = after_by_id.get(atom_id)
        if (before is not None and atom_id == f"child:{before['child_id']}") or (
            after is not None and atom_id == f"child:{after['child_id']}"
        ):
            continue
        if before == after:
            continue
        if before is None:
            assert after is not None
            classification = cast("str", after["addition_classification"])
            category = after["category"]
            scopes = cast("list[dict[str, object]]", after["affected_scopes"])
            reason = "semantic_atom_added"
        elif after is None:
            classification = "breaking"
            category = before["category"]
            scopes = cast("list[dict[str, object]]", before["affected_scopes"])
            reason = "semantic_atom_removed"
        else:
            policy_keys = (
                "child_id",
                "category",
                "affected_scopes",
                "addition_classification",
                "mutation_classification",
                "evidence_sha256",
            )
            policy_changed = tuple(before[key] for key in policy_keys) != tuple(
                after[key] for key in policy_keys
            )
            classification = (
                "breaking" if policy_changed else cast("str", after["mutation_classification"])
            )
            category = after["category"]
            scopes_by_id = {
                cast("str", scope["scope_id"]): scope
                for scope in cast("list[dict[str, object]]", before["affected_scopes"])
            }
            scopes_by_id.update(
                {
                    cast("str", scope["scope_id"]): scope
                    for scope in cast("list[dict[str, object]]", after["affected_scopes"])
                }
            )
            scopes = [scopes_by_id[key] for key in sorted(scopes_by_id)]
            reason = "semantic_atom_policy_changed" if policy_changed else "semantic_atom_changed"
        transition = {
            "schema_version": 1,
            "kind": "nbadb_authority_semantic_atom_transition",
            "atom_id": atom_id,
            "before": before,
            "after": after,
            "classification": classification,
            "reason_code": reason,
        }
        rows.append(
            {
                "change_id": f"atom:{atom_id}",
                "category": category,
                "classification": classification,
                "before_sha256": None if before is None else before["semantic_sha256"],
                "after_sha256": None if after is None else after["semantic_sha256"],
                "affected_scopes": scopes,
                "evidence_sha256": _sha256(transition),
                "reason_code": reason,
            }
        )
    return tuple(sorted(rows, key=lambda item: cast("str", item["change_id"])))


def _snapshot_changed(previous: dict[str, object], current: dict[str, object]) -> bool:
    def identity(snapshot: dict[str, object]) -> tuple[object, ...]:
        children = cast("list[dict[str, object]]", snapshot["children"])
        return (
            snapshot["source_sha"],
            snapshot["authority_sha256"],
            snapshot["manifest_sha256"],
            snapshot["generation_semantic_sha256"],
            tuple(cast("list[str]", snapshot["mandatory_child_ids"])),
            tuple((item["child_id"], item["child_sha256"]) for item in children),
            snapshot["semantic_atom_inventory_sha256"],
            snapshot["independent_verifier_sha256"],
        )

    return identity(previous) != identity(current)


def _bounds_support(payload: dict[str, object], exact_scope_ids: tuple[str, ...]) -> bool:
    bounds = cast("dict[str, object]", payload["delta_bounds"])
    mode = payload["preferred_delta_mode"]
    if mode is None:
        mode = "targeted_backfill" if exact_scope_ids else "since_last_observed"
    if mode == "since_last_observed":
        return bounds["since_watermark_sha256"] is not None
    if mode == "recent_window":
        return bounds["recent_window_start"] is not None and bounds["recent_window_end"] is not None
    if mode == "targeted_backfill":
        scope_ids = cast("list[str]", bounds["backfill_scope_ids"])
        return bool(scope_ids) and set(scope_ids) == set(exact_scope_ids)
    return False


def _decision(payload: dict[str, object]) -> tuple[str, str]:
    current = cast("dict[str, object]", payload["current"])
    previous = cast("dict[str, object] | None", payload["previous"])
    changes = cast("list[dict[str, object]]", payload["changes"])
    if current["complete"] is not True:
        return "blocked", "current_authority_incomplete"
    if payload["first_extraction"] is True:
        return "full", "first_extraction_requires_full"
    if previous is None:
        return "full", "previous_authority_missing"
    if previous["complete"] is not True:
        return "full", "previous_authority_incomplete"
    changed = _snapshot_changed(previous, current)
    if changed and not changes:
        return "full", "semantic_change_inventory_missing"
    if not changed and changes:
        return "full", "reported_change_without_authority_delta"
    if any(
        item["classification"] not in {"additive", "bounded_compatible"}
        or any(
            scope["exactly_enumerable"] is not True
            for scope in cast("list[dict[str, object]]", item["affected_scopes"])
        )
        for item in changes
    ):
        return "full", "breaking_ambiguous_or_unbounded_change"
    if changes:
        return "full", "fine_atom_denominator_authority_missing"
    exact_scope_ids: tuple[str, ...] = ()
    preferred = payload["preferred_delta_mode"]
    if preferred is None:
        preferred = "since_last_observed"
    if preferred not in _DELTA_MODES:
        return "full", "unsupported_delta_preference"
    if not _bounds_support(payload, exact_scope_ids):
        return "full", "delta_bounds_incomplete"
    return cast("str", preferred), "exact_bounded_delta"


@dataclass(frozen=True, slots=True)
class AuthoritySemanticDiffVerificationProofV1:
    """Verifier-emitted proof binding one decision and reconstruction."""

    decision_wire_sha256: str
    decision_receipt_sha256: str
    verifier_source_sha256: str
    reconstructed_change_inventory_sha256: str
    reconstructed_selected_mode: str
    reconstructed_decision_reason: str
    verification_status: Literal["verified"]
    proof_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = _PROOF_KIND

    def __post_init__(self) -> None:
        for field in (
            self.decision_wire_sha256,
            self.decision_receipt_sha256,
            self.verifier_source_sha256,
            self.reconstructed_change_inventory_sha256,
            self.proof_sha256,
        ):
            _sha(field, label="verification proof SHA-256")
        if self.reconstructed_selected_mode not in _MODES:
            raise AuthoritySemanticDiffError("verification proof mode is unsupported")
        _identifier(self.reconstructed_decision_reason, label="verification proof reason")
        if self.verification_status != "verified":
            raise AuthoritySemanticDiffError("verification proof status is not verified")
        if self.proof_sha256 != _sha256(self._body()):
            raise AuthoritySemanticDiffError("verification proof digest is invalid")

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "decision_wire_sha256": self.decision_wire_sha256,
            "decision_receipt_sha256": self.decision_receipt_sha256,
            "verifier_source_sha256": self.verifier_source_sha256,
            "reconstructed_change_inventory_sha256": self.reconstructed_change_inventory_sha256,
            "reconstructed_selected_mode": self.reconstructed_selected_mode,
            "reconstructed_decision_reason": self.reconstructed_decision_reason,
            "verification_status": self.verification_status,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "proof_sha256": self.proof_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _object(value, label="semantic diff verification proof")
        _exact_keys(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "decision_wire_sha256",
                    "decision_receipt_sha256",
                    "verifier_source_sha256",
                    "reconstructed_change_inventory_sha256",
                    "reconstructed_selected_mode",
                    "reconstructed_decision_reason",
                    "verification_status",
                    "proof_sha256",
                }
            ),
            label="semantic diff verification proof",
        )
        if payload["schema_version"] != 1 or payload["kind"] != _PROOF_KIND:
            raise AuthoritySemanticDiffError("verification proof schema identity is invalid")
        return cls(
            decision_wire_sha256=cast("str", payload["decision_wire_sha256"]),
            decision_receipt_sha256=cast("str", payload["decision_receipt_sha256"]),
            verifier_source_sha256=cast("str", payload["verifier_source_sha256"]),
            reconstructed_change_inventory_sha256=cast(
                "str", payload["reconstructed_change_inventory_sha256"]
            ),
            reconstructed_selected_mode=cast("str", payload["reconstructed_selected_mode"]),
            reconstructed_decision_reason=cast("str", payload["reconstructed_decision_reason"]),
            verification_status=cast("Literal['verified']", payload["verification_status"]),
            proof_sha256=cast("str", payload["proof_sha256"]),
        )


def verify_authority_semantic_diff_bytes_independently(
    raw: bytes,
) -> AuthoritySemanticDiffVerificationProofV1:
    """Independently parse/reconstruct a decision and emit a bound proof."""

    payload = _validate_decision_payload(_decode(raw))
    previous = (
        None if payload["previous"] is None else cast("dict[str, object]", payload["previous"])
    )
    current = cast("dict[str, object]", payload["current"])
    expected_changes = _derive_changes(previous, current)
    if tuple(cast("list[dict[str, object]]", payload["changes"])) != expected_changes:
        raise AuthoritySemanticDiffError(
            "independent semantic atom transition differs from the receipt"
        )
    expected_mode, expected_reason = _decision(payload)
    if (payload["selected_mode"], payload["decision_reason"]) != (
        expected_mode,
        expected_reason,
    ):
        raise AuthoritySemanticDiffError(
            "independent semantic diff decision differs from the receipt"
        )
    body = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    if payload["receipt_sha256"] != _sha256(body):
        raise AuthoritySemanticDiffError("independent semantic diff receipt digest is invalid")

    # Instantiate the primary DTO only after every independent wire check.
    AuthoritySemanticDiffV1.from_dict(payload)
    decision_wire_sha256 = _sha256_bytes(raw)
    decision_receipt_sha256 = _sha(payload["receipt_sha256"], label="receipt_sha256")
    verifier_source_sha256 = authority_semantic_diff_verifier_source_sha256()
    reconstructed_change_inventory_sha256 = _sha256(list(expected_changes))
    proof_body = {
        "schema_version": 1,
        "kind": _PROOF_KIND,
        "decision_wire_sha256": decision_wire_sha256,
        "decision_receipt_sha256": decision_receipt_sha256,
        "verifier_source_sha256": verifier_source_sha256,
        "reconstructed_change_inventory_sha256": reconstructed_change_inventory_sha256,
        "reconstructed_selected_mode": expected_mode,
        "reconstructed_decision_reason": expected_reason,
        "verification_status": "verified",
    }
    return AuthoritySemanticDiffVerificationProofV1(
        decision_wire_sha256=decision_wire_sha256,
        decision_receipt_sha256=decision_receipt_sha256,
        verifier_source_sha256=verifier_source_sha256,
        reconstructed_change_inventory_sha256=reconstructed_change_inventory_sha256,
        reconstructed_selected_mode=expected_mode,
        reconstructed_decision_reason=expected_reason,
        verification_status="verified",
        proof_sha256=_sha256(proof_body),
    )


@dataclass(frozen=True, slots=True)
class VerifiedAuthoritySemanticDiffV1:
    """Persisted envelope containing a decision and independent proof."""

    decision: AuthoritySemanticDiffV1
    verification: AuthoritySemanticDiffVerificationProofV1
    envelope_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = _ENVELOPE_KIND

    def __post_init__(self) -> None:
        if type(self.decision) is not AuthoritySemanticDiffV1:
            raise AuthoritySemanticDiffError("verified envelope decision is untyped")
        if type(self.verification) is not AuthoritySemanticDiffVerificationProofV1:
            raise AuthoritySemanticDiffError("verified envelope proof is untyped")
        expected = verify_authority_semantic_diff_bytes_independently(self.decision.canonical_bytes)
        if self.verification != expected:
            raise AuthoritySemanticDiffError("verified envelope proof differs from reconstruction")
        _sha(self.envelope_sha256, label="verified envelope SHA-256")
        if self.envelope_sha256 != _sha256(self._body()):
            raise AuthoritySemanticDiffError("verified envelope digest is invalid")

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "decision": self.decision.to_dict(),
            "verification": self.verification.to_dict(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "envelope_sha256": self.envelope_sha256}

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        payload = _decode(raw, label="verified semantic diff envelope")
        _exact_keys(
            payload,
            frozenset({"schema_version", "kind", "decision", "verification", "envelope_sha256"}),
            label="verified semantic diff envelope",
        )
        if payload["schema_version"] != 1 or payload["kind"] != _ENVELOPE_KIND:
            raise AuthoritySemanticDiffError("verified envelope schema identity is invalid")
        decision_payload = _object(payload["decision"], label="verified envelope decision")
        expected_proof = verify_authority_semantic_diff_bytes_independently(
            _canonical_bytes(decision_payload)
        )
        proof = AuthoritySemanticDiffVerificationProofV1.from_dict(payload["verification"])
        if proof != expected_proof:
            raise AuthoritySemanticDiffError(
                "persisted verification proof differs from reconstruction"
            )
        decision = AuthoritySemanticDiffV1.from_dict(decision_payload)
        return cls(
            decision=decision,
            verification=proof,
            envelope_sha256=cast("str", payload["envelope_sha256"]),
        )


def build_verified_authority_semantic_diff(
    decision: AuthoritySemanticDiffV1,
) -> VerifiedAuthoritySemanticDiffV1:
    """Execute independent verification and build a persisted envelope."""

    if type(decision) is not AuthoritySemanticDiffV1:
        raise AuthoritySemanticDiffError("verified envelope requires the exact decision type")
    proof = verify_authority_semantic_diff_bytes_independently(decision.canonical_bytes)
    body = {
        "schema_version": 1,
        "kind": _ENVELOPE_KIND,
        "decision": decision.to_dict(),
        "verification": proof.to_dict(),
    }
    return VerifiedAuthoritySemanticDiffV1(
        decision=decision,
        verification=proof,
        envelope_sha256=_sha256(body),
    )


def verify_verified_authority_semantic_diff_bytes(raw: bytes) -> VerifiedAuthoritySemanticDiffV1:
    """Re-run the verifier and validate a persisted envelope."""

    return VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(raw)
