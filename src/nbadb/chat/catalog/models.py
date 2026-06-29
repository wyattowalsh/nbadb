from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

_DEFAULT_JSON = Path(__file__).with_name("default.json")
_EXPORT_JSON = (
    Path(__file__).resolve().parents[4] / "docs" / "lib" / "generated" / "agent-catalog.json"
)

_SCD2_JOIN_NOTE = (
    "dim_player and dim_team_history are SCD2; filter is_current = TRUE for present-day names."
)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokens(value: str) -> tuple[str, ...]:
    normalized = value.casefold().replace("_", " ").replace("-", " ")
    return tuple(_TOKEN_PATTERN.findall(normalized))


def _contains_token_sequence(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(haystack[index : index + width] == needle for index in range(len(haystack)))


@dataclass(frozen=True)
class CatalogEntry:
    """Curated meaning for tables and metrics used by chat/query planning."""

    name: str
    description: str
    tables: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    route: str = ""
    sql_template: str = ""
    patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple, compare=False)

    def matches(self, question: str) -> bool:
        question_tokens = _tokens(question)
        terms = (self.name, *self.aliases, *self.metrics)
        if any(_contains_token_sequence(question_tokens, _tokens(term)) for term in terms):
            return True
        return any(pattern.search(question) for pattern in self.patterns)

    def scd2_notes(self) -> tuple[str, ...]:
        notes = list(self.caveats)
        if (
            any(table in {"dim_player", "dim_team_history"} for table in self.tables)
            and _SCD2_JOIN_NOTE not in notes
        ):
            notes.append(_SCD2_JOIN_NOTE)
        return tuple(notes)


@dataclass(frozen=True)
class SemanticCatalog:
    entries: tuple[CatalogEntry, ...] = field(default_factory=tuple)

    def relevant_entries(self, question: str, *, limit: int = 5) -> tuple[CatalogEntry, ...]:
        matches = [entry for entry in self.entries if entry.matches(question)]
        return tuple(matches[:limit])

    def table_hints(self, question: str) -> tuple[str, ...]:
        tables: list[str] = []
        for entry in self.relevant_entries(question):
            for table in entry.tables:
                if table not in tables:
                    tables.append(table)
        if not tables:
            export_tables = export_table_index()
            normalized = question.casefold()
            for table_name, metadata in export_tables.items():
                intents = metadata.get("agent_intents", [])
                if not isinstance(intents, list):
                    continue
                if (
                    any(str(intent).casefold() in normalized for intent in intents)
                    and table_name not in tables
                ):
                    tables.append(table_name)
        return tuple(tables)

    def export_context_lines(
        self,
        question: str,
        *,
        export: dict[str, Any] | None = None,
    ) -> tuple[str, ...]:
        export_tables = export_table_index(export)
        lines: list[str] = []
        for entry in self.relevant_entries(question):
            for table in entry.tables:
                metadata = export_tables.get(table)
                if metadata is None:
                    continue
                grain = metadata.get("grain")
                if grain:
                    lines.append(f"{table}: grain={grain}")
                scd2_notes = metadata.get("scd2_notes")
                if scd2_notes:
                    lines.append(f"{table}: {scd2_notes}")
        return tuple(lines)

    def match_route(self, question: str) -> CatalogEntry | None:
        for entry in self.entries:
            if not entry.sql_template:
                continue
            if entry.patterns:
                if any(pattern.search(question) for pattern in entry.patterns):
                    return entry
            elif entry.matches(question):
                return entry
        return None


