"""Tests for the shared SQL execution library."""

from __future__ import annotations

from pathlib import Path

SQL_EXEC_MODULE = Path(__file__).resolve().parents[3] / "apps" / "chat" / "server" / "_sql_exec.py"


def test_module_exists():
    """The shared SQL execution module exists."""
    assert SQL_EXEC_MODULE.exists()


def test_module_has_expected_functions():
    """Module exports execute_safe_sql, list_all_tables, describe_single_table."""
    content = SQL_EXEC_MODULE.read_text()
    assert "def execute_safe_sql(" in content
    assert "def list_all_tables(" in content
    assert "def describe_single_table(" in content


def test_execute_safe_sql_sets_enable_external_access():
    """execute_safe_sql disables external access on every connection."""
    content = SQL_EXEC_MODULE.read_text()
    assert "SET enable_external_access = false" in content


def test_execute_safe_sql_returns_original_query():
    """The result includes the original query (not the wrapped version)."""
    content = SQL_EXEC_MODULE.read_text()
    # The return dict should have "sql": query (the original), not safe_sql
    assert '"sql": query' in content


def test_mcp_sql_uses_shared_module():
    """mcp_servers/sql.py delegates to the shared _sql_exec module."""
    mcp_path = Path(__file__).resolve().parents[3] / "apps" / "chat" / "mcp_servers" / "sql.py"
    content = mcp_path.read_text()
    assert "from _sql_exec import" in content
    assert "execute_safe_sql" in content
    assert "list_all_tables" in content
    assert "describe_single_table" in content


def test_copilot_backend_uses_shared_module():
    """copilot_backend.py delegates to the shared _sql_exec module."""
    copilot_path = (
        Path(__file__).resolve().parents[3] / "apps" / "chat" / "server" / "copilot_backend.py"
    )
    content = copilot_path.read_text()
    assert "from server._sql_exec import" in content
    assert "execute_safe_sql" in content


def test_no_duplicate_sql_logic_in_copilot():
    """copilot_backend.py should not contain inline SQL execution logic."""
    copilot_path = (
        Path(__file__).resolve().parents[3] / "apps" / "chat" / "server" / "copilot_backend.py"
    )
    content = copilot_path.read_text()
    # The inline `conn.execute(safe_query)` pattern should be gone
    assert "cursor = conn.execute(safe_query)" not in content
    assert "cursor = conn.execute(safe_sql)" not in content


def test_no_duplicate_sql_logic_in_mcp():
    """mcp_servers/sql.py should not contain inline SQL execution logic."""
    mcp_path = Path(__file__).resolve().parents[3] / "apps" / "chat" / "mcp_servers" / "sql.py"
    content = mcp_path.read_text()
    # The inline guard + connect pattern should be replaced
    assert "guard.validate(query)" not in content
    assert "guard.wrap_with_limit" not in content
