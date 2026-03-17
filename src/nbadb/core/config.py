from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class NbaDbSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NBADB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("nbadb")
    log_dir: Path = Path("logs")

    formats: list[str] = ["sqlite", "duckdb", "csv", "parquet"]

    nba_base_url: str = "https://stats.nba.com/stats"

    semaphore_tiers: dict[str, int] = {
        "box_score": 10,
        "play_by_play": 5,
        "game_log": 20,
        "player_info": 15,
        "default": 10,
    }

    daily_lookback_days: int = 7
    pbp_chunk_size: int = 500
    default_chunk_size: int = 500
    thread_pool_size: int = 32
    rate_limit: float = 10.0  # max requests per second (global across all patterns)
    adaptive_rate_min: float = 1.0  # minimum rate floor during adaptive backoff
    adaptive_rate_recovery: int = 50  # consecutive successes before rate recovery
    extract_max_retries: int = 3  # per-extraction retry attempts for transient errors
    extract_retry_base_delay: float = 2.0  # base delay in seconds (exponential backoff)

    sqlite_path: Path | None = None
    duckdb_path: Path | None = None

    kaggle_dataset: str = "wyattowalsh/basketball"

    # ── proxy support (requires proxywhirl) ─────────────────
    proxy_enabled: bool = False
    proxy_urls: list[str] = Field(default=[], repr=False)
    proxy_user: str = Field(default="", repr=False)
    proxy_pass: str = Field(default="", repr=False)
    proxy_bootstrap: bool = True
    proxy_bootstrap_sample_size: int = 5
    proxy_strategy: str = "round_robin"
    proxy_timeout: int = 30
    proxy_max_retries: int = 3
    proxy_use_all_sources: bool = True
    proxy_semaphore_multiplier: float = 1.0

    @model_validator(mode="after")
    def _default_db_paths(self) -> NbaDbSettings:
        if self.sqlite_path is None:
            self.sqlite_path = self.data_dir / "nba.sqlite"
        if self.duckdb_path is None:
            self.duckdb_path = self.data_dir / "nba.duckdb"
        return self


@lru_cache(maxsize=1)
def get_settings() -> NbaDbSettings:
    return NbaDbSettings()
