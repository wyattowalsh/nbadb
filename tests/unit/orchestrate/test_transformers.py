"""Unit tests for fail-closed transformer discovery."""

from __future__ import annotations

import importlib as _real_importlib
from unittest.mock import patch

import pytest

from nbadb.orchestrate.transformers import (
    TransformerDiscoveryError,
    discover_all_transformers,
    discover_live_transformers,
    expected_transform_output_tables,
    require_complete_transformer_universe,
)

_real_import_module = _real_importlib.import_module
_PATCH_TARGET = "nbadb.orchestrate.transformers.importlib.import_module"


class TestDiscoverAllTransformers:
    def test_returns_non_empty_list(self) -> None:
        """Smoke test: discovers real transformers from the transform packages."""
        result = discover_all_transformers()
        assert isinstance(result, list)
        assert len(result) > 0
        assert {transformer.output_table for transformer in result} == set(
            expected_transform_output_tables()
        )

    def test_package_import_error_fails_closed(self) -> None:
        """A package import failure cannot produce a partial green universe."""

        def _failing_import(name: str, *args: object, **kw: object) -> object:
            if name == "nbadb.transform.dimensions":
                raise ImportError("synthetic failure")
            return _real_import_module(name)

        with (
            patch(_PATCH_TARGET, side_effect=_failing_import),
            pytest.raises(
                TransformerDiscoveryError,
                match=r"cannot import transform package nbadb\.transform\.dimensions",
            ),
        ):
            discover_all_transformers()

    def test_module_import_error_fails_closed(self) -> None:
        """A leaf-module import failure cannot produce a partial green universe."""

        def _selective_fail(name: str, *args: object, **kw: object) -> object:
            if name.endswith("dim_player"):
                raise ImportError("synthetic module failure")
            return _real_import_module(name)

        with (
            patch(_PATCH_TARGET, side_effect=_selective_fail),
            pytest.raises(
                TransformerDiscoveryError,
                match=r"cannot import transform module .*dim_player",
            ),
        ):
            discover_all_transformers()

    def test_all_packages_import_error_fails_closed(self) -> None:
        """Discovery never returns an empty list after import failures."""
        with (
            patch(_PATCH_TARGET, side_effect=ImportError("all fail")),
            pytest.raises(TransformerDiscoveryError, match="cannot import transform package"),
        ):
            discover_all_transformers()

    def test_deduplication(self) -> None:
        """Each transformer class appears only once in the result."""
        result = discover_all_transformers()
        output_tables = [t.output_table for t in result]
        assert len(output_tables) == len(set(output_tables))

    def test_discovered_count_exactly_matches_schema_backed_universe(self) -> None:
        """Guard against accidental loss or addition of transformer outputs."""
        result = discover_all_transformers()
        assert len(result) == len(expected_transform_output_tables())

    def test_live_transformers_can_be_filtered_out(self) -> None:
        historical_only = discover_all_transformers(include_live=False)
        assert all(not getattr(t, "is_live_snapshot", False) for t in historical_only)
        assert {transformer.output_table for transformer in historical_only} == set(
            expected_transform_output_tables(include_live=False)
        )

    def test_live_transformers_are_discoverable(self) -> None:
        live_transformers = discover_live_transformers()
        output_tables = {transformer.output_table for transformer in live_transformers}
        assert {
            "fact_live_score_board",
            "fact_live_odds",
            "fact_live_play_by_play",
            "fact_live_box_score_game",
            "fact_live_box_score_team",
            "fact_live_box_score_player",
        } <= output_tables

    def test_empty_universe_is_rejected(self) -> None:
        with pytest.raises(
            TransformerDiscoveryError,
            match=r"incomplete full transformer discovery: discovered=0; unique=0",
        ):
            require_complete_transformer_universe([])

    def test_partial_universe_is_rejected_with_missing_output(self) -> None:
        transformers = discover_all_transformers()
        omitted = transformers[-1].output_table

        with pytest.raises(TransformerDiscoveryError, match=rf"missing=.*{omitted}"):
            require_complete_transformer_universe(transformers[:-1])

    def test_duplicate_output_is_rejected(self) -> None:
        transformers = discover_all_transformers()
        duplicate = transformers[0].output_table

        with pytest.raises(TransformerDiscoveryError, match=rf"duplicates=.*{duplicate}"):
            require_complete_transformer_universe([*transformers, transformers[0]])
