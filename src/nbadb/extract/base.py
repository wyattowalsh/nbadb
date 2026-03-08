from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import polars as pl
from loguru import logger

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")


def _to_snake_case(name: str) -> str:
    """Convert any column name style to snake_case.

    Handles UPPER_SNAKE_CASE (e.g., GAME_ID -> game_id),
    camelCase (e.g., gameId -> game_id), and mixed cases.
    """
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


class BaseExtractor(ABC):
    endpoint_name: ClassVar[str]
    category: ClassVar[str] = "default"

    # Set by ExtractorRunner / EntityDiscovery before calling extract()
    _proxy_url: str | None = None

    @abstractmethod
    async def extract(self, **params: Any) -> pl.DataFrame: ...

    def _inject_proxy(self, kwargs: dict[str, Any]) -> None:
        """Add timeout/proxy kwargs for nba_api endpoint calls.

        - If NBADB_REQUEST_TIMEOUT is set, apply it to all calls unless a
          timeout was explicitly provided.
        - If a proxy URL is configured, inject proxy and preserve the prior
          default timeout behavior (60s) when no timeout is present.
        """
        timeout_override = os.getenv("NBADB_REQUEST_TIMEOUT")
        if timeout_override and "timeout" not in kwargs:
            try:
                kwargs["timeout"] = int(timeout_override)
            except ValueError:
                logger.warning("invalid NBADB_REQUEST_TIMEOUT={!r}; ignoring", timeout_override)

        if self._proxy_url is not None:
            kwargs.setdefault("proxy", self._proxy_url)
            kwargs.setdefault("timeout", 60)

    def _from_nba_api(self, endpoint_cls: type, **kwargs: Any) -> pl.DataFrame:
        """Call nba_api endpoint and convert to Polars DataFrame.

        nba_api returns pandas DataFrames with UPPERCASE columns.
        We lowercase all column names at this boundary.
        """
        self._inject_proxy(kwargs)
        result = endpoint_cls(**kwargs)
        dfs = result.get_data_frames()
        if not dfs:
            logger.warning(f"{self.endpoint_name}: no data frames returned")
            return pl.DataFrame()
        df = pl.from_pandas(dfs[0], include_index=False)
        return df.rename({c: _to_snake_case(c) for c in df.columns})

    def _from_nba_api_multi(self, endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        """Call nba_api endpoint returning multiple result sets."""
        self._inject_proxy(kwargs)
        result = endpoint_cls(**kwargs)
        dfs = result.get_data_frames()
        converted = []
        for pdf in dfs:
            df = pl.from_pandas(pdf, include_index=False)
            converted.append(df.rename({c: _to_snake_case(c) for c in df.columns}))
        return converted
