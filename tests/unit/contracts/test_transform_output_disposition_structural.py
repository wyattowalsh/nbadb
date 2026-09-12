from __future__ import annotations

import inspect
import json
from dataclasses import FrozenInstanceError, replace
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.contracts import transform_output_disposition_structural as structural_module
from nbadb.contracts.star_table_contract import (
    StarModelContractInventory,
    compile_star_table_contracts,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputDispositionStructuralError,
    TransformOutputStructuralAuthorityV1,
    compile_current_transform_output_structural_authority,
)
from nbadb.orchestrate.transformers import expected_transform_output_tables

if TYPE_CHECKING:
    from collections.abc import Iterable


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@pytest.fixture(scope="module")
def current_authority() -> TransformOutputStructuralAuthorityV1:
    return compile_current_transform_output_structural_authority()


@pytest.fixture(scope="module")
def current_inventory() -> StarModelContractInventory:
    return compile_star_table_contracts()


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    discovered: object,
    inventory: object,
) -> None:
    import nbadb.contracts.star_table_contract as contract_module
    import nbadb.orchestrate.transformers as transformer_module

    monkeypatch.setattr(
        transformer_module,
        "expected_transform_output_tables",
        lambda *, include_live: discovered if include_live else frozenset(),
    )
    monkeypatch.setattr(
        contract_module,
        "compile_star_table_contracts",
        lambda: inventory,
    )


def _payload(current_authority: TransformOutputStructuralAuthorityV1) -> dict[str, object]:
    value = json.loads(current_authority.canonical_bytes)
    assert type(value) is dict
    return value


def test_den_001_current_sources_are_exact_and_count_is_drift_sensitive(
    current_authority: TransformOutputStructuralAuthorityV1,
    current_inventory: StarModelContractInventory,
) -> None:
    discovered = tuple(sorted(expected_transform_output_tables(include_live=True)))
    compiled = tuple(table.output_name for table in current_inventory.tables)

    assert discovered == compiled == current_authority.output_names
    assert current_authority.output_count == len(discovered) == 261
    assert current_authority.star_model_contract_sha256 == current_inventory.contract_sha256
    assert len(current_authority.tables) == current_authority.output_count
    assert len({table.table_authority_sha256 for table in current_authority.tables}) == (
        current_authority.output_count
    )


def test_den_002_each_row_binds_exact_table_local_identities(
    current_authority: TransformOutputStructuralAuthorityV1,
    current_inventory: StarModelContractInventory,
) -> None:
    compiled_by_name = {table.output_name: table for table in current_inventory.tables}

    for authority in current_authority.tables:
        compiled = compiled_by_name[authority.output_name]
        assert authority.table_family == compiled.family
        assert authority.table_contract_sha256 == compiled.contract_sha256
        assert authority.schema_sha256 == compiled.schema_sha256
        assert authority.transform_sha256 == compiled.transform.implementation_sha256
        assert authority.ordered_columns == tuple(column.name for column in compiled.columns)
        assert authority.dependencies == compiled.transform.dependencies
        assert len(authority.ordered_column_inventory_sha256) == 64
        assert len(authority.dependency_inventory_sha256) == 64

    payload = current_authority.to_dict()
    assert set(payload) == {
        "schema_version",
        "kind",
        "output_count",
        "output_names",
        "output_name_inventory_sha256",
        "star_model_contract_sha256",
        "table_authority_inventory_sha256",
        "tables",
        "authority_sha256",
    }
    table_payload = cast("list[dict[str, object]]", payload["tables"])[0]
    assert "state" not in table_payload
    assert "capability_policy" not in table_payload
    assert "model_disposition" not in table_payload


def test_det_structural_authority_round_trips_canonical_bytes_and_is_deterministic(
    current_authority: TransformOutputStructuralAuthorityV1,
) -> None:
    replayed = TransformOutputStructuralAuthorityV1.from_canonical_bytes(
        current_authority.canonical_bytes
    )
    repeated = compile_current_transform_output_structural_authority()

    assert replayed == current_authority
    assert replayed.canonical_bytes == current_authority.canonical_bytes
    assert replayed.authority_sha256 == current_authority.authority_sha256
    assert repeated == current_authority
    assert repeated.canonical_bytes == current_authority.canonical_bytes


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "foreign_case",
        "blank",
    ],
)
def test_den_003_discovery_name_drift_fails_before_authority_construction(
    monkeypatch: pytest.MonkeyPatch,
    current_inventory: StarModelContractInventory,
    mutation: str,
) -> None:
    names = set(table.output_name for table in current_inventory.tables)
    first = min(names)
    names.remove(first)
    if mutation == "missing":
        pass
    elif mutation == "extra":
        names.update({first, "fact_foreign_output"})
    elif mutation == "foreign_case":
        names.add(first.upper())
    else:
        names.add("")
    _patch_sources(
        monkeypatch,
        discovered=frozenset(names),
        inventory=current_inventory,
    )

    with pytest.raises(TransformOutputDispositionStructuralError):
        compile_current_transform_output_structural_authority()


