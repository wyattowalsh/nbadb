"""AST-based safety tests for NBA analytics skill scripts."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[3] / "chat" / "skills" / "nba-data-analytics" / "scripts"
)

_ANALYTICS_SCRIPTS = tuple(sorted(path.stem for path in _SCRIPTS_DIR.glob("*.py")))

_BLOCKED_MODULES = {
    "os",
    "subprocess",
    "shutil",
    "socket",
    "http",
    "urllib",
    "requests",
    "builtins",
    "signal",
    "multiprocessing",
    "threading",
    "sys",
    "pathlib",
    "io",
}

_BLOCKED_CALLS = {"eval", "exec", "open", "compile", "input", "__import__"}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".", 1)[0])

    return modules


def _called_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    called: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)

    return called


def test_skill_safety_covers_all_current_scripts() -> None:
    assert _ANALYTICS_SCRIPTS == (
        "compare",
        "court",
        "lineups",
        "metric_calculator",
        "nba_stats",
        "season_utils",
        "similarity",
        "team_colors",
        "trends",
    )


@pytest.mark.parametrize("script_name", _ANALYTICS_SCRIPTS, ids=_ANALYTICS_SCRIPTS)
def test_analytics_scripts_do_not_import_blocked_modules(script_name: str) -> None:
    script_path = _SCRIPTS_DIR / f"{script_name}.py"
    imported_modules = _imported_modules(script_path)
    blocked_imports = sorted(imported_modules & _BLOCKED_MODULES)

    assert blocked_imports == [], f"{script_path.name} imports blocked modules: {blocked_imports}"


@pytest.mark.parametrize("script_name", _ANALYTICS_SCRIPTS, ids=_ANALYTICS_SCRIPTS)
def test_analytics_scripts_do_not_call_blocked_builtins(script_name: str) -> None:
    script_path = _SCRIPTS_DIR / f"{script_name}.py"
    blocked_calls = sorted(_called_names(script_path) & _BLOCKED_CALLS)

    assert blocked_calls == [], f"{script_path.name} calls blocked builtins: {blocked_calls}"
