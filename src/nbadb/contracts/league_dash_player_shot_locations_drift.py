"""Pinned red authority for LeagueDashPlayerShotLocations header drift.

The pinned ``nba_api`` 1.11.4 endpoint declaration and generated endpoint
documentation describe 26 columns, while the same release's rendered output
documentation shows 30.  This module records that contradiction without
promoting either representation to a current raw-response or public-model
contract.

The authority is intentionally terminal-red.  It cannot admit a stable model,
construct a Raw Authority V2 value, or manufacture a grouped 30-column header.
Resolving the blocker requires a separately captured raw response and a new,
immutable child authority.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from importlib import resources
from typing import ClassVar, Final, Literal, Self, cast

__all__ = [
    "DECLARED_HEADER_COLUMNS_26",
    "LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_BLOCKERS",
    "LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_DRIFT_KIND",
    "LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_DRIFT_SCHEMA_VERSION",
    "PINNED_NBA_API_COMMIT_SHA",
    "PINNED_NBA_API_VERSION",
    "RENDERED_HEADER_COLUMNS_30",
    "RENDERED_ONLY_COLUMNS_4",
    "DeclaredHeaderAtomV1",
    "LeagueDashPlayerShotLocationsContractDriftAuthorityV1",
    "LeagueDashPlayerShotLocationsDriftError",
    "MaterializerBehaviorProofV1",
    "PinnedEvidenceFileV1",
    "RenderedHeaderAtomV1",
    "build_pinned_league_dash_player_shot_locations_drift_authority",
    "compile_pinned_league_dash_player_shot_locations_drift_authority",
    "load_packaged_league_dash_player_shot_locations_drift_authority",
]

LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_DRIFT_SCHEMA_VERSION: Final = 1
LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_DRIFT_KIND: Final = (
    "nbadb_league_dash_player_shot_locations_contract_drift_authority"
)
PINNED_NBA_API_VERSION: Final = "1.11.4"
PINNED_NBA_API_COMMIT_SHA: Final = "e0295f8333c3496b5754dbffbdf4c1c1dee3c2f4"

_ENDPOINT_SOURCE_PATH = "src/nba_api/stats/endpoints/leaguedashplayershotlocations.py"
_ENDPOINT_DOCS_PATH = "docs/nba_api/stats/endpoints/leaguedashplayershotlocations.md"
_RENDERED_OUTPUT_PATH = (
    "docs/nba_api/stats/endpoints_output/leaguedashplayershotlocations_output.md"
)
_MATERIALIZER_SOURCE_PATH = "src/nba_api/stats/endpoints/_base.py"
_PACKAGED_AUTHORITY_RESOURCE = "data/league-dash-player-shot-locations-drift-v1.json"
_PACKAGED_AUTHORITY_RESOURCE_BYTES = 19_013
_PACKAGED_AUTHORITY_RESOURCE_SHA256 = (
    "ee6aad0fae39f0a45548686ba81afa7e413ff574e3611052b435ba01c6d4c97c"
)

_ENDPOINT_SOURCE_SHA256 = "f24d3bae0d1bca5e639899080c560a3f1130cda8fb2fdd71d63587e514fc0d5f"
_ENDPOINT_DOCS_SHA256 = "0d3012ca76b56f0fa19c51db58f108cafcbeeee0a5eab4e89e56da90e6f1aa86"
_RENDERED_OUTPUT_SHA256 = "b92113d4bc84a6dea1e11e858acefc3c78a83bd9d2377b51cea94f0269b153f3"
_MATERIALIZER_SOURCE_SHA256 = "0bfb14cdef84f7e284136aa546c89a5d1b6ed60e813603d6d45cf287c8294c71"
_MATERIALIZER_FUNCTION_AST_SHA256 = (
    "fba1ee23a4588411b3f479fc5c6139eace93793ee89648069d691e829d5cbdb3"
)

_ENDPOINT_SOURCE_BYTES = 6_496
_ENDPOINT_DOCS_BYTES = 20_041
_RENDERED_OUTPUT_BYTES = 10_347
_MATERIALIZER_SOURCE_BYTES = 3_837
_EXPECTED_CANONICAL_AUTHORITY_BYTES = 19_012

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
_SAFE_PATH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@/+()-]{0,511}\Z", flags=re.ASCII)
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 200_000

_EVIDENCE_FILE_DOMAIN = b"nbadb:ldpsl:evidence-file:v1"
_DECLARED_INVENTORY_DOMAIN = b"nbadb:ldpsl:declared-header-inventory:v1"
_RENDERED_INVENTORY_DOMAIN = b"nbadb:ldpsl:rendered-header-inventory:v1"
_RENDERED_ONLY_DIFFERENCE_DOMAIN = b"nbadb:ldpsl:rendered-only-difference:v1"
_DECLARED_ONLY_DIFFERENCE_DOMAIN = b"nbadb:ldpsl:declared-only-difference:v1"
_MATERIALIZER_PROOF_DOMAIN = b"nbadb:ldpsl:materializer-proof:v1"
_AUTHORITY_DOMAIN = b"nbadb:ldpsl:contract-drift-authority:v1"
_COMMON_MAPPING_DOMAIN = b"nbadb:ldpsl:common-header-mapping:v1"
_EVIDENCE_ROOT_DOMAIN = b"nbadb:ldpsl:evidence-root:v1"


class LeagueDashPlayerShotLocationsDriftError(ValueError):
    """Pinned shot-location drift evidence or authority is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (MemoryError, RecursionError, TypeError, ValueError) as exc:
        raise LeagueDashPlayerShotLocationsDriftError(
            "value is not bounded canonical JSON"
        ) from exc


def _domain_sha256(domain: bytes, value: object) -> str:
    raw = _canonical_bytes(value)
    return hashlib.sha256(domain + b"\x00" + struct.pack(">Q", len(raw)) + raw).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise LeagueDashPlayerShotLocationsDriftError(
            f"{field_name} must be an exact lowercase SHA-256"
        )
    return value


def _require_git_sha(value: object, *, field_name: str) -> str:
    if type(value) is not str or _GIT_SHA_RE.fullmatch(value) is None:
        raise LeagueDashPlayerShotLocationsDriftError(
            f"{field_name} must be an exact lowercase git SHA"
        )
    return value


