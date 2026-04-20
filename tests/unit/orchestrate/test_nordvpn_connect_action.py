from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "actions" / "nordvpn-connect" / "connect.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("nordvpn_connect_action", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
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
    monkeypatch.setattr(action, "command_timeout", lambda *, cap: 5.0)
    monkeypatch.setattr(action, "make_workdir_readable", lambda: None)
    monkeypatch.setattr(action, "pid_alive", lambda pid: True)
    monkeypatch.setattr(action, "initialization_complete", lambda: True)
    monkeypatch.setattr(action, "get_interface", lambda: "tun0")
    monkeypatch.setattr(action, "route_uses_interface", lambda route_expr, interface: True)

    def _fake_run_command(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        action.pid_file.write_text("12345", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    assert action.attempt_server("us1001.nordvpn.com", "openvpn_udp") is True
    assert action.status == "connected"
    assert action.server == "us1001.nordvpn.com"
    assert action.interface == "tun0"
    assert action.exit_ip == "2.2.2.2"
    assert action.pid == "12345"
    assert action.attempted_servers == ["us1001.nordvpn.com"]
    assert action.failed_servers == []
