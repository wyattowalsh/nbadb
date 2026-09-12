"""Typed helpers for extractor unit tests. Not a test module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from nbadb.extract.base import BaseExtractor

if TYPE_CHECKING:
    import pytest

type ExtractorCls = type[BaseExtractor]


def record_nba_api_kwargs(
    ext: BaseExtractor,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _fake(_endpoint_cls: type, **kwargs: object) -> pl.DataFrame:
        captured.update(kwargs)
        return pl.DataFrame({"ok": [1]})

    monkeypatch.setattr(ext, "_from_nba_api", _fake)
    return captured


def as_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected a dict")
    return {str(key): item for key, item in value.items()}
