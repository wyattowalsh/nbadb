from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from apps.chat.server.config import ChatSettings


def create_chat_model(settings: ChatSettings) -> BaseChatModel:
    """Create a LangChain chat model from settings."""
    match settings.provider:
        case "openai" | "custom":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=settings.model,
                api_key=settings.api_key.get_secret_value() if settings.api_key else None,
                base_url=settings.base_url,
                temperature=settings.temperature,
            )
        case "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=settings.model,
                api_key=settings.api_key.get_secret_value() if settings.api_key else None,
                temperature=settings.temperature,
            )
        case "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=settings.model,
                google_api_key=settings.api_key.get_secret_value() if settings.api_key else None,
                temperature=settings.temperature,
            )
        case "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=settings.model,
                base_url=settings.base_url or "http://localhost:11434",
                temperature=settings.temperature,
            )
        case "lmstudio":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=settings.model,
                api_key="not-needed",
                base_url=settings.base_url or "http://localhost:1234/v1",
                temperature=settings.temperature,
            )
        case "copilot":
            from apps.chat.server.providers.copilot_adapter import CopilotChatModel

            return CopilotChatModel(
                model_name=settings.model,
                temperature=settings.temperature,
            )
        case _:
            msg = f"Unknown provider: {settings.provider}"
            raise ValueError(msg)
