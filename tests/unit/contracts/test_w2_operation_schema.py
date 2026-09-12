from __future__ import annotations

import hashlib
import json

import polars as pl
import pytest
from pandera import errors as pa_errors

from nbadb.contracts.raw_request_authority import MAX_AUTHORITY_ROWS
from nbadb.contracts.w2_operation import W2OperationKeyV1, W2OperationReceiptV1
from nbadb.orchestrate.raw_request_store import RAW_REQUEST_AUTHORITY_TABLES
from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_COLUMNS,
    RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR,
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
    RawNbaApiW2OperationSchema,
)
from nbadb.schemas.registry import _raw_schema_registry, get_input_schema
from tests.unit.contracts.test_raw_request_authority import _attempt, _sha
from tests.unit.contracts.test_w2_operation import (
    _empty_values,
    _observation,
    _reseal_operation_row,
)


class _IntSubclass(int):
    pass


class _TextSubclass(str):
    pass


def _operation(*, provider_call_ordinal: int, bundle_marker: str) -> W2OperationReceiptV1:
    observation = _observation(
        _attempt(provider_call_ordinal=provider_call_ordinal),
        response_marker=f"response:{provider_call_ordinal}",
    )
    operation_key = W2OperationKeyV1.build((observation,))
    raw_bundle = _sha(bundle_marker)
    values = _empty_values(raw_bundle)
    values["w2_operation_schema_sha256"] = RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256
    return W2OperationReceiptV1.build(operation_key=operation_key, **values)


def _operations() -> tuple[W2OperationReceiptV1, W2OperationReceiptV1]:
    ordered = sorted(
        (
            _operation(provider_call_ordinal=0, bundle_marker="bundle:a"),
            _operation(provider_call_ordinal=1, bundle_marker="bundle:b"),
        ),
        key=lambda item: item.operation_key_sha256,
    )
    return ordered[0], ordered[1]


def _frame(*operations: W2OperationReceiptV1) -> pl.DataFrame:
    return pl.DataFrame([item.to_row() for item in operations], infer_schema_length=None)


def _object_column_frame(row: dict[str, object], *, column: str, value: object) -> pl.DataFrame:
    series = []
    for name, item in row.items():
        if name == column:
            series.append(pl.Series(name, [value], dtype=pl.Object))
        else:
            series.append(pl.Series(name, [item]))
    return pl.DataFrame(series)


