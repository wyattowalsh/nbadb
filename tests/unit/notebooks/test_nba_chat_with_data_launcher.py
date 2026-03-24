"""Behavior tests for the NBA chat notebook launcher."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "nba_chat_with_data.ipynb"
CHAT_DIR = PROJECT_ROOT / "apps" / "chat"
CURRENT_COMMIT = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _code_cells() -> list[str]:
    notebook = json.loads(NOTEBOOK_PATH.read_text())
    cells: list[str] = []
    for cell in notebook["cells"]:
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", [])
        cells.append(source if isinstance(source, str) else "".join(source))
    return cells


def _load_cell1_namespace() -> dict[str, object]:
    source = _code_cells()[0]
    prelude = source.split("CHAT_DIR = _find_checked_out_chat_dir() or _clone_chat_repo()", 1)[0]
    ns: dict[str, object] = {}
    exec(prelude, ns)  # noqa: S102
    return ns


def _load_cell5_namespace() -> dict[str, object]:
    source = _code_cells()[4]
    prelude = source.split("# Start server and wait for the HTTP endpoint to answer.\n", 1)[0]
    prelude = prelude.replace("from IPython.display import HTML, display\n", "")
    ns: dict[str, object] = {
        "HTML": lambda content: content,
        "display": lambda *_args, **_kwargs: None,
    }
    exec(prelude, ns)  # noqa: S102
    return ns


def test_prefers_checked_out_chat_app(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    chat_dir = repo_root / "apps" / "chat"
    chat_dir.mkdir(parents=True)
    (chat_dir / "chainlit_app.py").write_text("# app\n")
    (chat_dir / "pyproject.toml").write_text("[project]\nname='chat'\nversion='0.1.0'\n")

    nested = repo_root / "notebooks" / "examples"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    ns = _load_cell1_namespace()
    resolved = ns["_find_checked_out_chat_dir"]()
    assert resolved == chat_dir


def test_clone_fallback_is_pinned_to_current_commit(monkeypatch, tmp_path: Path) -> None:
    ns = _load_cell1_namespace()
    commands: list[list[str]] = []

    def fake_check_call(cmd: list[str], stdout=None, stderr=None) -> None:
        commands.append(cmd)

    ns["WORK_DIR"] = tmp_path
    monkeypatch.setattr(ns["subprocess"], "check_call", fake_check_call)

    chat_dir = ns["_clone_chat_repo"]()
    clone_dir = tmp_path / f"nbadb-{CURRENT_COMMIT[:8]}"

    assert chat_dir == clone_dir / "apps" / "chat"
    assert commands == [
        ["git", "clone", ns["REPO_URL"], str(clone_dir)],
        ["git", "-C", str(clone_dir), "checkout", "--detach", CURRENT_COMMIT],
    ]


def test_dependency_installation_is_derived_from_chat_pyproject(monkeypatch) -> None:
    ns = _load_cell1_namespace()
    source = _code_cells()[0]
    suffix = source.split('PYPROJECT_PATH = CHAT_DIR / "pyproject.toml"\n', 1)[1]
    install_block = 'PYPROJECT_PATH = CHAT_DIR / "pyproject.toml"\n' + suffix

    commands: list[list[str]] = []

    def fake_check_call(cmd: list[str], stdout=None, stderr=None) -> None:
        commands.append(cmd)

    ns["CHAT_DIR"] = CHAT_DIR
    monkeypatch.setattr(ns["subprocess"], "check_call", fake_check_call)

    exec(install_block, ns)  # noqa: S102

    with (CHAT_DIR / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    expected_deps = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        expected_deps.extend(extra)
    expected_deps = list(dict.fromkeys([*expected_deps, "cloudflared"]))

    assert commands == [[sys.executable, "-m", "pip", "install", "-q", *expected_deps]]


def test_public_demo_flag_is_exported_to_chainlit_process(monkeypatch) -> None:
    ns = _load_cell5_namespace()
    ns["CHAT_DIR"] = CHAT_DIR
    captured: dict[str, object] = {}

    def fake_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(ns["subprocess"], "Popen", fake_popen)

    ns["_run_chainlit"]()

    env = captured["kwargs"]["env"]
    assert env["NBADB_CHAT_PUBLIC_MODE"] == "1"
    assert captured["kwargs"]["cwd"] == str(CHAT_DIR)


def test_public_demo_setup_does_not_persist_api_key(monkeypatch, tmp_path: Path) -> None:
    source = _code_cells()[1]
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NBADB_CHAT_PUBLIC_MODE", "1")
    monkeypatch.setattr(
        "getpass.getpass",
        lambda prompt: (_ for _ in ()).throw(AssertionError("public demo should not prompt")),
    )

    ns: dict[str, object] = {}
    exec(source, ns)  # noqa: S102

    chat_config = tmp_path / ".nbadb" / "chat.json"
    payload = json.loads(chat_config.read_text())
    assert payload == {"provider": "openai", "model": "gpt-4.1"}
    assert "api_key" not in payload
    assert ns["PUBLIC_DEMO"] is True
    assert ns["API_KEY"] is None


def test_wait_for_chainlit_polls_until_http_ready(monkeypatch) -> None:
    ns = _load_cell5_namespace()
    clock = {"now": 0.0}
    attempts = {"count": 0}

    class FakeProcess:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_monotonic() -> float:
        return clock["now"]

    def fake_sleep(interval: float) -> None:
        clock["now"] += interval

    def fake_get(url: str, timeout: float):
        attempts["count"] += 1
        if attempts["count"] < 3:
            request = httpx.Request("GET", url)
            raise httpx.ConnectError("still starting", request=request)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(ns["time"], "monotonic", fake_monotonic)
    monkeypatch.setattr(ns["time"], "sleep", fake_sleep)
    monkeypatch.setattr(ns["httpx"], "get", fake_get)

    ns["_wait_for_chainlit"](FakeProcess(), "http://127.0.0.1:8421")
    assert attempts["count"] == 3


def test_wait_for_chainlit_raises_if_process_exits(monkeypatch) -> None:
    ns = _load_cell5_namespace()

    class FakeProcess:
        returncode = 9

        def poll(self) -> int:
            return self.returncode

    monkeypatch.setattr(ns["time"], "monotonic", lambda: 0.0)

    try:
        ns["_wait_for_chainlit"](FakeProcess(), "http://127.0.0.1:8421")
    except RuntimeError as exc:
        assert "exited early" in str(exc)
    else:
        raise AssertionError("expected launcher readiness check to fail fast on process exit")


def test_notebook_copy_mentions_public_demo_risk() -> None:
    content = NOTEBOOK_PATH.read_text()
    assert "Open NBA Chat" in content
    assert "Public demo warning" in content
    assert "anonymous URL" in content
    assert "Bring your own API key in the settings panel" in content
    assert "Your own API key from any supported provider" in content
