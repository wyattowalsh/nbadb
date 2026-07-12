from __future__ import annotations

import os
import shlex
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path

DIRECT_TIMEOUT_CAP_PATTERNS = frozenset(
    {
        "date",
        "game",
        "player_season",
        "team_season",
        "player_team_season",
    }
)
ENDPOINT_STALL_TIMEOUT_SECONDS = {
    "video_details_asset": 600,
}


def append_output(key: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def descendant_pids(root_pid: int) -> set[int]:
    descendants: set[int] = set()
    frontier = {root_pid}
    while frontier:
        pid = frontier.pop()
        try:
            result = subprocess.run(
                ["ps", "-o", "pid=", "--ppid", str(pid)],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            print(
                f"::warning::Timed out while listing descendants for PID {pid}; "
                "continuing with the current partial process tree"
            )
            continue
        children = {
            int(line.strip())
            for line in (result.stdout or "").splitlines()
            if line.strip().isdigit()
        }
        new_children = children - descendants
        descendants.update(new_children)
        frontier.update(new_children)
    return descendants


def terminate_tree(root_pid: int) -> None:
    descendants = descendant_pids(root_pid)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        with suppress(ProcessLookupError):
            os.killpg(root_pid, sig)
        for pid in descendants:
            with suppress(ProcessLookupError):
                os.kill(pid, sig)
        if sig is not signal.SIGKILL:
            time.sleep(5)


def build_command() -> list[str]:
    cmd = ["uv", "run", "nbadb", "backfill", "run", "--extract-only", "--verbose"]
    season_start = os.environ.get("SEASON_START", "").strip()
    season_end = os.environ.get("SEASON_END", "").strip()
    patterns = os.environ.get("PATTERNS", "").strip()
    season_types = os.environ.get("SEASON_TYPES", "").strip()
    endpoints = os.environ.get("BACKFILL_ENDPOINTS", "").strip()
    summary_path = os.environ.get("EXTRACT_SUMMARY_PATH", "").strip()
    force_reextract = os.environ.get("FORCE_REEXTRACT", "").strip().lower() == "true"

    if season_start and season_end:
        cmd.extend(["--seasons", f"{season_start}:{season_end}"])
    if patterns:
        cmd.extend(["--pattern", patterns])
    if season_types:
        cmd.extend(["--season-types", season_types])
    if endpoints:
        cmd.extend(["--endpoint", endpoints])
    if summary_path:
        cmd.extend(["--summary-path", summary_path])
    if force_reextract:
        cmd.append("--force")
    return cmd


def env_timeout_seconds() -> int:
    raw = os.environ.get("LANE_TIMEOUT_SECONDS", "").strip()
    try:
        timeout_seconds = int(raw)
    except ValueError as exc:
        raise ValueError(f"LANE_TIMEOUT_SECONDS must be an integer, got {raw!r}") from exc
    if timeout_seconds <= 0:
        raise ValueError(f"LANE_TIMEOUT_SECONDS must be > 0, got {timeout_seconds}")
    return timeout_seconds


def direct_timeout_cap_seconds() -> int | None:
    raw = os.environ.get("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "").strip()
    if not raw:
        return None
    try:
        timeout_seconds = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS must be an integer, got {raw!r}"
        ) from exc
    if timeout_seconds <= 0:
        raise ValueError(
            f"NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS must be > 0, got {timeout_seconds}"
        )
    return timeout_seconds


def direct_timeout_cap_applies() -> bool:
    patterns = {
        value.strip() for value in os.environ.get("PATTERNS", "").split(",") if value.strip()
    }
    return bool(patterns & DIRECT_TIMEOUT_CAP_PATTERNS)


def selected_endpoints() -> set[str]:
    return {
        value.strip()
        for value in os.environ.get("BACKFILL_ENDPOINTS", "").split(",")
        if value.strip()
    }


def validate_stall_watchdog_endpoint_isolation() -> None:
    endpoints = selected_endpoints()
    watched = endpoints & ENDPOINT_STALL_TIMEOUT_SECONDS.keys()
    unbounded = endpoints - ENDPOINT_STALL_TIMEOUT_SECONDS.keys()
    if watched and unbounded:
        raise ValueError(
            "stall-watched extraction endpoints must run in an isolated lane; "
            f"watched={sorted(watched)!r} unbounded={sorted(unbounded)!r}"
        )


def endpoint_stall_timeout_seconds() -> int | None:
    endpoints = selected_endpoints()
    caps = [
        ENDPOINT_STALL_TIMEOUT_SECONDS[endpoint]
        for endpoint in endpoints
        if endpoint in ENDPOINT_STALL_TIMEOUT_SECONDS
    ]
    return min(caps) if caps else None


def effective_timeout_seconds(timeout_seconds: int) -> int:
    effective_timeout = timeout_seconds
    if (
        os.environ.get("NBADB_NETWORK_MODE", "").strip().lower() == "direct"
        and direct_timeout_cap_applies()
    ):
        cap_seconds = direct_timeout_cap_seconds()
        if cap_seconds is not None:
            effective_timeout = min(effective_timeout, cap_seconds)
    return effective_timeout


def extraction_heartbeat_path() -> Path:
    root = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    return root / f"nbadb-extraction-heartbeat-{os.getpid()}"


def describe_timeout(timeout_seconds: int, effective_timeout_seconds: int) -> None:
    if timeout_seconds == effective_timeout_seconds:
        return
    print(
        "::notice::Extraction timeout capped from "
        f"{timeout_seconds}s to {effective_timeout_seconds}s"
    )


def status_for_exit_code(exit_code: int) -> str:
    if exit_code == 0:
        return "complete"
    if exit_code in {
        124,
        130,
        137,
        143,
        -signal.SIGINT,
        -signal.SIGTERM,
        -signal.SIGKILL,
    }:
        return "extract-timeout"
    return "extract-error"


def main() -> int:
    validate_stall_watchdog_endpoint_isolation()
    timeout_seconds = env_timeout_seconds()
    effective_timeout = effective_timeout_seconds(timeout_seconds)
    describe_timeout(timeout_seconds, effective_timeout)
    append_output("effective-timeout-seconds", str(effective_timeout))
    stall_timeout = endpoint_stall_timeout_seconds()
    heartbeat_path: Path | None = None
    child_env: dict[str, str] | None = None
    if stall_timeout is not None:
        heartbeat_path = extraction_heartbeat_path()
        heartbeat_path.touch()
        last_heartbeat_mtime_ns = heartbeat_path.stat().st_mtime_ns
        child_env = os.environ.copy()
        child_env["NBADB_EXTRACTION_HEARTBEAT_PATH"] = str(heartbeat_path)
        append_output("stall-timeout-seconds", str(stall_timeout))
        print(
            "::notice::Extraction no-progress watchdog enabled at "
            f"{stall_timeout}s using durable chunk heartbeats"
        )
    cmd = build_command()
    print(f"::notice::Running: {' '.join(shlex.quote(part) for part in cmd)}")

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    append_output("started-at", started_at)

    child = subprocess.Popen(cmd, start_new_session=True, env=child_env)
    deadline = time.monotonic() + effective_timeout
    if heartbeat_path is None:
        last_heartbeat_mtime_ns = None
    last_progress_at = time.monotonic()

    exit_code: int
    status: str
    try:
        while True:
            rc = child.poll()
            if rc is not None:
                exit_code = rc
                status = status_for_exit_code(rc)
                break
            now = time.monotonic()
            if heartbeat_path is not None:
                try:
                    current_mtime_ns = heartbeat_path.stat().st_mtime_ns
                except OSError as exc:
                    print(
                        "::error::Extraction heartbeat became unreadable "
                        f"({type(exc).__name__}); terminating the lane"
                    )
                    terminate_tree(child.pid)
                    exit_code = 124
                    status = "extract-timeout"
                    break
                if current_mtime_ns != last_heartbeat_mtime_ns:
                    last_heartbeat_mtime_ns = current_mtime_ns
                    last_progress_at = now
            if now >= deadline:
                print(
                    f"::error::Extraction lane exceeded the allotted timeout ({effective_timeout}s)"
                )
                terminate_tree(child.pid)
                exit_code = 124
                status = "extract-timeout"
                break
            if stall_timeout is not None and now - last_progress_at >= stall_timeout:
                print(f"::error::Extraction lane produced no completed chunk for {stall_timeout}s")
                terminate_tree(child.pid)
                exit_code = 124
                status = "extract-timeout"
                break
            time.sleep(1)
    except BaseException:
        terminate_tree(child.pid)
        raise
    finally:
        if heartbeat_path is not None:
            heartbeat_path.unlink(missing_ok=True)

    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    append_output("finished-at", finished_at)
    append_output("exit-code", str(exit_code))
    append_output("status", status)
    if status != "complete":
        print(f"::warning::Extraction lane finished with status={status} exit_code={exit_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
