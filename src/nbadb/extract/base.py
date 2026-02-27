from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import polars as pl
from loguru import logger


class BaseExtractor(ABC):
    endpoint_name: ClassVar[str]
    category: ClassVar[str] = "default"

    @abstractmethod
    async def extract(self, **params: Any) -> pl.DataFrame:
        ...

    def _from_nba_api(self, endpoint_cls: type, **kwargs: Any) -> pl.DataFrame:
        """Call nba_api endpoint and convert to Polars DataFrame.

        nba_api returns pandas DataFrames with UPPERCASE columns.
        We lowercase all column names at this boundary.
        """
        result = endpoint_cls(**kwargs)
        dfs = result.get_data_frames()
        if not dfs:
            logger.warning(f"{self.endpoint_name}: no data frames returned")
            return pl.DataFrame()
        df = pl.from_pandas(dfs[0], include_index=False)
        return df.rename({c: c.lower() for c in df.columns})

    def _from_nba_api_multi(
        self, endpoint_cls: type, **kwargs: Any
    ) -> list[pl.DataFrame]:
        """Call nba_api endpoint returning multiple result sets."""
        result = endpoint_cls(**kwargs)
        dfs = result.get_data_frames()
        return [
            pl.from_pandas(df, include_index=False).rename(
                {c: c.lower() for c in pl.from_pandas(df, include_index=False).columns}
            )
            for df in dfs
        ]