def _compile_patterns(patterns: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        compiled.append(re.compile(pattern, re.IGNORECASE))
    return tuple(compiled)


def _entry_from_mapping(data: dict[str, Any]) -> CatalogEntry:
    return CatalogEntry(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        tables=tuple(str(item) for item in data.get("tables", ())),
        aliases=tuple(str(item) for item in data.get("aliases", ())),
        metrics=tuple(str(item) for item in data.get("metrics", ())),
        caveats=tuple(str(item) for item in data.get("caveats", ())),
        route=str(data.get("route", "")),
        sql_template=str(data.get("sql_template", "")),
        patterns=_compile_patterns(str(item) for item in data.get("patterns", ())),
    )


def _builtin_entries() -> tuple[CatalogEntry, ...]:
    return (
        CatalogEntry(
            name="player season scoring",
            description="Season-level player scoring leaders from star-schema aggregates.",
            tables=("agg_player_season", "dim_player"),
            aliases=("scoring", "points", "most points", "points leader", "led scoring"),
            metrics=("total_pts",),
            route="player_season_scoring",
            sql_template=(
                "SELECT s.player_id, p.full_name, s.total_pts "
                "FROM agg_player_season s "
                "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
                "ORDER BY s.total_pts DESC"
            ),
            patterns=_compile_patterns(
                (
                    r"who\s+led\s+(?:in\s+)?scoring",
                    r"most\s+points",
                )
            ),
            caveats=("dim_player is SCD2; use current rows when asking for current names.",),
        ),
        CatalogEntry(
            name="player season assists",
            description="Season-level player assist leaders from star-schema aggregates.",
            tables=("agg_player_season", "dim_player"),
            aliases=("assists", "most assists", "assist leader"),
            metrics=("total_ast",),
            route="player_season_assists",
            sql_template=(
                "SELECT s.player_id, p.full_name, s.total_ast "
                "FROM agg_player_season s "
                "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
                "ORDER BY s.total_ast DESC"
            ),
            patterns=_compile_patterns((r"most\s+assists",)),
        ),
        CatalogEntry(
            name="player season rebounds",
            description="Season-level player rebound leaders from star-schema aggregates.",
            tables=("agg_player_season", "dim_player"),
            aliases=("rebounds", "most rebounds", "rebound leader"),
            metrics=("total_reb",),
            route="player_season_rebounds",
            sql_template=(
                "SELECT s.player_id, p.full_name, s.total_reb "
                "FROM agg_player_season s "
                "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
                "ORDER BY s.total_reb DESC"
            ),
            patterns=_compile_patterns((r"most\s+rebounds",)),
        ),
        CatalogEntry(
            name="team standings",
            description="Team win/loss standings joined to team dimensions.",
            tables=("fact_standings", "dim_team"),
            aliases=("standings", "team record", "wins", "losses"),
            metrics=("wins", "losses", "win_pct"),
            route="team_standings",
            sql_template=(
                "SELECT t.full_name, s.wins, s.losses, s.win_pct "
                "FROM fact_standings s "
                "JOIN dim_team t ON s.team_id = t.team_id "
                "ORDER BY s.wins DESC"
            ),
            patterns=_compile_patterns((r"team\s+standings", r"\bstandings\b")),
        ),
        CatalogEntry(
            name="pipeline inventory",
            description="Pipeline table row counts and metadata inventory.",
            tables=("_pipeline_metadata",),
            aliases=("how many games", "how many records", "row count", "records"),
            metrics=("row_count",),
            route="pipeline_inventory",
            sql_template=(
                "SELECT table_name, row_count FROM _pipeline_metadata ORDER BY row_count DESC"
            ),
            patterns=_compile_patterns((r"how\s+many\s+(?:games|records)",)),
        ),
        CatalogEntry(
            name="team pace leaders",
            description="Team-season pace and efficiency leaders.",
            tables=("agg_team_pace_and_efficiency", "dim_team"),
            aliases=("pace", "fastest pace", "team pace"),
            metrics=("avg_pace", "avg_ortg", "avg_drtg"),
            route="team_pace",
            sql_template=(
                "SELECT t.full_name, s.season_year, s.avg_pace, s.avg_ortg, s.avg_drtg "
                "FROM agg_team_pace_and_efficiency s "
                "JOIN dim_team t ON s.team_id = t.team_id "
                "ORDER BY s.avg_pace DESC"
            ),
            patterns=_compile_patterns((r"team\s+pace", r"pace\s+leaders?", r"fastest\s+pace")),
        ),
        CatalogEntry(
            name="shot chart",
            description="Player shot locations from fact_shot_chart.",
            tables=("fact_shot_chart", "dim_player"),
            aliases=("shot chart", "shot locations", "shooting zones"),
            metrics=("shot_zone_basic", "shot_made_flag"),
            route="shot_chart",
            sql_template=(
                "SELECT p.full_name, s.shot_zone_basic, COUNT(*) AS attempts, "
                "SUM(s.shot_made_flag) AS makes "
                "FROM fact_shot_chart s "
                "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
                "GROUP BY p.full_name, s.shot_zone_basic "
                "ORDER BY attempts DESC"
            ),
            patterns=_compile_patterns(
                (r"shot\s+chart", r"shot\s+locations?", r"shooting\s+zones?")
            ),
        ),
        CatalogEntry(
            name="draft value",
            description="Draft picks enriched with career outcomes.",
            tables=("analytics_draft_value", "dim_player"),
            aliases=("draft", "draft picks", "draft value"),
            metrics=("overall_pick", "career_pts"),
            route="draft_value",
            sql_template=(
                "SELECT d.season, d.overall_pick, p.full_name, d.career_pts "
                "FROM analytics_draft_value d "
                "LEFT JOIN dim_player p ON d.person_id = p.player_id AND p.is_current = TRUE "
                "ORDER BY d.overall_pick ASC"
            ),
            patterns=_compile_patterns((r"draft\s+picks?", r"draft\s+value", r"draft\s+class")),
        ),
        CatalogEntry(
            name="head to head",
            description="Team head-to-head records by season.",
            tables=("analytics_head_to_head", "dim_team"),
            aliases=("head to head", "h2h", "matchup record"),
            metrics=("wins", "losses", "avg_margin"),
            route="head_to_head",
            sql_template=(
                "SELECT h.team_abbr, h.opponent_abbr, h.season_year, "
                "h.wins, h.losses, h.avg_margin "
                "FROM analytics_head_to_head h "
                "ORDER BY h.season_year DESC, h.wins DESC"
            ),
            patterns=_compile_patterns((r"head[\s-]to[\s-]head", r"\bh2h\b")),
        ),
        CatalogEntry(
            name="team season stats",
            description="Team season traditional stat aggregates.",
            tables=("agg_team_season", "dim_team"),
            aliases=("team season", "team stats", "team averages"),
            metrics=("avg_pts", "avg_reb", "avg_ast"),
            route="team_season",
            sql_template=(
                "SELECT t.full_name, s.season_year, s.avg_pts, s.avg_reb, s.avg_ast "
                "FROM agg_team_season s "
                "JOIN dim_team t ON s.team_id = t.team_id "
                "ORDER BY s.avg_pts DESC"
            ),
            patterns=_compile_patterns((r"team\s+season", r"team\s+stats", r"team\s+averages?")),
        ),
        CatalogEntry(
            name="player season complete",
            description="Complete player-season profile.",
            tables=("analytics_player_season_complete", "dim_player"),
            aliases=("player season", "season stats", "player profile"),
            metrics=("total_pts", "avg_pts", "avg_ast"),
            route="player_season_complete",
            sql_template=(
                "SELECT s.player_name, s.season_year, s.total_pts, s.avg_pts, s.avg_ast "
                "FROM analytics_player_season_complete s "
                "ORDER BY s.total_pts DESC"
            ),
            patterns=_compile_patterns(
                (r"player\s+season", r"season\s+stats", r"player\s+profile")
            ),
        ),
        CatalogEntry(
            name="player game log",
            description="Per-game player box scores.",
            tables=("analytics_player_game_complete", "dim_player", "dim_game"),
            aliases=("game log", "recent games", "last game"),
            metrics=("pts", "reb", "ast", "game_date"),
            route="player_game_log",
            sql_template=(
                "SELECT g.game_date, s.player_name, s.pts, s.reb, s.ast "
                "FROM analytics_player_game_complete s "
                "JOIN dim_game g ON s.game_id = g.game_id "
                "ORDER BY g.game_date DESC"
            ),
            patterns=_compile_patterns((r"game\s+log", r"recent\s+games?", r"last\s+game")),
        ),
        CatalogEntry(
            name="clutch performance",
            description="Clutch-time player performance.",
            tables=("analytics_clutch_performance", "dim_player"),
            aliases=("clutch", "clutch stats", "clutch performance"),
            metrics=("pts", "fg_pct", "clutch_window"),
            route="clutch_performance",
            sql_template=(
                "SELECT c.player_name, c.season_year, c.clutch_window, c.pts, c.fg_pct "
                "FROM analytics_clutch_performance c "
                "ORDER BY c.pts DESC"
            ),
            patterns=_compile_patterns(
                (r"clutch\s+stats?", r"clutch\s+performance", r"\bclutch\b")
            ),
        ),
        CatalogEntry(
            name="player matchups",
            description="Player-vs-player matchup stats.",
            tables=("analytics_player_matchup", "dim_player"),
            aliases=("matchups", "player matchup", "vs player"),
            metrics=("matchup_min", "player_pts", "fg_pct"),
            route="player_matchups",
            sql_template=(
                "SELECT m.player_name, m.vs_player_name, m.season_year, "
                "m.matchup_min, m.player_pts "
                "FROM analytics_player_matchup m "
                "ORDER BY m.player_pts DESC"
            ),
            patterns=_compile_patterns((r"player\s+matchups?", r"vs\s+player")),
        ),
        CatalogEntry(
            name="franchise history",
            description="Franchise win totals and titles.",
            tables=("agg_team_franchise", "dim_team"),
            aliases=("franchise", "franchise history", "championships"),
            metrics=("wins", "losses", "league_titles"),
            route="franchise_history",
            sql_template=(
                "SELECT t.full_name, f.wins, f.losses, f.league_titles, f.computed_win_pct "
                "FROM agg_team_franchise f "
                "JOIN dim_team t ON f.team_id = t.team_id "
                "ORDER BY f.league_titles DESC, f.wins DESC"
            ),
            patterns=_compile_patterns(
                (r"franchise\s+history", r"\bfranchise\b", r"championships?")
            ),
        ),
        CatalogEntry(
            name="team game log",
            description="Per-game team box scores from analytics_team_game_complete.",
            tables=("analytics_team_game_complete", "dim_team"),
            aliases=("team game log", "team recent games", "team last game"),
            metrics=("pts", "reb", "ast", "game_date"),
            route="team_game_log",
            sql_template=(
                "SELECT s.game_date, s.team_name, s.pts, s.reb, s.ast "
                "FROM analytics_team_game_complete s "
                "ORDER BY s.game_date DESC"
            ),
            patterns=_compile_patterns(
                (r"team\s+game\s+log", r"team\s+recent\s+games?", r"team\s+last\s+game")
            ),
        ),
        CatalogEntry(
            name="player splits",
            description="Player general splits with season baselines.",
            tables=("analytics_player_general_splits", "dim_player"),
            aliases=("player splits", "home away splits", "split stats"),
            metrics=("split_type", "pts", "reb", "ast"),
            route="player_splits",
            sql_template=(
                "SELECT s.player_name, s.season_year, s.split_type, s.group_value, "
                "s.pts, s.reb, s.ast "
                "FROM analytics_player_general_splits s "
                "ORDER BY s.season_year DESC, s.pts DESC"
            ),
            patterns=_compile_patterns(
                (r"player\s+splits?", r"home[\s-]away\s+splits?", r"split\s+stats")
            ),
        ),
        CatalogEntry(
            name="team splits",
            description="Team general splits with season baselines.",
            tables=("analytics_team_general_splits", "dim_team"),
            aliases=("team splits", "team home away", "team split stats"),
            metrics=("split_type", "pts", "reb", "ast"),
            route="team_splits",
            sql_template=(
                "SELECT s.team_name, s.season_year, s.split_type, s.group_value, "
                "s.pts, s.reb, s.ast "
                "FROM analytics_team_general_splits s "
                "ORDER BY s.season_year DESC, s.pts DESC"
            ),
            patterns=_compile_patterns((r"team\s+splits?", r"team\s+home[\s-]away")),
        ),
        CatalogEntry(
            name="player impact",
            description="Player on/off impact and net rating differentials.",
            tables=("analytics_player_impact", "dim_player"),
            aliases=("player impact", "on off", "net rating diff"),
            metrics=("net_rating_diff", "on_net_rating", "off_net_rating"),
            route="player_impact",
            sql_template=(
                "SELECT s.player_name, s.season_year, s.on_net_rating, s.off_net_rating, "
                "s.net_rating_diff "
                "FROM analytics_player_impact s "
                "ORDER BY s.net_rating_diff DESC"
            ),
            patterns=_compile_patterns(
                (r"player\s+impact", r"on(?:\s|/|-)off", r"net\s+rating\s+diff")
            ),
        ),
        CatalogEntry(
            name="league benchmarks",
            description="League-wide season scoring and efficiency benchmarks.",
            tables=("analytics_league_benchmarks",),
            aliases=("league benchmarks", "league averages", "league stats"),
            metrics=("league_avg_ppg", "league_avg_rpg", "league_avg_apg"),
            route="league_benchmarks",
            sql_template=(
                "SELECT season_year, season_type, league_avg_ppg, league_avg_rpg, "
                "league_avg_apg, league_avg_fg_pct "
                "FROM analytics_league_benchmarks "
                "ORDER BY season_year DESC"
            ),
            patterns=_compile_patterns(
                (r"league\s+benchmarks?", r"league\s+averages?", r"league\s+stats")
            ),
        ),
        CatalogEntry(
            name="game summary",
            description="Game-level summary with scores and matchup context.",
            tables=("analytics_game_summary", "dim_game"),
            aliases=("game summary", "final score", "box score summary"),
            metrics=("pts_home", "pts_away", "matchup"),
            route="game_summary",
            sql_template=(
                "SELECT game_date, season_year, matchup, pts_home, pts_away "
                "FROM analytics_game_summary "
                "ORDER BY game_date DESC"
            ),
            patterns=_compile_patterns(
                (r"game\s+summary", r"final\s+score", r"box\s+score\s+summary")
            ),
        ),
        CatalogEntry(
            name="shooting efficiency",
            description="Player shooting efficiency by zone from analytics_shooting_efficiency.",
            tables=("analytics_shooting_efficiency", "dim_player"),
            aliases=("shooting efficiency", "shot zones", "zone shooting"),
            metrics=("shot_zone_basic", "fg_pct", "league_avg_fg_pct"),
            route="shooting_efficiency",
            sql_template=(
                "SELECT s.player_name, s.shot_zone_basic, s.shot_made_flag, "
                "s.league_avg_fga, "
                "s.league_avg_fg_pct "
                "FROM analytics_shooting_efficiency s "
                "ORDER BY s.league_avg_fga DESC"
            ),
            patterns=_compile_patterns(
                (r"shooting\s+efficiency", r"shot\s+zones?", r"zone\s+shooting")
            ),
        ),
        CatalogEntry(
            name="team roster",
            description="Player-team-season roster bridge.",
            tables=("bridge_player_team_season", "dim_player", "dim_team"),
            aliases=("roster", "team roster", "who played for"),
            metrics=("season_year", "player_id", "team_id"),
            route="team_roster",
            sql_template=(
                "SELECT b.season_year, p.full_name, t.full_name AS team_name "
                "FROM bridge_player_team_season b "
                "JOIN dim_player p ON b.player_id = p.player_id AND p.is_current = TRUE "
                "JOIN dim_team t ON b.team_id = t.team_id "
                "ORDER BY b.season_year DESC"
            ),
            patterns=_compile_patterns((r"\broster\b", r"team\s+roster", r"who\s+played\s+for")),
            caveats=("dim_player is SCD2; use current rows when asking for present-day names.",),
        ),
        CatalogEntry(
            name="team box score",
            description="Team-level traditional box score lines.",
            tables=("fact_box_score_team", "dim_team"),
            aliases=("team box score", "team box", "team game stats"),
            metrics=("pts", "reb", "ast"),
            route="team_box_score",
            sql_template=(
                "SELECT b.game_id, t.full_name, b.pts, b.reb, b.ast "
                "FROM fact_box_score_team b "
                "JOIN dim_team t ON b.team_id = t.team_id "
                "ORDER BY b.game_id DESC"
            ),
            patterns=_compile_patterns((r"team\s+box\s+score", r"team\s+box")),
        ),
        CatalogEntry(
            name="player box score",
            description="Player-level traditional game box scores.",
            tables=("fact_player_game_traditional", "dim_player"),
            aliases=("player box score", "player box", "player game stats"),
            metrics=("pts", "reb", "ast"),
            route="player_box_score",
            sql_template=(
                "SELECT b.game_id, p.full_name, b.pts, b.reb, b.ast "
                "FROM fact_player_game_traditional b "
                "JOIN dim_player p ON b.player_id = p.player_id AND p.is_current = TRUE "
                "ORDER BY b.game_id DESC"
            ),
            patterns=_compile_patterns((r"player\s+box\s+score", r"player\s+box")),
            caveats=("dim_player is SCD2; use current rows when asking for present-day names.",),
        ),
    )


def default_agent_catalog_export_path() -> Path:
    return _EXPORT_JSON


def load_agent_catalog_export(path: Path | None = None) -> dict[str, Any]:
    export_path = path or default_agent_catalog_export_path()
    if not export_path.exists():
        return {"version": 1, "table_count": 0, "tables": []}
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"version": 1, "table_count": 0, "tables": []}
    return payload


