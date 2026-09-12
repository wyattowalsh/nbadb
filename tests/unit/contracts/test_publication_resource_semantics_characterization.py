"""H.0 characterization of today's publication-resource projection.

These tests intentionally describe current behavior only. H.2 replaces the
metadata module's catalog/global and export-tree authority with typed inputs.
"""

from __future__ import annotations

from collections import Counter

import pytest

from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.kaggle.metadata import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    TERMINAL_ASSURANCE_REPORT_NAME,
    expected_full_publication_resource_contract,
)
from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY

_FIXED_RESOURCES = frozenset(
    {
        "nba.duckdb",
        "nba.sqlite",
        TERMINAL_ASSURANCE_REPORT_NAME,
        ASSURED_ARTIFACT_MANIFEST_NAME,
    }
)


def _contract(*, stats_conditional: bool, live_conditional: bool) -> dict[str, str]:
    # Explicit flags avoid filesystem discovery. H.2 will replace these flags
    # with the verified full-publication union rather than preserve this seam.
    return expected_full_publication_resource_contract(
        include_lossless_fallback=stats_conditional,
        include_live_lossless=live_conditional,
    )


@pytest.fixture(scope="module")
def contracts() -> dict[tuple[bool, bool], dict[str, str]]:
    return {
        flags: _contract(stats_conditional=flags[0], live_conditional=flags[1])
        for flags in ((False, False), (True, False), (False, True), (True, True))
    }


def _table_for_resource(path: str) -> str | None:
    if path.startswith("csv/") and path.endswith(".csv"):
        return path.removeprefix("csv/").removesuffix(".csv")
    if not path.startswith("parquet/"):
        return None
    remainder = path.removeprefix("parquet/")
    return remainder.split("/", maxsplit=1)[0]


def test_current_projection_has_four_fixed_resources_and_exactly_two_per_table(
    contracts: dict[tuple[bool, bool], dict[str, str]],
) -> None:
    contract = contracts[(False, False)]

    assert {path for path in contract if _table_for_resource(path) is None} == _FIXED_RESOURCES
    assert all(contract[path] == "file" for path in _FIXED_RESOURCES)
    table_counts = Counter(
        table for path in contract if (table := _table_for_resource(path)) is not None
    )
    assert table_counts
    assert set(table_counts.values()) == {2}
    for table in table_counts:
        assert contract[f"csv/{table}.csv"] == "file"
        assert f"parquet/{table}" in contract or f"parquet/{table}/{table}.parquet" in contract


def test_current_projection_distinguishes_partitioned_directory_and_single_file(
    contracts: dict[tuple[bool, bool], dict[str, str]],
) -> None:
    contract = contracts[(False, False)]

    assert contract["parquet/fact_player_game_traditional"] == "directory"
    assert (
        "parquet/fact_player_game_traditional/fact_player_game_traditional.parquet" not in contract
    )
    assert contract["parquet/dim_player/dim_player.parquet"] == "file"
    assert "parquet/dim_player" not in contract


@pytest.mark.parametrize(
    ("stats_conditional", "live_conditional", "expected_present"),
    [
        (False, False, frozenset()),
        (True, False, frozenset({LOSSLESS_FALLBACK_STAGING_KEY})),
        (False, True, frozenset({LIVE_LOSSLESS_STAGING_KEY})),
        (
            True,
            True,
            frozenset({LOSSLESS_FALLBACK_STAGING_KEY, LIVE_LOSSLESS_STAGING_KEY}),
        ),
    ],
)
def test_current_projection_uses_explicit_zero_one_or_both_typed_conditionals(
    contracts: dict[tuple[bool, bool], dict[str, str]],
    stats_conditional: bool,
    live_conditional: bool,
    expected_present: frozenset[str],
) -> None:
    contract = contracts[(stats_conditional, live_conditional)]
    conditional_tables = {LOSSLESS_FALLBACK_STAGING_KEY, LIVE_LOSSLESS_STAGING_KEY}

    for table in conditional_tables:
        paths = {
            f"csv/{table}.csv",
            f"parquet/{table}/{table}.parquet",
        }
        assert paths <= set(contract) if table in expected_present else paths.isdisjoint(contract)


def test_current_resource_counts_are_drift_sensitive_observations_only(
    contracts: dict[tuple[bool, bool], dict[str, str]],
) -> None:
    observed = {flags: len(contract) for flags, contract in contracts.items()}

    # Observation refreshed 2026-09-11 after the exact-four raw authority
    # relations became private-only (four tables x two formats left the public
    # contracts); not a production constant or timeless contract.
    assert observed == {
        (False, False): 1414,
        (True, False): 1416,
        (False, True): 1416,
        (True, True): 1418,
    }
    assert observed[(True, False)] - observed[(False, False)] == 2
    assert observed[(False, True)] - observed[(False, False)] == 2
    assert observed[(True, True)] - observed[(False, False)] == 4
