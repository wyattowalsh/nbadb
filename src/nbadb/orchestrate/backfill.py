from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import duckdb

from nbadb.core.types import SeasonType
from nbadb.orchestrate.planning import PATTERN_PRIORITY, ExtractionPlanItem
from nbadb.orchestrate.staging_map import (
    STAGING_MAP,
    StagingEntry,
)

if TYPE_CHECKING:
    from nbadb.orchestrate.journal import PipelineJournal


# ── data classes ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GapReport:
    """Summary of missing extractions for one endpoint×season."""

    endpoint: str
    season: str | None
    pattern: str
    expected: int | None  # None = can't determine without API calls
    actual: int
    missing: int | None  # None when expected is unknown
    min_season: int | None


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    """Full data completeness assessment.

    ``by_season`` is only populated for season-parametrized patterns.
    Non-season patterns (game, static, date, player, team, cross-product)
    appear only in ``by_endpoint`` under the ``"_all"`` key.
    """

    gaps: list[GapReport]
    summary: dict[str, int] = field(default_factory=dict)
    by_season: dict[str, dict[str, int]] = field(default_factory=dict)
    by_endpoint: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    """A scoped extraction plan ready for execution."""

    items: list[ExtractionPlanItem]
    total_tasks: int
    seasons: list[str]
    endpoints: list[str]
    patterns: list[str]
    dry_run_summary: str


# ── planner ──────────────────────────────────────────────────────


