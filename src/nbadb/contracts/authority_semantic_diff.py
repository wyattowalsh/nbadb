"""Canonical authority-change receipts for conservative full/delta admission.

The objects in this module are deliberately local and path-free.  They do not
inspect a checkout, run extraction, or authorize publication.  They bind the
output of those independent inspections and make the mode-selection rule
reproducible: incomplete current authority is blocked, the first extraction or
an incomplete prior baseline is full, and only bounded compatible changes may
select a delta.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nbadb.contracts.authority_semantic_diff_verifier import (
        AuthoritySemanticDiffVerificationProofV1,
    )

__all__ = [
    "AUTHORITY_SEMANTIC_DIFF_KIND",
    "AUTHORITY_SEMANTIC_DIFF_SCHEMA_VERSION",
    "AffectedAuthorityScope",
    "AuthorityChange",
    "AuthorityChildIdentity",
    "AuthoritySemanticAtom",
    "AuthoritySemanticDiffError",
    "AuthoritySemanticDiffV1",
    "AuthoritySnapshot",
    "DeltaBounds",
    "build_authority_semantic_diff",
    "verify_authority_semantic_diff_independently",
]

AUTHORITY_SEMANTIC_DIFF_SCHEMA_VERSION = 1
AUTHORITY_SEMANTIC_DIFF_KIND = "nbadb_authority_semantic_diff"

type ChangeCategory = Literal[
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
]
type ChangeClassification = Literal[
    "additive",
    "bounded_compatible",
    "breaking",
    "ambiguous",
]
type UpdateMode = Literal[
    "blocked",
    "full",
    "since_last_observed",
    "recent_window",
    "targeted_backfill",
]
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
_DELTA_MODES = frozenset({"since_last_observed", "recent_window", "targeted_backfill"})
_MODES = frozenset({"blocked", "full", *_DELTA_MODES})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,511}\Z", flags=re.ASCII)


class AuthoritySemanticDiffError(ValueError):
    """An authority snapshot, change row, or semantic diff is invalid."""


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
        raise AuthoritySemanticDiffError("semantic diff is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise AuthoritySemanticDiffError(f"{field} must be a lowercase SHA-256")
    return value


def _require_git_sha(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
        raise AuthoritySemanticDiffError(f"{field} must be a lowercase commit SHA")
    return value


def _require_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise AuthoritySemanticDiffError(f"{field} must be a safe nonempty identifier")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    if any(not isinstance(key, str) for key in payload):
        raise AuthoritySemanticDiffError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        extra = ",".join(sorted(actual - expected))
        raise AuthoritySemanticDiffError(
            f"{label} fields differ (missing={missing}; unexpected={extra})"
        )


def _require_tuple_ids(value: object, *, field: str, allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise AuthoritySemanticDiffError(f"{field} must be an exact tuple")
    typed = value
    if (not typed and not allow_empty) or any(not isinstance(item, str) for item in typed):
        raise AuthoritySemanticDiffError(f"{field} must contain safe identifiers")
    items = tuple(_require_id(item, field=field) for item in typed)
    if items != tuple(sorted(set(items))):
        raise AuthoritySemanticDiffError(f"{field} must be sorted and unique")
    return items


def _decode_canonical_bytes(raw: bytes) -> Mapping[str, object]:
    if not isinstance(raw, bytes) or not raw:
        raise AuthoritySemanticDiffError("semantic diff bytes must be nonempty")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise AuthoritySemanticDiffError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise AuthoritySemanticDiffError(f"non-finite JSON constant: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthoritySemanticDiffError("semantic diff bytes are invalid JSON") from exc
    if type(value) is not dict:
        raise AuthoritySemanticDiffError("semantic diff root must be an object")
    payload = cast("Mapping[str, object]", value)
    if _canonical_bytes(payload) != raw:
        raise AuthoritySemanticDiffError("semantic diff bytes are not canonical")
    return payload


@dataclass(frozen=True, slots=True, order=True)
class AuthorityChildIdentity:
    """One required assurance child and its exact semantic identity."""

    child_id: str
    child_sha256: str
    parent_authority_sha256: str
    semantic_atom_inventory_sha256: str
    semantic_atom_count: int

    def __post_init__(self) -> None:
        _require_id(self.child_id, field="child_id")
        _require_sha256(self.child_sha256, field="child_sha256")
        _require_sha256(self.parent_authority_sha256, field="parent_authority_sha256")
        _require_sha256(
            self.semantic_atom_inventory_sha256,
            field="semantic_atom_inventory_sha256",
        )
        if type(self.semantic_atom_count) is not int or self.semantic_atom_count < 0:
            raise AuthoritySemanticDiffError("semantic_atom_count must be a nonnegative integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "child_id": self.child_id,
            "child_sha256": self.child_sha256,
            "parent_authority_sha256": self.parent_authority_sha256,
            "semantic_atom_inventory_sha256": self.semantic_atom_inventory_sha256,
            "semantic_atom_count": self.semantic_atom_count,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthoritySemanticDiffError("authority child must be an object")
        payload = cast("Mapping[str, object]", value)
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "child_id",
                    "child_sha256",
                    "parent_authority_sha256",
                    "semantic_atom_inventory_sha256",
                    "semantic_atom_count",
                }
            ),
            label="authority child",
        )
        return cls(
            child_id=cast("str", payload["child_id"]),
            child_sha256=cast("str", payload["child_sha256"]),
            parent_authority_sha256=cast("str", payload["parent_authority_sha256"]),
            semantic_atom_inventory_sha256=cast("str", payload["semantic_atom_inventory_sha256"]),
            semantic_atom_count=cast("int", payload["semantic_atom_count"]),
        )


@dataclass(frozen=True, slots=True)
class AuthoritySnapshot:
    """One observed authority generation and its mandatory-child closure."""

    source_sha: str
    authority_sha256: str
    manifest_sha256: str
    generation_semantic_sha256: str
    mandatory_child_ids: tuple[str, ...]
    children: tuple[AuthorityChildIdentity, ...]
    semantic_atoms: tuple[AuthoritySemanticAtom, ...]
    complete: bool
    independent_verifier_sha256: str

    def __post_init__(self) -> None:
        _require_git_sha(self.source_sha, field="source_sha")
        _require_sha256(self.authority_sha256, field="authority_sha256")
        _require_sha256(self.manifest_sha256, field="manifest_sha256")
        _require_sha256(
            self.generation_semantic_sha256,
            field="generation_semantic_sha256",
        )
        _require_sha256(
            self.independent_verifier_sha256,
            field="independent_verifier_sha256",
        )
        _require_tuple_ids(self.mandatory_child_ids, field="mandatory_child_ids")
        if type(self.children) is not tuple or any(
            type(item) is not AuthorityChildIdentity for item in self.children
        ):
            raise AuthoritySemanticDiffError("children must be an exact typed tuple")
        if self.children != tuple(sorted(self.children)) or len(
            {item.child_id for item in self.children}
        ) != len(self.children):
            raise AuthoritySemanticDiffError("children must be sorted and unique")
        if any(item.parent_authority_sha256 != self.authority_sha256 for item in self.children):
            raise AuthoritySemanticDiffError("authority child is rebound to a foreign parent")
        if type(self.semantic_atoms) is not tuple or any(
            type(item) is not AuthoritySemanticAtom for item in self.semantic_atoms
        ):
            raise AuthoritySemanticDiffError("semantic_atoms must be an exact typed tuple")
        if self.semantic_atoms != tuple(sorted(self.semantic_atoms)) or len(
            {item.atom_id for item in self.semantic_atoms}
        ) != len(self.semantic_atoms):
            raise AuthoritySemanticDiffError("semantic atoms must be sorted and unique")
        if type(self.complete) is not bool:
            raise AuthoritySemanticDiffError("complete must be an exact boolean")
        child_ids = tuple(item.child_id for item in self.children)
        if self.complete and child_ids != self.mandatory_child_ids:
            raise AuthoritySemanticDiffError(
                "complete authority must contain every mandatory child exactly once"
            )
        if not set(child_ids).issubset(self.mandatory_child_ids):
            raise AuthoritySemanticDiffError("authority contains an undeclared child")
        atom_child_ids = {item.child_id for item in self.semantic_atoms}
        if not atom_child_ids.issubset(child_ids):
            raise AuthoritySemanticDiffError("semantic atom targets an undeclared child")
        if self.complete:
            children_by_id = {item.child_id: item for item in self.children}
            roots_by_child = {
                child_id: tuple(
                    item for item in self.semantic_atoms if item.atom_id == f"child:{child_id}"
                )
                for child_id in self.mandatory_child_ids
            }
            if any(len(roots) != 1 for roots in roots_by_child.values()):
                raise AuthoritySemanticDiffError(
                    "complete authority requires one exact root atom per mandatory child"
                )
            if any(
                roots[0].child_id != child_id
                or roots[0].category != "assurance_child"
                or roots[0].semantic_sha256 != children_by_id[child_id].child_sha256
                for child_id, roots in roots_by_child.items()
            ):
                raise AuthoritySemanticDiffError(
                    "mandatory child root atom differs from its child identity"
                )
            for child_id, child in children_by_id.items():
                fine_atoms = tuple(
                    item
                    for item in self.semantic_atoms
                    if item.child_id == child_id and item.atom_id != f"child:{child_id}"
                )
                if child.semantic_atom_count != len(
                    fine_atoms
                ) or child.semantic_atom_inventory_sha256 != _sha256(
                    [item.to_dict() for item in fine_atoms]
                ):
                    raise AuthoritySemanticDiffError(
                        "mandatory child fine-atom inventory differs from its child identity"
                    )

    @property
    def semantic_atom_inventory_sha256(self) -> str:
        return _sha256([item.to_dict() for item in self.semantic_atoms])

    def to_dict(self) -> dict[str, object]:
        return {
            "source_sha": self.source_sha,
            "authority_sha256": self.authority_sha256,
            "manifest_sha256": self.manifest_sha256,
            "generation_semantic_sha256": self.generation_semantic_sha256,
            "mandatory_child_ids": list(self.mandatory_child_ids),
            "children": [item.to_dict() for item in self.children],
            "semantic_atom_inventory_sha256": self.semantic_atom_inventory_sha256,
            "semantic_atoms": [item.to_dict() for item in self.semantic_atoms],
            "complete": self.complete,
            "independent_verifier_sha256": self.independent_verifier_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthoritySemanticDiffError("authority snapshot must be an object")
        payload = cast("Mapping[str, object]", value)
        _require_exact_keys(
            payload,
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
            label="authority snapshot",
        )
        mandatory = payload["mandatory_child_ids"]
        children = payload["children"]
        semantic_atoms = payload["semantic_atoms"]
        if (
            type(mandatory) is not list
            or type(children) is not list
            or type(semantic_atoms) is not list
        ):
            raise AuthoritySemanticDiffError("authority snapshot inventories must be arrays")
        snapshot = cls(
            source_sha=cast("str", payload["source_sha"]),
            authority_sha256=cast("str", payload["authority_sha256"]),
            manifest_sha256=cast("str", payload["manifest_sha256"]),
            generation_semantic_sha256=cast("str", payload["generation_semantic_sha256"]),
            mandatory_child_ids=tuple(cast("list[str]", mandatory)),
            children=tuple(AuthorityChildIdentity.from_dict(item) for item in children),
            semantic_atoms=tuple(AuthoritySemanticAtom.from_dict(item) for item in semantic_atoms),
            complete=cast("bool", payload["complete"]),
            independent_verifier_sha256=cast("str", payload["independent_verifier_sha256"]),
        )
        if payload["semantic_atom_inventory_sha256"] != snapshot.semantic_atom_inventory_sha256:
            raise AuthoritySemanticDiffError("semantic atom inventory digest is invalid")
        return snapshot


@dataclass(frozen=True, slots=True, order=True)
class AffectedAuthorityScope:
    """An exact enumerable provider/model scope affected by one change."""

    scope_id: str
    scope_sha256: str
    route_ids: tuple[str, ...]
    bound_values_sha256: str
    exactly_enumerable: bool

    def __post_init__(self) -> None:
        _require_id(self.scope_id, field="scope_id")
        _require_sha256(self.scope_sha256, field="scope_sha256")
        _require_sha256(self.bound_values_sha256, field="bound_values_sha256")
        _require_tuple_ids(self.route_ids, field="route_ids")
        if type(self.exactly_enumerable) is not bool:
            raise AuthoritySemanticDiffError("exactly_enumerable must be an exact boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "scope_id": self.scope_id,
            "scope_sha256": self.scope_sha256,
            "route_ids": list(self.route_ids),
            "bound_values_sha256": self.bound_values_sha256,
            "exactly_enumerable": self.exactly_enumerable,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthoritySemanticDiffError("affected scope must be an object")
        payload = cast("Mapping[str, object]", value)
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "scope_id",
                    "scope_sha256",
                    "route_ids",
                    "bound_values_sha256",
                    "exactly_enumerable",
                }
            ),
            label="affected scope",
        )
        routes = payload["route_ids"]
        if type(routes) is not list:
            raise AuthoritySemanticDiffError("affected scope routes must be an array")
        return cls(
            scope_id=cast("str", payload["scope_id"]),
            scope_sha256=cast("str", payload["scope_sha256"]),
            route_ids=tuple(cast("list[str]", routes)),
            bound_values_sha256=cast("str", payload["bound_values_sha256"]),
            exactly_enumerable=cast("bool", payload["exactly_enumerable"]),
        )


@dataclass(frozen=True, slots=True, order=True)
class AuthoritySemanticAtom:
    """One exact semantic atom exposed by a mandatory authority child.

    The snapshot owns the atom denominator.  Change rows are derived from two
    atom inventories; callers never supply a parallel change inventory.
    """

    atom_id: str
    child_id: str
    category: ChangeCategory
    semantic_sha256: str
    affected_scopes: tuple[AffectedAuthorityScope, ...]
    addition_classification: ChangeClassification
    mutation_classification: ChangeClassification
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.atom_id, field="atom_id")
        _require_id(self.child_id, field="atom child_id")
        if self.category not in _CATEGORIES:
            raise AuthoritySemanticDiffError("semantic atom category is unsupported")
        _require_sha256(self.semantic_sha256, field="atom semantic_sha256")
        if type(self.affected_scopes) is not tuple or any(
            type(item) is not AffectedAuthorityScope for item in self.affected_scopes
        ):
            raise AuthoritySemanticDiffError(
                "semantic atom affected_scopes must be an exact typed tuple"
            )
        if self.affected_scopes != tuple(sorted(self.affected_scopes)) or len(
            {item.scope_id for item in self.affected_scopes}
        ) != len(self.affected_scopes):
            raise AuthoritySemanticDiffError(
                "semantic atom affected scopes must be sorted and unique"
            )
        if self.addition_classification not in {"additive", "breaking", "ambiguous"}:
            raise AuthoritySemanticDiffError("semantic atom addition classification is unsupported")
        if self.mutation_classification not in {
            "bounded_compatible",
            "breaking",
            "ambiguous",
        }:
            raise AuthoritySemanticDiffError("semantic atom mutation classification is unsupported")
        if (
            self.addition_classification == "additive"
            or self.mutation_classification == "bounded_compatible"
        ) and not self.affected_scopes:
            raise AuthoritySemanticDiffError(
                "delta-compatible semantic atom requires an exact affected scope"
            )
        _require_sha256(self.evidence_sha256, field="atom evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "atom_id": self.atom_id,
            "child_id": self.child_id,
            "category": self.category,
            "semantic_sha256": self.semantic_sha256,
            "affected_scopes": [item.to_dict() for item in self.affected_scopes],
            "addition_classification": self.addition_classification,
            "mutation_classification": self.mutation_classification,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthoritySemanticDiffError("semantic atom must be an object")
        payload = cast("Mapping[str, object]", value)
        _require_exact_keys(
            payload,
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
            label="semantic atom",
        )
        scopes = payload["affected_scopes"]
        if type(scopes) is not list:
            raise AuthoritySemanticDiffError("semantic atom affected scopes must be an array")
        return cls(
            atom_id=cast("str", payload["atom_id"]),
            child_id=cast("str", payload["child_id"]),
            category=cast("ChangeCategory", payload["category"]),
            semantic_sha256=cast("str", payload["semantic_sha256"]),
            affected_scopes=tuple(AffectedAuthorityScope.from_dict(item) for item in scopes),
            addition_classification=cast(
                "ChangeClassification", payload["addition_classification"]
            ),
            mutation_classification=cast(
                "ChangeClassification", payload["mutation_classification"]
            ),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True, order=True)
class AuthorityChange:
    """One classified semantic change with exact affected scopes."""

    change_id: str
    category: ChangeCategory
    classification: ChangeClassification
    before_sha256: str | None
    after_sha256: str | None
    affected_scopes: tuple[AffectedAuthorityScope, ...]
    evidence_sha256: str
    reason_code: str

    def __post_init__(self) -> None:
        _require_id(self.change_id, field="change_id")
        if self.category not in _CATEGORIES:
            raise AuthoritySemanticDiffError("change category is unsupported")
        if self.classification not in _CLASSIFICATIONS:
            raise AuthoritySemanticDiffError("change classification is unsupported")
        if self.before_sha256 is not None:
            _require_sha256(self.before_sha256, field="before_sha256")
        if self.after_sha256 is not None:
            _require_sha256(self.after_sha256, field="after_sha256")
        if self.before_sha256 is None and self.after_sha256 is None:
            raise AuthoritySemanticDiffError("change must identify before or after authority")
        if self.classification == "additive" and (
            self.before_sha256 is not None or self.after_sha256 is None
        ):
            raise AuthoritySemanticDiffError("additive change must have only an after identity")
        if type(self.affected_scopes) is not tuple or any(
            type(item) is not AffectedAuthorityScope for item in self.affected_scopes
        ):
            raise AuthoritySemanticDiffError("affected_scopes must be an exact typed tuple")
        if self.affected_scopes != tuple(sorted(self.affected_scopes)) or len(
            {item.scope_id for item in self.affected_scopes}
        ) != len(self.affected_scopes):
            raise AuthoritySemanticDiffError("affected scopes must be sorted and unique")
        if self.classification in {"additive", "bounded_compatible"} and not self.affected_scopes:
            raise AuthoritySemanticDiffError("delta-compatible change requires an exact scope")
        _require_sha256(self.evidence_sha256, field="evidence_sha256")
        _require_id(self.reason_code, field="reason_code")

    @property
    def delta_compatible(self) -> bool:
        return self.classification in {"additive", "bounded_compatible"} and all(
            scope.exactly_enumerable for scope in self.affected_scopes
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "category": self.category,
            "classification": self.classification,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "affected_scopes": [item.to_dict() for item in self.affected_scopes],
            "evidence_sha256": self.evidence_sha256,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthoritySemanticDiffError("authority change must be an object")
        payload = cast("Mapping[str, object]", value)
        _require_exact_keys(
            payload,
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
            label="authority change",
        )
        scopes = payload["affected_scopes"]
        if type(scopes) is not list:
            raise AuthoritySemanticDiffError("affected scopes must be an array")
        return cls(
            change_id=cast("str", payload["change_id"]),
            category=cast("ChangeCategory", payload["category"]),
            classification=cast("ChangeClassification", payload["classification"]),
            before_sha256=cast("str | None", payload["before_sha256"]),
            after_sha256=cast("str | None", payload["after_sha256"]),
            affected_scopes=tuple(AffectedAuthorityScope.from_dict(item) for item in scopes),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
            reason_code=cast("str", payload["reason_code"]),
        )


def _derive_authority_changes(
    previous: AuthoritySnapshot | None,
    current: AuthoritySnapshot,
) -> tuple[AuthorityChange, ...]:
    """Derive the exact change inventory from two typed atom denominators."""

    if previous is None:
        return ()
    previous_by_id = {item.atom_id: item for item in previous.semantic_atoms}
    current_by_id = {item.atom_id: item for item in current.semantic_atoms}
    rows: list[AuthorityChange] = []
    for atom_id in sorted(set(previous_by_id) | set(current_by_id)):
        before = previous_by_id.get(atom_id)
        after = current_by_id.get(atom_id)
        if (
            before is not None
            and atom_id == f"child:{before.child_id}"
            or after is not None
            and atom_id == f"child:{after.child_id}"
        ):
            continue
        if before == after:
            continue
        if before is None:
            assert after is not None
            classification = after.addition_classification
            category = after.category
            scopes = after.affected_scopes
            reason = "semantic_atom_added"
        elif after is None:
            classification = "breaking"
            category = before.category
            scopes = before.affected_scopes
            reason = "semantic_atom_removed"
        else:
            policy_changed = (
                before.child_id,
                before.category,
                before.affected_scopes,
                before.addition_classification,
                before.mutation_classification,
                before.evidence_sha256,
            ) != (
                after.child_id,
                after.category,
                after.affected_scopes,
                after.addition_classification,
                after.mutation_classification,
                after.evidence_sha256,
            )
            classification = "breaking" if policy_changed else after.mutation_classification
            category = after.category
            scopes = tuple(sorted(set((*before.affected_scopes, *after.affected_scopes))))
            reason = "semantic_atom_policy_changed" if policy_changed else "semantic_atom_changed"
        evidence_sha256 = _sha256(
            {
                "schema_version": 1,
                "kind": "nbadb_authority_semantic_atom_transition",
                "atom_id": atom_id,
                "before": None if before is None else before.to_dict(),
                "after": None if after is None else after.to_dict(),
                "classification": classification,
                "reason_code": reason,
            }
        )
        rows.append(
            AuthorityChange(
                change_id=f"atom:{atom_id}",
                category=category,
                classification=classification,
                before_sha256=None if before is None else before.semantic_sha256,
                after_sha256=None if after is None else after.semantic_sha256,
                affected_scopes=scopes,
                evidence_sha256=evidence_sha256,
                reason_code=reason,
            )
        )
    return tuple(sorted(rows))


@dataclass(frozen=True, slots=True)
class DeltaBounds:
    """Mode-specific exact bounds; unused dimensions remain absent."""

    since_watermark_sha256: str | None = None
    recent_window_start: str | None = None
    recent_window_end: str | None = None
    backfill_scope_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.since_watermark_sha256 is not None:
            _require_sha256(
                self.since_watermark_sha256,
                field="since_watermark_sha256",
            )
        for field_name in ("recent_window_start", "recent_window_end"):
            value = getattr(self, field_name)
            if value is not None:
                _require_id(value, field=field_name)
        _require_tuple_ids(
            self.backfill_scope_ids,
            field="backfill_scope_ids",
            allow_empty=True,
        )
        if (self.recent_window_start is None) != (self.recent_window_end is None):
            raise AuthoritySemanticDiffError("recent window bounds are indivisible")
        if (
            self.recent_window_start is not None
            and self.recent_window_end is not None
            and self.recent_window_start > self.recent_window_end
        ):
            raise AuthoritySemanticDiffError("recent window bounds are reversed")

    def supports(self, mode: str, *, exact_scope_ids: tuple[str, ...]) -> bool:
        if mode == "since_last_observed":
            return self.since_watermark_sha256 is not None
        if mode == "recent_window":
            return self.recent_window_start is not None
        if mode == "targeted_backfill":
            return bool(self.backfill_scope_ids) and set(self.backfill_scope_ids) == set(
                exact_scope_ids
            )
        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "since_watermark_sha256": self.since_watermark_sha256,
            "recent_window_start": self.recent_window_start,
            "recent_window_end": self.recent_window_end,
            "backfill_scope_ids": list(self.backfill_scope_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthoritySemanticDiffError("delta bounds must be an object")
        payload = cast("Mapping[str, object]", value)
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "since_watermark_sha256",
                    "recent_window_start",
                    "recent_window_end",
                    "backfill_scope_ids",
                }
            ),
            label="delta bounds",
        )
        scopes = payload["backfill_scope_ids"]
        if type(scopes) is not list:
            raise AuthoritySemanticDiffError("backfill scope IDs must be an array")
        return cls(
            since_watermark_sha256=cast("str | None", payload["since_watermark_sha256"]),
            recent_window_start=cast("str | None", payload["recent_window_start"]),
            recent_window_end=cast("str | None", payload["recent_window_end"]),
            backfill_scope_ids=tuple(cast("list[str]", scopes)),
        )


def _decision(
    previous: AuthoritySnapshot | None,
    current: AuthoritySnapshot,
    changes: tuple[AuthorityChange, ...],
    *,
    first_extraction: bool,
    preferred_delta_mode: str | None,
    delta_bounds: DeltaBounds,
) -> tuple[UpdateMode, str]:
    if not current.complete:
        return "blocked", "current_authority_incomplete"
    if first_extraction:
        return "full", "first_extraction_requires_full"
    if previous is None:
        return "full", "previous_authority_missing"
    if not previous.complete:
        return "full", "previous_authority_incomplete"
    snapshot_changed = (
        previous.source_sha,
        previous.authority_sha256,
        previous.manifest_sha256,
        previous.generation_semantic_sha256,
        previous.mandatory_child_ids,
        tuple((item.child_id, item.child_sha256) for item in previous.children),
        previous.semantic_atom_inventory_sha256,
        previous.independent_verifier_sha256,
    ) != (
        current.source_sha,
        current.authority_sha256,
        current.manifest_sha256,
        current.generation_semantic_sha256,
        current.mandatory_child_ids,
        tuple((item.child_id, item.child_sha256) for item in current.children),
        current.semantic_atom_inventory_sha256,
        current.independent_verifier_sha256,
    )
    if snapshot_changed and not changes:
        return "full", "semantic_change_inventory_missing"
    if not snapshot_changed and changes:
        return "full", "reported_change_without_authority_delta"
    if any(not change.delta_compatible for change in changes):
        return "full", "breaking_ambiguous_or_unbounded_change"
    if changes:
        # The current children do not yet expose independently derived typed
        # fine-atom denominator authorities.  Their local count/digest checks
        # detect mutation of the submitted inventory, but cannot prove that a
        # producer did not omit a changed atom.  Keep semantic changes on the
        # conservative full path until those child authorities exist.
        return "full", "fine_atom_denominator_authority_missing"

    exact_scope_ids = tuple(
        sorted({scope.scope_id for change in changes for scope in change.affected_scopes})
    )
    preferred = preferred_delta_mode
    if preferred is None:
        preferred = "targeted_backfill" if exact_scope_ids else "since_last_observed"
    if preferred not in _DELTA_MODES:
        return "full", "unsupported_delta_preference"
    if not delta_bounds.supports(preferred, exact_scope_ids=exact_scope_ids):
        return "full", "delta_bounds_incomplete"
    return cast("UpdateMode", preferred), "exact_bounded_delta"


@dataclass(frozen=True, slots=True)
class AuthoritySemanticDiffV1:
    """One independently reproducible full-versus-delta decision receipt."""

    previous: AuthoritySnapshot | None
    current: AuthoritySnapshot
    changes: tuple[AuthorityChange, ...]
    first_extraction: bool
    preferred_delta_mode: str | None
    delta_bounds: DeltaBounds
    selected_mode: UpdateMode
    decision_reason: str
    receipt_sha256: str

    schema_version: ClassVar[int] = AUTHORITY_SEMANTIC_DIFF_SCHEMA_VERSION
    kind: ClassVar[str] = AUTHORITY_SEMANTIC_DIFF_KIND

    def __post_init__(self) -> None:
        if self.previous is not None and type(self.previous) is not AuthoritySnapshot:
            raise AuthoritySemanticDiffError("previous authority must be a typed snapshot")
        if type(self.current) is not AuthoritySnapshot:
            raise AuthoritySemanticDiffError("current authority must be a typed snapshot")
        if type(self.changes) is not tuple or any(
            type(item) is not AuthorityChange for item in self.changes
        ):
            raise AuthoritySemanticDiffError("changes must be an exact typed tuple")
        if self.changes != tuple(sorted(self.changes)) or len(
            {item.change_id for item in self.changes}
        ) != len(self.changes):
            raise AuthoritySemanticDiffError("changes must be sorted and unique")
        expected_changes = _derive_authority_changes(self.previous, self.current)
        if self.changes != expected_changes:
            raise AuthoritySemanticDiffError(
                "change inventory differs from the exact semantic atom transition"
            )
        if type(self.first_extraction) is not bool:
            raise AuthoritySemanticDiffError("first_extraction must be an exact boolean")
        if self.preferred_delta_mode is not None and self.preferred_delta_mode not in _DELTA_MODES:
            raise AuthoritySemanticDiffError("preferred_delta_mode is unsupported")
        if type(self.delta_bounds) is not DeltaBounds:
            raise AuthoritySemanticDiffError("delta_bounds must be typed")
        if self.selected_mode not in _MODES:
            raise AuthoritySemanticDiffError("selected_mode is unsupported")
        _require_id(self.decision_reason, field="decision_reason")
        expected_mode, expected_reason = _decision(
            self.previous,
            self.current,
            self.changes,
            first_extraction=self.first_extraction,
            preferred_delta_mode=self.preferred_delta_mode,
            delta_bounds=self.delta_bounds,
        )
        if (self.selected_mode, self.decision_reason) != (expected_mode, expected_reason):
            raise AuthoritySemanticDiffError("semantic diff decision was overridden")
        _require_sha256(self.receipt_sha256, field="receipt_sha256")
        if self.receipt_sha256 != _sha256(self._body()):
            raise AuthoritySemanticDiffError("semantic diff receipt digest is invalid")

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "previous": None if self.previous is None else self.previous.to_dict(),
            "current": self.current.to_dict(),
            "changes": [item.to_dict() for item in self.changes],
            "first_extraction": self.first_extraction,
            "preferred_delta_mode": self.preferred_delta_mode,
            "delta_bounds": self.delta_bounds.to_dict(),
            "selected_mode": self.selected_mode,
            "decision_reason": self.decision_reason,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @property
    def admission_allowed(self) -> bool:
        return self.selected_mode != "blocked"

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise AuthoritySemanticDiffError("semantic diff must be an object")
        payload = cast("Mapping[str, object]", value)
        _require_exact_keys(
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
            label="semantic diff",
        )
        if payload["schema_version"] != AUTHORITY_SEMANTIC_DIFF_SCHEMA_VERSION:
            raise AuthoritySemanticDiffError("semantic diff schema version is unsupported")
        if payload["kind"] != AUTHORITY_SEMANTIC_DIFF_KIND:
            raise AuthoritySemanticDiffError("semantic diff kind is unsupported")
        changes = payload["changes"]
        if type(changes) is not list:
            raise AuthoritySemanticDiffError("semantic diff changes must be an array")
        previous_value = payload["previous"]
        return cls(
            previous=(
                None if previous_value is None else AuthoritySnapshot.from_dict(previous_value)
            ),
            current=AuthoritySnapshot.from_dict(payload["current"]),
            changes=tuple(AuthorityChange.from_dict(item) for item in changes),
            first_extraction=cast("bool", payload["first_extraction"]),
            preferred_delta_mode=cast("str | None", payload["preferred_delta_mode"]),
            delta_bounds=DeltaBounds.from_dict(payload["delta_bounds"]),
            selected_mode=cast("UpdateMode", payload["selected_mode"]),
            decision_reason=cast("str", payload["decision_reason"]),
            receipt_sha256=cast("str", payload["receipt_sha256"]),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_bytes(raw))


def build_authority_semantic_diff(
    *,
    previous: AuthoritySnapshot | None,
    current: AuthoritySnapshot,
    first_extraction: bool,
    preferred_delta_mode: str | None,
    delta_bounds: DeltaBounds,
) -> AuthoritySemanticDiffV1:
    """Build a receipt using the non-overridable conservative decision rule."""

    normalized_changes = _derive_authority_changes(previous, current)
    mode, reason = _decision(
        previous,
        current,
        normalized_changes,
        first_extraction=first_extraction,
        preferred_delta_mode=preferred_delta_mode,
        delta_bounds=delta_bounds,
    )
    body = {
        "schema_version": AUTHORITY_SEMANTIC_DIFF_SCHEMA_VERSION,
        "kind": AUTHORITY_SEMANTIC_DIFF_KIND,
        "previous": None if previous is None else previous.to_dict(),
        "current": current.to_dict(),
        "changes": [item.to_dict() for item in normalized_changes],
        "first_extraction": first_extraction,
        "preferred_delta_mode": preferred_delta_mode,
        "delta_bounds": delta_bounds.to_dict(),
        "selected_mode": mode,
        "decision_reason": reason,
    }
    return AuthoritySemanticDiffV1(
        previous=previous,
        current=current,
        changes=normalized_changes,
        first_extraction=first_extraction,
        preferred_delta_mode=preferred_delta_mode,
        delta_bounds=delta_bounds,
        selected_mode=mode,
        decision_reason=reason,
        receipt_sha256=_sha256(body),
    )


def verify_authority_semantic_diff_independently(
    receipt: AuthoritySemanticDiffV1,
) -> AuthoritySemanticDiffVerificationProofV1:
    """Delegate exact wire reconstruction to the independent verifier module."""

    if type(receipt) is not AuthoritySemanticDiffV1:
        raise AuthoritySemanticDiffError("semantic diff verifier requires the exact type")
    from nbadb.contracts.authority_semantic_diff_verifier import (
        verify_authority_semantic_diff_bytes_independently,
    )

    return verify_authority_semantic_diff_bytes_independently(receipt.canonical_bytes)
