from __future__ import annotations

import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "run_extract_lane.py"
MODULE_CODE = compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec")


def _load_module():
    module = types.ModuleType("github_run_extract_lane")
    module.__file__ = str(MODULE_PATH)
    exec(MODULE_CODE, module.__dict__)
    return module


def test_build_command_includes_lane_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv("SEASON_START", "1946")
    monkeypatch.setenv("SEASON_END", "1963")
    monkeypatch.setenv("PATTERNS", "season")
    monkeypatch.setenv("SEASON_TYPES", "Regular Season,Playoffs")
    monkeypatch.setenv("CONTEXT_MEASURES", "PTS,AST")
    monkeypatch.setenv("BACKFILL_ENDPOINTS", "league_dash_player_stats")
    monkeypatch.setenv("FORCE_REEXTRACT", "true")
    monkeypatch.setenv("EXTRACT_SUMMARY_PATH", "artifacts/extraction/extract-summary.json")

    assert module.build_command() == [
        "uv",
        "run",
        "nbadb",
        "backfill",
        "run",
        "--extract-only",
        "--verbose",
        "--seasons",
        "1946:1963",
        "--pattern",
        "season",
        "--season-types",
        "Regular Season,Playoffs",
        "--context-measures",
        "PTS,AST",
        "--endpoint",
        "league_dash_player_stats",
        "--summary-path",
        "artifacts/extraction/extract-summary.json",
        "--force",
    ]


def test_effective_timeout_uses_manifest_timeout_for_singleton_player_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "direct")
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "1800")
    monkeypatch.setenv("PATTERNS", "player")
    monkeypatch.setenv("BACKFILL_ENDPOINTS", "common_player_info")

    assert module.effective_timeout_seconds(7200) == 7200


def test_effective_timeout_does_not_cap_multi_endpoint_player_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "direct")
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "1800")
    monkeypatch.setenv("PATTERNS", "player")
    monkeypatch.setenv("BACKFILL_ENDPOINTS", "common_player_info,player_profile_v2")

    assert module.effective_timeout_seconds(7200) == 7200


def test_effective_timeout_caps_direct_no_vpn_date_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "direct")
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "1800")
    monkeypatch.setenv("PATTERNS", "date")

    assert module.effective_timeout_seconds(7200) == 1800
    assert module.effective_timeout_seconds(600) == 600


def test_effective_timeout_caps_direct_no_vpn_game_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "direct")
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "1800")
    monkeypatch.setenv("PATTERNS", "game")

    assert module.effective_timeout_seconds(7200) == 1800


@pytest.mark.parametrize(
    "pattern",
    ["player_season", "team_season", "player_team_season"],
)
def test_effective_timeout_caps_direct_no_vpn_expensive_season_lanes(
    monkeypatch: pytest.MonkeyPatch,
    pattern: str,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "direct")
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "1800")
    monkeypatch.setenv("PATTERNS", pattern)

    assert module.effective_timeout_seconds(7200) == 1800


def test_effective_timeout_ignores_direct_cap_for_vpn_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "vpn")
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "1800")
    monkeypatch.setenv("PATTERNS", "date")

    assert module.effective_timeout_seconds(7200) == 7200


def test_effective_timeout_preserves_job_finalization_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_EXTRACT_JOB_DEADLINE_EPOCH_SECONDS", "22000")
    monkeypatch.setenv("NBADB_EXTRACT_FINALIZATION_RESERVE_SECONDS", "1200")
    monkeypatch.setattr(module.time, "time", lambda: 1000.0)

    assert module.job_budget_cap_seconds() == 19800
    assert module.effective_timeout_seconds(20000) == 19800
    assert module.effective_timeout_seconds(300) == 300


def test_job_budget_requires_paired_live_deadline_and_positive_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_EXTRACT_JOB_DEADLINE_EPOCH_SECONDS", "22000")
    with pytest.raises(ValueError, match="must be set together"):
        module.job_budget_cap_seconds()

    monkeypatch.setenv("NBADB_EXTRACT_FINALIZATION_RESERVE_SECONDS", "1200")
    monkeypatch.setattr(module.time, "time", lambda: 21000.0)
    with pytest.raises(ValueError, match="budget is exhausted"):
        module.job_budget_cap_seconds()


def test_video_details_asset_uses_stall_watchdog_without_shortening_lane_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "vpn")
    monkeypatch.setenv("BACKFILL_ENDPOINTS", "video_details_asset")

    assert module.effective_timeout_seconds(6300) == 6300
    assert module.effective_timeout_seconds(300) == 300
    assert module.endpoint_stall_timeout_seconds() == 600


def test_endpoint_stall_timeout_uses_strictest_selected_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv(
        "BACKFILL_ENDPOINTS",
        "video_details,video_details_asset",
    )

    assert module.endpoint_stall_timeout_seconds() == 600


def test_stall_watchdog_requires_endpoint_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv(
        "BACKFILL_ENDPOINTS",
        "video_details,video_details_asset",
    )

    with pytest.raises(ValueError, match="must run in an isolated lane"):
        module.validate_stall_watchdog_endpoint_isolation()


