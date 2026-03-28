"""Unit tests for nbadb.docs_gen.__main__ module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import typer
from typer.testing import CliRunner

# The __main__ module exposes `main` as a typer-runnable function.
from nbadb.docs_gen.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

# Build a minimal Typer app wrapping main so we can test via CliRunner
_app = typer.Typer()
_app.command()(main)

_GENERATE_PATH = "nbadb.docs_gen.__main__.generate_docs_artifacts"


class TestDocsGenMain:
    def test_main_reports_updated_and_unchanged(self, tmp_path: Path) -> None:
        """main() prints updated / unchanged counts."""
        updated = [tmp_path / "a.mdx"]
        unchanged = [tmp_path / "b.mdx", tmp_path / "c.mdx"]
        with patch(_GENERATE_PATH, return_value=(updated, unchanged)):
            result = runner.invoke(_app, ["--docs-root", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "updated:" in result.output
        assert "unchanged:" in result.output
        assert "1 updated, 2 unchanged" in result.output

    def test_main_no_updates(self, tmp_path: Path) -> None:
        """When nothing is updated, output shows 0 updated."""
        with patch(_GENERATE_PATH, return_value=([], [tmp_path / "x.mdx"])):
            result = runner.invoke(_app, ["--docs-root", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "0 updated, 1 unchanged" in result.output

    def test_module_is_importable(self) -> None:
        """The __main__ module can be imported without error."""
        import nbadb.docs_gen.__main__ as m

        assert hasattr(m, "main")
