from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.contracts.raw_request_authority import canonical_semantic_parameters
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_runtime_contracts,
)
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    BronzeCaptureStore,
    BronzeLimits,
    ParserInputContext,
    ResultSetReceipt,
)
from nbadb.extract.nba_api_adapter import (
    NbaApiCaptureContract,
    RawAuthorityResultSetDerivation,
    rederive_raw_authority_result_sets,
    rederive_raw_authority_unknown_stats_response,
)
from nbadb.extract.raw_request_capture import (
    PendingResultOccurrenceV2,
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
    RawRequestCaptureContract,
    wrap_raw_request_capture_contract,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


_SOURCE_SHA = "a" * 40
_SEMANTIC_REQUEST_SHA256 = "1" * 64
_LOGICAL_INVOCATION_SHA256 = "2" * 64
_SCOPE_SHA256 = "3" * 64
_PROVIDER_AUTHORITY_SHA256 = cast(
    "str",
    expected_nba_api_provider_authority()["authority_sha256"],
)
_TEAM_FIELDS = ("teamId", "teamCity", "teamName", "teamTricode", "teamSlug")
_PLAYER_FIELDS = (
    "personId",
    "firstName",
    "familyName",
    "nameI",
    "playerSlug",
    "position",
    "comment",
    "jerseyNum",
)


def _parser_input(payload: object) -> bytes:
    return json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _wire_parameters(
    endpoint_id: str,
    semantic_parameters: Mapping[str, object],
) -> dict[str, object]:
    query_names = dict(pinned_runtime_contracts()[endpoint_id].parameter_query_names)
    return {query_names[name]: value for name, value in semantic_parameters.items()}


def _capture(
    root: Path,
    *,
    endpoint_id: str,
    semantic_parameters: Mapping[str, object],
) -> tuple[RawRequestCaptureContract, BronzeCaptureStore]:
    contract = pinned_runtime_contracts()[endpoint_id]
    contract_sha256 = endpoint_contract_sha256(contract)
    _, _, provider_request_sha256 = canonical_semantic_parameters(
        "stats",
        endpoint_id,
        semantic_parameters,
    )
    store = BronzeCaptureStore(
        root / "private" / "bronze",
        public_roots=(root / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=1_000_000,
            max_generation_stored_bytes=2_000_000,
            minimum_free_bytes=1,
        ),
    )
    private = NbaApiCaptureContract(
        sink=store,
        context=ParserInputContext(
            attempt_id="stats-authority-attempt-1",
            workflow_run_id=101,
            workflow_run_attempt=1,
            chain_id="chain-1",
            lane_id="lane-1",
            semantic_source_sha=_SOURCE_SHA,
        ),
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        endpoint_contract_sha256=contract_sha256,
    )
    public = RawRequestCaptureContextV2(
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        source_sha=_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain-1",
        lane_id="lane-1",
        provider_calls=(
            RawProviderCallContextV2(
                request_ordinal=0,
                semantic_request_sha256=_SEMANTIC_REQUEST_SHA256,
                logical_invocation_sha256=_LOGICAL_INVOCATION_SHA256,
                provider_call_role="primary",
                provider_call_ordinal=0,
                source_family="stats",
                endpoint_id=endpoint_id,
                provider_request_sha256=provider_request_sha256,
                endpoint_contract_sha256=contract_sha256,
                scope_sha256=_SCOPE_SHA256,
            ),
        ),
    )
    return wrap_raw_request_capture_contract(private, public), store


def _declared_derivations(
    endpoint_id: str,
    parser_input: bytes,
) -> tuple[RawAuthorityResultSetDerivation, ...]:
    contract = pinned_runtime_contracts()[endpoint_id]
    return rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        endpoint_contract_sha256_value=endpoint_contract_sha256(contract),
    )


def _unknown_occurrences(
    endpoint_id: str,
    parser_input: bytes,
    semantic_parameters: Mapping[str, object],
) -> tuple[PendingResultOccurrenceV2, ...]:
    contract = pinned_runtime_contracts()[endpoint_id]
    safe_parameters_json, _, _ = canonical_semantic_parameters(
        "stats",
        endpoint_id,
        semantic_parameters,
    )
    response = rederive_raw_authority_unknown_stats_response(
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        safe_parameters_json=safe_parameters_json,
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        endpoint_contract_sha256_value=endpoint_contract_sha256(contract),
    )
    duplicate_names: dict[str, int] = {}
    results: list[PendingResultOccurrenceV2] = []
    for occurrence in response.occurrences:
        duplicate_ordinal = duplicate_names.get(occurrence.name, 0)
        duplicate_names[occurrence.name] = duplicate_ordinal + 1
        results.append(
            PendingResultOccurrenceV2(
                result_set=occurrence.receipt,
                duplicate_name_ordinal=duplicate_ordinal,
                ordered_headers=occurrence.headers,
            )
        )
    return tuple(results)


