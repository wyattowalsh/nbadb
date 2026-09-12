from __future__ import annotations

import hashlib
import json
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import duckdb
import pytest

from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    decode_parser_input_object,
)
from nbadb.extract.nba_api_adapter import (
    rederive_raw_authority_unknown_stats_response,
)
from nbadb.orchestrate.raw_request_store import RawRequestAuthorityStore
from nbadb.orchestrate.scanner import DataScanner, ScanSeverity
from tests.unit.contracts.test_raw_request_finalization import (
    _stats_fallback_case,
    finalize_raw_request_capture,
)
from tests.unit.orchestrate._raw_request_test_support import (
    raw_request_video_authority_bundle,
)

_STARTED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
_UNKNOWN_CONDITIONAL_ROUTE = "video_details:stg_nba_api_lossless_result_cells:0"
_UNKNOWN_FIXED_ROUTE = "video_details:stg_video_details:0"


def _sha(value: str | bytes) -> str:
    encoded = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parser_input(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _retry_attempt(
    attempt: RequestAttemptIdentityV2,
    retry_ordinal: int,
) -> RequestAttemptIdentityV2:
    return RequestAttemptIdentityV2.build(
        semantic_request_sha256=attempt.semantic_request_sha256,
        logical_invocation_sha256=attempt.logical_invocation_sha256,
        provider_call_role=attempt.provider_call_role,
        provider_call_ordinal=attempt.provider_call_ordinal,
        retry_ordinal=retry_ordinal,
        request_ordinal=attempt.request_ordinal,
        source_family=attempt.source_family,
        endpoint_id=attempt.endpoint_id,
        parameters=json.loads(attempt.safe_parameters_json),
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256=attempt.endpoint_contract_sha256,
        competition_id=attempt.competition_id,
        competition_identity_sha256=attempt.competition_identity_sha256,
        scope_sha256=attempt.scope_sha256,
        pagination_sha256=attempt.pagination_sha256,
        page_ordinal=attempt.page_ordinal,
        source_sha=attempt.source_sha,
        run_id=attempt.run_id,
        run_attempt=attempt.run_attempt,
        chain_id=attempt.chain_id,
        lane_id=attempt.lane_id,
    )


def _downstream_incomplete_observation(
    attempt: RequestAttemptIdentityV2,
    body: ParserInputObjectV2,
) -> RequestObservationV2:
    return RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        lifecycle="incomplete",
        outcome="downstream_incomplete",
        failure_class="response_contract",
        root_exception_class="ValueError",
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=(),
        route_landing_sha256s=(),
        capture_response_receipt_sha256=_sha(f"capture-response:{attempt.attempt_sha256}"),
        logical_receipt_sha256=None,
    )


def _unknown_case(
    *, retry_ordinal: int = 0
) -> tuple[
    ParserInputObjectV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    bundle = raw_request_video_authority_bundle(
        payload={
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
                {"name": "Stats", "headers": ["B"], "rowSet": [[2]]},
            ]
        },
        retry_ordinal=retry_ordinal,
    )
    return bundle.objects[0], bundle.observations[0], bundle.occurrences, bundle.landings


def _bundle(
    *cases: tuple[
        ParserInputObjectV2,
        RequestObservationV2,
        tuple[ResultOccurrenceV2, ...],
        tuple[ObservationRouteLandingV2, ...],
    ],
) -> RawRequestAuthorityBundleV2:
    landings = tuple(item for case in cases for item in case[3])
    return RawRequestAuthorityBundleV2.build(
        objects=tuple(case[0] for case in cases),
        observations=tuple(case[1] for case in cases),
        occurrences=tuple(item for case in cases for item in case[2]),
        landings=tuple(
            sorted(landings, key=lambda item: (item.observation_sha256, item.route_ordinal))
        ),
    )


