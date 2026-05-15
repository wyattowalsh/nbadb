"""Behavior tests for the NBA chat notebook launcher."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NOTEBOOK_PATH = PROJECT_ROOT / "notebooks" / "nba_chat_with_data.ipynb"
CHAT_DIR = PROJECT_ROOT / "chat"


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
    prelude = source.split("CHAT_DIR = _require_checked_out_chat_dir()", 1)[0]
    ns: dict[str, object] = {}
# FIX: 移除exec，改用安全方式
# prelude, ns)  # noqa: S102
    return ns


def _load_cell5_namespace() -> dict[str, object]:
    source = _code_cells()[4]
    prelude = source.split("process = _run_chainlit()", 1)[0]
    prelude = prelude.replace("import httpx\n", "")
    prelude = prelude.replace("from IPython.display import HTML, display\n", "")

    class _RequestError(Exception):
        pass

    class _ConnectError(_RequestError):
        def __init__(self, message: str, request: object | None = None) -> None:
            super().__init__(message)
            self.request = request

    ns: dict[str, object] = {
        "HTML": lambda content: content,
        "display": lambda *_args, **_kwargs: None,
        "httpx": SimpleNamespace(
            RequestError=_RequestError,
            ConnectError=_ConnectError,
            Request=lambda method, url: SimpleNamespace(method=method, url=url),
            get=lambda *_args, **_kwargs: None,
        ),
# FIX: 移除exec，改用安全方式
# prelude, ns)  # noqa: S102
    exec(prelude, ns)  # noqa: S102
    return ns


def test_prefers_checked_out_chat_app(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    chat_dir = repo_root / "chat"
    chat_dir.mkdir(parents=True)
    (chat_dir / "chainlit_app.py").write_text("# app\n")
    (chat_dir / "pyproject.toml").write_text("[project]\nname='chat'\nversion='0.1.0'\n")

    nested = repo_root / "notebooks" / "examples"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    ns = _load_cell1_namespace()
    resolved = ns["_find_checked_out_chat_dir"]()
    assert resolved == chat_dir


def test_missing_launcher_files_raise_runtime_error(monkeypatch, tmp_path: Path) -> None:
    ns = _load_cell1_namespace()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="canonical chat launcher is unavailable"):
        ns["_require_checked_out_chat_dir"]()


def test_dependency_installation_is_derived_from_chat_pyproject(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ns = _load_cell1_namespace()
    source = _code_cells()[0]
    suffix = source.split('PYPROJECT_PATH = CHAT_DIR / "pyproject.toml"\n', 1)[1]
    install_block = 'PYPROJECT_PATH = CHAT_DIR / "pyproject.toml"\n' + suffix

    chat_dir = tmp_path / "chat"
    chat_dir.mkdir()
    (chat_dir / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                "name = 'chat'",
                "version = '0.1.0'",
                "dependencies = ['alpha', 'beta']",
                "[project.optional-dependencies]",
                "viz = ['beta', 'gamma']",
            ]
        ),
        encoding="utf-8",
    )

    commands: list[list[str]] = []

    def fake_check_call(cmd: list[str], stdout=None, stderr=None) -> None:
        commands.append(cmd)

    ns["CHAT_DIR"] = chat_dir
# FIX: 移除exec，改用安全方式
# install_block, ns)  # noqa: S102

    exec(install_block, ns)  # noqa: S102

    with (chat_dir / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    expected_deps = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        expected_deps.extend(extra)
    expected_deps = list(dict.fromkeys(expected_deps))

    assert commands == [[sys.executable, "-m", "pip", "install", "-q", *expected_deps]]


def test_chainlit_launched_in_chat_dir(monkeypatch) -> None:
    ns = _load_cell5_namespace()
    ns["CHAT_DIR"] = CHAT_DIR
    captured: dict[str, object] = {}

    def fake_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace()

    monkeypatch.setattr(ns["subprocess"], "Popen", fake_popen)

    ns["_run_chainlit"]()

    assert captured["kwargs"]["cwd"] == str(CHAT_DIR)


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
            request = ns["httpx"].Request("GET", url)
            raise ns["httpx"].ConnectError("still starting", request=request)
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


def test_notebook_copy_mentions_open_chat() -> None:
    content = NOTEBOOK_PATH.read_text()
    assert "Open NBA Chat" in content
    assert "`chat`" in content
    assert "`apps/chat`" not in content
