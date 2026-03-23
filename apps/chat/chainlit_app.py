"""nbadb Chat — Chainlit frontend for the NBA data analytics agent."""

from __future__ import annotations

import json
import sys

import chainlit as cl
import pandas as pd
from chainlit.input_widget import Select, Slider, TextInput
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger
from server.agent import create_nba_agent
from server.config import ChatSettings
from server.tracing import setup_tracing

# Configure loguru — compact format, INFO level
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")


# -- Profile-specific starters ------------------------------------------------

_QUICK_STATS_STARTERS = [
    cl.Starter(
        label="Top scorers this season",
        message="Who are the top 10 scorers this season? Show me a bar chart.",
        icon="/public/icons/trophy.svg",
    ),
    cl.Starter(
        label="Team standings",
        message="Show me the current NBA standings by conference with win percentages.",
        icon="/public/icons/standings.svg",
    ),
    cl.Starter(
        label="Career averages",
        message="What are LeBron James' career averages across all seasons?",
        icon="/public/icons/stats.svg",
    ),
    cl.Starter(
        label="Best home record",
        message="Which team has the best home record this season?",
        icon="/public/icons/trend.svg",
    ),
]

_DEEP_ANALYSIS_STARTERS = [
    cl.Starter(
        label="Player comparison",
        message=(
            "Compare LeBron James and Stephen Curry's career stats "
            "side by side with a visualization."
        ),
        icon="/public/icons/versus.svg",
    ),
    cl.Starter(
        label="Shooting efficiency",
        message=(
            "Who are the most efficient scorers? Calculate TS% for players averaging 20+ PPG."
        ),
        icon="/public/icons/target.svg",
    ),
    cl.Starter(
        label="MVP candidates",
        message=(
            "Analyze how the top 5 MVP candidates compare across all advanced metrics this season."
        ),
        icon="/public/icons/trophy.svg",
    ),
    cl.Starter(
        label="Offense vs defense",
        message=("Break down the Lakers' offensive and defensive ratings over the last 5 seasons."),
        icon="/public/icons/stats.svg",
    ),
]

_VISUALIZATION_STARTERS = [
    cl.Starter(
        label="TS% vs usage scatter",
        message=(
            "Create a scatter plot of true shooting percentage vs usage rate "
            "for all players averaging 20+ PPG this season."
        ),
        icon="/public/icons/chart.svg",
    ),
    cl.Starter(
        label="Win trend line chart",
        message=(
            "Show me a line chart of the Warriors' win percentage "
            "trend by season over the last 10 years."
        ),
        icon="/public/icons/trend.svg",
    ),
    cl.Starter(
        label="Scoring distribution",
        message=("Visualize the points-per-game distribution across all NBA teams as a box plot."),
        icon="/public/icons/chart.svg",
    ),
    cl.Starter(
        label="Triple-double leaders",
        message=("Plot a bar chart of the top 10 triple-double leaders over the last 5 seasons."),
        icon="/public/icons/trophy.svg",
    ),
]

# -- Chat profiles -------------------------------------------------------------


@cl.set_chat_profiles
async def chat_profiles():
    """Define analysis modes with tailored starters."""
    return [
        cl.ChatProfile(
            name="Quick Stats",
            markdown_description="Fast answers with tables. Low temperature for precision.",
            icon="/public/icons/trophy.svg",
            starters=_QUICK_STATS_STARTERS,
        ),
        cl.ChatProfile(
            name="Deep Analysis",
            markdown_description=("Multi-step analysis with advanced metrics and context."),
            icon="/public/icons/target.svg",
            starters=_DEEP_ANALYSIS_STARTERS,
        ),
        cl.ChatProfile(
            name="Visualization",
            markdown_description=("Chart-first responses. Every answer includes a visualization."),
            icon="/public/icons/chart.svg",
            starters=_VISUALIZATION_STARTERS,
        ),
    ]


# -- Author rename --------------------------------------------------------------


@cl.author_rename
async def rename(orig_author: str) -> str:
    """Map raw tool names to user-friendly labels."""
    return {
        "run_sql": "SQL Query",
        "run_python": "Python",
        "list_tables": "Schema",
        "describe_table": "Schema",
        "web_search": "Web Search",
        "web_fetch": "Web Fetch",
    }.get(orig_author, orig_author)


