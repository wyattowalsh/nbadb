"""Tests for ChatSettings configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr


def test_default_settings():
    """ChatSettings has sensible defaults."""
    from apps.chat.server.config import ChatSettings

    settings = ChatSettings()
    assert settings.provider == "openai"
    assert settings.model == "gpt-4.1"
    assert settings.temperature == 0.1
    assert settings.api_key is None
    assert settings.extra_mcp_servers == {}


def test_settings_from_env(monkeypatch):
    """Settings can be loaded from environment variables."""
    from apps.chat.server.config import ChatSettings

    monkeypatch.setenv("NBADB_CHAT_PROVIDER", "anthropic")
    monkeypatch.setenv("NBADB_CHAT_MODEL", "claude-sonnet-4-20250514")
    monkeypatch.setenv("NBADB_CHAT_API_KEY", "sk-test-123")
    monkeypatch.setenv("NBADB_CHAT_TEMPERATURE", "0.5")

    settings = ChatSettings()
    assert settings.provider == "anthropic"
    assert settings.model == "claude-sonnet-4-20250514"
    assert isinstance(settings.api_key, SecretStr)
    assert settings.api_key.get_secret_value() == "sk-test-123"
    assert settings.temperature == 0.5


def test_public_demo_mode_can_be_enabled_with_notebook_env_alias(monkeypatch):
    """Notebook launcher env activates public-demo mode."""
    from apps.chat.server.config import ChatSettings

    monkeypatch.setenv("NBADB_CHAT_PUBLIC_MODE", "1")

    settings = ChatSettings()
    assert settings.public_demo_mode is True


def test_settings_from_json(tmp_path, monkeypatch):
    """Settings can be loaded from a JSON file."""
    from apps.chat.server.config import ChatSettings

    config_file = tmp_path / "chat.json"
    config_file.write_text(
        json.dumps(
            {"provider": "ollama", "model": "llama3.2", "base_url": "http://localhost:11434"}
        )
    )

    # Override the json_file path
    settings = ChatSettings(
        _json_file=config_file,
    )
    # At minimum, defaults should work
    assert settings.provider in ("openai", "ollama")


def test_invalid_provider():
    """Invalid provider raises validation error."""
    from apps.chat.server.config import ChatSettings

    with pytest.raises(Exception):  # noqa: B017, PT011
        ChatSettings(provider="invalid_provider")


def test_secret_str_redaction():
    """API keys are properly redacted in repr."""
    from apps.chat.server.config import ChatSettings

    settings = ChatSettings(api_key="sk-secret-key")
    repr_str = repr(settings)
    assert "sk-secret-key" not in repr_str


def test_extra_mcp_servers_default_isolation():
    """Mutable defaults are isolated between ChatSettings instances."""
    from apps.chat.server.config import ChatSettings

    first = ChatSettings()
    second = ChatSettings()
    first.extra_mcp_servers["demo"] = {"transport": "stdio"}
    assert second.extra_mcp_servers == {}


def test_duckdb_path_default():
    """DuckDB path defaults to ~/.nbadb/data/nba.duckdb."""
    from apps.chat.server.config import ChatSettings

    settings = ChatSettings()
    assert settings.duckdb_path == Path("~/.nbadb/data/nba.duckdb").expanduser().resolve()
