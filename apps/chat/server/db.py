from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path


def ensure_database(
    duckdb_path: Path,
    kaggle_dataset: str = "wyattowalsh/basketball",
) -> Path:
    """Ensure DuckDB file exists, downloading from Kaggle if missing."""
    if duckdb_path.exists():
        return duckdb_path

    logger.info(f"DuckDB not found at {duckdb_path}, downloading from Kaggle...")
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)

    from nbadb.kaggle.client import KaggleClient

    KaggleClient().download(target_dir=duckdb_path.parent)

    if not duckdb_path.exists():
        msg = f"Failed to download DuckDB to {duckdb_path}"
        raise FileNotFoundError(msg)

    return duckdb_path


def get_schema_context(duckdb_path: Path) -> str:
    """Build schema context string for the agent's system prompt."""
    from nbadb.agent.context import SchemaContext

    return SchemaContext(duckdb_path).build_prompt_context()
