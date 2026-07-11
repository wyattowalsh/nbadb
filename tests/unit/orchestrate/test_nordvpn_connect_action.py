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
ACTION_METADATA_PATH = MODULE_PATH.with_name("action.yml")
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


def _write_valid_nba_response(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "resource": "commonteamyears",
                "resultSets": [
                    {
                        "name": "TeamYears",
                        "headers": [
                            "LEAGUE_ID",
                            "TEAM_ID",
                            "MIN_YEAR",
                            "MAX_YEAR",
                            "ABBREVIATION",
                        ],
                        "rowSet": [["00", 1610612737, "1949", "2024", "ATL"]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


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


@pytest.mark.parametrize(
    ("overall_budget", "attempt_deadline", "expected_request", "expected_process"),
    [
        (60.0, 103.0, "2.25", 2.5),
        (6.0, None, "5.25", 5.5),
    ],
)
def test_retry_http_get_honors_attempt_and_overall_deadlines(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
    tmp_path: Path,
    overall_budget: float,
    attempt_deadline: float | None,
    expected_request: str,
    expected_process: float,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: overall_budget)
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def _fake_run_command(cmd: list[str], **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "200", "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    assert action.retry_http_get(
        "bounded request",
        tmp_path / "response.json",
        "https://example.test/data",
        attempt_deadline=attempt_deadline,
    )

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[cmd.index("--max-time") + 1] == expected_request
    assert cmd[cmd.index("--connect-timeout") + 1] == expected_request
    assert kwargs["timeout"] == expected_process
    assert kwargs["termination_grace"] == module.NBA_PROBE_TERMINATION_GRACE_SECONDS


def test_verification_helpers_honor_attempt_and_overall_deadlines(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def _fake_run_command(cmd: list[str], **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:4] == ["ip", "-o", "link", "show"]:
            return subprocess.CompletedProcess(cmd, 0, "7: tun0: <POINTOPOINT>", "")
        if cmd[:4] == ["ip", "route", "show", "default"]:
            return subprocess.CompletedProcess(cmd, 0, "default dev tun0", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    assert action.get_interface(attempt_deadline=102.0) == "tun0"
    assert action.route_uses_interface("default", "tun0", attempt_deadline=102.0) is True
    assert action.pid_alive("12345", attempt_deadline=102.0) is True

    assert len(calls) == 3
    for _cmd, kwargs in calls:
        assert kwargs["timeout"] == 1.5
        assert kwargs["termination_grace"] == module.NBA_PROBE_TERMINATION_GRACE_SECONDS


def test_nba_probe_succeeds_with_compatible_headers_and_bounded_request(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def _fake_run_command(cmd: list[str], **kwargs):
        calls.append((cmd, kwargs))
        _write_valid_nba_response(Path(cmd[cmd.index("-o") + 1]))
        return subprocess.CompletedProcess(cmd, 0, "200", "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    assert action.probe_nba_stats() is True
    assert action.nba_probe_status == "passed"
    assert action.nba_probe_diagnostic == "NBA Stats response matched the expected JSON structure"
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    headers = [cmd[index + 1] for index, value in enumerate(cmd) if value == "-H"]
    assert cmd[-1] == module.NBA_PROBE_DEFAULT_URL
    assert cmd[cmd.index("--max-time") + 1] == "10"
    assert cmd[cmd.index("--max-filesize") + 1] == str(module.NBA_PROBE_MAX_BYTES)
    assert "--compressed" in cmd
    assert "Accept: application/json, text/plain, */*" in headers
    assert "Referer: https://www.nba.com/" in headers
    assert any(header.startswith("User-Agent: Mozilla/5.0 ") for header in headers)
    assert kwargs["timeout"] == 10.25


def test_nba_probe_timeout_is_capped_by_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    calls: list[tuple[list[str], float]] = []

    def _raise_timeout(cmd: list[str], **kwargs):
        calls.append((cmd, kwargs["timeout"]))
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(module, "run_command", _raise_timeout)

    assert action.probe_nba_stats(attempt_deadline=103.0) is False
    assert action.nba_probe_status == "timeout"
    assert action.nba_probe_diagnostic == "NBA Stats probe timed out"
    assert len(calls) == 1
    cmd, process_timeout = calls[0]
    assert cmd[cmd.index("--max-time") + 1] == "2.25"
    assert process_timeout == 2.5


@pytest.mark.parametrize(
    ("result_set", "reason"),
    [
        ({"name": "Other", "headers": ["TEAM_ID"], "rowSet": [[1]]}, "wrong name"),
        (
            {
                "name": "TeamYears",
                "headers": ["LEAGUE_ID", "TEAM_ID"],
                "rowSet": [["00", 1]],
            },
            "missing headers",
        ),
        (
            {
                "name": "TeamYears",
                "headers": [
                    "LEAGUE_ID",
                    "TEAM_ID",
                    "MIN_YEAR",
                    "MAX_YEAR",
                    "ABBREVIATION",
                ],
                "rowSet": [],
            },
            "empty rows",
        ),
    ],
)
def test_nba_probe_rejects_unattested_team_years_shapes(
    tmp_path: Path,
    result_set: dict[str, object],
    reason: str,
) -> None:
    module = _load_module()
    path = tmp_path / "probe.json"
    path.write_text(json.dumps({"resultSets": [result_set]}), encoding="utf-8")

    assert module.NordVpnConnectAction.nba_probe_content_valid(path) is False, reason


def test_nba_probe_rejects_malformed_body(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)

    def _fake_run_command(cmd: list[str], **kwargs):
        Path(cmd[cmd.index("-o") + 1]).write_text("<html>blocked</html>", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "200", "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    assert action.probe_nba_stats() is False
    assert action.nba_probe_status == "invalid_content"
    assert action.nba_probe_diagnostic == (
        "NBA Stats probe returned malformed or unexpected content"
    )


def test_nba_probe_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBA_PROBE_ENABLED", "false")
    action = module.NordVpnConnectAction()

    def _unexpected_request(*args, **kwargs):
        raise AssertionError("disabled NBA probe made an HTTP request")

    monkeypatch.setattr(module, "run_command", _unexpected_request)

    assert action.probe_nba_stats() is True
    assert action.nba_probe_status == "disabled"
    assert action.nba_probe_diagnostic == "NBA Stats probe disabled by configuration"


def test_nba_probe_uses_custom_url_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    secret_marker = "secret-query-marker"
    monkeypatch.setenv(
        "NBA_PROBE_URL",
        f"https://stats.nba.com/stats/customprobe?LeagueID=00&key={secret_marker}",
    )
    monkeypatch.setenv("NBA_PROBE_TIMEOUT_SECONDS", "3")
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    calls: list[list[str]] = []

    def _fake_run_command(cmd: list[str], **kwargs):
        calls.append(cmd)
        _write_valid_nba_response(Path(cmd[cmd.index("-o") + 1]))
        return subprocess.CompletedProcess(cmd, 0, "200", "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    assert action.probe_nba_stats() is True
    assert calls[0][-1].endswith(f"key={secret_marker}")
    assert calls[0][calls[0].index("--max-time") + 1] == "3"
    action.finalize()
    assert secret_marker not in runner_env.read_text(encoding="utf-8")
    assert secret_marker not in capsys.readouterr().out


def test_nba_stack_probe_runs_both_discovery_canaries_with_bounded_process(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(
        module.shutil, "which", lambda tool: "/usr/bin/uv" if tool == "uv" else None
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def _fake_run_command(cmd: list[str], **kwargs):
        calls.append((cmd, kwargs))
        payload = {
            "status": "passed",
            "endpoints": {
                "common_all_players": {"rows": 4900},
                "league_game_log": {"rows": 2460},
            },
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "ignored diagnostic")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    assert action.probe_nba_discovery_stack() is True
    assert action.nba_probe_status == "passed"
    assert action.nba_probe_diagnostic == (
        "NBA discovery stack passed (common_all_players=4900 rows, league_game_log=2460 rows)"
    )
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[:8] == [
        "/usr/bin/uv",
        "run",
        "--project",
        str(action.project_root),
        "--frozen",
        "--quiet",
        "python",
        str(action.nba_stack_probe_script),
    ]
    assert cmd[cmd.index("--request-timeout-seconds") + 1] == "8"
    assert cmd[cmd.index("--season") + 1] == module.NBA_STACK_PROBE_DEFAULT_SEASON
    assert kwargs["timeout"] == 18.25
    assert kwargs["termination_grace"] == module.NBA_PROBE_TERMINATION_GRACE_SECONDS


def test_nba_stack_probe_timeout_is_capped_by_server_attempt_deadline(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(module.shutil, "which", lambda tool: "/usr/bin/uv")
    calls: list[tuple[list[str], float]] = []

    def _raise_timeout(cmd: list[str], **kwargs):
        calls.append((cmd, kwargs["timeout"]))
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(module, "run_command", _raise_timeout)

    assert action.probe_nba_discovery_stack(attempt_deadline=102.5) is False
    assert action.nba_probe_status == "stack_timeout"
    assert calls[0][0][calls[0][0].index("--request-timeout-seconds") + 1] == "1"
    assert calls[0][1] == 2.0


def test_nba_stack_probe_transport_failure_remains_server_specific(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(module.shutil, "which", lambda tool: "/usr/bin/uv")

    def _fake_run_command(cmd: list[str], **kwargs):
        payload = {
            "status": "failed",
            "endpoint": "common_all_players",
            "failure_kind": "exception",
            "error_type": "TransientError",
        }
        return subprocess.CompletedProcess(cmd, 1, json.dumps(payload), "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    assert action.probe_nba_discovery_stack() is False
    assert action.nba_probe_status == "stack_transport_failed"
    assert action.nba_probe_diagnostic == (
        "NBA discovery stack probe failed at common_all_players (TransientError)"
    )


@pytest.mark.parametrize(
    ("returncode", "payload", "expected_action_status", "expected_probe_status"),
    [
        (1, None, "nba_stack_runtime_error", "stack_runtime_error"),
        (
            1,
            {
                "status": "failed",
                "endpoint": "league_game_log",
                "failure_kind": "missing_columns",
                "error_type": "ProbeContractError",
            },
            "nba_stack_contract_error",
            "stack_contract_error",
        ),
        (
            1,
            {
                "status": "failed",
                "endpoint": "common_all_players",
                "failure_kind": "invalid_values",
                "error_type": "ProbeContractError",
            },
            "nba_stack_contract_error",
            "stack_contract_error",
        ),
        (
            1,
            {
                "status": "failed",
                "endpoint": "common_all_players",
                "failure_kind": "exception",
                "error_type": "RuntimeError",
            },
            "nba_stack_runtime_error",
            "stack_runtime_error",
        ),
        (
            0,
            {"status": "passed", "endpoints": {"common_all_players": {"rows": 1}}},
            "nba_stack_invalid_attestation",
            "stack_invalid_attestation",
        ),
    ],
)
def test_nba_stack_probe_host_independent_failures_are_fatal(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
    returncode: int,
    payload: dict[str, object] | None,
    expected_action_status: str,
    expected_probe_status: str,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(module.shutil, "which", lambda tool: "/usr/bin/uv")

    def _fake_run_command(cmd: list[str], **kwargs):
        stdout = "" if payload is None else json.dumps(payload)
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    with pytest.raises(module.ActionError) as excinfo:
        action.probe_nba_discovery_stack()

    assert excinfo.value.status == expected_action_status
    assert action.nba_probe_status == expected_probe_status


def test_nba_stack_probe_missing_runtime_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(module.shutil, "which", lambda tool: None)

    with pytest.raises(module.ActionError) as excinfo:
        action.probe_nba_discovery_stack()

    assert excinfo.value.status == "nba_stack_unavailable"
    assert action.nba_probe_status == "stack_unavailable"


def test_nba_stack_probe_failure_diagnostic_does_not_echo_child_content(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(module.shutil, "which", lambda tool: "/usr/bin/uv")
    secret_marker = "credential-secret-marker"

    def _fake_run_command(cmd: list[str], **kwargs):
        payload = {"status": "failed", "endpoint": secret_marker, "error_type": secret_marker}
        return subprocess.CompletedProcess(cmd, 1, json.dumps(payload), secret_marker)

    monkeypatch.setattr(module, "run_command", _fake_run_command)

    with pytest.raises(module.ActionError) as excinfo:
        action.probe_nba_discovery_stack()

    assert excinfo.value.status == "nba_stack_invalid_attestation"
    assert action.nba_probe_status == "stack_invalid_attestation"
    assert action.nba_probe_diagnostic == (
        "NBA discovery stack probe returned invalid failure attestation"
    )
    assert secret_marker not in action.nba_probe_diagnostic


def test_recommendations_exclude_runtime_failures_across_fallback_technologies(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.server_limit = 2
    action.failed_servers = ["us1001.nordvpn.com"]
    requested_urls: list[str] = []

    def _fake_retry_http_get(
        label: str,
        output_path: Path,
        url: str,
        *extra_args: str,
    ) -> bool:
        requested_urls.append(url)
        output_path.write_text(
            json.dumps(
                [
                    {"hostname": "us1001.nordvpn.com"},
                    {"hostname": "us1002.nordvpn.com"},
                    {"hostname": "us1003.nordvpn.com"},
                ]
            ),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(action, "retry_http_get", _fake_retry_http_get)

    assert action.recommendation_servers("openvpn_tcp") == [
        "us1002.nordvpn.com",
        "us1003.nordvpn.com",
    ]
    assert "limit=3" in requested_urls[0]
    assert "openvpn_tcp" in requested_urls[0]


def test_verify_connection_keeps_full_tunnel_gate_before_network_probes(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    route_checks: list[str] = []

    def _route_rejected(route_expr: str, interface: str, **kwargs) -> bool:
        assert interface == "tun0"
        route_checks.append(route_expr)
        return False

    def _unexpected_probe(*args, **kwargs):
        raise AssertionError("network probe ran before the full-tunnel route was verified")

    monkeypatch.setattr(action, "route_uses_interface", _route_rejected)
    monkeypatch.setattr(action, "retry_http_get", _unexpected_probe)
    monkeypatch.setattr(action, "probe_nba_stats", _unexpected_probe)
    monkeypatch.setattr(action, "probe_nba_discovery_stack", _unexpected_probe)

    assert action.verify_connection("tun0") is False
    assert action.verification_failure == "route"
    assert route_checks == ["default", "0.0.0.0/1"]


def test_action_metadata_exposes_nba_probe_contract() -> None:
    metadata = ACTION_METADATA_PATH.read_text(encoding="utf-8")

    assert "nba-probe-enabled:" in metadata
    assert 'default: "true"' in metadata
    assert "nba-probe-url:" in metadata
    assert "nba-probe-timeout-seconds:" in metadata
    assert "nba-stack-probe-enabled:" in metadata
    assert "nba-stack-probe-timeout-seconds:" in metadata
    assert "nba-stack-probe-season:" in metadata
    assert "nba-probe-status:" in metadata
    assert "nba-probe-diagnostic:" in metadata
    assert "NBA_PROBE_ENABLED: ${{ inputs.nba-probe-enabled }}" in metadata
    assert "NBA_PROBE_URL: ${{ inputs.nba-probe-url }}" in metadata
    assert "NBA_PROBE_TIMEOUT_SECONDS: ${{ inputs.nba-probe-timeout-seconds }}" in metadata
    assert "NBA_STACK_PROBE_ENABLED: ${{ inputs.nba-stack-probe-enabled }}" in metadata
    assert (
        "NBA_STACK_PROBE_TIMEOUT_SECONDS: ${{ inputs.nba-stack-probe-timeout-seconds }}" in metadata
    )
    assert "NBA_STACK_PROBE_SEASON: ${{ inputs.nba-stack-probe-season }}" in metadata


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
        "nba-probe-status": "not_run",
        "nba-probe-diagnostic": "NBA Stats probe did not run",
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
        "nba-probe-status": "not_run",
        "nba-probe-diagnostic": "NBA probes have not run",
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
        "nba-probe-status": "not_run",
        "nba-probe-diagnostic": "NBA probes have not run",
        "attempted-servers-json": "[]",
        "failed-servers-json": "[]",
    }


def test_switch_to_token_auth_after_configured_credentials_rejected(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.log_file.write_text("AUTH_FAILED\n", encoding="utf-8")
    action.pid_file.write_text("123\n", encoding="utf-8")
    monkeypatch.setenv("OPENVPN_USER", "stale-user")
    monkeypatch.setenv("OPENVPN_PASSWORD", "stale-password")
    monkeypatch.setenv("NORDVPN_TOKEN", "valid-token")

    action.prepare_auth()
    assert action.auth_source == "configured"
    assert action.auth_file.read_text(encoding="utf-8") == "stale-user\nstale-password\n"

    def _fake_retry_http_get(
        label: str,
        output_path: Path,
        url: str,
        *extra_args: str,
    ) -> bool:
        assert label == "NordVPN credentials request"
        assert url == "https://api.nordvpn.com/v1/users/services/credentials"
        assert extra_args == ("-u", "token:valid-token")
        output_path.write_text(
            json.dumps({"username": "token-user", "password": "token-password"}),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(action, "cleanup_openvpn", lambda: None)
    monkeypatch.setattr(action, "retry_http_get", _fake_retry_http_get)

    assert action.switch_to_token_auth_after_rejection() is True
    assert action.auth_source == "token"
    assert action.auth_file.read_text(encoding="utf-8") == "token-user\ntoken-password\n"
    assert not action.log_file.exists()
    assert not action.pid_file.exists()


def test_attempt_server_records_verified_tunnel_details(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.auth_file.write_text("user\npassword\n", encoding="utf-8")
    action.baseline_ip = "1.1.1.1"
    network_deadlines: list[float] = []

    def _fake_retry_http_get(
        label: str,
        output_path: Path,
        url: str,
        *extra_args: str,
        **kwargs,
    ) -> bool:
        network_deadlines.append(kwargs["attempt_deadline"])
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
    monkeypatch.setattr(action, "pid_alive", lambda pid, **kwargs: True)
    monkeypatch.setattr(action, "initialization_complete", lambda: True)
    monkeypatch.setattr(action, "get_interface", lambda **kwargs: "tun0")
    monkeypatch.setattr(
        action, "route_uses_interface", lambda route_expr, interface, **kwargs: True
    )
    monkeypatch.setattr(action, "probe_nba_stats", lambda **kwargs: True)
    monkeypatch.setattr(action, "probe_nba_discovery_stack", lambda **kwargs: True)

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
    assert len(network_deadlines) == 2
    assert network_deadlines[0] == network_deadlines[1]
    assert network_deadlines[0] <= action.deadline


def test_run_quarantines_nba_blocked_server_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()
    action.work_dir.mkdir(parents=True, exist_ok=True)
    action.auth_file.write_text("user\npassword\n", encoding="utf-8")
    action.baseline_ip = "1.1.1.1"
    action.fallback_technology = ""

    for method_name in (
        "prepare_workdir",
        "install_dependencies",
        "determine_baseline_ip",
        "prepare_auth",
        "make_workdir_readable",
    ):
        monkeypatch.setattr(action, method_name, lambda: None)
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(
        action,
        "recommendation_servers",
        lambda technology: ["us1001.nordvpn.com", "us1002.nordvpn.com"],
    )
    monkeypatch.setattr(action, "pid_alive", lambda pid, **kwargs: True)
    monkeypatch.setattr(action, "initialization_complete", lambda: True)
    monkeypatch.setattr(action, "get_interface", lambda **kwargs: "tun0")
    monkeypatch.setattr(
        action, "route_uses_interface", lambda route_expr, interface, **kwargs: True
    )
    monkeypatch.setattr(action, "auth_failed_in_log", lambda: False)
    monkeypatch.setattr(module, "run_quiet", lambda *args, **kwargs: None)

    def _fake_retry_http_get(
        label: str,
        output_path: Path,
        url: str,
        *extra_args: str,
        **kwargs,
    ) -> bool:
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

    class _FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

    launched: list[_FakeProcess] = []

    def _fake_popen(cmd: list[str], **kwargs) -> _FakeProcess:
        proc = _FakeProcess(90000 + len(launched))
        launched.append(proc)
        action.pid_file.write_text(str(proc.pid), encoding="utf-8")
        return proc

    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen)
    cleanup_calls: list[str] = []

    def _fake_cleanup_openvpn() -> None:
        cleanup_calls.append("cleanup")
        action.openvpn_process = None
        action.pid_file.unlink(missing_ok=True)

    monkeypatch.setattr(action, "cleanup_openvpn", _fake_cleanup_openvpn)
    probe_results = iter((False, True))

    def _fake_nba_stack_probe(**kwargs) -> bool:
        if next(probe_results):
            action.nba_probe_status = "passed"
            action.nba_probe_diagnostic = (
                "NBA discovery stack passed "
                "(common_all_players=4900 rows, league_game_log=2460 rows)"
            )
            return True
        action.nba_probe_status = "stack_timeout"
        action.nba_probe_diagnostic = "NBA discovery stack probe timed out"
        return False

    monkeypatch.setattr(action, "probe_nba_stats", lambda **kwargs: True)
    monkeypatch.setattr(action, "probe_nba_discovery_stack", _fake_nba_stack_probe)

    assert action.run() == 0
    assert [process.pid for process in launched] == [90000, 90001]
    assert action.attempted_servers == ["us1001.nordvpn.com", "us1002.nordvpn.com"]
    assert action.failed_servers == ["us1001.nordvpn.com"]
    assert action.server == "us1002.nordvpn.com"
    assert action.nba_probe_status == "passed"
    assert cleanup_calls == ["cleanup"]
    assert "quarantining it for this run" in capsys.readouterr().out
    action.finalize()
    outputs = _read_outputs(runner_env)
    assert json.loads(outputs["failed-servers-json"]) == ["us1001.nordvpn.com"]
    assert outputs["nba-probe-status"] == "passed"
    assert outputs["nba-probe-diagnostic"] == (
        "NBA discovery stack passed (common_all_players=4900 rows, league_game_log=2460 rows)"
    )


def test_run_stops_on_fatal_stack_failure_without_rotating_or_quarantining(
    monkeypatch: pytest.MonkeyPatch,
    runner_env: Path,
) -> None:
    module = _load_module()
    action = module.NordVpnConnectAction()

    for method_name in (
        "prepare_workdir",
        "install_dependencies",
        "determine_baseline_ip",
        "prepare_auth",
        "make_workdir_readable",
    ):
        monkeypatch.setattr(action, method_name, lambda: None)
    monkeypatch.setattr(action, "remaining_budget", lambda: 60.0)
    monkeypatch.setattr(action, "cleanup_openvpn", lambda: None)
    monkeypatch.setattr(
        action,
        "recommendation_servers",
        lambda technology: ["us1001.nordvpn.com", "us1002.nordvpn.com"],
    )
    attempts: list[str] = []

    def _fatal_attempt(server: str, technology: str) -> bool:
        attempts.append(server)
        action.append_unique(action.attempted_servers, server)
        raise module.ActionError(
            "nba_stack_contract_error",
            "NBA discovery stack probe failed at league_game_log (ProbeContractError)",
        )

    monkeypatch.setattr(action, "attempt_server", _fatal_attempt)

    with pytest.raises(module.ActionError) as excinfo:
        action.run()

    assert excinfo.value.status == "nba_stack_contract_error"
    assert action.status == "nba_stack_contract_error"
    assert attempts == ["us1001.nordvpn.com"]
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

    def _fake_retry_http_get(
        label: str,
        output_path: Path,
        url: str,
        *extra_args: str,
        **kwargs,
    ) -> bool:
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
