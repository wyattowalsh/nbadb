"""Deterministic structural census feeding stable-model candidate review.

This module discovers candidates from already-bound structural authorities.  It
does not author stable/experimental/withheld/rejected dispositions and it never
turns structural coverage into a MODEL-GREEN or DATA-GREEN claim.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import textwrap
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast

from nbadb.contracts.field_fate_structure import (
    FieldFateStructureBlockerV1,
    FieldFateStructureV1,
    ProviderFieldSourceOccurrenceV1,
    RouteFieldBindingV1,
    StorageSinkV1,
)
from nbadb.contracts.stable_model_disposition import (
    ImplementationStatus,
    ModelCandidateKind,
    ModelGateRequirement,
    StableModelCandidateV1,
)
from nbadb.contracts.staging_route_contract import (
    StagingRouteContract,
    StagingRouteContractBundle,
    staging_route_contract_bundle,
    validate_staging_route_contract_bundle,
)
from nbadb.contracts.star_table_contract import (
    StarColumnContract,
    StarModelContractInventory,
    StarTableContract,
    schema_contract_sha256,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import pandera.polars as pa

__all__ = [
    "ANALYTICAL_NEEDS_AUTHORITY_KIND",
    "ANALYTICAL_NEEDS_AUTHORITY_SCHEMA_VERSION",
    "MODEL_CANDIDATE_CENSUS_KIND",
    "MODEL_CANDIDATE_CENSUS_SCHEMA_VERSION",
    "AnalyticalNeedV1",
    "AnalyticalNeedsAuthorityV1",
    "ModelCandidateCensusBlockerV1",
    "ModelCandidateCensusError",
    "ModelCandidateCensusEvidenceV1",
    "ModelCandidateCensusV1",
    "canonical_analytical_needs_authority_v1",
    "compile_current_model_candidate_census",
    "compile_model_candidate_census",
    "parse_model_candidate_census",
    "validate_model_candidate_census",
]

MODEL_CANDIDATE_CENSUS_SCHEMA_VERSION = 1
MODEL_CANDIDATE_CENSUS_KIND = "nbadb_structural_model_candidate_census"
ANALYTICAL_NEEDS_AUTHORITY_SCHEMA_VERSION = 1
ANALYTICAL_NEEDS_AUTHORITY_KIND = "nbadb_analytical_needs_authority"

type AnalyticalModelFamily = Literal[
    "forecast",
    "prospect_value",
    "rapm",
    "rating",
    "wpa",
    "xfg",
]
type EvidenceKind = Literal[
    "analytical_need",
    "conditional_staging",
    "provider_result_occurrence",
    "public_transform",
    "raw_request_authority",
    "staging_route",
]
type AnalyticalNeedsState = Literal["absent", "foreign", "present"]
type ZeroFieldResultContractState = Literal[
    "explicit_named_zero_columns",
    "provider_result_contract_unknown",
]

_ANALYTICAL_MODEL_FAMILIES = frozenset(
    {"forecast", "prospect_value", "rapm", "rating", "wpa", "xfg"}
)
_EVIDENCE_KINDS = frozenset(
    {
        "analytical_need",
        "conditional_staging",
        "provider_result_occurrence",
        "public_transform",
        "raw_request_authority",
        "staging_route",
    }
)
_BLOCKER_CODES = frozenset(
    {
        "analytical_needs_authority_absent",
        "analytical_needs_authority_foreign",
        "analytical_need_dependency_unresolved",
        "lossless_storage_binding_unresolved",
        "route_storage_mismatch",
        "source_authority_unavailable",
        "source_result_contract_zero_fields",
        "staging_route_zero_storage",
        "star_dependency_unresolved",
        "star_structural_blocker",
    }
)
_KIND_LAYER = {
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
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_EXACT_NAMED_ZERO_COLUMN_RESULT_CONTRACTS = frozenset(
    {
        (
            "defense_hub:stg_defense_hub_stat10:1",
            "stats",
            "DefenseHub",
            "DefenseHub",
            "DefenseHubStat10",
            1,
            "DefenseHubStat10",
            1,
            "classified_provider_columns_absent",
        ),
        (
            "scoreboard_v2:stg_scoreboard_win_probability:9",
            "stats",
            "ScoreboardV2",
            "ScoreboardV2",
            "WinProbability",
            9,
            "WinProbability",
            9,
            "classified_provider_columns_absent",
        ),
    }
)
_EXACT_VIDEO_STATS_LOSSLESS_RESULT_CONTRACTS = frozenset(
    {
        (
            "video_details:stg_video_details:0",
            "stg_video_details",
            "stats",
            "VideoDetails",
            "VideoDetails",
            "videodetails",
            None,
            None,
            None,
            0,
            "classified_provider_packet_absent",
        ),
        (
            "video_details_asset:stg_video_details_asset:0",
            "stg_video_details_asset",
            "stats",
            "VideoDetailsAsset",
            "VideoDetailsAsset",
            "videodetailsasset",
            None,
            None,
            None,
            0,
            "classified_provider_packet_absent",
        ),
        (
            "video_events:stg_video_events:0",
            "stg_video_events",
            "stats",
            "VideoEvents",
            "VideoEvents",
            "videoevents",
            None,
            None,
            None,
            0,
            "classified_provider_packet_absent",
        ),
        (
            "video_events_asset:stg_video_events_asset:0",
            "stg_video_events_asset",
            "stats",
            "VideoEventsAsset",
            "VideoEventsAsset",
            "videoeventsasset",
            None,
            None,
            None,
            0,
            "classified_provider_packet_absent",
        ),
    }
)


class ModelCandidateCensusError(ValueError):
    """The structural candidate census or one of its authorities is invalid."""


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
        raise ModelCandidateCensusError("candidate census value is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ModelCandidateCensusError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise ModelCandidateCensusError(f"{field_name} must be a safe nonempty identifier")
    return value


def _exact_mapping(
    value: object,
    expected_keys: frozenset[str],
    *,
    label: str,
) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ModelCandidateCensusError(f"{label} must be an exact object")
    payload = cast("Mapping[str, object]", value)
    if frozenset(payload) != expected_keys or any(type(key) is not str for key in payload):
        raise ModelCandidateCensusError(f"{label} schema is not exact")
    return payload


def _string_tuple(value: object, *, field_name: str, allow_empty: bool = True) -> tuple[str, ...]:
    if type(value) is not list:
        raise ModelCandidateCensusError(f"{field_name} must be an exact array")
    result = tuple(_require_id(item, field_name=field_name) for item in value)
    if (not allow_empty and not result) or result != tuple(sorted(set(result))):
        raise ModelCandidateCensusError(f"{field_name} must be sorted and unique")
    return result


def _sha_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise ModelCandidateCensusError(f"{field_name} must be an exact array")
    result = tuple(_require_sha256(item, field_name=field_name) for item in value)
    if not result or result != tuple(sorted(set(result))):
        raise ModelCandidateCensusError(f"{field_name} must be nonempty, sorted, and unique")
    return result


def _canonical_payload_json(value: object) -> str:
    if type(value) is not dict:
        raise ModelCandidateCensusError("candidate structural payload must be an object")
    return _canonical_bytes(value).decode("utf-8")


def _decode_payload_json(value: str) -> Mapping[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ModelCandidateCensusError("candidate structural payload is invalid JSON") from exc
    if type(payload) is not dict or _canonical_payload_json(payload) != value:
        raise ModelCandidateCensusError("candidate structural payload is not canonical")
    return cast("Mapping[str, object]", payload)


@dataclass(frozen=True, slots=True, order=True)
class AnalyticalNeedV1:
    """One explicit analytical need, independent of implemented output names."""

    need_id: str
    model_family: AnalyticalModelFamily
    analytical_question: str
    required_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.need_id, field_name="analytical need_id")
        if self.model_family not in _ANALYTICAL_MODEL_FAMILIES:
            raise ModelCandidateCensusError("analytical model_family is unsupported")
        if self.need_id != self.model_family:
            raise ModelCandidateCensusError("analytical need_id must equal its v1 model family")
        if (
            type(self.analytical_question) is not str
            or not self.analytical_question.strip()
            or self.analytical_question != self.analytical_question.strip()
        ):
            raise ModelCandidateCensusError("analytical question must be an exact nonempty string")
        if self.required_candidate_ids != tuple(sorted(set(self.required_candidate_ids))):
            raise ModelCandidateCensusError(
                "analytical required_candidate_ids must be sorted and unique"
            )
        for candidate_id in self.required_candidate_ids:
            _require_id(candidate_id, field_name="analytical required_candidate_ids")

    @property
    def candidate_id(self) -> str:
        return f"experimental_model:{self.model_family}"

    @property
    def need_sha256(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "need_id": self.need_id,
            "model_family": self.model_family,
            "analytical_question": self.analytical_question,
            "required_candidate_ids": list(self.required_candidate_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _exact_mapping(
            value,
            frozenset({"need_id", "model_family", "analytical_question", "required_candidate_ids"}),
            label="analytical need",
        )
        return cls(
            need_id=cast("str", payload["need_id"]),
            model_family=cast("AnalyticalModelFamily", payload["model_family"]),
            analytical_question=cast("str", payload["analytical_question"]),
            required_candidate_ids=_string_tuple(
                payload["required_candidate_ids"], field_name="analytical required_candidate_ids"
            ),
        )


@dataclass(frozen=True, slots=True)
class AnalyticalNeedsAuthorityV1:
    """Versioned explicit input for experimental analytical-model candidates."""

    authority_id: str
    needs: tuple[AnalyticalNeedV1, ...]

    schema_version: ClassVar[int] = ANALYTICAL_NEEDS_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = ANALYTICAL_NEEDS_AUTHORITY_KIND

    def __post_init__(self) -> None:
        if self.authority_id != "nbadb:analytical-needs:v1":
            raise ModelCandidateCensusError("analytical-needs authority_id is foreign")
        if type(self.needs) is not tuple or any(
            type(item) is not AnalyticalNeedV1 for item in self.needs
        ):
            raise ModelCandidateCensusError("analytical needs must be an exact typed tuple")
        if self.needs != tuple(sorted(self.needs, key=lambda item: item.need_id)):
            raise ModelCandidateCensusError("analytical needs must be sorted")
        if {item.model_family for item in self.needs} != _ANALYTICAL_MODEL_FAMILIES:
            raise ModelCandidateCensusError("analytical-needs v1 family inventory is incomplete")
        if len({item.need_id for item in self.needs}) != len(self.needs):
            raise ModelCandidateCensusError("analytical need identities overlap")

    @property
    def authority_sha256(self) -> str:
        return _digest(self._content_dict())

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_id": self.authority_id,
            "needs": [item.to_dict() for item in self.needs],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "authority_sha256": self.authority_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _exact_mapping(
            value,
            frozenset({"schema_version", "kind", "authority_id", "needs", "authority_sha256"}),
            label="analytical-needs authority",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(payload["needs"]) is not list
        ):
            raise ModelCandidateCensusError("analytical-needs authority identity is invalid")
        rebuilt = cls(
            authority_id=cast("str", payload["authority_id"]),
            needs=tuple(AnalyticalNeedV1.from_dict(item) for item in payload["needs"]),
        )
        if payload != rebuilt.to_dict():
            raise ModelCandidateCensusError("analytical-needs authority digest is stale")
        return rebuilt

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_object(raw, label="analytical-needs authority"))


def canonical_analytical_needs_authority_v1() -> AnalyticalNeedsAuthorityV1:
    """Return the explicit v1 analytical-needs input; never infer from outputs."""

    questions = {
        "forecast": "Estimate future player and team outcomes with time-aware uncertainty.",
        "prospect_value": "Estimate prospect value from pre-NBA and early-career evidence.",
        "rapm": "Estimate regularized adjusted plus-minus from possession-level contexts.",
        "rating": "Estimate time-aware team and player strength ratings.",
        "wpa": "Estimate event-level win probability added from game-state transitions.",
        "xfg": "Estimate shot-level expected field-goal probability from spatial context.",
    }
    return AnalyticalNeedsAuthorityV1(
        authority_id="nbadb:analytical-needs:v1",
        needs=tuple(
            AnalyticalNeedV1(
                need_id=family,
                model_family=cast("AnalyticalModelFamily", family),
                analytical_question=question,
            )
            for family, question in sorted(questions.items())
        ),
    )


@dataclass(frozen=True, slots=True, order=True)
class ModelCandidateCensusEvidenceV1:
    """Visible canonical evidence behind one stable-model candidate row."""

    candidate_id: str
    evidence_kind: EvidenceKind
    authority_ids: tuple[str, ...]
    authority_sha256s: tuple[str, ...]
    structural_payload_json: str

    def __post_init__(self) -> None:
        _require_id(self.candidate_id, field_name="evidence candidate_id")
        if self.evidence_kind not in _EVIDENCE_KINDS:
            raise ModelCandidateCensusError("candidate evidence_kind is unsupported")
        if not self.authority_ids or self.authority_ids != tuple(sorted(set(self.authority_ids))):
            raise ModelCandidateCensusError(
                "candidate authority_ids must be nonempty, sorted, and unique"
            )
        for authority_id in self.authority_ids:
            _require_id(authority_id, field_name="candidate authority_ids")
        if not self.authority_sha256s or self.authority_sha256s != tuple(
            sorted(set(self.authority_sha256s))
        ):
            raise ModelCandidateCensusError(
                "candidate authority_sha256s must be nonempty, sorted, and unique"
            )
        for digest in self.authority_sha256s:
            _require_sha256(digest, field_name="candidate authority_sha256s")
        payload = _decode_payload_json(self.structural_payload_json)
        if payload.get("candidate_id") != self.candidate_id:
            raise ModelCandidateCensusError("candidate structural payload is rebound")

    @property
    def structural_sha256(self) -> str:
        return hashlib.sha256(self.structural_payload_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "evidence_kind": self.evidence_kind,
            "authority_ids": list(self.authority_ids),
            "authority_sha256s": list(self.authority_sha256s),
            "structural_payload": dict(_decode_payload_json(self.structural_payload_json)),
            "structural_sha256": self.structural_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _exact_mapping(
            value,
            frozenset(
                {
                    "candidate_id",
                    "evidence_kind",
                    "authority_ids",
                    "authority_sha256s",
                    "structural_payload",
                    "structural_sha256",
                }
            ),
            label="candidate evidence",
        )
        rebuilt = cls(
            candidate_id=cast("str", payload["candidate_id"]),
            evidence_kind=cast("EvidenceKind", payload["evidence_kind"]),
            authority_ids=_string_tuple(
                payload["authority_ids"], field_name="candidate authority_ids", allow_empty=False
            ),
            authority_sha256s=_sha_tuple(
                payload["authority_sha256s"], field_name="candidate authority_sha256s"
            ),
            structural_payload_json=_canonical_payload_json(payload["structural_payload"]),
        )
        if payload != rebuilt.to_dict():
            raise ModelCandidateCensusError("candidate evidence digest is stale")
        return rebuilt


@dataclass(frozen=True, slots=True, order=True)
class ModelCandidateCensusBlockerV1:
    """One exact unresolved structural census condition."""

    blocker_id: str
    subject_id: str
    code: str
    evidence_sha256: str
    resolution_requirement: str

    def __post_init__(self) -> None:
        _require_id(self.blocker_id, field_name="census blocker_id")
        _require_id(self.subject_id, field_name="census blocker subject_id")
        if self.code not in _BLOCKER_CODES:
            raise ModelCandidateCensusError("census blocker code is unsupported")
        _require_sha256(self.evidence_sha256, field_name="census blocker evidence_sha256")
        if (
            type(self.resolution_requirement) is not str
            or not self.resolution_requirement.strip()
            or self.resolution_requirement != self.resolution_requirement.strip()
        ):
            raise ModelCandidateCensusError(
                "census blocker resolution_requirement must be exact and nonempty"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "blocker_id": self.blocker_id,
            "subject_id": self.subject_id,
            "code": self.code,
            "evidence_sha256": self.evidence_sha256,
            "resolution_requirement": self.resolution_requirement,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _exact_mapping(
            value,
            frozenset(
                {
                    "blocker_id",
                    "subject_id",
                    "code",
                    "evidence_sha256",
                    "resolution_requirement",
                }
            ),
            label="candidate census blocker",
        )
        return cls(
            blocker_id=cast("str", payload["blocker_id"]),
            subject_id=cast("str", payload["subject_id"]),
            code=cast("str", payload["code"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
            resolution_requirement=cast("str", payload["resolution_requirement"]),
        )


def _validate_dependency_graph(candidates: Sequence[StableModelCandidateV1]) -> None:
    by_id = {item.candidate_id: item for item in candidates}
    if len(by_id) != len(candidates):
        raise ModelCandidateCensusError("candidate identities overlap")
    for candidate in candidates:
        unknown = sorted(set(candidate.dependency_ids) - set(by_id))
        if unknown:
            raise ModelCandidateCensusError(
                f"candidate has unknown dependencies: {candidate.candidate_id}"
            )
        if candidate.candidate_kind == "source" and candidate.dependency_ids:
            raise ModelCandidateCensusError("source candidate cannot have dependencies")
        layer = _KIND_LAYER[candidate.candidate_kind]
        if any(
            _KIND_LAYER[by_id[item].candidate_kind] > layer for item in candidate.dependency_ids
        ):
            raise ModelCandidateCensusError("candidate dependency layer is inverted")

    states: dict[str, int] = {}

    def visit(candidate_id: str) -> None:
        state = states.get(candidate_id, 0)
        if state == 1:
            raise ModelCandidateCensusError("candidate dependency graph contains a cycle")
        if state == 2:
            return
        states[candidate_id] = 1
        for dependency_id in by_id[candidate_id].dependency_ids:
            visit(dependency_id)
        states[candidate_id] = 2

    for candidate_id in sorted(by_id):
        visit(candidate_id)


@dataclass(frozen=True, slots=True)
class ModelCandidateCensusV1:
    """Canonical candidate/evidence/blocker inventory; never a semantic decision."""

    field_fate_structure_sha256: str
    staging_route_contract_sha256: str
    star_model_contract_sha256: str
    conditional_staging_authority_sha256: str
    raw_request_authority_sha256: str
    analytical_needs_state: AnalyticalNeedsState
    analytical_needs_authority_sha256: str | None
    candidates: tuple[StableModelCandidateV1, ...]
    evidence: tuple[ModelCandidateCensusEvidenceV1, ...]
    blockers: tuple[ModelCandidateCensusBlockerV1, ...]

    schema_version: ClassVar[int] = MODEL_CANDIDATE_CENSUS_SCHEMA_VERSION
    kind: ClassVar[str] = MODEL_CANDIDATE_CENSUS_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "field_fate_structure_sha256",
            "staging_route_contract_sha256",
            "star_model_contract_sha256",
            "conditional_staging_authority_sha256",
            "raw_request_authority_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if self.analytical_needs_state not in {"absent", "foreign", "present"}:
            raise ModelCandidateCensusError("analytical_needs_state is unsupported")
        if self.analytical_needs_state == "present":
            _require_sha256(
                self.analytical_needs_authority_sha256,
                field_name="analytical_needs_authority_sha256",
            )
        elif self.analytical_needs_authority_sha256 is not None:
            raise ModelCandidateCensusError(
                "absent/foreign analytical needs cannot carry an authority digest"
            )
        if type(self.candidates) is not tuple or any(
            type(item) is not StableModelCandidateV1 for item in self.candidates
        ):
            raise ModelCandidateCensusError("candidates must be an exact typed tuple")
        if self.candidates != tuple(sorted(self.candidates, key=lambda item: item.candidate_id)):
            raise ModelCandidateCensusError("candidates must be sorted")
        _validate_dependency_graph(self.candidates)
        if type(self.evidence) is not tuple or any(
            type(item) is not ModelCandidateCensusEvidenceV1 for item in self.evidence
        ):
            raise ModelCandidateCensusError("candidate evidence must be an exact typed tuple")
        if self.evidence != tuple(sorted(self.evidence, key=lambda item: item.candidate_id)):
            raise ModelCandidateCensusError("candidate evidence must be sorted")
        if len({item.candidate_id for item in self.evidence}) != len(self.evidence):
            raise ModelCandidateCensusError("candidate evidence identities overlap")
        evidence_by_id = {item.candidate_id: item for item in self.evidence}
        if set(evidence_by_id) != {item.candidate_id for item in self.candidates}:
            raise ModelCandidateCensusError("candidate evidence inventory is incomplete")
        for candidate in self.candidates:
            item = evidence_by_id[candidate.candidate_id]
            payload = _decode_payload_json(item.structural_payload_json)
            if (
                candidate.structural_sha256 != item.structural_sha256
                or candidate.evidence_sha256s != item.authority_sha256s
                or payload.get("candidate_kind") != candidate.candidate_kind
                or payload.get("gate_requirement") != candidate.gate_requirement
                or payload.get("dependency_ids") != list(candidate.dependency_ids)
                or payload.get("implementation_status") != candidate.implementation_status
                or payload.get("implementation_sha256") != candidate.implementation_sha256
            ):
                raise ModelCandidateCensusError("candidate differs from its exact evidence")
        if type(self.blockers) is not tuple or any(
            type(item) is not ModelCandidateCensusBlockerV1 for item in self.blockers
        ):
            raise ModelCandidateCensusError("census blockers must be an exact typed tuple")
        if self.blockers != tuple(sorted(self.blockers)):
            raise ModelCandidateCensusError("census blockers must be sorted")
        if len({item.blocker_id for item in self.blockers}) != len(self.blockers):
            raise ModelCandidateCensusError("census blocker identities overlap")
        candidate_ids = {item.candidate_id for item in self.candidates}
        if any(
            item.subject_id != "census" and item.subject_id not in candidate_ids
            for item in self.blockers
        ):
            raise ModelCandidateCensusError("census blocker names a foreign candidate")

    @property
    def candidate_inventory_sha256(self) -> str:
        return _digest([item.to_dict() for item in self.candidates])

    @property
    def evidence_inventory_sha256(self) -> str:
        return _digest([item.to_dict() for item in self.evidence])

    @property
    def blocker_inventory_sha256(self) -> str:
        return _digest([item.to_dict() for item in self.blockers])

    @property
    def candidate_source_authority_sha256(self) -> str:
        return _digest(
            {
                "schema_version": self.schema_version,
                "kind": "nbadb_model_candidate_source_authority",
                "field_fate_structure_sha256": self.field_fate_structure_sha256,
                "staging_route_contract_sha256": self.staging_route_contract_sha256,
                "star_model_contract_sha256": self.star_model_contract_sha256,
                "conditional_staging_authority_sha256": (self.conditional_staging_authority_sha256),
                "raw_request_authority_sha256": self.raw_request_authority_sha256,
                "analytical_needs_state": self.analytical_needs_state,
                "analytical_needs_authority_sha256": self.analytical_needs_authority_sha256,
                "candidate_inventory_sha256": self.candidate_inventory_sha256,
                "evidence_inventory_sha256": self.evidence_inventory_sha256,
                "blocker_inventory_sha256": self.blocker_inventory_sha256,
            }
        )

    def _content_dict(self) -> dict[str, object]:
        candidate_counts = Counter(item.candidate_kind for item in self.candidates)
        evidence_counts = Counter(item.evidence_kind for item in self.evidence)
        blocker_counts = Counter(item.code for item in self.blockers)
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "field_fate_structure_sha256": self.field_fate_structure_sha256,
            "staging_route_contract_sha256": self.staging_route_contract_sha256,
            "star_model_contract_sha256": self.star_model_contract_sha256,
            "conditional_staging_authority_sha256": self.conditional_staging_authority_sha256,
            "raw_request_authority_sha256": self.raw_request_authority_sha256,
            "analytical_needs_state": self.analytical_needs_state,
            "analytical_needs_authority_sha256": self.analytical_needs_authority_sha256,
            "candidate_source_authority_sha256": self.candidate_source_authority_sha256,
            "candidate_inventory_sha256": self.candidate_inventory_sha256,
            "evidence_inventory_sha256": self.evidence_inventory_sha256,
            "blocker_inventory_sha256": self.blocker_inventory_sha256,
            "summary": {
                "candidate_count": len(self.candidates),
                "candidate_kind_counts": dict(sorted(candidate_counts.items())),
                "evidence_kind_counts": dict(sorted(evidence_counts.items())),
                "implemented_candidate_count": sum(
                    item.implementation_status == "implemented" for item in self.candidates
                ),
                "missing_candidate_count": sum(
                    item.implementation_status == "missing" for item in self.candidates
                ),
                "blocker_count": len(self.blockers),
                "blocker_code_counts": dict(sorted(blocker_counts.items())),
                "model_green": "not_evaluated_by_structural_census",
                "data_green": "not_evaluated_by_structural_census",
            },
            "candidates": [item.to_dict() for item in self.candidates],
            "evidence": [item.to_dict() for item in self.evidence],
            "blockers": [item.to_dict() for item in self.blockers],
        }

    @property
    def census_sha256(self) -> str:
        return _digest(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "census_sha256": self.census_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_stable_candidates(self) -> tuple[StableModelCandidateV1, ...]:
        """Return the exact candidate rows for the separate disposition compiler."""

        return self.candidates

    @classmethod
    def from_dict(cls, value: object) -> Self:
        keys = frozenset(
            {
                "schema_version",
                "kind",
                "field_fate_structure_sha256",
                "staging_route_contract_sha256",
                "star_model_contract_sha256",
                "conditional_staging_authority_sha256",
                "raw_request_authority_sha256",
                "analytical_needs_state",
                "analytical_needs_authority_sha256",
                "candidate_source_authority_sha256",
                "candidate_inventory_sha256",
                "evidence_inventory_sha256",
                "blocker_inventory_sha256",
                "summary",
                "candidates",
                "evidence",
                "blockers",
                "census_sha256",
            }
        )
        payload = _exact_mapping(value, keys, label="model candidate census")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
            or type(payload["candidates"]) is not list
            or type(payload["evidence"]) is not list
            or type(payload["blockers"]) is not list
        ):
            raise ModelCandidateCensusError("model candidate census identity is invalid")
        needs_sha = payload["analytical_needs_authority_sha256"]
        if needs_sha is not None and type(needs_sha) is not str:
            raise ModelCandidateCensusError("analytical-needs digest must be a string or null")
        rebuilt = cls(
            field_fate_structure_sha256=cast("str", payload["field_fate_structure_sha256"]),
            staging_route_contract_sha256=cast("str", payload["staging_route_contract_sha256"]),
            star_model_contract_sha256=cast("str", payload["star_model_contract_sha256"]),
            conditional_staging_authority_sha256=cast(
                "str", payload["conditional_staging_authority_sha256"]
            ),
            raw_request_authority_sha256=cast("str", payload["raw_request_authority_sha256"]),
            analytical_needs_state=cast("AnalyticalNeedsState", payload["analytical_needs_state"]),
            analytical_needs_authority_sha256=needs_sha,
            candidates=tuple(
                StableModelCandidateV1.from_dict(item) for item in payload["candidates"]
            ),
            evidence=tuple(
                ModelCandidateCensusEvidenceV1.from_dict(item) for item in payload["evidence"]
            ),
            blockers=tuple(
                ModelCandidateCensusBlockerV1.from_dict(item) for item in payload["blockers"]
            ),
        )
        if payload != rebuilt.to_dict():
            raise ModelCandidateCensusError("model candidate census digest or summary is stale")
        return rebuilt

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_object(raw, label="model candidate census"))


def _decode_canonical_object(raw: bytes, *, label: str) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw:
        raise ModelCandidateCensusError(f"{label} bytes must be exact and nonempty")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ModelCandidateCensusError(f"{label} repeats JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ModelCandidateCensusError(f"{label} contains non-finite JSON: {value}")

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except ModelCandidateCensusError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelCandidateCensusError(f"{label} bytes are invalid JSON") from exc
    if type(value) is not dict or _canonical_bytes(value) != raw:
        raise ModelCandidateCensusError(f"{label} bytes are not canonical")
    return cast("Mapping[str, object]", value)


def _blocker(
    *,
    subject_id: str,
    code: str,
    evidence_sha256: str,
    resolution_requirement: str,
    discriminator: str,
) -> ModelCandidateCensusBlockerV1:
    suffix = _digest(
        {
            "subject_id": subject_id,
            "code": code,
            "evidence_sha256": evidence_sha256,
            "discriminator": discriminator,
        }
    )[:24]
    return ModelCandidateCensusBlockerV1(
        blocker_id=f"census_blocker:{code}:{suffix}",
        subject_id=subject_id,
        code=code,
        evidence_sha256=evidence_sha256,
        resolution_requirement=resolution_requirement,
    )


def _candidate_pair(
    *,
    candidate_id: str,
    candidate_kind: ModelCandidateKind,
    gate_requirement: ModelGateRequirement,
    dependency_ids: Sequence[str],
    evidence_kind: EvidenceKind,
    authority_ids: Sequence[str],
    authority_sha256s: Sequence[str],
    implementation_status: ImplementationStatus,
    implementation_sha256: str | None,
    specific_payload: Mapping[str, object],
) -> tuple[StableModelCandidateV1, ModelCandidateCensusEvidenceV1]:
    dependencies = tuple(sorted(set(dependency_ids)))
    authority_id_tuple = tuple(sorted(set(authority_ids)))
    authority_sha_tuple = tuple(sorted(set(authority_sha256s)))
    payload = {
        "schema_version": 1,
        "kind": "nbadb_model_candidate_structural_payload",
        "candidate_id": candidate_id,
        "candidate_kind": candidate_kind,
        "gate_requirement": gate_requirement,
        "dependency_ids": list(dependencies),
        "implementation_status": implementation_status,
        "implementation_sha256": implementation_sha256,
        **dict(specific_payload),
    }
    evidence = ModelCandidateCensusEvidenceV1(
        candidate_id=candidate_id,
        evidence_kind=evidence_kind,
        authority_ids=authority_id_tuple,
        authority_sha256s=authority_sha_tuple,
        structural_payload_json=_canonical_payload_json(payload),
    )
    candidate = StableModelCandidateV1(
        candidate_id=candidate_id,
        candidate_kind=candidate_kind,
        gate_requirement=gate_requirement,
        structural_sha256=evidence.structural_sha256,
        dependency_ids=dependencies,
        evidence_sha256s=authority_sha_tuple,
        implementation_status=implementation_status,
        implementation_sha256=implementation_sha256,
    )
    return candidate, evidence


def _source_candidate_id(source_family: str, endpoint_id: str, result_set_ordinal: int) -> str:
    return f"source:{source_family}:{endpoint_id}:{result_set_ordinal:04d}"


def _route_result_ordinal(route: StagingRouteContract) -> int:
    ordinal = (
        route.provider_result_set_ordinal
        if route.provider_result_set_ordinal is not None
        else route.canonical_result_set_ordinal
    )
    if type(ordinal) is not int or ordinal < 0:
        raise ModelCandidateCensusError("zero-field route lacks a canonical result ordinal")
    return ordinal


def _zero_field_result_contract_state(
    routes: Sequence[StagingRouteContract],
) -> ZeroFieldResultContractState:
    """Classify only the two exact provider-declared zero-column results as terminal.

    A named empty ``expected_data`` result is materially different from an
    endpoint whose complete result inventory is unknown.  Keep this admission
    deliberately exact so a new or mutated zero-column route remains blocked
    until its pinned provider contract is reviewed.
    """

    if len(routes) != 1:
        return "provider_result_contract_unknown"
    route = routes[0]
    identity = (
        route.route_id,
        route.source_family,
        route.provider_endpoint_id,
        route.provider_runtime_class,
        route.provider_result_set_name,
        route.provider_result_set_ordinal,
        route.canonical_result_set_name,
        route.canonical_result_set_ordinal,
        route.classified_status,
    )
    if not route.provider_columns and identity in _EXACT_NAMED_ZERO_COLUMN_RESULT_CONTRACTS:
        return "explicit_named_zero_columns"
    return "provider_result_contract_unknown"


def _is_exact_video_stats_lossless_result_contract(
    routes: Sequence[StagingRouteContract],
) -> bool:
    if len(routes) != 1:
        return False
    route = routes[0]
    identity = (
        route.route_id,
        route.staging_key,
        route.source_family,
        route.provider_endpoint_id,
        route.provider_runtime_class,
        route.provider_endpoint_slug,
        route.provider_result_set_name,
        route.provider_result_set_ordinal,
        route.canonical_result_set_name,
        route.canonical_result_set_ordinal,
        route.classified_status,
    )
    return not route.provider_columns and identity in _EXACT_VIDEO_STATS_LOSSLESS_RESULT_CONTRACTS


def _stats_lossless_conditional_authority() -> tuple[dict[str, object], str]:
    rows, authority_sha256 = _conditional_staging_rows()
    matching = [
        row
        for row in rows
        if row["staging_key"] == "stg_nba_api_lossless_result_cells"
        and row["conditional_kind"] == "stats_additive_result_cells"
    ]
    if len(matching) != 1:
        raise ModelCandidateCensusError("stats lossless conditional authority drifted")
    return matching[0], authority_sha256


def _compile_source_candidates(
    structure: FieldFateStructureV1,
    routes: StagingRouteContractBundle,
) -> tuple[
    list[StableModelCandidateV1],
    list[ModelCandidateCensusEvidenceV1],
    list[ModelCandidateCensusBlockerV1],
    dict[str, str],
    dict[str, str],
]:
    occurrences_by_group: dict[tuple[str, str, int], list[ProviderFieldSourceOccurrenceV1]] = (
        defaultdict(list)
    )
    for occurrence in structure.provider_sources.occurrences:
        occurrences_by_group[
            (occurrence.source_family, occurrence.endpoint_id, occurrence.result_set_ordinal)
        ].append(occurrence)
    expansion_by_id = {
        item.source_occurrence_id: item for item in structure.route_bindings.source_expansions
    }
    binding_by_id = structure.route_bindings.by_binding_id
    lossless_by_source = {item.source_occurrence_id: item for item in structure.lossless_bindings}
    blockers_by_source: dict[str, list[FieldFateStructureBlockerV1]] = defaultdict(list)
    for item in structure.blockers:
        blockers_by_source[item.source_occurrence_id].append(item)

    candidates: list[StableModelCandidateV1] = []
    evidence_rows: list[ModelCandidateCensusEvidenceV1] = []
    blockers: list[ModelCandidateCensusBlockerV1] = []
    candidate_by_occurrence: dict[str, str] = {}
    zero_candidate_by_route: dict[str, str] = {}

    for (source_family, endpoint_id, result_ordinal), raw_occurrences in sorted(
        occurrences_by_group.items()
    ):
        occurrences = sorted(raw_occurrences, key=lambda item: item.occurrence_id)
        result_names = {item.result_set_name for item in occurrences}
        if len(result_names) != 1:
            raise ModelCandidateCensusError("source group spans result-set names")
        candidate_id = _source_candidate_id(source_family, endpoint_id, result_ordinal)
        for occurrence in occurrences:
            candidate_by_occurrence[occurrence.occurrence_id] = candidate_id
        expansions = [expansion_by_id[item.occurrence_id] for item in occurrences]
        route_binding_ids = sorted(
            {binding_id for expansion in expansions for binding_id in expansion.binding_ids}
        )
        route_ids = sorted({binding_by_id[item].route_id for item in route_binding_ids})
        lossless = [
            lossless_by_source[item.occurrence_id]
            for item in occurrences
            if item.occurrence_id in lossless_by_source
        ]
        group_blockers = [
            blocker
            for item in occurrences
            for blocker in blockers_by_source.get(item.occurrence_id, ())
        ]
        routed_field_count = sum(bool(item.binding_ids) for item in expansions)
        wide_unrouted_count = len(expansions) - routed_field_count
        unresolved_lossless_count = sum(
            item.blocker_kind == "lossless_storage_binding_unresolved" for item in group_blockers
        )
        source_authority_blocker_count = sum(
            item.blocker_kind == "source_authority_unavailable" for item in group_blockers
        )
        implementation_binding_sha256 = _digest(
            {
                "route_binding_ids": route_binding_ids,
                "lossless_binding_sha256s": sorted(item.binding_sha256 for item in lossless),
            }
        )
        implemented = not group_blockers and (
            routed_field_count + len(lossless) == len(occurrences)
        )
        implementation_sha256 = implementation_binding_sha256 if implemented else None
        authority_ids = [item.occurrence_id for item in occurrences]
        authority_sha256s = [
            structure.provider_sources.identity_sha256,
            *(item.occurrence_sha256 for item in occurrences),
            *(binding_by_id[item].route_contract_sha256 for item in route_binding_ids),
            *(item.sink_authority_sha256 for item in lossless),
            *(item.binding_evidence_sha256 for item in lossless),
            *(item.evidence_sha256 for item in group_blockers),
        ]
        candidate, evidence = _candidate_pair(
            candidate_id=candidate_id,
            candidate_kind="source",
            gate_requirement="lossless_required",
            dependency_ids=(),
            evidence_kind="provider_result_occurrence",
            authority_ids=authority_ids,
            authority_sha256s=authority_sha256s,
            implementation_status="implemented" if implemented else "missing",
            implementation_sha256=implementation_sha256,
            specific_payload={
                "source_family": source_family,
                "endpoint_id": endpoint_id,
                "result_set_name": next(iter(result_names)),
                "result_set_ordinal": result_ordinal,
                "field_occurrence_ids": [item.occurrence_id for item in occurrences],
                "field_count": len(occurrences),
                "routed_field_count": routed_field_count,
                "wide_unrouted_field_count": wide_unrouted_count,
                "lossless_field_binding_count": len(lossless),
                "unresolved_lossless_binding_count": unresolved_lossless_count,
                "source_authority_blocker_count": source_authority_blocker_count,
                "route_binding_ids": route_binding_ids,
                "route_ids": route_ids,
                "lossless_binding_ids": sorted(item.binding_id for item in lossless),
                "zero_wide_route": not route_binding_ids,
                "explicit_zero_field_contract": False,
                "implementation_binding_sha256": implementation_binding_sha256,
            },
        )
        candidates.append(candidate)
        evidence_rows.append(evidence)
        for item in group_blockers:
            blockers.append(
                _blocker(
                    subject_id=candidate_id,
                    code=item.blocker_kind,
                    evidence_sha256=item.evidence_sha256,
                    resolution_requirement=item.resolution_requirement,
                    discriminator=item.blocker_id,
                )
            )

    represented_groups = set(occurrences_by_group)
    zero_routes_by_group: dict[tuple[str, str, int], list[StagingRouteContract]] = defaultdict(list)
    for route in routes.routes:
        result_ordinal = _route_result_ordinal(route)
        key = (route.source_family, route.provider_endpoint_id, result_ordinal)
        if key not in represented_groups and not route.provider_columns:
            zero_routes_by_group[key].append(route)
    stats_lossless_conditional: tuple[dict[str, object], str] | None = None
    for (source_family, endpoint_id, result_ordinal), zero_routes in sorted(
        zero_routes_by_group.items()
    ):
        candidate_id = _source_candidate_id(source_family, endpoint_id, result_ordinal)
        route_ids = sorted(item.route_id for item in zero_routes)
        for route_id in route_ids:
            zero_candidate_by_route[route_id] = candidate_id
        result_contract_state = _zero_field_result_contract_state(zero_routes)
        terminal_authority = result_contract_state == "explicit_named_zero_columns"
        conditional_lossless_binding = _is_exact_video_stats_lossless_result_contract(zero_routes)
        conditional_row: dict[str, object] | None = None
        conditional_authority_sha256: str | None = None
        if conditional_lossless_binding:
            if stats_lossless_conditional is None:
                stats_lossless_conditional = _stats_lossless_conditional_authority()
            conditional_row, conditional_authority_sha256 = stats_lossless_conditional
        implementation_binding_sha256 = _digest(
            {
                "route_contract_sha256s": sorted(item.contract_sha256 for item in zero_routes),
                "conditional_authority_sha256": conditional_authority_sha256,
                "conditional_implementation_sha256": (
                    conditional_row["implementation_sha256"]
                    if conditional_row is not None
                    else None
                ),
            }
        )
        implemented = terminal_authority or conditional_lossless_binding
        result_set_names = {item.provider_result_set_name for item in zero_routes}
        result_set_name = next(iter(result_set_names)) if len(result_set_names) == 1 else None
        candidate, evidence = _candidate_pair(
            candidate_id=candidate_id,
            candidate_kind="source",
            gate_requirement="lossless_required",
            dependency_ids=(),
            evidence_kind="provider_result_occurrence",
            authority_ids=[
                *route_ids,
                *(
                    [cast("str", conditional_row["staging_key"])]
                    if conditional_row is not None
                    else []
                ),
            ],
            authority_sha256s=[
                routes.digest,
                *(item.contract_sha256 for item in zero_routes),
                *(item.endpoint_contract_sha256 for item in zero_routes),
                *(
                    [
                        cast("str", conditional_authority_sha256),
                        cast("str", conditional_row["schema_sha256"]),
                        cast("str", conditional_row["validation_sha256"]),
                        cast("str", conditional_row["shared_implementation_sha256"]),
                        cast("str", conditional_row["implementation_sha256"]),
                    ]
                    if conditional_row is not None
                    else []
                ),
            ],
            implementation_status="implemented" if implemented else "missing",
            implementation_sha256=(implementation_binding_sha256 if implemented else None),
            specific_payload={
                "source_family": source_family,
                "endpoint_id": endpoint_id,
                "result_set_name": result_set_name,
                "result_set_ordinal": result_ordinal,
                "field_occurrence_ids": [],
                "field_count": 0,
                "routed_field_count": 0,
                "wide_unrouted_field_count": 0,
                "lossless_field_binding_count": 0,
                "unresolved_lossless_binding_count": 0,
                "source_authority_blocker_count": 0,
                "route_binding_ids": [],
                "route_ids": route_ids,
                "lossless_binding_ids": [],
                "zero_wide_route": True,
                "explicit_zero_field_contract": terminal_authority,
                "zero_field_result_contract_state": result_contract_state,
                "terminal_result_authority": (
                    "typed_present_empty_or_placeholder" if terminal_authority else "unresolved"
                ),
                "conditional_lossless_binding": conditional_lossless_binding,
                "conditional_lossless_staging_key": (
                    conditional_row["staging_key"] if conditional_row is not None else None
                ),
                "conditional_lossless_schema_sha256": (
                    conditional_row["schema_sha256"] if conditional_row is not None else None
                ),
                "conditional_lossless_validation_sha256": (
                    conditional_row["validation_sha256"] if conditional_row is not None else None
                ),
                "conditional_lossless_implementation_sha256": (
                    conditional_row["implementation_sha256"]
                    if conditional_row is not None
                    else None
                ),
                "classified_statuses": sorted({item.classified_status for item in zero_routes}),
                "disposition_reasons": sorted({item.disposition_reason for item in zero_routes}),
                "implementation_binding_sha256": implementation_binding_sha256,
            },
        )
        candidates.append(candidate)
        evidence_rows.append(evidence)
        if not implemented:
            blockers.append(
                _blocker(
                    subject_id=candidate_id,
                    code="source_result_contract_zero_fields",
                    evidence_sha256=evidence.structural_sha256,
                    resolution_requirement=(
                        "obtain an exact provider result contract before treating this zero-field "
                        "result occurrence as implemented"
                    ),
                    discriminator="|".join(route_ids),
                )
            )
    return candidates, evidence_rows, blockers, candidate_by_occurrence, zero_candidate_by_route


def _callable_implementation_sha256(*values: Any) -> str:
    normalized: list[dict[str, str]] = []
    for value in values:
        try:
            source = textwrap.dedent(inspect.getsource(value))
            tree = ast.parse(source)
        except (OSError, TypeError, SyntaxError) as exc:
            raise ModelCandidateCensusError("implementation source is unreadable") from exc
        normalized.append(
            {
                "module": cast("str", getattr(value, "__module__", "")),
                "qualname": cast("str", getattr(value, "__qualname__", "")),
                "ast": ast.dump(tree, annotate_fields=True, include_attributes=False),
            }
        )
    return _digest(normalized)


def _schema_authority(schema_type: type[pa.DataFrameModel]) -> tuple[dict[str, object], str]:
    try:
        schema = schema_type.to_schema()
    except Exception as exc:
        raise ModelCandidateCensusError("candidate schema authority cannot be compiled") from exc
    columns = [
        {
            "ordinal": ordinal,
            "name": name,
            "data_type": str(column.dtype),
            "nullable": bool(column.nullable),
            "unique": bool(column.unique),
            "required": bool(column.required),
        }
        for ordinal, (name, column) in enumerate(schema.columns.items())
    ]
    payload = {
        "schema_module": schema_type.__module__,
        "schema_class": schema_type.__name__,
        "columns": columns,
    }
    return payload, _digest(payload)


def _conditional_staging_rows() -> tuple[list[dict[str, object]], str]:
    from nbadb.contracts.staging_route_contract import admit_known_conditional_staging_route
    from nbadb.extract.live_lossless import (
        LIVE_LOSSLESS_STAGING_KEY,
        validate_live_lossless_frame,
    )
    from nbadb.extract.nba_api_adapter import (
        LOSSLESS_FALLBACK_STAGING_KEY,
        validate_lossless_fallback_frame,
    )
    from nbadb.orchestrate.staging_batches import StagingBatchStore
    from nbadb.orchestrate.staging_map import CONDITIONAL_STAGING_KEYS
    from nbadb.schemas.registry import get_input_schema

    expected_keys = frozenset({LIVE_LOSSLESS_STAGING_KEY, LOSSLESS_FALLBACK_STAGING_KEY})
    if expected_keys != CONDITIONAL_STAGING_KEYS:
        raise ModelCandidateCensusError("conditional staging-key authority drifted")
    shared_implementation = _callable_implementation_sha256(
        admit_known_conditional_staging_route,
        StagingBatchStore.persist_frame_batches,
    )
    rows: list[dict[str, object]] = []
    for staging_key in sorted(CONDITIONAL_STAGING_KEYS):
        schema_type = get_input_schema(staging_key)
        if schema_type is None:
            raise ModelCandidateCensusError("conditional staging schema is absent")
        schema_payload, schema_sha256 = _schema_authority(schema_type)
        validation = (
            validate_live_lossless_frame
            if staging_key == LIVE_LOSSLESS_STAGING_KEY
            else validate_lossless_fallback_frame
        )
        validation_sha256 = _callable_implementation_sha256(validation)
        implementation_sha256 = _digest(
            {
                "schema_sha256": schema_sha256,
                "shared_implementation_sha256": shared_implementation,
                "validation_sha256": validation_sha256,
            }
        )
        rows.append(
            {
                "staging_key": staging_key,
                "schema": schema_payload,
                "schema_sha256": schema_sha256,
                "validation_sha256": validation_sha256,
                "shared_implementation_sha256": shared_implementation,
                "implementation_sha256": implementation_sha256,
                "conditional_kind": (
                    "live_complete_node_tree"
                    if staging_key == LIVE_LOSSLESS_STAGING_KEY
                    else "stats_additive_result_cells"
                ),
            }
        )
    return rows, _digest(rows)


def _raw_request_authority_rows() -> tuple[list[dict[str, object]], str]:
    from nbadb.orchestrate.raw_publication_inventory import (
        RawRequestAuthorityPrivateTable,
        raw_request_authority_private_tables,
    )
    from nbadb.orchestrate.raw_request_store import RawRequestAuthorityStore
    from nbadb.schemas.raw.nba_api_authority import (
        RawNbaApiObservationRouteLandingSchema,
        RawNbaApiParserInputObjectSchema,
        RawNbaApiRequestObservationSchema,
        RawNbaApiResultOccurrenceSchema,
    )

    # The exact-four raw request-authority relations are private-only; the
    # census still enumerates them, but from the private registry.
    tables = raw_request_authority_private_tables()
    # The private registry's declaration order is the census authority.
    expected = (
        ("raw_nba_api_parser_input_object", RawNbaApiParserInputObjectSchema),
        ("raw_nba_api_request_observation", RawNbaApiRequestObservationSchema),
        ("raw_nba_api_result_occurrence", RawNbaApiResultOccurrenceSchema),
        ("raw_nba_api_observation_route_landing", RawNbaApiObservationRouteLandingSchema),
    )
    if (
        type(tables) is not tuple
        or any(type(item) is not RawRequestAuthorityPrivateTable for item in tables)
        or tuple((item.table_name, item.schema_type) for item in tables) != expected
    ):
        raise ModelCandidateCensusError("fixed public raw request-authority inventory drifted")
    persistence_sha256 = _callable_implementation_sha256(RawRequestAuthorityStore.persist_bundle)
    rows: list[dict[str, object]] = []
    for item in tables:
        schema_payload, schema_sha256 = _schema_authority(item.schema_type)
        implementation_sha256 = _digest(
            {
                "table_name": item.table_name,
                "schema_sha256": schema_sha256,
                "persistence_sha256": persistence_sha256,
            }
        )
        rows.append(
            {
                "table_name": item.table_name,
                "description": item.description,
                "schema": schema_payload,
                "schema_sha256": schema_sha256,
                "persistence_sha256": persistence_sha256,
                "implementation_sha256": implementation_sha256,
            }
        )
    return rows, _digest(rows)


def _compile_staging_candidates(
    structure: FieldFateStructureV1,
    routes: StagingRouteContractBundle,
    candidate_by_occurrence: Mapping[str, str],
    zero_candidate_by_route: Mapping[str, str],
) -> tuple[
    list[StableModelCandidateV1],
    list[ModelCandidateCensusEvidenceV1],
    list[ModelCandidateCensusBlockerV1],
    dict[str, str],
    str,
    str,
]:
    sinks_by_route: dict[str, list[StorageSinkV1]] = defaultdict(list)
    for sink in structure.storage_sinks.sinks:
        sinks_by_route[sink.route_id].append(sink)
    bindings_by_route: dict[str, list[RouteFieldBindingV1]] = defaultdict(list)
    for binding in structure.route_bindings.bindings:
        bindings_by_route[binding.route_id].append(binding)
    routes_by_staging: dict[str, list[StagingRouteContract]] = defaultdict(list)
    for route in routes.routes:
        routes_by_staging[route.staging_key].append(route)

    candidates: list[StableModelCandidateV1] = []
    evidence_rows: list[ModelCandidateCensusEvidenceV1] = []
    blockers: list[ModelCandidateCensusBlockerV1] = []
    candidate_by_staging_key: dict[str, str] = {}
    for staging_key, staging_routes in sorted(routes_by_staging.items()):
        candidate_id = f"staging:{staging_key}"
        candidate_by_staging_key[staging_key] = candidate_id
        route_ids = sorted(item.route_id for item in staging_routes)
        sinks = sorted(
            (sink for route_id in route_ids for sink in sinks_by_route.get(route_id, ())),
            key=lambda item: (item.route_ordinal, item.storage_ordinal),
        )
        for route in staging_routes:
            route_sinks = sorted(
                sinks_by_route.get(route.route_id, ()), key=lambda item: item.storage_ordinal
            )
            observed_columns = tuple(item.storage_column for item in route_sinks)
            if (
                tuple(item.storage_ordinal for item in route_sinks)
                != tuple(range(len(route_sinks)))
                or observed_columns != route.possible_storage_columns
            ):
                raise ModelCandidateCensusError(f"route/storage mismatch for {route.route_id}")
            declared_width = len(route.storage_columns)
            declared_sinks = route_sinks[:declared_width]
            request_scope_sinks = route_sinks[declared_width:]
            if tuple(item.storage_column for item in declared_sinks) != route.storage_columns:
                raise ModelCandidateCensusError(
                    f"route/declared-storage mismatch for {route.route_id}"
                )
            if tuple(item.storage_column for item in request_scope_sinks) != tuple(
                item.storage_column for item in route.request_scope_storage_fields
            ) or any(
                item.status != "storage_only" or item.binding_ids for item in request_scope_sinks
            ):
                raise ModelCandidateCensusError(
                    f"route/request-scope storage mismatch for {route.route_id}"
                )
            if any(
                item.route_contract_sha256 != route.contract_sha256
                or item.staging_key != route.staging_key
                for item in route_sinks
            ):
                raise ModelCandidateCensusError(
                    f"route/storage authority mismatch for {route.route_id}"
                )
        route_bindings = [
            item for route_id in route_ids for item in bindings_by_route.get(route_id, ())
        ]
        dependency_ids = {
            candidate_by_occurrence[item.source_occurrence_id] for item in route_bindings
        }
        dependency_ids.update(
            zero_candidate_by_route[route_id]
            for route_id in route_ids
            if route_id in zero_candidate_by_route
        )
        empty_storage = not sinks and all(not item.storage_columns for item in staging_routes)
        implementation_sha256 = (
            None
            if empty_storage
            else _digest(
                {
                    "route_contract_sha256s": sorted(
                        item.contract_sha256 for item in staging_routes
                    ),
                    "sink_sha256s": sorted(item.sink_sha256 for item in sinks),
                }
            )
        )
        candidate, evidence = _candidate_pair(
            candidate_id=candidate_id,
            candidate_kind="staging",
            gate_requirement="lossless_required",
            dependency_ids=sorted(dependency_ids),
            evidence_kind="staging_route",
            authority_ids=[*route_ids, *(item.sink_id for item in sinks)],
            authority_sha256s=[
                routes.digest,
                *(item.contract_sha256 for item in staging_routes),
                *(item.sink_sha256 for item in sinks),
            ],
            implementation_status="missing" if empty_storage else "implemented",
            implementation_sha256=implementation_sha256,
            specific_payload={
                "staging_key": staging_key,
                "route_ids": route_ids,
                "route_contract_sha256s": sorted(item.contract_sha256 for item in staging_routes),
                "storage_sink_ids": [item.sink_id for item in sinks],
                "storage_sink_count": len(sinks),
                "provider_bound_sink_count": sum(item.status == "provider_bound" for item in sinks),
                "storage_only_sink_count": sum(item.status == "storage_only" for item in sinks),
                "storage_columns": [item.storage_column for item in sinks],
                "declared_storage_sink_count": sum(
                    len(item.storage_columns) for item in staging_routes
                ),
                "declared_storage_columns": [
                    column for item in staging_routes for column in item.storage_columns
                ],
                "request_scope_storage_sink_count": sum(
                    len(item.request_scope_storage_fields) for item in staging_routes
                ),
                "request_scope_storage_columns": [
                    field.storage_column
                    for item in staging_routes
                    for field in item.request_scope_storage_fields
                ],
                "schema_tables": sorted({item.resolved_schema_table for item in staging_routes}),
                "schema_classes": sorted({item.resolved_schema_class for item in staging_routes}),
                "route_statuses": sorted({item.classified_status for item in staging_routes}),
                "explicit_zero_storage_route": empty_storage,
            },
        )
        candidates.append(candidate)
        evidence_rows.append(evidence)
        if empty_storage:
            blockers.append(
                _blocker(
                    subject_id=candidate_id,
                    code="staging_route_zero_storage",
                    evidence_sha256=evidence.structural_sha256,
                    resolution_requirement=(
                        "obtain exact provider fields and a nonempty typed storage contract"
                    ),
                    discriminator="|".join(route_ids),
                )
            )

    conditional_rows, conditional_authority_sha256 = _conditional_staging_rows()
    lossless_source_candidates = {
        candidate_by_occurrence[item.source_occurrence_id] for item in structure.lossless_bindings
    }
    for row in conditional_rows:
        staging_key = cast("str", row["staging_key"])
        candidate_id = f"staging:{staging_key}"
        if staging_key in candidate_by_staging_key:
            raise ModelCandidateCensusError("conditional staging candidate collides with a route")
        candidate_by_staging_key[staging_key] = candidate_id
        dependencies = (
            lossless_source_candidates
            if row["conditional_kind"] == "live_complete_node_tree"
            else set()
        )
        candidate, evidence = _candidate_pair(
            candidate_id=candidate_id,
            candidate_kind="staging",
            gate_requirement="lossless_required",
            dependency_ids=sorted(dependencies),
            evidence_kind="conditional_staging",
            authority_ids=[staging_key],
            authority_sha256s=[
                conditional_authority_sha256,
                cast("str", row["schema_sha256"]),
                cast("str", row["validation_sha256"]),
                cast("str", row["shared_implementation_sha256"]),
            ],
            implementation_status="implemented",
            implementation_sha256=cast("str", row["implementation_sha256"]),
            specific_payload=row,
        )
        candidates.append(candidate)
        evidence_rows.append(evidence)

    raw_rows, raw_authority_sha256 = _raw_request_authority_rows()
    for row in raw_rows:
        table_name = cast("str", row["table_name"])
        candidate_id = f"staging:{table_name}"
        if table_name in candidate_by_staging_key:
            raise ModelCandidateCensusError("raw request-authority candidate collides")
        candidate_by_staging_key[table_name] = candidate_id
        candidate, evidence = _candidate_pair(
            candidate_id=candidate_id,
            candidate_kind="staging",
            gate_requirement="lossless_required",
            dependency_ids=(),
            evidence_kind="raw_request_authority",
            authority_ids=[table_name],
            authority_sha256s=[
                raw_authority_sha256,
                cast("str", row["schema_sha256"]),
                cast("str", row["persistence_sha256"]),
            ],
            implementation_status="implemented",
            implementation_sha256=cast("str", row["implementation_sha256"]),
            specific_payload=row,
        )
        candidates.append(candidate)
        evidence_rows.append(evidence)
    return (
        candidates,
        evidence_rows,
        blockers,
        candidate_by_staging_key,
        conditional_authority_sha256,
        raw_authority_sha256,
    )


def _star_column_payload(column: StarColumnContract) -> dict[str, object]:
    return {
        "ordinal": column.ordinal,
        "name": column.name,
        "data_type": column.data_type,
        "nullable": column.nullable,
        "unique": column.unique,
        "required": column.required,
        "source": column.source,
        "fk_ref": column.fk_ref,
        "metadata": json.loads(column.metadata_json),
    }


def _star_table_payload(table: StarTableContract) -> dict[str, object]:
    return {
        "output_name": table.output_name,
        "family": table.family,
        "purpose": table.purpose,
        "schema_class": table.schema_class,
        "schema_module": table.schema_module,
        "columns": [_star_column_payload(item) for item in table.columns],
        "schema_sha256": table.schema_sha256,
        "foreign_keys": [
            {
                "column": item.column,
                "reference": item.reference,
                "target_table": item.target_table,
                "target_column": item.target_column,
                "target_column_unique": item.target_column_unique,
                "current_or_as_of": item.current_or_as_of,
                "reviewed": item.reviewed,
                "blockers": list(item.blockers),
            }
            for item in table.foreign_keys
        ],
        "transform": {
            "class_name": table.transform.class_name,
            "qualname": table.transform.qualname,
            "runtime_module": table.transform.runtime_module,
            "binding_module": table.transform.binding_module,
            "kind": table.transform.kind,
            "dependencies": list(table.transform.dependencies),
            "implementation_sha256": table.transform.implementation_sha256,
        },
        "consumer_metadata": (
            None
            if table.consumer_metadata is None
            else {
                "value": json.loads(table.consumer_metadata.canonical_json),
                "sha256": table.consumer_metadata.sha256,
            }
        ),
        "grain": {
            "label": table.grain.label,
            "columns": list(table.grain.columns),
            "evidence_kind": table.grain.evidence_kind,
            "reviewed": table.grain.reviewed,
        },
        "key_policy": {
            "kind": table.key_policy.kind,
            "columns": list(table.key_policy.columns),
            "reviewed": table.key_policy.reviewed,
            "evidence_kind": table.key_policy.evidence_kind,
        },
        "semantic_policies": [
            {
                "name": item.name,
                "value": item.value,
                "evidence_kind": item.evidence_kind,
                "reviewed": item.reviewed,
            }
            for item in table.semantic_policies
        ],
        "blockers": list(table.blockers),
        "model_green": table.model_green,
    }


def _validate_star_inventory(inventory: StarModelContractInventory) -> None:
    if type(inventory) is not StarModelContractInventory:
        raise ModelCandidateCensusError("star inventory has a foreign concrete type")
    if type(inventory.tables) is not tuple or any(
        type(item) is not StarTableContract for item in inventory.tables
    ):
        raise ModelCandidateCensusError("star tables must be an exact typed tuple")
    names = tuple(item.output_name for item in inventory.tables)
    if not names or names != tuple(sorted(set(names))):
        raise ModelCandidateCensusError("star table identities must be sorted and unique")
    for table in inventory.tables:
        if schema_contract_sha256(table.columns) != table.schema_sha256:
            raise ModelCandidateCensusError("star schema digest drifted")
        if _digest(_star_table_payload(table)) != table.contract_sha256:
            raise ModelCandidateCensusError("star table contract digest drifted")
        for digest in (
            table.schema_sha256,
            table.transform.implementation_sha256,
            table.contract_sha256,
        ):
            _require_sha256(digest, field_name="star table authority digest")
    actual_counts = Counter(item.family for item in inventory.tables)
    expected_counts = {
        "fact": inventory.family_counts.fact,
        "dim": inventory.family_counts.dim,
        "bridge": inventory.family_counts.bridge,
        "agg": inventory.family_counts.agg,
        "analytics": inventory.family_counts.analytics,
    }
    if actual_counts != expected_counts or inventory.family_counts.total != len(inventory.tables):
        raise ModelCandidateCensusError("star family-count authority drifted")
    inventory_payload = {
        "tables": [
            {"output_name": item.output_name, "contract_sha256": item.contract_sha256}
            for item in inventory.tables
        ],
        "family_counts": expected_counts,
        "blocker_summary": [
            {
                "code": item.code,
                "table_count": item.table_count,
                "occurrence_count": item.occurrence_count,
            }
            for item in inventory.blocker_summary
        ],
        "model_green": inventory.model_green,
    }
    if _digest(inventory_payload) != inventory.contract_sha256:
        raise ModelCandidateCensusError("star inventory contract digest drifted")


def _star_candidate_kind(table: StarTableContract) -> ModelCandidateKind:
    if table.transform.binding_module.startswith("nbadb.transform.live."):
        return "live"
    mapping = {
        "dim": "dimension",
        "fact": "fact",
        "bridge": "bridge",
        "agg": "aggregate",
        "analytics": "analytics",
    }
    kind = mapping.get(table.family)
    if kind is None:
        raise ModelCandidateCensusError("star family cannot be classified")
    return cast("ModelCandidateKind", kind)


def _compile_star_candidates(
    inventory: StarModelContractInventory,
    staging_candidate_by_name: Mapping[str, str],
) -> tuple[
    list[StableModelCandidateV1],
    list[ModelCandidateCensusEvidenceV1],
    list[ModelCandidateCensusBlockerV1],
    dict[str, str],
]:
    _validate_star_inventory(inventory)
    candidate_by_output = {
        item.output_name: f"star:{item.output_name}" for item in inventory.tables
    }
    candidates: list[StableModelCandidateV1] = []
    evidence_rows: list[ModelCandidateCensusEvidenceV1] = []
    blockers: list[ModelCandidateCensusBlockerV1] = []
    for table in inventory.tables:
        candidate_id = candidate_by_output[table.output_name]
        dependency_ids: set[str] = set()
        unresolved: list[str] = []
        dependency_proofs: list[dict[str, str]] = []
        for dependency in table.transform.dependencies:
            resolved = staging_candidate_by_name.get(dependency) or candidate_by_output.get(
                dependency
            )
            if resolved is None:
                unresolved.append(dependency)
                continue
            dependency_ids.add(resolved)
            dependency_proofs.append({"transform_dependency": dependency, "candidate_id": resolved})
        structural_blockers = sorted(
            item for item in table.blockers if item == "schema_empty" or item.startswith("schema_")
        )
        implemented = not structural_blockers and not unresolved
        implementation_sha256 = (
            _digest(
                {
                    "schema_module": table.schema_module,
                    "schema_class": table.schema_class,
                    "schema_sha256": table.schema_sha256,
                    "transform_module": table.transform.binding_module,
                    "transform_class": table.transform.class_name,
                    "transform_implementation_sha256": (table.transform.implementation_sha256),
                }
            )
            if implemented
            else None
        )
        candidate_kind = _star_candidate_kind(table)
        candidate, evidence = _candidate_pair(
            candidate_id=candidate_id,
            candidate_kind=candidate_kind,
            gate_requirement="stable_required",
            dependency_ids=sorted(dependency_ids),
            evidence_kind="public_transform",
            authority_ids=[
                table.output_name,
                f"{table.schema_module}:{table.schema_class}",
                f"{table.transform.binding_module}:{table.transform.class_name}",
            ],
            authority_sha256s=[
                inventory.contract_sha256,
                table.contract_sha256,
                table.schema_sha256,
                table.transform.implementation_sha256,
            ],
            implementation_status="implemented" if implemented else "missing",
            implementation_sha256=implementation_sha256,
            specific_payload={
                "output_name": table.output_name,
                "star_family": table.family,
                "schema_module": table.schema_module,
                "schema_class": table.schema_class,
                "schema_sha256": table.schema_sha256,
                "schema_column_count": len(table.columns),
                "transform_runtime_module": table.transform.runtime_module,
                "transform_binding_module": table.transform.binding_module,
                "transform_class": table.transform.class_name,
                "transform_kind": table.transform.kind,
                "transform_implementation_sha256": (table.transform.implementation_sha256),
                "transform_dependencies": list(table.transform.dependencies),
                "dependency_proofs": dependency_proofs,
                "unresolved_transform_dependencies": unresolved,
                "star_structural_blockers": structural_blockers,
                "star_contract_sha256": table.contract_sha256,
                "upstream_model_green": table.model_green,
            },
        )
        candidates.append(candidate)
        evidence_rows.append(evidence)
        for code in structural_blockers:
            blockers.append(
                _blocker(
                    subject_id=candidate_id,
                    code="star_structural_blocker",
                    evidence_sha256=table.contract_sha256,
                    resolution_requirement=(
                        "resolve the exact star schema/implementation structural blocker"
                    ),
                    discriminator=code,
                )
            )
        for dependency in unresolved:
            blockers.append(
                _blocker(
                    subject_id=candidate_id,
                    code="star_dependency_unresolved",
                    evidence_sha256=table.transform.implementation_sha256,
                    resolution_requirement=(
                        "bind the transform dependency to an exact staging or star candidate"
                    ),
                    discriminator=dependency,
                )
            )
    return candidates, evidence_rows, blockers, candidate_by_output


def _compile_analytical_candidates(
    analytical_needs: object,
    known_candidate_ids: set[str],
) -> tuple[
    list[StableModelCandidateV1],
    list[ModelCandidateCensusEvidenceV1],
    list[ModelCandidateCensusBlockerV1],
    AnalyticalNeedsState,
    str | None,
]:
    if analytical_needs is None:
        evidence_sha256 = _digest(
            {"kind": "analytical_needs_authority_absent", "schema_version": 1}
        )
        return (
            [],
            [],
            [
                _blocker(
                    subject_id="census",
                    code="analytical_needs_authority_absent",
                    evidence_sha256=evidence_sha256,
                    resolution_requirement=(
                        "supply the explicit versioned analytical-needs authority"
                    ),
                    discriminator="absent",
                )
            ],
            "absent",
            None,
        )
    if type(analytical_needs) is not AnalyticalNeedsAuthorityV1:
        foreign_type = f"{type(analytical_needs).__module__}.{type(analytical_needs).__qualname__}"
        evidence_sha256 = _digest(
            {
                "kind": "analytical_needs_authority_foreign",
                "schema_version": 1,
                "foreign_type": foreign_type,
            }
        )
        return (
            [],
            [],
            [
                _blocker(
                    subject_id="census",
                    code="analytical_needs_authority_foreign",
                    evidence_sha256=evidence_sha256,
                    resolution_requirement=("supply an exact AnalyticalNeedsAuthorityV1 input"),
                    discriminator=foreign_type,
                )
            ],
            "foreign",
            None,
        )
    authority = analytical_needs
    candidates: list[StableModelCandidateV1] = []
    evidence_rows: list[ModelCandidateCensusEvidenceV1] = []
    blockers: list[ModelCandidateCensusBlockerV1] = []
    for need in authority.needs:
        unresolved = sorted(set(need.required_candidate_ids) - known_candidate_ids)
        dependencies = sorted(set(need.required_candidate_ids) & known_candidate_ids)
        candidate, evidence = _candidate_pair(
            candidate_id=need.candidate_id,
            candidate_kind="experimental_model",
            gate_requirement="experimental_only",
            dependency_ids=dependencies,
            evidence_kind="analytical_need",
            authority_ids=[authority.authority_id, need.need_id],
            authority_sha256s=[authority.authority_sha256, need.need_sha256],
            implementation_status="missing",
            implementation_sha256=None,
            specific_payload={
                "analytical_need": need.to_dict(),
                "analytical_need_sha256": need.need_sha256,
                "analytical_needs_authority_sha256": authority.authority_sha256,
                "unresolved_required_candidate_ids": unresolved,
            },
        )
        candidates.append(candidate)
        evidence_rows.append(evidence)
        for dependency in unresolved:
            blockers.append(
                _blocker(
                    subject_id=need.candidate_id,
                    code="analytical_need_dependency_unresolved",
                    evidence_sha256=need.need_sha256,
                    resolution_requirement=(
                        "bind the explicit analytical need to a current structural candidate"
                    ),
                    discriminator=dependency,
                )
            )
    return candidates, evidence_rows, blockers, "present", authority.authority_sha256


def compile_model_candidate_census(
    *,
    field_structure: FieldFateStructureV1,
    star_inventory: StarModelContractInventory,
    analytical_needs: object,
    route_bundle: StagingRouteContractBundle | None = None,
) -> ModelCandidateCensusV1:
    """Compile the exact structural candidate census from independent inputs."""

    if type(field_structure) is not FieldFateStructureV1:
        raise ModelCandidateCensusError("field structure has a foreign concrete type")
    _validate_star_inventory(star_inventory)
    routes = staging_route_contract_bundle() if route_bundle is None else route_bundle
    if type(routes) is not StagingRouteContractBundle:
        raise ModelCandidateCensusError("staging route bundle has a foreign concrete type")
    try:
        validate_staging_route_contract_bundle(routes)
    except ValueError as exc:
        raise ModelCandidateCensusError(
            "staging route bundle differs from current authority"
        ) from exc
    if routes.digest != field_structure.route_bindings.staging_route_contract_sha256:
        raise ModelCandidateCensusError("field route/storage authority digest drifted")

    (
        source_candidates,
        source_evidence,
        source_blockers,
        candidate_by_occurrence,
        zero_candidate_by_route,
    ) = _compile_source_candidates(field_structure, routes)
    (
        staging_candidates,
        staging_evidence,
        staging_blockers,
        staging_candidate_by_name,
        conditional_authority_sha256,
        raw_authority_sha256,
    ) = _compile_staging_candidates(
        field_structure,
        routes,
        candidate_by_occurrence,
        zero_candidate_by_route,
    )
    star_candidates, star_evidence, star_blockers, _candidate_by_output = _compile_star_candidates(
        star_inventory, staging_candidate_by_name
    )
    known_ids = {
        item.candidate_id for item in (*source_candidates, *staging_candidates, *star_candidates)
    }
    analytical_candidates, analytical_evidence, analytical_blockers, needs_state, needs_sha = (
        _compile_analytical_candidates(analytical_needs, known_ids)
    )
    return ModelCandidateCensusV1(
        field_fate_structure_sha256=field_structure.identity_sha256,
        staging_route_contract_sha256=routes.digest,
        star_model_contract_sha256=star_inventory.contract_sha256,
        conditional_staging_authority_sha256=conditional_authority_sha256,
        raw_request_authority_sha256=raw_authority_sha256,
        analytical_needs_state=needs_state,
        analytical_needs_authority_sha256=needs_sha,
        candidates=tuple(
            sorted(
                (
                    *source_candidates,
                    *staging_candidates,
                    *star_candidates,
                    *analytical_candidates,
                ),
                key=lambda item: item.candidate_id,
            )
        ),
        evidence=tuple(
            sorted(
                (*source_evidence, *staging_evidence, *star_evidence, *analytical_evidence),
                key=lambda item: item.candidate_id,
            )
        ),
        blockers=tuple(
            sorted((*source_blockers, *staging_blockers, *star_blockers, *analytical_blockers))
        ),
    )


def compile_current_model_candidate_census(
    *,
    analytical_needs: object,
    upstream_root: str | None = None,
) -> ModelCandidateCensusV1:
    """Compile from the current field, route, and public-transform authorities."""

    from nbadb.contracts.field_fate_structure import compile_field_fate_structure
    from nbadb.contracts.star_table_contract import compile_star_table_contracts

    return compile_model_candidate_census(
        field_structure=compile_field_fate_structure(upstream_root),
        star_inventory=compile_star_table_contracts(),
        analytical_needs=analytical_needs,
        route_bundle=staging_route_contract_bundle(),
    )


def validate_model_candidate_census(
    census: ModelCandidateCensusV1,
    *,
    field_structure: FieldFateStructureV1,
    star_inventory: StarModelContractInventory,
    analytical_needs: object,
    route_bundle: StagingRouteContractBundle | None = None,
) -> None:
    """Recompute the census from bound authorities and reject stale/forged rows."""

    if type(census) is not ModelCandidateCensusV1:
        raise ModelCandidateCensusError("candidate census has a foreign concrete type")
    expected = compile_model_candidate_census(
        field_structure=field_structure,
        star_inventory=star_inventory,
        analytical_needs=analytical_needs,
        route_bundle=route_bundle,
    )
    if census.census_sha256 != expected.census_sha256 or census != expected:
        raise ModelCandidateCensusError(
            "candidate census differs from exact structural recomputation"
        )


def parse_model_candidate_census(raw: bytes) -> ModelCandidateCensusV1:
    """Parse only canonical, duplicate-free census bytes."""

    return ModelCandidateCensusV1.from_canonical_bytes(raw)
