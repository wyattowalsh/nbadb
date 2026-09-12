"""Database scanner for identifying missing data, gaps, and quality issues.

All queries are read-only. The DuckDB connection should be opened with
``read_only=True``.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, cast

import duckdb
from loguru import logger

from nbadb.orchestrate.raw_publication_inventory import (
    PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES,
    raw_request_authority_private_tables,
    raw_request_authority_publication_tables,
)
from nbadb.orchestrate.w2_publication_inventory import (
    w2_public_value_authority_publication_tables,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from nbadb.contracts.raw_request_authority import (
        ObservationRouteLandingV2,
        RequestObservationV2,
        ResultContainerKind,
        ResultOccurrenceV2,
        ResultPresence,
    )
    from nbadb.extract.nba_api_adapter import RawAuthorityResultSetDerivation
    from nbadb.orchestrate.raw_request_store import RawRequestPersistedAttemptV2
    from nbadb.orchestrate.request_closure_runtime import RequestClosureRuntimeReceipt
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


class _OrderedRawAuthorityInventoryHasher:
    """Bounded incremental replacement for a materialized digest inventory."""

    def __init__(self, expected_count: int) -> None:
        if type(expected_count) is not int or expected_count < 0:
            raise ValueError("raw authority inventory count is invalid")
        self._expected_count = expected_count
        self._seen = 0
        self._digest = hashlib.sha256()
        self._digest.update(b"nbadb-raw-authority-ordered-inventory-v1\0")
        self._digest.update(str(expected_count).encode("ascii"))
        self._digest.update(b"\0")

    def update(self, value: str) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("raw authority receipt inventory contains an invalid digest")
        if self._seen >= self._expected_count:
            raise ValueError("raw authority receipt inventory exceeds its SQL count")
        self._digest.update(value.encode("ascii"))
        self._digest.update(b"\n")
        self._seen += 1

    def hexdigest(self) -> str:
        if self._seen != self._expected_count:
            raise ValueError("raw authority receipt inventory is incomplete")
        return self._digest.hexdigest()


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
    evidence: dict[str, dict[str, object]] = field(default_factory=dict)
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
            "evidence": self.evidence,
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
        self._request_closure_inventory_path: Path | None = None
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
        request_closure_inventory_path: Path | None = None,
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
        self._request_closure_inventory_path = request_closure_inventory_path

        self._assure_transformer_discovery()

        active = categories if categories else [c.value for c in ScanCategory]

        if full_publication:
            self._check_full_publication_w2_database_authority()
            self._check_full_publication_raw_authority_tables()
            closure_receipt = self._check_request_closure_inventory()
            self._check_full_publication_anchors()
            self._check_full_publication_cardinality()
            self._check_full_publication_request_authority_join(closure_receipt)

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

    def scan_private_capture(
        self,
        *,
        request_closure_inventory_path: Path | None = None,
    ) -> ScanReport:
        """Verify private capture/reconstruction evidence without public admission.

        This path requires the exact-four private relations and may inspect
        provider-body authority.  ``scan(..., full_publication=True)`` never
        invokes it and instead proves the exact-four are absent.
        """

        start = time.monotonic()
        self._report = ScanReport()
        self._tables_cache = None
        self._columns_cache = {}
        self._transformers_cache = None
        self._request_closure_inventory_path = request_closure_inventory_path

        self._report.checks_run += 1
        try:
            expected = {entry.table_name for entry in raw_request_authority_private_tables()}
        except Exception as exc:
            self._add(
                ScanFinding(
                    category=ScanCategory.MISSING_TABLE,
                    severity=ScanSeverity.ERROR,
                    table="raw_request_authority_private",
                    check="private_raw_authority_registry_invalid",
                    message=(
                        "Private raw request-authority registry is invalid: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    details={"error_type": type(exc).__name__},
                )
            )
            self._report.duration_seconds = time.monotonic() - start
            return self._report

        existing = set(self._get_existing_tables())
        missing = sorted(expected - existing)
        if missing:
            self._add(
                ScanFinding(
                    category=ScanCategory.MISSING_TABLE,
                    severity=ScanSeverity.ERROR,
                    table="raw_request_authority_private",
                    check="missing_private_raw_authority_tables",
                    message=(
                        "Private capture is missing exact raw authority tables: "
                        + ", ".join(missing)
                    ),
                    details={"missing_tables": missing},
                )
            )
        else:
            self._check_private_raw_authority_reconstruction()
            receipt = self._check_request_closure_inventory()
            self._check_full_publication_request_authority_join(receipt)

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

            # The exact-four raw authority relations are private-only; the public
            # raw-authority surface under W2 is the exact-six value authority.
            raw_authority_tables = {
                entry.table_name for entry in w2_public_value_authority_publication_tables()
            }
            known_publication_tables = (
                expected_outputs
                | {entry.staging_key for entry in STAGING_MAP}
                | raw_authority_tables
            )
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

    def _check_full_publication_w2_database_authority(self) -> None:
        """Require one exact read-only receipt over the durable W2 namespace."""

        self._report.checks_run += 1
        try:
            from nbadb.orchestrate.w2_database_assurance import (
                W2DatabaseAuthorityReceiptV1,
                verify_w2_database_authority,
            )

            receipt = verify_w2_database_authority(self._conn, require_w2=True)
            if type(receipt) is not W2DatabaseAuthorityReceiptV1:
                raise TypeError("W2 database verifier returned a foreign receipt")
            replayed = W2DatabaseAuthorityReceiptV1.from_canonical_bytes(receipt.canonical_bytes())
            if type(replayed) is not W2DatabaseAuthorityReceiptV1 or replayed != receipt:
                raise ValueError("W2 database receipt failed exact canonical replay")
        except Exception as exc:
            logger.error(
                "scanner: W2 database authority verification failed: {}",
                type(exc).__name__,
            )
            self._add(
                ScanFinding(
                    category=ScanCategory.MISSING_TABLE,
                    severity=ScanSeverity.ERROR,
                    table="w2_database_authority",
                    check="w2_database_authority_unverified",
                    message=("Full publication lacks exact read-only W2 database authority."),
                    details={
                        "error_type": type(exc).__name__,
                        "required_contract": "exact_six_w2_database_authority_v1",
                    },
                )
            )
            return
        self._report.evidence["w2_database_authority"] = replayed.to_dict()

    def _check_full_publication_raw_authority_tables(self) -> bool:
        """Prove the exact-four private Raw Authority V2 tables are absent."""

        self._report.checks_run += 1
        try:
            private_tables = {entry.table_name for entry in raw_request_authority_private_tables()}
            public_tables = raw_request_authority_publication_tables()
            if public_tables != () or private_tables != set(
                PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES
            ):
                raise ValueError("raw authority public/private registry is inconsistent")
        except Exception as exc:
            self._add(
                ScanFinding(
                    category=ScanCategory.MISSING_TABLE,
                    severity=ScanSeverity.ERROR,
                    table="raw_request_authority_private",
                    check="raw_public_private_authority_invalid",
                    message=(
                        "Raw request-authority public/private registry is invalid: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    details={"error_type": type(exc).__name__},
                )
            )
            return False

        existing = set(self._get_existing_tables())
        leaked = sorted(private_tables & existing)
        if leaked:
            self._add(
                ScanFinding(
                    category=ScanCategory.DATA_QUALITY,
                    severity=ScanSeverity.ERROR,
                    table="raw_request_authority_private",
                    check="private_raw_authority_publication_leak",
                    message=(
                        "Public candidate contains private provider-body authority tables: "
                        + ", ".join(leaked)
                    ),
                    details={
                        "private_tables": sorted(private_tables),
                        "leaked_tables": leaked,
                    },
                )
            )
            return False

        self._report.evidence["private_raw_authority_exclusion"] = {
            "evidence_code": "private_raw_authority_absent",
            "private_tables": sorted(private_tables),
        }
        return True

    _RAW_AUTHORITY_PAGE_SIZE: ClassVar[int] = 128
    _RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION: ClassVar[int] = 4_096
    _RAW_BUNDLE_JOURNAL_SCHEMA: ClassVar[tuple[tuple[str, str, bool, bool], ...]] = (
        ("bundle_sha256", "VARCHAR", True, True),
        ("object_keys_json", "VARCHAR", True, False),
        ("observation_keys_json", "VARCHAR", True, False),
        ("occurrence_keys_json", "VARCHAR", True, False),
        ("landing_keys_json", "VARCHAR", True, False),
        ("object_count", "BIGINT", True, False),
        ("observation_count", "BIGINT", True, False),
        ("occurrence_count", "BIGINT", True, False),
        ("landing_count", "BIGINT", True, False),
        ("object_inventory_sha256", "VARCHAR", True, False),
        ("observation_inventory_sha256", "VARCHAR", True, False),
        ("occurrence_inventory_sha256", "VARCHAR", True, False),
        ("landing_inventory_sha256", "VARCHAR", True, False),
        ("object_rows_sha256", "VARCHAR", True, False),
        ("observation_rows_sha256", "VARCHAR", True, False),
        ("occurrence_rows_sha256", "VARCHAR", True, False),
        ("landing_rows_sha256", "VARCHAR", True, False),
        ("receipt_sha256", "VARCHAR", True, False),
    )
    _RAW_MANIFEST_JOURNAL_SCHEMA: ClassVar[tuple[tuple[str, str, bool, bool], ...]] = (
        ("manifest_sha256", "VARCHAR", True, True),
        ("operation_sha256", "VARCHAR", True, False),
        ("operation_json", "VARCHAR", True, False),
        ("source_sha", "VARCHAR", True, False),
        ("run_id", "BIGINT", True, False),
        ("run_attempt", "BIGINT", True, False),
        ("chain_id", "VARCHAR", True, False),
        ("lane_id", "VARCHAR", True, False),
        ("scope_sha256", "VARCHAR", True, False),
        ("generation", "BIGINT", True, False),
        ("parent_manifest_sha256", "VARCHAR", False, False),
        ("route_authority_sha256", "VARCHAR", True, False),
        ("request_closure_authority_sha256", "VARCHAR", True, False),
        ("field_authority_sha256", "VARCHAR", True, False),
        ("model_authority_sha256", "VARCHAR", True, False),
        ("authority_set_sha256", "VARCHAR", True, False),
        ("receipt_count", "BIGINT", True, False),
        ("receipt_inventory_sha256", "VARCHAR", True, False),
        ("canonical_json", "VARCHAR", True, False),
    )

    _RAW_LATEST_MANIFEST_CTES: ClassVar[str] = """
        WITH latest_manifests AS (
            SELECT canonical_json
            FROM _raw_request_authority_manifest_journal
            QUALIFY generation = MAX(generation) OVER (
                PARTITION BY source_sha, run_id, run_attempt, chain_id, lane_id
            )
        ),
        manifest_receipts AS (
            SELECT receipt.value AS receipt
            FROM latest_manifests AS manifest
            CROSS JOIN LATERAL json_each(
                json_extract(manifest.canonical_json, '$.receipts')
            ) AS receipt
        ),
        manifest_attempts AS (
            SELECT
                json_extract_string(attempt.value, '$.observation_sha256') AS observation_sha256,
                json_extract_string(attempt.value, '$.provider_request_sha256')
                    AS provider_request_sha256
            FROM manifest_receipts AS receipt
            CROSS JOIN LATERAL json_each(
                json_extract(receipt.receipt, '$.attempts')
            ) AS attempt
        ),
        manifest_calls AS (
            SELECT
                json_extract_string(call.value, '$.logical_request_sha256')
                    AS logical_request_sha256,
                json_extract_string(call.value, '$.provider_request_sha256')
                    AS provider_request_sha256
            FROM latest_manifests AS manifest
            CROSS JOIN LATERAL json_each(
                json_extract(manifest.canonical_json, '$.expected_calls')
            ) AS call
        ),
        manifest_bundles AS (
            SELECT json_extract_string(receipt, '$.bundle_sha256') AS bundle_sha256
            FROM manifest_receipts
        )
    """

    def _validate_raw_authority_journal_schemas(self) -> None:
        expected = {
            "_raw_request_authority_bundle_journal": self._RAW_BUNDLE_JOURNAL_SCHEMA,
            "_raw_request_authority_manifest_journal": self._RAW_MANIFEST_JOURNAL_SCHEMA,
        }
        rows = self._conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name IN (?, ?) ORDER BY table_name",
            list(sorted(expected)),
        ).fetchall()
        observed_tables = {str(row[0]) for row in rows}
        if observed_tables != set(expected):
            raise ValueError("raw authority persistence journals are missing")
        for table_name, expected_schema in expected.items():
            columns = self._conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            observed_schema = tuple(
                (str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5])) for row in columns
            )
            if observed_schema != expected_schema:
                raise ValueError(f"raw authority journal schema drifted: {table_name}")

    def _stream_raw_bundle_sha_inventory(
        self,
        *,
        bundle_sha256: str,
        column_name: str,
        count: int,
        digest: str,
        label: str,
        expected_values: tuple[str, ...] | None = None,
        output_hasher: object | None = None,
        require_lexicographic: bool = True,
    ) -> None:
        """Keyset-page one journal SHA array and reproduce its canonical bytes."""

        if column_name not in {
            "object_keys_json",
            "observation_keys_json",
            "occurrence_keys_json",
            "landing_keys_json",
        }:
            raise ValueError(f"{label} inventory column is unsupported")
        if (
            type(count) is not int
            or count < 0
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or (expected_values is not None and len(expected_values) != count)
        ):
            raise ValueError(f"{label} inventory envelope is invalid")
        envelope = self._conn.execute(
            f'SELECT json_valid("{column_name}"), json_type("{column_name}"), '
            f'json_array_length("{column_name}"), sha256("{column_name}") '
            "FROM _raw_request_authority_bundle_journal WHERE bundle_sha256 = ?",
            [bundle_sha256],
        ).fetchone()
        if envelope != (True, "ARRAY", count, digest):
            raise ValueError(f"{label} inventory envelope is invalid")

        canonical_digest = hashlib.sha256()
        canonical_digest.update(b"[")
        if output_hasher is not None:
            cast("Any", output_hasher).update(b"[")
        seen = 0
        seen_values: set[str] = set()
        previous: str | None = None
        last_ordinal = -1
        while True:
            rows = self._conn.execute(
                f"SELECT CAST(member.key AS BIGINT), json_type(member.value), "
                f"json_extract_string(member.value, '$') "
                "FROM _raw_request_authority_bundle_journal AS bundle "
                f'CROSS JOIN LATERAL json_each(bundle."{column_name}") AS member '
                "WHERE bundle.bundle_sha256 = ? AND CAST(member.key AS BIGINT) > ? "
                "ORDER BY CAST(member.key AS BIGINT) "
                f"LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}",
                [bundle_sha256, last_ordinal],
            ).fetchall()
            if not rows:
                break
            for ordinal, json_kind, value in rows:
                if (
                    type(ordinal) is not int
                    or ordinal != seen
                    or json_kind != "VARCHAR"
                    or type(value) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", value) is None
                    or value in seen_values
                    or (require_lexicographic and previous is not None and value <= previous)
                    or (expected_values is not None and expected_values[seen] != value)
                ):
                    raise ValueError(f"{label} inventory is not canonical and exact")
                if seen:
                    canonical_digest.update(b",")
                    if output_hasher is not None:
                        cast("Any", output_hasher).update(b",")
                encoded = b'"' + value.encode("ascii") + b'"'
                canonical_digest.update(encoded)
                if output_hasher is not None:
                    cast("Any", output_hasher).update(encoded)
                previous = value
                seen_values.add(value)
                last_ordinal = ordinal
                seen += 1
        canonical_digest.update(b"]")
        if output_hasher is not None:
            cast("Any", output_hasher).update(b"]")
        if seen != count or canonical_digest.hexdigest() != digest:
            raise ValueError(f"{label} inventory count or digest is invalid")

    def _raw_bundle_row_inventory_sha256(
        self,
        *,
        bundle_sha256: str,
        table_name: str,
        key_column: str,
        inventory_column: str,
        expected_count: int,
    ) -> str:
        """Rebuild one exact canonical-row inventory from persisted public rows."""

        from nbadb.contracts.raw_request_authority import (
            validate_parser_input_object,
            validate_result_occurrence,
        )
        from nbadb.schemas.raw.nba_api_authority import (
            RawNbaApiObservationRouteLandingSchema,
            RawNbaApiParserInputObjectSchema,
            RawNbaApiRequestObservationSchema,
            RawNbaApiResultOccurrenceSchema,
        )

        specifications = {
            "raw_nba_api_parser_input_object": (
                "object_sha256",
                "object_keys_json",
                RawNbaApiParserInputObjectSchema,
            ),
            "raw_nba_api_request_observation": (
                "observation_sha256",
                "observation_keys_json",
                RawNbaApiRequestObservationSchema,
            ),
            "raw_nba_api_result_occurrence": (
                "occurrence_sha256",
                "occurrence_keys_json",
                RawNbaApiResultOccurrenceSchema,
            ),
            "raw_nba_api_observation_route_landing": (
                "landing_sha256",
                "landing_keys_json",
                RawNbaApiObservationRouteLandingSchema,
            ),
        }
        specification = specifications.get(table_name)
        if specification is None or (key_column, inventory_column) != specification[:2]:
            raise ValueError("raw bundle row inventory table contract is unsupported")
        schema_type = specification[2]
        columns = list(schema_type.to_schema().columns)
        selection = ", ".join(
            (
                f'epoch_us(stored."{name}") AS "{name}"'
                if (
                    table_name == "raw_nba_api_request_observation"
                    and name in {"started_at", "finished_at"}
                )
                or (
                    table_name == "raw_nba_api_observation_route_landing"
                    and name == "live_snapshot_at"
                )
                else f'stored."{name}"'
            )
            for name in columns
        )
        digest = hashlib.sha256()
        digest.update(b"[")
        emitted = 0
        last_identity: str | None = None
        while True:
            parameters: list[object] = [bundle_sha256]
            predicate = ""
            if last_identity is not None:
                predicate = f'AND stored."{key_column}" > ? '
                parameters.append(last_identity)
            rows = self._conn.execute(
                f"""
                WITH expected AS (
                    SELECT json_extract_string(member.value, '$') AS identity
                    FROM _raw_request_authority_bundle_journal AS bundle
                    CROSS JOIN LATERAL json_each(bundle."{inventory_column}") AS member
                    WHERE bundle.bundle_sha256 = ?
                )
                SELECT {selection}
                FROM "{table_name}" AS stored
                INNER JOIN expected ON stored."{key_column}" = expected.identity
                WHERE TRUE {predicate}
                ORDER BY stored."{key_column}"
                LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}
                """,
                parameters,
            ).fetchall()
            if not rows:
                break
            for row in rows:
                materialized = dict(zip(columns, row, strict=True))
                identity = materialized[key_column]
                if (
                    type(identity) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", identity) is None
                    or (last_identity is not None and identity <= last_identity)
                ):
                    raise ValueError("raw bundle row identity is not exact and ordered")
                if table_name == "raw_nba_api_parser_input_object":
                    canonical_row = validate_parser_input_object(materialized).to_canonical_bytes()
                elif table_name == "raw_nba_api_request_observation":
                    canonical_row = self._decode_raw_observation_row(
                        materialized
                    ).to_canonical_bytes()
                elif table_name == "raw_nba_api_result_occurrence":
                    canonical_row = validate_result_occurrence(materialized).to_canonical_bytes()
                else:
                    canonical_row = self._decode_raw_landing_row(materialized).to_canonical_bytes()
                if emitted:
                    digest.update(b",")
                digest.update(
                    json.dumps(
                        {
                            "canonical_row_sha256": hashlib.sha256(canonical_row).hexdigest(),
                            "identity": identity,
                        },
                        allow_nan=False,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                )
                emitted += 1
                last_identity = identity
        digest.update(b"]")
        if emitted != expected_count:
            raise ValueError("raw bundle canonical row inventory is incomplete")
        return digest.hexdigest()

    def _raw_authority_join_sql_invariants(self) -> None:
        """Reject global extras and rebinding with bounded scalar SQL results."""

        ctes = self._RAW_LATEST_MANIFEST_CTES
        checks = (
            (
                "latest manifests repeat a logical request",
                "SELECT COUNT(*) - COUNT(DISTINCT logical_request_sha256) FROM manifest_calls",
            ),
            (
                "latest manifests repeat a provider request",
                "SELECT COUNT(*) - COUNT(DISTINCT provider_request_sha256) FROM manifest_calls",
            ),
            (
                "latest manifests repeat a raw observation",
                "SELECT COUNT(*) - COUNT(DISTINCT observation_sha256) FROM manifest_attempts",
            ),
            (
                "raw authority contains an observation outside terminal manifests",
                "SELECT COUNT(*) FROM raw_nba_api_request_observation AS stored "
                "LEFT JOIN manifest_attempts AS expected USING (observation_sha256) "
                "WHERE expected.observation_sha256 IS NULL",
            ),
            (
                "terminal manifests reference a missing raw observation",
                "SELECT COUNT(*) FROM manifest_attempts AS expected "
                "LEFT JOIN raw_nba_api_request_observation AS stored "
                "USING (observation_sha256) WHERE stored.observation_sha256 IS NULL",
            ),
            (
                "raw authority contains a bundle outside terminal manifests",
                "SELECT COUNT(*) FROM _raw_request_authority_bundle_journal AS stored "
                "LEFT JOIN manifest_bundles AS expected USING (bundle_sha256) "
                "WHERE expected.bundle_sha256 IS NULL",
            ),
            (
                "terminal manifests reference a missing raw bundle",
                "SELECT COUNT(*) FROM manifest_bundles AS expected "
                "LEFT JOIN _raw_request_authority_bundle_journal AS stored "
                "USING (bundle_sha256) WHERE stored.bundle_sha256 IS NULL",
            ),
            (
                "latest manifests repeat a raw bundle",
                "SELECT COUNT(*) - COUNT(DISTINCT bundle_sha256) FROM manifest_bundles",
            ),
        )
        for message, query in checks:
            row = self._conn.execute(f"{ctes} {query}").fetchone()
            if row is None or type(row[0]) is not int or row[0] != 0:
                raise ValueError(message)

        latest_count = self._conn.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT 1 FROM _raw_request_authority_manifest_journal "
            "QUALIFY generation = MAX(generation) OVER ("
            "PARTITION BY source_sha, run_id, run_attempt, chain_id, lane_id)) latest"
        ).fetchone()
        if latest_count is None or type(latest_count[0]) is not int or latest_count[0] <= 0:
            raise ValueError("raw authority has no terminal manifest generation")

    def _verify_raw_bundle_receipt(
        self,
        receipt: object,
    ) -> None:
        """Join one manifest receipt to its exact journal and raw rows."""

        from nbadb.orchestrate.raw_request_store import (
            RawRequestAuthorityPersistenceReceiptV2,
        )

        if type(receipt) is not RawRequestAuthorityPersistenceReceiptV2:
            raise ValueError("raw manifest contains a foreign persistence receipt")
        row = self._conn.execute(
            "SELECT bundle_sha256, object_count, observation_count, occurrence_count, "
            "landing_count, "
            "object_inventory_sha256, observation_inventory_sha256, "
            "occurrence_inventory_sha256, landing_inventory_sha256, "
            "object_rows_sha256, observation_rows_sha256, occurrence_rows_sha256, "
            "landing_rows_sha256, receipt_sha256 "
            "FROM _raw_request_authority_bundle_journal WHERE bundle_sha256 = ?",
            [receipt.bundle_sha256],
        ).fetchone()
        if row is None or len(row) != 14:
            raise ValueError("raw manifest receipt has no exact bundle journal row")
        (
            bundle_sha256,
            object_count,
            observation_count,
            occurrence_count,
            landing_count,
            object_inventory_sha256,
            observation_inventory_sha256,
            occurrence_inventory_sha256,
            landing_inventory_sha256,
            object_rows_sha256,
            observation_rows_sha256,
            occurrence_rows_sha256,
            landing_rows_sha256,
            receipt_sha256,
        ) = row
        projected = (
            bundle_sha256,
            object_count,
            observation_count,
            occurrence_count,
            landing_count,
            object_inventory_sha256,
            observation_inventory_sha256,
            occurrence_inventory_sha256,
            landing_inventory_sha256,
            object_rows_sha256,
            observation_rows_sha256,
            occurrence_rows_sha256,
            landing_rows_sha256,
            receipt_sha256,
        )
        expected = (
            receipt.bundle_sha256,
            receipt.object_count,
            receipt.observation_count,
            receipt.occurrence_count,
            receipt.landing_count,
            receipt.object_inventory_sha256,
            receipt.observation_inventory_sha256,
            receipt.occurrence_inventory_sha256,
            receipt.landing_inventory_sha256,
            receipt.object_rows_sha256,
            receipt.observation_rows_sha256,
            receipt.occurrence_rows_sha256,
            receipt.landing_rows_sha256,
            receipt.receipt_sha256,
        )
        if projected != expected:
            raise ValueError("raw bundle journal differs from its manifest receipt")

        attempt_observation_ids = tuple(
            sorted(item.observation_sha256 for item in receipt.attempts)
        )
        self._stream_raw_bundle_sha_inventory(
            bundle_sha256=receipt.bundle_sha256,
            column_name="landing_keys_json",
            count=receipt.landing_count,
            digest=receipt.landing_inventory_sha256,
            label="raw bundle route landing",
            require_lexicographic=False,
        )
        bundle_digest = hashlib.sha256()
        bundle_digest.update(b'{"landing_sha256s":[')
        emitted_landings = 0
        last_landing: str | None = None
        while True:
            parameters: list[object] = [receipt.bundle_sha256]
            predicate = ""
            if last_landing is not None:
                predicate = "AND stored.landing_sha256 > ? "
                parameters.append(last_landing)
            rows = self._conn.execute(
                "SELECT stored.landing_sha256 "
                "FROM _raw_request_authority_bundle_journal AS bundle "
                "CROSS JOIN LATERAL json_each(bundle.landing_keys_json) AS expected "
                "INNER JOIN raw_nba_api_observation_route_landing AS stored "
                "ON stored.landing_sha256 = json_extract_string(expected.value, '$') "
                "WHERE bundle.bundle_sha256 = ? "
                f"{predicate}"
                "ORDER BY stored.landing_sha256 "
                f"LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}",
                parameters,
            ).fetchall()
            if not rows:
                break
            for (raw_landing,) in rows:
                landing_sha256 = str(raw_landing)
                if re.fullmatch(r"[0-9a-f]{64}", landing_sha256) is None:
                    raise ValueError("raw bundle route-landing identity is invalid")
                if emitted_landings:
                    bundle_digest.update(b",")
                bundle_digest.update(b'"' + landing_sha256.encode("ascii") + b'"')
                emitted_landings += 1
                last_landing = landing_sha256
        if emitted_landings != receipt.landing_count:
            raise ValueError("raw bundle route-landing inventory is incomplete")
        bundle_digest.update(b'],"object_sha256s":')
        self._stream_raw_bundle_sha_inventory(
            bundle_sha256=receipt.bundle_sha256,
            column_name="object_keys_json",
            count=receipt.object_count,
            digest=receipt.object_inventory_sha256,
            label="raw bundle object",
            output_hasher=bundle_digest,
        )
        self._stream_raw_bundle_sha_inventory(
            bundle_sha256=receipt.bundle_sha256,
            column_name="observation_keys_json",
            count=receipt.observation_count,
            digest=receipt.observation_inventory_sha256,
            label="raw bundle observation",
            expected_values=attempt_observation_ids,
        )
        self._stream_raw_bundle_sha_inventory(
            bundle_sha256=receipt.bundle_sha256,
            column_name="occurrence_keys_json",
            count=receipt.occurrence_count,
            digest=receipt.occurrence_inventory_sha256,
            label="raw bundle occurrence",
        )

        row_inventories = (
            (
                "raw_nba_api_parser_input_object",
                "object_sha256",
                "object_keys_json",
                receipt.object_count,
                receipt.object_rows_sha256,
            ),
            (
                "raw_nba_api_request_observation",
                "observation_sha256",
                "observation_keys_json",
                receipt.observation_count,
                receipt.observation_rows_sha256,
            ),
            (
                "raw_nba_api_result_occurrence",
                "occurrence_sha256",
                "occurrence_keys_json",
                receipt.occurrence_count,
                receipt.occurrence_rows_sha256,
            ),
            (
                "raw_nba_api_observation_route_landing",
                "landing_sha256",
                "landing_keys_json",
                receipt.landing_count,
                receipt.landing_rows_sha256,
            ),
        )
        for (
            table_name,
            key_column,
            inventory_column,
            count,
            expected_rows_digest,
        ) in row_inventories:
            observed_rows_digest = self._raw_bundle_row_inventory_sha256(
                bundle_sha256=receipt.bundle_sha256,
                table_name=table_name,
                key_column=key_column,
                inventory_column=inventory_column,
                expected_count=count,
            )
            if observed_rows_digest != expected_rows_digest:
                raise ValueError(f"raw bundle {table_name} row identity differs")

        inventories = (
            (
                "raw_nba_api_parser_input_object",
                "object_sha256",
                "object_keys_json",
                receipt.object_count,
                "object",
            ),
            (
                "raw_nba_api_request_observation",
                "observation_sha256",
                "observation_keys_json",
                receipt.observation_count,
                "observation",
            ),
            (
                "raw_nba_api_result_occurrence",
                "occurrence_sha256",
                "occurrence_keys_json",
                receipt.occurrence_count,
                "occurrence",
            ),
            (
                "raw_nba_api_observation_route_landing",
                "landing_sha256",
                "landing_keys_json",
                receipt.landing_count,
                "route landing",
            ),
        )
        for table_name, key_column, inventory_column, expected_count, label in inventories:
            count_row = self._conn.execute(
                "SELECT COUNT(*) FROM _raw_request_authority_bundle_journal AS bundle "
                f'CROSS JOIN LATERAL json_each(bundle."{inventory_column}") AS expected '
                f'INNER JOIN "{table_name}" AS stored '
                f"ON stored.\"{key_column}\" = json_extract_string(expected.value, '$') "
                "WHERE bundle.bundle_sha256 = ?",
                [receipt.bundle_sha256],
            ).fetchone()
            if count_row is None or count_row[0] != expected_count:
                raise ValueError(f"raw bundle is missing a persisted {label}")

        landing_order_row = self._conn.execute(
            "WITH persisted AS ("
            "SELECT CAST(expected.key AS BIGINT) AS persisted_ordinal, "
            "stored.observation_sha256, stored.route_ordinal, stored.landing_sha256 "
            "FROM _raw_request_authority_bundle_journal AS bundle "
            "CROSS JOIN LATERAL json_each(bundle.landing_keys_json) AS expected "
            "INNER JOIN raw_nba_api_observation_route_landing AS stored "
            "ON stored.landing_sha256 = json_extract_string(expected.value, '$') "
            "WHERE bundle.bundle_sha256 = ?"
            "), ordered AS ("
            "SELECT persisted_ordinal, ROW_NUMBER() OVER ("
            "ORDER BY observation_sha256, route_ordinal) - 1 AS expected_ordinal "
            "FROM persisted"
            ") SELECT COUNT(*) FROM ordered "
            "WHERE persisted_ordinal <> expected_ordinal",
            [receipt.bundle_sha256],
        ).fetchone()
        if landing_order_row is None or landing_order_row[0] != 0:
            raise ValueError("raw bundle route-landing inventory order is not canonical")

        inventory_ctes = """
            WITH bundle AS (
                SELECT object_keys_json, observation_keys_json, occurrence_keys_json,
                       landing_keys_json
                FROM _raw_request_authority_bundle_journal WHERE bundle_sha256 = ?
            ),
            object_keys AS (
                SELECT json_extract_string(member.value, '$') AS object_sha256
                FROM bundle CROSS JOIN LATERAL json_each(bundle.object_keys_json) AS member
            ),
            observation_keys AS (
                SELECT json_extract_string(member.value, '$') AS observation_sha256
                FROM bundle CROSS JOIN LATERAL json_each(bundle.observation_keys_json) AS member
            ),
            occurrence_keys AS (
                SELECT json_extract_string(member.value, '$') AS occurrence_sha256
                FROM bundle CROSS JOIN LATERAL json_each(bundle.occurrence_keys_json) AS member
            ),
            landing_keys AS (
                SELECT json_extract_string(member.value, '$') AS landing_sha256
                FROM bundle CROSS JOIN LATERAL json_each(bundle.landing_keys_json) AS member
            )
        """
        closure_checks = (
            (
                "raw bundle occurrence is rebound outside its observations",
                "SELECT COUNT(*) FROM raw_nba_api_result_occurrence AS occurrence "
                "INNER JOIN occurrence_keys USING (occurrence_sha256) "
                "LEFT JOIN observation_keys USING (observation_sha256) "
                "WHERE observation_keys.observation_sha256 IS NULL",
            ),
            (
                "raw bundle observation has an occurrence outside its receipt",
                "SELECT COUNT(*) FROM raw_nba_api_result_occurrence AS occurrence "
                "INNER JOIN observation_keys USING (observation_sha256) "
                "LEFT JOIN occurrence_keys USING (occurrence_sha256) "
                "WHERE occurrence_keys.occurrence_sha256 IS NULL",
            ),
            (
                "raw bundle object is not referenced by its observations",
                "SELECT COUNT(*) FROM object_keys "
                "LEFT JOIN raw_nba_api_request_observation AS observation "
                "ON observation.body_object_sha256 = object_keys.object_sha256 "
                "AND observation.observation_sha256 IN "
                "(SELECT observation_sha256 FROM observation_keys) "
                "WHERE observation.observation_sha256 IS NULL",
            ),
            (
                "raw bundle observation references an object outside its receipt",
                "SELECT COUNT(*) FROM raw_nba_api_request_observation AS observation "
                "INNER JOIN observation_keys USING (observation_sha256) "
                "LEFT JOIN object_keys ON observation.body_object_sha256 = "
                "object_keys.object_sha256 "
                "WHERE observation.body_object_sha256 IS NOT NULL "
                "AND object_keys.object_sha256 IS NULL",
            ),
            (
                "raw bundle route landing is rebound outside its observations",
                "SELECT COUNT(*) FROM raw_nba_api_observation_route_landing AS landing "
                "INNER JOIN landing_keys USING (landing_sha256) "
                "LEFT JOIN observation_keys USING (observation_sha256) "
                "WHERE observation_keys.observation_sha256 IS NULL",
            ),
            (
                "raw bundle observation has a route landing outside its receipt",
                "SELECT COUNT(*) FROM raw_nba_api_observation_route_landing AS landing "
                "INNER JOIN observation_keys USING (observation_sha256) "
                "LEFT JOIN landing_keys USING (landing_sha256) "
                "WHERE landing_keys.landing_sha256 IS NULL",
            ),
        )
        for message, query in closure_checks:
            count_row = self._conn.execute(
                f"{inventory_ctes} {query}",
                [receipt.bundle_sha256],
            ).fetchone()
            if count_row is None or type(count_row[0]) is not int or count_row[0] != 0:
                raise ValueError(message)

        bundle_digest.update(b',"observation_record_sha256s":')
        bundle_digest.update(b"[")
        emitted = 0
        last_key: tuple[str, str] | None = None
        while True:
            parameters: list[object] = [receipt.bundle_sha256]
            predicate = ""
            if last_key is not None:
                predicate = (
                    "AND (stored.observation_record_sha256, stored.observation_sha256) > (?, ?) "
                )
                parameters.extend(last_key)
            rows = self._conn.execute(
                "SELECT stored.observation_record_sha256, stored.observation_sha256 "
                "FROM _raw_request_authority_bundle_journal AS bundle "
                "CROSS JOIN LATERAL json_each(bundle.observation_keys_json) AS expected "
                "INNER JOIN raw_nba_api_request_observation AS stored "
                "ON stored.observation_sha256 = json_extract_string(expected.value, '$') "
                "WHERE bundle.bundle_sha256 = ? "
                f"{predicate}"
                "ORDER BY stored.observation_record_sha256, stored.observation_sha256 "
                f"LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}",
                parameters,
            ).fetchall()
            if not rows:
                break
            for raw_record, raw_observation in rows:
                if emitted:
                    bundle_digest.update(b",")
                bundle_digest.update(b'"')
                bundle_digest.update(str(raw_record).encode("ascii"))
                bundle_digest.update(b'"')
                emitted += 1
                last_key = (str(raw_record), str(raw_observation))
        if emitted != receipt.observation_count:
            raise ValueError("raw bundle observation record inventory is incomplete")
        bundle_digest.update(b'],"occurrence_sha256s":')
        self._stream_raw_bundle_sha_inventory(
            bundle_sha256=receipt.bundle_sha256,
            column_name="occurrence_keys_json",
            count=receipt.occurrence_count,
            digest=receipt.occurrence_inventory_sha256,
            label="raw bundle occurrence",
            output_hasher=bundle_digest,
        )
        bundle_digest.update(b',"schema_version":2}')
        if bundle_digest.hexdigest() != receipt.bundle_sha256:
            raise ValueError("raw bundle digest differs after bounded reconstruction")

    def _load_manifest_attempt_observation(
        self,
        attempt: object,
        *,
        manifest: object,
        expected_call: object,
    ) -> tuple[
        RequestObservationV2,
        tuple[ResultOccurrenceV2, ...],
        tuple[ObservationRouteLandingV2, ...],
    ]:
        """Load and exact-join one manifested attempt to one stored observation."""

        from nbadb.orchestrate.raw_request_manifest import RawRequestAuthorityManifestV2
        from nbadb.orchestrate.raw_request_store import (
            RawRequestClosureCallV2,
            RawRequestPersistedAttemptV2,
        )
        from nbadb.schemas.raw.nba_api_authority import (
            RawNbaApiObservationRouteLandingSchema,
            RawNbaApiParserInputObjectSchema,
            RawNbaApiRequestObservationSchema,
            RawNbaApiResultOccurrenceSchema,
        )

        if (
            type(attempt) is not RawRequestPersistedAttemptV2
            or type(manifest) is not RawRequestAuthorityManifestV2
            or type(expected_call) is not RawRequestClosureCallV2
        ):
            raise ValueError("raw manifest attempt join received a foreign contract")
        observation_columns = list(RawNbaApiRequestObservationSchema.to_schema().columns)
        observation_selection = ", ".join(
            (
                f'epoch_us("{name}") AS "{name}"'
                if name in {"started_at", "finished_at"}
                else f'"{name}"'
            )
            for name in observation_columns
        )
        row = self._conn.execute(
            f"SELECT {observation_selection} "
            'FROM "raw_nba_api_request_observation" WHERE "observation_sha256" = ?',
            [attempt.observation_sha256],
        ).fetchone()
        if row is None:
            raise ValueError("manifested raw observation is missing")
        observation = self._decode_raw_observation_row(
            dict(zip(observation_columns, row, strict=True))
        )
        stored_attempt = observation.attempt
        stored_projection = (
            stored_attempt.observation_sha256,
            observation.observation_record_sha256,
            stored_attempt.semantic_request_sha256,
            stored_attempt.logical_invocation_sha256,
            stored_attempt.provider_call_sha256,
            stored_attempt.provider_call_role,
            stored_attempt.provider_call_ordinal,
            stored_attempt.retry_ordinal,
            stored_attempt.request_ordinal,
            stored_attempt.source_family,
            stored_attempt.endpoint_id,
            stored_attempt.provider_request_sha256,
            stored_attempt.safe_parameters_sha256,
            stored_attempt.scope_sha256,
            observation.lifecycle,
            observation.outcome,
        )
        manifested_projection = (
            attempt.observation_sha256,
            attempt.observation_record_sha256,
            attempt.semantic_request_sha256,
            attempt.logical_invocation_sha256,
            attempt.provider_call_sha256,
            attempt.provider_call_role,
            attempt.provider_call_ordinal,
            attempt.retry_ordinal,
            attempt.request_ordinal,
            attempt.source_family,
            attempt.endpoint_id,
            attempt.provider_request_sha256,
            attempt.safe_parameters_sha256,
            attempt.scope_sha256,
            attempt.lifecycle,
            attempt.outcome,
        )
        if stored_projection != manifested_projection:
            raise ValueError("manifest attempt is rebound to a different raw observation")
        execution = (
            stored_attempt.source_sha,
            stored_attempt.run_id,
            stored_attempt.run_attempt,
            stored_attempt.chain_id,
            stored_attempt.lane_id,
        )
        manifest_execution = (
            manifest.source_sha,
            manifest.run_id,
            manifest.run_attempt,
            manifest.chain_id,
            manifest.lane_id,
        )
        if execution != manifest_execution:
            raise ValueError("raw observation execution differs from manifest provenance")
        if (
            stored_attempt.source_family != expected_call.source_family
            or stored_attempt.endpoint_id != expected_call.endpoint_id
            or stored_attempt.provider_request_sha256 != expected_call.provider_request_sha256
            or stored_attempt.scope_sha256 != expected_call.scope_sha256
        ):
            raise ValueError("raw observation differs from its expected closure call")

        occurrence_columns = list(RawNbaApiResultOccurrenceSchema.to_schema().columns)
        occurrence_selection = ", ".join(f'"{name}"' for name in occurrence_columns)
        if observation.result_occurrence_count > self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION:
            raise ValueError("manifested observation exceeds the bounded result inventory")
        raw_occurrences = self._conn.execute(
            f"SELECT {occurrence_selection} "
            'FROM "raw_nba_api_result_occurrence" WHERE "observation_sha256" = ? '
            'ORDER BY "occurrence_ordinal" '
            f"LIMIT {self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION + 1}",
            [attempt.observation_sha256],
        ).fetchall()
        if len(raw_occurrences) > self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION:
            raise ValueError("manifested observation exceeds the bounded result inventory")
        from nbadb.contracts.raw_request_authority import (
            RawRequestAuthorityBundleV2,
            canonical_json_bytes,
            validate_parser_input_object,
            validate_result_occurrence,
        )

        occurrences = tuple(
            validate_result_occurrence(dict(zip(occurrence_columns, item, strict=True)))
            for item in raw_occurrences
        )
        landing_columns = list(RawNbaApiObservationRouteLandingSchema.to_schema().columns)
        landing_selection = ", ".join(
            (f'epoch_us("{name}") AS "{name}"' if name == "live_snapshot_at" else f'"{name}"')
            for name in landing_columns
        )
        if observation.route_landing_count > self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION:
            raise ValueError("manifested observation exceeds the bounded route inventory")
        raw_landings = self._conn.execute(
            f"SELECT {landing_selection} "
            'FROM "raw_nba_api_observation_route_landing" '
            'WHERE "observation_sha256" = ? ORDER BY "route_ordinal" '
            f"LIMIT {self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION + 1}",
            [attempt.observation_sha256],
        ).fetchall()
        if len(raw_landings) > self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION:
            raise ValueError("manifested observation exceeds the bounded route inventory")
        landings = tuple(
            self._decode_raw_landing_row(dict(zip(landing_columns, item, strict=True)))
            for item in raw_landings
        )
        landing_sha256s = [item.landing_sha256 for item in landings]
        if (
            len(landings) != observation.route_landing_count
            or [item.route_ordinal for item in landings] != list(range(len(landings)))
            or hashlib.sha256(canonical_json_bytes(landing_sha256s)).hexdigest()
            != observation.route_landings_sha256
        ):
            raise ValueError("manifested observation route-landing inventory is invalid")
        routes = tuple(sorted(item.route_id for item in landings))
        if len(routes) != len(set(routes)):
            raise ValueError("manifested observation repeats a route landing")
        if routes != attempt.route_ids:
            raise ValueError("manifest attempt routes differ from stored route landings")
        if observation.lifecycle == "selected_terminal":
            try:
                expected_call.validate_terminal_route_ids(routes)
            except ValueError as exc:
                raise ValueError(
                    "terminal raw routes differ from the expected closure call"
                ) from exc
        elif routes:
            raise ValueError("incomplete raw attempt claims route-landing coverage")
        body_object = None
        if observation.body_object_sha256 is not None:
            object_columns = list(RawNbaApiParserInputObjectSchema.to_schema().columns)
            object_selection = ", ".join(f'"{name}"' for name in object_columns)
            body_row = self._conn.execute(
                f"SELECT {object_selection} FROM raw_nba_api_parser_input_object "
                "WHERE object_sha256 = ?",
                [observation.body_object_sha256],
            ).fetchone()
            if body_row is None:
                raise ValueError("manifested observation parser-input object is missing")
            body_object = validate_parser_input_object(
                dict(zip(object_columns, body_row, strict=True))
            )
        rebuilt = RawRequestAuthorityBundleV2.build(
            objects=() if body_object is None else (body_object,),
            observations=(observation,),
            occurrences=occurrences,
            landings=landings,
        )
        if rebuilt.observations != (observation,):
            raise ValueError("manifested observation changed during exact bundle rebuild")
        return observation, occurrences, landings

    @staticmethod
    def _closure_occurrence_state(occurrence: ResultOccurrenceV2) -> str:
        if occurrence.presence == "present" and occurrence.row_count > 0:
            return "present_nonempty"
        if occurrence.presence in {
            "present",
            "present_empty",
            "empty_array",
            "empty_object",
        }:
            return "present_empty"
        return "absent_optional"

    def _verify_request_closure_call_join(
        self,
        *,
        call: object,
        attempts: tuple[object, ...],
        selected_observation: RequestObservationV2,
        selected_occurrences: tuple[ResultOccurrenceV2, ...],
        selected_landings: tuple[ObservationRouteLandingV2, ...],
        closure_observation: object,
        closure_receipt: RequestClosureRuntimeReceipt,
    ) -> None:
        """Bind one non-static manifest call to its exact closure observation."""

        from nbadb.extract.bronze import canonical_parameters_sha256
        from nbadb.orchestrate.raw_request_store import RawRequestClosureCallV2
        from nbadb.orchestrate.request_closure_runtime import RequestObservation

        if (
            type(call) is not RawRequestClosureCallV2
            or type(closure_observation) is not RequestObservation
        ):
            raise ValueError("request closure join received a foreign contract")
        closure = closure_observation
        if closure.state == "upstream_unavailable":
            raise ValueError(
                "upstream-unavailable closure evidence cannot be rebound as raw result coverage"
            )
        if closure.state not in {"success_nonempty", "success_empty"}:
            raise ValueError("request closure call is not a successful release terminal")
        if (
            closure.provider_request_sha256 != call.provider_request_sha256
            or closure.source_family != call.source_family
            or closure.endpoint_id != call.endpoint_id
            or closure.scope_sha256 != call.scope_sha256
        ):
            raise ValueError("request closure observation differs from the manifested call")
        if (
            closure.attempt_count != len(attempts)
            or closure.attempt_count != selected_observation.attempt.retry_ordinal + 1
        ):
            raise ValueError("request closure attempt count differs from raw retry authority")
        expected_outcome = (
            "success_nonempty" if closure.state == "success_nonempty" else "success_empty"
        )
        if selected_observation.outcome != expected_outcome:
            raise ValueError("request closure state differs from raw terminal outcome")

        body_sha256 = selected_observation.body_object_sha256
        if body_sha256 is None:
            raise ValueError("successful HTTP closure lacks its raw parser-input object")
        body_row = self._conn.execute(
            "SELECT response_sha256, uncompressed_bytes "
            "FROM raw_nba_api_parser_input_object WHERE object_sha256 = ?",
            [body_sha256],
        ).fetchone()
        if (
            body_row is None
            or closure.response_body_sha256 != body_row[0]
            or closure.parser_input_sha256 != body_row[0]
            or closure.response_body_bytes != body_row[1]
        ):
            raise ValueError("request closure body receipt differs from raw parser input")
        status_code = getattr(selected_observation.transport, "status_code", None)
        effective_status = getattr(
            selected_observation.transport,
            "effective_status_code",
            None,
        )
        if closure.http_status != status_code or closure.http_status != effective_status:
            raise ValueError("request closure HTTP status differs from raw transport evidence")

        route_by_id = {item.route_id: item for item in closure_receipt.route_manifest.routes}
        try:
            closure_routes = tuple(route_by_id[item] for item in closure.route_ids)
        except KeyError as exc:
            raise ValueError("request closure observation references a foreign route") from exc
        parameter_digests = {
            canonical_parameters_sha256(item.parameter_mapping) for item in closure_routes
        }
        if (
            call.provider_parameters_sha256 is None
            or parameter_digests != {call.provider_parameters_sha256}
            or {item.source_family for item in closure_routes} != {call.source_family}
            or {item.endpoint_id for item in closure_routes} != {call.endpoint_id}
        ):
            raise ValueError("request closure provider parameters or endpoint differ")

        landing_by_route = {item.route_id: item for item in selected_landings}
        if len(landing_by_route) != len(selected_landings):
            raise ValueError("request closure route denominator differs from raw landings")
        try:
            call.validate_terminal_route_ids(tuple(sorted(landing_by_route)))
        except ValueError as exc:
            raise ValueError("request closure route denominator differs from raw landings") from exc

        staging_by_ordinal = {item.result_set_ordinal: item for item in closure.staging_receipts}
        raw_by_ordinal = {
            item.provider_result_ordinal: item
            for item in selected_occurrences
            if item.provider_result_ordinal is not None
        }
        if len(raw_by_ordinal) != len(selected_occurrences):
            raise ValueError("raw result occurrences lack unique provider ordinals")
        if set(raw_by_ordinal) != {item.ordinal for item in closure.result_sets}:
            raise ValueError("request closure result inventory differs from raw occurrences")
        physical_routes: set[str] = set()
        for result in closure.result_sets:
            occurrence = raw_by_ordinal[result.ordinal]
            if (
                occurrence.result_name != result.result_set_name
                or self._closure_occurrence_state(occurrence) != result.occurrence_state
                or occurrence.row_count != (0 if result.row_count is None else result.row_count)
                or (
                    result.ordered_columns_sha256 is not None
                    and occurrence.ordered_headers_sha256 != result.ordered_columns_sha256
                )
                or (
                    result.result_set_payload_sha256 is not None
                    and occurrence.output_sha256 != result.result_set_payload_sha256
                )
            ):
                raise ValueError("request closure result receipt differs from raw occurrence")
            staging = staging_by_ordinal.get(result.ordinal)
            if result.occurrence_state == "absent_optional":
                if staging is not None:
                    raise ValueError("absent closure result claims a staging receipt")
                continue
            if staging is None or (
                staging.result_set_name != result.result_set_name
                or staging.row_count != result.row_count
                or staging.result_set_payload_sha256 != result.result_set_payload_sha256
            ):
                raise ValueError("request closure staging receipt differs from its result")
            physical_route = (
                f"{call.endpoint_name}:{staging.staging_key}:{staging.result_set_ordinal}"
            )
            physical_routes.add(physical_route)
            raw_routes = occurrence.canonical_route_ids()
            raw_receipts = occurrence.committed_staging_receipts_by_route()
            landing = landing_by_route.get(physical_route)
            if (
                physical_route not in raw_routes
                or raw_receipts.get(physical_route) != staging.staging_receipt_root_sha256
                or landing is None
                or landing.receipt_root_sha256 != staging.staging_receipt_root_sha256
            ):
                raise ValueError("request closure route receipt differs from raw landing")
        if not physical_routes.issubset(landing_by_route):
            raise ValueError("request closure physical route lacks a raw landing")

    def _verify_terminal_raw_manifest(
        self,
        manifest: object,
        *,
        closure_receipt: RequestClosureRuntimeReceipt | None,
        closure_by_provider: Mapping[str, object],
        seen_closure_providers: set[str],
        static_endpoint_counts: dict[str, int],
    ) -> tuple[int, int, int]:
        """Verify one latest manifest and join each planned call exactly once."""

        from nbadb.orchestrate.raw_request_manifest import RawRequestAuthorityManifestV2

        if type(manifest) is not RawRequestAuthorityManifestV2:
            raise ValueError("latest raw manifest has a foreign contract")
        if (
            not manifest.terminal_sealed
            or not manifest.coverage_complete
            or not manifest.is_complete
            or manifest.expected_request_count <= 0
            or manifest.expected_request_count != manifest.completed_request_count
            or manifest.unresolved_request_count != 0
            or manifest.unresolved_request_sha256s
            or manifest.expected_request_sha256s != manifest.completed_request_sha256s
        ):
            raise ValueError("latest raw manifest is not terminal-sealed and complete")

        for receipt in manifest.receipts:
            self._verify_raw_bundle_receipt(receipt)
        attempts_by_provider: dict[str, list[RawRequestPersistedAttemptV2]] = {
            call.provider_request_sha256: [] for call in manifest.expected_calls
        }
        for receipt in manifest.receipts:
            for attempt in receipt.attempts:
                attempts_by_provider[attempt.provider_request_sha256].append(attempt)

        selected_count = 0
        attempt_count = 0
        for call in manifest.expected_calls:
            if any(route_id.rsplit(":", 2)[0] != call.endpoint_name for route_id in call.route_ids):
                raise ValueError("manifested physical route differs from its logical endpoint")
            if call.source_family == "static":
                static_endpoint_counts[call.endpoint_id] = (
                    static_endpoint_counts.get(call.endpoint_id, 0) + 1
                )
                if call.provider_parameters_sha256 != call.logical_parameters_sha256:
                    raise ValueError("static manifested call invented provider parameters")
            attempts = tuple(
                sorted(
                    attempts_by_provider[call.provider_request_sha256],
                    key=lambda item: (item.retry_ordinal, item.request_ordinal),
                )
            )
            selected = tuple(item for item in attempts if item.lifecycle == "selected_terminal")
            if len(selected) != 1:
                raise ValueError("manifested provider request lacks one terminal raw attempt")
            selected_attempt = selected[0]
            selected_observation: RequestObservationV2 | None = None
            selected_occurrences: tuple[ResultOccurrenceV2, ...] | None = None
            selected_landings: tuple[ObservationRouteLandingV2, ...] | None = None
            for attempt in attempts:
                observation, occurrences, landings = self._load_manifest_attempt_observation(
                    attempt,
                    manifest=manifest,
                    expected_call=call,
                )
                attempt_count += 1
                if attempt is selected_attempt:
                    selected_observation = observation
                    selected_occurrences = occurrences
                    selected_landings = landings
            if (
                selected_observation is None
                or selected_occurrences is None
                or selected_landings is None
            ):
                raise ValueError("terminal raw observation disappeared during exact join")
            selected_count += 1
            if call.source_family == "static":
                if (
                    selected_observation.outcome != "static_snapshot_success"
                    or selected_observation.body_disposition != "declared_bodyless"
                    or selected_observation.body_object_sha256 is not None
                    or selected_observation.attempt.provider_call_role != "static_snapshot"
                ):
                    raise ValueError("static closure call lacks exact bodyless terminal evidence")
                continue
            if closure_receipt is None:
                raise ValueError("non-static raw manifest has no verified closure receipt")
            closure_observation = closure_by_provider.get(call.provider_request_sha256)
            if closure_observation is None:
                raise ValueError("raw manifest request is absent from request closure")
            self._verify_request_closure_call_join(
                call=call,
                attempts=cast("tuple[object, ...]", attempts),
                selected_observation=selected_observation,
                selected_occurrences=selected_occurrences,
                selected_landings=selected_landings,
                closure_observation=closure_observation,
                closure_receipt=closure_receipt,
            )
            seen_closure_providers.add(call.provider_request_sha256)
        return len(manifest.expected_calls), attempt_count, selected_count

    def _check_full_publication_request_authority_join(
        self,
        closure_receipt: RequestClosureRuntimeReceipt | None,
    ) -> None:
        """Exact-join terminal raw manifests, bundles, rows, and request closure."""

        from nbadb.orchestrate.raw_request_manifest import (
            parse_raw_request_authority_manifest,
            validate_raw_request_authority_manifest_roll_forward,
        )

        self._report.checks_run += 1
        stage = "journal_schema"
        chain_count = 0
        manifest_row_count = 0
        expected_call_count = 0
        attempt_count = 0
        selected_attempt_count = 0
        static_endpoint_counts: dict[str, int] = {}
        closure_by_provider = (
            {}
            if closure_receipt is None
            else {item.provider_request_sha256: item for item in closure_receipt.observations}
        )
        seen_closure_providers: set[str] = set()
        manifest_inventory = hashlib.sha256()
        manifest_inventory.update(b"nbadb-raw-terminal-manifest-inventory-v1\0")
        try:
            self._validate_raw_authority_journal_schemas()
            stage = "global_relations"
            self._raw_authority_join_sql_invariants()
            stage = "manifest_chain"
            select_columns = (
                "manifest_sha256, source_sha, run_id, run_attempt, chain_id, lane_id, "
                "scope_sha256, generation, parent_manifest_sha256, "
                "route_authority_sha256, request_closure_authority_sha256, "
                "field_authority_sha256, model_authority_sha256, authority_set_sha256, "
                "receipt_count, receipt_inventory_sha256, canonical_json"
            )
            order_columns = (
                "source_sha, run_id, run_attempt, chain_id, lane_id, generation, manifest_sha256"
            )
            last_order: tuple[object, ...] | None = None
            current_execution: tuple[object, ...] | None = None
            previous_manifest = None

            def finish_execution() -> None:
                nonlocal chain_count
                nonlocal expected_call_count
                nonlocal attempt_count
                nonlocal selected_attempt_count
                if previous_manifest is None:
                    return
                stage_counts = self._verify_terminal_raw_manifest(
                    previous_manifest,
                    closure_receipt=closure_receipt,
                    closure_by_provider=closure_by_provider,
                    seen_closure_providers=seen_closure_providers,
                    static_endpoint_counts=static_endpoint_counts,
                )
                chain_count += 1
                expected_call_count += stage_counts[0]
                attempt_count += stage_counts[1]
                selected_attempt_count += stage_counts[2]
                manifest_inventory.update(previous_manifest.manifest_sha256.encode("ascii"))
                manifest_inventory.update(b"\n")

            while True:
                if last_order is None:
                    rows = self._conn.execute(
                        f"SELECT {select_columns} "
                        "FROM _raw_request_authority_manifest_journal "
                        f"ORDER BY {order_columns} LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}"
                    ).fetchall()
                else:
                    rows = self._conn.execute(
                        f"SELECT {select_columns} "
                        "FROM _raw_request_authority_manifest_journal "
                        "WHERE (source_sha, run_id, run_attempt, chain_id, lane_id, "
                        "generation, manifest_sha256) > (?, ?, ?, ?, ?, ?, ?) "
                        f"ORDER BY {order_columns} LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}",
                        list(last_order),
                    ).fetchall()
                if not rows:
                    break
                for row in rows:
                    if len(row) != 17 or type(row[16]) is not str:
                        raise ValueError("raw manifest journal row is malformed")
                    manifest = parse_raw_request_authority_manifest(row[16].encode("utf-8"))
                    projected = (
                        manifest.manifest_sha256,
                        manifest.source_sha,
                        manifest.run_id,
                        manifest.run_attempt,
                        manifest.chain_id,
                        manifest.lane_id,
                        manifest.scope_sha256,
                        manifest.generation,
                        manifest.parent_manifest_sha256,
                        manifest.route_authority_sha256,
                        manifest.request_closure_authority_sha256,
                        manifest.field_authority_sha256,
                        manifest.model_authority_sha256,
                        manifest.authority_set_sha256,
                        manifest.receipt_count,
                        manifest.receipt_inventory_sha256,
                        manifest.canonical_bytes.decode("utf-8"),
                    )
                    if tuple(row) != projected:
                        raise ValueError("raw manifest journal columns differ from canonical bytes")
                    execution = (
                        manifest.source_sha,
                        manifest.run_id,
                        manifest.run_attempt,
                        manifest.chain_id,
                        manifest.lane_id,
                    )
                    if execution != current_execution:
                        finish_execution()
                        current_execution = execution
                        previous_manifest = None
                    if previous_manifest is None:
                        if manifest.generation != 0:
                            raise ValueError("raw manifest chain does not begin at generation zero")
                    else:
                        if previous_manifest.terminal_sealed:
                            raise ValueError("raw manifest has a generation after terminal sealing")
                        validate_raw_request_authority_manifest_roll_forward(
                            previous_manifest,
                            manifest,
                        )
                    previous_manifest = manifest
                    manifest_row_count += 1
                    last_order = (
                        manifest.source_sha,
                        manifest.run_id,
                        manifest.run_attempt,
                        manifest.chain_id,
                        manifest.lane_id,
                        manifest.generation,
                        manifest.manifest_sha256,
                    )
            finish_execution()
            if manifest_row_count <= 0 or chain_count <= 0:
                raise ValueError("raw authority has no complete manifest chain")

            stage = "authority_denominator"
            from nbadb.core.nba_api_request_surface import pinned_request_surface_authority

            expected_static_endpoints = {
                item.dataset_id for item in pinned_request_surface_authority().static_datasets
            }
            if set(static_endpoint_counts) != expected_static_endpoints or any(
                count != 1 for count in static_endpoint_counts.values()
            ):
                raise ValueError("terminal raw manifests do not exactly cover four static roots")
            if set(closure_by_provider) != seen_closure_providers:
                raise ValueError("request closure contains an extra or unjoined provider request")
            if expected_call_count != selected_attempt_count:
                raise ValueError("terminal raw selection count differs from planned requests")
        except Exception as exc:
            logger.error(
                "scanner: raw request-authority join failed at {}: {}",
                stage,
                type(exc).__name__,
            )
            self._add(
                ScanFinding(
                    category=ScanCategory.DATA_QUALITY,
                    severity=ScanSeverity.ERROR,
                    table="raw_request_authority",
                    check="raw_authority_manifest_join_failed",
                    message=(
                        "Full-publication raw authority failed its exact manifest/closure "
                        f"join at {stage}: {type(exc).__name__}: {exc}"
                    ),
                    details={
                        "verification_stage": stage,
                        "error_type": type(exc).__name__,
                        "manifest_row_count": manifest_row_count,
                        "manifest_chain_count": chain_count,
                        "expected_call_count": expected_call_count,
                        "attempt_count": attempt_count,
                        "selected_attempt_count": selected_attempt_count,
                        "static_endpoint_counts": dict(sorted(static_endpoint_counts.items())),
                    },
                )
            )
            return
        self._report.evidence["raw_request_manifest_join"] = {
            "evidence_code": "raw_request_manifest_closure_join_verified",
            "manifest_row_count": manifest_row_count,
            "manifest_chain_count": chain_count,
            "terminal_manifest_inventory_sha256": manifest_inventory.hexdigest(),
            "expected_call_count": expected_call_count,
            "attempt_count": attempt_count,
            "selected_attempt_count": selected_attempt_count,
            "static_endpoint_counts": dict(sorted(static_endpoint_counts.items())),
            "request_closure_observation_count": len(closure_by_provider),
        }

    def _raw_authority_bundle_sha256(self) -> str:
        """Hash the exact canonical bundle identity with bounded keyset pages."""

        digest = hashlib.sha256()
        inventories = (
            (
                b'{"landing_sha256s":[',
                "raw_nba_api_observation_route_landing",
                "landing_sha256",
            ),
            (
                b'],"object_sha256s":[',
                "raw_nba_api_parser_input_object",
                "object_sha256",
            ),
            (
                b'],"observation_record_sha256s":[',
                "raw_nba_api_request_observation",
                "observation_record_sha256",
            ),
            (
                b'],"occurrence_sha256s":[',
                "raw_nba_api_result_occurrence",
                "occurrence_sha256",
            ),
        )
        for prefix, table_name, key_column in inventories:
            digest.update(prefix)
            last_key: str | None = None
            emitted = 0
            while True:
                if last_key is None:
                    rows = self._conn.execute(
                        f'SELECT "{key_column}" FROM "{table_name}" '
                        f'ORDER BY "{key_column}" LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}'
                    ).fetchall()
                else:
                    rows = self._conn.execute(
                        f'SELECT "{key_column}" FROM "{table_name}" '
                        f'WHERE "{key_column}" > ? ORDER BY "{key_column}" '
                        f"LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}",
                        [last_key],
                    ).fetchall()
                if not rows:
                    break
                for (raw_value,) in rows:
                    value = str(raw_value)
                    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                        raise ValueError("raw authority bundle contains an invalid identity")
                    if emitted:
                        digest.update(b",")
                    digest.update(b'"')
                    digest.update(value.encode("ascii"))
                    digest.update(b'"')
                    emitted += 1
                    last_key = value
        digest.update(b'],"schema_version":2}')
        return digest.hexdigest()

    def _validate_raw_authority_sql_relations(self) -> None:
        """Prove global bundle invariants with bounded scalar SQL results."""

        scalar_failures = (
            (
                "raw authority parser-input keys are not unique",
                "SELECT COUNT(*) - COUNT(DISTINCT object_sha256) "
                "FROM raw_nba_api_parser_input_object",
            ),
            (
                "raw authority observation keys are not unique",
                "SELECT COUNT(*) - COUNT(DISTINCT observation_sha256) "
                "FROM raw_nba_api_request_observation",
            ),
            (
                "raw authority occurrence keys are not unique",
                "SELECT COUNT(*) - COUNT(DISTINCT occurrence_sha256) "
                "FROM raw_nba_api_result_occurrence",
            ),
            (
                "raw authority route-landing keys are not unique",
                "SELECT COUNT(*) - COUNT(DISTINCT landing_sha256) "
                "FROM raw_nba_api_observation_route_landing",
            ),
            (
                "raw authority observation references a missing parser-input object",
                "SELECT COUNT(*) FROM raw_nba_api_request_observation o "
                "LEFT JOIN raw_nba_api_parser_input_object b "
                "ON b.object_sha256 = o.body_object_sha256 "
                "WHERE o.body_object_sha256 IS NOT NULL AND b.object_sha256 IS NULL",
            ),
            (
                "raw authority contains an orphan parser-input object",
                "SELECT COUNT(*) FROM raw_nba_api_parser_input_object b "
                "LEFT JOIN (SELECT DISTINCT body_object_sha256 "
                "FROM raw_nba_api_request_observation "
                "WHERE body_object_sha256 IS NOT NULL) o "
                "ON o.body_object_sha256 = b.object_sha256 "
                "WHERE o.body_object_sha256 IS NULL",
            ),
            (
                "raw authority occurrence references a missing observation",
                "SELECT COUNT(*) FROM raw_nba_api_result_occurrence r "
                "LEFT JOIN raw_nba_api_request_observation o "
                "ON o.observation_sha256 = r.observation_sha256 "
                "WHERE o.observation_sha256 IS NULL",
            ),
            (
                "raw authority route landing references a missing observation",
                "SELECT COUNT(*) FROM raw_nba_api_observation_route_landing l "
                "LEFT JOIN raw_nba_api_request_observation o "
                "ON o.observation_sha256 = l.observation_sha256 "
                "WHERE o.observation_sha256 IS NULL",
            ),
            (
                "raw authority observation route-landing counts differ",
                "SELECT COUNT(*) FROM ("
                "SELECT o.observation_sha256, o.route_landing_count, COUNT(l.landing_sha256) "
                "AS observed_count FROM raw_nba_api_request_observation o "
                "LEFT JOIN raw_nba_api_observation_route_landing l "
                "ON l.observation_sha256 = o.observation_sha256 "
                "GROUP BY o.observation_sha256, o.route_landing_count "
                "HAVING o.route_landing_count <> COUNT(l.landing_sha256)"
                ") invalid",
            ),
            (
                "raw authority provider call lacks exactly one terminal selection",
                "SELECT COUNT(*) FROM ("
                "SELECT provider_call_sha256 FROM raw_nba_api_request_observation "
                "GROUP BY provider_call_sha256 "
                "HAVING SUM(CASE WHEN lifecycle = 'selected_terminal' THEN 1 ELSE 0 END) <> 1"
                ") invalid",
            ),
            (
                "raw authority repeats one provider-call retry ordinal",
                "SELECT COUNT(*) FROM ("
                "SELECT provider_call_sha256, retry_ordinal "
                "FROM raw_nba_api_request_observation "
                "GROUP BY provider_call_sha256, retry_ordinal HAVING COUNT(*) <> 1"
                ") invalid",
            ),
        )
        for message, query in scalar_failures:
            row = self._conn.execute(query).fetchone()
            if row is None or type(row[0]) is not int or row[0] != 0:
                raise ValueError(message)

    @staticmethod
    def _decode_raw_observation_row(
        row: dict[str, object],
    ) -> RequestObservationV2:
        from nbadb.contracts.raw_request_authority import (
            RequestAttemptIdentityV2,
            RequestObservationV2,
            validate_request_observation,
        )

        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        for field_name in ("started_at", "finished_at"):
            epoch_us = row[field_name]
            if epoch_us is not None:
                if type(epoch_us) is not int:
                    raise ValueError("raw authority timestamp epoch is not an exact integer")
                row[field_name] = epoch + timedelta(microseconds=epoch_us)
        attempt_fields = tuple(RequestAttemptIdentityV2.model_fields)
        observation_fields = tuple(RequestObservationV2.model_fields)
        attempt_payload = {field_name: row[field_name] for field_name in attempt_fields}
        transport_kind = row["transport_kind"]
        if transport_kind == "static_snapshot":
            if row["status_code"] is not None or row["effective_status_code"] is not None:
                raise ValueError("static raw observation contains HTTP status evidence")
            transport_payload: dict[str, object] = {"transport_kind": transport_kind}
        else:
            transport_payload = {
                "transport_kind": transport_kind,
                "status_code": row["status_code"],
                "effective_status_code": row["effective_status_code"],
            }
        observation_payload = {
            field_name: row[field_name]
            for field_name in observation_fields
            if field_name not in {"attempt", "transport"}
        }
        observation_payload["attempt"] = attempt_payload
        observation_payload["transport"] = transport_payload
        return validate_request_observation(observation_payload)

    @staticmethod
    def _decode_raw_landing_row(
        row: dict[str, object],
    ) -> ObservationRouteLandingV2:
        from nbadb.contracts.raw_request_authority import (
            validate_observation_route_landing,
        )

        materialized = dict(row)
        epoch_us = materialized["live_snapshot_at"]
        if epoch_us is not None:
            if type(epoch_us) is not int:
                raise ValueError("raw route-landing timestamp epoch is not an exact integer")
            materialized["live_snapshot_at"] = datetime(
                1970,
                1,
                1,
                tzinfo=UTC,
            ) + timedelta(microseconds=epoch_us)
        return validate_observation_route_landing(materialized)

    @staticmethod
    def _rederived_presence_fields(
        derived: RawAuthorityResultSetDerivation,
    ) -> tuple[ResultPresence, tuple[str, ...], int, int, int, int, int, int]:
        """Project a parser receipt through the exact public occurrence rules."""

        receipt = derived.result_set
        headers = derived.ordered_headers
        present_containers = receipt.container_count
        missing = receipt.missing_count
        nulls = receipt.null_count
        if present_containers == 0:
            if receipt.parent_observation_count == 0:
                return ("not_observed_parent_empty", headers, 0, 0, 0, 0, 0, 0)
            if missing > 0 and nulls == 0:
                return ("missing", (), 0, 0, 0, 0, missing, 0)
            if nulls > 0 and missing == 0:
                return ("null", (), 0, 0, nulls, nulls, 0, nulls)
            if missing > 0 and nulls > 0:
                return ("mixed_absent", (), 0, 0, nulls, nulls, missing, nulls)
            raise ValueError("rederived result lacks one exact absence state")
        row_count = receipt.row_count
        container_count = present_containers + nulls
        if row_count > 0:
            return (
                "present",
                headers,
                row_count,
                row_count * len(headers),
                0 if receipt.container_kind == "nba_api_result_set" else row_count,
                container_count,
                missing,
                nulls,
            )
        if receipt.container_kind == "nba_api_result_set":
            return ("present_empty", headers, 0, 0, 0, container_count, missing, nulls)
        if (
            receipt.container_kind in {"nba_api_live_json_array", "nba_api_static_records"}
            and present_containers == 1
            and missing == 0
            and nulls == 0
        ):
            return ("empty_array", (), 0, 0, 1, 1, 0, 0)
        return (
            "present",
            headers,
            0,
            0,
            present_containers,
            container_count,
            missing,
            nulls,
        )

    @classmethod
    def _compare_rederived_occurrence(
        cls,
        observation: RequestObservationV2,
        occurrence: ResultOccurrenceV2,
        derived: RawAuthorityResultSetDerivation,
    ) -> None:
        from nbadb.contracts.raw_request_authority import ResultOccurrenceV2

        (
            presence,
            headers,
            row_count,
            cell_count,
            node_count,
            container_count,
            missing_count,
            null_count,
        ) = cls._rederived_presence_fields(derived)
        receipt = derived.result_set
        route_ids = json.loads(occurrence.canonical_route_ids_json)
        committed_receipts = json.loads(occurrence.committed_staging_receipts_json)
        expected = ResultOccurrenceV2.build(
            observation_sha256=observation.attempt.observation_sha256,
            occurrence_ordinal=occurrence.occurrence_ordinal,
            result_name=receipt.name,
            duplicate_name_ordinal=derived.duplicate_name_ordinal,
            provider_result_ordinal=receipt.provider_index,
            canonical_result_ordinal=receipt.canonical_index,
            json_path="$" if observation.attempt.source_family == "static" else receipt.json_path,
            container_kind=cast("ResultContainerKind", receipt.container_kind),
            presence=presence,
            ordered_headers=headers,
            row_count=row_count,
            cell_count=cell_count,
            node_count=node_count,
            container_count=container_count,
            missing_count=missing_count,
            null_count=null_count,
            parent_state_sha256=receipt.parent_occurrence_states_sha256,
            output_sha256=receipt.normalized_output_sha256,
            canonical_route_ids=route_ids,
            committed_staging_receipts=committed_receipts,
            landing_disposition=occurrence.landing_disposition,
        )
        logical_fields = (
            "observation_sha256",
            "occurrence_ordinal",
            "result_name",
            "duplicate_name_ordinal",
            "provider_result_ordinal",
            "canonical_result_ordinal",
            "json_path",
            "container_kind",
            "presence",
            "ordered_headers_json",
            "ordered_headers_sha256",
            "header_count",
            "row_count",
            "cell_count",
            "node_count",
            "container_count",
            "missing_count",
            "null_count",
            "parent_state_sha256",
            "output_sha256",
            "logical_result_receipt_sha256",
        )
        if any(getattr(occurrence, name) != getattr(expected, name) for name in logical_fields):
            raise ValueError("stored result occurrence differs from parser-derived authority")

    @staticmethod
    def _compare_rederived_stats_route_membership(
        observation: RequestObservationV2,
        occurrences: tuple[ResultOccurrenceV2, ...],
        derivations: tuple[RawAuthorityResultSetDerivation, ...],
        parser_input: bytes,
    ) -> tuple[int, bool]:
        """Rebuild fallback occurrence routes without trusting stored membership.

        Strict-wide route membership is closed again by the request-closure join.
        A stats fallback additionally needs its body-derived safe-wide partition
        before an occurrence can claim either ``wide_plus_lossless`` or
        ``lossless_only``.  The conditional route fixes the logical endpoint
        alias selected by the call; every other route is then resolved against
        the immutable staging-route bundle.

        The fourth response-level landing table closes unknown Video fixed-zero
        and canonical-alias policy through the bundle reconstruction.  This
        occurrence-local pass therefore never reports that policy as unverified.
        """

        from nbadb.contracts.staging_route_contract import (
            conditional_staging_key_from_route_id,
            staging_route_contract_bundle,
        )
        from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
        from nbadb.extract.nba_api_adapter import rederive_raw_authority_stats_wide_rows
        from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY

        if observation.attempt.source_family != "stats" or not derivations:
            return 0, False
        contract = pinned_runtime_contracts().get(observation.attempt.endpoint_id)
        if contract is None:
            raise ValueError("stats route membership lacks its pinned endpoint contract")
        unknown_response = contract.response_mode == "unknown_dynamic_response"
        fallback = unknown_response or any(
            item.result_set.canonical_index is None for item in derivations
        )
        if not fallback:
            return 0, False

        claimed_route_ids = tuple(
            route_id for occurrence in occurrences for route_id in occurrence.canonical_route_ids()
        )
        conditional_ids = tuple(
            sorted(
                {
                    route_id
                    for route_id in claimed_route_ids
                    if conditional_staging_key_from_route_id(route_id)
                    == LOSSLESS_FALLBACK_STAGING_KEY
                }
            )
        )
        if len(conditional_ids) != 1:
            raise ValueError("stats fallback lacks one exact conditional route")
        conditional_route_id = conditional_ids[0]
        endpoint_name, staging_key, raw_result_index = conditional_route_id.rsplit(":", 2)
        if (
            not endpoint_name
            or staging_key != LOSSLESS_FALLBACK_STAGING_KEY
            or raw_result_index != str(len(contract.result_sets))
        ):
            raise ValueError("stats fallback conditional route differs from its pinned identity")

        route_bundle = staging_route_contract_bundle()
        static_routes = tuple(
            route
            for route in route_bundle.routes
            if route.source_family == "stats"
            and route.endpoint_name == endpoint_name
            and route.provider_endpoint_id == observation.attempt.endpoint_id
        )
        if not static_routes or any(
            route.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
            or route.provider_authority_sha256 != observation.attempt.provider_authority_sha256
            for route in static_routes
        ):
            raise ValueError("stats fallback routes differ from pinned endpoint authority")

        declared_by_result: dict[int, list[str]] = {index: [] for index in range(len(derivations))}
        wide_by_result: dict[int, list[str]] = {index: [] for index in range(len(derivations))}

        if not unknown_response:
            for route in static_routes:
                identity_indexes: list[int] = []
                for result_index, derived in enumerate(derivations):
                    receipt = derived.result_set
                    if route.provider_result_set_name != receipt.name:
                        continue
                    if receipt.canonical_index is not None:
                        matches = route.canonical_result_set_ordinal == receipt.canonical_index
                    elif route.canonical_result_set_ordinal < len(contract.result_sets):
                        expected = contract.result_sets[route.canonical_result_set_ordinal]
                        duplicate_ordinal = sum(
                            prior.result_set_name == expected.result_set_name
                            for prior in contract.result_sets[: route.canonical_result_set_ordinal]
                        )
                        matches = (
                            expected.result_set_name == receipt.name
                            and derived.duplicate_name_ordinal == duplicate_ordinal
                        )
                    else:
                        matches = False
                    if matches:
                        identity_indexes.append(result_index)
                if len(identity_indexes) != 1:
                    raise ValueError("stats fallback pinned route has no unique result occurrence")
                declared_by_result[identity_indexes[0]].append(route.route_id)

            safe_rows = rederive_raw_authority_stats_wide_rows(
                endpoint_id=observation.attempt.endpoint_id,
                parser_input=parser_input,
                provider_authority_sha256=(observation.attempt.provider_authority_sha256),
                endpoint_contract_sha256_value=(observation.attempt.endpoint_contract_sha256),
            )
            for route in static_routes:
                candidates = tuple(
                    item
                    for item in safe_rows
                    if item.result_set.name == route.provider_result_set_name
                    and item.result_set.canonical_index == route.canonical_result_set_ordinal
                    and item.ordered_headers == route.provider_columns
                )
                if not candidates:
                    if safe_rows:
                        raise ValueError("stats safe-wide authority omits a pinned staging route")
                    continue
                if len(candidates) != 1:
                    raise ValueError("stats safe-wide route membership is ambiguous")
                candidate = candidates[0]
                matching_indexes = tuple(
                    index
                    for index, derived in enumerate(derivations)
                    if derived.result_set.name == candidate.result_set.name
                    and derived.result_set.provider_index == candidate.result_set.provider_index
                    and derived.ordered_headers == candidate.ordered_headers
                    and derived.result_set.row_count == candidate.result_set.row_count
                )
                if len(matching_indexes) != 1:
                    raise ValueError("stats safe-wide packet lacks one exact fallback occurrence")
                wide_by_result[matching_indexes[0]].append(route.route_id)

        for result_index, occurrence in enumerate(occurrences):
            expected_routes = tuple(
                sorted((*declared_by_result[result_index], conditional_route_id))
            )
            expected_landing = (
                "wide_plus_lossless" if wide_by_result[result_index] else "lossless_only"
            )
            committed_routes = tuple(occurrence.committed_staging_receipts_by_route())
            if (
                occurrence.canonical_route_ids() != expected_routes
                or committed_routes != expected_routes
                or occurrence.landing_disposition != expected_landing
            ):
                raise ValueError(
                    "stored stats fallback route membership differs from body-derived authority"
                )
        return len(occurrences), False

    @staticmethod
    def _validate_raw_observation_outcome(
        observation: RequestObservationV2,
        occurrences: tuple[ResultOccurrenceV2, ...],
        landings: tuple[ObservationRouteLandingV2, ...],
    ) -> None:
        """Preserve the bundle's exact success/outcome reconciliation per page."""

        has_nonempty = any(
            item.presence == "present" and (item.row_count > 0 or item.node_count > 0)
            for item in occurrences
        )
        if observation.outcome == "success_nonempty" and not has_nonempty:
            raise ValueError("success-nonempty observation has no nonempty result")
        if observation.outcome == "success_empty":
            empty_states = {"present_empty", "empty_object", "empty_array"}
            response_fixed_zero = (
                not occurrences
                and bool(landings)
                and all(
                    item.landing_semantic == "response_fixed_zero" and item.persisted_row_count == 0
                    for item in landings
                )
            )
            if (
                not response_fixed_zero
                and not any(item.presence in empty_states for item in occurrences)
            ) or has_nonempty:
                raise ValueError("success-empty observation has inconsistent result evidence")

    def _check_private_raw_authority_reconstruction(self) -> None:
        """Page and independently reparse all fixed private raw authority rows."""

        from nbadb.contracts.raw_request_authority import (
            canonical_json_bytes,
            validate_observation_route_landing,
            validate_parser_input_object,
            validate_result_occurrence,
        )
        from nbadb.contracts.raw_request_reconstruction import (
            reconstruct_raw_request_authority,
        )
        from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
        from nbadb.extract.nba_api_adapter import (
            RawAuthorityResultSetDerivation,
            rederive_raw_authority_result_sets,
            rederive_raw_authority_unknown_stats_response,
            validate_raw_authority_contract_identity,
        )

        self._report.checks_run += 1
        stage = "schema"
        bundle_sha256: str | None = None
        table_row_counts: dict[str, int] = {}
        verified_observation_count = 0
        parsed_body_count = 0
        bodyless_observation_count = 0
        result_packet_count = 0
        parent_empty_packet_count = 0
        object_count = 0
        observation_count = 0
        occurrence_count = 0
        landing_count = 0
        route_landing_count = 0
        stats_route_membership_verified_count = 0
        video_alias_policy_unverified_observation_count = 0

        try:
            entries = raw_request_authority_private_tables()
            expected_names = set(PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES)
            if {entry.table_name for entry in entries} != expected_names:
                raise ValueError("raw authority registry differs from its fixed model")

            columns_by_table: dict[str, list[str]] = {}
            for entry in entries:
                expected_columns = list(entry.schema_type.to_schema().columns)
                observed_columns = [
                    str(row[0])
                    for row in self._conn.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'main' AND table_name = $1 "
                        "ORDER BY ordinal_position",
                        [entry.table_name],
                    ).fetchall()
                ]
                if observed_columns != expected_columns:
                    raise ValueError("raw authority table schema is not exact")
                columns_by_table[entry.table_name] = expected_columns
                count_row = self._conn.execute(
                    f'SELECT COUNT(*) FROM "{entry.table_name}"'
                ).fetchone()
                if count_row is None or type(count_row[0]) is not int or count_row[0] < 0:
                    raise ValueError("raw authority table count is invalid")
                table_row_counts[entry.table_name] = count_row[0]

            self._report.tables_scanned += len(entries)
            stage = "rows"
            object_count = table_row_counts["raw_nba_api_parser_input_object"]
            observation_count = table_row_counts["raw_nba_api_request_observation"]
            occurrence_count = table_row_counts["raw_nba_api_result_occurrence"]
            landing_count = table_row_counts["raw_nba_api_observation_route_landing"]
            if observation_count <= 0 or landing_count <= 0:
                raise ValueError("full publication raw authority contains no observations")
            stage = "bundle"
            self._validate_raw_authority_sql_relations()
            bundle_sha256 = self._raw_authority_bundle_sha256()

            reconstruction_inventory = _OrderedRawAuthorityInventoryHasher(observation_count)
            body_receipt_inventory = _OrderedRawAuthorityInventoryHasher(observation_count)
            packet_inventory = _OrderedRawAuthorityInventoryHasher(occurrence_count)
            occurrence_route_receipt_inventory = _OrderedRawAuthorityInventoryHasher(
                occurrence_count
            )
            route_landing_inventory = _OrderedRawAuthorityInventoryHasher(landing_count)

            observation_columns = columns_by_table["raw_nba_api_request_observation"]
            occurrence_columns = columns_by_table["raw_nba_api_result_occurrence"]
            object_columns = columns_by_table["raw_nba_api_parser_input_object"]
            landing_columns = columns_by_table["raw_nba_api_observation_route_landing"]
            observation_selection = ", ".join(
                (
                    f'epoch_us("{name}") AS "{name}"'
                    if name in {"started_at", "finished_at"}
                    else f'"{name}"'
                )
                for name in observation_columns
            )
            occurrence_selection = ", ".join(f'"{name}"' for name in occurrence_columns)
            object_selection = ", ".join(f'"{name}"' for name in object_columns)
            landing_selection = ", ".join(
                (f'epoch_us("{name}") AS "{name}"' if name == "live_snapshot_at" else f'"{name}"')
                for name in landing_columns
            )
            last_observation: str | None = None
            while True:
                if last_observation is None:
                    observation_rows = self._conn.execute(
                        f"SELECT {observation_selection} "
                        'FROM "raw_nba_api_request_observation" '
                        'ORDER BY "observation_sha256" '
                        f"LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}"
                    ).fetchall()
                else:
                    observation_rows = self._conn.execute(
                        f"SELECT {observation_selection} "
                        'FROM "raw_nba_api_request_observation" '
                        'WHERE "observation_sha256" > ? '
                        'ORDER BY "observation_sha256" '
                        f"LIMIT {self._RAW_AUTHORITY_PAGE_SIZE}",
                        [last_observation],
                    ).fetchall()
                if not observation_rows:
                    break
                for raw_observation_row in observation_rows:
                    stage = "rows"
                    observation_row = dict(
                        zip(observation_columns, raw_observation_row, strict=True)
                    )
                    observation = self._decode_raw_observation_row(observation_row)
                    last_observation = observation.attempt.observation_sha256
                    validate_raw_authority_contract_identity(
                        source_family=observation.attempt.source_family,
                        endpoint_id=observation.attempt.endpoint_id,
                        provider_authority_sha256=(observation.attempt.provider_authority_sha256),
                        endpoint_contract_sha256_value=(
                            observation.attempt.endpoint_contract_sha256
                        ),
                    )
                    body_object = None
                    if observation.body_object_sha256 is not None:
                        body_row = self._conn.execute(
                            f"SELECT {object_selection} "
                            'FROM "raw_nba_api_parser_input_object" '
                            'WHERE "object_sha256" = ?',
                            [observation.body_object_sha256],
                        ).fetchone()
                        if body_row is None:
                            raise ValueError("raw authority body object disappeared during scan")
                        body_object = validate_parser_input_object(
                            dict(zip(object_columns, body_row, strict=True))
                        )

                    if (
                        observation.result_occurrence_count
                        > self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION
                    ):
                        raise ValueError("one raw observation exceeds the bounded result inventory")
                    raw_occurrence_rows = self._conn.execute(
                        f"SELECT {occurrence_selection} "
                        'FROM "raw_nba_api_result_occurrence" '
                        'WHERE "observation_sha256" = ? '
                        'ORDER BY "occurrence_ordinal" '
                        f"LIMIT {self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION + 1}",
                        [observation.attempt.observation_sha256],
                    ).fetchall()
                    if len(raw_occurrence_rows) > self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION:
                        raise ValueError("one raw observation exceeds the bounded result inventory")
                    ordered_occurrences = tuple(
                        validate_result_occurrence(dict(zip(occurrence_columns, row, strict=True)))
                        for row in raw_occurrence_rows
                    )
                    if (
                        observation.route_landing_count
                        > self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION
                    ):
                        raise ValueError(
                            "one raw observation exceeds the bounded route-landing inventory"
                        )
                    raw_landing_rows = self._conn.execute(
                        f"SELECT {landing_selection} "
                        'FROM "raw_nba_api_observation_route_landing" '
                        'WHERE "observation_sha256" = ? ORDER BY "route_ordinal" '
                        f"LIMIT {self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION + 1}",
                        [observation.attempt.observation_sha256],
                    ).fetchall()
                    if len(raw_landing_rows) > self._RAW_AUTHORITY_MAX_RESULTS_PER_OBSERVATION:
                        raise ValueError(
                            "one raw observation exceeds the bounded route-landing inventory"
                        )
                    ordered_landings = tuple(
                        validate_observation_route_landing(
                            self._decode_raw_landing_row(
                                dict(zip(landing_columns, row, strict=True))
                            )
                        )
                        for row in raw_landing_rows
                    )

                    stage = "bundle"
                    self._validate_raw_observation_outcome(
                        observation,
                        ordered_occurrences,
                        ordered_landings,
                    )
                    stage = "reconstruction"
                    if observation.attempt.source_family == "live":
                        raise ValueError(
                            "live raw authority lacks a persisted independent sealed-plan receipt"
                        )
                    reconstruction = reconstruct_raw_request_authority(
                        body_object,
                        observation,
                        ordered_occurrences,
                        ordered_landings,
                    )
                    if (
                        reconstruction.observation_record_sha256
                        != observation.observation_record_sha256
                    ):
                        raise ValueError("reconstruction differs from observation record authority")
                    if (
                        reconstruction.public_authority_receipt_sha256
                        != observation.public_authority_receipt_sha256
                    ):
                        raise ValueError("reconstruction differs from public authority receipt")

                    parser_input = reconstruction.parser_input.parser_input_bytes
                    if body_object is None:
                        if parser_input is not None:
                            raise ValueError("bodyless reconstruction invented parser bytes")
                        bodyless_observation_count += 1
                    else:
                        if parser_input is None:
                            raise ValueError("body-bearing reconstruction lost parser bytes")
                        parsed_body_count += 1

                    successful_outcomes = {
                        "success_nonempty",
                        "success_empty",
                        "static_snapshot_success",
                    }
                    runtime_contract = (
                        pinned_runtime_contracts().get(observation.attempt.endpoint_id)
                        if observation.attempt.source_family == "stats"
                        else None
                    )
                    unknown_rederived: tuple[RawAuthorityResultSetDerivation, ...] | None = None
                    if (
                        runtime_contract is not None
                        and runtime_contract.response_mode == "unknown_dynamic_response"
                        and parser_input is not None
                    ):
                        unknown = rederive_raw_authority_unknown_stats_response(
                            endpoint_id=observation.attempt.endpoint_id,
                            parser_input=parser_input,
                            safe_parameters_json=(observation.attempt.safe_parameters_json),
                            provider_authority_sha256=(
                                observation.attempt.provider_authority_sha256
                            ),
                            endpoint_contract_sha256_value=(
                                observation.attempt.endpoint_contract_sha256
                            ),
                        )
                        duplicate_names: Counter[str] = Counter()
                        unknown_derivations: list[RawAuthorityResultSetDerivation] = []
                        for item in unknown.occurrences:
                            duplicate_ordinal = duplicate_names[item.name]
                            duplicate_names[item.name] += 1
                            unknown_derivations.append(
                                RawAuthorityResultSetDerivation(
                                    result_set=item.receipt,
                                    ordered_headers=item.headers,
                                    duplicate_name_ordinal=duplicate_ordinal,
                                )
                            )
                        unknown_rederived = tuple(unknown_derivations)
                        if observation.outcome not in successful_outcomes and unknown_rederived:
                            raise ValueError(
                                "non-success unknown stats observation hides "
                                "parser-derived result occurrences"
                            )
                    if observation.outcome in successful_outcomes:
                        if (
                            runtime_contract is not None
                            and runtime_contract.response_mode == "unknown_dynamic_response"
                        ):
                            if unknown_rederived is None:
                                raise ValueError(
                                    "unknown stats terminal observation lacks parser bytes"
                                )
                            rederived = unknown_rederived
                        else:
                            rederived = rederive_raw_authority_result_sets(
                                source_family=observation.attempt.source_family,
                                endpoint_id=observation.attempt.endpoint_id,
                                parser_input=parser_input,
                                provider_authority_sha256=(
                                    observation.attempt.provider_authority_sha256
                                ),
                                endpoint_contract_sha256_value=(
                                    observation.attempt.endpoint_contract_sha256
                                ),
                            )
                        if len(rederived) != len(ordered_occurrences):
                            raise ValueError(
                                "stored result inventory differs from parser-derived authority"
                            )
                        for occurrence, derived in zip(
                            ordered_occurrences,
                            rederived,
                            strict=True,
                        ):
                            self._compare_rederived_occurrence(
                                observation,
                                occurrence,
                                derived,
                            )
                        if (
                            observation.attempt.source_family == "stats"
                            and parser_input is not None
                        ):
                            verified_routes, video_alias_unverified = (
                                self._compare_rederived_stats_route_membership(
                                    observation,
                                    ordered_occurrences,
                                    rederived,
                                    parser_input,
                                )
                            )
                            stats_route_membership_verified_count += verified_routes
                            if video_alias_unverified:
                                video_alias_policy_unverified_observation_count += 1
                    elif ordered_occurrences:
                        raise ValueError("non-success raw observation contains result occurrences")

                    if len(reconstruction.result_packets) != len(ordered_occurrences):
                        raise ValueError("reconstruction result packet inventory is incomplete")
                    for packet, occurrence in zip(
                        reconstruction.result_packets,
                        ordered_occurrences,
                        strict=True,
                    ):
                        route_ids = tuple(json.loads(occurrence.canonical_route_ids_json))
                        raw_receipts = json.loads(occurrence.committed_staging_receipts_json)
                        committed_receipts = tuple(
                            (receipt["route_id"], receipt["receipt_sha256"])
                            for receipt in raw_receipts
                        )
                        if (
                            packet.occurrence_sha256 != occurrence.occurrence_sha256
                            or packet.occurrence_ordinal != occurrence.occurrence_ordinal
                            or packet.canonical_route_ids != route_ids
                            or packet.committed_staging_receipts != committed_receipts
                            or packet.landing_disposition != occurrence.landing_disposition
                        ):
                            raise ValueError("reconstruction packet or route receipt differs")
                        packet_inventory.update(packet.packet_sha256)
                        occurrence_route_receipt_inventory.update(occurrence.route_receipt_sha256)
                        if packet.presence == "not_observed_parent_empty":
                            parent_empty_packet_count += 1
                    if len(reconstruction.route_landings) != len(ordered_landings):
                        raise ValueError("reconstruction route-landing inventory is incomplete")
                    for reconstructed_landing, landing in zip(
                        reconstruction.route_landings,
                        ordered_landings,
                        strict=True,
                    ):
                        if reconstructed_landing.landing_sha256 != landing.landing_sha256:
                            raise ValueError("reconstruction route landing differs")
                        route_landing_inventory.update(reconstructed_landing.reconstruction_sha256)
                    reconstruction_inventory.update(reconstruction.reconstruction_sha256)
                    body_receipt_inventory.update(observation.body_authority_receipt_sha256)
                    result_packet_count += len(reconstruction.result_packets)
                    route_landing_count += len(reconstruction.route_landings)
                    verified_observation_count += 1

            if verified_observation_count != observation_count:
                raise ValueError("raw authority observation paging did not reach its SQL count")
            if result_packet_count != occurrence_count:
                raise ValueError("raw authority occurrence paging did not reach its SQL count")
            if route_landing_count != landing_count:
                raise ValueError("raw authority route-landing paging did not reach its SQL count")
            reconstruction_inventory_sha256 = reconstruction_inventory.hexdigest()
            body_receipt_inventory_sha256 = body_receipt_inventory.hexdigest()
            packet_inventory_sha256 = packet_inventory.hexdigest()
            occurrence_route_receipt_inventory_sha256 = (
                occurrence_route_receipt_inventory.hexdigest()
            )
            route_landing_inventory_sha256 = route_landing_inventory.hexdigest()
            assurance_payload = {
                "schema_version": 2,
                "bundle_sha256": bundle_sha256,
                "object_count": object_count,
                "observation_count": observation_count,
                "occurrence_count": occurrence_count,
                "landing_count": landing_count,
                "parsed_body_count": parsed_body_count,
                "bodyless_observation_count": bodyless_observation_count,
                "parent_empty_packet_count": parent_empty_packet_count,
                "reconstruction_inventory_sha256": reconstruction_inventory_sha256,
                "body_receipt_inventory_sha256": body_receipt_inventory_sha256,
                "packet_inventory_sha256": packet_inventory_sha256,
                "occurrence_route_receipt_inventory_sha256": (
                    occurrence_route_receipt_inventory_sha256
                ),
                "route_landing_inventory_sha256": route_landing_inventory_sha256,
                "stats_route_membership_verified_count": (stats_route_membership_verified_count),
                "video_alias_policy_unverified_observation_count": (
                    video_alias_policy_unverified_observation_count
                ),
            }
            assurance_sha256 = hashlib.sha256(canonical_json_bytes(assurance_payload)).hexdigest()
        except Exception as exc:
            issue_by_stage = {
                "schema": "raw_authority_schema_invalid",
                "rows": "raw_authority_rows_malformed",
                "bundle": "raw_authority_bundle_invalid",
                "reconstruction": "raw_authority_reconstruction_failed",
            }
            issue_code = issue_by_stage[stage]
            logger.error(
                "scanner: raw authority verification failed at {}: {}",
                stage,
                type(exc).__name__,
            )
            details: dict[str, object] = {
                "issue_code": issue_code,
                "verification_stage": stage,
                "error_type": type(exc).__name__,
                "table_row_counts": dict(sorted(table_row_counts.items())),
                "verified_observation_count": verified_observation_count,
                "parsed_body_count": parsed_body_count,
                "bodyless_observation_count": bodyless_observation_count,
                "verified_result_packet_count": result_packet_count,
                "verified_route_landing_count": route_landing_count,
                "verified_parent_empty_packet_count": parent_empty_packet_count,
            }
            if bundle_sha256 is not None:
                details["bundle_sha256"] = bundle_sha256
            self._add(
                ScanFinding(
                    category=ScanCategory.DATA_QUALITY,
                    severity=ScanSeverity.ERROR,
                    table="raw_request_authority",
                    check=issue_code,
                    message=(
                        "Private raw request authority failed independent "
                        f"{stage} verification ({type(exc).__name__})"
                    ),
                    details=details,
                )
            )
            return

        self._report.evidence["raw_request_authority"] = {
            "evidence_code": "raw_authority_reconstruction_verified",
            "bundle_sha256": bundle_sha256,
            "assurance_sha256": assurance_sha256,
            "object_count": object_count,
            "observation_count": observation_count,
            "occurrence_count": occurrence_count,
            "landing_count": landing_count,
            "parsed_body_count": parsed_body_count,
            "bodyless_observation_count": bodyless_observation_count,
            "result_packet_count": result_packet_count,
            "parent_empty_packet_count": parent_empty_packet_count,
            "reconstruction_inventory_sha256": reconstruction_inventory_sha256,
            "body_receipt_inventory_sha256": body_receipt_inventory_sha256,
            "packet_inventory_sha256": packet_inventory_sha256,
            "occurrence_route_receipt_inventory_sha256": (
                occurrence_route_receipt_inventory_sha256
            ),
            "route_landing_inventory_sha256": route_landing_inventory_sha256,
            "stats_route_membership_verified_count": stats_route_membership_verified_count,
            "video_alias_policy_unverified_observation_count": (
                video_alias_policy_unverified_observation_count
            ),
        }
        if video_alias_policy_unverified_observation_count:
            raise AssertionError("four-table reconstruction left Video alias policy unverified")

    def _check_request_closure_inventory(self) -> RequestClosureRuntimeReceipt | None:
        """Require a canonical independently reproduced request fixed point."""

        self._report.checks_run += 1
        path = self._request_closure_inventory_path
        if path is None or path.is_symlink() or not path.is_file():
            self._add(
                ScanFinding(
                    category=ScanCategory.DATA_QUALITY,
                    severity=ScanSeverity.ERROR,
                    table="request_closure",
                    check="request_closure_inventory_missing",
                    message=(
                        "Full publication lacks a regular canonical request-closure inventory"
                    ),
                    details={"required_contract": "green_request_closure_observation_inventory_v2"},
                )
            )
            return None
        try:
            encoded = path.read_bytes()
            from nbadb.orchestrate.request_closure_staging import (
                verify_request_closure_observation_inventory_bytes,
            )

            receipt = verify_request_closure_observation_inventory_bytes(encoded)
            if not receipt.green:
                raise ValueError("request closure runtime receipt is not green")
        except Exception as exc:
            logger.error("scanner: request closure assurance failed: {}", type(exc).__name__)
            self._add(
                ScanFinding(
                    category=ScanCategory.DATA_QUALITY,
                    severity=ScanSeverity.ERROR,
                    table="request_closure",
                    check="request_closure_inventory_invalid",
                    message=(
                        "Full-publication request closure failed independent verification: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    details={
                        "error_type": type(exc).__name__,
                        "required_contract": "green_request_closure_observation_inventory_v2",
                    },
                )
            )
            return None
        self._report.evidence["request_closure"] = {
            "evidence_code": "request_closure_inventory_verified",
            "artifact_sha256": hashlib.sha256(encoded).hexdigest(),
            "request_surface_sha256": receipt.request_surface_sha256,
            "route_manifest_sha256": receipt.route_manifest.manifest_sha256,
            "scope_sha256": receipt.scope.scope_sha256,
            "observation_count": len(receipt.observations),
            "terminal_inventory_sha256": receipt.terminal_inventory_sha256,
        }
        return receipt

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

        staging_keys = [
            key
            for key in get_all_staging_keys(present_keys=existing)
            if self._matches_filter(key, table_filter)
        ]
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
            # Staging and raw-authority tables have their own strict contracts.
            if table.startswith(("stg_", "raw_")):
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
