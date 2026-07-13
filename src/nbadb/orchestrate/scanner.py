"""Database scanner for identifying missing data, gaps, and quality issues.

All queries are read-only. The DuckDB connection should be opened with
``read_only=True``.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

import duckdb
from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.transform.base import BaseTransformer


def validate_full_publication_checkpoint_report(
    path: Path,
    *,
    manifest_path: Path,
    checkpoint_dir: Path,
    chain_id: str,
    source_sha: str,
) -> dict:
    """Validate and bind the terminal extraction proof required by a full scan."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Full-publication checkpoint report must be a regular file: {path}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Full-publication checkpoint report is not valid JSON") from exc
    if not isinstance(report, dict):
        raise ValueError("Full-publication checkpoint report must be an object")

    expected_source_sha = source_sha.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", expected_source_sha) is None:
        raise ValueError("Full-publication expected source_sha is invalid")
    reported_source_sha = str(report.get("source_sha") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", reported_source_sha) is None:
        raise ValueError("Full-publication checkpoint source_sha is invalid")
    if reported_source_sha != expected_source_sha:
        raise ValueError(
            "Full-publication checkpoint source_sha does not match the expected source commit"
        )
    for field_name in ("coverage_fingerprint", "database_sha256"):
        value = str(report.get(field_name) or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"Full-publication checkpoint {field_name} is invalid")

    run_id = str(report.get("run_id") or "").strip()
    if re.fullmatch(r"[1-9][0-9]*", run_id) is None:
        raise ValueError("Full-publication checkpoint run_id is invalid")
    included_run_ids = report.get("included_run_ids")
    if (
        not isinstance(included_run_ids, list)
        or not included_run_ids
        or len(set(map(str, included_run_ids))) != len(included_run_ids)
        or any(re.fullmatch(r"[1-9][0-9]*", str(value)) is None for value in included_run_ids)
        or run_id not in {str(value) for value in included_run_ids}
    ):
        raise ValueError("Full-publication checkpoint included_run_ids are invalid")

    included_lane_ids = report.get("included_lane_ids")
    if (
        not isinstance(included_lane_ids, list)
        or not included_lane_ids
        or any(not isinstance(value, str) or not value for value in included_lane_ids)
        or len(set(included_lane_ids)) != len(included_lane_ids)
    ):
        raise ValueError("Full-publication checkpoint included_lane_ids are invalid")
    lane_hashes = report.get("included_lane_coverage_hashes")
    if not isinstance(lane_hashes, dict) or set(lane_hashes) != set(included_lane_ids):
        raise ValueError("Full-publication checkpoint lane coverage inventory is incomplete")
    if any(
        re.fullmatch(r"[0-9a-f]{64}", str(value).lower()) is None for value in lane_hashes.values()
    ):
        raise ValueError("Full-publication checkpoint lane coverage hash is invalid")

    complete_count = report.get("complete_lane_count")
    blocked_count = report.get("contract_blocked_lane_count")
    manifest_count = report.get("manifest_lane_count")
    if any(type(value) is not int or value < 0 for value in (complete_count, blocked_count)):
        raise ValueError("Full-publication checkpoint lane counts are invalid")
    if type(manifest_count) is not int or manifest_count <= 0:
        raise ValueError("Full-publication checkpoint manifest_lane_count is invalid")
    if complete_count != len(included_lane_ids) or complete_count <= 0:
        raise ValueError("Full-publication checkpoint complete lane inventory is inconsistent")
    if manifest_count != complete_count + blocked_count:
        raise ValueError("Full-publication checkpoint does not account for every manifest lane")

    if report.get("terminal_ready") is not True or report.get("active_lane_count") != 0:
        raise ValueError("Full-publication checkpoint is not terminal-ready")
    empty_fields = (
        "missing_lane_ids",
        "skipped_complete_lane_ids",
        "current_lane_attestation_failures",
        "workload_contract_errors",
    )
    for field_name in empty_fields:
        if report.get(field_name) not in ([], {}):
            raise ValueError(f"Full-publication checkpoint {field_name} is not empty")
    if report.get("skipped_lane_count") != 0:
        raise ValueError("Full-publication checkpoint skipped_lane_count is not zero")

    from nbadb.orchestrate.full_extraction_control import (
        _database_row_counts,
        _single_database_path,
        _validated_checkpoint_contract_blocked_evidence,
        validate_checkpoint_artifact,
    )

    blocked_rows, _blocked_digest = _validated_checkpoint_contract_blocked_evidence(report)
    if len(blocked_rows) != blocked_count:
        raise ValueError("Full-publication checkpoint blocked evidence count is inconsistent")

    verified = validate_checkpoint_artifact(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
        checkpoint_report_path=path,
        chain_id=chain_id,
        source_sha=expected_source_sha,
        pointer_prefix="latest",
    )
    exact_fields = (
        "run_id",
        "coverage_fingerprint",
        "database_sha256",
        "included_lane_ids",
        "included_run_ids",
        "included_lane_coverage_hashes",
        "contract_blocked_lane_count",
    )
    mismatches = {
        field_name: {"report": report.get(field_name), "verified": verified.get(field_name)}
        for field_name in exact_fields
        if report.get(field_name) != verified.get(field_name)
    }
    if mismatches:
        raise ValueError(
            f"Full-publication checkpoint report differs from canonical verification: {mismatches}"
        )

    checkpoint_db_path = _single_database_path(
        checkpoint_dir,
        label="Full-publication checkpoint artifact",
    )
    actual_table_row_counts, actual_journal_row_count = _database_row_counts(checkpoint_db_path)
    reported_table_row_counts = report.get("table_row_counts")
    if (
        not isinstance(reported_table_row_counts, dict)
        or any(
            not isinstance(table, str)
            or not table.startswith("stg_")
            or type(row_count) is not int
            or row_count < 0
            for table, row_count in reported_table_row_counts.items()
        )
        or reported_table_row_counts != actual_table_row_counts
    ):
        raise ValueError(
            "Full-publication checkpoint staging row inventory differs from the verified database"
        )
    if report.get("journal_row_count") != actual_journal_row_count:
        raise ValueError(
            "Full-publication checkpoint journal row count differs from the verified database"
        )
    return report


class ScanCategory(StrEnum):
    CROSS_TABLE = "cross_table"
    TEMPORAL = "temporal"
    MISSING_TABLE = "missing_table"
    DATA_QUALITY = "data_quality"


class ScanSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class ScanFinding:
    """A single issue detected by the scanner."""

    category: str
    severity: str
    table: str
    check: str
    message: str
    details: dict | None = None


@dataclass
class ScanReport:
    """Aggregated scan results."""

    findings: list[ScanFinding] = field(default_factory=list)
    tables_scanned: int = 0
    checks_run: int = 0
    duration_seconds: float = 0.0

    def filter(
        self,
        *,
        category: str | None = None,
        severity: str | None = None,
        table: str | None = None,
    ) -> list[ScanFinding]:
        results = self.findings
        if category:
            results = [f for f in results if f.category == category]
        if severity:
            results = [f for f in results if f.severity == severity]
        if table:
            results = [f for f in results if f.table == table or f.table.startswith(table)]
        return results

    def summary(self) -> dict[str, int]:
        by_sev: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
        for f in self.findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        return {
            "total": len(self.findings),
            **by_sev,
            "tables_scanned": self.tables_scanned,
            "checks_run": self.checks_run,
        }

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "duration_seconds": self.duration_seconds,
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "table": f.table,
                    "check": f.check,
                    "message": f.message,
                    "details": f.details,
                }
                for f in self.findings
            ],
        }

    # ── CI output helpers ──────────────────────────────────────

    _SEVERITY_ICONS: ClassVar[dict[str, str]] = {
        "error": ":red_circle:",
        "warning": ":yellow_circle:",
        "info": ":blue_circle:",
    }

    _CATEGORY_LABELS: ClassVar[dict[str, str]] = {
        "missing_table": "Missing / Empty Tables",
        "cross_table": "Cross-Table Gaps",
        "temporal": "Temporal Coverage",
        "data_quality": "Data Quality",
    }

    _MAX_FINDINGS_PER_CATEGORY: ClassVar[int] = 50
    _MAX_ANNOTATIONS: ClassVar[int] = 50

    def to_markdown(self) -> str:
        """Render report as GitHub-flavored markdown for step summaries."""
        s = self.summary()
        if s["error"]:
            status = f":x: **{s['error']} error(s)**"
        elif s["warning"]:
            status = f":warning: **{s['warning']} warning(s)**"
        else:
            status = ":white_check_mark: **All clear**"

        lines = [
            "## Data Scan Report",
            "",
            status,
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Checks run | {s['checks_run']} |",
            f"| Tables scanned | {s['tables_scanned']} |",
            f"| Errors | {s['error']} |",
            f"| Warnings | {s['warning']} |",
            f"| Info | {s['info']} |",
            f"| Duration | {self.duration_seconds:.1f}s |",
            "",
        ]

        if not self.findings:
            lines.append("No issues found.")
            return "\n".join(lines)

        # Group by category, render per-category tables
        by_cat: dict[str, list[ScanFinding]] = {}
        for f in self.findings:
            by_cat.setdefault(f.category, []).append(f)

        cat_order = ["missing_table", "cross_table", "temporal", "data_quality"]
        for cat in cat_order:
            cat_findings = by_cat.get(cat, [])
            if not cat_findings:
                continue
            label = self._CATEGORY_LABELS.get(cat, cat)
            lines.append(f"### {label} ({len(cat_findings)})")
            lines.append("")
            lines.append("| Severity | Table | Message |")
            lines.append("|----------|-------|---------|")

            shown = cat_findings[: self._MAX_FINDINGS_PER_CATEGORY]
            for f in shown:
                icon = self._SEVERITY_ICONS.get(f.severity, "")
                # Escape pipe chars in message for markdown table safety
                msg = f.message.replace("|", "\\|")
                lines.append(f"| {icon} {f.severity} | `{f.table}` | {msg} |")

            remaining = len(cat_findings) - len(shown)
            if remaining > 0:
                lines.append(f"| | | *... and {remaining} more* |")
            lines.append("")

        return "\n".join(lines)

    def to_github_annotations(self) -> list[str]:
        """Return ``::error::``, ``::warning::``, ``::notice::`` lines for GitHub Actions."""
        annotations: list[str] = []
        for f in self.findings:
            if f.severity == "error":
                annotations.append(f"::error::{f.message}")
            elif f.severity == "warning":
                annotations.append(f"::warning::{f.message}")
            elif f.severity == "info":
                annotations.append(f"::notice::{f.message}")
        if len(annotations) > self._MAX_ANNOTATIONS:
            total = len(annotations)
            annotations = annotations[: self._MAX_ANNOTATIONS]
            annotations.append(
                f"::notice::... and {total - self._MAX_ANNOTATIONS} more findings"
                " (see step summary)"
            )
        return annotations


