"""Independent no-network verifier for the pinned competition authority."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from nbadb.core.nba_api_surface_inventory import (
    NbaApiSurfaceInventoryError,
    build_distribution_record_authority,
)

if TYPE_CHECKING:
    from importlib.metadata import Distribution

_DISTRIBUTION: Final = "nba-api"
_VERSION: Final = "1.11.4"
_RESOURCE: Final = "nba_api_competition_v1_11_4.json"
_SOURCE_PATH: Final = "nba_api/stats/library/parameters.py"
_CLASS_NAME: Final = "LeagueID"
_VERIFIER_ID: Final = "nbadb_independent_competition_source_ast_v1"
_SYMBOL_RE = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)
_LEAGUE_ID_RE = re.compile(r"[0-9]{2}", flags=re.ASCII)
_SHA256_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class NbaApiCompetitionVerificationError(ValueError):
    """Independent competition verification failed closed."""


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
        raise NbaApiCompetitionVerificationError("competition proof is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiCompetitionVerificationError(f"{field} must be a canonical SHA-256")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiCompetitionVerificationError(
                f"competition resource contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiCompetitionVerificationError(
        f"competition resource contains non-finite JSON constant: {value}"
    )


def _source_binding(
    distribution: Distribution,
) -> tuple[bytes, str, int, str]:
    try:
        record = build_distribution_record_authority(distribution)
    except NbaApiSurfaceInventoryError as exc:
        raise NbaApiCompetitionVerificationError(
            "installed nba_api RECORD authority is invalid"
        ) from exc
    entries = tuple(entry for entry in record.entries if entry.path == _SOURCE_PATH)
    if len(entries) != 1:
        raise NbaApiCompetitionVerificationError("competition source RECORD entry is ambiguous")
    entry = entries[0]
    try:
        path = Path(str(distribution.locate_file(_SOURCE_PATH))).resolve(strict=True)
        raw = path.read_bytes()
    except OSError as exc:
        raise NbaApiCompetitionVerificationError("competition source cannot be read") from exc
    if hashlib.sha256(raw).hexdigest() != entry.sha256 or len(raw) != entry.size:
        raise NbaApiCompetitionVerificationError(
            "competition source differs from its RECORD binding"
        )
    return raw, entry.sha256, entry.size, record.authority_sha256


def _derive_competitions_from_source(
    raw: bytes,
) -> tuple[tuple[tuple[str, str], ...], str, str]:
    """Parse the LeagueID class without importing or reflecting on it."""

    try:
        text = raw.decode("utf-8", errors="strict")
        tree = ast.parse(text, filename=_SOURCE_PATH)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise NbaApiCompetitionVerificationError(
            "competition source is not valid UTF-8 Python"
        ) from exc
    classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == _CLASS_NAME
    ]
    if len(classes) != 1:
        raise NbaApiCompetitionVerificationError(
            "competition source does not define exactly one LeagueID class"
        )
    class_node = classes[0]
    assignments: dict[str, ast.expr] = {}
    for node in class_node.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            raise NbaApiCompetitionVerificationError(
                "LeagueID class contains a noncanonical public definition"
            )
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id in assignments:
            raise NbaApiCompetitionVerificationError("LeagueID class assignments are ambiguous")
        assignments[target.id] = node.value
    default_node = assignments.pop("default", None)
    if not isinstance(default_node, ast.Name):
        raise NbaApiCompetitionVerificationError(
            "LeagueID default must reference one declared symbol"
        )
    rows: list[tuple[str, str]] = []
    for symbol, node in assignments.items():
        if _SYMBOL_RE.fullmatch(symbol) is None:
            raise NbaApiCompetitionVerificationError(
                "LeagueID contains a noncanonical competition symbol"
            )
        try:
            league_id = ast.literal_eval(node)
        except (TypeError, ValueError) as exc:
            raise NbaApiCompetitionVerificationError(
                "LeagueID competition value is not a literal"
            ) from exc
        if not isinstance(league_id, str) or _LEAGUE_ID_RE.fullmatch(league_id) is None:
            raise NbaApiCompetitionVerificationError(
                "LeagueID competition value is not two ASCII digits"
            )
        rows.append((league_id, symbol))
    competitions = tuple(sorted(rows))
    if (
        not competitions
        or len(competitions) != len(set(competitions))
        or len({item[0] for item in competitions}) != len(competitions)
        or len({item[1] for item in competitions}) != len(competitions)
    ):
        raise NbaApiCompetitionVerificationError(
            "LeagueID competition values are empty or non-bijective"
        )
    default_rows = tuple(item for item in competitions if item[1] == default_node.id)
    if len(default_rows) != 1:
        raise NbaApiCompetitionVerificationError(
            "LeagueID default references an unknown competition symbol"
        )
    return competitions, default_rows[0][1], default_rows[0][0]


def _load_checked_resource(path: Path | None) -> dict[str, object]:
    try:
        raw = (
            resources.files("nbadb.contracts").joinpath(_RESOURCE).read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionVerificationError("competition resource cannot be read") from exc
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiCompetitionVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiCompetitionVerificationError("competition resource cannot be decoded") from exc
    if not isinstance(payload, dict) or raw != _canonical_bytes(payload) + b"\n":
        raise NbaApiCompetitionVerificationError(
            "competition resource bytes are not canonical JSON"
        )
    expected_fields = {
        "schema_version",
        "kind",
        "provider",
        "competition_count",
        "competitions",
        "competition_values_sha256",
        "default",
        "authority_sha256",
        "independent_proof",
        "payload_sha256",
    }
    if set(payload) != expected_fields:
        raise NbaApiCompetitionVerificationError(
            "competition resource fields do not match the schema"
        )
    body = dict(payload)
    payload_sha256 = body.pop("payload_sha256", None)
    if _require_digest(payload_sha256, "payload_sha256") != _digest(body):
        raise NbaApiCompetitionVerificationError("competition resource payload digest is invalid")
    return cast("dict[str, object]", payload)


@dataclass(frozen=True, slots=True)
class IndependentCompetitionProof:
    """Independent AST/RECORD equality proof for the checked authority."""

    verifier_id: str
    competitions: tuple[tuple[str, str], ...]
    default_symbol: str
    default_league_id: str
    provider_source_sha256: str
    distribution_record_authority_sha256: str
    checked_payload_sha256: str
    proof_sha256: str


def _verify(path: Path | None) -> IndependentCompetitionProof:
    try:
        distribution = importlib.metadata.distribution(_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise NbaApiCompetitionVerificationError(
            "pinned nba_api distribution is not installed"
        ) from exc
    if distribution.version != _VERSION:
        raise NbaApiCompetitionVerificationError(
            "installed nba_api version differs from the exact pin"
        )
    source, source_sha256, source_size, record_sha256 = _source_binding(distribution)
    competitions, default_symbol, default_league_id = _derive_competitions_from_source(source)
    payload = _load_checked_resource(path)
    provider = payload.get("provider")
    rows = payload.get("competitions")
    default = payload.get("default")
    if (
        not isinstance(provider, dict)
        or not isinstance(rows, list)
        or not isinstance(default, dict)
    ):
        raise NbaApiCompetitionVerificationError(
            "competition resource authority fields are malformed"
        )
    expected_rows = [
        {"league_id": league_id, "symbol": symbol} for league_id, symbol in competitions
    ]
    authority_body = {
        "schema_version": 1,
        "kind": "nbadb_nba_api_competition_authority",
        "provider": {
            "distribution_name": _DISTRIBUTION,
            "distribution_version": _VERSION,
            "distribution_record_authority_sha256": record_sha256,
            "source_path": _SOURCE_PATH,
            "source_sha256": source_sha256,
            "source_size": source_size,
            "parameter_class_module": "nba_api.stats.library.parameters",
            "parameter_class_name": _CLASS_NAME,
        },
        "competition_count": len(competitions),
        "competitions": expected_rows,
        "competition_values_sha256": _digest([item[0] for item in competitions]),
        "default": {"league_id": default_league_id, "symbol": default_symbol},
    }
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "nbadb_nba_api_competition_authority"
        or provider != authority_body["provider"]
        or payload.get("competition_count") != len(competitions)
        or rows != expected_rows
        or payload.get("competition_values_sha256") != authority_body["competition_values_sha256"]
        or default != authority_body["default"]
        or payload.get("authority_sha256") != _digest(authority_body)
        or payload.get("independent_proof")
        != {
            "required": True,
            "schema_version": 1,
            "kind": "independent_competition_source_ast_receipt",
            "claim_status": "not_supplied_by_this_artifact",
        }
    ):
        raise NbaApiCompetitionVerificationError(
            "checked competition authority differs from independent source AST"
        )
    checked_payload_sha256 = _require_digest(payload.get("payload_sha256"), "payload_sha256")
    proof_body = {
        "schema_version": 1,
        "kind": "nbadb_independent_competition_proof",
        "verifier_id": _VERIFIER_ID,
        "competitions": expected_rows,
        "default": authority_body["default"],
        "provider_source_sha256": source_sha256,
        "distribution_record_authority_sha256": record_sha256,
        "checked_payload_sha256": checked_payload_sha256,
    }
    return IndependentCompetitionProof(
        verifier_id=_VERIFIER_ID,
        competitions=competitions,
        default_symbol=default_symbol,
        default_league_id=default_league_id,
        provider_source_sha256=source_sha256,
        distribution_record_authority_sha256=record_sha256,
        checked_payload_sha256=checked_payload_sha256,
        proof_sha256=_digest(proof_body),
    )


@lru_cache(maxsize=1)
def verify_pinned_competition_authority() -> IndependentCompetitionProof:
    """Independently verify the installed source against the checked receipt."""

    return _verify(None)


def verify_competition_authority_file(path: Path) -> IndependentCompetitionProof:
    """Independently verify an explicit candidate receipt without caching it."""

    return _verify(path)


__all__ = [
    "IndependentCompetitionProof",
    "NbaApiCompetitionVerificationError",
    "verify_competition_authority_file",
    "verify_pinned_competition_authority",
]
