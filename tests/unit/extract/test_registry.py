from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import (
    EndpointRegistry,
    EndpointRegistryAuthority,
    EndpointRegistryAuthorityError,
)


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


class _FakeExtractorReplacement(BaseExtractor):
    endpoint_name = "fake"
    category = "replacement"

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

    def test_capture_authority_rejects_empty_and_missing_inventory(self) -> None:
        reg = EndpointRegistry()

        with pytest.raises(EndpointRegistryAuthorityError, match="at least one endpoint"):
            reg.capture_authority()
        with pytest.raises(EndpointRegistryAuthorityError, match="nonempty unique tuple"):
            reg.capture_authority(())
        with pytest.raises(EndpointRegistryAuthorityError, match="required endpoint is absent"):
            reg.capture_authority(("missing",))
        with pytest.raises(EndpointRegistryAuthorityError, match="at least one endpoint"):
            EndpointRegistryAuthority(bindings=(), complete_inventory=False)

    def test_scoped_authority_binds_exact_class_and_import_identity(self) -> None:
        reg = EndpointRegistry()
        reg.register(_FakeExtractor)
        authority = reg.capture_authority(("fake",))

        assert authority.complete_inventory is False
        assert authority.endpoint_names == ("fake",)
        assert authority.bindings[0].extractor_cls is _FakeExtractor
        assert authority.bindings[0].module == _FakeExtractor.__module__
        assert authority.bindings[0].qualname == _FakeExtractor.__qualname__
        authority.require_current(reg, required_endpoint_name="fake")

    def test_scoped_authority_rejects_replacement_and_removal(self) -> None:
        replacement_registry = EndpointRegistry()
        replacement_registry.register(_FakeExtractor)
        replacement_authority = replacement_registry.capture_authority(("fake",))
        replacement_registry.register(_FakeExtractorReplacement)

        with pytest.raises(EndpointRegistryAuthorityError, match="class changed"):
            replacement_authority.require_current(replacement_registry)

        removed_registry = EndpointRegistry()
        removed_registry.register(_FakeExtractor)
        removed_authority = removed_registry.capture_authority(("fake",))
        removed_registry._extractors.pop("fake")  # noqa: SLF001

        with pytest.raises(EndpointRegistryAuthorityError, match="was removed"):
            removed_authority.require_current(removed_registry)

    def test_scoped_authority_allows_unbound_addition(self) -> None:
        reg = EndpointRegistry()
        reg.register(_FakeExtractor)
        authority = reg.capture_authority(("fake",))

        reg.register(_FakeExtractor2)

        authority.require_current(reg, required_endpoint_name="fake")

    def test_authority_rejects_stable_import_identity_drift(self) -> None:
        reg = EndpointRegistry()
        reg.register(_FakeExtractor)
        authority = reg.capture_authority(("fake",))
        original_module = _FakeExtractor.__module__
        try:
            _FakeExtractor.__module__ = "drifted.extractor.module"
            with pytest.raises(EndpointRegistryAuthorityError, match="class changed"):
                authority.require_current(reg)
        finally:
            _FakeExtractor.__module__ = original_module

    def test_complete_authority_rejects_addition(self) -> None:
        reg = EndpointRegistry()
        reg.register(_FakeExtractor)
        authority = reg.capture_authority()

        reg.register(_FakeExtractor2)

        with pytest.raises(EndpointRegistryAuthorityError, match="inventory changed"):
            authority.require_current(reg)

    def test_authority_rejects_unbound_required_endpoint(self) -> None:
        reg = EndpointRegistry()
        reg.register(_FakeExtractor)
        reg.register(_FakeExtractor2)
        authority = reg.capture_authority(("fake",))

        with pytest.raises(EndpointRegistryAuthorityError, match="absent from registry authority"):
            authority.require_current(reg, required_endpoint_name="fake2")