def _scan(connection: duckdb.DuckDBPyConnection):
    scanner = DataScanner(connection)
    with ExitStack() as stack:
        stack.enter_context(patch.object(scanner, "_check_request_closure_inventory"))
        stack.enter_context(patch.object(scanner, "_check_full_publication_request_authority_join"))
        return scanner.scan_private_capture()


def _raw_errors(report: object) -> list[object]:
    return [
        finding
        for finding in report.filter(severity=ScanSeverity.ERROR)  # type: ignore[attr-defined]
        if finding.table in {"raw_request_authority", "raw_request_authority_private"}
    ]


def test_scanner_replays_unknown_duplicate_occurrences_with_exact_safe_parameters() -> None:
    body, observation, occurrences, landings = _unknown_case()
    connection = duckdb.connect(":memory:")
    try:
        RawRequestAuthorityStore(connection).persist_bundle(
            _bundle((body, observation, occurrences, landings))
        )
        with patch(
            "nbadb.extract.nba_api_adapter.rederive_raw_authority_unknown_stats_response",
            wraps=rederive_raw_authority_unknown_stats_response,
        ) as replay:
            report = _scan(connection)
    finally:
        connection.close()

    assert _raw_errors(report) == []
    assert [
        (
            item.result_name,
            item.provider_result_ordinal,
            item.canonical_result_ordinal,
            item.duplicate_name_ordinal,
            item.ordered_headers(),
        )
        for item in occurrences
    ] == [
        ("Stats", 0, None, 0, ("A",)),
        ("Stats", 1, None, 1, ("B",)),
    ]
    assert replay.call_count >= 1
    assert all(
        item.kwargs["safe_parameters_json"] == observation.attempt.safe_parameters_json
        and item.kwargs["parser_input"] == decode_parser_input_object(body)
        for item in replay.call_args_list
    )
    evidence = report.evidence["raw_request_authority"]
    assert evidence["stats_route_membership_verified_count"] == 2
    assert evidence["video_alias_policy_unverified_observation_count"] == 0
    assert evidence["landing_count"] == 2
    assert len(evidence["route_landing_inventory_sha256"]) == 64
    warnings = [
        finding
        for finding in report.filter(severity=ScanSeverity.WARNING)
        if finding.check == "raw_authority_video_alias_policy_unverified"
    ]
    assert warnings == []


def test_scanner_accepts_response_fixed_zero_with_no_occurrences() -> None:
    bundle = raw_request_video_authority_bundle()
    assert bundle.occurrences == ()
    assert len(bundle.landings) == 1
    assert bundle.landings[0].landing_semantic == "response_fixed_zero"
    assert bundle.landings[0].source_occurrence_count == 0
    assert bundle.landings[0].persisted_row_count == 0

    connection = duckdb.connect(":memory:")
    try:
        RawRequestAuthorityStore(connection).persist_bundle(bundle)
        report = _scan(connection)
    finally:
        connection.close()

    assert _raw_errors(report) == []
    evidence = report.evidence["raw_request_authority"]
    assert evidence["occurrence_count"] == 0
    assert evidence["landing_count"] == 1
    assert evidence["result_packet_count"] == 0


def test_scanner_binds_landing_journal_count_order_inventory_and_full_rows() -> None:
    bundle = raw_request_video_authority_bundle(
        payload={
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
            ]
        }
    )
    connection = duckdb.connect(":memory:")
    try:
        receipt = RawRequestAuthorityStore(connection).persist_bundle(bundle)
        journal = connection.execute(
            "SELECT landing_count, landing_keys_json, landing_inventory_sha256, "
            "landing_rows_sha256 FROM _raw_request_authority_bundle_journal"
        ).fetchone()
        report = _scan(connection)
    finally:
        connection.close()

    assert journal is not None
    assert journal[0] == len(bundle.landings) == receipt.landing_count
    assert json.loads(journal[1]) == [item.landing_sha256 for item in bundle.landings]
    assert journal[2] == receipt.landing_inventory_sha256
    assert journal[3] == receipt.landing_rows_sha256
    assert journal[2] != journal[3]
    assert _raw_errors(report) == []