def export_table_index(export: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    payload = export or load_agent_catalog_export()
    tables = payload.get("tables", [])
    if not isinstance(tables, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for item in tables:
        if isinstance(item, dict) and item.get("table"):
            indexed[str(item["table"])] = item
    return indexed


def load_catalog(path: Path | None = None) -> SemanticCatalog:
    entries = {entry.route: entry for entry in _builtin_entries() if entry.route}
    catalog_path = path or _DEFAULT_JSON
    if catalog_path.exists():
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        for item in payload.get("entries", []):
            if not isinstance(item, dict):
                continue
            entry = _entry_from_mapping(item)
            if entry.route:
                base = entries.get(entry.route)
                if base is None:
                    entries[entry.route] = entry
                    continue
                entries[entry.route] = CatalogEntry(
                    name=entry.name or base.name,
                    description=entry.description or base.description,
                    tables=entry.tables or base.tables,
                    aliases=entry.aliases or base.aliases,
                    metrics=entry.metrics or base.metrics,
                    caveats=entry.caveats or base.caveats,
                    route=entry.route,
                    sql_template=entry.sql_template or base.sql_template,
                    patterns=entry.patterns or base.patterns,
                )
    return SemanticCatalog(entries=tuple(entries.values()))


def default_catalog() -> SemanticCatalog:
    return load_catalog()
