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

    # ── strategic migration scaffolding (placeholders only) ─────────
    strategic_track_ingestion_v2_enabled: bool = False
    strategic_track_storage_v2_enabled: bool = False
    strategic_track_schema_v2_enabled: bool = False
    strategic_track_serving_v2_enabled: bool = False
    strategic_phase_1_shadow_mode_enabled: bool = False
    strategic_phase_2_dual_write_enabled: bool = False

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