@pytest.mark.parametrize("mutation", ["missing", "additive", "reordered", "relabelled"])
def test_scanner_rejects_hostile_landing_inventory_mutations(mutation: str) -> None:
    bundle = raw_request_video_authority_bundle(
        payload={
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
            ]
        }
    )
    connection = duckdb.connect(":memory:")
    try:
        RawRequestAuthorityStore(connection).persist_bundle(bundle)
        if mutation == "missing":
            connection.execute(
                "DELETE FROM raw_nba_api_observation_route_landing WHERE route_ordinal = 1"
            )
        elif mutation == "additive":
            connection.execute(
                "INSERT INTO raw_nba_api_observation_route_landing "
                "SELECT * REPLACE (? AS landing_sha256) "
                "FROM raw_nba_api_observation_route_landing WHERE route_ordinal = 1",
                ("f" * 64,),
            )
        elif mutation == "reordered":
            connection.execute(
                "UPDATE raw_nba_api_observation_route_landing SET route_ordinal = 1 - route_ordinal"
            )
        else:
            connection.execute(
                "UPDATE raw_nba_api_observation_route_landing SET route_id = ? "
                "WHERE route_ordinal = 0",
                (_UNKNOWN_CONDITIONAL_ROUTE,),
            )
        report = _scan(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].details["verified_observation_count"] == 0
    assert "raw_request_authority" not in report.evidence


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_ordinal", "order", "headers", "output", "route"],
)
def test_scanner_rejects_fully_resealed_unknown_occurrence_tampering(
    mutation: str,
) -> None:
    case = _unknown_case()
    connection = duckdb.connect(":memory:")
    try:
        RawRequestAuthorityStore(connection).persist_bundle(_bundle(case))
        sql, parameters = {
            "duplicate_ordinal": (
                "UPDATE raw_nba_api_result_occurrence "
                "SET duplicate_name_ordinal = 7 WHERE occurrence_ordinal = 0",
                (),
            ),
            "order": (
                "UPDATE raw_nba_api_result_occurrence "
                "SET occurrence_ordinal = 1 - occurrence_ordinal",
                (),
            ),
            "headers": (
                "UPDATE raw_nba_api_result_occurrence "
                "SET ordered_headers_json = ? WHERE occurrence_ordinal = 0",
                ('["FORGED"]',),
            ),
            "output": (
                "UPDATE raw_nba_api_result_occurrence "
                "SET output_sha256 = ? WHERE occurrence_ordinal = 0",
                ("f" * 64,),
            ),
            "route": (
                "UPDATE raw_nba_api_result_occurrence "
                "SET canonical_route_ids_json = ? WHERE occurrence_ordinal = 0",
                (json.dumps([_UNKNOWN_FIXED_ROUTE], separators=(",", ":")),),
            ),
        }[mutation]
        connection.execute(sql, parameters)
        report = _scan(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check in {
        "raw_authority_rows_malformed",
        "raw_authority_bundle_invalid",
    }
    assert errors[0].details["verified_observation_count"] == 0


def test_scanner_keeps_zero_occurrence_unknown_body_downstream_incomplete() -> None:
    terminal = _unknown_case(retry_ordinal=1)
    terminal_attempt = terminal[1].attempt
    parser_input = _parser_input({"future": {"x": 1}})
    zero_body = ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    zero_attempt = _retry_attempt(terminal_attempt, 0)
    zero_response = rederive_raw_authority_unknown_stats_response(
        endpoint_id=zero_attempt.endpoint_id,
        parser_input=parser_input,
        safe_parameters_json=zero_attempt.safe_parameters_json,
        provider_authority_sha256=zero_attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=zero_attempt.endpoint_contract_sha256,
    )
    assert zero_response.occurrences == ()
    zero_observation = _downstream_incomplete_observation(zero_attempt, zero_body)
    zero_case = (zero_body, zero_observation, (), ())
    connection = duckdb.connect(":memory:")
    try:
        RawRequestAuthorityStore(connection).persist_bundle(_bundle(terminal, zero_case))
        report = _scan(connection)
    finally:
        connection.close()

    assert _raw_errors(report) == []
    evidence = report.evidence["raw_request_authority"]
    assert evidence["observation_count"] == 2
    assert evidence["occurrence_count"] == 2
    assert evidence["result_packet_count"] == 2
    assert evidence["parsed_body_count"] == 2


def test_scanner_rejects_resealed_nonterminal_unknown_body_hiding_legacy_result() -> None:
    terminal = _unknown_case(retry_ordinal=1)
    terminal_attempt = terminal[1].attempt
    hidden_parser_input = _parser_input(
        {
            "resultSets": [
                {"name": "Stats", "headers": ["C"], "rowSet": [[3]]},
            ]
        }
    )
    hidden_body = ParserInputObjectV2.from_parser_input(hidden_parser_input.decode("utf-8"))
    hidden_attempt = _retry_attempt(terminal_attempt, 0)
    hidden_response = rederive_raw_authority_unknown_stats_response(
        endpoint_id=hidden_attempt.endpoint_id,
        parser_input=hidden_parser_input,
        safe_parameters_json=hidden_attempt.safe_parameters_json,
        provider_authority_sha256=hidden_attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=hidden_attempt.endpoint_contract_sha256,
    )
    assert hidden_response.occurrences
    hidden = (
        hidden_body,
        _downstream_incomplete_observation(hidden_attempt, hidden_body),
        (),
        (),
    )
    connection = duckdb.connect(":memory:")
    try:
        RawRequestAuthorityStore(connection).persist_bundle(_bundle(terminal, hidden))
        report = _scan(connection)
    finally:
        connection.close()

    errors = _raw_errors(report)
    assert len(errors) == 1
    assert errors[0].check == "raw_authority_reconstruction_failed"
    assert "raw_request_authority" not in report.evidence


def _declared_fallback_case() -> tuple[
    ParserInputObjectV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    payload = {
        "resultSets": [
            {
                "name": "TeamYears",
                "headers": [
                    "LEAGUE_ID",
                    "TEAM_ID",
                    "MIN_YEAR",
                    "MAX_YEAR",
                    "ABBREVIATION",
                ],
                "rowSet": [["00", 1, "1946", "2026", "NBA"]],
            },
            {"name": "Additive", "headers": ["EXTRA"], "rowSet": [[9]]},
        ]
    }
    snapshot, binding, receipts = _stats_fallback_case("common_team_years", payload)
    bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    return bundle.objects[0], bundle.observations[0], bundle.occurrences, bundle.landings


def test_scanner_recomputes_declared_fallback_safe_wide_route_membership() -> None:
    exact = _declared_fallback_case()
    connection = duckdb.connect(":memory:")
    try:
        RawRequestAuthorityStore(connection).persist_bundle(_bundle(exact))
        exact_report = _scan(connection)
    finally:
        connection.close()
    assert _raw_errors(exact_report) == []
    assert (
        exact_report.evidence["raw_request_authority"]["stats_route_membership_verified_count"] == 2
    )

    connection = duckdb.connect(":memory:")
    try:
        RawRequestAuthorityStore(connection).persist_bundle(_bundle(exact))
        connection.execute(
            "UPDATE raw_nba_api_result_occurrence "
            "SET canonical_route_ids_json = ? WHERE occurrence_ordinal = 0",
            (json.dumps([_UNKNOWN_CONDITIONAL_ROUTE], separators=(",", ":")),),
        )
        forged_report = _scan(connection)
    finally:
        connection.close()
    assert len(_raw_errors(forged_report)) == 1
