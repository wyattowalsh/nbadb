from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "actions" / "nordvpn-connect" / "connect.py"
)
MODULE_CODE = compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec")


def _load_module():
    module = types.ModuleType("nordvpn_connect_action")
    module.__file__ = str(MODULE_PATH)
    exec(MODULE_CODE, module.__dict__)
    return module


def _read_outputs(path: Path) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        outputs[key] = value
    return outputs


@pytest.fixture
def runner_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner-temp"))
    return output_path


def test_env_int_validates_type_and_minimum(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()

    assert module.env_int("SHARD_INDEX", 7, minimum=0) == 7

    monkeypatch.setenv("SHARD_INDEX", "")
    assert module.env_int("SHARD_INDEX", 7, minimum=0) == 7

    monkeypatch.setenv("SHARD_INDEX", "oops")
    with pytest.raises(module.ActionError, match="SHARD_INDEX must be an integer"):
        module.env_int("SHARD_INDEX", 7, minimum=0)

    monkeypatch.setenv("SHARD_INDEX", "-1")
    with pytest.raises(module.ActionError, match="SHARD_INDEX must be >= 0"):
        module.env_int("SHARD_INDEX", 7, minimum=0)


def test_parse_quarantined_servers_normalizes_and_rejects_non_arrays(
    runner_env: Path,
) -> None:
    module = _load_module()

    assert module.parse_quarantined_servers(
        '[" us1001.nordvpn.com ", "", "us1001.nordvpn.com", 5]'
    ) == ("us1001.nordvpn.com", "5")

    with pytest.raises(module.ActionError, match="JSON array"):
        module.parse_quarantined_servers('{"server":"us1001.nordvpn.com"}')


def test_retry_http_get_raises_when_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
    tmp_path: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: 4.0)

    with pytest.raises(module.ActionError, match="budget is exhausted"):
        action.retry_http_get(
            "NordVPN server recommendations request",
            tmp_path / "servers.json",
            "https://example.test/recommendations",
        )


def test_pid_alive_returns_false_when_probe_times_out(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["sudo", "kill", "-0", "12345"], timeout=10)

    monkeypatch.setattr(module, "run_command", _raise_timeout)

    assert action.pid_alive("12345") is False