def _record_success(
    capture: RawRequestCaptureContract,
    *,
    endpoint_id: str,
    semantic_parameters: Mapping[str, object],
    parser_input: bytes,
    result_sets: Sequence[ResultSetReceipt],
) -> str:
    contract = pinned_runtime_contracts()[endpoint_id]
    request = capture.begin_request()
    captured = capture.sink.store_parser_input(
        parser_input.decode("utf-8", errors="strict"),
        representation=PARSER_INPUT_REPRESENTATION,
    )
    receipt = capture.sink.record_response_attempt(
        context=request,
        transport_kind="http_response",
        source_family="stats",
        endpoint_id=endpoint_id,
        endpoint_slug=contract.endpoint_slug,
        parameters=_wire_parameters(endpoint_id, semantic_parameters),
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        contract_sha256=endpoint_contract_sha256(contract),
        status_code=200,
        captured=captured,
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        result_sets=result_sets,
    )
    capture.record_receipt(request, receipt, successful=True)
    return receipt


def _assert_exact_pending_results(
    actual: tuple[PendingResultOccurrenceV2, ...],
    expected: tuple[PendingResultOccurrenceV2, ...],
) -> None:
    assert actual == expected
    assert tuple(
        (
            item.result_set.name,
            item.result_set.provider_index,
            item.result_set.canonical_index,
            item.duplicate_name_ordinal,
            item.ordered_headers,
        )
        for item in actual
    ) == tuple(
        (
            item.result_set.name,
            item.result_set.provider_index,
            item.result_set.canonical_index,
            item.duplicate_name_ordinal,
            item.ordered_headers,
        )
        for item in expected
    )


def _marker(prefix: str, fields: tuple[str, ...]) -> dict[str, object]:
    return {field: f"{prefix}:{field}" for field in fields}


def _box_score_advanced_payload() -> dict[str, object]:
    contract = pinned_runtime_contracts()["BoxScoreAdvancedV3"]
    routes = {result.result_set_name: result.expected_columns for result in contract.result_sets}
    player_statistics = routes["PlayerStats"][1 + len(_TEAM_FIELDS) + len(_PLAYER_FIELDS) :]
    team_statistics = routes["TeamStats"][1 + len(_TEAM_FIELDS) :]

    def team(side: str) -> dict[str, object]:
        return {
            **_marker(side, _TEAM_FIELDS),
            "players": [
                {
                    **_marker(f"{side}-player", _PLAYER_FIELDS),
                    "statistics": _marker(
                        f"{side}-player-stat",
                        player_statistics,
                    ),
                }
            ],
            "statistics": _marker(f"{side}-team-stat", team_statistics),
        }

    return {
        "meta": {"code": 200},
        "boxScoreAdvanced": {
            "gameId": "0022400001",
            "homeTeam": team("home"),
            "awayTeam": team("away"),
        },
    }


def _gravity_leaders_payload() -> dict[str, object]:
    headers = pinned_runtime_contracts()["GravityLeaders"].result_sets[0].expected_columns
    return {"leaders": [_marker("leader", headers)]}


@pytest.mark.parametrize(
    "raw_headers",
    [
        pytest.param({"A": 1}, id="mapping-header-container"),
        pytest.param(["A", 7, "B"], id="mixed-header-sequence"),
    ],
)
def test_declared_legacy_fallback_pending_authority_preserves_unsupported_headers(
    tmp_path: Path,
    raw_headers: object,
) -> None:
    endpoint_id = "CommonTeamYears"
    semantic_parameters = {"league_id": "00"}
    parser_input = _parser_input(
        {
            "resultSets": [
                {
                    "name": "TeamYears",
                    "headers": raw_headers,
                    "rowSet": [[1, 2, 3]],
                }
            ]
        }
    )
    derivations = _declared_derivations(endpoint_id, parser_input)
    expected = tuple(
        PendingResultOccurrenceV2(
            result_set=item.result_set,
            duplicate_name_ordinal=item.duplicate_name_ordinal,
            ordered_headers=item.ordered_headers,
        )
        for item in derivations
    )
    capture, store = _capture(
        tmp_path,
        endpoint_id=endpoint_id,
        semantic_parameters=semantic_parameters,
    )
    try:
        receipt = _record_success(
            capture,
            endpoint_id=endpoint_id,
            semantic_parameters=semantic_parameters,
            parser_input=parser_input,
            result_sets=tuple(item.result_set for item in derivations),
        )

        snapshot = capture.sink.snapshot()
        assert snapshot.issues == snapshot.observations == ()
        assert len(snapshot.objects) == len(snapshot.pending_successes) == 1
        pending = snapshot.pending_successes[0]
        assert pending.private_receipt_sha256 == receipt
        _assert_exact_pending_results(pending.results, expected)
        assert [
            (
                item.result_set.provider_index,
                item.result_set.canonical_index,
                item.duplicate_name_ordinal,
                item.ordered_headers,
            )
            for item in pending.results
        ] == [(0, None, 0, ())]
    finally:
        store.close()


