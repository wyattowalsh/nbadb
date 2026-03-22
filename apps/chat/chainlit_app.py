"""nbadb Chat — Chainlit frontend for the NBA data analytics agent."""

from __future__ import annotations

import json

import chainlit as cl
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from apps.chat.server.agent import create_nba_agent
from apps.chat.server.config import ChatSettings


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize the agent when a new chat session starts."""
    settings = ChatSettings()
    agent = await create_nba_agent(settings)
    cl.user_session.set("agent", agent)
    cl.user_session.set("settings", settings)


@cl.on_settings_update
async def on_settings_update(settings_dict: dict) -> None:
    """Recreate the agent when provider settings change."""
    current = cl.user_session.get("settings")
    if current is None:
        current = ChatSettings()

    # Update settings from the UI
    for key in ("provider", "api_key", "base_url", "model", "temperature"):
        if key in settings_dict and settings_dict[key]:
            setattr(current, key, settings_dict[key])

    agent = await create_nba_agent(current)
    cl.user_session.set("agent", agent)
    cl.user_session.set("settings", current)
    await cl.Message(content="Settings updated. Agent reconfigured.").send()


@cl.on_message
async def on_message(msg: cl.Message) -> None:
    """Handle incoming user messages."""
    agent = cl.user_session.get("agent")
    if agent is None:
        await cl.Message(content="Agent not initialized. Please refresh.").send()
        return

    response = cl.Message(content="")
    await response.send()

    async for event in agent.astream(
        {"messages": [HumanMessage(content=msg.content)]},
        stream_mode="messages",
    ):
        # astream with stream_mode="messages" yields (message, metadata) tuples
        message, _metadata = event

        if isinstance(message, AIMessage) and message.content:
            if isinstance(message.content, str):
                await response.stream_token(message.content)

        elif isinstance(message, ToolMessage):
            await _render_tool_result(message)

    await response.update()


async def _render_tool_result(message: ToolMessage) -> None:
    """Render tool results as Chainlit elements (charts, tables, text)."""
    content = message.content
    if not isinstance(content, str):
        return

    # Try to parse as JSON for structured results
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        # Plain text tool result — show as a step
        async with cl.Step(name=message.name or "Tool", type="tool") as step:
            step.output = content
        return

    # Handle SQL query results
    if isinstance(data, dict) and "columns" in data and "rows" in data:
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        elements: list[cl.Element] = [
            cl.Dataframe(name="query_result", data=df, display="inline"),
        ]
        sql = data.get("sql", "")
        caption = f"Query returned {data.get('row_count', len(df))} rows"
        if sql:
            caption += f"\n```sql\n{sql}\n```"
        await cl.Message(content=caption, elements=elements).send()
        return

    # Handle error responses
    if isinstance(data, dict) and "error" in data:
        await cl.Message(content=f"Tool error: {data['error']}").send()
        return

    # Check if content looks like Plotly JSON (has "data" and "layout" keys)
    if isinstance(data, dict) and "data" in data and "layout" in data:
        import plotly.io as pio

        fig = pio.from_json(json.dumps(data))
        elements = [cl.Plotly(name="chart", figure=fig, display="inline")]
        await cl.Message(content="", elements=elements).send()
        return

    # Fallback: show as formatted JSON
    async with cl.Step(name=message.name or "Tool", type="tool") as step:
        step.output = json.dumps(data, indent=2, default=str)
