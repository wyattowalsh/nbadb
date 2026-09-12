from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import InitVar, dataclass
from dataclasses import field as dataclass_field
from functools import cache, lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Literal, cast

from nbadb.contracts.implicit_competition_source_authority_loader import (
    ImplicitCompetitionSourceAuthorityLoadError,
    load_implicit_competition_current_source_authority,
)
from nbadb.core.nba_api_competition import pinned_competition_authority
from nbadb.core.nba_api_competition_applicability import (
    CompetitionApplicabilityAuthority,
    pinned_competition_applicability_authority,
)
from nbadb.core.nba_api_competition_occurrences import (
    CompetitionOccurrenceAuthority,
    pinned_competition_occurrence_authority,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


IMPLICIT_COMPETITION_RESOURCE = "nba_api_implicit_competition_v1_11_4.json"
IMPLICIT_COMPETITION_SCHEMA_VERSION = 1

_PACKAGED_PROVENANCE_ROOT = (
    "provenance",
    "nba_api_v1_11_4",
    "implicit_competition",
)
_TASK_PACKET = "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2d.json"
_ROOT_EVIDENCE = (
    "artifacts/assurance/complete-nba-api-sink/A1.2d/source-inputs/"
    "implicit-competition-root-evidence.json"
)
_SOURCE_REVIEW = "artifacts/assurance/complete-nba-api-sink/A1.2d/source-inputs/source-review.json"
_EXPECTED_FILE_SHA256 = {
    _TASK_PACKET: "acc12887aa5525a0ed9cc8047264c7efda3da92da745c5145138b4eb2a72e1bb",
    _ROOT_EVIDENCE: "ff848edf46d65bbfc5748e0b30a59d45e2be2a981a578fab73170089aa1c12ba",
    _SOURCE_REVIEW: "d028c60baa78832991d83cbd977d0d555b32b6ebc38a281bb14e7592d76f37e8",
}
_VERIFIER_ID = "nbadb_independent_implicit_competition_v1"
_RECEIPT_SCHEMA = "ReceiptBoundCompetitionRootV1"
_ROOT_KINDS = frozenset({"game", "player", "team", "static"})
_DYNAMIC_ROOT_KINDS = frozenset({"game", "player", "team"})
_ROOT_MODES = frozenset(
    {
        "request_parameter",
        "response_game_collection",
        "response_game_join",
        "embedded_static_dataset",
    }
)
_DYNAMIC_ROOT_MODES = frozenset(
    {"request_parameter", "response_game_collection", "response_game_join"}
)
_LEAGUE_IDS = ("00", "01", "10", "15", "20")
_SYMBOLS = {
    "00": "nba",
    "01": "aba",
    "10": "wnba",
    "15": "summer_league",
    "20": "g_league",
}
_DIGEST_LENGTH = 64
_LIVE_RAW_ROOT_EVIDENCE_SHA256 = "f45dd10412bbd8a45f846b0ebb8f046848d997f0162c4d040baab61fd17ef13f"

RootKind = Literal["game", "player", "team", "static"]
RootMode = Literal[
    "request_parameter",
    "response_game_collection",
    "response_game_join",
    "embedded_static_dataset",
]
RootValue = int | str


class NbaApiImplicitCompetitionError(ValueError):
    """The offline implicit-competition authority is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiImplicitCompetitionError(
            "implicit competition value is not canonical JSON"
        ) from exc


def _pretty_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiImplicitCompetitionError(
            "implicit competition value is not pretty canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NbaApiImplicitCompetitionError(f"{field} must be a canonical SHA-256")
    return value


def _require_identifier(value: object, field: str) -> str:
    if type(value) is not str or not value:
        raise NbaApiImplicitCompetitionError(f"{field} must be a nonempty string")
    return value


def _exact_equal(value: object, expected: object) -> bool:
    """Compare primitive evidence without admitting subclasses or bool-as-int."""

    return type(value) is type(expected) and value == expected


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise NbaApiImplicitCompetitionError(
                f"implicit competition JSON contains duplicate key {key!r}"
            )
        payload[key] = value
    return payload


def _reject_constant(value: str) -> object:
    raise NbaApiImplicitCompetitionError(
        f"implicit competition JSON contains non-finite value {value!r}"
    )


def _strict_json(raw: bytes, *, label: str, pretty: bool) -> dict[str, object]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiImplicitCompetitionError(f"{label} is not strict JSON") from exc
    if type(payload) is not dict:
        raise NbaApiImplicitCompetitionError(f"{label} must be a JSON object")
    expected = _pretty_bytes(payload) if pretty else _canonical_bytes(payload) + b"\n"
    if raw != expected:
        raise NbaApiImplicitCompetitionError(f"{label} bytes are not canonical JSON")
    return payload


def _payload_digest(payload: Mapping[str, object]) -> str:
    body = dict(payload)
    supplied = body.pop("payload_sha256", None)
    expected = _digest(body)
    if _require_digest(supplied, "payload_sha256") != expected:
        raise NbaApiImplicitCompetitionError("payload_sha256 does not match its payload")
    return expected


def _authority_digest(payload: Mapping[str, object]) -> str:
    canonicalization = payload.get("canonicalization")
    if type(canonicalization) is not dict:
        raise NbaApiImplicitCompetitionError("canonicalization authority is missing")
    fields = canonicalization.get("authority_sha256_fields")
    if type(fields) is not list or any(type(field) is not str for field in fields):
        raise NbaApiImplicitCompetitionError("authority digest field projection is invalid")
    field_names = cast("list[str]", fields)
    if len(field_names) != len(set(field_names)) or any(
        field not in payload for field in field_names
    ):
        raise NbaApiImplicitCompetitionError("authority digest field projection is incomplete")
    expected = _digest({field: payload[field] for field in field_names})
    if _require_digest(payload.get("authority_sha256"), "authority_sha256") != expected:
        raise NbaApiImplicitCompetitionError("authority_sha256 does not match its projection")
    return expected


@cache
def _read_sealed(relative_path: str) -> tuple[bytes, dict[str, object]]:
    expected_sha256 = _EXPECTED_FILE_SHA256[relative_path]
    if relative_path not in {_TASK_PACKET, _ROOT_EVIDENCE, _SOURCE_REVIEW}:
        raise NbaApiImplicitCompetitionError(
            f"sealed input {relative_path} has no packaged authority"
        )
    try:
        raw = (
            resources.files("nbadb.contracts")
            .joinpath(*_PACKAGED_PROVENANCE_ROOT, relative_path.rsplit("/", 1)[-1])
            .read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiImplicitCompetitionError(
            f"sealed input {relative_path} cannot be read"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise NbaApiImplicitCompetitionError(f"sealed input {relative_path} drifted")
    payload = _strict_json(raw, label=relative_path, pretty=True)
    if relative_path != _TASK_PACKET:
        _payload_digest(payload)
    return raw, payload


def _verify_canonicalization(payload: Mapping[str, object]) -> None:
    canonicalization = payload.get("canonicalization")
    if type(canonicalization) is not dict:
        raise NbaApiImplicitCompetitionError("canonicalization object is missing")
    if _require_digest(
        payload.get("canonicalization_sha256"), "canonicalization_sha256"
    ) != _digest(canonicalization):
        raise NbaApiImplicitCompetitionError("canonicalization digest drifted")
    if (
        canonicalization.get("sort_keys") is not True
        or canonicalization.get("ensure_ascii") is not False
        or canonicalization.get("allow_nan") is not False
        or canonicalization.get("indent") != 2
        or canonicalization.get("duplicate_keys") != "reject"
    ):
        raise NbaApiImplicitCompetitionError("canonicalization contract is not exact")


def _verify_named_subdigest(payload: Mapping[str, object], name: str) -> None:
    expected = _digest(payload.get(name))
    if _require_digest(payload.get(f"{name}_sha256"), f"{name}_sha256") != expected:
        raise NbaApiImplicitCompetitionError(f"{name} subdigest drifted")


@lru_cache(maxsize=1)
def _task_packet_payload() -> dict[str, object]:
    _, payload = _read_sealed(_TASK_PACKET)
    if payload.get("schema") != "TaskPacketV1" or payload.get("task_id") != "A1.2d":
        raise NbaApiImplicitCompetitionError("A1.2d TaskPacket identity is invalid")
    return payload


@lru_cache(maxsize=1)
def _root_source_payload() -> dict[str, object]:
    raw, payload = _read_sealed(_ROOT_EVIDENCE)
    if (
        payload.get("schema") != "ImplicitCompetitionRootEvidenceV1"
        or payload.get("schema_version") != 1
        or type(payload.get("schema_version")) is not int
        or payload.get("task_id") != "A1.2d"
        or payload.get("evidence_scope") != "offline_implicit_competition_root_source_input_only"
    ):
        raise NbaApiImplicitCompetitionError("implicit root source identity is invalid")
    _verify_canonicalization(payload)
    _authority_digest(payload)
    for name in (
        "competition_values",
        "implicit_alias_complement",
        "root_bindings",
        "static_root_chains",
        "physical_competition_cells",
        "alias_competition_cells",
        "live_raw_root_evidence",
        "repo_source_inventory",
    ):
        _verify_named_subdigest(payload, name)
    if (
        hashlib.sha256(raw).hexdigest() != _EXPECTED_FILE_SHA256[_ROOT_EVIDENCE]
        or payload.get("network_used") is not False
        or payload.get("provider_probe_executed") is not False
        or payload.get("provider_availability_values") != ["unknown"]
        or payload.get("provider_availability_claim_count") != 0
        or payload.get("terminal_status_claim_count") != 0
        or payload.get("upstream_unavailable_claim_count") != 0
    ):
        raise NbaApiImplicitCompetitionError("implicit root source overclaims evidence")
    census = payload.get("census")
    if type(census) is not dict or {
        "implicit_physical_endpoint_count": census.get("implicit_physical_endpoint_count"),
        "implicit_alias_count": census.get("implicit_alias_count"),
        "physical_competition_cell_count": census.get("physical_competition_cell_count"),
        "alias_competition_cell_count": census.get("alias_competition_cell_count"),
    } != {
        "implicit_physical_endpoint_count": 36,
        "implicit_alias_count": 36,
        "physical_competition_cell_count": 180,
        "alias_competition_cell_count": 180,
    }:
        raise NbaApiImplicitCompetitionError("implicit root source denominator drifted")
    for row in cast("list[object]", payload.get("root_bindings")):
        if type(row) is not dict:
            raise NbaApiImplicitCompetitionError("root binding is not an object")
        body = dict(row)
        supplied = body.pop("binding_sha256", None)
        if _require_digest(supplied, "binding_sha256") != _digest(body):
            raise NbaApiImplicitCompetitionError("root binding self-digest drifted")
    for row in cast("list[object]", payload.get("static_root_chains")):
        if type(row) is not dict:
            raise NbaApiImplicitCompetitionError("static root chain is not an object")
        body = dict(row)
        supplied = body.pop("chain_sha256", None)
        if _require_digest(supplied, "chain_sha256") != _digest(body):
            raise NbaApiImplicitCompetitionError("static root chain self-digest drifted")
    inventory = payload.get("repo_source_inventory")
    if type(inventory) is not list or len(inventory) != 13:
        raise NbaApiImplicitCompetitionError("repo source inventory is incomplete")
    historical_paths: list[str] = []
    for row in inventory:
        if type(row) is not dict or set(row) != {"path", "sha256", "size"}:
            raise NbaApiImplicitCompetitionError("repo source inventory row is invalid")
        relative_path = _require_identifier(row.get("path"), "repo source path")
        size = row.get("size")
        if type(size) is not int or size <= 0:
            raise NbaApiImplicitCompetitionError("historical repo source size is invalid")
        _require_digest(row.get("sha256"), "historical repo source sha256")
        historical_paths.append(relative_path)

    # The sealed A1.2d inventory remains immutable historical evidence.  Its
    # byte hashes must not be silently reinterpreted as current source hashes.
    # Current package bytes are admitted only through the separately authored,
    # independently reviewed, pinned sidecar authority.
    try:
        current_source = load_implicit_competition_current_source_authority()
    except ImplicitCompetitionSourceAuthorityLoadError as exc:
        raise NbaApiImplicitCompetitionError(
            "current implicit-competition source authority is invalid"
        ) from exc
    current_paths = tuple(binding.path for binding in current_source.candidate.source_bindings)
    if tuple(historical_paths) != current_paths:
        raise NbaApiImplicitCompetitionError(
            "historical and current implicit source path inventories differ"
        )
    return payload


@lru_cache(maxsize=1)
def _source_review_payload() -> dict[str, object]:
    root_raw, root_payload = _read_sealed(_ROOT_EVIDENCE)
    _, payload = _read_sealed(_SOURCE_REVIEW)
    if (
        payload.get("schema") != "IndependentSourceReviewV1"
        or payload.get("schema_version") != 1
        or type(payload.get("schema_version")) is not int
        or payload.get("task_id") != "A1.2d-source-inputs"
        or payload.get("disposition") != "pass"
        or payload.get("findings") != []
        or payload.get("network_used") is not False
    ):
        raise NbaApiImplicitCompetitionError("implicit source review is not finding-free")
    _verify_canonicalization(payload)
    _authority_digest(payload)
    identities = payload.get("authority_identities")
    if type(identities) is not dict or (
        identities.get("implicit_evidence_resource_sha256") != hashlib.sha256(root_raw).hexdigest()
        or identities.get("implicit_evidence_payload_sha256") != root_payload.get("payload_sha256")
        or identities.get("implicit_evidence_authority_sha256")
        != root_payload.get("authority_sha256")
        or identities.get("implicit_evidence_receipt_policy_sha256")
        != root_payload.get("receipt_bound_root_policy_sha256")
    ):
        raise NbaApiImplicitCompetitionError("implicit source review binds another source")
    return payload


def _root_rows() -> tuple[dict[str, object], ...]:
    rows = _root_source_payload().get("root_bindings")
    if type(rows) is not list or len(rows) != 36 or any(type(row) is not dict for row in rows):
        raise NbaApiImplicitCompetitionError("exact 36 root bindings are required")
    return tuple(cast("dict[str, object]", row) for row in rows)


def _alias_rows() -> tuple[dict[str, object], ...]:
    rows = _root_source_payload().get("implicit_alias_complement")
    if type(rows) is not list or len(rows) != 36 or any(type(row) is not dict for row in rows):
        raise NbaApiImplicitCompetitionError("exact 36 implicit aliases are required")
    return tuple(cast("dict[str, object]", row) for row in rows)


def _cell_rows(kind: Literal["physical", "alias"]) -> tuple[dict[str, object], ...]:
    name = f"{kind}_competition_cells"
    rows = _root_source_payload().get(name)
    if type(rows) is not list or len(rows) != 180 or any(type(row) is not dict for row in rows):
        raise NbaApiImplicitCompetitionError(f"exact 180 {kind} cells are required")
    return tuple(cast("dict[str, object]", row) for row in rows)


def _binding_row(binding_sha256: str) -> dict[str, object]:
    matches = [row for row in _root_rows() if row.get("binding_sha256") == binding_sha256]
    if len(matches) != 1:
        raise NbaApiImplicitCompetitionError("root binding digest is not unique and current")
    return matches[0]


def _static_chain(chain_sha256: str) -> dict[str, object]:
    rows = _root_source_payload().get("static_root_chains")
    if type(rows) is not list:
        raise NbaApiImplicitCompetitionError("static root chains are missing")
    matches = [row for row in rows if type(row) is dict and row.get("chain_sha256") == chain_sha256]
    if len(matches) != 1:
        raise NbaApiImplicitCompetitionError("static root chain is not unique and current")
    return cast("dict[str, object]", matches[0])


def _root_value_type(value: object) -> str:
    if type(value) is str and value:
        return "str"
    if type(value) is int:
        return "int"
    raise NbaApiImplicitCompetitionError("root value must be an exact nonempty str or int")


@dataclass(frozen=True, slots=True)
class CompetitionRootRequirement:
    """One exact mode-discriminated root requirement from the sealed source."""

    root_binding_sha256: str
    root_kind: RootKind
    root_mode: RootMode
    provider_occurrence_id: str | None
    parameter_location: str | None
    source_signature_sha256: str | None
    typed_domain_sha256: str | None
    root_value_types: tuple[str, ...]
    live_raw_root_evidence_sha256: str | None
    static_chain_sha256: str | None
    fixed_league_id: str | None
    fixed_symbol: str | None
    receipt_required_before_request: bool
    receipt_join_required: bool

    def __post_init__(self) -> None:
        _require_digest(self.root_binding_sha256, "root_binding_sha256")
        if (
            type(self.root_kind) is not str
            or self.root_kind not in _ROOT_KINDS
            or type(self.root_mode) is not str
            or self.root_mode not in _ROOT_MODES
        ):
            raise NbaApiImplicitCompetitionError("root requirement discriminator is invalid")
        if (
            type(self.root_value_types) is not tuple
            or not self.root_value_types
            or self.root_value_types != tuple(dict.fromkeys(self.root_value_types))
            or any(
                type(value) is not str or value not in {"int", "str"}
                for value in self.root_value_types
            )
            or type(self.receipt_required_before_request) is not bool
            or type(self.receipt_join_required) is not bool
        ):
            raise NbaApiImplicitCompetitionError(
                "root requirement value types or booleans are invalid"
            )
        if self.root_mode == "request_parameter":
            if (
                self.root_kind not in _DYNAMIC_ROOT_KINDS
                or type(self.provider_occurrence_id) is not str
                or not self.provider_occurrence_id
                or type(self.parameter_location) is not str
                or self.parameter_location not in {"path", "query"}
                or type(self.source_signature_sha256) is not str
                or type(self.typed_domain_sha256) is not str
                or self.live_raw_root_evidence_sha256 is not None
                or self.static_chain_sha256 is not None
                or self.fixed_league_id is not None
                or self.fixed_symbol is not None
                or self.receipt_required_before_request is not True
                or self.receipt_join_required is not False
            ):
                raise NbaApiImplicitCompetitionError("request root requirement state is invalid")
            _require_digest(self.source_signature_sha256, "source_signature_sha256")
            _require_digest(self.typed_domain_sha256, "typed_domain_sha256")
        elif self.root_mode in {"response_game_collection", "response_game_join"}:
            if (
                self.root_kind != "game"
                or self.provider_occurrence_id is not None
                or self.parameter_location is not None
                or self.source_signature_sha256 is not None
                or self.typed_domain_sha256 is not None
                or self.root_value_types != ("str",)
                or type(self.live_raw_root_evidence_sha256) is not str
                or self.static_chain_sha256 is not None
                or self.fixed_league_id is not None
                or self.fixed_symbol is not None
                or self.receipt_required_before_request is not False
                or self.receipt_join_required is not True
            ):
                raise NbaApiImplicitCompetitionError("response root requirement state is invalid")
            _require_digest(
                self.live_raw_root_evidence_sha256,
                "live_raw_root_evidence_sha256",
            )
        elif (
            self.root_kind != "static"
            or self.provider_occurrence_id is not None
            or self.parameter_location is not None
            or self.source_signature_sha256 is not None
            or self.typed_domain_sha256 is not None
            or self.root_value_types != ("str",)
            or self.live_raw_root_evidence_sha256 is not None
            or type(self.static_chain_sha256) is not str
            or type(self.fixed_league_id) is not str
            or self.fixed_league_id not in _LEAGUE_IDS
            or type(self.fixed_symbol) is not str
            or self.fixed_symbol != _SYMBOLS.get(self.fixed_league_id)
            or self.receipt_required_before_request is not False
            or self.receipt_join_required is not False
        ):
            raise NbaApiImplicitCompetitionError("static root requirement state is invalid")
        if self.static_chain_sha256 is not None:
            _require_digest(self.static_chain_sha256, "static_chain_sha256")
        row = _binding_row(self.root_binding_sha256)
        if self.to_source_parts() != _requirement_parts(row):
            raise NbaApiImplicitCompetitionError("root requirement differs from its exact binding")

    def to_source_parts(self) -> tuple[str, str, dict[str, object]]:
        evidence: dict[str, object]
        if self.root_mode == "request_parameter":
            evidence = {
                "parameter": {
                    "coverage_policy": "enumerate_discovered_values",
                    "domain_kind": "discovered_identifier",
                    "location": self.parameter_location,
                    "name": {"game": "game_id", "player": "player_id", "team": "team_id"}[
                        self.root_kind
                    ],
                    "nullable": False,
                    "occurrence_id": self.provider_occurrence_id,
                    "ordinal": 0,
                    "query_name": {"game": "GameID", "player": "PlayerID", "team": "TeamID"}[
                        self.root_kind
                    ],
                    "required": True,
                    "semantic_role": "discovery_key",
                    "source_signature_sha256": self.source_signature_sha256,
                    "typed_domain_sha256": self.typed_domain_sha256,
                    "value_types": list(self.root_value_types),
                },
                "receipt_required_before_request": self.receipt_required_before_request,
                "repo_root_parameter_name": {
                    "game": "game_id",
                    "player": "player_id",
                    "team": "team_id",
                }[self.root_kind],
            }
        elif self.root_mode in {"response_game_collection", "response_game_join"}:
            evidence = {
                "live_raw_root_evidence_sha256": self.live_raw_root_evidence_sha256,
                "receipt_join_required": self.receipt_join_required,
            }
        else:
            evidence = {
                "fixed_league_id": self.fixed_league_id,
                "fixed_symbol": self.fixed_symbol,
                "provider_default_used": False,
                "static_chain_sha256": self.static_chain_sha256,
            }
        return self.root_kind, self.root_mode, evidence


def _requirement_parts(row: Mapping[str, object]) -> tuple[str, str, dict[str, object]]:
    root_kind = _require_identifier(row.get("root_kind"), "root_kind")
    root_mode = _require_identifier(row.get("root_mode"), "root_mode")
    evidence = row.get("root_evidence")
    if type(evidence) is not dict:
        raise NbaApiImplicitCompetitionError("root evidence must be an exact object")
    return root_kind, root_mode, cast("dict[str, object]", evidence)


def _requirement_from_row(row: Mapping[str, object]) -> CompetitionRootRequirement:
    root_kind = cast("RootKind", row["root_kind"])
    root_mode = cast("RootMode", row["root_mode"])
    evidence = cast("dict[str, object]", row["root_evidence"])
    provider_occurrence_id: str | None = None
    parameter_location: str | None = None
    source_signature_sha256: str | None = None
    typed_domain_sha256: str | None = None
    root_value_types: tuple[str, ...] = ("str",)
    live_sha256: str | None = None
    static_sha256: str | None = None
    fixed_league_id: str | None = None
    fixed_symbol: str | None = None
    before_request = False
    join_required = False
    if root_mode == "request_parameter":
        parameter = cast("dict[str, object]", evidence["parameter"])
        provider_occurrence_id = cast("str", parameter["occurrence_id"])
        parameter_location = cast("str", parameter["location"])
        source_signature_sha256 = cast("str", parameter["source_signature_sha256"])
        typed_domain_sha256 = cast("str", parameter["typed_domain_sha256"])
        root_value_types = tuple(cast("list[str]", parameter["value_types"]))
        before_request = cast("bool", evidence["receipt_required_before_request"])
    elif root_mode in {"response_game_collection", "response_game_join"}:
        live_sha256 = cast("str", evidence["live_raw_root_evidence_sha256"])
        join_required = cast("bool", evidence["receipt_join_required"])
    else:
        static_sha256 = cast("str", evidence["static_chain_sha256"])
        fixed_league_id = cast("str", evidence["fixed_league_id"])
        fixed_symbol = cast("str", evidence["fixed_symbol"])
    return CompetitionRootRequirement(
        root_binding_sha256=cast("str", row["binding_sha256"]),
        root_kind=root_kind,
        root_mode=root_mode,
        provider_occurrence_id=provider_occurrence_id,
        parameter_location=parameter_location,
        source_signature_sha256=source_signature_sha256,
        typed_domain_sha256=typed_domain_sha256,
        root_value_types=root_value_types,
        live_raw_root_evidence_sha256=live_sha256,
        static_chain_sha256=static_sha256,
        fixed_league_id=fixed_league_id,
        fixed_symbol=fixed_symbol,
        receipt_required_before_request=before_request,
        receipt_join_required=join_required,
    )


_COMMON_VARIANT_FIELDS = frozenset(
    {
        "root_kind",
        "root_value",
        "league_id",
        "competition_authority_sha256",
        "root_binding_sha256",
        "root_mode",
        "root_generation_sha256",
        "source_endpoint_id",
        "source_request_identity_sha256",
        "source_request_receipt_sha256",
    }
)
_PRODUCER_VARIANT_FIELDS = frozenset(
    {
        "producer_schema",
        "producer_task_id",
        "producer_artifact_sha256",
        "producer_payload_sha256",
        "producer_receipt_sha256",
        "source_scope_sha256",
    }
)
_PRODUCER_RECEIPT_FIELDS = frozenset(
    {
        "artifact_sha256",
        "payload_sha256",
        "receipt_sha256",
        "schema",
        "source_request_identity_sha256",
        "source_scope_sha256",
        "task_id",
    }
)
_MODE_VARIANT_FIELDS = {
    "request_parameter": frozenset(
        {
            "provider_occurrence_id",
            "source_signature_sha256",
            "typed_domain_sha256",
            "root_value_type",
        }
    ),
    "response_game_collection": frozenset(
        {
            "live_raw_root_evidence_sha256",
            "captured_body_sha256",
            "league_id_json_path",
            "game_id_json_path",
            "captured_league_id",
            "captured_game_id",
            "result_occurrence_sha256",
            "row_ordinal",
            "root_value_type",
        }
    ),
    "response_game_join": frozenset(
        {
            "live_raw_root_evidence_sha256",
            "captured_body_sha256",
            "game_id_json_path",
            "captured_game_id",
            "result_occurrence_sha256",
            "row_ordinal",
            "root_value_type",
        }
    ),
}


def _retained_evidence_dict(
    items: object,
    required_fields: frozenset[str],
    label: str,
) -> dict[str, object]:
    """Reload one exact normalized private evidence copy without coercion."""

    if type(items) is not tuple:
        raise NbaApiImplicitCompetitionError(f"retained {label} evidence is not immutable")
    evidence: dict[str, object] = {}
    previous_field: str | None = None
    for item in items:
        if type(item) is not tuple or len(item) != 2:
            raise NbaApiImplicitCompetitionError(f"retained {label} evidence item is invalid")
        evidence_field, value = item
        if (
            type(evidence_field) is not str
            or evidence_field in evidence
            or (previous_field is not None and evidence_field <= previous_field)
        ):
            raise NbaApiImplicitCompetitionError(
                f"retained {label} evidence fields are not normalized"
            )
        evidence[evidence_field] = value
        previous_field = evidence_field
    if set(evidence) != required_fields:
        raise NbaApiImplicitCompetitionError(f"retained {label} evidence fields are not exact")
    return evidence


@dataclass(frozen=True, slots=True)
class ReceiptBoundCompetitionRoot:
    """A dynamic root receipt validated with its complete typed evidence."""

    schema: str
    root_kind: str
    root_value: RootValue
    league_id: str
    competition_authority_sha256: str
    root_binding_sha256: str
    root_mode: str
    root_generation_sha256: str
    source_endpoint_id: str
    source_request_identity_sha256: str
    source_request_receipt_sha256: str
    variant_evidence_sha256: str
    root_observation_sha256: str
    receipt_sha256: str
    variant_evidence: InitVar[Mapping[str, object]]
    producer_receipt: InitVar[Mapping[str, object]]
    _variant_evidence_items: tuple[tuple[str, object], ...] = dataclass_field(
        init=False,
        repr=False,
        compare=False,
    )
    _producer_receipt_items: tuple[tuple[str, object], ...] = dataclass_field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(
        self,
        variant_evidence: Mapping[str, object],
        producer_receipt: Mapping[str, object],
    ) -> None:
        if type(variant_evidence) is not dict or type(producer_receipt) is not dict:
            raise NbaApiImplicitCompetitionError(
                "typed variant and producer evidence must be exact dicts"
            )
        if any(type(evidence_field) is not str for evidence_field in variant_evidence):
            raise NbaApiImplicitCompetitionError("typed variant evidence fields are not exact")
        if any(type(evidence_field) is not str for evidence_field in producer_receipt):
            raise NbaApiImplicitCompetitionError("producer receipt fields are not exact")
        object.__setattr__(
            self,
            "_variant_evidence_items",
            tuple(sorted(variant_evidence.items())),
        )
        object.__setattr__(
            self,
            "_producer_receipt_items",
            tuple(sorted(producer_receipt.items())),
        )
        self._revalidate()

    def _revalidate(self) -> None:
        """Revalidate the complete retained receipt chain before every use."""

        if (
            type(self.schema) is not str
            or self.schema != _RECEIPT_SCHEMA
            or type(self.root_kind) is not str
            or self.root_kind not in _DYNAMIC_ROOT_KINDS
            or type(self.root_mode) is not str
            or self.root_mode not in _DYNAMIC_ROOT_MODES
            or type(self.league_id) is not str
            or self.league_id not in _LEAGUE_IDS
            or type(self.source_endpoint_id) is not str
            or not self.source_endpoint_id
        ):
            raise NbaApiImplicitCompetitionError("dynamic root receipt identity is invalid")
        value_type = _root_value_type(self.root_value)
        for field, value in (
            ("competition_authority_sha256", self.competition_authority_sha256),
            ("root_binding_sha256", self.root_binding_sha256),
            ("root_generation_sha256", self.root_generation_sha256),
            ("source_request_identity_sha256", self.source_request_identity_sha256),
            ("source_request_receipt_sha256", self.source_request_receipt_sha256),
            ("variant_evidence_sha256", self.variant_evidence_sha256),
            ("root_observation_sha256", self.root_observation_sha256),
            ("receipt_sha256", self.receipt_sha256),
        ):
            _require_digest(value, field)
        competition = pinned_competition_authority()
        if self.competition_authority_sha256 != competition.authority_sha256:
            raise NbaApiImplicitCompetitionError("receipt binds another competition authority")
        binding = _binding_row(self.root_binding_sha256)
        requirement = _requirement_from_row(binding)
        if (
            self.root_kind != requirement.root_kind
            or self.root_mode != requirement.root_mode
            or self.source_endpoint_id != binding["provider_endpoint_id"]
            or value_type not in requirement.root_value_types
        ):
            raise NbaApiImplicitCompetitionError("receipt root does not match its binding")
        required_fields = (
            _COMMON_VARIANT_FIELDS | _PRODUCER_VARIANT_FIELDS | _MODE_VARIANT_FIELDS[self.root_mode]
        )
        variant = _retained_evidence_dict(
            self._variant_evidence_items,
            required_fields,
            "typed variant",
        )
        common = {
            "root_kind": self.root_kind,
            "root_value": self.root_value,
            "league_id": self.league_id,
            "competition_authority_sha256": self.competition_authority_sha256,
            "root_binding_sha256": self.root_binding_sha256,
            "root_mode": self.root_mode,
            "root_generation_sha256": self.root_generation_sha256,
            "source_endpoint_id": self.source_endpoint_id,
            "source_request_identity_sha256": self.source_request_identity_sha256,
            "source_request_receipt_sha256": self.source_request_receipt_sha256,
        }
        if any(not _exact_equal(variant.get(field), value) for field, value in common.items()):
            raise NbaApiImplicitCompetitionError("typed variant common identity drifted")
        for field in (
            "producer_artifact_sha256",
            "producer_payload_sha256",
            "producer_receipt_sha256",
            "source_scope_sha256",
        ):
            _require_digest(variant.get(field), field)
        _require_identifier(variant.get("producer_schema"), "producer_schema")
        _require_identifier(variant.get("producer_task_id"), "producer_task_id")
        if not _exact_equal(
            variant["producer_receipt_sha256"], self.source_request_receipt_sha256
        ) or not _exact_equal(variant["source_scope_sha256"], self.root_generation_sha256):
            raise NbaApiImplicitCompetitionError("producer evidence does not bind the receipt")
        producer_receipt = _retained_evidence_dict(
            self._producer_receipt_items,
            _PRODUCER_RECEIPT_FIELDS,
            "producer receipt",
        )
        producer_body = dict(producer_receipt)
        producer_sha256 = producer_body.pop("receipt_sha256", None)
        if (
            _require_digest(producer_sha256, "producer receipt_sha256")
            != self.source_request_receipt_sha256
            or _digest(producer_body) != self.source_request_receipt_sha256
        ):
            raise NbaApiImplicitCompetitionError("producer receipt digest is invalid")
        for field in (
            "artifact_sha256",
            "payload_sha256",
            "source_request_identity_sha256",
            "source_scope_sha256",
        ):
            _require_digest(producer_body.get(field), f"producer {field}")
        _require_identifier(producer_body.get("schema"), "producer schema")
        _require_identifier(producer_body.get("task_id"), "producer task_id")
        producer_bindings = {
            "producer_artifact_sha256": producer_body["artifact_sha256"],
            "producer_payload_sha256": producer_body["payload_sha256"],
            "producer_receipt_sha256": producer_sha256,
            "producer_schema": producer_body["schema"],
            "producer_task_id": producer_body["task_id"],
            "source_scope_sha256": producer_body["source_scope_sha256"],
        }
        if any(
            not _exact_equal(variant.get(field), value)
            for field, value in producer_bindings.items()
        ) or any(
            not _exact_equal(producer_body.get(field), value)
            for field, value in (
                ("source_request_identity_sha256", self.source_request_identity_sha256),
                ("source_scope_sha256", self.root_generation_sha256),
            )
        ):
            raise NbaApiImplicitCompetitionError(
                "producer receipt does not match its typed and source commitments"
            )
        self._validate_mode_variant(variant, requirement, value_type)
        if _digest(variant) != self.variant_evidence_sha256:
            raise NbaApiImplicitCompetitionError("variant evidence digest is invalid")
        observation = {
            "schema": self.schema,
            "root_kind": self.root_kind,
            "root_value": self.root_value,
            "league_id": self.league_id,
            "competition_authority_sha256": self.competition_authority_sha256,
            "root_binding_sha256": self.root_binding_sha256,
            "root_mode": self.root_mode,
            "root_generation_sha256": self.root_generation_sha256,
            "source_endpoint_id": self.source_endpoint_id,
            "source_request_identity_sha256": self.source_request_identity_sha256,
            "source_request_receipt_sha256": self.source_request_receipt_sha256,
            "variant_evidence_sha256": self.variant_evidence_sha256,
        }
        if _digest(observation) != self.root_observation_sha256:
            raise NbaApiImplicitCompetitionError("root observation digest is invalid")
        if _digest(self.to_dict(include_receipt_sha256=False)) != self.receipt_sha256:
            raise NbaApiImplicitCompetitionError("root receipt digest is invalid")

    def _validate_mode_variant(
        self,
        variant: Mapping[str, object],
        requirement: CompetitionRootRequirement,
        value_type: str,
    ) -> None:
        if not _exact_equal(variant.get("root_value_type"), value_type):
            raise NbaApiImplicitCompetitionError("typed variant root value type is invalid")
        if self.root_mode == "request_parameter":
            expected = {
                "provider_occurrence_id": requirement.provider_occurrence_id,
                "source_signature_sha256": requirement.source_signature_sha256,
                "typed_domain_sha256": requirement.typed_domain_sha256,
                "root_value_type": value_type,
            }
            if any(
                not _exact_equal(variant.get(field), value) for field, value in expected.items()
            ):
                raise NbaApiImplicitCompetitionError("request root locator evidence drifted")
            return
        if (
            not _exact_equal(
                variant.get("live_raw_root_evidence_sha256"),
                _LIVE_RAW_ROOT_EVIDENCE_SHA256,
            )
            or not _exact_equal(variant.get("captured_game_id"), self.root_value)
            or not _exact_equal(variant.get("root_value_type"), "str")
            or type(variant.get("row_ordinal")) is not int
            or cast("int", variant["row_ordinal"]) < 0
        ):
            raise NbaApiImplicitCompetitionError("live game root evidence is invalid")
        for field in ("captured_body_sha256", "result_occurrence_sha256"):
            _require_digest(variant.get(field), field)
        if self.root_mode == "response_game_join":
            if not _exact_equal(variant.get("game_id_json_path"), "$.games.gameId"):
                raise NbaApiImplicitCompetitionError("Odds game path drifted")
        elif (
            not _exact_equal(variant.get("league_id_json_path"), "$.scoreboard.leagueId")
            or not _exact_equal(variant.get("game_id_json_path"), "$.scoreboard.games.gameId")
            or not _exact_equal(variant.get("captured_league_id"), self.league_id)
        ):
            raise NbaApiImplicitCompetitionError("ScoreBoard league/game evidence disagrees")

    def to_dict(self, *, include_receipt_sha256: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "competition_authority_sha256": self.competition_authority_sha256,
            "league_id": self.league_id,
            "receipt_sha256": self.receipt_sha256,
            "root_binding_sha256": self.root_binding_sha256,
            "root_generation_sha256": self.root_generation_sha256,
            "root_kind": self.root_kind,
            "root_mode": self.root_mode,
            "root_observation_sha256": self.root_observation_sha256,
            "root_value": self.root_value,
            "schema": self.schema,
            "source_endpoint_id": self.source_endpoint_id,
            "source_request_identity_sha256": self.source_request_identity_sha256,
            "source_request_receipt_sha256": self.source_request_receipt_sha256,
            "variant_evidence_sha256": self.variant_evidence_sha256,
        }
        if not include_receipt_sha256:
            payload.pop("receipt_sha256")
        return payload


@dataclass(frozen=True, slots=True)
class ImplicitCompetitionEndpointBinding:
    """One exact implicit physical endpoint/root binding."""

    physical_endpoint_key: str
    repo_endpoint_name: str
    provider_endpoint_id: str
    source_family: str
    extractor_module: str
    extractor_qualname: str
    repo_source_path: str
    repo_source_sha256: str
    repo_source_size: int
    provider_source_path: str
    provider_source_sha256: str
    provider_source_size: int
    provider_contract_sha256: str
    explicit_competition_axis_status: str
    explicit_competition_axis_occurrence_ids: tuple[str, ...]
    forwarding_behavior: str
    root_requirement: CompetitionRootRequirement
    binding_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "physical_endpoint_key",
            "repo_endpoint_name",
            "provider_endpoint_id",
            "source_family",
            "extractor_module",
            "extractor_qualname",
            "repo_source_path",
            "provider_source_path",
            "explicit_competition_axis_status",
            "forwarding_behavior",
        ):
            _require_identifier(getattr(self, field), field)
        for field in (
            "repo_source_sha256",
            "provider_source_sha256",
            "provider_contract_sha256",
            "binding_sha256",
        ):
            _require_digest(getattr(self, field), field)
        if (
            type(self.repo_source_size) is not int
            or self.repo_source_size <= 0
            or type(self.provider_source_size) is not int
            or self.provider_source_size <= 0
            or type(self.explicit_competition_axis_occurrence_ids) is not tuple
            or self.explicit_competition_axis_occurrence_ids
            or type(self.root_requirement) is not CompetitionRootRequirement
            or self.root_requirement.root_binding_sha256 != self.binding_sha256
        ):
            raise NbaApiImplicitCompetitionError("endpoint binding types or axis state are invalid")
        row = _binding_row(self.binding_sha256)
        if self.to_dict() != row:
            raise NbaApiImplicitCompetitionError("endpoint binding differs from sealed source")

    def to_dict(self) -> dict[str, object]:
        root_kind, root_mode, root_evidence = self.root_requirement.to_source_parts()
        return {
            "binding_sha256": self.binding_sha256,
            "explicit_competition_axis_occurrence_ids": list(
                self.explicit_competition_axis_occurrence_ids
            ),
            "explicit_competition_axis_status": self.explicit_competition_axis_status,
            "extractor_module": self.extractor_module,
            "extractor_qualname": self.extractor_qualname,
            "forwarding_behavior": self.forwarding_behavior,
            "physical_endpoint_key": self.physical_endpoint_key,
            "provider_contract_sha256": self.provider_contract_sha256,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_source_path": self.provider_source_path,
            "provider_source_sha256": self.provider_source_sha256,
            "provider_source_size": self.provider_source_size,
            "repo_endpoint_name": self.repo_endpoint_name,
            "repo_source_path": self.repo_source_path,
            "repo_source_sha256": self.repo_source_sha256,
            "repo_source_size": self.repo_source_size,
            "root_evidence": root_evidence,
            "root_kind": root_kind,
            "root_mode": root_mode,
            "source_family": self.source_family,
        }


def _endpoint_binding_from_row(row: Mapping[str, object]) -> ImplicitCompetitionEndpointBinding:
    return ImplicitCompetitionEndpointBinding(
        physical_endpoint_key=cast("str", row["physical_endpoint_key"]),
        repo_endpoint_name=cast("str", row["repo_endpoint_name"]),
        provider_endpoint_id=cast("str", row["provider_endpoint_id"]),
        source_family=cast("str", row["source_family"]),
        extractor_module=cast("str", row["extractor_module"]),
        extractor_qualname=cast("str", row["extractor_qualname"]),
        repo_source_path=cast("str", row["repo_source_path"]),
        repo_source_sha256=cast("str", row["repo_source_sha256"]),
        repo_source_size=cast("int", row["repo_source_size"]),
        provider_source_path=cast("str", row["provider_source_path"]),
        provider_source_sha256=cast("str", row["provider_source_sha256"]),
        provider_source_size=cast("int", row["provider_source_size"]),
        provider_contract_sha256=cast("str", row["provider_contract_sha256"]),
        explicit_competition_axis_status=cast("str", row["explicit_competition_axis_status"]),
        explicit_competition_axis_occurrence_ids=tuple(
            cast("list[str]", row["explicit_competition_axis_occurrence_ids"])
        ),
        forwarding_behavior=cast("str", row["forwarding_behavior"]),
        root_requirement=_requirement_from_row(row),
        binding_sha256=cast("str", row["binding_sha256"]),
    )


@dataclass(frozen=True, slots=True)
class ImplicitCompetitionAliasBinding:
    """One exact current repo alias in the implicit complement."""

    provider_endpoint_id: str
    repo_endpoint_name: str
    source_family: str
    source_path: str

    def __post_init__(self) -> None:
        for field in ("provider_endpoint_id", "repo_endpoint_name", "source_family", "source_path"):
            _require_identifier(getattr(self, field), field)
        matches = [row for row in _alias_rows() if row == self.to_dict()]
        if len(matches) != 1:
            raise NbaApiImplicitCompetitionError("alias binding is not exact and current")
        bindings = [
            row
            for row in _root_rows()
            if row["provider_endpoint_id"] == self.provider_endpoint_id
            and row["repo_endpoint_name"] == self.repo_endpoint_name
            and row["source_family"] == self.source_family
        ]
        if len(bindings) != 1:
            raise NbaApiImplicitCompetitionError("alias does not bind one physical endpoint")

    @property
    def root_binding_sha256(self) -> str:
        return cast(
            "str",
            next(
                row["binding_sha256"]
                for row in _root_rows()
                if row["provider_endpoint_id"] == self.provider_endpoint_id
                and row["repo_endpoint_name"] == self.repo_endpoint_name
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_endpoint_id": self.provider_endpoint_id,
            "repo_endpoint_name": self.repo_endpoint_name,
            "source_family": self.source_family,
            "source_path": self.source_path,
        }


@dataclass(frozen=True, slots=True)
class ImplicitCompetitionCell:
    """One exact physical or alias implicit-competition cell."""

    cell_kind: Literal["physical", "alias"]
    assignment_authority: str
    cell_id: str
    endpoint_support_status: str
    league_id: str
    physical_endpoint_key: str
    provider_availability_status: str
    provider_endpoint_id: str
    provider_probe_executed: bool
    request_terminal_state: str
    root_binding_sha256: str
    root_kind: str
    root_state: str
    source_family: str
    symbol: str
    repo_endpoint_name: str | None = None

    def __post_init__(self) -> None:
        if type(self.cell_kind) is not str or self.cell_kind not in {"physical", "alias"}:
            raise NbaApiImplicitCompetitionError("competition cell kind is invalid")
        for field in (
            "assignment_authority",
            "cell_id",
            "physical_endpoint_key",
            "provider_endpoint_id",
            "root_kind",
            "root_state",
            "source_family",
            "symbol",
        ):
            _require_identifier(getattr(self, field), field)
        _require_digest(self.root_binding_sha256, "root_binding_sha256")
        if (
            type(self.league_id) is not str
            or self.league_id not in _LEAGUE_IDS
            or self.symbol != _SYMBOLS[self.league_id]
            or type(self.endpoint_support_status) is not str
            or self.endpoint_support_status != "unknown"
            or type(self.provider_availability_status) is not str
            or self.provider_availability_status != "unknown"
            or type(self.provider_probe_executed) is not bool
            or self.provider_probe_executed
            or type(self.request_terminal_state) is not str
            or self.request_terminal_state != "not_asserted"
            or (
                self.repo_endpoint_name is not None
                and (type(self.repo_endpoint_name) is not str or not self.repo_endpoint_name)
            )
            or (self.cell_kind == "physical") != (self.repo_endpoint_name is None)
        ):
            raise NbaApiImplicitCompetitionError(
                "competition cell makes an unsupported availability or terminal claim"
            )
        rows = _cell_rows(self.cell_kind)
        if sum(row == self.to_dict() for row in rows) != 1:
            raise NbaApiImplicitCompetitionError("competition cell is not exact and current")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "assignment_authority": self.assignment_authority,
            "cell_id": self.cell_id,
            "endpoint_support_status": self.endpoint_support_status,
            "league_id": self.league_id,
            "physical_endpoint_key": self.physical_endpoint_key,
            "provider_availability_status": self.provider_availability_status,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_probe_executed": self.provider_probe_executed,
            "request_terminal_state": self.request_terminal_state,
            "root_binding_sha256": self.root_binding_sha256,
            "root_kind": self.root_kind,
            "root_state": self.root_state,
            "source_family": self.source_family,
            "symbol": self.symbol,
        }
        if self.cell_kind == "alias":
            payload["repo_endpoint_name"] = self.repo_endpoint_name
        return payload


def _cell_from_row(
    row: Mapping[str, object], kind: Literal["physical", "alias"]
) -> ImplicitCompetitionCell:
    return ImplicitCompetitionCell(
        cell_kind=kind,
        assignment_authority=cast("str", row["assignment_authority"]),
        cell_id=cast("str", row["cell_id"]),
        endpoint_support_status=cast("str", row["endpoint_support_status"]),
        league_id=cast("str", row["league_id"]),
        physical_endpoint_key=cast("str", row["physical_endpoint_key"]),
        provider_availability_status=cast("str", row["provider_availability_status"]),
        provider_endpoint_id=cast("str", row["provider_endpoint_id"]),
        provider_probe_executed=cast("bool", row["provider_probe_executed"]),
        request_terminal_state=cast("str", row["request_terminal_state"]),
        root_binding_sha256=cast("str", row["root_binding_sha256"]),
        root_kind=cast("str", row["root_kind"]),
        root_state=cast("str", row["root_state"]),
        source_family=cast("str", row["source_family"]),
        symbol=cast("str", row["symbol"]),
        repo_endpoint_name=cast("str | None", row.get("repo_endpoint_name")),
    )


@dataclass(frozen=True, slots=True)
class ImplicitCompetitionResolution:
    """One non-availability resolution bound to an exact authority cell."""

    physical_endpoint_key: str
    provider_endpoint_id: str
    repo_endpoint_name: str | None
    league_id: str
    symbol: str
    cell_id: str
    root_binding_sha256: str
    root_kind: str
    root_mode: str
    root_value: RootValue | None
    resolution_state: str
    assignment_authority: str
    receipt_sha256: str | None
    static_chain_sha256: str | None
    endpoint_support_status: str = "unknown"
    provider_availability_status: str = "unknown"
    request_terminal_state: str = "not_asserted"
    receipt: InitVar[ReceiptBoundCompetitionRoot | None] = None

    def __post_init__(self, receipt: ReceiptBoundCompetitionRoot | None) -> None:
        if receipt is not None:
            if type(receipt) is not ReceiptBoundCompetitionRoot:
                raise NbaApiImplicitCompetitionError("root receipt must be an exact public DTO")
            receipt._revalidate()
        for field in (
            "physical_endpoint_key",
            "provider_endpoint_id",
            "symbol",
            "cell_id",
            "root_kind",
            "root_mode",
            "resolution_state",
            "assignment_authority",
        ):
            _require_identifier(getattr(self, field), field)
        _require_digest(self.root_binding_sha256, "root_binding_sha256")
        if self.receipt_sha256 is not None:
            _require_digest(self.receipt_sha256, "receipt_sha256")
        if self.static_chain_sha256 is not None:
            _require_digest(self.static_chain_sha256, "static_chain_sha256")
        if (
            type(self.repo_endpoint_name) not in {str, type(None)}
            or (type(self.repo_endpoint_name) is str and not self.repo_endpoint_name)
            or type(self.league_id) is not str
            or self.league_id not in _LEAGUE_IDS
            or self.symbol != _SYMBOLS[self.league_id]
            or type(self.root_value) not in {int, str, type(None)}
            or type(self.endpoint_support_status) is not str
            or self.endpoint_support_status != "unknown"
            or type(self.provider_availability_status) is not str
            or self.provider_availability_status != "unknown"
            or type(self.request_terminal_state) is not str
            or self.request_terminal_state != "not_asserted"
        ):
            raise NbaApiImplicitCompetitionError("implicit resolution claims forbidden state")
        kind: Literal["physical", "alias"] = (
            "physical" if self.repo_endpoint_name is None else "alias"
        )
        rows = _cell_rows(kind)
        cells = [row for row in rows if row.get("cell_id") == self.cell_id]
        if len(cells) != 1:
            raise NbaApiImplicitCompetitionError("resolution cell is not exact")
        cell = cells[0]
        binding = _binding_row(self.root_binding_sha256)
        if (
            cell["physical_endpoint_key"] != self.physical_endpoint_key
            or cell["provider_endpoint_id"] != self.provider_endpoint_id
            or cell.get("repo_endpoint_name") != self.repo_endpoint_name
            or cell["league_id"] != self.league_id
            or cell["symbol"] != self.symbol
            or cell["root_binding_sha256"] != self.root_binding_sha256
            or cell["root_kind"] != self.root_kind
            or binding["root_mode"] != self.root_mode
            or cell["assignment_authority"] != self.assignment_authority
        ):
            raise NbaApiImplicitCompetitionError("resolution contradicts its cell or binding")
        self._validate_resolution_evidence(cell, binding, receipt)

    def _validate_resolution_evidence(
        self,
        cell: Mapping[str, object],
        binding: Mapping[str, object],
        receipt: ReceiptBoundCompetitionRoot | None,
    ) -> None:
        if self.root_kind == "static":
            evidence = cast("dict[str, object]", binding["root_evidence"])
            chain_sha256 = cast("str", evidence["static_chain_sha256"])
            _static_chain(chain_sha256)
            if self.static_chain_sha256 != chain_sha256 or self.receipt_sha256 is not None:
                raise NbaApiImplicitCompetitionError(
                    "Static resolution requires only its pinned chain"
                )
            expected_state = (
                "competition_resolved"
                if cell["root_state"] == "fixed_static_root"
                else "root_not_exposed"
            )
            if (
                receipt is not None
                or self.root_value is not None
                or self.resolution_state != expected_state
            ):
                raise NbaApiImplicitCompetitionError("Static resolution state is invalid")
            return
        if self.static_chain_sha256 is not None:
            raise NbaApiImplicitCompetitionError("dynamic resolution cannot use a Static chain")
        if receipt is None:
            if (
                self.resolution_state
                not in {"root_receipt_required", "root_unresolved_nonterminal"}
                or self.root_value is not None
                or self.receipt_sha256 is not None
            ):
                raise NbaApiImplicitCompetitionError("missing dynamic receipt is not nonterminal")
            return
        if (
            self.resolution_state != "competition_resolved"
            or self.root_value != receipt.root_value
            or self.receipt_sha256 != receipt.receipt_sha256
            or receipt.root_binding_sha256 != self.root_binding_sha256
            or receipt.root_kind != self.root_kind
            or receipt.root_mode != self.root_mode
            or receipt.league_id != self.league_id
            or receipt.source_endpoint_id != self.provider_endpoint_id
        ):
            raise NbaApiImplicitCompetitionError("dynamic resolution is not receipt-bound")


@dataclass(frozen=True, slots=True)
class ImplicitCompetitionAuthority:
    """Complete offline authority for the exact implicit complement."""

    task_packet_sha256: str
    evidence_sha256: str
    evidence_payload_sha256: str
    evidence_authority_sha256: str
    evidence_canonicalization_sha256: str
    receipt_bound_root_policy_sha256: str
    source_review_sha256: str
    source_review_payload_sha256: str
    source_review_authority_sha256: str
    source_review_canonicalization_sha256: str
    competition_authority_sha256: str
    competition_occurrence_authority_sha256: str
    competition_applicability_authority_sha256: str
    endpoint_bindings: tuple[ImplicitCompetitionEndpointBinding, ...]
    alias_bindings: tuple[ImplicitCompetitionAliasBinding, ...]
    physical_competition_cells: tuple[ImplicitCompetitionCell, ...]
    alias_competition_cells: tuple[ImplicitCompetitionCell, ...]

    def __post_init__(self) -> None:
        for field in (
            "task_packet_sha256",
            "evidence_sha256",
            "evidence_payload_sha256",
            "evidence_authority_sha256",
            "evidence_canonicalization_sha256",
            "receipt_bound_root_policy_sha256",
            "source_review_sha256",
            "source_review_payload_sha256",
            "source_review_authority_sha256",
            "source_review_canonicalization_sha256",
            "competition_authority_sha256",
            "competition_occurrence_authority_sha256",
            "competition_applicability_authority_sha256",
        ):
            _require_digest(getattr(self, field), field)
        source = _root_source_payload()
        review = _source_review_payload()
        competition = pinned_competition_authority()
        occurrence = pinned_competition_occurrence_authority()
        applicability = pinned_competition_applicability_authority()
        expected_edges = (
            self.task_packet_sha256 == _EXPECTED_FILE_SHA256[_TASK_PACKET],
            self.evidence_sha256 == _EXPECTED_FILE_SHA256[_ROOT_EVIDENCE],
            self.evidence_payload_sha256 == source["payload_sha256"],
            self.evidence_authority_sha256 == source["authority_sha256"],
            self.evidence_canonicalization_sha256 == source["canonicalization_sha256"],
            self.receipt_bound_root_policy_sha256 == source["receipt_bound_root_policy_sha256"],
            self.source_review_sha256 == _EXPECTED_FILE_SHA256[_SOURCE_REVIEW],
            self.source_review_payload_sha256 == review["payload_sha256"],
            self.source_review_authority_sha256 == review["authority_sha256"],
            self.source_review_canonicalization_sha256 == review["canonicalization_sha256"],
            self.competition_authority_sha256 == competition.authority_sha256,
            self.competition_occurrence_authority_sha256 == occurrence.authority_sha256,
            self.competition_applicability_authority_sha256 == applicability.authority_sha256,
        )
        if not all(expected_edges):
            raise NbaApiImplicitCompetitionError("implicit authority source identity drifted")
        self._validate_exact_arrays(occurrence, applicability)

    def _validate_exact_arrays(
        self,
        occurrence: CompetitionOccurrenceAuthority,
        applicability: CompetitionApplicabilityAuthority,
    ) -> None:
        groups: tuple[tuple[object, type[object], int], ...] = (
            (self.endpoint_bindings, ImplicitCompetitionEndpointBinding, 36),
            (self.alias_bindings, ImplicitCompetitionAliasBinding, 36),
            (self.physical_competition_cells, ImplicitCompetitionCell, 180),
            (self.alias_competition_cells, ImplicitCompetitionCell, 180),
        )
        for values, child_type, count in groups:
            if (
                type(values) is not tuple
                or len(cast("tuple[object, ...]", values)) != count
                or any(type(item) is not child_type for item in cast("tuple[object, ...]", values))
            ):
                raise NbaApiImplicitCompetitionError("implicit authority tuple is incomplete")
        endpoint_rows = tuple(item.to_dict() for item in self.endpoint_bindings)
        alias_rows = tuple(item.to_dict() for item in self.alias_bindings)
        physical_rows = tuple(item.to_dict() for item in self.physical_competition_cells)
        alias_cell_rows = tuple(item.to_dict() for item in self.alias_competition_cells)
        if (
            endpoint_rows != _root_rows()
            or alias_rows != _alias_rows()
            or physical_rows != _cell_rows("physical")
            or alias_cell_rows != _cell_rows("alias")
        ):
            raise NbaApiImplicitCompetitionError("implicit authority differs from sealed arrays")
        explicit_endpoints = {item.provider_endpoint_id for item in occurrence.package_occurrences}
        implicit_provider_endpoints = {item.provider_endpoint_id for item in self.endpoint_bindings}
        implicit_physical_keys = {item.physical_endpoint_key for item in self.endpoint_bindings}
        explicit_aliases = {item.repo_endpoint_name for item in occurrence.repo_aliases}
        implicit_aliases = {item.repo_endpoint_name for item in self.alias_bindings}
        if (
            len(explicit_endpoints) != 111
            or len(implicit_physical_keys) != 36
            or explicit_endpoints & implicit_provider_endpoints
            or len(explicit_endpoints) + len(implicit_physical_keys) != 147
            or len(explicit_aliases) != 126
            or len(implicit_aliases) != 36
            or explicit_aliases & implicit_aliases
            or len(explicit_aliases | implicit_aliases) != 162
            or len(applicability.endpoint_cells) + len(physical_rows) != 735
            or len(applicability.parameter_axis_cells) + len(physical_rows) != 740
            or len(applicability.alias_role_cells) + len(alias_cell_rows) != 815
        ):
            raise NbaApiImplicitCompetitionError("implicit/explicit denominator partition drifted")
        if (
            Counter(item.root_requirement.root_kind for item in self.endpoint_bindings)
            != {"game": 30, "player": 1, "team": 1, "static": 4}
            or Counter(item.root_requirement.root_mode for item in self.endpoint_bindings)
            != {
                "request_parameter": 30,
                "response_game_collection": 1,
                "response_game_join": 1,
                "embedded_static_dataset": 4,
            }
            or Counter(item.root_state for item in self.physical_competition_cells)
            != {
                "receipt_bound_root_required": 160,
                "fixed_static_root": 4,
                "root_not_exposed": 16,
            }
        ):
            raise NbaApiImplicitCompetitionError("root kind, mode, or state partition drifted")

    @property
    def authority_sha256(self) -> str:
        return _digest(_authority_body(self))


def _source_authorities() -> dict[str, object]:
    packet = _task_packet_payload()
    source = _root_source_payload()
    return {
        "implicit_competition_roots": cast("dict[str, object]", packet["source_input_authority"])[
            "implicit_competition_roots"
        ],
        "independent_source_review": cast("dict[str, object]", packet["source_input_authority"])[
            "independent_source_review"
        ],
        "predecessor_receipts": packet["predecessor_receipts"],
        "predecessor_resources": source["source_authorities"],
        "task_packet": {"path": _TASK_PACKET, "sha256": _EXPECTED_FILE_SHA256[_TASK_PACKET]},
    }


def _authority_body(authority: ImplicitCompetitionAuthority) -> dict[str, object]:
    endpoints = [item.to_dict() for item in authority.endpoint_bindings]
    aliases = [item.to_dict() for item in authority.alias_bindings]
    physical = [item.to_dict() for item in authority.physical_competition_cells]
    alias_cells = [item.to_dict() for item in authority.alias_competition_cells]
    source = _root_source_payload()
    packet = _task_packet_payload()
    denominator_counts = packet.get("denominator_authority")
    if type(denominator_counts) is not dict:
        raise NbaApiImplicitCompetitionError("TaskPacket denominator authority is missing")
    false_green = packet.get("false_green_counters")
    if type(false_green) is not dict or any(
        type(value) is not int or value != 0 for value in false_green.values()
    ):
        raise NbaApiImplicitCompetitionError("false-green counters are not exact zero integers")
    policy = source.get("receipt_bound_root_policy")
    if type(policy) is not dict:
        raise NbaApiImplicitCompetitionError("receipt-bound root policy is missing")
    return {
        "alias_bindings": aliases,
        "alias_bindings_sha256": _digest(aliases),
        "alias_competition_cells": alias_cells,
        "alias_competition_cells_sha256": _digest(alias_cells),
        "denominator_counts": denominator_counts,
        "endpoint_bindings": endpoints,
        "endpoint_bindings_sha256": _digest(endpoints),
        "false_green_counters": false_green,
        "independent_proof": {"required": True, "verifier_id": _VERIFIER_ID},
        "kind": "nbadb_nba_api_implicit_competition_authority",
        "physical_competition_cells": physical,
        "physical_competition_cells_sha256": _digest(physical),
        "provider_availability_values": ["unknown"],
        "receipt_bound_root_policy": policy,
        "receipt_bound_root_policy_sha256": authority.receipt_bound_root_policy_sha256,
        "schema_version": IMPLICIT_COMPETITION_SCHEMA_VERSION,
        "source_authorities": _source_authorities(),
        "task_id": "A1.2d",
    }


@lru_cache(maxsize=1)
def build_implicit_competition_authority() -> ImplicitCompetitionAuthority:
    """Compile the complete implicit complement from reviewed offline authorities."""

    source = _root_source_payload()
    review = _source_review_payload()
    competition = pinned_competition_authority()
    occurrence = pinned_competition_occurrence_authority()
    applicability = pinned_competition_applicability_authority()
    return ImplicitCompetitionAuthority(
        task_packet_sha256=_EXPECTED_FILE_SHA256[_TASK_PACKET],
        evidence_sha256=_EXPECTED_FILE_SHA256[_ROOT_EVIDENCE],
        evidence_payload_sha256=cast("str", source["payload_sha256"]),
        evidence_authority_sha256=cast("str", source["authority_sha256"]),
        evidence_canonicalization_sha256=cast("str", source["canonicalization_sha256"]),
        receipt_bound_root_policy_sha256=cast("str", source["receipt_bound_root_policy_sha256"]),
        source_review_sha256=_EXPECTED_FILE_SHA256[_SOURCE_REVIEW],
        source_review_payload_sha256=cast("str", review["payload_sha256"]),
        source_review_authority_sha256=cast("str", review["authority_sha256"]),
        source_review_canonicalization_sha256=cast("str", review["canonicalization_sha256"]),
        competition_authority_sha256=competition.authority_sha256,
        competition_occurrence_authority_sha256=occurrence.authority_sha256,
        competition_applicability_authority_sha256=applicability.authority_sha256,
        endpoint_bindings=tuple(_endpoint_binding_from_row(row) for row in _root_rows()),
        alias_bindings=tuple(
            ImplicitCompetitionAliasBinding(
                provider_endpoint_id=cast("str", row["provider_endpoint_id"]),
                repo_endpoint_name=cast("str", row["repo_endpoint_name"]),
                source_family=cast("str", row["source_family"]),
                source_path=cast("str", row["source_path"]),
            )
            for row in _alias_rows()
        ),
        physical_competition_cells=tuple(
            _cell_from_row(row, "physical") for row in _cell_rows("physical")
        ),
        alias_competition_cells=tuple(_cell_from_row(row, "alias") for row in _cell_rows("alias")),
    )


def build_pinned_implicit_competition_payload() -> dict[str, object]:
    """Build the exact checked A1.2d authority payload."""

    authority = build_implicit_competition_authority()
    payload = _authority_body(authority)
    payload["authority_sha256"] = _digest(payload)
    payload["payload_sha256"] = _digest(payload)
    return payload


def write_pinned_implicit_competition(path: Path, *, check: bool = False) -> bool:
    """Write or check the sorted pretty checked authority resource."""

    encoded = _pretty_bytes(build_pinned_implicit_competition_payload())
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise NbaApiImplicitCompetitionError(
            "pinned implicit competition authority has generated drift"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False


def load_pinned_implicit_competition_payload(
    path: Path | None = None,
) -> dict[str, object]:
    """Load a strict checked resource and reproduce every current source edge."""

    try:
        raw = (
            resources.files("nbadb.contracts").joinpath(IMPLICIT_COMPETITION_RESOURCE).read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiImplicitCompetitionError(
            "implicit competition checked resource cannot be read"
        ) from exc
    payload = _strict_json(raw, label="implicit competition checked resource", pretty=True)
    body = dict(payload)
    supplied_payload = body.pop("payload_sha256", None)
    if _require_digest(supplied_payload, "payload_sha256") != _digest(body):
        raise NbaApiImplicitCompetitionError("checked resource payload digest is invalid")
    authority_body = dict(body)
    supplied_authority = authority_body.pop("authority_sha256", None)
    if _require_digest(supplied_authority, "authority_sha256") != _digest(authority_body):
        raise NbaApiImplicitCompetitionError("checked resource authority digest is invalid")
    if payload != build_pinned_implicit_competition_payload():
        raise NbaApiImplicitCompetitionError(
            "checked resource differs from current sealed authorities"
        )
    return payload


@lru_cache(maxsize=1)
def pinned_implicit_competition_authority() -> ImplicitCompetitionAuthority:
    """Return the authority only after checked-resource and independent verification."""

    payload = load_pinned_implicit_competition_payload()
    authority = build_implicit_competition_authority()
    from nbadb.core.nba_api_implicit_competition_verifier import (
        verify_pinned_implicit_competition_authority,
    )

    proof = verify_pinned_implicit_competition_authority()
    if (
        proof.candidate_authority_sha256 != authority.authority_sha256
        or proof.candidate_payload_sha256 != payload.get("payload_sha256")
        or proof.endpoint_bindings_sha256 != payload.get("endpoint_bindings_sha256")
        or proof.alias_bindings_sha256 != payload.get("alias_bindings_sha256")
        or proof.physical_competition_cells_sha256
        != payload.get("physical_competition_cells_sha256")
        or proof.alias_competition_cells_sha256 != payload.get("alias_competition_cells_sha256")
    ):
        raise NbaApiImplicitCompetitionError(
            "primary and independent implicit competition authorities differ"
        )
    return authority


def resolve_implicit_competition(
    physical_endpoint_key: str,
    league_id: str,
    *,
    repo_endpoint_name: str | None = None,
    receipt: ReceiptBoundCompetitionRoot | None = None,
) -> ImplicitCompetitionResolution:
    """Resolve one exact cell without making availability or terminal claims."""

    if type(physical_endpoint_key) is not str or not physical_endpoint_key:
        raise NbaApiImplicitCompetitionError("physical endpoint key is invalid")
    if type(league_id) is not str or league_id not in _LEAGUE_IDS:
        raise NbaApiImplicitCompetitionError("league_id is not in the pinned finite authority")
    if repo_endpoint_name is not None and (
        type(repo_endpoint_name) is not str or not repo_endpoint_name
    ):
        raise NbaApiImplicitCompetitionError("repo endpoint alias is invalid")
    if receipt is not None and type(receipt) is not ReceiptBoundCompetitionRoot:
        raise NbaApiImplicitCompetitionError("root receipt must be an exact public DTO")
    if receipt is not None:
        receipt._revalidate()
    authority = build_implicit_competition_authority()
    cells = (
        authority.physical_competition_cells
        if repo_endpoint_name is None
        else authority.alias_competition_cells
    )
    matches = [
        cell
        for cell in cells
        if cell.physical_endpoint_key == physical_endpoint_key
        and cell.league_id == league_id
        and cell.repo_endpoint_name == repo_endpoint_name
    ]
    if len(matches) != 1:
        raise NbaApiImplicitCompetitionError("resolution requires one exact authority cell")
    cell = matches[0]
    binding = next(
        item
        for item in authority.endpoint_bindings
        if item.binding_sha256 == cell.root_binding_sha256
    )
    requirement = binding.root_requirement
    if requirement.root_kind == "static":
        if receipt is not None:
            raise NbaApiImplicitCompetitionError("Static roots reject receipt resolution")
        state = (
            "competition_resolved" if cell.root_state == "fixed_static_root" else "root_not_exposed"
        )
        return ImplicitCompetitionResolution(
            physical_endpoint_key=cell.physical_endpoint_key,
            provider_endpoint_id=cell.provider_endpoint_id,
            repo_endpoint_name=repo_endpoint_name,
            league_id=cell.league_id,
            symbol=cell.symbol,
            cell_id=cell.cell_id,
            root_binding_sha256=cell.root_binding_sha256,
            root_kind=cell.root_kind,
            root_mode=requirement.root_mode,
            root_value=None,
            resolution_state=state,
            assignment_authority=cell.assignment_authority,
            receipt_sha256=None,
            static_chain_sha256=requirement.static_chain_sha256,
        )
    if receipt is None:
        return ImplicitCompetitionResolution(
            physical_endpoint_key=cell.physical_endpoint_key,
            provider_endpoint_id=cell.provider_endpoint_id,
            repo_endpoint_name=repo_endpoint_name,
            league_id=cell.league_id,
            symbol=cell.symbol,
            cell_id=cell.cell_id,
            root_binding_sha256=cell.root_binding_sha256,
            root_kind=cell.root_kind,
            root_mode=requirement.root_mode,
            root_value=None,
            resolution_state="root_receipt_required",
            assignment_authority=cell.assignment_authority,
            receipt_sha256=None,
            static_chain_sha256=None,
        )
    if (
        receipt.root_binding_sha256 != cell.root_binding_sha256
        or receipt.league_id != league_id
        or receipt.source_endpoint_id != cell.provider_endpoint_id
        or receipt.root_kind != cell.root_kind
        or receipt.root_mode != requirement.root_mode
    ):
        return ImplicitCompetitionResolution(
            physical_endpoint_key=cell.physical_endpoint_key,
            provider_endpoint_id=cell.provider_endpoint_id,
            repo_endpoint_name=repo_endpoint_name,
            league_id=cell.league_id,
            symbol=cell.symbol,
            cell_id=cell.cell_id,
            root_binding_sha256=cell.root_binding_sha256,
            root_kind=cell.root_kind,
            root_mode=requirement.root_mode,
            root_value=None,
            resolution_state="root_receipt_required",
            assignment_authority=cell.assignment_authority,
            receipt_sha256=None,
            static_chain_sha256=None,
        )
    return ImplicitCompetitionResolution(
        physical_endpoint_key=cell.physical_endpoint_key,
        provider_endpoint_id=cell.provider_endpoint_id,
        repo_endpoint_name=repo_endpoint_name,
        league_id=cell.league_id,
        symbol=cell.symbol,
        cell_id=cell.cell_id,
        root_binding_sha256=cell.root_binding_sha256,
        root_kind=cell.root_kind,
        root_mode=requirement.root_mode,
        root_value=receipt.root_value,
        resolution_state="competition_resolved",
        assignment_authority=cell.assignment_authority,
        receipt_sha256=receipt.receipt_sha256,
        static_chain_sha256=None,
        receipt=receipt,
    )


__all__ = [
    "CompetitionRootRequirement",
    "ImplicitCompetitionAliasBinding",
    "ImplicitCompetitionAuthority",
    "ImplicitCompetitionCell",
    "ImplicitCompetitionEndpointBinding",
    "ImplicitCompetitionResolution",
    "NbaApiImplicitCompetitionError",
    "ReceiptBoundCompetitionRoot",
    "build_implicit_competition_authority",
    "build_pinned_implicit_competition_payload",
    "load_pinned_implicit_competition_payload",
    "pinned_implicit_competition_authority",
    "resolve_implicit_competition",
    "write_pinned_implicit_competition",
]
