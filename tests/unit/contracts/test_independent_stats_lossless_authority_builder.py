from __future__ import annotations

import ast
from pathlib import Path

import pytest

import nbadb.contracts.independent_stats_lossless_authority_builder as builder_module
from nbadb.contracts.independent_stats_lossless_authority_builder import (
    IndependentStatsLosslessAuthorityBuilderError,
    build_independent_stats_lossless_authorities,
)
from nbadb.contracts.stats_lossless_value_authority import (
    StatsLosslessValueAuthorityV1,
)
from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
from tests.unit.contracts.test_raw_request_authority import (
    _stats_fallback_bundle,
    _video_bundle,
)
from tests.unit.contracts.test_raw_result_cell_authority import _stats_case


def _build(variant: str = "header_drift") -> StatsLosslessValueAuthorityV1:
    bundle, _observation, _occurrences, _landings = _stats_fallback_bundle(variant)
    authorities = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    assert len(authorities) == 1
    return authorities[0]


@pytest.mark.parametrize(
    "variant",
    [
        "header_drift",
        "missing_result",
        "heterogeneous",
        "duplicate_name",
        "additive_result",
    ],
)
def test_declared_stats_drift_builds_one_exact_closed_authority(variant: str) -> None:
    bundle, observation, occurrences, landings = _stats_fallback_bundle(variant)
    authority = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )[0]
    conditional = next(item for item in landings if item.landing_semantic == "conditional_lossless")

    assert authority.manifest.raw_authority_bundle_sha256 == bundle.bundle_sha256
    assert authority.manifest.observation_sha256 == observation.attempt.observation_sha256
    assert authority.manifest.route_id == conditional.route_id
    assert authority.manifest.committed_receipt_sha256 == conditional.receipt_root_sha256
    assert tuple(item.occurrence_sha256 for item in authority.results) == tuple(
        item.occurrence_sha256 for item in occurrences
    )
    assert tuple(item.global_record_ordinal for item in authority.records) == tuple(
        range(len(authority.records))
    )
    assert authority.manifest.response_residual_record_count > 1
    assert authority.records[-authority.manifest.response_residual_record_count].record_kind == (
        "response"
    )
    assert authority.public_rows() == tuple(item.to_row() for item in authority.records)

    replayed = StatsLosslessValueAuthorityV1(
        receipt=authority.receipt,
        manifest=authority.manifest,
        expected_unit_inventory=authority.expected_unit_inventory,
        representation_assignments=authority.representation_assignments,
        results=authority.results,
        records=authority.records,
    )
    assert replayed == authority


def test_missing_expected_result_is_normalized_without_invented_header_records() -> None:
    authority = _build("missing_result")
    missing = authority.results[-1]
    partition = authority.records[
        missing.first_global_record_ordinal : missing.first_global_record_ordinal
        + missing.record_count
    ]

    assert missing.presence == "missing"
    assert missing.header_record_count == 0
    assert missing.raw_row_occurrence_count == 0
    assert tuple(item.record_kind for item in partition) == (
        "missing_expected",
        "raw_headers",
        "raw_rows",
    )
    assert partition[1].value()
    assert partition[2].value() == []


def test_unknown_legacy_results_preserve_duplicates_unicode_and_large_integers() -> None:
    payload = {
        "resultSets": [
            {
                "name": "Extra",
                "headers": ["VALUE"],
                "rowSet": [["café"], [(1 << 63) - 1]],
            },
            {
                "name": "Extra",
                "headers": ["VALUE"],
                "rowSet": [[True]],
            },
        ]
    }
    bundle, observation, occurrences, _landings = _video_bundle("VideoEvents", payload)
    authority = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )[0]

    assert [(item.result_set_name, item.result_set_occurrence) for item in authority.results] == [
        ("Extra", 0),
        ("Extra", 1),
    ]
    assert tuple(item.occurrence_sha256 for item in authority.results) == tuple(
        item.occurrence_sha256 for item in occurrences
    )
    assert authority.manifest.provider_result_set_count == 2
    assert authority.manifest.expected_result_set_count == 0
    assert authority.records[0].endpoint_id == observation.attempt.endpoint_id
    canonical_values = tuple(
        item.canonical_json for item in authority.records if item.canonical_json is not None
    )
    assert '"café"' in canonical_values
    assert str((1 << 63) - 1) in canonical_values
    assert "heterogeneous_column" in authority.records[0].global_anomaly_codes_json


def test_response_mode_authority_matches_the_pinned_runtime_contract() -> None:
    declared = _build("header_drift")
    declared_contract = pinned_runtime_contracts()[declared.manifest.endpoint_id]
    assert (
        declared.records[0].response_mode_authority_sha256
        == declared_contract.response_contract.authority_sha256
    )

    bundle, _observation, _occurrences, _landings = _video_bundle(
        "VideoEvents",
        {"resultSets": [{"name": "Extra", "headers": ["A"], "rowSet": [[1]]}]},
    )
    unknown = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )[0]
    unknown_contract = pinned_runtime_contracts()[unknown.manifest.endpoint_id]
    assert (
        unknown.records[0].response_mode_authority_sha256
        == unknown_contract.response_contract.authority_sha256
    )


