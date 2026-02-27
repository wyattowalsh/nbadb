from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

from nbadb.load.base import BaseLoader

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl


class CSVLoader(BaseLoader):
    def __init__(self, csv_dir: Path) -> None:
        self.csv_dir = csv_dir

    def load(
        self,
        table: str,
        df: pl.DataFrame,
        mode: Literal["replace", "append"] = "replace",
    ) -> None:
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.csv_dir / f"{table}.csv"
        df.write_csv(output_path)
        logger.debug(
            f"CSV: wrote {df.shape[0]} rows to {output_path.name}"
        )
