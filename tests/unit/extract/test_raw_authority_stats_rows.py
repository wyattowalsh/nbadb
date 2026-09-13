from __future__ import annotations

import hashlib
import json

import pytest

import nbadb.extract.nba_api_adapter as adapter_module
from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_runtime_contracts,
)
from nbadb.extract.nba_api_adapter import (
    UpstreamApplicationError,
    UpstreamTransientHttpError,
    rederive_raw_authority_result_sets,
    rederive_raw_authority_stats_fallback,
    rederive_raw_authority_stats_rows,
    rederive_raw_authority_unknown_stats_response,
)


def _authority(endpoint_id: str) -> tuple[str, str]:
    contract = pinned_runtime_contracts()[endpoint_id]
    return (
        str(expected_nba_api_provider_authority()["authority_sha256"]),
        endpoint_contract_sha256(contract),
    )


def test_exact_legacy_bytes_rederive_immutable_typed_rows() -> None:
    endpoint_id = "LeagueGameLog"
    contract = pinned_runtime_contracts()[endpoint_id]
    assert contract.parser_kind == "legacy_result_sets"
    result_sets = []
    for result_index, result in enumerate(contract.result_sets):
        values: list[object] = [None] * len(result.expected_columns)
        values[0] = result_index + 1
        if len(values) > 1:
            values[1] = "one"
        result_sets.append(
            {
                "name": result.result_set_name,
                "headers": list(result.expected_columns),
                "rowSet": [values],
            }
        )
    parser_input = json.dumps(
        {"resultSets": result_sets},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    provider_sha256, contract_sha256 = _authority(endpoint_id)

    derived = rederive_raw_authority_stats_rows(
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=provider_sha256,
        endpoint_contract_sha256_value=contract_sha256,
    )

    assert len(derived) == len(contract.result_sets)
    for canonical_ordinal, item in enumerate(derived):
        assert item.result_set.canonical_index == canonical_ordinal
        assert item.result_set.provider_index == canonical_ordinal
        assert item.duplicate_name_ordinal == 0
        assert item.ordered_headers == contract.result_sets[canonical_ordinal].expected_columns
        assert type(item.rows) is tuple
        assert all(type(row) is tuple for row in item.rows)
        assert json.loads(item.rows[0][0].canonical_json) == canonical_ordinal + 1


def test_stats_raw_replayers_reject_status_error_envelope_with_valid_results() -> None:
    endpoint_id = "LeagueGameLog"
    contract = pinned_runtime_contracts()[endpoint_id]
    result_sets = [
        {
            "name": result.result_set_name,
            "headers": list(result.expected_columns),
            "rowSet": [],
        }
        for result in contract.result_sets
    ]
    payload = {"code": 500, "resultSets": result_sets}
    parser_input = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    provider_sha256, contract_sha256 = _authority(endpoint_id)

    with pytest.raises(UpstreamTransientHttpError):
        rederive_raw_authority_stats_rows(
            endpoint_id=endpoint_id,
            parser_input=parser_input,
            provider_authority_sha256=provider_sha256,
            endpoint_contract_sha256_value=contract_sha256,
        )
    with pytest.raises(UpstreamTransientHttpError):
        rederive_raw_authority_result_sets(
            source_family="stats",
            endpoint_id=endpoint_id,
            parser_input=parser_input,
            provider_authority_sha256=provider_sha256,
            endpoint_contract_sha256_value=contract_sha256,
        )

    drifted = json.loads(parser_input)
    drifted["resultSets"][0]["headers"].append("ADDITIVE")
    with pytest.raises(UpstreamTransientHttpError):
        rederive_raw_authority_stats_fallback(
            endpoint_id=endpoint_id,
            parser_input=json.dumps(drifted, separators=(",", ":")).encode("utf-8"),
            provider_authority_sha256=provider_sha256,
            endpoint_contract_sha256_value=contract_sha256,
        )


def test_custom_nested_branch_preserves_canonical_and_provider_ordinals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint_id = "BoxScoreTraditionalV3"
    contract = pinned_runtime_contracts()[endpoint_id]
    assert contract.parser_kind == "custom_nested"
    provider_sets = [
        (result.result_set_name, list(result.expected_columns), [])
        for result in reversed(contract.result_sets)
    ]
    monkeypatch.setattr(
        adapter_module,
        "_custom_data_sets",
        lambda _text, slug: (
            provider_sets
            if slug == contract.endpoint_slug
            else pytest.fail("foreign endpoint slug")
        ),
    )
    provider_sha256, contract_sha256 = _authority(endpoint_id)

    derived = rederive_raw_authority_stats_rows(
        endpoint_id=endpoint_id,
        parser_input=b"{}",
        provider_authority_sha256=provider_sha256,
        endpoint_contract_sha256_value=contract_sha256,
    )

    assert tuple(item.result_set.name for item in derived) == tuple(
        result.result_set_name for result in contract.result_sets
    )
    assert tuple(item.result_set.canonical_index for item in derived) == tuple(
        range(len(contract.result_sets))
    )
    assert tuple(item.result_set.provider_index for item in derived) == tuple(
        reversed(range(len(contract.result_sets)))
    )
    assert all(item.rows == () for item in derived)


def test_real_box_score_v3_parser_rederives_nonempty_nested_rows() -> None:
    endpoint_id = "BoxScoreTraditionalV3"
    payload = {
        "boxScoreTraditional": {
            "gameId": "0022400001",
            "homeTeam": {
                "teamId": 1,
                "teamCity": "Home",
                "teamName": "Hosts",
                "teamTricode": "HOM",
                "teamSlug": "hosts",
                "players": [
                    {
                        "personId": 10,
                        "firstName": "Exact",
                        "familyName": "Player",
                        "nameI": "E. Player",
                        "playerSlug": "exact-player",
                        "position": "G",
                        "comment": "",
                        "jerseyNum": "1",
                        "statistics": {"points": 7, "assists": 3},
                    }
                ],
                "statistics": {"points": 100},
                "starters": {"points": 60},
                "bench": {"points": 40},
            },
            "awayTeam": {
                "teamId": 2,
                "teamCity": "Away",
                "teamName": "Visitors",
                "teamTricode": "AWY",
                "teamSlug": "visitors",
                "players": [],
                "statistics": {"points": 90},
                "starters": {"points": 55},
                "bench": {"points": 35},
            },
        }
    }
    parser_input = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    provider_sha256, contract_sha256 = _authority(endpoint_id)

    derived = rederive_raw_authority_stats_rows(
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=provider_sha256,
        endpoint_contract_sha256_value=contract_sha256,
    )

    by_name = {item.result_set.name: item for item in derived}
    assert by_name["PlayerStats"].result_set.row_count == 1
    assert by_name["TeamStarterBenchStats"].result_set.row_count == 4
    assert by_name["TeamStats"].result_set.row_count == 2
    player_headers = by_name["PlayerStats"].ordered_headers
    player_values = {
        header: json.loads(cell.canonical_json)
        for header, cell in zip(
            player_headers,
            by_name["PlayerStats"].rows[0],
            strict=True,
        )
    }
    assert player_values["gameId"] == "0022400001"
    assert player_values["personId"] == 10
    assert player_values["points"] == 7


def test_custom_nested_duplicate_result_names_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint_id = "BoxScoreTraditionalV3"
    contract = pinned_runtime_contracts()[endpoint_id]
    first = contract.result_sets[0]
    provider_sets = [
        (first.result_set_name, list(first.expected_columns), []),
        (first.result_set_name, list(first.expected_columns), []),
    ]
    monkeypatch.setattr(
        adapter_module,
        "_custom_data_sets",
        lambda _text, _slug: provider_sets,
    )
    provider_sha256, contract_sha256 = _authority(endpoint_id)

    with pytest.raises(ResponseContractError, match="duplicate result-set names"):
        rederive_raw_authority_stats_rows(
            endpoint_id=endpoint_id,
            parser_input=b"{}",
            provider_authority_sha256=provider_sha256,
            endpoint_contract_sha256_value=contract_sha256,
        )


def test_stats_row_replay_rejects_foreign_contract_pin() -> None:
    endpoint_id = "LeagueGameLog"
    provider_sha256, _contract_sha256 = _authority(endpoint_id)

    with pytest.raises(ResponseContractError, match="exact pinned endpoint contract"):
        rederive_raw_authority_stats_rows(
            endpoint_id=endpoint_id,
            parser_input=b"{}",
            provider_authority_sha256=provider_sha256,
            endpoint_contract_sha256_value="f" * 64,
        )


def test_unknown_stats_response_replays_generic_nested_body() -> None:
    endpoint_id = "VideoDetails"
    provider_sha256, contract_sha256 = _authority(endpoint_id)
    parser_input = b'{"unexpected":{"nested":[1,null,true]}}'

    response = rederive_raw_authority_unknown_stats_response(
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        safe_parameters_json=(
            '{"ahead_behind_nullable":"","clutch_time_nullable":"",'
            '"context_filter_nullable":"","context_measure_detailed":"PTS",'
            '"date_from_nullable":"","date_to_nullable":"",'
            '"end_period_nullable":"","end_range_nullable":"",'
            '"game_id_nullable":"","game_segment_nullable":"",'
            '"last_n_games":"0","league_id_nullable":"00",'
            '"location_nullable":"","month":"0","opponent_team_id":0,'
            '"outcome_nullable":"","period":"0","player_id":2,'
            '"point_diff_nullable":"","position_nullable":"",'
            '"range_type_nullable":"","rookie_year_nullable":"",'
            '"season":"2024-25","season_segment_nullable":"",'
            '"season_type_all_star":"Regular Season",'
            '"start_period_nullable":"","start_range_nullable":"",'
            '"team_id":1,"vs_conference_nullable":"",'
            '"vs_division_nullable":""}'
        ),
        provider_authority_sha256=provider_sha256,
        endpoint_contract_sha256_value=contract_sha256,
    )

    assert response.endpoint_id == endpoint_id
    assert response.state == "generic_nested_json"
    assert response.occurrences == ()
    assert response.response_receipt_sha256 is None
    assert response.parser_input_sha256 == hashlib.sha256(parser_input).hexdigest()


def test_unknown_stats_response_rejects_application_error_envelope() -> None:
    endpoint_id = "VideoDetails"
    provider_sha256, contract_sha256 = _authority(endpoint_id)

    with pytest.raises(UpstreamApplicationError):
        rederive_raw_authority_unknown_stats_response(
            endpoint_id=endpoint_id,
            parser_input=b'{"message":"provider says no"}',
            safe_parameters_json="{}",
            provider_authority_sha256=provider_sha256,
            endpoint_contract_sha256_value=contract_sha256,
        )


@pytest.mark.parametrize(
    "safe_parameters_json",
    ('{ "x":1}', '{"x":1,"x":2}', '{"x":NaN}'),
)
def test_unknown_stats_response_rejects_noncanonical_or_ambiguous_parameters(
    safe_parameters_json: str,
) -> None:
    endpoint_id = "VideoDetails"
    provider_sha256, contract_sha256 = _authority(endpoint_id)

    with pytest.raises(ResponseContractError):
        rederive_raw_authority_unknown_stats_response(
            endpoint_id=endpoint_id,
            parser_input=b"{}",
            safe_parameters_json=safe_parameters_json,
            provider_authority_sha256=provider_sha256,
            endpoint_contract_sha256_value=contract_sha256,
        )
