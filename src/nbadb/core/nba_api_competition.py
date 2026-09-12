"""Exact-package authority for the finite NBA API competition domain.

The provider's ``LeagueID`` class is the compiler input.  The checked JSON is
only a receipt: every load rebuilds the authority from the installed pinned
distribution, verifies its complete ``RECORD``, and then requires an
independent source-AST proof before exposing the finite values to planners.
No provider request or network access is performed.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from nba_api.stats.library import parameters as provider_parameters

from nbadb.core.nba_api_surface_inventory import (
    NBA_API_DISTRIBUTION,
    NBA_API_VERSION,
    NbaApiSurfaceInventoryError,
    build_distribution_record_authority,
)

if TYPE_CHECKING:
    from importlib.metadata import Distribution

COMPETITION_SCHEMA_VERSION: Final = 1
COMPETITION_RESOURCE: Final = "nba_api_competition_v1_11_4.json"
COMPETITION_SOURCE_PATH: Final = "nba_api/stats/library/parameters.py"
COMPETITION_PARAMETER_CLASS: Final = "LeagueID"

_SYMBOL_RE = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)
_LEAGUE_ID_RE = re.compile(r"[0-9]{2}", flags=re.ASCII)
_SHA256_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class NbaApiCompetitionError(ValueError):
    """The exact package competition authority is invalid."""


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
        raise NbaApiCompetitionError("competition authority is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiCompetitionError(f"{field} must be a canonical SHA-256")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiCompetitionError(
                f"competition resource contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiCompetitionError(f"competition resource contains non-finite JSON constant: {value}")


@dataclass(frozen=True, slots=True, order=True)
class CompetitionValue:
    """One provider-declared competition symbol and exact wire value."""

    league_id: str
    symbol: str

    def __post_init__(self) -> None:
        if not isinstance(self.league_id, str) or _LEAGUE_ID_RE.fullmatch(self.league_id) is None:
            raise NbaApiCompetitionError("competition league_id must be two ASCII digits")
        if not isinstance(self.symbol, str) or _SYMBOL_RE.fullmatch(self.symbol) is None:
            raise NbaApiCompetitionError("competition symbol must be canonical snake case")

    def to_dict(self) -> dict[str, str]:
        return {"league_id": self.league_id, "symbol": self.symbol}


@dataclass(frozen=True, slots=True)
class CompetitionAuthority:
    """Primary reflection-derived finite competition authority."""

    distribution_record_authority_sha256: str
    provider_source_path: str
    provider_source_sha256: str
    provider_source_size: int
    competitions: tuple[CompetitionValue, ...]
    default_symbol: str
    default_league_id: str

    def __post_init__(self) -> None:
        _require_digest(
            self.distribution_record_authority_sha256,
            "distribution_record_authority_sha256",
        )
        _require_digest(self.provider_source_sha256, "provider_source_sha256")
        if self.provider_source_path != COMPETITION_SOURCE_PATH:
            raise NbaApiCompetitionError("competition provider source path is invalid")
        if (
            isinstance(self.provider_source_size, bool)
            or not isinstance(self.provider_source_size, int)
            or self.provider_source_size <= 0
        ):
            raise NbaApiCompetitionError("competition provider source size is invalid")
        if (
            type(self.competitions) is not tuple
            or not self.competitions
            or any(type(item) is not CompetitionValue for item in self.competitions)
            or self.competitions != tuple(sorted(set(self.competitions)))
        ):
            raise NbaApiCompetitionError("competition values must be sorted, unique, and nonempty")
        symbols = tuple(item.symbol for item in self.competitions)
        league_ids = tuple(item.league_id for item in self.competitions)
        if len(symbols) != len(set(symbols)) or len(league_ids) != len(set(league_ids)):
            raise NbaApiCompetitionError("competition symbols and league IDs must be bijective")
        defaults = tuple(
            item
            for item in self.competitions
            if item.symbol == self.default_symbol and item.league_id == self.default_league_id
        )
        if len(defaults) != 1:
            raise NbaApiCompetitionError("competition default must select one declared value")

    @property
    def league_ids(self) -> tuple[str, ...]:
        return tuple(item.league_id for item in self.competitions)

    @property
    def competition_values_sha256(self) -> str:
        return _digest(list(self.league_ids))

    @property
    def authority_sha256(self) -> str:
        return _digest(_authority_payload(self))


def _authority_payload(authority: CompetitionAuthority) -> dict[str, object]:
    return {
        "schema_version": COMPETITION_SCHEMA_VERSION,
        "kind": "nbadb_nba_api_competition_authority",
        "provider": {
            "distribution_name": NBA_API_DISTRIBUTION,
            "distribution_version": NBA_API_VERSION,
            "distribution_record_authority_sha256": (
                authority.distribution_record_authority_sha256
            ),
            "source_path": authority.provider_source_path,
            "source_sha256": authority.provider_source_sha256,
            "source_size": authority.provider_source_size,
            "parameter_class_module": "nba_api.stats.library.parameters",
            "parameter_class_name": COMPETITION_PARAMETER_CLASS,
        },
        "competition_count": len(authority.competitions),
        "competitions": [item.to_dict() for item in authority.competitions],
        "competition_values_sha256": authority.competition_values_sha256,
        "default": {
            "league_id": authority.default_league_id,
            "symbol": authority.default_symbol,
        },
    }


def _source_binding(
    distribution: Distribution,
) -> tuple[str, int, str]:
    try:
        record = build_distribution_record_authority(distribution)
    except NbaApiSurfaceInventoryError as exc:
        raise NbaApiCompetitionError("installed nba_api RECORD authority is invalid") from exc
    entries = tuple(entry for entry in record.entries if entry.path == COMPETITION_SOURCE_PATH)
    if len(entries) != 1:
        raise NbaApiCompetitionError("competition provider source RECORD entry is ambiguous")
    entry = entries[0]
    return entry.sha256, entry.size, record.authority_sha256


def _runtime_competitions(
    parameter_class: type[object],
) -> tuple[tuple[CompetitionValue, ...], str, str]:
    if (
        parameter_class.__module__ != "nba_api.stats.library.parameters"
        or parameter_class.__name__ != COMPETITION_PARAMETER_CLASS
    ):
        raise NbaApiCompetitionError("competition parameter class identity is invalid")
    values: list[CompetitionValue] = []
    for symbol, raw_value in vars(parameter_class).items():
        if symbol.startswith("_") or symbol == "default":
            continue
        if not isinstance(raw_value, str):
            raise NbaApiCompetitionError(
                "competition parameter class contains a non-string public member"
            )
        values.append(CompetitionValue(league_id=raw_value, symbol=symbol))
    competitions = tuple(sorted(values))
    default = vars(parameter_class).get("default")
    if not isinstance(default, str):
        raise NbaApiCompetitionError("competition parameter class default is invalid")
    default_symbols = tuple(item.symbol for item in competitions if item.league_id == default)
    if len(default_symbols) != 1:
        raise NbaApiCompetitionError("competition parameter default is not a unique member")
    return competitions, default_symbols[0], default


@lru_cache(maxsize=1)
def build_competition_authority() -> CompetitionAuthority:
    """Derive the finite competition authority from the installed package."""

    try:
        distribution = importlib.metadata.distribution(NBA_API_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise NbaApiCompetitionError("pinned nba_api distribution is not installed") from exc
    if distribution.version != NBA_API_VERSION:
        raise NbaApiCompetitionError("installed nba_api version differs from the exact pin")
    parameter_class = getattr(provider_parameters, COMPETITION_PARAMETER_CLASS, None)
    if not inspect.isclass(parameter_class):
        raise NbaApiCompetitionError("installed package omits the LeagueID parameter class")
    expected_source = Path(str(distribution.locate_file(COMPETITION_SOURCE_PATH))).resolve(
        strict=True
    )
    observed_source_name = inspect.getsourcefile(parameter_class)
    if observed_source_name is None:
        raise NbaApiCompetitionError("competition parameter class source is unavailable")
    observed_source = Path(observed_source_name).resolve(strict=True)
    if observed_source != expected_source:
        raise NbaApiCompetitionError(
            "competition parameter class is not owned by the pinned distribution source"
        )
    source_sha256, source_size, record_sha256 = _source_binding(distribution)
    competitions, default_symbol, default_league_id = _runtime_competitions(parameter_class)
    return CompetitionAuthority(
        distribution_record_authority_sha256=record_sha256,
        provider_source_path=COMPETITION_SOURCE_PATH,
        provider_source_sha256=source_sha256,
        provider_source_size=source_size,
        competitions=competitions,
        default_symbol=default_symbol,
        default_league_id=default_league_id,
    )


def build_pinned_competition_payload() -> dict[str, object]:
    """Build the canonical checked receipt for the current exact package."""

    authority = build_competition_authority()
    authority_payload = _authority_payload(authority)
    payload: dict[str, object] = {
        **authority_payload,
        "authority_sha256": authority.authority_sha256,
        "independent_proof": {
            "required": True,
            "schema_version": 1,
            "kind": "independent_competition_source_ast_receipt",
            "claim_status": "not_supplied_by_this_artifact",
        },
    }
    payload["payload_sha256"] = _digest(payload)
    return payload


def write_pinned_competition(path: Path, *, check: bool = False) -> bool:
    """Write or verify the canonical checked competition receipt."""

    encoded = _canonical_bytes(build_pinned_competition_payload()) + b"\n"
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise NbaApiCompetitionError("pinned competition authority has generated drift")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False


def load_pinned_competition_payload(path: Path | None = None) -> dict[str, object]:
    """Load the checked receipt and reproduce it from the installed package."""

    try:
        raw = (
            resources.files("nbadb.contracts").joinpath(COMPETITION_RESOURCE).read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionError("competition resource cannot be read") from exc
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiCompetitionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiCompetitionError("competition resource cannot be decoded") from exc
    if not isinstance(payload, dict) or raw != _canonical_bytes(payload) + b"\n":
        raise NbaApiCompetitionError("competition resource bytes are not canonical JSON")
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
        raise NbaApiCompetitionError("competition resource fields do not match the schema")
    body = dict(payload)
    digest = body.pop("payload_sha256", None)
    if _require_digest(digest, "payload_sha256") != _digest(body):
        raise NbaApiCompetitionError("competition resource payload digest is invalid")
    if payload != build_pinned_competition_payload():
        raise NbaApiCompetitionError(
            "competition resource differs from the installed package authority"
        )
    return cast("dict[str, object]", payload)


@lru_cache(maxsize=1)
def pinned_competition_authority() -> CompetitionAuthority:
    """Return the primary authority only after independent source verification."""

    payload = load_pinned_competition_payload()
    authority = build_competition_authority()
    from nbadb.core.nba_api_competition_verifier import (
        verify_pinned_competition_authority,
    )

    proof = verify_pinned_competition_authority()
    primary_rows = tuple((item.league_id, item.symbol) for item in authority.competitions)
    if (
        proof.competitions != primary_rows
        or proof.default_symbol != authority.default_symbol
        or proof.default_league_id != authority.default_league_id
        or proof.checked_payload_sha256 != payload.get("payload_sha256")
        or proof.provider_source_sha256 != authority.provider_source_sha256
        or proof.distribution_record_authority_sha256
        != authority.distribution_record_authority_sha256
    ):
        raise NbaApiCompetitionError("primary and independent competition authorities differ")
    return authority


def pinned_competition_values() -> tuple[str, ...]:
    """Return the exact finite league IDs admitted by the pinned package."""

    return pinned_competition_authority().league_ids


__all__ = [
    "COMPETITION_PARAMETER_CLASS",
    "COMPETITION_RESOURCE",
    "COMPETITION_SCHEMA_VERSION",
    "COMPETITION_SOURCE_PATH",
    "CompetitionAuthority",
    "CompetitionValue",
    "NbaApiCompetitionError",
    "build_competition_authority",
    "build_pinned_competition_payload",
    "load_pinned_competition_payload",
    "pinned_competition_authority",
    "pinned_competition_values",
    "write_pinned_competition",
]
