"""Deterministic, read-only work packets for per-table star semantic review.

The compiler in this module joins existing repository authorities without
turning any observation into an authored semantic decision.  Structural
metadata, candidate evidence, and the current red stable-disposition inventory
remain explicitly labelled as observations.  Only literal rows from the fixed
star-semantic decision corpus appear under ``authored_semantic_decision``.

This is a review aid, not an admission primitive.  It emits no review receipt,
does not make MODEL-GREEN or DATA-GREEN claims, and has no public seam for
candidate decisions, approval booleans, alternate registries, or authority
overrides.
"""

from __future__ import annotations

import hashlib
import json
import math
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
    StableModelDispositionInventoryV1,
    StableModelDispositionV1,
    compile_stable_model_disposition_inventory,
    draft_required_model_dispositions,
)
from nbadb.contracts.star_semantic_authoring import StarTableSemanticDecisionV1
from nbadb.contracts.star_semantic_decision_corpus import (
    StarSemanticDecisionCorpusV1,
    load_star_semantic_decision_corpus,
)
from nbadb.contracts.star_semantic_inventory import (
    StarTableSemanticAuthorityV1,
    derive_star_semantic_authorities,
)
from nbadb.contracts.star_table_contract import (
    StarModelContractInventory,
    StarTableContract,
    compile_star_table_contracts,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nbadb.contracts.stable_model_disposition import (
        ModelDispositionBlockerV1,
    )
    from nbadb.contracts.star_semantic_decision_corpus import (
        StarSemanticDecisionCorpusBlockerV1,
    )

__all__ = [
    "STAR_SEMANTIC_REVIEW_PACKET_KIND",
    "STAR_SEMANTIC_REVIEW_PACKET_SCHEMA_VERSION",
    "StarSemanticReviewPacketError",
    "StarSemanticReviewPacketV1",
    "StarSemanticReviewTableV1",
    "compile_current_star_semantic_review_packet",
]

STAR_SEMANTIC_REVIEW_PACKET_SCHEMA_VERSION = 1
STAR_SEMANTIC_REVIEW_PACKET_KIND = "nbadb_star_semantic_review_packet"

_MISSING_DECISION_BLOCKERS = (
    "semantic_decision_not_authored",
    "table_specific_semantic_evidence_unreviewed",
)
_FAMILY_NAMES = ("fact", "dim", "bridge", "agg", "analytics")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_MAX_CANONICAL_BYTES = 16 * 1024 * 1024
_MAX_OBSERVATION_BYTES = 2 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_MAX_JSON_CONTAINER_ITEMS = 16_384
_MAX_JSON_NODES = 1_000_000
_MAX_JSON_STRING_BYTES = 12 * 1024 * 1024
_MAX_JSON_INTEGER_DIGITS = 128
_COMPILER_TOKEN = object()

type SemanticDecisionState = Literal["authored", "missing"]


class StarSemanticReviewPacketError(ValueError):
    """The star-semantic review packet or one of its source joins is invalid."""


def _validate_json_shape(value: object, *, label: str, byte_limit: int) -> None:
    """Bound canonical JSON before recursive serialization or typed admission."""

    nodes = 0
    string_bytes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise StarSemanticReviewPacketError(f"{label} exceeds the JSON node bound")
        if depth > _MAX_JSON_DEPTH:
            raise StarSemanticReviewPacketError(f"{label} exceeds the JSON depth bound")
        if type(item) is dict:
            if len(item) > _MAX_JSON_CONTAINER_ITEMS:
                raise StarSemanticReviewPacketError(f"{label} exceeds the JSON object-item bound")
            for key, child in cast("dict[object, object]", item).items():
                if type(key) is not str:
                    raise StarSemanticReviewPacketError(
                        f"{label} contains a non-string JSON object key"
                    )
                string_bytes += len(key.encode("utf-8"))
                stack.append((child, depth + 1))
        elif type(item) is list:
            if len(item) > _MAX_JSON_CONTAINER_ITEMS:
                raise StarSemanticReviewPacketError(f"{label} exceeds the JSON array-item bound")
            stack.extend((child, depth + 1) for child in cast("list[object]", item))
        elif type(item) is str:
            string_bytes += len(item.encode("utf-8"))
        elif type(item) is int:
            if len(str(abs(item))) > _MAX_JSON_INTEGER_DIGITS:
                raise StarSemanticReviewPacketError(f"{label} contains an oversized JSON integer")
        elif type(item) is float:
            if not math.isfinite(item):
                raise StarSemanticReviewPacketError(f"{label} contains a non-finite JSON number")
        elif item is not None and type(item) is not bool:
            raise StarSemanticReviewPacketError(f"{label} contains a non-JSON value")
        if string_bytes > min(byte_limit, _MAX_JSON_STRING_BYTES):
            raise StarSemanticReviewPacketError(f"{label} exceeds the JSON string-byte bound")


def _canonical_bytes(value: object) -> bytes:
    _validate_json_shape(value, label="star-semantic review value", byte_limit=_MAX_CANONICAL_BYTES)
    try:
        raw = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise StarSemanticReviewPacketError(
            "star-semantic review value is not canonical JSON"
        ) from exc
    if len(raw) > _MAX_CANONICAL_BYTES:
        raise StarSemanticReviewPacketError(
            "star-semantic review value exceeds the canonical byte bound"
        )
    return raw


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise StarSemanticReviewPacketError(f"{field} must be a lowercase SHA-256")
    return value


def _require_id(value: object, *, field: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise StarSemanticReviewPacketError(f"{field} must be a safe nonempty identifier")
    return value


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise StarSemanticReviewPacketError(f"{label} must be an exact JSON object")
    return cast("Mapping[str, object]", value)


def _decode_canonical_bytes(raw: bytes) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise StarSemanticReviewPacketError(
            "review packet bytes are empty or exceed the canonical byte bound"
        )

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise StarSemanticReviewPacketError("review packet contains duplicate JSON keys")
            result[key] = value
        return result

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise StarSemanticReviewPacketError("review packet contains a non-finite JSON number")
        return parsed

    def bounded_int(value: str) -> int:
        digits = value.removeprefix("-")
        if len(digits) > _MAX_JSON_INTEGER_DIGITS:
            raise StarSemanticReviewPacketError("review packet contains an oversized JSON integer")
        return int(value)

    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_float=finite_float,
            parse_int=bounded_int,
            parse_constant=lambda value: (_ for _ in ()).throw(
                StarSemanticReviewPacketError(f"review packet contains non-finite JSON: {value}")
            ),
        )
    except StarSemanticReviewPacketError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise StarSemanticReviewPacketError("review packet bytes are invalid JSON") from exc
    _validate_json_shape(decoded, label="review packet", byte_limit=_MAX_CANONICAL_BYTES)
    payload = _mapping(decoded, label="review packet")
    if _canonical_bytes(payload) != raw:
        raise StarSemanticReviewPacketError("review packet bytes are not canonical JSON")
    return payload


def _canonical_observation(value: object, *, label: str) -> str:
    payload = _mapping(value, label=label)
    _validate_json_shape(payload, label=label, byte_limit=_MAX_OBSERVATION_BYTES)
    raw = _canonical_bytes(payload)
    if len(raw) > _MAX_OBSERVATION_BYTES:
        raise StarSemanticReviewPacketError(f"{label} exceeds the observation byte bound")
    return raw.decode("utf-8")


def _observation_value(value: str, *, label: str) -> Mapping[str, object]:
    if type(value) is not str or not value or len(value.encode("utf-8")) > _MAX_OBSERVATION_BYTES:
        raise StarSemanticReviewPacketError(f"{label} must be canonical JSON text")
    try:
        payload = _decode_canonical_bytes(value.encode("utf-8"))
    except StarSemanticReviewPacketError as exc:
        raise StarSemanticReviewPacketError(f"{label} is invalid canonical JSON") from exc
    return payload


def _structural_observation(table: StarTableContract) -> dict[str, object]:
    """Copy exact structural facts while labelling semantic-looking hints."""

    return {
        "observation_kind": "star_table_structural_observation_v1",
        "output_name": table.output_name,
        "family": table.family,
        "direct_purpose_observation": table.purpose,
        "schema": {
            "class_name": table.schema_class,
            "module": table.schema_module,
            "sha256": table.schema_sha256,
            "ordered_columns": [
                {
                    "ordinal": column.ordinal,
                    "name": column.name,
                    "data_type": column.data_type,
                    "nullable": column.nullable,
                    "unique": column.unique,
                    "required": column.required,
                    "source_observation": column.source,
                    "foreign_key_reference_observation": column.fk_ref,
                    "metadata_observation": json.loads(column.metadata_json),
                }
                for column in table.columns
            ],
        },
        "foreign_key_observations": [
            {
                "column": item.column,
                "reference": item.reference,
                "target_table": item.target_table,
                "target_column": item.target_column,
                "target_column_unique": item.target_column_unique,
                "current_or_as_of_observation": item.current_or_as_of,
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
        "consumer_metadata_observation": (
            None
            if table.consumer_metadata is None
            else {
                "value": json.loads(table.consumer_metadata.canonical_json),
                "sha256": table.consumer_metadata.sha256,
            }
        ),
        "grain_observation": {
            "label": table.grain.label,
            "columns": list(table.grain.columns),
            "evidence_kind": table.grain.evidence_kind,
            "reviewed": table.grain.reviewed,
        },
        "key_policy_observation": {
            "kind": table.key_policy.kind,
            "columns": list(table.key_policy.columns),
            "evidence_kind": table.key_policy.evidence_kind,
            "reviewed": table.key_policy.reviewed,
        },
        "semantic_policy_observations": [
            {
                "name": item.name,
                "value": item.value,
                "evidence_kind": item.evidence_kind,
                "reviewed": item.reviewed,
            }
            for item in table.semantic_policies
        ],
        "structural_blockers": list(table.blockers),
        "structural_model_green_observation": table.model_green,
        "structural_table_sha256": table.contract_sha256,
    }


@dataclass(frozen=True, slots=True, order=True, init=False)
class StarSemanticReviewTableV1:
    """One exact table work item with observations kept apart from authorship."""

    output_name: str
    family: str
    structural_observation_json: str
    candidate_observation_json: str
    candidate_source_evidence_observation_json: str
    stable_disposition_inventory_observation_json: str
    stable_disposition_blockers: tuple[str, ...]
    semantic_authority_observation_json: str
    semantic_decision_state: SemanticDecisionState
    authored_semantic_decision_json: str | None
    authored_semantic_decision_blockers: tuple[str, ...]

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise StarSemanticReviewPacketError(
            "review tables may only be constructed by the fixed-source compiler"
        )

    @classmethod
    def _from_compiler(
        cls,
        *,
        _token: object,
        output_name: str,
        family: str,
        structural_observation_json: str,
        candidate_observation_json: str,
        candidate_source_evidence_observation_json: str,
        stable_disposition_inventory_observation_json: str,
        stable_disposition_blockers: tuple[str, ...],
        semantic_authority_observation_json: str,
        semantic_decision_state: SemanticDecisionState,
        authored_semantic_decision_json: str | None,
        authored_semantic_decision_blockers: tuple[str, ...],
    ) -> Self:
        if _token is not _COMPILER_TOKEN:
            raise StarSemanticReviewPacketError(
                "review table construction requires the private compiler token"
            )
        row = object.__new__(cls)
        for field, value in (
            ("output_name", output_name),
            ("family", family),
            ("structural_observation_json", structural_observation_json),
            ("candidate_observation_json", candidate_observation_json),
            (
                "candidate_source_evidence_observation_json",
                candidate_source_evidence_observation_json,
            ),
            (
                "stable_disposition_inventory_observation_json",
                stable_disposition_inventory_observation_json,
            ),
            ("stable_disposition_blockers", stable_disposition_blockers),
            ("semantic_authority_observation_json", semantic_authority_observation_json),
            ("semantic_decision_state", semantic_decision_state),
            ("authored_semantic_decision_json", authored_semantic_decision_json),
            ("authored_semantic_decision_blockers", authored_semantic_decision_blockers),
        ):
            object.__setattr__(row, field, value)
        row._validate()
        return row

    def _validate(self) -> None:
        _require_id(self.output_name, field="table output_name")
        if self.family not in _FAMILY_NAMES:
            raise StarSemanticReviewPacketError("table family is unsupported")
        structural = _observation_value(
            self.structural_observation_json,
            label="structural observation",
        )
        candidate = _observation_value(
            self.candidate_observation_json,
            label="candidate observation",
        )
        evidence = _observation_value(
            self.candidate_source_evidence_observation_json,
            label="candidate source evidence observation",
        )
        disposition = _observation_value(
            self.stable_disposition_inventory_observation_json,
            label="stable disposition inventory observation",
        )
        authority = _observation_value(
            self.semantic_authority_observation_json,
            label="semantic authority observation",
        )
        candidate_id = f"star:{self.output_name}"
        if (
            structural.get("output_name") != self.output_name
            or structural.get("family") != self.family
            or candidate.get("candidate_id") != candidate_id
            or evidence.get("candidate_id") != candidate_id
            or disposition.get("candidate_id") != candidate_id
            or authority.get("output_name") != self.output_name
            or authority.get("expected_candidate_id") != candidate_id
        ):
            raise StarSemanticReviewPacketError(
                "table observations do not share one exact table identity"
            )
        if self.stable_disposition_blockers != tuple(sorted(set(self.stable_disposition_blockers))):
            raise StarSemanticReviewPacketError(
                "stable disposition blockers must be sorted and unique"
            )
        for blocker in self.stable_disposition_blockers:
            _require_id(blocker, field="stable disposition blocker")
        if self.semantic_decision_state == "authored":
            if (
                self.authored_semantic_decision_json is None
                or self.authored_semantic_decision_blockers
            ):
                raise StarSemanticReviewPacketError(
                    "authored semantic decision cannot carry missing-decision blockers"
                )
            decision = _observation_value(
                self.authored_semantic_decision_json,
                label="authored semantic decision",
            )
            if decision.get("table_name") != self.output_name or decision.get(
                "authority_sha256"
            ) != authority.get("authority_sha256"):
                raise StarSemanticReviewPacketError(
                    "authored semantic decision is stale for its exact authority"
                )
        elif self.semantic_decision_state == "missing":
            if (
                self.authored_semantic_decision_json is not None
                or self.authored_semantic_decision_blockers != _MISSING_DECISION_BLOCKERS
            ):
                raise StarSemanticReviewPacketError(
                    "missing semantic decision must preserve the exact corpus blockers"
                )
        else:
            raise StarSemanticReviewPacketError("semantic decision state is unsupported")

    def _content_dict(self) -> dict[str, object]:
        return {
            "output_name": self.output_name,
            "family": self.family,
            "structural_observation": dict(
                _observation_value(
                    self.structural_observation_json,
                    label="structural observation",
                )
            ),
            "candidate_observation": dict(
                _observation_value(
                    self.candidate_observation_json,
                    label="candidate observation",
                )
            ),
            "candidate_source_evidence_observation": dict(
                _observation_value(
                    self.candidate_source_evidence_observation_json,
                    label="candidate source evidence observation",
                )
            ),
            "stable_disposition_inventory_observation": dict(
                _observation_value(
                    self.stable_disposition_inventory_observation_json,
                    label="stable disposition inventory observation",
                )
            ),
            "stable_disposition_blockers": list(self.stable_disposition_blockers),
            "semantic_authority_observation": dict(
                _observation_value(
                    self.semantic_authority_observation_json,
                    label="semantic authority observation",
                )
            ),
            "semantic_decision_state": self.semantic_decision_state,
            "authored_semantic_decision": (
                None
                if self.authored_semantic_decision_json is None
                else dict(
                    _observation_value(
                        self.authored_semantic_decision_json,
                        label="authored semantic decision",
                    )
                )
            ),
            "authored_semantic_decision_blockers": list(self.authored_semantic_decision_blockers),
        }

    @property
    def row_sha256(self) -> str:
        return _sha256(self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "row_sha256": self.row_sha256}


@dataclass(frozen=True, slots=True, init=False)
class StarSemanticReviewPacketV1:
    """Complete exact-denominator, read-only semantic-review work packet."""

    structural_inventory_sha256: str
    candidate_census_sha256: str
    candidate_source_authority_sha256: str
    stable_disposition_inventory_sha256: str
    semantic_authority_inventory_sha256: str
    semantic_decision_corpus_sha256: str
    semantic_decision_corpus_source_bytes_sha256: str
    family_counts: tuple[tuple[str, int], ...]
    tables: tuple[StarSemanticReviewTableV1, ...]

    schema_version: ClassVar[int] = STAR_SEMANTIC_REVIEW_PACKET_SCHEMA_VERSION
    kind: ClassVar[str] = STAR_SEMANTIC_REVIEW_PACKET_KIND
    read_only: ClassVar[bool] = True
    authority_admitted: ClassVar[bool] = False
    model_green: ClassVar[bool] = False

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise StarSemanticReviewPacketError(
            "review packets may only be constructed by the fixed-source compiler"
        )

    @classmethod
    def _from_compiler(
        cls,
        *,
        _token: object,
        structural_inventory_sha256: str,
        candidate_census_sha256: str,
        candidate_source_authority_sha256: str,
        stable_disposition_inventory_sha256: str,
        semantic_authority_inventory_sha256: str,
        semantic_decision_corpus_sha256: str,
        semantic_decision_corpus_source_bytes_sha256: str,
        family_counts: tuple[tuple[str, int], ...],
        tables: tuple[StarSemanticReviewTableV1, ...],
    ) -> Self:
        if _token is not _COMPILER_TOKEN:
            raise StarSemanticReviewPacketError(
                "review packet construction requires the private compiler token"
            )
        packet = object.__new__(cls)
        for field, value in (
            ("structural_inventory_sha256", structural_inventory_sha256),
            ("candidate_census_sha256", candidate_census_sha256),
            ("candidate_source_authority_sha256", candidate_source_authority_sha256),
            ("stable_disposition_inventory_sha256", stable_disposition_inventory_sha256),
            ("semantic_authority_inventory_sha256", semantic_authority_inventory_sha256),
            ("semantic_decision_corpus_sha256", semantic_decision_corpus_sha256),
            (
                "semantic_decision_corpus_source_bytes_sha256",
                semantic_decision_corpus_source_bytes_sha256,
            ),
            ("family_counts", family_counts),
            ("tables", tables),
        ):
            object.__setattr__(packet, field, value)
        packet._validate()
        return packet

    def _validate(self) -> None:
        for field in (
            "structural_inventory_sha256",
            "candidate_census_sha256",
            "candidate_source_authority_sha256",
            "stable_disposition_inventory_sha256",
            "semantic_authority_inventory_sha256",
            "semantic_decision_corpus_sha256",
            "semantic_decision_corpus_source_bytes_sha256",
        ):
            _require_sha256(getattr(self, field), field=field)
        if type(self.tables) is not tuple or any(
            type(item) is not StarSemanticReviewTableV1 for item in self.tables
        ):
            raise StarSemanticReviewPacketError("review tables must be an exact typed tuple")
        if not self.tables or self.tables != tuple(
            sorted(self.tables, key=lambda item: item.output_name)
        ):
            raise StarSemanticReviewPacketError(
                "review tables must be nonempty and sorted by exact output name"
            )
        names = tuple(item.output_name for item in self.tables)
        if len(set(names)) != len(names):
            raise StarSemanticReviewPacketError("review table identities overlap")
        expected_counts = tuple(
            (family, sum(item.family == family for item in self.tables)) for family in _FAMILY_NAMES
        )
        if self.family_counts != expected_counts:
            raise StarSemanticReviewPacketError(
                "family counts differ from the exact review-table denominator"
            )
        if any(
            item.semantic_decision_state == "missing"
            and item.authored_semantic_decision_json is not None
            for item in self.tables
        ):
            raise StarSemanticReviewPacketError(
                "missing decisions cannot be prefilled from observations"
            )

    @property
    def output_names(self) -> tuple[str, ...]:
        return tuple(item.output_name for item in self.tables)

    @property
    def output_count(self) -> int:
        return len(self.tables)

    @property
    def authored_decision_count(self) -> int:
        return sum(item.semantic_decision_state == "authored" for item in self.tables)

    @property
    def missing_decision_count(self) -> int:
        return sum(item.semantic_decision_state == "missing" for item in self.tables)

    def table(self, output_name: str) -> StarSemanticReviewTableV1:
        """Return one exact table work item or fail closed."""

        for item in self.tables:
            if item.output_name == output_name:
                return item
        raise KeyError(output_name)

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "read_only": self.read_only,
            "authority_admitted": self.authority_admitted,
            "model_green": self.model_green,
            "structural_inventory_sha256": self.structural_inventory_sha256,
            "candidate_census_sha256": self.candidate_census_sha256,
            "candidate_source_authority_sha256": self.candidate_source_authority_sha256,
            "stable_disposition_inventory_sha256": (self.stable_disposition_inventory_sha256),
            "semantic_authority_inventory_sha256": self.semantic_authority_inventory_sha256,
            "semantic_decision_corpus_sha256": self.semantic_decision_corpus_sha256,
            "semantic_decision_corpus_source_bytes_sha256": (
                self.semantic_decision_corpus_source_bytes_sha256
            ),
            "output_names": list(self.output_names),
            "output_count": self.output_count,
            "family_counts": {family: count for family, count in self.family_counts},
            "authored_decision_count": self.authored_decision_count,
            "missing_decision_count": self.missing_decision_count,
            "tables": [item.to_dict() for item in self.tables],
        }

    @property
    def packet_sha256(self) -> str:
        return _sha256(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "packet_sha256": self.packet_sha256}

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        """Admit only bytes identical to a fresh exact current-source replay."""

        if cls is not StarSemanticReviewPacketV1:
            raise StarSemanticReviewPacketError("review packet subclasses are not admitted")
        _decode_canonical_bytes(raw)
        current = compile_current_star_semantic_review_packet()
        if raw != current.canonical_bytes:
            raise StarSemanticReviewPacketError(
                "persisted review packet differs from fresh fixed-source compilation"
            )
        return cast("Self", current)


@dataclass(frozen=True, slots=True)
class _CurrentStarSemanticReviewSources:
    """Private typed bundle used to exercise the exact source join in tests."""

    discovered_output_names: tuple[str, ...]
    structural_inventory: StarModelContractInventory
    candidate_census: ModelCandidateCensusV1
    stable_disposition_inventory: StableModelDispositionInventoryV1
    semantic_authorities: tuple[StarTableSemanticAuthorityV1, ...]
    semantic_corpus: StarSemanticDecisionCorpusV1


def _current_star_semantic_review_sources() -> _CurrentStarSemanticReviewSources:
    from nbadb.orchestrate.transformers import expected_transform_output_tables

    discovered = tuple(sorted(expected_transform_output_tables(include_live=True)))
    structural = compile_star_table_contracts()
    census = compile_current_model_candidate_census(
        analytical_needs=canonical_analytical_needs_authority_v1()
    )
    candidates = census.to_stable_candidates()
    stable = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=census.candidate_source_authority_sha256,
        candidates=candidates,
        dispositions=draft_required_model_dispositions(
            candidate_source_authority_sha256=census.candidate_source_authority_sha256,
            candidates=candidates,
        ),
        review_receipts=(),
    )
    authorities = derive_star_semantic_authorities(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
    )
    corpus = load_star_semantic_decision_corpus(authorities=authorities)
    return _CurrentStarSemanticReviewSources(
        discovered_output_names=discovered,
        structural_inventory=structural,
        candidate_census=census,
        stable_disposition_inventory=stable,
        semantic_authorities=authorities,
        semantic_corpus=corpus,
    )


def _exact_name_index(
    rows: Sequence[object],
    *,
    identity: str,
    expected_names: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    names = tuple(cast("str", getattr(row, identity)) for row in rows)
    if names != expected_names:
        raise StarSemanticReviewPacketError(
            f"{label} denominator differs from the exact structural table sequence"
        )
    return {name: row for name, row in zip(names, rows, strict=True)}


def _star_candidate_rows(
    census: ModelCandidateCensusV1,
    expected_names: tuple[str, ...],
) -> tuple[
    dict[str, StableModelCandidateV1],
    dict[str, ModelCandidateCensusEvidenceV1],
]:
    expected_ids = tuple(f"star:{name}" for name in expected_names)
    candidates = tuple(item for item in census.candidates if item.candidate_id.startswith("star:"))
    evidence = tuple(item for item in census.evidence if item.candidate_id.startswith("star:"))
    if (
        tuple(item.candidate_id for item in candidates) != expected_ids
        or tuple(item.candidate_id for item in evidence) != expected_ids
    ):
        raise StarSemanticReviewPacketError(
            "model candidate census does not exactly cover every structural star table"
        )
    try:
        if any(
            StableModelCandidateV1.from_dict(item.to_dict()) != item for item in candidates
        ) or any(
            ModelCandidateCensusEvidenceV1.from_dict(item.to_dict()) != item for item in evidence
        ):
            raise StarSemanticReviewPacketError(
                "model candidate observations failed exact typed reconstruction"
            )
    except StarSemanticReviewPacketError:
        raise
    except (TypeError, ValueError, RuntimeError) as exc:
        raise StarSemanticReviewPacketError(
            "model candidate observations failed exact typed reconstruction"
        ) from exc
    return (
        {item.candidate_id: item for item in candidates},
        {item.candidate_id: item for item in evidence},
    )


def _stable_star_rows(
    stable: StableModelDispositionInventoryV1,
    expected_names: tuple[str, ...],
) -> tuple[
    dict[str, StableModelDispositionV1],
    dict[str, tuple[ModelDispositionBlockerV1, ...]],
]:
    expected_ids = tuple(f"star:{name}" for name in expected_names)
    dispositions = tuple(
        item for item in stable.dispositions if item.candidate_id.startswith("star:")
    )
    if tuple(item.candidate_id for item in dispositions) != expected_ids:
        raise StarSemanticReviewPacketError(
            "stable disposition inventory does not exactly cover every structural star table"
        )
    try:
        if any(StableModelDispositionV1.from_dict(item.to_dict()) != item for item in dispositions):
            raise StarSemanticReviewPacketError(
                "stable disposition observations failed exact typed reconstruction"
            )
    except StarSemanticReviewPacketError:
        raise
    except (TypeError, ValueError, RuntimeError) as exc:
        raise StarSemanticReviewPacketError(
            "stable disposition observations failed exact typed reconstruction"
        ) from exc
    blockers: dict[str, list[ModelDispositionBlockerV1]] = {
        candidate_id: [] for candidate_id in expected_ids
    }
    for blocker in stable.blockers:
        if blocker.candidate_id in blockers:
            blockers[blocker.candidate_id].append(blocker)
    return (
        {item.candidate_id: item for item in dispositions},
        {key: tuple(value) for key, value in blockers.items()},
    )


def _semantic_corpus_rows(
    corpus: StarSemanticDecisionCorpusV1,
    expected_names: tuple[str, ...],
) -> tuple[
    dict[str, StarTableSemanticDecisionV1],
    dict[str, StarSemanticDecisionCorpusBlockerV1],
]:
    decisions = {item.table_name: item for item in corpus.decisions}
    blockers = {item.table_name: item for item in corpus.blockers}
    if tuple(sorted((*decisions, *blockers))) != expected_names or set(decisions) & set(blockers):
        raise StarSemanticReviewPacketError(
            "semantic corpus decisions and blockers do not partition the exact denominator"
        )
    if corpus.unreviewed_table_ids != tuple(sorted(blockers)):
        raise StarSemanticReviewPacketError(
            "semantic corpus unreviewed IDs differ from its exact blockers"
        )
    try:
        if any(
            StarTableSemanticDecisionV1.from_dict(item.to_dict()) != item
            for item in corpus.decisions
        ):
            raise StarSemanticReviewPacketError(
                "authored semantic decisions failed exact typed reconstruction"
            )
    except StarSemanticReviewPacketError:
        raise
    except (TypeError, ValueError, RuntimeError) as exc:
        raise StarSemanticReviewPacketError(
            "authored semantic decisions failed exact typed reconstruction"
        ) from exc
    return decisions, blockers


def _compile_star_semantic_review_packet(
    sources: _CurrentStarSemanticReviewSources,
) -> StarSemanticReviewPacketV1:
    """Private pure join used by the zero-argument current-source compiler."""

    if type(sources) is not _CurrentStarSemanticReviewSources:
        raise StarSemanticReviewPacketError("review sources have a foreign concrete type")
    names = sources.discovered_output_names
    if type(names) is not tuple or not names or names != tuple(sorted(set(names))):
        raise StarSemanticReviewPacketError(
            "discovered output names must be nonempty, sorted, and unique"
        )
    structural = sources.structural_inventory
    structural_names = tuple(item.output_name for item in structural.tables)
    if structural_names != names:
        raise StarSemanticReviewPacketError(
            "structural discovery and star-contract table sequences differ"
        )
    census = sources.candidate_census
    stable = sources.stable_disposition_inventory
    if census.star_model_contract_sha256 != structural.contract_sha256:
        raise StarSemanticReviewPacketError(
            "candidate census has a stale structural inventory root"
        )
    if stable.candidate_source_authority_sha256 != census.candidate_source_authority_sha256:
        raise StarSemanticReviewPacketError(
            "stable disposition inventory has a stale candidate-source root"
        )
    if stable.candidates != census.to_stable_candidates():
        raise StarSemanticReviewPacketError(
            "stable disposition candidates differ from the exact model census"
        )
    try:
        if ModelCandidateCensusV1.from_canonical_bytes(census.canonical_bytes) != census:
            raise StarSemanticReviewPacketError("candidate census failed exact readback")
        if StableModelDispositionInventoryV1.from_canonical_bytes(stable.canonical_bytes) != stable:
            raise StarSemanticReviewPacketError(
                "stable disposition inventory failed exact readback"
            )
        expected_authorities = derive_star_semantic_authorities(
            structural_inventory=structural,
            stable_disposition_inventory=stable,
        )
    except StarSemanticReviewPacketError:
        raise
    except (TypeError, ValueError, RuntimeError) as exc:
        raise StarSemanticReviewPacketError(
            "structural, census, or stable source mutation failed exact reconstruction"
        ) from exc
    authorities = sources.semantic_authorities
    if authorities != expected_authorities:
        raise StarSemanticReviewPacketError(
            "semantic authority denominator differs from fresh exact reconstruction"
        )
    try:
        if any(
            StarTableSemanticAuthorityV1.from_dict(item.to_dict()) != item for item in authorities
        ):
            raise StarSemanticReviewPacketError(
                "semantic authority observations failed exact typed reconstruction"
            )
    except StarSemanticReviewPacketError:
        raise
    except (TypeError, ValueError, RuntimeError) as exc:
        raise StarSemanticReviewPacketError(
            "semantic authority observations failed exact typed reconstruction"
        ) from exc
    authority_by_name = cast(
        "dict[str, StarTableSemanticAuthorityV1]",
        _exact_name_index(
            authorities,
            identity="output_name",
            expected_names=names,
            label="semantic authority",
        ),
    )
    corpus = sources.semantic_corpus
    if (
        corpus.authorities != authorities
        or corpus.structural_inventory_sha256 != structural.contract_sha256
        or corpus.stable_inventory_sha256 != stable.inventory_sha256
    ):
        raise StarSemanticReviewPacketError(
            "semantic decision corpus is stale for current exact authorities"
        )
    candidate_by_id, evidence_by_id = _star_candidate_rows(census, names)
    disposition_by_id, stable_blockers_by_id = _stable_star_rows(stable, names)
    decision_by_name, semantic_blocker_by_name = _semantic_corpus_rows(corpus, names)

    table_by_name = {item.output_name: item for item in structural.tables}
    rows: list[StarSemanticReviewTableV1] = []
    for output_name in names:
        candidate_id = f"star:{output_name}"
        table = table_by_name[output_name]
        candidate = candidate_by_id[candidate_id]
        evidence = evidence_by_id[candidate_id]
        disposition = disposition_by_id[candidate_id]
        authority = authority_by_name[output_name]
        decision = decision_by_name.get(output_name)
        semantic_blocker = semantic_blocker_by_name.get(output_name)
        if (decision is None) == (semantic_blocker is None):
            raise StarSemanticReviewPacketError(
                "each table must have exactly one authored decision or one corpus blocker"
            )
        if decision is not None and decision.authority_sha256 != authority.authority_sha256:
            raise StarSemanticReviewPacketError(
                "authored semantic decision is stale for its exact typed authority"
            )
        rows.append(
            StarSemanticReviewTableV1._from_compiler(
                _token=_COMPILER_TOKEN,
                output_name=output_name,
                family=table.family,
                structural_observation_json=_canonical_observation(
                    _structural_observation(table),
                    label="structural observation",
                ),
                candidate_observation_json=_canonical_observation(
                    candidate.to_dict(),
                    label="candidate observation",
                ),
                candidate_source_evidence_observation_json=_canonical_observation(
                    evidence.to_dict(),
                    label="candidate source evidence observation",
                ),
                stable_disposition_inventory_observation_json=_canonical_observation(
                    disposition.to_dict(),
                    label="stable disposition inventory observation",
                ),
                stable_disposition_blockers=tuple(
                    sorted(item.code for item in stable_blockers_by_id[candidate_id])
                ),
                semantic_authority_observation_json=_canonical_observation(
                    authority.to_dict(),
                    label="semantic authority observation",
                ),
                semantic_decision_state="authored" if decision is not None else "missing",
                authored_semantic_decision_json=(
                    None
                    if decision is None
                    else _canonical_observation(
                        decision.to_dict(),
                        label="authored semantic decision",
                    )
                ),
                authored_semantic_decision_blockers=(
                    () if semantic_blocker is None else semantic_blocker.codes
                ),
            )
        )

    counts = Counter(item.family for item in structural.tables)
    return StarSemanticReviewPacketV1._from_compiler(
        _token=_COMPILER_TOKEN,
        structural_inventory_sha256=structural.contract_sha256,
        candidate_census_sha256=census.census_sha256,
        candidate_source_authority_sha256=census.candidate_source_authority_sha256,
        stable_disposition_inventory_sha256=stable.inventory_sha256,
        semantic_authority_inventory_sha256=corpus.authority_inventory_sha256,
        semantic_decision_corpus_sha256=corpus.corpus_sha256,
        semantic_decision_corpus_source_bytes_sha256=corpus.source_bytes_sha256,
        family_counts=tuple((family, counts[family]) for family in _FAMILY_NAMES),
        tables=tuple(rows),
    )


def compile_current_star_semantic_review_packet() -> StarSemanticReviewPacketV1:
    """Compile current per-table review work from fixed repository authorities."""

    return _compile_star_semantic_review_packet(_current_star_semantic_review_sources())
