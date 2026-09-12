from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / ".github/scripts/full_extraction_handoffs.py"
_SPEC = importlib.util.spec_from_file_location("full_extraction_handoffs", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
subject = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = subject
_SPEC.loader.exec_module(subject)

_COMMAND_MARKERS = {
    "resolve-resume-source-committed-manifest": ("RESUME_SOURCE_COMMITTED_MANIFEST_RESOLVER"),
    "build-lane-manifest": "MANUAL_HANDOFF_CHAIN_VERIFIER",
    "resolve-prior-discovery-artifact-receipt": ("DISCOVERY_ARTIFACT_RECEIPT_RESOLVER"),
    "resolve-exact-source-checkpoint-receipt": "TERMINAL_REPLAY_ARTIFACT_RESOLVER",
    "attest-terminal-replay-inputs": "TERMINAL_REPLAY_ATTESTATION",
}


def test_command_inventory_is_exact_and_preserves_authority_markers() -> None:
    assert set(subject.COMMANDS) == set(_COMMAND_MARKERS)
    for command, marker in _COMMAND_MARKERS.items():
        script = subject.COMMANDS[command]
        assert marker in script
        assert ".github/workflows/full-extraction.yml" in script or command in {
            "attest-terminal-replay-inputs",
        }


@pytest.mark.parametrize("returncode", [0, 1])
@pytest.mark.parametrize("command", sorted(_COMMAND_MARKERS))
def test_main_executes_exact_selected_script_and_propagates_status(
    command: str,
    returncode: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Sequence[str], bool]] = []

    def fake_run(arguments: Sequence[str], *, check: bool) -> SimpleNamespace:
        calls.append((arguments, check))
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert subject.main([command]) == returncode
    assert calls == [
        (
            ["bash", "-e", "-c", subject.COMMANDS[command]],
            False,
        )
    ]


def test_main_rejects_unknown_command_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("subprocess must not run for an unknown command")

    monkeypatch.setattr(subprocess, "run", unexpected_run)

    with pytest.raises(SystemExit, match="2"):
        subject.main(["unknown-command"])
