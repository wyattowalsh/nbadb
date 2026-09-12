from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

import pytest

import nbadb.contracts.transform_output_staging_input_authority as authority
from nbadb.contracts import transform_output_disposition_evidence as evidence_module
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.contracts.star_table_contract import compile_star_table_contracts
from nbadb.orchestrate.transformers import expected_transform_output_tables
from nbadb.schemas.registry import get_input_schema

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="module")
def inventory() -> Iterator[authority.RegisteredStagingInputContractInventoryV1]:
    yield authority.compile_registered_staging_input_contract_inventory()


def test_compiler_binds_every_current_transform_staging_dependency(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
) -> None:
    expected_names = tuple(
        sorted(
            {
                dependency
                for table in compile_star_table_contracts().tables
                for dependency in table.transform.dependencies
                if dependency.startswith("stg_")
            }
        )
    )
    routes = staging_route_contract_bundle().routes
    expected_outputs = tuple(sorted(expected_transform_output_tables(include_live=True)))
    star = compile_star_table_contracts()

    assert len(expected_outputs) == 261
    assert expected_outputs == tuple(table.output_name for table in star.tables)
    assert inventory.structural_output_names == expected_outputs
    assert inventory.structural_output_count == len(expected_outputs)
    assert inventory.star_model_contract_sha256 == star.contract_sha256
    assert inventory.entry_count == len(expected_names) == 399
    assert tuple(entry.dependency_id for entry in inventory.entries) == expected_names
    assert inventory.entry_count == len(set(expected_names))
    for entry in inventory.entries:
        schema_type = get_input_schema(entry.dependency_id)
        assert schema_type is not None
        expected_routes = tuple(
            sorted(route.route_id for route in routes if route.staging_key == entry.dependency_id)
        )
        route_by_id = {route.route_id: route for route in routes}
        assert entry.classification == "staging"
        assert entry.route_ids == expected_routes
        assert entry.route_contract_sha256s == tuple(
            route_by_id[route_id].contract_sha256 for route_id in expected_routes
        )
        assert entry.schema_module == schema_type.__module__
        assert entry.schema_class == schema_type.__name__


def test_inventory_is_canonical_deterministic_and_fresh_replayable(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
) -> None:
    second = authority.compile_registered_staging_input_contract_inventory()
    raw = inventory.canonical_bytes()

    assert second == inventory
    assert second.canonical_bytes() == raw
    assert (
        authority.RegisteredStagingInputContractInventoryV1.from_canonical_bytes(raw) == inventory
    )
    assert (
        json.dumps(
            inventory.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        == raw
    )
    assert inventory.entry_inventory_sha256 == authority._digest(
        {
            "kind": "nbadb_registered_staging_entry_inventory",
            "rows": [[entry.dependency_id, entry.contract_sha256] for entry in inventory.entries],
        }
    )
    assert inventory.contract_sha256 == authority._digest(inventory._preimage())
    assert inventory.structural_output_inventory_sha256 == authority._digest(
        {
            "schema_version": 1,
            "kind": authority._STRUCTURAL_OUTPUT_INVENTORY_KIND,
            "output_names": list(inventory.structural_output_names),
        }
    )


def test_dtos_are_parser_owned_and_surface_is_non_admitting() -> None:
    with pytest.raises(TypeError, match="compiler/parser owned"):
        authority.RegisteredStagingInputContractEntryV1()
    with pytest.raises(TypeError, match="requires from_canonical_bytes"):
        authority.RegisteredStagingInputContractInventoryV1()

    assert tuple(
        field.name
        for field in dataclasses.fields(authority.RegisteredStagingInputContractInventoryV1)
    ) == (
        "structural_output_names",
        "structural_output_count",
        "structural_output_inventory_sha256",
        "star_model_contract_sha256",
        "entries",
        "entry_count",
        "entry_inventory_sha256",
        "contract_sha256",
    )
    public = set(authority.__all__)
    assert not any(
        token in name.lower()
        for name in public
        for token in ("approve", "admit", "materialize", "publish")
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.pop("entry_count"),
        lambda payload: payload.update({"schema_version": True}),
        lambda payload: payload["entries"][0].update({"route_ids": [False]}),
        lambda payload: payload["entries"][0].update({"staging_schema_sha256": "0" * 63}),
    ],
)
def test_replay_rejects_unknown_omitted_and_foreign_values(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
    mutate: object,
) -> None:
    payload = inventory.to_dict()
    mutate(payload)  # type: ignore[operator]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises((authority.StagingInputContractAuthorityError, ValueError)):
        authority.RegisteredStagingInputContractInventoryV1.from_canonical_bytes(raw)


def test_replay_rejects_duplicate_json_keys_and_noncanonical_bytes(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
) -> None:
    raw = inventory.canonical_bytes()
    duplicate = raw.replace(b'{"contract_sha256":', b'{"contract_sha256":"0","contract_sha256":', 1)
    for candidate in (duplicate, raw + b"\n", b" " + raw):
        with pytest.raises(ValueError):
            authority.RegisteredStagingInputContractInventoryV1.from_canonical_bytes(candidate)


