from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from contextlib import suppress


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
    force_reextract = os.environ.get("FORCE_REEXTRACT", "").strip().lower() == "true"

    if season_start and season_end:
        cmd.extend(["--seasons", f"{season_start}:{season_end}"])
    if patterns:
        cmd.extend(["--pattern", patterns])
    if season_types:
        cmd.extend(["--season-types", season_types])
    if endpoints:
        cmd.extend(["--endpoint", endpoints])
    if force_reextract:
        cmd.append("--force")
    return cmd


def main() -> int:
    timeout_seconds = int(os.environ["LANE_TIMEOUT_SECONDS"])
    cmd = build_command()
    print(f"::notice::Running: {' '.join(shlex.quote(part) for part in cmd)}")

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    append_output("started-at", started_at)

    child = subprocess.Popen(cmd, start_new_session=True)
    deadline = time.monotonic() + timeout_seconds

    exit_code: int
    status: str
    while True:
        rc = child.poll()
        if rc is not None:
            exit_code = rc
            status = "complete" if rc == 0 else "extract-error"
            break
        if time.monotonic() >= deadline:
            print(
                f"::error::Extraction lane exceeded the allotted timeout "
                f"({timeout_seconds}s)"
            )
            terminate_tree(child.pid)
            exit_code = 124
            status = "extract-timeout"
            break
        time.sleep(1)

    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    append_output("finished-at", finished_at)
    append_output("exit-code", str(exit_code))
    append_output("status", status)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
