from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandera.polars as pa
import polars as pl
import pytest

from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
)
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
)
from nbadb.schemas.raw.nba_api_authority import (
    RawNbaApiObservationRouteLandingSchema,
    RawNbaApiParserInputObjectSchema,
    RawNbaApiRequestObservationSchema,
    RawNbaApiResultOccurrenceSchema,
)
from nbadb.schemas.registry import _raw_schema_registry

_HASHES = tuple(f"{value:064x}" for value in range(1, 40))
_STARTED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def _valid_rows(
    *,
    occurrence_presence: str = "present",
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    parent_empty = occurrence_presence == "not_observed_parent_empty"
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=_HASHES[0],
        logical_invocation_sha256=_HASHES[1],
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=0,
        request_ordinal=0,
        source_family="live",
        endpoint_id="ScoreBoard",
        parameters={},
        provider_authority_sha256=_HASHES[2],
        endpoint_contract_sha256=_HASHES[3],
        competition_id="nba",
        competition_identity_sha256=_HASHES[4],
        scope_sha256=_HASHES[5],
        pagination_sha256=None,
        page_ordinal=None,
        source_sha="1" * 40,
        run_id=1,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )
    occurrence = ResultOccurrenceV2.build(
        observation_sha256=attempt.observation_sha256,
        occurrence_ordinal=0,
        result_name="scoreboard",
        duplicate_name_ordinal=0,
        provider_result_ordinal=0,
        canonical_result_ordinal=0,
        json_path="$.scoreboard",
        container_kind="nba_api_live_json_object",
        presence=occurrence_presence,  # type: ignore[arg-type]
        ordered_headers=[],
        row_count=0,
        cell_count=0,
        node_count=0 if occurrence_presence == "missing" or parent_empty else 1,
        container_count=0 if occurrence_presence == "missing" or parent_empty else 1,
        missing_count=1 if occurrence_presence == "missing" else 0,
        null_count=0,
        parent_state_sha256=_HASHES[9] if parent_empty else None,
        output_sha256=_HASHES[6],
        canonical_route_ids=["live_scoreboard"],
        committed_staging_receipts=[{"route_id": "live_scoreboard", "receipt_sha256": _HASHES[7]}],
        landing_disposition="wide_only",
    )
    receipt = CommittedStagingChunkReceiptV2(
        chunk_id="chunk",
        staging_key="stg_scoreboard",
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=_HASHES[11],
        persisted_row_count=0,
        persisted_content_sha256=_HASHES[12],
        persisted_schema_sha256=_HASHES[13],
        logical_call_receipt_sha256=_HASHES[8],
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        result_route_id="live_scoreboard",
    )
    landing = ObservationRouteLandingV2.build(
        observation_sha256=attempt.observation_sha256,
        logical_receipt_sha256=_HASHES[8],
        route_ordinal=0,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=_HASHES[14],
        landing_semantic="occurrence_bound",
        conditional_lossless=False,
        alias_target_route_id=None,
        live_snapshot_at=_STARTED_AT,
        source_occurrence_sha256s=[occurrence.occurrence_sha256],
        committed_receipt=receipt,
    )
    body = ParserInputObjectV2.from_parser_input('{"scoreboard":{}}')
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "live_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        lifecycle="selected_terminal",
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[occurrence.occurrence_sha256],
        route_landing_sha256s=[landing.landing_sha256],
        capture_response_receipt_sha256=_HASHES[10],
        logical_receipt_sha256=_HASHES[8],
    )
    return body.to_row(), observation.to_row(), occurrence.to_row(), landing.to_row()


