"""Tests for preamble helper functions and template content."""

from __future__ import annotations

from pathlib import Path

import pytest

PREAMBLE_MODULE = Path(__file__).resolve().parents[3] / "apps" / "chat" / "server" / "_preamble.py"


@pytest.fixture()
def preamble_content():
    """Return the raw _PREAMBLE_TEMPLATE content."""
    return PREAMBLE_MODULE.read_text()


@pytest.fixture()
def built_preamble():
    """Return a built preamble with test paths."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_preamble", PREAMBLE_MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_preamble("/tmp/test.duckdb", "/tmp/skills", "/tmp/session/test")


class TestSessionState:
    """Test session state (last_result) persistence code."""

    def test_last_result_load(self, preamble_content):
        assert "last_result = pd.read_parquet" in preamble_content

    def test_last_result_fallback(self, preamble_content):
        assert "last_result = pd.DataFrame()" in preamble_content

    def test_save_last_result_function(self, preamble_content):
        assert "def _save_last_result(df, _last_result_path=_LAST_RESULT_PATH)" in preamble_content

    def test_table_saves_last_result(self, preamble_content):
        assert "_save_last_result(df)" in preamble_content

    def test_session_dir_creation(self, preamble_content):
        assert "_LAST_RESULT_PATH.parent.mkdir(parents=True" in preamble_content


class TestDisplayHelpers:
    """Test display helper function definitions."""

    def test_chart_function(self, preamble_content):
        assert "def chart(fig):" in preamble_content

    def test_table_function(self, preamble_content):
        assert "def table(df):" in preamble_content

    def test_show_function(self, preamble_content):
        assert "def show(data):" in preamble_content

    def test_annotated_chart_function(self, preamble_content):
        assert "def annotated_chart(fig" in preamble_content

    def test_annotated_chart_adds_hline(self, preamble_content):
        assert "add_hline" in preamble_content


class TestExportHelpers:
    """Test export helper function definitions."""

    def test_to_csv(self, preamble_content):
        assert "def to_csv(df" in preamble_content

    def test_to_xlsx(self, preamble_content):
        assert "def to_xlsx(df" in preamble_content

    def test_to_json(self, preamble_content):
        assert "def to_json(df" in preamble_content

    def test_export_dispatch(self, preamble_content):
        assert "def export(df" in preamble_content

    def test_to_spreadsheet(self, preamble_content):
        assert "def to_spreadsheet(df" in preamble_content
        assert "ag-grid" in preamble_content.lower() or "AG Grid" in preamble_content


class TestShareableOutput:
    """Test shareable output helper definitions."""

    def test_to_embed(self, preamble_content):
        assert "def to_embed(fig" in preamble_content
        assert "to_html" in preamble_content

    def test_to_social(self, preamble_content):
        assert "def to_social(" in preamble_content
        assert "1D428A" in preamble_content  # NBA blue brand color

    def test_to_thread(self, preamble_content):
        assert "def to_thread(insights)" in preamble_content


class TestBuildPreamble:
    """Test build_preamble function."""

    def test_substitutes_db_path(self, built_preamble):
        assert "/tmp/test.duckdb" in built_preamble

    def test_substitutes_skills_dir(self, built_preamble):
        assert "/tmp/skills" in built_preamble

    def test_substitutes_session_dir(self, built_preamble):
        assert "/tmp/session/test" in built_preamble

    def test_uses_private_duckdb_import(self, built_preamble):
        assert "import duckdb as _duckdb" in built_preamble
        assert "del _duckdb" in built_preamble

    def test_no_raw_placeholders(self, built_preamble):
        assert "__DB_PATH__" not in built_preamble
        assert "__SKILLS_DIR__" not in built_preamble
        assert "__SESSION_DIR__" not in built_preamble

    def test_braces_in_path_safe(self):
        """Paths with curly braces don't crash build_preamble."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("_preamble", PREAMBLE_MODULE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # This would crash with str.format()
        result = mod.build_preamble(
            "/tmp/{weird}/db.duckdb",
            "/skills/{odd}",
            "/session/{safe}",
        )
        assert "{weird}" in result  # Braces preserved, not interpreted
        assert "{safe}" in result
