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
        "common_player_info": 1,
        "defense_hub": 1,
        "franchise_leaders": 1,
        "franchise_players": 1,
        "player_awards": 1,
        "player_career_stats": 1,
        "player_dashboard_clutch": 1,
        "player_profile_v2": 2,
        "player_streak_finder": 2,
        "player_dash_game_splits": 1,
        "player_dash_general_splits": 1,
        "player_dash_last_n_games": 1,
        "player_dash_shooting_splits": 1,
        "player_dash_team_perf": 1,
        "player_dash_yoy": 1,
        "player_next_games": 1,
        "shot_chart_detail": 2,
        "team_details": 1,
        "team_info_common": 1,
        "team_historical_leaders": 1,
        "team_year_by_year": 1,
        "video_details_asset": 2,
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
        "common_player_info": 1.0,
        # Isolate flaky historical backfill surfaces so their failures do not
        # drag down the shared adaptive limiter for every other endpoint.
        "defense_hub": 1.0,
        "franchise_leaders": 1.0,
        "franchise_players": 1.0,
        "player_awards": 1.0,
        "player_career_stats": 1.0,
        "player_dashboard_clutch": 1.0,
        "player_profile_v2": 2.0,
        "player_streak_finder": 2.0,
        "player_dash_game_splits": 1.0,
        "player_dash_general_splits": 1.0,
        "player_dash_last_n_games": 1.0,
        "player_dash_shooting_splits": 1.0,
        "player_dash_team_perf": 1.0,
        "player_dash_yoy": 1.0,
        "player_next_games": 1.0,
        "shot_chart_detail": 1.5,
        "team_details": 1.0,
        "team_info_common": 1.0,
        "team_historical_leaders": 1.0,
        "team_year_by_year": 1.0,
        "video_details_asset": 2.0,
        "win_probability": 1.0,
    }
    endpoint_family_overrides: dict[str, str] = {
        "scoreboard_v2": "play_by_play",
        "scoreboard_v3": "play_by_play",
        "win_probability": "play_by_play",
        "common_player_info": "player_history",
        "player_awards": "player_history",
        "player_career_stats": "player_history",
        "player_compare": "player_history",
        "player_dashboard_clutch": "player_history",
        "player_dash_game_splits": "player_history",
        "player_dash_general_splits": "player_history",
        "player_dash_last_n_games": "player_history",
        "player_dash_shooting_splits": "player_history",
        "player_dash_team_perf": "player_history",
        "player_dash_yoy": "player_history",
        "player_next_games": "player_history",
        "player_profile_v2": "player_history",
        "player_streak_finder": "player_history",
        "shot_chart_detail": "player_history",
        "franchise_leaders": "team_history",
        "franchise_players": "team_history",
        "team_details": "team_history",
        "team_historical_leaders": "team_history",
        "team_info_common": "team_history",
        "team_year_by_year": "team_history",
        "video_details_asset": "player_history",
    }
    family_semaphore_limits: dict[str, int] = {
        "play_by_play": 4,
        "player_history": 2,
        "team_history": 2,
    }
    family_rate_limits: dict[str, float] = {
        "play_by_play": 4.0,
        "player_history": 2.0,
        "team_history": 2.0,
    }
    family_chunk_multipliers: dict[str, float] = {
        "default": 1.0,
        "box_score": 1.0,
        "play_by_play": 0.5,
        "player_history": 0.25,
        "team_history": 0.5,
    }
    endpoint_chunk_size_limits: dict[str, int] = {
        "video_details_asset": 10,
    }
    endpoint_retry_budgets: dict[str, int] = {
        "video_details_asset": 0,
    }
    zero_progress_abort_endpoints: set[str] = {
        "video_details_asset",
    }
    endpoint_request_timeouts: dict[str, int] = {
        "box_score_summary": 60,
        "box_score_summary_v3": 60,
        "box_score_usage": 60,
        "box_score_four_factors": 60,
        "box_score_hustle": 60,
        "common_player_info": 45,
        "defense_hub": 90,
        "franchise_leaders": 120,
        "franchise_players": 120,
        "player_awards": 120,
        "player_career_stats": 120,
        "player_dashboard_clutch": 120,
        "player_profile_v2": 150,
        "player_streak_finder": 150,
        "player_dash_game_splits": 120,
        "player_dash_general_splits": 120,
        "player_dash_last_n_games": 120,
        "player_dash_shooting_splits": 120,
        "player_dash_team_perf": 120,
        "player_dash_yoy": 120,
        "player_next_games": 120,
        "play_by_play": 60,
        "play_by_play_v2": 60,
        "shot_chart_detail": 180,
        "team_details": 120,
        "team_info_common": 180,
        "team_historical_leaders": 120,
        "team_year_by_year": 120,
        "video_details_asset": 15,
        "win_probability": 60,
    }
    adaptive_rate_min: float = 1.0  # minimum rate floor during adaptive backoff
    adaptive_rate_recovery: int = 50  # consecutive successes before rate recovery
    adaptive_chunk_min_size: int = 25
    adaptive_chunk_max_size: int = 1_000
    circuit_breaker_max_wait: float = 600.0  # cap breaker-open waiting before failing fast
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