def test_den_003_foreign_discovery_collection_type_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    current_inventory: StarModelContractInventory,
) -> None:
    names: Iterable[str] = (table.output_name for table in current_inventory.tables)
    _patch_sources(
        monkeypatch,
        discovered=tuple(names),
        inventory=current_inventory,
    )

    with pytest.raises(
        TransformOutputDispositionStructuralError,
        match="foreign collection type",
    ):
        compile_current_transform_output_structural_authority()


@pytest.mark.parametrize("mutation", ["reordered", "duplicate", "foreign"])
def test_den_004_compiled_name_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    current_inventory: StarModelContractInventory,
    mutation: str,
) -> None:
    tables = list(current_inventory.tables)
    if mutation == "reordered":
        tables[0], tables[1] = tables[1], tables[0]
    elif mutation == "duplicate":
        tables[1] = tables[0]
    else:
        tables[0] = replace(tables[0], output_name="fact_foreign_output")
    malformed = replace(current_inventory, tables=tuple(tables))
    _patch_sources(
        monkeypatch,
        discovered=frozenset(table.output_name for table in current_inventory.tables),
        inventory=malformed,
    )

    with pytest.raises(TransformOutputDispositionStructuralError):
        compile_current_transform_output_structural_authority()


def test_den_004_compiled_inventory_root_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    current_inventory: StarModelContractInventory,
) -> None:
    malformed = replace(current_inventory, contract_sha256="0" * 64)
    _patch_sources(
        monkeypatch,
        discovered=frozenset(table.output_name for table in current_inventory.tables),
        inventory=malformed,
    )

    with pytest.raises(
        TransformOutputDispositionStructuralError,
        match="root differs",
    ):
        compile_current_transform_output_structural_authority()


def test_den_004_compiled_per_table_root_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    current_inventory: StarModelContractInventory,
) -> None:
    tables = list(current_inventory.tables)
    tables[0] = replace(tables[0], contract_sha256="0" * 64)
    malformed = replace(current_inventory, tables=tuple(tables))
    _patch_sources(
        monkeypatch,
        discovered=frozenset(table.output_name for table in current_inventory.tables),
        inventory=malformed,
    )

    with pytest.raises(
        TransformOutputDispositionStructuralError,
        match="root differs",
    ):
        compile_current_transform_output_structural_authority()


@pytest.mark.parametrize(
    "mutation",
    [
        "count",
        "duplicate_name",
        "name_root",
        "table_root",
        "global_root",
        "authority_root",
        "unknown_field",
    ],
)
def test_den_005_canonical_payload_mutations_fail_closed(
    current_authority: TransformOutputStructuralAuthorityV1,
    mutation: str,
) -> None:
    payload = _payload(current_authority)
    if mutation == "count":
        payload["output_count"] = cast("int", payload["output_count"]) + 1
    elif mutation == "duplicate_name":
        names = cast("list[str]", payload["output_names"])
        names.append(names[0])
    elif mutation == "name_root":
        payload["output_name_inventory_sha256"] = "0" * 64
    elif mutation == "table_root":
        tables = cast("list[dict[str, object]]", payload["tables"])
        tables[0]["table_contract_sha256"] = "0" * 64
    elif mutation == "global_root":
        payload["star_model_contract_sha256"] = "0" * 64
    elif mutation == "authority_root":
        payload["authority_sha256"] = "0" * 64
    else:
        payload["verified"] = True

    with pytest.raises(TransformOutputDispositionStructuralError):
        TransformOutputStructuralAuthorityV1.from_canonical_bytes(_canonical(payload))


def test_den_005_duplicate_keys_noncanonical_bytes_and_nonfinite_values_fail(
    current_authority: TransformOutputStructuralAuthorityV1,
) -> None:
    with pytest.raises(TransformOutputDispositionStructuralError, match="duplicate JSON key"):
        TransformOutputStructuralAuthorityV1.from_canonical_bytes(
            b'{"kind":"first","kind":"second"}'
        )
    with pytest.raises(TransformOutputDispositionStructuralError, match="not exact canonical"):
        TransformOutputStructuralAuthorityV1.from_canonical_bytes(
            current_authority.canonical_bytes + b"\n"
        )
    with pytest.raises(TransformOutputDispositionStructuralError, match="non-finite"):
        TransformOutputStructuralAuthorityV1.from_canonical_bytes(b'{"value":NaN}')


def test_den_006_compiler_has_no_caller_denominator_or_filter_inputs() -> None:
    signature = inspect.signature(compile_current_transform_output_structural_authority)
    source = inspect.getsource(structural_module)

    assert tuple(signature.parameters) == ()
    assert "expected_count" not in source
    assert "disposition_filter" not in source
    assert "caller_inventory" not in source
    assert "261" not in source


def test_structural_dtos_are_deeply_immutable(
    current_authority: TransformOutputStructuralAuthorityV1,
) -> None:
    with pytest.raises(FrozenInstanceError):
        current_authority.star_model_contract_sha256 = "0" * 64
    with pytest.raises(TypeError):
        current_authority.tables[0] = current_authority.tables[0]
    with pytest.raises(FrozenInstanceError):
        current_authority.tables[0].schema_sha256 = "0" * 64