@pytest.mark.parametrize(
    ("endpoint_id", "semantic_parameters", "payload", "expected_ordinals"),
    [
        pytest.param(
            "BoxScoreAdvancedV3",
            {"game_id": "0022400001"},
            _box_score_advanced_payload(),
            ((0, 0, 0), (1, 1, 0)),
            id="multi-result",
        ),
        pytest.param(
            "GravityLeaders",
            {
                "league_id": "00",
                "season": "2024-25",
                "season_type_all_star": "Regular Season",
            },
            _gravity_leaders_payload(),
            ((0, 0, 0),),
            id="single-result",
        ),
    ],
)
def test_custom_nested_success_uses_exact_rederived_result_authority(
    tmp_path: Path,
    endpoint_id: str,
    semantic_parameters: Mapping[str, object],
    payload: object,
    expected_ordinals: tuple[tuple[int, int, int], ...],
) -> None:
    parser_input = _parser_input(payload)
    derivations = _declared_derivations(endpoint_id, parser_input)
    expected = tuple(
        PendingResultOccurrenceV2(
            result_set=item.result_set,
            duplicate_name_ordinal=item.duplicate_name_ordinal,
            ordered_headers=item.ordered_headers,
        )
        for item in derivations
    )
    capture, store = _capture(
        tmp_path,
        endpoint_id=endpoint_id,
        semantic_parameters=semantic_parameters,
    )
    try:
        receipt = _record_success(
            capture,
            endpoint_id=endpoint_id,
            semantic_parameters=semantic_parameters,
            parser_input=parser_input,
            result_sets=tuple(item.result_set for item in derivations),
        )

        snapshot = capture.sink.snapshot()
        assert snapshot.issues == snapshot.observations == ()
        assert len(snapshot.objects) == len(snapshot.pending_successes) == 1
        pending = snapshot.pending_successes[0]
        assert pending.private_receipt_sha256 == receipt
        _assert_exact_pending_results(pending.results, expected)
        assert (
            tuple(
                (
                    item.result_set.provider_index,
                    item.result_set.canonical_index,
                    item.duplicate_name_ordinal,
                )
                for item in pending.results
            )
            == expected_ordinals
        )
        assert tuple(item.ordered_headers for item in pending.results) == tuple(
            result.expected_columns
            for result in pinned_runtime_contracts()[endpoint_id].result_sets
        )
    finally:
        store.close()


def test_unknown_legacy_duplicate_results_preserve_provider_and_duplicate_ordinals(
    tmp_path: Path,
) -> None:
    endpoint_id = "VideoEvents"
    semantic_parameters = {"game_id": "0022400001", "game_event_id": 7}
    parser_input = _parser_input(
        {
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
                {"name": "Stats", "headers": ["B"], "rowSet": [[2]]},
            ]
        }
    )
    expected = _unknown_occurrences(endpoint_id, parser_input, semantic_parameters)
    capture, store = _capture(
        tmp_path,
        endpoint_id=endpoint_id,
        semantic_parameters=semantic_parameters,
    )
    try:
        receipt = _record_success(
            capture,
            endpoint_id=endpoint_id,
            semantic_parameters=semantic_parameters,
            parser_input=parser_input,
            result_sets=tuple(item.result_set for item in expected),
        )

        snapshot = capture.sink.snapshot()
        assert snapshot.issues == snapshot.observations == ()
        pending = snapshot.pending_successes[0]
        assert pending.private_receipt_sha256 == receipt
        _assert_exact_pending_results(pending.results, expected)
        assert [
            (
                item.result_set.name,
                item.result_set.provider_index,
                item.result_set.canonical_index,
                item.duplicate_name_ordinal,
                item.ordered_headers,
            )
            for item in pending.results
        ] == [
            ("Stats", 0, None, 0, ("A",)),
            ("Stats", 1, None, 1, ("B",)),
        ]
    finally:
        store.close()


