from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

SUPERVISOR_HEADROOM_SECONDS = 10


def append_output(key: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
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
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with suppress(ProcessLookupError):
            os.killpg(root_pid, sig)
        for pid in descendants:
            with suppress(ProcessLookupError):
                os.kill(pid, sig)
        if sig is signal.SIGTERM:
            time.sleep(5)


def kill_matching_processes(pattern: str) -> None:
    if not pattern:
        return
    for sig_name in ("TERM", "KILL"):
        for prefix in (["sudo"], []):
            with suppress(subprocess.TimeoutExpired, OSError):
                subprocess.run(
                    [*prefix, "pkill", f"-{sig_name}", "-f", pattern],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
        if sig_name == "TERM":
            time.sleep(5)


def main() -> int:
    action_dir = Path(__file__).resolve().parent
    connect_script = action_dir / "connect.py"
    overall_timeout = int(os.environ.get("OVERALL_TIMEOUT_SECONDS", "300").strip() or "300")
    deadline = time.monotonic() + overall_timeout + SUPERVISOR_HEADROOM_SECONDS

    child = subprocess.Popen(
        [sys.executable, str(connect_script)],
        start_new_session=True,
    )

    while True:
        rc = child.poll()
        if rc is not None:
            return rc
        if time.monotonic() >= deadline:
            print(
                f"::error::NordVPN action exceeded the outer action timeout "
                f"({overall_timeout + SUPERVISOR_HEADROOM_SECONDS}s)"
            )
            terminate_tree(child.pid)
            kill_matching_processes(str(Path(os.environ.get("RUNNER_TEMP", "")) / "nordvpn"))
            append_output("status", "vpn_connect_timeout")
            append_output("nba-probe-status", "timeout")
            append_output(
                "nba-probe-diagnostic",
                "NBA probes did not complete before the VPN action deadline",
            )
            append_output("attempted-servers-json", "[]")
            append_output("failed-servers-json", "[]")
            return 1
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
