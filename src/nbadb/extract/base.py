from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, time
from typing import Any, ClassVar

import pandas as pd
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

_RETRYABLE_ERROR_NAMES = frozenset(
    {
        "ReadTimeout",
        "ConnectTimeout",
        "ConnectionError",
        "ConnectionResetError",
        "SSLError",
        "JSONDecodeError",
        "ChunkedEncodingError",
        "RemoteDisconnected",
        "KeyError",
        "ArrowTypeError",
    }
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


def is_retryable_error(exc: Exception) -> bool:
    """Return True if *exc* looks transient and worth retrying."""
    return type(exc).__name__ in _RETRYABLE_ERROR_NAMES


def _coerce_snapshot_at(value: object | None) -> datetime:
    """Normalize snapshot inputs to a timezone-aware UTC datetime."""
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    raise TypeError(f"snapshot_at must be a date or datetime, got {type(value).__name__}")


def _safe_from_pandas(pdf: Any) -> pl.DataFrame:
    """Convert pandas DataFrame to Polars, handling mixed-type columns.

    nba_api responses sometimes contain columns with mixed types (e.g.,
    int and None/str) that crash Arrow conversion. Falls back to coercing
    object-dtype columns to str, but logs which columns were affected.
    """
    try:
        return pl.from_pandas(pdf, nan_to_null=True, include_index=False)
    except Exception:
        coerced: list[str] = []
        for col in pdf.columns:
            if pdf[col].dtype == object:
                try:
                    pdf[col] = pd.to_numeric(pdf[col], errors="coerce")
                    coerced.append(col)
                except (ValueError, TypeError):
                    pdf[col] = pdf[col].astype(str)
                    coerced.append(col)
        if coerced:
            logger.warning(
                "mixed-type columns coerced during Arrow fallback: {}",
                ", ".join(coerced),
            )
        return pl.from_pandas(pdf, nan_to_null=True, include_index=False)


class BaseExtractor(ABC):
    endpoint_name: ClassVar[str]
    category: ClassVar[str] = "default"
    _request_timeout_override: int | None = None

    @abstractmethod
    async def extract(self, **params: Any) -> pl.DataFrame: ...

    def _inject_timeout(self, kwargs: dict[str, Any]) -> None:
        """Apply timeout override for nba_api endpoint calls.

        Per-endpoint overrides set by the runner take precedence over the
        global NBADB_REQUEST_TIMEOUT environment variable.
        """
        if "timeout" in kwargs:
            return
        timeout_override: int | str | None = self._request_timeout_override
        if timeout_override is None:
            timeout_override = os.getenv("NBADB_REQUEST_TIMEOUT")
        if timeout_override is None:
            return
        try:
            kwargs["timeout"] = int(timeout_override)
        except (TypeError, ValueError):
            logger.warning("invalid request timeout override={!r}; ignoring", timeout_override)

    def _call_nba_api(self, endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        """Call nba_api endpoint and return all result sets as Polars DataFrames.

        Handles timeout injection, column snake_case normalization, and
        ``season_type`` column injection.  Shared by both single and
        multi-result helpers.
        """
        season_type = _extract_season_type(kwargs)
        self._inject_timeout(kwargs)
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

    def _from_nba_api(self, endpoint_cls: type, **kwargs: Any) -> pl.DataFrame:
        """Call nba_api endpoint and convert to Polars DataFrame.

        nba_api returns pandas DataFrames with UPPERCASE columns.
        We lowercase all column names at this boundary and inject a
        ``season_type`` column when the endpoint was queried with one.
        """
        converted = self._call_nba_api(endpoint_cls, **kwargs)
        if not converted:
            logger.warning(f"{self.endpoint_name}: no data frames returned")
            return pl.DataFrame()
        return converted[0]

    def _from_nba_api_multi(self, endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        """Call nba_api endpoint returning multiple result sets.

        Injects ``season_type`` column into each result set when applicable.
        """
        return self._call_nba_api(endpoint_cls, **kwargs)

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

        serialized_records = [json.dumps(record, sort_keys=True, default=str) for record in records]
        df = pl.from_dicts(records)
        df = df.rename({c: _to_snake_case(c) for c in df.columns})
        return df.with_columns(pl.Series("payload_json", serialized_records))

    @staticmethod
    def _apply_live_snapshot_contract(
        df: pl.DataFrame,
        *,
        source_endpoint: str,
        natural_keys: tuple[str, ...],
        snapshot_at: datetime,
        params: dict[str, Any],
    ) -> pl.DataFrame:
        missing: list[str] = []
        expressions: list[pl.Expr] = []

        for key in natural_keys:
            if key in df.columns:
                continue
            if key in params:
                expressions.append(pl.lit(params[key]).alias(key))
                continue
            if df.is_empty():
                expressions.append(pl.lit(None).alias(key))
                continue
            missing.append(key)

        if missing:
            missing_keys = ", ".join(missing)
            raise ValueError(
                f"{source_endpoint}: live payload missing required natural keys: {missing_keys}"
            )

        expressions.extend(
            [
                pl.lit(snapshot_at).alias("snapshot_at"),
                pl.lit(snapshot_at.date()).alias("snapshot_date"),
                pl.lit(source_endpoint).alias("source_endpoint"),
            ]
        )
        if "payload_json" not in df.columns:
            expressions.append(pl.lit(None).alias("payload_json"))
        return df.with_columns(expressions)

    def _from_nba_live(
        self,
        endpoint_cls: type,
        attr: str,
        *,
        source_endpoint: str,
        natural_keys: tuple[str, ...],
        **kwargs: Any,
    ) -> pl.DataFrame:
        """Call nba_api live endpoint and convert a single dataset to Polars."""
        snapshot_at = _coerce_snapshot_at(kwargs.pop("snapshot_at", None))
        self._inject_timeout(kwargs)
        result = endpoint_cls(**kwargs)
        dataset = getattr(result, attr, None)
        if dataset is None:
            logger.warning(f"{self.endpoint_name}: live dataset {attr!r} was not returned")
            frame = pl.DataFrame()
        else:
            frame = self._live_payload_to_frame(dataset)
        return self._apply_live_snapshot_contract(
            frame,
            source_endpoint=source_endpoint,
            natural_keys=natural_keys,
            snapshot_at=snapshot_at,
            params=kwargs,
        )

    def _from_nba_live_multi(
        self,
        endpoint_cls: type,
        specs: list[tuple[str, str, tuple[str, ...]]],
        **kwargs: Any,
    ) -> list[pl.DataFrame]:
        """Call nba_api live endpoint and convert multiple datasets to Polars."""
        snapshot_at = _coerce_snapshot_at(kwargs.pop("snapshot_at", None))
        self._inject_timeout(kwargs)
        result = endpoint_cls(**kwargs)
        frames: list[pl.DataFrame] = []
        for attr, source_endpoint, natural_keys in specs:
            dataset = getattr(result, attr, None)
            if dataset is None:
                logger.warning(f"{self.endpoint_name}: live dataset {attr!r} was not returned")
                frame = pl.DataFrame()
            else:
                frame = self._live_payload_to_frame(dataset)
            frames.append(
                self._apply_live_snapshot_contract(
                    frame,
                    source_endpoint=source_endpoint,
                    natural_keys=natural_keys,
                    snapshot_at=snapshot_at,
                    params=kwargs,
                )
            )
        return frames