@pytest.mark.parametrize(
    "tamper_kind",
    ["receipt", "order", "headers", "duplicate-name-ordinal"],
)
def test_unknown_legacy_duplicate_result_authority_tampering_fails_closed(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    endpoint_id = "VideoEvents"
    semantic_parameters = {"game_id": "0022400001", "game_event_id": 7}
    parser_input = _parser_input(
        {
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
                {"name": "Stats", "headers": ["B"], "rowSet": [[2]]},
            ]
        }
    )
    expected = _unknown_occurrences(endpoint_id, parser_input, semantic_parameters)
    exact = tuple(item.result_set for item in expected)
    if tamper_kind == "receipt":
        result_sets = (
            exact[0],
            replace(exact[1], normalized_output_sha256="f" * 64),
        )
    elif tamper_kind == "order":
        result_sets = (
            replace(exact[1], provider_index=0),
            replace(exact[0], provider_index=1),
        )
    elif tamper_kind == "headers":
        result_sets = (
            exact[0],
            replace(exact[1], headers_sha256="f" * 64),
        )
    else:
        result_sets = (
            exact[0],
            replace(exact[1], name="Other"),
        )
    capture, store = _capture(
        tmp_path,
        endpoint_id=endpoint_id,
        semantic_parameters=semantic_parameters,
    )
    try:
        receipt = _record_success(
            capture,
            endpoint_id=endpoint_id,
            semantic_parameters=semantic_parameters,
            parser_input=parser_input,
            result_sets=result_sets,
        )

        snapshot = capture.sink.snapshot()
        assert capture.sink.replay_parser_input(receipt) == parser_input
        assert snapshot.objects == snapshot.observations == snapshot.pending_successes == ()
        assert [issue.code for issue in snapshot.issues] == ["response_observation_unavailable"]
    finally:
        store.close()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"future": {"x": 1}}, id="generic-nested"),
        pytest.param({}, id="missing-envelope"),
        pytest.param({"resultSets": []}, id="empty-legacy-envelope"),
    ],
)
def test_unknown_zero_occurrence_success_remains_explicitly_pending(
    tmp_path: Path,
    payload: object,
) -> None:
    endpoint_id = "VideoEvents"
    semantic_parameters = {"game_id": "0022400001", "game_event_id": 7}
    parser_input = _parser_input(payload)
    expected = _unknown_occurrences(endpoint_id, parser_input, semantic_parameters)
    assert expected == ()
    capture, store = _capture(
        tmp_path,
        endpoint_id=endpoint_id,
        semantic_parameters=semantic_parameters,
    )
    try:
        receipt = _record_success(
            capture,
            endpoint_id=endpoint_id,
            semantic_parameters=semantic_parameters,
            parser_input=parser_input,
            result_sets=(),
        )

        snapshot = capture.sink.snapshot()
        assert snapshot.observations == ()
        assert [issue.code for issue in snapshot.issues] == ["success_result_authority_pending"]
        assert len(snapshot.objects) == len(snapshot.pending_successes) == 1
        pending = snapshot.pending_successes[0]
        assert pending.private_receipt_sha256 == receipt
        assert pending.results == ()
    finally:
        store.close()


@pytest.mark.parametrize(
    "tamper_kind",
    ["receipt", "order", "headers"],
)
def test_stats_result_authority_tampering_fails_closed(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    endpoint_id = "BoxScoreAdvancedV3"
    semantic_parameters = {"game_id": "0022400001"}
    parser_input = _parser_input(_box_score_advanced_payload())
    derivations = _declared_derivations(endpoint_id, parser_input)
    exact = tuple(item.result_set for item in derivations)
    if tamper_kind == "receipt":
        result_sets = (
            replace(exact[0], normalized_output_sha256="f" * 64),
            exact[1],
        )
    elif tamper_kind == "order":
        result_sets = (
            replace(exact[1], provider_index=0, canonical_index=0),
            replace(exact[0], provider_index=1, canonical_index=1),
        )
    else:
        result_sets = (replace(exact[0], headers_sha256="f" * 64), exact[1])
    capture, store = _capture(
        tmp_path,
        endpoint_id=endpoint_id,
        semantic_parameters=semantic_parameters,
    )
    try:
        receipt = _record_success(
            capture,
            endpoint_id=endpoint_id,
            semantic_parameters=semantic_parameters,
            parser_input=parser_input,
            result_sets=result_sets,
        )

        snapshot = capture.sink.snapshot()
        assert capture.sink.replay_parser_input(receipt) == parser_input
        assert snapshot.objects == snapshot.observations == snapshot.pending_successes == ()
        assert [issue.code for issue in snapshot.issues] == ["response_observation_unavailable"]
    finally:
        store.close()
