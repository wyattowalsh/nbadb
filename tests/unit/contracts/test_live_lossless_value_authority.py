from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING

import polars as pl
import pytest
from pandera import errors as pa_errors

import nbadb.contracts.live_lossless_value_authority as authority_module
import nbadb.contracts.raw_request_authority as raw_authority_module
from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_COLUMNS,
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    LIVE_LOSSLESS_REPRESENTATION_KIND,
    LIVE_LOSSLESS_SOURCE_INPUT_KIND,
    LIVE_LOSSLESS_TEXT_COLUMNS,
    LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND,
    MAX_LIVE_LOSSLESS_ANOMALY_BYTES,
    MAX_LIVE_LOSSLESS_CANONICAL_BYTES,
    LiveLosslessNodeRecordV1,
    LiveLosslessValueAuthorityError,
    LiveLosslessValueAuthorityReceiptV1,
    build_live_lossless_value_authority,
    canonical_json_bytes,
    canonical_ordered_root_sha256,
)
from nbadb.contracts.public_value_types import (
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.core.nba_api_runtime_contract import pinned_live_contracts
from nbadb.schemas.raw.nba_api_live_lossless_node import (
    RawNbaApiLiveLosslessNodeSchema,
)
from tests.unit.contracts.test_raw_request_finalization import (
    _case,
    _complete_endpoint_payload,
    _mixed_live_parent_bundle,
    _replace_live_payload,
    finalize_raw_request_capture,
)

if TYPE_CHECKING:
    from nbadb.contracts.live_lossless_value_authority import LiveLosslessValueAuthorityV1
    from nbadb.contracts.raw_request_authority import RawRequestAuthorityBundleV2


@pytest.fixture(scope="module")
def live_bundle() -> RawRequestAuthorityBundleV2:
    snapshot, binding, receipts = _case("live")
    return finalize_raw_request_capture(snapshot, binding, receipts)


@pytest.fixture(scope="module")
def authority(live_bundle: RawRequestAuthorityBundleV2) -> LiveLosslessValueAuthorityV1:
    return build_live_lossless_value_authority(
        live_bundle,
        expected_raw_authority_bundle_sha256=live_bundle.bundle_sha256,
    )


def _reseal_live_row(
    row: dict[str, object],
    **changes: object,
) -> dict[str, object]:
    prepared = dict(row)
    payload = json.loads(str(prepared.pop("payload_json")))
    prepared.pop("schema_version")
    prepared.pop("record_sha256")
    prepared.pop("payload_sha256")
    prepared.update(changes)
    return LiveLosslessNodeRecordV1.build(payload=payload, **prepared).to_row()


def _second_live_authority() -> LiveLosslessValueAuthorityV1:
    snapshot, binding, _receipts = _case("live")
    contract = pinned_live_contracts()[snapshot.pending_successes[0].attempt.endpoint_id]
    payload = _complete_endpoint_payload(contract)
    payload["publicDescription"] = "Second immutable public bundle"
    snapshot, receipts = _replace_live_payload(snapshot, binding, payload)
    bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    return build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )


def _rebound_second_observation_records(
    authority: LiveLosslessValueAuthorityV1,
) -> tuple[LiveLosslessNodeRecordV1, ...]:
    unit_offset = authority.expected_units.unit_count
    observation_sha256 = "f" * 64
    units_and_assignments: dict[
        str,
        tuple[ExpectedValueUnitV1, ValueRepresentationAssignmentV1],
    ] = {}
    for unit, assignment in zip(
        authority.expected_units.units,
        authority.representation_assignments,
        strict=True,
    ):
        rebound_unit = ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=(authority.receipt.raw_authority_bundle_sha256),
            unit_ordinal=unit_offset + unit.unit_ordinal,
            observation_sha256=observation_sha256,
            observation_ordinal=1,
            unit_kind=unit.unit_kind,
            occurrence_sha256=unit.occurrence_sha256,
            occurrence_ordinal=unit.occurrence_ordinal,
        )
        rebound_assignment = ValueRepresentationAssignmentV1.build(
            expected_unit=rebound_unit,
            source_input_kind=assignment.source_input_kind,
            representation_kind=assignment.representation_kind,
        )
        units_and_assignments[unit.unit_sha256] = (rebound_unit, rebound_assignment)

    rebound: list[LiveLosslessNodeRecordV1] = []
    for record in authority.records:
        unit, assignment = units_and_assignments[record.expected_unit_sha256]
        row = _reseal_live_row(
            record.to_row(),
            observation_record_sha256="e" * 64,
            observation_sha256=observation_sha256,
            attempt_sha256="f" * 64,
            semantic_request_sha256="f" * 64,
            logical_invocation_sha256="f" * 64,
            provider_call_sha256="f" * 64,
            observation_ordinal=1,
            global_record_ordinal=len(authority.records) + len(rebound),
            observation_record_ordinal=len(rebound),
            expected_unit_sha256=unit.unit_sha256,
            expected_unit_ordinal=unit.unit_ordinal,
            representation_assignment_sha256=assignment.assignment_sha256,
        )
        rebound.append(LiveLosslessNodeRecordV1.from_row(row))
    return tuple(rebound)


