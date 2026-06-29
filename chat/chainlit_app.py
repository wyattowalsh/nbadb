from __future__ import annotations

import chainlit as cl

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
            "Ask a read-only question about the local nbadb DuckDB warehouse. "
            "I will show the answer first and keep SQL provenance attached to each result."
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
        record = runtime.promote_to_finding(prior, title=title, session_id=cl.context.session.id)
        await cl.Message(content=f"Saved finding: {record.title}").send()
        return

    response = runtime.ask(content, limit=25)
    cl.user_session.set("last_response", response)
    elements: list[cl.Element] = []
    if response.sql:
        elements.append(cl.Text(name="SQL", content=response.sql, display="side"))
    if response.rows:
        table = response.render_text().splitlines()
        elements.append(cl.Text(name="Rows", content="\n".join(table), display="inline"))

    await cl.Message(content=response.render_text(verbose=True), elements=elements).send()
