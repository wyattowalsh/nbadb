"""Route-local entity capability and parameter-binding metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from nbadb.chat.catalog.sql_shape import has_top_level_set_operator, split_filterable_sql

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nbadb.chat.catalog.models import CatalogEntry, SemanticCatalog

EntityKind = Literal["none", "player", "team"]
_COLUMN_RE = re.compile(r"^(?:[a-z][a-z0-9_]*\.)?[a-z][a-z0-9_]*$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SEASONISH_RE = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d{2}(?:\s*[-/–—]\s*\d{1,4})?")
_PAIR_CUE_RE = re.compile(r"\b(?:vs\.?|versus|against)\b", re.IGNORECASE)
_ROSTER_REQUIRED_RE = re.compile(r"\bwho\s+played\s+for\b", re.IGNORECASE)
_GENERIC_TOKENS = frozenset(
    {
        "a",
        "all",
        "and",
        "are",
        "by",
        "can",
        "current",
        "during",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "is",
        "last",
        "latest",
        "leaders",
        "me",
        "of",
        "on",
        "playoff",
        "playoffs",
        "please",
        "regular",
        "season",
        "show",
        "stats",
        "the",
        "this",
        "to",
        "versus",
        "vs",
        "what",
        "which",
        "who",
        "with",
        "year",
    }
)


@dataclass(frozen=True)
class RouteEntityMeta:
    """Static entity predicate contract for one routed catalog entry."""

    kind: EntityKind = "none"
    columns: tuple[str, ...] = ()
    probe_columns: tuple[str, ...] = ()
    max_entities: int = 0
    pair_cue_required: bool = False
    roster_cue_required: bool = False

    def required_count(self, question: str) -> int:
        if self.pair_cue_required and _PAIR_CUE_RE.search(question):
            return 2
        if self.roster_cue_required and _ROSTER_REQUIRED_RE.search(question):
            return 1
        return 0


ROUTE_ENTITY_META: dict[str, RouteEntityMeta] = {
    "player_season_scoring": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "player_season_assists": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "player_season_rebounds": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "team_standings": RouteEntityMeta("team", ("s.team_id",), ("s.team_id",), 1),
    "pipeline_inventory": RouteEntityMeta(),
    "game_count": RouteEntityMeta(),
    "team_pace": RouteEntityMeta("team", ("s.team_id",), ("s.team_id",), 1),
    "shot_chart": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "draft_value": RouteEntityMeta("player", ("d.person_id",), (), 1),
    "head_to_head": RouteEntityMeta(
        "team",
        ("h.team_id", "h.opponent_team_id"),
        ("h.team_id", "h.opponent_team_id"),
        2,
        pair_cue_required=True,
    ),
    "team_season": RouteEntityMeta("team", ("s.team_id",), ("s.team_id",), 1),
    "player_season_complete": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "player_game_log": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "clutch_performance": RouteEntityMeta("player", ("c.player_id",), ("c.player_id",), 1),
    "player_matchups": RouteEntityMeta(
        "player",
        ("m.player_id", "m.vs_player_id"),
        ("m.player_id", "m.vs_player_id"),
        2,
        pair_cue_required=True,
    ),
    "franchise_history": RouteEntityMeta("team", ("f.team_id",), (), 1),
    "team_game_log": RouteEntityMeta("team", ("s.team_id",), ("s.team_id",), 1),
    "player_splits": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "team_splits": RouteEntityMeta("team", ("s.team_id",), ("s.team_id",), 1),
    "player_impact": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "league_benchmarks": RouteEntityMeta(),
    "game_summary": RouteEntityMeta(
        "team",
        ("home_team_id", "away_team_id"),
        ("home_team_id", "away_team_id"),
        2,
        pair_cue_required=True,
    ),
    "shooting_efficiency": RouteEntityMeta("player", ("s.player_id",), ("s.player_id",), 1),
    "team_roster": RouteEntityMeta(
        "team", ("b.team_id",), ("b.team_id",), 1, roster_cue_required=True
    ),
    "team_box_score": RouteEntityMeta("team", ("b.team_id",), ("b.team_id",), 1),
    "player_box_score": RouteEntityMeta("player", ("b.player_id",), ("b.player_id",), 1),
}


def _entry_tokens(entry: CatalogEntry) -> set[str]:
    tokens: set[str] = set()
    for text in (entry.name, *entry.aliases, *entry.metrics):
        tokens.update(_TOKEN_RE.findall(text.casefold().replace("_", " ")))
    return tokens


def question_has_entity_intent(entry: CatalogEntry, question: str) -> bool:
    """Conservatively detect entity text left outside the matched route language."""
    remainder = list(_SEASONISH_RE.sub(" ", question.casefold()))
    source = "".join(remainder)
    for pattern in entry.patterns:
        for match in pattern.finditer(source):
            remainder[match.start() : match.end()] = " " * (match.end() - match.start())
    ignored = _GENERIC_TOKENS | _entry_tokens(entry)
    return any(
        token not in ignored
        and not (token.endswith("s") and token[:-1] in ignored)
        and not token.isdigit()
        for token in _TOKEN_RE.findall("".join(remainder))
    )


def entity_meta_for(route: str) -> RouteEntityMeta:
    return ROUTE_ENTITY_META.get(route, RouteEntityMeta())


def _positive_entity_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("entity IDs must be positive integers")
    return value


def apply_entity_bind(
    sql: str,
    meta: RouteEntityMeta,
    entity_ids: Sequence[int],
    *,
    for_probe: bool = False,
) -> tuple[str, tuple[int, ...]]:
    """Attach one static route predicate and return its positional parameters."""
    ids = tuple(_positive_entity_id(value) for value in entity_ids)
    if not ids:
        return sql, ()
    columns = meta.probe_columns if for_probe else meta.columns
    if len(ids) > meta.max_entities or not columns:
        raise ValueError("entity binding does not match the route contract")
    if has_top_level_set_operator(sql):
        raise ValueError("catalog SQL set operations cannot receive entity filters")

    if len(columns) == 1 and len(ids) == 1:
        entity_predicate = f"{columns[0]} = ?"
        parameters = ids
    elif len(columns) == 2 and len(ids) == 1:
        entity_predicate = f"({columns[0]} = ? OR {columns[1]} = ?)"
        parameters = (ids[0], ids[0])
    elif len(columns) == 2 and len(ids) == 2:
        entity_predicate = (
            f"(({columns[0]} = ? AND {columns[1]} = ?) OR ({columns[0]} = ? AND {columns[1]} = ?))"
        )
        parameters = (ids[0], ids[1], ids[1], ids[0])
    else:
        raise ValueError("entity binding does not match the route contract")

    shape = split_filterable_sql(sql)
    predicate = (
        entity_predicate
        if shape.predicate is None
        else f"({shape.predicate}) AND {entity_predicate}"
    )
    tail = f" {shape.suffix}" if shape.suffix else ""
    return f"{shape.source} WHERE {predicate}{tail}", parameters


def validate_route_entity_meta(
    catalog: SemanticCatalog,
    *,
    metadata: Mapping[str, RouteEntityMeta] | None = None,
) -> list[str]:
    """Return fail-closed static contract errors for entity metadata."""
    from nbadb.chat.catalog.route_meta import season_meta_for

    target = ROUTE_ENTITY_META if metadata is None else metadata
    routed = {entry.route: entry for entry in catalog.entries if entry.route and entry.sql_template}
    errors: list[str] = []
    for route in sorted(set(routed) - set(target)):
        errors.append(f"{route}: missing route entity metadata")
    for route in sorted(set(target) - set(routed)):
        errors.append(f"{route}: entity metadata has no routed catalog entry")

    for route, entry in routed.items():
        meta = target.get(route)
        if meta is None:
            continue
        if meta.kind == "none":
            if meta.columns or meta.probe_columns or meta.max_entities:
                errors.append(f"{route}: non-entity route declares entity binding")
            continue
        identity_table = f"dim_{meta.kind}"
        if identity_table not in entry.tables:
            errors.append(f"{route}: entity lookup table {identity_table!r} is undeclared")
        if meta.max_entities not in {1, 2} or len(meta.columns) not in {1, 2}:
            errors.append(f"{route}: invalid entity cardinality")
        if len(meta.columns) == 1 and meta.max_entities != 1:
            errors.append(f"{route}: single-column route must bind at most one entity")
        for column in (*meta.columns, *meta.probe_columns):
            if not _COLUMN_RE.fullmatch(column):
                errors.append(f"{route}: invalid entity column {column!r}")
        normalized_template = entry.sql_template.casefold()
        for column in meta.columns:
            parts = column.split(".", 1)
            if len(parts) == 1:
                # Unqualified columns may be filter-only and absent from SELECT.
                present = True
            else:
                alias = parts[0]
                alias_pattern = rf"\b(?:from|join)\s+[a-z][a-z0-9_]*\s+{re.escape(alias)}\b"
                present = re.search(alias_pattern, normalized_template) is not None
            if not present:
                errors.append(f"{route}: entity alias for {column!r} is absent from route SQL")
        season_meta = season_meta_for(route)
        if season_meta.probe is None:
            if meta.probe_columns:
                errors.append(f"{route}: seasonless route declares probe entity columns")
            continue
        if not meta.probe_columns:
            errors.append(f"{route}: entity-capable year route lacks probe columns")
            continue
        normalized_probe = season_meta.probe.sql.casefold()
        for column in meta.probe_columns:
            parts = column.split(".", 1)
            if len(parts) == 1:
                # The route-schema EXPLAIN gate validates filter-only columns.
                present = True
            else:
                alias = parts[0]
                alias_pattern = rf"\b(?:from|join)\s+[a-z][a-z0-9_]*\s+{re.escape(alias)}\b"
                present = re.search(alias_pattern, normalized_probe) is not None
            if not present:
                errors.append(
                    f"{route}: probe entity alias for {column!r} is absent from probe SQL"
                )
    return errors