def _require_int(value: object, *, field_name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise LeagueDashPlayerShotLocationsDriftError(
            f"{field_name} must be an exact integer in [{minimum}, {maximum}]"
        )
    return value


def _require_exact_keys(
    payload: dict[str, object], *, expected: frozenset[str], label: str
) -> None:
    if any(type(key) is not str for key in payload):
        raise LeagueDashPlayerShotLocationsDriftError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual != expected:
        raise LeagueDashPlayerShotLocationsDriftError(
            f"{label} fields differ: missing={sorted(expected - actual)}; "
            f"unexpected={sorted(actual - expected)}"
        )


def _validate_json_tree(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise LeagueDashPlayerShotLocationsDriftError(
                "authority exceeds its JSON structure budget"
            )
        if type(node) is dict:
            stack.extend((item, depth + 1) for item in cast("dict[str, object]", node).values())
        elif type(node) is list:
            stack.extend((item, depth + 1) for item in cast("list[object]", node))
        elif node is not None and type(node) not in {str, int, float, bool}:
            raise LeagueDashPlayerShotLocationsDriftError("authority contains a non-JSON value")


def _decode_canonical_object(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or len(raw) != _EXPECTED_CANONICAL_AUTHORITY_BYTES:
        raise LeagueDashPlayerShotLocationsDriftError(
            "authority bytes differ from the exact pinned canonical size"
        )

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LeagueDashPlayerShotLocationsDriftError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise LeagueDashPlayerShotLocationsDriftError(
            f"non-finite JSON constant is forbidden: {value}"
        )

    try:
        decoded = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except LeagueDashPlayerShotLocationsDriftError:
        raise
    except (
        MemoryError,
        RecursionError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise LeagueDashPlayerShotLocationsDriftError("authority bytes are invalid JSON") from exc
    if type(decoded) is not dict:
        raise LeagueDashPlayerShotLocationsDriftError("authority root must be an object")
    payload = cast("dict[str, object]", decoded)
    _validate_json_tree(payload)
    if _canonical_bytes(payload) != raw:
        raise LeagueDashPlayerShotLocationsDriftError("authority bytes are not canonical")
    return payload


def _safe_path(value: object, *, field_name: str) -> str:
    if (
        type(value) is not str
        or _SAFE_PATH_RE.fullmatch(value) is None
        or value.startswith("/")
        or "//" in value
        or "/../" in f"/{value}/"
        or "/./" in f"/{value}/"
        or "\\" in value
    ):
        raise LeagueDashPlayerShotLocationsDriftError(
            f"{field_name} must be a safe canonical relative path"
        )
    return value


def _bronze_identifier(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", value.lower(), flags=re.ASCII).strip("_")


@dataclass(frozen=True, slots=True, order=True)
class DeclaredHeaderAtomV1:
    """One exact atom from the pinned structured endpoint declaration."""

    ordinal: int
    source_form: Literal["identity", "group_leaf"]
    label_path: tuple[str, ...]
    flattened_name: str

    def __post_init__(self) -> None:
        _require_int(self.ordinal, field_name="declared ordinal", minimum=0, maximum=25)
        if self.source_form not in {"identity", "group_leaf"}:
            raise LeagueDashPlayerShotLocationsDriftError("declared source_form is invalid")
        if (
            type(self.label_path) is not tuple
            or len(self.label_path) != (1 if self.source_form == "identity" else 2)
            or any(type(item) is not str or not item for item in self.label_path)
        ):
            raise LeagueDashPlayerShotLocationsDriftError(
                "declared label_path is empty, foreign, or malformed"
            )
        if type(self.flattened_name) is not str or not self.flattened_name:
            raise LeagueDashPlayerShotLocationsDriftError("declared flattened_name is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "flattened_name": self.flattened_name,
            "label_path": list(self.label_path),
            "ordinal": self.ordinal,
            "source_form": self.source_form,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise LeagueDashPlayerShotLocationsDriftError("declared atom must be an object")
        payload = cast("dict[str, object]", value)
        _require_exact_keys(
            payload,
            expected=frozenset({"ordinal", "source_form", "label_path", "flattened_name"}),
            label="declared atom",
        )
        if type(payload["label_path"]) is not list:
            raise LeagueDashPlayerShotLocationsDriftError("declared label_path must be an array")
        return cls(
            ordinal=cast("int", payload["ordinal"]),
            source_form=cast('Literal["identity", "group_leaf"]', payload["source_form"]),
            label_path=tuple(cast("list[str]", payload["label_path"])),
            flattened_name=cast("str", payload["flattened_name"]),
        )


@dataclass(frozen=True, slots=True, order=True)
class RenderedHeaderAtomV1:
    """One exact header atom parsed from rendered output documentation."""

    ordinal: int
    label_path: tuple[str, str]
    flattened_name: str
    evidence_kind: Literal["rendered_documentation_output"] = "rendered_documentation_output"
    is_raw_response_header: Literal[False] = False

    def __post_init__(self) -> None:
        _require_int(self.ordinal, field_name="rendered ordinal", minimum=0, maximum=29)
        if (
            type(self.label_path) is not tuple
            or len(self.label_path) != 2
            or any(type(item) is not str for item in self.label_path)
            or not self.label_path[1]
        ):
            raise LeagueDashPlayerShotLocationsDriftError(
                "rendered label_path is empty, foreign, or malformed"
            )
        if type(self.flattened_name) is not str or not self.flattened_name:
            raise LeagueDashPlayerShotLocationsDriftError("rendered flattened_name is invalid")
        if self.evidence_kind != "rendered_documentation_output":
            raise LeagueDashPlayerShotLocationsDriftError("rendered evidence kind is invalid")
        if type(self.is_raw_response_header) is not bool or self.is_raw_response_header:
            raise LeagueDashPlayerShotLocationsDriftError(
                "rendered documentation cannot be raw response-header evidence"
            )

    @property
    def logical_label_path(self) -> tuple[str, ...]:
        return (self.label_path[1],) if not self.label_path[0] else self.label_path

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_kind": self.evidence_kind,
            "flattened_name": self.flattened_name,
            "is_raw_response_header": self.is_raw_response_header,
            "label_path": list(self.label_path),
            "ordinal": self.ordinal,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise LeagueDashPlayerShotLocationsDriftError("rendered atom must be an object")
        payload = cast("dict[str, object]", value)
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "ordinal",
                    "label_path",
                    "flattened_name",
                    "evidence_kind",
                    "is_raw_response_header",
                }
            ),
            label="rendered atom",
        )
        if type(payload["label_path"]) is not list:
            raise LeagueDashPlayerShotLocationsDriftError("rendered label_path must be an array")
        label_path = tuple(cast("list[str]", payload["label_path"]))
        return cls(
            ordinal=cast("int", payload["ordinal"]),
            label_path=cast("tuple[str, str]", label_path),
            flattened_name=cast("str", payload["flattened_name"]),
            evidence_kind=cast(
                'Literal["rendered_documentation_output"]', payload["evidence_kind"]
            ),
            is_raw_response_header=cast("Literal[False]", payload["is_raw_response_header"]),
        )


def _declared_atoms() -> tuple[DeclaredHeaderAtomV1, ...]:
    identities = ("PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "AGE")
    groups = (
        "Restricted Area",
        "In The Paint (Non-RA)",
        "Mid-Range",
        "Left Corner 3",
        "Right Corner 3",
        "Above the Break 3",
        "Backcourt",
    )
    atoms: list[DeclaredHeaderAtomV1] = []
    for label in identities:
        atoms.append(
            DeclaredHeaderAtomV1(
                ordinal=len(atoms),
                source_form="identity",
                label_path=(label,),
                flattened_name=label,
            )
        )
    for group in groups:
        for metric in ("FGM", "FGA", "FG_PCT"):
            atoms.append(
                DeclaredHeaderAtomV1(
                    ordinal=len(atoms),
                    source_form="group_leaf",
                    label_path=(group, metric),
                    flattened_name=f"{_bronze_identifier(group)}_{_bronze_identifier(metric)}",
                )
            )
    return tuple(atoms)


def _rendered_atoms() -> tuple[RenderedHeaderAtomV1, ...]:
    pairs: list[tuple[str, str]] = [
        ("", "PLAYER_ID"),
        ("", "PLAYER_NAME"),
        ("", "TEAM_ID"),
        ("", "TEAM_ABBREVIATION"),
        ("", "AGE"),
        ("", "NICKNAME"),
    ]
    for group in (
        "Restricted Area",
        "In The Paint (Non-RA)",
        "Mid-Range",
        "Left Corner 3",
        "Right Corner 3",
        "Above the Break 3",
        "Backcourt",
        "Corner 3",
    ):
        pairs.extend((group, metric) for metric in ("FGM", "FGA", "FG_PCT"))
    return tuple(
        RenderedHeaderAtomV1(
            ordinal=ordinal,
            label_path=pair,
            flattened_name=(
                pair[1]
                if not pair[0]
                else f"{_bronze_identifier(pair[0])}_{_bronze_identifier(pair[1])}"
            ),
        )
        for ordinal, pair in enumerate(pairs)
    )


_DECLARED_ATOMS = _declared_atoms()
_RENDERED_ATOMS = _rendered_atoms()

DECLARED_HEADER_COLUMNS_26: Final = tuple(item.flattened_name for item in _DECLARED_ATOMS)
RENDERED_HEADER_COLUMNS_30: Final = tuple(item.flattened_name for item in _RENDERED_ATOMS)
RENDERED_ONLY_COLUMNS_4: Final = (
    "NICKNAME",
    "corner_3_fgm",
    "corner_3_fga",
    "corner_3_fg_pct",
)

LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_BLOCKERS: Final = tuple(
    sorted(
        {
            "raw_response_headers_unobserved",
            "current_runtime_signature_unproven",
            "rendered_group_structure_unproven",
            "field_presence_nullability_unproven",
            "corner_3_semantics_unproven",
            "row_identity_cardinality_unproven",
        }
    )
)


@dataclass(frozen=True, slots=True)
class PinnedEvidenceFileV1:
    """Content-addressed receipt for one exact upstream evidence file."""

    evidence_kind: Literal["endpoint_source", "endpoint_docs", "rendered_output_docs"]
    upstream_path: str
    byte_count: int
    content_sha256: str
    parser_id: str
    parser_version: int
    parsed_inventory_sha256: str
    nba_api_version: str = PINNED_NBA_API_VERSION
    nba_api_commit_sha: str = PINNED_NBA_API_COMMIT_SHA

    schema_version: ClassVar[int] = LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_DRIFT_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_ldpsl_pinned_evidence_file"

    def __post_init__(self) -> None:
        if self.evidence_kind not in {
            "endpoint_source",
            "endpoint_docs",
            "rendered_output_docs",
        }:
            raise LeagueDashPlayerShotLocationsDriftError("evidence kind is unsupported")
        _safe_path(self.upstream_path, field_name="upstream_path")
        _require_int(
            self.byte_count,
            field_name="evidence byte_count",
            minimum=1,
            maximum=64 * 1024 * 1024,
        )
        _require_sha256(self.content_sha256, field_name="content_sha256")
        _require_sha256(self.parsed_inventory_sha256, field_name="parsed_inventory_sha256")
        if type(self.parser_id) is not str or not self.parser_id or len(self.parser_id) > 128:
            raise LeagueDashPlayerShotLocationsDriftError("parser_id is invalid")
        _require_int(self.parser_version, field_name="parser_version", minimum=1, maximum=1)
        if self.nba_api_version != PINNED_NBA_API_VERSION:
            raise LeagueDashPlayerShotLocationsDriftError("evidence nba_api version is foreign")
        _require_git_sha(self.nba_api_commit_sha, field_name="nba_api_commit_sha")
        if self.nba_api_commit_sha != PINNED_NBA_API_COMMIT_SHA:
            raise LeagueDashPlayerShotLocationsDriftError("evidence commit is foreign")

    def _content_dict(self) -> dict[str, object]:
        return {
            "byte_count": self.byte_count,
            "content_sha256": self.content_sha256,
            "evidence_kind": self.evidence_kind,
            "kind": self.kind,
            "nba_api_commit_sha": self.nba_api_commit_sha,
            "nba_api_version": self.nba_api_version,
            "parsed_inventory_sha256": self.parsed_inventory_sha256,
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "schema_version": self.schema_version,
            "upstream_path": self.upstream_path,
        }

    @property
    def receipt_sha256(self) -> str:
        return _domain_sha256(_EVIDENCE_FILE_DOMAIN, self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise LeagueDashPlayerShotLocationsDriftError("evidence receipt must be an object")
        payload = cast("dict[str, object]", value)
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "nba_api_version",
                    "nba_api_commit_sha",
                    "evidence_kind",
                    "upstream_path",
                    "byte_count",
                    "content_sha256",
                    "parser_id",
                    "parser_version",
                    "parsed_inventory_sha256",
                    "receipt_sha256",
                }
            ),
            label="evidence receipt",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise LeagueDashPlayerShotLocationsDriftError("evidence receipt schema is invalid")
        result = cls(
            evidence_kind=cast(
                'Literal["endpoint_source", "endpoint_docs", "rendered_output_docs"]',
                payload["evidence_kind"],
            ),
            upstream_path=cast("str", payload["upstream_path"]),
            byte_count=cast("int", payload["byte_count"]),
            content_sha256=cast("str", payload["content_sha256"]),
            parser_id=cast("str", payload["parser_id"]),
            parser_version=cast("int", payload["parser_version"]),
            parsed_inventory_sha256=cast("str", payload["parsed_inventory_sha256"]),
            nba_api_version=cast("str", payload["nba_api_version"]),
            nba_api_commit_sha=cast("str", payload["nba_api_commit_sha"]),
        )
        if payload["receipt_sha256"] != result.receipt_sha256:
            raise LeagueDashPlayerShotLocationsDriftError("evidence receipt digest is invalid")
        return result


@dataclass(frozen=True, slots=True)
class MaterializerBehaviorProofV1:
    """AST-bound proof that DataSet materialization uses response headers/data."""

    source_path: str = _MATERIALIZER_SOURCE_PATH
    source_byte_count: int = _MATERIALIZER_SOURCE_BYTES
    source_sha256: str = _MATERIALIZER_SOURCE_SHA256
    symbol: str = "Endpoint.DataSet.get_data_frame"
    function_ast_sha256: str = _MATERIALIZER_FUNCTION_AST_SHA256
    ast_parser_id: str = "python_ast_dump"
    ast_parser_version: int = 1
    behavior: Literal["dataframe_columns_and_rows_directly_from_response_headers_and_data"] = (
        "dataframe_columns_and_rows_directly_from_response_headers_and_data"
    )
    nba_api_version: str = PINNED_NBA_API_VERSION
    nba_api_commit_sha: str = PINNED_NBA_API_COMMIT_SHA

    schema_version: ClassVar[int] = LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_DRIFT_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_ldpsl_materializer_behavior_proof"

    def __post_init__(self) -> None:
        if self.source_path != _MATERIALIZER_SOURCE_PATH:
            raise LeagueDashPlayerShotLocationsDriftError("materializer source path is foreign")
        _require_int(
            self.source_byte_count,
            field_name="materializer source_byte_count",
            minimum=1,
            maximum=64 * 1024 * 1024,
        )
        if self.source_byte_count != _MATERIALIZER_SOURCE_BYTES:
            raise LeagueDashPlayerShotLocationsDriftError("materializer byte count is foreign")
        if self.source_sha256 != _MATERIALIZER_SOURCE_SHA256:
            raise LeagueDashPlayerShotLocationsDriftError("materializer source digest is foreign")
        _require_sha256(self.function_ast_sha256, field_name="function_ast_sha256")
        if self.function_ast_sha256 != _MATERIALIZER_FUNCTION_AST_SHA256:
            raise LeagueDashPlayerShotLocationsDriftError("materializer function digest is foreign")
        if (
            self.symbol != "Endpoint.DataSet.get_data_frame"
            or self.ast_parser_id != "python_ast_dump"
            or type(self.ast_parser_version) is not int
            or self.ast_parser_version != 1
            or self.behavior != "dataframe_columns_and_rows_directly_from_response_headers_and_data"
        ):
            raise LeagueDashPlayerShotLocationsDriftError("materializer proof contract is foreign")
        if self.nba_api_version != PINNED_NBA_API_VERSION:
            raise LeagueDashPlayerShotLocationsDriftError("materializer version is foreign")
        _require_git_sha(self.nba_api_commit_sha, field_name="materializer commit")
        if self.nba_api_commit_sha != PINNED_NBA_API_COMMIT_SHA:
            raise LeagueDashPlayerShotLocationsDriftError("materializer commit is foreign")

    def _content_dict(self) -> dict[str, object]:
        return {
            "ast_parser_id": self.ast_parser_id,
            "ast_parser_version": self.ast_parser_version,
            "behavior": self.behavior,
            "function_ast_sha256": self.function_ast_sha256,
            "kind": self.kind,
            "nba_api_commit_sha": self.nba_api_commit_sha,
            "nba_api_version": self.nba_api_version,
            "schema_version": self.schema_version,
            "source_byte_count": self.source_byte_count,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "symbol": self.symbol,
        }

    @property
    def proof_sha256(self) -> str:
        return _domain_sha256(_MATERIALIZER_PROOF_DOMAIN, self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "proof_sha256": self.proof_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        if type(value) is not dict:
            raise LeagueDashPlayerShotLocationsDriftError("materializer proof must be an object")
        payload = cast("dict[str, object]", value)
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "nba_api_version",
                    "nba_api_commit_sha",
                    "source_path",
                    "source_byte_count",
                    "source_sha256",
                    "symbol",
                    "function_ast_sha256",
                    "ast_parser_id",
                    "ast_parser_version",
                    "behavior",
                    "proof_sha256",
                }
            ),
            label="materializer proof",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise LeagueDashPlayerShotLocationsDriftError("materializer proof schema is invalid")
        result = cls(
            source_path=cast("str", payload["source_path"]),
            source_byte_count=cast("int", payload["source_byte_count"]),
            source_sha256=cast("str", payload["source_sha256"]),
            symbol=cast("str", payload["symbol"]),
            function_ast_sha256=cast("str", payload["function_ast_sha256"]),
            ast_parser_id=cast("str", payload["ast_parser_id"]),
            ast_parser_version=cast("int", payload["ast_parser_version"]),
            behavior=cast(
                'Literal["dataframe_columns_and_rows_directly_from_response_headers_and_data"]',
                payload["behavior"],
            ),
            nba_api_version=cast("str", payload["nba_api_version"]),
            nba_api_commit_sha=cast("str", payload["nba_api_commit_sha"]),
        )
        if payload["proof_sha256"] != result.proof_sha256:
            raise LeagueDashPlayerShotLocationsDriftError("materializer proof digest is invalid")
        return result


def _inventory_root(
    domain: bytes,
    atoms: tuple[DeclaredHeaderAtomV1, ...] | tuple[RenderedHeaderAtomV1, ...],
) -> str:
    rows = [item.to_dict() for item in atoms]
    return _domain_sha256(domain, {"count": len(rows), "items": rows})


def _difference_root(atoms: tuple[RenderedHeaderAtomV1, ...]) -> str:
    return _domain_sha256(
        _RENDERED_ONLY_DIFFERENCE_DOMAIN,
        {"count": len(atoms), "items": [item.to_dict() for item in atoms]},
    )


def _declared_difference_root(atoms: tuple[DeclaredHeaderAtomV1, ...]) -> str:
    return _domain_sha256(
        _DECLARED_ONLY_DIFFERENCE_DOMAIN,
        {"count": len(atoms), "items": [item.to_dict() for item in atoms]},
    )


@dataclass(frozen=True, slots=True)
class LeagueDashPlayerShotLocationsContractDriftAuthorityV1:
    """Exact pinned contradiction; never a current raw or stable-model authority."""

    endpoint_source_receipt: PinnedEvidenceFileV1
    endpoint_docs_receipt: PinnedEvidenceFileV1
    rendered_output_receipt: PinnedEvidenceFileV1
    materializer_proof: MaterializerBehaviorProofV1
    declared_source_inventory: tuple[DeclaredHeaderAtomV1, ...]
    declared_docs_inventory: tuple[DeclaredHeaderAtomV1, ...]
    rendered_inventory: tuple[RenderedHeaderAtomV1, ...]
    endpoint: str = "LeagueDashPlayerShotLocations"
    dataset: str = "ShotLocations"
    nba_api_version: str = PINNED_NBA_API_VERSION
    nba_api_commit_sha: str = PINNED_NBA_API_COMMIT_SHA
    drift_kind: Literal["declared_vs_rendered_additive_header_drift"] = (
        "declared_vs_rendered_additive_header_drift"
    )
    state: Literal["awaiting_captured_raw_response"] = "awaiting_captured_raw_response"
    public_model_state: Literal["red_blocked"] = "red_blocked"
    fixed_superset_staging_state: Literal["red_blocked"] = "red_blocked"
    raw_capture_authority_sha256: None = None
    observed_header_signature_sha256: None = None

    schema_version: ClassVar[int] = LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_DRIFT_SCHEMA_VERSION
    kind: ClassVar[str] = LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_DRIFT_KIND

    def __post_init__(self) -> None:
        if self.endpoint != "LeagueDashPlayerShotLocations" or self.dataset != "ShotLocations":
            raise LeagueDashPlayerShotLocationsDriftError("endpoint or dataset is foreign")
        if self.nba_api_version != PINNED_NBA_API_VERSION:
            raise LeagueDashPlayerShotLocationsDriftError("authority nba_api version is foreign")
        _require_git_sha(self.nba_api_commit_sha, field_name="authority commit")
        if self.nba_api_commit_sha != PINNED_NBA_API_COMMIT_SHA:
            raise LeagueDashPlayerShotLocationsDriftError("authority commit is foreign")
        if self.drift_kind != "declared_vs_rendered_additive_header_drift":
            raise LeagueDashPlayerShotLocationsDriftError("drift kind is foreign")
        if (
            self.state != "awaiting_captured_raw_response"
            or self.public_model_state != "red_blocked"
            or self.fixed_superset_staging_state != "red_blocked"
            or self.raw_capture_authority_sha256 is not None
            or self.observed_header_signature_sha256 is not None
        ):
            raise LeagueDashPlayerShotLocationsDriftError(
                "pinned drift authority cannot carry capture or green state"
            )
        if self.declared_source_inventory != _DECLARED_ATOMS:
            raise LeagueDashPlayerShotLocationsDriftError("source declaration inventory is foreign")
        if self.declared_docs_inventory != _DECLARED_ATOMS:
            raise LeagueDashPlayerShotLocationsDriftError("docs declaration inventory is foreign")
        if self.rendered_inventory != _RENDERED_ATOMS:
            raise LeagueDashPlayerShotLocationsDriftError("rendered inventory is foreign")
        if self.declared_source_inventory != self.declared_docs_inventory:
            raise LeagueDashPlayerShotLocationsDriftError(
                "source/docs declaration inventories differ"
            )
        if len(self.declared_source_inventory) != 26 or len(self.rendered_inventory) != 30:
            raise LeagueDashPlayerShotLocationsDriftError("header inventory counts are not 26/30")
        if tuple(item.ordinal for item in self.declared_source_inventory) != tuple(range(26)):
            raise LeagueDashPlayerShotLocationsDriftError("declared ordinals are not contiguous")
        if tuple(item.ordinal for item in self.rendered_inventory) != tuple(range(30)):
            raise LeagueDashPlayerShotLocationsDriftError("rendered ordinals are not contiguous")
        if len(set(DECLARED_HEADER_COLUMNS_26)) != 26 or len(set(RENDERED_HEADER_COLUMNS_30)) != 30:
            raise LeagueDashPlayerShotLocationsDriftError("header inventory contains duplicates")
        if tuple(item.flattened_name for item in self.rendered_only_inventory) != (
            RENDERED_ONLY_COLUMNS_4
        ):
            raise LeagueDashPlayerShotLocationsDriftError(
                "rendered-only difference is not the exact pinned four"
            )
        if self.declared_only_inventory:
            raise LeagueDashPlayerShotLocationsDriftError("declared-only difference must be empty")
        if len(self.common_mapping) != 26:
            raise LeagueDashPlayerShotLocationsDriftError("common mapping does not cover all 26")
        if tuple(item[0] for item in self.common_mapping) != tuple(range(26)):
            raise LeagueDashPlayerShotLocationsDriftError(
                "common mapping declaration order differs"
            )
        if tuple(item[3] for item in self.common_mapping) != DECLARED_HEADER_COLUMNS_26:
            raise LeagueDashPlayerShotLocationsDriftError("common mapping label identities differ")
        expected_receipts = {
            "endpoint_source": (
                _ENDPOINT_SOURCE_PATH,
                _ENDPOINT_SOURCE_BYTES,
                _ENDPOINT_SOURCE_SHA256,
                self.declared_source_inventory_sha256,
                "python_ast_expected_data",
            ),
            "endpoint_docs": (
                _ENDPOINT_DOCS_PATH,
                _ENDPOINT_DOCS_BYTES,
                _ENDPOINT_DOCS_SHA256,
                self.declared_docs_inventory_sha256,
                "markdown_json_data_sets",
            ),
            "rendered_output_docs": (
                _RENDERED_OUTPUT_PATH,
                _RENDERED_OUTPUT_BYTES,
                _RENDERED_OUTPUT_SHA256,
                self.rendered_inventory_sha256,
                "markdown_multiindex_header",
            ),
        }
        if (
            self.endpoint_source_receipt.evidence_kind != "endpoint_source"
            or self.endpoint_docs_receipt.evidence_kind != "endpoint_docs"
            or self.rendered_output_receipt.evidence_kind != "rendered_output_docs"
        ):
            raise LeagueDashPlayerShotLocationsDriftError(
                "evidence receipts are assigned to foreign authority roles"
            )
        for receipt in (
            self.endpoint_source_receipt,
            self.endpoint_docs_receipt,
            self.rendered_output_receipt,
        ):
            expected = expected_receipts[receipt.evidence_kind]
            if (
                receipt.upstream_path,
                receipt.byte_count,
                receipt.content_sha256,
                receipt.parsed_inventory_sha256,
                receipt.parser_id,
            ) != expected:
                raise LeagueDashPlayerShotLocationsDriftError(
                    f"{receipt.evidence_kind} receipt differs from the exact pin"
                )
        if (
            len(
                {
                    self.endpoint_source_receipt.evidence_kind,
                    self.endpoint_docs_receipt.evidence_kind,
                    self.rendered_output_receipt.evidence_kind,
                }
            )
            != 3
        ):
            raise LeagueDashPlayerShotLocationsDriftError("evidence receipt kinds are duplicated")

    @property
    def declared_source_inventory_sha256(self) -> str:
        return _inventory_root(_DECLARED_INVENTORY_DOMAIN, self.declared_source_inventory)

    @property
    def declared_docs_inventory_sha256(self) -> str:
        return _inventory_root(_DECLARED_INVENTORY_DOMAIN, self.declared_docs_inventory)

    @property
    def rendered_inventory_sha256(self) -> str:
        return _inventory_root(_RENDERED_INVENTORY_DOMAIN, self.rendered_inventory)

    @property
    def common_mapping(self) -> tuple[tuple[int, int, tuple[str, ...], str], ...]:
        rendered_by_name = {item.flattened_name: item for item in self.rendered_inventory}
        return tuple(
            (
                declared.ordinal,
                rendered_by_name[declared.flattened_name].ordinal,
                declared.label_path,
                declared.flattened_name,
            )
            for declared in self.declared_source_inventory
        )

    @property
    def common_mapping_sha256(self) -> str:
        return _domain_sha256(
            _COMMON_MAPPING_DOMAIN,
            {
                "count": len(self.common_mapping),
                "items": [
                    {
                        "declared_ordinal": declared_ordinal,
                        "flattened_name": flattened_name,
                        "label_path": list(label_path),
                        "rendered_ordinal": rendered_ordinal,
                    }
                    for declared_ordinal, rendered_ordinal, label_path, flattened_name in (
                        self.common_mapping
                    )
                ],
            },
        )

    @property
    def rendered_only_inventory(self) -> tuple[RenderedHeaderAtomV1, ...]:
        declared_names = frozenset(DECLARED_HEADER_COLUMNS_26)
        return tuple(
            item for item in self.rendered_inventory if item.flattened_name not in declared_names
        )

    @property
    def declared_only_inventory(self) -> tuple[DeclaredHeaderAtomV1, ...]:
        rendered_names = frozenset(RENDERED_HEADER_COLUMNS_30)
        return tuple(
            item
            for item in self.declared_source_inventory
            if item.flattened_name not in rendered_names
        )

    @property
    def rendered_only_sha256(self) -> str:
        return _difference_root(self.rendered_only_inventory)

    @property
    def declared_only_sha256(self) -> str:
        return _declared_difference_root(self.declared_only_inventory)

    @property
    def evidence_root_sha256(self) -> str:
        return _domain_sha256(
            _EVIDENCE_ROOT_DOMAIN,
            {
                "evidence_receipt_sha256s": [
                    self.endpoint_source_receipt.receipt_sha256,
                    self.endpoint_docs_receipt.receipt_sha256,
                    self.rendered_output_receipt.receipt_sha256,
                ],
                "materializer_proof_sha256": self.materializer_proof.proof_sha256,
            },
        )

    def _content_dict(self) -> dict[str, object]:
        common_items = [
            {
                "declared_ordinal": declared_ordinal,
                "flattened_name": flattened_name,
                "label_path": list(label_path),
                "rendered_ordinal": rendered_ordinal,
            }
            for declared_ordinal, rendered_ordinal, label_path, flattened_name in (
                self.common_mapping
            )
        ]
        return {
            "blocker_codes": list(LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_BLOCKERS),
            "common_mapping": common_items,
            "common_mapping_count": len(common_items),
            "common_mapping_sha256": self.common_mapping_sha256,
            "dataset": self.dataset,
            "declared_docs_inventory": [item.to_dict() for item in self.declared_docs_inventory],
            "declared_docs_inventory_sha256": self.declared_docs_inventory_sha256,
            "declared_only_count": len(self.declared_only_inventory),
            "declared_only_inventory": [item.to_dict() for item in self.declared_only_inventory],
            "declared_only_sha256": self.declared_only_sha256,
            "declared_source_inventory": [
                item.to_dict() for item in self.declared_source_inventory
            ],
            "declared_source_inventory_sha256": self.declared_source_inventory_sha256,
            "drift_kind": self.drift_kind,
            "endpoint": self.endpoint,
            "endpoint_docs_receipt": self.endpoint_docs_receipt.to_dict(),
            "endpoint_source_receipt": self.endpoint_source_receipt.to_dict(),
            "evidence_root_sha256": self.evidence_root_sha256,
            "fixed_superset_staging_state": self.fixed_superset_staging_state,
            "kind": self.kind,
            "materializer_proof": self.materializer_proof.to_dict(),
            "nba_api_commit_sha": self.nba_api_commit_sha,
            "nba_api_version": self.nba_api_version,
            "observed_header_signature_sha256": self.observed_header_signature_sha256,
            "public_model_state": self.public_model_state,
            "raw_capture_authority_sha256": self.raw_capture_authority_sha256,
            "rendered_inventory": [item.to_dict() for item in self.rendered_inventory],
            "rendered_inventory_sha256": self.rendered_inventory_sha256,
            "rendered_only_count": len(self.rendered_only_inventory),
            "rendered_only_inventory": [item.to_dict() for item in self.rendered_only_inventory],
            "rendered_only_sha256": self.rendered_only_sha256,
            "rendered_output_receipt": self.rendered_output_receipt.to_dict(),
            "schema_version": self.schema_version,
            "state": self.state,
        }

    @property
    def authority_sha256(self) -> str:
        return _domain_sha256(_AUTHORITY_DOMAIN, self._content_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "authority_sha256": self.authority_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        payload = _decode_canonical_object(raw)
        expected_keys = frozenset(
            build_pinned_league_dash_player_shot_locations_drift_authority().to_dict()
        )
        _require_exact_keys(payload, expected=expected_keys, label="drift authority")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise LeagueDashPlayerShotLocationsDriftError("drift authority schema is invalid")
        for name in (
            "declared_source_inventory",
            "declared_docs_inventory",
            "rendered_inventory",
        ):
            if type(payload[name]) is not list:
                raise LeagueDashPlayerShotLocationsDriftError(f"{name} must be an array")
        result = cls(
            endpoint_source_receipt=PinnedEvidenceFileV1.from_dict(
                payload["endpoint_source_receipt"]
            ),
            endpoint_docs_receipt=PinnedEvidenceFileV1.from_dict(payload["endpoint_docs_receipt"]),
            rendered_output_receipt=PinnedEvidenceFileV1.from_dict(
                payload["rendered_output_receipt"]
            ),
            materializer_proof=MaterializerBehaviorProofV1.from_dict(payload["materializer_proof"]),
            declared_source_inventory=tuple(
                DeclaredHeaderAtomV1.from_dict(item)
                for item in cast("list[object]", payload["declared_source_inventory"])
            ),
            declared_docs_inventory=tuple(
                DeclaredHeaderAtomV1.from_dict(item)
                for item in cast("list[object]", payload["declared_docs_inventory"])
            ),
            rendered_inventory=tuple(
                RenderedHeaderAtomV1.from_dict(item)
                for item in cast("list[object]", payload["rendered_inventory"])
            ),
            endpoint=cast("str", payload["endpoint"]),
            dataset=cast("str", payload["dataset"]),
            nba_api_version=cast("str", payload["nba_api_version"]),
            nba_api_commit_sha=cast("str", payload["nba_api_commit_sha"]),
            drift_kind=cast(
                'Literal["declared_vs_rendered_additive_header_drift"]',
                payload["drift_kind"],
            ),
            state=cast('Literal["awaiting_captured_raw_response"]', payload["state"]),
            public_model_state=cast('Literal["red_blocked"]', payload["public_model_state"]),
            fixed_superset_staging_state=cast(
                'Literal["red_blocked"]', payload["fixed_superset_staging_state"]
            ),
            raw_capture_authority_sha256=cast("None", payload["raw_capture_authority_sha256"]),
            observed_header_signature_sha256=cast(
                "None", payload["observed_header_signature_sha256"]
            ),
        )
        if payload != result.to_dict():
            raise LeagueDashPlayerShotLocationsDriftError(
                "drift authority differs from its exact pinned reconstruction"
            )
        return result


def build_pinned_league_dash_player_shot_locations_drift_authority() -> (
    LeagueDashPlayerShotLocationsContractDriftAuthorityV1
):
    """Build the immutable D0 red authority from pinned parsed evidence."""
    declared_root = _inventory_root(_DECLARED_INVENTORY_DOMAIN, _DECLARED_ATOMS)
    rendered_root = _inventory_root(_RENDERED_INVENTORY_DOMAIN, _RENDERED_ATOMS)
    return LeagueDashPlayerShotLocationsContractDriftAuthorityV1(
        endpoint_source_receipt=PinnedEvidenceFileV1(
            evidence_kind="endpoint_source",
            upstream_path=_ENDPOINT_SOURCE_PATH,
            byte_count=_ENDPOINT_SOURCE_BYTES,
            content_sha256=_ENDPOINT_SOURCE_SHA256,
            parser_id="python_ast_expected_data",
            parser_version=1,
            parsed_inventory_sha256=declared_root,
        ),
        endpoint_docs_receipt=PinnedEvidenceFileV1(
            evidence_kind="endpoint_docs",
            upstream_path=_ENDPOINT_DOCS_PATH,
            byte_count=_ENDPOINT_DOCS_BYTES,
            content_sha256=_ENDPOINT_DOCS_SHA256,
            parser_id="markdown_json_data_sets",
            parser_version=1,
            parsed_inventory_sha256=declared_root,
        ),
        rendered_output_receipt=PinnedEvidenceFileV1(
            evidence_kind="rendered_output_docs",
            upstream_path=_RENDERED_OUTPUT_PATH,
            byte_count=_RENDERED_OUTPUT_BYTES,
            content_sha256=_RENDERED_OUTPUT_SHA256,
            parser_id="markdown_multiindex_header",
            parser_version=1,
            parsed_inventory_sha256=rendered_root,
        ),
        materializer_proof=MaterializerBehaviorProofV1(),
        declared_source_inventory=_DECLARED_ATOMS,
        declared_docs_inventory=_DECLARED_ATOMS,
        rendered_inventory=_RENDERED_ATOMS,
    )


def load_packaged_league_dash_player_shot_locations_drift_authority() -> (
    LeagueDashPlayerShotLocationsContractDriftAuthorityV1
):
    """Load and strict-replay the repository-packaged canonical D0 authority."""
    try:
        packaged_raw = (
            resources.files("nbadb.contracts").joinpath(_PACKAGED_AUTHORITY_RESOURCE).read_bytes()
        )
    except (FileNotFoundError, IsADirectoryError, OSError) as exc:
        raise LeagueDashPlayerShotLocationsDriftError(
            "packaged shot-location drift authority is unavailable"
        ) from exc
    return _decode_packaged_authority_resource(packaged_raw)


def _decode_packaged_authority_resource(
    packaged_raw: bytes,
) -> LeagueDashPlayerShotLocationsContractDriftAuthorityV1:
    """Validate the single-LF repository wrapper before strict canonical replay."""
    if (
        type(packaged_raw) is not bytes
        or len(packaged_raw) != _PACKAGED_AUTHORITY_RESOURCE_BYTES
        or not packaged_raw.endswith(b"\n")
        or packaged_raw.endswith(b"\n\n")
        or hashlib.sha256(packaged_raw).hexdigest() != _PACKAGED_AUTHORITY_RESOURCE_SHA256
    ):
        raise LeagueDashPlayerShotLocationsDriftError(
            "packaged shot-location drift authority differs from its exact wrapper pin"
        )
    return LeagueDashPlayerShotLocationsContractDriftAuthorityV1.from_canonical_bytes(
        packaged_raw[:-1]
    )


def _verify_pinned_bytes(
    raw: bytes, *, label: str, expected_size: int, expected_sha256: str
) -> None:
    if type(raw) is not bytes or len(raw) != expected_size:
        raise LeagueDashPlayerShotLocationsDriftError(f"{label} byte count differs from pin")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise LeagueDashPlayerShotLocationsDriftError(f"{label} digest differs from pin")


def _structured_header_to_atoms(value: object) -> tuple[DeclaredHeaderAtomV1, ...]:
    if type(value) is not list or len(value) != 2:
        raise LeagueDashPlayerShotLocationsDriftError(
            "structured declaration must contain exactly two header levels"
        )
    rows = cast("list[object]", value)
    if any(type(item) is not dict for item in rows):
        raise LeagueDashPlayerShotLocationsDriftError("structured header levels must be objects")
    group = cast("dict[str, object]", rows[0])
    columns = cast("dict[str, object]", rows[1])
    _require_exact_keys(
        group,
        expected=frozenset({"columnNames", "columnSpan", "columnsToSkip", "name"}),
        label="structured group header",
    )
    _require_exact_keys(
        columns,
        expected=frozenset({"columnNames", "columnSpan", "name"}),
        label="structured columns header",
    )
    if (
        group["name"] != "SHOT_CATEGORY"
        or type(group["columnSpan"]) is not int
        or group["columnSpan"] != 3
        or type(group["columnsToSkip"]) is not int
        or group["columnsToSkip"] != 5
        or columns["name"] != "columns"
        or type(columns["columnSpan"]) is not int
        or columns["columnSpan"] != 1
        or type(group["columnNames"]) is not list
        or type(columns["columnNames"]) is not list
    ):
        raise LeagueDashPlayerShotLocationsDriftError("structured header shape is foreign")
    group_names = cast("list[object]", group["columnNames"])
    column_names = cast("list[object]", columns["columnNames"])
    if any(type(item) is not str for item in (*group_names, *column_names)):
        raise LeagueDashPlayerShotLocationsDriftError("structured header labels must be strings")
    identities = cast("list[str]", column_names[:5])
    metrics = cast("list[str]", column_names[5:])
    atoms: list[DeclaredHeaderAtomV1] = [
        DeclaredHeaderAtomV1(
            ordinal=index,
            source_form="identity",
            label_path=(label,),
            flattened_name=label,
        )
        for index, label in enumerate(identities)
    ]
    cursor = 0
    for group_name in cast("list[str]", group_names):
        for _ in range(3):
            if cursor >= len(metrics):
                raise LeagueDashPlayerShotLocationsDriftError(
                    "structured metric header ends before its groups"
                )
            metric = metrics[cursor]
            cursor += 1
            atoms.append(
                DeclaredHeaderAtomV1(
                    ordinal=len(atoms),
                    source_form="group_leaf",
                    label_path=(group_name, metric),
                    flattened_name=(
                        f"{_bronze_identifier(group_name)}_{_bronze_identifier(metric)}"
                    ),
                )
            )
    if cursor != len(metrics):
        raise LeagueDashPlayerShotLocationsDriftError(
            "structured metric header has unbound trailing columns"
        )
    return tuple(atoms)


def _parse_endpoint_source(raw: bytes) -> tuple[DeclaredHeaderAtomV1, ...]:
    try:
        tree = ast.parse(raw)
    except (MemoryError, RecursionError, SyntaxError) as exc:
        raise LeagueDashPlayerShotLocationsDriftError("endpoint source AST is invalid") from exc
    candidates: list[object] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "LeagueDashPlayerShotLocations":
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "expected_data"
                ):
                    try:
                        candidates.append(ast.literal_eval(statement.value))
                    except (MemoryError, RecursionError, SyntaxError, ValueError) as exc:
                        raise LeagueDashPlayerShotLocationsDriftError(
                            "endpoint expected_data is not a literal"
                        ) from exc
    if len(candidates) != 1 or type(candidates[0]) is not dict:
        raise LeagueDashPlayerShotLocationsDriftError(
            "endpoint source must contain one exact expected_data declaration"
        )
    expected_data = cast("dict[object, object]", candidates[0])
    if set(expected_data) != {"ShotLocations"}:
        raise LeagueDashPlayerShotLocationsDriftError("endpoint expected_data dataset is foreign")
    return _structured_header_to_atoms(expected_data["ShotLocations"])


def _parse_endpoint_docs(raw: bytes) -> tuple[DeclaredHeaderAtomV1, ...]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LeagueDashPlayerShotLocationsDriftError("endpoint docs are not UTF-8") from exc
    matches = re.findall(r"## JSON\s*```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if len(matches) != 1:
        raise LeagueDashPlayerShotLocationsDriftError("endpoint docs JSON block is ambiguous")
    try:
        payload = json.loads(matches[0])
    except (MemoryError, RecursionError, json.JSONDecodeError) as exc:
        raise LeagueDashPlayerShotLocationsDriftError("endpoint docs JSON is invalid") from exc
    if type(payload) is not dict or payload.get("endpoint") != "LeagueDashPlayerShotLocations":
        raise LeagueDashPlayerShotLocationsDriftError("endpoint docs identity is foreign")
    data_sets = payload.get("data_sets")
    if type(data_sets) is not dict or set(data_sets) != {"ShotLocations"}:
        raise LeagueDashPlayerShotLocationsDriftError("endpoint docs dataset is foreign")
    return _structured_header_to_atoms(data_sets["ShotLocations"])


def _parse_rendered_output(raw: bytes) -> tuple[RenderedHeaderAtomV1, ...]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LeagueDashPlayerShotLocationsDriftError("rendered output is not UTF-8") from exc
    lines = text.splitlines()
    try:
        heading_index = lines.index("ShotLocations:")
    except ValueError as exc:
        raise LeagueDashPlayerShotLocationsDriftError("rendered output dataset is absent") from exc
    candidate_lines = [line for line in lines[heading_index + 1 :] if line.strip()]
    if not candidate_lines:
        raise LeagueDashPlayerShotLocationsDriftError("rendered output header is absent")
    header_line = candidate_lines[0]
    cells = [cell.strip() for cell in header_line.strip().strip("|").split("|")]
    pairs: list[tuple[str, str]] = []
    for cell in cells:
        try:
            value = ast.literal_eval(cell)
        except (MemoryError, RecursionError, SyntaxError, ValueError) as exc:
            raise LeagueDashPlayerShotLocationsDriftError(
                "rendered output header cell is not an exact tuple literal"
            ) from exc
        if (
            type(value) is not tuple
            or len(value) != 2
            or any(type(item) is not str for item in value)
        ):
            raise LeagueDashPlayerShotLocationsDriftError(
                "rendered output header cell is malformed"
            )
        pairs.append(cast("tuple[str, str]", value))
    atoms = tuple(
        RenderedHeaderAtomV1(
            ordinal=ordinal,
            label_path=pair,
            flattened_name=(
                pair[1]
                if not pair[0]
                else f"{_bronze_identifier(pair[0])}_{_bronze_identifier(pair[1])}"
            ),
        )
        for ordinal, pair in enumerate(pairs)
    )
    return atoms


def _prove_materializer(raw: bytes) -> MaterializerBehaviorProofV1:
    try:
        tree = ast.parse(raw)
    except (MemoryError, RecursionError, SyntaxError) as exc:
        raise LeagueDashPlayerShotLocationsDriftError("materializer source AST is invalid") from exc
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "get_data_frame"
    ]
    if len(functions) != 1:
        raise LeagueDashPlayerShotLocationsDriftError(
            "materializer source does not contain one get_data_frame"
        )
    function = functions[0]
    ast_digest = hashlib.sha256(
        ast.dump(function, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()
    if ast_digest != _MATERIALIZER_FUNCTION_AST_SHA256:
        raise LeagueDashPlayerShotLocationsDriftError("materializer function AST differs")
    string_constants = {
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and type(node.value) is str
    }
    if "headers" not in string_constants or "data" not in string_constants:
        raise LeagueDashPlayerShotLocationsDriftError(
            "materializer does not bind response headers and data"
        )
    if {"NICKNAME", "Corner 3"} & string_constants:
        raise LeagueDashPlayerShotLocationsDriftError(
            "materializer contains endpoint-specific inserted fields"
        )
    return MaterializerBehaviorProofV1()


def compile_pinned_league_dash_player_shot_locations_drift_authority(
    *,
    endpoint_source_bytes: bytes,
    endpoint_docs_bytes: bytes,
    rendered_output_bytes: bytes,
    materializer_source_bytes: bytes,
) -> LeagueDashPlayerShotLocationsContractDriftAuthorityV1:
    """Compile D0 only after exact upstream bytes and parsed evidence agree."""
    for raw, label, size, digest in (
        (
            endpoint_source_bytes,
            "endpoint source",
            _ENDPOINT_SOURCE_BYTES,
            _ENDPOINT_SOURCE_SHA256,
        ),
        (endpoint_docs_bytes, "endpoint docs", _ENDPOINT_DOCS_BYTES, _ENDPOINT_DOCS_SHA256),
        (
            rendered_output_bytes,
            "rendered output",
            _RENDERED_OUTPUT_BYTES,
            _RENDERED_OUTPUT_SHA256,
        ),
        (
            materializer_source_bytes,
            "materializer source",
            _MATERIALIZER_SOURCE_BYTES,
            _MATERIALIZER_SOURCE_SHA256,
        ),
    ):
        _verify_pinned_bytes(raw, label=label, expected_size=size, expected_sha256=digest)
    source_inventory = _parse_endpoint_source(endpoint_source_bytes)
    docs_inventory = _parse_endpoint_docs(endpoint_docs_bytes)
    rendered_inventory = _parse_rendered_output(rendered_output_bytes)
    materializer_proof = _prove_materializer(materializer_source_bytes)
    compiled = LeagueDashPlayerShotLocationsContractDriftAuthorityV1(
        endpoint_source_receipt=PinnedEvidenceFileV1(
            evidence_kind="endpoint_source",
            upstream_path=_ENDPOINT_SOURCE_PATH,
            byte_count=len(endpoint_source_bytes),
            content_sha256=hashlib.sha256(endpoint_source_bytes).hexdigest(),
            parser_id="python_ast_expected_data",
            parser_version=1,
            parsed_inventory_sha256=_inventory_root(_DECLARED_INVENTORY_DOMAIN, source_inventory),
        ),
        endpoint_docs_receipt=PinnedEvidenceFileV1(
            evidence_kind="endpoint_docs",
            upstream_path=_ENDPOINT_DOCS_PATH,
            byte_count=len(endpoint_docs_bytes),
            content_sha256=hashlib.sha256(endpoint_docs_bytes).hexdigest(),
            parser_id="markdown_json_data_sets",
            parser_version=1,
            parsed_inventory_sha256=_inventory_root(_DECLARED_INVENTORY_DOMAIN, docs_inventory),
        ),
        rendered_output_receipt=PinnedEvidenceFileV1(
            evidence_kind="rendered_output_docs",
            upstream_path=_RENDERED_OUTPUT_PATH,
            byte_count=len(rendered_output_bytes),
            content_sha256=hashlib.sha256(rendered_output_bytes).hexdigest(),
            parser_id="markdown_multiindex_header",
            parser_version=1,
            parsed_inventory_sha256=_inventory_root(_RENDERED_INVENTORY_DOMAIN, rendered_inventory),
        ),
        materializer_proof=materializer_proof,
        declared_source_inventory=source_inventory,
        declared_docs_inventory=docs_inventory,
        rendered_inventory=rendered_inventory,
    )
    pinned = build_pinned_league_dash_player_shot_locations_drift_authority()
    if compiled.to_dict() != pinned.to_dict():
        raise LeagueDashPlayerShotLocationsDriftError(
            "compiled drift authority differs from its exact pinned reconstruction"
        )
    return compiled
