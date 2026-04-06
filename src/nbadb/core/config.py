from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class NbaDbSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NBADB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("data/nbadb")
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
    endpoint_semaphore_limits: dict[str, int] = {
        "scoreboard_v2": 1,
        "scoreboard_v3": 1,
        "box_score_summary": 2,
        "box_score_summary_v3": 2,
        "box_score_usage": 2,
        "box_score_four_factors": 2,
        "box_score_hustle": 2,
        "win_probability": 1,
    }
    discovery_concurrency: int = 2

    daily_lookback_days: int = 7
    pbp_chunk_size: int = 500
    default_chunk_size: int = 500
    thread_pool_size: int = 32
    rate_limit: float = 10.0  # shared requests/second cap for non-isolated endpoints
    endpoint_rate_limits: dict[str, float] = {
        "scoreboard_v2": 2.0,
        "scoreboard_v3": 2.0,
        "box_score_summary": 3.0,
        "box_score_summary_v3": 3.0,
        "box_score_usage": 3.0,
        "box_score_four_factors": 3.0,
        "box_score_hustle": 2.0,
        "win_probability": 1.5,
    }
    endpoint_request_timeouts: dict[str, int] = {
        "box_score_summary": 60,
        "box_score_summary_v3": 60,
        "box_score_usage": 60,
        "box_score_four_factors": 60,
        "box_score_hustle": 60,
        "play_by_play": 60,
        "play_by_play_v2": 60,
        "win_probability": 60,
    }
    adaptive_rate_min: float = 1.0  # minimum rate floor during adaptive backoff
    adaptive_rate_recovery: int = 50  # consecutive successes before rate recovery
    extract_max_retries: int = 6  # per-extraction retry attempts
    extract_retry_base_delay: float = 2.0  # base delay in seconds (exponential backoff)

    sqlite_path: Path | None = None
    duckdb_path: Path | None = None

    kaggle_dataset: str = "wyattowalsh/basketball"

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
