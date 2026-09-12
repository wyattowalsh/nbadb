from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import nbadb.contracts.field_fate_structure_verifier as verifier_module
from nbadb.contracts.field_fate_structure import (
    FieldFateStructureV1,
    compile_field_fate_structure,
)
from nbadb.contracts.field_fate_structure_verifier import (
    FieldFateStructureVerificationError,
    FieldFateStructureVerificationV1,
    canonical_verification_bytes,
    parse_field_fate_structure_verification,
    validate_field_fate_structure_verification,
    verify_field_fate_structure,
    verify_field_fate_structure_independently,
)


@pytest.fixture(scope="module")
def structure() -> FieldFateStructureV1:
    return compile_field_fate_structure()


@pytest.fixture(scope="module")
def receipt(structure: FieldFateStructureV1) -> FieldFateStructureVerificationV1:
    return verify_field_fate_structure_independently(structure)


def test_independent_verifier_readback_has_exact_counts_and_digests(
    structure: FieldFateStructureV1,
    receipt: FieldFateStructureVerificationV1,
) -> None:
    assert receipt.structure_sha256 == structure.identity_sha256
    assert receipt.provider_source_occurrence_count == 9_970
    assert receipt.route_binding_count == 11_323
    assert receipt.routed_source_occurrence_count == 9_694
    assert receipt.unrouted_source_occurrence_count == 276
    assert receipt.lossless_field_binding_count == 276
    assert receipt.storage_sink_count == 13_260
    assert receipt.provider_bound_storage_sink_count == 11_207
    assert receipt.storage_only_sink_count == 2_053
    assert receipt.source_authority_blocker_count == 21
    assert receipt.unresolved_lossless_binding_count == 0
    assert receipt.open_blocker_count == 21
    assert receipt.wide_route_complete is False
    assert receipt.lossless_field_binding_complete is True
    assert json.loads(json.dumps(receipt.to_dict(), sort_keys=True)) == receipt.to_dict()
    assert len(receipt.receipt_sha256) == 64
    summary = cast("dict[str, object]", receipt.to_dict()["summary"])
    assert isinstance(summary, dict)
    assert summary["model_green"] == "not_evaluated_by_structural_verifier"


