from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

import duckdb
import polars as pl
from loguru import logger

from nbadb.core.config import NbaDbSettings, get_settings
from nbadb.core.db import DBManager
from nbadb.core.types import validate_sql_identifier
from nbadb.extract.live.endpoints import (
    LiveBoxScoreExtractor,
    LiveOddsExtractor,
    LivePlayByPlayExtractor,
    LiveScoreBoardExtractor,
)
from nbadb.load.duckdb_loader import DuckDBLoader
from nbadb.load.multi import create_multi_loader
from nbadb.orchestrate.extractor_runner import _sync_extract, _sync_extract_all
from nbadb.orchestrate.transformers import discover_live_transformers
from nbadb.schemas.registry import get_input_schema
from nbadb.transform.pipeline import TransformPipeline

_LIVE_BOX_SCORE_STAGING_KEYS = [
    "stg_live_box_score_game_details",
    "stg_live_box_score_arena",
    "stg_live_box_score_officials",
    "stg_live_box_score_team_stats_home",
    "stg_live_box_score_team_stats_away",
    "stg_live_box_score_player_stats_home",
    "stg_live_box_score_player_stats_away",
]

_LIVE_RAW_SCHEMA_BY_STAGING_KEY = {
    "stg_live_score_board": "raw_live_score_board",
    "stg_live_odds": "raw_live_odds",
    "stg_live_play_by_play": "raw_live_play_by_play",
    "stg_live_box_score_game_details": "raw_live_box_score_game_details",
    "stg_live_box_score_arena": "raw_live_box_score_arena",
    "stg_live_box_score_officials": "raw_live_box_score_officials",
    "stg_live_box_score_team_stats_home": "raw_live_box_score_team_stats",
    "stg_live_box_score_team_stats_away": "raw_live_box_score_team_stats",
    "stg_live_box_score_player_stats_home": "raw_live_box_score_player_stats",
    "stg_live_box_score_player_stats_away": "raw_live_box_score_player_stats",
}


@dataclass(frozen=True, slots=True)
class LiveSnapshotResult:
    snapshot_at: datetime
    game_ids: list[str]
    staging_tables_persisted: int
    star_tables_loaded: int
    staging_rows_persisted: int
    star_rows_loaded: int


