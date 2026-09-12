"""Validated warehouse entity resolution for catalog query planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import duckdb

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.chat.catalog.entity_meta import RouteEntityMeta

EntityResolutionStatus = Literal["resolved", "ambiguous", "unresolved"]
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PLAYER_LOOKUP_SQL = (
    "SELECT DISTINCT player_id, full_name, first_name, last_name "
    "FROM dim_player WHERE is_current = TRUE ORDER BY player_id, full_name"
)
_TEAM_LOOKUP_SQL = (
    "SELECT DISTINCT team_id, full_name, abbreviation, city "
    "FROM dim_team ORDER BY team_id, full_name"
)
_ALIAS_STOP = frozenset({"jr", "sr", "ii", "iii", "iv", "the"})


@dataclass(frozen=True)
class EntityIdentity:
    entity_id: int
    display_name: str


@dataclass(frozen=True)
class EntityResolution:
    status: EntityResolutionStatus
    identities: tuple[EntityIdentity, ...] = ()


@dataclass(frozen=True)
class _AliasMatch:
    start: int
    end: int
    specificity: tuple[int, int]
    identity: EntityIdentity


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(value.casefold()))


def _positive_id(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _aliases(*values: object) -> tuple[tuple[str, ...], ...]:
    aliases: set[tuple[str, ...]] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = _tokens(value)
        if normalized:
            aliases.add(normalized)
            if len(normalized) > 1:
                aliases.update(
                    (token,) for token in normalized if len(token) >= 2 and token not in _ALIAS_STOP
                )
    return tuple(sorted(aliases, key=lambda item: (len(item), item)))


def _identity_rows(
    path: Path,
    meta: RouteEntityMeta,
) -> tuple[tuple[EntityIdentity, tuple[tuple[str, ...], ...]], ...]:
    sql = _PLAYER_LOOKUP_SQL if meta.kind == "player" else _TEAM_LOOKUP_SQL
    with duckdb.connect(str(path), read_only=True) as conn:
        conn.execute("SET enable_external_access = false")
        rows = conn.execute(sql).fetchall()

    identities: dict[int, tuple[EntityIdentity, set[tuple[str, ...]]]] = {}
    for row in rows:
        entity_id = _positive_id(row[0])
        display_name = row[1]
        if entity_id is None or not isinstance(display_name, str) or not display_name.strip():
            continue
        identity, identity_aliases = identities.setdefault(
            entity_id,
            (EntityIdentity(entity_id, display_name.strip()), set()),
        )
        identity_aliases.update(_aliases(*row[1:]))
        identities[entity_id] = (identity, identity_aliases)
    return tuple(
        (identity, tuple(sorted(aliases, key=lambda item: (len(item), item))))
        for identity, aliases in identities.values()
    )


def _find_matches(
    question: str,
    rows: tuple[tuple[EntityIdentity, tuple[tuple[str, ...], ...]], ...],
) -> tuple[_AliasMatch, ...]:
    question_tokens = _tokens(question)
    matches: list[_AliasMatch] = []
    for identity, aliases in rows:
        for alias in aliases:
            width = len(alias)
            for index in range(len(question_tokens) - width + 1):
                if question_tokens[index : index + width] == alias:
                    matches.append(
                        _AliasMatch(
                            start=index,
                            end=index + width,
                            specificity=(width, sum(len(token) for token in alias)),
                            identity=identity,
                        )
                    )
    return tuple(matches)


def _best_identities(matches: tuple[_AliasMatch, ...]) -> tuple[EntityIdentity, ...] | None:
    by_span: dict[tuple[int, int], list[_AliasMatch]] = {}
    for match in matches:
        by_span.setdefault((match.start, match.end), []).append(match)

    candidates: list[tuple[int, int, tuple[int, int], tuple[EntityIdentity, ...]]] = []
    for (start, end), span_matches in by_span.items():
        specificity = max(item.specificity for item in span_matches)
        identities = tuple(
            sorted(
                {
                    item.identity.entity_id: item.identity
                    for item in span_matches
                    if item.specificity == specificity
                }.values(),
                key=lambda item: item.entity_id,
            )
        )
        candidates.append((start, end, specificity, identities))

    survivors: list[tuple[int, int, tuple[int, int], tuple[EntityIdentity, ...]]] = []
    for candidate in candidates:
        start, end, specificity, _ = candidate
        if any(
            other_start <= start and end <= other_end and other_specificity > specificity
            for other_start, other_end, other_specificity, _ in candidates
        ):
            continue
        survivors.append(candidate)
    survivors.sort(key=lambda item: (item[0], -item[2][0], -item[2][1]))

    resolved: dict[int, EntityIdentity] = {}
    for _, _, _, identities in survivors:
        if len(identities) != 1:
            return None
        identity = identities[0]
        resolved.setdefault(identity.entity_id, identity)
    return tuple(resolved.values())


def resolve_entities(
    path: Path,
    meta: RouteEntityMeta,
    question: str,
    *,
    required_count: int,
) -> EntityResolution:
    """Resolve unique identities without putting question text into SQL."""
    try:
        rows = _identity_rows(path, meta)
    except (duckdb.Error, OSError):
        return EntityResolution("unresolved")
    identities = _best_identities(_find_matches(question, rows))
    if identities is None:
        return EntityResolution("ambiguous")
    if len(identities) > meta.max_entities:
        return EntityResolution("ambiguous")
    if len(identities) < max(1, required_count):
        return EntityResolution("unresolved")
    return EntityResolution("resolved", identities)
