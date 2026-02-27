from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import EndpointRegistry


class _FakeExtractor(BaseExtractor):
    endpoint_name = "fake"
    category = "test"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return pl.DataFrame()


class _FakeExtractor2(BaseExtractor):
    endpoint_name = "fake2"
    category = "other"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return pl.DataFrame()


class TestEndpointRegistry:
    def test_register_and_get(self) -> None:
        reg = EndpointRegistry()
        reg.register(_FakeExtractor)
        assert reg.get("fake") is _FakeExtractor

    def test_get_unknown_raises(self) -> None:
        reg = EndpointRegistry()
        with pytest.raises(KeyError, match="Unknown endpoint"):
            reg.get("nonexistent")

    def test_get_by_category(self) -> None:
        reg = EndpointRegistry()
        reg.register(_FakeExtractor)
        reg.register(_FakeExtractor2)
        test_extractors = reg.get_by_category("test")
        assert len(test_extractors) == 1
        assert test_extractors[0] is _FakeExtractor

    def test_get_all(self) -> None:
        reg = EndpointRegistry()
        reg.register(_FakeExtractor)
        reg.register(_FakeExtractor2)
        assert reg.count == 2
        assert len(reg.get_all()) == 2

    def test_count_empty(self) -> None:
        reg = EndpointRegistry()
        assert reg.count == 0

    def test_register_returns_class(self) -> None:
        reg = EndpointRegistry()
        result = reg.register(_FakeExtractor)
        assert result is _FakeExtractor
