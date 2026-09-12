from __future__ import annotations

import asyncio

import chainlit as cl

from nbadb.chat.artifacts import ArtifactStoreError
from nbadb.chat.runtime import ChatRuntime, build_runtime


@cl.on_chat_start
async def on_chat_start() -> None:
    try:
        runtime = build_runtime()
    except RuntimeError as exc:
        cl.user_session.set("runtime_error", str(exc))
        await cl.Message(content=f"Chat startup failed: {exc}").send()
        return

    cl.user_session.set("runtime", runtime)
    await cl.Message(
        content=(
            "Ask a **catalog** question about the local nbadb DuckDB warehouse.\n\n"
            "Examples:\n"
            "- team pace leaders\n"
            "- team stats for 2024-25\n"
            "- clutch stats for 2024-25\n"
            "- franchise championships\n\n"
            "Use `/save <title>` to store the last successful result as a finding. "
            "SQL provenance is attached when a route matches."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    runtime_error = cl.user_session.get("runtime_error")
    if runtime_error:
        await cl.Message(content=f"Chat is unavailable: {runtime_error}").send()
        return

    runtime = cl.user_session.get("runtime")
    if not isinstance(runtime, ChatRuntime):
        await cl.Message(
            content="Chat runtime is not initialized. Restart the session and try again."
        ).send()
        return

    content = message.content.strip()
    if content.casefold().startswith("/save"):
        title = content[5:].strip() or "Saved finding"
        prior = cl.user_session.get("last_response")
        if prior is None:
            await cl.Message(content="No prior query result to save. Ask a question first.").send()
            return
        try:
            record = runtime.promote_to_finding(
                prior,
                title=title,
                session_id=cl.context.session.id,
            )
        except (ArtifactStoreError, ValueError) as exc:
            await cl.Message(content=f"Finding was not saved: {exc}").send()
            return
        await cl.Message(content=f"Saved finding: {record.title}").send()
        return

    # DuckDB work is blocking; run it off the event loop so other sessions
    # stay responsive while this query executes.
    response = await asyncio.to_thread(runtime.ask, content, limit=25)
    if response.ok:
        cl.user_session.set("last_response", response)
    elements: list[cl.Element] = []
    if response.sql:
        elements.append(cl.Text(name="SQL", content=response.sql, display="side"))

    answer = response.render_text()
    if response.warnings:
        answer += "\n\n" + "\n".join(f"Warning: {warning}" for warning in response.warnings)
    await cl.Message(content=answer, elements=elements).send()