def test_stats_without_a_conditional_landing_produce_no_side_authority() -> None:
    bundle, _cells = _stats_case()

    assert (
        build_independent_stats_lossless_authorities(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        )
        == ()
    )


def test_raw_occurrence_drift_is_rejected_against_independent_body_decoding() -> None:
    bundle, _observation, _occurrences, _landings = _stats_fallback_bundle("header_drift")
    object.__setattr__(bundle.occurrences[0], "output_sha256", "f" * 64)

    with pytest.raises(
        IndependentStatsLosslessAuthorityBuilderError,
        match="failed exact independent replay",
    ):
        build_independent_stats_lossless_authorities(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        )


def test_external_bundle_pin_is_checked_before_decoder_traversal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _observation, _occurrences, _landings = _stats_fallback_bundle("header_drift")

    def forbidden_decode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("decoder must not run")

    monkeypatch.setattr(builder_module, "decode_stats_projection_response", forbidden_decode)
    with pytest.raises(
        IndependentStatsLosslessAuthorityBuilderError,
        match="external bundle pin",
    ):
        build_independent_stats_lossless_authorities(
            bundle,
            expected_raw_authority_bundle_sha256="0" * 64,
        )


def test_hostile_decoder_errors_are_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, _observation, _occurrences, _landings = _stats_fallback_bundle("header_drift")
    secret = "Bearer hostile-token-12345678901234567890 /Users/private/path"

    def hostile_decode(*_args: object, **_kwargs: object) -> object:
        raise ValueError(secret)

    monkeypatch.setattr(builder_module, "decode_stats_projection_response", hostile_decode)
    with pytest.raises(IndependentStatsLosslessAuthorityBuilderError) as caught:
        build_independent_stats_lossless_authorities(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        )
    assert secret not in str(caught.value)
    assert "Bearer" not in str(caught.value)
    assert "/Users/" not in str(caught.value)


def test_hostile_decoder_cannot_spoof_the_builder_error_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _observation, _occurrences, _landings = _stats_fallback_bundle("header_drift")
    secret = "Bearer same-class-hostile-token /Users/private/same-class"

    def hostile_decode(*_args: object, **_kwargs: object) -> object:
        raise IndependentStatsLosslessAuthorityBuilderError(secret)

    monkeypatch.setattr(builder_module, "decode_stats_projection_response", hostile_decode)
    with pytest.raises(IndependentStatsLosslessAuthorityBuilderError) as caught:
        build_independent_stats_lossless_authorities(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        )
    assert str(caught.value) == (
        "stats-lossless authority construction failed exact independent replay"
    )
    assert secret not in str(caught.value)


def test_generic_unknown_response_is_preserved_as_zero_result_residual_authority() -> None:
    bundle, _observation, _occurrences, _landings = _video_bundle(
        "VideoEvents",
        {"mystery": {"café": [(1 << 63) - 1]}},
    )

    authority = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )[0]

    assert authority.results == ()
    assert authority.manifest.provider_result_set_count == 0
    assert authority.manifest.expected_result_set_count == 0
    assert authority.manifest.occurrence_count == 0
    assert authority.records[0].response_state == "generic_nested_json"
    assert authority.manifest.response_residual_record_count == len(authority.records)
    canonical_values = tuple(
        item.canonical_json for item in authority.records if item.canonical_json is not None
    )
    assert "café" in tuple(
        item.object_key for item in authority.records if item.object_key is not None
    )
    assert str((1 << 63) - 1) in canonical_values


def test_module_is_import_independent_from_runtime_parser_and_projection_surfaces() -> None:
    source_path = Path(builder_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    forbidden = (
        "nba_api",
        "polars",
        "nbadb.extract",
        "nbadb.load",
        "nbadb.orchestrate",
        "nbadb.schemas",
        "nbadb.contracts.public_value_authority_adapter",
        "nbadb.contracts.typed_field_value_receipt",
    )
    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported
        for prefix in forbidden
    )


def test_raw_children_are_grouped_once_without_per_observation_rescans() -> None:
    source_path = Path(builder_module.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    group_source = ast.get_source_segment(source, functions["_group_observation_children"])
    build_one_source = ast.get_source_segment(source, functions["_build_one"])
    public_source = ast.get_source_segment(
        source,
        functions["build_independent_stats_lossless_authorities"],
    )

    assert group_source is not None
    assert build_one_source is not None
    assert public_source is not None
    assert group_source.count("bundle.occurrences") == 1
    assert group_source.count("bundle.landings") == 1
    assert "sorted(" not in group_source
    assert "bundle.occurrences" not in build_one_source
    assert "bundle.landings" not in build_one_source
    assert public_source.count("_group_observation_children(bundle)") == 1
