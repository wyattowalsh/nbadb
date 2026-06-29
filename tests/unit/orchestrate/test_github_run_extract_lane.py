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
    monkeypatch.setenv("PATTERNS", "player")
    monkeypatch.setenv("BACKFILL_ENDPOINTS", "common_player_info")

    assert module.effective_timeout_seconds(7200) == 7200


def test_effective_timeout_does_not_cap_multi_endpoint_player_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("PATTERNS", "player")
    monkeypatch.setenv("BACKFILL_ENDPOINTS", "common_player_info,player_profile_v2")

    assert module.effective_timeout_seconds(7200) == 7200


def test_effective_timeout_caps_direct_no_vpn_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "direct")
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "1800")

    assert module.effective_timeout_seconds(7200) == 1800
    assert module.effective_timeout_seconds(600) == 600


def test_effective_timeout_ignores_direct_cap_for_vpn_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("NBADB_NETWORK_MODE", "vpn")
    monkeypatch.setenv("NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS", "1800")

    assert module.effective_timeout_seconds(7200) == 7200


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
    assert module.status_for_exit_code(130) == "extract-timeout"
    assert module.status_for_exit_code(137) == "extract-timeout"
    assert module.status_for_exit_code(143) == "extract-timeout"
    assert module.status_for_exit_code(-module.signal.SIGINT) == "extract-timeout"
    assert module.status_for_exit_code(-module.signal.SIGTERM) == "extract-timeout"
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
    assert "status=extract-timeout" in output
