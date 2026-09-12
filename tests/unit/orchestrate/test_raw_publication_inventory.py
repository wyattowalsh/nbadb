from __future__ import annotations

from typing import cast

import pytest

from nbadb.orchestrate import raw_request_store
from nbadb.orchestrate.raw_publication_inventory import (
    PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES,
    RAW_REQUEST_AUTHORITY_PRIVATE_CATEGORY,
    RawRequestAuthorityPrivateTable,
    raw_request_authority_private_tables,
    raw_request_authority_publication_tables,
)
from nbadb.schemas.raw.nba_api_authority import (
    RawNbaApiObservationRouteLandingSchema,
)


def test_private_inventory_joins_exact_store_names_to_fixed_strict_schemas() -> None:
    entries = raw_request_authority_private_tables()

    assert RAW_REQUEST_AUTHORITY_PRIVATE_CATEGORY == "raw_request_authority_private"
    assert tuple(entry.table_name for entry in entries) == PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES
    assert (
        PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES == raw_request_store.RAW_REQUEST_AUTHORITY_TABLES
    )
    assert len(entries) == 4
    assert all(type(entry) is RawRequestAuthorityPrivateTable for entry in entries)
    assert len({entry.schema_type for entry in entries}) == 4
    assert all(entry.description for entry in entries)
    assert all(entry.contains_provider_body_authority is True for entry in entries)
    assert all(entry.schema_type.Config.strict is True for entry in entries)
    assert all(entry.schema_type.Config.coerce is False for entry in entries)
    assert all(entry.schema_type.Config.ordered is True for entry in entries)


def test_legacy_publication_inventory_is_empty_but_still_validates_private_registry() -> None:
    assert raw_request_authority_publication_tables() == ()


def test_private_inventory_rejects_reordered_fourth_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reversed_names = tuple(reversed(raw_request_store.RAW_REQUEST_AUTHORITY_TABLES))
    monkeypatch.setattr(raw_request_store, "RAW_REQUEST_AUTHORITY_TABLES", reversed_names)

    with pytest.raises(RuntimeError, match="private raw request-authority store"):
        raw_request_authority_private_tables()
    with pytest.raises(RuntimeError, match="private raw request-authority store"):
        raw_request_authority_publication_tables()


def test_private_inventory_includes_response_route_landing_contract() -> None:
    entries = raw_request_authority_private_tables()
    landing = next(
        entry for entry in entries if entry.table_name == "raw_nba_api_observation_route_landing"
    )

    assert landing.schema_type is RawNbaApiObservationRouteLandingSchema
    assert "Private response-to-route landing authority" in landing.description


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values[:-1],
        lambda values: (*values, "raw_nba_api_unregistered"),
        lambda values: (values[0], values[1], values[2], values[2]),
        lambda values: (*values[:-1], "raw_nba_api_unregistered"),
        lambda values: cast("tuple[str, ...]", list(values)),
    ],
)
def test_private_inventory_fails_closed_for_store_schema_mutation(
    monkeypatch: pytest.MonkeyPatch,
    mutation,
) -> None:
    monkeypatch.setattr(
        raw_request_store,
        "RAW_REQUEST_AUTHORITY_TABLES",
        mutation(raw_request_store.RAW_REQUEST_AUTHORITY_TABLES),
    )

    with pytest.raises(RuntimeError, match="private raw request-authority store"):
        raw_request_authority_private_tables()