class BackfillPlanner:
    """Analyzes journal + staging to detect gaps and build targeted plans.

    All gap detection is done via DuckDB queries — no API calls.
    """

    DEFAULT_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        journal: PipelineJournal,
    ) -> None:
        self._conn = conn
        self._journal = journal

    # ── gap detection ────────────────────────────────────────────

    def detect_gaps(
        self,
        *,
        seasons: list[str] | None = None,
        endpoints: list[str] | None = None,
        patterns: list[str] | None = None,
        season_types: list[str] | None = None,
    ) -> CompletenessReport:
        """Analyze journal to find missing extractions.

        Uses DuckDB queries only — no API calls.  When staging tables
        don't exist, expected counts are reported as ``None``.
        """
        if season_types is None:
            season_types = list(self.DEFAULT_SEASON_TYPES)

        done_by_ep_season_type = self._journal.count_done_by_endpoint_season_type()
        done_map: dict[tuple[str, str | None, str | None], int] = {}
        for ep, season, season_type, count in done_by_ep_season_type:
            done_map[(ep, season, season_type)] = count

        # Count done entries for endpoints with no season param
        ep_status = self._journal.count_by_endpoint_and_status()
        done_total_by_ep: dict[str, int] = {}
        for ep, status, count in ep_status:
            if status == "done":
                done_total_by_ep[ep] = done_total_by_ep.get(ep, 0) + count

        all_gaps: list[GapReport] = []

        for entry in self._unique_entries(endpoints=endpoints, patterns=patterns):
            entry_gaps = self._detect_entry_gaps(
                entry,
                done_map=done_map,
                done_total_by_ep=done_total_by_ep,
                seasons=seasons,
                season_types=season_types,
            )
            all_gaps.extend(entry_gaps)

        return self._build_completeness_report(all_gaps)

    def _unique_entries(
        self,
        *,
        endpoints: list[str] | None = None,
        patterns: list[str] | None = None,
    ) -> list[StagingEntry]:
        """Deduplicated entries filtered by endpoint/pattern."""
        seen: set[tuple[str, str]] = set()
        result: list[StagingEntry] = []
        for entry in self._filter_entries(endpoints=endpoints, patterns=patterns):
            key = (entry.endpoint_name, entry.param_pattern)
            if key not in seen:
                seen.add(key)
                result.append(entry)
        return result

    def _detect_entry_gaps(
        self,
        entry: StagingEntry,
        *,
        done_map: dict[tuple[str, str | None, str | None], int],
        done_total_by_ep: dict[str, int],
        seasons: list[str] | None,
        season_types: list[str],
    ) -> list[GapReport]:
        """Detect gaps for a single staging entry."""
        pattern = entry.param_pattern

        if pattern == "static":
            return self._gaps_static(entry, done_total_by_ep)
        if pattern == "season":
            return self._gaps_season(entry, done_map, seasons, season_types)
        if pattern == "game":
            return self._gaps_game(entry, done_total_by_ep, seasons)
        if pattern == "player":
            return self._gaps_entity(entry, done_total_by_ep, "person_id", "stg_common_all_players")
        if pattern == "team":
            return self._gaps_entity(entry, done_total_by_ep, "team_id", "stg_common_team_years")
        if pattern == "date":
            return self._gaps_date(entry, done_total_by_ep, seasons)
        if pattern in ("player_season", "team_season", "player_team_season"):
            return self._gaps_cross_product(
                entry,
                done_map,
                done_total_by_ep,
                seasons,
                season_types,
            )

        return []

    def _gaps_static(
        self,
        entry: StagingEntry,
        done_total_by_ep: dict[str, int],
    ) -> list[GapReport]:
        actual = done_total_by_ep.get(entry.endpoint_name, 0)
        expected = 1
        if actual >= expected:
            return []
        return [
            GapReport(
                endpoint=entry.endpoint_name,
                season=None,
                pattern="static",
                expected=expected,
                actual=actual,
                missing=expected - actual,
                min_season=entry.min_season,
            )
        ]

    def _gaps_season(
        self,
        entry: StagingEntry,
        done_map: dict[tuple[str, str | None, str | None], int],
        seasons: list[str] | None,
        season_types: list[str],
    ) -> list[GapReport]:
        from nbadb.orchestrate.seasons import season_range

        target_seasons = seasons if seasons is not None else season_range()
        gaps: list[GapReport] = []

        for season in target_seasons:
            # Respect min_season
            try:
                season_year = int(season[:4])
            except (ValueError, IndexError):
                continue

            if entry.min_season is not None and season_year < entry.min_season:
                continue

            target_season_types = self._target_season_types_for_entry(entry, season_types)
            if target_season_types:
                expected = len(target_season_types)
                actual = sum(
                    done_map.get((entry.endpoint_name, season, season_type), 0)
                    for season_type in target_season_types
                )
            else:
                expected = 1
                actual = done_map.get((entry.endpoint_name, season, None), 0)
            if actual < expected:
                gaps.append(
                    GapReport(
                        endpoint=entry.endpoint_name,
                        season=season,
                        pattern="season",
                        expected=expected,
                        actual=actual,
                        missing=expected - actual,
                        min_season=entry.min_season,
                    )
                )

        return gaps

    def _gaps_game(
        self,
        entry: StagingEntry,
        done_total_by_ep: dict[str, int],
        seasons: list[str] | None,
    ) -> list[GapReport]:
        expected = self._count_from_table("stg_league_game_log", "game_id", seasons=seasons)
        actual = done_total_by_ep.get(entry.endpoint_name, 0)

        if expected is not None and actual >= expected:
            return []

        return [
            GapReport(
                endpoint=entry.endpoint_name,
                season=None,
                pattern="game",
                expected=expected,
                actual=actual,
                missing=(expected - actual) if expected is not None else None,
                min_season=entry.min_season,
            )
        ]

    def _gaps_entity(
        self,
        entry: StagingEntry,
        done_total_by_ep: dict[str, int],
        id_col: str,
        ref_table: str,
    ) -> list[GapReport]:
        expected = self._count_from_table(ref_table, id_col)
        actual = done_total_by_ep.get(entry.endpoint_name, 0)

        if expected is not None and actual >= expected:
            return []

        return [
            GapReport(
                endpoint=entry.endpoint_name,
                season=None,
                pattern=entry.param_pattern,
                expected=expected,
                actual=actual,
                missing=(expected - actual) if expected is not None else None,
                min_season=entry.min_season,
            )
        ]

    def _gaps_date(
        self,
        entry: StagingEntry,
        done_total_by_ep: dict[str, int],
        seasons: list[str] | None,
    ) -> list[GapReport]:
        expected = self._count_from_table("stg_league_game_log", "game_date", seasons=seasons)
        actual = done_total_by_ep.get(entry.endpoint_name, 0)

        if expected is not None and actual >= expected:
            return []

        return [
            GapReport(
                endpoint=entry.endpoint_name,
                season=None,
                pattern="date",
                expected=expected,
                actual=actual,
                missing=(expected - actual) if expected is not None else None,
                min_season=entry.min_season,
            )
        ]

    def _gaps_cross_product(
        self,
        entry: StagingEntry,
        done_map: dict[tuple[str, str | None, str | None], int],
        done_total_by_ep: dict[str, int],
        seasons: list[str] | None,
        season_types: list[str],
    ) -> list[GapReport]:
        """Detect gaps for *_season pattern types.

        Expected = entity_count * season_count.  Since we can't cheaply
        determine per-season expected counts for cross-product patterns,
        we report a single aggregate gap.
        """
        if (
            entry.param_pattern == "player_team_season"
            and entry.season_type_capability == "supported"
            and entry.supported_season_types
        ):
            season_col = self._player_team_season_season_column()
            if season_col is not None:
                target_seasons = seasons or self._distinct_values(
                    "stg_common_all_players",
                    season_col,
                )
                gaps: list[GapReport] = []
                for season in target_seasons:
                    target_season_types = self._target_season_types_for_entry(entry, season_types)
                    expected_pairs = self._count_player_team_season_pairs(season)
                    if expected_pairs is None:
                        return self._unknown_cross_product_gap(entry, done_total_by_ep)
                    expected = expected_pairs * max(len(target_season_types), 1)
                    if target_season_types:
                        actual = sum(
                            done_map.get((entry.endpoint_name, season, season_type), 0)
                            for season_type in target_season_types
                        )
                    else:
                        actual = done_map.get((entry.endpoint_name, season, None), 0)
                    if actual < expected:
                        gaps.append(
                            GapReport(
                                endpoint=entry.endpoint_name,
                                season=season,
                                pattern=entry.param_pattern,
                                expected=expected,
                                actual=actual,
                                missing=expected - actual,
                                min_season=entry.min_season,
                            )
                        )
                if gaps:
                    return gaps
        return self._unknown_cross_product_gap(entry, done_total_by_ep)

    @staticmethod
    def _unknown_cross_product_gap(
        entry: StagingEntry,
        done_total_by_ep: dict[str, int],
    ) -> list[GapReport]:
        actual = done_total_by_ep.get(entry.endpoint_name, 0)
        return [
            GapReport(
                endpoint=entry.endpoint_name,
                season=None,
                pattern=entry.param_pattern,
                expected=None,
                actual=actual,
                missing=None,
                min_season=entry.min_season,
            )
        ]

    def _count_from_table(
        self,
        table: str,
        id_col: str,
        *,
        seasons: list[str] | None = None,
    ) -> int | None:
        """Count distinct values of ``id_col`` from a DuckDB table.

        Returns None if the table doesn't exist.
        """
        try:
            if seasons and "season_id" in self._get_columns(table):
                placeholders = ", ".join(f"${i + 1}" for i in range(len(seasons)))
                row = self._conn.execute(
                    f"SELECT COUNT(DISTINCT {id_col}) FROM {table} "
                    f"WHERE season_id IN ({placeholders})",
                    seasons,
                ).fetchone()
            else:
                row = self._conn.execute(f"SELECT COUNT(DISTINCT {id_col}) FROM {table}").fetchone()
            return row[0] if row else None
        except duckdb.CatalogException:
            return None

    def _get_columns(self, table: str) -> set[str]:
        """Return column names for a DuckDB table, or empty set if missing."""
        try:
            rows = self._conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = $1 AND table_schema = 'main'",
                [table],
            ).fetchall()
            return {r[0] for r in rows}
        except duckdb.CatalogException:
            return set()

    def _distinct_values(self, table: str, column: str) -> list[str]:
        try:
            rows = self._conn.execute(
                f"SELECT DISTINCT {column} FROM {table} "
                f"WHERE {column} IS NOT NULL ORDER BY {column}"
            ).fetchall()
        except duckdb.CatalogException:
            return []
        return [str(row[0]) for row in rows if row and row[0] is not None]

    def _player_team_season_season_column(self) -> str | None:
        columns = self._get_columns("stg_common_all_players")
        if "season" in columns:
            return "season"
        if "season_id" in columns:
            return "season_id"
        return None

    def _count_player_team_season_pairs(self, season: str) -> int | None:
        season_col = self._player_team_season_season_column()
        if season_col is None:
            return None
        columns = self._get_columns("stg_common_all_players")
        if not {"person_id", "team_id"} <= columns:
            return None
        try:
            row = self._conn.execute(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT person_id, team_id
                    FROM stg_common_all_players
                    WHERE {season_col} = $1
                      AND person_id IS NOT NULL
                      AND team_id IS NOT NULL
                      AND team_id > 0
                )
                """,
                [season],
            ).fetchone()
        except duckdb.CatalogException:
            return None
        return int(row[0]) if row else None

    @staticmethod
    def _supports_season_type(entries: list[StagingEntry]) -> bool:
        return bool(entries) and all(
            entry.season_type_capability == "supported" and bool(entry.supported_season_types)
            for entry in entries
        )

    @staticmethod
    def _resolved_season_types(
        entry: StagingEntry,
        requested_season_types: list[str] | None,
    ) -> list[str]:
        if entry.season_type_capability != "supported":
            return []

        supported_season_types = [str(value) for value in (entry.supported_season_types or ())]
        if not supported_season_types:
            return []

        requested = requested_season_types or supported_season_types
        return [season_type for season_type in supported_season_types if season_type in requested]

    @classmethod
    def _target_season_types_for_entry(
        cls,
        entry: StagingEntry,
        requested_season_types: list[str] | None,
    ) -> list[str]:
        return cls._resolved_season_types(entry, requested_season_types)

    @staticmethod
    def _historical_start_year(entry: StagingEntry) -> int:
        return entry.min_season or 1946

    @classmethod
    def _season_entry_groups(
        cls,
        entries: list[StagingEntry],
        requested_season_types: list[str] | None,
    ) -> list[tuple[list[StagingEntry], int, list[str]]]:
        grouped: dict[tuple[int, tuple[str, ...]], list[StagingEntry]] = {}
        for entry in entries:
            season_types = cls._resolved_season_types(entry, requested_season_types)
            if entry.season_type_capability == "supported" and not season_types:
                continue
            group_key = (cls._historical_start_year(entry), tuple(season_types))
            grouped.setdefault(group_key, []).append(entry)

        return [
            (grouped[group_key], group_key[0], list(group_key[1])) for group_key in sorted(grouped)
        ]

    @staticmethod
    def _filter_seasons_for_start_year(
        seasons: list[str],
        start_year: int,
    ) -> list[str]:
        filtered: list[str] = []
        for season in seasons:
            try:
                season_year = int(season[:4])
            except (ValueError, IndexError):
                continue
            if season_year >= start_year:
                filtered.append(season)
        return filtered

    @staticmethod
    def _build_completeness_report(gaps: list[GapReport]) -> CompletenessReport:
        """Aggregate gap reports into a CompletenessReport."""
        summary: dict[str, int] = {}
        by_season: dict[str, dict[str, int]] = {}
        by_endpoint: dict[str, dict[str, int]] = {}

        for gap in gaps:
            if gap.missing is not None:
                summary[gap.pattern] = summary.get(gap.pattern, 0) + gap.missing
            else:
                key = f"{gap.pattern}_unknown"
                summary[key] = summary.get(key, 0) + 1

            missing = gap.missing if gap.missing is not None else 0
            if gap.season:
                by_season.setdefault(gap.season, {})[gap.endpoint] = missing
                by_endpoint.setdefault(gap.endpoint, {})[gap.season] = missing
            else:
                by_endpoint.setdefault(gap.endpoint, {})["_all"] = missing

        return CompletenessReport(
            gaps=gaps,
            summary=summary,
            by_season=by_season,
            by_endpoint=by_endpoint,
        )

    # ── plan building ────────────────────────────────────────────

    def build_plan(
        self,
        *,
        seasons: list[str] | None = None,
        endpoints: list[str] | None = None,
        patterns: list[str] | None = None,
        force: bool = False,
        season_types: list[str] | None = None,
    ) -> BackfillPlan:
        """Build a targeted extraction plan.

        When ``force=True``, resets matching journal entries before
        planning so they become eligible for extraction.
        """
        from nbadb.orchestrate.seasons import season_range

        if season_types is None:
            season_types = list(self.DEFAULT_SEASON_TYPES)

        effective_seasons = seasons if seasons is not None else season_range()

        if force:
            self.force_reset(seasons=seasons, endpoints=endpoints, patterns=patterns)

        # Filter STAGING_MAP entries
        filtered_entries = self._filter_entries(endpoints=endpoints, patterns=patterns)

        # Group entries by pattern
        entries_by_pattern: dict[str, list[StagingEntry]] = {}
        for entry in filtered_entries:
            entries_by_pattern.setdefault(entry.param_pattern, []).append(entry)

        plan_items: list[ExtractionPlanItem] = []

        for pattern, entries in entries_by_pattern.items():
            priority = PATTERN_PRIORITY.get(pattern, 99)
            if pattern == "season":
                for grouped_entries, start_year, grouped_season_types in self._season_entry_groups(
                    entries, season_types
                ):
                    grouped_seasons = self._filter_seasons_for_start_year(
                        effective_seasons, start_year
                    )
                    params = self._build_params_for_pattern(
                        pattern,
                        grouped_entries,
                        grouped_seasons,
                        grouped_season_types,
                    )
                    if not params:
                        continue
                    label = "backfill:season"
                    if grouped_season_types:
                        label = f"{label}[{'/'.join(grouped_season_types)}]"
                    plan_items.append(
                        ExtractionPlanItem(
                            label=label,
                            pattern=pattern,
                            entries=grouped_entries,
                            params=params,
                            priority=priority,
                        )
                    )
                continue

            params = self._build_params_for_pattern(
                pattern,
                entries,
                effective_seasons,
                season_types,
            )
            if not params:
                continue
            plan_items.append(
                ExtractionPlanItem(
                    label=f"backfill:{pattern}",
                    pattern=pattern,
                    entries=entries,
                    params=params,
                    priority=priority,
                )
            )

        total_tasks = sum(item.task_count for item in plan_items)
        used_patterns = sorted({item.pattern for item in plan_items})
        used_endpoints = sorted({e.endpoint_name for item in plan_items for e in item.entries})

        summary_lines = [
            f"Backfill plan: {total_tasks:,} tasks across {len(plan_items)} pattern groups",
            f"  Seasons: {len(effective_seasons)} ({effective_seasons[0]}..{effective_seasons[-1]})"
            if effective_seasons
            else "  Seasons: none",
            f"  Season types: {', '.join(season_types)}",
            f"  Patterns: {', '.join(used_patterns)}",
            f"  Endpoints: {len(used_endpoints)}",
            f"  Force: {force}",
            "",
        ]
        for item in plan_items:
            summary_lines.append(
                f"  [{item.pattern}] {len(item.entries)} endpoints × "
                f"{len(item.params)} param sets = {item.task_count:,} tasks "
                f"(priority {item.priority})"
            )

        return BackfillPlan(
            items=plan_items,
            total_tasks=total_tasks,
            seasons=effective_seasons,
            endpoints=used_endpoints,
            patterns=used_patterns,
            dry_run_summary="\n".join(summary_lines),
        )

    def force_reset(
        self,
        *,
        seasons: list[str] | None,
        endpoints: list[str] | None,
        patterns: list[str] | None,
    ) -> None:
        """Reset journal entries matching the backfill scope."""
        target_endpoints = self._resolve_endpoint_names(endpoints=endpoints, patterns=patterns)
        if not target_endpoints:
            return
        if seasons:
            for season in seasons:
                self._journal.reset_entries(endpoint=target_endpoints, season_like=season)
        else:
            self._journal.reset_entries(endpoint=target_endpoints)

    def _resolve_endpoint_names(
        self,
        *,
        endpoints: list[str] | None,
        patterns: list[str] | None,
    ) -> list[str]:
        """Resolve user filters into a list of endpoint names."""
        if endpoints:
            return endpoints
        entries = self._filter_entries(endpoints=endpoints, patterns=patterns)
        return sorted({e.endpoint_name for e in entries})

    @staticmethod
    def _filter_entries(
        *,
        endpoints: list[str] | None = None,
        patterns: list[str] | None = None,
    ) -> list[StagingEntry]:
        """Filter STAGING_MAP by endpoint and/or pattern."""
        result: list[StagingEntry] = []
        for entry in STAGING_MAP:
            if endpoints and entry.endpoint_name not in endpoints:
                continue
            if patterns and entry.param_pattern not in patterns:
                continue
            result.append(entry)
        return result

    @classmethod
    def _build_params_for_pattern(
        cls,
        pattern: str,
        entries: list[StagingEntry],
        seasons: list[str],
        season_types: list[str],
    ) -> list[dict[str, int | str]]:
        """Build param dicts for a pattern type.

        For entity-dependent patterns (game, player, team, *_season),
        returns empty — discovery must happen at run time.
        Params are placeholders that the orchestrator will replace
        with discovered entity IDs.
        """
        if pattern == "static":
            return [{}]
        if pattern == "season":
            if cls._supports_season_type(entries):
                return [
                    {"season": season, "season_type": st}
                    for season in seasons
                    for st in season_types
                ]
            return [{"season": season} for season in seasons]
        # Entity-dependent patterns need runtime discovery — return
        # a sentinel so the caller knows params must be resolved later
        return []
