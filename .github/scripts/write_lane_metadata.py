from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from nbadb.core.extraction_failures import classify_error_name
from nbadb.orchestrate.extraction_contract import contract_blocking_rules_for_lane

_ERROR_MARKER_RE = re.compile(
    r"\[(transport_transient|response_contract|application):([A-Za-z][A-Za-z0-9_]*)\]"
)


def _int_value(value: object, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _csv_values(value: str) -> list[str]:
    return [item for item in value.split(",") if item]


def _json_list_env(name: str) -> list[Any]:
    raw = os.environ.get(name, "[]") or "[]"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def append_output(key: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def _has_table(con: Any, table_name: str) -> bool:
    return bool(
        con.execute(
            """
            select 1
            from information_schema.tables
            where table_schema = 'main' and table_name = ?
            limit 1
            """,
            [table_name],
        ).fetchone()
    )


def _table_columns(con: Any, table_name: str) -> set[str]:
    return {
        str(row[0])
        for row in con.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'main' and table_name = ?
            """,
            [table_name],
        ).fetchall()
    }


def _duckdb_telemetry(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "source_path": str(db_path),
            "readable": False,
            "journal_present": False,
            "done_endpoints": [],
            "error": "missing",
        }

    try:
        import duckdb
    except ImportError as exc:
        return {"source_path": str(db_path), "error": f"duckdb_import_error: {exc}"}

    telemetry: dict[str, Any] = {
        "source_path": str(db_path),
        "readable": False,
        "journal_present": False,
        "planned_calls": 0,
        "journal_skips": 0,
        "failed_calls": 0,
        "running_calls": 0,
        "done_calls": 0,
        "completed_calls": 0,
        "tables_persisted": 0,
        "rows_persisted": 0,
        "journal_rows_extracted": 0,
        "done_endpoints": [],
        "staging_rows_persisted": 0,
        "staging_tables": {},
        "error": "",
    }
    con: Any | None = None
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        telemetry["readable"] = True
        if _has_table(con, "_extraction_journal"):
            telemetry["journal_present"] = True
            journal_columns = _table_columns(con, "_extraction_journal")
            required_columns = {"status", "rows_extracted"}
            if not required_columns <= journal_columns:
                missing = sorted(required_columns - journal_columns)
                raise ValueError(
                    "_extraction_journal is missing required columns: " + ", ".join(missing)
                )
            journal_rows = con.execute(
                """
                select
                    count(*) as planned_calls,
                    coalesce(sum(case when status = 'skipped' then 1 else 0 end), 0)
                        as journal_skips,
                    coalesce(
                        sum(
                            case
                                when status not in ('done', 'running', 'skipped')
                                then 1
                                else 0
                            end
                        ),
                        0
                    ) as failed_calls,
                    coalesce(sum(case when status = 'running' then 1 else 0 end), 0)
                        as running_calls,
                    coalesce(sum(case when status = 'done' then 1 else 0 end), 0)
                        as done_calls,
                    coalesce(
                        sum(case when status = 'done' then rows_extracted else 0 end),
                        0
                    ) as journal_rows_extracted
                from _extraction_journal
                """
            ).fetchone()
            if journal_rows:
                (
                    telemetry["planned_calls"],
                    telemetry["journal_skips"],
                    telemetry["failed_calls"],
                    telemetry["running_calls"],
                    telemetry["done_calls"],
                    telemetry["journal_rows_extracted"],
                ) = [int(value or 0) for value in journal_rows]
                telemetry["completed_calls"] = int(telemetry["done_calls"]) + int(
                    telemetry["journal_skips"]
                )
            if "endpoint" in journal_columns:
                telemetry["done_endpoints"] = [
                    str(row[0])
                    for row in con.execute(
                        """
                        select distinct endpoint
                        from _extraction_journal
                        where status = 'done'
                        order by endpoint
                        """
                    ).fetchall()
                ]

        staging_tables = con.execute(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'main' and table_name like 'stg_%'
            order by table_name
            """
        ).fetchall()
        staging_counts: dict[str, int] = {}
        for (table_name,) in staging_tables:
            row = con.execute(f'select count(*) from "{table_name}"').fetchone()
            rows = int(row[0]) if row else 0
            staging_counts[str(table_name)] = rows

        telemetry["staging_tables"] = staging_counts
        telemetry["tables_persisted"] = sum(1 for rows in staging_counts.values() if rows > 0)
        telemetry["staging_rows_persisted"] = sum(staging_counts.values())
        telemetry["rows_persisted"] = max(
            int(telemetry["journal_rows_extracted"]),
            int(telemetry["staging_rows_persisted"]),
        )
    except Exception as exc:
        telemetry["error"] = str(exc)
    finally:
        if con is not None:
            con.close()
    return telemetry


def _load_extract_summary(summary_path: Path) -> tuple[dict[str, Any], str]:
    if not summary_path.exists():
        return {}, ""
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, str(exc)
    return summary if isinstance(summary, dict) else {}, ""


def _error_diagnostics(extract_summary: dict[str, Any]) -> dict[str, Any]:
    result = extract_summary.get("result")
    result_payload = result if isinstance(result, dict) else {}
    errors = result_payload.get("errors")
    error_values = errors if isinstance(errors, list) else []
    class_counts: Counter[str] = Counter()
    root_counts: Counter[str] = Counter()
    for raw_error in error_values:
        error = str(raw_error)
        marker = _ERROR_MARKER_RE.search(error)
        if marker is not None:
            failure_class, root_type = marker.groups()
        else:
            tail = error.rsplit(": ", maxsplit=1)[-1]
            root_type = re.split(r"[^A-Za-z0-9_]", tail, maxsplit=1)[0] or "Unknown"
            failure_class = classify_error_name(error)
            if failure_class == "application":
                failure_class = classify_error_name(root_type)
        class_counts[failure_class] += 1
        root_counts[root_type] += 1

    class_precedence = {
        "application": 3,
        "response_contract": 2,
        "transport_transient": 1,
    }
    dominant_class = max(
        class_counts,
        key=lambda key: (class_counts[key], class_precedence.get(key, 0), key),
        default="",
    )
    dominant_root = max(
        root_counts,
        key=lambda key: (root_counts[key], key),
        default="",
    )
    return {
        "failure_class": dominant_class,
        "failure_class_counts": dict(sorted(class_counts.items())),
        "root_error_type": dominant_root,
        "root_error_type_counts": dict(sorted(root_counts.items())),
    }


def _failure_class(
    *,
    raw_status: str,
    final_outcome: str,
    vpn_status: str,
    completed_calls: int,
    rows_persisted: int,
    running_calls: int,
    diagnostics: dict[str, Any],
) -> str:
    if final_outcome == "contract_blocked":
        return "contract_blocked"
    if final_outcome == "complete":
        return ""
    if raw_status in {"cancelled", "cancellation_no_metadata"}:
        return "runner_infrastructure"
    if vpn_status in {"vpn_auth_failure", "vpn_connect_timeout"}:
        return "vpn_egress"
    if raw_status in {"extract-timeout", "timeout_with_persisted_progress", "needs_resume"}:
        return "timeout_progress" if completed_calls or rows_persisted else "timeout_stalled"
    diagnostic_class = str(diagnostics.get("failure_class") or "")
    if diagnostic_class:
        return diagnostic_class
    if raw_status == "extract-error" and running_calls > 0:
        return "runner_infrastructure"
    return "application"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _completion_evidence_errors(
    *,
    db_telemetry: dict[str, Any],
    expected_endpoints: list[str],
    coverage_units_hash: str,
    database_sha256: str,
) -> list[str]:
    errors: list[str] = []
    if not db_telemetry.get("readable") or db_telemetry.get("error"):
        errors.append("database_unreadable")
    if not db_telemetry.get("journal_present"):
        errors.append("journal_missing")
    if _int_value(db_telemetry.get("failed_calls")):
        errors.append("failed_journal_calls")
    if _int_value(db_telemetry.get("running_calls")):
        errors.append("running_journal_calls")
    if _int_value(db_telemetry.get("done_calls")) < 1:
        errors.append("no_completed_journal_calls")
    done_endpoints = {str(value) for value in db_telemetry.get("done_endpoints", [])}
    missing_endpoints = sorted(set(expected_endpoints) - done_endpoints)
    if missing_endpoints:
        errors.append("missing_endpoint_evidence:" + ",".join(missing_endpoints))
    if not _is_sha256(coverage_units_hash):
        errors.append("coverage_units_hash_missing_or_invalid")
    if not _is_sha256(database_sha256):
        errors.append("database_sha256_missing_or_invalid")
    return errors


def _progress_fingerprint(*, completed_calls: int, rows_persisted: int) -> str:
    payload = json.dumps(
        {"completed_calls": completed_calls, "rows_persisted": rows_persisted},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _final_outcome(
    *,
    raw_status: str,
    effective_network_mode: str,
    rows_persisted: int,
    failed_calls: int,
    journal_skips: int,
    running_calls: int,
    support_rules: list[dict[str, Any]],
    completion_evidence_errors: list[str],
) -> str:
    if raw_status == "complete":
        return "pipeline_failure" if completion_evidence_errors else "complete"
    if raw_status in {"needs_resume", "contract_blocked", "pipeline_failure"}:
        return raw_status
    if rows_persisted == 0 and failed_calls > 0 and support_rules:
        return "contract_blocked"
    if raw_status == "extract-error" and (
        rows_persisted > 0 or journal_skips > 0 or running_calls > 0
    ):
        return "needs_resume"
    if (
        raw_status == "extract-timeout"
        and effective_network_mode == "direct"
        and rows_persisted == 0
        and journal_skips == 0
        and running_calls > 0
    ):
        return "pipeline_failure"
    if raw_status in {"extract-timeout", "timeout_with_persisted_progress"}:
        return "needs_resume"
    if raw_status == "cancelled" and (rows_persisted > 0 or journal_skips > 0 or running_calls > 0):
        return "needs_resume"
    return "pipeline_failure"


def build_payload() -> dict[str, Any]:
    resume_only = os.environ["RESUME_ONLY"].lower() == "true"
    network_mode = os.environ.get("NETWORK_MODE", "vpn").strip() or "vpn"
    effective_network_mode = os.environ.get("EFFECTIVE_NETWORK_MODE", "").strip() or network_mode
    direct_egress_reason = os.environ.get("DIRECT_EGRESS_REASON", "").strip()
    vpn_status = os.environ.get("VPN_STATUS", "").strip()
    if not vpn_status:
        if resume_only:
            vpn_status = "resume-only"
        elif effective_network_mode == "direct":
            vpn_status = "direct-no-vpn"
        else:
            vpn_status = "unknown"

    summary_path = Path(os.environ["EXTRACT_SUMMARY_PATH"])
    extract_summary, extract_summary_parse_error = _load_extract_summary(summary_path)

    result_summary = extract_summary.get("result", {})
    progress_summary = extract_summary.get("progress", {})
    if not isinstance(result_summary, dict):
        result_summary = {}
    if not isinstance(progress_summary, dict):
        progress_summary = {}

    totals = progress_summary.get("totals", {})
    if not isinstance(totals, dict):
        totals = {}
    rows_persisted = _int_value(result_summary.get("rows_total") or totals.get("rows_extracted"))
    failed_calls = _int_value(result_summary.get("failed_extractions") or totals.get("failed"))
    journal_skips = _int_value(result_summary.get("skipped_extractions") or totals.get("skipped"))
    tables_persisted = _int_value(result_summary.get("tables_updated"))
    planned_calls = (
        sum(
            _int_value(pattern.get("total"))
            for pattern in progress_summary.get("patterns", [])
            if isinstance(pattern, dict)
        )
        if isinstance(progress_summary.get("patterns", []), list)
        else 0
    )

    db_telemetry = _duckdb_telemetry(Path("data/nbadb/nba.duckdb"))
    if not rows_persisted:
        rows_persisted = _int_value(db_telemetry.get("rows_persisted"))
    if not tables_persisted:
        tables_persisted = _int_value(db_telemetry.get("tables_persisted"))
    if not planned_calls:
        planned_calls = _int_value(db_telemetry.get("planned_calls"))
    if not failed_calls:
        failed_calls = _int_value(db_telemetry.get("failed_calls"))
    if not journal_skips:
        journal_skips = _int_value(db_telemetry.get("journal_skips"))

    raw_status = os.environ["STATUS"]
    endpoints = _csv_values(os.environ.get("ENDPOINTS", ""))
    patterns = _csv_values(os.environ.get("PATTERNS", ""))
    season_start_raw = os.environ.get("SEASON_START", "")
    season_end_raw = os.environ.get("SEASON_END", "")
    season_start = _int_value(season_start_raw, default=0) or None
    season_end = _int_value(season_end_raw, default=0) or None

    support_rules = [
        rule.to_dict()
        for rule in contract_blocking_rules_for_lane(
            endpoints=tuple(endpoints),
            patterns=tuple(patterns),
            season_start=season_start,
            season_end=season_end,
        )
    ]
    db_path = Path("data/nbadb/nba.duckdb")
    database_sha256 = _sha256(db_path) if db_path.is_file() else ""
    coverage_units_hash = os.environ.get("COVERAGE_UNITS_HASH", "").strip().lower()
    running_calls = _int_value(db_telemetry.get("running_calls"))
    completed_calls = _int_value(db_telemetry.get("completed_calls"))
    completion_evidence_errors = _completion_evidence_errors(
        db_telemetry=db_telemetry,
        expected_endpoints=endpoints,
        coverage_units_hash=coverage_units_hash,
        database_sha256=database_sha256,
    )
    final_outcome = _final_outcome(
        raw_status=raw_status,
        effective_network_mode=effective_network_mode,
        rows_persisted=rows_persisted,
        failed_calls=failed_calls,
        journal_skips=journal_skips,
        running_calls=running_calls,
        support_rules=support_rules,
        completion_evidence_errors=completion_evidence_errors,
    )
    error_diagnostics = _error_diagnostics(extract_summary)
    failure_class = _failure_class(
        raw_status=raw_status,
        final_outcome=final_outcome,
        vpn_status=vpn_status,
        completed_calls=completed_calls,
        rows_persisted=rows_persisted,
        running_calls=running_calls,
        diagnostics=error_diagnostics,
    )

    zero_row_reason = ""
    if rows_persisted == 0:
        if final_outcome == "complete":
            zero_row_reason = "expected_empty"
        elif final_outcome == "contract_blocked":
            zero_row_reason = "contract_blocked"
        elif final_outcome == "pipeline_failure" and raw_status == "extract-timeout":
            zero_row_reason = "zero_progress_timeout"
        elif journal_skips > 0 or completed_calls > 0:
            zero_row_reason = "zero_row_progress"
        elif running_calls > 0:
            zero_row_reason = "running_without_durable_progress"
        elif failed_calls > 0:
            zero_row_reason = "contract_gap"
        elif effective_network_mode == "direct":
            zero_row_reason = "direct_no_data"
        else:
            zero_row_reason = "unknown"

    state_artifact_name = f"extraction-lane-{os.environ['CHAIN_ID']}-{os.environ['LANE_ID']}"
    return {
        "metadata_schema_version": 3,
        "chain_id": os.environ["CHAIN_ID"],
        "iteration": os.environ["ITERATION"],
        "lane_id": os.environ["LANE_ID"],
        "lane_index": os.environ["LANE_INDEX"],
        "lane_name": os.environ["NAME"],
        "lane_kind": os.environ["KIND"],
        "source_ref": os.environ["SOURCE_REF"],
        "source_sha": os.environ["SOURCE_SHA"],
        "coverage_units_hash": coverage_units_hash,
        "database_sha256": database_sha256,
        "status": final_outcome,
        "raw_status": raw_status,
        "cache_hit": os.environ["CACHE_HIT"],
        "restore_source": os.environ["RESTORE_SOURCE"],
        "restore_usable": os.environ["RESTORE_USABLE"].lower() == "true",
        "restart_mode": os.environ["RESTART_MODE"],
        "restore_error": os.environ.get("RESTORE_ERROR", ""),
        "resume_only": resume_only,
        "timeout_seconds": int(os.environ["TIMEOUT_SECONDS"]),
        "effective_timeout_seconds": int(os.environ["EFFECTIVE_TIMEOUT_SECONDS"]),
        "started_at": os.environ.get("STARTED_AT", ""),
        "finished_at": os.environ.get("FINISHED_AT", ""),
        "extract_status": os.environ.get("EXTRACT_STATUS", ""),
        "extract_exit_code": os.environ.get("EXTRACT_EXIT_CODE", ""),
        "network_mode": network_mode,
        "effective_network_mode": effective_network_mode,
        "direct_egress_reason": direct_egress_reason,
        "vpn_status": vpn_status,
        "patterns": patterns,
        "season_types": _csv_values(os.environ.get("SEASON_TYPES", "")),
        "endpoints": endpoints,
        "season_start": season_start_raw,
        "season_end": season_end_raw,
        "parent_lane_id": os.environ.get("PARENT_LANE_ID", ""),
        "split_generation": int(os.environ.get("SPLIT_GENERATION") or 0),
        "support_rules": support_rules,
        "failure_class": failure_class,
        "failure_class_counts": error_diagnostics["failure_class_counts"],
        "root_error_type": error_diagnostics["root_error_type"],
        "root_error_type_counts": error_diagnostics["root_error_type_counts"],
        "progress": {
            "completed_calls": completed_calls,
            "rows_persisted": rows_persisted,
            "fingerprint": _progress_fingerprint(
                completed_calls=completed_calls,
                rows_persisted=rows_persisted,
            ),
        },
        "state_artifact": {
            "run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "name": state_artifact_name,
            "sha256": database_sha256,
            "required": final_outcome != "complete",
            "retention_days": 7 if final_outcome == "complete" else 30,
        },
        "artifact_requirements": {
            "lane_metadata": final_outcome != "complete",
            "vpn_diagnostics": (
                final_outcome != "complete"
                and not resume_only
                and effective_network_mode != "direct"
            ),
        },
        "telemetry": {
            "planned_calls": planned_calls,
            "journal_skips": journal_skips,
            "failed_calls": failed_calls,
            "completed_calls": completed_calls,
            "tables_persisted": tables_persisted,
            "rows_persisted": rows_persisted,
            "zero_row_reason": zero_row_reason,
            "circuit_breaker_endpoints": extract_summary.get("circuit_breaker_endpoints", []),
            "rate_degradation_events": extract_summary.get("rate_degradation_events", []),
            "extract_summary_parse_error": extract_summary_parse_error,
            "completion_evidence_errors": completion_evidence_errors,
            "db_telemetry": db_telemetry,
        },
        "extract_summary": extract_summary,
        "vpn": {
            "status": vpn_status,
            "server": os.environ.get("VPN_SERVER", ""),
            "interface": os.environ.get("VPN_INTERFACE", ""),
            "exit_ip": os.environ.get("VPN_EXIT_IP", ""),
            "attempted_servers": _json_list_env("VPN_ATTEMPTED_SERVERS_JSON"),
            "failed_servers": _json_list_env("VPN_FAILED_SERVERS_JSON"),
        },
    }


def main() -> int:
    Path("artifacts/extraction").mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    Path("artifacts/extraction/lane-metadata.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    append_output("final-outcome", str(payload["status"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
