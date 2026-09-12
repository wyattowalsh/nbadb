"""Immutable workload values for cumulative player and team statistics.

``CumeStatsPlayer`` and ``CumeStatsTeam`` are dependent endpoints: their
``GameIDs`` argument must come from an already-complete player/team game
inventory.  This module binds that inventory to the exact entity and season
scope without integrating it into planning or workflow execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self, cast

from nbadb.core.types import SeasonType

CUME_WORKLOAD_SCHEMA_VERSION = 1

_GAME_ID_RE = re.compile(r"[0-9]{10}")
_SEASON_RE = re.compile(r"([0-9]{4})-([0-9]{2})")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_REASON_RE = re.compile(r"[a-z0-9][a-z0-9_]*")
_MAX_CANONICAL_BYTES = 16 * 1024
_WORKLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "entity_kind",
        "entity_id",
        "season",
        "season_type",
        "game_ids",
        "disposition",
        "typed_zero_reason",
        "foundation_receipt_sha256",
        "provider_authority_sha256",
    }
)


class CumeWorkloadContractError(ValueError):
    """Raised when cumulative-stat workload evidence is unsafe to execute."""


class CumeEntityKind(StrEnum):
    PLAYER = "player"
    TEAM = "team"


class CumeWorkloadDisposition(StrEnum):
    COMPLETE = "complete"
    TYPED_ZERO = "typed_zero"


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _require_sha256(value: object, *, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise CumeWorkloadContractError(f"{field_name} must be a lowercase SHA-256")


def _decode_canonical_object(encoded: bytes) -> dict[str, object]:
    if type(encoded) is not bytes:
        raise CumeWorkloadContractError("cume workload canonical input must be bytes")
    if not encoded or len(encoded) > _MAX_CANONICAL_BYTES:
        raise CumeWorkloadContractError("cume workload canonical byte length is invalid")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CumeWorkloadContractError(
                    "cume workload canonical JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                CumeWorkloadContractError(
                    "cume workload canonical JSON contains a non-finite number"
                )
            ),
        )
    except CumeWorkloadContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CumeWorkloadContractError("cume workload canonical input is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise CumeWorkloadContractError("cume workload canonical root must be an object")
    payload = cast("dict[str, object]", decoded)
    try:
        canonical = _canonical_bytes(payload)
    except (TypeError, ValueError, RecursionError) as exc:
        raise CumeWorkloadContractError("cume workload canonical JSON value is invalid") from exc
    if canonical != encoded:
        raise CumeWorkloadContractError("cume workload input is not canonical JSON")
    return payload


def _normalize_season(value: object) -> str:
    if not isinstance(value, str) or (match := _SEASON_RE.fullmatch(value)) is None:
        raise CumeWorkloadContractError("season must use exact consecutive YYYY-YY form")
    start_year = int(match.group(1))
    if int(match.group(2)) != (start_year + 1) % 100:
        raise CumeWorkloadContractError("season must use exact consecutive YYYY-YY form")
    return value


def _normalize_season_type(value: object) -> str:
    if not isinstance(value, str):
        raise CumeWorkloadContractError("season_type must be an exact supported value")
    try:
        return SeasonType(value).value
    except ValueError as exc:
        raise CumeWorkloadContractError("season_type must be an exact supported value") from exc


def normalize_cume_game_ids(value: object, *, allow_empty: bool = False) -> tuple[str, ...]:
    """Validate an ordered GAME_ID sequence or its exact pipe encoding.

    Sets and generic iterables are rejected because their iteration order is
    not an admissible workload authority.  No trimming or case/number coercion
    occurs: every GAME_ID must already be its exact ten-digit provider value.
    """

    if isinstance(value, str):
        game_ids = tuple(value.split("|")) if value else ()
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        game_ids = tuple(value)
    else:
        raise CumeWorkloadContractError(
            "game_ids must be an ordered sequence or exact pipe-delimited string"
        )

    if not game_ids and not allow_empty:
        raise CumeWorkloadContractError("game_ids must be nonempty")
    normalized: list[str] = []
    for game_id in game_ids:
        if not isinstance(game_id, str) or _GAME_ID_RE.fullmatch(game_id) is None:
            raise CumeWorkloadContractError("each GAME_ID must be an exact ten-digit string")
        normalized.append(game_id)
    if len(normalized) != len(set(normalized)):
        raise CumeWorkloadContractError("game_ids must not contain duplicates")
    return tuple(normalized)


def encode_cume_game_ids(value: object) -> str:
    """Return the exact ``nba_api`` ``GameIDs`` pipe encoding."""

    return "|".join(normalize_cume_game_ids(value))


@dataclass(frozen=True, slots=True)
class CumeWorkloadValue:
    """One content-addressed cumulative-stat dependent workload scope."""

    entity_kind: CumeEntityKind
    entity_id: int
    season: str
    season_type: str
    game_ids: tuple[str, ...]
    disposition: CumeWorkloadDisposition = CumeWorkloadDisposition.COMPLETE
    typed_zero_reason: str | None = None
    foundation_receipt_sha256: str | None = None
    provider_authority_sha256: str | None = None

    def __post_init__(self) -> None:
        try:
            entity_kind = CumeEntityKind(self.entity_kind)
        except ValueError as exc:
            raise CumeWorkloadContractError("entity_kind must be player or team") from exc
        if type(self.entity_id) is not int or self.entity_id <= 0:
            raise CumeWorkloadContractError("entity_id must be a positive integer")
        try:
            disposition = CumeWorkloadDisposition(self.disposition)
        except ValueError as exc:
            raise CumeWorkloadContractError("workload disposition is invalid") from exc

        season = _normalize_season(self.season)
        season_type = _normalize_season_type(self.season_type)
        game_ids = normalize_cume_game_ids(
            self.game_ids,
            allow_empty=disposition is CumeWorkloadDisposition.TYPED_ZERO,
        )
        if disposition is CumeWorkloadDisposition.COMPLETE:
            if self.typed_zero_reason is not None:
                raise CumeWorkloadContractError(
                    "complete workload must not declare a typed-zero reason"
                )
        else:
            if game_ids:
                raise CumeWorkloadContractError("typed-zero workload must not contain GAME_IDs")
            if (
                not isinstance(self.typed_zero_reason, str)
                or _REASON_RE.fullmatch(self.typed_zero_reason) is None
            ):
                raise CumeWorkloadContractError("typed-zero workload requires a stable reason code")

        _require_sha256(
            self.foundation_receipt_sha256,
            field_name="foundation_receipt_sha256",
        )
        _require_sha256(
            self.provider_authority_sha256,
            field_name="provider_authority_sha256",
        )
        object.__setattr__(self, "entity_kind", entity_kind)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "season", season)
        object.__setattr__(self, "season_type", season_type)
        object.__setattr__(self, "game_ids", game_ids)

    @classmethod
    def complete(
        cls,
        *,
        entity_kind: CumeEntityKind,
        entity_id: int,
        season: str,
        season_type: str,
        game_ids: object,
        foundation_receipt_sha256: str | None = None,
        provider_authority_sha256: str | None = None,
    ) -> CumeWorkloadValue:
        return cls(
            entity_kind=entity_kind,
            entity_id=entity_id,
            season=season,
            season_type=season_type,
            game_ids=normalize_cume_game_ids(game_ids),
            foundation_receipt_sha256=foundation_receipt_sha256,
            provider_authority_sha256=provider_authority_sha256,
        )

    @classmethod
    def typed_zero(
        cls,
        *,
        entity_kind: CumeEntityKind,
        entity_id: int,
        season: str,
        season_type: str,
        reason_code: str,
        foundation_receipt_sha256: str | None = None,
        provider_authority_sha256: str | None = None,
    ) -> CumeWorkloadValue:
        return cls(
            entity_kind=entity_kind,
            entity_id=entity_id,
            season=season,
            season_type=season_type,
            game_ids=(),
            disposition=CumeWorkloadDisposition.TYPED_ZERO,
            typed_zero_reason=reason_code,
            foundation_receipt_sha256=foundation_receipt_sha256,
            provider_authority_sha256=provider_authority_sha256,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        """Strictly decode one current-schema canonical workload body."""

        if not isinstance(payload, Mapping) or set(payload) != _WORKLOAD_FIELDS:
            raise CumeWorkloadContractError("cume workload fields are invalid")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != CUME_WORKLOAD_SCHEMA_VERSION
            or payload["kind"] != "nbadb_cume_workload"
        ):
            raise CumeWorkloadContractError("cume workload schema identity is invalid")
        raw_entity_kind = payload["entity_kind"]
        raw_disposition = payload["disposition"]
        try:
            entity_kind = CumeEntityKind(raw_entity_kind)
            disposition = CumeWorkloadDisposition(raw_disposition)
        except (TypeError, ValueError) as exc:
            raise CumeWorkloadContractError("cume workload enum value is invalid") from exc
        raw_game_ids = payload["game_ids"]
        if not isinstance(raw_game_ids, list):
            raise CumeWorkloadContractError("cume workload game_ids must be a list")
        if any(not isinstance(game_id, str) for game_id in raw_game_ids):
            raise CumeWorkloadContractError("each GAME_ID must be an exact ten-digit string")
        entity_id = payload["entity_id"]
        if type(entity_id) is not int:
            raise CumeWorkloadContractError("entity_id must be a positive integer")
        season = payload["season"]
        season_type = payload["season_type"]
        if not isinstance(season, str) or not isinstance(season_type, str):
            raise CumeWorkloadContractError("season and season_type must be exact strings")
        typed_zero_reason = payload["typed_zero_reason"]
        if typed_zero_reason is not None and not isinstance(typed_zero_reason, str):
            raise CumeWorkloadContractError("typed_zero_reason must be a string or null")
        foundation_receipt = payload["foundation_receipt_sha256"]
        provider_authority = payload["provider_authority_sha256"]
        _require_sha256(
            foundation_receipt,
            field_name="foundation_receipt_sha256",
        )
        _require_sha256(
            provider_authority,
            field_name="provider_authority_sha256",
        )
        result = cls(
            entity_kind=entity_kind,
            entity_id=entity_id,
            season=season,
            season_type=season_type,
            game_ids=tuple(cast("list[str]", raw_game_ids)),
            disposition=disposition,
            typed_zero_reason=typed_zero_reason,
            foundation_receipt_sha256=cast("str | None", foundation_receipt),
            provider_authority_sha256=cast("str | None", provider_authority),
        )
        if result._identity_payload() != dict(payload):
            raise CumeWorkloadContractError("cume workload body differs after strict normalization")
        return result

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        """Decode exact compact UTF-8 JSON without normalization or fallback."""

        payload = _decode_canonical_object(encoded)
        result = cls.from_dict(payload)
        if result.canonical_bytes != encoded:
            raise CumeWorkloadContractError("cume workload canonical bytes differ")
        return result

    @property
    def encoded_game_ids(self) -> str:
        if self.disposition is CumeWorkloadDisposition.TYPED_ZERO:
            raise CumeWorkloadContractError("typed-zero cume workload is not executable")
        return encode_cume_game_ids(self.game_ids)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": CUME_WORKLOAD_SCHEMA_VERSION,
            "kind": "nbadb_cume_workload",
            "entity_kind": self.entity_kind.value,
            "entity_id": self.entity_id,
            "season": self.season,
            "season_type": self.season_type,
            "game_ids": list(self.game_ids),
            "disposition": self.disposition.value,
            "typed_zero_reason": self.typed_zero_reason,
            "foundation_receipt_sha256": self.foundation_receipt_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self._identity_payload())

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @property
    def generation_basename(self) -> str:
        return f"cume-workload.{self.content_sha256}.json"

    def to_payload(self) -> dict[str, object]:
        return {"content_sha256": self.content_sha256, **self._identity_payload()}