def test_public_verifier_alias_uses_the_independent_path(
    structure: FieldFateStructureV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.field_fate_structure as structure_module

    def fail_if_called() -> None:
        raise AssertionError("structural compiler must not be called by readback")

    monkeypatch.setattr(structure_module, "compile_field_fate_structure", fail_if_called)
    assert verify_field_fate_structure(structure).structure_sha256 == structure.identity_sha256


def test_verifier_rejects_mutated_unrouted_source_occurrence(
    structure: FieldFateStructureV1,
) -> None:
    unrouted = next(
        item for item in structure.route_bindings.source_expansions if item.status == "unrouted"
    )
    source = structure.provider_sources.by_occurrence_id[unrouted.source_occurrence_id]
    changed_source = replace(source, provider_field_name=f"{source.provider_field_name}_stale")
    changed_occurrences = tuple(
        changed_source if item.occurrence_id == source.occurrence_id else item
        for item in structure.provider_sources.occurrences
    )
    changed_sources = replace(structure.provider_sources, occurrences=changed_occurrences)
    changed_expansions = tuple(
        replace(item, source_occurrence_sha256=changed_source.occurrence_sha256)
        if item.source_occurrence_id == source.occurrence_id
        else item
        for item in structure.route_bindings.source_expansions
    )
    changed_routes = replace(
        structure.route_bindings,
        source_expansions=changed_expansions,
        provider_source_inventory_sha256=changed_sources.identity_sha256,
    )
    changed_sinks = replace(
        structure.storage_sinks,
        route_binding_inventory_sha256=changed_routes.identity_sha256,
    )
    changed_lossless = tuple(
        replace(
            item,
            source_occurrence_sha256=changed_source.occurrence_sha256,
            provider_field_name=changed_source.provider_field_name,
        )
        if item.source_occurrence_id == source.occurrence_id
        else item
        for item in structure.lossless_bindings
    )
    changed_blockers = tuple(
        replace(item, source_occurrence_sha256=changed_source.occurrence_sha256)
        if item.source_occurrence_id == source.occurrence_id
        else item
        for item in structure.blockers
    )
    changed = FieldFateStructureV1(
        changed_sources,
        changed_routes,
        changed_sinks,
        changed_lossless,
        changed_blockers,
    )

    with pytest.raises(FieldFateStructureVerificationError, match="provider source"):
        verify_field_fate_structure_independently(changed)


def test_verifier_rejects_stale_authority_identity(
    structure: FieldFateStructureV1,
) -> None:
    changed_sources = replace(
        structure.provider_sources,
        independent_package_inventory_sha256="0" * 64,
    )
    changed_routes = replace(
        structure.route_bindings,
        provider_source_inventory_sha256=changed_sources.identity_sha256,
    )
    changed_sinks = replace(
        structure.storage_sinks,
        route_binding_inventory_sha256=changed_routes.identity_sha256,
    )
    changed = FieldFateStructureV1(
        changed_sources,
        changed_routes,
        changed_sinks,
        structure.lossless_bindings,
        structure.blockers,
    )

    with pytest.raises(FieldFateStructureVerificationError, match="authority digest"):
        verify_field_fate_structure_independently(changed)


def test_verifier_rejects_route_and_storage_mutation(
    structure: FieldFateStructureV1,
) -> None:
    changed_binding = replace(
        structure.route_bindings.bindings[0],
        canonical_column="stale_canonical_column",
    )
    changed_routes = replace(
        structure.route_bindings,
        bindings=(changed_binding, *structure.route_bindings.bindings[1:]),
    )
    changed_sinks = replace(
        structure.storage_sinks,
        route_binding_inventory_sha256=changed_routes.identity_sha256,
    )
    changed = FieldFateStructureV1(
        structure.provider_sources,
        changed_routes,
        changed_sinks,
        structure.lossless_bindings,
        structure.blockers,
    )

    with pytest.raises(FieldFateStructureVerificationError, match="route bindings"):
        verify_field_fate_structure_independently(changed)


def _mutated_scope_field(field, **changes):
    identity = field.identity_payload() | changes
    digest = hashlib.sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return replace(field, **changes, field_sha256=digest)


@pytest.mark.parametrize("mutation", ("omitted", "extra", "reordered", "type_drift"))
def test_independent_scope_reconstruction_rejects_mutated_route_fields(
    mutation: str,
) -> None:
    route = verifier_module.staging_route_contract_bundle().by_route_id[
        "common_all_players:stg_common_all_players:0"
    ]
    season, league = route.request_scope_storage_fields
    if mutation == "omitted":
        fields = (season,)
    elif mutation == "extra":
        fields = (
            season,
            league,
            _mutated_scope_field(
                league,
                field_ordinal=2,
                storage_column="foreign_scope",
            ),
        )
    elif mutation == "reordered":
        fields = (league, season)
    else:
        fields = (_mutated_scope_field(season, logical_type="int64"), league)
    changed = replace(route, request_scope_storage_fields=fields)

    with pytest.raises(FieldFateStructureVerificationError, match="request-scope"):
        verifier_module._expected_request_scope_field_rows(changed)


def test_independent_verifier_rejects_changed_production_injection_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.extract.base as base_module

    monkeypatch.setattr(
        base_module,
        "_SEASON_YEAR_KEYS",
        (*base_module._SEASON_YEAR_KEYS, "foreign_season"),
    )
    with pytest.raises(FieldFateStructureVerificationError, match="injection policy"):
        verifier_module._verify_production_request_scope_policy()


def test_independent_verifier_rejects_changed_production_injection_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.extract.base as base_module

    monkeypatch.setattr(
        base_module,
        "_inject_request_scope_columns",
        lambda frame, _parameters: frame,
    )
    with pytest.raises(FieldFateStructureVerificationError, match="injection behavior"):
        verifier_module._verify_production_request_scope_policy()


def test_verifier_rejects_mutated_lossless_field_binding(
    structure: FieldFateStructureV1,
) -> None:
    changed_binding = replace(
        structure.lossless_bindings[0],
        sink_authority_sha256="0" * 64,
        binding_evidence_sha256="1" * 64,
    )
    changed = FieldFateStructureV1(
        structure.provider_sources,
        structure.route_bindings,
        structure.storage_sinks,
        (changed_binding, *structure.lossless_bindings[1:]),
        structure.blockers,
    )

    with pytest.raises(FieldFateStructureVerificationError, match="lossless field"):
        verify_field_fate_structure_independently(changed)


def test_canonical_receipt_round_trip_and_recomputation_gate(
    structure: FieldFateStructureV1,
    receipt: FieldFateStructureVerificationV1,
) -> None:
    raw = canonical_verification_bytes(receipt)
    parsed = parse_field_fate_structure_verification(raw)
    assert parsed == receipt
    validate_field_fate_structure_verification(parsed, structure)

    forged = replace(receipt, structure_sha256="0" * 64)
    with pytest.raises(FieldFateStructureVerificationError, match="recomputation"):
        validate_field_fate_structure_verification(forged, structure)


def test_receipt_rejects_nonexact_checks_types_duplicates_and_noncanonical_bytes(
    receipt: FieldFateStructureVerificationV1,
) -> None:
    with pytest.raises(FieldFateStructureVerificationError, match="check set"):
        replace(receipt, checks=(*receipt.checks, "invented_check"))

    payload = receipt.to_dict()
    summary = cast("dict[str, object]", payload["summary"])
    assert isinstance(summary, dict)
    summary["route_binding_count"] = True
    bad_type = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    with pytest.raises(FieldFateStructureVerificationError, match="counts"):
        parse_field_fate_structure_verification(bad_type)

    canonical = canonical_verification_bytes(receipt)
    duplicate = canonical.replace(
        b"{",
        b'{"kind":"field_fate_structure_verification",',
        1,
    )
    with pytest.raises(FieldFateStructureVerificationError, match="repeats object key"):
        parse_field_fate_structure_verification(duplicate)
    with pytest.raises(FieldFateStructureVerificationError, match="not canonical"):
        parse_field_fate_structure_verification(canonical.rstrip(b"\n"))


def test_verifier_has_no_compiler_or_star_parent_dependency() -> None:
    source = Path(verifier_module.__file__).read_text(encoding="utf-8")
    forbidden_imports = (
        "compile_field_fate_structure",
        "nbadb.contracts.assurance",
        "nbadb.contracts.field_fate_contract",
        "nbadb.schemas.star",
        "nbadb.transform",
    )
    assert all(f"import {name}" not in source for name in forbidden_imports)
