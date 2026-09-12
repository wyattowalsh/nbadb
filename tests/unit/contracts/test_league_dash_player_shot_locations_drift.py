from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from importlib import resources

import pytest

import nbadb.contracts.league_dash_player_shot_locations_drift as drift
from nbadb.contracts.league_dash_player_shot_locations_drift import (
    DECLARED_HEADER_COLUMNS_26,
    LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_BLOCKERS,
    PINNED_NBA_API_COMMIT_SHA,
    PINNED_NBA_API_VERSION,
    RENDERED_HEADER_COLUMNS_30,
    RENDERED_ONLY_COLUMNS_4,
    LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
    LeagueDashPlayerShotLocationsDriftError,
    MaterializerBehaviorProofV1,
    build_pinned_league_dash_player_shot_locations_drift_authority,
    load_packaged_league_dash_player_shot_locations_drift_authority,
)
from nbadb.core.nba_api_contract import structured_data_set_columns


@pytest.fixture
def authority() -> LeagueDashPlayerShotLocationsContractDriftAuthorityV1:
    return build_pinned_league_dash_player_shot_locations_drift_authority()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _declared_header() -> list[dict[str, object]]:
    return [
        {
            "columnNames": [
                "Restricted Area",
                "In The Paint (Non-RA)",
                "Mid-Range",
                "Left Corner 3",
                "Right Corner 3",
                "Above the Break 3",
                "Backcourt",
            ],
            "columnSpan": 3,
            "columnsToSkip": 5,
            "name": "SHOT_CATEGORY",
        },
        {
            "columnNames": [
                "PLAYER_ID",
                "PLAYER_NAME",
                "TEAM_ID",
                "TEAM_ABBREVIATION",
                "AGE",
                *[metric for _ in range(7) for metric in ("FGM", "FGA", "FG_PCT")],
            ],
            "columnSpan": 1,
            "name": "columns",
        },
    ]


