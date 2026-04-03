"""nbadb Chat — Chainlit frontend for the NBA data analytics agent."""

from __future__ import annotations

import base64
import html as _html
import io
import json
import re
import sys
from pathlib import Path

import chainlit as cl
import pandas as pd
from chainlit.input_widget import Select, Slider, TextInput
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger
from pydantic import SecretStr
from server.agent import create_nba_agent
from server.config import ChatSettings
from server.tracing import setup_tracing

# Configure loguru — compact format, INFO level
logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

_KEY_REQUIRED_PROVIDERS = frozenset({"openai", "anthropic", "google", "custom", "copilot"})
_PUBLIC_DEMO_SETUP_MESSAGE = (
    "**Public demo: bring your own API key.**\n\n"
    "This anonymous URL exposes the full open-source app. Open the gear icon, "
    "choose a provider and model, and enter your own API key before chatting."
)


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
            "Compare LeBron James and Stephen Curry's career stats side by side with a radar chart."
        ),
        icon="/public/icons/versus.svg",
    ),
    cl.Starter(
        label="Similar players",
        message=(
            "Which players are statistically most similar to Shai Gilgeous-Alexander "
            "this season? Show a comparison table."
        ),
        icon="/public/icons/stats.svg",
    ),
    cl.Starter(
        label="Significance test",
        message=(
            "Is Jayson Tatum's 3-point shooting this season significantly "
            "different from last season? Run a statistical test."
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
]

_VISUALIZATION_STARTERS = [
    cl.Starter(
        label="Shot chart heatmap",
        message=("Show me Stephen Curry's shot chart this season as a heatmap on a court diagram."),
        icon="/public/icons/target.svg",
    ),
    cl.Starter(
        label="TS% vs usage scatter",
        message=(
            "Create a scatter plot of true shooting percentage vs usage rate "
            "for all players averaging 20+ PPG this season."
        ),
        icon="/public/icons/chart.svg",
    ),
    cl.Starter(
        label="Compare shooting zones",
        message=(
            "Compare the shooting zones of Jayson Tatum vs Devin Booker "
            "with side-by-side court diagrams."
        ),
        icon="/public/icons/versus.svg",
    ),
    cl.Starter(
        label="Hot streak finder",
        message=("Find the longest scoring streaks of 30+ points this season."),
        icon="/public/icons/trend.svg",
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


@cl.action_callback("copy_code")
async def on_copy_code(action: cl.Action) -> None:
    """Show the code (SQL or Python) used in a step for easy copying."""
    code = action.payload.get("code", "")
    lang = action.payload.get("lang", "python")
    await cl.Message(content=f"```{lang}\n{code}\n```").send()
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


@cl.action_callback("download_xlsx")
async def on_download_xlsx(action: cl.Action) -> None:
    """Generate and send an XLSX file from query results."""
    raw = action.payload.get("data", "{}")
    data = json.loads(raw) if isinstance(raw, str) else raw
    df = pd.DataFrame(data.get("rows", []), columns=data.get("columns", []))
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    elements = [cl.File(name="query_result.xlsx", content=buf.getvalue(), display="inline")]
    await cl.Message(content="", elements=elements).send()
    await action.remove()


@cl.action_callback("download_json")
async def on_download_json(action: cl.Action) -> None:
    """Generate and send a JSON file from query results."""
    raw = action.payload.get("data", "{}")
    data = json.loads(raw) if isinstance(raw, str) else raw
    df = pd.DataFrame(data.get("rows", []), columns=data.get("columns", []))
    json_str = df.to_json(orient="records", indent=2) or "[]"
    json_bytes = json_str.encode()
    elements = [cl.File(name="query_result.json", content=json_bytes, display="inline")]
    await cl.Message(content="", elements=elements).send()
    await action.remove()


@cl.action_callback("edit_spreadsheet")
async def on_edit_spreadsheet(action: cl.Action) -> None:
    """Generate an editable HTML spreadsheet from query results."""
    raw = action.payload.get("data", "{}")
    data = json.loads(raw) if isinstance(raw, str) else raw
    df = pd.DataFrame(data.get("rows", []), columns=data.get("columns", []))

    # Generate AG Grid HTML spreadsheet
    columns_json = json.dumps(
        [{"field": c, "editable": True, "sortable": True, "filter": True} for c in df.columns]
    )
    rows_json = df.to_json(orient="records") or "[]"
    name = "query_result"
    html_content = _build_spreadsheet_html(name, columns_json, rows_json)
    elements = [cl.File(name=f"{name}.html", content=html_content.encode(), display="inline")]
    await cl.Message(
        content="Open the HTML file in your browser to edit, sort, filter, and export.",
        elements=elements,
    ).send()
    await action.remove()


@cl.action_callback("refine_query")
async def on_refine_query(action: cl.Action) -> None:
    """Prompt the user to refine their last query."""
    sql = action.payload.get("sql", "")
    await cl.Message(
        content=f"What would you like to change about this query?\n```sql\n{sql}\n```",
    ).send()


@cl.action_callback("export_session_code")
async def on_export_session_code(action: cl.Action) -> None:
    """Export all code from the session as a Python script."""
    code_log: list[dict] = cl.user_session.get("code_log") or []
    if not code_log:
        await cl.Message(content="No code has been executed in this session yet.").send()
        return

    lines = [
        '"""NBA Data Analytics — exported session code."""\n',
        "import pandas as pd",
        "import numpy as np",
        "import duckdb",
        "import plotly.express as px",
        "import plotly.graph_objects as go",
        "",
        "# Connect to database (update path as needed)",
        'conn = duckdb.connect("~/.nbadb/data/nba.duckdb", read_only=True)',
        "",
        "def query(sql: str) -> pd.DataFrame:",
        '    """Run SQL and return a DataFrame."""',
        "    return conn.execute(sql).fetchdf()",
        "",
    ]

    for i, entry in enumerate(code_log, 1):
        lines.append(f"# --- Step {i}: {entry['tool']} ---")
        if entry["lang"] == "sql":
            lines.append(f"df_{i} = query({entry['code']!r})")
            lines.append(f"print(df_{i})")
        else:
            lines.append(entry["code"])
        lines.append("")

    script = "\n".join(lines)
    elements = [cl.File(name="session_code.py", content=script.encode(), display="inline")]
    await cl.Message(content="Exported session code:", elements=elements).send()


@cl.action_callback("save_template")
async def on_save_template(action: cl.Action) -> None:
    """Save the session code as a reusable analysis template."""
    code_log: list[dict] = cl.user_session.get("code_log") or []
    if not code_log:
        await cl.Message(content="No code to save as a template.").send()
        return

    raw_name = action.payload.get("name", "analysis")
    name = Path(raw_name).stem
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        name = "analysis"
    template_dir = Path.home() / ".nbadb" / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)

    script = _build_template_script(code_log, name)
    path = template_dir / f"{name}.py"
    path.write_text(script)

    elements = [cl.File(name=f"{name}.py", content=script.encode(), display="inline")]
    await cl.Message(
        content=f'Template saved to `{path}`\nRe-run anytime: *"Run the {name} template"*',
        elements=elements,
    ).send()
    await action.remove()


@cl.action_callback("list_templates")
async def on_list_templates(action: cl.Action) -> None:
    """List all saved analysis templates."""
    template_dir = Path.home() / ".nbadb" / "templates"
    if not template_dir.exists():
        await cl.Message(content="No templates saved yet.").send()
        return
    templates = sorted(template_dir.glob("*.py"))
    if not templates:
        await cl.Message(content="No templates saved yet.").send()
        return
    lines = [f"- **{t.stem}** ({t.stat().st_size} bytes)" for t in templates]
    await cl.Message(content="Saved templates:\n" + "\n".join(lines)).send()


def _build_template_script(code_log: list[dict], name: str) -> str:
    """Build a parameterized template script from the session code log."""
    lines = [
        f'"""NBA Analysis Template: {name}"""',
        "",
        "import pandas as pd",
        "import numpy as np",
        "import duckdb",
        "import plotly.express as px",
        "import plotly.graph_objects as go",
        "",
        "# Parameters — edit these to reuse the template",
        "# PARAMS = {}  # Add your parameters here",
        "",
        "# Connect to database (update path as needed)",
        'conn = duckdb.connect("~/.nbadb/data/nba.duckdb", read_only=True)',
        "",
        "def query(sql: str) -> pd.DataFrame:",
        '    """Run SQL and return a DataFrame."""',
        "    return conn.execute(sql).fetchdf()",
        "",
    ]
    for i, entry in enumerate(code_log, 1):
        lines.append(f"# --- Step {i}: {entry['tool']} ---")
        if entry["lang"] == "sql":
            lines.append(f"df_{i} = query({entry['code']!r})")
            lines.append(f"print(df_{i})")
        else:
            lines.append(entry["code"])
        lines.append("")
    return "\n".join(lines)


def _build_updated_settings(
    current: ChatSettings,
    settings_dict: dict[str, object],
) -> ChatSettings:
    """Validate a full settings snapshot before committing it to session state."""
    updates = {
        k: v
        for k, v in settings_dict.items()
        if k in ("provider", "base_url", "model", "temperature") and v is not None
    }
    api_key = settings_dict.get("api_key")
    if api_key:
        updates["api_key"] = SecretStr(str(api_key))

    merged_settings = current.model_dump(mode="python")
    merged_settings.update(updates)
    return ChatSettings(**merged_settings)


def _prepare_session_settings(
    settings: ChatSettings,
    profile: str | None,
) -> ChatSettings:
    """Apply per-session adjustments before attempting agent creation."""
    next_settings = settings
    if settings.public_demo_mode:
        next_settings = next_settings.model_copy(update={"api_key": None})
    if profile == "Quick Stats":
        next_settings = next_settings.model_copy(update={"temperature": 0.05})
    return next_settings


def _settings_can_create_agent(settings: ChatSettings) -> bool:
    """Return whether the current settings are sufficient to create an agent."""
    return not (settings.provider in _KEY_REQUIRED_PROVIDERS and settings.api_key is None)


async def _send_settings_panel(settings: ChatSettings) -> None:
    """Render the provider settings panel."""
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
                placeholder="Provider model ID, for example gpt-4.1 or gemini-2.5-flash",
            ),
            TextInput(
                id="api_key",
                label="API Key",
                initial="",
                placeholder="Enter your own provider key for this session",
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


def _cleanup_session_state(
    session_id: str | None = None,
    session_root: Path | None = None,
) -> None:
    """Remove only the current session's persisted state directory."""
    import shutil

    resolved_session_id = (
        session_id or cl.user_session.get("session_id") or cl.user_session.get("id")
    )
    if not resolved_session_id:
        return

    resolved_session_root = session_root or (Path.home() / ".nbadb" / "session")
    session_dir = resolved_session_root / str(resolved_session_id)
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)


# -- Lifecycle hooks ------------------------------------------------------------


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize the agent when a new chat session starts."""
    session_id = str(cl.user_session.get("id") or "default")
    cl.user_session.set("session_id", session_id)

    # Adjust settings based on selected profile
    profile = cl.user_session.get("chat_profile")
    settings = _prepare_session_settings(ChatSettings(), profile)

    cl.user_session.set("agent", None)
    cl.user_session.set("settings", settings)
    cl.user_session.set("callbacks", [])
    cl.user_session.set("chat_profile_name", profile)
    cl.user_session.set("code_log", [])  # Track code for session export

    await _send_settings_panel(settings)

    if settings.public_demo_mode and not _settings_can_create_agent(settings):
        await cl.Message(content=_PUBLIC_DEMO_SETUP_MESSAGE).send()
        return

    try:
        agent = await create_nba_agent(settings, profile=profile, session_id=session_id)
    except Exception as e:
        logger.exception("Failed to initialize agent")
        detail = "" if settings.public_demo_mode else f" {e}"
        await cl.Message(
            content=(
                f"**Failed to initialize agent.**{detail}\n\n"
                "Please check your configuration and refresh."
            )
        ).send()
        return

    callbacks = setup_tracing(settings)
    cl.user_session.set("agent", agent)
    cl.user_session.set("callbacks", callbacks)


@cl.on_settings_update
async def on_settings_update(settings_dict: dict) -> None:
    """Recreate the agent when provider settings change."""
    current = cl.user_session.get("settings")
    if current is None:
        current = _prepare_session_settings(ChatSettings(), None)

    profile = cl.user_session.get("chat_profile") or cl.user_session.get("chat_profile_name")
    session_id = str(cl.user_session.get("session_id") or cl.user_session.get("id") or "default")
    old_agent = cl.user_session.get("agent")
    agent = None
    try:
        next_settings = _build_updated_settings(current, settings_dict)
        if next_settings.public_demo_mode and not _settings_can_create_agent(next_settings):
            if old_agent is None:
                cl.user_session.set("agent", None)
                cl.user_session.set("settings", next_settings)
                cl.user_session.set("callbacks", [])
                cl.user_session.set("chat_profile_name", profile)
                await cl.Message(content=_PUBLIC_DEMO_SETUP_MESSAGE).send()
                return
            await cl.Message(
                content=(
                    "**Configuration incomplete.**\n\n"
                    "Your previous agent is still available. Enter a valid provider key to switch."
                )
            ).send()
            return
        agent = await create_nba_agent(next_settings, profile=profile, session_id=session_id)
        callbacks = setup_tracing(next_settings)
    except Exception as e:
        if agent is not None and hasattr(agent, "cleanup"):
            await agent.cleanup()
        logger.exception("Failed to rebuild agent after settings update")
        detail = "" if current.public_demo_mode else f" {e}"
        await cl.Message(
            content=(
                f"**Failed to update settings.**{detail}\n\n"
                "Your previous agent is still available. "
                "Please check your configuration and try again."
            )
        ).send()
        return

    cl.user_session.set("agent", agent)
    cl.user_session.set("settings", next_settings)
    cl.user_session.set("callbacks", callbacks)
    cl.user_session.set("chat_profile_name", profile)
    if old_agent is not None and old_agent is not agent and hasattr(old_agent, "cleanup"):
        try:
            await old_agent.cleanup()
        except Exception:
            logger.exception("Failed to clean up previous agent after settings update")
    await cl.Message(content="Settings updated. Agent reconfigured.").send()


@cl.on_chat_end
async def on_chat_end() -> None:
    """Clean up resources when the chat session ends."""
    try:
        agent = cl.user_session.get("agent")
        if agent is not None and hasattr(agent, "cleanup"):
            await agent.cleanup()
    finally:
        _cleanup_session_state()


# -- Message handling -----------------------------------------------------------


@cl.on_message
async def on_message(msg: cl.Message) -> None:
    """Handle incoming user messages."""
    agent = cl.user_session.get("agent")
    if agent is None:
        settings = cl.user_session.get("settings")
        if settings is not None and getattr(settings, "public_demo_mode", False):
            await cl.Message(content=_PUBLIC_DEMO_SETUP_MESSAGE).send()
        else:
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
        settings = cl.user_session.get("settings")
        if settings and getattr(settings, "public_demo_mode", False):
            response.content = "**Error:** Something went wrong. Please try again."
        else:
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

    # Extract code from step input for Copy Code / session tracking
    step_input = step.input or ""
    tool_name = message.name or "tool"

    # SQL query results
    if "columns" in data and "rows" in data:
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        step.elements = [cl.Dataframe(name="query_result", data=df, display="inline")]
        sql = data.get("sql", "")
        caption = f"{data.get('row_count', len(df))} rows returned"
        if sql:
            caption += f"\n```sql\n{sql}\n```"
        # Auto-annotations: basic stats for numeric columns
        num_cols = df.select_dtypes(include="number")
        if len(df) >= 5 and num_cols.shape[1] > 0:
            stats_parts = []
            for col in num_cols.columns[:3]:
                vals = num_cols[col].dropna()
                if len(vals) >= 3:
                    stats_parts.append(
                        f"**{col}**: mean={vals.mean():.1f}, "
                        f"med={vals.median():.1f}, "
                        f"range=[{vals.min():.1f}\u2013{vals.max():.1f}]"
                    )
            if stats_parts:
                caption += "\n\n*Context:* " + " | ".join(stats_parts)
        if 0 < len(df) < 20:
            caption += f"\n*Note: {len(df)} rows \u2014 small sample.*"
        step.output = caption

        # Data payload for export buttons (capped at 100 rows)
        payload_rows = data["rows"][:100]
        data_payload = json.dumps({"columns": data["columns"], "rows": payload_rows}, default=str)

        step.actions = [
            cl.Action(name="copy_sql", label="Copy SQL", payload={"sql": sql}),
            cl.Action(name="download_csv", label="CSV", payload={"data": data_payload}),
            cl.Action(name="download_xlsx", label="XLSX", payload={"data": data_payload}),
            cl.Action(name="download_json", label="JSON", payload={"data": data_payload}),
            cl.Action(
                name="edit_spreadsheet",
                label="Edit as Spreadsheet",
                payload={"data": data_payload},
            ),
        ]
        if sql:
            step.actions.append(
                cl.Action(name="refine_query", label="Refine", payload={"sql": sql}),
            )
            step.actions.extend(
                [
                    cl.Action(
                        name="export_session_code",
                        label="Export Code",
                        payload={},
                    ),
                    cl.Action(
                        name="save_template",
                        label="Save Template",
                        payload={"name": "analysis"},
                    ),
                ]
            )
            # Track SQL in session code log
            _track_code(sql, tool="run_sql", lang="sql")
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

    # File export from sandbox helpers (to_csv, to_xlsx, to_json)
    if "export_file" in data and "content" in data:
        file_bytes = base64.b64decode(data["content"])
        step.elements = [cl.File(name=data["export_file"], content=file_bytes, display="inline")]
        step.output = f"Exported: **{data['export_file']}**"
        if step_input:
            _add_code_actions(step, step_input, tool_name)
        return

    # Matplotlib base64 PNG images
    if "image_base64" in data:
        img_bytes = base64.b64decode(data["image_base64"])
        step.elements = [cl.Image(name="chart", content=img_bytes, display="inline")]
        step.output = "Chart"
        # Add copy code for the Python that generated the chart
        if step_input:
            _add_code_actions(step, step_input, tool_name)
        return

    # Plotly JSON (has "data" and "layout" keys)
    if "data" in data and "layout" in data:
        import plotly.io as pio

        fig = pio.from_json(json.dumps(data))
        step.elements = [cl.Plotly(name="chart", figure=fig, display="inline")]
        step.output = "Chart"
        if step_input:
            _add_code_actions(step, step_input, tool_name)
        return

    # Sandbox stdout output
    if "stdout" in data:
        stdout = data["stdout"]
        stderr = data.get("stderr", "")
        step.output = f"```\n{stdout}\n```" if stdout else ""
        if stderr:
            step.output += f"\n**stderr:**\n```\n{stderr}\n```"
        if step_input:
            _add_code_actions(step, step_input, tool_name)
        return

    # Fallback: show as formatted JSON
    step.output = json.dumps(data, indent=2, default=str)


def _add_code_actions(step: cl.Step, code: str, tool_name: str) -> None:
    """Add Copy Code + Export Session actions to a step."""
    lang = "sql" if tool_name in ("run_sql", "list_tables", "describe_table") else "python"
    actions = step.actions or []
    actions.extend(
        [
            cl.Action(
                name="copy_code",
                label="Copy Code",
                payload={"code": code, "lang": lang},
            ),
            cl.Action(
                name="export_session_code",
                label="Export All Code",
                payload={},
            ),
        ]
    )
    step.actions = actions
    _track_code(code, tool=tool_name, lang=lang)


def _track_code(code: str, tool: str, lang: str) -> None:
    """Append code to the session-level code log for export."""
    code_log: list[dict] = cl.user_session.get("code_log") or []
    code_log.append({"code": code, "tool": tool, "lang": lang})
    cl.user_session.set("code_log", code_log)


def _build_spreadsheet_html(name: str, columns_json: str, rows_json: str) -> str:
    """Generate a self-contained HTML file with an AG Grid editable spreadsheet."""
    safe_name = _html.escape(name)
    safe_rows = rows_json.replace("</", "<\\/")
    safe_cols = columns_json.replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{safe_name} — NBA Data Spreadsheet</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/ag-grid-community@33.2.4/dist/ag-grid-community.min.js"
  onerror="document.getElementById('grid').textContent='AG Grid failed to load.'"></script>
<style>
  body {{ font-family: Inter, system-ui, sans-serif; margin: 0;
         padding: 16px; background: #fafafa; }}
  h1 {{ font-size: 1.25rem; color: #1D428A; margin: 0 0 12px; }}
  .toolbar {{ display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }}
  .toolbar button {{
    padding: 6px 16px; border: 1px solid #ddd; border-radius: 6px;
    background: #fff; cursor: pointer; font-size: 0.875rem;
  }}
  .toolbar button:hover, .toolbar button:focus-visible {{ background: #f0f0f0; }}
  #grid {{ height: calc(100vh - 100px); width: 100%; }}
  .ag-theme-alpine {{ --ag-font-family: Inter, system-ui, sans-serif; }}
</style>
</head>
<body>
<h1>{safe_name}</h1>
<div class="toolbar">
  <button onclick="exportCSV()">Export CSV</button>
  <button onclick="exportJSON()">Export JSON</button>
  <button onclick="resetData()">Reset</button>
  <span id="status" style="line-height:32px;color:#666;font-size:0.8rem;"></span>
</div>
<div id="grid" class="ag-theme-alpine"></div>
<script>
const originalData = {safe_rows};
const columnDefs = {safe_cols};
const gridOptions = {{
  columnDefs: columnDefs,
  rowData: JSON.parse(JSON.stringify(originalData)),
  defaultColDef: {{ resizable: true, editable: true, sortable: true, filter: true }},
  onCellValueChanged: () => document.getElementById("status").textContent = "Modified",
}};
const gridDiv = document.getElementById("grid");
const api = agGrid.createGrid(gridDiv, gridOptions);

function getRows() {{
  const rows = [];
  api.forEachNode(n => rows.push(n.data));
  return rows;
}}
function csvEscape(val) {{
  const s = String(val ?? "");
  return /[",\\n\\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}}
function exportCSV() {{
  const rows = getRows();
  const cols = columnDefs.map(c => c.field);
  const hdr = cols.map(csvEscape).join(",");
  const body = rows.map(r => cols.map(c => csvEscape(r[c])).join(","));
  const csv = [hdr, ...body].join("\\n");
  download(csv, "{safe_name}.csv", "text/csv");
}}
function exportJSON() {{
  download(JSON.stringify(getRows(), null, 2), "{safe_name}.json", "application/json");
}}
function resetData() {{
  api.setGridOption("rowData", JSON.parse(JSON.stringify(originalData)));
  document.getElementById("status").textContent = "Reset";
}}
function download(content, filename, type) {{
  const blob = new Blob([content], {{ type }});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}}
</script>
</body>
</html>"""
