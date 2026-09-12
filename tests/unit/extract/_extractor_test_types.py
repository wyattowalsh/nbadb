"""Shared typing helpers for extractor unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from nbadb.extract.base import BaseExtractor

if TYPE_CHECKING:
    import polars as pl

ExtractorCls = type[BaseExtractor]


class RosterCoachesExtractor(Protocol):
    async def extract_coaches(self, **params: object) -> pl.DataFrame: ...


def provider_kwargs(captured: dict[str, object]) -> dict[str, object]:
    raw = captured["kwargs"]
    assert isinstance(raw, dict)
    return {str(key): value for key, value in raw.items()}