def test_cleanup_openvpn_terminates_foreground_process_group(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()

    class _FakeProcess:
        pid = 43210

        def __init__(self) -> None:
            self.wait_calls: list[float | None] = []

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            return 0

    proc = _FakeProcess()
    action.openvpn_process = proc
    kills: list[tuple[int, int]] = []

    monkeypatch.setattr(module.os, "killpg", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(module, "run_quiet", lambda *args, **kwargs: None)

    action.cleanup_openvpn()

    assert kills == [(43210, module.signal.SIGTERM)]
    assert proc.wait_calls == [5]
    assert action.openvpn_process is None


def test_make_workdir_readable_keeps_auth_material_private(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.auth_file.write_text("user\npassword\n", encoding="utf-8")
    action.creds_file.write_text("{}", encoding="utf-8")
    action.log_file.write_text("log\n", encoding="utf-8")
    config_path = action.work_dir / "us1001.nordvpn.com.ovpn"
    config_path.write_text("client\n", encoding="utf-8")
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "run_quiet", lambda cmd, **kwargs: calls.append(cmd))

    action.make_workdir_readable()

    assert ["sudo", "chmod", "-R", "a+rX", str(action.work_dir)] not in calls
    assert ["sudo", "chmod", "a+rx", str(action.work_dir)] in calls
    assert ["sudo", "chmod", "600", str(action.auth_file)] in calls
    assert ["sudo", "chmod", "600", str(action.creds_file)] in calls
    assert ["sudo", "chmod", "a+rX", str(action.log_file)] in calls
    assert ["sudo", "chmod", "a+rX", str(config_path)] in calls


def test_finalize_preserves_auth_file_for_connected_tunnel(runner_env: Path) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.status = "connected"

    for path in (
        action.auth_file,
        action.creds_file,
        action.servers_file,
        action.verify_file,
        action.baseline_file,
    ):
        path.write_text("secret\n", encoding="utf-8")

    action.finalize()

    assert action.auth_file.exists()
    assert not action.creds_file.exists()
    assert not action.servers_file.exists()
    assert not action.verify_file.exists()
    assert not action.baseline_file.exists()


def test_finalize_removes_auth_file_when_tunnel_not_connected(runner_env: Path) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.status = "vpn_network_error"
    action.auth_file.write_text("user\npassword\n", encoding="utf-8")

    action.finalize()

    assert not action.auth_file.exists()


def test_run_command_kills_timed_out_process_groups(
    runner_env: Path,
    tmp_path: Path,
) -> None:
    module = _load_module()
    child_pid_path = tmp_path / "child.pid"
    script = """
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(str(child.pid))
time.sleep(60)
"""

    with pytest.raises(subprocess.TimeoutExpired) as excinfo:
        module.run_command([sys.executable, "-c", script, str(child_pid_path)], timeout=2)

    assert excinfo.value.cmd
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except OSError:
            break
        time.sleep(0.1)
    else:
        pytest.fail(f"child process {child_pid} survived the timed-out process group")


def test_main_writes_bounded_outputs_for_init_time_action_failure(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    monkeypatch.setenv("QUARANTINED_SERVERS_JSON", "not-json")

    rc = module.main()

    assert rc == 1
    assert _read_outputs(runner_env) == {
        "status": "vpn_network_error",
        "attempted-servers-json": "[]",
        "failed-servers-json": "[]",
    }


def test_main_writes_outputs_for_action_failure_after_initialization(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()

    def _raise_action_failure(self) -> int:
        raise module.ActionError("vpn_auth_failure", "bad credentials")

    monkeypatch.setattr(module.NordVpnConnectAction, "run", _raise_action_failure)
    monkeypatch.setattr(
        module.NordVpnConnectAction,
        "make_workdir_readable",
        lambda self: None,
    )
    monkeypatch.setattr(module.NordVpnConnectAction, "cleanup_openvpn", lambda self: None)

    rc = module.main()

    assert rc == 1
    assert _read_outputs(runner_env) == {
        "status": "vpn_auth_failure",
        "attempted-servers-json": "[]",
        "failed-servers-json": "[]",
    }


def test_main_writes_outputs_for_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()

    def _raise_unexpected(self) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(module.NordVpnConnectAction, "run", _raise_unexpected)
    monkeypatch.setattr(
        module.NordVpnConnectAction,
        "make_workdir_readable",
        lambda self: None,
    )
    monkeypatch.setattr(module.NordVpnConnectAction, "cleanup_openvpn", lambda self: None)

    rc = module.main()

    assert rc == 1
    assert _read_outputs(runner_env) == {
        "status": "vpn_network_error",
        "attempted-servers-json": "[]",
        "failed-servers-json": "[]",
    }


def test_attempt_server_records_verified_tunnel_details(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.auth_file.write_text("user\npassword\n", encoding="utf-8")
    action.baseline_ip = "1.1.1.1"

    def _fake_retry_http_get(label: str, output_path: Path, url: str, *extra_args: str) -> bool:
        if label.startswith("NordVPN OpenVPN config download"):
            output_path.write_text("client\n", encoding="utf-8")
            return True
        if label == "VPN verification probe":
            output_path.write_text(json.dumps({"ip": "2.2.2.2"}), encoding="utf-8")
            return True
        raise AssertionError(f"unexpected retry label: {label}")

    monkeypatch.setattr(action, "retry_http_get", _fake_retry_http_get)
    monkeypatch.setattr(
        action, "config_url", lambda server, technology: "https://example.test/server.ovpn"
    )
    monkeypatch.setattr(action, "make_workdir_readable", lambda: None)
    monkeypatch.setattr(action, "pid_alive", lambda pid: True)
    monkeypatch.setattr(action, "initialization_complete", lambda: True)
    monkeypatch.setattr(action, "get_interface", lambda: "tun0")
    monkeypatch.setattr(action, "route_uses_interface", lambda route_expr, interface: True)

    class _FakeProcess:
        def __init__(self, cmd: list[str]) -> None:
            self.cmd = cmd
            self.pid = 98765
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    launched: list[_FakeProcess] = []

    def _fake_popen(cmd: list[str], **kwargs) -> _FakeProcess:
        action.pid_file.write_text("12345", encoding="utf-8")
        proc = _FakeProcess(cmd)
        launched.append(proc)
        return proc

    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen)

    assert action.attempt_server("us1001.nordvpn.com", "openvpn_udp") is True
    assert launched
    assert "--daemon" not in launched[0].cmd
    assert action.status == "connected"
    assert action.server == "us1001.nordvpn.com"
    assert action.interface == "tun0"
    assert action.exit_ip == "2.2.2.2"
    assert action.pid == "12345"
    assert action.attempted_servers == ["us1001.nordvpn.com"]
    assert action.failed_servers == []


def test_attempt_server_classifies_auth_failure_when_openvpn_exits_early(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.auth_file.write_text("user\npassword\n", encoding="utf-8")

    def _fake_retry_http_get(label: str, output_path: Path, url: str, *extra_args: str) -> bool:
        if label.startswith("NordVPN OpenVPN config download"):
            output_path.write_text("client\n", encoding="utf-8")
            return True
        raise AssertionError(f"unexpected retry label: {label}")

    monkeypatch.setattr(action, "retry_http_get", _fake_retry_http_get)
    monkeypatch.setattr(
        action, "config_url", lambda server, technology: "https://example.test/server.ovpn"
    )
    monkeypatch.setattr(action, "make_workdir_readable", lambda: None)
    monkeypatch.setattr(action, "cleanup_openvpn", lambda: None)

    class _AuthFailedProcess:
        pid = 98765

        def poll(self):
            return 0

    def _fake_popen(cmd: list[str], **kwargs) -> _AuthFailedProcess:
        action.log_file.write_text(
            "AUTH: Received control message: AUTH_FAILED\n",
            encoding="utf-8",
        )
        return _AuthFailedProcess()

    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen)

    assert action.attempt_server("us1001.nordvpn.com", "openvpn_udp") is False
    assert action.failed_servers == ["us1001.nordvpn.com"]


def test_run_reports_auth_failure_after_all_recommended_servers_reject_credentials(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()

    monkeypatch.setattr(action, "prepare_workdir", lambda: None)
    monkeypatch.setattr(action, "install_dependencies", lambda: None)
    monkeypatch.setattr(action, "determine_baseline_ip", lambda: None)
    monkeypatch.setattr(action, "prepare_auth", lambda: None)
    monkeypatch.setattr(action, "make_workdir_readable", lambda: None)
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(action, "cleanup_openvpn", lambda: None)
    monkeypatch.setattr(action, "recommendation_servers", lambda technology: ["us1001.nordvpn.com"])
    monkeypatch.setattr(action, "attempt_server", lambda server, technology: False)
    monkeypatch.setattr(action, "auth_failed_in_log", lambda: True)

    with pytest.raises(module.ActionError) as excinfo:
        action.run()

    assert excinfo.value.status == "vpn_auth_failure"


def test_install_dependencies_skips_when_tools_are_already_present(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()

    monkeypatch.setattr(module.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "run_command", lambda *args, **kwargs: calls.append(args[0]))

    action.install_dependencies()

    assert calls == []


def test_install_dependencies_retries_timeout_once_before_succeeding(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()

    monkeypatch.setattr(module.shutil, "which", lambda tool: None)
    monkeypatch.setattr(action, "command_timeout", lambda *, cap: 120.0)
    monkeypatch.setattr(action, "remaining_budget", lambda: 120.0)

    calls: list[str] = []

    def _fake_run_command(cmd: list[str], **kwargs):
        label = " ".join(cmd[:3])
        calls.append(label)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    action.install_dependencies()

    assert calls == [
        "sudo apt-get update",
        "sudo apt-get update",
        "sudo apt-get install",
    ]


def test_run_continues_to_next_server_after_per_server_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()

    monkeypatch.setattr(action, "prepare_workdir", lambda: None)
    monkeypatch.setattr(action, "install_dependencies", lambda: None)
    monkeypatch.setattr(action, "determine_baseline_ip", lambda: None)
    monkeypatch.setattr(action, "prepare_auth", lambda: None)
    monkeypatch.setattr(action, "make_workdir_readable", lambda: None)
    cleanup_calls: list[str] = []
    monkeypatch.setattr(action, "cleanup_openvpn", lambda: cleanup_calls.append("cleanup"))
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(
        action,
        "recommendation_servers",
        lambda technology: ["us1001.nordvpn.com", "us1002.nordvpn.com"],
    )

    attempts: list[str] = []

    def _fake_attempt_server(server: str, technology: str) -> bool:
        attempts.append(server)
        if server == "us1001.nordvpn.com":
            raise module.ActionError(
                "vpn_connect_timeout",
                "OpenVPN launch exceeded the remaining VPN connection budget "
                "for us1001.nordvpn.com over openvpn_udp",
            )
        action.server = server
        action.interface = "tun0"
        action.exit_ip = "2.2.2.2"
        action.pid = "12345"
        action.status = "connected"
        return True

    monkeypatch.setattr(action, "attempt_server", _fake_attempt_server)

    assert action.run() == 0
    assert attempts == ["us1001.nordvpn.com", "us1002.nordvpn.com"]
    assert cleanup_calls == ["cleanup"]
