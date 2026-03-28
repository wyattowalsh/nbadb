"""Unit tests for the lint-sql CLI command."""

from __future__ import annotations

import builtins
import sys
from typing import ClassVar
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from nbadb.cli.app import app
from nbadb.transform.base import SqlTransformer

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DISCOVER_PATH = "nbadb.orchestrate.transformers.discover_all_transformers"


class _FakeTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_example"
    depends_on: ClassVar[list[str]] = []
    _SQL: ClassVar[str] = "SELECT 1 AS id"


class _FakeTransformerB(SqlTransformer):
    output_table: ClassVar[str] = "dim_other"
    depends_on: ClassVar[list[str]] = []
    _SQL: ClassVar[str] = "SELECT 2 AS name"


class _FakeTransformerEmpty(SqlTransformer):
    output_table: ClassVar[str] = "empty_sql"
    depends_on: ClassVar[list[str]] = []
    _SQL: ClassVar[str] = "   "


def _make_violation(
    rule_code: str = "LT01",
    line_no: int = 1,
    desc: str = "bad indent",
    severity: str = "warning",
) -> MagicMock:
    v = MagicMock()
    v.rule_code.return_value = rule_code
    v.line_no = line_no
    v.desc.return_value = desc
    v.severity = severity
    return v


def _lint_result(violations: list | None = None) -> MagicMock:
    result = MagicMock()
    result.violations = violations or []
    return result


def _fix_result(fixed_sql: str, violations: list | None = None) -> MagicMock:
    result = MagicMock()
    result.fix_string = fixed_sql
    result.violations = violations or []
    return result


def _mock_sqlfluff(linter_instance: MagicMock | None = None) -> MagicMock:
    """Create a fake sqlfluff.core module with a mock Linter class."""
    mock_module = MagicMock()
    if linter_instance is not None:
        mock_module.Linter.return_value = linter_instance
    return mock_module


# ---------------------------------------------------------------------------
# Tests — import error
# ---------------------------------------------------------------------------

_original_import = builtins.__import__


def _import_raiser(name: str, *args: object, **kwargs: object) -> object:
    if name == "sqlfluff.core":
        raise ImportError("no sqlfluff")
    return _original_import(name, *args, **kwargs)


def test_sqlfluff_import_error() -> None:
    """When sqlfluff is not installed, exit 1 with helpful message."""
    with patch("builtins.__import__", side_effect=_import_raiser):
        result = runner.invoke(app, ["lint-sql"])
    assert result.exit_code == 1
    assert "sqlfluff is not installed" in result.output


# ---------------------------------------------------------------------------
# Tests — no transformers
# ---------------------------------------------------------------------------


def test_no_transformers_found() -> None:
    """When discover returns no SqlTransformers, exit 0."""
    linter_instance = MagicMock()
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[]),
    ):
        result = runner.invoke(app, ["lint-sql"])
    assert result.exit_code == 0
    assert "No SqlTransformers found" in result.output


def test_empty_sql_filtered_out() -> None:
    """Transformers with blank _SQL are excluded."""
    linter_instance = MagicMock()
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformerEmpty()]),
    ):
        result = runner.invoke(app, ["lint-sql"])
    assert result.exit_code == 0
    assert "No SqlTransformers found" in result.output


# ---------------------------------------------------------------------------
# Tests — table filter
# ---------------------------------------------------------------------------


def test_table_filter_narrows_scope() -> None:
    """--table flag filters to only the matching output_table."""
    linter_instance = MagicMock()
    linter_instance.lint_string.return_value = _lint_result()
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer(), _FakeTransformerB()]),
    ):
        result = runner.invoke(app, ["lint-sql", "--table", "dim_other"])
    assert result.exit_code == 0
    assert "Linted 1 transforms" in result.output


def test_table_filter_no_match() -> None:
    """--table with no matching transformer exits 0."""
    linter_instance = MagicMock()
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
    ):
        result = runner.invoke(app, ["lint-sql", "--table", "nonexistent"])
    assert result.exit_code == 0
    assert "No SqlTransformers found" in result.output


# ---------------------------------------------------------------------------
# Tests — lint with no violations
# ---------------------------------------------------------------------------


def test_lint_clean() -> None:
    """All transformers lint clean -> exit 0."""
    linter_instance = MagicMock()
    linter_instance.lint_string.return_value = _lint_result()
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
    ):
        result = runner.invoke(app, ["lint-sql"])
    assert result.exit_code == 0
    assert "0 violation(s) found" in result.output


# ---------------------------------------------------------------------------
# Tests — lint with violations
# ---------------------------------------------------------------------------


def test_lint_with_violations_exits_1() -> None:
    """Violations cause exit 1 and display a results table."""
    violation = _make_violation()
    linter_instance = MagicMock()
    linter_instance.lint_string.return_value = _lint_result([violation])
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
    ):
        result = runner.invoke(app, ["lint-sql"])
    assert result.exit_code == 1
    assert "1 violation(s) found" in result.output
    assert "fact_example" in result.output


# ---------------------------------------------------------------------------
# Tests — fix mode
# ---------------------------------------------------------------------------


def test_fix_mode_no_change() -> None:
    """--fix with no actual changes does not write files."""
    sql_in = "SELECT 1 AS id\n"
    linter_instance = MagicMock()
    linter_instance.fix_string.return_value = _fix_result(sql_in)
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
        patch("nbadb.cli.commands.lint_sql._write_fix") as mock_write,
    ):
        result = runner.invoke(app, ["lint-sql", "--fix"])
    assert result.exit_code == 0
    mock_write.assert_not_called()
    assert "0 auto-fixed" in result.output


