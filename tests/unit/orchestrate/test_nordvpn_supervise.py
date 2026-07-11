from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "actions" / "nordvpn-connect" / "supervise.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("nordvpn_supervise", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_descendant_pids_tolerates_ps_timeout(monkeypatch) -> None:
    module = _load_module()

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["ps"], timeout=5)

    monkeypatch.setattr(module.subprocess, "run", _raise_timeout)

    assert module.descendant_pids(12345) == set()


def test_kill_matching_processes_tries_sudo_and_non_sudo(monkeypatch) -> None:
    module = _load_module()
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    module.kill_matching_processes("/tmp/runner/nordvpn")

    assert calls == [
        ["sudo", "pkill", "-TERM", "-f", "/tmp/runner/nordvpn"],
        ["pkill", "-TERM", "-f", "/tmp/runner/nordvpn"],
        ["sudo", "pkill", "-KILL", "-f", "/tmp/runner/nordvpn"],
        ["pkill", "-KILL", "-f", "/tmp/runner/nordvpn"],
    ]


def test_main_timeout_emits_complete_bounded_outputs(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("OVERALL_TIMEOUT_SECONDS", "1")

    class _FakeChild:
        pid = 12345

        def poll(self):
            return None

    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: _FakeChild())
    monotonic_values = iter((0.0, 12.0))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(module, "terminate_tree", lambda pid: None)
    monkeypatch.setattr(module, "kill_matching_processes", lambda pattern: None)

    assert module.main() == 1
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "status=vpn_connect_timeout",
        "auth-source=",
        "nba-probe-status=timeout",
        "nba-probe-diagnostic=NBA probes did not complete before the VPN action deadline",
        "attempted-servers-json=[]",
        "failed-servers-json=[]",
    ]
