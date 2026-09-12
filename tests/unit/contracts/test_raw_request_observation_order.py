from __future__ import annotations

from datetime import timedelta

import pytest

from nbadb.contracts.raw_request_authority import (
    RequestAttemptIdentityV2,
    RequestObservationV2,
)
from nbadb.contracts.raw_request_observation_order import (
    RawRequestObservationOrderError,
    canonical_raw_request_observations,
    raw_request_observation_order_key,
)
from tests.unit.contracts.test_raw_request_authority import (
    _STARTED_AT,
    _attempt,
    _sha,
    _video_bundle,
)


class _TextSubclass(str):
    pass


def _downstream_incomplete(
    *,
    attempt: RequestAttemptIdentityV2,
    body_object_sha256: str,
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
        elapsed_ns=1,
        lifecycle="incomplete",
        outcome="downstream_incomplete",
        failure_class="response_contract",
        root_exception_class="ResponseContractError",
        body_disposition="public_parser_input",
        body_object_sha256=body_object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[],
        route_landing_sha256s=[],
        capture_response_receipt_sha256=_sha(f"capture:{attempt.attempt_sha256}"),
        logical_receipt_sha256=None,
    )


def test_canonical_order_is_semantic_and_selection_is_exact() -> None:
    bundle, selected, _occurrences, _landings = _video_bundle("VideoDetails", {})
    incomplete = _downstream_incomplete(
        attempt=_attempt(
            source_family="stats",
            endpoint_id="VideoDetails",
            parameters={"team_id": 1, "player_id": 2, "season": "2024-25"},
            provider_authority_sha256=selected.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=selected.attempt.endpoint_contract_sha256,
            provider_call_ordinal=1,
        ),
        body_object_sha256=bundle.objects[0].object_sha256,
    )
    ordered = canonical_raw_request_observations([incomplete, selected])
    assert ordered == (selected, incomplete)
    assert canonical_raw_request_observations(
        [incomplete, selected],
        selection="selected_terminal",
    ) == (selected,)
    assert canonical_raw_request_observations(
        [incomplete, selected],
        selection="downstream_incomplete",
    ) == (incomplete,)
    assert len(raw_request_observation_order_key(selected)) == 9


def test_downstream_incomplete_is_not_misclassified_from_lifecycle_alone() -> None:
    bundle, selected, _occurrences, _landings = _video_bundle("VideoDetails", {})
    attempt = _attempt(
        source_family="stats",
        endpoint_id="VideoDetails",
        parameters={"team_id": 1, "player_id": 2, "season": "2024-25"},
        provider_authority_sha256=selected.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=selected.attempt.endpoint_contract_sha256,
        provider_call_ordinal=2,
    )
    parser_failure = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1,
        lifecycle="incomplete",
        outcome="parser_failure",
        failure_class="response_contract",
        root_exception_class="ResponseContractError",
        body_disposition="excluded_failure_body",
        body_object_sha256=None,
        bodyless_evidence_sha256=_sha("excluded"),
        result_occurrence_sha256s=[],
        route_landing_sha256s=[],
        capture_response_receipt_sha256=None,
        logical_receipt_sha256=None,
    )
    assert (
        canonical_raw_request_observations(
            [parser_failure],
            selection="downstream_incomplete",
        )
        == ()
    )
    assert bundle.objects


def test_coordinate_collision_is_rejected_before_tie_breaking() -> None:
    bundle, selected, _occurrences, _landings = _video_bundle("VideoDetails", {})
    attempt = selected.attempt
    colliding_attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=attempt.semantic_request_sha256,
        logical_invocation_sha256=attempt.logical_invocation_sha256,
        provider_call_role=attempt.provider_call_role,
        provider_call_ordinal=attempt.provider_call_ordinal,
        retry_ordinal=attempt.retry_ordinal,
        request_ordinal=attempt.request_ordinal,
        source_family=attempt.source_family,
        endpoint_id=attempt.endpoint_id,
        parameters={"team_id": 1, "player_id": 2, "season": "2024-25"},
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256=attempt.endpoint_contract_sha256,
        competition_id=attempt.competition_id,
        competition_identity_sha256=attempt.competition_identity_sha256,
        scope_sha256=attempt.scope_sha256,
        pagination_sha256=attempt.pagination_sha256,
        page_ordinal=attempt.page_ordinal,
        source_sha=attempt.source_sha,
        run_id=attempt.run_id + 1,
        run_attempt=attempt.run_attempt,
        chain_id=attempt.chain_id,
        lane_id=attempt.lane_id,
    )
    collision = _downstream_incomplete(
        attempt=colliding_attempt,
        body_object_sha256=bundle.objects[0].object_sha256,
    )
    assert collision.attempt.observation_sha256 != selected.attempt.observation_sha256
    with pytest.raises(RawRequestObservationOrderError, match="collide"):
        canonical_raw_request_observations((selected, collision))


@pytest.mark.parametrize("bad", [True, 1.5, "rows", object()])
def test_order_rejects_foreign_sequences(bad: object) -> None:
    with pytest.raises(RawRequestObservationOrderError):
        canonical_raw_request_observations(bad)  # type: ignore[arg-type]


def test_order_rejects_duplicate_types_bounds_and_unknown_selection() -> None:
    _bundle, selected, _occurrences, _landings = _video_bundle("VideoDetails", {})
    with pytest.raises(RawRequestObservationOrderError, match="unique"):
        canonical_raw_request_observations((selected, selected))
    with pytest.raises(RawRequestObservationOrderError, match="bound"):
        canonical_raw_request_observations((selected,), maximum=0)
    with pytest.raises(RawRequestObservationOrderError, match="selection"):
        canonical_raw_request_observations(
            (selected,),
            selection="incomplete",  # type: ignore[arg-type]
        )
    with pytest.raises(RawRequestObservationOrderError, match="selection"):
        canonical_raw_request_observations(
            (selected,),
            selection=_TextSubclass("selected_terminal"),
        )
    with pytest.raises(RawRequestObservationOrderError, match="foreign"):
        raw_request_observation_order_key(object())  # type: ignore[arg-type]
