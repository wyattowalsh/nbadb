"""Tests for _render_tool_result and related rendering logic in chainlit_app.py.

Since we can't import chainlit in unit tests, we test the pure logic by
pattern-matching the source file and by extracting testable helpers.
"""

from __future__ import annotations

from pathlib import Path

CHAINLIT_APP = Path(__file__).resolve().parents[3] / "apps" / "chat" / "chainlit_app.py"


def test_render_function_exists():
    """_render_tool_result is defined in chainlit_app.py."""
    content = CHAINLIT_APP.read_text()
    assert "async def _render_tool_result(" in content


def test_render_handles_sql_results():
    """SQL results with columns/rows are detected."""
    content = CHAINLIT_APP.read_text()
    assert '"columns" in data and "rows" in data' in content


def test_render_handles_error_json():
    """Error responses with 'error' key are detected."""
    content = CHAINLIT_APP.read_text()
    assert '"error" in data' in content


def test_render_handles_export_file():
    """Export file responses with export_file/content keys are detected."""
    content = CHAINLIT_APP.read_text()
    assert '"export_file" in data and "content" in data' in content


def test_render_handles_image_base64():
    """Matplotlib base64 PNG images are detected."""
    content = CHAINLIT_APP.read_text()
    assert '"image_base64" in data' in content


def test_render_handles_plotly_json():
    """Plotly JSON with data/layout keys is detected."""
    content = CHAINLIT_APP.read_text()
    assert '"data" in data and "layout" in data' in content


def test_render_handles_stdout():
    """Sandbox stdout output is detected."""
    content = CHAINLIT_APP.read_text()
    assert '"stdout" in data' in content


def test_render_has_non_dict_fallback():
    """Non-dict JSON falls back to formatted output."""
    content = CHAINLIT_APP.read_text()
    assert "not isinstance(data, dict)" in content


def test_render_has_json_parse_fallback():
    """Non-JSON strings fall back to raw output."""
    content = CHAINLIT_APP.read_text()
    assert "json.JSONDecodeError" in content


class TestContextualAnnotations:
    """Test the auto-annotation logic in SQL result rendering."""

    def test_stats_footer_code_exists(self):
        """Stats footer annotation code is present."""
        content = CHAINLIT_APP.read_text()
        assert "select_dtypes" in content
        assert "mean()" in content
        assert "median()" in content

    def test_small_sample_warning_exists(self):
        """Small sample warning for < 20 rows is present."""
        content = CHAINLIT_APP.read_text()
        assert "small sample" in content.lower()

    def test_stats_cap_at_three_columns(self):
        """Stats are computed for at most 3 numeric columns."""
        content = CHAINLIT_APP.read_text()
        assert "columns[:3]" in content


class TestActionButtons:
    """Test that action buttons are created on SQL results."""

    def test_sql_has_copy_sql_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"copy_sql"' in content

    def test_sql_has_csv_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"download_csv"' in content

    def test_sql_has_xlsx_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"download_xlsx"' in content

    def test_sql_has_json_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"download_json"' in content

    def test_sql_has_spreadsheet_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"edit_spreadsheet"' in content

    def test_sql_has_refine_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"refine_query"' in content

    def test_sql_has_export_code_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"export_session_code"' in content

    def test_sql_has_save_template_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"save_template"' in content

    def test_non_sql_has_copy_code_button(self):
        content = CHAINLIT_APP.read_text()
        assert '"copy_code"' in content


class TestPayloadCapping:
    """Test that action payloads are capped for size."""

    def test_payload_rows_capped(self):
        """Data payloads for action buttons are capped at 100 rows."""
        content = CHAINLIT_APP.read_text()
        assert '["rows"][:100]' in content
