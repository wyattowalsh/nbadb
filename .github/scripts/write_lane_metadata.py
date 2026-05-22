from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nbadb.orchestrate.extraction_contract import contract_blocking_rules_for_lane


def _int_value(value: object, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _csv_values(value: str) -> list[str]:
    return [item for item in value.split(",") if item]


def _json_list_env(name: str) -> list[Any]:
    raw = os.environ.get(name, "[]") or "[]"
    parsed = json.loads(raw)
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


def _duckdb_telemetry(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"source_path": str(db_path), "error": "missing"}

    try:
        import duckdb
    except ImportError as exc:
        return {"source_path": str(db_path), "error": f"duckdb_import_error: {exc}"}

    telemetry: dict[str, Any] = {
        "source_path": str(db_path),
        "planned_calls": 0,
        "journal_skips": 0,
        "failed_calls": 0,
        "running_calls": 0,
        "tables_persisted": 0,
        "rows_persisted": 0,
        "journal_rows_extracted": 0,
        "staging_rows_persisted": 0,
        "staging_tables": {},
        "error": "",
    }
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        if _has_table(con, "_extraction_journal"):
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
                    telemetry["journal_rows_extracted"],
                ) = [int(value or 0) for value in journal_rows]

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
            rows = int(con.execute(f'select count(*) from "{table_name}"').fetchone()[0])
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
    return telemetry


def _load_extract_summary(summary_path: Path) -> tuple[dict[str, Any], str]:
    if not summary_path.exists():
        return {}, ""
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, str(exc)
    return summary if isinstance(summary, dict) else {}, ""


def _final_outcome(
    *,
    raw_status: str,
    rows_persisted: int,
    failed_calls: int,
    journal_skips: int,
    running_calls: int,
    support_rules: list[dict[str, Any]],
) -> str:
    if raw_status == "complete":
        return "complete"
    if raw_status in {"complete", "needs_resume", "contract_blocked", "pipeline_failure"}:
        return raw_status
    if rows_persisted == 0 and failed_calls > 0 and support_rules:
        return "contract_blocked"
    if raw_status == "extract-error" and (rows_persisted > 0 or journal_skips > 0):
        return "needs_resume"
    if raw_status in {"extract-timeout", "timeout_with_persisted_progress"}:
        return "needs_resume"
    if raw_status == "cancelled" and (rows_persisted > 0 or journal_skips > 0 or running_calls > 0):
        return "needs_resume"
    return "pipeline_failure"


def build_payload() -> dict[str, Any]:
    resume_only = os.environ["RESUME_ONLY"].lower() == "true"
    vpn_status = os.environ.get("VPN_STATUS", "").strip()
    if not vpn_status:
        vpn_status = "resume-only" if resume_only else "unknown"

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
    running_calls = _int_value(db_telemetry.get("running_calls"))
    final_outcome = _final_outcome(
        raw_status=raw_status,
        rows_persisted=rows_persisted,
        failed_calls=failed_calls,
        journal_skips=journal_skips,
        running_calls=running_calls,
        support_rules=support_rules,
    )

    zero_row_reason = ""
    if rows_persisted == 0:
        if final_outcome == "complete":
            zero_row_reason = "expected_empty"
        elif final_outcome == "contract_blocked":
            zero_row_reason = "contract_blocked"
        elif journal_skips > 0 or _int_value(db_telemetry.get("running_calls")) > 0:
            zero_row_reason = "zero_row_progress"
        elif failed_calls > 0:
            zero_row_reason = "contract_gap"
        else:
            zero_row_reason = "unknown"

    return {
        "chain_id": os.environ["CHAIN_ID"],
        "iteration": os.environ["ITERATION"],
        "lane_id": os.environ["LANE_ID"],
        "lane_index": os.environ["LANE_INDEX"],
        "lane_name": os.environ["NAME"],
        "lane_kind": os.environ["KIND"],
        "source_ref": os.environ["SOURCE_REF"],
        "source_sha": os.environ["SOURCE_SHA"],
        "status": final_outcome,
        "raw_status": raw_status,
        "cache_hit": os.environ["CACHE_HIT"],
        "restore_source": os.environ["RESTORE_SOURCE"],
        "restore_usable": os.environ["RESTORE_USABLE"].lower() == "true",
        "restart_mode": os.environ["RESTART_MODE"],
        "resume_only": resume_only,
        "timeout_seconds": int(os.environ["TIMEOUT_SECONDS"]),
        "effective_timeout_seconds": int(os.environ["EFFECTIVE_TIMEOUT_SECONDS"]),
        "started_at": os.environ.get("STARTED_AT", ""),
        "finished_at": os.environ.get("FINISHED_AT", ""),
        "extract_status": os.environ.get("EXTRACT_STATUS", ""),
        "extract_exit_code": os.environ.get("EXTRACT_EXIT_CODE", ""),
        "vpn_status": vpn_status,
        "patterns": patterns,
        "season_types": _csv_values(os.environ.get("SEASON_TYPES", "")),
        "endpoints": endpoints,
        "season_start": season_start_raw,
        "season_end": season_end_raw,
        "parent_lane_id": os.environ.get("PARENT_LANE_ID", ""),
        "split_generation": int(os.environ.get("SPLIT_GENERATION") or 0),
        "support_rules": support_rules,
        "artifact_requirements": {
            "lane_metadata": final_outcome != "complete",
            "vpn_diagnostics": final_outcome != "complete" and not resume_only,
        },
        "telemetry": {
            "planned_calls": planned_calls,
            "journal_skips": journal_skips,
            "failed_calls": failed_calls,
            "tables_persisted": tables_persisted,
            "rows_persisted": rows_persisted,
            "zero_row_reason": zero_row_reason,
            "circuit_breaker_endpoints": extract_summary.get("circuit_breaker_endpoints", []),
            "rate_degradation_events": extract_summary.get("rate_degradation_events", []),
            "extract_summary_parse_error": extract_summary_parse_error,
            "db_telemetry": db_telemetry,
        },
        "extract_summary": extract_summary,
        "vpn": {
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