def _observation_frame(row: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(
        [row],
        schema_overrides={
            "competition_id": pl.String,
            "competition_identity_sha256": pl.String,
            "pagination_sha256": pl.String,
            "page_ordinal": pl.Int64,
            "status_code": pl.Int64,
            "effective_status_code": pl.Int64,
            "started_at": pl.Datetime("us", "UTC"),
            "finished_at": pl.Datetime("us", "UTC"),
            "elapsed_ns": pl.Int64,
            "failure_class": pl.String,
            "root_exception_class": pl.String,
            "body_object_sha256": pl.String,
            "bodyless_evidence_sha256": pl.String,
            "capture_response_receipt_sha256": pl.String,
            "logical_receipt_sha256": pl.String,
            "logical_provider_parameter_binding_sha256": pl.String,
            "logical_provider_parameter_binding_json": pl.String,
        },
    )


def _occurrence_frame(row: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(
        [row],
        schema_overrides={
            "provider_result_ordinal": pl.Int64,
            "canonical_result_ordinal": pl.Int64,
            "json_path": pl.String,
            "parent_state_sha256": pl.String,
        },
    )


def _landing_frame(row: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(
        [row],
        schema_overrides={
            "alias_target_route_id": pl.String,
            "live_snapshot_at": pl.Datetime("us", "UTC"),
        },
    )


@pytest.mark.parametrize(
    ("table_name", "expected"),
    [
        ("raw_nba_api_parser_input_object", RawNbaApiParserInputObjectSchema),
        ("raw_nba_api_request_observation", RawNbaApiRequestObservationSchema),
        ("raw_nba_api_result_occurrence", RawNbaApiResultOccurrenceSchema),
        (
            "raw_nba_api_observation_route_landing",
            RawNbaApiObservationRouteLandingSchema,
        ),
    ],
)
def test_fixed_authority_schemas_are_registered_under_exact_table_names(
    table_name: str,
    expected: type,
) -> None:
    _raw_schema_registry.cache_clear()
    assert _raw_schema_registry()[table_name] is expected


@pytest.mark.parametrize(
    "schema_type",
    [
        RawNbaApiParserInputObjectSchema,
        RawNbaApiRequestObservationSchema,
        RawNbaApiResultOccurrenceSchema,
        RawNbaApiObservationRouteLandingSchema,
    ],
)
def test_fixed_authority_schemas_are_strict_ordered_and_never_coerce(
    schema_type: type,
) -> None:
    schema = schema_type.to_schema()
    assert (schema.strict, schema.coerce, schema.ordered) == (True, False, True)


def test_schema_columns_and_explicit_frames_match_all_four_contract_rows() -> None:
    object_row, observation_row, occurrence_row, landing_row = _valid_rows()
    cases = (
        (RawNbaApiParserInputObjectSchema, object_row, pl.DataFrame([object_row])),
        (
            RawNbaApiRequestObservationSchema,
            observation_row,
            _observation_frame(observation_row),
        ),
        (
            RawNbaApiResultOccurrenceSchema,
            occurrence_row,
            _occurrence_frame(occurrence_row),
        ),
        (
            RawNbaApiObservationRouteLandingSchema,
            landing_row,
            _landing_frame(landing_row),
        ),
    )
    for schema_type, row, frame in cases:
        assert list(schema_type.to_schema().columns) == list(row)
        assert schema_type.validate(frame).height == 1


def test_parent_empty_live_child_schema_accepts_only_exact_zero_state() -> None:
    _, _, row, _ = _valid_rows(occurrence_presence="not_observed_parent_empty")
    RawNbaApiResultOccurrenceSchema.validate(_occurrence_frame(row))
    for column_name, invalid in (
        ("row_count", 1),
        ("container_count", 1),
        ("parent_state_sha256", None),
        ("container_kind", "nba_api_static_records"),
    ):
        with pytest.raises(pa.errors.SchemaError):
            RawNbaApiResultOccurrenceSchema.validate(
                _occurrence_frame(dict(row, **{column_name: invalid}))
            )


@pytest.mark.parametrize(
    ("column_name", "invalid"),
    [
        ("landing_semantic", "response_fixed_zero"),
        ("conditional_lossless", True),
        ("route_authority_kind", "conditional_staging_route_admission_v1"),
        ("alias_target_route_id", "foreign_alias"),
        ("source_occurrence_count", 0),
    ],
)
def test_route_landing_schema_rejects_cross_partition_mutations(
    column_name: str,
    invalid: object,
) -> None:
    _, _, _, row = _valid_rows()
    with pytest.raises(pa.errors.SchemaError):
        RawNbaApiObservationRouteLandingSchema.validate(
            _landing_frame(dict(row, **{column_name: invalid}))
        )


@pytest.mark.parametrize("schema_version", [1, True, "2"])
def test_v1_and_nonexact_schema_versions_fail_closed(schema_version: object) -> None:
    object_row, observation_row, _, _ = _valid_rows()
    with pytest.raises(pa.errors.SchemaError):
        RawNbaApiParserInputObjectSchema.validate(
            pl.DataFrame([dict(object_row, schema_version=schema_version)])
        )
    with pytest.raises(pa.errors.SchemaError):
        RawNbaApiRequestObservationSchema.validate(
            _observation_frame(dict(observation_row, schema_version=schema_version))
        )


def test_timestamp_and_ordered_column_policy_fail_closed() -> None:
    object_row, observation_row, _, _ = _valid_rows()
    naive = _observation_frame(observation_row).with_columns(
        pl.col("started_at").dt.replace_time_zone(None),
        pl.col("finished_at").dt.replace_time_zone(None),
    )
    with pytest.raises(pa.errors.SchemaError):
        RawNbaApiRequestObservationSchema.validate(naive)

    reordered = {"stored_payload": object_row["stored_payload"]}
    reordered.update({key: value for key, value in object_row.items() if key != "stored_payload"})
    with pytest.raises(pa.errors.SchemaError):
        RawNbaApiParserInputObjectSchema.validate(pl.DataFrame([reordered]))
