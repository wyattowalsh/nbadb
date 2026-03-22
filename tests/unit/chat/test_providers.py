"""Tests for the provider factory.

These tests require langchain provider packages to be installed.
They're skipped when running from the main nbadb venv.
"""

from __future__ import annotations

import importlib

import pytest

_has_langchain_openai = importlib.util.find_spec("langchain_openai") is not None
_has_langchain_anthropic = importlib.util.find_spec("langchain_anthropic") is not None
_has_langchain_google = importlib.util.find_spec("langchain_google_genai") is not None
_has_langchain_ollama = importlib.util.find_spec("langchain_ollama") is not None

skip_no_openai = pytest.mark.skipif(
    not _has_langchain_openai, reason="langchain-openai not installed",
)
skip_no_anthropic = pytest.mark.skipif(
    not _has_langchain_anthropic, reason="langchain-anthropic not installed",
)
skip_no_google = pytest.mark.skipif(
    not _has_langchain_google, reason="langchain-google-genai not installed",
)
skip_no_ollama = pytest.mark.skipif(
    not _has_langchain_ollama, reason="langchain-ollama not installed",
)


@skip_no_openai
def test_factory_openai():
    """OpenAI provider creates ChatOpenAI."""
    from apps.chat.server.config import ChatSettings
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(provider="openai", api_key="sk-test", model="gpt-4o")
    model = create_chat_model(settings)

    from langchain_openai import ChatOpenAI

    assert isinstance(model, ChatOpenAI)


@skip_no_anthropic
def test_factory_anthropic():
    """Anthropic provider creates ChatAnthropic."""
    from apps.chat.server.config import ChatSettings
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(
        provider="anthropic", api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
    )
    model = create_chat_model(settings)

    from langchain_anthropic import ChatAnthropic

    assert isinstance(model, ChatAnthropic)


@skip_no_ollama
def test_factory_ollama():
    """Ollama provider creates ChatOllama."""
    from apps.chat.server.config import ChatSettings
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(provider="ollama", model="llama3.2")
    model = create_chat_model(settings)

    from langchain_ollama import ChatOllama

    assert isinstance(model, ChatOllama)


@skip_no_openai
def test_factory_lmstudio():
    """LM Studio provider creates ChatOpenAI with custom base_url."""
    from apps.chat.server.config import ChatSettings
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(provider="lmstudio", model="local-model")
    model = create_chat_model(settings)

    from langchain_openai import ChatOpenAI

    assert isinstance(model, ChatOpenAI)


@skip_no_openai
def test_factory_custom_with_base_url():
    """Custom provider uses ChatOpenAI with user-specified base_url."""
    from apps.chat.server.config import ChatSettings
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(
        provider="custom",
        api_key="test-key",
        base_url="http://my-server:8080/v1",
        model="my-model",
    )
    model = create_chat_model(settings)

    from langchain_openai import ChatOpenAI

    assert isinstance(model, ChatOpenAI)


@pytest.mark.skipif(
    importlib.util.find_spec("copilot") is None,
    reason="github-copilot-sdk not installed",
)
def test_factory_copilot():
    """Copilot provider creates CopilotChatModel."""
    from apps.chat.server.config import ChatSettings
    from apps.chat.server.providers.copilot_adapter import CopilotChatModel
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(provider="copilot", model="gpt-4.1")
    model = create_chat_model(settings)

    assert isinstance(model, CopilotChatModel)


def test_factory_unknown_provider():
    """Unknown provider raises ValueError."""
    from apps.chat.server.config import ChatSettings
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(provider="openai")
    settings.provider = "nonexistent"  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Unknown provider"):
        create_chat_model(settings)


@skip_no_google
def test_factory_google():
    """Google provider creates ChatGoogleGenerativeAI."""
    from apps.chat.server.config import ChatSettings
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(
        provider="google", api_key="google-key", model="gemini-2.5-pro",
    )
    model = create_chat_model(settings)

    from langchain_google_genai import ChatGoogleGenerativeAI

    assert isinstance(model, ChatGoogleGenerativeAI)
