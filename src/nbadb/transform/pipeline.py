from __future__ import annotations

import contextlib
import importlib
import inspect
import pkgutil
import traceback
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, cast

import pandera.polars as pa
import polars as pl
from loguru import logger

from nbadb.transform.metrics import PipelineMetrics

if TYPE_CHECKING:
    import duckdb

    from nbadb.transform.base import BaseTransformer


@dataclass
class PipelineResult:
    """Captures pass/fail details from a pipeline run."""

    completed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    """List of (table_name, error_message) tuples for failed transformers."""
    skipped: list[str] = field(default_factory=list)
    """List of table names loaded from checkpoint (skipped re-computation)."""

    @property
    def success_count(self) -> int:
        return len(self.completed)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    @property
    def failed_tables(self) -> list[str]:
        return [t for t, _ in self.failed]


_INPUT_SCHEMA_ALIASES = {
    "stg_schedule": "stg_schedule_league_v2",
    "stg_standings": "stg_league_standings_v3",
    "stg_draft": "stg_draft_history",
    "stg_draft_combine": "stg_draft_combine_stats",
    "stg_synergy": "stg_synergy_play_types",
    "stg_box_score_traditional": "stg_box_score_traditional_player",
    "stg_box_score_advanced": "stg_box_score_advanced_player",
    "stg_box_score_hustle": "stg_box_score_hustle_player",
    "stg_box_score_defensive": "stg_box_score_defensive_player",
    "stg_play_by_play": "stg_play_by_play_v3",
    "stg_matchup": "stg_box_score_matchups",
    "stg_rotation_away": "stg_game_rotation",
    "stg_rotation_home": "stg_game_rotation",
    "stg_scoreboard": "stg_scoreboard_v2",
    "stg_shot_chart": "stg_shot_chart_detail",
    "stg_team_years": "stg_common_team_years",
    "stg_player_info": "raw_common_player_info",
    "stg_team_info": "raw_team_info_common",
    "stg_coaches": "raw_common_team_roster_coaches",
    "stg_franchise": "raw_franchise_history",
    "stg_box_score_misc": "raw_box_score_misc_player",
    "stg_box_score_scoring": "raw_box_score_scoring_player",
    "stg_box_score_usage": "raw_box_score_usage_player",
    "stg_playoff_picture_east": "raw_playoff_picture",
    "stg_playoff_picture_west": "raw_playoff_picture",
    "stg_draft_combine_drills": "raw_draft_combine_drill_results",
    "stg_draft_combine_nonstat_shooting": "raw_draft_combine_non_stationary_shooting",
    "stg_draft_combine_anthro": "raw_draft_combine_player_anthro",
}


def _table_name_from_schema_class(
    class_name: str,
    *,
    class_prefix: str = "",
    table_prefix: str = "",
) -> str:
    name = class_name.removesuffix("Schema").removesuffix("Model")
    if class_prefix:
        name = name.removeprefix(class_prefix)
    parts: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index > 0:
            parts.append("_")
        parts.append(char.lower())
    return f"{table_prefix}{''.join(parts)}"


def _discover_schema_map(
    package_name: str,
    *,
    class_prefix: str,
    table_prefix: str,
) -> dict[str, type[pa.DataFrameModel]]:
    try:
        schema_pkg = importlib.import_module(package_name)
    except ImportError:
        return {}

    schema_map: dict[str, type[pa.DataFrameModel]] = {}
    for _, module_name, _ in pkgutil.walk_packages(schema_pkg.__path__, prefix=f"{package_name}."):
        module = importlib.import_module(module_name)
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj.__module__ != module_name
                or not issubclass(obj, pa.DataFrameModel)
                or obj is pa.DataFrameModel
                or not name.endswith(("Schema", "Model"))
                or (class_prefix and not name.startswith(class_prefix))
            ):
                continue
            table_name = _table_name_from_schema_class(
                name,
                class_prefix=class_prefix,
                table_prefix=table_prefix,
            )
            schema_map[table_name] = obj
    return schema_map


@lru_cache(maxsize=1)
def _star_schema_map() -> dict[str, type[pa.DataFrameModel]]:
    return _discover_schema_map(
        "nbadb.schemas.star",
        class_prefix="",
        table_prefix="",
    )


@lru_cache(maxsize=1)
def _staging_schema_map() -> dict[str, type[pa.DataFrameModel]]:
    return _discover_schema_map(
        "nbadb.schemas.staging",
        class_prefix="Staging",
        table_prefix="stg_",
    )


@lru_cache(maxsize=1)
def _raw_schema_map() -> dict[str, type[pa.DataFrameModel]]:
    return _discover_schema_map(
        "nbadb.schemas.raw",
        class_prefix="Raw",
        table_prefix="raw_",
    )