def test_fabricated_internally_consistent_inventory_fails_fresh_registry_replay(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
) -> None:
    original = inventory.entries[0]
    forged_entry = authority._build_entry(
        dependency_id=original.dependency_id,
        route_ids=original.route_ids,
        route_contract_sha256s=("0" * 64, *original.route_contract_sha256s[1:]),
        schema_module=original.schema_module,
        schema_class=original.schema_class,
        staging_schema_sha256=original.staging_schema_sha256,
    )
    forged = authority._build_inventory(
        (forged_entry, *inventory.entries[1:]),
        structural_output_names=inventory.structural_output_names,
        star_model_contract_sha256=inventory.star_model_contract_sha256,
    )

    assert forged.contract_sha256 != inventory.contract_sha256
    with pytest.raises(
        authority.StagingInputContractAuthorityError,
        match="fresh registered authority",
    ):
        authority.RegisteredStagingInputContractInventoryV1.from_canonical_bytes(
            forged.canonical_bytes()
        )


def test_private_builders_reject_ambiguous_routes_and_dependency_order(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
) -> None:
    first = inventory.entries[0]
    with pytest.raises(authority.StagingInputContractAuthorityError, match="routes are invalid"):
        authority._build_entry(
            dependency_id=first.dependency_id,
            route_ids=(first.route_ids[0], first.route_ids[0]),
            route_contract_sha256s=(first.route_contract_sha256s[0],) * 2,
            schema_module=first.schema_module,
            schema_class=first.schema_class,
            staging_schema_sha256=first.staging_schema_sha256,
        )
    with pytest.raises(authority.StagingInputContractAuthorityError, match="sorted and unique"):
        authority._build_inventory(
            tuple(reversed(inventory.entries)),
            structural_output_names=inventory.structural_output_names,
            star_model_contract_sha256=inventory.star_model_contract_sha256,
        )


def test_resealed_structural_scope_omission_fails_even_when_dependency_union_is_unchanged(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
) -> None:
    star = compile_star_table_contracts()
    complete_union = {
        dependency
        for table in star.tables
        for dependency in table.transform.dependencies
        if dependency.startswith("stg_")
    }
    removable = next(
        table.output_name
        for table in star.tables
        if {
            dependency
            for other in star.tables
            if other.output_name != table.output_name
            for dependency in other.transform.dependencies
            if dependency.startswith("stg_")
        }
        == complete_union
    )
    narrowed_names = tuple(name for name in inventory.structural_output_names if name != removable)
    forged = authority._build_inventory(
        inventory.entries,
        structural_output_names=narrowed_names,
        star_model_contract_sha256=inventory.star_model_contract_sha256,
    )

    assert forged.entry_inventory_sha256 == inventory.entry_inventory_sha256
    assert forged.structural_output_inventory_sha256 != (
        inventory.structural_output_inventory_sha256
    )
    with pytest.raises(
        authority.StagingInputContractAuthorityError,
        match="fresh registered authority",
    ):
        authority.RegisteredStagingInputContractInventoryV1.from_canonical_bytes(
            forged.canonical_bytes()
        )


@pytest.mark.parametrize("mutation", ["substitution", "star_contract"])
def test_resealed_structural_scope_or_star_contract_substitution_fails_current_replay(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
    mutation: str,
) -> None:
    output_names = inventory.structural_output_names
    star_contract = inventory.star_model_contract_sha256
    if mutation == "substitution":
        output_names = tuple(sorted((*output_names[1:], "fact_fictional_substitution")))
    else:
        star_contract = "0" * 64
    forged = authority._build_inventory(
        inventory.entries,
        structural_output_names=output_names,
        star_model_contract_sha256=star_contract,
    )

    with pytest.raises(
        authority.StagingInputContractAuthorityError,
        match="fresh registered authority",
    ):
        authority.RegisteredStagingInputContractInventoryV1.from_canonical_bytes(
            forged.canonical_bytes()
        )


def test_historical_parser_is_typed_but_does_not_consult_current_registries(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authority,
        "compile_registered_staging_input_contract_inventory",
        lambda: (_ for _ in ()).throw(AssertionError("current compiler must not run")),
    )

    observed = authority.RegisteredStagingInputContractInventoryV1.from_historical_canonical_bytes(
        inventory.canonical_bytes()
    )
    assert observed == inventory


def test_public_parsers_retain_shared_byte_and_depth_bounds(
    inventory: authority.RegisteredStagingInputContractInventoryV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = inventory.canonical_bytes()
    monkeypatch.setattr(evidence_module, "CANONICAL_JSON_MAX_BYTES", len(raw) - 1)
    with pytest.raises(ValueError, match="over-bound"):
        authority.RegisteredStagingInputContractInventoryV1.from_canonical_bytes(raw)

    monkeypatch.setattr(evidence_module, "CANONICAL_JSON_MAX_BYTES", 32 * 1024 * 1024)
    excessive_depth = b"[" * 49 + b"0" + b"]" * 49
    with pytest.raises(ValueError, match="depth"):
        authority.RegisteredStagingInputContractInventoryV1.from_historical_canonical_bytes(
            excessive_depth
        )
