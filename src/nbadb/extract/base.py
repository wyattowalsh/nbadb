from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import polars as pl
from loguru import logger

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_UPPER_TOKEN_RE = re.compile(r"^[A-Z0-9_]+$")

# nba_api kwargs that carry the season_type value (checked in priority order)
_SEASON_TYPE_KEYS = (
    "season_type_all_star",
    "season_type_playoffs",
    "season_type",
    "season_type_nullable",
    "season_type_all_star_nullable",
)


def _extract_season_type(kwargs: dict[str, Any]) -> str | None:
    """Extract the season_type value from nba_api kwargs.

    Returns the season_type string if found, None otherwise (e.g. game-level
    endpoints that don't use season_type).
    """
    for key in _SEASON_TYPE_KEYS:
        if key in kwargs:
            val = kwargs[key]
            return val if val else None
    return None


def _to_snake_case(name: str) -> str:
    """Convert any column name style to snake_case.

    Handles UPPER_SNAKE_CASE (e.g., GAME_ID -> game_id),
    all-uppercase nba_api stat shorthands (e.g., FG3M -> fg3m),
    camelCase (e.g., gameId -> game_id), and mixed cases.
    """
    if _UPPER_TOKEN_RE.fullmatch(name):
        return name.lower()
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


def _safe_from_pandas(pdf: Any) -> pl.DataFrame:
    """Convert pandas DataFrame to Polars, handling mixed-type columns.

    nba_api responses sometimes contain columns with mixed types (e.g.,
    int and None/str) that crash Arrow conversion. Falls back to coercing
    object-dtype columns to str.
    """
    try:
        return pl.from_pandas(pdf, include_index=False)
    except Exception:
        for col in pdf.columns:
            if pdf[col].dtype == object:
                pdf[col] = pdf[col].astype(str)
        return pl.from_pandas(pdf, include_index=False)


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
        We lowercase all column names at this boundary and inject a
        ``season_type`` column when the endpoint was queried with one.
        """
        season_type = _extract_season_type(kwargs)
        self._inject_proxy(kwargs)
        result = endpoint_cls(**kwargs)
        dfs = result.get_data_frames()
        if not dfs:
            logger.warning(f"{self.endpoint_name}: no data frames returned")
            return pl.DataFrame()
        df = _safe_from_pandas(dfs[0])
        df = df.rename({c: _to_snake_case(c) for c in df.columns})
        if season_type and "season_type" not in df.columns:
            df = df.with_columns(pl.lit(season_type).alias("season_type"))
        return df

    def _from_nba_api_multi(self, endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        """Call nba_api endpoint returning multiple result sets.

        Injects ``season_type`` column into each result set when applicable.
        """
        season_type = _extract_season_type(kwargs)
        self._inject_proxy(kwargs)
        result = endpoint_cls(**kwargs)
        dfs = result.get_data_frames()
        converted = []
        for pdf in dfs:
            df = _safe_from_pandas(pdf)
            df = df.rename({c: _to_snake_case(c) for c in df.columns})
            if season_type and "season_type" not in df.columns:
                df = df.with_columns(pl.lit(season_type).alias("season_type"))
            converted.append(df)
        return converted

    @staticmethod
    def _live_payload_to_frame(payload: Any) -> pl.DataFrame:
        if hasattr(payload, "get_dict"):
            payload = payload.get_dict()
        elif hasattr(payload, "data"):
            payload = payload.data

        if payload is None:
            return pl.DataFrame()
        if isinstance(payload, dict):
            records: list[dict[str, Any]] = [payload]
        elif isinstance(payload, list):
            if not payload:
                return pl.DataFrame()
            if isinstance(payload[0], dict):
                records = payload
            else:
                return pl.DataFrame({"value": payload})
        else:
            return pl.DataFrame({"value": [payload]})

        df = pl.from_dicts(records)
        return df.rename({c: _to_snake_case(c) for c in df.columns})

    def _from_nba_live(self, endpoint_cls: type, attr: str, **kwargs: Any) -> pl.DataFrame:
        """Call nba_api live endpoint and convert a single dataset to Polars."""
        self._inject_proxy(kwargs)
        result = endpoint_cls(**kwargs)
        dataset = getattr(result, attr, None)
        if dataset is None:
            logger.warning(f"{self.endpoint_name}: live dataset {attr!r} was not returned")
            return pl.DataFrame()
        return self._live_payload_to_frame(dataset)

    def _from_nba_live_multi(
        self,
        endpoint_cls: type,
        attrs: list[str],
        **kwargs: Any,
    ) -> list[pl.DataFrame]:
        """Call nba_api live endpoint and convert multiple datasets to Polars."""
        self._inject_proxy(kwargs)
        result = endpoint_cls(**kwargs)
        frames: list[pl.DataFrame] = []
        for attr in attrs:
            dataset = getattr(result, attr, None)
            if dataset is None:
                logger.warning(f"{self.endpoint_name}: live dataset {attr!r} was not returned")
                frames.append(pl.DataFrame())
                continue
            frames.append(self._live_payload_to_frame(dataset))
        return frames
