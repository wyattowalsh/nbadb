from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class CopilotChatModel(BaseChatModel):
    """LangChain chat model wrapping the GitHub Copilot SDK."""

    model_name: str = "gpt-4.1"
    temperature: float = 0.1

    @property
    def _llm_type(self) -> str:
        return "copilot"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "temperature": self.temperature}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return asyncio.run(self._agenerate(messages, stop=stop, **kwargs))

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        from copilot import CopilotClient

        client = CopilotClient()
        await client.start()
        try:
            session = await client.create_session({"model": self.model_name})
            # Convert LangChain messages to a single prompt
            prompt = "\n".join(
                f"{m.type}: {m.content}" for m in messages if isinstance(m.content, str)
            )
            response = await session.send_and_wait({"prompt": prompt})
            content = response.data.content if hasattr(response, "data") else str(response)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])
        finally:
            await session.disconnect()
            await client.stop()
