from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import polars as pl
from loguru import logger

_CAMEL_RE = re.compile(r'([a-z0-9])([A-Z])')


def _to_snake_case(name: str) -> str:
    """Convert any column name style to snake_case.

    Handles UPPER_SNAKE_CASE (e.g., GAME_ID -> game_id),
    camelCase (e.g., gameId -> game_id), and mixed cases.
    """
    return _CAMEL_RE.sub(r'\1_\2', name).lower()


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
        return df.rename({c: _to_snake_case(c) for c in df.columns})

    def _from_nba_api_multi(
        self, endpoint_cls: type, **kwargs: Any
    ) -> list[pl.DataFrame]:
        """Call nba_api endpoint returning multiple result sets."""
        result = endpoint_cls(**kwargs)
        dfs = result.get_data_frames()
        converted = []
        for pdf in dfs:
            df = pl.from_pandas(pdf, include_index=False)
            converted.append(df.rename({c: _to_snake_case(c) for c in df.columns}))
        return converted
