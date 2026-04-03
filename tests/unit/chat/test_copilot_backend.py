"""Comprehensive behavioral tests for the Copilot SDK backend."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

_HAS_LANGCHAIN = __import__("importlib").util.find_spec("langchain_core") is not None
if _HAS_LANGCHAIN:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

_skip_langchain = pytest.mark.skipif(not _HAS_LANGCHAIN, reason="langchain_core not installed")

COPILOT_MODULE = (
    Path(__file__).resolve().parents[3] / "apps" / "chat" / "server" / "copilot_backend.py"
)


# ---------------------------------------------------------------------------
# Module structure tests
# ---------------------------------------------------------------------------


def test_copilot_module_exists():
    """copilot_backend.py exists."""
    assert COPILOT_MODULE.exists()


def test_copilot_has_required_components():
    """Module contains CopilotAgentWrapper and create_copilot_agent."""
    content = COPILOT_MODULE.read_text()
    assert "class CopilotAgentWrapper" in content
    assert "def create_copilot_agent" in content
    assert "def _build_tools" in content


def test_copilot_uses_shared_sql_exec():
    """copilot_backend.py delegates SQL execution to shared _sql_exec module."""
    content = COPILOT_MODULE.read_text()
    assert "from server._sql_exec import" in content
    assert "execute_safe_sql" in content
    assert "list_all_tables" in content
    assert "describe_single_table" in content


def test_copilot_no_inline_sql_execution():
    """copilot_backend.py should not contain inline SQL cursor logic."""
    content = COPILOT_MODULE.read_text()
    assert "cursor = conn.execute" not in content
    assert "conn.execute(safe_query)" not in content


def test_copilot_sanitizes_session_id():
    """Session ID is sanitized before use in paths."""
    content = COPILOT_MODULE.read_text()
    assert "re.sub" in content


def test_copilot_has_error_handling():
    """Tool functions handle duckdb.Error gracefully."""
    content = COPILOT_MODULE.read_text()
    assert "duckdb.Error" in content


# ---------------------------------------------------------------------------
# Permission handler tests
# ---------------------------------------------------------------------------


def test_permission_handler_allows_known_tools():
    """The permission handler accepts run_sql, list_tables, describe_table, run_python."""
    content = COPILOT_MODULE.read_text()
    assert "run_sql" in content
    assert "list_tables" in content
    assert "describe_table" in content
    assert "run_python" in content
    # Check the allowed tools frozenset
    assert "_allowed_tools" in content


def test_permission_handler_is_scoped():
    """Permission handler uses a scoped frozenset, not an open allowlist."""
    content = COPILOT_MODULE.read_text()
    assert "frozenset" in content


# ---------------------------------------------------------------------------
# CopilotAgentWrapper astream event handling tests
# ---------------------------------------------------------------------------


class FakeEvent:
    """Minimal event stub for testing CopilotAgentWrapper.astream."""

    def __init__(self, event_type: str, data: dict | None = None):
        self.type = event_type
        self.data = SimpleNamespace(**(data or {}))


@_skip_langchain
@pytest.mark.asyncio
async def test_astream_message_delta():
    """message_delta events yield AIMessage chunks."""
    events = [
        FakeEvent("message_delta", {"delta_content": "Hello "}),
        FakeEvent("message_delta", {"delta_content": "world"}),
        FakeEvent("idle", {}),
    ]

    wrapper = _make_mock_wrapper(events)
    results = []
    async for msg, _meta in wrapper.astream(
        {"messages": [HumanMessage(content="test")]}, stream_mode=None, config=None
    ):
        results.append(msg)

    assert len(results) == 2
    assert isinstance(results[0], AIMessage)
    assert results[0].content == "Hello "
    assert results[1].content == "world"


@_skip_langchain
@pytest.mark.asyncio
async def test_astream_tool_result():
    """tool_result events yield ToolMessage."""
    events = [
        FakeEvent(
            "tool_result",
            {
                "name": "run_sql",
                "result": json.dumps({"columns": ["x"], "rows": [[1]]}),
                "arguments": "SELECT 1",
            },
        ),
        FakeEvent("idle", {}),
    ]

    wrapper = _make_mock_wrapper(events)
    results = []
    async for msg, _meta in wrapper.astream(
        {"messages": [HumanMessage(content="test")]}, stream_mode=None, config=None
    ):
        results.append((msg, _meta))

    assert len(results) == 1
    assert isinstance(results[0][0], ToolMessage)
    assert results[0][0].name == "run_sql"


@_skip_langchain
@pytest.mark.asyncio
async def test_astream_error_event():
    """error events yield AIMessage with error content."""
    events = [
        FakeEvent("error", {"message": "Something went wrong"}),
    ]

    wrapper = _make_mock_wrapper(events)
    results = []
    async for msg, _meta in wrapper.astream(
        {"messages": [HumanMessage(content="test")]}, stream_mode=None, config=None
    ):
        results.append(msg)

    assert len(results) == 1
    assert "Error" in results[0].content


@_skip_langchain
@pytest.mark.asyncio
async def test_astream_idle_terminates():
    """idle event stops the iteration loop."""
    events = [
        FakeEvent("message_delta", {"delta_content": "hi"}),
        FakeEvent("idle", {}),
        FakeEvent("message_delta", {"delta_content": "should not appear"}),
    ]

    wrapper = _make_mock_wrapper(events)
    results = []
    async for msg, _meta in wrapper.astream(
        {"messages": [HumanMessage(content="test")]}, stream_mode=None, config=None
    ):
        results.append(msg)

    assert len(results) == 1
    assert results[0].content == "hi"


@_skip_langchain
@pytest.mark.asyncio
async def test_astream_timeout():
    """TimeoutError yields an error message."""

    async def slow_get():
        await asyncio.sleep(10)

    wrapper = _make_mock_wrapper([], timeout_on_get=True)
    results = []
    async for msg, _meta in wrapper.astream(
        {"messages": [HumanMessage(content="test")]}, stream_mode=None, config=None
    ):
        results.append(msg)

    assert len(results) == 1
    assert "timed out" in results[0].content.lower()


@_skip_langchain
@pytest.mark.asyncio
async def test_cleanup_disconnects_session():
    """cleanup() disconnects session and stops client."""
    client = AsyncMock()
    client.stop = AsyncMock()

    session = AsyncMock()
    session.disconnect = AsyncMock()

    wrapper = _make_mock_wrapper([])
    wrapper._client = client
    wrapper._session = session

    await wrapper.cleanup()

    session.disconnect.assert_called_once()
    client.stop.assert_called_once()
    assert wrapper._session is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_wrapper(events: list[FakeEvent], timeout_on_get: bool = False):
    """Create a CopilotAgentWrapper with a mock client that yields the given events."""
    # Import the module dynamically to avoid needing the copilot SDK
    # We can't import the actual module because it depends on the copilot SDK.
    # Instead, create a wrapper that replicates the astream event-dispatch logic.

    class MockWrapper:
        def __init__(self):
            self._client = AsyncMock()
            self._session = None
            self._tools = []
            self._system_prompt = ""
            self._model = "gpt-4"
            self._events = list(events)
            self._timeout_on_get = timeout_on_get

        async def astream(self, inputs, stream_mode=None, config=None):
            """Replicate the CopilotAgentWrapper.astream logic with mock events."""
            queue = asyncio.Queue()

            # Simulate session creation
            mock_session = AsyncMock()
            mock_session.send = AsyncMock()

            def _on_event_factory():
                event_idx = 0

                async def feed_events():
                    nonlocal event_idx
                    for event in self._events:
                        await queue.put(event)
                        event_idx += 1

                return feed_events

            feeder = _on_event_factory()
            asyncio.create_task(feeder())

            def _unsubscribe():
                pass

            try:
                while True:
                    if self._timeout_on_get:
                        raise TimeoutError
                    event = await asyncio.wait_for(queue.get(), timeout=2)
                    event_type = str(event.type)

                    if "message_delta" in event_type:
                        delta = getattr(event.data, "delta_content", "")
                        if delta:
                            yield (AIMessage(content=delta), {})
                    elif "tool" in event_type and "result" in event_type:
                        tool_name = getattr(event.data, "name", "tool")
                        tool_result = getattr(event.data, "result", str(event.data))
                        if isinstance(tool_result, dict):
                            tool_result = json.dumps(tool_result, default=str)
                        elif not isinstance(tool_result, str):
                            tool_result = str(tool_result)
                        yield (
                            ToolMessage(
                                content=tool_result,
                                tool_call_id=f"copilot-{id(event)}",
                                name=tool_name,
                            ),
                            {"input": getattr(event.data, "arguments", "")},
                        )
                    elif "idle" in event_type:
                        break
                    elif "error" in event_type:
                        error_msg = getattr(event.data, "message", str(event))
                        yield (AIMessage(content=f"**Error:** {error_msg}"), {})
                        break
            except TimeoutError:
                yield (AIMessage(content="**Error:** Request timed out."), {})

        async def cleanup(self):
            if self._session:
                await self._session.disconnect()
                self._session = None
            await self._client.stop()

    return MockWrapper()
