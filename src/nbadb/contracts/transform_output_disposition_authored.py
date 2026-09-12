"""Independent authored decisions for transform-output dispositions.

Structural identities are pins, never authored semantic input: the pure compiler
rebinds them from an independently compiled structural authority.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Literal, Self, cast

from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputDispositionAuthorityError,
    TransformOutputEvidenceReferenceV1,
    TransformOutputSemanticClaimV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1,
    SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1,
    DispositionEvidenceError,
    canonical_json_bytes_v1,
    decode_canonical_json_bytes_v1,
    validate_authored_source_bundle_representability_v1,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputStructuralAuthorityV1,
    compile_current_transform_output_structural_authority,
)

__all__ = [
    "AuthoredCurrentTransformOutputDecisionV1",
    "AuthoredTransformOutputDispositionCorpusV1",
    "AuthoredTransformOutputDispositionError",
    "AuthoredTransformOutputEvidenceProjectionV1",
    "AuthoredTransformOutputRemovalDecisionV1",
    "CompiledAuthoredTransformOutputDispositionAuthorityV1",
    "load_current_transform_output_disposition_authored_authority",
]

type State = Literal["active", "observed_only_experimental", "contract_not_modeled"]

_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_NAME = re.compile(r"(?:fact|dim|bridge|agg|analytics)_[a-z0-9]+(?:_[a-z0-9]+)*\Z", re.ASCII)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", re.ASCII)
_REFERENCE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z", re.ASCII)
_MAX_ROWS = 4096
_MAX_EVIDENCE_PROJECTIONS = AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1
_MAX_BYTES = SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1
_MAX_SEQUENCE = (1 << 63) - 1
_STATES = frozenset({"active", "observed_only_experimental", "contract_not_modeled"})
_EVIDENCE_MEMBER_PREFIX = "transform-output-disposition/evidence"
_RESOURCE = Path(__file__).with_name("data") / "transform-output-disposition-authored-v1.json"


class AuthoredTransformOutputDispositionError(ValueError):
    """The independently authored corpus is invalid or unavailable."""


def _canonical_bytes(value: object, label: str) -> bytes:
    try:
        return canonical_json_bytes_v1(value)
    except DispositionEvidenceError as exc:
        raise AuthoredTransformOutputDispositionError(
            f"{label} is not bounded canonical JSON"
        ) from exc


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value, "authored digest preimage")).hexdigest()


def _require(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise AuthoredTransformOutputDispositionError(f"{label} is invalid")
    return value


def _mapping(value: object, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AuthoredTransformOutputDispositionError(f"{label} must be an object")
    result = cast("dict[str, object]", value)
    if set(result) != keys or any(type(key) is not str for key in result):
        raise AuthoredTransformOutputDispositionError(f"{label} fields differ")
    return result


def _array(value: object, label: str) -> list[object]:
    if type(value) is not list or len(value) > _MAX_ROWS:
        raise AuthoredTransformOutputDispositionError(f"{label} must be a bounded array")
    return cast("list[object]", value)


def _schema_identity(payload: dict[str, object], *, kind: str, label: str) -> None:
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or type(payload["kind"]) is not str
        or payload["kind"] != kind
    ):
        raise AuthoredTransformOutputDispositionError(f"{label} schema differs")


def _strings(value: object, label: str, *, empty: bool = False) -> tuple[str, ...]:
    values = tuple(_require(item, _ID, label) for item in _array(value, label))
    if (not empty and not values) or values != tuple(sorted(set(values))):
        raise AuthoredTransformOutputDispositionError(f"{label} must be sorted and unique")
    return values


def _validated_triggers(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise AuthoredTransformOutputDispositionError(f"{label} must be an exact tuple")
    values = tuple(_require(item, _ID, label) for item in value)
    if not values or len(values) > _MAX_ROWS or values != tuple(sorted(set(values))):
        raise AuthoredTransformOutputDispositionError(f"{label} must be sorted and unique")
    return values


def _validated_references(
    value: object, label: str
) -> tuple[TransformOutputEvidenceReferenceV1, ...]:
    if (
        type(value) is not tuple
        or not value
        or len(value) > _MAX_ROWS
        or any(type(item) is not TransformOutputEvidenceReferenceV1 for item in value)
    ):
        raise AuthoredTransformOutputDispositionError(
            f"{label} must contain bounded exact typed rows"
        )
    references = cast("tuple[TransformOutputEvidenceReferenceV1, ...]", value)
    identities = tuple((item.evidence_class, item.reference_id) for item in references)
    if references != tuple(sorted(references)) or len(identities) != len(set(identities)):
        raise AuthoredTransformOutputDispositionError(
            f"{label} must be sorted with unique identities"
        )
    return references


def _policy(value: object) -> TransformOutputCapabilityPolicyV1:
    p = _mapping(
        value,
        {
            "schema_version",
            "kind",
            "execute",
            "primary_materialize",
            "stable_load",
            "transform_publication",
            "chat_ceiling",
            "policy_sha256",
        },
        "capability policy",
    )
    _schema_identity(p, kind=TransformOutputCapabilityPolicyV1.kind, label="capability policy")
    boolean_fields = (
        "execute",
        "primary_materialize",
        "stable_load",
        "transform_publication",
        "chat_ceiling",
    )
    if any(type(p[key]) is not bool for key in boolean_fields):
        raise AuthoredTransformOutputDispositionError("capability fields must be booleans")
    try:
        result = TransformOutputCapabilityPolicyV1(
            cast("bool", p["execute"]),
            cast("bool", p["primary_materialize"]),
            cast("bool", p["stable_load"]),
            cast("bool", p["transform_publication"]),
            cast("bool", p["chat_ceiling"]),
        )
    except TransformOutputDispositionAuthorityError as exc:
        raise AuthoredTransformOutputDispositionError("capability policy is invalid") from exc
    if p["policy_sha256"] != result.policy_sha256:
        raise AuthoredTransformOutputDispositionError("capability policy digest differs")
    return result


def _reference(value: object) -> TransformOutputEvidenceReferenceV1:
    p = _mapping(
        value,
        {"schema_version", "kind", "evidence_class", "reference_id", "evidence_sha256"},
        "evidence reference",
    )
    _schema_identity(p, kind=TransformOutputEvidenceReferenceV1.kind, label="evidence reference")
    try:
        return TransformOutputEvidenceReferenceV1(
            cast("str", p["evidence_class"]),
            cast("str", p["reference_id"]),
            cast("str", p["evidence_sha256"]),
        )
    except TransformOutputDispositionAuthorityError as exc:
        raise AuthoredTransformOutputDispositionError("evidence reference is invalid") from exc


def _claim(value: object) -> TransformOutputSemanticClaimV1:
    p = _mapping(
        value,
        {"schema_version", "kind", "claim_id", "claim_kind", "claim_sha256", "evidence_sha256s"},
        "semantic claim",
    )
    _schema_identity(p, kind=TransformOutputSemanticClaimV1.kind, label="semantic claim")
    digests = tuple(
        _require(item, _SHA, "claim evidence digest")
        for item in _array(p["evidence_sha256s"], "claim evidence digests")
    )
    try:
        return TransformOutputSemanticClaimV1(
            cast("str", p["claim_id"]),
            cast("str", p["claim_kind"]),
            cast("str", p["claim_sha256"]),
            digests,
        )
    except TransformOutputDispositionAuthorityError as exc:
        raise AuthoredTransformOutputDispositionError("semantic claim is invalid") from exc


@dataclass(frozen=True, slots=True, order=True)
class AuthoredTransformOutputEvidenceProjectionV1:
    output_name: str
    evidence_class: str
    reference_id: str
    evidence_payload: object = field(compare=False)
    _projection_bytes: bytes = field(init=False, repr=False)
    _evidence_sha256: str = field(init=False, compare=False, repr=False)
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_authored_transform_output_evidence_projection"

    def __post_init__(self) -> None:
        _require(self.output_name, _NAME, "evidence output_name")
        _require(self.evidence_class, _ID, "evidence_class")
        _require(self.reference_id, _REFERENCE_ID, "normalized evidence reference_id")
        projection = {
            "schema_version": 1,
            "kind": self.kind,
            "output_name": self.output_name,
            "evidence_class": self.evidence_class,
            "reference_id": self.reference_id,
            "evidence_payload": self.evidence_payload,
        }
        projection_bytes = _canonical_bytes(projection, "evidence projection")
        if len(projection_bytes) > SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1:
            raise AuthoredTransformOutputDispositionError(
                "evidence projection is not representable as one source member"
            )
        canonical_copy = cast(
            "dict[str, object]",
            decode_canonical_json_bytes_v1(projection_bytes, persisted=False),
        )
        object.__setattr__(self, "evidence_payload", canonical_copy["evidence_payload"])
        object.__setattr__(self, "_projection_bytes", projection_bytes)
        object.__setattr__(
            self,
            "_evidence_sha256",
            hashlib.sha256(projection_bytes).hexdigest(),
        )

    @property
    def source_member_path(self) -> str:
        return f"{_EVIDENCE_MEMBER_PREFIX}/{self.output_name}/{self.reference_id}.json"

    def projection_dict(self) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            decode_canonical_json_bytes_v1(self._projection_bytes, persisted=False),
        )

    @property
    def projection_bytes(self) -> bytes:
        return self._projection_bytes

    @property
    def evidence_sha256(self) -> str:
        return self._evidence_sha256

    def to_dict(self) -> dict[str, object]:
        return {**self.projection_dict(), "evidence_sha256": self.evidence_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        p = _mapping(
            value,
            {
                "schema_version",
                "kind",
                "output_name",
                "evidence_class",
                "reference_id",
                "evidence_payload",
                "evidence_sha256",
            },
            "evidence projection",
        )
        _schema_identity(p, kind=cls.kind, label="evidence projection")
        result = cls(
            cast("str", p["output_name"]),
            cast("str", p["evidence_class"]),
            cast("str", p["reference_id"]),
            p["evidence_payload"],
        )
        if p["evidence_sha256"] != result.evidence_sha256:
            raise AuthoredTransformOutputDispositionError("evidence projection digest differs")
        return result


@dataclass(frozen=True, slots=True)
class AuthoredCurrentTransformOutputDecisionV1:
    """One immutable authored semantic decision at an explicit corpus revision."""

    output_name: str
    authored_decision_revision: int
    structural_table_authority_sha256: str
    state: State
    capability_policy: TransformOutputCapabilityPolicyV1
    semantic_claims: tuple[TransformOutputSemanticClaimV1, ...]
    reason_code: str
    evidence_references: tuple[TransformOutputEvidenceReferenceV1, ...]
    revalidation_triggers: tuple[str, ...]
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_authored_current_transform_output_decision"

    def __post_init__(self) -> None:
        _require(self.output_name, _NAME, "decision output_name")
        if type(self.authored_decision_revision) is not int or not (
            1 <= self.authored_decision_revision <= _MAX_SEQUENCE
        ):
            raise AuthoredTransformOutputDispositionError("authored decision revision is invalid")
        _require(self.structural_table_authority_sha256, _SHA, "structural table pin")
        if type(self.state) is not str or self.state not in _STATES:
            raise AuthoredTransformOutputDispositionError("decision state is invalid")
        if type(self.capability_policy) is not TransformOutputCapabilityPolicyV1:
            raise AuthoredTransformOutputDispositionError("decision capability policy is invalid")
        try:
            self.capability_policy.validate_for_state(self.state)
        except TransformOutputDispositionAuthorityError as exc:
            raise AuthoredTransformOutputDispositionError(
                "decision capability policy differs from state"
            ) from exc
        if (
            type(self.semantic_claims) is not tuple
            or any(
                type(item) is not TransformOutputSemanticClaimV1 for item in self.semantic_claims
            )
            or not self.semantic_claims
            or len(self.semantic_claims) > _MAX_ROWS
            or self.semantic_claims != tuple(sorted(set(self.semantic_claims)))
        ):
            raise AuthoredTransformOutputDispositionError(
                "semantic claims must be sorted and unique"
            )
        _require(self.reason_code, _ID, "reason_code")
        _validated_references(self.evidence_references, "evidence references")
        _validated_triggers(self.revalidation_triggers, "revalidation triggers")

    def content_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "output_name": self.output_name,
            "authored_decision_revision": self.authored_decision_revision,
            **self._decision_body_dict(),
        }

    def _decision_body_dict(self) -> dict[str, object]:
        """Return authored content excluding only its explicit revision identity."""
        return {
            "structural_table_authority_sha256": self.structural_table_authority_sha256,
            "state": self.state,
            "capability_policy": self.capability_policy.to_dict(),
            "semantic_claims": [x.to_dict() for x in self.semantic_claims],
            "reason_code": self.reason_code,
            "evidence_references": [x.to_dict() for x in self.evidence_references],
            "revalidation_triggers": list(self.revalidation_triggers),
        }

    @property
    def authored_decision_sha256(self) -> str:
        return _sha(self.content_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.content_dict(),
            "authored_decision_sha256": self.authored_decision_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        p = _mapping(
            value,
            {
                "schema_version",
                "kind",
                "output_name",
                "authored_decision_revision",
                "structural_table_authority_sha256",
                "state",
                "capability_policy",
                "semantic_claims",
                "reason_code",
                "evidence_references",
                "revalidation_triggers",
                "authored_decision_sha256",
            },
            "current decision",
        )
        _schema_identity(p, kind=cls.kind, label="current decision")
        result = cls(
            cast("str", p["output_name"]),
            cast("int", p["authored_decision_revision"]),
            cast("str", p["structural_table_authority_sha256"]),
            cast("State", p["state"]),
            _policy(p["capability_policy"]),
            tuple(_claim(x) for x in _array(p["semantic_claims"], "semantic claims")),
            cast("str", p["reason_code"]),
            tuple(_reference(x) for x in _array(p["evidence_references"], "evidence references")),
            _strings(p["revalidation_triggers"], "revalidation triggers"),
        )
        if p["authored_decision_sha256"] != result.authored_decision_sha256:
            raise AuthoredTransformOutputDispositionError(
                "authored current decision digest differs"
            )
        return result


@dataclass(frozen=True, slots=True)
class AuthoredTransformOutputRemovalDecisionV1:
    """One retained removal decision pinned to the exact prior authored decision."""

    output_name: str
    prior_authored_decision_revision: int
    prior_authored_decision_sha256: str
    first_tombstone_generation_sequence: int
    removal_reason_code: str
    evidence_references: tuple[TransformOutputEvidenceReferenceV1, ...]
    revalidation_triggers: tuple[str, ...]
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_authored_transform_output_removal_decision"

    def __post_init__(self) -> None:
        _require(self.output_name, _NAME, "removal output_name")
        if type(self.prior_authored_decision_revision) is not int or not (
            1 <= self.prior_authored_decision_revision <= _MAX_SEQUENCE
        ):
            raise AuthoredTransformOutputDispositionError(
                "prior authored decision revision is invalid"
            )
        _require(
            self.prior_authored_decision_sha256,
            _SHA,
            "prior authored decision digest",
        )
        if type(self.first_tombstone_generation_sequence) is not int or not (
            2 <= self.first_tombstone_generation_sequence <= _MAX_SEQUENCE
        ):
            raise AuthoredTransformOutputDispositionError("first tombstone generation is invalid")
        if self.prior_authored_decision_revision >= self.first_tombstone_generation_sequence:
            raise AuthoredTransformOutputDispositionError(
                "prior authored revision must precede the first tombstone generation"
            )
        _require(self.removal_reason_code, _ID, "removal reason")
        _validated_references(self.evidence_references, "removal evidence")
        _validated_triggers(self.revalidation_triggers, "removal triggers")

    def content_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "output_name": self.output_name,
            "prior_authored_decision_revision": self.prior_authored_decision_revision,
            "prior_authored_decision_sha256": self.prior_authored_decision_sha256,
            "first_tombstone_generation_sequence": self.first_tombstone_generation_sequence,
            "removal_reason_code": self.removal_reason_code,
            "evidence_references": [x.to_dict() for x in self.evidence_references],
            "revalidation_triggers": list(self.revalidation_triggers),
        }

    @property
    def removal_decision_sha256(self) -> str:
        return _sha(self.content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self.content_dict(), "removal_decision_sha256": self.removal_decision_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        p = _mapping(
            value,
            {
                "schema_version",
                "kind",
                "output_name",
                "prior_authored_decision_revision",
                "prior_authored_decision_sha256",
                "first_tombstone_generation_sequence",
                "removal_reason_code",
                "evidence_references",
                "revalidation_triggers",
                "removal_decision_sha256",
            },
            "removal decision",
        )
        _schema_identity(p, kind=cls.kind, label="removal")
        result = cls(
            cast("str", p["output_name"]),
            cast("int", p["prior_authored_decision_revision"]),
            cast("str", p["prior_authored_decision_sha256"]),
            cast("int", p["first_tombstone_generation_sequence"]),
            cast("str", p["removal_reason_code"]),
            tuple(_reference(x) for x in _array(p["evidence_references"], "removal evidence")),
            _strings(p["revalidation_triggers"], "removal triggers"),
        )
        if p["removal_decision_sha256"] != result.removal_decision_sha256:
            raise AuthoredTransformOutputDispositionError("removal digest differs")
        return result


@dataclass(frozen=True, slots=True)
class AuthoredTransformOutputDispositionCorpusV1:
    generation_sequence: int
    prior_authored_authority_sha256: str | None
    structural_authority_sha256: str
    star_model_contract_sha256: str
    current_decisions: tuple[AuthoredCurrentTransformOutputDecisionV1, ...]
    removal_decisions: tuple[AuthoredTransformOutputRemovalDecisionV1, ...]
    evidence_projections: tuple[AuthoredTransformOutputEvidenceProjectionV1, ...]
    _corpus_bytes: bytes = field(init=False, repr=False, compare=False)
    _minimum_source_bundle_canonical_bytes: int = field(init=False, repr=False, compare=False)
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_authored_transform_output_disposition_corpus"

    def __post_init__(self) -> None:
        if type(self.generation_sequence) is not int or not (
            1 <= self.generation_sequence <= _MAX_SEQUENCE
        ):
            raise AuthoredTransformOutputDispositionError("generation sequence is invalid")
        if (self.generation_sequence == 1) != (self.prior_authored_authority_sha256 is None):
            raise AuthoredTransformOutputDispositionError(
                "prior authority bound differs from generation"
            )
        if self.generation_sequence == 1 and self.removal_decisions:
            raise AuthoredTransformOutputDispositionError(
                "initial corpus cannot contain tombstones"
            )
        if self.prior_authored_authority_sha256 is not None:
            _require(self.prior_authored_authority_sha256, _SHA, "prior authority")
        _require(self.structural_authority_sha256, _SHA, "structural authority")
        _require(self.star_model_contract_sha256, _SHA, "star model contract")
        for values, label in (
            (self.current_decisions, "current decisions"),
            (self.removal_decisions, "removal decisions"),
        ):
            expected_type = (
                AuthoredCurrentTransformOutputDecisionV1
                if label == "current decisions"
                else AuthoredTransformOutputRemovalDecisionV1
            )
            if type(values) is not tuple or any(type(item) is not expected_type for item in values):
                raise AuthoredTransformOutputDispositionError(
                    f"{label} must contain exact typed rows"
                )
            if label == "current decisions" and not values:
                raise AuthoredTransformOutputDispositionError("current decisions must be nonempty")
            names = tuple(x.output_name for x in values)
            if (
                len(values) > _MAX_ROWS
                or names != tuple(sorted(names))
                or len(names) != len(set(names))
            ):
                raise AuthoredTransformOutputDispositionError(
                    f"{label} must be sorted and output-unique"
                )
        if (
            type(self.evidence_projections) is not tuple
            or any(
                type(item) is not AuthoredTransformOutputEvidenceProjectionV1
                for item in self.evidence_projections
            )
            or not self.evidence_projections
            or len(self.evidence_projections) > _MAX_EVIDENCE_PROJECTIONS
        ):
            raise AuthoredTransformOutputDispositionError(
                "evidence projections exceed the source-bundle projection limit"
            )
        projection_identities = tuple(
            (item.output_name, item.evidence_class, item.reference_id)
            for item in self.evidence_projections
        )
        if projection_identities != tuple(sorted(projection_identities)) or len(
            projection_identities
        ) != len(set(projection_identities)):
            raise AuthoredTransformOutputDispositionError(
                "evidence projections must be sorted with unique identities"
            )
        source_member_paths = tuple(item.source_member_path for item in self.evidence_projections)
        expected_member_paths = tuple(
            f"{_EVIDENCE_MEMBER_PREFIX}/{item.output_name}/{item.reference_id}.json"
            for item in self.evidence_projections
        )
        if source_member_paths != expected_member_paths or len(source_member_paths) != len(
            set(source_member_paths)
        ):
            raise AuthoredTransformOutputDispositionError(
                "evidence projection source-member paths are ambiguous"
            )
        if any(
            decision.authored_decision_revision > self.generation_sequence
            for decision in self.current_decisions
        ):
            raise AuthoredTransformOutputDispositionError(
                "current decision revision exceeds the corpus generation"
            )
        if self.generation_sequence == 1 and any(
            decision.authored_decision_revision != 1 for decision in self.current_decisions
        ):
            raise AuthoredTransformOutputDispositionError(
                "initial current decisions must have authored revision one"
            )
        if any(
            not (
                decision.prior_authored_decision_revision
                < decision.first_tombstone_generation_sequence
                <= self.generation_sequence
            )
            for decision in self.removal_decisions
        ):
            raise AuthoredTransformOutputDispositionError(
                "removal decision revision or tombstone generation is inconsistent"
            )
        current = {x.output_name for x in self.current_decisions}
        removed = {x.output_name for x in self.removal_decisions}
        if current & removed:
            raise AuthoredTransformOutputDispositionError(
                "current decisions and tombstones overlap"
            )
        projections = {
            (x.output_name, x.evidence_class, x.reference_id): x for x in self.evidence_projections
        }
        if len(projections) != len(self.evidence_projections):
            raise AuthoredTransformOutputDispositionError(
                "evidence projection identities duplicate"
            )
        used: set[tuple[str, str, str]] = set()
        for decision in (*self.current_decisions, *self.removal_decisions):
            refs = decision.evidence_references
            for ref in refs:
                key = (decision.output_name, ref.evidence_class, ref.reference_id)
                projection = projections.get(key)
                if projection is None or projection.evidence_sha256 != ref.evidence_sha256:
                    raise AuthoredTransformOutputDispositionError(
                        "table-local evidence projection differs"
                    )
                used.add(key)
            if isinstance(decision, AuthoredCurrentTransformOutputDecisionV1):
                available = {x.evidence_sha256 for x in refs}
                if any(
                    set(claim.evidence_sha256s) - available for claim in decision.semantic_claims
                ):
                    raise AuthoredTransformOutputDispositionError(
                        "semantic claim evidence is not table-local"
                    )
        if used != set(projections):
            raise AuthoredTransformOutputDispositionError(
                "evidence projections are not exact-closure"
            )
        raw = _canonical_bytes(self.to_dict(), "authored corpus")
        if len(raw) > _MAX_BYTES:
            raise AuthoredTransformOutputDispositionError(
                "authored corpus is not representable as one source member"
            )
        try:
            minimum_bundle_bytes = validate_authored_source_bundle_representability_v1(
                corpus_bytes=raw,
                evidence_projection_members=tuple(
                    (projection.source_member_path, projection.projection_bytes)
                    for projection in self.evidence_projections
                ),
            )
        except DispositionEvidenceError as exc:
            raise AuthoredTransformOutputDispositionError(
                "authored corpus is not representable in its mandatory source bundle"
            ) from exc
        object.__setattr__(self, "_corpus_bytes", raw)
        object.__setattr__(
            self,
            "_minimum_source_bundle_canonical_bytes",
            minimum_bundle_bytes,
        )

    def content_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "generation_sequence": self.generation_sequence,
            "prior_authored_authority_sha256": self.prior_authored_authority_sha256,
            "structural_authority_sha256": self.structural_authority_sha256,
            "star_model_contract_sha256": self.star_model_contract_sha256,
            "current_decisions": [x.to_dict() for x in self.current_decisions],
            "removal_decisions": [x.to_dict() for x in self.removal_decisions],
            "evidence_projections": [x.to_dict() for x in self.evidence_projections],
        }

    @property
    def authored_authority_sha256(self) -> str:
        return _sha(self.content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self.content_dict(), "authored_authority_sha256": self.authored_authority_sha256}

    def canonical_bytes(self) -> bytes:
        return self._corpus_bytes

    def validate_successor_of(self, prior: AuthoredTransformOutputDispositionCorpusV1) -> None:
        """Prove one immediate authored revision and immutable tombstone evolution."""
        if type(prior) is not AuthoredTransformOutputDispositionCorpusV1:
            raise AuthoredTransformOutputDispositionError(
                "prior corpus must be an exact authored corpus"
            )
        if (
            self.generation_sequence != prior.generation_sequence + 1
            or self.prior_authored_authority_sha256 != prior.authored_authority_sha256
        ):
            raise AuthoredTransformOutputDispositionError(
                "authored corpus does not bind its exact immediate predecessor"
            )
        prior_current = {item.output_name: item for item in prior.current_decisions}
        current = {item.output_name: item for item in self.current_decisions}
        prior_removed = {item.output_name: item for item in prior.removal_decisions}
        removed = {item.output_name: item for item in self.removal_decisions}
        if set(current) & set(prior_removed):
            raise AuthoredTransformOutputDispositionError(
                "a retained tombstone name reappears as current"
            )
        for output_name, tombstone in prior_removed.items():
            if removed.get(output_name) != tombstone:
                raise AuthoredTransformOutputDispositionError(
                    "a retained authored tombstone was deleted or mutated"
                )

        removed_now = set(prior_current) - set(current)
        added_now = set(current) - set(prior_current)
        expected_removed = set(prior_removed) | removed_now
        if set(removed) != expected_removed:
            raise AuthoredTransformOutputDispositionError(
                "authored tombstones differ from exact removals"
            )
        for output_name in removed_now:
            previous = prior_current[output_name]
            tombstone = removed[output_name]
            if (
                tombstone.prior_authored_decision_revision != previous.authored_decision_revision
                or tombstone.prior_authored_decision_sha256 != previous.authored_decision_sha256
                or tombstone.first_tombstone_generation_sequence != self.generation_sequence
            ):
                raise AuthoredTransformOutputDispositionError(
                    "new tombstone differs from its exact prior authored decision"
                )

        for output_name in added_now:
            if current[output_name].authored_decision_revision != self.generation_sequence:
                raise AuthoredTransformOutputDispositionError(
                    "new authored decision revision differs from its generation"
                )
        for output_name in set(prior_current) & set(current):
            previous = prior_current[output_name]
            candidate = current[output_name]
            if candidate == previous:
                continue
            if (
                candidate.authored_decision_revision != self.generation_sequence
                or candidate.authored_decision_revision <= previous.authored_decision_revision
            ):
                raise AuthoredTransformOutputDispositionError(
                    "changed authored decision revision is not monotonic and current"
                )
            if candidate._decision_body_dict() == previous._decision_body_dict():
                raise AuthoredTransformOutputDispositionError(
                    "authored decision cannot advance by revision alone"
                )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise AuthoredTransformOutputDispositionError("authored corpus bytes are invalid")
        try:
            p = _mapping(
                decode_canonical_json_bytes_v1(raw, persisted=False),
                {
                    "schema_version",
                    "kind",
                    "generation_sequence",
                    "prior_authored_authority_sha256",
                    "structural_authority_sha256",
                    "star_model_contract_sha256",
                    "current_decisions",
                    "removal_decisions",
                    "evidence_projections",
                    "authored_authority_sha256",
                },
                "authored corpus",
            )
        except Exception as exc:
            raise AuthoredTransformOutputDispositionError(
                "authored corpus is not strict canonical JSON"
            ) from exc
        _schema_identity(p, kind=cls.kind, label="authored corpus")
        result = cls(
            cast("int", p["generation_sequence"]),
            cast("str | None", p["prior_authored_authority_sha256"]),
            cast("str", p["structural_authority_sha256"]),
            cast("str", p["star_model_contract_sha256"]),
            tuple(
                AuthoredCurrentTransformOutputDecisionV1.from_dict(x)
                for x in _array(p["current_decisions"], "current decisions")
            ),
            tuple(
                AuthoredTransformOutputRemovalDecisionV1.from_dict(x)
                for x in _array(p["removal_decisions"], "removal decisions")
            ),
            tuple(
                AuthoredTransformOutputEvidenceProjectionV1.from_dict(x)
                for x in _array(p["evidence_projections"], "evidence projections")
            ),
        )
        if p["authored_authority_sha256"] != result.authored_authority_sha256:
            raise AuthoredTransformOutputDispositionError(
                "authored corpus authority digest differs"
            )
        if result.canonical_bytes() != raw:
            raise AuthoredTransformOutputDispositionError(
                "authored corpus differs from its exact canonical reconstruction"
            )
        return result


@dataclass(frozen=True, slots=True)
class CompiledAuthoredTransformOutputDispositionAuthorityV1:
    source_bytes_sha256: str
    corpus: AuthoredTransformOutputDispositionCorpusV1
    entries: tuple[CurrentTransformOutputDispositionV1, ...]

    @property
    def authority_sha256(self) -> str:
        return _sha(
            {
                "schema_version": 1,
                "kind": "nbadb_compiled_authored_transform_output_disposition_authority",
                "source_bytes_sha256": self.source_bytes_sha256,
                "authored_authority_sha256": self.corpus.authored_authority_sha256,
                "entry_sha256s": [x.entry_sha256 for x in self.entries],
            }
        )


def _compile_authored_transform_output_disposition_authority(
    raw: bytes, structural_authority: TransformOutputStructuralAuthorityV1
) -> CompiledAuthoredTransformOutputDispositionAuthorityV1:
    if type(structural_authority) is not TransformOutputStructuralAuthorityV1:
        raise AuthoredTransformOutputDispositionError(
            "structural authority must be exact typed authority"
        )
    corpus = AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(raw)
    if (
        corpus.structural_authority_sha256 != structural_authority.authority_sha256
        or corpus.star_model_contract_sha256 != structural_authority.star_model_contract_sha256
    ):
        raise AuthoredTransformOutputDispositionError("corpus structural authority pins are stale")
    names = tuple(x.output_name for x in corpus.current_decisions)
    if names != structural_authority.output_names:
        raise AuthoredTransformOutputDispositionError(
            "current decisions do not exactly join the structural denominator"
        )
    entries = []
    for decision, table in zip(corpus.current_decisions, structural_authority.tables, strict=True):
        if decision.structural_table_authority_sha256 != table.table_authority_sha256:
            raise AuthoredTransformOutputDispositionError(
                f"structural table pin is stale: {table.output_name}"
            )
        entries.append(
            CurrentTransformOutputDispositionV1(
                table.output_name,
                table.table_family,
                table.table_contract_sha256,
                table.schema_sha256,
                table.transform_sha256,
                table.ordered_column_inventory_sha256,
                table.dependency_inventory_sha256,
                decision.state,
                decision.capability_policy,
                decision.semantic_claims,
                decision.reason_code,
                decision.evidence_references,
                decision.revalidation_triggers,
            )
        )
    return CompiledAuthoredTransformOutputDispositionAuthorityV1(
        hashlib.sha256(raw).hexdigest(), corpus, tuple(entries)
    )


def load_current_transform_output_disposition_authored_authority() -> (
    CompiledAuthoredTransformOutputDispositionAuthorityV1
):
    """Load only the fixed repository resource; callers cannot substitute authority."""
    try:
        path_stat = os.lstat(_RESOURCE)
    except FileNotFoundError as exc:
        raise AuthoredTransformOutputDispositionError(
            "canonical authored disposition resource is absent"
        ) from exc
    except OSError as exc:
        raise AuthoredTransformOutputDispositionError(
            "canonical authored disposition resource is unsafe"
        ) from exc
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_size <= 0
        or path_stat.st_size > _MAX_BYTES
    ):
        raise AuthoredTransformOutputDispositionError(
            "canonical authored disposition resource is unsafe"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(_RESOURCE, flags)
    except FileNotFoundError as exc:
        raise AuthoredTransformOutputDispositionError(
            "canonical authored disposition resource changed before read"
        ) from exc
    except OSError as exc:
        raise AuthoredTransformOutputDispositionError(
            "canonical authored disposition resource is unsafe"
        ) from exc
    try:
        initial_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(initial_stat.st_mode)
            or initial_stat.st_size <= 0
            or initial_stat.st_size > _MAX_BYTES
            or (initial_stat.st_dev, initial_stat.st_ino, initial_stat.st_size)
            != (path_stat.st_dev, path_stat.st_ino, path_stat.st_size)
        ):
            raise AuthoredTransformOutputDispositionError(
                "canonical authored disposition resource is unsafe"
            )
        chunks: list[bytes] = []
        remaining = initial_stat.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise AuthoredTransformOutputDispositionError(
                    "canonical authored disposition resource changed during read"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise AuthoredTransformOutputDispositionError(
                "canonical authored disposition resource changed during read"
            )
        final_stat = os.fstat(descriptor)
    except OSError as exc:
        raise AuthoredTransformOutputDispositionError(
            "canonical authored disposition resource could not be read safely"
        ) from exc
    finally:
        os.close(descriptor)
    if (
        initial_stat.st_dev,
        initial_stat.st_ino,
        initial_stat.st_size,
        initial_stat.st_mtime_ns,
        initial_stat.st_ctime_ns,
    ) != (
        final_stat.st_dev,
        final_stat.st_ino,
        final_stat.st_size,
        final_stat.st_mtime_ns,
        final_stat.st_ctime_ns,
    ):
        raise AuthoredTransformOutputDispositionError(
            "canonical authored disposition resource changed during read"
        )
    raw = b"".join(chunks)
    return _compile_authored_transform_output_disposition_authority(
        raw, compile_current_transform_output_structural_authority()
    )