def test_fix_mode_applies_fix() -> None:
    """--fix rewrites source when SQL changes."""
    fixed_sql = "SELECT\n    1 AS id\n"
    linter_instance = MagicMock()
    linter_instance.fix_string.return_value = _fix_result(fixed_sql)
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
        patch("nbadb.cli.commands.lint_sql._write_fix") as mock_write,
    ):
        result = runner.invoke(app, ["lint-sql", "--fix"])
    assert result.exit_code == 0
    mock_write.assert_called_once()
    assert "1 auto-fixed" in result.output


def test_fix_mode_with_remaining_violations_reports_them() -> None:
    """--fix with remaining violations reports them but exits 0 (fix mode skips final exit 1)."""
    violation = _make_violation()
    fixed_sql = "SELECT\n    1 AS id\n"
    linter_instance = MagicMock()
    linter_instance.fix_string.return_value = _fix_result(fixed_sql, [violation])
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
        patch("nbadb.cli.commands.lint_sql._write_fix"),
    ):
        result = runner.invoke(app, ["lint-sql", "--fix"])
    # In fix mode, the `total_violations > 0 and not fix` guard is False,
    # so remaining violations are reported but do not cause exit 1 unless
    # --fail-on is also specified.
    assert result.exit_code == 0
    assert "1 violation(s) found" in result.output
    assert "1 auto-fixed" in result.output


def test_fix_mode_with_fail_on_exits_1() -> None:
    """--fix combined with --fail-on error exits 1 on error-severity violations."""
    violation = _make_violation(severity="error")
    fixed_sql = "SELECT\n    1 AS id\n"
    linter_instance = MagicMock()
    linter_instance.fix_string.return_value = _fix_result(fixed_sql, [violation])
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
        patch("nbadb.cli.commands.lint_sql._write_fix"),
    ):
        result = runner.invoke(app, ["lint-sql", "--fix", "--fail-on", "error"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Tests — fail-on severity
# ---------------------------------------------------------------------------


def test_fail_on_error_skips_warnings() -> None:
    """--fail-on error with only warning-severity still exits 1 (total_violations > 0)."""
    violation = _make_violation(severity="warning")
    linter_instance = MagicMock()
    linter_instance.lint_string.return_value = _lint_result([violation])
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
    ):
        result = runner.invoke(app, ["lint-sql", "--fail-on", "error"])
    # The fail_on check doesn't trigger for warnings when fail_on="error",
    # but the final total_violations > 0 check still causes exit 1.
    assert result.exit_code == 1


def test_fail_on_error_exits_on_error_severity() -> None:
    """--fail-on error exits 1 when an error-severity violation exists."""
    violation = _make_violation(severity="error")
    linter_instance = MagicMock()
    linter_instance.lint_string.return_value = _lint_result([violation])
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
    ):
        result = runner.invoke(app, ["lint-sql", "--fail-on", "error"])
    assert result.exit_code == 1


def test_fail_on_warning_exits_on_warning() -> None:
    """--fail-on warning exits 1 on warning-severity violations."""
    violation = _make_violation(severity="warning")
    linter_instance = MagicMock()
    linter_instance.lint_string.return_value = _lint_result([violation])
    fake_sqlfluff = _mock_sqlfluff(linter_instance)

    with (
        patch.dict(sys.modules, {"sqlfluff": MagicMock(), "sqlfluff.core": fake_sqlfluff}),
        patch(_DISCOVER_PATH, return_value=[_FakeTransformer()]),
    ):
        result = runner.invoke(app, ["lint-sql", "--fail-on", "warning"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Tests — _write_fix
# ---------------------------------------------------------------------------


def test_write_fix_rewrites_source(tmp_path) -> None:  # noqa: ANN001
    """_write_fix replaces _SQL content in the source file."""
    from nbadb.cli.commands.lint_sql import _write_fix

    src_content = '''class MyTransformer(SqlTransformer):
    _SQL = """SELECT 1 AS id"""
'''
    src_file = tmp_path / "my_transformer.py"
    src_file.write_text(src_content, encoding="utf-8")

    class _LocalTransformer:
        _SQL = "SELECT 1 AS id"

    transformer = _LocalTransformer()

    with patch("inspect.getfile", return_value=str(src_file)):
        _write_fix(transformer, "SELECT\n    1 AS id")

    result = src_file.read_text(encoding="utf-8")
    assert "SELECT\n    1 AS id" in result
    assert "SELECT 1 AS id" not in result


def test_write_fix_no_src_file() -> None:
    """_write_fix does nothing when inspect.getfile returns falsy."""
    from nbadb.cli.commands.lint_sql import _write_fix

    class _LocalTransformer:
        _SQL = "SELECT 1"

    with patch("inspect.getfile", return_value=""):
        # Should not raise
        _write_fix(_LocalTransformer(), "SELECT 2")


def test_write_fix_sql_not_in_source(tmp_path) -> None:  # noqa: ANN001
    """_write_fix skips when _SQL is not found in source."""
    from nbadb.cli.commands.lint_sql import _write_fix

    src_content = "# nothing here\n"
    src_file = tmp_path / "other.py"
    src_file.write_text(src_content, encoding="utf-8")

    class _LocalTransformer:
        _SQL = "SELECT 99"

    with patch("inspect.getfile", return_value=str(src_file)):
        _write_fix(_LocalTransformer(), "SELECT 100")

    # File should be unchanged (no write happened)
    assert src_file.read_text(encoding="utf-8") == src_content