def test_direct_timeout_cap_seconds_validates_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "0")

    with pytest.raises(ValueError, match="must be > 0"):
        module.direct_timeout_cap_seconds()


def test_env_timeout_seconds_validates_input(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setenv("LANE_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError, match="must be > 0"):
        module.env_timeout_seconds()


def test_status_for_exit_code_classifies_runner_interrupts() -> None:
    module = _load_module()

    assert module.status_for_exit_code(0) == "complete"
    assert module.status_for_exit_code(124) == "extract-timeout"
    assert module.status_for_exit_code(130) == "cancelled"
    assert module.status_for_exit_code(137) == "extract-timeout"
    assert module.status_for_exit_code(143) == "cancelled"
    assert module.status_for_exit_code(-module.signal.SIGINT) == "cancelled"
    assert module.status_for_exit_code(-module.signal.SIGTERM) == "cancelled"
    assert module.status_for_exit_code(2) == "extract-error"


def test_main_reports_interrupted_child_without_canceling_post_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    output_path = tmp_path / "github-output.txt"

    class FakeProcess:
        pid = 12345

        def poll(self) -> int:
            return 130

    monkeypatch.setenv("LANE_TIMEOUT_SECONDS", "7200")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())

    assert module.main() == 0
    output = output_path.read_text(encoding="utf-8")
    assert "exit-code=130" in output
    assert "status=cancelled" in output


def test_main_finalizes_outputs_after_runner_termination_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    output_path = tmp_path / "github-output.txt"
    terminations: list[tuple[int, dict[str, object]]] = []

    class FakeProcess:
        pid = 54321

        def poll(self) -> None:
            raise module.ExtractionInterruptedError(module.signal.SIGTERM)

    monkeypatch.setenv("LANE_TIMEOUT_SECONDS", "7200")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(
        module,
        "terminate_tree",
        lambda pid, **kwargs: terminations.append((pid, kwargs)),
    )

    assert module.main() == 0
    assert terminations == [(54321, {"grace_seconds": 2.0, "discover_descendants": False})]
    output = output_path.read_text(encoding="utf-8")
    assert "exit-code=143" in output
    assert "status=cancelled" in output


def test_main_installs_signal_handlers_before_spawning_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    installed: set[int] = set()

    class FakeProcess:
        pid = 54322

        def poll(self) -> int:
            return 0

    def fake_signal(signal_number: int, _handler: object) -> None:
        installed.add(signal_number)

    def fake_popen(*_args, **_kwargs):
        assert installed == {module.signal.SIGINT, module.signal.SIGTERM}
        return FakeProcess()

    monkeypatch.setenv("LANE_TIMEOUT_SECONDS", "7200")
    monkeypatch.setattr(module.signal, "signal", fake_signal)
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    assert module.main() == 0


def test_main_terminates_live_child_after_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    terminated: list[int] = []

    class FakeProcess:
        pid = 54323

        def poll(self) -> None:
            raise RuntimeError("unexpected monitoring failure")

    monkeypatch.setenv("LANE_TIMEOUT_SECONDS", "7200")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(module, "terminate_tree", terminated.append)

    with pytest.raises(RuntimeError, match="unexpected monitoring failure"):
        module.main()

    assert terminated == [FakeProcess.pid]


def test_main_terminates_asset_lane_after_no_completed_chunk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    output_path = tmp_path / "github-output.txt"
    popen_env: dict[str, str] = {}
    terminated: list[int] = []

    class FakeProcess:
        pid = 23456

        def poll(self) -> None:
            return None

    def fake_popen(*_args, **kwargs):
        popen_env.update(kwargs["env"])
        return FakeProcess()

    monotonic_values = iter([0.0, 0.0, 601.0])
    monkeypatch.setenv("LANE_TIMEOUT_SECONDS", "7200")
    monkeypatch.setenv("BACKFILL_ENDPOINTS", "video_details_asset")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(module, "terminate_tree", terminated.append)

    assert module.main() == 0
    assert popen_env["NBADB_EXTRACTION_HEARTBEAT_PATH"].startswith(str(tmp_path))
    assert terminated == [FakeProcess.pid]
    output = output_path.read_text(encoding="utf-8")
    assert "stall-timeout-seconds=600" in output
    assert "exit-code=124" in output
    assert "status=extract-timeout" in output


def test_main_terminates_child_when_heartbeat_disappears(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    output_path = tmp_path / "github-output.txt"
    terminated: list[int] = []

    class FakeProcess:
        pid = 34567

        def poll(self) -> None:
            return None

    def fake_popen(*_args, **kwargs):
        Path(kwargs["env"]["NBADB_EXTRACTION_HEARTBEAT_PATH"]).unlink()
        return FakeProcess()

    monotonic_values = iter([0.0, 0.0, 1.0])
    monkeypatch.setenv("LANE_TIMEOUT_SECONDS", "7200")
    monkeypatch.setenv("BACKFILL_ENDPOINTS", "video_details_asset")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(module, "terminate_tree", terminated.append)

    assert module.main() == 0
    assert terminated == [FakeProcess.pid]
    output = output_path.read_text(encoding="utf-8")
    assert "exit-code=124" in output
    assert "status=extract-timeout" in output
