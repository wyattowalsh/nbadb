"""Tests for tracing configuration and setup."""

from __future__ import annotations

import os

import pytest

from apps.chat.server.config import ChatSettings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove tracing env vars before each test."""
    for var in (
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_PROJECT",
        "LANGCHAIN_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
    ):
        monkeypatch.delenv(var, raising=False)


def test_config_tracing_defaults():
    """Default tracing provider is none."""
    settings = ChatSettings()
    assert settings.tracing_provider == "none"
    assert settings.langfuse_host is None
    assert settings.langfuse_public_key is None
    assert settings.langfuse_secret_key is None


def test_setup_tracing_none_returns_empty():
    """No tracing returns empty callback list."""
    from apps.chat.server.tracing import setup_tracing

    settings = ChatSettings(tracing_provider="none")
    callbacks = setup_tracing(settings)
    assert callbacks == []


def test_setup_tracing_langsmith_sets_env(monkeypatch):
    """LangSmith tracing sets env vars for auto-instrumentation."""
    from apps.chat.server.tracing import setup_tracing

    monkeypatch.setenv("LANGCHAIN_API_KEY", "test-key")
    settings = ChatSettings(tracing_provider="langsmith")
    callbacks = setup_tracing(settings)

    # LangSmith auto-instruments via env — no callback handlers returned
    assert callbacks == []
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGCHAIN_PROJECT"] == "nbadb-chat"


def test_setup_tracing_langsmith_warns_no_key():
    """LangSmith returns empty callbacks when LANGCHAIN_API_KEY is missing."""
    from apps.chat.server.tracing import setup_tracing

    settings = ChatSettings(tracing_provider="langsmith")
    callbacks = setup_tracing(settings)
    assert callbacks == []


def test_setup_tracing_langfuse_missing_package():
    """LangFuse returns empty callbacks when package is not installed."""
    from unittest.mock import patch

    settings = ChatSettings(
        tracing_provider="langfuse",
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
    )

    # Simulate langfuse not installed
    with patch.dict("sys.modules", {"langfuse": None, "langfuse.callback": None}):
        import importlib

        import apps.chat.server.tracing as tracing_mod

        importlib.reload(tracing_mod)
        callbacks = tracing_mod.setup_tracing(settings)

    assert callbacks == []


def test_setup_tracing_langfuse_warns_no_keys():
    """LangFuse returns empty callbacks when keys are not configured."""
    from apps.chat.server.tracing import setup_tracing

    settings = ChatSettings(tracing_provider="langfuse")
    callbacks = setup_tracing(settings)
    assert callbacks == []


def test_copilot_provider_raises_in_factory():
    """Copilot provider raises ValueError in factory (handled in agent.py)."""
    from apps.chat.server.providers.factory import create_chat_model

    settings = ChatSettings(
        provider="copilot",
        model="gpt-4.1",
    )
    with pytest.raises(ValueError, match="CopilotAgentWrapper"):
        create_chat_model(settings)


def test_copilot_backend_module_exists():
    """Copilot backend module exists and has required components."""
    content = (
        __import__("pathlib").Path(__file__).resolve().parents[3]
        / "apps"
        / "chat"
        / "server"
        / "copilot_backend.py"
    ).read_text()
    assert "class CopilotAgentWrapper" in content
    assert "async def astream" in content
    assert "define_tool" in content
    assert "run_sql" in content
    assert "run_python" in content