def _input_schema_for(table: str) -> type[pa.DataFrameModel] | None:
    if schema_cls := _staging_schema_map().get(table):
        return schema_cls

    alias = _INPUT_SCHEMA_ALIASES.get(table)
    if alias is not None:
        if schema_cls := _staging_schema_map().get(alias):
            return schema_cls
        if schema_cls := _raw_schema_map().get(alias):
            return schema_cls

    if table.startswith("stg_"):
        raw_table = f"raw_{table.removeprefix('stg_')}"
        if schema_cls := _raw_schema_map().get(raw_table):
            return schema_cls

    return None


class TransformPipeline:
    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        run_id: str | None = None,
    ) -> None:
        self._conn = conn
        self._run_id = run_id or uuid.uuid4().hex
        self._transformers: list[BaseTransformer] = []
        self._outputs: dict[str, pl.DataFrame] = {}
        self._last_result: PipelineResult | None = None
        self._metrics = PipelineMetrics(run_id=self._run_id)

    @property
    def last_result(self) -> PipelineResult | None:
        """Access the pass/fail summary from the most recent run."""
        return self._last_result

    def register(self, transformer: BaseTransformer) -> None:
        self._transformers.append(transformer)

    def register_all(self, transformers: list[BaseTransformer]) -> None:
        self._transformers.extend(transformers)

    # ------------------------------------------------------------------
    # Checkpoint persistence
    # ------------------------------------------------------------------

    def _save_checkpoint(self, table: str, row_count: int) -> None:
        """Record a completed table in the checkpoint table."""
        try:
            self._conn.execute(
                "INSERT INTO _transform_checkpoints (run_id, table_name, row_count) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT (run_id, table_name) DO UPDATE "
                "SET completed_at = now(), row_count = EXCLUDED.row_count",
                [self._run_id, table, row_count],
            )
        except Exception:
            logger.debug(f"Checkpoint save failed for '{table}' (non-fatal)")

    def _load_checkpoint(self) -> set[str]:
        """Return set of table names completed in a prior run with this run_id."""
        try:
            rows = self._conn.execute(
                "SELECT table_name FROM _transform_checkpoints WHERE run_id = ?",
                [self._run_id],
            ).fetchall()
            return {row[0] for row in rows}
        except Exception:
            return set()

    def _clear_checkpoint(self) -> None:
        """Remove all checkpoint entries for this run_id (clean completion)."""
        try:
            self._conn.execute(
                "DELETE FROM _transform_checkpoints WHERE run_id = ?",
                [self._run_id],
            )
        except Exception:
            logger.debug("Checkpoint clear failed (non-fatal)")

    # ------------------------------------------------------------------
    # Core pipeline logic
    # ------------------------------------------------------------------

    def _topological_sort(self) -> list[BaseTransformer]:
        graph: dict[str, BaseTransformer] = {t.output_table: t for t in self._transformers}
        white, gray, black = 0, 1, 2
        color: dict[str, int] = {name: white for name in graph}
        order: list[BaseTransformer] = []

        def visit(name: str) -> None:
            if name not in color or color[name] == black:
                return
            if color[name] == gray:
                raise ValueError(f"Cyclic dependency detected involving '{name}'")
            color[name] = gray
            transformer = graph.get(name)
            if transformer:
                for dep in transformer.depends_on:
                    visit(dep)
                order.append(transformer)
            color[name] = black

        for name in graph:
            visit(name)
        return order

    @staticmethod
    def _validate_input_schema(table: str, df: pl.DataFrame) -> pl.DataFrame:
        schema_cls = _input_schema_for(table)
        if schema_cls is None:
            return df
        validated = schema_cls.validate(df)
        if not isinstance(validated, pl.DataFrame):
            raise TypeError(
                f"{schema_cls.__name__}.validate() returned {type(validated).__name__}, "
                "expected polars.DataFrame"
            )
        logger.debug("Validated input '{}' against {}", table, schema_cls.__name__)
        return validated

    def _prepare_staging(
        self,
        staging: dict[str, pl.LazyFrame],
        *,
        validate_input_schemas: bool = False,
    ) -> tuple[dict[str, pl.LazyFrame], set[str]]:
        """Validate and register staging tables into the shared DuckDB connection once.

        Returns the prepared staging mapping plus the set of staging keys that
        failed to validate/register so callers can skip dependent transforms.
        """
        prepared: dict[str, pl.LazyFrame] = {}
        failed: set[str] = set()
        for key, val in staging.items():
            try:
                data = cast("pl.DataFrame", val.collect())
                if validate_input_schemas:
                    data = self._validate_input_schema(key, data)
                prepared[key] = data.lazy()
                self._conn.register(key, data)
            except Exception as exc:
                failed.add(key)
                logger.error(
                    "Failed to prepare staging table '{}': {} — "
                    "transforms depending on it will be skipped",
                    key,
                    type(exc).__name__,
                )
        return prepared, failed

    @staticmethod
    def _validate_output_schema(table: str, df: pl.DataFrame) -> pl.DataFrame:
        schema_cls = _star_schema_map().get(table)
        if schema_cls is None:
            return df
        validated = schema_cls.validate(df)
        if not isinstance(validated, pl.DataFrame):
            raise TypeError(
                f"{schema_cls.__name__}.validate() returned {type(validated).__name__}, "
                "expected polars.DataFrame"
            )
        logger.debug("Validated '{}' against {}", table, schema_cls.__name__)
        return validated

    def run(
        self,
        staging: dict[str, pl.LazyFrame],
        *,
        resume: bool = False,
        validate_input_schemas: bool = False,
        validate_output_schemas: bool = True,
    ) -> dict[str, pl.DataFrame]:
        ordered = self._topological_sort()
        logger.info(f"Pipeline: {len(ordered)} transformers in dependency order")

        result = PipelineResult()
        self._last_result = result

        # Load checkpoint data when resuming
        checkpointed: set[str] = set()
        if resume:
            checkpointed = self._load_checkpoint()
            if checkpointed:
                logger.info(f"Checkpoint: {len(checkpointed)} tables from prior run")

        # DuckDB optimization: allow reordering for lower memory usage
        with contextlib.suppress(Exception):
            self._conn.execute("SET preserve_insertion_order = false")

        # INFRA-006: Register all staging tables ONCE before the transformer loop
        prepared_staging, failed_staging = self._prepare_staging(
            staging,
            validate_input_schemas=validate_input_schemas,
        )

        try:
            for transformer in ordered:
                table = transformer.output_table

                # Skip if any dependency failed to register
                missing_deps = failed_staging & set(transformer.depends_on)
                if missing_deps:
                    error_msg = f"missing staging: {', '.join(sorted(missing_deps))}"
                    logger.warning(f"Skipping {table}: {error_msg}")
                    result.failed.append((table, error_msg))
                    continue

                # Resume path: skip if already in memory outputs
                if resume and table in self._outputs:
                    logger.info(f"Skipping {table} (already completed)")
                    result.completed.append(table)
                    self._metrics.skip_transformer(table)
                    continue

                # Checkpoint resume: skip if table was checkpointed and exists in DuckDB
                if resume and table in checkpointed:
                    try:
                        df = self._conn.execute(f'SELECT * FROM "{table}"').pl()
                        if validate_output_schemas:
                            df = self._validate_output_schema(table, df)
                        self._outputs[table] = df
                        result.completed.append(table)
                        result.skipped.append(table)
                        self._metrics.skip_transformer(table)
                        logger.info(f"Skipping {table} (loaded from checkpoint)")
                        continue
                    except Exception as exc:
                        logger.warning(
                            "Checkpoint entry for '{}' could not be reused ({}), re-computing",
                            table,
                            type(exc).__name__,
                        )

                self._metrics.start_transformer(table)
                try:
                    transformer._conn = self._conn
                    # Build combined view: original staging + accumulated outputs
                    combined = {**prepared_staging}
                    for name, out_df in self._outputs.items():
                        combined[name] = out_df.lazy()
                    df = transformer.run(combined)
                    if validate_output_schemas:
                        df = self._validate_output_schema(table, df)
                except Exception as exc:
                    tb = traceback.format_exc()
                    error_msg = f"{type(exc).__name__}: {exc}"
                    self._metrics.fail_transformer(table, error_msg)
                    logger.error(
                        f"Transformer '{table}' failed "
                        f"({type(transformer).__name__}, "
                        f"depends_on={transformer.depends_on}, "
                        f"completed={result.success_count}/{len(ordered)}): "
                        f"{error_msg}\n{tb}"
                    )
                    result.failed.append((table, error_msg))
                    continue
                self._outputs[table] = df
                self._metrics.complete_transformer(table, df.shape[0], df.shape[1])
                # INFRA-006: Only register the NEW output from each completed transformer
                self._conn.register(table, df)
                result.completed.append(table)
                self._save_checkpoint(table, df.shape[0])
                logger.debug(f"Registered {table} in DuckDB ({df.shape[0]} rows)")

            # QUAL-005: Log summary of pass/fail counts
            logger.info(
                f"Pipeline finished: {result.success_count} passed, "
                f"{result.failure_count} failed out of {len(ordered)} transformers"
            )
            if result.failed:
                logger.warning(f"Failed transformers: {result.failed_tables}")

            # Finalize and persist metrics
            self._metrics.finalize()
            self._metrics.log_summary()
            with contextlib.suppress(Exception):
                self._metrics.persist(self._conn)

            # Clean run completed — clear checkpoint data
            if not result.failed:
                self._clear_checkpoint()
        finally:
            for t in self._transformers:
                t._conn = None

        return self._outputs

    def get_output(self, table: str) -> pl.DataFrame | None:
        return self._outputs.get(table)

    @property
    def execution_order(self) -> list[str]:
        return [t.output_table for t in self._topological_sort()]