class DataScanner:
    """Read-only scanner that analyzes DuckDB for missing or incomplete data.

    All queries are SELECT-only.  The connection should be opened in
    read-only mode.
    """

    # Game-level fact tables that should have entries for every game.
    _GAME_COVERAGE_TABLES: ClassVar[list[str]] = [
        "fact_box_score_team",
        "fact_play_by_play",
        "fact_game_result",
        "fact_rotation",
    ]

    # Full publication requires populated conformed dimensions. Other transform
    # outputs can legitimately contain zero rows for unsupported source scopes.
    _FULL_PUBLICATION_ANCHORS: ClassVar[frozenset[str]] = frozenset(
        {"dim_game", "dim_player", "dim_team"}
    )
    _FULL_PUBLICATION_DOMAIN_ANCHORS: ClassVar[dict[str, frozenset[str]]] = {
        "game_discovery": frozenset(
            {
                "stg_league_game_log",
                "dim_game",
                "dim_season",
                "bridge_game_team",
                "fact_game_result",
            }
        ),
        "roster": frozenset(
            {
                "stg_common_all_players",
                "stg_player_info",
                "dim_all_players",
                "dim_player",
                "bridge_player_team_season",
            }
        ),
        "teams": frozenset(
            {
                "stg_static_teams",
                "stg_team_years",
                "stg_team_details",
                "stg_team_info_common",
                "fact_static_teams",
                "dim_team",
            }
        ),
        "box_scores": frozenset(
            {
                "stg_box_score_traditional",
                "stg_box_score_traditional_team",
                "stg_line_score",
                "fact_player_game_traditional",
                "fact_box_score_team",
                "fact_team_game",
            }
        ),
        "play_by_play": frozenset({"stg_play_by_play", "fact_play_by_play"}),
        "shots": frozenset({"stg_shot_chart", "fact_shot_chart", "dim_shot_zone"}),
        "standings": frozenset({"stg_standings", "fact_standings"}),
        "draft": frozenset({"stg_draft", "fact_draft_history", "fact_draft"}),
        "gold_game": frozenset({"agg_game_totals", "analytics_game_summary"}),
        "gold_player": frozenset(
            {"agg_player_season", "agg_player_career", "analytics_player_game_complete"}
        ),
        "gold_team": frozenset({"agg_team_season", "analytics_team_season_summary"}),
        "gold_shots": frozenset({"agg_shot_zones"}),
    }
    _FULL_PUBLICATION_CARDINALITY_PAIRS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("stg_static_teams", "fact_static_teams"),
        ("stg_box_score_traditional_team", "fact_box_score_team"),
        ("stg_play_by_play", "fact_play_by_play"),
        ("stg_standings", "fact_standings"),
        ("stg_draft", "fact_draft_history"),
        ("stg_shot_chart", "fact_shot_chart"),
    )

    # Explicit referential-integrity pairs:
    # (fact_table, fk_column, dim_table, pk_column)
    _REF_INTEGRITY_CHECKS: ClassVar[list[tuple[str, str, str, str]]] = [
        ("fact_game_result", "game_id", "dim_game", "game_id"),
        ("fact_player_game_log", "player_id", "dim_player", "player_id"),
        ("fact_standings", "team_id", "dim_team", "team_id"),
    ]

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn
        self._report = ScanReport()
        self._tables_cache: list[str] | None = None
        self._columns_cache: dict[str, list[tuple[str, str]]] = {}
        self._transformers_cache: list[BaseTransformer] | None = None

    # ── public API ────────────────────────────────────────────────

    def scan(
        self,
        *,
        categories: list[str] | None = None,
        table_filter: str | None = None,
        full_publication: bool = False,
    ) -> ScanReport:
        """Run all (or selected) scan categories and return the report.

        When ``full_publication`` is true, missing or empty conformed publication
        anchors are errors. Other zero-row transform outputs retain their normal
        warning severity because they can be valid for unsupported source scopes.
        """
        start = time.monotonic()
        self._report = ScanReport()
        self._tables_cache = None
        self._columns_cache = {}
        self._transformers_cache = None

        self._assure_transformer_discovery()

        active = categories if categories else [c.value for c in ScanCategory]

        if full_publication:
            self._check_full_publication_anchors()
            self._check_full_publication_cardinality()

        if ScanCategory.MISSING_TABLE in active:
            publication_anchor_tables = self._FULL_PUBLICATION_ANCHORS | frozenset(
                table
                for candidates in self._FULL_PUBLICATION_DOMAIN_ANCHORS.values()
                for table in candidates
            )
            self._check_missing_tables(
                table_filter,
                excluded_transform_tables=(
                    publication_anchor_tables if full_publication else frozenset()
                ),
            )

        if ScanCategory.CROSS_TABLE in active:
            self._check_cross_table_gaps(table_filter)

        if ScanCategory.TEMPORAL in active:
            self._check_temporal_coverage(table_filter)

        if ScanCategory.DATA_QUALITY in active:
            self._check_data_quality(table_filter)

        self._report.duration_seconds = time.monotonic() - start
        return self._report

    # ── helpers ───────────────────────────────────────────────────

    def _get_existing_tables(self) -> list[str]:
        """Return all user tables (excluding ``_*`` pipeline tables)."""
        if self._tables_cache is not None:
            return self._tables_cache
        rows = self._conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' "
            "AND table_name NOT LIKE '\\_%' ESCAPE '\\'"
        ).fetchall()
        self._tables_cache = sorted(r[0] for r in rows)
        return self._tables_cache

    def _get_columns(
        self,
        table: str,
        *,
        category: ScanCategory,
    ) -> list[str] | None:
        """Return column names for *table* (cached)."""
        typed_columns = self._get_columns_typed(table, category=category)
        if typed_columns is None:
            return None
        return [name for name, _ in typed_columns]

    def _get_columns_typed(
        self,
        table: str,
        *,
        category: ScanCategory,
    ) -> list[tuple[str, str]] | None:
        """Return ``(column_name, data_type)`` tuples for *table* (cached)."""
        if table in self._columns_cache:
            return self._columns_cache[table]
        try:
            rows = self._conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = $1 AND table_schema = 'main' "
                "ORDER BY ordinal_position",
                [table],
            ).fetchall()
            cols = [(r[0], r[1]) for r in rows]
        except duckdb.Error as exc:
            self._add_query_error(
                category=category,
                table=table,
                check="schema_introspection",
                exc=exc,
            )
            return None
        self._columns_cache[table] = cols
        return cols

    def _row_count(self, table: str) -> int:
        row = self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return row[0] if row else 0

    _NUMERIC_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "INTEGER",
            "BIGINT",
            "FLOAT",
            "DOUBLE",
            "DECIMAL",
            "SMALLINT",
            "TINYINT",
            "HUGEINT",
        }
    )

    def _get_numeric_columns(
        self,
        table: str,
        *,
        category: ScanCategory,
    ) -> list[str] | None:
        """Return columns with numeric types, excluding ``*_id`` columns."""
        typed_columns = self._get_columns_typed(table, category=category)
        if typed_columns is None:
            return None
        return [
            name
            for name, dtype in typed_columns
            if dtype.upper() in self._NUMERIC_TYPES and not name.endswith("_id")
        ]

    def _infer_key_columns(
        self,
        table: str,
        *,
        category: ScanCategory,
    ) -> list[str] | None:
        """Infer likely primary-key columns from convention."""
        columns = self._get_columns(table, category=category)
        if columns is None:
            return None
        col_set = set(columns)
        keys: list[str] = []
        for col in ("game_id", "player_id", "team_id", "event_num"):
            if col in col_set:
                keys.append(col)
        if not keys:
            keys = [c for c in columns if c.endswith("_id")]
        return keys[:4]

    @staticmethod
    def _matches_filter(table: str, table_filter: str | None) -> bool:
        if table_filter is None:
            return True
        return table.startswith(table_filter)

    def _add(self, finding: ScanFinding) -> None:
        self._report.findings.append(finding)

    def _add_query_error(
        self,
        *,
        category: ScanCategory,
        table: str,
        check: str,
        exc: duckdb.Error,
    ) -> None:
        """Record a configured scan query failure as a hard finding."""
        logger.error("scanner: {} query failed for {}: {}", check, table, exc)
        self._add(
            ScanFinding(
                category=category,
                severity=ScanSeverity.ERROR,
                table=table,
                check=f"{check}_query_failed",
                message=f"{table}: {check} query failed: {type(exc).__name__}: {exc}",
                details={
                    "failed_check": check,
                    "error_type": type(exc).__name__,
                },
            )
        )

    def _assure_transformer_discovery(self) -> None:
        """Cache a complete runtime universe or record a hard assurance error."""
        self._report.checks_run += 1
        try:
            from nbadb.orchestrate.transformers import (
                discover_all_transformers,
                expected_transform_output_tables,
                require_complete_transformer_universe,
            )

            transformers = discover_all_transformers()
            require_complete_transformer_universe(transformers, include_live=True)
            expected_outputs = expected_transform_output_tables(include_live=True)
            invalid_coverage_tables = set(self._GAME_COVERAGE_TABLES) - expected_outputs
            if invalid_coverage_tables:
                invalid = ", ".join(sorted(invalid_coverage_tables))
                msg = f"game coverage tables are not schema-backed transform outputs: {invalid}"
                raise RuntimeError(msg)
            from nbadb.orchestrate.staging_map import STAGING_MAP

            known_publication_tables = expected_outputs | {
                entry.staging_key for entry in STAGING_MAP
            }
            configured_publication_tables = self._FULL_PUBLICATION_ANCHORS | frozenset(
                table
                for candidates in self._FULL_PUBLICATION_DOMAIN_ANCHORS.values()
                for table in candidates
            )
            invalid_publication_tables = configured_publication_tables - known_publication_tables
            if invalid_publication_tables:
                invalid = ", ".join(sorted(invalid_publication_tables))
                raise RuntimeError(f"publication anchors are not schema-backed tables: {invalid}")
        except Exception as exc:
            logger.error("scanner: transformer discovery assurance failed: {}", exc)
            self._add(
                ScanFinding(
                    category=ScanCategory.MISSING_TABLE,
                    severity=ScanSeverity.ERROR,
                    table="transform_outputs",
                    check="transformer_discovery_failed",
                    message=f"Transformer discovery assurance failed: {exc}",
                    details={
                        "error_type": type(exc).__name__,
                        "required_contract": "exact_schema_backed_output_universe",
                    },
                )
            )
            return
        self._transformers_cache = transformers

    # ── category 1: missing / empty tables ────────────────────────

    def _check_full_publication_anchors(self) -> None:
        """Require conformed dimensions and representative domain families to be populated."""
        existing = set(self._get_existing_tables())

        for table in sorted(self._FULL_PUBLICATION_ANCHORS):
            self._report.checks_run += 1
            if table not in existing:
                self._add(
                    ScanFinding(
                        category=ScanCategory.MISSING_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=table,
                        check="missing_publication_anchor",
                        message=f"Full publication anchor {table} not found in database",
                        details={"hard_nonempty_policy": "full_publication_anchor"},
                    )
                )
                continue

            self._report.tables_scanned += 1
            try:
                row_count = self._row_count(table)
            except duckdb.Error as exc:
                self._add_query_error(
                    category=ScanCategory.MISSING_TABLE,
                    table=table,
                    check="publication_anchor_nonempty",
                    exc=exc,
                )
                continue

            if row_count == 0:
                self._add(
                    ScanFinding(
                        category=ScanCategory.MISSING_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=table,
                        check="empty_publication_anchor",
                        message=f"Full publication anchor {table} exists but is empty",
                        details={
                            "row_count": 0,
                            "hard_nonempty_policy": "full_publication_anchor",
                        },
                    )
                )

        for domain, candidates in sorted(self._FULL_PUBLICATION_DOMAIN_ANCHORS.items()):
            self._report.checks_run += 1
            existing_candidates = sorted(candidates & existing)
            missing_candidates = sorted(candidates - existing)
            if missing_candidates:
                self._add(
                    ScanFinding(
                        category=ScanCategory.MISSING_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=f"publication_domain:{domain}",
                        check="missing_publication_domain",
                        message=f"Full publication domain {domain} is missing required anchors",
                        details={
                            "candidate_tables": sorted(candidates),
                            "missing_tables": missing_candidates,
                            "hard_nonempty_policy": "full_publication_domain",
                        },
                    )
                )
                continue

            row_counts: dict[str, int] = {}
            for table in existing_candidates:
                self._report.tables_scanned += 1
                try:
                    row_count = self._row_count(table)
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=ScanCategory.MISSING_TABLE,
                        table=table,
                        check="publication_domain_nonempty",
                        exc=exc,
                    )
                    continue
                row_counts[table] = row_count

            empty_candidates = sorted(
                table for table, row_count in row_counts.items() if row_count == 0
            )
            if empty_candidates:
                self._add(
                    ScanFinding(
                        category=ScanCategory.MISSING_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=f"publication_domain:{domain}",
                        check="empty_publication_domain",
                        message=f"Full publication domain {domain} has empty required anchors",
                        details={
                            "candidate_tables": sorted(candidates),
                            "existing_tables": existing_candidates,
                            "empty_tables": empty_candidates,
                            "row_counts": row_counts,
                            "hard_nonempty_policy": "full_publication_domain",
                        },
                    )
                )

    def _check_full_publication_cardinality(self) -> None:
        """Enforce declared row-preserving silver-to-gold transform contracts."""
        existing = set(self._get_existing_tables())
        for source_table, output_table in self._FULL_PUBLICATION_CARDINALITY_PAIRS:
            self._report.checks_run += 1
            if source_table not in existing or output_table not in existing:
                continue
            counts: dict[str, int] = {}
            for table in (source_table, output_table):
                try:
                    counts[table] = self._row_count(table)
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=ScanCategory.CROSS_TABLE,
                        table=table,
                        check="publication_cardinality",
                        exc=exc,
                    )
            if len(counts) == 2 and counts[source_table] != counts[output_table]:
                self._add(
                    ScanFinding(
                        category=ScanCategory.CROSS_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=output_table,
                        check="publication_cardinality_mismatch",
                        message=(
                            f"Full publication row-preserving contract failed: {source_table} "
                            f"has {counts[source_table]:,} rows, but {output_table} has "
                            f"{counts[output_table]:,}"
                        ),
                        details={
                            "source_table": source_table,
                            "output_table": output_table,
                            "source_row_count": counts[source_table],
                            "output_row_count": counts[output_table],
                        },
                    )
                )

    def _batch_row_counts(
        self,
        tables: list[str],
        *,
        category: ScanCategory,
    ) -> dict[str, int]:
        """Return ``{table: row_count}`` for *tables* in a single query."""
        if not tables:
            return {}
        parts = [f"SELECT '{t}' AS tbl, COUNT(*) AS cnt FROM \"{t}\"" for t in tables]
        try:
            rows = self._conn.execute(" UNION ALL ".join(parts)).fetchall()
            return {r[0]: r[1] for r in rows}
        except duckdb.Error:
            # Fallback to per-table counts if UNION ALL fails
            counts: dict[str, int] = {}
            for table in tables:
                try:
                    counts[table] = self._row_count(table)
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=category,
                        table=table,
                        check="row_count",
                        exc=exc,
                    )
            return counts

    def _check_missing_tables(
        self,
        table_filter: str | None,
        *,
        excluded_transform_tables: frozenset[str],
    ) -> None:
        existing = set(self._get_existing_tables())

        # 1. Staging tables
        from nbadb.orchestrate.staging_map import get_all_staging_keys

        staging_keys = [k for k in get_all_staging_keys() if self._matches_filter(k, table_filter)]
        existing_staging = [k for k in staging_keys if k in existing]
        staging_counts = self._batch_row_counts(
            existing_staging,
            category=ScanCategory.MISSING_TABLE,
        )

        for key in staging_keys:
            self._report.checks_run += 1
            if key not in existing:
                self._add(
                    ScanFinding(
                        category=ScanCategory.MISSING_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=key,
                        check="missing_staging_table",
                        message=f"Staging table {key} not found in database",
                    )
                )
            else:
                if key in staging_counts and staging_counts[key] == 0:
                    self._add(
                        ScanFinding(
                            category=ScanCategory.MISSING_TABLE,
                            severity=ScanSeverity.WARNING,
                            table=key,
                            check="empty_staging_table",
                            message=f"Staging table {key} exists but is empty",
                            details={"row_count": 0},
                        )
                    )
                self._report.tables_scanned += 1

        # 2. Transform outputs
        transformers = self._transformers_cache
        if transformers is None:
            return

        tf_map = {
            tf.output_table: tf
            for tf in transformers
            if self._matches_filter(tf.output_table, table_filter)
            and tf.output_table not in excluded_transform_tables
        }
        existing_tf = [t for t in tf_map if t in existing]
        tf_counts = self._batch_row_counts(
            existing_tf,
            category=ScanCategory.MISSING_TABLE,
        )

        for out, tf in tf_map.items():
            self._report.checks_run += 1
            if out not in existing:
                self._add(
                    ScanFinding(
                        category=ScanCategory.MISSING_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=out,
                        check="missing_transform_table",
                        message=f"Transform output {out} not found in database",
                        details={"depends_on": tf.depends_on},
                    )
                )
            else:
                if out in tf_counts and tf_counts[out] == 0:
                    self._add(
                        ScanFinding(
                            category=ScanCategory.MISSING_TABLE,
                            severity=ScanSeverity.WARNING,
                            table=out,
                            check="empty_transform_table",
                            message=(
                                f"Transform output {out} exists but is empty; "
                                "no unconditional nonempty contract is established"
                            ),
                            details={
                                "row_count": 0,
                                "depends_on": tf.depends_on,
                                "hard_nonempty_policy": (
                                    "conditional_on_dim_game_coverage"
                                    if out in self._GAME_COVERAGE_TABLES
                                    else "not_established"
                                ),
                                "policy_limitation": (
                                    "No repo-backed unconditional nonempty contract exists; "
                                    "empty transform outputs remain warnings."
                                ),
                            },
                        )
                    )
                self._report.tables_scanned += 1

    # ── category 2: cross-table gaps ──────────────────────────────

    def _check_cross_table_gaps(self, table_filter: str | None) -> None:
        existing = set(self._get_existing_tables())

        # 1. Game coverage
        if "dim_game" in existing:
            for fact_table in self._GAME_COVERAGE_TABLES:
                if fact_table not in existing:
                    continue
                if not self._matches_filter(fact_table, table_filter):
                    continue
                self._report.checks_run += 1
                try:
                    row = self._conn.execute(f"""
                        WITH
                            dim_games AS (
                                SELECT DISTINCT game_id
                                FROM dim_game
                                WHERE game_id IS NOT NULL
                            ),
                            fact_games AS (
                                SELECT DISTINCT game_id
                                FROM "{fact_table}"
                                WHERE game_id IS NOT NULL
                            )
                        SELECT
                            (SELECT COUNT(*) FROM dim_games) AS dim_count,
                            (SELECT COUNT(*) FROM fact_games) AS fact_count,
                            (
                                SELECT COUNT(*)
                                FROM dim_games d
                                LEFT JOIN fact_games f ON d.game_id = f.game_id
                                WHERE f.game_id IS NULL
                            ) AS missing_count
                    """).fetchone()
                    if row is None:
                        continue
                    dim_count, fact_count, missing = row[0], row[1], row[2]
                    if missing > 0:
                        pct = missing / dim_count * 100 if dim_count > 0 else 0
                        severity = ScanSeverity.ERROR if pct > 10 else ScanSeverity.WARNING
                        self._add(
                            ScanFinding(
                                category=ScanCategory.CROSS_TABLE,
                                severity=severity,
                                table=fact_table,
                                check="game_coverage",
                                message=(
                                    f"{fact_table}: {missing:,} games in dim_game "
                                    f"missing from fact table ({pct:.1f}%)"
                                ),
                                details={
                                    "dim_game_count": dim_count,
                                    "fact_game_count": fact_count,
                                    "missing": missing,
                                    "missing_pct": round(pct, 2),
                                },
                            )
                        )
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=ScanCategory.CROSS_TABLE,
                        table=fact_table,
                        check="game_coverage",
                        exc=exc,
                    )

        # 2. Explicit referential integrity
        for fact_table, fk_col, dim_table, pk_col in self._REF_INTEGRITY_CHECKS:
            if fact_table not in existing or dim_table not in existing:
                continue
            if not self._matches_filter(fact_table, table_filter):
                continue
            self._report.checks_run += 1
            try:
                row = self._conn.execute(f"""
                    SELECT COUNT(*) FROM "{fact_table}" f
                    LEFT JOIN "{dim_table}" d ON f."{fk_col}" = d."{pk_col}"
                    WHERE d."{pk_col}" IS NULL AND f."{fk_col}" IS NOT NULL
                """).fetchone()
                orphans = row[0] if row else 0
                if orphans > 0:
                    self._add(
                        ScanFinding(
                            category=ScanCategory.CROSS_TABLE,
                            severity=ScanSeverity.WARNING,
                            table=fact_table,
                            check="referential_integrity",
                            message=(
                                f"{fact_table}.{fk_col} -> {dim_table}.{pk_col}: "
                                f"{orphans:,} orphan records"
                            ),
                            details={
                                "fk": f"{fact_table}.{fk_col}",
                                "pk": f"{dim_table}.{pk_col}",
                                "orphans": orphans,
                            },
                        )
                    )
            except duckdb.Error as exc:
                self._add_query_error(
                    category=ScanCategory.CROSS_TABLE,
                    table=fact_table,
                    check="referential_integrity",
                    exc=exc,
                )

        # 3. Dynamic ref integrity for all fact_ tables with game_id
        checked_facts = {t for t, _, _, _ in self._REF_INTEGRITY_CHECKS}
        if "dim_game" in existing:
            for table in sorted(existing):
                if not table.startswith("fact_"):
                    continue
                if table in checked_facts:
                    continue
                if not self._matches_filter(table, table_filter):
                    continue
                cols = self._get_columns(table, category=ScanCategory.CROSS_TABLE)
                if cols is None:
                    continue
                if "game_id" not in cols:
                    continue
                self._report.checks_run += 1
                try:
                    row = self._conn.execute(f"""
                        SELECT COUNT(*) FROM "{table}" f
                        LEFT JOIN dim_game d ON f.game_id = d.game_id
                        WHERE d.game_id IS NULL AND f.game_id IS NOT NULL
                    """).fetchone()
                    orphans = row[0] if row else 0
                    if orphans > 0:
                        self._add(
                            ScanFinding(
                                category=ScanCategory.CROSS_TABLE,
                                severity=ScanSeverity.WARNING,
                                table=table,
                                check="referential_integrity",
                                message=(
                                    f"{table}.game_id -> dim_game.game_id: "
                                    f"{orphans:,} orphan records"
                                ),
                                details={"fk": f"{table}.game_id", "orphans": orphans},
                            )
                        )
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=ScanCategory.CROSS_TABLE,
                        table=table,
                        check="referential_integrity",
                        exc=exc,
                    )

    # ── category 3: temporal coverage ─────────────────────────────

    def _check_temporal_coverage(
        self,
        table_filter: str | None,
        *,
        low_threshold: float = 0.3,
    ) -> None:
        existing = self._get_existing_tables()

        for table in existing:
            if not self._matches_filter(table, table_filter):
                continue
            cols = self._get_columns(table, category=ScanCategory.TEMPORAL)
            if cols is None:
                continue

            # Season distribution
            if "season_year" in cols:
                self._report.checks_run += 1
                self._report.tables_scanned += 1
                try:
                    rows = self._conn.execute(f"""
                        SELECT season_year, COUNT(*) AS cnt
                        FROM "{table}"
                        WHERE season_year IS NOT NULL
                        GROUP BY season_year
                        ORDER BY season_year
                    """).fetchall()
                    if len(rows) >= 3:
                        counts = [r[1] for r in rows]
                        median = sorted(counts)[len(counts) // 2]
                        threshold = median * low_threshold
                        for season, cnt in rows:
                            if cnt < threshold and median > 0:
                                self._add(
                                    ScanFinding(
                                        category=ScanCategory.TEMPORAL,
                                        severity=ScanSeverity.WARNING,
                                        table=table,
                                        check="low_season_count",
                                        message=(
                                            f"{table}: season {season} has {cnt:,} rows "
                                            f"(median={median:,}, threshold={threshold:.0f})"
                                        ),
                                        details={
                                            "season": str(season),
                                            "row_count": cnt,
                                            "median": median,
                                            "threshold": threshold,
                                        },
                                    )
                                )
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=ScanCategory.TEMPORAL,
                        table=table,
                        check="low_season_count",
                        exc=exc,
                    )

            # Date gap detection (game-level tables only)
            if "game_date" in cols and table in (
                "dim_game",
                "stg_league_game_log",
                "fact_game_result",
            ):
                self._report.checks_run += 1
                try:
                    rows = self._conn.execute(f"""
                        WITH dates AS (
                            SELECT DISTINCT CAST(game_date AS DATE) AS d
                            FROM "{table}"
                            WHERE game_date IS NOT NULL
                        ),
                        gaps AS (
                            SELECT
                                d AS gap_start,
                                LEAD(d) OVER (ORDER BY d) AS gap_end,
                                DATEDIFF('day', d, LEAD(d) OVER (ORDER BY d)) AS gap_days
                            FROM dates
                        )
                        SELECT gap_start, gap_end, gap_days
                        FROM gaps
                        WHERE gap_days > 14
                        ORDER BY gap_days DESC
                        LIMIT 10
                    """).fetchall()
                    for gap_start, gap_end, gap_days in rows:
                        # Skip off-season gaps (June-September)
                        if (
                            gap_start is not None
                            and hasattr(gap_start, "month")
                            and 6 <= gap_start.month <= 9
                        ):
                            continue
                        self._add(
                            ScanFinding(
                                category=ScanCategory.TEMPORAL,
                                severity=ScanSeverity.INFO,
                                table=table,
                                check="date_gap",
                                message=(
                                    f"{table}: {gap_days}-day gap from {gap_start} to {gap_end}"
                                ),
                                details={
                                    "gap_start": str(gap_start),
                                    "gap_end": str(gap_end),
                                    "gap_days": gap_days,
                                },
                            )
                        )
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=ScanCategory.TEMPORAL,
                        table=table,
                        check="date_gap",
                        exc=exc,
                    )

    # ── category 4: data quality ──────────────────────────────────

    def _check_data_quality(self, table_filter: str | None) -> None:
        existing = self._get_existing_tables()
        critical_cols = {"game_id", "player_id", "team_id"}

        for table in existing:
            if not self._matches_filter(table, table_filter):
                continue
            # Skip staging tables — raw data can be messy
            if table.startswith("stg_"):
                continue

            cols = self._get_columns(table, category=ScanCategory.DATA_QUALITY)
            if cols is None:
                continue
            col_set = set(cols)

            # 1. Null rate on critical columns
            for critical in sorted(critical_cols & col_set):
                self._report.checks_run += 1
                try:
                    row = self._conn.execute(f"""
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE "{critical}" IS NULL) AS nulls
                        FROM "{table}"
                    """).fetchone()
                    if row is None:
                        continue
                    total, nulls = row[0], row[1]
                    if nulls > 0 and total > 0:
                        pct = nulls / total * 100
                        self._add(
                            ScanFinding(
                                category=ScanCategory.DATA_QUALITY,
                                severity=ScanSeverity.ERROR if pct > 1 else ScanSeverity.WARNING,
                                table=table,
                                check="null_key_column",
                                message=(
                                    f"{table}.{critical}: {nulls:,}/{total:,} nulls ({pct:.2f}%)"
                                ),
                                details={
                                    "column": critical,
                                    "nulls": nulls,
                                    "total": total,
                                    "null_pct": round(pct, 4),
                                },
                            )
                        )
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=ScanCategory.DATA_QUALITY,
                        table=table,
                        check="null_key_column",
                        exc=exc,
                    )

            # 2. Duplicate key detection
            keys = self._infer_key_columns(table, category=ScanCategory.DATA_QUALITY)
            if keys is None:
                continue
            if keys:
                self._report.checks_run += 1
                cols_str = ", ".join(f'"{k}"' for k in keys)
                try:
                    row = self._conn.execute(
                        f'SELECT COUNT(*) - COUNT(DISTINCT ({cols_str})) FROM "{table}"'
                    ).fetchone()
                    dupes = row[0] if row else 0
                    if dupes > 0:
                        self._add(
                            ScanFinding(
                                category=ScanCategory.DATA_QUALITY,
                                severity=ScanSeverity.WARNING,
                                table=table,
                                check="duplicate_keys",
                                message=f"{table}[{', '.join(keys)}]: {dupes:,} duplicate rows",
                                details={"key_columns": keys, "duplicates": dupes},
                            )
                        )
                except duckdb.Error as exc:
                    self._add_query_error(
                        category=ScanCategory.DATA_QUALITY,
                        table=table,
                        check="duplicate_keys",
                        exc=exc,
                    )

            # 3. Zero-stat detection (fact tables with ≥5 numeric columns)
            if table.startswith("fact_"):
                numeric_cols = self._get_numeric_columns(
                    table,
                    category=ScanCategory.DATA_QUALITY,
                )
                if numeric_cols is None:
                    continue
                if len(numeric_cols) >= 5:
                    self._report.checks_run += 1
                    check_cols = numeric_cols[:15]
                    zero_conds = " AND ".join(f'COALESCE("{c}", 0) = 0' for c in check_cols)
                    try:
                        row = self._conn.execute(
                            f'SELECT COUNT(*) FROM "{table}" WHERE {zero_conds}'
                        ).fetchone()
                        zero_rows = row[0] if row else 0
                        total = self._row_count(table)
                        if zero_rows > 0 and total > 0:
                            pct = zero_rows / total * 100
                            if pct > 5:
                                self._add(
                                    ScanFinding(
                                        category=ScanCategory.DATA_QUALITY,
                                        severity=ScanSeverity.INFO,
                                        table=table,
                                        check="zero_stat_rows",
                                        message=(
                                            f"{table}: {zero_rows:,}/{total:,} rows "
                                            f"with all-zero stats ({pct:.1f}%)"
                                        ),
                                        details={
                                            "zero_rows": zero_rows,
                                            "total": total,
                                            "pct": round(pct, 2),
                                            "numeric_columns_checked": len(check_cols),
                                        },
                                    )
                                )
                    except duckdb.Error as exc:
                        self._add_query_error(
                            category=ScanCategory.DATA_QUALITY,
                            table=table,
                            check="zero_stat_rows",
                            exc=exc,
                        )

            self._report.tables_scanned += 1
