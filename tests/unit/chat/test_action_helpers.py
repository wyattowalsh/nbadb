"""Tests for action helper functions in chainlit_app.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CHAINLIT_APP = Path(__file__).resolve().parents[3] / "apps" / "chat" / "chainlit_app.py"


class TestBuildTemplateScript:
    """Test the _build_template_script helper."""

    @pytest.fixture(autouse=True)
    def _load_helper(self):
        """Extract _build_template_script via exec (can't import chainlit)."""
        source = CHAINLIT_APP.read_text()
        # Extract the function from source
        start = source.index("def _build_template_script(")
        # Find the end by looking for the next top-level def or class
        lines = source[start:].split("\n")
        func_lines = []
        for i, line in enumerate(lines):
            if i > 0 and line and not line[0].isspace() and not line.startswith("#"):
                break
            func_lines.append(line)
        func_source = "\n".join(func_lines)
        ns = {}
        exec(func_source, ns)  # noqa: S102
        self.build = ns["_build_template_script"]

    def test_empty_code_log(self):
        result = self.build([], "test")
        assert '"""NBA Analysis Template: test"""' in result
        assert "import pandas" in result

    def test_sql_entry(self):
        log = [{"code": "SELECT 1", "tool": "run_sql", "lang": "sql"}]
        result = self.build(log, "my_analysis")
        assert "Step 1: run_sql" in result
        assert "query('SELECT 1')" in result

    def test_python_entry(self):
        log = [{"code": "print('hello')", "tool": "run_python", "lang": "python"}]
        result = self.build(log, "test")
        assert "print('hello')" in result

    def test_multiple_entries(self):
        log = [
            {"code": "SELECT * FROM t", "tool": "run_sql", "lang": "sql"},
            {"code": "table(df)", "tool": "run_python", "lang": "python"},
        ]
        result = self.build(log, "multi")
        assert "Step 1" in result
        assert "Step 2" in result

    def test_has_db_connection(self):
        result = self.build([], "test")
        assert "duckdb.connect" in result
        assert "def query(sql" in result


class TestBuildSpreadsheetHtml:
    """Test the _build_spreadsheet_html helper."""

    @pytest.fixture(autouse=True)
    def _load_helper(self):
        source = CHAINLIT_APP.read_text()
        start = source.index("def _build_spreadsheet_html(")
        lines = source[start:].split("\n")
        func_lines = []
        for i, line in enumerate(lines):
            if (
                i > 0
                and line
                and not line[0].isspace()
                and line.startswith(("def ", "class ", "@"))
            ):
                break
            func_lines.append(line)
        import html as _html_mod

        func_source = "\n".join(func_lines)
        ns = {"_html": _html_mod}
        exec(func_source, ns)  # noqa: S102
        self.build = ns["_build_spreadsheet_html"]

    def test_returns_html(self):
        result = self.build("test", "[]", "[]")
        assert "<!DOCTYPE html>" in result
        assert "</html>" in result

    def test_includes_ag_grid(self):
        result = self.build("test", "[]", "[]")
        assert "ag-grid-community" in result

    def test_includes_name(self):
        result = self.build("my_data", "[]", "[]")
        assert "my_data" in result

    def test_includes_export_buttons(self):
        result = self.build("test", "[]", "[]")
        assert "exportCSV" in result
        assert "exportJSON" in result
        assert "resetData" in result

    def test_includes_data(self):
        cols = json.dumps([{"field": "name"}])
        rows = json.dumps([{"name": "LeBron"}])
        result = self.build("test", cols, rows)
        assert "LeBron" in result


class TestTrackCode:
    """Test that _track_code function exists and has the right structure."""

    def test_track_code_exists(self):
        content = CHAINLIT_APP.read_text()
        assert "def _track_code(" in content
        assert "code_log" in content

    def test_track_code_appends(self):
        content = CHAINLIT_APP.read_text()
        assert "code_log.append(" in content