def test_body_derived_authority_closes_every_mandatory_record_partition(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    receipt = authority.receipt
    kinds = [item.record_kind for item in authority.records]

    assert receipt.selected_observation_count == 1
    assert receipt.result_declaration_count == kinds.count("result_declaration") == 11
    assert receipt.result_occurrence_count == kinds.count("result_occurrence") == 11
    assert receipt.node_count == kinds.count("node")
    assert receipt.field_cell_count == kinds.count("field_cell")
    assert receipt.record_count == len(authority.records)
    assert receipt.node_schema_sha256 == LIVE_LOSSLESS_NODE_SCHEMA_SHA256
    assert set(kinds) == {"result_declaration", "result_occurrence", "node", "field_cell"}
    assert tuple(authority.public_rows()[0]) == LIVE_LOSSLESS_NODE_COLUMNS
    assert tuple(item.global_record_ordinal for item in authority.records) == tuple(
        range(len(authority.records))
    )


def test_hybrid_ownership_assigns_occurrences_and_explicit_response_residual(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    occurrence_rows = tuple(
        item for item in authority.records if item.ownership_kind == "result_occurrence"
    )
    residual_rows = tuple(
        item for item in authority.records if item.ownership_kind == "response_residual"
    )
    units = authority.expected_units.units

    assert residual_rows
    assert all(item.raw_occurrence_sha256 is not None for item in occurrence_rows)
    assert all(
        item.raw_occurrence_sha256 is None and item.record_kind == "node" for item in residual_rows
    )
    assert {item.source_input_kind for item in authority.records} == {
        LIVE_LOSSLESS_SOURCE_INPUT_KIND
    }
    assert {item.representation_kind for item in occurrence_rows} == {
        LIVE_LOSSLESS_REPRESENTATION_KIND
    }
    assert {item.representation_kind for item in residual_rows} == {
        LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND
    }
    assert [item.unit_kind for item in units[:-1]] == [
        "result_occurrence"
    ] * authority.receipt.result_declaration_count
    assert units[-1].unit_kind == "response_residual"
    assert units[-1].occurrence_sha256 is None
    assert authority.expected_units.raw_authority_bundle_sha256 == (
        authority.receipt.raw_authority_bundle_sha256
    )
    assert all(
        item.raw_authority_bundle_sha256 == authority.receipt.raw_authority_bundle_sha256
        for item in units
    )
    assert len(authority.representation_assignments) == len(units)
    assert all(
        item.raw_authority_bundle_sha256 == authority.receipt.raw_authority_bundle_sha256
        for item in authority.representation_assignments
    )
    assert authority.representation_assignments[-1].representation_kind == (
        LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND
    )
    residual_root = canonical_ordered_root_sha256(
        kind="live_lossless_response_residual_source_items_v1",
        count=len(residual_rows),
        item_sha256s=(item.source_item_sha256 for item in residual_rows),
    )
    assert authority.receipt.response_residual_record_count == len(residual_rows)
    assert authority.receipt.response_residual_record_inventory_sha256 == residual_root
    assert authority.receipt.response_residual_observation_count == 1
    assert authority.receipt.zero_response_residual_observation_count == 0
    assert all(
        item.response_residual_record_count == len(residual_rows)
        and item.response_residual_record_root_sha256 == residual_root
        for item in authority.records
    )


def test_independently_resealed_residual_root_cannot_rewrite_observation_partition(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    index = next(
        index
        for index, item in enumerate(authority.records)
        if item.ownership_kind == "response_residual"
    )
    row = dict(authority.records[index].to_row())
    payload = json.loads(str(row.pop("payload_json")))
    row.pop("schema_version")
    row.pop("record_sha256")
    row.pop("payload_sha256")
    row["response_residual_record_root_sha256"] = "f" * 64
    forged = LiveLosslessNodeRecordV1.build(payload=payload, **row)
    records = list(authority.records)
    records[index] = forged

    with pytest.raises(LiveLosslessValueAuthorityError, match="residual partition"):
        replace(authority, records=tuple(records))


def test_public_rows_roundtrip_through_exact_dto_and_strict_ordered_schema(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    assert tuple(LiveLosslessNodeRecordV1.from_row(row) for row in rows) == authority.records

    frame = pl.DataFrame(rows, infer_schema_length=None)
    validated = RawNbaApiLiveLosslessNodeSchema.validate(frame)
    assert validated.height == len(rows)
    assert tuple(validated.columns) == LIVE_LOSSLESS_NODE_COLUMNS


def test_cumulative_schema_accepts_two_bundle_local_zero_authorities(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    second = _second_live_authority()
    assert authority.receipt.raw_authority_bundle_sha256 != (
        second.receipt.raw_authority_bundle_sha256
    )
    assert authority.expected_units.units[0].unit_ordinal == 0
    assert second.expected_units.units[0].unit_ordinal == 0
    assert authority.records[0].global_record_ordinal == 0
    assert second.records[0].global_record_ordinal == 0

    rows = [*authority.public_rows(), *second.public_rows()]
    validated = RawNbaApiLiveLosslessNodeSchema.validate(
        pl.DataFrame(rows, infer_schema_length=None)
    )
    assert validated.height == len(rows)


def test_same_bundle_multi_observation_units_remain_contiguous(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    second_observation = _rebound_second_observation_records(authority)
    records = (*authority.records, *second_observation)
    validated = authority_module._validate_authority_record_inventory(
        records,
        expected_raw_authority_bundle_sha256=(authority.receipt.raw_authority_bundle_sha256),
    )

    assert validated.selected_observation_count == 2
    assert tuple(unit.unit_ordinal for unit in validated.expected_units.units) == tuple(
        range(validated.expected_units.unit_count)
    )
    assert tuple(
        dict.fromkeys(unit.observation_ordinal for unit in validated.expected_units.units)
    ) == (0, 1)


@pytest.mark.parametrize(
    ("record_index", "field_name", "new_value"),
    [
        (1, "global_record_ordinal", 0),
        (-1, "global_record_ordinal", 10_000),
        (1, "observation_record_ordinal", 0),
        (-1, "observation_record_ordinal", 10_000),
    ],
)
def test_cumulative_schema_rejects_bundle_local_record_coordinate_gaps_and_duplicates(
    authority: LiveLosslessValueAuthorityV1,
    record_index: int,
    field_name: str,
    new_value: int,
) -> None:
    rows = list(authority.public_rows())
    rows[record_index] = _reseal_live_row(
        rows[record_index],
        **{field_name: new_value},
    )
    assert LiveLosslessNodeRecordV1.from_row(rows[record_index])

    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiLiveLosslessNodeSchema.validate(pl.DataFrame(rows, infer_schema_length=None))


@pytest.mark.parametrize("new_unit_ordinal", [0, 10_000])
def test_cumulative_schema_rejects_bundle_local_unit_duplicate_or_gap_after_reseal(
    authority: LiveLosslessValueAuthorityV1,
    new_unit_ordinal: int,
) -> None:
    original_unit = authority.expected_units.units[1]
    original_assignment = authority.representation_assignments[1]
    forged_unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=original_unit.raw_authority_bundle_sha256,
        unit_ordinal=new_unit_ordinal,
        observation_sha256=original_unit.observation_sha256,
        observation_ordinal=original_unit.observation_ordinal,
        unit_kind=original_unit.unit_kind,
        occurrence_sha256=original_unit.occurrence_sha256,
        occurrence_ordinal=original_unit.occurrence_ordinal,
    )
    forged_assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=forged_unit,
        source_input_kind=original_assignment.source_input_kind,
        representation_kind=original_assignment.representation_kind,
    )
    rows = [
        _reseal_live_row(
            row,
            expected_unit_sha256=forged_unit.unit_sha256,
            expected_unit_ordinal=forged_unit.unit_ordinal,
            representation_assignment_sha256=forged_assignment.assignment_sha256,
        )
        if row["expected_unit_sha256"] == original_unit.unit_sha256
        else row
        for row in authority.public_rows()
    ]
    assert all(LiveLosslessNodeRecordV1.from_row(row) for row in rows)

    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiLiveLosslessNodeSchema.validate(pl.DataFrame(rows, infer_schema_length=None))


def test_cumulative_schema_rejects_coordinated_cross_bundle_row_reseal(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    row = authority.public_rows()[0]
    original_unit = authority.expected_units.units[0]
    original_assignment = authority.representation_assignments[0]
    foreign_bundle = "0" * 64
    forged_unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=foreign_bundle,
        unit_ordinal=original_unit.unit_ordinal,
        observation_sha256=original_unit.observation_sha256,
        observation_ordinal=original_unit.observation_ordinal,
        unit_kind=original_unit.unit_kind,
        occurrence_sha256=original_unit.occurrence_sha256,
        occurrence_ordinal=original_unit.occurrence_ordinal,
    )
    forged_assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=forged_unit,
        source_input_kind=original_assignment.source_input_kind,
        representation_kind=original_assignment.representation_kind,
    )
    forged = _reseal_live_row(
        row,
        raw_authority_bundle_sha256=foreign_bundle,
        expected_unit_sha256=forged_unit.unit_sha256,
        expected_unit_ordinal=forged_unit.unit_ordinal,
        representation_assignment_sha256=forged_assignment.assignment_sha256,
    )
    assert LiveLosslessNodeRecordV1.from_row(forged)
    rows = [forged, *authority.public_rows()[1:]]

    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiLiveLosslessNodeSchema.validate(pl.DataFrame(rows, infer_schema_length=None))


def test_records_bind_attempt_provider_source_snapshot_and_raw_occurrences(
    authority: LiveLosslessValueAuthorityV1,
    live_bundle: RawRequestAuthorityBundleV2,
) -> None:
    observation = live_bundle.observations[0]
    rows = authority.records
    assert {item.attempt_sha256 for item in rows} == {observation.attempt.attempt_sha256}
    assert {item.provider_authority_sha256 for item in rows} == {
        observation.attempt.provider_authority_sha256
    }
    assert {item.source_sha for item in rows} == {observation.attempt.source_sha}
    assert {item.live_snapshot_at for item in rows} == {"2026-08-27T12:00:00.000000Z"}
    expected_raw = {item.occurrence_sha256 for item in live_bundle.occurrences}
    assert {
        item.raw_occurrence_sha256 for item in rows if item.raw_occurrence_sha256 is not None
    } == expected_raw
    assert any(item.raw_occurrence_sha256 is None for item in rows if item.record_kind == "node")


def test_mixed_missing_and_null_parent_states_remain_recursively_lossless() -> None:
    bundle, _body = _mixed_live_parent_bundle(("missing", "null"))
    authority = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    declaration = next(
        item
        for item in authority.records
        if item.record_kind == "result_declaration"
        and item.result_set_name == "scoreboard_games_pbodds"
    )
    occurrences = [
        item
        for item in authority.records
        if item.record_kind == "result_occurrence"
        and item.result_set_name == "scoreboard_games_pbodds"
    ]

    assert declaration.presence_kind == "mixed_absent"
    assert [item.presence_kind for item in occurrences] == ["missing", "null"]
    assert [item.result_set_occurrence for item in occurrences] == [0, 1]
    assert all(
        item.raw_occurrence_sha256 == declaration.raw_occurrence_sha256 for item in occurrences
    )


def test_builder_requires_exact_v2_bundle_and_external_bundle_pin(
    authority: LiveLosslessValueAuthorityV1,
    live_bundle: RawRequestAuthorityBundleV2,
) -> None:
    with pytest.raises(LiveLosslessValueAuthorityError, match="exact Raw Authority V2"):
        build_live_lossless_value_authority(
            object(),
            expected_raw_authority_bundle_sha256=live_bundle.bundle_sha256,
        )
    with pytest.raises(LiveLosslessValueAuthorityError, match="external bundle pin"):
        build_live_lossless_value_authority(
            live_bundle,
            expected_raw_authority_bundle_sha256="0" * 64,
        )
    with pytest.raises(
        LiveLosslessValueAuthorityError,
        match="ownership binding|digest differs",
    ):
        replace(authority.records[0], raw_authority_bundle_sha256="0" * 64)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: {**row, "extra": 1},
        lambda row: {key: value for key, value in row.items() if key != "payload_sha256"},
        lambda row: {**row, "schema_version": True},
        lambda row: {**row, "global_record_ordinal": True},
        lambda row: dict(reversed(row.items())),
    ],
)
def test_public_row_parser_rejects_additive_missing_and_bool_integer_fields(
    authority: LiveLosslessValueAuthorityV1,
    mutation: object,
) -> None:
    row = authority.public_rows()[0]
    with pytest.raises(LiveLosslessValueAuthorityError):
        LiveLosslessNodeRecordV1.from_row(mutation(row))  # type: ignore[operator]


def test_public_json_rejects_secret_nonfinite_deep_and_unbounded_values_without_echo() -> None:
    sentinel = "ghp_123456789012345678901234567890"
    with pytest.raises(LiveLosslessValueAuthorityError) as captured:
        canonical_json_bytes({"apiKey": sentinel}, maximum_bytes=4_096)
    assert sentinel not in str(captured.value)
    with pytest.raises(LiveLosslessValueAuthorityError, match="non-finite"):
        canonical_json_bytes({"value": float("nan")}, maximum_bytes=4_096)
    deep: object = 1
    for _ in range(70):
        deep = [deep]
    with pytest.raises(LiveLosslessValueAuthorityError, match="node or depth"):
        canonical_json_bytes(deep, maximum_bytes=4_096)
    with pytest.raises(LiveLosslessValueAuthorityError, match="byte bound"):
        canonical_json_bytes(
            {"value": "x" * (MAX_LIVE_LOSSLESS_CANONICAL_BYTES + 1)},
            maximum_bytes=MAX_LIVE_LOSSLESS_CANONICAL_BYTES,
        )


def test_benign_nba_text_and_unicode_are_public_safe() -> None:
    assert (
        canonical_json_bytes(
            {"playerName": "Nikola Jokić", "gameClock": "PT00M42.00S"},
            maximum_bytes=4_096,
        ).decode()
        == '{"gameClock":"PT00M42.00S","playerName":"Nikola Jokić"}'
    )
    assert canonical_json_bytes(
        {"description": "Basic Basketball and Bearer scoring"},
        maximum_bytes=4_096,
    )
    for value in (
        "Authorization is required for League Pass",
        "Bearer of the scoring load",
        "Basic Basketball",
    ):
        assert canonical_json_bytes({"description": value}, maximum_bytes=4_096)


@pytest.mark.parametrize(
    "value",
    [
        {"Authorization": "Bearer ABCDEFGHIJKLMNOPQRST"},
        {"value": "Bearer ABCDEFGHIJKLMNOPQRST"},
        {"value": "Basic QUJDREVGR0hJSktM"},
        {"value": "prefix Authorization: Bearer ABCDEFGHIJKLMNOPQRST suffix"},
        {"value": "prefix Authorization: Basic QUJDREVGR0hJSktM suffix"},
        {"value": "prefix Bearer ABCDEFGHIJKLMNOPQRST suffix"},
        {"value": "prefix Basic QUJDREVGR0hJSktM suffix"},
        {"value": "/Users/private-name"},
        {"value": "/home/private-name"},
        {"value": "/private/var"},
        {"value": "prefix /Users/private-name suffix"},
        {"value": "prefix /home/private-name suffix"},
        {"value": "prefix /private/var suffix"},
        {"value": "/Users/private-name:"},
        {"value": "/home/private-name,"},
        {"value": "/private/var."},
        {"value": "eyJabcdefgh.abcdefgh.abcdefgh"},
        {"nested": {"authToken": "opaque-value"}},
        {"nested": {"sessionKey": "opaque-value"}},
        {"session": "opaque-value"},
    ],
)
def test_authority_and_schema_reject_secret_shaped_nested_json_without_echo(
    authority: LiveLosslessValueAuthorityV1,
    value: dict[str, object],
) -> None:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    with pytest.raises(LiveLosslessValueAuthorityError) as authority_error:
        canonical_json_bytes(value, maximum_bytes=4_096)
    assert "opaque-value" not in str(authority_error.value)
    assert "ABCDEFGHIJKLMNOPQRST" not in str(authority_error.value)

    row = dict(authority.public_rows()[0])
    row["canonical_json"] = encoded
    row["canonical_json_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    with pytest.raises(LiveLosslessValueAuthorityError):
        LiveLosslessNodeRecordV1.from_row(row)
    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiLiveLosslessNodeSchema.validate(pl.DataFrame([row], infer_schema_length=None))


def test_builder_has_intrinsic_contextual_secret_gate_after_raw_authority_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, binding, _receipts = _case("live")
    contract = pinned_live_contracts()[snapshot.pending_successes[0].attempt.endpoint_id]
    payload = _complete_endpoint_payload(contract)
    payload["publicDescription"] = "prefix Authorization: Bearer ABCDEFGHIJKLMNOPQRST suffix"

    with monkeypatch.context() as raw_gate_bypass:
        raw_gate_bypass.setattr(
            raw_authority_module,
            "_reject_sensitive_bytes",
            lambda _raw, *, known_secrets=(): None,
        )
        hostile_snapshot, hostile_receipts = _replace_live_payload(snapshot, binding, payload)
        hostile_bundle = finalize_raw_request_capture(
            hostile_snapshot,
            binding,
            hostile_receipts,
        )
        with pytest.raises(LiveLosslessValueAuthorityError, match="secret-shaped"):
            build_live_lossless_value_authority(
                hostile_bundle,
                expected_raw_authority_bundle_sha256=hostile_bundle.bundle_sha256,
            )


def test_raw_v2_preflight_rejects_nested_foreign_values_before_callbacks(
    live_bundle: RawRequestAuthorityBundleV2,
) -> None:
    class PoisonText(str):
        callback_count = 0

        def encode(self, *_args: object, **_kwargs: object) -> bytes:
            type(self).callback_count += 1
            raise AssertionError("foreign encode callback executed")

        def __eq__(self, _other: object) -> bool:
            type(self).callback_count += 1
            raise AssertionError("foreign equality callback executed")

        __hash__ = str.__hash__

    parser_object = live_bundle.objects[0].model_copy(
        update={"representation": PoisonText(live_bundle.objects[0].representation)}
    )
    forged = live_bundle.model_copy(update={"objects": (parser_object,)})
    with pytest.raises(LiveLosslessValueAuthorityError, match="foreign nested value"):
        build_live_lossless_value_authority(
            forged,
            expected_raw_authority_bundle_sha256=live_bundle.bundle_sha256,
        )
    assert PoisonText.callback_count == 0


def test_raw_v2_preflight_rejects_untrusted_timezone_without_callbacks(
    live_bundle: RawRequestAuthorityBundleV2,
) -> None:
    class PoisonTimezone(tzinfo):
        callback_count = 0

        def utcoffset(self, _value: datetime | None):
            type(self).callback_count += 1
            raise AssertionError("timezone callback executed")

        def dst(self, _value: datetime | None):
            type(self).callback_count += 1
            raise AssertionError("timezone callback executed")

        def tzname(self, _value: datetime | None):
            type(self).callback_count += 1
            raise AssertionError("timezone callback executed")

    timestamp = datetime(2026, 8, 27, 12, 0, tzinfo=PoisonTimezone())
    observation = live_bundle.observations[0].model_copy(update={"started_at": timestamp})
    forged = live_bundle.model_copy(update={"observations": (observation,)})
    with pytest.raises(LiveLosslessValueAuthorityError, match="trusted UTC"):
        build_live_lossless_value_authority(
            forged,
            expected_raw_authority_bundle_sha256=live_bundle.bundle_sha256,
        )
    assert PoisonTimezone.callback_count == 0


def test_canonical_zero_live_complement_and_value_free_receipt() -> None:
    snapshot, binding, receipts = _case("stats")
    bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    authority = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )

    assert authority.records == ()
    assert authority.public_rows() == ()
    assert authority.expected_units.units == ()
    assert authority.expected_units.raw_authority_bundle_sha256 == bundle.bundle_sha256
    assert authority.representation_assignments == ()
    assert authority.receipt.selected_observation_count == 0
    assert authority.receipt.record_count == 0
    assert authority.receipt.expected_unit_count == 0
    assert authority.receipt.representation_assignment_count == 0
    assert authority.receipt.response_residual_record_count == 0
    assert authority.receipt.response_residual_observation_count == 0
    assert authority.receipt.zero_response_residual_observation_count == 0
    assert authority.receipt.response_residual_record_inventory_sha256 == (
        canonical_ordered_root_sha256(
            kind="live_lossless_response_residual_source_items_v1",
            count=0,
            item_sha256s=(),
        )
    )
    assert (
        authority.receipt.result_declaration_count,
        authority.receipt.result_occurrence_count,
        authority.receipt.node_count,
        authority.receipt.field_cell_count,
    ) == (0, 0, 0, 0)
    receipt = authority.receipt.to_dict()
    assert not {
        "payload_json",
        "canonical_json",
        "value_sha256",
        "parser_input",
        "body",
    } & set(receipt)


def test_zero_live_inventory_roots_are_scoped_without_fabricated_response_units() -> None:
    snapshot, binding, receipts = _case("stats")
    first_bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    snapshot, binding, receipts = _case("static")
    second_bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    first = build_live_lossless_value_authority(
        first_bundle,
        expected_raw_authority_bundle_sha256=first_bundle.bundle_sha256,
    )
    second = build_live_lossless_value_authority(
        second_bundle,
        expected_raw_authority_bundle_sha256=second_bundle.bundle_sha256,
    )

    assert first.expected_units.units == second.expected_units.units == ()
    assert first.representation_assignments == second.representation_assignments == ()
    assert first.expected_units.unit_root_sha256 != second.expected_units.unit_root_sha256
    assert first.expected_units.inventory_sha256 != second.expected_units.inventory_sha256


def test_schema_enforces_order_timestamp_id_and_text_byte_contracts(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    row = dict(authority.public_rows()[0])
    frame = pl.DataFrame([row], infer_schema_length=None)
    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiLiveLosslessNodeSchema.validate(frame.select(list(reversed(frame.columns))))

    for column, invalid in (
        ("live_snapshot_at", "2026-08-27T12:00:00+00:00"),
        ("chain_id", "chain/with/slash"),
        (
            "decoder_anomaly_codes_json",
            json.dumps(["x" * (MAX_LIVE_LOSSLESS_ANOMALY_BYTES + 1)]),
        ),
    ):
        changed = dict(row)
        changed[column] = invalid
        with pytest.raises(pa_errors.SchemaError):
            RawNbaApiLiveLosslessNodeSchema.validate(
                pl.DataFrame([changed], infer_schema_length=None)
            )
        with pytest.raises(LiveLosslessValueAuthorityError):
            LiveLosslessNodeRecordV1.from_row(changed)

    assert {
        "canonical_json",
        "payload_json",
        "decoder_anomaly_codes_json",
    } <= set(LIVE_LOSSLESS_TEXT_COLUMNS)


@pytest.mark.parametrize(
    ("owner", "changes"),
    [
        (
            "result_occurrence",
            {"representation_kind": LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND},
        ),
        (
            "response_residual",
            {
                "ownership_kind": "result_occurrence",
                "representation_kind": LIVE_LOSSLESS_REPRESENTATION_KIND,
            },
        ),
        ("response_residual", {"response_residual_record_count": 0}),
    ],
)
def test_schema_rejects_owner_representation_and_zero_proof_contradictions(
    authority: LiveLosslessValueAuthorityV1,
    owner: str,
    changes: dict[str, object],
) -> None:
    row = dict(next(item.to_row() for item in authority.records if item.ownership_kind == owner))
    row.update(changes)
    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiLiveLosslessNodeSchema.validate(pl.DataFrame([row], infer_schema_length=None))
    with pytest.raises(LiveLosslessValueAuthorityError):
        LiveLosslessNodeRecordV1.from_row(row)


def test_receipt_cannot_be_resealed_over_foreign_schema_or_denominator(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    receipt = authority.receipt
    values = {
        key: value
        for key, value in receipt.to_dict().items()
        if key not in {"schema_version", "kind", "receipt_sha256"}
    }
    values["record_count"] = receipt.record_count + 1
    values["node_count"] = receipt.node_count + 1
    forged = LiveLosslessValueAuthorityReceiptV1.build(**values)
    with pytest.raises(LiveLosslessValueAuthorityError, match="count differs"):
        replace(authority, receipt=forged)


def test_payload_and_receipt_digests_are_not_python_hash_or_equality_authority(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    class AlwaysEqual(str):
        def __eq__(self, _other: object) -> bool:
            return True

        def __hash__(self) -> int:
            return hash(str(self))

    row = authority.public_rows()[0]
    row["record_sha256"] = AlwaysEqual(row["record_sha256"])
    with pytest.raises(LiveLosslessValueAuthorityError, match="exact lowercase"):
        LiveLosslessNodeRecordV1.from_row(row)

    first = authority.records[0]
    assert hashlib.sha256(first.payload_json.encode()).hexdigest() == first.payload_sha256
