from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from nbadb.chat.runtime import ChatRuntime, build_runtime
from nbadb.chat.runtime.core import WarehouseUnavailableError, require_usable_warehouse


def test_chat_runtime_delegates_to_query_agent() -> None:
    runtime = ChatRuntime(duckdb_path=Path("/tmp/test.duckdb"))

    with patch("nbadb.chat.runtime.core.QueryAgent") as query_agent:
        expected = query_agent.return_value.ask_result.return_value
        result = runtime.ask("Who scored the most?", limit=7)

    query_agent.assert_called_once_with(Path("/tmp/test.duckdb"))
    query_agent.return_value.ask_result.assert_called_once_with("Who scored the most?", limit=7)
    assert result is expected


def test_build_runtime_requires_duckdb_path() -> None:
    with patch("nbadb.chat.runtime.core.get_settings") as get_settings:
        get_settings.return_value.duckdb_path = None
        with pytest.raises(RuntimeError, match="NBADB_DUCKDB_PATH"):
            build_runtime()


def test_require_usable_warehouse_accepts_valid_duckdb(tmp_path: Path) -> None:
    warehouse = tmp_path / "nba.duckdb"
    duckdb.connect(str(warehouse)).close()

    assert require_usable_warehouse(warehouse) == warehouse.resolve()


def test_require_usable_warehouse_rejects_corrupt_file(tmp_path: Path) -> None:
    warehouse = tmp_path / "nba.duckdb"
    warehouse.write_bytes(b"not a DuckDB database")

    with pytest.raises(WarehouseUnavailableError, match="not found or unusable"):
        require_usable_warehouse(warehouse)


def test_build_runtime_rejects_corrupt_warehouse(tmp_path: Path) -> None:
    warehouse = tmp_path / "nba.duckdb"
    warehouse.write_bytes(b"not a DuckDB database")

    with patch("nbadb.chat.runtime.core.get_settings") as get_settings:
        get_settings.return_value.duckdb_path = warehouse
        with pytest.raises(WarehouseUnavailableError, match="not found or unusable"):
            build_runtime()


def test_require_usable_warehouse_bounds_invalid_path_errors() -> None:
    with pytest.raises(WarehouseUnavailableError, match="not found or unusable") as exc_info:
        require_usable_warehouse("\0")

    assert "embedded null" not in str(exc_info.value)


def test_chat_runtime_caches_one_query_agent() -> None:
    """W8.5 R2-HIGH: the agent (catalog load + validation) is built once per runtime."""
    runtime = ChatRuntime(duckdb_path=Path("/tmp/test.duckdb"))

    with patch("nbadb.chat.runtime.core.QueryAgent") as query_agent:
        first = runtime.ask("first question")
        second = runtime.ask("second question")

    query_agent.assert_called_once_with(Path("/tmp/test.duckdb"))
    assert first is query_agent.return_value.ask_result.return_value
    assert second is query_agent.return_value.ask_result.return_value
