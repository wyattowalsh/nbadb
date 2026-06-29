from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nbadb.chat.runtime import ChatRuntime, build_runtime


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
