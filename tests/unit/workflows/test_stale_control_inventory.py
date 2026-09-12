"""Guard the reviewed GitHub Actions publication and metadata mutation inventory."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACTIONS = REPO_ROOT / ".github" / "actions"

EXPECTED_SCHEDULED_WORKFLOWS = {
    ".github/workflows/daily-update.yml",
    ".github/workflows/model-audit.yml",
    ".github/workflows/monthly-update.yml",
}
EXPECTED_CONTENTS_WRITE_WORKFLOWS = {
    ".github/workflows/full-extraction.yml",
}
EXPECTED_KAGGLE_MUTATION_WORKFLOWS = {
    ".github/workflows/daily-update.yml",
    ".github/workflows/full-extraction.yml",
    ".github/workflows/monthly-update.yml",
}
EXPECTED_GIT_PUSH_SURFACES = {
    ".github/actions/refresh-metadata/action.yml",
}
EXPECTED_METADATA_COMMIT_SURFACES = {
    ".github/actions/refresh-metadata/action.yml",
    ".github/workflows/full-extraction.yml",
}


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _yaml_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted((*root.rglob("*.yml"), *root.rglob("*.yaml"))))


def _matching_paths(paths: tuple[Path, ...], pattern: str) -> set[str]:
    matcher = re.compile(pattern, flags=re.MULTILINE)
    return {
        _relative(path)
        for path in paths
        if matcher.search(path.read_text(encoding="utf-8")) is not None
    }


def test_stale_kaggle_control_files_and_references_are_absent() -> None:
    stale_paths = (
        Path("notebooks") / ("kaggle_" + "pipeline.ipynb"),
        Path("notebooks") / ("kaggle_" + "update.py"),
        Path("src/nbadb/kaggle") / ("note" + "book.py"),
        Path("tests/unit/kaggle") / ("test_" + "notebook.py"),
        Path(".github/workflows") / ("update-" + "metadata.yml"),
    )
    assert not [path.as_posix() for path in stale_paths if (REPO_ROOT / path).exists()]

    stale_references = (
        "nbadb.kaggle." + "notebook",
        "notebooks/kaggle_" + "pipeline.ipynb",
        "notebooks/kaggle_" + "update.py",
        ".github/workflows/update-" + "metadata.yml",
    )
    searchable_roots = (
        REPO_ROOT / ".github",
        REPO_ROOT / "notebooks",
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
    )
    this_file = Path(__file__).resolve()
    matches: list[str] = []
    for root in searchable_roots:
        for path in root.rglob("*"):
            if (
                path == this_file
                or not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix not in {".ipynb", ".json", ".py", ".toml", ".yaml", ".yml"}
            ):
                continue
            text = path.read_text(encoding="utf-8")
            for reference in stale_references:
                if reference in text:
                    matches.append(f"{_relative(path)}:{reference}")
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for reference in stale_references:
        if reference in pyproject:
            matches.append(f"pyproject.toml:{reference}")
    assert matches == []

    # This consumer notebook and the separate published-example catalog are not stale writers.
    assert (REPO_ROOT / "notebooks/kaggle_starter.ipynb").is_file()
    assert len(tuple((REPO_ROOT / "notebooks").glob("*_kernel-metadata.json"))) == 11


def test_reviewed_schedule_and_mutation_inventory_is_exact() -> None:
    workflows = _yaml_files(WORKFLOWS)
    actions = _yaml_files(ACTIONS)
    all_actions_yaml = workflows + actions

    assert _matching_paths(workflows, r"^\s*schedule:\s*$") == EXPECTED_SCHEDULED_WORKFLOWS
    assert (
        _matching_paths(workflows, r"^\s*contents:\s*write\s*$")
        == EXPECTED_CONTENTS_WRITE_WORKFLOWS
    )
    assert (
        _matching_paths(workflows, r"\buv run nbadb upload\b") == EXPECTED_KAGGLE_MUTATION_WORKFLOWS
    )
    assert _matching_paths(all_actions_yaml, r"\bgit push\b") == EXPECTED_GIT_PUSH_SURFACES
    assert (
        _matching_paths(
            all_actions_yaml,
            r"git add dataset-metadata\.json|Refresh checked-in metadata",
        )
        == EXPECTED_METADATA_COMMIT_SURFACES
    )
