"""Unit tests for nbadb.orchestrate.transformers module.

Covers the ImportError handling branches in discover_all_transformers().
"""

from __future__ import annotations

import importlib as _real_importlib
from unittest.mock import patch

from nbadb.orchestrate.transformers import discover_all_transformers

_real_import_module = _real_importlib.import_module
_PATCH_TARGET = "nbadb.orchestrate.transformers.importlib.import_module"


class TestDiscoverAllTransformers:
    def test_returns_non_empty_list(self) -> None:
        """Smoke test: discovers real transformers from the transform packages."""
        result = discover_all_transformers()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_package_import_error_is_handled(self) -> None:
        """When a transform package cannot be imported, it is skipped."""

        def _failing_import(name: str, *args: object, **kw: object) -> object:
            if name == "nbadb.transform.dimensions":
                raise ImportError("synthetic failure")
            return _real_import_module(name)

        with patch(_PATCH_TARGET, side_effect=_failing_import):
            result = discover_all_transformers()
        # Should still return transformers from the other 3 packages
        assert isinstance(result, list)

    def test_module_import_error_is_handled(self) -> None:
        """When a module within a package fails to import, it is skipped."""

        def _selective_fail(name: str, *args: object, **kw: object) -> object:
            if name.endswith("dim_player"):
                raise ImportError("synthetic module failure")
            return _real_import_module(name)

        with patch(_PATCH_TARGET, side_effect=_selective_fail):
            result = discover_all_transformers()
        assert isinstance(result, list)

    def test_all_four_packages_import_error_returns_empty(self) -> None:
        """When ALL packages fail to import, result is empty."""
        with patch(_PATCH_TARGET, side_effect=ImportError("all fail")):
            result = discover_all_transformers()
        assert result == []

    def test_deduplication(self) -> None:
        """Each transformer class appears only once in the result."""
        result = discover_all_transformers()
        output_tables = [t.output_table for t in result]
        assert len(output_tables) == len(set(output_tables))

    def test_minimum_transformer_count(self) -> None:
        """Guard against accidental loss of transformers."""
        result = discover_all_transformers()
        assert len(result) >= 170, (
            f"Expected at least 170 transformers but discovered {len(result)}. "
            "A transform module may have been accidentally removed."
        )
