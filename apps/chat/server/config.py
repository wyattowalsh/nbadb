from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (  # noqa: TC002 — needed at runtime by Pydantic
    AliasChoices,
    Field,
    SecretStr,
    model_validator,
)
from pydantic_settings import BaseSettings, JsonConfigSettingsSource, SettingsConfigDict


class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NBADB_CHAT_",
        json_file=Path("~/.nbadb/chat.json").expanduser(),
        json_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    provider: Literal[
        "openai", "anthropic", "google", "ollama", "lmstudio", "copilot", "custom"
    ] = "openai"
    api_key: SecretStr | None = None
    base_url: str | None = None
    model: str = "gpt-4.1"
    temperature: float = 0.1
    public_demo_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "NBADB_CHAT_PUBLIC_MODE",
            "NBADB_CHAT_PUBLIC_DEMO_MODE",
        ),
    )

    duckdb_path: Path = Path("~/.nbadb/data/nba.duckdb")

    @model_validator(mode="after")
    def _expand_paths(self) -> ChatSettings:
        object.__setattr__(self, "duckdb_path", self.duckdb_path.expanduser().resolve())
        return self

    extra_mcp_servers: dict[str, dict] = Field(default_factory=dict)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            JsonConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    # Tracing
    tracing_provider: Literal["none", "langsmith", "langfuse"] = "none"
    langfuse_host: str | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None


@lru_cache(maxsize=1)
def get_chat_settings() -> ChatSettings:
    """Return a cached ChatSettings instance.

    Intended for CLI entry points and non-Chainlit callers where a single
    global settings object is appropriate. Chainlit uses per-session
    ChatSettings() instances to support independent user configurations.
    """
    return ChatSettings()