class LiveSnapshotWarehouse:
    """Dedicated append-only live snapshot warehouse path.

    This path deliberately avoids the historical journal and replace-style
    transform/load flow so repeated live snapshots for the same game can be
    persisted side-by-side.
    """

    def __init__(self, settings: NbaDbSettings | None = None) -> None:
        self._settings = settings if settings is not None else get_settings()

    @staticmethod
    def _coerce_snapshot_at(value: datetime | date | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)

    @staticmethod
    def _concat_frames(frames: list[pl.DataFrame]) -> pl.DataFrame:
        non_empty = [frame for frame in frames if not frame.is_empty()]
        if not non_empty:
            return frames[0] if frames else pl.DataFrame()
        if len(non_empty) == 1:
            return non_empty[0]
        return pl.concat(non_empty, how="diagonal_relaxed")

    @staticmethod
    def _ordered_game_ids(frame: pl.DataFrame) -> list[str]:
        if frame.is_empty or "game_id" not in frame.columns:
            return []
        seen: set[str] = set()
        ordered: list[str] = []
        for raw_game_id in frame.get_column("game_id").drop_nulls().to_list():
            game_id = str(raw_game_id)
            if game_id in seen:
                continue
            seen.add(game_id)
            ordered.append(game_id)
        return ordered

    @classmethod
    def _active_game_ids(cls, score_board: pl.DataFrame) -> list[str]:
        if score_board.is_empty:
            return []
        active_rows = score_board
        if "game_status" in score_board.columns:
            active_rows = score_board.filter(pl.col("game_status") == 2)
        return cls._ordered_game_ids(active_rows)

    @staticmethod
    def _filter_game_ids(frame: pl.DataFrame, game_ids: list[str]) -> pl.DataFrame:
        if frame.is_empty or not game_ids or "game_id" not in frame.columns:
            return frame
        return frame.filter(pl.col("game_id").cast(pl.Utf8).is_in(game_ids))

    @staticmethod
    def _schema_columns(table_name: str) -> list[str]:
        schema_cls = get_input_schema(table_name)
        if schema_cls is None:
            raise ValueError(f"No schema registered for {table_name}")
        return list(schema_cls.to_schema().columns)

    @classmethod
    def _conform_columns(cls, table_name: str, frame: pl.DataFrame) -> pl.DataFrame:
        columns = cls._schema_columns(table_name)
        missing = [column for column in columns if column not in frame.columns]
        if not missing:
            return frame
        return frame.with_columns([pl.lit(None).alias(column) for column in missing])

    @classmethod
    def _validate_frame(cls, table_name: str, frame: pl.DataFrame) -> pl.DataFrame:
        schema_cls = get_input_schema(table_name)
        if schema_cls is None:
            raise ValueError(f"No schema registered for {table_name}")
        return schema_cls.validate(cls._conform_columns(table_name, frame))

    def _extract_live_frames(
        self,
        *,
        snapshot_at: datetime,
        game_ids: list[str] | None,
    ) -> tuple[dict[str, pl.DataFrame], list[str]]:
        score_board = _sync_extract(LiveScoreBoardExtractor(), snapshot_at=snapshot_at)
        effective_game_ids = list(game_ids or self._active_game_ids(score_board))
        if not effective_game_ids and not game_ids:
            return {}, []

        score_board = self._filter_game_ids(score_board, effective_game_ids)
        odds = self._filter_game_ids(
            _sync_extract(LiveOddsExtractor(), snapshot_at=snapshot_at),
            effective_game_ids,
        )

        play_by_play_frames: list[pl.DataFrame] = []
        box_score_frames: dict[str, list[pl.DataFrame]] = {
            staging_key: [] for staging_key in _LIVE_BOX_SCORE_STAGING_KEYS
        }

        for game_id in effective_game_ids:
            play_by_play_frames.append(
                _sync_extract(
                    LivePlayByPlayExtractor(),
                    game_id=game_id,
                    snapshot_at=snapshot_at,
                )
            )
            live_box_score_packets = _sync_extract_all(
                LiveBoxScoreExtractor(),
                game_id=game_id,
                snapshot_at=snapshot_at,
            )
            for staging_key, frame in zip(
                _LIVE_BOX_SCORE_STAGING_KEYS,
                live_box_score_packets,
                strict=True,
            ):
                box_score_frames[staging_key].append(frame)

        raw_frames = {
            "stg_live_score_board": score_board,
            "stg_live_odds": odds,
            "stg_live_play_by_play": self._concat_frames(play_by_play_frames),
        }
        raw_frames.update(
            {
                staging_key: self._concat_frames(frames)
                for staging_key, frames in box_score_frames.items()
            }
        )
        return raw_frames, effective_game_ids

    def _validate_live_contracts(
        self,
        raw_frames: dict[str, pl.DataFrame],
    ) -> dict[str, pl.DataFrame]:
        validated: dict[str, pl.DataFrame] = {}
        for staging_key, frame in raw_frames.items():
            raw_table_name = _LIVE_RAW_SCHEMA_BY_STAGING_KEY[staging_key]
            raw_validated = self._validate_frame(raw_table_name, frame)
            validated[staging_key] = self._validate_frame(staging_key, raw_validated)
        return validated

    @staticmethod
    def _persist_staging_to_duckdb(
        db: DBManager,
        staging_frames: dict[str, pl.DataFrame],
    ) -> tuple[int, int]:
        persisted_tables = 0
        persisted_rows = 0
        for staging_key, frame in staging_frames.items():
            if frame.is_empty():
                continue
            safe_key = validate_sql_identifier(staging_key)
            db.duckdb.register("_live_snapshot_tmp", frame)
            try:
                try:
                    db.duckdb.execute(
                        f"INSERT INTO {safe_key} "
                        f"SELECT * FROM _live_snapshot_tmp EXCEPT ALL SELECT * FROM {safe_key}"
                    )
                except duckdb.CatalogException:
                    db.duckdb.execute(
                        f"CREATE TABLE {safe_key} AS SELECT * FROM _live_snapshot_tmp"
                    )
            finally:
                db.duckdb.unregister("_live_snapshot_tmp")
            persisted_tables += 1
            persisted_rows += frame.height
        return persisted_tables, persisted_rows

    def run(
        self,
        *,
        game_ids: list[str] | None = None,
        snapshot_at: datetime | date | None = None,
        load_mode: Literal["append"] = "append",
    ) -> LiveSnapshotResult:
        if load_mode != "append":
            raise ValueError("Live snapshot warehousing only supports append mode")

        snapshot_ts = self._coerce_snapshot_at(snapshot_at)
        with DBManager(
            sqlite_path=self._settings.sqlite_path,
            duckdb_path=self._settings.duckdb_path,
        ) as db:
            raw_frames, effective_game_ids = self._extract_live_frames(
                snapshot_at=snapshot_ts,
                game_ids=game_ids,
            )
            if not effective_game_ids and game_ids is None:
                logger.info("live snapshot skipped: no active live games")
                return LiveSnapshotResult(
                    snapshot_at=snapshot_ts,
                    game_ids=[],
                    staging_tables_persisted=0,
                    star_tables_loaded=0,
                    staging_rows_persisted=0,
                    star_rows_loaded=0,
                )
            staging_frames = self._validate_live_contracts(raw_frames)
            staging_tables_persisted, staging_rows_persisted = self._persist_staging_to_duckdb(
                db,
                staging_frames,
            )

            live_transformers = discover_live_transformers()
            if not live_transformers:
                raise RuntimeError("No live snapshot transformers were discovered")

            pipeline = TransformPipeline(db.duckdb)
            pipeline.register_all(live_transformers)
            outputs = pipeline.run(
                {key: frame.lazy() for key, frame in staging_frames.items()},
                validate_input_schemas=True,
            )

            loader = create_multi_loader(self._settings, duckdb_conn=db.duckdb)
            duckdb_loader = DuckDBLoader(db.duckdb)
            star_tables_loaded = 0
            star_rows_loaded = 0
            for table_name, frame in outputs.items():
                if frame.is_empty():
                    continue
                with contextlib.suppress(Exception):
                    db.duckdb.unregister(table_name)
                load_mode_for_table = (
                    "append"
                    if db.duckdb.execute(
                        (
                            "SELECT 1 FROM information_schema.tables "
                            "WHERE table_schema = 'main' "
                            "AND table_name = ? "
                            "AND table_type = 'BASE TABLE'"
                        ),
                        [table_name],
                    ).fetchone()
                    else "replace"
                )
                if load_mode_for_table == "append":
                    duckdb_loader.load(table_name, frame, mode="append")
                else:
                    loader.load(table_name, frame, mode="replace")
                star_tables_loaded += 1
                star_rows_loaded += frame.height
                logger.info("loaded live snapshot table {}: {} rows", table_name, frame.height)

        return LiveSnapshotResult(
            snapshot_at=snapshot_ts,
            game_ids=effective_game_ids,
            staging_tables_persisted=staging_tables_persisted,
            star_tables_loaded=star_tables_loaded,
            staging_rows_persisted=staging_rows_persisted,
            star_rows_loaded=star_rows_loaded,
        )