def test_schema_descriptor_digest_columns_and_dtypes_are_exact() -> None:
    operation = _operation(provider_call_ordinal=0, bundle_marker="bundle:one")
    assert tuple(operation.to_row()) == RAW_NBA_API_W2_OPERATION_COLUMNS
    assert len(RAW_NBA_API_W2_OPERATION_COLUMNS) == 73
    assert (
        tuple(
            (
                name,
                "int" if name == "schema_version" or name.endswith("_count") else "str",
                False,
            )
            for name in RAW_NBA_API_W2_OPERATION_COLUMNS
        )
        == RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR
    )
    expected_schema_sha256 = "aea5cbd21061a675558a739fbb89661bd1c9107d089cc21896a788db9766180b"
    assert expected_schema_sha256 == RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256
    assert (
        hashlib.sha256(
            json.dumps(
                [list(item) for item in RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR],
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        == RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256
    )
    schema = RawNbaApiW2OperationSchema.to_schema()
    assert tuple(schema.columns) == RAW_NBA_API_W2_OPERATION_COLUMNS
    assert (schema.strict, schema.coerce, schema.ordered) == (True, False, True)
    assert {name: str(column.dtype) for name, column in schema.columns.items()} == {
        name: "Int64" if name == "schema_version" or name.endswith("_count") else "String"
        for name in RAW_NBA_API_W2_OPERATION_COLUMNS
    }


def test_one_and_multiple_bundle_rows_validate_in_either_physical_order() -> None:
    first, second = _operations()
    one = RawNbaApiW2OperationSchema.validate(_frame(first))
    assert one.to_dicts() == [first.to_row()]

    multiple = RawNbaApiW2OperationSchema.validate(_frame(first, second))
    assert multiple.to_dicts() == [first.to_row(), second.to_row()]
    assert first.raw_authority_bundle_sha256 != second.raw_authority_bundle_sha256

    reversed_rows = RawNbaApiW2OperationSchema.validate(_frame(second, first))
    assert reversed_rows.to_dicts() == [second.to_row(), first.to_row()]


def test_typed_zero_row_frame_is_valid() -> None:
    integer_columns = {
        name
        for name in RAW_NBA_API_W2_OPERATION_COLUMNS
        if name == "schema_version" or name.endswith("_count")
    }
    empty = pl.DataFrame(
        schema={
            name: pl.Int64 if name in integer_columns else pl.String
            for name in RAW_NBA_API_W2_OPERATION_COLUMNS
        }
    )
    validated = RawNbaApiW2OperationSchema.validate(empty)
    assert validated.height == 0
    assert tuple(validated.columns) == RAW_NBA_API_W2_OPERATION_COLUMNS


def test_registry_discovers_only_the_public_w2_operation_name() -> None:
    _raw_schema_registry.cache_clear()
    registry = _raw_schema_registry()
    assert registry["raw_nba_api_w2_operation"] is RawNbaApiW2OperationSchema
    assert get_input_schema("raw_nba_api_w2_operation") is RawNbaApiW2OperationSchema
    assert [name for name in registry if name == "raw_nba_api_w2_operation"] == [
        "raw_nba_api_w2_operation"
    ]
    assert RAW_REQUEST_AUTHORITY_TABLES == (
        "raw_nba_api_parser_input_object",
        "raw_nba_api_request_observation",
        "raw_nba_api_result_occurrence",
        "raw_nba_api_observation_route_landing",
    )
    assert "raw_nba_api_w2_operation" not in RAW_REQUEST_AUTHORITY_TABLES
    assert "raw_nba_api_w2_operation" not in {entry.staging_key for entry in STAGING_MAP}


def test_duplicate_exact_valid_operation_row_is_rejected() -> None:
    operation = _operation(provider_call_ordinal=0, bundle_marker="bundle:duplicate")
    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiW2OperationSchema.validate(_frame(operation, operation))


def test_coordinated_duplicate_key_reseal_is_rejected_after_valid_dto_replay() -> None:
    first, second = _operations()
    second_row = second.to_row()
    first_row = first.to_row()
    for field in (
        "operation_key_sha256",
        "operation_attempt_count",
        "operation_attempt_root_sha256",
    ):
        second_row[field] = first_row[field]
    _reseal_operation_row(second_row)
    W2OperationReceiptV1.from_row(
        second_row,
        expected_operation_receipt_sha256=second_row["operation_receipt_sha256"],
        expected_operation_key_sha256=second_row["operation_key_sha256"],
        expected_raw_authority_bundle_sha256=second_row["raw_authority_bundle_sha256"],
        expected_w2_operation_schema_sha256=RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
    )
    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiW2OperationSchema.validate(
            pl.DataFrame([first.to_row(), second_row], infer_schema_length=None)
        )


@pytest.mark.parametrize(
    ("field", "value", "reseal"),
    [
        ("schema_version", 2, False),
        ("schema_version", "1", False),
        ("operation_attempt_count", -1, False),
        ("operation_attempt_count", 0, False),
        ("operation_attempt_count", MAX_AUTHORITY_ROWS + 1, False),
        ("body_blob_count", 14_000_001, False),
        ("raw_authority_bundle_sha256", "A" * 64, False),
        ("raw_authority_bundle_sha256", "0" * 63, False),
        ("raw_authority_bundle_sha256", "g" * 64, False),
        ("raw_authority_bundle_sha256", "Authorization: Bearer placeholder", False),
        ("w2_operation_schema_sha256", "9" * 64, True),
        ("body_blob_count", 1, True),
        ("body_blob_root_sha256", "9" * 64, True),
        ("bodyless_packet_byte_count", 1, True),
        ("ownership_observation_count", 1, True),
        ("ownership_binding_count", 1, True),
        ("expected_unit_count", 1, True),
        ("representation_assignment_count", 1, True),
        ("route_field_landing_count", 1, True),
        ("projection_partition_count", 1, True),
        ("projection_item_count", 1, True),
    ],
)
def test_field_bounds_sha_shape_schema_pin_and_dto_algebra_are_enforced(
    field: str, value: object, reseal: bool
) -> None:
    row = _operation(provider_call_ordinal=0, bundle_marker="bundle:mutate").to_row()
    row[field] = value
    if reseal:
        _reseal_operation_row(row)
    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiW2OperationSchema.validate(pl.DataFrame([row], infer_schema_length=None))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("operation_attempt_count", True),
        ("operation_attempt_count", _IntSubclass(1)),
        ("operation_key_sha256", _TextSubclass("1" * 64)),
    ],
)
def test_bool_and_subclass_columns_are_not_coerced(field: str, value: object) -> None:
    row = _operation(provider_call_ordinal=0, bundle_marker="bundle:types").to_row()
    if isinstance(value, (_IntSubclass, _TextSubclass)):
        frame = _object_column_frame(row, column=field, value=value)
    else:
        row[field] = value
        frame = pl.DataFrame([row], infer_schema_length=None)
    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiW2OperationSchema.validate(frame)


@pytest.mark.parametrize("shape", ["missing", "extra", "reordered"])
def test_columns_are_strict_complete_and_ordered(shape: str) -> None:
    row = _operation(provider_call_ordinal=0, bundle_marker="bundle:columns").to_row()
    if shape == "missing":
        row.pop("equality_root_sha256")
    elif shape == "extra":
        row["operation_row_sha256"] = "0" * 64
    else:
        row = dict(reversed(tuple(row.items())))
    with pytest.raises(pa_errors.SchemaError):
        RawNbaApiW2OperationSchema.validate(pl.DataFrame([row], infer_schema_length=None))


def test_validated_rows_replay_against_exact_public_pins() -> None:
    first, second = _operations()
    validated = RawNbaApiW2OperationSchema.validate(_frame(first, second))
    for row in validated.iter_rows(named=True):
        replayed = W2OperationReceiptV1.from_row(
            row,
            expected_operation_receipt_sha256=row["operation_receipt_sha256"],
            expected_operation_key_sha256=row["operation_key_sha256"],
            expected_raw_authority_bundle_sha256=row["raw_authority_bundle_sha256"],
            expected_w2_operation_schema_sha256=(RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256),
        )
        assert replayed.to_row() == row


def test_dto_replay_exception_is_normalized_without_sensitive_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = _operation(provider_call_ordinal=0, bundle_marker="bundle:bomb")

    def _bomb(*_args: object, **_kwargs: object) -> None:
        raise RecursionError("Authorization: Bearer forbidden-sensitive-detail")

    monkeypatch.setattr(W2OperationReceiptV1, "from_row", _bomb)
    with pytest.raises(pa_errors.SchemaError) as error:
        RawNbaApiW2OperationSchema.validate(_frame(operation))
    assert "forbidden-sensitive-detail" not in str(error.value)
    assert "W2 operation table failed exact receipt replay" in str(error.value)
