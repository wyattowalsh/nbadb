from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "run_with_deadline.sh"
SUPERVISOR_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "actions" / "nordvpn-connect" / "supervise.py"
)


def _load_supervisor_module():
    spec = importlib.util.spec_from_file_location("nordvpn_supervise_deadline", SUPERVISOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_with_deadline_returns_child_exit_code(tmp_path: Path) -> None:
    output_path = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(output_path)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "10",
            "0",
            sys.executable,
            "-c",
            "raise SystemExit(7)",
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 7
    assert not output_path.exists()


def test_run_with_deadline_writes_timeout_outputs(tmp_path: Path) -> None:
    output_path = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(output_path)

    started = time.monotonic()
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "1",
            "0",
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 1
    assert elapsed < 5
    assert "Command exceeded 1s deadline" in result.stderr
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "status=vpn_connect_timeout",
        "nba-probe-status=timeout",
        "nba-probe-diagnostic=NBA probes did not complete before the command deadline",
        "attempted-servers-json=[]",
        "failed-servers-json=[]",
    ]


def test_supervisor_timeout_writes_nba_probe_outputs(monkeypatch, tmp_path: Path) -> None:
    module = _load_supervisor_module()
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner"))
    monkeypatch.setenv("OVERALL_TIMEOUT_SECONDS", "1")

    class _Child:
        pid = 43210

        def poll(self):
            return None

    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: _Child())
    monotonic_values = iter((100.0, 132.0))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    terminated: list[int] = []
    killed_patterns: list[str] = []
    monkeypatch.setattr(module, "terminate_tree", lambda pid: terminated.append(pid))
    monkeypatch.setattr(
        module,
        "kill_matching_processes",
        lambda pattern: killed_patterns.append(pattern),
    )

    assert module.main() == 1
    assert terminated == [43210]
    assert killed_patterns == [str(tmp_path / "runner" / "nordvpn")]
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "status=vpn_connect_timeout",
        "nba-probe-status=timeout",
        "nba-probe-diagnostic=NBA probes did not complete before the VPN action deadline",
        "attempted-servers-json=[]",
        "failed-servers-json=[]",
    ]