def test_pinned_authority_records_exact_upstream_identity_and_evidence(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    assert authority.endpoint == "LeagueDashPlayerShotLocations"
    assert authority.dataset == "ShotLocations"
    assert authority.nba_api_version == PINNED_NBA_API_VERSION == "1.11.4"
    assert (
        authority.nba_api_commit_sha
        == PINNED_NBA_API_COMMIT_SHA
        == "e0295f8333c3496b5754dbffbdf4c1c1dee3c2f4"
    )
    assert authority.endpoint_source_receipt.content_sha256 == (
        "f24d3bae0d1bca5e639899080c560a3f1130cda8fb2fdd71d63587e514fc0d5f"
    )
    assert authority.endpoint_docs_receipt.content_sha256 == (
        "0d3012ca76b56f0fa19c51db58f108cafcbeeee0a5eab4e89e56da90e6f1aa86"
    )
    assert authority.rendered_output_receipt.content_sha256 == (
        "b92113d4bc84a6dea1e11e858acefc3c78a83bd9d2377b51cea94f0269b153f3"
    )
    assert authority.materializer_proof.source_sha256 == (
        "0bfb14cdef84f7e284136aa546c89a5d1b6ed60e813603d6d45cf287c8294c71"
    )
    assert authority.materializer_proof.function_ast_sha256 == (
        "fba1ee23a4588411b3f479fc5c6139eace93793ee89648069d691e829d5cbdb3"
    )


def test_exact_declared_26_matches_shared_structured_header_algorithm() -> None:
    assert len(DECLARED_HEADER_COLUMNS_26) == 26
    assert structured_data_set_columns(_declared_header()) == DECLARED_HEADER_COLUMNS_26
    assert DECLARED_HEADER_COLUMNS_26[:5] == (
        "PLAYER_ID",
        "PLAYER_NAME",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "AGE",
    )
    assert DECLARED_HEADER_COLUMNS_26[-3:] == (
        "backcourt_fgm",
        "backcourt_fga",
        "backcourt_fg_pct",
    )


def test_exact_rendered_30_and_four_field_difference(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    assert len(RENDERED_HEADER_COLUMNS_30) == 30
    assert len(set(RENDERED_HEADER_COLUMNS_30)) == 30
    assert tuple(item.flattened_name for item in authority.rendered_only_inventory) == (
        RENDERED_ONLY_COLUMNS_4
    )
    assert RENDERED_ONLY_COLUMNS_4 == (
        "NICKNAME",
        "corner_3_fgm",
        "corner_3_fga",
        "corner_3_fg_pct",
    )
    assert authority.declared_only_inventory == ()
    assert len(authority.common_mapping) == 26
    assert tuple(item[0] for item in authority.common_mapping) == tuple(range(26))
    assert tuple(item[3] for item in authority.common_mapping) == DECLARED_HEADER_COLUMNS_26


def test_rendered_page_is_never_represented_as_raw_grouped_header(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    assert all(item.is_raw_response_header is False for item in authority.rendered_inventory)
    assert {item.evidence_kind for item in authority.rendered_inventory} == {
        "rendered_documentation_output"
    }
    assert authority.raw_capture_authority_sha256 is None
    assert authority.observed_header_signature_sha256 is None
    assert "group_span" not in authority.to_dict()
    assert "raw_response_header" not in authority.to_dict()


def test_materializer_proof_is_behavioral_and_not_a_caller_boolean(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    proof = authority.materializer_proof
    assert proof.symbol == "Endpoint.DataSet.get_data_frame"
    assert proof.behavior == ("dataframe_columns_and_rows_directly_from_response_headers_and_data")
    assert proof.proof_sha256 == (
        "7d7f02777a454421d82dba9bcfb420357488ccce5450899b70d4ce0d2990f4e5"
    )
    assert "derives_columns" not in proof.to_dict()


def test_authority_is_terminal_red_with_exact_blockers(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    assert authority.state == "awaiting_captured_raw_response"
    assert authority.public_model_state == "red_blocked"
    assert authority.fixed_superset_staging_state == "red_blocked"
    assert tuple(sorted(LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_BLOCKERS)) == (
        LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_BLOCKERS
    )
    assert set(LEAGUE_DASH_PLAYER_SHOT_LOCATIONS_BLOCKERS) == {
        "corner_3_semantics_unproven",
        "current_runtime_signature_unproven",
        "field_presence_nullability_unproven",
        "raw_response_headers_unobserved",
        "rendered_group_structure_unproven",
        "row_identity_cardinality_unproven",
    }
    wire = authority.to_dict()
    assert "authority_admitted" not in wire
    assert "review_gate_green" not in wire
    assert "release_gate_green" not in wire
    assert "formula" not in wire
    assert "rank" not in wire


def test_generic_zone_fields_are_not_aliases_or_inputs() -> None:
    forbidden = {
        "shot_zone_basic",
        "shot_zone_area",
        "shot_zone_range",
        "fgm",
        "fga",
        "fg_pct",
        "season_fgm_rank",
    }
    assert forbidden.isdisjoint(DECLARED_HEADER_COLUMNS_26)
    assert forbidden.isdisjoint(RENDERED_HEADER_COLUMNS_30)


def test_domain_separated_roots_and_golden_authority(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    assert authority.declared_source_inventory_sha256 == (
        "c0a6fc30b2ff73c7341bb206a9054d0ce6083676f70227cac1aae712e5497199"
    )
    assert authority.declared_docs_inventory_sha256 == (authority.declared_source_inventory_sha256)
    assert authority.rendered_inventory_sha256 == (
        "3f9601aff68e829d1ddc34443bdceee226711f9603e2e3b7d454a542499323e2"
    )
    assert authority.common_mapping_sha256 == (
        "2db65b71f74958291fce8bef98a419ee77f5a5633209a80c4e2f8c68dd91667a"
    )
    assert authority.rendered_only_sha256 != authority.declared_only_sha256
    assert authority.evidence_root_sha256 == (
        "7fde9dec2a27aefbaac3a121623508a644cccfab11bd2082cb0590411677c519"
    )
    assert authority.authority_sha256 == (
        "18caccb400de1472041ce9236e46b5eb8ce669c9908c3e683c412b05f75c1008"
    )


def test_canonical_round_trip_is_exact_and_packaged_resource_matches(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    raw = authority.to_canonical_bytes()
    assert len(raw) == 19_012
    assert (
        LeagueDashPlayerShotLocationsContractDriftAuthorityV1.from_canonical_bytes(raw) == authority
    )
    assert load_packaged_league_dash_player_shot_locations_drift_authority() == authority


def test_packaged_resource_has_one_exact_digest_bound_lf_wrapper(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    packaged_raw = (
        resources.files("nbadb.contracts")
        .joinpath("data/league-dash-player-shot-locations-drift-v1.json")
        .read_bytes()
    )
    assert len(packaged_raw) == 19_013
    assert hashlib.sha256(packaged_raw).hexdigest() == (
        "ee6aad0fae39f0a45548686ba81afa7e413ff574e3611052b435ba01c6d4c97c"
    )
    assert packaged_raw.endswith(b"\n")
    assert not packaged_raw.endswith(b"\n\n")
    assert packaged_raw[:-1] == authority.to_canonical_bytes()
    assert drift._decode_packaged_authority_resource(packaged_raw) == authority


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value[:-1],
        lambda value: value + b"\n",
        lambda value: value[:-1] + b"\r\n",
        lambda value: bytes([value[0] ^ 1]) + value[1:],
    ],
)
def test_packaged_resource_rejects_missing_extra_crlf_and_same_size_mutation(
    mutation: object,
) -> None:
    packaged_raw = (
        resources.files("nbadb.contracts")
        .joinpath("data/league-dash-player-shot-locations-drift-v1.json")
        .read_bytes()
    )
    with pytest.raises(LeagueDashPlayerShotLocationsDriftError, match="exact wrapper pin"):
        drift._decode_packaged_authority_resource(mutation(packaged_raw))  # type: ignore[operator]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: replace(value, state="resolved"),
        lambda value: replace(value, public_model_state="green"),
        lambda value: replace(value, fixed_superset_staging_state="green"),
        lambda value: replace(value, raw_capture_authority_sha256="0" * 64),
        lambda value: replace(value, observed_header_signature_sha256="0" * 64),
        lambda value: replace(
            value,
            endpoint_source_receipt=value.endpoint_docs_receipt,
            endpoint_docs_receipt=value.endpoint_source_receipt,
        ),
        lambda value: replace(
            value,
            declared_docs_inventory=tuple(reversed(value.declared_docs_inventory)),
        ),
        lambda value: replace(
            value,
            rendered_inventory=tuple(reversed(value.rendered_inventory)),
        ),
    ],
)
def test_constructor_rejects_green_capture_swapped_and_reordered_state(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
    mutation: object,
) -> None:
    with pytest.raises(LeagueDashPlayerShotLocationsDriftError):
        mutation(authority)  # type: ignore[operator]


def test_materializer_proof_rejects_foreign_source_symbol_mode_and_pin() -> None:
    proof = MaterializerBehaviorProofV1()
    mutations = (
        {"source_sha256": "0" * 64},
        {"function_ast_sha256": "0" * 64},
        {"symbol": "Endpoint.DataSet.other"},
        {"ast_parser_id": "caller_boolean"},
        {"behavior": "derives_columns_false"},
        {"nba_api_version": "1.11.3"},
        {"nba_api_commit_sha": "0" * 40},
    )
    for values in mutations:
        with pytest.raises(LeagueDashPlayerShotLocationsDriftError):
            replace(proof, **values)  # type: ignore[arg-type]


def test_canonical_wire_rejects_missing_extra_green_and_resealed_mutations(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    original = authority.to_dict()
    mutations: list[dict[str, object]] = []

    missing = copy.deepcopy(original)
    missing.pop("blocker_codes")
    mutations.append(missing)

    extra = copy.deepcopy(original)
    extra["release_gate_green"] = True
    mutations.append(extra)

    green = copy.deepcopy(original)
    green["public_model_state"] = "green_ok"
    mutations.append(green)

    captured = copy.deepcopy(original)
    captured["raw_capture_authority_sha256"] = "0" * 64
    mutations.append(captured)

    raw_claim = copy.deepcopy(original)
    rendered = raw_claim["rendered_inventory"]
    assert isinstance(rendered, list)
    assert isinstance(rendered[0], dict)
    rendered[0]["is_raw_response_header"] = True
    mutations.append(raw_claim)

    resealed = copy.deepcopy(original)
    resealed["authority_sha256"] = "0" * 64
    mutations.append(resealed)

    for payload in mutations:
        with pytest.raises(LeagueDashPlayerShotLocationsDriftError):
            LeagueDashPlayerShotLocationsContractDriftAuthorityV1.from_canonical_bytes(
                _canonical(payload)
            )


def test_canonical_decoder_rejects_noncanonical_duplicate_and_nonfinite_input(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
) -> None:
    raw = authority.to_canonical_bytes()
    with pytest.raises(LeagueDashPlayerShotLocationsDriftError):
        LeagueDashPlayerShotLocationsContractDriftAuthorityV1.from_canonical_bytes(b" " + raw)

    duplicate_prefix = b'{"a":1,"a":1,"pad":"'
    duplicate = duplicate_prefix + b"x" * (len(raw) - len(duplicate_prefix) - 2) + b'"}'
    assert len(duplicate) == len(raw)
    with pytest.raises(LeagueDashPlayerShotLocationsDriftError, match="duplicate JSON key"):
        LeagueDashPlayerShotLocationsContractDriftAuthorityV1.from_canonical_bytes(duplicate)

    nonfinite_prefix = b'{"a":NaN,"pad":"'
    nonfinite = nonfinite_prefix + b"x" * (len(raw) - len(nonfinite_prefix) - 2) + b'"}'
    assert len(nonfinite) == len(raw)
    with pytest.raises(LeagueDashPlayerShotLocationsDriftError, match="non-finite"):
        LeagueDashPlayerShotLocationsContractDriftAuthorityV1.from_canonical_bytes(nonfinite)


def test_canonical_decoder_has_a_pre_materialization_exact_size_gate(
    authority: LeagueDashPlayerShotLocationsContractDriftAuthorityV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _unexpected_loads(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("json.loads must not run")

    monkeypatch.setattr(drift.json, "loads", _unexpected_loads)
    with pytest.raises(LeagueDashPlayerShotLocationsDriftError, match="exact pinned"):
        LeagueDashPlayerShotLocationsContractDriftAuthorityV1.from_canonical_bytes(
            authority.to_canonical_bytes() + b"x"
        )
    assert called is False


def test_compiler_rejects_foreign_bytes_before_any_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _unexpected_parser(raw: bytes) -> object:
        nonlocal called
        called = True
        return raw

    monkeypatch.setattr(drift, "_parse_endpoint_source", _unexpected_parser)
    with pytest.raises(LeagueDashPlayerShotLocationsDriftError, match="byte count"):
        drift.compile_pinned_league_dash_player_shot_locations_drift_authority(
            endpoint_source_bytes=b"foreign",
            endpoint_docs_bytes=b"foreign",
            rendered_output_bytes=b"foreign",
            materializer_source_bytes=b"foreign",
        )
    assert called is False


def test_new_authority_has_no_raw_authority_v2_dependency_or_mutation_surface() -> None:
    source = drift.__file__
    assert source is not None
    raw = open(source, encoding="utf-8").read()  # noqa: PTH123, SIM115
    assert "raw_request_authority" not in raw
    assert "RawRequestAuthorityBundleV2" not in raw
    assert "RAW_REQUEST_AUTHORITY_SCHEMA_VERSION" not in raw