# -- Action callbacks -----------------------------------------------------------


@cl.action_callback("copy_sql")
async def on_copy_sql(action: cl.Action) -> None:
    """Show SQL query for easy copying."""
    sql = action.payload.get("sql", "")
    await cl.Message(content=f"```sql\n{sql}\n```").send()
    await action.remove()


@cl.action_callback("download_csv")
async def on_download_csv(action: cl.Action) -> None:
    """Generate and send a CSV file from query results."""
    raw = action.payload.get("data", "{}")
    data = json.loads(raw) if isinstance(raw, str) else raw
    df = pd.DataFrame(data.get("rows", []), columns=data.get("columns", []))
    csv_bytes = df.to_csv(index=False).encode()
    elements = [cl.File(name="query_result.csv", content=csv_bytes, display="inline")]
    await cl.Message(content="", elements=elements).send()
    await action.remove()


@cl.action_callback("refine_query")
async def on_refine_query(action: cl.Action) -> None:
    """Prompt the user to refine their last query."""
    sql = action.payload.get("sql", "")
    await cl.Message(
        content=f"What would you like to change about this query?\n```sql\n{sql}\n```",
    ).send()


# -- Lifecycle hooks ------------------------------------------------------------


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize the agent when a new chat session starts."""
    settings = ChatSettings()

    # Adjust settings based on selected profile
    profile = cl.user_session.get("chat_profile")
    if profile == "Quick Stats":
        settings = settings.model_copy(update={"temperature": 0.05})

    try:
        agent = await create_nba_agent(settings)
    except Exception as e:
        await cl.Message(
            content=(
                f"**Failed to initialize agent:** {e}\n\n"
                "Please check your configuration and refresh."
            )
        ).send()
        return

    callbacks = setup_tracing(settings)
    cl.user_session.set("agent", agent)
    cl.user_session.set("settings", settings)
    cl.user_session.set("callbacks", callbacks)
    cl.user_session.set("chat_profile_name", profile)

    # Present settings panel via gear icon
    await cl.ChatSettings(
        [
            Select(
                id="provider",
                label="Provider",
                values=[
                    "openai",
                    "anthropic",
                    "google",
                    "ollama",
                    "lmstudio",
                    "copilot",
                    "custom",
                ],
                initial_value=settings.provider,
            ),
            TextInput(
                id="model",
                label="Model",
                initial=settings.model,
                placeholder="gpt-4o, claude-sonnet-4-20250514, gemini-2.0-flash...",
            ),
            TextInput(
                id="api_key",
                label="API Key",
                initial="",
                placeholder="sk-... (leave empty to use env var)",
            ),
            Slider(
                id="temperature",
                label="Temperature",
                initial=settings.temperature,
                min=0.0,
                max=1.5,
                step=0.05,
            ),
            TextInput(
                id="base_url",
                label="Base URL (optional)",
                initial=settings.base_url or "",
                placeholder="Custom API endpoint",
            ),
        ]
    ).send()


@cl.on_settings_update
async def on_settings_update(settings_dict: dict) -> None:
    """Recreate the agent when provider settings change."""
    current = cl.user_session.get("settings")
    if current is None:
        current = ChatSettings()

    # Update settings from the UI — handle api_key separately (HR-5)
    updates = {
        k: v
        for k, v in settings_dict.items()
        if k in ("provider", "base_url", "model", "temperature") and v is not None
    }
    # Only update api_key if the user actually entered a value
    if settings_dict.get("api_key"):
        updates["api_key"] = settings_dict["api_key"]

    if updates:
        current = current.model_copy(update=updates)

    # Clean up old agent before creating a new one (HR-3)
    old_agent = cl.user_session.get("agent")
    if old_agent is not None and hasattr(old_agent, "cleanup"):
        await old_agent.cleanup()

    agent = await create_nba_agent(current)
    callbacks = setup_tracing(current)
    cl.user_session.set("agent", agent)
    cl.user_session.set("settings", current)
    cl.user_session.set("callbacks", callbacks)
    await cl.Message(content="Settings updated. Agent reconfigured.").send()


@cl.on_chat_end
async def on_chat_end() -> None:
    """Clean up resources when the chat session ends."""
    agent = cl.user_session.get("agent")
    if agent is not None and hasattr(agent, "cleanup"):
        await agent.cleanup()


# -- Message handling -----------------------------------------------------------


@cl.on_message
async def on_message(msg: cl.Message) -> None:
    """Handle incoming user messages."""
    agent = cl.user_session.get("agent")
    if agent is None:
        await cl.Message(content="Agent not initialized. Please refresh.").send()
        return

    callbacks = cl.user_session.get("callbacks") or []
    config = {"callbacks": callbacks} if callbacks else {}

    response = cl.Message(content="")
    await response.send()

    try:
        async for event in agent.astream(
            {"messages": [HumanMessage(content=msg.content)]},
            stream_mode="messages",
            config=config,
        ):
            # Guard against non-tuple events from LangGraph state updates
            if not isinstance(event, tuple) or len(event) != 2:
                continue

            message, _metadata = event

            if isinstance(message, AIMessage) and message.content:
                if isinstance(message.content, str):
                    await response.stream_token(message.content)

            elif isinstance(message, ToolMessage):
                tool_name = message.name or "tool"
                async with cl.Step(name=tool_name, type="tool") as tool_step:
                    tool_step.input = (
                        _metadata.get("input", "") if isinstance(_metadata, dict) else ""
                    )
                    await _render_tool_result(message, tool_step)
    except Exception as exc:
        logger.exception("Agent streaming error")
        response.content = f"**Error:** {exc}"
    finally:
        await response.update()


# -- Tool result rendering ------------------------------------------------------


async def _render_tool_result(message: ToolMessage, step: cl.Step) -> None:
    """Render tool results into the already-open Chainlit step."""
    content = message.content
    if not isinstance(content, str):
        return

    # Try to parse as JSON for structured results
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        step.output = content
        return

    if not isinstance(data, dict):
        step.output = json.dumps(data, indent=2, default=str)
        return

    # SQL query results
    if "columns" in data and "rows" in data:
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        step.elements = [cl.Dataframe(name="query_result", data=df, display="inline")]
        sql = data.get("sql", "")
        caption = f"{data.get('row_count', len(df))} rows returned"
        if sql:
            caption += f"\n```sql\n{sql}\n```"
        step.output = caption

        # Action buttons for SQL results
        payload_rows = data["rows"][:100]  # Cap payload size
        step.actions = [
            cl.Action(
                name="copy_sql",
                label="Copy SQL",
                payload={"sql": sql},
            ),
            cl.Action(
                name="download_csv",
                label="Download CSV",
                payload={
                    "data": json.dumps(
                        {"columns": data["columns"], "rows": payload_rows},
                        default=str,
                    )
                },
            ),
        ]
        if sql:
            step.actions.append(
                cl.Action(
                    name="refine_query",
                    label="Refine",
                    payload={"sql": sql},
                ),
            )
        return

    # Error responses
    if "error" in data:
        error_msg = data["error"]
        stdout = data.get("stdout", "")
        output = f"**Error:** {error_msg}"
        if stdout:
            output += f"\n\n**Output before error:**\n```\n{stdout}\n```"
        step.output = output
        return

    # Matplotlib base64 PNG images
    if "image_base64" in data:
        import base64

        img_bytes = base64.b64decode(data["image_base64"])
        step.elements = [cl.Image(name="chart", content=img_bytes, display="inline")]
        step.output = "Chart"
        return

    # Plotly JSON (has "data" and "layout" keys)
    if "data" in data and "layout" in data:
        import plotly.io as pio

        fig = pio.from_json(json.dumps(data))
        step.elements = [cl.Plotly(name="chart", figure=fig, display="inline")]
        step.output = "Chart"
        return

    # Sandbox stdout output
    if "stdout" in data:
        stdout = data["stdout"]
        stderr = data.get("stderr", "")
        step.output = f"```\n{stdout}\n```" if stdout else ""
        if stderr:
            step.output += f"\n**stderr:**\n```\n{stderr}\n```"
        return

    # Fallback: show as formatted JSON
    step.output = json.dumps(data, indent=2, default=str)
