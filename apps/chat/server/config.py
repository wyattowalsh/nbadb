from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr  # noqa: TC002 — needed at runtime by Pydantic
from pydantic_settings import BaseSettings, SettingsConfigDict


class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NBADB_CHAT_",
        json_file=Path("~/.nbadb/chat.json").expanduser(),
        json_file_encoding="utf-8",
        extra="ignore",
    )

    provider: Literal[
        "openai", "anthropic", "google", "ollama", "lmstudio", "copilot", "custom"
    ] = "openai"
    api_key: SecretStr | None = None
    base_url: str | None = None
    model: str = "gpt-4o"
    temperature: float = 0.1

    duckdb_path: Path = Path("~/.nbadb/data/nba.duckdb")

    sandbox: Literal["local", "e2b"] = "local"
    e2b_api_key: SecretStr | None = None

    extra_mcp_servers: dict[str, dict] = {}


@lru_cache(maxsize=1)
def get_chat_settings() -> ChatSettings:
    return ChatSettings()
