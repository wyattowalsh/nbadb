from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / ".github"
    / "actions"
    / "nordvpn-connect"
    / "supervise.py"
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
