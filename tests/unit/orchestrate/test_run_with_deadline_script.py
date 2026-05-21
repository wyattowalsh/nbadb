from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "run_with_deadline.sh"


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
        "attempted-servers-json=[]",
        "failed-servers-json=[]",
    ]
