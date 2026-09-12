"""Frozen, fail-closed corpus for authored star semantic decisions.

The checked-in v1 resource is intentionally an exact-denominator shard
manifest.  It contains no fabricated decisions: every current table remains
explicitly blocked until a table-specific authoring pass supplies evidence for
the complete :class:`StarTableSemanticDecisionV1` surface.  This module never
creates review receipts or admits semantic contracts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Literal, cast

from nbadb.contracts.star_semantic_authoring import (
    StarSemanticAuthoringGenerationV1,
    StarTableSemanticDecisionV1,
    canonical_star_semantic_authoring_json_bytes,
    canonical_star_semantic_authoring_sha256,
    compile_star_semantic_authoring_generation_v1,
)
from nbadb.contracts.star_semantic_inventory import StarTableSemanticAuthorityV1

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "STAR_SEMANTIC_DECISION_CORPUS_KIND",
    "STAR_SEMANTIC_DECISION_CORPUS_SCHEMA_VERSION",
    "StarSemanticDecisionCorpusBlockerV1",
    "StarSemanticDecisionCorpusError",
    "StarSemanticDecisionCorpusV1",
    "compile_star_semantic_decision_corpus_bytes",
    "load_star_semantic_decision_corpus",
    "parse_star_semantic_decision_corpus",
    "star_semantic_decision_corpus_path",
]

STAR_SEMANTIC_DECISION_CORPUS_SCHEMA_VERSION = 1
STAR_SEMANTIC_DECISION_CORPUS_KIND = "nbadb_star_semantic_decision_corpus_shard_manifest"
_CORPUS_MODE = "exact_denominator_shard_manifest"
_BLOCKER_CODES = (
    "semantic_decision_not_authored",
    "table_specific_semantic_evidence_unreviewed",
)
_REVALIDATION_TRIGGERS = (
    "authority_inventory_changed",
    "decision_shard_extended",
    "stable_disposition_inventory_changed",
    "structural_inventory_changed",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_MAX_TABLES = 10_000
_RESOURCE_NAME = "star-semantic-decisions-v1.json"


class StarSemanticDecisionCorpusError(ValueError):
    """The frozen corpus or its exact authority denominator is invalid."""


def _require_sha256(value: object, *, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise StarSemanticDecisionCorpusError(f"{field} must be a lowercase SHA-256")
    return value


def _require_id(value: object, *, field: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise StarSemanticDecisionCorpusError(f"{field} must be a safe identifier")
    return value


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise StarSemanticDecisionCorpusError(f"{label} must be an exact object")
    return cast("Mapping[str, object]", value)


def _array(value: object, *, label: str) -> list[object]:
    if type(value) is not list or len(value) > _MAX_TABLES:
        raise StarSemanticDecisionCorpusError(f"{label} must be an exact bounded array")
    return cast("list[object]", value)


def _decode_canonical(raw: bytes) -> Mapping[str, object]:
    if type(raw) is not bytes or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise StarSemanticDecisionCorpusError(
            "decision corpus must use exact canonical JSON plus one LF"
        )
    canonical_body = raw[:-1]

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise StarSemanticDecisionCorpusError(
                    "decision corpus contains duplicate JSON keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            canonical_body.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                StarSemanticDecisionCorpusError(
                    f"decision corpus contains non-finite JSON: {value}"
                )
            ),
        )
    except StarSemanticDecisionCorpusError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarSemanticDecisionCorpusError("decision corpus is invalid JSON") from exc
    payload = _mapping(decoded, label="decision corpus")
    if canonical_star_semantic_authoring_json_bytes(payload) != canonical_body:
        raise StarSemanticDecisionCorpusError("decision corpus bytes are not canonical")
    return payload


def _authority_inventory_sha256(
    authorities: Sequence[StarTableSemanticAuthorityV1],
) -> str:
    return canonical_star_semantic_authoring_sha256(
        {
            "schema_version": 1,
            "kind": "nbadb_star_semantic_authority_input",
            "authorities": [authority.to_dict() for authority in authorities],
        }
    )


def _content_payload(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "corpus_sha256"}


def compile_star_semantic_decision_corpus_bytes(
    *,
    authorities: tuple[StarTableSemanticAuthorityV1, ...],
    decision_shards: Sequence[StarTableSemanticDecisionV1],
) -> bytes:
    """Merge literal authored shards by exact table identity into frozen bytes.

    This is a canonical packer, not an author or reviewer.  It copies complete
    :class:`StarTableSemanticDecisionV1` rows supplied by an external author,
    rejects every foreign/stale/duplicate row, and leaves every uncovered
    authority as one explicit table-local blocker.
    """

    if type(authorities) is not tuple or any(
        type(item) is not StarTableSemanticAuthorityV1 for item in authorities
    ):
        raise StarSemanticDecisionCorpusError("authorities must be an exact typed tuple")
    if not authorities or len(authorities) > _MAX_TABLES:
        raise StarSemanticDecisionCorpusError("authority denominator must be nonempty and bounded")
    if authorities != tuple(sorted(authorities, key=lambda item: item.output_name)):
        raise StarSemanticDecisionCorpusError("authority denominator must be sorted")
    authority_names = tuple(item.output_name for item in authorities)
    if len(set(authority_names)) != len(authority_names):
        raise StarSemanticDecisionCorpusError("authority denominator contains duplicates")
    structural_generations = {item.structural_inventory_sha256 for item in authorities}
    stable_generations = {item.stable_inventory_sha256 for item in authorities}
    if len(structural_generations) != 1 or len(stable_generations) != 1:
        raise StarSemanticDecisionCorpusError("authority denominator mixes generations")

    decisions = tuple(decision_shards)
    if len(decisions) > _MAX_TABLES or any(
        type(item) is not StarTableSemanticDecisionV1 for item in decisions
    ):
        raise StarSemanticDecisionCorpusError(
            "decision shards must be exact bounded semantic decisions"
        )
    decisions = tuple(sorted(decisions, key=lambda item: item.table_name))
    decision_names = tuple(item.table_name for item in decisions)
    if len(set(decision_names)) != len(decision_names):
        raise StarSemanticDecisionCorpusError("decision shards contain duplicate table IDs")
    authorities_by_name = {item.output_name: item for item in authorities}
    for decision in decisions:
        authority = authorities_by_name.get(decision.table_name)
        if authority is None:
            raise StarSemanticDecisionCorpusError("decision shard references a foreign table ID")
        if decision.authority_sha256 != authority.authority_sha256:
            raise StarSemanticDecisionCorpusError(
                "decision shard is stale for its exact authority row"
            )

    unreviewed = tuple(sorted(set(authority_names) - set(decision_names)))
    blocker_codes = _BLOCKER_CODES if unreviewed else ()
    content: dict[str, object] = {
        "schema_version": STAR_SEMANTIC_DECISION_CORPUS_SCHEMA_VERSION,
        "kind": STAR_SEMANTIC_DECISION_CORPUS_KIND,
        "corpus_mode": _CORPUS_MODE,
        "structural_inventory_sha256": next(iter(structural_generations)),
        "stable_inventory_sha256": next(iter(stable_generations)),
        "authority_inventory_sha256": _authority_inventory_sha256(authorities),
        "denominator_count": len(authorities),
        "decisions": [decision.to_dict() for decision in decisions],
        "unreviewed_table_ids": list(unreviewed),
        "blocker_codes": list(blocker_codes),
        "blockers": [
            {
                "table_name": table_name,
                "authority_sha256": authorities_by_name[table_name].authority_sha256,
                "blocker_codes": list(blocker_codes),
            }
            for table_name in unreviewed
        ],
        "revalidation_triggers": list(_REVALIDATION_TRIGGERS),
    }
    payload = {
        **content,
        "corpus_sha256": canonical_star_semantic_authoring_sha256(content),
    }
    return canonical_star_semantic_authoring_json_bytes(payload) + b"\n"


@dataclass(frozen=True, slots=True, order=True)
class StarSemanticDecisionCorpusBlockerV1:
    """One explicit table-local authoring blocker in the frozen shard."""

    table_name: str
    codes: tuple[str, ...]
    authority_sha256: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.table_name, field="blocker table_name")
        if self.codes != _BLOCKER_CODES:
            raise StarSemanticDecisionCorpusError(
                "blocker codes must preserve the complete authoring reason set"
            )
        _require_sha256(self.authority_sha256, field="blocker authority_sha256")
        _require_sha256(self.evidence_sha256, field="blocker evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "table_name": self.table_name,
            "codes": list(self.codes),
            "authority_sha256": self.authority_sha256,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class StarSemanticDecisionCorpusV1:
    """Exact authority-bound authored shard, deliberately non-admitted."""

    structural_inventory_sha256: str
    stable_inventory_sha256: str
    authority_inventory_sha256: str
    corpus_sha256: str
    source_bytes_sha256: str
    authorities: tuple[StarTableSemanticAuthorityV1, ...]
    decisions: tuple[StarTableSemanticDecisionV1, ...]
    unreviewed_table_ids: tuple[str, ...]
    blockers: tuple[StarSemanticDecisionCorpusBlockerV1, ...]
    revalidation_triggers: tuple[str, ...]
    _by_table_name: Mapping[str, StarTableSemanticDecisionV1]
    admitted: Literal[False]
    model_green: Literal[False]

    schema_version: ClassVar[int] = STAR_SEMANTIC_DECISION_CORPUS_SCHEMA_VERSION
    kind: ClassVar[str] = STAR_SEMANTIC_DECISION_CORPUS_KIND
    corpus_mode: ClassVar[str] = _CORPUS_MODE

    @property
    def by_table_name(self) -> Mapping[str, StarTableSemanticDecisionV1]:
        return self._by_table_name

    def authoring_generation(self) -> StarSemanticAuthoringGenerationV1:
        """Feed only literal authored rows into the existing non-admitted compiler."""

        return compile_star_semantic_authoring_generation_v1(
            authorities=self.authorities,
            decisions=self.decisions,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "corpus_mode": self.corpus_mode,
            "structural_inventory_sha256": self.structural_inventory_sha256,
            "stable_inventory_sha256": self.stable_inventory_sha256,
            "authority_inventory_sha256": self.authority_inventory_sha256,
            "corpus_sha256": self.corpus_sha256,
            "source_bytes_sha256": self.source_bytes_sha256,
            "denominator_count": len(self.authorities),
            "decision_count": len(self.decisions),
            "unreviewed_table_ids": list(self.unreviewed_table_ids),
            "blockers": [item.to_dict() for item in self.blockers],
            "revalidation_triggers": list(self.revalidation_triggers),
            "admitted": self.admitted,
            "model_green": self.model_green,
        }


def parse_star_semantic_decision_corpus(
    raw: bytes,
    *,
    authorities: tuple[StarTableSemanticAuthorityV1, ...],
) -> StarSemanticDecisionCorpusV1:
    """Bind exact canonical corpus bytes to one complete authority generation."""

    payload = _decode_canonical(raw)
    expected_keys = frozenset(
        {
            "schema_version",
            "kind",
            "corpus_mode",
            "structural_inventory_sha256",
            "stable_inventory_sha256",
            "authority_inventory_sha256",
            "denominator_count",
            "decisions",
            "unreviewed_table_ids",
            "blocker_codes",
            "blockers",
            "revalidation_triggers",
            "corpus_sha256",
        }
    )
    if frozenset(payload) != expected_keys:
        raise StarSemanticDecisionCorpusError("decision corpus fields are missing or unexpected")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != STAR_SEMANTIC_DECISION_CORPUS_SCHEMA_VERSION
        or payload["kind"] != STAR_SEMANTIC_DECISION_CORPUS_KIND
        or payload["corpus_mode"] != _CORPUS_MODE
    ):
        raise StarSemanticDecisionCorpusError("decision corpus schema identity is invalid")
    corpus_sha256 = _require_sha256(payload["corpus_sha256"], field="corpus_sha256")
    if corpus_sha256 != canonical_star_semantic_authoring_sha256(_content_payload(payload)):
        raise StarSemanticDecisionCorpusError("decision corpus digest is invalid")
    if type(authorities) is not tuple or any(
        type(item) is not StarTableSemanticAuthorityV1 for item in authorities
    ):
        raise StarSemanticDecisionCorpusError("authorities must be an exact typed tuple")
    if not authorities or len(authorities) > _MAX_TABLES:
        raise StarSemanticDecisionCorpusError("authority denominator must be nonempty and bounded")
    if authorities != tuple(sorted(authorities, key=lambda item: item.output_name)):
        raise StarSemanticDecisionCorpusError("authority denominator must be sorted")
    authority_names = tuple(item.output_name for item in authorities)
    if len(set(authority_names)) != len(authority_names):
        raise StarSemanticDecisionCorpusError("authority denominator contains duplicates")
    structural_generations = {item.structural_inventory_sha256 for item in authorities}
    stable_generations = {item.stable_inventory_sha256 for item in authorities}
    if len(structural_generations) != 1 or len(stable_generations) != 1:
        raise StarSemanticDecisionCorpusError("authority denominator mixes generations")
    structural_sha256 = _require_sha256(
        payload["structural_inventory_sha256"],
        field="structural_inventory_sha256",
    )
    stable_sha256 = _require_sha256(
        payload["stable_inventory_sha256"],
        field="stable_inventory_sha256",
    )
    if structural_generations != {structural_sha256} or stable_generations != {stable_sha256}:
        raise StarSemanticDecisionCorpusError(
            "decision corpus is stale for the supplied structural or stable authority"
        )
    authority_inventory_sha256 = _require_sha256(
        payload["authority_inventory_sha256"],
        field="authority_inventory_sha256",
    )
    if authority_inventory_sha256 != _authority_inventory_sha256(authorities):
        raise StarSemanticDecisionCorpusError("decision corpus authority rows are stale or foreign")
    if type(payload["denominator_count"]) is not int or payload["denominator_count"] != len(
        authorities
    ):
        raise StarSemanticDecisionCorpusError("decision corpus denominator count is incomplete")

    decisions = tuple(
        StarTableSemanticDecisionV1.from_dict(item)
        for item in _array(payload["decisions"], label="corpus decisions")
    )
    if decisions != tuple(sorted(decisions, key=lambda item: item.table_name)):
        raise StarSemanticDecisionCorpusError("corpus decisions must be sorted")
    decision_names = tuple(item.table_name for item in decisions)
    if len(set(decision_names)) != len(decision_names):
        raise StarSemanticDecisionCorpusError("corpus decisions contain duplicates")
    authorities_by_name = {item.output_name: item for item in authorities}
    for decision in decisions:
        authority = authorities_by_name.get(decision.table_name)
        if authority is None:
            raise StarSemanticDecisionCorpusError("corpus decision references a foreign table")
        if decision.authority_sha256 != authority.authority_sha256:
            raise StarSemanticDecisionCorpusError(
                "corpus decision is stale for its exact authority row"
            )

    unreviewed_values = tuple(
        _require_id(item, field="unreviewed_table_ids")
        for item in _array(
            payload["unreviewed_table_ids"],
            label="unreviewed table IDs",
        )
    )
    expected_unreviewed = tuple(sorted(set(authority_names) - set(decision_names)))
    if unreviewed_values != expected_unreviewed:
        raise StarSemanticDecisionCorpusError(
            "unreviewed table IDs do not exactly cover the decision denominator"
        )
    blocker_codes = tuple(
        _require_id(item, field="blocker_codes")
        for item in _array(payload["blocker_codes"], label="blocker codes")
    )
    expected_blocker_codes = _BLOCKER_CODES if expected_unreviewed else ()
    if blocker_codes != expected_blocker_codes:
        raise StarSemanticDecisionCorpusError(
            "decision corpus blocker codes are incomplete or unsupported"
        )
    source_blockers = tuple(
        _mapping(item, label="corpus blocker")
        for item in _array(payload["blockers"], label="corpus blockers")
    )
    expected_source_blockers = tuple(
        {
            "table_name": table_name,
            "authority_sha256": authorities_by_name[table_name].authority_sha256,
            "blocker_codes": list(expected_blocker_codes),
        }
        for table_name in expected_unreviewed
    )
    if source_blockers != expected_source_blockers:
        raise StarSemanticDecisionCorpusError(
            "decision corpus blockers do not exactly bind every unreviewed authority"
        )
    triggers = tuple(
        _require_id(item, field="revalidation_triggers")
        for item in _array(
            payload["revalidation_triggers"],
            label="revalidation triggers",
        )
    )
    if triggers != _REVALIDATION_TRIGGERS:
        raise StarSemanticDecisionCorpusError(
            "decision corpus revalidation triggers are incomplete"
        )
    blockers = tuple(
        sorted(
            StarSemanticDecisionCorpusBlockerV1(
                table_name=table_name,
                codes=expected_blocker_codes,
                authority_sha256=authorities_by_name[table_name].authority_sha256,
                evidence_sha256=canonical_star_semantic_authoring_sha256(
                    {
                        "schema_version": 1,
                        "kind": "nbadb_star_semantic_decision_corpus_blocker",
                        "table_name": table_name,
                        "codes": list(expected_blocker_codes),
                        "authority_sha256": authorities_by_name[table_name].authority_sha256,
                        "corpus_sha256": corpus_sha256,
                    }
                ),
            )
            for table_name in expected_unreviewed
        )
    )
    return StarSemanticDecisionCorpusV1(
        structural_inventory_sha256=structural_sha256,
        stable_inventory_sha256=stable_sha256,
        authority_inventory_sha256=authority_inventory_sha256,
        corpus_sha256=corpus_sha256,
        source_bytes_sha256=hashlib.sha256(raw).hexdigest(),
        authorities=authorities,
        decisions=decisions,
        unreviewed_table_ids=expected_unreviewed,
        blockers=blockers,
        revalidation_triggers=triggers,
        _by_table_name=MappingProxyType({decision.table_name: decision for decision in decisions}),
        admitted=False,
        model_green=False,
    )


def star_semantic_decision_corpus_path() -> Path:
    """Return the checked-in canonical v1 corpus resource path."""

    return Path(__file__).with_name("data") / _RESOURCE_NAME


def load_star_semantic_decision_corpus(
    *,
    authorities: tuple[StarTableSemanticAuthorityV1, ...],
    path: Path | None = None,
) -> StarSemanticDecisionCorpusV1:
    """Load and authority-bind the checked-in corpus without admitting it."""

    source = star_semantic_decision_corpus_path() if path is None else path
    if not isinstance(source, Path) or not source.is_file() or source.is_symlink():
        raise StarSemanticDecisionCorpusError(
            "decision corpus path must be a regular non-symlink file"
        )
    return parse_star_semantic_decision_corpus(
        source.read_bytes(),
        authorities=authorities,
    )
