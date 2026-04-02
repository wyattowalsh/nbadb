"""Database utilities for the chat app.

Inlines minimal logic from nbadb.kaggle.client and nbadb.agent.context
to avoid pulling the full nbadb dependency chain (sqlalchemy, polars, etc.)
which conflicts with chainlit's aiofiles version cap.
"""

from __future__ import annotations

import re
import shutil
from functools import lru_cache
from pathlib import Path

import duckdb
from loguru import logger


def ensure_database(
    duckdb_path: Path,
    kaggle_dataset: str = "wyattowalsh/basketball",
) -> Path:
    """Ensure DuckDB file exists, downloading from Kaggle if missing."""
    if duckdb_path.exists():
        return duckdb_path

    logger.info(f"DuckDB not found at {duckdb_path}, downloading from Kaggle...")
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import kagglehub
    except ImportError:
        msg = "kagglehub is required for first-run data download. Install it with: uv add kagglehub"
        raise ImportError(msg) from None

    download_path = kagglehub.dataset_download(kaggle_dataset)
    download_dir = Path(download_path)

    # Check for DuckDB file first
    duckdb_files = list(download_dir.glob("*.duckdb"))
    if duckdb_files:
        shutil.copy2(duckdb_files[0], duckdb_path)
        logger.info(f"Copied DuckDB to {duckdb_path}")
        return duckdb_path

    # Kaggle dataset is SQLite — convert to DuckDB
    sqlite_files = list(download_dir.glob("*.sqlite"))
    if not sqlite_files:
        msg = f"No .duckdb or .sqlite file found in Kaggle download at {download_path}"
        raise FileNotFoundError(msg)

    sqlite_path = sqlite_files[0]
    logger.info(f"Converting {sqlite_path.name} to DuckDB...")
    with duckdb.connect(str(duckdb_path)) as conn:
        safe_path = str(sqlite_path).replace("'", "''")
        conn.execute(f"ATTACH '{safe_path}' AS sqlite_db (TYPE sqlite, READ_ONLY)")
        # Copy all tables from SQLite to DuckDB
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'sqlite_db'"
        ).fetchall()
        for (table_name,) in tables:
            if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
                logger.warning(f"Skipping suspicious table name: {table_name!r}")
                continue
            conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM sqlite_db."{table_name}"')
        conn.execute("DETACH sqlite_db")
    logger.info(f"Converted {len(tables)} tables to DuckDB at {duckdb_path}")

    if not duckdb_path.exists():
        msg = f"Failed to download DuckDB to {duckdb_path}"
        raise FileNotFoundError(msg)

    return duckdb_path


@lru_cache(maxsize=4)
def get_schema_context(duckdb_path: Path) -> str:
    """Build compact schema context for the agent's system prompt.

    Full column details for analytics/agg/dim tables (commonly queried).
    Names-only for fact tables (use describe_table for details).
    """
    lines = ["Available tables and columns:\n"]
    with duckdb.connect(str(duckdb_path), read_only=True) as conn:
        tables = conn.execute(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()

        # Group tables by prefix
        detail_prefixes = ("analytics_", "agg_", "dim_")
        detail_tables = []
        summary_tables = []
        for (name,) in tables:
            if name.startswith(detail_prefixes):
                detail_tables.append(name)
            else:
                summary_tables.append(name)

        # Full column details for analytics/agg/dim
        for table_name in detail_tables:
            lines.append(f"\n{table_name}:")
            columns = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ? "
                "ORDER BY ordinal_position",
                [table_name],
            ).fetchall()
            for col_name, data_type in columns:
                lines.append(f"  - {col_name} ({data_type})")

        # Names-only for fact/bridge tables (use describe_table for details)
        if summary_tables:
            lines.append("\n\nFact tables (use describe_table for columns):")
            for name in summary_tables:
                lines.append(f"  - {name}")

    return "\n".join(lines)
